"""
Document event handlers for TradeHub Marketing module.

These handlers are registered in hooks.py and executed on specific document events
for Campaign, Coupon, and Group Buy DocTypes.
"""

import frappe
from frappe import _
from frappe.utils import nowdate, getdate, flt


def on_campaign_update(doc, method=None):
    """
    Handle Campaign document updates.

    Actions:
    - Update associated coupons when campaign status changes
    - Clear relevant caches
    - Trigger ECA rules via tradehub_core
    """
    frappe.logger("tradehub_marketing").debug(f"Campaign updated: {doc.name}")

    # If campaign becomes active, activate associated coupons
    if doc.status == "Active":
        activate_campaign_coupons(doc.name)
    elif doc.status in ["Completed", "Cancelled"]:
        deactivate_campaign_coupons(doc.name)

    # Clear campaign cache
    clear_campaign_cache(doc.name)


def on_campaign_created(doc, method=None):
    """
    Handle new Campaign creation.

    Actions:
    - Set default values
    - Create associated tracking entries
    - Send notification to marketing team
    """
    frappe.logger("tradehub_marketing").debug(f"New campaign created: {doc.name}")

    # Notify marketing team about new campaign
    marketing_users = frappe.get_all(
        "Has Role",
        filters={"role": ["in", ["Marketing Manager", "Marketing User"]]},
        pluck="parent"
    )

    if marketing_users:
        frappe.publish_realtime(
            event="new_campaign",
            message={
                "campaign_name": doc.campaign_name,
                "campaign_id": doc.name,
                "start_date": str(doc.start_date) if doc.start_date else None,
                "end_date": str(doc.end_date) if doc.end_date else None
            },
            user=marketing_users
        )


def validate_coupon(doc, method=None):
    """
    Validate Coupon document before save.

    Validations:
    - Discount value is within allowed limits
    - Valid date range
    - Required fields based on coupon type
    - Usage limits are reasonable
    """
    frappe.logger("tradehub_marketing").debug(f"Validating coupon: {doc.name}")

    # Validate discount values
    if doc.discount_type == "Percentage":
        if flt(doc.discount_value) <= 0 or flt(doc.discount_value) > 100:
            frappe.throw(_("Percentage discount must be between 0 and 100"))
    elif doc.discount_type == "Fixed Amount":
        if flt(doc.discount_value) <= 0:
            frappe.throw(_("Fixed amount discount must be greater than 0"))
        if doc.minimum_purchase and flt(doc.discount_value) >= flt(doc.minimum_purchase):
            frappe.throw(_("Discount cannot be greater than or equal to minimum purchase amount"))

    # Validate date range
    if doc.valid_from and doc.valid_until:
        if getdate(doc.valid_from) > getdate(doc.valid_until):
            frappe.throw(_("Valid From date must be before Valid Until date"))

        # Check if coupon is already expired
        if getdate(doc.valid_until) < getdate(nowdate()) and doc.is_active:
            frappe.msgprint(
                _("Warning: Coupon valid until date is in the past"),
                indicator="orange"
            )

    # Validate usage limits
    if doc.max_uses and doc.max_uses < 1:
        frappe.throw(_("Maximum uses must be at least 1 if specified"))

    if doc.max_uses_per_user and doc.max_uses_per_user < 1:
        frappe.throw(_("Maximum uses per user must be at least 1 if specified"))

    # Validate coupon type specific fields
    if doc.coupon_type == "Product Specific":
        if not doc.applicable_products and not doc.applicable_categories:
            frappe.throw(_("Product specific coupons must have at least one applicable product or category"))

    # Validate minimum purchase for free shipping coupons
    if doc.coupon_type == "Free Shipping" and not doc.minimum_purchase:
        frappe.msgprint(
            _("Consider setting a minimum purchase amount for free shipping coupons"),
            indicator="blue"
        )


def on_group_buy_update(doc, method=None):
    """
    Handle Group Buy document updates.

    Actions:
    - Recalculate commitment counts
    - Update progress percentage
    - Trigger notifications at milestones
    """
    frappe.logger("tradehub_marketing").debug(f"Group Buy updated: {doc.name}")

    # Calculate current commitment count
    total_quantity = frappe.db.sql("""
        SELECT COALESCE(SUM(quantity), 0)
        FROM `tabGroup Buy Commitment`
        WHERE group_buy = %s AND status = 'Confirmed'
    """, doc.name)[0][0]

    # Update current quantity if changed
    if flt(doc.current_quantity) != flt(total_quantity):
        frappe.db.set_value("Group Buy", doc.name, "current_quantity", total_quantity, update_modified=False)

    # Calculate progress percentage
    if doc.minimum_quantity:
        progress = (flt(total_quantity) / flt(doc.minimum_quantity)) * 100
        frappe.db.set_value("Group Buy", doc.name, "progress_percentage", min(progress, 100), update_modified=False)

        # Send notifications at milestones
        send_milestone_notifications(doc, progress)

    # Clear Group Buy cache
    clear_group_buy_cache(doc.name)


def activate_campaign_coupons(campaign_name):
    """Activate all coupons associated with a campaign."""
    coupons = frappe.get_all(
        "Coupon",
        filters={"campaign": campaign_name, "is_active": 0},
        pluck="name"
    )

    for coupon_name in coupons:
        frappe.db.set_value("Coupon", coupon_name, "is_active", 1)

    if coupons:
        frappe.logger("tradehub_marketing").info(
            f"Activated {len(coupons)} coupons for campaign {campaign_name}"
        )


def deactivate_campaign_coupons(campaign_name):
    """Deactivate all coupons associated with a campaign."""
    coupons = frappe.get_all(
        "Coupon",
        filters={"campaign": campaign_name, "is_active": 1},
        pluck="name"
    )

    for coupon_name in coupons:
        frappe.db.set_value("Coupon", coupon_name, "is_active", 0)

    if coupons:
        frappe.logger("tradehub_marketing").info(
            f"Deactivated {len(coupons)} coupons for campaign {campaign_name}"
        )


def clear_campaign_cache(campaign_name):
    """Clear cache entries related to a campaign."""
    frappe.cache().hdel("campaign_data", campaign_name)
    frappe.cache().delete_key(f"active_campaigns")


def clear_group_buy_cache(group_buy_name):
    """Clear cache entries related to a Group Buy."""
    frappe.cache().hdel("group_buy_data", group_buy_name)
    frappe.cache().delete_key(f"active_group_buys")


def send_milestone_notifications(doc, progress):
    """
    Send notifications when Group Buy reaches certain milestones.

    Milestones: 25%, 50%, 75%, 100%
    """
    milestones = [25, 50, 75, 100]
    current_milestone = None

    for milestone in milestones:
        if progress >= milestone:
            current_milestone = milestone

    if current_milestone:
        # Check if we've already sent notification for this milestone
        milestone_key = f"group_buy_milestone_{doc.name}_{current_milestone}"
        if not frappe.cache().get_value(milestone_key):
            # Get all participants
            participants = frappe.get_all(
                "Group Buy Commitment",
                filters={"group_buy": doc.name, "status": "Confirmed"},
                pluck="buyer_email"
            )

            if participants:
                message = f"Group Buy '{doc.title}' has reached {current_milestone}% of its goal!"
                if current_milestone == 100:
                    message = f"Great news! Group Buy '{doc.title}' has reached its goal and will proceed!"

                try:
                    frappe.sendmail(
                        recipients=list(set(participants)),
                        subject=f"Group Buy Milestone: {current_milestone}% reached!",
                        message=message,
                        now=True
                    )

                    # Mark milestone as notified
                    frappe.cache().set_value(milestone_key, True, expires_in_sec=86400 * 30)

                    frappe.logger("tradehub_marketing").info(
                        f"Sent {current_milestone}% milestone notification for Group Buy {doc.name}"
                    )
                except Exception as e:
                    frappe.logger("tradehub_marketing").error(
                        f"Failed to send milestone notification: {str(e)}"
                    )

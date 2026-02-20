# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt, getdate, now_datetime, nowdate, add_days, add_months


class SellerTier(Document):
    """
    Seller Tier DocType for defining seller performance tiers.

    Manages tier levels (Bronze, Silver, Gold, Platinum, Diamond) with:
    - Minimum requirements (score, sales, ratings)
    - Benefits (commission discounts, priority support, etc.)
    - Automatic upgrade/downgrade logic
    - Badge display settings
    """

    def before_insert(self):
        """Set default values before inserting a new tier."""
        if not self.created_by:
            self.created_by = frappe.session.user
        self.created_at = now_datetime()

        # Ensure tier_code is uppercase
        if self.tier_code:
            self.tier_code = self.tier_code.upper().replace(" ", "_")

    def validate(self):
        """Validate tier data before saving."""
        self.validate_tier_code()
        self.validate_tier_level()
        self.validate_requirements()
        self.validate_benefits()
        self.validate_progression()
        self.validate_default_tier()
        self.modified_by = frappe.session.user
        self.modified_at = now_datetime()

    def on_update(self):
        """Actions to perform after tier is updated."""
        self.update_seller_count()
        self.clear_cache()

    def on_trash(self):
        """Prevent deletion of tier with active sellers."""
        self.check_active_sellers()

    def validate_tier_code(self):
        """Validate tier code format."""
        if not self.tier_code:
            frappe.throw(_("Tier Code is required"))

        self.tier_code = self.tier_code.upper().replace(" ", "_")

        # Check for valid characters
        import re
        if not re.match(r'^[A-Z0-9_]+$', self.tier_code):
            frappe.throw(_("Tier Code can only contain uppercase letters, numbers, and underscores"))

    def validate_tier_level(self):
        """Validate tier level is positive."""
        if cint(self.tier_level) < 1:
            frappe.throw(_("Tier Level must be at least 1"))

        # Check for duplicate tier levels within same tenant
        filters = {
            "tier_level": self.tier_level,
            "name": ["!=", self.name]
        }
        if self.tenant:
            filters["tenant"] = self.tenant
        else:
            filters["tenant"] = ["is", "not set"]

        existing = frappe.db.get_value("Seller Tier", filters, "name")
        if existing:
            frappe.msgprint(
                _("Warning: Another tier '{0}' has the same level {1}").format(
                    existing, self.tier_level
                ),
                indicator="orange"
            )

    def validate_requirements(self):
        """Validate requirement thresholds."""
        # Score must be 0-100
        if flt(self.min_seller_score) < 0 or flt(self.min_seller_score) > 100:
            frappe.throw(_("Minimum seller score must be between 0 and 100"))

        # Rating must be 0-5
        if flt(self.min_average_rating) < 0 or flt(self.min_average_rating) > 5:
            frappe.throw(_("Minimum average rating must be between 0 and 5"))

        # Percentages must be 0-100
        percentage_fields = [
            ("min_positive_feedback_rate", "Minimum positive feedback rate"),
            ("max_return_rate", "Maximum return rate"),
            ("min_order_fulfillment_rate", "Minimum order fulfillment rate"),
            ("min_on_time_delivery_rate", "Minimum on-time delivery rate"),
            ("max_cancellation_rate", "Maximum cancellation rate"),
            ("max_complaint_rate", "Maximum complaint rate")
        ]

        for field, label in percentage_fields:
            value = flt(getattr(self, field, 0))
            if value < 0 or value > 100:
                frappe.throw(_("{0} must be between 0 and 100").format(label))

        # Non-negative integer fields
        if cint(self.min_total_sales_count) < 0:
            frappe.throw(_("Minimum total sales cannot be negative"))

        if flt(self.min_total_sales_amount) < 0:
            frappe.throw(_("Minimum total sales amount cannot be negative"))

        if cint(self.min_active_months) < 0:
            frappe.throw(_("Minimum active months cannot be negative"))

        if flt(self.max_response_time_hours) < 0:
            frappe.throw(_("Maximum response time cannot be negative"))

    def validate_benefits(self):
        """Validate benefit values."""
        # Commission discount 0-100%
        if flt(self.commission_discount_percent) < 0 or flt(self.commission_discount_percent) > 100:
            frappe.throw(_("Commission discount must be between 0 and 100%"))

        # Non-negative integers
        if cint(self.reduced_payout_hold_days) < 0:
            frappe.throw(_("Reduced payout hold days cannot be negative"))

        if cint(self.listing_limit_bonus) < 0:
            frappe.throw(_("Listing limit bonus cannot be negative"))

        if flt(self.promotional_credit_amount) < 0:
            frappe.throw(_("Promotional credit amount cannot be negative"))

    def validate_progression(self):
        """Validate tier progression links."""
        # Prevent circular references
        if self.next_tier and self.next_tier == self.name:
            frappe.throw(_("Next tier cannot be the same as current tier"))

        if self.previous_tier and self.previous_tier == self.name:
            frappe.throw(_("Previous tier cannot be the same as current tier"))

        # Check level ordering makes sense
        if self.next_tier:
            next_level = frappe.db.get_value("Seller Tier", self.next_tier, "tier_level")
            if next_level and cint(next_level) <= cint(self.tier_level):
                frappe.msgprint(
                    _("Warning: Next tier should typically have a higher level"),
                    indicator="orange"
                )

        if self.previous_tier:
            prev_level = frappe.db.get_value("Seller Tier", self.previous_tier, "tier_level")
            if prev_level and cint(prev_level) >= cint(self.tier_level):
                frappe.msgprint(
                    _("Warning: Previous tier should typically have a lower level"),
                    indicator="orange"
                )

        # Validate grace period
        if cint(self.downgrade_grace_days) < 0:
            frappe.throw(_("Downgrade grace days cannot be negative"))

    def validate_default_tier(self):
        """Ensure only one default tier exists per tenant."""
        if cint(self.is_default) and self.status == "Active":
            filters = {
                "is_default": 1,
                "status": "Active",
                "name": ["!=", self.name]
            }
            if self.tenant:
                filters["tenant"] = self.tenant
            else:
                filters["tenant"] = ["is", "not set"]

            existing_default = frappe.db.get_value("Seller Tier", filters, "name")
            if existing_default:
                frappe.db.set_value("Seller Tier", existing_default, "is_default", 0)
                frappe.msgprint(
                    _("Previous default tier '{0}' has been unset").format(existing_default),
                    indicator="blue"
                )

    def check_active_sellers(self):
        """Check for active sellers before deletion."""
        seller_count = frappe.db.count("Seller Profile", {"seller_tier": self.name})
        if seller_count > 0:
            frappe.throw(
                _("Cannot delete Seller Tier with {0} sellers. "
                  "Please reassign sellers to a different tier first.").format(seller_count)
            )

    def update_seller_count(self):
        """Update seller statistics for this tier."""
        stats = frappe.db.sql("""
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN status = 'Active' THEN 1 ELSE 0 END) as active,
                AVG(seller_score) as avg_score
            FROM `tabSeller Profile`
            WHERE seller_tier = %s
        """, self.name, as_dict=True)

        if stats:
            self.db_set("total_sellers", stats[0].total or 0, update_modified=False)
            self.db_set("active_sellers", stats[0].active or 0, update_modified=False)
            self.db_set("avg_seller_performance", round(stats[0].avg_score or 0, 2), update_modified=False)
            self.db_set("last_stats_update", now_datetime(), update_modified=False)

    def clear_cache(self):
        """Clear cached tier data."""
        cache_keys = [
            f"seller_tier:{self.name}",
            f"seller_tier_code:{self.tier_code}",
            "default_seller_tier",
            "seller_tiers_list"
        ]
        for key in cache_keys:
            frappe.cache().delete_value(key)

    # Eligibility Check Methods
    def check_seller_eligibility(self, seller):
        """
        Check if a seller meets the requirements for this tier.

        Args:
            seller: Seller Profile document or name

        Returns:
            tuple: (is_eligible: bool, reasons: list of unmet requirements)
        """
        if isinstance(seller, str):
            seller = frappe.get_doc("Seller Profile", seller)

        unmet_requirements = []

        # Check seller score
        if flt(self.min_seller_score) > 0:
            if flt(seller.seller_score) < flt(self.min_seller_score):
                unmet_requirements.append(
                    _("Seller score {0} is below minimum {1}").format(
                        round(seller.seller_score, 2), round(self.min_seller_score, 2)
                    )
                )

        # Check total sales count
        if cint(self.min_total_sales_count) > 0:
            if cint(seller.total_sales_count) < cint(self.min_total_sales_count):
                unmet_requirements.append(
                    _("Total sales {0} is below minimum {1}").format(
                        seller.total_sales_count, self.min_total_sales_count
                    )
                )

        # Check total sales amount
        if flt(self.min_total_sales_amount) > 0:
            if flt(seller.total_sales_amount) < flt(self.min_total_sales_amount):
                unmet_requirements.append(
                    _("Total sales amount is below minimum {0}").format(
                        self.min_total_sales_amount
                    )
                )

        # Check active months
        if cint(self.min_active_months) > 0:
            if seller.joined_at:
                from frappe.utils import month_diff
                months_active = month_diff(nowdate(), seller.joined_at)
                if months_active < cint(self.min_active_months):
                    unmet_requirements.append(
                        _("Active months {0} is below minimum {1}").format(
                            months_active, self.min_active_months
                        )
                    )

        # Check average rating
        if flt(self.min_average_rating) > 0:
            if flt(seller.average_rating) < flt(self.min_average_rating):
                unmet_requirements.append(
                    _("Average rating {0} is below minimum {1}").format(
                        round(seller.average_rating, 2), round(self.min_average_rating, 2)
                    )
                )

        # Check positive feedback rate
        if flt(self.min_positive_feedback_rate) > 0:
            if flt(seller.positive_feedback_rate) < flt(self.min_positive_feedback_rate):
                unmet_requirements.append(
                    _("Positive feedback rate {0}% is below minimum {1}%").format(
                        round(seller.positive_feedback_rate, 1), round(self.min_positive_feedback_rate, 1)
                    )
                )

        # Check return rate (max)
        if flt(self.max_return_rate) < 100:
            if flt(seller.return_rate) > flt(self.max_return_rate):
                unmet_requirements.append(
                    _("Return rate {0}% exceeds maximum {1}%").format(
                        round(seller.return_rate, 1), round(self.max_return_rate, 1)
                    )
                )

        # Check order fulfillment rate
        if flt(self.min_order_fulfillment_rate) > 0:
            if flt(seller.order_fulfillment_rate) < flt(self.min_order_fulfillment_rate):
                unmet_requirements.append(
                    _("Order fulfillment rate {0}% is below minimum {1}%").format(
                        round(seller.order_fulfillment_rate, 1), round(self.min_order_fulfillment_rate, 1)
                    )
                )

        # Check on-time delivery rate
        if flt(self.min_on_time_delivery_rate) > 0:
            if flt(seller.on_time_delivery_rate) < flt(self.min_on_time_delivery_rate):
                unmet_requirements.append(
                    _("On-time delivery rate {0}% is below minimum {1}%").format(
                        round(seller.on_time_delivery_rate, 1), round(self.min_on_time_delivery_rate, 1)
                    )
                )

        # Check cancellation rate (max)
        if flt(self.max_cancellation_rate) < 100:
            if flt(seller.cancellation_rate) > flt(self.max_cancellation_rate):
                unmet_requirements.append(
                    _("Cancellation rate {0}% exceeds maximum {1}%").format(
                        round(seller.cancellation_rate, 1), round(self.max_cancellation_rate, 1)
                    )
                )

        # Check complaint rate (max)
        if flt(self.max_complaint_rate) < 100:
            if flt(seller.complaint_rate) > flt(self.max_complaint_rate):
                unmet_requirements.append(
                    _("Complaint rate {0}% exceeds maximum {1}%").format(
                        round(seller.complaint_rate, 1), round(self.max_complaint_rate, 1)
                    )
                )

        # Check response time (max)
        if flt(self.max_response_time_hours) > 0:
            if flt(seller.response_time_hours) > flt(self.max_response_time_hours):
                unmet_requirements.append(
                    _("Response time {0}hrs exceeds maximum {1}hrs").format(
                        round(seller.response_time_hours, 1), round(self.max_response_time_hours, 1)
                    )
                )

        return len(unmet_requirements) == 0, unmet_requirements

    def get_benefits_summary(self):
        """Get a summary of tier benefits."""
        benefits = []

        if flt(self.commission_discount_percent) > 0:
            benefits.append(_("{0}% commission discount").format(round(self.commission_discount_percent, 1)))

        if cint(self.reduced_payout_hold_days) > 0:
            benefits.append(_("{0} days faster payouts").format(self.reduced_payout_hold_days))

        if cint(self.priority_support):
            benefits.append(_("Priority support"))

        if cint(self.featured_placement):
            benefits.append(_("Featured placement eligibility"))

        if cint(self.increased_listing_limit) and cint(self.listing_limit_bonus) > 0:
            benefits.append(_("{0} extra listings").format(self.listing_limit_bonus))

        if cint(self.early_payout_access):
            benefits.append(_("Early payout access"))

        if cint(self.analytics_access):
            benefits.append(_("Advanced analytics"))

        if cint(self.promotional_credits) and flt(self.promotional_credit_amount) > 0:
            benefits.append(_("Monthly promotional credits"))

        if cint(self.priority_listing_boost):
            benefits.append(_("Priority search placement"))

        return benefits

    def get_requirements_summary(self):
        """Get a summary of tier requirements."""
        requirements = []

        if flt(self.min_seller_score) > 0:
            requirements.append(_("Min score: {0}").format(round(self.min_seller_score, 0)))

        if cint(self.min_total_sales_count) > 0:
            requirements.append(_("Min sales: {0}").format(self.min_total_sales_count))

        if flt(self.min_total_sales_amount) > 0:
            requirements.append(_("Min sales amount"))

        if cint(self.min_active_months) > 0:
            requirements.append(_("Min {0} months active").format(self.min_active_months))

        if flt(self.min_average_rating) > 0:
            requirements.append(_("Min rating: {0}").format(round(self.min_average_rating, 1)))

        if flt(self.min_positive_feedback_rate) > 0:
            requirements.append(_("Min {0}% positive feedback").format(round(self.min_positive_feedback_rate, 0)))

        return requirements

    def get_tier_card(self):
        """Get tier information for card display."""
        return {
            "name": self.name,
            "tier_name": self.tier_name,
            "tier_code": self.tier_code,
            "tier_level": self.tier_level,
            "badge_icon": self.badge_icon,
            "badge_color": self.badge_color,
            "badge_image": self.badge_image,
            "short_description": self.short_description,
            "benefits": self.get_benefits_summary(),
            "requirements": self.get_requirements_summary(),
            "total_sellers": self.total_sellers,
            "status": self.status
        }


# API Endpoints
@frappe.whitelist()
def get_seller_tier(tier_name=None, tier_code=None):
    """
    Get seller tier details.

    Args:
        tier_name: Name of the tier
        tier_code: Code of the tier

    Returns:
        dict: Tier card information
    """
    if not tier_name and not tier_code:
        frappe.throw(_("Please provide tier name or code"))

    if tier_code:
        tier_name = frappe.db.get_value("Seller Tier", {"tier_code": tier_code.upper()}, "name")

    if not tier_name or not frappe.db.exists("Seller Tier", tier_name):
        return {"error": _("Seller tier not found")}

    tier = frappe.get_doc("Seller Tier", tier_name)
    return tier.get_tier_card()


@frappe.whitelist()
def get_default_seller_tier(tenant=None):
    """
    Get the default seller tier.

    Args:
        tenant: Optional tenant filter

    Returns:
        dict: Default tier card or None
    """
    filters = {
        "is_default": 1,
        "status": "Active"
    }

    if tenant:
        filters["tenant"] = tenant
    else:
        filters["tenant"] = ["is", "not set"]

    tier_name = frappe.db.get_value("Seller Tier", filters, "name")

    if not tier_name:
        # Fall back to any active default tier
        tier_name = frappe.db.get_value("Seller Tier", {
            "is_default": 1,
            "status": "Active"
        }, "name")

    if not tier_name:
        # Fall back to lowest level tier
        tier_name = frappe.db.get_value("Seller Tier",
            {"status": "Active"},
            "name",
            order_by="tier_level asc"
        )

    if not tier_name:
        return None

    tier = frappe.get_doc("Seller Tier", tier_name)
    return tier.get_tier_card()


@frappe.whitelist()
def get_all_tiers(tenant=None, include_inactive=False):
    """
    Get all seller tiers.

    Args:
        tenant: Optional tenant filter
        include_inactive: Include inactive tiers

    Returns:
        list: List of tier cards
    """
    filters = {}

    if not cint(include_inactive):
        filters["status"] = "Active"

    if tenant:
        filters["tenant"] = ["in", [tenant, None, ""]]

    tiers = frappe.get_all("Seller Tier",
        filters=filters,
        fields=["name"],
        order_by="tier_level asc"
    )

    result = []
    for t in tiers:
        tier = frappe.get_doc("Seller Tier", t.name)
        result.append(tier.get_tier_card())

    return result


@frappe.whitelist()
def check_tier_eligibility(seller, tier_name):
    """
    Check if a seller is eligible for a specific tier.

    Args:
        seller: Seller profile name
        tier_name: Tier name to check

    Returns:
        dict: Eligibility result with reasons
    """
    if not frappe.db.exists("Seller Profile", seller):
        frappe.throw(_("Seller not found"))

    if not frappe.db.exists("Seller Tier", tier_name):
        frappe.throw(_("Tier not found"))

    tier = frappe.get_doc("Seller Tier", tier_name)
    is_eligible, unmet = tier.check_seller_eligibility(seller)

    return {
        "tier_name": tier.tier_name,
        "tier_code": tier.tier_code,
        "is_eligible": is_eligible,
        "unmet_requirements": unmet
    }


@frappe.whitelist()
def get_eligible_tiers(seller, tenant=None):
    """
    Get all tiers a seller is eligible for.

    Args:
        seller: Seller profile name
        tenant: Optional tenant filter

    Returns:
        list: Eligible tiers with details
    """
    if not frappe.db.exists("Seller Profile", seller):
        frappe.throw(_("Seller not found"))

    filters = {"status": "Active"}
    if tenant:
        filters["tenant"] = ["in", [tenant, None, ""]]

    tiers = frappe.get_all("Seller Tier",
        filters=filters,
        fields=["name", "tier_name", "tier_code", "tier_level"],
        order_by="tier_level desc"
    )

    result = []
    highest_eligible = None

    for t in tiers:
        tier = frappe.get_doc("Seller Tier", t.name)
        is_eligible, unmet = tier.check_seller_eligibility(seller)

        tier_info = {
            "name": tier.name,
            "tier_name": tier.tier_name,
            "tier_code": tier.tier_code,
            "tier_level": tier.tier_level,
            "is_eligible": is_eligible,
            "unmet_requirements": unmet if not is_eligible else [],
            "badge_color": tier.badge_color,
            "badge_icon": tier.badge_icon
        }

        if is_eligible and not highest_eligible:
            highest_eligible = tier_info
            tier_info["is_recommended"] = True

        result.append(tier_info)

    return {
        "eligible_tiers": [t for t in result if t["is_eligible"]],
        "all_tiers": result,
        "recommended_tier": highest_eligible
    }


@frappe.whitelist()
def assign_tier_to_seller(seller, tier_name):
    """
    Assign a tier to a seller.

    Args:
        seller: Seller profile name
        tier_name: Tier name to assign

    Returns:
        dict: Result of assignment
    """
    if not frappe.db.exists("Seller Profile", seller):
        frappe.throw(_("Seller not found"))

    if not frappe.db.exists("Seller Tier", tier_name):
        frappe.throw(_("Tier not found"))

    tier = frappe.get_doc("Seller Tier", tier_name)

    if tier.status != "Active":
        frappe.throw(_("Cannot assign inactive tier"))

    # Check eligibility
    is_eligible, unmet = tier.check_seller_eligibility(seller)

    if not is_eligible:
        frappe.throw(_("Seller does not meet tier requirements: {0}").format(", ".join(unmet)))

    # Get previous tier for logging
    prev_tier = frappe.db.get_value("Seller Profile", seller, "seller_tier")

    # Update seller's tier
    frappe.db.set_value("Seller Profile", seller, "seller_tier", tier_name)

    # Update tier seller counts
    tier.update_seller_count()
    if prev_tier and prev_tier != tier_name:
        prev_tier_doc = frappe.get_doc("Seller Tier", prev_tier)
        prev_tier_doc.update_seller_count()

    return {
        "status": "success",
        "message": _("Tier assigned successfully"),
        "seller": seller,
        "tier": tier_name,
        "previous_tier": prev_tier
    }


@frappe.whitelist()
def evaluate_seller_tier(seller, auto_assign=False):
    """
    Evaluate and recommend appropriate tier for a seller.

    Args:
        seller: Seller profile name
        auto_assign: If True, automatically assign the recommended tier

    Returns:
        dict: Evaluation result with current and recommended tiers
    """
    if not frappe.db.exists("Seller Profile", seller):
        frappe.throw(_("Seller not found"))

    seller_doc = frappe.get_doc("Seller Profile", seller)
    current_tier = seller_doc.seller_tier

    # Get eligible tiers
    result = get_eligible_tiers(seller, seller_doc.tenant)
    recommended = result.get("recommended_tier")

    evaluation = {
        "seller": seller,
        "current_tier": current_tier,
        "current_tier_name": frappe.db.get_value("Seller Tier", current_tier, "tier_name") if current_tier else None,
        "recommended_tier": recommended.get("name") if recommended else None,
        "recommended_tier_name": recommended.get("tier_name") if recommended else None,
        "eligible_tiers": result.get("eligible_tiers", []),
        "action_needed": None
    }

    # Determine action needed
    if not current_tier and recommended:
        evaluation["action_needed"] = "assign"
    elif current_tier and recommended:
        current_level = frappe.db.get_value("Seller Tier", current_tier, "tier_level")
        recommended_level = recommended.get("tier_level")

        if recommended_level > current_level:
            evaluation["action_needed"] = "upgrade"
        elif recommended_level < current_level:
            evaluation["action_needed"] = "downgrade"
        else:
            evaluation["action_needed"] = None  # Already at correct tier
    elif current_tier and not recommended:
        # No eligible tiers - unusual case
        evaluation["action_needed"] = "review"

    # Auto-assign if requested
    if cint(auto_assign) and recommended and evaluation["action_needed"] in ["assign", "upgrade"]:
        assign_result = assign_tier_to_seller(seller, recommended["name"])
        evaluation["auto_assigned"] = True
        evaluation["assign_result"] = assign_result

    return evaluation


@frappe.whitelist()
def get_tier_progression(seller):
    """
    Get tier progression information for a seller.

    Args:
        seller: Seller profile name

    Returns:
        dict: Current tier, next tier requirements, progress
    """
    if not frappe.db.exists("Seller Profile", seller):
        frappe.throw(_("Seller not found"))

    seller_doc = frappe.get_doc("Seller Profile", seller)
    current_tier_name = seller_doc.seller_tier

    result = {
        "seller": seller,
        "current_tier": None,
        "next_tier": None,
        "progress": {},
        "benefits_at_next_tier": []
    }

    if current_tier_name:
        current_tier = frappe.get_doc("Seller Tier", current_tier_name)
        result["current_tier"] = current_tier.get_tier_card()

        if current_tier.next_tier:
            next_tier = frappe.get_doc("Seller Tier", current_tier.next_tier)
            result["next_tier"] = next_tier.get_tier_card()
            result["benefits_at_next_tier"] = next_tier.get_benefits_summary()

            # Calculate progress towards next tier
            progress = {}

            if flt(next_tier.min_seller_score) > 0:
                progress["seller_score"] = {
                    "current": flt(seller_doc.seller_score),
                    "required": flt(next_tier.min_seller_score),
                    "percent": min(100, (flt(seller_doc.seller_score) / flt(next_tier.min_seller_score)) * 100)
                }

            if cint(next_tier.min_total_sales_count) > 0:
                progress["total_sales"] = {
                    "current": cint(seller_doc.total_sales_count),
                    "required": cint(next_tier.min_total_sales_count),
                    "percent": min(100, (cint(seller_doc.total_sales_count) / cint(next_tier.min_total_sales_count)) * 100)
                }

            if flt(next_tier.min_average_rating) > 0:
                progress["average_rating"] = {
                    "current": flt(seller_doc.average_rating),
                    "required": flt(next_tier.min_average_rating),
                    "percent": min(100, (flt(seller_doc.average_rating) / flt(next_tier.min_average_rating)) * 100)
                }

            result["progress"] = progress

    return result


@frappe.whitelist()
def get_tier_statistics(tier_name):
    """
    Get detailed statistics for a tier.

    Args:
        tier_name: Tier name

    Returns:
        dict: Tier statistics
    """
    if not frappe.db.exists("Seller Tier", tier_name):
        frappe.throw(_("Tier not found"))

    tier = frappe.get_doc("Seller Tier", tier_name)

    # Get detailed seller stats
    stats = frappe.db.sql("""
        SELECT
            COUNT(*) as total_sellers,
            SUM(CASE WHEN status = 'Active' THEN 1 ELSE 0 END) as active_sellers,
            AVG(seller_score) as avg_score,
            AVG(average_rating) as avg_rating,
            SUM(total_sales_count) as total_orders,
            SUM(total_sales_amount) as total_gmv,
            AVG(order_fulfillment_rate) as avg_fulfillment,
            AVG(on_time_delivery_rate) as avg_on_time
        FROM `tabSeller Profile`
        WHERE seller_tier = %s
    """, tier_name, as_dict=True)

    return {
        "tier_name": tier.tier_name,
        "tier_code": tier.tier_code,
        "tier_level": tier.tier_level,
        "status": tier.status,
        "total_sellers": stats[0].total_sellers or 0 if stats else 0,
        "active_sellers": stats[0].active_sellers or 0 if stats else 0,
        "average_score": round(stats[0].avg_score or 0, 2) if stats else 0,
        "average_rating": round(stats[0].avg_rating or 0, 2) if stats else 0,
        "total_orders": stats[0].total_orders or 0 if stats else 0,
        "total_gmv": stats[0].total_gmv or 0 if stats else 0,
        "avg_fulfillment_rate": round(stats[0].avg_fulfillment or 0, 1) if stats else 0,
        "avg_on_time_rate": round(stats[0].avg_on_time or 0, 1) if stats else 0,
        "benefits": tier.get_benefits_summary(),
        "requirements": tier.get_requirements_summary()
    }

# Copyright (c) 2026, TR TradeHub and contributors
# For license information, please see license.txt

"""
Campaign DocType for TR-TradeHub Marketplace.

This module manages promotional campaigns for the marketplace.
Campaigns can include discounts, flash sales, seasonal promotions,
and various other marketing activities.

Key Features:
- Multiple campaign types (Discount, Flash Sale, Seasonal, etc.)
- Automatic activation/deactivation based on schedule
- Budget management and usage tracking
- Customer targeting and segmentation
- Coupon integration
- Analytics tracking
- Multi-tenant support
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import (
    flt, cint, getdate, nowdate, now_datetime,
    get_datetime, add_days, date_diff
)
from typing import Dict, List, Optional
import random
import string


class Campaign(Document):
    """
    Campaign DocType for managing promotional campaigns.

    Supports various campaign types and provides methods for
    validation, discount calculation, and analytics tracking.
    """

    def before_insert(self):
        """Set defaults before creating a new campaign."""
        self.set_tenant_from_seller()
        self.calculate_remaining_budget()

    def validate(self):
        """Validate campaign data before saving."""
        self.validate_dates()
        self.validate_discount_value()
        self.validate_budget()
        self.validate_usage_limits()
        self.update_status()
        self.calculate_remaining_budget()

    def on_update(self):
        """Actions after campaign is updated."""
        self.generate_coupons_if_needed()
        self.clear_campaign_cache()

    # =========================================================================
    # Initialization Methods
    # =========================================================================

    def set_tenant_from_seller(self):
        """Set tenant from seller if not already set."""
        if self.seller and not self.tenant:
            tenant = frappe.db.get_value("Seller Profile", self.seller, "tenant")
            if tenant:
                self.tenant = tenant

    def calculate_remaining_budget(self):
        """Calculate remaining budget."""
        if self.budget_enabled:
            self.remaining_budget = flt(self.total_budget) - flt(self.spent_amount)

    # =========================================================================
    # Validation Methods
    # =========================================================================

    def validate_dates(self):
        """Validate campaign dates."""
        if not self.start_date or not self.end_date:
            frappe.throw(_("Start date and end date are required"))

        start = get_datetime(self.start_date)
        end = get_datetime(self.end_date)

        if end <= start:
            frappe.throw(_("End date must be after start date"))

        # Warn if campaign is in the past
        if end < now_datetime() and self.status == "Active":
            frappe.msgprint(
                _("Warning: This campaign has already ended"),
                indicator="orange"
            )

    def validate_discount_value(self):
        """Validate discount configuration."""
        if self.discount_type == "Percentage":
            if flt(self.discount_value) <= 0:
                frappe.throw(_("Discount percentage must be greater than 0"))
            if flt(self.discount_value) > 100:
                frappe.throw(_("Discount percentage cannot exceed 100%"))

        elif self.discount_type == "Fixed Amount":
            if flt(self.discount_value) <= 0:
                frappe.throw(_("Discount amount must be greater than 0"))

    def validate_budget(self):
        """Validate budget settings."""
        if self.budget_enabled:
            if flt(self.total_budget) <= 0:
                frappe.throw(_("Total budget must be greater than 0"))

            if flt(self.spent_amount) > flt(self.total_budget):
                frappe.throw(_("Spent amount cannot exceed total budget"))

    def validate_usage_limits(self):
        """Validate usage limit settings."""
        if cint(self.usage_limit) < 0:
            frappe.throw(_("Usage limit cannot be negative"))

        if cint(self.usage_per_customer) < 0:
            frappe.throw(_("Usage per customer cannot be negative"))

    # =========================================================================
    # Status Management
    # =========================================================================

    def update_status(self):
        """Update campaign status based on current state."""
        current_time = now_datetime()
        start = get_datetime(self.start_date) if self.start_date else None
        end = get_datetime(self.end_date) if self.end_date else None

        # Don't change if manually cancelled or paused
        if self.status in ["Cancelled", "Paused"]:
            return

        # Check if budget exhausted
        if self.budget_enabled and flt(self.remaining_budget) <= 0:
            self.status = "Ended"
            return

        # Check if usage limit reached
        if cint(self.usage_limit) > 0 and cint(self.total_usage) >= cint(self.usage_limit):
            self.status = "Ended"
            return

        # Check date-based status
        if start and current_time < start:
            if self.status != "Draft":
                self.status = "Scheduled"
        elif end and current_time > end:
            self.status = "Ended"
        elif start and end and start <= current_time <= end:
            if self.auto_activate and self.status in ["Draft", "Scheduled"]:
                self.status = "Active"

    def activate(self):
        """Manually activate the campaign."""
        if self.status in ["Cancelled", "Ended"]:
            frappe.throw(_("Cannot activate a cancelled or ended campaign"))

        self.status = "Active"
        self.save()
        return True

    def pause(self):
        """Pause the campaign."""
        if self.status != "Active":
            frappe.throw(_("Only active campaigns can be paused"))

        self.status = "Paused"
        self.save()
        return True

    def resume(self):
        """Resume a paused campaign."""
        if self.status != "Paused":
            frappe.throw(_("Only paused campaigns can be resumed"))

        self.status = "Active"
        self.save()
        return True

    def cancel(self, reason=None):
        """Cancel the campaign."""
        if self.status == "Cancelled":
            return

        self.status = "Cancelled"
        if reason:
            self.internal_notes = (self.internal_notes or "") + f"\nCancelled: {reason}"
        self.save()
        return True

    # =========================================================================
    # Eligibility Methods
    # =========================================================================

    def is_active(self) -> bool:
        """Check if campaign is currently active."""
        if self.status != "Active":
            return False

        current_time = now_datetime()
        start = get_datetime(self.start_date) if self.start_date else None
        end = get_datetime(self.end_date) if self.end_date else None

        if start and current_time < start:
            return False
        if end and current_time > end:
            return False

        return True

    def is_valid_for_order(
        self,
        order_amount: float,
        buyer: str = None,
        categories: List[str] = None,
        products: List[str] = None,
        seller: str = None,
        city: str = None
    ) -> tuple:
        """
        Check if campaign is valid for a given order.

        Args:
            order_amount: Total order amount
            buyer: Buyer profile name
            categories: List of category names in the order
            products: List of product codes in the order
            seller: Seller profile name
            city: Buyer's city

        Returns:
            tuple: (is_valid, error_message)
        """
        # Check if active
        if not self.is_active():
            return False, _("Campaign is not active")

        # Check minimum order amount
        if flt(self.min_order_amount) > 0 and order_amount < flt(self.min_order_amount):
            return False, _("Minimum order amount of {0} required").format(
                frappe.format_value(self.min_order_amount, {"fieldtype": "Currency"})
            )

        # Check budget
        if self.budget_enabled and flt(self.remaining_budget) <= 0:
            return False, _("Campaign budget exhausted")

        # Check usage limit
        if cint(self.usage_limit) > 0 and cint(self.total_usage) >= cint(self.usage_limit):
            return False, _("Campaign usage limit reached")

        # Check per-customer usage
        if buyer and cint(self.usage_per_customer) > 0:
            customer_usage = self.get_customer_usage(buyer)
            if customer_usage >= cint(self.usage_per_customer):
                return False, _("You have reached the maximum usage for this campaign")

        # Check customer targeting
        if buyer and not self.is_customer_eligible(buyer):
            return False, _("This campaign is not available for your account")

        # Check geographic targeting
        if city and self.geographic_regions:
            regions = [r.strip().lower() for r in self.geographic_regions.split(",")]
            if city.lower() not in regions:
                return False, _("Campaign not available in your region")

        # Check seller targeting
        if seller and self.applies_to == "Specific Sellers":
            if self.applicable_sellers:
                sellers = [s.strip() for s in self.applicable_sellers.split(",")]
                if seller not in sellers:
                    return False, _("Campaign not available for this seller")

        # Check category targeting
        if categories and self.applies_to == "Specific Categories":
            if self.applicable_categories:
                allowed = [c.strip().lower() for c in self.applicable_categories.split(",")]
                if not any(c.lower() in allowed for c in categories):
                    return False, _("Campaign not applicable to these categories")

        # Check product exclusions
        if products and self.excluded_products:
            excluded = [p.strip() for p in self.excluded_products.split(",")]
            if any(p in excluded for p in products):
                return False, _("Some products are excluded from this campaign")

        return True, None

    def is_customer_eligible(self, buyer: str) -> bool:
        """Check if customer is eligible for this campaign."""
        if self.target_audience == "All Customers":
            return True

        # Get buyer info
        buyer_data = frappe.db.get_value(
            "Buyer Profile",
            buyer,
            ["buyer_level", "user"],
            as_dict=True
        )

        if not buyer_data:
            return self.target_audience == "New Customers"

        # Check order count for targeting
        order_count = frappe.db.count("Order", {"buyer": buyer, "status": ["!=", "Cancelled"]})

        if self.target_audience == "New Customers":
            return order_count == 0

        elif self.target_audience == "Returning Customers":
            return order_count > 0

        elif self.target_audience == "VIP Customers":
            return buyer_data.get("buyer_level", "").lower() in ["vip", "premium", "gold", "platinum"]

        elif self.target_audience == "Inactive Customers":
            # Check last order date
            last_order = frappe.db.get_value(
                "Order",
                {"buyer": buyer, "status": ["!=", "Cancelled"]},
                "creation",
                order_by="creation desc"
            )
            if not last_order:
                return True
            days_since = date_diff(nowdate(), getdate(last_order))
            return days_since > 90  # Inactive if no orders in 90 days

        elif self.target_audience == "Specific Levels":
            if self.buyer_levels:
                levels = [l.strip().lower() for l in self.buyer_levels.split(",")]
                return buyer_data.get("buyer_level", "").lower() in levels

        # Check min/max previous orders
        if cint(self.min_previous_orders) > 0 and order_count < cint(self.min_previous_orders):
            return False
        if cint(self.max_previous_orders) > 0 and order_count > cint(self.max_previous_orders):
            return False

        return True

    def get_customer_usage(self, buyer: str) -> int:
        """Get campaign usage count for a customer."""
        # Query order records for this campaign
        return frappe.db.count(
            "Order",
            filters={
                "buyer": buyer,
                "campaign": self.name,
                "status": ["!=", "Cancelled"]
            }
        )

    # =========================================================================
    # Discount Calculation
    # =========================================================================

    def calculate_discount(self, order_amount: float, applicable_amount: float = None) -> float:
        """
        Calculate discount amount for an order.

        Args:
            order_amount: Total order amount
            applicable_amount: Amount of applicable items (for partial campaigns)

        Returns:
            float: Discount amount
        """
        if applicable_amount is None:
            applicable_amount = order_amount

        if self.discount_type == "Percentage":
            discount = applicable_amount * (flt(self.discount_value) / 100)
            # Apply max discount cap
            if flt(self.max_discount_amount) > 0:
                discount = min(discount, flt(self.max_discount_amount))
            return round(discount, 2)

        elif self.discount_type == "Fixed Amount":
            return min(flt(self.discount_value), applicable_amount)

        elif self.discount_type == "Free Shipping":
            # Return 0 - shipping handled separately
            return 0

        return 0

    # =========================================================================
    # Coupon Integration
    # =========================================================================

    def generate_coupons_if_needed(self):
        """Generate coupon codes if auto_generate_coupon is enabled."""
        if not self.auto_generate_coupon:
            return

        # Check if coupons already generated
        if self.linked_coupons:
            return

        quantity = cint(self.coupon_quantity) or 1
        prefix = self.coupon_prefix or self.campaign_name[:5].upper()

        generated_codes = []

        for _ in range(quantity):
            code = self._generate_unique_coupon_code(prefix)
            coupon = self._create_coupon_from_campaign(code)
            if coupon:
                generated_codes.append(code)

        if generated_codes:
            self.db_set("linked_coupons", ", ".join(generated_codes))

    def _generate_unique_coupon_code(self, prefix: str) -> str:
        """Generate a unique coupon code."""
        while True:
            suffix = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
            code = f"{prefix}{suffix}"
            if not frappe.db.exists("Coupon", code):
                return code

    def _create_coupon_from_campaign(self, code: str):
        """Create a coupon linked to this campaign."""
        try:
            coupon = frappe.get_doc({
                "doctype": "Coupon",
                "coupon_code": code,
                "title": f"{self.campaign_name} - {code}",
                "discount_type": self.discount_type if self.discount_type != "No Discount" else "Percentage",
                "discount_value": self.discount_value or 0,
                "max_discount_amount": self.max_discount_amount,
                "min_order_amount": self.min_order_amount,
                "valid_from": self.start_date,
                "valid_until": self.end_date,
                "usage_limit": 1,
                "seller": self.seller,
                "is_active": 1,
                "description": f"Coupon from campaign: {self.campaign_name}"
            })
            coupon.insert(ignore_permissions=True)
            return coupon
        except Exception as e:
            frappe.log_error(f"Failed to create coupon {code}: {str(e)}", "Campaign Coupon Error")
            return None

    # =========================================================================
    # Analytics & Tracking
    # =========================================================================

    def record_view(self):
        """Record a campaign view."""
        self.db_set("views_count", cint(self.views_count) + 1, update_modified=False)

    def record_click(self):
        """Record a campaign click."""
        self.db_set("clicks_count", cint(self.clicks_count) + 1, update_modified=False)

    def record_usage(self, order_name: str, discount_amount: float, order_total: float, buyer: str):
        """
        Record campaign usage from an order.

        Args:
            order_name: Order document name
            discount_amount: Discount amount applied
            order_total: Total order amount
            buyer: Buyer profile name
        """
        self.db_set("total_usage", cint(self.total_usage) + 1, update_modified=False)
        self.db_set("orders_count", cint(self.orders_count) + 1, update_modified=False)
        self.db_set("spent_amount", flt(self.spent_amount) + flt(discount_amount), update_modified=False)
        self.db_set("revenue_generated", flt(self.revenue_generated) + flt(order_total), update_modified=False)

        # Update unique users count
        existing_usage = frappe.db.count(
            "Order",
            filters={"campaign": self.name, "buyer": buyer, "name": ["!=", order_name]}
        )
        if existing_usage == 0:
            self.db_set("unique_users", cint(self.unique_users) + 1, update_modified=False)

        # Update remaining budget
        if self.budget_enabled:
            remaining = flt(self.total_budget) - flt(self.spent_amount) - flt(discount_amount)
            self.db_set("remaining_budget", max(0, remaining), update_modified=False)

    def get_analytics_summary(self) -> Dict:
        """Get campaign analytics summary."""
        return {
            "campaign_name": self.campaign_name,
            "status": self.status,
            "views": self.views_count,
            "clicks": self.clicks_count,
            "orders": self.orders_count,
            "unique_users": self.unique_users,
            "total_usage": self.total_usage,
            "spent_amount": self.spent_amount,
            "revenue_generated": self.revenue_generated,
            "remaining_budget": self.remaining_budget if self.budget_enabled else None,
            "conversion_rate": round(
                (cint(self.orders_count) / cint(self.clicks_count) * 100)
                if cint(self.clicks_count) > 0 else 0, 2
            ),
            "roi": round(
                (flt(self.revenue_generated) / flt(self.spent_amount))
                if flt(self.spent_amount) > 0 else 0, 2
            )
        }

    # =========================================================================
    # Cache Management
    # =========================================================================

    def clear_campaign_cache(self):
        """Clear cached campaign data."""
        cache_keys = [
            "active_campaigns",
            f"campaign:{self.name}",
            f"seller_campaigns:{self.seller}",
            f"tenant_campaigns:{self.tenant}",
        ]
        for key in cache_keys:
            frappe.cache().delete_value(key)


# =============================================================================
# API Endpoints
# =============================================================================


@frappe.whitelist()
def get_active_campaigns(
    seller: str = None,
    category: str = None,
    include_platform: bool = True
) -> List[Dict]:
    """
    Get all active campaigns.

    Args:
        seller: Optional seller filter
        category: Optional category filter
        include_platform: Include platform-wide campaigns

    Returns:
        list: Active campaigns
    """
    filters = {"status": "Active"}

    or_filters = []
    if seller:
        or_filters.append({"seller": seller})
        if include_platform:
            or_filters.append({"seller": ["is", "not set"]})
    elif include_platform:
        filters["seller"] = ["is", "not set"]

    campaigns = frappe.get_all(
        "Campaign",
        filters=filters,
        or_filters=or_filters if or_filters else None,
        fields=[
            "name", "campaign_name", "campaign_type", "status",
            "discount_type", "discount_value", "max_discount_amount",
            "min_order_amount", "start_date", "end_date",
            "banner_image", "highlight_text", "highlight_color",
            "is_featured", "display_order"
        ],
        order_by="is_featured DESC, priority DESC, display_order ASC"
    )

    # Filter by validity period
    current_time = now_datetime()
    valid_campaigns = []

    for campaign in campaigns:
        start = get_datetime(campaign.start_date) if campaign.start_date else None
        end = get_datetime(campaign.end_date) if campaign.end_date else None

        if start and current_time < start:
            continue
        if end and current_time > end:
            continue

        # Check category if specified
        if category:
            full_campaign = frappe.get_doc("Campaign", campaign.name)
            if full_campaign.applies_to == "Specific Categories":
                if full_campaign.applicable_categories:
                    allowed = [c.strip().lower() for c in full_campaign.applicable_categories.split(",")]
                    if category.lower() not in allowed:
                        continue

        valid_campaigns.append(campaign)

    return valid_campaigns


@frappe.whitelist()
def apply_campaign_to_order(
    campaign_name: str,
    order_name: str
) -> Dict:
    """
    Apply a campaign to an order.

    Args:
        campaign_name: Campaign document name
        order_name: Order document name

    Returns:
        dict: Application result
    """
    campaign = frappe.get_doc("Campaign", campaign_name)
    order = frappe.get_doc("Order", order_name)

    # Validate eligibility
    is_valid, error = campaign.is_valid_for_order(
        order_amount=flt(order.total_amount),
        buyer=order.buyer,
        seller=order.seller if hasattr(order, 'seller') else None
    )

    if not is_valid:
        return {"success": False, "message": error}

    # Calculate discount
    discount = campaign.calculate_discount(flt(order.subtotal))

    # Update order
    order.campaign = campaign_name
    order.campaign_discount = discount
    order.total_amount = flt(order.subtotal) + flt(order.shipping_amount) + flt(order.tax_amount) - discount
    order.save()

    # Record usage
    campaign.record_usage(order_name, discount, order.total_amount, order.buyer)

    return {
        "success": True,
        "discount_amount": discount,
        "campaign_name": campaign.campaign_name,
        "new_total": order.total_amount
    }


@frappe.whitelist()
def validate_campaign_for_checkout(
    campaign_name: str,
    order_amount: float,
    buyer: str = None,
    seller: str = None,
    city: str = None
) -> Dict:
    """
    Validate if a campaign can be applied at checkout.

    Args:
        campaign_name: Campaign document name
        order_amount: Order total amount
        buyer: Buyer profile name
        seller: Seller profile name
        city: Buyer's city

    Returns:
        dict: Validation result
    """
    if not frappe.db.exists("Campaign", campaign_name):
        return {"valid": False, "message": _("Campaign not found")}

    campaign = frappe.get_doc("Campaign", campaign_name)

    is_valid, error = campaign.is_valid_for_order(
        order_amount=flt(order_amount),
        buyer=buyer,
        seller=seller,
        city=city
    )

    if is_valid:
        discount = campaign.calculate_discount(flt(order_amount))
        return {
            "valid": True,
            "campaign_name": campaign.campaign_name,
            "discount_type": campaign.discount_type,
            "discount_value": campaign.discount_value,
            "estimated_discount": discount
        }
    else:
        return {"valid": False, "message": error}


@frappe.whitelist()
def get_campaign_analytics(campaign_name: str) -> Dict:
    """
    Get analytics for a campaign.

    Args:
        campaign_name: Campaign document name

    Returns:
        dict: Campaign analytics
    """
    campaign = frappe.get_doc("Campaign", campaign_name)
    return campaign.get_analytics_summary()


@frappe.whitelist()
def record_campaign_interaction(campaign_name: str, interaction_type: str) -> Dict:
    """
    Record a campaign interaction (view or click).

    Args:
        campaign_name: Campaign document name
        interaction_type: 'view' or 'click'

    Returns:
        dict: Success status
    """
    if not frappe.db.exists("Campaign", campaign_name):
        return {"success": False}

    campaign = frappe.get_doc("Campaign", campaign_name)

    if interaction_type == "view":
        campaign.record_view()
    elif interaction_type == "click":
        campaign.record_click()

    return {"success": True}


@frappe.whitelist()
def get_homepage_campaigns() -> List[Dict]:
    """
    Get campaigns to display on homepage.

    Returns:
        list: Homepage campaigns
    """
    return frappe.get_all(
        "Campaign",
        filters={
            "status": "Active",
            "show_on_homepage": 1
        },
        fields=[
            "name", "campaign_name", "campaign_type",
            "banner_image", "highlight_text", "highlight_color",
            "discount_type", "discount_value", "end_date"
        ],
        order_by="is_featured DESC, display_order ASC",
        limit=10
    )


# =============================================================================
# Scheduled Tasks
# =============================================================================


def update_campaign_statuses():
    """
    Scheduled task to update campaign statuses.

    This function:
    1. Activates scheduled campaigns that have reached their start date
    2. Deactivates/expires campaigns that have passed their end date
    3. Pauses campaigns that have exhausted their budget

    Called via cron job: daily at 5 AM
    """
    current_time = now_datetime()
    frappe.logger().info("Starting campaign status update...")

    activated = 0
    expired = 0
    paused = 0

    # Activate scheduled campaigns
    scheduled_campaigns = frappe.get_all(
        "Campaign",
        filters={
            "status": "Scheduled",
            "start_date": ["<=", current_time]
        },
        fields=["name", "campaign_name", "end_date"]
    )

    for campaign in scheduled_campaigns:
        end_date = get_datetime(campaign.end_date) if campaign.end_date else None

        if end_date and end_date < current_time:
            # Already expired before activation
            frappe.db.set_value("Campaign", campaign.name, "status", "Expired")
            expired += 1
        else:
            frappe.db.set_value("Campaign", campaign.name, "status", "Active")
            activated += 1
            frappe.logger().info(f"Activated campaign: {campaign.campaign_name}")

    # Expire ended campaigns
    active_campaigns = frappe.get_all(
        "Campaign",
        filters={
            "status": "Active",
            "end_date": ["<", current_time]
        },
        fields=["name", "campaign_name"]
    )

    for campaign in active_campaigns:
        frappe.db.set_value("Campaign", campaign.name, "status", "Expired")
        expired += 1
        frappe.logger().info(f"Expired campaign: {campaign.campaign_name}")

    # Pause campaigns that exceeded budget
    budget_campaigns = frappe.get_all(
        "Campaign",
        filters={
            "status": "Active",
            "budget_enabled": 1
        },
        fields=["name", "campaign_name", "total_budget", "spent_amount"]
    )

    for campaign in budget_campaigns:
        if flt(campaign.spent_amount) >= flt(campaign.total_budget):
            frappe.db.set_value("Campaign", campaign.name, "status", "Paused")
            paused += 1
            frappe.logger().info(f"Paused campaign (budget exhausted): {campaign.campaign_name}")

    frappe.db.commit()

    frappe.logger().info(
        f"Campaign status update complete. Activated: {activated}, Expired: {expired}, Paused: {paused}"
    )

    return {
        "activated": activated,
        "expired": expired,
        "paused": paused
    }


def aggregate_daily_analytics():
    """
    Scheduled task to aggregate daily campaign analytics.

    This function:
    1. Calculates daily metrics for all active campaigns
    2. Updates ROI and conversion rates
    3. Logs analytics data for historical tracking

    Called via cron job: daily at 2 AM
    """
    frappe.logger().info("Starting daily campaign analytics aggregation...")

    # Get all campaigns that had activity today
    today = nowdate()
    yesterday = add_days(today, -1)

    active_campaigns = frappe.get_all(
        "Campaign",
        filters={
            "status": ["in", ["Active", "Expired", "Completed"]],
            "modified": [">=", yesterday]
        },
        fields=[
            "name", "campaign_name", "views_count", "clicks_count",
            "orders_count", "spent_amount", "revenue_generated"
        ]
    )

    for campaign in active_campaigns:
        try:
            # Calculate metrics
            ctr = 0
            conversion_rate = 0
            roi = 0

            if cint(campaign.views_count) > 0:
                ctr = (cint(campaign.clicks_count) / cint(campaign.views_count)) * 100

            if cint(campaign.clicks_count) > 0:
                conversion_rate = (cint(campaign.orders_count) / cint(campaign.clicks_count)) * 100

            if flt(campaign.spent_amount) > 0:
                roi = flt(campaign.revenue_generated) / flt(campaign.spent_amount)

            # Log analytics (could be stored in a separate analytics table)
            frappe.logger().debug(
                f"Campaign {campaign.campaign_name}: CTR={ctr:.2f}%, Conv={conversion_rate:.2f}%, ROI={roi:.2f}"
            )

        except Exception as e:
            frappe.log_error(
                f"Failed to aggregate analytics for {campaign.name}: {str(e)}",
                "Campaign Analytics Error"
            )

    frappe.logger().info(
        f"Campaign analytics aggregation complete. Processed {len(active_campaigns)} campaigns."
    )

    return {"processed": len(active_campaigns)}


@frappe.whitelist()
def create_flash_sale_campaign(
    name: str,
    seller: str = None,
    discount_percent: float = 20,
    duration_hours: int = 24,
    category: str = None,
    products: str = None
) -> Dict:
    """
    Quickly create a flash sale campaign.

    Args:
        name: Campaign name
        seller: Seller profile (optional for platform-wide)
        discount_percent: Discount percentage
        duration_hours: Duration in hours
        category: Optional category restriction
        products: Optional comma-separated product list

    Returns:
        dict: Created campaign details
    """
    from frappe.utils import now_datetime, add_to_date

    start = now_datetime()
    end = add_to_date(start, hours=duration_hours)

    campaign = frappe.get_doc({
        "doctype": "Campaign",
        "campaign_name": name,
        "campaign_type": "Flash Sale",
        "status": "Scheduled",
        "start_date": start,
        "end_date": end,
        "discount_type": "Percentage",
        "discount_value": discount_percent,
        "seller": seller,
        "applies_to": "Specific Categories" if category else ("Specific Products" if products else "All Products"),
        "applicable_categories": category,
        "applicable_products": products,
        "is_featured": 1,
        "show_on_homepage": 1,
        "highlight_text": f"{discount_percent}% OFF - Flash Sale!"
    })

    campaign.insert()

    return {
        "success": True,
        "campaign_name": campaign.name,
        "starts": str(start),
        "ends": str(end)
    }

# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import nowdate, now_datetime, getdate, add_months


class SellerLevel(Document):
    """Seller Level DocType for tier-based benefits system."""

    def validate(self):
        """Validate seller level data."""
        self.validate_level_code()
        self.validate_level_rank()
        self.validate_default_level()
        self.validate_thresholds()
        self.validate_commission()
        self.validate_next_level()
        self.set_display_name()

    def validate_level_code(self):
        """Validate and format level code."""
        if self.level_code:
            import re
            # Auto-format to uppercase
            self.level_code = self.level_code.upper().replace(" ", "_")
            if not re.match(r'^[A-Z0-9_]+$', self.level_code):
                frappe.throw(_("Level code should contain only letters, numbers, and underscores"))

    def validate_level_rank(self):
        """Validate level rank is positive."""
        if self.level_rank is None or self.level_rank < 0:
            frappe.throw(_("Level rank must be a non-negative integer"))

    def validate_default_level(self):
        """Ensure only one level is marked as default."""
        if self.is_default:
            existing_default = frappe.db.get_value(
                "Seller Level",
                {"is_default": 1, "name": ("!=", self.name)},
                "name"
            )
            if existing_default:
                frappe.throw(
                    _("Level '{0}' is already set as default. Only one level can be default.").format(
                        existing_default
                    )
                )

    def validate_thresholds(self):
        """Validate threshold values."""
        if self.threshold_value and self.threshold_value < 0:
            frappe.throw(_("Threshold value cannot be negative"))

        if self.min_sales_count and self.min_sales_count < 0:
            frappe.throw(_("Minimum sales count cannot be negative"))

        if self.min_sales_amount and self.min_sales_amount < 0:
            frappe.throw(_("Minimum sales amount cannot be negative"))

        if self.min_rating is not None:
            if self.min_rating < 0 or self.min_rating > 5:
                frappe.throw(_("Minimum rating must be between 0 and 5"))

        if self.max_return_rate and (self.max_return_rate < 0 or self.max_return_rate > 100):
            frappe.throw(_("Maximum return rate must be between 0 and 100"))

        if self.min_response_rate and (self.min_response_rate < 0 or self.min_response_rate > 100):
            frappe.throw(_("Minimum response rate must be between 0 and 100"))

        if self.evaluation_period_months and self.evaluation_period_months < 1:
            frappe.throw(_("Evaluation period must be at least 1 month"))

        if self.downgrade_grace_period_days and self.downgrade_grace_period_days < 0:
            frappe.throw(_("Downgrade grace period cannot be negative"))

    def validate_commission(self):
        """Validate commission rates."""
        if self.commission_rate and (self.commission_rate < 0 or self.commission_rate > 100):
            frappe.throw(_("Commission rate must be between 0 and 100"))

        if self.commission_reduction and (self.commission_reduction < 0 or self.commission_reduction > 100):
            frappe.throw(_("Commission reduction must be between 0 and 100"))

        if self.max_product_limit and self.max_product_limit < 0:
            frappe.throw(_("Maximum product limit cannot be negative"))

        if self.max_sku_per_product and self.max_sku_per_product < 0:
            frappe.throw(_("Maximum SKUs per product cannot be negative"))

    def validate_next_level(self):
        """Validate next level reference."""
        if self.next_level:
            if self.next_level == self.name:
                frappe.throw(_("Next level cannot be the same as current level"))

            # Check if next level has higher rank
            next_level_rank = frappe.db.get_value("Seller Level", self.next_level, "level_rank")
            if next_level_rank and next_level_rank <= self.level_rank:
                frappe.msgprint(
                    _("Warning: Next level '{0}' has equal or lower rank than this level").format(
                        self.next_level
                    ),
                    indicator="orange",
                    alert=True
                )

    def set_display_name(self):
        """Set display name if not provided."""
        if not self.display_name:
            self.display_name = self.level_name

    def before_save(self):
        """Actions before saving."""
        self.modified_at = now_datetime()
        if not self.created_at:
            self.created_at = now_datetime()

    def on_update(self):
        """Actions after update."""
        # Clear cache for seller level lookups
        frappe.cache().delete_key("seller_levels_list")

    def get_active_benefits(self):
        """Get list of active benefits for this level."""
        return [b for b in self.benefits if b.is_active]

    def get_benefit_by_type(self, benefit_type):
        """Get a specific benefit by type."""
        for benefit in self.benefits:
            if benefit.benefit_type == benefit_type and benefit.is_active:
                return benefit
        return None

    def get_benefit_by_code(self, benefit_code):
        """Get a specific benefit by code."""
        for benefit in self.benefits:
            if benefit.benefit_code == benefit_code and benefit.is_active:
                return benefit
        return None

    def get_all_benefits_dict(self):
        """Get all active benefits as a dictionary."""
        result = {}
        for benefit in self.benefits:
            if benefit.is_active:
                key = benefit.benefit_code or benefit.benefit_type
                result[key] = {
                    "name": benefit.benefit_name,
                    "type": benefit.benefit_type,
                    "value": benefit.get_numeric_value() if hasattr(benefit, 'get_numeric_value') else benefit.value,
                    "value_type": benefit.value_type,
                    "description": benefit.description
                }
        return result

    def get_effective_commission_rate(self, base_rate=None):
        """Calculate effective commission rate after reduction."""
        base = base_rate or self.commission_rate or 0
        reduction = self.commission_reduction or 0
        effective_rate = base - (base * reduction / 100)
        return max(0, effective_rate)

    def evaluate_seller(self, seller_profile):
        """Check if a seller qualifies for this level."""
        if not seller_profile:
            return False

        if self.qualification_type == "Manual Assignment":
            return False  # Cannot auto-qualify for manual levels

        # Get seller statistics
        seller_stats = self.get_seller_statistics(seller_profile)

        if self.qualification_type == "Sales Amount":
            return seller_stats.get("total_amount", 0) >= (self.threshold_value or 0)

        elif self.qualification_type == "Order Count":
            return seller_stats.get("sales_count", 0) >= (self.min_sales_count or 0)

        elif self.qualification_type == "Performance Score":
            rating_ok = seller_stats.get("rating", 0) >= (self.min_rating or 0)
            return_ok = seller_stats.get("return_rate", 100) <= (self.max_return_rate or 100)
            response_ok = seller_stats.get("response_rate", 0) >= (self.min_response_rate or 0)
            return rating_ok and return_ok and response_ok

        elif self.qualification_type == "Combined":
            amount_ok = seller_stats.get("total_amount", 0) >= (self.threshold_value or 0)
            count_ok = seller_stats.get("sales_count", 0) >= (self.min_sales_count or 0)
            rating_ok = seller_stats.get("rating", 0) >= (self.min_rating or 0)
            return amount_ok and count_ok and rating_ok

        return False

    def get_seller_statistics(self, seller_profile):
        """Get seller sales and performance statistics for evaluation."""
        evaluation_start = None
        if self.evaluation_period_months:
            evaluation_start = add_months(nowdate(), -self.evaluation_period_months)

        filters = {"seller": seller_profile, "docstatus": 1}
        if evaluation_start:
            filters["transaction_date"] = (">=", evaluation_start)

        # Get sales statistics from Sub Orders
        orders = frappe.get_all(
            "Sub Order",
            filters=filters,
            fields=["name", "grand_total", "transaction_date"]
        )

        total_amount = sum(o.grand_total or 0 for o in orders)
        sales_count = len(orders)

        # Get seller metrics
        seller_metrics = frappe.db.get_value(
            "Seller Profile",
            seller_profile,
            ["average_rating", "return_rate", "response_rate"],
            as_dict=True
        ) or {}

        return {
            "total_amount": total_amount,
            "sales_count": sales_count,
            "rating": seller_metrics.get("average_rating", 0) or 0,
            "return_rate": seller_metrics.get("return_rate", 0) or 0,
            "response_rate": seller_metrics.get("response_rate", 0) or 0,
            "orders": orders
        }

    def update_seller_count(self):
        """Update the count of sellers at this level."""
        count = frappe.db.count("Seller Profile", {"seller_level": self.name})
        premium_count = frappe.db.count("Premium Seller", {"seller_level": self.name})
        self.seller_count = count + premium_count
        self.last_calculated_at = now_datetime()
        self.db_update()

    def can_list_products(self, current_product_count):
        """Check if a seller at this level can list more products."""
        if not self.max_product_limit or self.max_product_limit == 0:
            return True  # Unlimited
        return current_product_count < self.max_product_limit

    def get_remaining_product_slots(self, current_product_count):
        """Get number of products a seller can still list."""
        if not self.max_product_limit or self.max_product_limit == 0:
            return -1  # Unlimited (indicated by -1)
        return max(0, self.max_product_limit - current_product_count)


@frappe.whitelist()
def get_seller_level(seller_profile):
    """Get the current level for a seller."""
    if not seller_profile:
        return None

    # Check Seller Profile first
    level = frappe.db.get_value("Seller Profile", seller_profile, "seller_level")
    if level:
        return frappe.get_doc("Seller Level", level)

    # Return default level if no level assigned
    return get_default_level()


@frappe.whitelist()
def get_default_level():
    """Get the default seller level."""
    default_level = frappe.db.get_value(
        "Seller Level",
        {"is_default": 1, "status": "Active"},
        "name"
    )
    if default_level:
        return frappe.get_doc("Seller Level", default_level)

    # If no default, return lowest rank active level
    lowest = frappe.db.get_value(
        "Seller Level",
        {"status": "Active"},
        "name",
        order_by="level_rank ASC"
    )
    if lowest:
        return frappe.get_doc("Seller Level", lowest)

    return None


@frappe.whitelist()
def get_all_levels():
    """Get all active seller levels ordered by rank."""
    levels = frappe.get_all(
        "Seller Level",
        filters={"status": "Active"},
        fields=[
            "name", "level_name", "level_code", "level_rank",
            "color", "icon", "threshold_value", "commission_rate",
            "commission_reduction", "max_product_limit"
        ],
        order_by="level_rank ASC"
    )
    return levels


@frappe.whitelist()
def get_next_level(current_level):
    """Get the next level a seller can progress to."""
    if not current_level:
        return get_default_level()

    level_doc = frappe.get_doc("Seller Level", current_level)

    # If next_level is explicitly set, use it
    if level_doc.next_level:
        return frappe.get_doc("Seller Level", level_doc.next_level)

    # Otherwise, find the next higher rank level
    next_level = frappe.db.get_value(
        "Seller Level",
        {"status": "Active", "level_rank": (">", level_doc.level_rank)},
        "name",
        order_by="level_rank ASC"
    )
    if next_level:
        return frappe.get_doc("Seller Level", next_level)

    return None


@frappe.whitelist()
def evaluate_seller_for_upgrade(seller_profile):
    """Check if a seller qualifies for a level upgrade."""
    if not seller_profile:
        return {"upgrade": False, "message": _("No seller profile provided")}

    current_level = get_seller_level(seller_profile)
    if not current_level:
        return {"upgrade": False, "message": _("No current level found")}

    next_level = get_next_level(current_level.name)
    if not next_level:
        return {"upgrade": False, "message": _("Already at highest level")}

    if next_level.evaluate_seller(seller_profile):
        return {
            "upgrade": True,
            "current_level": current_level.name,
            "new_level": next_level.name,
            "message": _("Seller qualifies for upgrade to {0}").format(next_level.level_name)
        }

    return {
        "upgrade": False,
        "current_level": current_level.name,
        "next_level": next_level.name,
        "message": _("Seller does not yet qualify for {0}").format(next_level.level_name)
    }


@frappe.whitelist()
def get_level_benefits(level_name):
    """Get all active benefits for a specific level."""
    if not level_name:
        return []

    level_doc = frappe.get_doc("Seller Level", level_name)
    return level_doc.get_all_benefits_dict()


@frappe.whitelist()
def get_commission_rate_for_seller(seller_profile, base_rate=None):
    """Get the effective commission rate for a seller based on their level."""
    level = get_seller_level(seller_profile)
    if not level:
        return base_rate or 0

    return level.get_effective_commission_rate(base_rate)


@frappe.whitelist()
def check_product_limit(seller_profile):
    """Check if a seller can list more products."""
    level = get_seller_level(seller_profile)
    if not level:
        return {"can_list": True, "remaining": -1, "message": _("No level restrictions")}

    # Get current product count
    product_count = frappe.db.count("Listing", {"seller": seller_profile, "status": ("!=", "Deleted")})

    can_list = level.can_list_products(product_count)
    remaining = level.get_remaining_product_slots(product_count)

    if can_list:
        msg = _("Unlimited products allowed") if remaining == -1 else _("{0} product slots remaining").format(remaining)
        return {"can_list": True, "remaining": remaining, "message": msg}
    else:
        return {
            "can_list": False,
            "remaining": 0,
            "message": _("Product limit reached. Upgrade to {0} for more slots.").format(
                get_next_level(level.name).level_name if get_next_level(level.name) else _("higher level")
            )
        }


@frappe.whitelist()
def update_all_seller_counts():
    """Update seller counts for all levels. Usually run as a scheduled task."""
    levels = frappe.get_all("Seller Level", pluck="name")
    for level_name in levels:
        level = frappe.get_doc("Seller Level", level_name)
        level.update_seller_count()
    frappe.db.commit()
    return {"success": True, "updated_levels": len(levels)}

# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import nowdate, now_datetime, getdate, add_months


class BuyerLevel(Document):
    """Buyer Level DocType for tier-based benefits system."""

    def validate(self):
        """Validate buyer level data."""
        self.validate_level_code()
        self.validate_level_rank()
        self.validate_default_level()
        self.validate_thresholds()
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
                "Buyer Level",
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

        if self.min_order_count and self.min_order_count < 0:
            frappe.throw(_("Minimum order count cannot be negative"))

        if self.min_order_amount and self.min_order_amount < 0:
            frappe.throw(_("Minimum order amount cannot be negative"))

        if self.evaluation_period_months and self.evaluation_period_months < 1:
            frappe.throw(_("Evaluation period must be at least 1 month"))

        if self.downgrade_grace_period_days and self.downgrade_grace_period_days < 0:
            frappe.throw(_("Downgrade grace period cannot be negative"))

    def validate_next_level(self):
        """Validate next level reference."""
        if self.next_level:
            if self.next_level == self.name:
                frappe.throw(_("Next level cannot be the same as current level"))

            # Check if next level has higher rank
            next_level_rank = frappe.db.get_value("Buyer Level", self.next_level, "level_rank")
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
        # Clear cache for buyer level lookups
        frappe.cache().delete_key("buyer_levels_list")

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

    def evaluate_buyer(self, buyer_profile):
        """Check if a buyer qualifies for this level."""
        if not buyer_profile:
            return False

        if self.qualification_type == "Manual Assignment":
            return False  # Cannot auto-qualify for manual levels

        # Get buyer statistics
        buyer_stats = self.get_buyer_statistics(buyer_profile)

        if self.qualification_type == "Purchase Amount":
            return buyer_stats.get("total_amount", 0) >= (self.threshold_value or 0)

        elif self.qualification_type == "Order Count":
            return buyer_stats.get("order_count", 0) >= (self.min_order_count or 0)

        elif self.qualification_type == "Points":
            buyer_points = frappe.db.get_value("Buyer Profile", buyer_profile, "reward_points") or 0
            return buyer_points >= (self.threshold_value or 0)

        elif self.qualification_type == "Combined":
            amount_ok = buyer_stats.get("total_amount", 0) >= (self.threshold_value or 0)
            count_ok = buyer_stats.get("order_count", 0) >= (self.min_order_count or 0)
            return amount_ok and count_ok

        return False

    def get_buyer_statistics(self, buyer_profile):
        """Get buyer purchase statistics for evaluation."""
        evaluation_start = None
        if self.evaluation_period_months:
            evaluation_start = add_months(nowdate(), -self.evaluation_period_months)

        filters = {"buyer": buyer_profile, "docstatus": 1}
        if evaluation_start:
            filters["transaction_date"] = (">=", evaluation_start)

        # Get order statistics
        orders = frappe.get_all(
            "Marketplace Order",
            filters=filters,
            fields=["name", "grand_total", "transaction_date"]
        )

        total_amount = sum(o.grand_total or 0 for o in orders)
        order_count = len(orders)

        return {
            "total_amount": total_amount,
            "order_count": order_count,
            "orders": orders
        }

    def update_buyer_count(self):
        """Update the count of buyers at this level."""
        count = frappe.db.count("Buyer Profile", {"buyer_level": self.name})
        premium_count = frappe.db.count("Premium Buyer", {"buyer_level": self.name})
        self.buyer_count = count + premium_count
        self.last_calculated_at = now_datetime()
        self.db_update()


@frappe.whitelist()
def get_buyer_level(buyer_profile):
    """Get the current level for a buyer."""
    if not buyer_profile:
        return None

    # Check Buyer Profile first
    level = frappe.db.get_value("Buyer Profile", buyer_profile, "buyer_level")
    if level:
        return frappe.get_doc("Buyer Level", level)

    # Return default level if no level assigned
    return get_default_level()


@frappe.whitelist()
def get_default_level():
    """Get the default buyer level."""
    default_level = frappe.db.get_value(
        "Buyer Level",
        {"is_default": 1, "status": "Active"},
        "name"
    )
    if default_level:
        return frappe.get_doc("Buyer Level", default_level)

    # If no default, return lowest rank active level
    lowest = frappe.db.get_value(
        "Buyer Level",
        {"status": "Active"},
        "name",
        order_by="level_rank ASC"
    )
    if lowest:
        return frappe.get_doc("Buyer Level", lowest)

    return None


@frappe.whitelist()
def get_all_levels():
    """Get all active buyer levels ordered by rank."""
    levels = frappe.get_all(
        "Buyer Level",
        filters={"status": "Active"},
        fields=["name", "level_name", "level_code", "level_rank", "color", "icon", "threshold_value"],
        order_by="level_rank ASC"
    )
    return levels


@frappe.whitelist()
def get_next_level(current_level):
    """Get the next level a buyer can progress to."""
    if not current_level:
        return get_default_level()

    level_doc = frappe.get_doc("Buyer Level", current_level)

    # If next_level is explicitly set, use it
    if level_doc.next_level:
        return frappe.get_doc("Buyer Level", level_doc.next_level)

    # Otherwise, find the next higher rank level
    next_level = frappe.db.get_value(
        "Buyer Level",
        {"status": "Active", "level_rank": (">", level_doc.level_rank)},
        "name",
        order_by="level_rank ASC"
    )
    if next_level:
        return frappe.get_doc("Buyer Level", next_level)

    return None


@frappe.whitelist()
def evaluate_buyer_for_upgrade(buyer_profile):
    """Check if a buyer qualifies for a level upgrade."""
    if not buyer_profile:
        return {"upgrade": False, "message": _("No buyer profile provided")}

    current_level = get_buyer_level(buyer_profile)
    if not current_level:
        return {"upgrade": False, "message": _("No current level found")}

    next_level = get_next_level(current_level.name)
    if not next_level:
        return {"upgrade": False, "message": _("Already at highest level")}

    if next_level.evaluate_buyer(buyer_profile):
        return {
            "upgrade": True,
            "current_level": current_level.name,
            "new_level": next_level.name,
            "message": _("Buyer qualifies for upgrade to {0}").format(next_level.level_name)
        }

    return {
        "upgrade": False,
        "current_level": current_level.name,
        "next_level": next_level.name,
        "message": _("Buyer does not yet qualify for {0}").format(next_level.level_name)
    }


@frappe.whitelist()
def get_level_benefits(level_name):
    """Get all active benefits for a specific level."""
    if not level_name:
        return []

    level_doc = frappe.get_doc("Buyer Level", level_name)
    return level_doc.get_all_benefits_dict()


@frappe.whitelist()
def update_all_buyer_counts():
    """Update buyer counts for all levels. Usually run as a scheduled task."""
    levels = frappe.get_all("Buyer Level", pluck="name")
    for level_name in levels:
        level = frappe.get_doc("Buyer Level", level_name)
        level.update_buyer_count()
    frappe.db.commit()
    return {"success": True, "updated_levels": len(levels)}

# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import nowdate, now_datetime, getdate, add_days


class SubscriptionPackage(Document):
    """Subscription Package DocType for subscription billing system."""

    def validate(self):
        """Validate subscription package data."""
        self.validate_package_code()
        self.validate_package_rank()
        self.validate_default_package()
        self.validate_pricing()
        self.validate_limits()
        self.validate_grace_period()
        self.validate_upgrade_path()
        self.set_display_name()

    def validate_package_code(self):
        """Validate and format package code."""
        if self.package_code:
            import re
            # Auto-format to uppercase
            self.package_code = self.package_code.upper().replace(" ", "_")
            if not re.match(r'^[A-Z0-9_]+$', self.package_code):
                frappe.throw(_("Package code should contain only letters, numbers, and underscores"))

    def validate_package_rank(self):
        """Validate package rank is positive."""
        if self.package_rank is None or self.package_rank < 0:
            frappe.throw(_("Package rank must be a non-negative integer"))

    def validate_default_package(self):
        """Ensure only one package is marked as default."""
        if self.is_default:
            existing_default = frappe.db.get_value(
                "Subscription Package",
                {"is_default": 1, "name": ("!=", self.name)},
                "name"
            )
            if existing_default:
                frappe.throw(
                    _("Package '{0}' is already set as default. Only one package can be default.").format(
                        existing_default
                    )
                )

    def validate_pricing(self):
        """Validate pricing fields."""
        if self.price and self.price < 0:
            frappe.throw(_("Price cannot be negative"))

        if self.setup_fee and self.setup_fee < 0:
            frappe.throw(_("Setup fee cannot be negative"))

        if self.trial_days and self.trial_days < 0:
            frappe.throw(_("Trial days cannot be negative"))

        if self.annual_discount_percent and (self.annual_discount_percent < 0 or self.annual_discount_percent > 100):
            frappe.throw(_("Annual discount must be between 0 and 100"))

        if self.promotional_price and self.promotional_price < 0:
            frappe.throw(_("Promotional price cannot be negative"))

        if self.promotional_price and self.promotional_price >= self.price:
            frappe.msgprint(
                _("Warning: Promotional price is not less than regular price"),
                indicator="orange",
                alert=True
            )

    def validate_limits(self):
        """Validate package limits."""
        if self.max_products and self.max_products < 0:
            frappe.throw(_("Max products cannot be negative"))

        if self.max_skus_per_product and self.max_skus_per_product < 0:
            frappe.throw(_("Max SKUs per product cannot be negative"))

        if self.max_orders_per_month and self.max_orders_per_month < 0:
            frappe.throw(_("Max orders per month cannot be negative"))

        if self.max_storage_mb and self.max_storage_mb < 0:
            frappe.throw(_("Max storage cannot be negative"))

        if self.max_api_calls_per_day and self.max_api_calls_per_day < 0:
            frappe.throw(_("Max API calls cannot be negative"))

        if self.max_team_members and self.max_team_members < 0:
            frappe.throw(_("Max team members cannot be negative"))

    def validate_grace_period(self):
        """Validate grace period settings."""
        if self.grace_period_days and self.grace_period_days < 0:
            frappe.throw(_("Grace period days cannot be negative"))

        if self.suspension_warning_days and self.suspension_warning_days < 0:
            frappe.throw(_("Suspension warning days cannot be negative"))

        if self.suspend_after_days and self.suspend_after_days < 0:
            frappe.throw(_("Suspend after days cannot be negative"))

        # Warning if suspension is before grace period ends
        if self.suspend_after_days and self.grace_period_days:
            if self.suspend_after_days < self.grace_period_days:
                frappe.msgprint(
                    _("Warning: Suspension will occur before grace period ends"),
                    indicator="orange",
                    alert=True
                )

    def validate_upgrade_path(self):
        """Validate upgrade and downgrade paths."""
        if self.upgrade_path:
            if self.upgrade_path == self.name:
                frappe.throw(_("Upgrade path cannot be the same as current package"))

            # Check if upgrade path has higher rank
            upgrade_rank = frappe.db.get_value("Subscription Package", self.upgrade_path, "package_rank")
            if upgrade_rank and upgrade_rank <= self.package_rank:
                frappe.msgprint(
                    _("Warning: Upgrade package '{0}' has equal or lower rank than this package").format(
                        self.upgrade_path
                    ),
                    indicator="orange",
                    alert=True
                )

        if self.downgrade_path:
            if self.downgrade_path == self.name:
                frappe.throw(_("Downgrade path cannot be the same as current package"))

            # Check if downgrade path has lower rank
            downgrade_rank = frappe.db.get_value("Subscription Package", self.downgrade_path, "package_rank")
            if downgrade_rank and downgrade_rank >= self.package_rank:
                frappe.msgprint(
                    _("Warning: Downgrade package '{0}' has equal or higher rank than this package").format(
                        self.downgrade_path
                    ),
                    indicator="orange",
                    alert=True
                )

    def set_display_name(self):
        """Set display name if not provided."""
        if not self.display_name:
            self.display_name = self.package_name

    def before_save(self):
        """Actions before saving."""
        self.modified_at = now_datetime()
        if not self.created_at:
            self.created_at = now_datetime()

    def on_update(self):
        """Actions after update."""
        # Clear cache for subscription package lookups
        frappe.cache().delete_key("subscription_packages_list")

    def is_free_package(self):
        """Check if this is a free package."""
        return not self.price or self.price == 0

    def get_effective_price(self, billing_period=None):
        """Get the effective price considering promotions and discounts."""
        # Check for active promotion
        if self.promotional_price and self.promotion_valid_until:
            if getdate(self.promotion_valid_until) >= getdate(nowdate()):
                return self.promotional_price

        # Check for annual discount
        period = billing_period or self.billing_period
        if period == "Annual" and self.annual_discount_percent:
            monthly_equivalent = self.price * 12
            discount = monthly_equivalent * (self.annual_discount_percent / 100)
            return monthly_equivalent - discount

        return self.price or 0

    def get_features_list(self):
        """Get list of enabled features."""
        features = []
        feature_fields = [
            ("has_analytics", _("Analytics Dashboard")),
            ("has_priority_support", _("Priority Support")),
            ("has_custom_domain", _("Custom Domain")),
            ("has_api_access", _("API Access")),
            ("has_bulk_import", _("Bulk Import/Export")),
            ("has_advanced_reporting", _("Advanced Reporting")),
            ("has_multi_warehouse", _("Multi-Warehouse")),
            ("has_white_label", _("White Label")),
        ]

        for field, label in feature_fields:
            if getattr(self, field, False):
                features.append(label)

        return features

    def get_limits_dict(self):
        """Get package limits as a dictionary."""
        return {
            "max_products": self.max_products or 0,
            "max_skus_per_product": self.max_skus_per_product or 0,
            "max_orders_per_month": self.max_orders_per_month or 0,
            "max_storage_mb": self.max_storage_mb or 0,
            "max_api_calls_per_day": self.max_api_calls_per_day or 0,
            "max_team_members": self.max_team_members or 0,
        }

    def has_unlimited(self, limit_type):
        """Check if a specific limit is unlimited (0 = unlimited)."""
        limit_value = getattr(self, limit_type, None)
        return limit_value is None or limit_value == 0

    def calculate_commission(self, transaction_amount):
        """Calculate commission and fees for a transaction."""
        commission = transaction_amount * ((self.commission_rate or 0) / 100)
        transaction_fee = transaction_amount * ((self.transaction_fee_percent or 0) / 100)

        total_fee = commission + transaction_fee

        # Apply minimum fee
        if self.minimum_transaction_fee and total_fee < self.minimum_transaction_fee:
            total_fee = self.minimum_transaction_fee

        # Apply fee cap
        if self.fee_cap_per_transaction and self.fee_cap_per_transaction > 0:
            total_fee = min(total_fee, self.fee_cap_per_transaction)

        return {
            "commission": commission,
            "transaction_fee": transaction_fee,
            "total_fee": total_fee,
            "net_amount": transaction_amount - total_fee
        }

    def get_suspension_date(self, due_date):
        """Calculate the suspension date based on due date."""
        if not due_date:
            return None
        return add_days(getdate(due_date), self.suspend_after_days or 14)

    def get_warning_date(self, due_date):
        """Calculate the warning notification date."""
        if not due_date:
            return None
        suspension_date = self.get_suspension_date(due_date)
        if suspension_date and self.suspension_warning_days:
            return add_days(suspension_date, -(self.suspension_warning_days or 3))
        return None

    def update_subscriber_counts(self):
        """Update subscriber statistics."""
        # Count total subscribers
        total_count = frappe.db.count(
            "Subscription",
            {"subscription_package": self.name}
        )

        # Count active subscribers
        active_count = frappe.db.count(
            "Subscription",
            {"subscription_package": self.name, "status": "Active"}
        )

        self.subscriber_count = total_count
        self.active_subscriber_count = active_count
        self.last_calculated_at = now_datetime()
        self.db_update()


@frappe.whitelist()
def get_subscription_package(package_name):
    """Get a subscription package by name."""
    if not package_name:
        return None
    return frappe.get_doc("Subscription Package", package_name)


@frappe.whitelist()
def get_default_package():
    """Get the default subscription package."""
    default_package = frappe.db.get_value(
        "Subscription Package",
        {"is_default": 1, "status": "Active"},
        "name"
    )
    if default_package:
        return frappe.get_doc("Subscription Package", default_package)

    # If no default, return lowest rank active package
    lowest = frappe.db.get_value(
        "Subscription Package",
        {"status": "Active"},
        "name",
        order_by="package_rank ASC"
    )
    if lowest:
        return frappe.get_doc("Subscription Package", lowest)

    return None


@frappe.whitelist()
def get_all_packages(include_inactive=False):
    """Get all subscription packages ordered by rank."""
    filters = {}
    if not include_inactive:
        filters["status"] = "Active"

    packages = frappe.get_all(
        "Subscription Package",
        filters=filters,
        fields=[
            "name", "package_name", "package_code", "package_rank",
            "status", "billing_period", "price", "currency",
            "trial_days", "max_products", "max_orders_per_month",
            "commission_rate", "is_default", "is_featured",
            "display_name", "short_description", "color", "icon"
        ],
        order_by="package_rank ASC"
    )
    return packages


@frappe.whitelist()
def get_public_packages():
    """Get all public subscription packages for pricing page."""
    packages = frappe.get_all(
        "Subscription Package",
        filters={"status": "Active", "is_public": 1},
        fields=[
            "name", "package_name", "display_name", "package_rank",
            "billing_period", "price", "currency", "promotional_price",
            "promotion_valid_until", "trial_days", "is_featured",
            "short_description", "highlight_features", "color", "icon",
            "max_products", "max_orders_per_month", "has_analytics",
            "has_priority_support", "has_api_access", "has_bulk_import"
        ],
        order_by="display_order ASC, package_rank ASC"
    )
    return packages


@frappe.whitelist()
def get_upgrade_options(current_package):
    """Get available upgrade options from current package."""
    if not current_package:
        return get_all_packages()

    current = frappe.get_doc("Subscription Package", current_package)

    # Get all packages with higher rank
    packages = frappe.get_all(
        "Subscription Package",
        filters={
            "status": "Active",
            "package_rank": (">", current.package_rank)
        },
        fields=[
            "name", "package_name", "display_name", "package_rank",
            "price", "billing_period", "max_products", "commission_rate"
        ],
        order_by="package_rank ASC"
    )
    return packages


@frappe.whitelist()
def get_downgrade_options(current_package):
    """Get available downgrade options from current package."""
    if not current_package:
        return []

    current = frappe.get_doc("Subscription Package", current_package)

    if not current.allow_downgrade:
        return []

    # Get all packages with lower rank
    packages = frappe.get_all(
        "Subscription Package",
        filters={
            "status": "Active",
            "package_rank": ("<", current.package_rank)
        },
        fields=[
            "name", "package_name", "display_name", "package_rank",
            "price", "billing_period", "max_products", "commission_rate"
        ],
        order_by="package_rank DESC"
    )
    return packages


@frappe.whitelist()
def calculate_proration(current_package, new_package, days_remaining):
    """Calculate prorated amount when changing packages."""
    if not current_package or not new_package:
        return {"error": _("Both packages must be specified")}

    current = frappe.get_doc("Subscription Package", current_package)
    new = frappe.get_doc("Subscription Package", new_package)

    # Get billing period days
    period_days = {
        "Monthly": 30,
        "Quarterly": 90,
        "Semi-Annual": 180,
        "Annual": 365,
        "Lifetime": 0
    }

    current_period_days = period_days.get(current.billing_period, 30)
    new_period_days = period_days.get(new.billing_period, 30)

    # Calculate daily rates
    current_daily = (current.price or 0) / current_period_days if current_period_days > 0 else 0
    new_daily = (new.price or 0) / new_period_days if new_period_days > 0 else 0

    # Calculate credit and charge
    credit = current_daily * int(days_remaining)
    charge = new_daily * int(days_remaining)

    return {
        "credit": credit,
        "charge": charge,
        "net_amount": charge - credit,
        "is_upgrade": new.package_rank > current.package_rank
    }


@frappe.whitelist()
def update_all_subscriber_counts():
    """Update subscriber counts for all packages. Usually run as a scheduled task."""
    packages = frappe.get_all("Subscription Package", pluck="name")
    for package_name in packages:
        package = frappe.get_doc("Subscription Package", package_name)
        package.update_subscriber_counts()
    frappe.db.commit()
    return {"success": True, "updated_packages": len(packages)}

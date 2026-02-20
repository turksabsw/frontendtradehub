# Copyright (c) 2026, TR TradeHub and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, getdate, nowdate


class TaxRate(Document):
    """
    Tax Rate DocType for managing Turkish KDV (VAT) and other tax rates.

    Turkish VAT (KDV) Rates:
    - Standard Rate: 18% (General goods and services)
    - Reduced Rate 1: 8% (Food, textiles, medical supplies)
    - Reduced Rate 2: 1% (Newspapers, periodicals, basic food)
    - Exempt: 0% (Exports, certain services)

    Features:
    - Multiple tax rate support
    - Category-based tax assignment
    - Date-based effectiveness
    - Compound tax calculation
    - Shipping tax application
    """

    # begin: auto-generated types
    # This code is auto-generated. Do not modify anything in this block.

    from typing import TYPE_CHECKING

    if TYPE_CHECKING:
        from frappe.types import DF
        from tradehub_commerce.tradehub_commerce.doctype.tax_rate_category.tax_rate_category import TaxRateCategory

        applicable_categories: DF.TableMultiSelect[TaxRateCategory]
        apply_to_shipping: DF.Check
        country: DF.Link
        description: DF.SmallText | None
        effective_from: DF.Date | None
        effective_to: DF.Date | None
        is_active: DF.Check
        is_compound: DF.Check
        is_default: DF.Check
        rate: DF.Percent
        rate_type: DF.Literal["Percentage", "Fixed Amount"]
        tax_code: DF.Data
        tax_name: DF.Data
        tax_type: DF.Literal["VAT", "Sales Tax", "Service Tax", "Customs Duty", "Excise", "Withholding", "Other"]
    # end: auto-generated types

    def validate(self):
        """Validate tax rate data."""
        self.validate_rate()
        self.validate_dates()
        self.validate_default()

    def validate_rate(self):
        """Validate tax rate value."""
        if self.rate_type == "Percentage":
            if flt(self.rate) < 0 or flt(self.rate) > 100:
                frappe.throw(_("Tax rate percentage must be between 0 and 100"))
        else:
            if flt(self.rate) < 0:
                frappe.throw(_("Fixed tax amount cannot be negative"))

    def validate_dates(self):
        """Validate effective dates."""
        if self.effective_from and self.effective_to:
            if getdate(self.effective_from) > getdate(self.effective_to):
                frappe.throw(_("Effective From date cannot be after Effective To date"))

    def validate_default(self):
        """Ensure only one default tax rate exists."""
        if self.is_default:
            # Unset other defaults
            frappe.db.sql("""
                UPDATE `tabTax Rate`
                SET is_default = 0
                WHERE name != %s AND is_default = 1
            """, self.name)

    def is_effective(self, check_date=None):
        """
        Check if tax rate is effective on given date.

        Args:
            check_date: Date to check (defaults to today)

        Returns:
            bool: True if effective
        """
        if not self.is_active:
            return False

        check_date = getdate(check_date) if check_date else getdate(nowdate())

        if self.effective_from and getdate(self.effective_from) > check_date:
            return False

        if self.effective_to and getdate(self.effective_to) < check_date:
            return False

        return True

    def applies_to_category(self, category):
        """
        Check if tax rate applies to given category.

        Args:
            category: Category name to check

        Returns:
            bool: True if applicable
        """
        # If no categories specified, applies to all
        if not self.applicable_categories:
            return True

        # Check if category is in the list
        for cat in self.applicable_categories:
            if cat.category == category:
                return True

            # Check parent categories
            parent = frappe.db.get_value("Category", category, "parent_category")
            while parent:
                if cat.category == parent:
                    return True
                parent = frappe.db.get_value("Category", parent, "parent_category")

        return False


# =================================================================
# Utility Functions
# =================================================================

def get_default_tax_rate():
    """
    Get the default tax rate.

    Returns:
        float: Default tax rate percentage or 18.0 (Turkish standard KDV)
    """
    default_rate = frappe.db.get_value(
        "Tax Rate",
        {"is_default": 1, "is_active": 1},
        "rate"
    )
    return flt(default_rate) if default_rate is not None else 18.0


def get_tax_rate_for_category(category, check_date=None):
    """
    Get applicable tax rate for a category.

    Args:
        category: Category name
        check_date: Date to check effectiveness (defaults to today)

    Returns:
        float: Tax rate percentage
    """
    if not category:
        return get_default_tax_rate()

    # First check if category has a direct tax rate
    category_tax_rate = frappe.db.get_value("Category", category, "tax_rate")
    if category_tax_rate:
        tax_rate_doc = frappe.get_doc("Tax Rate", category_tax_rate)
        if tax_rate_doc.is_effective(check_date):
            return flt(tax_rate_doc.rate)

    # Check tax rates that apply to this category
    tax_rates = frappe.get_all(
        "Tax Rate",
        filters={"is_active": 1},
        fields=["name", "rate", "effective_from", "effective_to"]
    )

    for tax_rate in tax_rates:
        doc = frappe.get_doc("Tax Rate", tax_rate.name)
        if doc.is_effective(check_date) and doc.applies_to_category(category):
            return flt(doc.rate)

    # Fall back to default
    return get_default_tax_rate()


def get_all_active_tax_rates():
    """
    Get all active tax rates.

    Returns:
        list: List of active tax rate dicts
    """
    return frappe.get_all(
        "Tax Rate",
        filters={"is_active": 1},
        fields=["name", "tax_name", "tax_code", "rate", "tax_type", "is_default"],
        order_by="rate ASC"
    )


def create_default_turkish_tax_rates():
    """
    Create default Turkish KDV tax rates.
    Called during setup.
    """
    tax_rates = [
        {
            "tax_name": "KDV %18 (Standard)",
            "tax_code": "KDV18",
            "rate": 18,
            "tax_type": "VAT",
            "country": "Turkey",
            "is_default": 1,
            "description": "Standard Turkish VAT rate for general goods and services",
            "apply_to_shipping": 1
        },
        {
            "tax_name": "KDV %8 (Reduced)",
            "tax_code": "KDV8",
            "rate": 8,
            "tax_type": "VAT",
            "country": "Turkey",
            "is_default": 0,
            "description": "Reduced Turkish VAT rate for food, textiles, medical supplies"
        },
        {
            "tax_name": "KDV %1 (Minimum)",
            "tax_code": "KDV1",
            "rate": 1,
            "tax_type": "VAT",
            "country": "Turkey",
            "is_default": 0,
            "description": "Minimum Turkish VAT rate for newspapers, basic food items"
        },
        {
            "tax_name": "KDV %0 (Exempt)",
            "tax_code": "KDV0",
            "rate": 0,
            "tax_type": "VAT",
            "country": "Turkey",
            "is_default": 0,
            "description": "Tax exempt for exports and certain services"
        }
    ]

    for rate_data in tax_rates:
        if not frappe.db.exists("Tax Rate", rate_data["tax_name"]):
            doc = frappe.get_doc({
                "doctype": "Tax Rate",
                **rate_data
            })
            doc.flags.ignore_permissions = True
            doc.insert()

    frappe.db.commit()

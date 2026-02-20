# Copyright (c) 2026, TR TradeHub and contributors
# For license information, please see license.txt

"""
Patch: Setup Default Turkish Tax Rates (KDV)

This patch creates the default Turkish VAT (KDV) rates:
- KDV %18 (Standard) - Default rate for most goods/services
- KDV %8 (Reduced) - Food, textiles, medical supplies
- KDV %1 (Minimum) - Newspapers, periodicals, basic food
- KDV %0 (Exempt) - Exports, certain services
"""

import frappe


def execute():
    """Create default Turkish tax rates."""
    # Schema reload for migration safety
    frappe.reload_doc("tr_tradehub", "doctype", "tax_rate")
    # Check if Tax Rate doctype exists
    if not frappe.db.exists("DocType", "Tax Rate"):
        frappe.log_error(
            "Tax Rate DocType does not exist. Please run bench migrate first.",
            "Setup Default Tax Rates Patch"
        )
        return

    tax_rates = [
        {
            "tax_name": "KDV %18 (Standard)",
            "tax_code": "KDV18",
            "rate": 18,
            "rate_type": "Percentage",
            "tax_type": "VAT",
            "country": "Turkey",
            "is_active": 1,
            "is_default": 1,
            "apply_to_shipping": 1,
            "description": "Standard Turkish VAT rate (Katma Deger Vergisi) for general goods and services. This is the default rate applied to most products."
        },
        {
            "tax_name": "KDV %8 (Reduced)",
            "tax_code": "KDV8",
            "rate": 8,
            "rate_type": "Percentage",
            "tax_type": "VAT",
            "country": "Turkey",
            "is_active": 1,
            "is_default": 0,
            "apply_to_shipping": 0,
            "description": "Reduced Turkish VAT rate for essential goods including food products, textiles, medical supplies, hotels, and tourism services."
        },
        {
            "tax_name": "KDV %1 (Minimum)",
            "tax_code": "KDV1",
            "rate": 1,
            "rate_type": "Percentage",
            "tax_type": "VAT",
            "country": "Turkey",
            "is_active": 1,
            "is_default": 0,
            "apply_to_shipping": 0,
            "description": "Minimum Turkish VAT rate for newspapers, periodicals, magazines, basic food staples like bread and flour."
        },
        {
            "tax_name": "KDV %0 (Exempt)",
            "tax_code": "KDV0",
            "rate": 0,
            "rate_type": "Percentage",
            "tax_type": "VAT",
            "country": "Turkey",
            "is_active": 1,
            "is_default": 0,
            "apply_to_shipping": 0,
            "description": "Tax exempt rate for exports, international transport, certain financial and insurance services, and other legally exempt transactions."
        }
    ]

    created_count = 0
    updated_count = 0

    for rate_data in tax_rates:
        # Check if tax rate already exists by tax_code
        existing = frappe.db.get_value("Tax Rate", {"tax_code": rate_data["tax_code"]}, "name")

        if existing:
            # Update existing tax rate
            doc = frappe.get_doc("Tax Rate", existing)
            for key, value in rate_data.items():
                if key != "tax_name":  # Don't change the name
                    setattr(doc, key, value)
            doc.flags.ignore_permissions = True
            doc.save()
            updated_count += 1
            frappe.msgprint(f"Updated tax rate: {rate_data['tax_name']}")
        else:
            # Create new tax rate
            doc = frappe.get_doc({
                "doctype": "Tax Rate",
                **rate_data
            })
            doc.flags.ignore_permissions = True
            doc.insert()
            created_count += 1
            frappe.msgprint(f"Created tax rate: {rate_data['tax_name']}")

    frappe.db.commit()

    if created_count > 0:
        frappe.msgprint(f"Setup complete: Created {created_count} Turkish tax rates (KDV)")
    if updated_count > 0:
        frappe.msgprint(f"Updated {updated_count} existing tax rates")

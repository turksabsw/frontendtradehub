# Copyright (c) 2026, TR TradeHub and contributors
# For license information, please see license.txt

"""
Patch to create default Turkish shipping rules for TR TradeHub.

Creates the following shipping rules:
- Türkiye Standart Kargo (Standard domestic shipping)
- İstanbul İçi Teslimat (Istanbul local delivery)
- Ağır Kargo (Heavy freight shipping)
- Ekonomik Kargo (Economy shipping)
"""

import frappe


def execute():
    """Create default Turkish shipping rules."""
    # Schema reload for migration safety
    frappe.reload_doc("tr_tradehub", "doctype", "shipping_rule")
    from tr_tradehub.utils.shipping_calculator import create_default_turkish_shipping_rules

    try:
        result = create_default_turkish_shipping_rules()
        frappe.db.commit()

        if result.get("created"):
            print(f"Created shipping rules: {', '.join(result['created'])}")
        if result.get("skipped"):
            print(f"Skipped existing rules: {', '.join(result['skipped'])}")

    except Exception as e:
        frappe.log_error(f"Failed to create shipping rules: {str(e)}", "Setup Patch Error")
        # Don't raise - allow patch to pass even if rules already exist

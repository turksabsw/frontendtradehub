# Copyright (c) 2026, TR TradeHub and contributors
# For license information, please see license.txt

"""
Patch to create default product ranking configuration for TR TradeHub.

Creates a default ranking weight configuration with balanced weights
for sales, engagement, and quality factors.
"""

import frappe


def execute():
    """Create default product ranking configuration."""
    # Schema reload for migration safety
    frappe.reload_doc("tr_tradehub", "doctype", "ranking_weight_config")
    from tr_tradehub.tr_tradehub.doctype.ranking_weight_config.ranking_weight_config import (
        create_default_ranking_config
    )

    try:
        result = create_default_ranking_config()
        frappe.db.commit()

        if result.get("name"):
            print(f"Created default ranking configuration: {result['name']}")

    except Exception as e:
        frappe.log_error(
            f"Failed to create default ranking configuration: {str(e)}",
            "Setup Patch Error"
        )
        # Don't raise - allow patch to pass even if config already exists

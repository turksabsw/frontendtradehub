# Copyright (c) 2026, Trade Hub and contributors
# For license information, please see license.txt

"""
Trade Hub Webhooks Module.

This module provides webhook handlers for external system integrations:

- ERPNext hooks: Handles reverse sync when ERPNext documents are modified
- Future: External marketplace webhooks (Amazon, eBay, etc.)
- Future: Payment gateway webhooks (Stripe, PayPal, etc.)
- Future: Shipping provider webhooks (DHL, FedEx, etc.)

Usage:
    Webhooks are configured in hooks.py and called automatically
    by Frappe's doc_events system when documents are modified.

    from tr_tradehub.webhooks.erpnext_hooks import (
        on_supplier_update,
        on_customer_update,
        on_item_update,
        on_sales_order_update,
    )
"""

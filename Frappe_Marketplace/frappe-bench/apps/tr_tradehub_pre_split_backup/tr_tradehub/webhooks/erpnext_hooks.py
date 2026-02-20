# Copyright (c) 2026, Trade Hub and contributors
# For license information, please see license.txt

"""
ERPNext Webhook Handlers for Reverse Sync.

This module provides webhook handlers that are called when ERPNext documents
are modified. These handlers enable reverse synchronization from ERPNext
back to Trade Hub entities.

Supported ERPNext -> Trade Hub mappings:
- Supplier -> Seller Profile
- Customer -> Buyer Profile
- Item -> SKU Product
- Sales Order -> Order
- Stock Entry -> Inventory updates
- Purchase Invoice -> Payment status updates

These handlers are registered in hooks.py under doc_events and are called
automatically by Frappe when the corresponding ERPNext documents are saved
or updated.

IMPORTANT: These handlers check if ERPNext sync is enabled for the tenant
and if the document is linked to a Trade Hub entity before performing
any updates. This prevents unwanted sync loops.

Usage:
    # Handlers are called automatically via hooks.py
    # Manual invocation for testing:
    from tr_tradehub.webhooks.erpnext_hooks import on_item_update
    on_item_update(doc, method)
"""

from typing import Any, Dict, Optional

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt, now_datetime


# =============================================================================
# CONSTANTS
# =============================================================================

# Sync direction flag to prevent infinite loops
SYNC_FLAG_KEY = "trade_hub_sync_in_progress"

# Cache prefix for webhook processing
WEBHOOK_CACHE_PREFIX = "trade_hub:webhook"


# =============================================================================
# UTILITY FUNCTIONS
# =============================================================================


def is_sync_in_progress() -> bool:
    """
    Check if a sync operation is currently in progress.

    This prevents infinite loops when Trade Hub updates ERPNext
    and ERPNext triggers a webhook back to Trade Hub.

    Returns:
        bool: True if sync is in progress, False otherwise.
    """
    return frappe.flags.get(SYNC_FLAG_KEY, False)


def set_sync_in_progress(in_progress: bool = True) -> None:
    """
    Set the sync-in-progress flag.

    Args:
        in_progress: Whether sync is currently in progress.
    """
    frappe.flags[SYNC_FLAG_KEY] = in_progress


def is_erpnext_sync_enabled() -> bool:
    """
    Check if ERPNext sync is available and the module is installed.

    Returns:
        bool: True if ERPNext sync is available, False otherwise.
    """
    try:
        from tr_tradehub.utils.erpnext_sync import is_erpnext_installed
        return is_erpnext_installed()
    except ImportError:
        return False


def get_sync_settings(tenant: str = None) -> Dict[str, Any]:
    """
    Get sync settings for a tenant.

    Args:
        tenant: The tenant to get settings for.

    Returns:
        dict: Sync settings including reverse sync flags.
    """
    try:
        from tr_tradehub.utils.erpnext_sync import get_sync_settings as _get_settings
        settings = _get_settings(tenant)
        # Add reverse sync default if not present
        if "reverse_sync" not in settings:
            settings["reverse_sync"] = settings.get("enabled", False)
        return settings
    except ImportError:
        return {
            "enabled": False,
            "reverse_sync": False,
        }


def should_process_reverse_sync(doc: Document, doctype_key: str) -> bool:
    """
    Determine if reverse sync should be processed for this document.

    Args:
        doc: The ERPNext document being processed.
        doctype_key: The sync settings key to check (e.g., "sync_sellers").

    Returns:
        bool: True if reverse sync should proceed, False otherwise.
    """
    # Check if sync is already in progress (prevent loops)
    if is_sync_in_progress():
        return False

    # Check if ERPNext sync is available
    if not is_erpnext_sync_enabled():
        return False

    # Don't process during install/setup
    if frappe.flags.in_install or frappe.flags.in_setup_wizard:
        return False

    # Check if document was modified by Trade Hub sync
    if getattr(doc, "_from_trade_hub_sync", False):
        return False

    return True


def log_webhook_event(
    erpnext_doctype: str,
    erpnext_name: str,
    trade_hub_doctype: str,
    trade_hub_name: str,
    event_type: str,
    status: str = "success",
    error: str = None
) -> None:
    """
    Log a webhook sync event for auditing.

    Args:
        erpnext_doctype: The ERPNext DocType.
        erpnext_name: The ERPNext document name.
        trade_hub_doctype: The Trade Hub DocType.
        trade_hub_name: The Trade Hub document name.
        event_type: Type of event (update, create, delete).
        status: Status of the operation (success, failed, skipped).
        error: Error message if failed.
    """
    try:
        # Log to frappe error log for debugging
        if status == "failed" and error:
            frappe.log_error(
                message=f"ERPNext: {erpnext_doctype}/{erpnext_name} -> "
                        f"Trade Hub: {trade_hub_doctype}/{trade_hub_name}\n"
                        f"Event: {event_type}\nError: {error}",
                title=f"Webhook Sync Error: {erpnext_doctype}"
            )

        # Cache recent webhook events for monitoring
        cache_key = f"{WEBHOOK_CACHE_PREFIX}:recent_events"
        recent_events = frappe.cache().get_value(cache_key) or []

        event = {
            "timestamp": str(now_datetime()),
            "erpnext_doctype": erpnext_doctype,
            "erpnext_name": erpnext_name,
            "trade_hub_doctype": trade_hub_doctype,
            "trade_hub_name": trade_hub_name,
            "event_type": event_type,
            "status": status,
            "error": error,
        }

        recent_events.insert(0, event)
        # Keep only last 100 events
        recent_events = recent_events[:100]

        frappe.cache().set_value(cache_key, recent_events, expires_in_sec=3600)

    except Exception:
        # Don't fail webhook processing due to logging errors
        pass


# =============================================================================
# SUPPLIER -> SELLER PROFILE WEBHOOK
# =============================================================================


def on_supplier_update(doc: Document, method: str) -> None:
    """
    Webhook handler for Supplier updates.

    Called when a Supplier document is saved in ERPNext.
    Updates the linked Seller Profile in Trade Hub if exists.

    Args:
        doc: The Supplier document.
        method: The Frappe hook method (on_update, after_save, etc.).
    """
    if not should_process_reverse_sync(doc, "sync_sellers"):
        return

    try:
        set_sync_in_progress(True)

        # Find linked Seller Profile
        seller_name = frappe.db.get_value(
            "Seller Profile",
            {"erpnext_supplier": doc.name},
            "name"
        )

        if not seller_name:
            # Try to find by tax_id
            if doc.tax_id:
                seller_name = frappe.db.get_value(
                    "Seller Profile",
                    {"tax_id": doc.tax_id},
                    "name"
                )

        if not seller_name:
            # No linked seller found
            return

        # Import sync function and perform reverse sync
        from tr_tradehub.utils.erpnext_sync import sync_supplier_to_seller
        result = sync_supplier_to_seller(doc.name, seller_name, ignore_permissions=True)

        if result:
            log_webhook_event(
                "Supplier", doc.name,
                "Seller Profile", seller_name,
                "reverse_sync", "success"
            )

    except Exception as e:
        log_webhook_event(
            "Supplier", doc.name,
            "Seller Profile", seller_name or "unknown",
            "reverse_sync", "failed", str(e)
        )
    finally:
        set_sync_in_progress(False)


def on_supplier_delete(doc: Document, method: str) -> None:
    """
    Webhook handler for Supplier deletion.

    Called when a Supplier document is deleted in ERPNext.
    Clears the ERPNext link in the associated Seller Profile.

    Args:
        doc: The Supplier document being deleted.
        method: The Frappe hook method (on_trash, after_delete).
    """
    if not should_process_reverse_sync(doc, "sync_sellers"):
        return

    try:
        # Find linked Seller Profile
        seller_name = frappe.db.get_value(
            "Seller Profile",
            {"erpnext_supplier": doc.name},
            "name"
        )

        if seller_name:
            # Clear the ERPNext link
            frappe.db.set_value(
                "Seller Profile",
                seller_name,
                "erpnext_supplier",
                None,
                update_modified=False
            )

            log_webhook_event(
                "Supplier", doc.name,
                "Seller Profile", seller_name,
                "unlink", "success"
            )

    except Exception as e:
        log_webhook_event(
            "Supplier", doc.name,
            "Seller Profile", "unknown",
            "unlink", "failed", str(e)
        )


# =============================================================================
# CUSTOMER -> BUYER PROFILE WEBHOOK
# =============================================================================


def on_customer_update(doc: Document, method: str) -> None:
    """
    Webhook handler for Customer updates.

    Called when a Customer document is saved in ERPNext.
    Updates the linked Buyer Profile in Trade Hub if exists.

    Args:
        doc: The Customer document.
        method: The Frappe hook method (on_update, after_save, etc.).
    """
    if not should_process_reverse_sync(doc, "sync_buyers"):
        return

    try:
        set_sync_in_progress(True)

        # Find linked Buyer Profile
        buyer_name = frappe.db.get_value(
            "Buyer Profile",
            {"erpnext_customer": doc.name},
            "name"
        )

        if not buyer_name:
            # Try to find by tax_id
            if doc.tax_id:
                buyer_name = frappe.db.get_value(
                    "Buyer Profile",
                    {"tax_id": doc.tax_id},
                    "name"
                )

        if not buyer_name:
            # No linked buyer found
            return

        # Import sync function and perform reverse sync
        from tr_tradehub.utils.erpnext_sync import sync_customer_to_buyer
        result = sync_customer_to_buyer(doc.name, buyer_name, ignore_permissions=True)

        if result:
            log_webhook_event(
                "Customer", doc.name,
                "Buyer Profile", buyer_name,
                "reverse_sync", "success"
            )

    except Exception as e:
        log_webhook_event(
            "Customer", doc.name,
            "Buyer Profile", buyer_name or "unknown",
            "reverse_sync", "failed", str(e)
        )
    finally:
        set_sync_in_progress(False)


def on_customer_delete(doc: Document, method: str) -> None:
    """
    Webhook handler for Customer deletion.

    Called when a Customer document is deleted in ERPNext.
    Clears the ERPNext link in the associated Buyer Profile.

    Args:
        doc: The Customer document being deleted.
        method: The Frappe hook method (on_trash, after_delete).
    """
    if not should_process_reverse_sync(doc, "sync_buyers"):
        return

    try:
        # Find linked Buyer Profile
        buyer_name = frappe.db.get_value(
            "Buyer Profile",
            {"erpnext_customer": doc.name},
            "name"
        )

        if buyer_name:
            # Clear the ERPNext link
            frappe.db.set_value(
                "Buyer Profile",
                buyer_name,
                "erpnext_customer",
                None,
                update_modified=False
            )

            log_webhook_event(
                "Customer", doc.name,
                "Buyer Profile", buyer_name,
                "unlink", "success"
            )

    except Exception as e:
        log_webhook_event(
            "Customer", doc.name,
            "Buyer Profile", "unknown",
            "unlink", "failed", str(e)
        )


# =============================================================================
# ITEM -> SKU PRODUCT WEBHOOK
# =============================================================================


def on_item_update(doc: Document, method: str) -> None:
    """
    Webhook handler for Item updates.

    Called when an Item document is saved in ERPNext.
    Updates the linked SKU Product in Trade Hub if exists.

    Args:
        doc: The Item document.
        method: The Frappe hook method (on_update, after_save, etc.).
    """
    if not should_process_reverse_sync(doc, "sync_products"):
        return

    try:
        set_sync_in_progress(True)

        # Find linked SKU Product
        sku_name = frappe.db.get_value(
            "SKU Product",
            {"erpnext_item_code": doc.item_code},
            "name"
        )

        if not sku_name:
            # Try to find by sku_code matching item_code
            sku_name = frappe.db.get_value(
                "SKU Product",
                {"sku_code": doc.item_code},
                "name"
            )

        if not sku_name:
            # No linked SKU found
            return

        # Import sync function and perform reverse sync
        from tr_tradehub.utils.erpnext_sync import sync_item_to_sku
        result = sync_item_to_sku(doc.item_code, sku_name, ignore_permissions=True)

        if result:
            log_webhook_event(
                "Item", doc.item_code,
                "SKU Product", sku_name,
                "reverse_sync", "success"
            )

    except Exception as e:
        log_webhook_event(
            "Item", doc.item_code,
            "SKU Product", sku_name or "unknown",
            "reverse_sync", "failed", str(e)
        )
    finally:
        set_sync_in_progress(False)


def on_item_delete(doc: Document, method: str) -> None:
    """
    Webhook handler for Item deletion.

    Called when an Item document is deleted in ERPNext.
    Clears the ERPNext link in the associated SKU Product.

    Args:
        doc: The Item document being deleted.
        method: The Frappe hook method (on_trash, after_delete).
    """
    if not should_process_reverse_sync(doc, "sync_products"):
        return

    try:
        # Find linked SKU Product
        sku_name = frappe.db.get_value(
            "SKU Product",
            {"erpnext_item_code": doc.item_code},
            "name"
        )

        if sku_name:
            # Clear the ERPNext link
            frappe.db.set_value(
                "SKU Product",
                sku_name,
                "erpnext_item_code",
                None,
                update_modified=False
            )

            log_webhook_event(
                "Item", doc.item_code,
                "SKU Product", sku_name,
                "unlink", "success"
            )

    except Exception as e:
        log_webhook_event(
            "Item", doc.item_code,
            "SKU Product", "unknown",
            "unlink", "failed", str(e)
        )


# =============================================================================
# SALES ORDER -> ORDER WEBHOOK
# =============================================================================


def on_sales_order_update(doc: Document, method: str) -> None:
    """
    Webhook handler for Sales Order updates.

    Called when a Sales Order document is saved in ERPNext.
    Updates the linked Order in Trade Hub if exists.

    Args:
        doc: The Sales Order document.
        method: The Frappe hook method (on_update, after_save, etc.).
    """
    if not should_process_reverse_sync(doc, "sync_orders"):
        return

    try:
        set_sync_in_progress(True)

        # Find linked Order
        order_name = frappe.db.get_value(
            "Order",
            {"linked_sales_order": doc.name},
            "name"
        )

        if not order_name:
            # Try to find by PO reference
            if doc.po_no:
                order_name = frappe.db.get_value(
                    "Order",
                    {"name": doc.po_no},
                    "name"
                )

        if not order_name:
            # No linked order found
            return

        # Import sync function and perform reverse sync
        from tr_tradehub.utils.erpnext_sync import sync_sales_order_to_order
        result = sync_sales_order_to_order(doc.name, order_name, ignore_permissions=True)

        if result:
            log_webhook_event(
                "Sales Order", doc.name,
                "Order", order_name,
                "reverse_sync", "success"
            )

    except Exception as e:
        log_webhook_event(
            "Sales Order", doc.name,
            "Order", order_name or "unknown",
            "reverse_sync", "failed", str(e)
        )
    finally:
        set_sync_in_progress(False)


def on_sales_order_submit(doc: Document, method: str) -> None:
    """
    Webhook handler for Sales Order submission.

    Called when a Sales Order is submitted in ERPNext.
    Updates the linked Order status in Trade Hub.

    Args:
        doc: The Sales Order document.
        method: The Frappe hook method (on_submit).
    """
    if not should_process_reverse_sync(doc, "sync_orders"):
        return

    try:
        set_sync_in_progress(True)

        # Find linked Order
        order_name = frappe.db.get_value(
            "Order",
            {"linked_sales_order": doc.name},
            "name"
        )

        if not order_name and doc.po_no:
            order_name = frappe.db.get_value(
                "Order",
                {"name": doc.po_no},
                "name"
            )

        if not order_name:
            return

        # Update Trade Hub Order status to Confirmed
        order = frappe.get_doc("Order", order_name)
        if order.status == "Draft":
            order.status = "Confirmed"
            order.save(ignore_permissions=True)

            log_webhook_event(
                "Sales Order", doc.name,
                "Order", order_name,
                "submit_sync", "success"
            )

    except Exception as e:
        log_webhook_event(
            "Sales Order", doc.name,
            "Order", order_name or "unknown",
            "submit_sync", "failed", str(e)
        )
    finally:
        set_sync_in_progress(False)


def on_sales_order_cancel(doc: Document, method: str) -> None:
    """
    Webhook handler for Sales Order cancellation.

    Called when a Sales Order is cancelled in ERPNext.
    Updates the linked Order status in Trade Hub.

    Args:
        doc: The Sales Order document.
        method: The Frappe hook method (on_cancel).
    """
    if not should_process_reverse_sync(doc, "sync_orders"):
        return

    try:
        set_sync_in_progress(True)

        # Find linked Order
        order_name = frappe.db.get_value(
            "Order",
            {"linked_sales_order": doc.name},
            "name"
        )

        if not order_name and doc.po_no:
            order_name = frappe.db.get_value(
                "Order",
                {"name": doc.po_no},
                "name"
            )

        if not order_name:
            return

        # Update Trade Hub Order status to Cancelled
        order = frappe.get_doc("Order", order_name)
        if order.status not in ["Completed", "Refunded"]:
            order.status = "Cancelled"
            order.cancellation_reason = f"Cancelled in ERPNext (Sales Order: {doc.name})"
            order.save(ignore_permissions=True)

            log_webhook_event(
                "Sales Order", doc.name,
                "Order", order_name,
                "cancel_sync", "success"
            )

    except Exception as e:
        log_webhook_event(
            "Sales Order", doc.name,
            "Order", order_name or "unknown",
            "cancel_sync", "failed", str(e)
        )
    finally:
        set_sync_in_progress(False)


# =============================================================================
# STOCK ENTRY -> INVENTORY UPDATE WEBHOOK
# =============================================================================


def on_stock_entry_submit(doc: Document, method: str) -> None:
    """
    Webhook handler for Stock Entry submission.

    Called when a Stock Entry is submitted in ERPNext.
    Updates inventory quantities for linked SKU Products.

    Args:
        doc: The Stock Entry document.
        method: The Frappe hook method (on_submit).
    """
    if not should_process_reverse_sync(doc, "sync_products"):
        return

    try:
        set_sync_in_progress(True)

        # Process each item in the stock entry
        for item in doc.items:
            sku_name = frappe.db.get_value(
                "SKU Product",
                {"erpnext_item_code": item.item_code},
                "name"
            )

            if not sku_name:
                continue

            # Get current stock from ERPNext
            from frappe.stock.utils import get_stock_balance
            stock_qty = get_stock_balance(item.item_code, item.t_warehouse or item.s_warehouse)

            # Update SKU Product stock quantity
            frappe.db.set_value(
                "SKU Product",
                sku_name,
                "stock_quantity",
                flt(stock_qty),
                update_modified=False
            )

            log_webhook_event(
                "Stock Entry", doc.name,
                "SKU Product", sku_name,
                "stock_update", "success"
            )

    except Exception as e:
        log_webhook_event(
            "Stock Entry", doc.name,
            "SKU Product", "multiple",
            "stock_update", "failed", str(e)
        )
    finally:
        set_sync_in_progress(False)


def on_stock_entry_cancel(doc: Document, method: str) -> None:
    """
    Webhook handler for Stock Entry cancellation.

    Called when a Stock Entry is cancelled in ERPNext.
    Reverses inventory updates for linked SKU Products.

    Args:
        doc: The Stock Entry document.
        method: The Frappe hook method (on_cancel).
    """
    # Same logic as submit - just recalculate stock
    on_stock_entry_submit(doc, method)


# =============================================================================
# PURCHASE INVOICE -> PAYMENT STATUS WEBHOOK
# =============================================================================


def on_purchase_invoice_submit(doc: Document, method: str) -> None:
    """
    Webhook handler for Purchase Invoice submission.

    Called when a Purchase Invoice is submitted in ERPNext.
    Can trigger payment status updates for related orders.

    Args:
        doc: The Purchase Invoice document.
        method: The Frappe hook method (on_submit).
    """
    if not should_process_reverse_sync(doc, "sync_orders"):
        return

    # Purchase invoices don't directly link to Trade Hub orders
    # This handler is here for future payment tracking integration
    pass


# =============================================================================
# DELIVERY NOTE -> SHIPMENT WEBHOOK
# =============================================================================


def on_delivery_note_submit(doc: Document, method: str) -> None:
    """
    Webhook handler for Delivery Note submission.

    Called when a Delivery Note is submitted in ERPNext.
    Updates the linked Order status to Shipped in Trade Hub.

    Args:
        doc: The Delivery Note document.
        method: The Frappe hook method (on_submit).
    """
    if not should_process_reverse_sync(doc, "sync_orders"):
        return

    try:
        set_sync_in_progress(True)

        # Find linked Sales Order
        sales_order = None
        for item in doc.items:
            if item.against_sales_order:
                sales_order = item.against_sales_order
                break

        if not sales_order:
            return

        # Find linked Trade Hub Order
        order_name = frappe.db.get_value(
            "Order",
            {"linked_sales_order": sales_order},
            "name"
        )

        if not order_name:
            return

        # Update Trade Hub Order status to Shipped
        order = frappe.get_doc("Order", order_name)
        if order.status in ["Confirmed", "Processing", "Ready to Ship"]:
            order.status = "Shipped"
            order.save(ignore_permissions=True)

            log_webhook_event(
                "Delivery Note", doc.name,
                "Order", order_name,
                "shipment_sync", "success"
            )

    except Exception as e:
        log_webhook_event(
            "Delivery Note", doc.name,
            "Order", "unknown",
            "shipment_sync", "failed", str(e)
        )
    finally:
        set_sync_in_progress(False)


# =============================================================================
# WHITELISTED API ENDPOINTS
# =============================================================================


@frappe.whitelist()
def get_recent_webhook_events(limit: int = 50) -> list:
    """
    Get recent webhook sync events.

    Args:
        limit: Maximum number of events to return.

    Returns:
        list: Recent webhook events with metadata.
    """
    frappe.only_for("System Manager")

    cache_key = f"{WEBHOOK_CACHE_PREFIX}:recent_events"
    events = frappe.cache().get_value(cache_key) or []

    return events[:cint(limit)]


@frappe.whitelist()
def clear_webhook_event_log() -> dict:
    """
    Clear the webhook event log cache.

    Returns:
        dict: Success status.
    """
    frappe.only_for("System Manager")

    cache_key = f"{WEBHOOK_CACHE_PREFIX}:recent_events"
    frappe.cache().delete_value(cache_key)

    return {"success": True, "message": "Webhook event log cleared"}


@frappe.whitelist()
def test_webhook_connection(doctype: str, docname: str) -> dict:
    """
    Test webhook connection for a specific document.

    Args:
        doctype: The ERPNext DocType to test.
        docname: The document name to test.

    Returns:
        dict: Test result with status and details.
    """
    frappe.only_for("System Manager")

    if not is_erpnext_sync_enabled():
        return {
            "success": False,
            "error": "ERPNext sync is not available"
        }

    if not frappe.db.exists(doctype, docname):
        return {
            "success": False,
            "error": f"Document {doctype}/{docname} not found"
        }

    # Map ERPNext DocTypes to Trade Hub DocTypes
    doctype_map = {
        "Supplier": ("Seller Profile", "erpnext_supplier"),
        "Customer": ("Buyer Profile", "erpnext_customer"),
        "Item": ("SKU Product", "erpnext_item_code"),
        "Sales Order": ("Order", "linked_sales_order"),
    }

    if doctype not in doctype_map:
        return {
            "success": False,
            "error": f"DocType {doctype} is not supported for webhook testing"
        }

    trade_hub_doctype, link_field = doctype_map[doctype]

    # Find linked Trade Hub document
    linked_doc = frappe.db.get_value(
        trade_hub_doctype,
        {link_field: docname},
        "name"
    )

    return {
        "success": True,
        "erpnext_doctype": doctype,
        "erpnext_docname": docname,
        "trade_hub_doctype": trade_hub_doctype,
        "linked_document": linked_doc,
        "is_linked": bool(linked_doc),
        "sync_enabled": is_erpnext_sync_enabled(),
    }


@frappe.whitelist()
def trigger_manual_reverse_sync(doctype: str, docname: str) -> dict:
    """
    Manually trigger reverse sync for a document.

    Args:
        doctype: The ERPNext DocType.
        docname: The document name.

    Returns:
        dict: Sync result.
    """
    frappe.only_for("System Manager")

    if not is_erpnext_sync_enabled():
        return {"success": False, "error": "ERPNext sync is not available"}

    handler_map = {
        "Supplier": on_supplier_update,
        "Customer": on_customer_update,
        "Item": on_item_update,
        "Sales Order": on_sales_order_update,
    }

    if doctype not in handler_map:
        return {"success": False, "error": f"DocType {doctype} is not supported"}

    try:
        doc = frappe.get_doc(doctype, docname)
        handler_map[doctype](doc, "manual_sync")
        return {
            "success": True,
            "message": f"Reverse sync triggered for {doctype}/{docname}"
        }
    except Exception as e:
        return {"success": False, "error": str(e)}

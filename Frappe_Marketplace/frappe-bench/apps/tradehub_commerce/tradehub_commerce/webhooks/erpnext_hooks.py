"""ERPNext Webhook Handlers for TradeHub Commerce

This module handles reverse synchronization from ERPNext back to TradeHub.
When documents are created/updated/submitted in ERPNext, these handlers
sync the changes back to the corresponding TradeHub DocTypes.

Events handled:
- Sales Order: Syncs order status and details back to Marketplace Order
- Stock Entry: Updates inventory levels in TradeHub
- Delivery Note: Updates shipment tracking and delivery status
"""

import frappe
from frappe import _


def on_sales_order_update(doc, method):
    """Handle Sales Order update events from ERPNext.

    Syncs Sales Order changes back to the corresponding Marketplace Order
    in TradeHub Commerce when the Sales Order is updated.

    Args:
        doc: The ERPNext Sales Order document
        method: The event method name (on_update)
    """
    # Check if this Sales Order is linked to a TradeHub Marketplace Order
    marketplace_order_id = doc.get("custom_marketplace_order_id")
    if not marketplace_order_id:
        return

    # Check if Marketplace Order DocType exists
    if not frappe.db.exists("Marketplace Order", marketplace_order_id):
        frappe.log_error(
            f"Marketplace Order {marketplace_order_id} not found for Sales Order {doc.name}",
            "ERPNext Sync Error"
        )
        return

    try:
        # Update the Marketplace Order with changes from Sales Order
        marketplace_order = frappe.get_doc("Marketplace Order", marketplace_order_id)

        # Sync relevant fields
        if doc.status:
            marketplace_order.erpnext_status = doc.status

        if doc.grand_total:
            marketplace_order.erpnext_grand_total = doc.grand_total

        marketplace_order.erpnext_sales_order = doc.name
        marketplace_order.last_erpnext_sync = frappe.utils.now()

        marketplace_order.flags.ignore_validate = True
        marketplace_order.save()

        frappe.logger().info(
            f"Synced Sales Order {doc.name} to Marketplace Order {marketplace_order_id}"
        )

    except Exception as e:
        frappe.log_error(
            f"Failed to sync Sales Order {doc.name}: {str(e)}",
            "ERPNext Sync Error"
        )


def on_sales_order_submit(doc, method):
    """Handle Sales Order submit events from ERPNext.

    When a Sales Order is submitted in ERPNext, this updates the
    corresponding Marketplace Order to reflect the confirmed status.

    Args:
        doc: The ERPNext Sales Order document
        method: The event method name (on_submit)
    """
    marketplace_order_id = doc.get("custom_marketplace_order_id")
    if not marketplace_order_id:
        return

    if not frappe.db.exists("Marketplace Order", marketplace_order_id):
        return

    try:
        marketplace_order = frappe.get_doc("Marketplace Order", marketplace_order_id)

        # Mark as confirmed in ERPNext
        marketplace_order.erpnext_status = "Submitted"
        marketplace_order.erpnext_submitted_at = frappe.utils.now()
        marketplace_order.erpnext_sales_order = doc.name
        marketplace_order.last_erpnext_sync = frappe.utils.now()

        marketplace_order.flags.ignore_validate = True
        marketplace_order.save()

        # Create an Order Event to track this status change
        if frappe.db.exists("DocType", "Order Event"):
            order_event = frappe.new_doc("Order Event")
            order_event.order = marketplace_order.order if hasattr(marketplace_order, 'order') else None
            order_event.marketplace_order = marketplace_order_id
            order_event.event_type = "ERPNext Submission"
            order_event.event_data = {
                "sales_order": doc.name,
                "status": "Submitted"
            }
            order_event.flags.ignore_validate = True
            order_event.insert()

        frappe.logger().info(
            f"Sales Order {doc.name} submitted - Marketplace Order {marketplace_order_id} updated"
        )

    except Exception as e:
        frappe.log_error(
            f"Failed to sync submitted Sales Order {doc.name}: {str(e)}",
            "ERPNext Sync Error"
        )


def on_stock_entry_submit(doc, method):
    """Handle Stock Entry submit events from ERPNext.

    When a Stock Entry is submitted in ERPNext (e.g., Material Receipt,
    Material Issue), this updates the relevant inventory records in TradeHub.

    Args:
        doc: The ERPNext Stock Entry document
        method: The event method name (on_submit)
    """
    # Check if this Stock Entry is linked to TradeHub
    marketplace_reference = doc.get("custom_marketplace_reference")
    if not marketplace_reference:
        return

    try:
        # Process each item in the Stock Entry
        for item in doc.items:
            # Check if this item is linked to a TradeHub SKU
            sku_code = item.get("custom_tradehub_sku")
            if not sku_code:
                continue

            if not frappe.db.exists("SKU", sku_code):
                continue

            sku_doc = frappe.get_doc("SKU", sku_code)

            # Update stock levels based on Stock Entry type
            if doc.stock_entry_type == "Material Receipt":
                # Increase stock
                if hasattr(sku_doc, 'available_qty'):
                    sku_doc.available_qty = (sku_doc.available_qty or 0) + item.qty
            elif doc.stock_entry_type == "Material Issue":
                # Decrease stock
                if hasattr(sku_doc, 'available_qty'):
                    sku_doc.available_qty = max(0, (sku_doc.available_qty or 0) - item.qty)

            sku_doc.last_erpnext_sync = frappe.utils.now()
            sku_doc.flags.ignore_validate = True
            sku_doc.save()

            frappe.logger().info(
                f"SKU {sku_code} inventory updated from Stock Entry {doc.name}"
            )

    except Exception as e:
        frappe.log_error(
            f"Failed to sync Stock Entry {doc.name}: {str(e)}",
            "ERPNext Sync Error"
        )


def on_delivery_note_submit(doc, method):
    """Handle Delivery Note submit events from ERPNext.

    When a Delivery Note is submitted in ERPNext, this updates the
    corresponding Shipment and Order status in TradeHub.

    Args:
        doc: The ERPNext Delivery Note document
        method: The event method name (on_submit)
    """
    # Check if linked to a TradeHub Shipment
    shipment_id = doc.get("custom_tradehub_shipment_id")
    order_id = doc.get("custom_marketplace_order_id")

    # Update Shipment if linked
    if shipment_id and frappe.db.exists("Marketplace Shipment", shipment_id):
        try:
            shipment = frappe.get_doc("Marketplace Shipment", shipment_id)

            # Update shipment status
            shipment.erpnext_delivery_note = doc.name
            shipment.erpnext_status = "Delivered"
            shipment.last_erpnext_sync = frappe.utils.now()

            # Create a tracking event
            if frappe.db.exists("DocType", "Tracking Event"):
                tracking_event = frappe.new_doc("Tracking Event")
                tracking_event.shipment = shipment_id
                tracking_event.event_type = "Delivered"
                tracking_event.event_time = frappe.utils.now()
                tracking_event.description = f"Delivery Note {doc.name} submitted in ERPNext"
                tracking_event.source = "ERPNext"
                tracking_event.flags.ignore_validate = True
                tracking_event.insert()

            shipment.flags.ignore_validate = True
            shipment.save()

            frappe.logger().info(
                f"Shipment {shipment_id} updated from Delivery Note {doc.name}"
            )

        except Exception as e:
            frappe.log_error(
                f"Failed to sync Delivery Note {doc.name} to Shipment: {str(e)}",
                "ERPNext Sync Error"
            )

    # Update Marketplace Order if linked
    if order_id and frappe.db.exists("Marketplace Order", order_id):
        try:
            marketplace_order = frappe.get_doc("Marketplace Order", order_id)

            # Update delivery status
            marketplace_order.erpnext_delivery_note = doc.name
            marketplace_order.delivery_status = "Delivered"
            marketplace_order.last_erpnext_sync = frappe.utils.now()

            marketplace_order.flags.ignore_validate = True
            marketplace_order.save()

            frappe.logger().info(
                f"Marketplace Order {order_id} updated from Delivery Note {doc.name}"
            )

        except Exception as e:
            frappe.log_error(
                f"Failed to sync Delivery Note {doc.name} to Marketplace Order: {str(e)}",
                "ERPNext Sync Error"
            )

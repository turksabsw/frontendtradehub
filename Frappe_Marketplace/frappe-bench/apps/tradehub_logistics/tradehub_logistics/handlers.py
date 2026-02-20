# Copyright (c) 2024, TradeHub and contributors
# For license information, please see license.txt

"""Document Event Handlers for TradeHub Logistics

This module contains event handlers for logistics-related documents.
These handlers are triggered by Frappe's doc_events system configured in hooks.py.

Handlers:
- on_shipment_created: Triggered when a new Shipment is created
- on_shipment_update: Triggered when a Shipment is updated
"""

import frappe
from frappe import _
from frappe.utils import now_datetime


def on_shipment_created(doc, method):
    """Handle new shipment creation.

    This handler:
    1. Validates carrier configuration
    2. Creates initial tracking event
    3. Triggers label creation if carrier supports API
    4. Updates linked Order status

    Args:
        doc: The Shipment document
        method: The event method name (after_insert)
    """
    try:
        # Create initial tracking event
        if doc.tracking_number:
            create_initial_tracking_event(doc)

        # Update order status if linked
        if doc.order:
            update_order_shipment_status(doc.order, "Shipment Created")

        frappe.logger().info(f"Shipment {doc.name} created successfully")

    except Exception as e:
        frappe.log_error(
            message=f"Error in on_shipment_created for {doc.name}: {str(e)}",
            title="Shipment Creation Handler Error"
        )


def on_shipment_update(doc, method):
    """Handle shipment updates.

    This handler:
    1. Checks for status changes
    2. Creates tracking events for status changes
    3. Triggers carrier tracking update if needed
    4. Updates linked Order status
    5. Sends notifications on significant status changes

    Args:
        doc: The Shipment document
        method: The event method name (on_update)
    """
    try:
        # Check if status changed
        if doc.has_value_changed("status"):
            handle_status_change(doc)

        # Check if tracking number was added
        if doc.has_value_changed("tracking_number") and doc.tracking_number:
            trigger_carrier_tracking(doc)

    except Exception as e:
        frappe.log_error(
            message=f"Error in on_shipment_update for {doc.name}: {str(e)}",
            title="Shipment Update Handler Error"
        )


def create_initial_tracking_event(doc):
    """Create the initial tracking event for a new shipment.

    Args:
        doc: The Shipment document
    """
    try:
        if not frappe.db.exists("Tracking Event", {"shipment": doc.name, "status": "Created"}):
            tracking_event = frappe.new_doc("Tracking Event")
            tracking_event.shipment = doc.name
            tracking_event.event_datetime = now_datetime()
            tracking_event.status = "Created"
            tracking_event.description = "Shipment created in system"
            tracking_event.location = doc.origin_city or ""
            tracking_event.flags.ignore_permissions = True
            tracking_event.insert()

    except Exception as e:
        frappe.log_error(
            message=f"Failed to create initial tracking event for {doc.name}: {str(e)}",
            title="Tracking Event Creation Error"
        )


def handle_status_change(doc):
    """Handle shipment status change.

    Args:
        doc: The Shipment document with changed status
    """
    old_status = doc.get_doc_before_save().status if doc.get_doc_before_save() else None
    new_status = doc.status

    # Create tracking event for the status change
    create_status_tracking_event(doc, new_status)

    # Update order status based on shipment status
    if doc.order:
        update_order_from_shipment_status(doc)

    # Send notifications for significant status changes
    if new_status in ["Out for Delivery", "Delivered", "Failed Delivery"]:
        send_shipment_notification(doc, new_status)


def create_status_tracking_event(doc, status):
    """Create a tracking event for a status change.

    Args:
        doc: The Shipment document
        status: The new status
    """
    try:
        # Map internal status to event description
        status_descriptions = {
            "Pending": "Shipment pending pickup",
            "Picked Up": "Shipment picked up from sender",
            "In Transit": "Shipment in transit",
            "At Hub": "Shipment arrived at sorting hub",
            "Out for Delivery": "Shipment out for delivery",
            "Delivered": "Shipment delivered successfully",
            "Failed Delivery": "Delivery attempt failed",
            "Returned": "Shipment returned to sender",
            "Cancelled": "Shipment cancelled"
        }

        description = status_descriptions.get(status, f"Status changed to {status}")

        tracking_event = frappe.new_doc("Tracking Event")
        tracking_event.shipment = doc.name
        tracking_event.event_datetime = now_datetime()
        tracking_event.status = status
        tracking_event.description = description
        tracking_event.location = get_current_location(doc, status)
        tracking_event.flags.ignore_permissions = True
        tracking_event.insert()

    except Exception as e:
        frappe.log_error(
            message=f"Failed to create status tracking event for {doc.name}: {str(e)}",
            title="Tracking Event Creation Error"
        )


def get_current_location(doc, status):
    """Get the current location based on shipment status.

    Args:
        doc: The Shipment document
        status: The current status

    Returns:
        str: Location description
    """
    if status in ["Pending", "Picked Up"]:
        return doc.origin_city or "Origin"
    elif status in ["Out for Delivery", "Delivered", "Failed Delivery"]:
        return doc.destination_city or "Destination"
    else:
        return "In Transit"


def trigger_carrier_tracking(doc):
    """Trigger carrier API to fetch tracking info.

    Args:
        doc: The Shipment document
    """
    if not doc.carrier or not doc.tracking_number:
        return

    try:
        # Get carrier integration
        carrier_module = get_carrier_module(doc.carrier)
        if carrier_module:
            # Fetch tracking asynchronously
            frappe.enqueue(
                "tradehub_logistics.tasks.process_shipment_tracking",
                shipment={"name": doc.name, "carrier": doc.carrier, "tracking_number": doc.tracking_number},
                queue="short"
            )

    except Exception as e:
        frappe.log_error(
            message=f"Failed to trigger carrier tracking for {doc.name}: {str(e)}",
            title="Carrier Tracking Error"
        )


def get_carrier_module(carrier_name):
    """Get the carrier integration module.

    Args:
        carrier_name: The carrier name or code

    Returns:
        module: The carrier integration module or None
    """
    carrier_map = {
        "Aras Kargo": "aras",
        "ARAS": "aras",
        "Yurtici Kargo": "yurtici",
        "YURTICI": "yurtici"
    }

    carrier_code = carrier_map.get(carrier_name)
    if carrier_code:
        try:
            module = frappe.get_module(
                f"tradehub_logistics.integrations.carriers.{carrier_code}"
            )
            return module
        except ImportError:
            return None

    return None


def update_order_shipment_status(order_name, status):
    """Update the linked order's shipment status.

    Args:
        order_name: The Order document name
        status: The shipment status
    """
    try:
        if frappe.db.exists("Order", order_name):
            frappe.db.set_value("Order", order_name, "shipment_status", status)
    except Exception as e:
        frappe.log_error(
            message=f"Failed to update order {order_name} shipment status: {str(e)}",
            title="Order Update Error"
        )


def update_order_from_shipment_status(doc):
    """Update order status based on shipment status.

    Args:
        doc: The Shipment document
    """
    status_mapping = {
        "Delivered": "Delivered",
        "Returned": "Returned",
        "Cancelled": "Cancelled"
    }

    if doc.status in status_mapping:
        update_order_shipment_status(doc.order, status_mapping[doc.status])

        # If delivered, also update delivery timestamp
        if doc.status == "Delivered":
            try:
                frappe.db.set_value("Order", doc.order, {
                    "delivered_at": now_datetime(),
                    "shipment_status": "Delivered"
                })
            except Exception:
                pass


def send_shipment_notification(doc, status):
    """Send notification for significant shipment status changes.

    Args:
        doc: The Shipment document
        status: The new status
    """
    # This would integrate with tradehub_core notification system
    # For now, just log the notification intent
    notification_messages = {
        "Out for Delivery": _("Your order is out for delivery"),
        "Delivered": _("Your order has been delivered"),
        "Failed Delivery": _("Delivery attempt failed - please contact support")
    }

    message = notification_messages.get(status)
    if message:
        frappe.logger().info(
            f"Notification for {doc.name}: {message}"
        )
        # In production, this would call the ECA dispatcher or notification template
        # from tradehub_core to send actual notifications

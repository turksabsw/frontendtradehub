"""
Scheduled tasks for TradeHub Logistics

This module contains scheduled tasks for the logistics layer.
Tasks are registered in hooks.py scheduler_events configuration.

Tasks:
- shipment_tracking: Hourly task to fetch tracking updates from carriers
"""

import frappe
from frappe.utils import nowdate, now_datetime, add_days, getdate


def shipment_tracking():
    """
    Hourly scheduled task to fetch and update shipment tracking information.

    This task:
    1. Finds all active shipments that need tracking updates
    2. Queries each carrier's API for tracking information
    3. Creates Tracking Event records for status changes
    4. Updates Shipment status based on latest tracking
    5. Sends notifications for delivery status changes

    Business Rules:
    - Only track shipments in transit (not delivered/cancelled)
    - Respect carrier API rate limits
    - Create Tracking Event for each status change
    - Notify buyer/seller on significant status changes
    """
    frappe.logger().info("Running shipment_tracking scheduled task")

    try:
        # Get active shipments that need tracking
        active_shipments = get_active_shipments()

        for shipment in active_shipments:
            try:
                process_shipment_tracking(shipment)
            except Exception as e:
                frappe.log_error(
                    message=f"Failed to track shipment {shipment.name}: {str(e)}",
                    title="Shipment Tracking Error"
                )
                continue

        frappe.logger().info(f"Completed shipment_tracking: processed {len(active_shipments)} shipments")

    except Exception as e:
        frappe.log_error(
            message=str(e),
            title="Shipment Tracking Task Failed"
        )


def get_active_shipments():
    """
    Get shipments that are in transit and need tracking updates.

    Criteria:
    - Shipment status is 'In Transit' or 'Out for Delivery'
    - Has a tracking number
    - Has a carrier assigned
    - Last tracking update was more than 1 hour ago
    """
    # In real implementation, this would query the Shipment DocType
    # For now, return empty list as DocTypes will be created in subtask-6-2
    return []


def process_shipment_tracking(shipment):
    """
    Process tracking update for a single shipment.

    Steps:
    1. Get carrier integration for this shipment
    2. Query carrier API for tracking info
    3. Parse tracking response
    4. Create Tracking Event records for new statuses
    5. Update Shipment status if needed
    6. Send notifications for significant changes
    """
    carrier = get_carrier_integration(shipment.get("carrier"))
    if not carrier:
        return

    # Fetch tracking from carrier API
    tracking_info = fetch_tracking_from_carrier(
        carrier=carrier,
        tracking_number=shipment.get("tracking_number")
    )

    if not tracking_info:
        return

    # Process tracking events
    for event in tracking_info.get("events", []):
        create_tracking_event(shipment, event)

    # Update shipment status
    latest_status = tracking_info.get("current_status")
    if latest_status:
        update_shipment_status(shipment, latest_status)


def get_carrier_integration(carrier_name):
    """
    Get the carrier integration module for the specified carrier.

    Supported carriers:
    - Aras Kargo
    - Yurtici Kargo
    - MNG Kargo
    - PTT Kargo
    - Surat Kargo
    """
    if not carrier_name:
        return None

    # Map carrier names to integration modules
    carrier_map = {
        "Aras Kargo": "aras",
        "Yurtici Kargo": "yurtici",
        "MNG Kargo": "mng",
        "PTT Kargo": "ptt",
        "Surat Kargo": "surat"
    }

    carrier_module = carrier_map.get(carrier_name)
    if carrier_module:
        try:
            # Dynamic import of carrier integration
            module = frappe.get_module(
                f"tradehub_logistics.integrations.carriers.{carrier_module}"
            )
            return module
        except ImportError:
            return None

    return None


def fetch_tracking_from_carrier(carrier, tracking_number):
    """
    Fetch tracking information from carrier API.

    Returns dict with:
    - current_status: Latest shipment status
    - events: List of tracking events
    - estimated_delivery: Estimated delivery date (if available)
    """
    if not carrier or not tracking_number:
        return None

    # In real implementation, this would call carrier.get_tracking(tracking_number)
    # For now, return None as carrier integrations will be created in subtask-6-3
    return None


def create_tracking_event(shipment, event):
    """
    Create a Tracking Event record for a shipment status update.

    Event data includes:
    - event_datetime: When the event occurred
    - status: Status code/description
    - location: Where the event occurred
    - description: Detailed event description
    """
    event_datetime = event.get("datetime")
    status = event.get("status")

    # Check if this event already exists to avoid duplicates
    existing = frappe.db.exists(
        "Tracking Event",
        {
            "shipment": shipment.get("name"),
            "event_datetime": event_datetime,
            "status": status
        }
    )

    if existing:
        return

    # Create new tracking event
    # In real implementation, this would create Tracking Event DocType
    # For now, just log it
    frappe.logger().info(
        f"Tracking event for {shipment.get('name')}: {status} at {event_datetime}"
    )


def update_shipment_status(shipment, new_status):
    """
    Update shipment status based on carrier tracking.

    Status mapping:
    - picked_up -> In Transit
    - in_transit -> In Transit
    - out_for_delivery -> Out for Delivery
    - delivered -> Delivered
    - returned -> Returned
    - failed_delivery -> Failed Delivery
    """
    status_map = {
        "picked_up": "In Transit",
        "in_transit": "In Transit",
        "out_for_delivery": "Out for Delivery",
        "delivered": "Delivered",
        "returned": "Returned",
        "failed_delivery": "Failed Delivery"
    }

    mapped_status = status_map.get(new_status, new_status)
    current_status = shipment.get("status")

    if mapped_status != current_status:
        # Update shipment status
        frappe.db.set_value("Shipment", shipment.get("name"), "status", mapped_status)

        # If delivered, update delivery timestamp and notify
        if mapped_status == "Delivered":
            frappe.db.set_value("Shipment", shipment.get("name"), "delivered_at", now_datetime())
            notify_delivery_completed(shipment)


def notify_delivery_completed(shipment):
    """
    Send notifications when a shipment is delivered.

    Notifies:
    - Buyer (email + in-app notification)
    - Seller (in-app notification)
    - Updates Order status if all shipments delivered
    """
    # In real implementation, this would:
    # 1. Get buyer email from linked Order
    # 2. Send email notification
    # 3. Create in-app notification for buyer and seller
    # 4. Check if all shipments for order are delivered
    # 5. Update Order status to "Delivered" if complete
    pass


def check_delayed_shipments():
    """
    Check for shipments that are delayed beyond expected delivery.

    Business Rules:
    - Flag shipments past estimated delivery date
    - Notify seller about delayed shipments
    - Escalate to support if delay > 3 days
    """
    cutoff_date = add_days(nowdate(), -3)

    # In real implementation, this would:
    # 1. Query shipments with estimated_delivery < today and status != Delivered
    # 2. Create alerts for delayed shipments
    # 3. Escalate severely delayed shipments
    pass

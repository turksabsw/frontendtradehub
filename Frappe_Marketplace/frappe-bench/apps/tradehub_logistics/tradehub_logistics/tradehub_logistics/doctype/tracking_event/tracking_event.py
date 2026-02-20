# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import (
    cint, flt, getdate, nowdate, now_datetime,
    add_days, get_datetime, date_diff
)
import json


class TrackingEvent(Document):
    """
    Tracking Event DocType for TR-TradeHub.

    Tracks all shipment tracking events from carriers including:
    - Pickup and collection events
    - Transit and facility events
    - Delivery attempts and completions
    - Exceptions and delays
    - Return shipments

    Features:
    - Carrier integration support (Yurtici, Aras, MNG, PTT, UPS, DHL, FedEx)
    - Location tracking with geo coordinates
    - Milestone identification
    - Exception handling
    - Notification tracking
    - Duplicate prevention via sync_id
    """

    def before_insert(self):
        """Set default values before creating a new tracking event."""
        # Set event timestamp if not provided
        if not self.event_timestamp:
            self.event_timestamp = now_datetime()

        # Set synced_at
        if not self.synced_at:
            self.synced_at = now_datetime()

        # Auto-populate from shipment
        self.populate_from_shipment()

        # Set milestone flag based on event type
        self.set_milestone_flag()

        # Set severity based on event type
        self.set_default_severity()

        # Set exception type if is_exception
        self.set_exception_details()

        # Generate sync_id if not provided
        if not self.sync_id:
            self.generate_sync_id()

    def validate(self):
        """Validate tracking event data before saving."""
        self.validate_shipment()
        self.validate_event_type()
        self.validate_location()
        self.validate_json_fields()
        self.validate_duplicate()

    def on_update(self):
        """Actions after tracking event is created/updated."""
        # Update shipment status if needed
        if self.is_new():
            self.update_shipment_status()

        # Send notifications if enabled
        if self.should_send_notification():
            self.queue_notification()

    def after_insert(self):
        """Actions after tracking event is inserted."""
        # Log to order event if linked to order
        self.log_to_order_events()

    # =================================================================
    # Helper Methods
    # =================================================================

    def populate_from_shipment(self):
        """Populate fields from linked shipment."""
        if not self.shipment:
            return

        shipment = frappe.get_doc("Marketplace Shipment", self.shipment)

        # Tracking number
        if not self.tracking_number:
            self.tracking_number = shipment.tracking_number

        # Carrier
        if not self.carrier:
            self.carrier = shipment.carrier

        # Order references
        if not self.sub_order and shipment.sub_order:
            self.sub_order = shipment.sub_order

        if self.sub_order and not self.marketplace_order:
            self.marketplace_order = frappe.db.get_value(
                "Sub Order", self.sub_order, "marketplace_order"
            )

        # Seller
        if not self.seller and shipment.seller:
            self.seller = shipment.seller

        # Get buyer from order
        if not self.buyer and self.marketplace_order:
            self.buyer = frappe.db.get_value(
                "Marketplace Order", self.marketplace_order, "buyer"
            )

        # Tenant
        if not self.tenant and shipment.tenant:
            self.tenant = shipment.tenant

    def set_milestone_flag(self):
        """Set is_milestone based on event type."""
        milestone_events = [
            "Shipment Created",
            "Pickup Completed",
            "Departed Origin Facility",
            "Arrived at Destination City",
            "Out for Delivery",
            "Delivered",
            "Signed For",
            "Returned to Sender",
            "Delivery Exception"
        ]

        if self.event_type in milestone_events:
            self.is_milestone = 1

    def set_default_severity(self):
        """Set severity based on event type."""
        if self.severity and self.severity != "Info":
            return

        critical_events = ["Lost", "Damaged"]
        error_events = [
            "Delivery Exception", "Pickup Failed", "Address Issue",
            "Refused", "Customs Hold", "Package Held"
        ]
        warning_events = [
            "Delivery Attempted", "Recipient Unavailable", "Weather Delay",
            "Holiday Delay", "Return Initiated", "Redirected"
        ]

        if self.event_type in critical_events:
            self.severity = "Critical"
            self.is_exception = 1
        elif self.event_type in error_events or self.is_exception:
            self.severity = "Error"
            self.is_exception = 1
        elif self.event_type in warning_events:
            self.severity = "Warning"
        else:
            self.severity = "Info"

    def set_exception_details(self):
        """Set exception type based on event type."""
        if not self.is_exception:
            return

        if self.exception_type:
            return

        exception_mapping = {
            "Address Issue": "Address Issue",
            "Recipient Unavailable": "Recipient Not Available",
            "Refused": "Refused by Recipient",
            "Damaged": "Package Damaged",
            "Lost": "Package Lost",
            "Customs Hold": "Customs Issue",
            "Weather Delay": "Weather Delay",
            "Delivery Attempted": "Delivery Attempt Failed",
            "Delivery Exception": "Other"
        }

        self.exception_type = exception_mapping.get(self.event_type, "Other")

    def generate_sync_id(self):
        """Generate unique sync_id to prevent duplicates."""
        # Create sync_id from shipment, timestamp, event type, and location
        components = [
            self.shipment or "",
            str(self.event_timestamp) if self.event_timestamp else "",
            self.event_type or "",
            self.city or "",
            self.carrier_event_code or ""
        ]
        sync_string = "|".join(components)
        self.sync_id = frappe.generate_hash(sync_string, length=32)

    # =================================================================
    # Validation Methods
    # =================================================================

    def validate_shipment(self):
        """Validate shipment reference."""
        if not self.shipment:
            frappe.throw(_("Shipment is required"))

        if not frappe.db.exists("Marketplace Shipment", self.shipment):
            frappe.throw(_(
                "Marketplace Shipment {0} does not exist"
            ).format(self.shipment))

    def validate_event_type(self):
        """Validate event type is provided."""
        if not self.event_type:
            frappe.throw(_("Event Type is required"))

    def validate_location(self):
        """Validate location data if provided."""
        if self.latitude:
            if not (-90 <= flt(self.latitude) <= 90):
                frappe.throw(_("Latitude must be between -90 and 90"))

        if self.longitude:
            if not (-180 <= flt(self.longitude) <= 180):
                frappe.throw(_("Longitude must be between -180 and 180"))

    def validate_json_fields(self):
        """Validate JSON fields."""
        if self.raw_event_data:
            try:
                if isinstance(self.raw_event_data, str):
                    json.loads(self.raw_event_data)
            except json.JSONDecodeError:
                frappe.throw(_("Raw Event Data must be valid JSON"))

    def validate_duplicate(self):
        """Validate no duplicate event exists."""
        if self.is_new() and self.sync_id:
            existing = frappe.db.exists(
                "Tracking Event",
                {"sync_id": self.sync_id, "name": ["!=", self.name]}
            )
            if existing:
                frappe.throw(_(
                    "Duplicate tracking event. Event with sync_id {0} already exists."
                ).format(self.sync_id))

    # =================================================================
    # Shipment Update Methods
    # =================================================================

    def update_shipment_status(self):
        """Update parent shipment status based on tracking event."""
        if not self.shipment:
            return

        status_mapping = {
            "Shipment Created": "Pending",
            "Label Printed": "Label Generated",
            "Pickup Scheduled": "Pickup Scheduled",
            "Pickup Completed": "Picked Up",
            "In Transit": "In Transit",
            "Arrived at Facility": "In Transit",
            "Departed Facility": "In Transit",
            "Arrived at Destination City": "In Transit",
            "Arrived at Destination Facility": "In Transit",
            "Out for Delivery": "Out for Delivery",
            "Delivery Attempted": "Failed Delivery",
            "Delivered": "Delivered",
            "Signed For": "Delivered",
            "Left at Door": "Delivered",
            "Delivered to Neighbor": "Delivered",
            "Delivered to Safe Place": "Delivered",
            "Delivered to Pickup Point": "Delivered",
            "Delivered to Locker": "Delivered",
            "Delivery Exception": "Exception",
            "Return Initiated": "Returning",
            "Returning to Sender": "Returning",
            "Returned to Sender": "Returned",
            "Cancelled": "Cancelled"
        }

        new_status = status_mapping.get(self.event_type)
        if not new_status:
            return

        try:
            shipment = frappe.get_doc("Marketplace Shipment", self.shipment)
            current_status = shipment.status

            # Check if status should be updated (avoid going backwards)
            status_order = [
                "Pending", "Label Generated", "Pickup Scheduled",
                "Picked Up", "In Transit", "Out for Delivery",
                "Delivered", "Failed Delivery", "Returning",
                "Returned", "Exception", "Cancelled"
            ]

            current_index = status_order.index(current_status) if current_status in status_order else -1
            new_index = status_order.index(new_status) if new_status in status_order else -1

            # Exception and Failed Delivery can happen at any time
            exception_statuses = ["Exception", "Failed Delivery", "Returning", "Returned", "Cancelled"]

            should_update = (
                new_index > current_index or
                new_status in exception_statuses or
                current_status in ["Pending", "Label Generated"]
            )

            if should_update and current_status != new_status:
                shipment.status = new_status

                # Update timestamps
                if new_status == "Picked Up":
                    shipment.picked_up_at = self.event_timestamp
                elif new_status == "In Transit":
                    if not shipment.in_transit_at:
                        shipment.in_transit_at = self.event_timestamp
                elif new_status == "Out for Delivery":
                    shipment.out_for_delivery_at = self.event_timestamp
                elif new_status == "Delivered":
                    shipment.delivered_at = self.event_timestamp
                    shipment.actual_delivery_date = getdate(self.event_timestamp)
                    shipment.delivery_status = "Delivered"
                    if self.signed_by:
                        shipment.delivered_to = self.signed_by
                elif new_status == "Failed Delivery":
                    shipment.delivery_attempts = cint(shipment.delivery_attempts) + 1
                    shipment.delivery_status = "Attempted"
                elif new_status == "Exception":
                    shipment.exception_at = self.event_timestamp

                shipment.last_sync_at = now_datetime()
                shipment.flags.ignore_permissions = True
                shipment.save()

        except Exception as e:
            frappe.log_error(
                f"Failed to update shipment status: {str(e)}",
                "Tracking Event - Shipment Update Error"
            )

    # =================================================================
    # Notification Methods
    # =================================================================

    def should_send_notification(self):
        """Determine if notification should be sent for this event."""
        if self.notification_sent:
            return False

        # Events that should trigger notifications
        notification_events = [
            "Pickup Completed",
            "Out for Delivery",
            "Delivered",
            "Signed For",
            "Delivery Attempted",
            "Delivery Exception",
            "Return Initiated",
            "Available for Pickup"
        ]

        return self.event_type in notification_events

    def queue_notification(self):
        """Queue notification to buyer/seller."""
        try:
            # This would integrate with notification system
            # For now, just mark as needing notification
            pass
        except Exception as e:
            frappe.log_error(
                f"Failed to queue tracking notification: {str(e)}",
                "Tracking Event Notification Error"
            )

    def send_notification(self, notification_type="Email"):
        """Send notification for this tracking event."""
        recipient = self.buyer

        if not recipient:
            return

        self.notification_sent = 1
        self.notification_type = notification_type
        self.notification_sent_at = now_datetime()
        self.notification_recipient = recipient

        if notification_type == "Email":
            self.email_sent = 1
        elif notification_type == "SMS":
            self.sms_sent = 1
        elif notification_type == "Push":
            self.push_sent = 1

        self.notification_status = "Sent"
        self.save(ignore_permissions=True)

    # =================================================================
    # Order Event Integration
    # =================================================================

    def log_to_order_events(self):
        """Log tracking event to order events for unified timeline."""
        if not self.sub_order and not self.marketplace_order:
            return

        try:
            # Map tracking event to order event type
            order_event_mapping = {
                "Shipment Created": "Tracking Added",
                "Pickup Completed": "Shipped",
                "In Transit": "In Transit",
                "Out for Delivery": "Out for Delivery",
                "Delivered": "Delivered",
                "Signed For": "Delivered",
                "Delivery Attempted": "Delivery Attempted",
                "Delivery Exception": "Delivery Failed",
                "Return Initiated": "Return Shipped",
                "Returned to Sender": "Return Received"
            }

            order_event_type = order_event_mapping.get(self.event_type)
            if not order_event_type:
                return

            from tradehub_commerce.tradehub_commerce.doctype.order_event.order_event import log_order_event

            location_info = []
            if self.city:
                location_info.append(self.city)
            if self.country and self.country != "Turkey":
                location_info.append(self.country)

            description = f"{self.event_description}"
            if location_info:
                description += f" ({', '.join(location_info)})"

            log_order_event(
                event_type=order_event_type,
                description=description,
                marketplace_order=self.marketplace_order,
                sub_order=self.sub_order,
                actor_type="System",
                data={
                    "tracking_event": self.name,
                    "tracking_number": self.tracking_number,
                    "carrier": self.carrier,
                    "location": {
                        "city": self.city,
                        "country": self.country,
                        "facility": self.facility_name
                    }
                },
                notes=f"Carrier: {self.carrier}, Tracking: {self.tracking_number}"
            )

        except Exception as e:
            # Don't fail tracking event if order event logging fails
            frappe.log_error(
                f"Failed to log tracking event to order events: {str(e)}",
                "Tracking Event - Order Event Logging Error"
            )

    # =================================================================
    # Utility Methods
    # =================================================================

    def get_event_summary(self):
        """Get a summary of the tracking event."""
        return {
            "name": self.name,
            "shipment": self.shipment,
            "tracking_number": self.tracking_number,
            "carrier": self.carrier,
            "event_type": self.event_type,
            "event_status": self.event_status,
            "event_description": self.event_description,
            "event_timestamp": self.event_timestamp,
            "is_milestone": self.is_milestone,
            "is_exception": self.is_exception,
            "exception_type": self.exception_type,
            "location": {
                "city": self.city,
                "state": self.state,
                "country": self.country,
                "facility": self.facility_name
            },
            "severity": self.severity
        }

    def get_timeline_display(self):
        """Get event data formatted for timeline display."""
        location_parts = []
        if self.facility_name:
            location_parts.append(self.facility_name)
        if self.city:
            location_parts.append(self.city)
        if self.country and self.country != "Turkey":
            location_parts.append(self.country)

        return {
            "id": self.name,
            "timestamp": self.event_timestamp,
            "type": self.event_type,
            "status": self.event_status,
            "description": self.event_description,
            "location": ", ".join(location_parts) if location_parts else None,
            "is_milestone": self.is_milestone,
            "is_exception": self.is_exception,
            "severity": self.severity,
            "icon": self.get_event_icon()
        }

    def get_event_icon(self):
        """Get icon for the event type."""
        icon_mapping = {
            "Shipment Created": "file-plus",
            "Label Printed": "printer",
            "Pickup Scheduled": "calendar",
            "Pickup Completed": "package",
            "In Transit": "truck",
            "Arrived at Facility": "warehouse",
            "Departed Facility": "arrow-right",
            "Out for Delivery": "navigation",
            "Delivered": "check-circle",
            "Signed For": "edit",
            "Delivery Attempted": "alert-circle",
            "Delivery Exception": "alert-triangle",
            "Return Initiated": "rotate-ccw",
            "Returned to Sender": "corner-down-left"
        }
        return icon_mapping.get(self.event_type, "circle")


# =================================================================
# Helper Functions
# =================================================================

def log_tracking_event(
    shipment,
    event_type,
    description,
    event_timestamp=None,
    event_status=None,
    city=None,
    country=None,
    facility_name=None,
    carrier_event_code=None,
    carrier_event_description=None,
    is_exception=False,
    exception_type=None,
    signed_by=None,
    attempt_number=None,
    reason_code=None,
    reason_description=None,
    raw_event_data=None,
    source="System",
    sync_id=None
):
    """
    Utility function to log a tracking event.

    Args:
        shipment: Marketplace Shipment reference
        event_type: Type of tracking event
        description: Event description
        event_timestamp: When the event occurred
        event_status: Status code
        city: City where event occurred
        country: Country where event occurred
        facility_name: Facility name
        carrier_event_code: Original carrier event code
        carrier_event_description: Original carrier description
        is_exception: Is this an exception event
        exception_type: Type of exception
        signed_by: Who signed for delivery
        attempt_number: Delivery attempt number
        reason_code: Reason code for exceptions
        reason_description: Reason description
        raw_event_data: Raw data from carrier
        source: Source of the event
        sync_id: Unique sync ID for deduplication

    Returns:
        Tracking Event document or None
    """
    event_data = {
        "doctype": "Tracking Event",
        "shipment": shipment,
        "event_type": event_type,
        "event_description": description,
        "event_timestamp": event_timestamp or now_datetime(),
        "event_status": event_status,
        "city": city,
        "country": country,
        "facility_name": facility_name,
        "carrier_event_code": carrier_event_code,
        "carrier_event_description": carrier_event_description,
        "is_exception": 1 if is_exception else 0,
        "exception_type": exception_type,
        "signed_by": signed_by,
        "attempt_number": attempt_number,
        "reason_code": reason_code,
        "reason_description": reason_description,
        "source": source,
        "sync_id": sync_id
    }

    # Add raw event data if provided
    if raw_event_data:
        event_data["raw_event_data"] = (
            json.dumps(raw_event_data)
            if isinstance(raw_event_data, dict)
            else raw_event_data
        )

    try:
        # Check for duplicate
        if sync_id and frappe.db.exists("Tracking Event", {"sync_id": sync_id}):
            return None

        event = frappe.get_doc(event_data)
        event.insert(ignore_permissions=True)
        return event

    except Exception as e:
        frappe.log_error(
            f"Failed to log tracking event: {str(e)}\n"
            f"Shipment: {shipment}, Event: {event_type}",
            "Tracking Event Logging Error"
        )
        return None


def get_shipment_tracking_history(shipment):
    """
    Get complete tracking history for a shipment.

    Args:
        shipment: Marketplace Shipment name

    Returns:
        list: Tracking events ordered by timestamp
    """
    events = frappe.get_all(
        "Tracking Event",
        filters={"shipment": shipment},
        fields=[
            "name", "event_type", "event_status", "event_description",
            "event_timestamp", "is_milestone", "is_exception", "severity",
            "city", "state", "country", "facility_name", "signed_by"
        ],
        order_by="event_timestamp ASC"
    )

    return events


def get_latest_tracking_event(shipment):
    """
    Get the latest tracking event for a shipment.

    Args:
        shipment: Marketplace Shipment name

    Returns:
        dict: Latest tracking event
    """
    events = frappe.get_all(
        "Tracking Event",
        filters={"shipment": shipment},
        fields=[
            "name", "event_type", "event_status", "event_description",
            "event_timestamp", "is_milestone", "is_exception", "severity",
            "city", "country", "facility_name"
        ],
        order_by="event_timestamp DESC",
        limit=1
    )

    return events[0] if events else None


def process_carrier_events(shipment, carrier_events):
    """
    Process multiple tracking events from carrier API.

    Args:
        shipment: Marketplace Shipment name
        carrier_events: List of carrier event data dicts

    Returns:
        dict: Processing result with counts
    """
    created = 0
    skipped = 0
    errors = 0

    for event_data in carrier_events:
        try:
            # Generate sync_id from carrier data
            sync_components = [
                shipment,
                str(event_data.get("timestamp", "")),
                event_data.get("code", ""),
                event_data.get("location", {}).get("city", "")
            ]
            sync_id = frappe.generate_hash("|".join(sync_components), length=32)

            # Check if already exists
            if frappe.db.exists("Tracking Event", {"sync_id": sync_id}):
                skipped += 1
                continue

            # Map carrier event to our event type
            event_type = map_carrier_event_type(
                event_data.get("code"),
                event_data.get("description", "")
            )

            result = log_tracking_event(
                shipment=shipment,
                event_type=event_type,
                description=event_data.get("description", ""),
                event_timestamp=event_data.get("timestamp"),
                event_status=event_data.get("status"),
                city=event_data.get("location", {}).get("city"),
                country=event_data.get("location", {}).get("country"),
                facility_name=event_data.get("location", {}).get("facility"),
                carrier_event_code=event_data.get("code"),
                carrier_event_description=event_data.get("carrier_description"),
                raw_event_data=event_data.get("raw_data"),
                source="Carrier API",
                sync_id=sync_id
            )

            if result:
                created += 1
            else:
                skipped += 1

        except Exception as e:
            errors += 1
            frappe.log_error(
                f"Error processing carrier event: {str(e)}\n{event_data}",
                "Carrier Event Processing Error"
            )

    return {
        "created": created,
        "skipped": skipped,
        "errors": errors,
        "total": len(carrier_events)
    }


def map_carrier_event_type(carrier_code, description=""):
    """
    Map carrier event code to standard event type.

    Args:
        carrier_code: Carrier-specific event code
        description: Event description for fuzzy matching

    Returns:
        str: Standard event type
    """
    # Common carrier event code mappings
    code_mapping = {
        # Pickup events
        "PU": "Pickup Completed",
        "PICKUP": "Pickup Completed",
        "OC": "Picked Up",

        # Transit events
        "IT": "In Transit",
        "AR": "Arrived at Facility",
        "DP": "Departed Facility",
        "OH": "Arrived at Facility",

        # Delivery events
        "OD": "Out for Delivery",
        "DL": "Delivered",
        "OK": "Delivered",
        "SN": "Signed For",
        "LF": "Left at Door",

        # Exception events
        "EX": "Delivery Exception",
        "NA": "Recipient Unavailable",
        "RF": "Refused",
        "AD": "Address Issue",
        "DA": "Damaged",
        "LO": "Lost",

        # Return events
        "RS": "Return Initiated",
        "RT": "Returned to Sender"
    }

    # Try exact code match
    if carrier_code and carrier_code.upper() in code_mapping:
        return code_mapping[carrier_code.upper()]

    # Try description-based matching
    description_lower = description.lower() if description else ""

    if "delivered" in description_lower:
        if "signed" in description_lower:
            return "Signed For"
        return "Delivered"
    elif "out for delivery" in description_lower:
        return "Out for Delivery"
    elif "in transit" in description_lower:
        return "In Transit"
    elif "picked up" in description_lower or "collected" in description_lower:
        return "Pickup Completed"
    elif "arrived" in description_lower:
        if "destination" in description_lower:
            return "Arrived at Destination Facility"
        return "Arrived at Facility"
    elif "departed" in description_lower or "left" in description_lower:
        return "Departed Facility"
    elif "attempt" in description_lower:
        return "Delivery Attempted"
    elif "exception" in description_lower or "problem" in description_lower:
        return "Delivery Exception"
    elif "return" in description_lower:
        return "Return Initiated"
    elif "refused" in description_lower:
        return "Refused"

    return "Status Update"


# =================================================================
# API Endpoints
# =================================================================

@frappe.whitelist()
def get_tracking_events(
    shipment=None,
    tracking_number=None,
    carrier=None,
    event_type=None,
    is_exception=None,
    from_date=None,
    to_date=None,
    page=1,
    page_size=50
):
    """
    Get tracking events with filtering.

    Args:
        shipment: Filter by Marketplace Shipment
        tracking_number: Filter by tracking number
        carrier: Filter by carrier
        event_type: Filter by event type
        is_exception: Filter exception events
        from_date: Filter from date
        to_date: Filter to date
        page: Page number
        page_size: Results per page

    Returns:
        dict: Events with pagination
    """
    filters = {}

    if shipment:
        filters["shipment"] = shipment
    if tracking_number:
        filters["tracking_number"] = tracking_number
    if carrier:
        filters["carrier"] = carrier
    if event_type:
        filters["event_type"] = event_type
    if is_exception is not None:
        filters["is_exception"] = cint(is_exception)
    if from_date:
        filters["event_timestamp"] = [">=", from_date]
    if to_date:
        if "event_timestamp" in filters:
            filters["event_timestamp"] = [
                "between", [from_date, to_date]
            ]
        else:
            filters["event_timestamp"] = ["<=", to_date]

    start = (cint(page) - 1) * cint(page_size)
    total = frappe.db.count("Tracking Event", filters)

    events = frappe.get_all(
        "Tracking Event",
        filters=filters,
        fields=[
            "name", "shipment", "tracking_number", "carrier",
            "event_type", "event_status", "event_description",
            "event_timestamp", "is_milestone", "is_exception",
            "severity", "city", "country", "facility_name"
        ],
        order_by="event_timestamp DESC",
        start=start,
        limit_page_length=cint(page_size)
    )

    return {
        "events": events,
        "total": total,
        "page": cint(page),
        "page_size": cint(page_size),
        "total_pages": (total + cint(page_size) - 1) // cint(page_size)
    }


@frappe.whitelist()
def get_shipment_timeline(shipment):
    """
    Get tracking timeline for a shipment.

    Args:
        shipment: Marketplace Shipment name

    Returns:
        list: Timeline events for display
    """
    if not shipment:
        frappe.throw(_("Shipment is required"))

    if not frappe.db.exists("Marketplace Shipment", shipment):
        frappe.throw(_("Shipment not found"))

    events = frappe.get_all(
        "Tracking Event",
        filters={"shipment": shipment},
        fields=[
            "name", "event_type", "event_status", "event_description",
            "event_timestamp", "is_milestone", "is_exception", "severity",
            "city", "state", "country", "facility_name", "signed_by",
            "exception_type", "reason_description"
        ],
        order_by="event_timestamp ASC"
    )

    timeline = []
    for event in events:
        location_parts = []
        if event.facility_name:
            location_parts.append(event.facility_name)
        if event.city:
            location_parts.append(event.city)
        if event.country and event.country != "Turkey":
            location_parts.append(event.country)

        timeline_item = {
            "id": event.name,
            "timestamp": event.event_timestamp,
            "type": event.event_type,
            "status": event.event_status,
            "description": event.event_description,
            "location": ", ".join(location_parts) if location_parts else None,
            "is_milestone": event.is_milestone,
            "is_exception": event.is_exception,
            "severity": event.severity
        }

        if event.signed_by:
            timeline_item["signed_by"] = event.signed_by

        if event.is_exception:
            timeline_item["exception_type"] = event.exception_type
            timeline_item["reason"] = event.reason_description

        timeline.append(timeline_item)

    return timeline


@frappe.whitelist()
def get_tracking_by_number(tracking_number, carrier=None):
    """
    Get tracking history by tracking number.

    Args:
        tracking_number: Carrier tracking number
        carrier: Optional carrier filter

    Returns:
        dict: Tracking information with timeline
    """
    if not tracking_number:
        frappe.throw(_("Tracking number is required"))

    filters = {"tracking_number": tracking_number}
    if carrier:
        filters["carrier"] = carrier

    # Find shipment
    shipments = frappe.get_all(
        "Marketplace Shipment",
        filters=filters,
        fields=["name", "status", "carrier", "tracking_url",
                "expected_delivery_date", "actual_delivery_date"],
        limit=1
    )

    if not shipments:
        return {"error": _("Tracking number not found")}

    shipment = shipments[0]

    # Get tracking events
    events = frappe.get_all(
        "Tracking Event",
        filters={"shipment": shipment.name},
        fields=[
            "name", "event_type", "event_status", "event_description",
            "event_timestamp", "is_milestone", "is_exception",
            "city", "country", "facility_name"
        ],
        order_by="event_timestamp ASC"
    )

    # Get latest event
    latest = events[-1] if events else None

    return {
        "tracking_number": tracking_number,
        "carrier": shipment.carrier,
        "status": shipment.status,
        "tracking_url": shipment.tracking_url,
        "expected_delivery": shipment.expected_delivery_date,
        "actual_delivery": shipment.actual_delivery_date,
        "latest_event": latest,
        "timeline": events,
        "total_events": len(events)
    }


@frappe.whitelist()
def create_tracking_event(
    shipment,
    event_type,
    event_description,
    **kwargs
):
    """
    Create a new tracking event via API.

    Args:
        shipment: Marketplace Shipment reference
        event_type: Type of tracking event
        event_description: Event description
        **kwargs: Additional event fields

    Returns:
        dict: Created event info
    """
    if not shipment:
        frappe.throw(_("Shipment is required"))

    if not frappe.db.exists("Marketplace Shipment", shipment):
        frappe.throw(_("Shipment not found"))

    event = log_tracking_event(
        shipment=shipment,
        event_type=event_type,
        description=event_description,
        source="API",
        **kwargs
    )

    if event:
        return {
            "status": "success",
            "event_name": event.name,
            "event_type": event.event_type,
            "event_timestamp": event.event_timestamp
        }
    else:
        return {
            "status": "error",
            "message": _("Failed to create tracking event")
        }


@frappe.whitelist()
def get_tracking_statistics(
    shipment=None,
    seller=None,
    carrier=None,
    days=30
):
    """
    Get tracking event statistics.

    Args:
        shipment: Filter by shipment
        seller: Filter by seller
        carrier: Filter by carrier
        days: Number of days to analyze

    Returns:
        dict: Tracking statistics
    """
    from_date = add_days(nowdate(), -cint(days))

    # Use parameterized queries to prevent SQL injection
    params = {"from_date": from_date}
    filters = ["event_timestamp >= %(from_date)s"]
    if shipment:
        filters.append("shipment = %(shipment)s")
        params["shipment"] = shipment
    if seller:
        filters.append("seller = %(seller)s")
        params["seller"] = seller
    if carrier:
        filters.append("carrier = %(carrier)s")
        params["carrier"] = carrier

    where_clause = " AND ".join(filters)

    # Events by type
    by_type = frappe.db.sql("""
        SELECT event_type, COUNT(*) as count
        FROM `tabTracking Event`
        WHERE {where_clause}
        GROUP BY event_type
        ORDER BY count DESC
        LIMIT 15
    """.format(where_clause=where_clause), params, as_dict=True)

    # Events by carrier
    by_carrier = frappe.db.sql("""
        SELECT carrier, COUNT(*) as count
        FROM `tabTracking Event`
        WHERE {where_clause}
        GROUP BY carrier
        ORDER BY count DESC
    """.format(where_clause=where_clause), params, as_dict=True)

    # Exception count
    exception_count = frappe.db.sql("""
        SELECT COUNT(*) as count
        FROM `tabTracking Event`
        WHERE {where_clause} AND is_exception = 1
    """.format(where_clause=where_clause), params, as_dict=True)[0].count

    # Milestone count
    milestone_count = frappe.db.sql("""
        SELECT COUNT(*) as count
        FROM `tabTracking Event`
        WHERE {where_clause} AND is_milestone = 1
    """.format(where_clause=where_clause), params, as_dict=True)[0].count

    # Daily trend
    daily_trend = frappe.db.sql("""
        SELECT DATE(event_timestamp) as date, COUNT(*) as count
        FROM `tabTracking Event`
        WHERE {where_clause}
        GROUP BY DATE(event_timestamp)
        ORDER BY date
    """.format(where_clause=where_clause), params, as_dict=True)

    total_events = sum(e.count for e in by_type)

    return {
        "period_days": cint(days),
        "total_events": total_events,
        "exception_count": exception_count,
        "milestone_count": milestone_count,
        "exception_rate": round(exception_count / total_events * 100, 2) if total_events else 0,
        "by_type": {e.event_type: e.count for e in by_type},
        "by_carrier": {e.carrier: e.count for e in by_carrier if e.carrier},
        "daily_trend": [{"date": str(e.date), "count": e.count} for e in daily_trend]
    }


@frappe.whitelist()
def sync_carrier_tracking(shipment):
    """
    Sync tracking events from carrier API.

    Args:
        shipment: Marketplace Shipment name

    Returns:
        dict: Sync result
    """
    if not shipment:
        frappe.throw(_("Shipment is required"))

    if not frappe.db.exists("Marketplace Shipment", shipment):
        frappe.throw(_("Shipment not found"))

    shipment_doc = frappe.get_doc("Marketplace Shipment", shipment)

    if not shipment_doc.tracking_number:
        return {"error": _("No tracking number available")}

    try:
        # This would integrate with carrier APIs
        # For now, return placeholder
        # In production, this would call the carrier integration module

        return {
            "status": "success",
            "message": _("Tracking sync initiated"),
            "shipment": shipment,
            "tracking_number": shipment_doc.tracking_number,
            "carrier": shipment_doc.carrier
        }

    except Exception as e:
        frappe.log_error(
            f"Failed to sync carrier tracking: {str(e)}",
            "Carrier Tracking Sync Error"
        )
        return {
            "status": "error",
            "message": str(e)
        }


@frappe.whitelist()
def get_exception_events(
    shipment=None,
    seller=None,
    days=7,
    limit=20
):
    """
    Get recent exception events.

    Args:
        shipment: Filter by shipment
        seller: Filter by seller
        days: Number of days to look back
        limit: Max events to return

    Returns:
        list: Exception events
    """
    from_date = add_days(nowdate(), -cint(days))

    filters = {"is_exception": 1}
    if shipment:
        filters["shipment"] = shipment
    if seller:
        filters["seller"] = seller

    filters["event_timestamp"] = [">=", from_date]

    events = frappe.get_all(
        "Tracking Event",
        filters=filters,
        fields=[
            "name", "shipment", "tracking_number", "carrier",
            "event_type", "event_description", "event_timestamp",
            "exception_type", "reason_description", "city", "country",
            "marketplace_order", "sub_order", "severity"
        ],
        order_by="event_timestamp DESC",
        limit=cint(limit)
    )

    return events

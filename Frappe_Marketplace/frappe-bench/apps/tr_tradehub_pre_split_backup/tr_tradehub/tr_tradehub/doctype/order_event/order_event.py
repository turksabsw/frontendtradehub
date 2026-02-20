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


class OrderEvent(Document):
    """
    Order Event DocType for TR-TradeHub.

    Tracks all events related to marketplace orders and sub-orders
    for audit trail, status tracking, and analytics.

    Features:
    - Comprehensive event logging
    - Status change tracking
    - Actor identification (buyer, seller, system, admin)
    - Request metadata capture
    - Error tracking
    - Notification tracking
    - Related event linking
    """

    def before_insert(self):
        """Set default values before creating a new order event."""
        # Set event timestamp if not provided
        if not self.event_timestamp:
            self.event_timestamp = now_datetime()

        # Auto-populate order IDs from linked documents
        self.populate_order_ids()

        # Auto-populate actor information
        self.populate_actor_info()

        # Capture request metadata
        self.capture_request_metadata()

        # Set severity based on event type
        self.set_default_severity()

        # Set event category if not provided
        self.set_event_category()

    def validate(self):
        """Validate order event data before saving."""
        self.validate_order_reference()
        self.validate_status_change()
        self.validate_event_type()
        self.validate_json_fields()

    def on_update(self):
        """Actions after order event is updated."""
        # Order events should generally be immutable
        # Log warning if being modified
        if not self.is_new():
            frappe.log_error(
                f"Order Event {self.name} was modified after creation",
                "Order Event Modification Warning"
            )

    # =================================================================
    # Helper Methods
    # =================================================================

    def populate_order_ids(self):
        """Populate customer-facing order IDs from linked documents."""
        # Get order_id from Marketplace Order
        if self.marketplace_order and not self.order_id:
            self.order_id = frappe.db.get_value(
                "Marketplace Order", self.marketplace_order, "order_id"
            )

        # Get sub_order_id from Sub Order
        if self.sub_order and not self.sub_order_id:
            self.sub_order_id = frappe.db.get_value(
                "Sub Order", self.sub_order, "sub_order_id"
            )

            # Also populate marketplace_order if not set
            if not self.marketplace_order:
                self.marketplace_order = frappe.db.get_value(
                    "Sub Order", self.sub_order, "marketplace_order"
                )
                if self.marketplace_order and not self.order_id:
                    self.order_id = frappe.db.get_value(
                        "Marketplace Order", self.marketplace_order, "order_id"
                    )

        # Get buyer and seller from orders
        if self.marketplace_order:
            if not self.buyer:
                self.buyer = frappe.db.get_value(
                    "Marketplace Order", self.marketplace_order, "buyer"
                )
            if not self.tenant:
                self.tenant = frappe.db.get_value(
                    "Marketplace Order", self.marketplace_order, "tenant"
                )

        if self.sub_order:
            if not self.seller:
                self.seller = frappe.db.get_value(
                    "Sub Order", self.sub_order, "seller"
                )

    def populate_actor_info(self):
        """Populate actor information from session."""
        # Set actor to current user if not provided
        if not self.actor:
            self.actor = frappe.session.user

        # Set actor name
        if self.actor and not self.actor_name:
            self.actor_name = frappe.db.get_value(
                "User", self.actor, "full_name"
            ) or self.actor

        # Determine actor type if not set
        if not self.actor_type or self.actor_type == "System":
            self.actor_type = self.determine_actor_type()

        # Get actor role
        if self.actor and not self.actor_role:
            roles = frappe.get_roles(self.actor)
            if "System Manager" in roles:
                self.actor_role = "System Manager"
            elif "Administrator" in roles:
                self.actor_role = "Administrator"
            else:
                self.actor_role = roles[0] if roles else None

    def determine_actor_type(self):
        """Determine the type of actor based on context."""
        user = self.actor or frappe.session.user

        # System users
        if user in ["Administrator", "Guest", ""]:
            return "System"

        # Check if API request
        if frappe.request and frappe.request.path and "/api/" in frappe.request.path:
            return "API"

        # Check if scheduler
        if frappe.flags.in_scheduler:
            return "Scheduler"

        # Check if user is seller
        if self.seller:
            seller_user = frappe.db.get_value(
                "Seller Profile", self.seller, "user"
            )
            if user == seller_user:
                return "Seller"

        # Check if user is buyer
        if self.buyer and user == self.buyer:
            return "Buyer"

        # Check if admin
        if frappe.has_permission("System Manager"):
            return "Admin"

        return "Unknown"

    def capture_request_metadata(self):
        """Capture request metadata from the current request."""
        try:
            if frappe.request:
                # IP Address
                if not self.ip_address:
                    self.ip_address = frappe.get_request_header("X-Forwarded-For") or \
                                     frappe.get_request_header("X-Real-IP") or \
                                     getattr(frappe.request, "remote_addr", None)

                # User Agent
                if not self.user_agent:
                    self.user_agent = frappe.get_request_header("User-Agent")

                # Determine device type from user agent
                if not self.device_type and self.user_agent:
                    self.device_type = self.detect_device_type(self.user_agent)

                # Session ID
                if not self.session_id:
                    self.session_id = frappe.session.sid if hasattr(frappe.session, "sid") else None

                # Request ID
                if not self.request_id:
                    self.request_id = frappe.get_request_header("X-Request-ID") or \
                                     frappe.generate_hash(length=16)

        except Exception:
            # Don't fail if metadata capture fails
            pass

    def detect_device_type(self, user_agent):
        """Detect device type from user agent string."""
        if not user_agent:
            return "Unknown"

        user_agent_lower = user_agent.lower()

        if "mobile" in user_agent_lower or "android" in user_agent_lower:
            if "tablet" in user_agent_lower or "ipad" in user_agent_lower:
                return "Tablet"
            return "Mobile"
        elif "tablet" in user_agent_lower or "ipad" in user_agent_lower:
            return "Tablet"
        elif any(bot in user_agent_lower for bot in ["bot", "crawler", "spider", "api"]):
            return "API Client"
        else:
            return "Desktop"

    def set_default_severity(self):
        """Set severity based on event type."""
        if self.severity:
            return

        error_events = [
            "Payment Failed", "Delivery Failed", "Error Occurred",
            "E-Invoice Rejected", "Payout Failed", "Fraud Detected"
        ]
        warning_events = [
            "Cancellation Requested", "Refund Requested", "Return Requested",
            "Dispute Opened", "SLA Breach", "Warning Raised"
        ]
        critical_events = [
            "Fraud Detected", "Dispute Escalated"
        ]

        if self.event_type in critical_events:
            self.severity = "Critical"
        elif self.event_type in error_events or self.is_error:
            self.severity = "Error"
        elif self.event_type in warning_events:
            self.severity = "Warning"
        else:
            self.severity = "Info"

    def set_event_category(self):
        """Set event category based on event type."""
        if self.event_category:
            return

        category_mapping = {
            "Order": [
                "Order Created", "Order Confirmed", "Order Updated",
                "Status Changed", "Item Added", "Item Removed", "Item Updated",
                "Quantity Changed", "Price Changed", "Hold Applied", "Hold Released"
            ],
            "Payment": [
                "Payment Received", "Payment Failed", "Payment Refunded",
                "Escrow Held", "Escrow Released", "Escrow Disputed",
                "Discount Applied", "Coupon Applied"
            ],
            "Fulfillment": [
                "Packed", "Seller Accepted", "Seller Rejected"
            ],
            "Shipping": [
                "Shipping Updated", "Tracking Added", "Shipped", "In Transit",
                "Out for Delivery", "Delivered", "Delivery Failed", "Delivery Attempted",
                "Address Changed", "Address Verified"
            ],
            "Return": [
                "Return Requested", "Return Approved", "Return Rejected",
                "Return Shipped", "Return Received", "Return Completed"
            ],
            "Refund": [
                "Refund Requested", "Refund Approved", "Refund Processed", "Refund Rejected"
            ],
            "Cancellation": [
                "Cancellation Requested", "Cancellation Approved",
                "Cancellation Rejected", "Order Cancelled"
            ],
            "Dispute": [
                "Dispute Opened", "Dispute Escalated", "Dispute Resolved", "Dispute Closed"
            ],
            "Communication": [
                "Seller Note Added", "Buyer Note Added", "Internal Note Added",
                "Reminder Sent"
            ],
            "Invoice": [
                "Invoice Generated", "E-Invoice Sent", "E-Invoice Accepted", "E-Invoice Rejected"
            ],
            "Commission": [
                "Commission Calculated", "Commission Collected"
            ],
            "Payout": [
                "Payout Scheduled", "Payout Processed", "Payout Failed"
            ],
            "Security": [
                "Fraud Detected", "Fraud Cleared", "Document Uploaded", "Document Verified"
            ],
            "Integration": [
                "Webhook Triggered", "Integration Sync"
            ],
            "System": [
                "System Event", "API Call", "Escalation Triggered", "SLA Breach"
            ],
            "Error": [
                "Error Occurred"
            ]
        }

        for category, events in category_mapping.items():
            if self.event_type in events:
                self.event_category = category
                return

        self.event_category = "Other"

    # =================================================================
    # Validation Methods
    # =================================================================

    def validate_order_reference(self):
        """Validate that at least one order reference is provided."""
        if not self.marketplace_order and not self.sub_order:
            frappe.throw(_(
                "At least one of Marketplace Order or Sub Order is required"
            ))

        # Validate marketplace order exists
        if self.marketplace_order:
            if not frappe.db.exists("Marketplace Order", self.marketplace_order):
                frappe.throw(_(
                    "Marketplace Order {0} does not exist"
                ).format(self.marketplace_order))

        # Validate sub order exists
        if self.sub_order:
            if not frappe.db.exists("Sub Order", self.sub_order):
                frappe.throw(_(
                    "Sub Order {0} does not exist"
                ).format(self.sub_order))

    def validate_status_change(self):
        """Validate status change fields."""
        if self.event_type == "Status Changed":
            if not self.previous_status and not self.new_status:
                frappe.msgprint(_(
                    "Status change event should include previous and new status"
                ))

    def validate_event_type(self):
        """Validate event type is provided."""
        if not self.event_type:
            frappe.throw(_("Event Type is required"))

    def validate_json_fields(self):
        """Validate JSON fields are valid JSON."""
        if self.data_json:
            try:
                if isinstance(self.data_json, str):
                    json.loads(self.data_json)
            except json.JSONDecodeError:
                frappe.throw(_("Event Data must be valid JSON"))

        if self.related_events:
            try:
                if isinstance(self.related_events, str):
                    json.loads(self.related_events)
            except json.JSONDecodeError:
                frappe.throw(_("Related Events must be valid JSON"))

    # =================================================================
    # Utility Methods
    # =================================================================

    def get_event_summary(self):
        """Get a summary of the event for display."""
        return {
            "name": self.name,
            "event_type": self.event_type,
            "event_category": self.event_category,
            "event_description": self.event_description,
            "event_timestamp": self.event_timestamp,
            "severity": self.severity,
            "actor": self.actor,
            "actor_type": self.actor_type,
            "actor_name": self.actor_name,
            "marketplace_order": self.marketplace_order,
            "order_id": self.order_id,
            "sub_order": self.sub_order,
            "sub_order_id": self.sub_order_id,
            "previous_status": self.previous_status,
            "new_status": self.new_status
        }

    def get_timeline_display(self):
        """Get event data formatted for timeline display."""
        return {
            "timestamp": self.event_timestamp,
            "type": self.event_type,
            "category": self.event_category,
            "description": self.event_description,
            "actor": self.actor_name or self.actor or "System",
            "actor_type": self.actor_type,
            "severity": self.severity,
            "status_change": {
                "from": self.previous_status,
                "to": self.new_status
            } if self.previous_status or self.new_status else None,
            "notes": self.notes
        }


# =================================================================
# Helper Functions
# =================================================================

def log_order_event(
    event_type,
    description,
    marketplace_order=None,
    sub_order=None,
    previous_status=None,
    new_status=None,
    previous_value=None,
    new_value=None,
    field_changed=None,
    actor=None,
    actor_type=None,
    data=None,
    notes=None,
    internal_notes=None,
    is_error=False,
    error_code=None,
    error_message=None,
    severity=None,
    parent_event=None,
    notification_type=None,
    notification_recipient=None
):
    """
    Utility function to log an order event.

    Args:
        event_type: Type of event
        description: Event description
        marketplace_order: Marketplace Order reference
        sub_order: Sub Order reference
        previous_status: Previous status value
        new_status: New status value
        previous_value: Previous value (for field changes)
        new_value: New value (for field changes)
        field_changed: Name of field that changed
        actor: User who triggered the event
        actor_type: Type of actor
        data: Additional data (dict)
        notes: Public notes
        internal_notes: Internal notes
        is_error: Is this an error event
        error_code: Error code if error
        error_message: Error message if error
        severity: Event severity
        parent_event: Parent event for related events
        notification_type: Type of notification sent
        notification_recipient: Notification recipient

    Returns:
        Order Event document
    """
    event_data = {
        "doctype": "Order Event",
        "event_type": event_type,
        "event_description": description,
        "marketplace_order": marketplace_order,
        "sub_order": sub_order,
        "previous_status": previous_status,
        "new_status": new_status,
        "previous_value": previous_value,
        "new_value": new_value,
        "field_changed": field_changed,
        "actor": actor,
        "actor_type": actor_type,
        "notes": notes,
        "internal_notes": internal_notes,
        "is_error": is_error,
        "error_code": error_code,
        "error_message": error_message,
        "severity": severity,
        "parent_event": parent_event
    }

    # Add data JSON if provided
    if data:
        event_data["data_json"] = json.dumps(data) if isinstance(data, dict) else data

    # Add notification info
    if notification_type:
        event_data["notification_sent"] = 1
        event_data["notification_type"] = notification_type
        event_data["notification_recipient"] = notification_recipient
        event_data["notification_sent_at"] = now_datetime()

    try:
        event = frappe.get_doc(event_data)
        event.insert(ignore_permissions=True)
        return event
    except Exception as e:
        frappe.log_error(
            f"Failed to log order event: {str(e)}\nEvent: {event_type}, Order: {marketplace_order}, Sub: {sub_order}",
            "Order Event Logging Error"
        )
        return None


def log_status_change(
    doctype,
    doc_name,
    previous_status,
    new_status,
    actor=None,
    notes=None
):
    """
    Log a status change event.

    Args:
        doctype: Document type (Marketplace Order or Sub Order)
        doc_name: Document name
        previous_status: Previous status
        new_status: New status
        actor: User who triggered the change
        notes: Optional notes

    Returns:
        Order Event document
    """
    marketplace_order = None
    sub_order = None

    if doctype == "Marketplace Order":
        marketplace_order = doc_name
    elif doctype == "Sub Order":
        sub_order = doc_name

    return log_order_event(
        event_type="Status Changed",
        description=f"{doctype} status changed from {previous_status} to {new_status}",
        marketplace_order=marketplace_order,
        sub_order=sub_order,
        previous_status=previous_status,
        new_status=new_status,
        actor=actor,
        notes=notes
    )


def log_error_event(
    marketplace_order=None,
    sub_order=None,
    error_code=None,
    error_message=None,
    stack_trace=None,
    context=None
):
    """
    Log an error event.

    Args:
        marketplace_order: Marketplace Order reference
        sub_order: Sub Order reference
        error_code: Error code
        error_message: Error message
        stack_trace: Stack trace
        context: Additional context dict

    Returns:
        Order Event document
    """
    event_data = {
        "doctype": "Order Event",
        "event_type": "Error Occurred",
        "event_description": error_message or "An error occurred",
        "marketplace_order": marketplace_order,
        "sub_order": sub_order,
        "is_error": 1,
        "error_code": error_code,
        "error_message": error_message,
        "stack_trace": stack_trace,
        "severity": "Error",
        "actor_type": "System"
    }

    if context:
        event_data["data_json"] = json.dumps(context)

    try:
        event = frappe.get_doc(event_data)
        event.insert(ignore_permissions=True)
        return event
    except Exception as e:
        frappe.log_error(
            f"Failed to log error event: {str(e)}",
            "Order Event Logging Error"
        )
        return None


# =================================================================
# API Endpoints
# =================================================================

@frappe.whitelist()
def get_order_events(
    marketplace_order=None,
    sub_order=None,
    event_type=None,
    event_category=None,
    severity=None,
    from_date=None,
    to_date=None,
    page=1,
    page_size=50
):
    """
    Get order events with filtering.

    Args:
        marketplace_order: Filter by Marketplace Order
        sub_order: Filter by Sub Order
        event_type: Filter by event type
        event_category: Filter by event category
        severity: Filter by severity
        from_date: Filter from date
        to_date: Filter to date
        page: Page number
        page_size: Results per page

    Returns:
        dict: Events with pagination
    """
    filters = {}

    if marketplace_order:
        filters["marketplace_order"] = marketplace_order
    if sub_order:
        filters["sub_order"] = sub_order
    if event_type:
        filters["event_type"] = event_type
    if event_category:
        filters["event_category"] = event_category
    if severity:
        filters["severity"] = severity
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
    total = frappe.db.count("Order Event", filters)

    events = frappe.get_all(
        "Order Event",
        filters=filters,
        fields=[
            "name", "event_type", "event_category", "event_description",
            "event_timestamp", "severity", "actor", "actor_type", "actor_name",
            "marketplace_order", "order_id", "sub_order", "sub_order_id",
            "previous_status", "new_status", "is_error", "notification_sent"
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
def get_order_timeline(marketplace_order=None, sub_order=None):
    """
    Get order timeline for display.

    Args:
        marketplace_order: Marketplace Order name
        sub_order: Sub Order name

    Returns:
        list: Timeline events
    """
    if not marketplace_order and not sub_order:
        frappe.throw(_("Either marketplace_order or sub_order is required"))

    filters = {}
    if marketplace_order:
        filters["marketplace_order"] = marketplace_order
    if sub_order:
        filters["sub_order"] = sub_order

    events = frappe.get_all(
        "Order Event",
        filters=filters,
        fields=[
            "name", "event_type", "event_category", "event_description",
            "event_timestamp", "severity", "actor_name", "actor_type",
            "previous_status", "new_status", "notes"
        ],
        order_by="event_timestamp ASC"
    )

    timeline = []
    for event in events:
        timeline_item = {
            "id": event.name,
            "timestamp": event.event_timestamp,
            "type": event.event_type,
            "category": event.event_category,
            "description": event.event_description,
            "actor": event.actor_name or "System",
            "actor_type": event.actor_type,
            "severity": event.severity
        }

        if event.previous_status or event.new_status:
            timeline_item["status_change"] = {
                "from": event.previous_status,
                "to": event.new_status
            }

        if event.notes:
            timeline_item["notes"] = event.notes

        timeline.append(timeline_item)

    return timeline


@frappe.whitelist()
def get_event_statistics(
    marketplace_order=None,
    sub_order=None,
    seller=None,
    days=30
):
    """
    Get event statistics.

    Args:
        marketplace_order: Filter by Marketplace Order
        sub_order: Filter by Sub Order
        seller: Filter by seller
        days: Number of days to analyze

    Returns:
        dict: Event statistics
    """
    from_date = add_days(nowdate(), -cint(days))

    # Use parameterized queries to prevent SQL injection
    params = {"from_date": from_date}
    filters = ["event_timestamp >= %(from_date)s"]
    if marketplace_order:
        filters.append("marketplace_order = %(marketplace_order)s")
        params["marketplace_order"] = marketplace_order
    if sub_order:
        filters.append("sub_order = %(sub_order)s")
        params["sub_order"] = sub_order
    if seller:
        filters.append("seller = %(seller)s")
        params["seller"] = seller

    where_clause = " AND ".join(filters)

    # Events by type
    by_type = frappe.db.sql("""
        SELECT event_type, COUNT(*) as count
        FROM `tabOrder Event`
        WHERE {where_clause}
        GROUP BY event_type
        ORDER BY count DESC
        LIMIT 20
    """.format(where_clause=where_clause), params, as_dict=True)

    # Events by category
    by_category = frappe.db.sql("""
        SELECT event_category, COUNT(*) as count
        FROM `tabOrder Event`
        WHERE {where_clause}
        GROUP BY event_category
        ORDER BY count DESC
    """.format(where_clause=where_clause), params, as_dict=True)

    # Events by severity
    by_severity = frappe.db.sql("""
        SELECT severity, COUNT(*) as count
        FROM `tabOrder Event`
        WHERE {where_clause}
        GROUP BY severity
    """.format(where_clause=where_clause), params, as_dict=True)

    # Events by actor type
    by_actor = frappe.db.sql("""
        SELECT actor_type, COUNT(*) as count
        FROM `tabOrder Event`
        WHERE {where_clause}
        GROUP BY actor_type
        ORDER BY count DESC
    """.format(where_clause=where_clause), params, as_dict=True)

    # Error count
    error_count = frappe.db.sql("""
        SELECT COUNT(*) as count
        FROM `tabOrder Event`
        WHERE {where_clause} AND is_error = 1
    """.format(where_clause=where_clause), params, as_dict=True)[0].count

    # Events per day
    daily_trend = frappe.db.sql("""
        SELECT DATE(event_timestamp) as date, COUNT(*) as count
        FROM `tabOrder Event`
        WHERE {where_clause}
        GROUP BY DATE(event_timestamp)
        ORDER BY date
    """.format(where_clause=where_clause), params, as_dict=True)

    total_events = sum(e.count for e in by_type)

    return {
        "period_days": cint(days),
        "total_events": total_events,
        "error_count": error_count,
        "by_type": {e.event_type: e.count for e in by_type},
        "by_category": {e.event_category: e.count for e in by_category},
        "by_severity": {e.severity: e.count for e in by_severity},
        "by_actor_type": {e.actor_type: e.count for e in by_actor},
        "daily_trend": [{"date": str(e.date), "count": e.count} for e in daily_trend]
    }


@frappe.whitelist()
def get_recent_errors(
    marketplace_order=None,
    sub_order=None,
    limit=10
):
    """
    Get recent error events.

    Args:
        marketplace_order: Filter by Marketplace Order
        sub_order: Filter by Sub Order
        limit: Number of errors to return

    Returns:
        list: Recent error events
    """
    filters = {"is_error": 1}

    if marketplace_order:
        filters["marketplace_order"] = marketplace_order
    if sub_order:
        filters["sub_order"] = sub_order

    errors = frappe.get_all(
        "Order Event",
        filters=filters,
        fields=[
            "name", "event_type", "event_description", "event_timestamp",
            "error_code", "error_message", "marketplace_order", "sub_order",
            "order_id", "sub_order_id"
        ],
        order_by="event_timestamp DESC",
        limit=cint(limit)
    )

    return errors


@frappe.whitelist()
def create_order_event(
    event_type,
    event_description,
    marketplace_order=None,
    sub_order=None,
    **kwargs
):
    """
    Create a new order event via API.

    Args:
        event_type: Type of event
        event_description: Event description
        marketplace_order: Marketplace Order reference
        sub_order: Sub Order reference
        **kwargs: Additional event fields

    Returns:
        dict: Created event info
    """
    if not marketplace_order and not sub_order:
        frappe.throw(_("Either marketplace_order or sub_order is required"))

    event = log_order_event(
        event_type=event_type,
        description=event_description,
        marketplace_order=marketplace_order,
        sub_order=sub_order,
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
            "message": _("Failed to create order event")
        }


@frappe.whitelist()
def get_order_event(event_name):
    """
    Get order event details.

    Args:
        event_name: Order Event name

    Returns:
        dict: Event details
    """
    if not frappe.db.exists("Order Event", event_name):
        return {"error": _("Order Event not found")}

    event = frappe.get_doc("Order Event", event_name)

    return {
        "name": event.name,
        "event_type": event.event_type,
        "event_category": event.event_category,
        "event_description": event.event_description,
        "event_timestamp": event.event_timestamp,
        "severity": event.severity,
        "is_system_event": event.is_system_event,
        "reference_doctype": event.reference_doctype,
        "marketplace_order": event.marketplace_order,
        "order_id": event.order_id,
        "sub_order": event.sub_order,
        "sub_order_id": event.sub_order_id,
        "previous_status": event.previous_status,
        "new_status": event.new_status,
        "previous_value": event.previous_value,
        "new_value": event.new_value,
        "field_changed": event.field_changed,
        "actor": event.actor,
        "actor_type": event.actor_type,
        "actor_name": event.actor_name,
        "seller": event.seller,
        "buyer": event.buyer,
        "ip_address": event.ip_address,
        "source_channel": event.source_channel,
        "device_type": event.device_type,
        "data": event.data_json,
        "notes": event.notes,
        "is_error": event.is_error,
        "error_code": event.error_code,
        "error_message": event.error_message,
        "notification_sent": event.notification_sent,
        "notification_type": event.notification_type
    }

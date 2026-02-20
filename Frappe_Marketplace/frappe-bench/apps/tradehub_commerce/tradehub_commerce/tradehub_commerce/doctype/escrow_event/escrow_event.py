# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt, nowdate, now_datetime, add_days
import json


class EscrowEvent(Document):
    """
    Escrow Event DocType for TR-TradeHub.

    Tracks all events and changes for escrow accounts.
    Provides audit trail for:
    - Status changes
    - Fund movements (hold, release, refund)
    - Dispute lifecycle
    - Payout processing
    - System events
    """

    def before_insert(self):
        """Set default values before creating a new event."""
        # Set timestamp
        if not self.timestamp:
            self.timestamp = now_datetime()

        # Set event category based on type
        if not self.event_category:
            self.set_event_category()

        # Set severity if not provided
        if not self.severity:
            self.set_default_severity()

        # Populate escrow-related fields
        self.populate_from_escrow()

        # Capture request metadata
        self.capture_request_metadata()

        # Set actor info
        self.populate_actor_info()

    def validate(self):
        """Validate event data before saving."""
        self.validate_escrow_account()
        self.validate_event_type()

    def on_update(self):
        """Actions after event is created."""
        # Send notifications if needed
        self.send_notifications()

    # =================================================================
    # Auto-population Methods
    # =================================================================

    def set_event_category(self):
        """Set event category based on event type."""
        category_mapping = {
            # Lifecycle
            "Created": "Lifecycle",
            "Status Change": "Lifecycle",
            "Expired": "Lifecycle",
            "Cancelled": "Lifecycle",

            # Funds Movement
            "Funds Held": "Funds Movement",
            "Partially Released": "Funds Movement",
            "Fully Released": "Funds Movement",
            "Refund Initiated": "Funds Movement",
            "Refund Completed": "Funds Movement",
            "Partially Refunded": "Funds Movement",
            "Auto Released": "Funds Movement",
            "Release Approved": "Funds Movement",
            "Release Scheduled": "Funds Movement",
            "Delivery Confirmed": "Funds Movement",
            "Amount Updated": "Funds Movement",
            "Fee Calculated": "Funds Movement",

            # Dispute
            "Dispute Opened": "Dispute",
            "Dispute Updated": "Dispute",
            "Dispute Escalated": "Dispute",
            "Dispute Resolved": "Dispute",

            # Payout
            "Payout Scheduled": "Payout",
            "Payout Processing": "Payout",
            "Payout Completed": "Payout",
            "Payout Failed": "Payout",

            # Notification
            "Notification Sent": "Notification",

            # Integration
            "ERPNext Synced": "Integration",

            # Admin
            "Admin Action": "Admin",
            "Comment Added": "Admin",
            "Hold Extended": "Admin",

            # System
            "System Event": "System",
            "General": "System"
        }

        self.event_category = category_mapping.get(self.event_type, "System")

    def set_default_severity(self):
        """Set default severity based on event type."""
        severity_mapping = {
            # Critical events
            "Payout Failed": "Error",
            "Dispute Escalated": "Warning",

            # Warning events
            "Dispute Opened": "Warning",
            "Refund Initiated": "Warning",
            "Expired": "Warning",
            "Cancelled": "Warning",

            # Info events (default for most)
            "Created": "Info",
            "Funds Held": "Info",
            "Partially Released": "Info",
            "Fully Released": "Info",
            "Refund Completed": "Info",
            "Payout Completed": "Info",
            "Dispute Resolved": "Info",
            "Status Change": "Info",
            "Delivery Confirmed": "Info",

            # Debug events
            "System Event": "Debug"
        }

        self.severity = severity_mapping.get(self.event_type, "Info")

    def populate_from_escrow(self):
        """Populate fields from the linked escrow account."""
        if not self.escrow_account:
            return

        escrow = frappe.get_doc("Escrow Account", self.escrow_account)

        # Set related references if not provided
        if not self.marketplace_order:
            self.marketplace_order = escrow.marketplace_order

        if not self.sub_order:
            self.sub_order = escrow.sub_order

        if not self.payment_intent:
            self.payment_intent = escrow.payment_intent

        if not self.seller:
            self.seller = escrow.seller

        if not self.buyer:
            self.buyer = escrow.buyer

        if not self.currency:
            self.currency = escrow.currency

        # Set running balance
        if not self.running_balance:
            self.running_balance = escrow.held_amount

    def capture_request_metadata(self):
        """Capture request metadata for audit trail."""
        try:
            if not self.ip_address:
                self.ip_address = frappe.local.request_ip

            if not self.user_agent and hasattr(frappe.local, 'request'):
                self.user_agent = frappe.local.request.headers.get("User-Agent", "")[:500]

            if not self.request_id:
                self.request_id = frappe.local.request_id if hasattr(frappe.local, 'request_id') else None

        except Exception:
            # Ignore errors in capturing metadata
            pass

    def populate_actor_info(self):
        """Set actor information based on context."""
        if not self.user:
            self.user = frappe.session.user

        # Determine actor type
        if not self.actor_type or self.actor_type == "System":
            if frappe.session.user == "Administrator":
                self.actor_type = "Admin"
            elif frappe.session.user == "Guest":
                self.actor_type = "System"
            elif self.is_system_event:
                self.actor_type = "System"
            else:
                # Check if user is buyer or seller
                if self.escrow_account:
                    escrow = frappe.get_doc("Escrow Account", self.escrow_account)
                    if frappe.session.user == escrow.buyer:
                        self.actor_type = "Buyer"
                    else:
                        # Check if seller
                        seller_user = frappe.db.get_value(
                            "Seller Profile", escrow.seller, "user"
                        )
                        if seller_user and frappe.session.user == seller_user:
                            self.actor_type = "Seller"
                        else:
                            self.actor_type = "Admin"
                else:
                    self.actor_type = "System"

    # =================================================================
    # Validation Methods
    # =================================================================

    def validate_escrow_account(self):
        """Validate that escrow account exists."""
        if not self.escrow_account:
            frappe.throw(_("Escrow Account is required"))

        if not frappe.db.exists("Escrow Account", self.escrow_account):
            frappe.throw(
                _("Escrow Account {0} does not exist").format(self.escrow_account)
            )

    def validate_event_type(self):
        """Validate event type."""
        valid_types = [
            "General", "Created", "Funds Held", "Partially Released",
            "Fully Released", "Refund Initiated", "Refund Completed",
            "Partially Refunded", "Delivery Confirmed", "Release Scheduled",
            "Release Approved", "Auto Released", "Dispute Opened",
            "Dispute Updated", "Dispute Escalated", "Dispute Resolved",
            "Hold Extended", "Payout Scheduled", "Payout Processing",
            "Payout Completed", "Payout Failed", "Status Change",
            "Amount Updated", "Fee Calculated", "ERPNext Synced",
            "Notification Sent", "Comment Added", "Admin Action",
            "System Event", "Expired", "Cancelled"
        ]

        if self.event_type not in valid_types:
            frappe.throw(
                _("Invalid event type: {0}").format(self.event_type)
            )

    # =================================================================
    # Notification Methods
    # =================================================================

    def send_notifications(self):
        """Send notifications based on event type."""
        # Define which events trigger notifications
        notification_events = {
            "Funds Held": ["buyer", "seller"],
            "Fully Released": ["seller"],
            "Refund Completed": ["buyer"],
            "Dispute Opened": ["buyer", "seller", "admin"],
            "Dispute Resolved": ["buyer", "seller"],
            "Payout Completed": ["seller"],
            "Payout Failed": ["seller", "admin"],
            "Auto Released": ["seller"]
        }

        recipients_config = notification_events.get(self.event_type)

        if not recipients_config:
            return

        recipients = []

        if self.escrow_account:
            escrow = frappe.get_doc("Escrow Account", self.escrow_account)

            if "buyer" in recipients_config and escrow.buyer:
                recipients.append(escrow.buyer)

            if "seller" in recipients_config and escrow.seller:
                seller_user = frappe.db.get_value(
                    "Seller Profile", escrow.seller, "user"
                )
                if seller_user:
                    recipients.append(seller_user)

            if "admin" in recipients_config:
                # Add system manager or marketplace admin
                admins = frappe.get_all(
                    "Has Role",
                    filters={"role": "System Manager"},
                    pluck="parent"
                )[:3]  # Limit to 3 admins
                recipients.extend(admins)

        if recipients:
            self.db_set("notification_recipients", ", ".join(set(recipients)))

            # Queue notification (actual sending would be handled separately)
            self.queue_notification(recipients)

    def queue_notification(self, recipients):
        """Queue notification for sending."""
        try:
            # Mark notification as queued
            self.db_set("notification_sent", 1)
            self.db_set("notification_type", "In-App")
            self.db_set("notification_sent_at", now_datetime())

            # Create notification for each recipient
            for recipient in set(recipients):
                if recipient and recipient != "Guest":
                    self.create_in_app_notification(recipient)

        except Exception as e:
            frappe.log_error(
                f"Failed to queue escrow notification: {str(e)}",
                "Escrow Event Notification Error"
            )

    def create_in_app_notification(self, user):
        """Create in-app notification for user."""
        try:
            # Create a Frappe notification
            notification = frappe.get_doc({
                "doctype": "Notification Log",
                "for_user": user,
                "document_type": "Escrow Account",
                "document_name": self.escrow_account,
                "subject": self.get_notification_subject(),
                "email_content": self.description
            })
            notification.insert(ignore_permissions=True)
        except Exception:
            # Notification Log might not exist or have different structure
            pass

    def get_notification_subject(self):
        """Get notification subject based on event type."""
        subjects = {
            "Funds Held": _("Payment held in escrow"),
            "Fully Released": _("Escrow funds released"),
            "Refund Completed": _("Refund processed"),
            "Dispute Opened": _("Escrow dispute opened"),
            "Dispute Resolved": _("Escrow dispute resolved"),
            "Payout Completed": _("Payout completed"),
            "Payout Failed": _("Payout failed - action required"),
            "Auto Released": _("Escrow auto-released")
        }

        return subjects.get(self.event_type, _("Escrow account updated"))

    # =================================================================
    # Utility Methods
    # =================================================================

    def get_event_summary(self):
        """Get event summary for display."""
        return {
            "name": self.name,
            "escrow_account": self.escrow_account,
            "event_type": self.event_type,
            "event_category": self.event_category,
            "description": self.description,
            "timestamp": str(self.timestamp),
            "severity": self.severity,
            "actor_type": self.actor_type,
            "user": self.user,
            "amount": self.amount,
            "amount_type": self.amount_type,
            "running_balance": self.running_balance,
            "previous_status": self.previous_status,
            "new_status": self.new_status
        }

    def get_timeline_display(self):
        """Get formatted display for timeline view."""
        icon_mapping = {
            "Created": "🆕",
            "Funds Held": "🔒",
            "Partially Released": "🔓",
            "Fully Released": "✅",
            "Refund Initiated": "↩️",
            "Refund Completed": "💸",
            "Dispute Opened": "⚠️",
            "Dispute Resolved": "✔️",
            "Payout Completed": "💰",
            "Payout Failed": "❌",
            "Auto Released": "⏰"
        }

        return {
            "icon": icon_mapping.get(self.event_type, "📝"),
            "title": self.event_type,
            "description": self.description,
            "timestamp": str(self.timestamp),
            "actor": self.user,
            "severity": self.severity
        }


# =================================================================
# Helper Functions
# =================================================================

def log_escrow_event(
    escrow_account,
    event_type,
    description,
    amount=None,
    amount_type=None,
    old_status=None,
    new_status=None,
    user=None,
    actor_type=None,
    event_data=None,
    **kwargs
):
    """
    Helper function to log an escrow event.

    Args:
        escrow_account: Escrow Account name
        event_type: Type of event
        description: Event description
        amount: Amount involved
        amount_type: Type of amount (Hold, Release, Refund, etc.)
        old_status: Previous status
        new_status: New status
        user: User who triggered event
        actor_type: Actor type
        event_data: Additional data as dict
        **kwargs: Additional fields

    Returns:
        EscrowEvent: Created event document
    """
    event = frappe.get_doc({
        "doctype": "Escrow Event",
        "escrow_account": escrow_account,
        "event_type": event_type,
        "description": description,
        "amount": flt(amount) if amount else 0,
        "amount_type": amount_type,
        "previous_status": old_status,
        "new_status": new_status,
        "user": user or frappe.session.user,
        "actor_type": actor_type,
        "event_data": json.dumps(event_data) if event_data else None,
        **kwargs
    })

    event.insert(ignore_permissions=True)
    return event


def log_status_change(
    escrow_account,
    old_status,
    new_status,
    reason=None,
    user=None
):
    """
    Log a status change event.

    Args:
        escrow_account: Escrow Account name
        old_status: Previous status
        new_status: New status
        reason: Reason for change
        user: User who triggered

    Returns:
        EscrowEvent: Created event document
    """
    description = f"Status changed from {old_status} to {new_status}"
    if reason:
        description += f": {reason}"

    return log_escrow_event(
        escrow_account=escrow_account,
        event_type="Status Change",
        description=description,
        old_status=old_status,
        new_status=new_status,
        status_reason=reason,
        user=user
    )


def log_funds_event(
    escrow_account,
    event_type,
    amount,
    description=None,
    user=None,
    **kwargs
):
    """
    Log a funds movement event.

    Args:
        escrow_account: Escrow Account name
        event_type: Type of event (Funds Held, Partially Released, etc.)
        amount: Amount involved
        description: Event description
        user: User who triggered
        **kwargs: Additional fields

    Returns:
        EscrowEvent: Created event document
    """
    # Determine amount type
    amount_type_mapping = {
        "Funds Held": "Hold",
        "Partially Released": "Release",
        "Fully Released": "Release",
        "Auto Released": "Release",
        "Release Approved": "Release",
        "Refund Initiated": "Refund",
        "Refund Completed": "Refund",
        "Partially Refunded": "Refund"
    }

    amount_type = amount_type_mapping.get(event_type, "Hold")

    if not description:
        escrow = frappe.get_doc("Escrow Account", escrow_account)
        description = f"{event_type}: {escrow.currency} {flt(amount):,.2f}"

    return log_escrow_event(
        escrow_account=escrow_account,
        event_type=event_type,
        description=description,
        amount=amount,
        amount_type=amount_type,
        user=user,
        **kwargs
    )


def log_dispute_event(
    escrow_account,
    event_type,
    description,
    dispute_case=None,
    user=None,
    **kwargs
):
    """
    Log a dispute-related event.

    Args:
        escrow_account: Escrow Account name
        event_type: Type of event (Dispute Opened, etc.)
        description: Event description
        dispute_case: Moderation Case reference
        user: User who triggered
        **kwargs: Additional fields

    Returns:
        EscrowEvent: Created event document
    """
    return log_escrow_event(
        escrow_account=escrow_account,
        event_type=event_type,
        description=description,
        dispute_case=dispute_case,
        user=user,
        **kwargs
    )


def log_payout_event(
    escrow_account,
    event_type,
    description,
    payout_reference=None,
    payout_method=None,
    payout_status=None,
    payout_error=None,
    amount=None,
    user=None,
    **kwargs
):
    """
    Log a payout-related event.

    Args:
        escrow_account: Escrow Account name
        event_type: Type of event (Payout Scheduled, etc.)
        description: Event description
        payout_reference: Payout transaction reference
        payout_method: Payout method
        payout_status: Payout status
        payout_error: Error message if failed
        amount: Payout amount
        user: User who triggered
        **kwargs: Additional fields

    Returns:
        EscrowEvent: Created event document
    """
    return log_escrow_event(
        escrow_account=escrow_account,
        event_type=event_type,
        description=description,
        amount=amount,
        amount_type="Payout",
        payout_reference=payout_reference,
        payout_method=payout_method,
        payout_status=payout_status,
        payout_error=payout_error,
        user=user,
        **kwargs
    )


# =================================================================
# API Endpoints
# =================================================================

@frappe.whitelist()
def get_escrow_events(
    escrow_account,
    event_type=None,
    event_category=None,
    limit=50,
    offset=0
):
    """
    Get events for an escrow account.

    Args:
        escrow_account: Escrow Account name
        event_type: Filter by event type
        event_category: Filter by category
        limit: Number of events to return
        offset: Offset for pagination

    Returns:
        list: List of events
    """
    filters = {"escrow_account": escrow_account}

    if event_type:
        filters["event_type"] = event_type

    if event_category:
        filters["event_category"] = event_category

    events = frappe.get_all(
        "Escrow Event",
        filters=filters,
        fields=[
            "name", "event_type", "event_category", "description",
            "timestamp", "severity", "actor_type", "user",
            "amount", "amount_type", "running_balance",
            "previous_status", "new_status"
        ],
        order_by="timestamp desc",
        limit_page_length=cint(limit),
        limit_start=cint(offset)
    )

    return events


@frappe.whitelist()
def get_escrow_timeline(escrow_account):
    """
    Get timeline view for escrow account.

    Args:
        escrow_account: Escrow Account name

    Returns:
        list: Timeline items
    """
    events = frappe.get_all(
        "Escrow Event",
        filters={"escrow_account": escrow_account},
        fields=[
            "name", "event_type", "description", "timestamp",
            "user", "severity", "amount", "amount_type",
            "previous_status", "new_status"
        ],
        order_by="timestamp desc"
    )

    timeline = []
    for event in events:
        timeline.append({
            "name": event.name,
            "event_type": event.event_type,
            "description": event.description,
            "timestamp": str(event.timestamp),
            "user": event.user,
            "severity": event.severity,
            "amount": event.amount if event.amount else None,
            "amount_type": event.amount_type,
            "status_change": {
                "from": event.previous_status,
                "to": event.new_status
            } if event.previous_status or event.new_status else None
        })

    return timeline


@frappe.whitelist()
def get_event_statistics(escrow_account=None, days=30):
    """
    Get escrow event statistics.

    Args:
        escrow_account: Filter by specific escrow
        days: Number of days to analyze

    Returns:
        dict: Event statistics
    """
    from_date = add_days(nowdate(), -cint(days))

    filters = {"timestamp": [">=", from_date]}
    if escrow_account:
        filters["escrow_account"] = escrow_account

    # Event type breakdown
    type_data = frappe.db.sql("""
        SELECT
            event_type,
            COUNT(*) as count
        FROM `tabEscrow Event`
        WHERE timestamp >= %(from_date)s
        {escrow_filter}
        GROUP BY event_type
        ORDER BY count DESC
    """.format(
        escrow_filter=f"AND escrow_account = %(escrow_account)s" if escrow_account else ""
    ), {"from_date": from_date, "escrow_account": escrow_account}, as_dict=True)

    # Category breakdown
    category_data = frappe.db.sql("""
        SELECT
            event_category,
            COUNT(*) as count
        FROM `tabEscrow Event`
        WHERE timestamp >= %(from_date)s
        {escrow_filter}
        GROUP BY event_category
        ORDER BY count DESC
    """.format(
        escrow_filter=f"AND escrow_account = %(escrow_account)s" if escrow_account else ""
    ), {"from_date": from_date, "escrow_account": escrow_account}, as_dict=True)

    # Severity breakdown
    severity_data = frappe.db.sql("""
        SELECT
            severity,
            COUNT(*) as count
        FROM `tabEscrow Event`
        WHERE timestamp >= %(from_date)s
        {escrow_filter}
        GROUP BY severity
        ORDER BY count DESC
    """.format(
        escrow_filter=f"AND escrow_account = %(escrow_account)s" if escrow_account else ""
    ), {"from_date": from_date, "escrow_account": escrow_account}, as_dict=True)

    return {
        "period_days": cint(days),
        "total_events": sum(t.count for t in type_data),
        "type_breakdown": {t.event_type: t.count for t in type_data},
        "category_breakdown": {c.event_category: c.count for c in category_data},
        "severity_breakdown": {s.severity: s.count for s in severity_data}
    }


@frappe.whitelist()
def create_escrow_event(
    escrow_account,
    event_type,
    description,
    amount=None,
    notes=None,
    event_data=None
):
    """
    Create a manual escrow event.

    Args:
        escrow_account: Escrow Account name
        event_type: Type of event
        description: Event description
        amount: Amount involved
        notes: Notes
        event_data: Additional data JSON

    Returns:
        dict: Created event details
    """
    # Permission check
    if not frappe.has_permission("Escrow Event", "create"):
        frappe.throw(_("Not permitted to create escrow events"))

    event = frappe.get_doc({
        "doctype": "Escrow Event",
        "escrow_account": escrow_account,
        "event_type": event_type,
        "description": description,
        "amount": flt(amount) if amount else 0,
        "notes": notes,
        "event_data": event_data
    })

    event.insert(ignore_permissions=True)

    return {
        "status": "success",
        "name": event.name,
        "event_type": event.event_type
    }


@frappe.whitelist()
def get_recent_errors(escrow_account=None, limit=10):
    """
    Get recent error events.

    Args:
        escrow_account: Filter by escrow
        limit: Number of events to return

    Returns:
        list: Error events
    """
    filters = {"severity": ["in", ["Error", "Critical"]]}

    if escrow_account:
        filters["escrow_account"] = escrow_account

    return frappe.get_all(
        "Escrow Event",
        filters=filters,
        fields=[
            "name", "escrow_account", "event_type", "description",
            "timestamp", "severity", "payout_error", "event_data"
        ],
        order_by="timestamp desc",
        limit_page_length=cint(limit)
    )

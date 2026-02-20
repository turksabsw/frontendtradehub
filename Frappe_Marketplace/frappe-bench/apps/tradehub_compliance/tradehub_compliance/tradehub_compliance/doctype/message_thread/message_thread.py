# Copyright (c) 2026, Trade Hub and contributors
# For license information, please see license.txt

"""
Message Thread DocType for Trade Hub B2B Marketplace.

This module implements conversation management for buyer-seller communications.
Message threads allow organized discussions about products, orders, RFQs,
samples, and general inquiries.

Key features:
- Multi-tenant data isolation via buyer/seller tenant
- Thread types: General, RFQ Discussion, Order Inquiry, Sample Discussion, etc.
- Status workflow: Active -> Pending -> Closed -> Archived
- Related document linking (RFQ, Order, Sample Request, Quotation)
- Activity tracking with message counts and last message info
- Auto-close functionality for inactive threads
- Notification settings per thread
- fetch_from pattern for buyer, seller, and related document information
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import nowdate, now_datetime, getdate, add_days, cint


# Valid status transitions
STATUS_TRANSITIONS = {
    "Active": ["Pending", "Closed", "Archived"],
    "Pending": ["Active", "Closed", "Archived"],
    "Closed": ["Active", "Archived"],
    "Archived": ["Active"]
}

# Thread type to related doctype mapping
THREAD_TYPE_MAPPING = {
    "RFQ Discussion": "RFQ",
    "Order Inquiry": "Order",
    "Sample Discussion": "Sample Request",
    "Quotation Discussion": "Quotation"
}


class MessageThread(Document):
    """
    Message Thread DocType for conversation management.

    Each Message Thread represents a conversation between a buyer and seller
    or between a user and support. Features include:
    - Link to Buyer Profile and Seller Profile with auto-fetched info
    - Multi-tenant isolation via buyer's tenant
    - Thread types for organizing conversations
    - Status workflow tracking
    - Related document linking
    - Activity metrics (message count, last message info)
    - Notification and auto-close settings
    """

    def before_insert(self):
        """Set defaults before inserting a new thread."""
        self.set_default_dates()
        self.set_tenant_from_participants()

    def validate(self):
        """Validate thread data before saving."""
        self.validate_participants()
        self.validate_related_documents()
        self.validate_status_transition()
        self.validate_tenant_isolation()
        self.validate_auto_close_days()
        self.update_dates_on_status_change()
        self.set_thread_type_from_reference()

    def on_update(self):
        """Actions after thread is updated."""
        self.clear_thread_cache()

    def on_trash(self):
        """Actions before thread is deleted."""
        self.check_for_linked_messages()

    # =========================================================================
    # DEFAULT SETTINGS
    # =========================================================================

    def set_default_dates(self):
        """Set default dates for new threads."""
        if not self.created_date:
            self.created_date = nowdate()

    def set_tenant_from_participants(self):
        """
        Set tenant from buyer or seller if not already set.

        Priority: buyer.tenant > seller.tenant
        """
        if self.tenant:
            return

        if self.buyer:
            buyer_tenant = frappe.db.get_value("Buyer Profile", self.buyer, "tenant")
            if buyer_tenant:
                self.tenant = buyer_tenant
                return

        if self.seller:
            seller_tenant = frappe.db.get_value("Seller Profile", self.seller, "tenant")
            if seller_tenant:
                self.tenant = seller_tenant

    # =========================================================================
    # VALIDATION METHODS
    # =========================================================================

    def validate_participants(self):
        """Validate that at least one participant is specified."""
        if not self.buyer and not self.seller:
            frappe.throw(
                _("At least one participant (Buyer or Seller) must be specified")
            )

        # Warn if only one participant for buyer-seller thread types
        if self.thread_type in ["RFQ Discussion", "Order Inquiry", "Sample Discussion",
                                 "Quotation Discussion", "Negotiation"]:
            if not self.buyer or not self.seller:
                frappe.msgprint(
                    _("Both Buyer and Seller are recommended for {0} threads").format(
                        self.thread_type
                    ),
                    indicator='orange',
                    alert=True
                )

    def validate_related_documents(self):
        """Validate related document links are consistent."""
        # If RFQ is set, validate it exists
        if self.rfq:
            if not frappe.db.exists("RFQ", self.rfq):
                frappe.throw(_("RFQ {0} does not exist").format(self.rfq))

        # If Order is set, validate it exists
        if self.order:
            if not frappe.db.exists("Order", self.order):
                frappe.throw(_("Order {0} does not exist").format(self.order))

        # If Sample Request is set, validate it exists
        if self.sample_request:
            if not frappe.db.exists("Sample Request", self.sample_request):
                frappe.throw(
                    _("Sample Request {0} does not exist").format(self.sample_request)
                )

        # If Quotation is set, validate it exists
        if self.quotation:
            if not frappe.db.exists("Quotation", self.quotation):
                frappe.throw(_("Quotation {0} does not exist").format(self.quotation))

    def validate_status_transition(self):
        """Validate status transitions are valid."""
        if self.is_new():
            return

        old_status = frappe.db.get_value("Message Thread", self.name, "status")
        if old_status and old_status != self.status:
            valid_transitions = STATUS_TRANSITIONS.get(old_status, [])
            if self.status not in valid_transitions:
                frappe.throw(
                    _("Cannot change status from {0} to {1}. "
                      "Valid transitions are: {2}").format(
                        old_status, self.status,
                        ", ".join(valid_transitions) if valid_transitions else "None"
                    )
                )

    def validate_tenant_isolation(self):
        """
        Validate that thread belongs to user's tenant.

        Inherits tenant from buyer/seller to ensure multi-tenant data isolation.
        """
        if not self.tenant:
            return

        # System Manager can access all tenants
        if "System Manager" in frappe.get_roles():
            return

        # Get current user's tenant
        from tradehub_core.tradehub_core.utils.tenant import get_current_tenant
        current_tenant = get_current_tenant()

        if current_tenant and self.tenant != current_tenant:
            frappe.throw(
                _("Access denied: You can only access message threads in your tenant")
            )

    def validate_auto_close_days(self):
        """Validate auto-close days is a reasonable value."""
        if cint(self.auto_close_days) < 0:
            frappe.throw(_("Auto-Close Days cannot be negative"))

        if cint(self.auto_close_days) > 365:
            frappe.msgprint(
                _("Auto-Close Days is set to {0}. This is a long time for thread inactivity.").format(
                    self.auto_close_days
                ),
                indicator='orange',
                alert=True
            )

    # =========================================================================
    # STATUS MANAGEMENT
    # =========================================================================

    def update_dates_on_status_change(self):
        """Update date fields based on status changes."""
        if not self.is_new():
            old_status = frappe.db.get_value("Message Thread", self.name, "status")
            if old_status == self.status:
                return

        today = nowdate()

        if self.status == "Closed":
            if not self.closed_date:
                self.closed_date = today

        elif self.status == "Archived":
            if not self.archived_date:
                self.archived_date = today

        elif self.status == "Active":
            # Clear dates when reactivating
            if self.closed_date:
                self.closed_date = None
            if self.archived_date:
                self.archived_date = None

    def set_status(self, new_status):
        """
        Change the status of the message thread.

        Args:
            new_status: The new status to set

        Returns:
            bool: True if status was changed successfully
        """
        valid_transitions = STATUS_TRANSITIONS.get(self.status, [])
        if new_status not in valid_transitions:
            frappe.throw(
                _("Cannot change status from {0} to {1}").format(
                    self.status, new_status
                )
            )

        self.status = new_status
        self.save()
        return True

    def close_thread(self):
        """Close the message thread."""
        return self.set_status("Closed")

    def archive_thread(self):
        """Archive the message thread."""
        return self.set_status("Archived")

    def reactivate_thread(self):
        """Reactivate a closed or archived thread."""
        return self.set_status("Active")

    def set_pending(self):
        """Set thread to pending status."""
        return self.set_status("Pending")

    # =========================================================================
    # THREAD TYPE MANAGEMENT
    # =========================================================================

    def set_thread_type_from_reference(self):
        """
        Auto-set thread type based on reference document.

        Only sets if thread_type is 'General' and a related document is linked.
        """
        if self.thread_type != "General":
            return

        if self.rfq:
            self.thread_type = "RFQ Discussion"
        elif self.order:
            self.thread_type = "Order Inquiry"
        elif self.sample_request:
            self.thread_type = "Sample Discussion"
        elif self.quotation:
            self.thread_type = "Quotation Discussion"

    # =========================================================================
    # MESSAGE TRACKING
    # =========================================================================

    def update_message_stats(self, message_content=None, message_by=None):
        """
        Update message statistics when a new message is added.

        Args:
            message_content: Content of the new message (for preview)
            message_by: Who sent the message

        Returns:
            dict: Updated statistics
        """
        self.message_count = cint(self.message_count) + 1
        self.last_message_date = now_datetime()

        if message_by:
            self.last_message_by = message_by

        if message_content:
            # Truncate preview to 200 characters
            preview = str(message_content)[:200]
            if len(str(message_content)) > 200:
                preview += "..."
            self.last_message_preview = preview

        # Reactivate thread if closed/archived
        if self.status in ["Closed", "Archived"]:
            self.status = "Active"
            self.closed_date = None
            self.archived_date = None

        self.save(ignore_permissions=True)

        return {
            "message_count": self.message_count,
            "last_message_date": self.last_message_date,
            "last_message_by": self.last_message_by
        }

    def increment_unread_count(self, count=1):
        """
        Increment unread message count.

        Args:
            count: Number to increment by (default 1)
        """
        self.unread_count = cint(self.unread_count) + cint(count)
        self.db_set("unread_count", self.unread_count)

    def mark_as_read(self):
        """Mark all messages in thread as read."""
        self.unread_count = 0
        self.db_set("unread_count", 0)

    # =========================================================================
    # AUTO-CLOSE FUNCTIONALITY
    # =========================================================================

    def check_auto_close(self):
        """
        Check if thread should be auto-closed due to inactivity.

        Returns:
            bool: True if thread was auto-closed
        """
        if self.status != "Active":
            return False

        if not self.auto_close_days or cint(self.auto_close_days) <= 0:
            return False

        if not self.last_message_date:
            return False

        last_activity = getdate(self.last_message_date)
        threshold_date = add_days(nowdate(), -cint(self.auto_close_days))

        if last_activity < getdate(threshold_date):
            self.status = "Closed"
            self.closed_date = nowdate()
            self.internal_notes = (self.internal_notes or "") + \
                f"\nAuto-closed due to {self.auto_close_days} days of inactivity on {nowdate()}"
            self.save(ignore_permissions=True)
            return True

        return False

    # =========================================================================
    # DELETION CHECKS
    # =========================================================================

    def check_for_linked_messages(self):
        """Check if thread has messages before deletion."""
        if cint(self.message_count) > 0:
            frappe.msgprint(
                _("Warning: This thread has {0} messages that will be orphaned").format(
                    self.message_count
                ),
                indicator='orange',
                alert=True
            )

    # =========================================================================
    # CACHE MANAGEMENT
    # =========================================================================

    def clear_thread_cache(self):
        """Clear cached thread data."""
        cache_keys = [
            f"message_thread:{self.name}",
        ]

        if self.buyer:
            cache_keys.append(f"buyer_threads:{self.buyer}")

        if self.seller:
            cache_keys.append(f"seller_threads:{self.seller}")

        for key in cache_keys:
            frappe.cache().delete_value(key)


# =============================================================================
# WHITELISTED API FUNCTIONS
# =============================================================================


@frappe.whitelist()
def get_threads_for_buyer(buyer, status=None, thread_type=None):
    """
    Get all message threads for a buyer.

    Args:
        buyer: The Buyer Profile name
        status: Optional status filter
        thread_type: Optional thread type filter

    Returns:
        list: List of thread records
    """
    filters = {"buyer": buyer}

    if status:
        filters["status"] = status

    if thread_type:
        filters["thread_type"] = thread_type

    threads = frappe.get_all(
        "Message Thread",
        filters=filters,
        fields=[
            "name", "subject", "status", "thread_type", "priority",
            "seller_name", "seller_company", "message_count",
            "last_message_date", "last_message_preview", "unread_count",
            "is_starred"
        ],
        order_by="last_message_date desc"
    )

    return threads


@frappe.whitelist()
def get_threads_for_seller(seller, status=None, thread_type=None):
    """
    Get all message threads for a seller.

    Args:
        seller: The Seller Profile name
        status: Optional status filter
        thread_type: Optional thread type filter

    Returns:
        list: List of thread records
    """
    filters = {"seller": seller}

    if status:
        filters["status"] = status

    if thread_type:
        filters["thread_type"] = thread_type

    threads = frappe.get_all(
        "Message Thread",
        filters=filters,
        fields=[
            "name", "subject", "status", "thread_type", "priority",
            "buyer_name", "buyer_company", "message_count",
            "last_message_date", "last_message_preview", "unread_count",
            "is_starred"
        ],
        order_by="last_message_date desc"
    )

    return threads


@frappe.whitelist()
def create_thread(subject, buyer=None, seller=None, thread_type="General",
                  rfq=None, order=None, sample_request=None, quotation=None,
                  initiator_type="Buyer"):
    """
    Create a new message thread.

    Args:
        subject: Thread subject
        buyer: Optional Buyer Profile name
        seller: Optional Seller Profile name
        thread_type: Type of thread (default General)
        rfq: Optional RFQ link
        order: Optional Order link
        sample_request: Optional Sample Request link
        quotation: Optional Quotation link
        initiator_type: Who started the thread (Buyer/Seller/System)

    Returns:
        dict: Created thread info
    """
    doc = frappe.new_doc("Message Thread")
    doc.subject = subject
    doc.buyer = buyer
    doc.seller = seller
    doc.thread_type = thread_type
    doc.initiator_type = initiator_type
    doc.rfq = rfq
    doc.order = order
    doc.sample_request = sample_request
    doc.quotation = quotation

    doc.insert()

    return {
        "name": doc.name,
        "message": _("Message thread created successfully"),
        "status": doc.status,
        "thread_type": doc.thread_type
    }


@frappe.whitelist()
def update_thread_status(thread_name, new_status):
    """
    Update the status of a message thread.

    Args:
        thread_name: The Message Thread document name
        new_status: The new status to set

    Returns:
        dict: Updated thread info
    """
    doc = frappe.get_doc("Message Thread", thread_name)
    doc.status = new_status
    doc.save()

    return {
        "name": doc.name,
        "status": doc.status,
        "message": _("Thread status updated to {0}").format(new_status)
    }


@frappe.whitelist()
def close_thread(thread_name):
    """
    Close a message thread.

    Args:
        thread_name: The Message Thread document name

    Returns:
        dict: Success message
    """
    doc = frappe.get_doc("Message Thread", thread_name)
    doc.close_thread()

    return {
        "success": True,
        "message": _("Thread closed successfully")
    }


@frappe.whitelist()
def archive_thread(thread_name):
    """
    Archive a message thread.

    Args:
        thread_name: The Message Thread document name

    Returns:
        dict: Success message
    """
    doc = frappe.get_doc("Message Thread", thread_name)
    doc.archive_thread()

    return {
        "success": True,
        "message": _("Thread archived successfully")
    }


@frappe.whitelist()
def reactivate_thread(thread_name):
    """
    Reactivate a closed or archived thread.

    Args:
        thread_name: The Message Thread document name

    Returns:
        dict: Success message
    """
    doc = frappe.get_doc("Message Thread", thread_name)
    doc.reactivate_thread()

    return {
        "success": True,
        "message": _("Thread reactivated successfully")
    }


@frappe.whitelist()
def mark_thread_as_read(thread_name):
    """
    Mark all messages in a thread as read.

    Args:
        thread_name: The Message Thread document name

    Returns:
        dict: Success message
    """
    doc = frappe.get_doc("Message Thread", thread_name)
    doc.mark_as_read()

    return {
        "success": True,
        "message": _("Thread marked as read")
    }


@frappe.whitelist()
def toggle_starred(thread_name):
    """
    Toggle the starred status of a thread.

    Args:
        thread_name: The Message Thread document name

    Returns:
        dict: Updated starred status
    """
    doc = frappe.get_doc("Message Thread", thread_name)
    doc.is_starred = 0 if doc.is_starred else 1
    doc.save()

    return {
        "success": True,
        "is_starred": doc.is_starred,
        "message": _("Thread starred") if doc.is_starred else _("Thread unstarred")
    }


@frappe.whitelist()
def get_threads_for_document(doctype, docname):
    """
    Get all threads related to a specific document.

    Args:
        doctype: The DocType name (RFQ, Order, etc.)
        docname: The document name

    Returns:
        list: List of related threads
    """
    field_map = {
        "RFQ": "rfq",
        "Order": "order",
        "Sample Request": "sample_request",
        "Quotation": "quotation"
    }

    field_name = field_map.get(doctype)
    if not field_name:
        # Try reference_doctype/reference_name
        threads = frappe.get_all(
            "Message Thread",
            filters={
                "reference_doctype": doctype,
                "reference_name": docname
            },
            fields=[
                "name", "subject", "status", "thread_type",
                "message_count", "last_message_date", "buyer_name", "seller_name"
            ],
            order_by="last_message_date desc"
        )
    else:
        threads = frappe.get_all(
            "Message Thread",
            filters={field_name: docname},
            fields=[
                "name", "subject", "status", "thread_type",
                "message_count", "last_message_date", "buyer_name", "seller_name"
            ],
            order_by="last_message_date desc"
        )

    return threads


@frappe.whitelist()
def get_unread_thread_count(user_type, user_profile):
    """
    Get count of threads with unread messages.

    Args:
        user_type: 'buyer' or 'seller'
        user_profile: The profile name

    Returns:
        dict: Unread counts
    """
    field_name = "buyer" if user_type == "buyer" else "seller"

    total_unread = frappe.db.sql("""
        SELECT COUNT(*) as thread_count, SUM(unread_count) as message_count
        FROM `tabMessage Thread`
        WHERE {field} = %s AND unread_count > 0 AND status = 'Active'
    """.format(field=field_name), (user_profile,), as_dict=True)[0]

    return {
        "threads_with_unread": cint(total_unread.get("thread_count", 0)),
        "total_unread_messages": cint(total_unread.get("message_count", 0))
    }


@frappe.whitelist()
def auto_close_inactive_threads():
    """
    Scheduled job to auto-close inactive threads.

    This function should be called by a scheduler job to automatically
    close threads that have been inactive for their configured auto_close_days.

    Returns:
        dict: Results of the auto-close operation
    """
    threads = frappe.get_all(
        "Message Thread",
        filters={
            "status": "Active",
            "auto_close_days": [">", 0]
        },
        fields=["name", "auto_close_days", "last_message_date"]
    )

    closed_count = 0
    for thread_data in threads:
        doc = frappe.get_doc("Message Thread", thread_data.name)
        if doc.check_auto_close():
            closed_count += 1

    return {
        "checked": len(threads),
        "closed": closed_count,
        "message": _("{0} threads auto-closed").format(closed_count)
    }


@frappe.whitelist()
def get_thread_statistics(buyer=None, seller=None, date_from=None, date_to=None):
    """
    Get message thread statistics.

    Args:
        buyer: Optional buyer filter
        seller: Optional seller filter
        date_from: Start date for statistics
        date_to: End date for statistics

    Returns:
        dict: Statistics including counts, activity metrics, etc.
    """
    filters = {}

    if buyer:
        filters["buyer"] = buyer
    if seller:
        filters["seller"] = seller
    if date_from:
        filters["created_date"] = [">=", date_from]
    if date_to:
        if "created_date" in filters:
            filters["created_date"] = ["between", [date_from, date_to]]
        else:
            filters["created_date"] = ["<=", date_to]

    # Get counts by status
    status_counts = frappe.db.get_all(
        "Message Thread",
        filters=filters,
        fields=["status", "count(*) as count"],
        group_by="status"
    )

    status_dict = {s.status: s.count for s in status_counts}

    # Get counts by thread type
    type_counts = frappe.db.get_all(
        "Message Thread",
        filters=filters,
        fields=["thread_type", "count(*) as count"],
        group_by="thread_type"
    )

    type_dict = {t.thread_type: t.count for t in type_counts}

    # Get total message count
    total_messages = frappe.db.sql("""
        SELECT SUM(message_count) as total
        FROM `tabMessage Thread`
        WHERE 1=1 {conditions}
    """.format(conditions=get_filter_conditions(filters)))[0][0] or 0

    return {
        "total_threads": sum(status_dict.values()),
        "status_breakdown": status_dict,
        "type_breakdown": type_dict,
        "total_messages": cint(total_messages),
        "active_threads": status_dict.get("Active", 0),
        "pending_threads": status_dict.get("Pending", 0)
    }


def get_filter_conditions(filters):
    """Helper function to build SQL filter conditions."""
    conditions = []

    if filters.get("buyer"):
        conditions.append(f"AND buyer = '{filters['buyer']}'")

    if filters.get("seller"):
        conditions.append(f"AND seller = '{filters['seller']}'")

    return " ".join(conditions)

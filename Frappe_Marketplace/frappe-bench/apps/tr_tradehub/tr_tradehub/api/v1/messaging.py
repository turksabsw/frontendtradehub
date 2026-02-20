# Copyright (c) 2026, Trade Hub and contributors
# For license information, please see license.txt

"""
Trade Hub Messaging API v1.

This module provides a comprehensive REST API for the messaging system
in the Trade Hub B2B marketplace. It enables communication between
buyers and sellers through conversation threads.

Key Features:
- Thread management (create, list, close, archive)
- Message sending and retrieval
- Read receipts and delivery tracking
- Multi-tenant data isolation
- Search and filtering capabilities
- Statistics and analytics

Usage Flow:
1. create_thread() - Start a new conversation with buyer/seller
2. send_message() - Send messages within a thread
3. get_thread_messages() - Retrieve messages in a thread
4. mark_messages_as_read() - Mark messages as read
5. get_my_threads() - List user's conversation threads
6. search_messages() - Search across messages

Thread Types:
- General: General inquiries and discussions
- RFQ Discussion: Discussions related to RFQs
- Order Inquiry: Order-related conversations
- Sample Discussion: Sample request discussions
- Quotation Discussion: Quotation negotiations
- Support: Customer support threads
- Negotiation: Price/terms negotiations
- Complaint: Issue reporting
- Feedback: Review and feedback

Message Types:
- Text: Plain text messages
- Rich Text: HTML formatted messages
- System Notification: Auto-generated notifications
- Auto Reply: Automated responses
- Quotation Response: Quotation-related updates
- RFQ Response: RFQ-related updates
- Order Update: Order status updates
- Shipping Update: Shipment tracking updates
"""

import json
from typing import Optional, Dict, Any, List

import frappe
from frappe import _
from frappe.utils import (
    cint, flt, nowdate, now_datetime, get_datetime, getdate, add_days
)


# =============================================================================
# CONSTANTS
# =============================================================================

# Default pagination limits
DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100

# Thread Types
THREAD_TYPES = [
    "General", "RFQ Discussion", "Order Inquiry", "Sample Discussion",
    "Quotation Discussion", "Support", "Negotiation", "Complaint", "Feedback"
]

# Thread Statuses
THREAD_STATUSES = ["Active", "Pending", "Closed", "Archived"]

# Message Types
MESSAGE_TYPES = [
    "Text", "Rich Text", "System Notification", "Auto Reply",
    "Quotation Response", "RFQ Response", "Order Update", "Shipping Update"
]

# Message Statuses
MESSAGE_STATUSES = ["Draft", "Sent", "Delivered", "Read", "Failed"]

# System message types (auto-generated)
SYSTEM_MESSAGE_TYPES = [
    "System Notification", "Auto Reply", "Quotation Response",
    "RFQ Response", "Order Update", "Shipping Update"
]

# Priority levels
PRIORITY_LEVELS = ["Low", "Normal", "High", "Urgent"]


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def get_current_tenant() -> Optional[str]:
    """Get current user's tenant."""
    try:
        from tr_tradehub.utils.tenant import get_current_tenant as _get_tenant
        return _get_tenant()
    except ImportError:
        return frappe.db.get_value("User", frappe.session.user, "tenant")


def validate_page_params(limit: int, offset: int) -> tuple:
    """Validate and sanitize pagination parameters."""
    limit = min(max(cint(limit), 1), MAX_PAGE_SIZE) if limit else DEFAULT_PAGE_SIZE
    offset = max(cint(offset), 0)
    return limit, offset


def get_user_buyer_profile() -> Optional[str]:
    """Get the Buyer Profile for the current user."""
    return frappe.db.get_value(
        "Buyer Profile",
        {"user": frappe.session.user, "status": ["in", ["Active", "Verified"]]},
        "name"
    )


def get_user_seller_profile() -> Optional[str]:
    """Get the Seller Profile for the current user."""
    return frappe.db.get_value(
        "Seller Profile",
        {"user": frappe.session.user, "status": ["in", ["Active", "Verified"]]},
        "name"
    )


def get_user_profile_info() -> Dict[str, Any]:
    """
    Get the current user's profile information.

    Returns:
        dict: {
            "user_type": "buyer" | "seller" | "system_manager",
            "profile_name": str,
            "profile_display_name": str
        }
    """
    if "System Manager" in frappe.get_roles():
        return {
            "user_type": "system_manager",
            "profile_name": None,
            "profile_display_name": frappe.session.user
        }

    buyer = get_user_buyer_profile()
    if buyer:
        buyer_name = frappe.db.get_value("Buyer Profile", buyer, "buyer_name")
        return {
            "user_type": "buyer",
            "profile_name": buyer,
            "profile_display_name": buyer_name
        }

    seller = get_user_seller_profile()
    if seller:
        seller_name = frappe.db.get_value("Seller Profile", seller, "seller_name")
        return {
            "user_type": "seller",
            "profile_name": seller,
            "profile_display_name": seller_name
        }

    return {
        "user_type": "unknown",
        "profile_name": None,
        "profile_display_name": frappe.session.user
    }


def validate_thread_access(thread_name: str) -> bool:
    """
    Validate that current user has access to the thread.

    Args:
        thread_name: The Message Thread document name

    Returns:
        bool: True if user has access

    Raises:
        frappe.PermissionError: If user doesn't have access
    """
    if "System Manager" in frappe.get_roles():
        return True

    thread = frappe.db.get_value(
        "Message Thread",
        thread_name,
        ["buyer", "seller", "tenant"],
        as_dict=True
    )

    if not thread:
        frappe.throw(_("Thread not found"))

    user_info = get_user_profile_info()

    if user_info["user_type"] == "buyer" and thread.buyer == user_info["profile_name"]:
        return True

    if user_info["user_type"] == "seller" and thread.seller == user_info["profile_name"]:
        return True

    # Check tenant isolation
    current_tenant = get_current_tenant()
    if current_tenant and thread.tenant != current_tenant:
        frappe.throw(_("Access denied: Thread belongs to different tenant"))

    frappe.throw(_("Access denied: You are not a participant in this thread"))


def parse_json_param(param: Any, param_name: str) -> Any:
    """Parse a JSON parameter if it's a string."""
    if param is None:
        return None
    if isinstance(param, str):
        try:
            return json.loads(param)
        except json.JSONDecodeError:
            frappe.throw(_("{0} must be valid JSON").format(param_name))
    return param


# =============================================================================
# THREAD LISTING AND SEARCH APIs
# =============================================================================

@frappe.whitelist()
def get_thread_list(
    buyer: str = None,
    seller: str = None,
    status: str = None,
    thread_type: str = None,
    priority: str = None,
    tenant: str = None,
    search: str = None,
    rfq: str = None,
    order: str = None,
    limit: int = None,
    offset: int = None,
    starred_only: int = 0,
    with_unread: int = 0
) -> Dict[str, Any]:
    """
    Get a paginated list of message threads with optional filters.

    This is the primary endpoint for listing conversation threads,
    used by both buyers and sellers to manage their conversations.

    Args:
        buyer: Filter by Buyer Profile name
        seller: Filter by Seller Profile name
        status: Filter by thread status (Active, Pending, Closed, Archived)
        thread_type: Filter by thread type
        priority: Filter by priority level
        tenant: Filter by tenant (multi-tenant support)
        search: Search in subject, buyer name, seller name
        rfq: Filter by related RFQ
        order: Filter by related Order
        limit: Number of records per page (default 20, max 100)
        offset: Starting position for pagination
        starred_only: Only return starred threads
        with_unread: Only return threads with unread messages

    Returns:
        dict: {
            "success": True,
            "threads": [...],
            "count": int,
            "limit": int,
            "offset": int,
            "has_more": bool
        }
    """
    limit, offset = validate_page_params(limit, offset)

    filters = {}
    or_filters = {}

    # Apply filters
    if buyer:
        filters["buyer"] = buyer
    if seller:
        filters["seller"] = seller
    if status:
        if status in THREAD_STATUSES:
            filters["status"] = status
        else:
            frappe.throw(_("Invalid status. Must be one of: {0}").format(
                ", ".join(THREAD_STATUSES)
            ))
    if thread_type:
        filters["thread_type"] = thread_type
    if priority:
        filters["priority"] = priority
    if rfq:
        filters["rfq"] = rfq
    if order:
        filters["order"] = order
    if cint(starred_only):
        filters["is_starred"] = 1
    if cint(with_unread):
        filters["unread_count"] = [">", 0]

    # Apply tenant filter
    if tenant:
        filters["tenant"] = tenant
    elif "System Manager" not in frappe.get_roles():
        current_tenant = get_current_tenant()
        if current_tenant:
            filters["tenant"] = current_tenant

        # Filter by user's profile
        user_info = get_user_profile_info()
        if user_info["user_type"] == "buyer":
            filters["buyer"] = user_info["profile_name"]
        elif user_info["user_type"] == "seller":
            filters["seller"] = user_info["profile_name"]

    # Search filter
    if search:
        or_filters = [
            ["subject", "like", f"%{search}%"],
            ["buyer_name", "like", f"%{search}%"],
            ["seller_name", "like", f"%{search}%"],
            ["buyer_company", "like", f"%{search}%"],
            ["seller_company", "like", f"%{search}%"]
        ]

    # Get threads
    threads = frappe.get_all(
        "Message Thread",
        filters=filters,
        or_filters=or_filters if or_filters else None,
        fields=[
            "name", "subject", "status", "thread_type", "priority",
            "is_starred", "unread_count", "message_count",
            "buyer", "buyer_name", "buyer_company",
            "seller", "seller_name", "seller_company",
            "last_message_date", "last_message_by", "last_message_preview",
            "rfq", "rfq_title", "order", "order_status",
            "notification_enabled", "tenant"
        ],
        order_by="last_message_date desc, creation desc",
        start=offset,
        page_length=limit + 1
    )

    has_more = len(threads) > limit
    if has_more:
        threads = threads[:limit]

    return {
        "success": True,
        "threads": threads,
        "count": len(threads),
        "limit": limit,
        "offset": offset,
        "has_more": has_more
    }


@frappe.whitelist()
def get_my_threads(
    status: str = None,
    thread_type: str = None,
    search: str = None,
    limit: int = None,
    offset: int = None,
    starred_only: int = 0,
    with_unread: int = 0
) -> Dict[str, Any]:
    """
    Get threads for the current user (buyer or seller).

    Convenience endpoint that automatically filters by user's profile.

    Args:
        status: Filter by status
        thread_type: Filter by thread type
        search: Search in subject and participant names
        limit: Number of records per page
        offset: Starting position
        starred_only: Only return starred threads
        with_unread: Only return threads with unread messages

    Returns:
        dict: List of threads for current user
    """
    user_info = get_user_profile_info()

    if user_info["user_type"] == "buyer":
        return get_thread_list(
            buyer=user_info["profile_name"],
            status=status,
            thread_type=thread_type,
            search=search,
            limit=limit,
            offset=offset,
            starred_only=starred_only,
            with_unread=with_unread
        )
    elif user_info["user_type"] == "seller":
        return get_thread_list(
            seller=user_info["profile_name"],
            status=status,
            thread_type=thread_type,
            search=search,
            limit=limit,
            offset=offset,
            starred_only=starred_only,
            with_unread=with_unread
        )
    elif user_info["user_type"] == "system_manager":
        return get_thread_list(
            status=status,
            thread_type=thread_type,
            search=search,
            limit=limit,
            offset=offset,
            starred_only=starred_only,
            with_unread=with_unread
        )
    else:
        frappe.throw(_("You must be a buyer or seller to access threads"))


@frappe.whitelist()
def get_thread_details(thread_name: str) -> Dict[str, Any]:
    """
    Get detailed information about a specific thread.

    Returns the full thread document with messages and participant info.

    Args:
        thread_name: The Message Thread document name

    Returns:
        dict: {
            "success": True,
            "thread": {...},
            "messages": [...],
            "participant_info": {...}
        }
    """
    if not thread_name:
        frappe.throw(_("Thread name is required"))

    validate_thread_access(thread_name)

    thread = frappe.get_doc("Message Thread", thread_name)

    # Get messages
    messages = frappe.get_all(
        "Message",
        filters={"message_thread": thread_name, "is_deleted": 0},
        fields=[
            "name", "message_type", "status", "sender_type",
            "sender_user", "sender_name", "buyer", "buyer_name",
            "seller", "seller_name", "content", "plain_text_content",
            "has_attachments", "attachments", "sent_at", "is_read",
            "read_at", "is_edited", "edited_at", "is_system_message",
            "reply_to", "reply_to_preview"
        ],
        order_by="sent_at asc",
        limit_page_length=100
    )

    # Get participant info
    participant_info = {
        "buyer": None,
        "seller": None
    }

    if thread.buyer:
        participant_info["buyer"] = frappe.db.get_value(
            "Buyer Profile",
            thread.buyer,
            ["name", "buyer_name", "company_name", "email", "phone"],
            as_dict=True
        )

    if thread.seller:
        participant_info["seller"] = frappe.db.get_value(
            "Seller Profile",
            thread.seller,
            ["name", "seller_name", "company_name", "email", "phone"],
            as_dict=True
        )

    return {
        "success": True,
        "thread": thread.as_dict(),
        "messages": messages,
        "message_count": len(messages),
        "participant_info": participant_info
    }


# =============================================================================
# THREAD CREATION AND MANAGEMENT APIs
# =============================================================================

@frappe.whitelist()
def create_thread(
    subject: str,
    recipient_type: str,
    recipient: str,
    thread_type: str = "General",
    priority: str = "Normal",
    initial_message: str = None,
    rfq: str = None,
    order: str = None,
    sample_request: str = None,
    quotation: str = None
) -> Dict[str, Any]:
    """
    Create a new message thread.

    Creates a new conversation thread between the current user
    and the specified recipient.

    Args:
        subject: Thread subject (required)
        recipient_type: Type of recipient ('buyer' or 'seller')
        recipient: Recipient profile name (Buyer Profile or Seller Profile)
        thread_type: Type of thread (General, RFQ Discussion, etc.)
        priority: Priority level (Low, Normal, High, Urgent)
        initial_message: Optional first message to send
        rfq: Optional related RFQ
        order: Optional related Order
        sample_request: Optional related Sample Request
        quotation: Optional related Quotation

    Returns:
        dict: {
            "success": True,
            "thread_name": str,
            "status": str,
            "message": str
        }
    """
    if not subject:
        frappe.throw(_("Subject is required"))
    if not recipient_type:
        frappe.throw(_("Recipient type is required"))
    if not recipient:
        frappe.throw(_("Recipient is required"))

    user_info = get_user_profile_info()

    if user_info["user_type"] not in ["buyer", "seller", "system_manager"]:
        frappe.throw(_("You must be a buyer or seller to create threads"))

    # Determine initiator and recipient
    doc = frappe.new_doc("Message Thread")
    doc.subject = subject
    doc.thread_type = thread_type
    doc.priority = priority
    doc.status = "Active"

    if user_info["user_type"] == "buyer":
        doc.buyer = user_info["profile_name"]
        doc.initiator_type = "Buyer"
        doc.recipient_type = "Seller" if recipient_type.lower() == "seller" else "Support"
        if recipient_type.lower() == "seller":
            doc.seller = recipient
    elif user_info["user_type"] == "seller":
        doc.seller = user_info["profile_name"]
        doc.initiator_type = "Seller"
        doc.recipient_type = "Buyer" if recipient_type.lower() == "buyer" else "Support"
        if recipient_type.lower() == "buyer":
            doc.buyer = recipient
    else:
        # System Manager - can set both
        doc.initiator_type = "System"
        if recipient_type.lower() == "buyer":
            doc.buyer = recipient
            doc.recipient_type = "Buyer"
        elif recipient_type.lower() == "seller":
            doc.seller = recipient
            doc.recipient_type = "Seller"

    # Set related documents
    if rfq:
        doc.rfq = rfq
    if order:
        doc.order = order
    if sample_request:
        doc.sample_request = sample_request
    if quotation:
        doc.quotation = quotation

    doc.insert()

    # Send initial message if provided
    if initial_message:
        send_message(
            message_thread=doc.name,
            content=initial_message,
            message_type="Text"
        )

    return {
        "success": True,
        "thread_name": doc.name,
        "status": doc.status,
        "message": _("Thread created successfully")
    }


@frappe.whitelist()
def start_conversation_with_seller(
    seller: str,
    subject: str,
    message: str,
    thread_type: str = "General",
    rfq: str = None,
    order: str = None
) -> Dict[str, Any]:
    """
    Start a new conversation with a seller.

    Convenience endpoint for buyers to initiate contact with sellers.

    Args:
        seller: Seller Profile name
        subject: Thread subject
        message: Initial message content
        thread_type: Type of thread (default: General)
        rfq: Optional related RFQ
        order: Optional related Order

    Returns:
        dict: Thread creation result
    """
    user_info = get_user_profile_info()

    if user_info["user_type"] != "buyer":
        frappe.throw(_("Only buyers can use this endpoint"))

    # Check if seller exists and is valid
    seller_status = frappe.db.get_value("Seller Profile", seller, "status")
    if not seller_status or seller_status not in ["Active", "Verified"]:
        frappe.throw(_("Seller not found or inactive"))

    return create_thread(
        subject=subject,
        recipient_type="seller",
        recipient=seller,
        thread_type=thread_type,
        initial_message=message,
        rfq=rfq,
        order=order
    )


@frappe.whitelist()
def start_conversation_with_buyer(
    buyer: str,
    subject: str,
    message: str,
    thread_type: str = "General",
    rfq: str = None,
    order: str = None
) -> Dict[str, Any]:
    """
    Start a new conversation with a buyer.

    Convenience endpoint for sellers to initiate contact with buyers.

    Args:
        buyer: Buyer Profile name
        subject: Thread subject
        message: Initial message content
        thread_type: Type of thread (default: General)
        rfq: Optional related RFQ
        order: Optional related Order

    Returns:
        dict: Thread creation result
    """
    user_info = get_user_profile_info()

    if user_info["user_type"] != "seller":
        frappe.throw(_("Only sellers can use this endpoint"))

    # Check if buyer exists and is valid
    buyer_status = frappe.db.get_value("Buyer Profile", buyer, "status")
    if not buyer_status or buyer_status not in ["Active", "Verified"]:
        frappe.throw(_("Buyer not found or inactive"))

    return create_thread(
        subject=subject,
        recipient_type="buyer",
        recipient=buyer,
        thread_type=thread_type,
        initial_message=message,
        rfq=rfq,
        order=order
    )


@frappe.whitelist()
def close_thread(thread_name: str, reason: str = None) -> Dict[str, Any]:
    """
    Close a message thread.

    Args:
        thread_name: The Message Thread document name
        reason: Optional reason for closing

    Returns:
        dict: {
            "success": True,
            "status": "Closed"
        }
    """
    if not thread_name:
        frappe.throw(_("Thread name is required"))

    validate_thread_access(thread_name)

    doc = frappe.get_doc("Message Thread", thread_name)

    if doc.status == "Archived":
        frappe.throw(_("Cannot close an archived thread"))

    if doc.status == "Closed":
        return {
            "success": True,
            "status": "Closed",
            "message": _("Thread is already closed")
        }

    doc.status = "Closed"
    doc.closed_date = nowdate()

    if reason:
        doc.internal_notes = (doc.internal_notes or "") + \
            f"\nClosed on {nowdate()}: {reason}"

    doc.save()

    return {
        "success": True,
        "status": doc.status,
        "message": _("Thread closed successfully")
    }


@frappe.whitelist()
def reopen_thread(thread_name: str) -> Dict[str, Any]:
    """
    Reopen a closed thread.

    Args:
        thread_name: The Message Thread document name

    Returns:
        dict: {
            "success": True,
            "status": "Active"
        }
    """
    if not thread_name:
        frappe.throw(_("Thread name is required"))

    validate_thread_access(thread_name)

    doc = frappe.get_doc("Message Thread", thread_name)

    if doc.status == "Archived":
        frappe.throw(_("Cannot reopen an archived thread"))

    if doc.status == "Active":
        return {
            "success": True,
            "status": "Active",
            "message": _("Thread is already active")
        }

    doc.status = "Active"
    doc.closed_date = None
    doc.save()

    return {
        "success": True,
        "status": doc.status,
        "message": _("Thread reopened successfully")
    }


@frappe.whitelist()
def archive_thread(thread_name: str) -> Dict[str, Any]:
    """
    Archive a message thread.

    Args:
        thread_name: The Message Thread document name

    Returns:
        dict: {
            "success": True,
            "status": "Archived"
        }
    """
    if not thread_name:
        frappe.throw(_("Thread name is required"))

    validate_thread_access(thread_name)

    doc = frappe.get_doc("Message Thread", thread_name)

    doc.status = "Archived"
    doc.archived_date = nowdate()
    doc.save()

    return {
        "success": True,
        "status": doc.status,
        "message": _("Thread archived successfully")
    }


@frappe.whitelist()
def star_thread(thread_name: str, starred: int = 1) -> Dict[str, Any]:
    """
    Star or unstar a thread.

    Args:
        thread_name: The Message Thread document name
        starred: 1 to star, 0 to unstar

    Returns:
        dict: {
            "success": True,
            "is_starred": bool
        }
    """
    if not thread_name:
        frappe.throw(_("Thread name is required"))

    validate_thread_access(thread_name)

    doc = frappe.get_doc("Message Thread", thread_name)
    doc.is_starred = cint(starred)
    doc.save()

    return {
        "success": True,
        "is_starred": bool(doc.is_starred),
        "message": _("Thread starred" if doc.is_starred else "Thread unstarred")
    }


@frappe.whitelist()
def update_thread_priority(thread_name: str, priority: str) -> Dict[str, Any]:
    """
    Update thread priority.

    Args:
        thread_name: The Message Thread document name
        priority: New priority level (Low, Normal, High, Urgent)

    Returns:
        dict: {
            "success": True,
            "priority": str
        }
    """
    if not thread_name:
        frappe.throw(_("Thread name is required"))

    if priority not in PRIORITY_LEVELS:
        frappe.throw(_("Invalid priority. Must be one of: {0}").format(
            ", ".join(PRIORITY_LEVELS)
        ))

    validate_thread_access(thread_name)

    doc = frappe.get_doc("Message Thread", thread_name)
    doc.priority = priority
    doc.save()

    return {
        "success": True,
        "priority": doc.priority,
        "message": _("Priority updated to {0}").format(priority)
    }


# =============================================================================
# MESSAGE APIs
# =============================================================================

@frappe.whitelist()
def send_message(
    message_thread: str,
    content: str,
    message_type: str = "Text",
    attachments: str = None,
    reply_to: str = None
) -> Dict[str, Any]:
    """
    Send a new message to a thread.

    Args:
        message_thread: The Message Thread name (required)
        content: Message content (can be HTML for rich text)
        message_type: Type of message (default: Text)
        attachments: Optional JSON array of attachment objects
        reply_to: Optional message name to reply to

    Returns:
        dict: {
            "success": True,
            "message_name": str,
            "status": str,
            "sent_at": str
        }
    """
    if not message_thread:
        frappe.throw(_("Message thread is required"))
    if not content or not content.strip():
        frappe.throw(_("Message content is required"))

    validate_thread_access(message_thread)

    # Check thread status
    thread_status = frappe.db.get_value("Message Thread", message_thread, "status")
    if thread_status == "Archived":
        frappe.throw(_("Cannot send messages to archived threads"))

    doc = frappe.new_doc("Message")
    doc.message_thread = message_thread
    doc.content = content
    doc.message_type = message_type
    doc.status = "Sent"
    doc.reply_to = reply_to

    if attachments:
        doc.attachments = attachments if isinstance(
            attachments, str
        ) else json.dumps(attachments)

    doc.insert()

    # Reactivate closed threads
    if thread_status == "Closed":
        frappe.db.set_value("Message Thread", message_thread, {
            "status": "Active",
            "closed_date": None
        })

    return {
        "success": True,
        "message_name": doc.name,
        "status": doc.status,
        "sent_at": str(doc.sent_at),
        "message": _("Message sent successfully")
    }


@frappe.whitelist()
def get_thread_messages(
    message_thread: str,
    include_deleted: int = 0,
    limit: int = 50,
    offset: int = 0,
    since: str = None
) -> Dict[str, Any]:
    """
    Get messages in a thread.

    Args:
        message_thread: The Message Thread name
        include_deleted: Include soft-deleted messages (default: 0)
        limit: Maximum messages to return (default: 50)
        offset: Offset for pagination (default: 0)
        since: Only return messages sent after this datetime

    Returns:
        dict: {
            "success": True,
            "messages": [...],
            "count": int,
            "has_more": bool
        }
    """
    if not message_thread:
        frappe.throw(_("Message thread is required"))

    validate_thread_access(message_thread)
    limit, offset = validate_page_params(limit, offset)

    filters = {"message_thread": message_thread}

    if not cint(include_deleted):
        filters["is_deleted"] = 0

    if since:
        filters["sent_at"] = [">=", since]

    messages = frappe.get_all(
        "Message",
        filters=filters,
        fields=[
            "name", "message_type", "status", "sender_type",
            "sender_user", "sender_name", "buyer", "buyer_name",
            "seller", "seller_name", "content", "plain_text_content",
            "has_attachments", "attachments", "sent_at", "is_read",
            "read_at", "is_edited", "edited_at", "is_system_message",
            "reply_to", "reply_to_preview"
        ],
        order_by="sent_at asc",
        limit_page_length=limit + 1,
        limit_start=offset
    )

    has_more = len(messages) > limit
    if has_more:
        messages = messages[:limit]

    return {
        "success": True,
        "messages": messages,
        "count": len(messages),
        "offset": offset,
        "has_more": has_more
    }


@frappe.whitelist()
def mark_messages_as_read(message_thread: str) -> Dict[str, Any]:
    """
    Mark all unread messages in a thread as read for the current user.

    Args:
        message_thread: The Message Thread name

    Returns:
        dict: {
            "success": True,
            "marked_count": int
        }
    """
    if not message_thread:
        frappe.throw(_("Message thread is required"))

    validate_thread_access(message_thread)

    user_info = get_user_profile_info()

    # Get unread messages not sent by current user
    filters = {
        "message_thread": message_thread,
        "is_read": 0,
        "is_deleted": 0
    }

    # Exclude messages sent by current user
    if user_info["user_type"] == "buyer":
        filters["buyer"] = ["!=", user_info["profile_name"]]
    elif user_info["user_type"] == "seller":
        filters["seller"] = ["!=", user_info["profile_name"]]

    messages = frappe.get_all("Message", filters=filters, fields=["name"])

    count = 0
    for msg in messages:
        frappe.db.set_value("Message", msg.name, {
            "is_read": 1,
            "read_at": now_datetime(),
            "status": "Read"
        })
        count += 1

    # Update thread unread count
    frappe.db.set_value("Message Thread", message_thread, "unread_count", 0)

    return {
        "success": True,
        "marked_count": count,
        "message": _("{0} messages marked as read").format(count)
    }


@frappe.whitelist()
def edit_message(message_name: str, new_content: str) -> Dict[str, Any]:
    """
    Edit a message's content.

    Args:
        message_name: The Message document name
        new_content: The new message content

    Returns:
        dict: {
            "success": True,
            "edited_at": str
        }
    """
    if not message_name:
        frappe.throw(_("Message name is required"))
    if not new_content or not new_content.strip():
        frappe.throw(_("Message content is required"))

    doc = frappe.get_doc("Message", message_name)

    # Validate access to the thread
    validate_thread_access(doc.message_thread)

    # Validate user can edit this message
    user_info = get_user_profile_info()
    can_edit = False

    if user_info["user_type"] == "buyer" and doc.buyer == user_info["profile_name"]:
        can_edit = True
    elif user_info["user_type"] == "seller" and doc.seller == user_info["profile_name"]:
        can_edit = True
    elif "System Manager" in frappe.get_roles():
        can_edit = True

    if not can_edit:
        frappe.throw(_("You can only edit your own messages"))

    doc.edit_content(new_content)

    return {
        "success": True,
        "edited_at": str(doc.edited_at),
        "message": _("Message edited successfully")
    }


@frappe.whitelist()
def delete_message(message_name: str, reason: str = None) -> Dict[str, Any]:
    """
    Soft delete a message.

    Args:
        message_name: The Message document name
        reason: Optional reason for deletion

    Returns:
        dict: {
            "success": True,
            "message": str
        }
    """
    if not message_name:
        frappe.throw(_("Message name is required"))

    doc = frappe.get_doc("Message", message_name)

    # Validate access to the thread
    validate_thread_access(doc.message_thread)

    # Validate user can delete this message
    user_info = get_user_profile_info()
    can_delete = False

    if user_info["user_type"] == "buyer" and doc.buyer == user_info["profile_name"]:
        can_delete = True
    elif user_info["user_type"] == "seller" and doc.seller == user_info["profile_name"]:
        can_delete = True
    elif "System Manager" in frappe.get_roles():
        can_delete = True

    if not can_delete:
        frappe.throw(_("You can only delete your own messages"))

    doc.soft_delete(reason)

    return {
        "success": True,
        "message": _("Message deleted")
    }


# =============================================================================
# SEARCH APIs
# =============================================================================

@frappe.whitelist()
def search_messages(
    query: str,
    thread: str = None,
    buyer: str = None,
    seller: str = None,
    message_type: str = None,
    date_from: str = None,
    date_to: str = None,
    limit: int = None,
    offset: int = None
) -> Dict[str, Any]:
    """
    Search messages across threads.

    Args:
        query: Search query string (required)
        thread: Optional thread filter
        buyer: Optional buyer filter
        seller: Optional seller filter
        message_type: Optional message type filter
        date_from: Filter messages from this date
        date_to: Filter messages until this date
        limit: Number of results (default 20, max 100)
        offset: Starting position

    Returns:
        dict: {
            "success": True,
            "messages": [...],
            "count": int,
            "has_more": bool
        }
    """
    if not query or len(query) < 2:
        frappe.throw(_("Search query must be at least 2 characters"))

    limit, offset = validate_page_params(limit, offset)

    filters = {"is_deleted": 0}

    if thread:
        filters["message_thread"] = thread
    if buyer:
        filters["buyer"] = buyer
    if seller:
        filters["seller"] = seller
    if message_type:
        filters["message_type"] = message_type

    if date_from and date_to:
        filters["sent_at"] = ["between", [date_from, date_to]]
    elif date_from:
        filters["sent_at"] = [">=", date_from]
    elif date_to:
        filters["sent_at"] = ["<=", date_to]

    # Apply tenant filter
    if "System Manager" not in frappe.get_roles():
        current_tenant = get_current_tenant()
        if current_tenant:
            filters["tenant"] = current_tenant

        # Filter by user's profile
        user_info = get_user_profile_info()
        if user_info["user_type"] == "buyer":
            filters["message_thread"] = ["in", frappe.get_all(
                "Message Thread",
                filters={"buyer": user_info["profile_name"]},
                pluck="name"
            )]
        elif user_info["user_type"] == "seller":
            filters["message_thread"] = ["in", frappe.get_all(
                "Message Thread",
                filters={"seller": user_info["profile_name"]},
                pluck="name"
            )]

    or_filters = [
        ["content", "like", f"%{query}%"],
        ["plain_text_content", "like", f"%{query}%"]
    ]

    messages = frappe.get_all(
        "Message",
        filters=filters,
        or_filters=or_filters,
        fields=[
            "name", "message_thread", "thread_subject", "message_type",
            "sender_type", "sender_name", "buyer_name", "seller_name",
            "plain_text_content", "sent_at", "is_read"
        ],
        order_by="sent_at desc",
        start=offset,
        page_length=limit + 1
    )

    has_more = len(messages) > limit
    if has_more:
        messages = messages[:limit]

    return {
        "success": True,
        "messages": messages,
        "count": len(messages),
        "query": query,
        "has_more": has_more
    }


# =============================================================================
# STATISTICS AND ANALYTICS APIs
# =============================================================================

@frappe.whitelist()
def get_messaging_statistics(
    buyer: str = None,
    seller: str = None,
    tenant: str = None,
    date_from: str = None,
    date_to: str = None
) -> Dict[str, Any]:
    """
    Get messaging statistics for dashboard display.

    Args:
        buyer: Filter by Buyer Profile
        seller: Filter by Seller Profile
        tenant: Filter by tenant
        date_from: Start date
        date_to: End date

    Returns:
        dict: Messaging statistics
    """
    thread_filters = {}
    message_filters = {"is_deleted": 0}

    if buyer:
        thread_filters["buyer"] = buyer
    if seller:
        thread_filters["seller"] = seller
    if tenant:
        thread_filters["tenant"] = tenant
    elif "System Manager" not in frappe.get_roles():
        current_tenant = get_current_tenant()
        if current_tenant:
            thread_filters["tenant"] = current_tenant

    # Get thread statistics
    thread_count = frappe.db.count("Message Thread", thread_filters)

    thread_status_counts = frappe.db.get_all(
        "Message Thread",
        filters=thread_filters,
        fields=["status", "count(*) as count"],
        group_by="status"
    )
    thread_status_dict = {t.status: t.count for t in thread_status_counts}

    # Build message filters based on threads
    if thread_filters:
        thread_names = frappe.get_all(
            "Message Thread",
            filters=thread_filters,
            pluck="name"
        )
        if thread_names:
            message_filters["message_thread"] = ["in", thread_names]

    if date_from and date_to:
        message_filters["sent_at"] = ["between", [date_from, date_to]]
    elif date_from:
        message_filters["sent_at"] = [">=", date_from]
    elif date_to:
        message_filters["sent_at"] = ["<=", date_to]

    # Get message statistics
    message_count = frappe.db.count("Message", message_filters)

    read_filters = {**message_filters, "is_read": 1}
    read_count = frappe.db.count("Message", read_filters)

    message_type_counts = frappe.db.get_all(
        "Message",
        filters=message_filters,
        fields=["message_type", "count(*) as count"],
        group_by="message_type"
    )
    message_type_dict = {m.message_type: m.count for m in message_type_counts}

    # Calculate unread count
    unread_filters = {**message_filters, "is_read": 0}
    unread_count = frappe.db.count("Message", unread_filters)

    # Calculate average response time (placeholder)
    avg_response_time = None

    return {
        "success": True,
        "statistics": {
            "thread_count": thread_count,
            "thread_status_breakdown": thread_status_dict,
            "active_threads": thread_status_dict.get("Active", 0),
            "pending_threads": thread_status_dict.get("Pending", 0),
            "closed_threads": thread_status_dict.get("Closed", 0),
            "archived_threads": thread_status_dict.get("Archived", 0),
            "message_count": message_count,
            "read_count": read_count,
            "unread_count": unread_count,
            "read_rate": (read_count / message_count * 100) if message_count > 0 else 0,
            "message_type_breakdown": message_type_dict,
            "average_response_time": avg_response_time
        }
    }


@frappe.whitelist()
def get_my_messaging_stats() -> Dict[str, Any]:
    """
    Get messaging statistics for the current user.

    Returns:
        dict: User-specific messaging statistics
    """
    user_info = get_user_profile_info()

    if user_info["user_type"] == "buyer":
        return get_messaging_statistics(buyer=user_info["profile_name"])
    elif user_info["user_type"] == "seller":
        return get_messaging_statistics(seller=user_info["profile_name"])
    else:
        return get_messaging_statistics()


@frappe.whitelist()
def get_unread_count() -> Dict[str, Any]:
    """
    Get the total unread message count for the current user.

    Returns:
        dict: {
            "success": True,
            "unread_count": int,
            "threads_with_unread": int
        }
    """
    user_info = get_user_profile_info()

    thread_filters = {}

    if user_info["user_type"] == "buyer":
        thread_filters["buyer"] = user_info["profile_name"]
    elif user_info["user_type"] == "seller":
        thread_filters["seller"] = user_info["profile_name"]

    # Get threads with unread messages
    thread_filters["unread_count"] = [">", 0]
    threads_with_unread = frappe.db.count("Message Thread", thread_filters)

    # Get total unread messages
    del thread_filters["unread_count"]
    thread_names = frappe.get_all(
        "Message Thread",
        filters=thread_filters,
        pluck="name"
    )

    unread_count = 0
    if thread_names:
        message_filters = {
            "message_thread": ["in", thread_names],
            "is_read": 0,
            "is_deleted": 0
        }

        # Exclude messages sent by current user
        if user_info["user_type"] == "buyer":
            message_filters["buyer"] = ["!=", user_info["profile_name"]]
        elif user_info["user_type"] == "seller":
            message_filters["seller"] = ["!=", user_info["profile_name"]]

        unread_count = frappe.db.count("Message", message_filters)

    return {
        "success": True,
        "unread_count": unread_count,
        "threads_with_unread": threads_with_unread
    }


# =============================================================================
# UTILITY APIs
# =============================================================================

@frappe.whitelist()
def get_messaging_config() -> Dict[str, Any]:
    """
    Get messaging configuration options.

    Returns available options for thread types, message types, etc.
    Useful for populating dropdown menus in the frontend.

    Returns:
        dict: Configuration options
    """
    return {
        "success": True,
        "config": {
            "thread_types": THREAD_TYPES,
            "thread_statuses": THREAD_STATUSES,
            "message_types": MESSAGE_TYPES,
            "message_statuses": MESSAGE_STATUSES,
            "system_message_types": SYSTEM_MESSAGE_TYPES,
            "priority_levels": PRIORITY_LEVELS,
            "default_page_size": DEFAULT_PAGE_SIZE,
            "max_page_size": MAX_PAGE_SIZE
        }
    }


@frappe.whitelist()
def get_or_create_thread(
    buyer: str = None,
    seller: str = None,
    thread_type: str = "General",
    rfq: str = None,
    order: str = None,
    subject: str = None
) -> Dict[str, Any]:
    """
    Get an existing thread or create a new one.

    Finds an existing active thread between the buyer and seller for
    the given context, or creates a new one if none exists.

    Args:
        buyer: Buyer Profile name
        seller: Seller Profile name
        thread_type: Type of thread
        rfq: Optional related RFQ
        order: Optional related Order
        subject: Subject for new thread if created

    Returns:
        dict: {
            "success": True,
            "thread_name": str,
            "is_new": bool
        }
    """
    user_info = get_user_profile_info()

    # Determine buyer/seller based on current user
    if not buyer and user_info["user_type"] == "buyer":
        buyer = user_info["profile_name"]
    if not seller and user_info["user_type"] == "seller":
        seller = user_info["profile_name"]

    if not buyer or not seller:
        frappe.throw(_("Both buyer and seller must be specified"))

    # Look for existing thread
    filters = {
        "buyer": buyer,
        "seller": seller,
        "status": ["in", ["Active", "Pending"]]
    }

    if rfq:
        filters["rfq"] = rfq
    if order:
        filters["order"] = order
    if thread_type != "General":
        filters["thread_type"] = thread_type

    existing = frappe.db.exists("Message Thread", filters)

    if existing:
        return {
            "success": True,
            "thread_name": existing,
            "is_new": False
        }

    # Create new thread
    if not subject:
        buyer_name = frappe.db.get_value("Buyer Profile", buyer, "buyer_name")
        seller_name = frappe.db.get_value("Seller Profile", seller, "seller_name")
        subject = f"Conversation: {buyer_name} - {seller_name}"

    doc = frappe.new_doc("Message Thread")
    doc.subject = subject
    doc.thread_type = thread_type
    doc.buyer = buyer
    doc.seller = seller
    doc.initiator_type = "Buyer" if user_info["user_type"] == "buyer" else "Seller"
    doc.recipient_type = "Seller" if user_info["user_type"] == "buyer" else "Buyer"

    if rfq:
        doc.rfq = rfq
    if order:
        doc.order = order

    doc.insert()

    return {
        "success": True,
        "thread_name": doc.name,
        "is_new": True
    }


@frappe.whitelist()
def send_system_notification(
    thread_name: str,
    content: str,
    message_type: str = "System Notification"
) -> Dict[str, Any]:
    """
    Send a system-generated message to a thread.

    This endpoint is for system/automated messages only.

    Args:
        thread_name: The Message Thread name
        content: Message content
        message_type: System message type

    Returns:
        dict: Created message info
    """
    if message_type not in SYSTEM_MESSAGE_TYPES:
        frappe.throw(
            _("Invalid system message type. Must be one of: {0}").format(
                ", ".join(SYSTEM_MESSAGE_TYPES)
            )
        )

    # Only system manager or internal calls
    if "System Manager" not in frappe.get_roles():
        frappe.throw(_("Only administrators can send system notifications"))

    doc = frappe.new_doc("Message")
    doc.message_thread = thread_name
    doc.content = content
    doc.message_type = message_type
    doc.sender_type = "System"
    doc.is_system_message = 1
    doc.status = "Sent"

    doc.insert(ignore_permissions=True)

    return {
        "success": True,
        "message_name": doc.name,
        "status": doc.status,
        "message": _("System notification sent")
    }

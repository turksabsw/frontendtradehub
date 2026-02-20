# Copyright (c) 2024, Mock Data Engine and contributors
# For license information, please see license.txt

"""
Document Event Handlers for Mock Data Engine.

This module provides document event handlers for Mock Generation Request
and Mock Generation Log DocTypes to support:
- Progress tracking updates
- Cleanup on deletion
- Statistics aggregation

These handlers are registered in hooks.py via doc_events configuration.
"""

from __future__ import annotations

try:
    import frappe
    from frappe import _
except ImportError:
    frappe = None
    _ = lambda x: x


def on_generation_request_update(doc, method):
    """
    Handle Mock Generation Request update events.

    This handler is called when a Mock Generation Request is updated.
    It performs the following actions:
    - Publishes realtime updates for status changes
    - Logs status transitions for audit trail

    Args:
        doc: The Mock Generation Request document
        method: The method name that triggered this event ('on_update')
    """
    if not frappe:
        return

    # Check if status changed
    if doc.has_value_changed("status"):
        old_status = doc.get_doc_before_save()
        old_status_value = old_status.status if old_status else "Draft"

        # Publish realtime event for UI updates
        frappe.publish_realtime(
            event="mock_generation_status_change",
            message={
                "request_name": doc.name,
                "old_status": old_status_value,
                "new_status": doc.status,
                "progress_percent": doc.progress_percent or 0,
                "records_created": doc.records_created or 0,
                "records_failed": doc.records_failed or 0,
            },
            doctype="Mock Generation Request",
            docname=doc.name,
            after_commit=True
        )

        # Log status transition
        frappe.logger().info(
            f"Mock Generation Request {doc.name}: "
            f"{old_status_value} -> {doc.status}"
        )


def on_generation_request_trash(doc, method):
    """
    Handle Mock Generation Request trash/delete events.

    This handler is called when a Mock Generation Request is deleted.
    It performs cleanup of related Mock Generation Log records.

    Args:
        doc: The Mock Generation Request document
        method: The method name that triggered this event ('on_trash')
    """
    if not frappe:
        return

    # Delete related generation logs
    # Note: This is handled by Frappe's linked document cleanup
    # but we log it for audit purposes
    log_count = frappe.db.count(
        "Mock Generation Log",
        filters={"generation_request": doc.name}
    )

    if log_count > 0:
        frappe.logger().info(
            f"Deleting {log_count} Mock Generation Log records "
            f"for request {doc.name}"
        )

        # Delete the logs explicitly to ensure cleanup
        frappe.db.delete(
            "Mock Generation Log",
            {"generation_request": doc.name}
        )


def on_generation_log_insert(doc, method):
    """
    Handle Mock Generation Log insert events.

    This handler is called when a new Mock Generation Log is created.
    It updates the parent request's statistics.

    Args:
        doc: The Mock Generation Log document
        method: The method name that triggered this event ('after_insert')
    """
    if not frappe:
        return

    # Skip if no parent request linked
    if not doc.generation_request:
        return

    # Update parent request statistics
    # Note: This is a lightweight update to avoid blocking
    # The main statistics update happens in the generator itself
    try:
        # Increment appropriate counter based on log status
        if doc.status == "Success":
            frappe.db.sql("""
                UPDATE `tabMock Generation Request`
                SET records_created = COALESCE(records_created, 0) + 1,
                    modified = NOW()
                WHERE name = %s
            """, (doc.generation_request,))
        elif doc.status == "Failed":
            frappe.db.sql("""
                UPDATE `tabMock Generation Request`
                SET records_failed = COALESCE(records_failed, 0) + 1,
                    modified = NOW()
                WHERE name = %s
            """, (doc.generation_request,))
    except Exception:
        # Don't fail the log insert if stats update fails
        pass

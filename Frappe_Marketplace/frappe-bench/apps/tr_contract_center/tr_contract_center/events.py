# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

"""
TR Contract Center Document Events
"""

import frappe
from frappe import _


def contract_instance_on_update(doc, method):
    """
    Handle Contract Instance on_update event.

    - Create revision record on significant changes
    - Validate wet signature has PDF
    """
    # Check if status changed to Signed
    if doc.has_value_changed("status") and doc.status == "Signed":
        # Validate wet signature has PDF
        if doc.signature_method == "Wet" and not doc.signed_pdf:
            frappe.throw(
                _("Wet signature requires a signed PDF document to be uploaded")
            )

        # Set signed_at if not set
        if not doc.signed_at:
            doc.signed_at = frappe.utils.now_datetime()

    # Create revision record for significant changes
    if not doc.is_new() and doc.has_value_changed("content_snapshot"):
        create_revision(doc)


def create_revision(doc):
    """Create a revision record for the contract."""
    # Get current revision number
    last_revision = frappe.db.get_value(
        "Contract Revision",
        {"contract_instance": doc.name},
        "revision_number",
        order_by="revision_number desc"
    ) or 0

    frappe.get_doc({
        "doctype": "Contract Revision",
        "contract_instance": doc.name,
        "revision_number": last_revision + 1,
        "content_snapshot": doc.content_snapshot,
        "created_by": frappe.session.user,
        "revision_notes": f"Content updated at {frappe.utils.now_datetime()}"
    }).insert(ignore_permissions=True)

# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

"""
Consent Audit Log DocType Controller

Immutable audit log for all consent-related actions.
KVKK/GDPR compliance requires complete audit trails.

IMMUTABILITY RULES:
- Records can ONLY be created, NEVER modified or deleted
- All fields are read-only after creation
- on_trash() throws an error to prevent deletion
- validate() throws an error on modification attempts
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime


class ConsentAuditLog(Document):
    """
    Controller for Consent Audit Log DocType.

    This DocType is IMMUTABLE - records cannot be modified or deleted.
    """

    def before_insert(self):
        """Set metadata before inserting."""
        # Set action date if not provided
        if not self.action_date:
            self.action_date = now_datetime()

        # Set action_by if not provided
        if not self.action_by:
            self.action_by = frappe.session.user

        # Cache party info from consent record for reporting
        if self.consent_record:
            consent_data = frappe.db.get_value(
                "Consent Record",
                self.consent_record,
                ["party_type", "party"],
                as_dict=True
            )
            if consent_data:
                self.party_type = consent_data.party_type
                self.party = consent_data.party

        # Capture IP if available
        if not self.ip_address and hasattr(frappe.local, 'request_ip'):
            self.ip_address = frappe.local.request_ip

    def validate(self):
        """
        Validate the audit log.

        IMMUTABILITY: Prevent any modifications to existing records.
        """
        if not self.is_new():
            frappe.throw(
                _("Consent Audit Logs are immutable and cannot be modified. "
                  "This is required for KVKK/GDPR compliance.")
            )

    def on_update(self):
        """
        Block updates to existing records.

        This is a secondary protection in case validate() is bypassed.
        """
        pass  # validate() already handles this

    def on_trash(self):
        """
        BLOCK ALL DELETIONS.

        KVKK/GDPR compliance requires audit logs to be retained
        for the entire retention period. Deletion is never allowed.
        """
        frappe.throw(
            _("Consent Audit Logs cannot be deleted. "
              "This is required for KVKK/GDPR compliance. "
              "Audit logs must be retained for legal purposes.")
        )

    def db_update(self):
        """
        Override db_update to prevent updates.

        Additional protection layer.
        """
        frappe.throw(
            _("Consent Audit Logs are immutable and cannot be updated.")
        )


def create_audit_log(consent_record, action, details=None, old_status=None, new_status=None):
    """
    Create an audit log entry.

    Args:
        consent_record: Name of the consent record
        action: Action performed (Created, Status Change, etc.)
        details: Optional details about the action
        old_status: Previous status (for status changes)
        new_status: New status (for status changes)

    Returns:
        Document: The created audit log
    """
    doc = frappe.get_doc({
        "doctype": "Consent Audit Log",
        "consent_record": consent_record,
        "action": action,
        "action_by": frappe.session.user,
        "action_date": now_datetime(),
        "details": details,
        "old_status": old_status,
        "new_status": new_status,
        "ip_address": getattr(frappe.local, 'request_ip', None),
        "user_agent": getattr(frappe.local.request, 'user_agent', None) if hasattr(frappe.local, 'request') else None
    })

    doc.insert(ignore_permissions=True)
    return doc


def get_audit_trail(consent_record):
    """
    Get the complete audit trail for a consent record.

    Args:
        consent_record: Name of the consent record

    Returns:
        list: List of audit log entries in chronological order
    """
    return frappe.get_all(
        "Consent Audit Log",
        filters={"consent_record": consent_record},
        fields=["name", "action", "action_by", "action_date",
                "details", "old_status", "new_status", "ip_address"],
        order_by="action_date asc"
    )


def get_audit_stats(filters=None):
    """
    Get audit statistics for compliance reporting.

    Args:
        filters: Optional filters for date range, etc.

    Returns:
        dict: Statistics about audit log entries
    """
    base_filters = filters or {}

    stats = {
        "total_entries": frappe.db.count("Consent Audit Log", base_filters),
        "by_action": {},
        "by_user": {}
    }

    # Count by action type
    actions = ["Created", "Status Change", "Verified", "Auto Expired", "Deletion Attempted"]
    for action in actions:
        action_filters = dict(base_filters)
        action_filters["action"] = action
        stats["by_action"][action] = frappe.db.count("Consent Audit Log", action_filters)

    return stats

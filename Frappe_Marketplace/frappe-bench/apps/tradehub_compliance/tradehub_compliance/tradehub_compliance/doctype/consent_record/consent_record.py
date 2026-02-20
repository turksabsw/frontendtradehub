# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

"""
Consent Record DocType Controller

The main DocType for recording user consents. Uses Dynamic Link pattern
to link to any party type (User, Customer, Lead, Seller Profile, etc.).

KVKK/GDPR Compliance:
- Records must have minimum 5-year retention period
- Cannot be deleted before retention_until date
- All changes are logged to Consent Audit Log
- Supports verification (double opt-in)
- Status transitions are controlled and logged
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime, today, add_years, getdate
import secrets


class ConsentRecord(Document):
    """
    Controller for Consent Record DocType.

    Implements KVKK/GDPR compliant consent record management.
    """

    def before_insert(self):
        """Set initial values before first save."""
        # Set granted_at if not provided
        if not self.granted_at:
            self.granted_at = now_datetime()

        # Set granted_by if not provided
        if not self.granted_by:
            self.granted_by = frappe.session.user

        # Calculate retention period (KVKK minimum: 5 years)
        self.calculate_retention_until()

        # Set party name
        self.set_party_name()

        # Copy consent text metadata
        self.set_consent_text_metadata()

        # Generate verification token if needed
        if self.status == "Pending":
            self.verification_token = secrets.token_urlsafe(32)

    def validate(self):
        """Validate the consent record."""
        self.validate_party()
        self.validate_consent_text()
        self.validate_status_transition()
        self.validate_retention_period()

    def validate_party(self):
        """Validate party exists and is valid."""
        if not self.party_type or not self.party:
            frappe.throw(_("Party Type and Party are required"))

        # Verify party exists
        if not frappe.db.exists(self.party_type, self.party):
            frappe.throw(
                _("{0} '{1}' does not exist").format(self.party_type, self.party)
            )

    def validate_consent_text(self):
        """Validate consent text if provided."""
        if self.consent_text:
            text_doc = frappe.db.get_value(
                "Consent Text",
                self.consent_text,
                ["status", "consent_topic"],
                as_dict=True
            )

            if text_doc and text_doc.status != "Active":
                frappe.msgprint(
                    _("Warning: The consent text '{0}' is not Active").format(self.consent_text),
                    indicator="orange"
                )

            # Verify topic matches
            if text_doc and self.consent_topic and text_doc.consent_topic != self.consent_topic:
                frappe.throw(
                    _("Consent text topic ({0}) does not match selected topic ({1})").format(
                        text_doc.consent_topic, self.consent_topic
                    )
                )

    def validate_status_transition(self):
        """Validate status transitions."""
        if self.is_new():
            return

        old_status = frappe.db.get_value("Consent Record", self.name, "status")

        # Valid transitions
        valid_transitions = {
            "Pending": ["Active", "Expired"],
            "Active": ["Revoked", "Expired"],
            "Revoked": [],  # Cannot change from Revoked
            "Expired": []   # Cannot change from Expired
        }

        if old_status and self.status != old_status:
            if self.status not in valid_transitions.get(old_status, []):
                frappe.throw(
                    _("Cannot change status from {0} to {1}").format(old_status, self.status)
                )

    def validate_retention_period(self):
        """Ensure retention period is set correctly."""
        if not self.retention_until:
            self.calculate_retention_until()

    def calculate_retention_until(self):
        """Calculate the retention period based on KVKK requirements."""
        # KVKK requires minimum 5 years retention from grant date
        grant_date = getdate(self.granted_at) if self.granted_at else today()
        self.retention_until = add_years(grant_date, 5)

    def set_party_name(self):
        """Fetch and set the party name."""
        if not self.party_type or not self.party:
            return

        # Try common name fields
        name_fields = ["full_name", "name1", "customer_name", "title", "email", "name"]

        for field in name_fields:
            try:
                name = frappe.db.get_value(self.party_type, self.party, field)
                if name:
                    self.party_name = name
                    return
            except Exception:
                continue

        # Fallback to party ID
        self.party_name = self.party

    def set_consent_text_metadata(self):
        """Copy consent text version and hash for immutable reference."""
        if self.consent_text:
            text_data = frappe.db.get_value(
                "Consent Text",
                self.consent_text,
                ["version", "content_hash"],
                as_dict=True
            )
            if text_data:
                self.consent_text_version = text_data.version
                self.consent_text_hash = text_data.content_hash

    def before_save(self):
        """Actions before saving."""
        # Handle status changes
        if self.has_value_changed("status"):
            self.handle_status_change()

    def handle_status_change(self):
        """Handle status change actions."""
        old_status = frappe.db.get_value("Consent Record", self.name, "status") if not self.is_new() else None

        # Log status change
        if old_status:
            self.create_audit_log(
                "Status Change",
                f"Status changed from {old_status} to {self.status}"
            )

        # Handle revocation
        if self.status == "Revoked":
            if not self.revoked_at:
                self.revoked_at = now_datetime()
            if not self.revoked_by:
                self.revoked_by = frappe.session.user

    def after_insert(self):
        """Actions after inserting a new record."""
        self.create_audit_log("Created", "Consent record created")

    def on_update(self):
        """Actions after updating."""
        pass  # Audit log created in before_save for status changes

    def on_trash(self):
        """
        Prevent deletion if retention period has not expired.

        KVKK COMPLIANCE: Consent records cannot be deleted before
        the retention_until date (minimum 5 years from grant).
        """
        if self.retention_until:
            if getdate(self.retention_until) > getdate(today()):
                frappe.throw(
                    _("Cannot delete consent record before retention period ends ({0}). "
                      "KVKK requires minimum 5 years retention.").format(self.retention_until)
                )

        # Log the deletion attempt
        self.create_audit_log("Deletion Attempted", "Record deletion was attempted")

    def create_audit_log(self, action, details):
        """
        Create an audit log entry.

        Args:
            action: The action performed
            details: Details about the action
        """
        try:
            frappe.get_doc({
                "doctype": "Consent Audit Log",
                "consent_record": self.name,
                "action": action,
                "action_by": frappe.session.user,
                "action_date": now_datetime(),
                "details": details,
                "ip_address": frappe.local.request_ip if hasattr(frappe.local, 'request_ip') else None
            }).insert(ignore_permissions=True)
        except Exception as e:
            frappe.logger().error(f"Failed to create audit log: {str(e)}")


def revoke_consent(consent_record_name, reason=None, ip_address=None):
    """
    Revoke a consent record.

    Args:
        consent_record_name: Name of the consent record
        reason: Reason for revocation
        ip_address: IP address of the person revoking

    Returns:
        Document: Updated consent record
    """
    doc = frappe.get_doc("Consent Record", consent_record_name)

    if doc.status != "Active":
        frappe.throw(
            _("Can only revoke Active consents. Current status: {0}").format(doc.status)
        )

    doc.status = "Revoked"
    doc.revoked_at = now_datetime()
    doc.revoked_by = frappe.session.user
    doc.revocation_reason = reason
    doc.revocation_ip_address = ip_address
    doc.save()

    return doc


def verify_consent(consent_record_name, verification_token=None):
    """
    Verify a pending consent (double opt-in).

    Args:
        consent_record_name: Name of the consent record
        verification_token: Token to verify

    Returns:
        bool: True if verified successfully
    """
    doc = frappe.get_doc("Consent Record", consent_record_name)

    if doc.status != "Pending":
        return False

    if verification_token and doc.verification_token != verification_token:
        return False

    doc.status = "Active"
    doc.is_verified = 1
    doc.verified_at = now_datetime()
    doc.double_opt_in_completed = 1
    doc.save()

    return True


def get_consents_for_party(party_type, party, topic=None, status="Active"):
    """
    Get all consents for a party.

    Args:
        party_type: DocType of the party
        party: Name of the party
        topic: Optional topic filter
        status: Status filter (default: Active)

    Returns:
        list: List of consent records
    """
    filters = {
        "party_type": party_type,
        "party": party
    }

    if topic:
        filters["consent_topic"] = topic

    if status:
        filters["status"] = status

    return frappe.get_all(
        "Consent Record",
        filters=filters,
        fields=["name", "consent_topic", "consent_method", "status",
                "granted_at", "expiry_date", "is_verified"],
        order_by="granted_at desc"
    )


def has_active_consent(party_type, party, topic, method=None):
    """
    Check if a party has active consent for a topic.

    Args:
        party_type: DocType of the party
        party: Name of the party
        topic: Consent topic name or code
        method: Optional method filter

    Returns:
        bool: True if active consent exists
    """
    filters = {
        "party_type": party_type,
        "party": party,
        "status": "Active"
    }

    # Handle topic as name or code
    topic_name = frappe.db.get_value(
        "Consent Topic",
        {"topic_code": topic.upper()},
        "name"
    ) if topic else None

    filters["consent_topic"] = topic_name or topic

    if method:
        method_name = frappe.db.get_value(
            "Consent Method",
            {"method_code": method.upper()},
            "name"
        )
        filters["consent_method"] = method_name or method

    return frappe.db.exists("Consent Record", filters)

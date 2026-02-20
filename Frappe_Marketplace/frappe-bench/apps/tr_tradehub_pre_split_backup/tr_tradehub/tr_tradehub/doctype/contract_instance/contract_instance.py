# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

"""
Contract Instance DocType Controller

Individual contracts instantiated from templates.
Workflow: Draft → Sent → Pending Signature → Signed/Rejected → Expired
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime, add_days, getdate, today


class ContractInstance(Document):
    """
    Controller for Contract Instance DocType.

    Handles contract workflow and signature validation.
    """

    def before_insert(self):
        """Set initial values."""
        self.created_at = now_datetime()

        # Snapshot template
        self.snapshot_template()

        # Set party name
        self.set_party_name()

        # Generate title if not provided
        if not self.title:
            template = frappe.get_doc("Contract Template", self.template)
            self.title = f"{template.title} - {self.party_name or self.party}"

    def snapshot_template(self):
        """Snapshot the template content for immutable reference."""
        if not self.template_version_snapshot:
            template = frappe.get_doc("Contract Template", self.template)
            self.template_version_snapshot = template.version
            self.template_content_snapshot = template.content
            self.content_hash_snapshot = template.content_hash

            # Set validity based on template
            if template.valid_days and not self.valid_until:
                self.valid_until = add_days(now_datetime(), template.valid_days)

    def set_party_name(self):
        """Fetch party name."""
        if not self.party_type or not self.party:
            return

        name_fields = ["full_name", "name1", "customer_name", "title", "email", "name"]

        for field in name_fields:
            try:
                name = frappe.db.get_value(self.party_type, self.party, field)
                if name:
                    self.party_name = name
                    return
            except Exception:
                continue

        self.party_name = self.party

    def validate(self):
        """Validate the contract instance."""
        self.validate_template()
        self.validate_status_transition()
        self.validate_signature()

    def validate_template(self):
        """Validate template is published."""
        template_status = frappe.db.get_value("Contract Template", self.template, "status")

        if template_status != "Published" and self.is_new():
            frappe.throw(
                _("Cannot create contract from unpublished template. Template status: {0}").format(template_status)
            )

    def validate_status_transition(self):
        """Validate status transitions."""
        if self.is_new():
            return

        old_status = frappe.db.get_value("Contract Instance", self.name, "status")

        valid_transitions = {
            "Draft": ["Sent", "Expired"],
            "Sent": ["Pending Signature", "Expired", "Rejected"],
            "Pending Signature": ["Signed", "Rejected", "Expired"],
            "Signed": ["Expired"],  # Signed contracts can only expire
            "Rejected": [],  # Terminal state
            "Expired": []    # Terminal state
        }

        if old_status and self.status != old_status:
            if self.status not in valid_transitions.get(old_status, []):
                frappe.throw(
                    _("Invalid status transition: {0} → {1}").format(old_status, self.status)
                )

    def validate_signature(self):
        """Validate signature requirements."""
        # If being signed
        if self.status == "Signed":
            # Wet signature requires PDF
            if self.signature_method == "Wet" and not self.signed_pdf:
                frappe.throw(
                    _("Wet signature requires a signed PDF document to be uploaded")
                )

            # Set signed_at if not set
            if not self.signed_at:
                self.signed_at = now_datetime()

    def before_save(self):
        """Actions before save."""
        # Handle status changes
        if self.has_value_changed("status"):
            self.handle_status_change()

    def handle_status_change(self):
        """Handle status change side effects."""
        if self.status == "Sent" and not self.sent_at:
            self.sent_at = now_datetime()

        if self.status == "Rejected" and not self.rejected_at:
            self.rejected_at = now_datetime()

    def on_trash(self):
        """Prevent deletion of signed contracts."""
        if self.status == "Signed":
            frappe.throw(
                _("Signed contracts cannot be deleted for legal compliance.")
            )


def create_contract_instance(template, party_type, party, signature_method=None):
    """
    Create a new contract instance from a template.

    Args:
        template: Template name or code
        party_type: DocType of the party
        party: Name of the party
        signature_method: 'Digital' or 'Wet' (optional)

    Returns:
        Document: The created Contract Instance
    """
    # Resolve template by code if needed
    if not frappe.db.exists("Contract Template", template):
        template = frappe.db.get_value(
            "Contract Template",
            {"template_code": template.upper(), "status": "Published"},
            "name"
        )

    if not template:
        frappe.throw(_("Template not found or not published"))

    doc = frappe.get_doc({
        "doctype": "Contract Instance",
        "template": template,
        "party_type": party_type,
        "party": party,
        "signature_method": signature_method,
        "status": "Draft"
    })

    doc.insert()
    return doc


def send_for_signature(contract_instance):
    """
    Send a contract for signature.

    Args:
        contract_instance: Name of the Contract Instance

    Returns:
        dict: Result with signing details
    """
    doc = frappe.get_doc("Contract Instance", contract_instance)

    if doc.status != "Draft":
        frappe.throw(_("Only Draft contracts can be sent for signature"))

    doc.status = "Sent"
    doc.save()

    # If digital signature, initiate e-sign
    if doc.signature_method == "Digital" and doc.esign_provider:
        from tr_contract_center.esign import get_provider_adapter

        adapter = get_provider_adapter(doc.esign_provider)
        if adapter:
            result = adapter.create_signing_request(
                doc.name,
                doc.template_content_snapshot,
                {
                    "name": doc.party_name,
                    "party_type": doc.party_type,
                    "party": doc.party
                }
            )

            if result.get("success"):
                doc.esign_transaction = result.get("transaction_name")
                doc.status = "Pending Signature"
                doc.save()

                return {
                    "success": True,
                    "signing_url": result.get("signing_url"),
                    "external_id": result.get("external_id")
                }

            return {
                "success": False,
                "error": result.get("error")
            }

    doc.status = "Pending Signature"
    doc.save()

    return {
        "success": True,
        "contract": doc.name,
        "status": doc.status
    }

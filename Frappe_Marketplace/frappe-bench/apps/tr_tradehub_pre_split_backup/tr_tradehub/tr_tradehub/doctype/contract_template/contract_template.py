# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

"""
Contract Template DocType Controller

Versioned contract templates with SHA256 hash verification.
Similar pattern to Consent Text but for contracts.
"""

import frappe
from frappe import _
from frappe.model.document import Document
import hashlib


class ContractTemplate(Document):
    """
    Controller for Contract Template DocType.

    Implements versioning with SHA256 hash verification.
    """

    def before_insert(self):
        """Set initial values."""
        if not self.version:
            self.version = 1

        self.content_hash = self.calculate_content_hash()

    def before_save(self):
        """Handle versioning on content change."""
        if self.has_value_changed("content"):
            self.handle_content_change()

        # Handle status change to Published
        if self.has_value_changed("status") and self.status == "Published":
            if not self.published_at:
                self.published_at = frappe.utils.now_datetime()
            if not self.published_by:
                self.published_by = frappe.session.user

    def handle_content_change(self):
        """Handle content changes with versioning."""
        old_hash = frappe.db.get_value("Contract Template", self.name, "content_hash")
        new_hash = self.calculate_content_hash()

        if old_hash and old_hash != new_hash:
            self.version = (self.version or 0) + 1
            self.content_hash = new_hash

            frappe.logger().info(
                f"Contract Template {self.name} content changed: v{self.version - 1} -> v{self.version}"
            )
        elif not old_hash:
            self.content_hash = new_hash

    def calculate_content_hash(self):
        """Calculate SHA256 hash of content."""
        if not self.content:
            return None

        normalized = self.content.strip()
        return hashlib.sha256(normalized.encode('utf-8')).hexdigest()

    def validate(self):
        """Validate the template."""
        self.validate_status_transition()
        self.validate_template_code()

    def validate_status_transition(self):
        """Validate status transitions."""
        if self.is_new():
            return

        old_status = frappe.db.get_value("Contract Template", self.name, "status")

        # Cannot edit published template content
        if old_status == "Published" and self.has_value_changed("content"):
            frappe.throw(
                _("Cannot edit content of Published template. Create a new version or archive first.")
            )

        # Cannot unarchive
        if old_status == "Archived" and self.status != "Archived":
            frappe.throw(_("Cannot change status of Archived template."))

    def validate_template_code(self):
        """Ensure template_code is uppercase."""
        if self.template_code:
            self.template_code = self.template_code.upper().strip().replace(" ", "_")

    def on_trash(self):
        """Prevent deletion if template has instances."""
        instance_count = frappe.db.count(
            "Contract Instance",
            filters={"template": self.name}
        )

        if instance_count > 0:
            frappe.throw(
                _("Cannot delete template '{0}' as it has {1} contract instance(s). Archive instead.").format(
                    self.title, instance_count
                )
            )


def get_published_template(template_code):
    """
    Get the published version of a template by code.

    Args:
        template_code: Template code (e.g., 'SELLER_AGREEMENT')

    Returns:
        Document: The published Contract Template or None
    """
    template_name = frappe.db.get_value(
        "Contract Template",
        {
            "template_code": template_code.upper(),
            "status": "Published"
        },
        "name"
    )

    if template_name:
        return frappe.get_doc("Contract Template", template_name)

    return None

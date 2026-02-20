# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

"""
Consent Text DocType Controller

Consent Text stores versioned consent text with SHA256 hash verification.
Each content change triggers:
1. Version increment
2. New SHA256 hash calculation
3. Previous version linking

KVKK/GDPR Compliance:
- Every consent text must be versioned
- Content changes require new versions (no in-place editing)
- Hash verification ensures text integrity
- Audit trail of all consent text versions
"""

import frappe
from frappe import _
from frappe.model.document import Document
import hashlib


class ConsentText(Document):
    """
    Controller for Consent Text DocType.

    Implements versioning with SHA256 hash verification.
    """

    def before_insert(self):
        """Set initial values before first save."""
        if not self.created_by:
            self.created_by = frappe.session.user

        if not self.version:
            self.version = 1

        # Calculate hash for new content
        self.content_hash = self.calculate_content_hash()

    def before_save(self):
        """Handle versioning on content change."""
        if self.has_value_changed("content"):
            self.handle_content_change()

        # Auto-approve if status changed to Active
        if self.has_value_changed("status") and self.status == "Active":
            if not self.approved_by:
                self.approved_by = frappe.session.user
                self.approved_at = frappe.utils.now_datetime()

    def handle_content_change(self):
        """
        Handle content changes with versioning.

        When content changes:
        1. Increment version number
        2. Calculate new SHA256 hash
        3. Log the change
        """
        # Get old hash for comparison
        old_hash = frappe.db.get_value("Consent Text", self.name, "content_hash")

        # Calculate new hash
        new_hash = self.calculate_content_hash()

        # Only process if content actually changed (hash is different)
        if old_hash and old_hash != new_hash:
            # Increment version
            self.version = (self.version or 0) + 1
            self.content_hash = new_hash

            frappe.logger().info(
                f"Consent Text {self.name} content changed: v{self.version - 1} -> v{self.version}"
            )
        elif not old_hash:
            # First save with content
            self.content_hash = new_hash

    def calculate_content_hash(self):
        """
        Calculate SHA256 hash of the content.

        Returns:
            str: SHA256 hex digest of the content
        """
        if not self.content:
            return None

        # Normalize content (strip whitespace, normalize line endings)
        normalized_content = self.content.strip()

        # Calculate SHA256 hash
        return hashlib.sha256(normalized_content.encode('utf-8')).hexdigest()

    def validate(self):
        """Validate the consent text."""
        self.validate_status_transition()
        self.validate_active_version()

    def validate_status_transition(self):
        """Validate status transitions."""
        if self.is_new():
            return

        old_status = frappe.db.get_value("Consent Text", self.name, "status")

        # Cannot edit content once Active (must create new version)
        if old_status == "Active" and self.has_value_changed("content"):
            frappe.throw(
                _("Cannot edit content of Active consent text. Create a new version instead.")
            )

        # Cannot reactivate archived text
        if old_status == "Archived" and self.status not in ["Archived"]:
            frappe.throw(
                _("Cannot change status of Archived consent text.")
            )

    def validate_active_version(self):
        """Ensure only one active version per topic."""
        if self.status == "Active" and self.is_current:
            # Find other active current versions for same topic
            existing = frappe.db.exists(
                "Consent Text",
                {
                    "consent_topic": self.consent_topic,
                    "is_current": 1,
                    "status": "Active",
                    "name": ["!=", self.name]
                }
            )

            if existing:
                frappe.throw(
                    _("Another consent text is already the current version for this topic. "
                      "Supersede it first before making this the current version.")
                )

    def on_trash(self):
        """Prevent deletion of consent texts that are referenced."""
        # Check if any consent records reference this text
        consent_count = frappe.db.count(
            "Consent Record",
            filters={"consent_text": self.name}
        )

        if consent_count > 0:
            frappe.throw(
                _("Cannot delete Consent Text '{0}' as it is referenced by {1} consent record(s). "
                  "Archive it instead.").format(self.title, consent_count)
            )


def get_current_text(consent_topic, language="tr"):
    """
    Get the current active consent text for a topic.

    Args:
        consent_topic: The consent topic name or code
        language: Language code (default: 'tr' for Turkish)

    Returns:
        dict: Current consent text with content and metadata
    """
    # First try to find by topic name
    text = frappe.db.get_value(
        "Consent Text",
        {
            "consent_topic": consent_topic,
            "is_current": 1,
            "status": "Active"
        },
        ["name", "title", "content", "content_summary", "version",
         "content_hash", "effective_date"],
        as_dict=True
    )

    if text:
        return text

    # Try to find by topic code
    topic_name = frappe.db.get_value(
        "Consent Topic",
        {"topic_code": consent_topic.upper()},
        "name"
    )

    if topic_name:
        return frappe.db.get_value(
            "Consent Text",
            {
                "consent_topic": topic_name,
                "is_current": 1,
                "status": "Active"
            },
            ["name", "title", "content", "content_summary", "version",
             "content_hash", "effective_date"],
            as_dict=True
        )

    return None


def verify_content_hash(consent_text_name, content_to_verify):
    """
    Verify that content matches the stored hash.

    Args:
        consent_text_name: Name of the consent text
        content_to_verify: Content string to verify

    Returns:
        bool: True if hash matches, False otherwise
    """
    stored_hash = frappe.db.get_value("Consent Text", consent_text_name, "content_hash")

    if not stored_hash:
        return False

    # Normalize and hash the content
    normalized = content_to_verify.strip()
    calculated_hash = hashlib.sha256(normalized.encode('utf-8')).hexdigest()

    return stored_hash == calculated_hash


def create_new_version(consent_text_name, new_content, change_summary=None):
    """
    Create a new version of a consent text.

    Args:
        consent_text_name: Name of the current consent text
        new_content: New content for the version
        change_summary: Summary of what changed

    Returns:
        Document: The new Consent Text document
    """
    old_doc = frappe.get_doc("Consent Text", consent_text_name)

    # Create new version
    new_doc = frappe.copy_doc(old_doc)
    new_doc.content = new_content
    new_doc.change_summary = change_summary
    new_doc.previous_version = consent_text_name
    new_doc.version = old_doc.version + 1
    new_doc.status = "Draft"
    new_doc.is_current = 0
    new_doc.approved_by = None
    new_doc.approved_at = None
    new_doc.insert()

    return new_doc


def supersede_consent_text(old_name, new_name):
    """
    Mark old consent text as superseded by new one.

    Args:
        old_name: Name of the consent text to supersede
        new_name: Name of the new consent text
    """
    # Update old text
    frappe.db.set_value("Consent Text", old_name, {
        "status": "Superseded",
        "is_current": 0,
        "superseded_by": new_name
    })

    # Update new text
    frappe.db.set_value("Consent Text", new_name, {
        "is_current": 1,
        "previous_version": old_name
    })

    frappe.db.commit()

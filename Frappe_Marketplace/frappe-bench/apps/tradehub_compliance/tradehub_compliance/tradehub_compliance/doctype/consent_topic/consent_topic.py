# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

"""
Consent Topic DocType Controller

Consent Topics define what the user is consenting to.
Examples: Marketing Communications, Newsletter, Product Updates, Third Party Sharing.

KVKK/GDPR Compliance:
- Each topic must have a clear legal basis
- Marketing topics require explicit consent
- Topics can be mandatory or optional
- Separate consent may be required for sensitive purposes
"""

import frappe
from frappe import _
from frappe.model.document import Document


class ConsentTopic(Document):
    """
    Controller for Consent Topic DocType.

    Consent Topics define the purpose of consent collection.
    """

    def validate(self):
        """Validate the consent topic before saving."""
        self.validate_topic_code()
        self.validate_legal_requirements()
        self.validate_default_enabled()

    def validate_topic_code(self):
        """Ensure topic_code is uppercase and contains only valid characters."""
        if self.topic_code:
            self.topic_code = self.topic_code.upper().strip().replace(" ", "_")

            import re
            if not re.match(r'^[A-Z0-9_]+$', self.topic_code):
                frappe.throw(
                    _("Topic Code must contain only uppercase letters, numbers, and underscores")
                )

    def validate_legal_requirements(self):
        """Validate KVKK/GDPR legal requirements."""
        # Marketing topics should require explicit consent per KVKK
        if self.category == "Marketing" and not self.requires_explicit_consent:
            frappe.msgprint(
                _("Marketing topics should require explicit consent per KVKK regulations"),
                indicator="orange",
                alert=True
            )

        # Third party sharing requires separate consent
        if self.category == "Third Party" and not self.requires_separate_consent:
            frappe.msgprint(
                _("Third party data sharing should require separate consent per KVKK"),
                indicator="orange",
                alert=True
            )

    def validate_default_enabled(self):
        """Warn about pre-selected consent (KVKK requires opt-in, not opt-out)."""
        if self.default_enabled and self.requires_explicit_consent:
            frappe.msgprint(
                _("Pre-selected consent for topics requiring explicit consent may violate KVKK. "
                  "Consider setting Default Enabled to false."),
                indicator="red",
                alert=True
            )

    def on_trash(self):
        """Prevent deletion if topic is in use."""
        consent_count = frappe.db.count(
            "Consent Record",
            filters={"consent_topic": self.name}
        )

        if consent_count > 0:
            frappe.throw(
                _("Cannot delete Consent Topic '{0}' as it is referenced by {1} consent record(s). "
                  "Disable the topic instead.").format(self.topic_name, consent_count)
            )


def get_active_topics(category=None):
    """
    Get all active consent topics, optionally filtered by category.

    Args:
        category: Optional category filter

    Returns:
        list: List of active topics
    """
    filters = {"enabled": 1}
    if category:
        filters["category"] = category

    return frappe.get_all(
        "Consent Topic",
        filters=filters,
        fields=["topic_name", "topic_code", "category", "mandatory",
                "requires_explicit_consent", "description"],
        order_by="display_order asc"
    )

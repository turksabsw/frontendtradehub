# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

"""
Consent Channel DocType Controller

Consent Channels represent the source/platform where consent was collected.
Examples: Website, Mobile App, Call Center, Partner Portal, Physical Store.

KVKK/GDPR Compliance:
- Each channel can have different verification requirements
- Default retention periods follow KVKK minimum (5 years)
- Channels can be enabled/disabled without affecting existing consents
"""

import frappe
from frappe import _
from frappe.model.document import Document


class ConsentChannel(Document):
    """
    Controller for Consent Channel DocType.

    Consent Channels define where/how consent is collected.
    """

    def validate(self):
        """Validate the consent channel before saving."""
        self.validate_channel_code()
        self.validate_retention_period()
        self.set_defaults()

    def validate_channel_code(self):
        """Ensure channel_code is uppercase and contains only valid characters."""
        if self.channel_code:
            # Convert to uppercase
            self.channel_code = self.channel_code.upper().strip()

            # Replace spaces with underscores
            self.channel_code = self.channel_code.replace(" ", "_")

            # Validate format: alphanumeric and underscores only
            import re
            if not re.match(r'^[A-Z0-9_]+$', self.channel_code):
                frappe.throw(
                    _("Channel Code must contain only uppercase letters, numbers, and underscores")
                )

    def validate_retention_period(self):
        """Ensure retention period meets KVKK minimum requirements."""
        min_retention = 5  # KVKK minimum retention period in years

        if self.default_retention_years and self.default_retention_years < min_retention:
            frappe.throw(
                _("Default retention period cannot be less than {0} years per KVKK requirements").format(min_retention)
            )

    def set_defaults(self):
        """Set default values if not provided."""
        if not self.default_retention_years:
            self.default_retention_years = 5

    def before_save(self):
        """Actions before saving the document."""
        # Update channel_name if it changed (for logging purposes)
        if self.has_value_changed("channel_name"):
            frappe.logger().info(
                f"Consent Channel renamed: {self.name} -> {self.channel_name}"
            )

    def on_trash(self):
        """Prevent deletion if channel is in use by consent records."""
        # Check if any consent records reference this channel
        consent_count = frappe.db.count(
            "Consent Record",
            filters={"consent_channel": self.name}
        )

        if consent_count > 0:
            frappe.throw(
                _("Cannot delete Consent Channel '{0}' as it is referenced by {1} consent record(s). "
                  "Disable the channel instead.").format(self.channel_name, consent_count)
            )


def get_active_channels():
    """
    Get all active consent channels.

    Returns:
        list: List of dicts with channel_name and channel_code
    """
    return frappe.get_all(
        "Consent Channel",
        filters={"enabled": 1},
        fields=["channel_name", "channel_code", "channel_type", "requires_verification"],
        order_by="display_order asc"
    )


def get_channel_by_code(channel_code):
    """
    Get a consent channel by its code.

    Args:
        channel_code: The unique channel code (e.g., 'WEB', 'MOBILE')

    Returns:
        Document: The Consent Channel document or None
    """
    if not channel_code:
        return None

    channel_code = channel_code.upper().strip()

    channel_name = frappe.db.get_value(
        "Consent Channel",
        {"channel_code": channel_code, "enabled": 1},
        "name"
    )

    if channel_name:
        return frappe.get_doc("Consent Channel", channel_name)

    return None

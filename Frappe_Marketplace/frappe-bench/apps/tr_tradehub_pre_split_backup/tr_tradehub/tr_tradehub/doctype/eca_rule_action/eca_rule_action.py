# Copyright (c) 2026, TR TradeHub and contributors
# For license information, please see license.txt

import json
import frappe
from frappe import _
from frappe.model.document import Document


class ECARuleAction(Document):
    """
    ECA Rule Action Child Table

    Defines individual actions to execute when ECA rule conditions are met.
    Actions are executed in order of execution_order field.

    Supported Action Types:
    - Send Email: Send email using Email Template
    - System Notification: Create system notification for users
    - Webhook: Make HTTP request to external URL
    - Set Field: Update field value on trigger document
    - Create Document: Create new Frappe document
    - Update Document: Update existing Frappe document
    - Delete Document: Delete existing Frappe document
    - Custom Method: Call custom Python method
    - Log Message: Log message to ECA Rule Log
    """

    def validate(self):
        """Validate action configuration based on action type"""
        self.validate_action_config()
        self.validate_json_fields()

    def validate_action_config(self):
        """Ensure required fields are set for each action type"""
        if self.action_type == "Send Email":
            if not self.email_template and not self.recipients:
                frappe.throw(
                    _("Email Template or Recipients required for Send Email action"),
                    title=_("Missing Configuration")
                )

        elif self.action_type == "System Notification":
            if not self.notification_recipients and not self.notification_message:
                frappe.throw(
                    _("Recipients or Message required for System Notification action"),
                    title=_("Missing Configuration")
                )

        elif self.action_type == "Webhook":
            if not self.webhook_url:
                frappe.throw(
                    _("Webhook URL is required for Webhook action"),
                    title=_("Missing Configuration")
                )

        elif self.action_type == "Set Field":
            if not self.target_field:
                frappe.throw(
                    _("Target Field is required for Set Field action"),
                    title=_("Missing Configuration")
                )

        elif self.action_type in ["Create Document", "Update Document", "Delete Document"]:
            if not self.target_doctype:
                frappe.throw(
                    _("Target DocType is required for {0} action").format(self.action_type),
                    title=_("Missing Configuration")
                )

        elif self.action_type == "Custom Method":
            if not self.custom_method:
                frappe.throw(
                    _("Custom Method is required for Custom Method action"),
                    title=_("Missing Configuration")
                )

    def validate_json_fields(self):
        """Validate JSON format for configuration fields"""
        json_fields = ["webhook_headers", "webhook_body", "document_values", "custom_args"]

        for field in json_fields:
            value = getattr(self, field, None)
            if value:
                try:
                    json.loads(value)
                except json.JSONDecodeError:
                    frappe.throw(
                        _("{0} must be valid JSON").format(field.replace("_", " ").title()),
                        title=_("Invalid JSON")
                    )

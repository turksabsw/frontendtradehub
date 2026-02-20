# Copyright (c) 2026, TR TradeHub and contributors
# For license information, please see license.txt

import re
import json
import frappe
from frappe import _
from frappe.model.document import Document


class ECAActionTemplate(Document):
    """
    ECA Action Template DocType

    Provides reusable action configurations that can be referenced
    by ECA Rules. Templates define pre-configured actions for common
    workflows like stock alerts, order notifications, price change webhooks, etc.

    Categories:
    - Commerce: Stock alerts, price changes, order processing
    - Communication: Email notifications, SMS alerts
    - Compliance: Audit logging, certificate expiry warnings
    - Integration: Webhooks, API calls, data sync
    - Notification: System notifications, alerts
    - Workflow: Status updates, document creation
    """

    def validate(self):
        """Validate the template configuration"""
        self.validate_template_code()
        self.validate_config()

    def validate_template_code(self):
        """Ensure template_code is valid"""
        if self.template_code:
            # Normalize the code
            self.template_code = self.template_code.lower().replace(" ", "_").replace("-", "_")

            # Validate format
            if not re.match(r'^[a-z][a-z0-9_]*$', self.template_code):
                frappe.throw(
                    _("Template Code must start with a letter and contain only lowercase letters, numbers, and underscores"),
                    title=_("Invalid Template Code")
                )

    def validate_config(self):
        """Validate JSON configuration"""
        if self.config:
            try:
                config = json.loads(self.config)
                self.validate_config_for_action_type(config)
            except json.JSONDecodeError:
                frappe.throw(
                    _("Configuration must be valid JSON"),
                    title=_("Invalid JSON")
                )

    def validate_config_for_action_type(self, config):
        """Validate config structure based on action_type"""
        required_fields = {
            "Send Email": ["recipients"],
            "System Notification": ["recipients", "message"],
            "Webhook": ["url"],
            "Set Field": ["target_field", "target_value"],
            "Create Document": ["target_doctype"],
            "Update Document": ["target_doctype"],
            "Delete Document": ["target_doctype"],
            "Custom Method": ["method"]
        }

        if self.action_type in required_fields:
            missing = [f for f in required_fields[self.action_type] if f not in config]
            if missing:
                frappe.msgprint(
                    _("Template configuration is missing recommended fields: {0}").format(", ".join(missing)),
                    indicator="yellow"
                )

    def get_config_dict(self):
        """
        Get configuration as dictionary

        Returns:
            dict: Configuration dictionary
        """
        if self.config:
            return json.loads(self.config)
        return {}

    def apply_to_action(self, action_row):
        """
        Apply template configuration to an ECA Rule Action row

        Args:
            action_row: ECA Rule Action child table row

        Returns:
            ECA Rule Action: Updated action row
        """
        config = self.get_config_dict()

        action_row.action_type = self.action_type

        # Map config fields to action fields based on action type
        if self.action_type == "Send Email":
            action_row.email_template = config.get("email_template")
            action_row.recipients = config.get("recipients")
            action_row.cc_recipients = config.get("cc_recipients")
            action_row.subject_override = config.get("subject_override")

        elif self.action_type == "System Notification":
            action_row.notification_type = config.get("notification_type", "System")
            action_row.notification_recipients = config.get("recipients")
            action_row.notification_message = config.get("message")

        elif self.action_type == "Webhook":
            action_row.webhook_url = config.get("url")
            action_row.webhook_method = config.get("method", "POST")
            action_row.webhook_headers = json.dumps(config.get("headers", {}))
            action_row.webhook_body = json.dumps(config.get("body", {}))

        elif self.action_type == "Set Field":
            action_row.target_field = config.get("target_field")
            action_row.target_value = config.get("target_value")

        elif self.action_type in ["Create Document", "Update Document", "Delete Document"]:
            action_row.target_doctype = config.get("target_doctype")
            action_row.document_values = json.dumps(config.get("values", {}))
            action_row.link_to_parent = config.get("link_to_parent", False)
            action_row.parent_field_name = config.get("parent_field_name")

        elif self.action_type == "Custom Method":
            action_row.custom_method = config.get("method")
            action_row.custom_args = json.dumps(config.get("args", {}))

        return action_row

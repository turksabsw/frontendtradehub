# Copyright (c) 2026, TR TradeHub and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
import json
import re


class SalesChannel(Document):
    """
    Sales Channel DocType

    Defines sales channels for multi-channel product publishing including
    marketplaces (Amazon, eBay, Alibaba, Trendyol, etc.), webstores,
    B2B portals, feeds, and custom API integrations.
    """

    def validate(self):
        """Validate the document before saving"""
        self.validate_channel_code()
        self.validate_api_credentials()
        self.validate_category_tree()
        self.validate_export_schedule()
        self.set_defaults()

    def validate_channel_code(self):
        """Ensure channel_code is lowercase and contains only valid characters"""
        if self.channel_code:
            # Convert to lowercase and replace spaces with underscores
            self.channel_code = self.channel_code.lower().replace(" ", "_").replace("-", "_")

            # Check for valid characters (alphanumeric and underscore only)
            if not re.match(r'^[a-z0-9_]+$', self.channel_code):
                frappe.throw(
                    _("Channel Code can only contain lowercase letters, numbers, and underscores"),
                    title=_("Invalid Channel Code")
                )

    def validate_api_credentials(self):
        """Validate that api_credentials is valid JSON if provided"""
        if self.api_credentials:
            try:
                parsed = json.loads(self.api_credentials)
                if not isinstance(parsed, dict):
                    frappe.throw(
                        _("API Credentials must be a JSON object"),
                        title=_("Invalid API Credentials")
                    )
            except json.JSONDecodeError as e:
                frappe.throw(
                    _("API Credentials contains invalid JSON: {0}").format(str(e)),
                    title=_("Invalid JSON")
                )

    def validate_category_tree(self):
        """Validate that category_tree is valid JSON if provided"""
        if self.category_tree:
            try:
                parsed = json.loads(self.category_tree)
                if not isinstance(parsed, (dict, list)):
                    frappe.throw(
                        _("Category Tree must be a JSON object or array"),
                        title=_("Invalid Category Tree")
                    )
            except json.JSONDecodeError as e:
                frappe.throw(
                    _("Category Tree contains invalid JSON: {0}").format(str(e)),
                    title=_("Invalid JSON")
                )

    def validate_export_schedule(self):
        """Basic validation of cron expression format"""
        if self.export_schedule:
            parts = self.export_schedule.strip().split()
            if len(parts) != 5:
                frappe.throw(
                    _("Export Schedule must be a valid cron expression with 5 parts (minute hour day month weekday)"),
                    title=_("Invalid Cron Expression")
                )

    def set_defaults(self):
        """Set default values if not provided"""
        if self.is_active is None:
            self.is_active = 1

        if self.is_default is None:
            self.is_default = 0

        if self.priority is None:
            self.priority = 0

        if not self.default_locale:
            self.default_locale = "en_US"

        if not self.export_batch_size:
            self.export_batch_size = 100

        if not self.export_retry_count:
            self.export_retry_count = 3

        if not self.requests_per_minute:
            self.requests_per_minute = 60

        if self.cooldown_seconds is None:
            self.cooldown_seconds = 0

    def before_save(self):
        """Actions to perform before saving"""
        # If setting this channel as default, unset other defaults
        if self.is_default:
            frappe.db.sql("""
                UPDATE `tabSales Channel`
                SET is_default = 0
                WHERE name != %s AND is_default = 1
            """, (self.name,))

    def get_api_credentials_dict(self):
        """Return API credentials as a Python dictionary"""
        if self.api_credentials:
            try:
                return json.loads(self.api_credentials)
            except json.JSONDecodeError:
                return {}
        return {}

    def get_category_tree_data(self):
        """Return category tree as a Python object"""
        if self.category_tree:
            try:
                return json.loads(self.category_tree)
            except json.JSONDecodeError:
                return None
        return None

    def update_last_export(self):
        """Update the last_export timestamp"""
        self.db_set('last_export', frappe.utils.now())

    def before_rename(self, old_name, new_name, merge=False):
        """Handle rename operations"""
        if merge:
            frappe.throw(
                _("Cannot merge Sales Channels"),
                title=_("Merge Not Allowed")
            )

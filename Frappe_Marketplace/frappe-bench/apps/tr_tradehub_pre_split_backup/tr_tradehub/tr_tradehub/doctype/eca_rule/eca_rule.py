# Copyright (c) 2026, TR TradeHub and contributors
# For license information, please see license.txt

import re
import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime


class ECARule(Document):
    """
    ECA Rule DocType

    Defines Event-Condition-Action rules for automated workflows.
    Rules trigger on document events, evaluate conditions, and execute actions.

    Features:
    - Event-based triggers (before_insert, after_save, on_submit, etc.)
    - Cron-based scheduled execution
    - Field-based conditions with multiple operators
    - Jinja template conditions with SandboxedEnvironment
    - Python conditions with sandboxed execution
    - Multiple action types (email, webhook, set field, create doc, etc.)
    - Rate limiting (per minute, per day, cooldown)
    - Comprehensive logging to ECA Rule Log
    """

    def validate(self):
        """Validate the rule configuration"""
        self.validate_rule_code()
        self.validate_event_config()
        self.validate_conditions()
        self.validate_rate_limiting()
        self.validate_cron_expression()
        self.set_defaults()

    def validate_rule_code(self):
        """Generate or validate rule_code"""
        if not self.rule_code:
            # Auto-generate from rule_name
            base_code = re.sub(r'[^a-zA-Z0-9]', '_', self.rule_name.lower())
            base_code = re.sub(r'_+', '_', base_code).strip('_')
            self.rule_code = base_code[:50]  # Limit length

        # Validate format
        if not re.match(r'^[a-z][a-z0-9_]*$', self.rule_code):
            frappe.throw(
                _("Rule Code must start with a letter and contain only lowercase letters, numbers, and underscores"),
                title=_("Invalid Rule Code")
            )

    def validate_event_config(self):
        """Validate event configuration"""
        if self.event_doctype:
            # Verify DocType exists
            if not frappe.db.exists("DocType", self.event_doctype):
                frappe.throw(
                    _("Event DocType '{0}' does not exist").format(self.event_doctype),
                    title=_("Invalid DocType")
                )

        # Validate filter field exists on DocType
        if self.filter_doctype_field and self.event_doctype:
            meta = frappe.get_meta(self.event_doctype)
            if not meta.has_field(self.filter_doctype_field):
                frappe.msgprint(
                    _("Filter field '{0}' does not exist on DocType '{1}'").format(
                        self.filter_doctype_field, self.event_doctype
                    ),
                    indicator="yellow"
                )

    def validate_conditions(self):
        """Validate condition configuration"""
        # Validate Jinja condition syntax (basic check)
        if self.jinja_condition:
            # Check for balanced braces
            if self.jinja_condition.count('{{') != self.jinja_condition.count('}}'):
                frappe.throw(
                    _("Jinja Condition has unbalanced braces"),
                    title=_("Invalid Jinja Syntax")
                )

        # Validate Python condition (basic syntax check)
        if self.python_condition:
            try:
                compile(self.python_condition, '<string>', 'eval')
            except SyntaxError as e:
                frappe.throw(
                    _("Python Condition has syntax error: {0}").format(str(e)),
                    title=_("Invalid Python Syntax")
                )

    def validate_rate_limiting(self):
        """Validate rate limiting configuration"""
        if self.max_executions_per_minute and self.max_executions_per_minute < 0:
            frappe.throw(
                _("Max Executions/Minute cannot be negative"),
                title=_("Invalid Configuration")
            )

        if self.cooldown_seconds and self.cooldown_seconds < 0:
            frappe.throw(
                _("Cooldown cannot be negative"),
                title=_("Invalid Configuration")
            )

        if self.max_daily_executions and self.max_daily_executions < 0:
            frappe.throw(
                _("Max Daily Executions cannot be negative"),
                title=_("Invalid Configuration")
            )

    def validate_cron_expression(self):
        """Validate cron expression if schedule_type is Cron"""
        if self.schedule_type == "Cron" and self.cron_expression:
            # Basic cron validation (5 or 6 fields)
            parts = self.cron_expression.strip().split()
            if len(parts) not in [5, 6]:
                frappe.throw(
                    _("Invalid cron expression. Must have 5 or 6 fields."),
                    title=_("Invalid Cron")
                )

    def set_defaults(self):
        """Set default values"""
        if not self.created_by_user:
            self.created_by_user = frappe.session.user

        if self.is_active is None:
            self.is_active = 1

        if not self.priority:
            self.priority = 10

    def before_save(self):
        """Before save hooks"""
        # Sort actions by execution_order
        if self.actions:
            self.actions = sorted(self.actions, key=lambda x: x.execution_order or 0)

    def on_update(self):
        """After update hooks"""
        # Clear cached rules
        frappe.cache().delete_key("eca_rules_cache")

    def on_trash(self):
        """Before deletion hooks"""
        # Check if rule has execution logs
        log_count = frappe.db.count("ECA Rule Log", {"eca_rule": self.name})
        if log_count > 0:
            frappe.msgprint(
                _("This rule has {0} execution logs that will be orphaned").format(log_count),
                indicator="yellow"
            )

    # Helper Methods

    def get_conditions_dict(self):
        """
        Get conditions as a list of dictionaries

        Returns:
            list: Condition dictionaries
        """
        return [
            {
                "field_name": c.field_name,
                "operator": c.operator,
                "value": c.value,
                "value_type": c.value_type,
                "logic_operator": c.logic_operator
            }
            for c in self.conditions
        ]

    def get_actions_dict(self):
        """
        Get actions as a list of dictionaries

        Returns:
            list: Action dictionaries with configuration
        """
        return [
            {
                "action_type": a.action_type,
                "execution_order": a.execution_order,
                "is_active": a.is_active,
                "stop_on_error": a.stop_on_error,
                "async_execution": a.async_execution,
                "config": self._get_action_config(a)
            }
            for a in self.actions if a.is_active
        ]

    def _get_action_config(self, action):
        """Extract action-specific configuration"""
        config = {}

        if action.action_type == "Send Email":
            config = {
                "email_template": action.email_template,
                "recipients": action.recipients,
                "cc_recipients": action.cc_recipients,
                "subject_override": action.subject_override
            }
        elif action.action_type == "System Notification":
            config = {
                "notification_type": action.notification_type,
                "recipients": action.notification_recipients,
                "message": action.notification_message
            }
        elif action.action_type == "Webhook":
            config = {
                "url": action.webhook_url,
                "method": action.webhook_method,
                "headers": action.webhook_headers,
                "body": action.webhook_body
            }
        elif action.action_type == "Set Field":
            config = {
                "target_field": action.target_field,
                "target_value": action.target_value
            }
        elif action.action_type in ["Create Document", "Update Document", "Delete Document"]:
            config = {
                "target_doctype": action.target_doctype,
                "document_values": action.document_values,
                "link_to_parent": action.link_to_parent,
                "parent_field_name": action.parent_field_name
            }
        elif action.action_type == "Custom Method":
            config = {
                "method": action.custom_method,
                "args": action.custom_args
            }

        return config

    def update_last_execution(self):
        """Update last_execution timestamp"""
        self.db_set("last_execution", now_datetime(), update_modified=False)

    def check_rate_limit(self, doc_name=None, user=None):
        """
        Check if rule execution is within rate limits

        Args:
            doc_name: Document name for per-document scope
            user: User for per-user scope

        Returns:
            tuple: (is_allowed, reason)
        """
        from frappe.utils import now_datetime, add_to_date, get_datetime

        now = now_datetime()

        # Check cooldown
        if self.cooldown_seconds and self.last_execution:
            cooldown_until = add_to_date(
                get_datetime(self.last_execution),
                seconds=self.cooldown_seconds
            )
            if now < cooldown_until:
                return False, _("Rule is in cooldown period")

        # Build scope filters for log queries
        scope_filters = {"eca_rule": self.name}
        if self.rate_limit_scope == "Per Document" and doc_name:
            scope_filters["trigger_document"] = doc_name
        elif self.rate_limit_scope == "Per User" and user:
            scope_filters["trigger_user"] = user

        # Check per-minute limit
        if self.max_executions_per_minute:
            minute_ago = add_to_date(now, minutes=-1)
            minute_count = frappe.db.count(
                "ECA Rule Log",
                filters={
                    **scope_filters,
                    "creation": [">=", minute_ago]
                }
            )
            if minute_count >= self.max_executions_per_minute:
                return False, _("Exceeded max executions per minute")

        # Check daily limit
        if self.max_daily_executions:
            today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            daily_count = frappe.db.count(
                "ECA Rule Log",
                filters={
                    **scope_filters,
                    "creation": [">=", today_start]
                }
            )
            if daily_count >= self.max_daily_executions:
                return False, _("Exceeded max daily executions")

        return True, None

    def matches_filter(self, doc):
        """
        Check if document matches the rule's filter criteria

        Args:
            doc: Frappe document to check

        Returns:
            bool: True if document matches filter
        """
        if not self.filter_doctype_field:
            return True

        doc_value = doc.get(self.filter_doctype_field)
        filter_value = self.filter_doctype_value

        # Handle empty filter value (match any)
        if not filter_value:
            return True

        return str(doc_value) == str(filter_value)

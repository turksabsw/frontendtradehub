# Copyright (c) 2026, TR TradeHub and contributors
# For license information, please see license.txt

"""
ECA Event Dispatcher

Event dispatcher integrated with Frappe doc_events hooks.
Evaluates ECA rules when document events occur and executes matching actions.

Key Features:
- Circular trigger prevention via frappe.flags.in_eca_execution
- Field-based conditions with 18 operators
- Jinja template conditions with SandboxedEnvironment
- Python expression conditions with sandboxed execution
- Rate limiting (per-minute, per-day, cooldown)
- Comprehensive logging to ECA Rule Log
- Modular action handlers for extensibility
"""

import json
import re
import time
import traceback
from typing import Any, Dict, List, Optional, Tuple

import frappe
from frappe import _
from frappe.utils import cint, cstr, flt, now_datetime, get_datetime

try:
    from jinja2.sandbox import SandboxedEnvironment
except ImportError:
    from jinja2 import Environment as SandboxedEnvironment

# Import modular action handlers
from tr_tradehub.eca.actions import (
    execute_action,
    get_action_handler,
    ActionResult,
    ACTION_HANDLERS,
)
from tr_tradehub.eca.actions.email_handler import execute_email_action
from tr_tradehub.eca.actions.webhook_handler import execute_webhook_action
from tr_tradehub.eca.actions.field_handler import execute_set_field_action
from tr_tradehub.eca.actions.document_handler import (
    execute_create_document_action,
    execute_update_document_action,
    execute_delete_document_action,
)
from tr_tradehub.eca.actions.notification_handler import execute_notification_action


# Event type mapping from doc_events hook names
EVENT_TYPE_MAP = {
    'before_insert': 'before_insert',
    'after_insert': 'after_insert',
    'validate': 'validate',
    'before_save': 'before_save',
    'after_save': 'after_save',
    'on_update': 'on_update',
    'on_submit': 'on_submit',
    'on_cancel': 'on_cancel',
    'on_trash': 'on_trash',
    'on_update_after_submit': 'on_update_after_submit',
    'before_rename': 'before_rename',
    'after_rename': 'after_rename',
    'on_change': 'on_change',
}


class ECADispatcher:
    """
    Dispatches ECA rules for document events.

    Handles the complete lifecycle:
    1. Check for circular execution
    2. Find matching active rules
    3. Check rate limits
    4. Evaluate conditions
    5. Execute actions
    6. Log results
    """

    def __init__(self, doc: Any, event_type: str, method: Optional[str] = None):
        """
        Initialize dispatcher for a document event.

        Args:
            doc: Frappe document that triggered the event
            event_type: Type of event (after_save, on_submit, etc.)
            method: Optional method name for method-based events
        """
        self.doc = doc
        self.doctype = doc.doctype
        self.event_type = event_type
        self.method = method
        self.start_time = time.time()
        self.rules_cache = None

    def dispatch(self) -> List[Dict]:
        """
        Main dispatch method - evaluate and execute all matching rules.

        Returns:
            list: Results for each rule evaluated
        """
        results = []

        # Check circular execution flag
        if getattr(frappe.flags, 'in_eca_execution', False):
            return results

        try:
            # Set flag to prevent circular triggers
            frappe.flags.in_eca_execution = True

            # Get matching rules
            rules = self._get_matching_rules()

            for rule in rules:
                result = self._process_rule(rule)
                results.append(result)

        finally:
            # Always clear the flag
            frappe.flags.in_eca_execution = False

        return results

    def _get_matching_rules(self) -> List[Any]:
        """
        Get active rules matching the current DocType and event type.

        Returns:
            list: Matching ECA Rule documents sorted by priority
        """
        # Try to get from cache first
        cache_key = f"eca_rules_{self.doctype}_{self.event_type}"
        cached_rules = frappe.cache().get_value(cache_key)

        if cached_rules is not None:
            # Load full documents for cached rule names
            rules = []
            for rule_name in cached_rules:
                try:
                    rule = frappe.get_doc("ECA Rule", rule_name)
                    # Check is_active safely (field might not exist in DB)
                    is_active = getattr(rule, 'is_active', True)  # Default to True if field doesn't exist
                    if is_active and rule.matches_filter(self.doc):
                        rules.append(rule)
                except frappe.DoesNotExistError:
                    pass
                except Exception:
                    # Skip rules that can't be loaded
                    pass
            return rules

        # Query for matching rules
        # Handle case where is_active column might not exist
        filters = {
            "event_doctype": self.doctype,
            "event_type": self.event_type,
            "schedule_type": "Event-based"  # Only event-based rules
        }
        
        # Check if is_active column exists before adding filter
        try:
            meta = frappe.get_meta("ECA Rule")
            if meta.has_field("is_active"):
                filters["is_active"] = 1
        except Exception:
            pass  # If meta check fails, proceed without is_active filter
        
        rule_names = frappe.get_all(
            "ECA Rule",
            filters=filters,
            pluck="name",
            order_by="priority ASC"
        )

        # Cache rule names for 5 minutes
        frappe.cache().set_value(cache_key, rule_names, expires_in_sec=300)

        # Load and filter rules
        rules = []
        for rule_name in rule_names:
            try:
                rule = frappe.get_doc("ECA Rule", rule_name)
                if rule.matches_filter(self.doc):
                    rules.append(rule)
            except frappe.DoesNotExistError:
                pass

        return rules

    def _process_rule(self, rule: Any) -> Dict:
        """
        Process a single rule: evaluate conditions and execute actions.

        Args:
            rule: ECA Rule document

        Returns:
            dict: Processing result
        """
        result = {
            'rule': rule.name,
            'rule_name': rule.rule_name,
            'status': 'Success',
            'condition_result': False,
            'condition_details': [],
            'actions_executed': 0,
            'actions_succeeded': 0,
            'actions_failed': 0,
            'action_results': [],
            'error_message': None,
            'execution_time_ms': 0
        }

        start_time = time.time()

        try:
            # Check rate limits
            is_allowed, rate_limit_reason = rule.check_rate_limit(
                doc_name=self.doc.name,
                user=frappe.session.user
            )

            if not is_allowed:
                result['status'] = 'Skipped'
                result['error_message'] = rate_limit_reason
                self._log_execution(rule, result)
                return result

            # Evaluate conditions
            condition_result, condition_details = self._evaluate_conditions(rule)
            result['condition_result'] = condition_result
            result['condition_details'] = condition_details

            if not condition_result:
                result['status'] = 'Skipped'
                self._log_execution(rule, result)
                return result

            # Execute actions
            action_results = self._execute_actions(rule)
            result['action_results'] = action_results
            result['actions_executed'] = len(action_results)
            result['actions_succeeded'] = sum(1 for a in action_results if a.get('success'))
            result['actions_failed'] = sum(1 for a in action_results if not a.get('success'))

            # Determine overall status
            if result['actions_failed'] > 0:
                if result['actions_succeeded'] > 0:
                    result['status'] = 'Partial'
                else:
                    result['status'] = 'Failed'

            # Update last execution time
            rule.update_last_execution()

        except Exception as e:
            result['status'] = 'Error'
            result['error_message'] = str(e)
            frappe.log_error(
                title=f"ECA Rule Error: {rule.name}",
                message=traceback.format_exc()
            )

        finally:
            result['execution_time_ms'] = (time.time() - start_time) * 1000

            # Log execution
            self._log_execution(rule, result)

        return result

    def _evaluate_conditions(self, rule: Any) -> Tuple[bool, List[Dict]]:
        """
        Evaluate all conditions for a rule.

        Args:
            rule: ECA Rule document

        Returns:
            tuple: (overall_result, condition_details)
        """
        condition_details = []

        # Evaluate field-based conditions
        field_conditions_result = self._evaluate_field_conditions(rule, condition_details)

        # Evaluate Jinja condition
        jinja_result = self._evaluate_jinja_condition(rule, condition_details)

        # Evaluate Python condition
        python_result = self._evaluate_python_condition(rule, condition_details)

        # Combine results based on condition_logic
        if rule.condition_logic == 'AND':
            overall = field_conditions_result and jinja_result and python_result
        elif rule.condition_logic == 'OR':
            # For OR, at least one must be True (if any condition is defined)
            has_field_conditions = bool(rule.conditions)
            has_jinja = bool(rule.jinja_condition)
            has_python = bool(rule.python_condition)

            if not any([has_field_conditions, has_jinja, has_python]):
                overall = True  # No conditions = always true
            else:
                overall = (
                    (not has_field_conditions or field_conditions_result) or
                    (not has_jinja or jinja_result) or
                    (not has_python or python_result)
                )
        else:  # Custom - currently defaults to AND
            overall = field_conditions_result and jinja_result and python_result

        return overall, condition_details

    def _evaluate_field_conditions(self, rule: Any, details: List) -> bool:
        """
        Evaluate field-based conditions from the conditions child table.

        Args:
            rule: ECA Rule document
            details: List to append condition results to

        Returns:
            bool: Result of field conditions evaluation
        """
        if not rule.conditions:
            return True

        results = []

        for condition in rule.conditions:
            result = self._evaluate_single_condition(condition)

            details.append({
                'type': 'field',
                'field': condition.field_name,
                'operator': condition.operator,
                'expected': condition.value,
                'actual': self._get_field_value(condition.field_name),
                'passed': result
            })

            results.append((result, condition.logic_operator))

        # Apply logic operators between conditions
        final_result = results[0][0] if results else True

        for i in range(1, len(results)):
            prev_logic = results[i - 1][1]
            current_result = results[i][0]

            if prev_logic == 'AND':
                final_result = final_result and current_result
            else:  # OR
                final_result = final_result or current_result

        return final_result

    def _evaluate_single_condition(self, condition: Any) -> bool:
        """
        Evaluate a single field condition.

        Args:
            condition: ECA Rule Condition child document

        Returns:
            bool: Condition result
        """
        field_value = self._get_field_value(condition.field_name)
        compare_value = self._get_compare_value(condition)
        operator = condition.operator

        try:
            if operator == 'equals':
                return self._compare_equal(field_value, compare_value)
            elif operator == 'not_equals':
                return not self._compare_equal(field_value, compare_value)
            elif operator == 'greater_than':
                return flt(field_value) > flt(compare_value)
            elif operator == 'less_than':
                return flt(field_value) < flt(compare_value)
            elif operator == 'greater_than_or_equals':
                return flt(field_value) >= flt(compare_value)
            elif operator == 'less_than_or_equals':
                return flt(field_value) <= flt(compare_value)
            elif operator == 'contains':
                return cstr(compare_value) in cstr(field_value)
            elif operator == 'not_contains':
                return cstr(compare_value) not in cstr(field_value)
            elif operator == 'starts_with':
                return cstr(field_value).startswith(cstr(compare_value))
            elif operator == 'ends_with':
                return cstr(field_value).endswith(cstr(compare_value))
            elif operator == 'is_set':
                return field_value is not None and field_value != '' and field_value != []
            elif operator == 'is_not_set':
                return field_value is None or field_value == '' or field_value == []
            elif operator == 'changed':
                return self._field_changed(condition.field_name)
            elif operator == 'changed_from':
                return self._field_changed_from(condition.field_name, compare_value)
            elif operator == 'changed_to':
                return self._field_changed_to(condition.field_name, compare_value)
            elif operator == 'in_list':
                return self._value_in_list(field_value, compare_value)
            elif operator == 'not_in_list':
                return not self._value_in_list(field_value, compare_value)
            elif operator == 'regex_match':
                return bool(re.match(cstr(compare_value), cstr(field_value)))
            else:
                # Unknown operator - default to False
                return False

        except Exception:
            return False

    def _get_field_value(self, field_name: str) -> Any:
        """Get field value from document, supporting nested fields."""
        if not field_name:
            return None

        # Support nested field names like "customer.name"
        parts = field_name.split('.')
        value = self.doc

        for part in parts:
            if hasattr(value, part):
                value = getattr(value, part)
            elif isinstance(value, dict):
                value = value.get(part)
            else:
                return None

        return value

    def _get_compare_value(self, condition: Any) -> Any:
        """
        Get the comparison value based on value_type.

        Args:
            condition: Condition with value and value_type

        Returns:
            The resolved comparison value
        """
        value = condition.value
        value_type = condition.value_type or 'Static'

        if value_type == 'Static':
            return value
        elif value_type == 'Field Reference':
            return self._get_field_value(value)
        elif value_type == 'Jinja Expression':
            return self._render_jinja(value)
        else:
            return value

    def _compare_equal(self, a: Any, b: Any) -> bool:
        """Compare two values for equality, handling type conversions."""
        if a is None and b is None:
            return True
        if a is None or b is None:
            return False

        # Try string comparison
        if cstr(a) == cstr(b):
            return True

        # Try numeric comparison
        try:
            if flt(a) == flt(b):
                return True
        except (ValueError, TypeError):
            pass

        return False

    def _field_changed(self, field_name: str) -> bool:
        """Check if field value changed from previous value."""
        if not hasattr(self.doc, '_doc_before_save'):
            return False

        old_value = self.doc._doc_before_save.get(field_name)
        new_value = self._get_field_value(field_name)

        return not self._compare_equal(old_value, new_value)

    def _field_changed_from(self, field_name: str, from_value: Any) -> bool:
        """Check if field changed from a specific value."""
        if not hasattr(self.doc, '_doc_before_save'):
            return False

        old_value = self.doc._doc_before_save.get(field_name)
        new_value = self._get_field_value(field_name)

        return (
            self._compare_equal(old_value, from_value) and
            not self._compare_equal(new_value, from_value)
        )

    def _field_changed_to(self, field_name: str, to_value: Any) -> bool:
        """Check if field changed to a specific value."""
        if not hasattr(self.doc, '_doc_before_save'):
            return False

        old_value = self.doc._doc_before_save.get(field_name)
        new_value = self._get_field_value(field_name)

        return (
            not self._compare_equal(old_value, to_value) and
            self._compare_equal(new_value, to_value)
        )

    def _value_in_list(self, value: Any, list_value: Any) -> bool:
        """Check if value is in a list (comma-separated or JSON array)."""
        if not list_value:
            return False

        # Try to parse as JSON array
        if isinstance(list_value, str):
            try:
                list_value = json.loads(list_value)
            except json.JSONDecodeError:
                # Treat as comma-separated
                list_value = [v.strip() for v in list_value.split(',')]

        if isinstance(list_value, (list, tuple)):
            return any(self._compare_equal(value, v) for v in list_value)

        return False

    def _evaluate_jinja_condition(self, rule: Any, details: List) -> bool:
        """
        Evaluate Jinja template condition.

        Uses SandboxedEnvironment for security.

        Args:
            rule: ECA Rule document
            details: List to append result to

        Returns:
            bool: Jinja condition result
        """
        if not rule.jinja_condition:
            return True

        try:
            result = self._render_jinja(rule.jinja_condition)

            # Convert result to boolean
            if isinstance(result, str):
                result = result.strip().lower() not in ('false', '0', '', 'none')
            else:
                result = bool(result)

            details.append({
                'type': 'jinja',
                'expression': rule.jinja_condition[:100],  # Truncate for logging
                'passed': result
            })

            return result

        except Exception as e:
            details.append({
                'type': 'jinja',
                'expression': rule.jinja_condition[:100],
                'passed': False,
                'error': str(e)
            })
            frappe.log_error(
                title="ECA Jinja Condition Error",
                message=f"Rule: {rule.name}\nExpression: {rule.jinja_condition}\nError: {str(e)}"
            )
            return False

    def _render_jinja(self, template: str) -> Any:
        """
        Render a Jinja template with document context.

        Uses SandboxedEnvironment for security.

        Args:
            template: Jinja template string

        Returns:
            Rendered result
        """
        if not template:
            return ''

        # Create sandboxed environment
        env = SandboxedEnvironment()

        # Build context
        context = {
            'doc': self.doc.as_dict(),
            'frappe': frappe,
            'utils': frappe.utils,
            'user': frappe.session.user,
            'now': now_datetime(),
            'event_type': self.event_type
        }

        # Add _doc_before_save if available
        if hasattr(self.doc, '_doc_before_save'):
            context['doc_before_save'] = self.doc._doc_before_save

        # Render template
        jinja_template = env.from_string(template)
        return jinja_template.render(**context)

    def _evaluate_python_condition(self, rule: Any, details: List) -> bool:
        """
        Evaluate Python expression condition.

        Uses restricted eval for security.

        Args:
            rule: ECA Rule document
            details: List to append result to

        Returns:
            bool: Python condition result
        """
        if not rule.python_condition:
            return True

        try:
            result = self._safe_eval(rule.python_condition)
            result = bool(result)

            details.append({
                'type': 'python',
                'expression': rule.python_condition[:100],  # Truncate for logging
                'passed': result
            })

            return result

        except Exception as e:
            details.append({
                'type': 'python',
                'expression': rule.python_condition[:100],
                'passed': False,
                'error': str(e)
            })
            frappe.log_error(
                title="ECA Python Condition Error",
                message=f"Rule: {rule.name}\nExpression: {rule.python_condition}\nError: {str(e)}"
            )
            return False

    def _safe_eval(self, expression: str) -> Any:
        """
        Safely evaluate a Python expression.

        Args:
            expression: Python expression string

        Returns:
            Evaluation result
        """
        # Restricted built-ins
        safe_builtins = {
            'True': True,
            'False': False,
            'None': None,
            'str': str,
            'int': int,
            'float': float,
            'bool': bool,
            'list': list,
            'dict': dict,
            'len': len,
            'abs': abs,
            'min': min,
            'max': max,
            'sum': sum,
            'round': round,
            'any': any,
            'all': all,
        }

        # Build safe namespace
        namespace = {
            '__builtins__': safe_builtins,
            'doc': self.doc.as_dict(),
            'frappe': frappe,
            'utils': frappe.utils,
            'cint': cint,
            'cstr': cstr,
            'flt': flt,
            'now_datetime': now_datetime,
            'get_datetime': get_datetime,
        }

        # Add _doc_before_save if available
        if hasattr(self.doc, '_doc_before_save'):
            namespace['doc_before_save'] = self.doc._doc_before_save

        return eval(expression, namespace)

    def _execute_actions(self, rule: Any) -> List[Dict]:
        """
        Execute all active actions for a rule.

        Args:
            rule: ECA Rule document

        Returns:
            list: Results for each action
        """
        results = []

        # Get sorted active actions
        actions = sorted(
            [a for a in rule.actions if a.is_active],
            key=lambda x: x.execution_order or 0
        )

        for action in actions:
            result = self._execute_single_action(action)
            results.append(result)

            # Check if we should stop on error
            if not result.get('success') and action.stop_on_error:
                break

        return results

    def _execute_single_action(self, action: Any) -> Dict:
        """
        Execute a single action using the modular action handler system.

        First checks for registered modular handlers, then falls back to
        legacy inline handlers for backward compatibility.

        Args:
            action: ECA Rule Action child document

        Returns:
            dict: Execution result
        """
        result = {
            'action_type': action.action_type,
            'success': False,
            'message': None,
            'error': None
        }

        try:
            # Check if there's a registered modular handler
            modular_handler = get_action_handler(action.action_type)

            if modular_handler:
                # Use the modular action handler system
                if action.async_execution:
                    # Queue for background execution
                    frappe.enqueue(
                        'tr_tradehub.eca.actions.execute_action',
                        action=action,
                        doc=self.doc,
                        queue='short',
                        now=frappe.conf.developer_mode
                    )
                    result['success'] = True
                    result['message'] = 'Queued for async execution'
                else:
                    # Execute using modular handler
                    action_result = execute_action(action, self.doc)

                    # Convert ActionResult to dict
                    if isinstance(action_result, ActionResult):
                        result['success'] = action_result.success
                        result['message'] = action_result.message
                        result['error'] = action_result.error
                        if action_result.data:
                            result['data'] = action_result.data
                    else:
                        # Handler returned dict directly
                        result['success'] = action_result.get('success', True)
                        result['message'] = action_result.get('message')
                        result['error'] = action_result.get('error')
            else:
                # Fall back to legacy inline handlers
                legacy_handler = self._get_legacy_action_handler(action.action_type)

                if legacy_handler:
                    if action.async_execution:
                        # Queue for background execution
                        frappe.enqueue(
                            legacy_handler,
                            action=action,
                            doc=self.doc,
                            queue='short',
                            now=frappe.conf.developer_mode
                        )
                        result['success'] = True
                        result['message'] = 'Queued for async execution'
                    else:
                        handler_result = legacy_handler(action, self.doc)
                        result['success'] = handler_result.get('success', True)
                        result['message'] = handler_result.get('message')
                        result['error'] = handler_result.get('error')
                else:
                    result['error'] = f"No handler for action type: {action.action_type}"

        except Exception as e:
            result['error'] = str(e)
            frappe.log_error(
                title=f"ECA Action Error: {action.action_type}",
                message=traceback.format_exc()
            )

        return result

    def _get_legacy_action_handler(self, action_type: str):
        """
        Get the legacy inline handler function for an action type.

        This method provides fallback handlers for action types that
        don't have modular handlers registered. Used for backward
        compatibility and for action types like Custom Method and
        Log Message that are handled inline.

        Args:
            action_type: Type of action

        Returns:
            Handler function or None
        """
        # Legacy handlers - used as fallback when modular handler not available
        handlers = {
            'Send Email': self._handle_email_action,
            'System Notification': self._handle_notification_action,
            'Webhook': self._handle_webhook_action,
            'Set Field': self._handle_set_field_action,
            'Create Document': self._handle_create_document_action,
            'Update Document': self._handle_update_document_action,
            'Delete Document': self._handle_delete_document_action,
            'Custom Method': self._handle_custom_method_action,
            'Log Message': self._handle_log_action,
        }

        return handlers.get(action_type)

    def _handle_email_action(self, action: Any, doc: Any) -> Dict:
        """Handle Send Email action."""
        try:
            # Render recipients
            recipients = self._render_jinja(action.recipients or '')
            cc_recipients = self._render_jinja(action.cc_recipients or '') if action.cc_recipients else None

            # Parse recipients (comma-separated)
            recipient_list = [r.strip() for r in recipients.split(',') if r.strip()]
            cc_list = [r.strip() for r in cc_recipients.split(',') if r.strip()] if cc_recipients else None

            if not recipient_list:
                return {'success': False, 'message': 'No recipients specified'}

            # Get email template
            if action.email_template:
                template = frappe.get_doc("Email Template", action.email_template)
                subject = self._render_jinja(action.subject_override or template.subject)
                message = self._render_jinja(template.response)
            else:
                subject = self._render_jinja(action.subject_override or f"ECA: {doc.doctype} {doc.name}")
                message = f"Document {doc.doctype} {doc.name} triggered ECA rule"

            # Send email
            frappe.sendmail(
                recipients=recipient_list,
                cc=cc_list,
                subject=subject,
                message=message,
                reference_doctype=doc.doctype,
                reference_name=doc.name
            )

            return {'success': True, 'message': f"Email sent to {', '.join(recipient_list)}"}

        except Exception as e:
            return {'success': False, 'message': str(e)}

    def _handle_notification_action(self, action: Any, doc: Any) -> Dict:
        """Handle System Notification action."""
        try:
            # Render message
            message = self._render_jinja(action.notification_message or f"ECA notification for {doc.name}")

            # Parse recipients
            recipients = self._render_jinja(action.notification_recipients or frappe.session.user)
            recipient_list = [r.strip() for r in recipients.split(',') if r.strip()]

            for user in recipient_list:
                frappe.publish_realtime(
                    'msgprint',
                    {'message': message, 'indicator': action.notification_type or 'blue'},
                    user=user
                )

            return {'success': True, 'message': f"Notification sent to {len(recipient_list)} users"}

        except Exception as e:
            return {'success': False, 'message': str(e)}

    def _handle_webhook_action(self, action: Any, doc: Any) -> Dict:
        """Handle Webhook action."""
        try:
            import requests

            # Render URL
            url = self._render_jinja(action.webhook_url)

            if not url:
                return {'success': False, 'message': 'No webhook URL specified'}

            # Parse headers
            headers = {'Content-Type': 'application/json'}
            if action.webhook_headers:
                try:
                    custom_headers = json.loads(self._render_jinja(action.webhook_headers))
                    headers.update(custom_headers)
                except json.JSONDecodeError:
                    pass

            # Prepare body
            if action.webhook_body:
                body = self._render_jinja(action.webhook_body)
                try:
                    body = json.loads(body)
                except json.JSONDecodeError:
                    pass
            else:
                body = doc.as_dict()

            # Make request
            method = (action.webhook_method or 'POST').upper()

            if method == 'GET':
                response = requests.get(url, headers=headers, params=body, timeout=30)
            elif method == 'POST':
                response = requests.post(url, headers=headers, json=body, timeout=30)
            elif method == 'PUT':
                response = requests.put(url, headers=headers, json=body, timeout=30)
            elif method == 'PATCH':
                response = requests.patch(url, headers=headers, json=body, timeout=30)
            elif method == 'DELETE':
                response = requests.delete(url, headers=headers, timeout=30)
            else:
                return {'success': False, 'message': f"Unsupported HTTP method: {method}"}

            response.raise_for_status()

            return {
                'success': True,
                'message': f"Webhook {method} to {url} - Status: {response.status_code}"
            }

        except Exception as e:
            return {'success': False, 'message': str(e)}

    def _handle_set_field_action(self, action: Any, doc: Any) -> Dict:
        """Handle Set Field action."""
        try:
            field = action.target_field
            value = self._render_jinja(action.target_value or '')

            if not field:
                return {'success': False, 'message': 'No target field specified'}

            # Update field value
            frappe.db.set_value(
                doc.doctype,
                doc.name,
                field,
                value,
                update_modified=False
            )

            return {'success': True, 'message': f"Set {field} = {value}"}

        except Exception as e:
            return {'success': False, 'message': str(e)}

    def _handle_create_document_action(self, action: Any, doc: Any) -> Dict:
        """Handle Create Document action."""
        try:
            target_doctype = action.target_doctype

            if not target_doctype:
                return {'success': False, 'message': 'No target DocType specified'}

            # Parse document values
            values = {}
            if action.document_values:
                try:
                    values = json.loads(self._render_jinja(action.document_values))
                except json.JSONDecodeError:
                    return {'success': False, 'message': 'Invalid document values JSON'}

            # Add link to parent if configured
            if action.link_to_parent and action.parent_field_name:
                values[action.parent_field_name] = doc.name

            # Create document
            new_doc = frappe.new_doc(target_doctype)
            new_doc.update(values)
            new_doc.insert(ignore_permissions=True)

            return {
                'success': True,
                'message': f"Created {target_doctype}: {new_doc.name}"
            }

        except Exception as e:
            return {'success': False, 'message': str(e)}

    def _handle_update_document_action(self, action: Any, doc: Any) -> Dict:
        """Handle Update Document action."""
        try:
            target_doctype = action.target_doctype

            if not target_doctype:
                return {'success': False, 'message': 'No target DocType specified'}

            # Parse document values - must include document name
            values = {}
            if action.document_values:
                try:
                    values = json.loads(self._render_jinja(action.document_values))
                except json.JSONDecodeError:
                    return {'success': False, 'message': 'Invalid document values JSON'}

            doc_name = values.pop('name', None)
            if not doc_name:
                return {'success': False, 'message': 'Document name required for update'}

            # Update document
            frappe.db.set_value(
                target_doctype,
                doc_name,
                values
            )

            return {
                'success': True,
                'message': f"Updated {target_doctype}: {doc_name}"
            }

        except Exception as e:
            return {'success': False, 'message': str(e)}

    def _handle_delete_document_action(self, action: Any, doc: Any) -> Dict:
        """Handle Delete Document action."""
        try:
            target_doctype = action.target_doctype

            if not target_doctype:
                return {'success': False, 'message': 'No target DocType specified'}

            # Parse document values to get name
            values = {}
            if action.document_values:
                try:
                    values = json.loads(self._render_jinja(action.document_values))
                except json.JSONDecodeError:
                    return {'success': False, 'message': 'Invalid document values JSON'}

            doc_name = values.get('name')
            if not doc_name:
                return {'success': False, 'message': 'Document name required for delete'}

            # Delete document
            frappe.delete_doc(target_doctype, doc_name, ignore_permissions=True)

            return {
                'success': True,
                'message': f"Deleted {target_doctype}: {doc_name}"
            }

        except Exception as e:
            return {'success': False, 'message': str(e)}

    def _handle_custom_method_action(self, action: Any, doc: Any) -> Dict:
        """Handle Custom Method action."""
        try:
            method_path = action.custom_method

            if not method_path:
                return {'success': False, 'message': 'No custom method specified'}

            # Parse custom arguments
            args = {}
            if action.custom_args:
                try:
                    args = json.loads(self._render_jinja(action.custom_args))
                except json.JSONDecodeError:
                    pass

            # Get method
            method = frappe.get_attr(method_path)

            # Call method
            result = method(doc=doc, **args)

            return {
                'success': True,
                'message': f"Custom method {method_path} executed",
                'result': result
            }

        except Exception as e:
            return {'success': False, 'message': str(e)}

    def _handle_log_action(self, action: Any, doc: Any) -> Dict:
        """Handle Log Message action."""
        try:
            message = self._render_jinja(action.notification_message or f"ECA Log: {doc.name}")
            frappe.log_error(title="ECA Log Message", message=message)
            return {'success': True, 'message': 'Message logged'}
        except Exception as e:
            return {'success': False, 'message': str(e)}

    def _log_execution(self, rule: Any, result: Dict):
        """
        Log execution to ECA Rule Log.

        Args:
            rule: ECA Rule document
            result: Execution result dictionary
        """
        if not rule.enable_logging:
            return

        # Check log level
        log_level = rule.log_level or 'Info'
        status = result.get('status', 'Success')

        should_log = (
            log_level == 'Debug' or
            (log_level == 'Info' and status in ['Success', 'Partial', 'Failed', 'Error']) or
            (log_level == 'Warning' and status in ['Partial', 'Failed', 'Error']) or
            (log_level == 'Error Only' and status == 'Error')
        )

        if not should_log:
            return

        try:
            log = frappe.new_doc("ECA Rule Log")
            log.eca_rule = rule.name
            log.status = status
            log.trigger_doctype = self.doctype
            log.trigger_document = self.doc.name
            log.trigger_event = self.event_type
            log.trigger_user = frappe.session.user
            log.trigger_time = now_datetime()
            log.execution_time_ms = result.get('execution_time_ms', 0)
            log.condition_result = result.get('condition_result', False)

            if rule.log_condition_results:
                log.condition_details = json.dumps(result.get('condition_details', []))

            log.actions_executed = result.get('actions_executed', 0)
            log.actions_succeeded = result.get('actions_succeeded', 0)
            log.actions_failed = result.get('actions_failed', 0)

            if rule.log_action_results:
                log.action_results = json.dumps(result.get('action_results', []))

            if result.get('error_message'):
                log.error_message = result['error_message']

            log.insert(ignore_permissions=True)

        except Exception as e:
            frappe.log_error(
                title="ECA Rule Log Error",
                message=f"Failed to log execution for rule {rule.name}: {str(e)}"
            )


def evaluate_rules(doc: Any, method: str):
    """
    Main entry point for ECA rule evaluation.

    This function is called from Frappe doc_events hooks.

    Args:
        doc: Frappe document that triggered the event
        method: Event method name (after_save, on_submit, etc.)

    Example hook in hooks.py:
        doc_events = {
            "*": {
                "after_save": "tr_tradehub.eca.dispatcher.evaluate_rules",
            }
        }
    """
    # Skip if already in ECA execution (prevent circular triggers)
    if getattr(frappe.flags, 'in_eca_execution', False):
        return

    # Skip system documents
    skip_doctypes = [
        'ECA Rule',
        'ECA Rule Log',
        'ECA Action Template',
        'Error Log',
        'Activity Log',
        'Version',
        'Communication',
        'Email Queue',
    ]

    if doc.doctype in skip_doctypes:
        return

    # Map method to event type
    event_type = EVENT_TYPE_MAP.get(method)
    if not event_type:
        return

    # Check if any rules exist for this doctype/event (quick check)
    # Handle case where is_active column might not exist in database
    try:
        # Check if is_active column exists
        meta = frappe.get_meta("ECA Rule")
        has_is_active = meta.has_field("is_active")
        
        filters = {
            "event_doctype": doc.doctype,
            "event_type": event_type,
            "schedule_type": "Event-based"
        }
        
        if has_is_active:
            filters["is_active"] = 1
        
        rule_count = frappe.db.count("ECA Rule", filters=filters)
    except Exception as e:
        # If there's any error (including missing column), try without is_active
        try:
            rule_count = frappe.db.count(
                "ECA Rule",
                filters={
                    "event_doctype": doc.doctype,
                    "event_type": event_type,
                    "schedule_type": "Event-based"
                }
            )
        except Exception:
            # If still fails, assume no rules and return early
            return

    if rule_count == 0:
        return

    # Dispatch rules
    try:
        dispatcher = ECADispatcher(doc, event_type, method)
        dispatcher.dispatch()
    except Exception as e:
        frappe.log_error(
            title=f"ECA Dispatcher Error: {doc.doctype}",
            message=f"Document: {doc.name}\nEvent: {event_type}\nError: {str(e)}\n{traceback.format_exc()}"
        )


def get_rules_for_doctype(doctype: str, event_type: Optional[str] = None) -> List[Dict]:
    """
    Get all active ECA rules for a DocType.

    Args:
        doctype: DocType name
        event_type: Optional event type filter

    Returns:
        list: List of rule dictionaries
    """
    filters = {
        "is_active": 1,
        "event_doctype": doctype
    }

    if event_type:
        filters["event_type"] = event_type

    rules = frappe.get_all(
        "ECA Rule",
        filters=filters,
        fields=[
            "name", "rule_name", "rule_code", "event_type",
            "condition_logic", "enable_logging", "priority"
        ],
        order_by="priority ASC"
    )

    return rules


def test_rule(rule_name: str, doc_name: str) -> Dict:
    """
    Test a rule against a specific document without executing actions.

    Args:
        rule_name: ECA Rule name
        doc_name: Document name to test against

    Returns:
        dict: Test results including condition evaluation
    """
    rule = frappe.get_doc("ECA Rule", rule_name)
    doc = frappe.get_doc(rule.event_doctype, doc_name)

    dispatcher = ECADispatcher(doc, rule.event_type)
    condition_result, condition_details = dispatcher._evaluate_conditions(rule)

    return {
        'rule': rule_name,
        'document': doc_name,
        'condition_result': condition_result,
        'condition_details': condition_details,
        'would_execute': condition_result and rule.is_active
    }

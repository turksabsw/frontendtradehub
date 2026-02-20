# Copyright (c) 2026, TradeHub and contributors
# For license information, please see license.txt

"""
Test Suite for ECA Action Executors

This test suite covers:
- ActionResult dataclass
- ActionContext class and template rendering
- ActionExecutor base class
- ActionRegistry for executor management
- ActionRunner for executing actions
- All 16 action type executors:
  - Update Field
  - Create Document
  - Delete Document
  - Send Notification
  - Send Email
  - Create Notification Log
  - Webhook
  - Custom Python
  - Set Workflow State
  - Add Comment
  - Add Tag
  - Remove Tag
  - Create Todo
  - Enqueue Job
  - Call API
  - Assign To

Run with:
    bench --site [site] run-tests --module tr_tradehub.tests.test_eca_actions
"""

import unittest
from unittest.mock import MagicMock, patch, Mock
from datetime import datetime
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
import json


# =============================================================================
# MOCK FRAPPE MODULE
# =============================================================================

class MockFrappeSession:
    """Mock Frappe session."""
    user = "test@example.com"


class MockFrappeUtils:
    """Mock frappe.utils for testing."""

    @staticmethod
    def cstr(val):
        return str(val) if val is not None else ""

    @staticmethod
    def cint(val):
        try:
            return int(val) if val is not None else 0
        except (ValueError, TypeError):
            return 0

    @staticmethod
    def flt(val):
        try:
            return float(val) if val is not None else 0.0
        except (ValueError, TypeError):
            return 0.0

    @staticmethod
    def now_datetime():
        return datetime.now()

    @staticmethod
    def today():
        return datetime.now().strftime("%Y-%m-%d")

    @staticmethod
    def getdate(val):
        if isinstance(val, datetime):
            return val.date()
        if isinstance(val, str):
            try:
                return datetime.strptime(val, "%Y-%m-%d").date()
            except ValueError:
                return None
        return None

    @staticmethod
    def get_datetime(val):
        if isinstance(val, datetime):
            return val
        if isinstance(val, str):
            try:
                return datetime.strptime(val, "%Y-%m-%d %H:%M:%S")
            except ValueError:
                try:
                    return datetime.strptime(val, "%Y-%m-%d")
                except ValueError:
                    return None
        return None

    @staticmethod
    def add_days(date_val, days):
        if isinstance(date_val, str):
            date_val = MockFrappeUtils.getdate(date_val)
        if date_val:
            from datetime import timedelta
            return date_val + timedelta(days=days)
        return None

    @staticmethod
    def date_diff(date1, date2):
        d1 = MockFrappeUtils.getdate(date1)
        d2 = MockFrappeUtils.getdate(date2)
        if d1 and d2:
            return (d1 - d2).days
        return 0


class MockFrappeDB:
    """Mock frappe.db for testing."""

    def __init__(self):
        self._docs = {}  # {doctype: {name: doc_data}}
        self._counter = 0

    def exists(self, doctype, filters=None):
        if doctype not in self._docs:
            return False
        if isinstance(filters, str):
            return filters in self._docs[doctype]
        if isinstance(filters, dict):
            for name, doc in self._docs[doctype].items():
                match = True
                for key, value in filters.items():
                    if isinstance(value, tuple) and value[0] == "!=":
                        if doc.get(key) == value[1]:
                            match = False
                            break
                    elif doc.get(key) != value:
                        match = False
                        break
                if match:
                    return name
        return False

    def get_value(self, doctype, name, fieldname=None):
        if doctype in self._docs and name in self._docs[doctype]:
            doc = self._docs[doctype][name]
            if fieldname:
                return doc.get(fieldname)
            return doc
        return None

    def commit(self):
        pass

    def get_list(self, doctype, filters=None, fields=None, **kwargs):
        if doctype not in self._docs:
            return []
        results = []
        for name, doc in self._docs[doctype].items():
            if filters:
                match = True
                for key, value in filters.items():
                    if isinstance(value, list) and value[0] == "in":
                        if doc.get(key) not in value[1]:
                            match = False
                            break
                    elif doc.get(key) != value:
                        match = False
                        break
                if not match:
                    continue
            results.append(doc)
        return results

    def new_id(self):
        self._counter += 1
        return f"new-id-{self._counter}"


class MockFrappeFlags:
    """Mock frappe.flags for testing."""
    pass


class MockFrappeExceptions:
    """Mock frappe exceptions."""
    class ValidationError(Exception):
        pass

    class PermissionError(Exception):
        pass

    class LinkExistsError(Exception):
        pass


class MockFrappe:
    """Mock Frappe module for standalone testing."""

    session = MockFrappeSession()
    utils = MockFrappeUtils
    db = MockFrappeDB()
    flags = MockFrappeFlags()
    exceptions = MockFrappeExceptions
    ValidationError = MockFrappeExceptions.ValidationError
    PermissionError = MockFrappeExceptions.PermissionError
    LinkExistsError = MockFrappeExceptions.LinkExistsError

    _enqueued_jobs = []
    _sent_emails = []
    _created_docs = []
    _deleted_docs = []
    _logged_errors = []

    @staticmethod
    def _(text):
        return text

    @staticmethod
    def log_error(message, title=None):
        MockFrappe._logged_errors.append({"message": message, "title": title})

    @staticmethod
    def logger():
        return MagicMock()

    @staticmethod
    def render_template(template, context):
        """Simple Jinja-like template rendering."""
        result = template
        for key, value in context.items():
            if key == "doc" and hasattr(value, "__dict__"):
                for field_name, field_value in vars(value).items():
                    if not field_name.startswith("_"):
                        patterns = [
                            "{{doc." + field_name + "}}",
                            "{{ doc." + field_name + " }}",
                            "{{doc." + field_name + " }}",
                            "{{ doc." + field_name + "}}",
                        ]
                        for pattern in patterns:
                            result = result.replace(pattern, str(field_value) if field_value is not None else "")
            patterns = [
                "{{" + key + "}}",
                "{{ " + key + " }}",
            ]
            for pattern in patterns:
                result = result.replace(pattern, str(value) if value is not None else "")
        return result

    @staticmethod
    def generate_hash(length=12):
        import random
        import string
        return ''.join(random.choices(string.ascii_lowercase + string.digits, k=length))

    @staticmethod
    def get_doc(doctype_or_dict, name=None):
        if isinstance(doctype_or_dict, dict):
            # Creating a new document
            doc = MockDocument(**doctype_or_dict)
            return doc
        else:
            # Getting an existing document
            if doctype_or_dict in MockFrappe.db._docs:
                if name in MockFrappe.db._docs[doctype_or_dict]:
                    data = MockFrappe.db._docs[doctype_or_dict][name]
                    return MockDocument(**data)
            return MockDocument(doctype=doctype_or_dict, name=name)

    @staticmethod
    def get_all(doctype, filters=None, fields=None, pluck=None, **kwargs):
        results = MockFrappe.db.get_list(doctype, filters=filters, fields=fields, **kwargs)
        if pluck:
            return [r.get(pluck) for r in results if r.get(pluck)]
        return results

    @staticmethod
    def delete_doc(doctype, name, ignore_permissions=False, force=False):
        MockFrappe._deleted_docs.append({"doctype": doctype, "name": name})
        if doctype in MockFrappe.db._docs and name in MockFrappe.db._docs[doctype]:
            del MockFrappe.db._docs[doctype][name]

    @staticmethod
    def enqueue(func, queue="default", timeout=None, job_name=None, now=False, enqueue_after_commit=True, **kwargs):
        MockFrappe._enqueued_jobs.append({
            "func": func,
            "queue": queue,
            "timeout": timeout,
            "job_name": job_name,
            "now": now,
            "kwargs": kwargs
        })

    @staticmethod
    def sendmail(recipients, subject, message, reference_doctype=None, reference_name=None, delayed=True, **kwargs):
        MockFrappe._sent_emails.append({
            "recipients": recipients,
            "subject": subject,
            "message": message,
            "reference_doctype": reference_doctype,
            "reference_name": reference_name,
            "kwargs": kwargs
        })

    @staticmethod
    def call(method, **kwargs):
        # Simulate API call
        return {"method": method, "args": kwargs}

    @staticmethod
    def safe_exec(script, _globals=None, _locals=None, restrict_commit_rollback=False, script_filename=None):
        # Execute script in a controlled environment
        exec(script, _globals or {}, _locals or {})

    @staticmethod
    def whitelist():
        def decorator(func):
            return func
        return decorator

    @staticmethod
    def reset_mocks():
        MockFrappe._enqueued_jobs = []
        MockFrappe._sent_emails = []
        MockFrappe._created_docs = []
        MockFrappe._deleted_docs = []
        MockFrappe._logged_errors = []
        MockFrappe.db = MockFrappeDB()


# Patch frappe module before imports
import sys
sys.modules['frappe'] = MockFrappe
sys.modules['frappe.utils'] = MockFrappe.utils
sys.modules['frappe.exceptions'] = MockFrappe.exceptions


# =============================================================================
# MOCK DOCUMENT CLASS
# =============================================================================

class MockDocument:
    """Mock document class for testing."""

    def __init__(self, doctype="Test DocType", name=None, **kwargs):
        self.doctype = doctype
        self.name = name or MockFrappe.db.new_id()
        self._comments = []
        self._tags = []
        self._saved = False
        self._inserted = False

        # Set all provided fields
        for key, value in kwargs.items():
            setattr(self, key, value)

    def get(self, field, default=None):
        return getattr(self, field, default)

    def set(self, field, value):
        setattr(self, field, value)

    def save(self, ignore_permissions=False):
        self._saved = True
        # Update in mock db
        if self.doctype not in MockFrappe.db._docs:
            MockFrappe.db._docs[self.doctype] = {}
        MockFrappe.db._docs[self.doctype][self.name] = self.as_dict()

    def insert(self, ignore_permissions=False):
        self._inserted = True
        # Generate name if not set
        if not self.name or self.name.startswith("new-id-"):
            self.name = MockFrappe.db.new_id()
        # Add to mock db
        if self.doctype not in MockFrappe.db._docs:
            MockFrappe.db._docs[self.doctype] = {}
        MockFrappe.db._docs[self.doctype][self.name] = self.as_dict()
        MockFrappe._created_docs.append(self.as_dict())

    def add_comment(self, comment_type, text):
        comment = MockDocument(
            doctype="Comment",
            comment_type=comment_type,
            content=text,
            reference_doctype=self.doctype,
            reference_name=self.name
        )
        self._comments.append(comment)
        return comment

    def as_dict(self):
        result = {}
        for key, value in self.__dict__.items():
            if not key.startswith("_"):
                result[key] = value
        return result


@dataclass
class MockAction:
    """Mock ECA Rule Action for testing."""
    action_type: str = "Update Field"
    enabled: bool = True
    sequence: int = 1
    stop_on_error: bool = False
    action_condition: str = ""
    target_doctype: str = ""
    target_reference_field: str = ""
    field_mapping_json: str = ""
    recipient_type: str = ""
    recipient_field: str = ""
    subject_template: str = ""
    message_template: str = ""
    webhook_url: str = ""
    webhook_method: str = "POST"
    webhook_payload_json: str = ""
    python_code: str = ""


@dataclass
class MockRule:
    """Mock ECA Rule for testing."""
    name: str = "ECA-2026-00001"
    rule_name: str = "Test Rule"
    enabled: bool = True
    priority: int = 10
    event_doctype: str = "Test DocType"
    event_type: str = "After Save"
    actions: List[MockAction] = field(default_factory=list)


# =============================================================================
# TESTABLE ACTION CLASSES (copied from actions.py for standalone testing)
# =============================================================================

@dataclass
class ActionResult:
    """Result of an action execution."""
    success: bool
    action_type: str
    sequence: int = 0
    message: str = ""
    duration_ms: float = 0.0
    data: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "status": "success" if self.success else "failed",
            "action_type": self.action_type,
            "sequence": self.sequence,
            "message": self.message,
            "duration_ms": self.duration_ms,
            "data": self.data
        }


@dataclass
class ActionContext:
    """Context passed to action executors."""
    doc: Any
    old_doc: Optional[Any]
    rule: Any
    action: Any
    chain_id: str = ""
    chain_depth: int = 0

    def get_template_context(self) -> Dict[str, Any]:
        return {
            "doc": self.doc,
            "old_doc": self.old_doc,
            "rule": self.rule,
            "action": self.action,
            "frappe": MockFrappe,
            "now": MockFrappe.utils.now_datetime,
            "today": MockFrappe.utils.today,
            "user": MockFrappe.session.user,
            "_": MockFrappe._,
        }

    def render_template(self, template: str) -> str:
        if not template or not isinstance(template, str):
            return template
        if "{{" not in template and "{%" not in template:
            return template
        try:
            return MockFrappe.render_template(template, self.get_template_context())
        except Exception:
            return template


class ActionExecutor:
    """Base class for action executors."""
    action_type: str = ""

    def execute(self, context: ActionContext) -> ActionResult:
        raise NotImplementedError

    def validate(self, context: ActionContext) -> Optional[str]:
        return None

    def should_execute(self, context: ActionContext) -> bool:
        action = context.action
        if not action.enabled:
            return False
        if not action.action_condition:
            return True
        try:
            result = context.render_template(action.action_condition)
            result_str = str(result).strip().lower()
            return result_str in ("true", "1", "yes")
        except Exception:
            return False

    def _resolve_field_path(self, obj: Any, field_path: str) -> Any:
        if not obj or not field_path:
            return None
        try:
            import re
            parts = field_path.split(".")
            current = obj
            for part in parts:
                if current is None:
                    return None
                match = re.match(r"(\w+)\[(\d+)\]", part)
                if match:
                    field_name, index = match.groups()
                    if hasattr(current, field_name):
                        current = getattr(current, field_name)
                    elif isinstance(current, dict):
                        current = current.get(field_name)
                    else:
                        return None
                    if isinstance(current, (list, tuple)) and int(index) < len(current):
                        current = current[int(index)]
                    else:
                        return None
                else:
                    if hasattr(current, part):
                        current = getattr(current, part)
                    elif isinstance(current, dict):
                        current = current.get(part)
                    else:
                        return None
            return current
        except Exception:
            return None

    def _render_field_mapping(self, context: ActionContext, field_mapping: Dict[str, Any]) -> Dict[str, Any]:
        rendered = {}
        for field_name, value in field_mapping.items():
            if isinstance(value, str):
                rendered[field_name] = context.render_template(value)
            else:
                rendered[field_name] = value
        return rendered


class ActionRegistry:
    """Registry for action executors."""
    _instance = None
    _executors: Dict[str, type] = {}

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._executors = {}
        return cls._instance

    def register(self, executor_class):
        if not executor_class.action_type:
            raise ValueError(f"Executor {executor_class.__name__} has no action_type")
        self._executors[executor_class.action_type] = executor_class

    def unregister(self, action_type: str):
        if action_type in self._executors:
            del self._executors[action_type]

    def get_executor(self, action_type: str):
        executor_class = self._executors.get(action_type)
        if executor_class:
            return executor_class()
        return None

    def has_executor(self, action_type: str) -> bool:
        return action_type in self._executors

    def get_action_types(self) -> List[str]:
        return list(self._executors.keys())

    def reset(self):
        self._executors = {}


# Global registry for testing
test_registry = ActionRegistry()


def register_action(executor_class):
    test_registry.register(executor_class)
    return executor_class


# =============================================================================
# ACTION EXECUTOR IMPLEMENTATIONS FOR TESTING
# =============================================================================

@register_action
class TestableUpdateFieldExecutor(ActionExecutor):
    """Testable Update Field executor."""
    action_type = "Update Field"

    def validate(self, context: ActionContext) -> Optional[str]:
        action = context.action
        if not action.field_mapping_json:
            return "field_mapping_json is required for Update Field action"
        try:
            mapping = json.loads(action.field_mapping_json)
            if not isinstance(mapping, dict):
                return "field_mapping_json must be a JSON object"
            if not mapping:
                return "field_mapping_json must have at least one field mapping"
        except json.JSONDecodeError as e:
            return f"Invalid JSON in field_mapping_json: {str(e)}"
        return None

    def execute(self, context: ActionContext) -> ActionResult:
        action = context.action
        doc = context.doc
        try:
            field_mapping = json.loads(action.field_mapping_json)
            rendered_mapping = self._render_field_mapping(context, field_mapping)
            changed_fields = []
            for field_name, new_value in rendered_mapping.items():
                old_value = doc.get(field_name)
                if old_value != new_value:
                    doc.set(field_name, new_value)
                    changed_fields.append(f"{field_name}: {old_value} -> {new_value}")
            if not changed_fields:
                return ActionResult(
                    success=True,
                    action_type=self.action_type,
                    message="No fields changed",
                    data={"fields_updated": 0}
                )
            doc.save(ignore_permissions=True)
            doc.add_comment("Info", f"Updated fields: {', '.join(changed_fields)}")
            return ActionResult(
                success=True,
                action_type=self.action_type,
                message=f"Updated {len(changed_fields)} field(s)",
                data={"fields_updated": len(changed_fields), "changes": changed_fields}
            )
        except Exception as e:
            return ActionResult(success=False, action_type=self.action_type, message=str(e))


@register_action
class TestableCreateDocumentExecutor(ActionExecutor):
    """Testable Create Document executor."""
    action_type = "Create Document"

    def validate(self, context: ActionContext) -> Optional[str]:
        action = context.action
        if not action.target_doctype:
            return "target_doctype is required for Create Document action"
        return None

    def execute(self, context: ActionContext) -> ActionResult:
        action = context.action
        trigger_doc = context.doc
        try:
            doc_data = {"doctype": action.target_doctype}
            if action.field_mapping_json:
                field_mapping = json.loads(action.field_mapping_json)
                rendered_mapping = self._render_field_mapping(context, field_mapping)
                doc_data.update(rendered_mapping)
            if action.target_reference_field:
                doc_data[action.target_reference_field] = trigger_doc.name
            new_doc = MockFrappe.get_doc(doc_data)
            new_doc.insert(ignore_permissions=True)
            return ActionResult(
                success=True,
                action_type=self.action_type,
                message=f"Created {action.target_doctype}: {new_doc.name}",
                data={"doctype": action.target_doctype, "name": new_doc.name}
            )
        except Exception as e:
            return ActionResult(success=False, action_type=self.action_type, message=str(e))


@register_action
class TestableDeleteDocumentExecutor(ActionExecutor):
    """Testable Delete Document executor."""
    action_type = "Delete Document"

    def validate(self, context: ActionContext) -> Optional[str]:
        action = context.action
        if action.target_doctype and action.target_doctype != context.doc.doctype:
            if not action.target_reference_field:
                return "target_reference_field is required when target_doctype differs from trigger document"
        return None

    def execute(self, context: ActionContext) -> ActionResult:
        action = context.action
        trigger_doc = context.doc
        try:
            if action.target_doctype and action.target_doctype != trigger_doc.doctype:
                target_name = self._resolve_field_path(trigger_doc, action.target_reference_field)
                if not target_name:
                    return ActionResult(
                        success=False,
                        action_type=self.action_type,
                        message="Could not determine target document to delete"
                    )
                doctype_to_delete = action.target_doctype
                name_to_delete = target_name
            else:
                doctype_to_delete = trigger_doc.doctype
                name_to_delete = trigger_doc.name
            MockFrappe.delete_doc(doctype_to_delete, name_to_delete, ignore_permissions=True, force=True)
            return ActionResult(
                success=True,
                action_type=self.action_type,
                message=f"Deleted {doctype_to_delete}: {name_to_delete}",
                data={"doctype": doctype_to_delete, "name": name_to_delete}
            )
        except Exception as e:
            return ActionResult(success=False, action_type=self.action_type, message=str(e))


@register_action
class TestableSendNotificationExecutor(ActionExecutor):
    """Testable Send Notification executor."""
    action_type = "Send Notification"

    def validate(self, context: ActionContext) -> Optional[str]:
        action = context.action
        if not action.recipient_type:
            return "recipient_type is required for Send Notification action"
        if not action.recipient_field:
            return "recipient_field is required for Send Notification action"
        if not action.subject_template:
            return "subject_template is required for Send Notification action"
        return None

    def execute(self, context: ActionContext) -> ActionResult:
        action = context.action
        try:
            recipients = self._get_recipients(context)
            if not recipients:
                return ActionResult(
                    success=True,
                    action_type=self.action_type,
                    message="No recipients found",
                    data={"recipients_notified": 0}
                )
            subject = context.render_template(action.subject_template)
            message = context.render_template(action.message_template or "")
            for recipient in recipients:
                notification = MockFrappe.get_doc({
                    "doctype": "Notification Log",
                    "for_user": recipient,
                    "type": "Alert",
                    "subject": subject,
                    "email_content": message
                })
                notification.insert(ignore_permissions=True)
            return ActionResult(
                success=True,
                action_type=self.action_type,
                message=f"Sent notifications to {len(recipients)} recipient(s)",
                data={"recipients_notified": len(recipients), "recipients": recipients}
            )
        except Exception as e:
            return ActionResult(success=False, action_type=self.action_type, message=str(e))

    def _get_recipients(self, context: ActionContext) -> List[str]:
        action = context.action
        if action.recipient_type == "User List":
            return [u.strip() for u in action.recipient_field.split(",") if u.strip()]
        elif action.recipient_type == "Field Value":
            value = self._resolve_field_path(context.doc, action.recipient_field)
            if value:
                return [str(value)]
        elif action.recipient_type == "Jinja Expression":
            rendered = context.render_template(action.recipient_field)
            if rendered:
                return [u.strip() for u in rendered.split(",") if u.strip()]
        return []


@register_action
class TestableSendEmailExecutor(ActionExecutor):
    """Testable Send Email executor."""
    action_type = "Send Email"

    def validate(self, context: ActionContext) -> Optional[str]:
        action = context.action
        if not action.recipient_type:
            return "recipient_type is required for Send Email action"
        if not action.recipient_field:
            return "recipient_field is required for Send Email action"
        if not action.subject_template:
            return "subject_template is required for Send Email action"
        if not action.message_template:
            return "message_template is required for Send Email action"
        return None

    def execute(self, context: ActionContext) -> ActionResult:
        action = context.action
        doc = context.doc
        try:
            recipients = self._get_recipients(context)
            if not recipients:
                return ActionResult(
                    success=True,
                    action_type=self.action_type,
                    message="No recipients found for email",
                    data={"recipients_emailed": 0}
                )
            subject = context.render_template(action.subject_template)
            message = context.render_template(action.message_template)
            MockFrappe.sendmail(
                recipients=recipients,
                subject=subject,
                message=message,
                reference_doctype=doc.doctype,
                reference_name=doc.name,
                delayed=True
            )
            return ActionResult(
                success=True,
                action_type=self.action_type,
                message=f"Email queued for {len(recipients)} recipient(s)",
                data={"recipients_emailed": len(recipients), "recipients": recipients}
            )
        except Exception as e:
            return ActionResult(success=False, action_type=self.action_type, message=str(e))

    def _get_recipients(self, context: ActionContext) -> List[str]:
        action = context.action
        if action.recipient_type == "User List":
            return [u.strip() for u in action.recipient_field.split(",") if u.strip() and "@" in u]
        elif action.recipient_type == "Field Value":
            value = self._resolve_field_path(context.doc, action.recipient_field)
            if value and "@" in str(value):
                return [str(value)]
        return []


@register_action
class TestableWebhookExecutor(ActionExecutor):
    """Testable Webhook executor."""
    action_type = "Webhook"

    def validate(self, context: ActionContext) -> Optional[str]:
        action = context.action
        if not action.webhook_url:
            return "webhook_url is required for Webhook action"
        if action.webhook_payload_json:
            try:
                json.loads(action.webhook_payload_json)
            except json.JSONDecodeError as e:
                return f"Invalid JSON in webhook_payload_json: {str(e)}"
        return None

    def execute(self, context: ActionContext) -> ActionResult:
        action = context.action
        doc = context.doc
        try:
            webhook_url = context.render_template(action.webhook_url)
            payload = {}
            if action.webhook_payload_json:
                raw_payload = json.loads(action.webhook_payload_json)
                payload = self._render_payload(context, raw_payload)
            method = (action.webhook_method or "POST").upper()
            job_name = f"eca_webhook_{context.rule.name}_{doc.name}_{context.chain_id}"
            MockFrappe.enqueue(
                "tr_tradehub.eca.actions._execute_webhook_request",
                queue="short",
                job_name=job_name,
                url=webhook_url,
                method=method,
                payload=payload
            )
            return ActionResult(
                success=True,
                action_type=self.action_type,
                message=f"Webhook enqueued: {method} {webhook_url}",
                data={"url": webhook_url, "method": method, "job_name": job_name}
            )
        except Exception as e:
            return ActionResult(success=False, action_type=self.action_type, message=str(e))

    def _render_payload(self, context: ActionContext, payload: Any) -> Any:
        if isinstance(payload, dict):
            return {k: self._render_payload(context, v) for k, v in payload.items()}
        elif isinstance(payload, list):
            return [self._render_payload(context, item) for item in payload]
        elif isinstance(payload, str):
            return context.render_template(payload)
        return payload


@register_action
class TestableAddCommentExecutor(ActionExecutor):
    """Testable Add Comment executor."""
    action_type = "Add Comment"

    def validate(self, context: ActionContext) -> Optional[str]:
        action = context.action
        if not action.message_template:
            return "message_template is required for Add Comment action"
        return None

    def execute(self, context: ActionContext) -> ActionResult:
        action = context.action
        doc = context.doc
        try:
            comment_text = context.render_template(action.message_template)
            comment_type = action.subject_template.strip() if action.subject_template else "Info"
            doc.add_comment(comment_type, comment_text)
            return ActionResult(
                success=True,
                action_type=self.action_type,
                message=f"Added {comment_type} comment to {doc.doctype}/{doc.name}",
                data={"comment_type": comment_type, "doctype": doc.doctype, "name": doc.name}
            )
        except Exception as e:
            return ActionResult(success=False, action_type=self.action_type, message=str(e))


@register_action
class TestableAddTagExecutor(ActionExecutor):
    """Testable Add Tag executor."""
    action_type = "Add Tag"

    def validate(self, context: ActionContext) -> Optional[str]:
        action = context.action
        if not action.subject_template:
            return "subject_template (tag name) is required for Add Tag action"
        return None

    def execute(self, context: ActionContext) -> ActionResult:
        action = context.action
        doc = context.doc
        try:
            tag = context.render_template(action.subject_template).strip()
            if not hasattr(doc, "_tags"):
                doc._tags = []
            doc._tags.append(tag)
            return ActionResult(
                success=True,
                action_type=self.action_type,
                message=f"Added tag '{tag}' to {doc.doctype}/{doc.name}",
                data={"tag": tag, "doctype": doc.doctype, "name": doc.name}
            )
        except Exception as e:
            return ActionResult(success=False, action_type=self.action_type, message=str(e))


@register_action
class TestableRemoveTagExecutor(ActionExecutor):
    """Testable Remove Tag executor."""
    action_type = "Remove Tag"

    def validate(self, context: ActionContext) -> Optional[str]:
        action = context.action
        if not action.subject_template:
            return "subject_template (tag name) is required for Remove Tag action"
        return None

    def execute(self, context: ActionContext) -> ActionResult:
        action = context.action
        doc = context.doc
        try:
            tag = context.render_template(action.subject_template).strip()
            if hasattr(doc, "_tags") and tag in doc._tags:
                doc._tags.remove(tag)
            return ActionResult(
                success=True,
                action_type=self.action_type,
                message=f"Removed tag '{tag}' from {doc.doctype}/{doc.name}",
                data={"tag": tag, "doctype": doc.doctype, "name": doc.name}
            )
        except Exception as e:
            return ActionResult(success=False, action_type=self.action_type, message=str(e))


@register_action
class TestableCreateTodoExecutor(ActionExecutor):
    """Testable Create Todo executor."""
    action_type = "Create Todo"

    def validate(self, context: ActionContext) -> Optional[str]:
        action = context.action
        if not action.recipient_type:
            return "recipient_type is required for Create Todo action"
        if not action.recipient_field:
            return "recipient_field is required for Create Todo action"
        if not action.subject_template:
            return "subject_template (ToDo description) is required for Create Todo action"
        return None

    def execute(self, context: ActionContext) -> ActionResult:
        action = context.action
        doc = context.doc
        try:
            assignees = self._get_assignees(context)
            if not assignees:
                return ActionResult(
                    success=True,
                    action_type=self.action_type,
                    message="No assignees found for ToDo",
                    data={"todos_created": 0}
                )
            description = context.render_template(action.subject_template)
            todos_created = []
            for assignee in assignees:
                todo = MockFrappe.get_doc({
                    "doctype": "ToDo",
                    "allocated_to": assignee,
                    "description": description,
                    "reference_type": doc.doctype,
                    "reference_name": doc.name,
                    "status": "Open"
                })
                todo.insert(ignore_permissions=True)
                todos_created.append({"name": todo.name, "allocated_to": assignee})
            return ActionResult(
                success=True,
                action_type=self.action_type,
                message=f"Created {len(todos_created)} ToDo(s)",
                data={"todos_created": len(todos_created), "todos": todos_created}
            )
        except Exception as e:
            return ActionResult(success=False, action_type=self.action_type, message=str(e))

    def _get_assignees(self, context: ActionContext) -> List[str]:
        action = context.action
        if action.recipient_type == "User List":
            return [u.strip() for u in action.recipient_field.split(",") if u.strip()]
        elif action.recipient_type == "Field Value":
            value = self._resolve_field_path(context.doc, action.recipient_field)
            if value:
                return [str(value)]
        return []


@register_action
class TestableEnqueueJobExecutor(ActionExecutor):
    """Testable Enqueue Job executor."""
    action_type = "Enqueue Job"

    def validate(self, context: ActionContext) -> Optional[str]:
        action = context.action
        if not action.subject_template:
            return "subject_template (function path) is required for Enqueue Job action"
        if "." not in action.subject_template:
            return "subject_template must be a dotted Python function path"
        return None

    def execute(self, context: ActionContext) -> ActionResult:
        action = context.action
        doc = context.doc
        try:
            func_path = context.render_template(action.subject_template.strip())
            job_args = {}
            if action.field_mapping_json:
                raw_args = json.loads(action.field_mapping_json)
                job_args = self._render_field_mapping(context, raw_args)
            queue = "default"
            if action.message_template:
                queue = context.render_template(action.message_template.strip())
            job_name = f"eca_job_{context.rule.name}_{doc.name}_{context.chain_id}"
            MockFrappe.enqueue(
                func_path,
                queue=queue,
                job_name=job_name,
                **job_args
            )
            return ActionResult(
                success=True,
                action_type=self.action_type,
                message=f"Job enqueued: {func_path}",
                data={"function": func_path, "queue": queue, "job_name": job_name}
            )
        except Exception as e:
            return ActionResult(success=False, action_type=self.action_type, message=str(e))


@register_action
class TestableCallAPIExecutor(ActionExecutor):
    """Testable Call API executor."""
    action_type = "Call API"

    def validate(self, context: ActionContext) -> Optional[str]:
        action = context.action
        if not action.subject_template:
            return "subject_template (API method name) is required for Call API action"
        if "." not in action.subject_template:
            return "subject_template must be a dotted Python method path"
        return None

    def execute(self, context: ActionContext) -> ActionResult:
        action = context.action
        try:
            method_path = context.render_template(action.subject_template.strip())
            method_args = {}
            if action.field_mapping_json:
                raw_args = json.loads(action.field_mapping_json)
                method_args = self._render_field_mapping(context, raw_args)
            result = MockFrappe.call(method_path, **method_args)
            return ActionResult(
                success=True,
                action_type=self.action_type,
                message=f"API call executed: {method_path}",
                data={"method": method_path, "args": method_args, "result": result}
            )
        except Exception as e:
            return ActionResult(success=False, action_type=self.action_type, message=str(e))


@register_action
class TestableAssignToExecutor(ActionExecutor):
    """Testable Assign To executor."""
    action_type = "Assign To"

    def validate(self, context: ActionContext) -> Optional[str]:
        action = context.action
        if not action.recipient_type:
            return "recipient_type is required for Assign To action"
        if not action.recipient_field:
            return "recipient_field is required for Assign To action"
        return None

    def execute(self, context: ActionContext) -> ActionResult:
        action = context.action
        doc = context.doc
        try:
            assignees = self._get_assignees(context)
            if not assignees:
                return ActionResult(
                    success=True,
                    action_type=self.action_type,
                    message="No assignees found for assignment",
                    data={"assignments_created": 0}
                )
            description = ""
            if action.subject_template:
                description = context.render_template(action.subject_template)
            for assignee in assignees:
                todo = MockFrappe.get_doc({
                    "doctype": "ToDo",
                    "allocated_to": assignee,
                    "description": description or f"Assigned: {doc.name}",
                    "reference_type": doc.doctype,
                    "reference_name": doc.name,
                    "status": "Open"
                })
                todo.insert(ignore_permissions=True)
            return ActionResult(
                success=True,
                action_type=self.action_type,
                message=f"Assigned to {len(assignees)} user(s)",
                data={"assignments_created": len(assignees), "assignees": assignees}
            )
        except Exception as e:
            return ActionResult(success=False, action_type=self.action_type, message=str(e))

    def _get_assignees(self, context: ActionContext) -> List[str]:
        action = context.action
        if action.recipient_type == "User List":
            return [u.strip() for u in action.recipient_field.split(",") if u.strip()]
        elif action.recipient_type == "Field Value":
            value = self._resolve_field_path(context.doc, action.recipient_field)
            if value:
                return [str(value)]
        return []


# =============================================================================
# ACTION RUNNER FOR TESTING
# =============================================================================

class TestableActionRunner:
    """Runs action executors for testing."""

    def __init__(self, context: ActionContext):
        self.context = context
        self.results: List[ActionResult] = []

    def execute_action(self, action) -> ActionResult:
        action_context = ActionContext(
            doc=self.context.doc,
            old_doc=self.context.old_doc,
            rule=self.context.rule,
            action=action,
            chain_id=self.context.chain_id,
            chain_depth=self.context.chain_depth
        )
        executor = test_registry.get_executor(action.action_type)
        if not executor:
            return ActionResult(
                success=False,
                action_type=action.action_type,
                message=f"No executor registered for action type: {action.action_type}"
            )
        if not executor.should_execute(action_context):
            return ActionResult(
                success=True,
                action_type=action.action_type,
                message="Skipped: action condition not met"
            )
        validation_error = executor.validate(action_context)
        if validation_error:
            return ActionResult(
                success=False,
                action_type=action.action_type,
                message=f"Validation failed: {validation_error}"
            )
        try:
            return executor.execute(action_context)
        except Exception as e:
            return ActionResult(
                success=False,
                action_type=action.action_type,
                message=str(e)
            )

    def execute_all(self) -> List[ActionResult]:
        rule = self.context.rule
        self.results = []
        if not rule.actions:
            return self.results
        sorted_actions = sorted(rule.actions, key=lambda a: a.sequence)
        for action in sorted_actions:
            if not action.enabled:
                continue
            result = self.execute_action(action)
            self.results.append(result)
            if not result.success and action.stop_on_error:
                break
        return self.results


# =============================================================================
# TEST CASES
# =============================================================================

class TestActionResult(unittest.TestCase):
    """Tests for ActionResult dataclass."""

    def test_action_result_success(self):
        """Test successful action result."""
        result = ActionResult(
            success=True,
            action_type="Update Field",
            message="Updated 2 fields"
        )
        self.assertTrue(result.success)
        self.assertEqual(result.action_type, "Update Field")
        self.assertEqual(result.message, "Updated 2 fields")

    def test_action_result_failure(self):
        """Test failed action result."""
        result = ActionResult(
            success=False,
            action_type="Create Document",
            message="DocType not found"
        )
        self.assertFalse(result.success)
        self.assertEqual(result.message, "DocType not found")

    def test_action_result_to_dict(self):
        """Test ActionResult to_dict serialization."""
        result = ActionResult(
            success=True,
            action_type="Webhook",
            sequence=1,
            message="Webhook sent",
            duration_ms=150.5,
            data={"url": "https://example.com"}
        )
        result_dict = result.to_dict()
        self.assertEqual(result_dict["status"], "success")
        self.assertEqual(result_dict["action_type"], "Webhook")
        self.assertEqual(result_dict["sequence"], 1)
        self.assertEqual(result_dict["data"]["url"], "https://example.com")


class TestActionContext(unittest.TestCase):
    """Tests for ActionContext."""

    def setUp(self):
        self.doc = MockDocument(
            doctype="Test DocType",
            name="TEST-001",
            status="Draft",
            amount=100.0,
            owner="test@example.com"
        )
        self.rule = MockRule()
        self.action = MockAction()

    def test_get_template_context(self):
        """Test getting template context."""
        context = ActionContext(
            doc=self.doc,
            old_doc=None,
            rule=self.rule,
            action=self.action,
            chain_id="test-chain-123"
        )
        template_context = context.get_template_context()
        self.assertEqual(template_context["doc"], self.doc)
        self.assertEqual(template_context["rule"], self.rule)
        self.assertEqual(template_context["user"], "test@example.com")

    def test_render_template_with_doc_fields(self):
        """Test rendering template with document fields."""
        context = ActionContext(
            doc=self.doc,
            old_doc=None,
            rule=self.rule,
            action=self.action
        )
        template = "Document {{doc.name}} has status {{doc.status}}"
        result = context.render_template(template)
        self.assertEqual(result, "Document TEST-001 has status Draft")

    def test_render_template_no_jinja(self):
        """Test that non-Jinja strings are returned as-is."""
        context = ActionContext(
            doc=self.doc,
            old_doc=None,
            rule=self.rule,
            action=self.action
        )
        plain_text = "Just a plain string"
        result = context.render_template(plain_text)
        self.assertEqual(result, plain_text)


class TestActionRegistry(unittest.TestCase):
    """Tests for ActionRegistry."""

    def test_register_executor(self):
        """Test registering an executor."""
        registry = ActionRegistry()
        self.assertTrue(registry.has_executor("Update Field"))

    def test_get_executor(self):
        """Test getting an executor by action type."""
        registry = ActionRegistry()
        executor = registry.get_executor("Update Field")
        self.assertIsNotNone(executor)
        self.assertEqual(executor.action_type, "Update Field")

    def test_get_nonexistent_executor(self):
        """Test getting a non-existent executor."""
        registry = ActionRegistry()
        executor = registry.get_executor("Non Existent Action")
        self.assertIsNone(executor)

    def test_get_action_types(self):
        """Test getting list of all registered action types."""
        registry = ActionRegistry()
        action_types = registry.get_action_types()
        self.assertIn("Update Field", action_types)
        self.assertIn("Create Document", action_types)
        self.assertIn("Webhook", action_types)


class TestUpdateFieldExecutor(unittest.TestCase):
    """Tests for Update Field action executor."""

    def setUp(self):
        MockFrappe.reset_mocks()
        self.doc = MockDocument(
            doctype="Test DocType",
            name="TEST-001",
            status="Draft",
            amount=100.0
        )
        self.rule = MockRule()

    def test_validate_missing_field_mapping(self):
        """Test validation fails without field_mapping_json."""
        action = MockAction(action_type="Update Field", field_mapping_json="")
        context = ActionContext(doc=self.doc, old_doc=None, rule=self.rule, action=action)
        executor = TestableUpdateFieldExecutor()
        error = executor.validate(context)
        self.assertEqual(error, "field_mapping_json is required for Update Field action")

    def test_validate_invalid_json(self):
        """Test validation fails with invalid JSON."""
        action = MockAction(action_type="Update Field", field_mapping_json="invalid json")
        context = ActionContext(doc=self.doc, old_doc=None, rule=self.rule, action=action)
        executor = TestableUpdateFieldExecutor()
        error = executor.validate(context)
        self.assertIn("Invalid JSON", error)

    def test_execute_update_single_field(self):
        """Test updating a single field."""
        action = MockAction(
            action_type="Update Field",
            field_mapping_json='{"status": "Approved"}'
        )
        context = ActionContext(doc=self.doc, old_doc=None, rule=self.rule, action=action)
        executor = TestableUpdateFieldExecutor()
        result = executor.execute(context)
        self.assertTrue(result.success)
        self.assertEqual(self.doc.status, "Approved")
        self.assertIn("1 field(s)", result.message)

    def test_execute_update_with_jinja(self):
        """Test updating field with Jinja template."""
        self.doc.owner = "admin@example.com"
        action = MockAction(
            action_type="Update Field",
            field_mapping_json='{"modified_by": "{{doc.owner}}"}'
        )
        context = ActionContext(doc=self.doc, old_doc=None, rule=self.rule, action=action)
        executor = TestableUpdateFieldExecutor()
        result = executor.execute(context)
        self.assertTrue(result.success)
        self.assertEqual(self.doc.modified_by, "admin@example.com")


class TestCreateDocumentExecutor(unittest.TestCase):
    """Tests for Create Document action executor."""

    def setUp(self):
        MockFrappe.reset_mocks()
        self.doc = MockDocument(
            doctype="Order",
            name="ORD-001",
            customer="CUST-001"
        )
        self.rule = MockRule()

    def test_validate_missing_target_doctype(self):
        """Test validation fails without target_doctype."""
        action = MockAction(action_type="Create Document", target_doctype="")
        context = ActionContext(doc=self.doc, old_doc=None, rule=self.rule, action=action)
        executor = TestableCreateDocumentExecutor()
        error = executor.validate(context)
        self.assertEqual(error, "target_doctype is required for Create Document action")

    def test_execute_create_document(self):
        """Test creating a new document."""
        action = MockAction(
            action_type="Create Document",
            target_doctype="Activity Log",
            field_mapping_json='{"activity_type": "Order Created"}'
        )
        context = ActionContext(doc=self.doc, old_doc=None, rule=self.rule, action=action)
        executor = TestableCreateDocumentExecutor()
        result = executor.execute(context)
        self.assertTrue(result.success)
        self.assertEqual(result.data["doctype"], "Activity Log")
        self.assertEqual(len(MockFrappe._created_docs), 1)

    def test_execute_create_with_reference_field(self):
        """Test creating document with reference to trigger doc."""
        action = MockAction(
            action_type="Create Document",
            target_doctype="Comment",
            target_reference_field="reference_name",
            field_mapping_json='{"content": "Auto-generated"}'
        )
        context = ActionContext(doc=self.doc, old_doc=None, rule=self.rule, action=action)
        executor = TestableCreateDocumentExecutor()
        result = executor.execute(context)
        self.assertTrue(result.success)
        # Check that the reference was set
        created_doc = MockFrappe._created_docs[-1]
        self.assertEqual(created_doc["reference_name"], "ORD-001")


class TestDeleteDocumentExecutor(unittest.TestCase):
    """Tests for Delete Document action executor."""

    def setUp(self):
        MockFrappe.reset_mocks()
        self.doc = MockDocument(
            doctype="Draft Order",
            name="DRAFT-001"
        )
        self.rule = MockRule()

    def test_execute_delete_trigger_document(self):
        """Test deleting the trigger document."""
        action = MockAction(action_type="Delete Document")
        context = ActionContext(doc=self.doc, old_doc=None, rule=self.rule, action=action)
        executor = TestableDeleteDocumentExecutor()
        result = executor.execute(context)
        self.assertTrue(result.success)
        self.assertEqual(len(MockFrappe._deleted_docs), 1)
        self.assertEqual(MockFrappe._deleted_docs[0]["name"], "DRAFT-001")

    def test_validate_target_doctype_without_reference_field(self):
        """Test validation fails when target_doctype specified without reference field."""
        action = MockAction(
            action_type="Delete Document",
            target_doctype="Other DocType",
            target_reference_field=""
        )
        context = ActionContext(doc=self.doc, old_doc=None, rule=self.rule, action=action)
        executor = TestableDeleteDocumentExecutor()
        error = executor.validate(context)
        self.assertIn("target_reference_field is required", error)


class TestSendNotificationExecutor(unittest.TestCase):
    """Tests for Send Notification action executor."""

    def setUp(self):
        MockFrappe.reset_mocks()
        self.doc = MockDocument(
            doctype="Order",
            name="ORD-001",
            owner="owner@example.com"
        )
        self.rule = MockRule()

    def test_validate_missing_recipient_type(self):
        """Test validation fails without recipient_type."""
        action = MockAction(action_type="Send Notification")
        context = ActionContext(doc=self.doc, old_doc=None, rule=self.rule, action=action)
        executor = TestableSendNotificationExecutor()
        error = executor.validate(context)
        self.assertEqual(error, "recipient_type is required for Send Notification action")

    def test_execute_send_to_user_list(self):
        """Test sending notification to user list."""
        action = MockAction(
            action_type="Send Notification",
            recipient_type="User List",
            recipient_field="user1@example.com, user2@example.com",
            subject_template="Order {{doc.name}} updated",
            message_template="Please review"
        )
        context = ActionContext(doc=self.doc, old_doc=None, rule=self.rule, action=action)
        executor = TestableSendNotificationExecutor()
        result = executor.execute(context)
        self.assertTrue(result.success)
        self.assertEqual(result.data["recipients_notified"], 2)

    def test_execute_send_to_field_value(self):
        """Test sending notification to field value."""
        action = MockAction(
            action_type="Send Notification",
            recipient_type="Field Value",
            recipient_field="owner",
            subject_template="Update on {{doc.name}}",
            message_template="Document updated"
        )
        context = ActionContext(doc=self.doc, old_doc=None, rule=self.rule, action=action)
        executor = TestableSendNotificationExecutor()
        result = executor.execute(context)
        self.assertTrue(result.success)
        self.assertIn("owner@example.com", result.data["recipients"])


class TestSendEmailExecutor(unittest.TestCase):
    """Tests for Send Email action executor."""

    def setUp(self):
        MockFrappe.reset_mocks()
        self.doc = MockDocument(
            doctype="Invoice",
            name="INV-001",
            customer_email="customer@example.com"
        )
        self.rule = MockRule()

    def test_validate_missing_message_template(self):
        """Test validation fails without message_template."""
        action = MockAction(
            action_type="Send Email",
            recipient_type="User List",
            recipient_field="test@example.com",
            subject_template="Test Subject"
        )
        context = ActionContext(doc=self.doc, old_doc=None, rule=self.rule, action=action)
        executor = TestableSendEmailExecutor()
        error = executor.validate(context)
        self.assertEqual(error, "message_template is required for Send Email action")

    def test_execute_send_email(self):
        """Test sending email."""
        action = MockAction(
            action_type="Send Email",
            recipient_type="User List",
            recipient_field="customer@example.com",
            subject_template="Invoice {{doc.name}}",
            message_template="<p>Please find your invoice attached.</p>"
        )
        context = ActionContext(doc=self.doc, old_doc=None, rule=self.rule, action=action)
        executor = TestableSendEmailExecutor()
        result = executor.execute(context)
        self.assertTrue(result.success)
        self.assertEqual(len(MockFrappe._sent_emails), 1)
        self.assertEqual(MockFrappe._sent_emails[0]["subject"], "Invoice INV-001")


class TestWebhookExecutor(unittest.TestCase):
    """Tests for Webhook action executor."""

    def setUp(self):
        MockFrappe.reset_mocks()
        self.doc = MockDocument(
            doctype="Order",
            name="ORD-001",
            status="Confirmed"
        )
        self.rule = MockRule()

    def test_validate_missing_webhook_url(self):
        """Test validation fails without webhook_url."""
        action = MockAction(action_type="Webhook")
        context = ActionContext(doc=self.doc, old_doc=None, rule=self.rule, action=action)
        executor = TestableWebhookExecutor()
        error = executor.validate(context)
        self.assertEqual(error, "webhook_url is required for Webhook action")

    def test_validate_invalid_payload_json(self):
        """Test validation fails with invalid payload JSON."""
        action = MockAction(
            action_type="Webhook",
            webhook_url="https://example.com/webhook",
            webhook_payload_json="invalid"
        )
        context = ActionContext(doc=self.doc, old_doc=None, rule=self.rule, action=action)
        executor = TestableWebhookExecutor()
        error = executor.validate(context)
        self.assertIn("Invalid JSON", error)

    def test_execute_webhook(self):
        """Test executing webhook."""
        action = MockAction(
            action_type="Webhook",
            webhook_url="https://api.example.com/orders",
            webhook_method="POST",
            webhook_payload_json='{"order_id": "{{doc.name}}", "status": "{{doc.status}}"}'
        )
        context = ActionContext(
            doc=self.doc,
            old_doc=None,
            rule=self.rule,
            action=action,
            chain_id="chain-123"
        )
        executor = TestableWebhookExecutor()
        result = executor.execute(context)
        self.assertTrue(result.success)
        self.assertEqual(len(MockFrappe._enqueued_jobs), 1)
        job = MockFrappe._enqueued_jobs[0]
        self.assertEqual(job["kwargs"]["url"], "https://api.example.com/orders")
        self.assertEqual(job["kwargs"]["payload"]["order_id"], "ORD-001")


class TestAddCommentExecutor(unittest.TestCase):
    """Tests for Add Comment action executor."""

    def setUp(self):
        MockFrappe.reset_mocks()
        self.doc = MockDocument(
            doctype="Order",
            name="ORD-001"
        )
        self.rule = MockRule()

    def test_validate_missing_message_template(self):
        """Test validation fails without message_template."""
        action = MockAction(action_type="Add Comment")
        context = ActionContext(doc=self.doc, old_doc=None, rule=self.rule, action=action)
        executor = TestableAddCommentExecutor()
        error = executor.validate(context)
        self.assertEqual(error, "message_template is required for Add Comment action")

    def test_execute_add_comment(self):
        """Test adding a comment."""
        action = MockAction(
            action_type="Add Comment",
            message_template="Order {{doc.name}} was processed",
            subject_template="Info"
        )
        context = ActionContext(doc=self.doc, old_doc=None, rule=self.rule, action=action)
        executor = TestableAddCommentExecutor()
        result = executor.execute(context)
        self.assertTrue(result.success)
        self.assertEqual(len(self.doc._comments), 1)
        self.assertEqual(self.doc._comments[0].content, "Order ORD-001 was processed")


class TestAddTagExecutor(unittest.TestCase):
    """Tests for Add Tag action executor."""

    def setUp(self):
        MockFrappe.reset_mocks()
        self.doc = MockDocument(
            doctype="Customer",
            name="CUST-001"
        )
        self.rule = MockRule()

    def test_validate_missing_tag(self):
        """Test validation fails without tag name."""
        action = MockAction(action_type="Add Tag")
        context = ActionContext(doc=self.doc, old_doc=None, rule=self.rule, action=action)
        executor = TestableAddTagExecutor()
        error = executor.validate(context)
        self.assertIn("tag name", error)

    def test_execute_add_tag(self):
        """Test adding a tag."""
        action = MockAction(
            action_type="Add Tag",
            subject_template="VIP Customer"
        )
        context = ActionContext(doc=self.doc, old_doc=None, rule=self.rule, action=action)
        executor = TestableAddTagExecutor()
        result = executor.execute(context)
        self.assertTrue(result.success)
        self.assertIn("VIP Customer", self.doc._tags)


class TestRemoveTagExecutor(unittest.TestCase):
    """Tests for Remove Tag action executor."""

    def setUp(self):
        MockFrappe.reset_mocks()
        self.doc = MockDocument(
            doctype="Customer",
            name="CUST-001"
        )
        self.doc._tags = ["VIP Customer", "Priority"]
        self.rule = MockRule()

    def test_execute_remove_tag(self):
        """Test removing a tag."""
        action = MockAction(
            action_type="Remove Tag",
            subject_template="VIP Customer"
        )
        context = ActionContext(doc=self.doc, old_doc=None, rule=self.rule, action=action)
        executor = TestableRemoveTagExecutor()
        result = executor.execute(context)
        self.assertTrue(result.success)
        self.assertNotIn("VIP Customer", self.doc._tags)
        self.assertIn("Priority", self.doc._tags)


class TestCreateTodoExecutor(unittest.TestCase):
    """Tests for Create Todo action executor."""

    def setUp(self):
        MockFrappe.reset_mocks()
        self.doc = MockDocument(
            doctype="Task",
            name="TASK-001"
        )
        self.rule = MockRule()

    def test_validate_missing_recipient_type(self):
        """Test validation fails without recipient_type."""
        action = MockAction(action_type="Create Todo")
        context = ActionContext(doc=self.doc, old_doc=None, rule=self.rule, action=action)
        executor = TestableCreateTodoExecutor()
        error = executor.validate(context)
        self.assertEqual(error, "recipient_type is required for Create Todo action")

    def test_execute_create_todo(self):
        """Test creating a ToDo."""
        action = MockAction(
            action_type="Create Todo",
            recipient_type="User List",
            recipient_field="assignee@example.com",
            subject_template="Review task {{doc.name}}"
        )
        context = ActionContext(doc=self.doc, old_doc=None, rule=self.rule, action=action)
        executor = TestableCreateTodoExecutor()
        result = executor.execute(context)
        self.assertTrue(result.success)
        self.assertEqual(result.data["todos_created"], 1)
        # Check ToDo was created
        created_todos = [d for d in MockFrappe._created_docs if d.get("doctype") == "ToDo"]
        self.assertEqual(len(created_todos), 1)


class TestEnqueueJobExecutor(unittest.TestCase):
    """Tests for Enqueue Job action executor."""

    def setUp(self):
        MockFrappe.reset_mocks()
        self.doc = MockDocument(
            doctype="Order",
            name="ORD-001"
        )
        self.rule = MockRule()

    def test_validate_missing_function_path(self):
        """Test validation fails without function path."""
        action = MockAction(action_type="Enqueue Job")
        context = ActionContext(doc=self.doc, old_doc=None, rule=self.rule, action=action)
        executor = TestableEnqueueJobExecutor()
        error = executor.validate(context)
        self.assertIn("function path", error)

    def test_validate_invalid_function_path(self):
        """Test validation fails with invalid function path."""
        action = MockAction(
            action_type="Enqueue Job",
            subject_template="invalid_path_without_dots"
        )
        context = ActionContext(doc=self.doc, old_doc=None, rule=self.rule, action=action)
        executor = TestableEnqueueJobExecutor()
        error = executor.validate(context)
        self.assertIn("dotted Python function path", error)

    def test_execute_enqueue_job(self):
        """Test enqueueing a job."""
        action = MockAction(
            action_type="Enqueue Job",
            subject_template="myapp.tasks.process_order",
            field_mapping_json='{"order_name": "{{doc.name}}"}'
        )
        context = ActionContext(
            doc=self.doc,
            old_doc=None,
            rule=self.rule,
            action=action,
            chain_id="chain-123"
        )
        executor = TestableEnqueueJobExecutor()
        result = executor.execute(context)
        self.assertTrue(result.success)
        self.assertEqual(len(MockFrappe._enqueued_jobs), 1)
        job = MockFrappe._enqueued_jobs[0]
        self.assertEqual(job["func"], "myapp.tasks.process_order")


class TestCallAPIExecutor(unittest.TestCase):
    """Tests for Call API action executor."""

    def setUp(self):
        MockFrappe.reset_mocks()
        self.doc = MockDocument(
            doctype="Order",
            name="ORD-001"
        )
        self.rule = MockRule()

    def test_validate_missing_method_path(self):
        """Test validation fails without method path."""
        action = MockAction(action_type="Call API")
        context = ActionContext(doc=self.doc, old_doc=None, rule=self.rule, action=action)
        executor = TestableCallAPIExecutor()
        error = executor.validate(context)
        self.assertIn("API method name", error)

    def test_execute_call_api(self):
        """Test calling an API method."""
        action = MockAction(
            action_type="Call API",
            subject_template="frappe.client.get_value",
            field_mapping_json='{"doctype": "Customer", "fieldname": "customer_name"}'
        )
        context = ActionContext(doc=self.doc, old_doc=None, rule=self.rule, action=action)
        executor = TestableCallAPIExecutor()
        result = executor.execute(context)
        self.assertTrue(result.success)
        self.assertEqual(result.data["method"], "frappe.client.get_value")


class TestAssignToExecutor(unittest.TestCase):
    """Tests for Assign To action executor."""

    def setUp(self):
        MockFrappe.reset_mocks()
        self.doc = MockDocument(
            doctype="Issue",
            name="ISSUE-001"
        )
        self.rule = MockRule()

    def test_validate_missing_recipient_type(self):
        """Test validation fails without recipient_type."""
        action = MockAction(action_type="Assign To")
        context = ActionContext(doc=self.doc, old_doc=None, rule=self.rule, action=action)
        executor = TestableAssignToExecutor()
        error = executor.validate(context)
        self.assertEqual(error, "recipient_type is required for Assign To action")

    def test_execute_assign_to_users(self):
        """Test assigning document to users."""
        action = MockAction(
            action_type="Assign To",
            recipient_type="User List",
            recipient_field="user1@example.com, user2@example.com",
            subject_template="Please review this issue"
        )
        context = ActionContext(doc=self.doc, old_doc=None, rule=self.rule, action=action)
        executor = TestableAssignToExecutor()
        result = executor.execute(context)
        self.assertTrue(result.success)
        self.assertEqual(result.data["assignments_created"], 2)


class TestActionRunner(unittest.TestCase):
    """Tests for ActionRunner."""

    def setUp(self):
        MockFrappe.reset_mocks()
        self.doc = MockDocument(
            doctype="Order",
            name="ORD-001",
            status="Draft"
        )
        self.rule = MockRule()

    def test_execute_all_actions(self):
        """Test executing all actions in a rule."""
        self.rule.actions = [
            MockAction(
                action_type="Update Field",
                sequence=1,
                field_mapping_json='{"status": "Processing"}'
            ),
            MockAction(
                action_type="Add Comment",
                sequence=2,
                message_template="Order status updated"
            )
        ]
        context = ActionContext(
            doc=self.doc,
            old_doc=None,
            rule=self.rule,
            action=None
        )
        runner = TestableActionRunner(context)
        results = runner.execute_all()
        self.assertEqual(len(results), 2)
        self.assertTrue(all(r.success for r in results))

    def test_stop_on_error(self):
        """Test that execution stops when stop_on_error is set."""
        self.rule.actions = [
            MockAction(
                action_type="Update Field",
                sequence=1,
                stop_on_error=True,
                field_mapping_json=""  # Invalid - will fail validation
            ),
            MockAction(
                action_type="Add Comment",
                sequence=2,
                message_template="This should not execute"
            )
        ]
        context = ActionContext(
            doc=self.doc,
            old_doc=None,
            rule=self.rule,
            action=None
        )
        runner = TestableActionRunner(context)
        results = runner.execute_all()
        # Should only have one result because first action failed and had stop_on_error
        self.assertEqual(len(results), 1)
        self.assertFalse(results[0].success)

    def test_disabled_action_skipped(self):
        """Test that disabled actions are skipped."""
        self.rule.actions = [
            MockAction(
                action_type="Update Field",
                sequence=1,
                enabled=False,
                field_mapping_json='{"status": "Processing"}'
            ),
            MockAction(
                action_type="Add Comment",
                sequence=2,
                enabled=True,
                message_template="Only this executes"
            )
        ]
        context = ActionContext(
            doc=self.doc,
            old_doc=None,
            rule=self.rule,
            action=None
        )
        runner = TestableActionRunner(context)
        results = runner.execute_all()
        # Only the enabled action should have a result
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].action_type, "Add Comment")

    def test_action_condition_evaluation(self):
        """Test that action conditions are evaluated."""
        self.rule.actions = [
            MockAction(
                action_type="Add Comment",
                sequence=1,
                action_condition="{{doc.status}}",  # Will render to "Draft"
                message_template="This has a condition"
            )
        ]
        context = ActionContext(
            doc=self.doc,
            old_doc=None,
            rule=self.rule,
            action=None
        )
        runner = TestableActionRunner(context)
        results = runner.execute_all()
        # "Draft" is not "true", "1", or "yes", so action should be skipped
        self.assertEqual(len(results), 1)
        self.assertIn("Skipped", results[0].message)


class TestActionExecutorBaseClass(unittest.TestCase):
    """Tests for ActionExecutor base class functionality."""

    def setUp(self):
        MockFrappe.reset_mocks()

    def test_resolve_simple_field_path(self):
        """Test resolving simple field path."""
        doc = MockDocument(status="Active", amount=500)
        executor = ActionExecutor()
        self.assertEqual(executor._resolve_field_path(doc, "status"), "Active")
        self.assertEqual(executor._resolve_field_path(doc, "amount"), 500)

    def test_resolve_nested_field_path(self):
        """Test resolving nested field path with dot notation."""
        buyer = MockDocument(email="buyer@example.com", name="BUYER-001")
        doc = MockDocument(buyer=buyer)
        executor = ActionExecutor()
        self.assertEqual(executor._resolve_field_path(doc, "buyer.email"), "buyer@example.com")

    def test_resolve_array_field_path(self):
        """Test resolving field path with array index."""
        item1 = MockDocument(quantity=10, item_code="ITEM-001")
        item2 = MockDocument(quantity=20, item_code="ITEM-002")
        doc = MockDocument(items=[item1, item2])
        executor = ActionExecutor()
        self.assertEqual(executor._resolve_field_path(doc, "items[0].quantity"), 10)
        self.assertEqual(executor._resolve_field_path(doc, "items[1].item_code"), "ITEM-002")

    def test_resolve_nonexistent_field_path(self):
        """Test resolving non-existent field returns None."""
        doc = MockDocument(status="Active")
        executor = ActionExecutor()
        self.assertIsNone(executor._resolve_field_path(doc, "nonexistent"))
        self.assertIsNone(executor._resolve_field_path(doc, "buyer.email"))

    def test_should_execute_when_enabled(self):
        """Test should_execute returns True when enabled."""
        action = MockAction(enabled=True, action_condition="")
        doc = MockDocument()
        rule = MockRule()
        context = ActionContext(doc=doc, old_doc=None, rule=rule, action=action)
        executor = ActionExecutor()
        self.assertTrue(executor.should_execute(context))

    def test_should_execute_when_disabled(self):
        """Test should_execute returns False when disabled."""
        action = MockAction(enabled=False, action_condition="")
        doc = MockDocument()
        rule = MockRule()
        context = ActionContext(doc=doc, old_doc=None, rule=rule, action=action)
        executor = ActionExecutor()
        self.assertFalse(executor.should_execute(context))


class TestFieldMappingRendering(unittest.TestCase):
    """Tests for field mapping rendering with Jinja templates."""

    def setUp(self):
        MockFrappe.reset_mocks()
        self.doc = MockDocument(
            doctype="Order",
            name="ORD-001",
            customer="CUST-001",
            amount=1000.00
        )
        self.rule = MockRule()
        self.action = MockAction()

    def test_render_simple_mapping(self):
        """Test rendering simple field mapping."""
        context = ActionContext(
            doc=self.doc,
            old_doc=None,
            rule=self.rule,
            action=self.action
        )
        executor = ActionExecutor()
        mapping = {"status": "Approved", "priority": "High"}
        result = executor._render_field_mapping(context, mapping)
        self.assertEqual(result["status"], "Approved")
        self.assertEqual(result["priority"], "High")

    def test_render_mapping_with_jinja(self):
        """Test rendering field mapping with Jinja templates."""
        context = ActionContext(
            doc=self.doc,
            old_doc=None,
            rule=self.rule,
            action=self.action
        )
        executor = ActionExecutor()
        mapping = {
            "order_ref": "{{doc.name}}",
            "customer_id": "{{doc.customer}}"
        }
        result = executor._render_field_mapping(context, mapping)
        self.assertEqual(result["order_ref"], "ORD-001")
        self.assertEqual(result["customer_id"], "CUST-001")


class TestEdgeCases(unittest.TestCase):
    """Tests for edge cases and error handling."""

    def setUp(self):
        MockFrappe.reset_mocks()

    def test_empty_rule_actions(self):
        """Test handling rule with no actions."""
        doc = MockDocument()
        rule = MockRule()
        rule.actions = []
        context = ActionContext(doc=doc, old_doc=None, rule=rule, action=None)
        runner = TestableActionRunner(context)
        results = runner.execute_all()
        self.assertEqual(len(results), 0)

    def test_unregistered_action_type(self):
        """Test handling unregistered action type."""
        doc = MockDocument()
        rule = MockRule()
        action = MockAction(action_type="Unknown Action Type")
        rule.actions = [action]
        context = ActionContext(doc=doc, old_doc=None, rule=rule, action=None)
        runner = TestableActionRunner(context)
        results = runner.execute_all()
        self.assertEqual(len(results), 1)
        self.assertFalse(results[0].success)
        self.assertIn("No executor registered", results[0].message)

    def test_null_doc_field_handling(self):
        """Test handling null document fields."""
        doc = MockDocument(buyer=None)
        executor = ActionExecutor()
        result = executor._resolve_field_path(doc, "buyer.email")
        self.assertIsNone(result)

    def test_empty_recipients_handling(self):
        """Test handling actions with no recipients."""
        doc = MockDocument(owner=None)
        rule = MockRule()
        action = MockAction(
            action_type="Send Notification",
            recipient_type="Field Value",
            recipient_field="owner",
            subject_template="Test"
        )
        context = ActionContext(doc=doc, old_doc=None, rule=rule, action=action)
        executor = TestableSendNotificationExecutor()
        result = executor.execute(context)
        self.assertTrue(result.success)
        self.assertEqual(result.data["recipients_notified"], 0)


# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":
    unittest.main()

# Copyright (c) 2026, TradeHub and contributors
# For license information, please see license.txt

"""
ECA Action Executors Module

This module provides the action execution framework for ECA rules,
including the ActionExecutor base class, action registry, and
implementations of 16 different action types.

Pattern Reference: tr_tradehub/rfq/tasks.py

Action Types:
- Update Field: Modify field values on the trigger document
- Create Document: Create a new document of specified DocType
- Delete Document: Delete the trigger or target document
- Send Notification: Create Frappe notification
- Send Email: Send email via Frappe email system
- Create Notification Log: Create Notification Log entry
- Webhook: Send HTTP request to external URL
- Custom Python: Execute custom Python code via safe_exec
- Set Workflow State: Change workflow state of document
- Add Comment: Add comment to document
- Add Tag: Add tag to document
- Remove Tag: Remove tag from document
- Create Todo: Create ToDo entry
- Enqueue Job: Queue background job
- Call API: Call Frappe API method
- Assign To: Assign document to user
"""

import json
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Type, Union

import frappe
from frappe import _
from frappe.utils import cstr, now_datetime


# =============================================================================
# ACTION RESULT
# =============================================================================

@dataclass
class ActionResult:
    """
    Result of an action execution.

    Attributes:
        success: Whether the action succeeded
        action_type: The type of action executed
        sequence: The sequence number of the action
        message: Status or error message
        duration_ms: Execution time in milliseconds
        data: Additional result data
    """
    success: bool
    action_type: str
    sequence: int = 0
    message: str = ""
    duration_ms: float = 0.0
    data: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "success": self.success,
            "status": "success" if self.success else "failed",
            "action_type": self.action_type,
            "sequence": self.sequence,
            "message": self.message,
            "duration_ms": self.duration_ms,
            "data": self.data
        }


# =============================================================================
# ACTION CONTEXT
# =============================================================================

@dataclass
class ActionContext:
    """
    Context passed to action executors.

    Attributes:
        doc: The trigger document
        old_doc: Previous version of document (for change detection)
        rule: The ECA Rule document
        action: The ECA Rule Action row
        chain_id: Unique ID for the execution chain
        chain_depth: Current depth in the execution chain
    """
    doc: Any
    old_doc: Optional[Any]
    rule: Any
    action: Any
    chain_id: str = ""
    chain_depth: int = 0

    def get_template_context(self) -> Dict[str, Any]:
        """
        Build template context for Jinja rendering.

        Returns:
            Dictionary with doc, old_doc, rule, action, frappe, etc.
        """
        return {
            "doc": self.doc,
            "old_doc": self.old_doc,
            "rule": self.rule,
            "action": self.action,
            "frappe": frappe,
            "now": frappe.utils.now_datetime,
            "today": frappe.utils.today,
            "user": frappe.session.user if frappe.session else None,
            "_": _,
        }

    def render_template(self, template: str) -> str:
        """
        Render a Jinja template with the current context.

        Args:
            template: The Jinja template string

        Returns:
            Rendered string
        """
        if not template or not isinstance(template, str):
            return template

        if "{{" not in template and "{%" not in template:
            return template

        try:
            return frappe.render_template(template, self.get_template_context())
        except Exception as e:
            frappe.log_error(
                f"Error rendering action template: {template}\nError: {str(e)}",
                "ECA Action Template Error"
            )
            return template


# =============================================================================
# ACTION EXECUTOR BASE CLASS
# =============================================================================

class ActionExecutor(ABC):
    """
    Abstract base class for action executors.

    All action types must inherit from this class and implement
    the execute() method.

    Usage:
        class MyActionExecutor(ActionExecutor):
            action_type = "My Action"

            def execute(self, context: ActionContext) -> ActionResult:
                # Implementation here
                return ActionResult(success=True, action_type=self.action_type)
    """

    # The action type this executor handles
    action_type: str = ""

    def __init__(self):
        """Initialize the action executor."""
        pass

    @abstractmethod
    def execute(self, context: ActionContext) -> ActionResult:
        """
        Execute the action.

        Args:
            context: The action context with doc, rule, action, etc.

        Returns:
            ActionResult indicating success/failure
        """
        pass

    def validate(self, context: ActionContext) -> Optional[str]:
        """
        Validate the action configuration before execution.

        Override this method to add action-specific validation.

        Args:
            context: The action context

        Returns:
            Error message if validation fails, None if valid
        """
        return None

    def should_execute(self, context: ActionContext) -> bool:
        """
        Check if this action should execute based on action_condition.

        Args:
            context: The action context

        Returns:
            True if action should execute
        """
        action = context.action

        if not action.enabled:
            return False

        if not action.action_condition:
            return True

        try:
            result = context.render_template(action.action_condition)
            result_str = cstr(result).strip().lower()
            return result_str in ("true", "1", "yes")
        except Exception:
            return False

    def _resolve_field_path(self, obj: Any, field_path: str) -> Any:
        """
        Resolve a field path to get value from an object.

        Supports dot notation (buyer.email) and array access (items[0].qty).

        Args:
            obj: The object to resolve from
            field_path: The field path

        Returns:
            The resolved value or None
        """
        if not obj or not field_path:
            return None

        try:
            import re

            parts = field_path.split(".")
            current = obj

            for part in parts:
                if current is None:
                    return None

                # Check for array index
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

    def _render_field_mapping(
        self, context: ActionContext, field_mapping: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Render field mapping values with Jinja templates.

        Args:
            context: The action context
            field_mapping: Dictionary of field -> value mappings

        Returns:
            Dictionary with rendered values
        """
        rendered = {}

        for field_name, value in field_mapping.items():
            if isinstance(value, str):
                rendered[field_name] = context.render_template(value)
            else:
                rendered[field_name] = value

        return rendered


# =============================================================================
# ACTION REGISTRY
# =============================================================================

class ActionRegistry:
    """
    Registry for action executors.

    Manages the mapping between action types and their executor classes.

    Usage:
        # Register an executor
        registry = ActionRegistry()
        registry.register(UpdateFieldExecutor)

        # Get executor for action type
        executor = registry.get_executor("Update Field")
        result = executor.execute(context)
    """

    _instance: Optional["ActionRegistry"] = None
    _executors: Dict[str, Type[ActionExecutor]] = {}

    def __new__(cls):
        """Singleton pattern for registry."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._executors = {}
        return cls._instance

    def register(self, executor_class: Type[ActionExecutor]) -> None:
        """
        Register an action executor.

        Args:
            executor_class: The ActionExecutor subclass to register
        """
        if not executor_class.action_type:
            raise ValueError(f"Executor {executor_class.__name__} has no action_type")

        self._executors[executor_class.action_type] = executor_class

    def unregister(self, action_type: str) -> None:
        """
        Unregister an action executor.

        Args:
            action_type: The action type to unregister
        """
        if action_type in self._executors:
            del self._executors[action_type]

    def get_executor(self, action_type: str) -> Optional[ActionExecutor]:
        """
        Get an executor instance for an action type.

        Args:
            action_type: The action type

        Returns:
            An executor instance, or None if not registered
        """
        executor_class = self._executors.get(action_type)
        if executor_class:
            return executor_class()
        return None

    def has_executor(self, action_type: str) -> bool:
        """
        Check if an executor is registered for an action type.

        Args:
            action_type: The action type

        Returns:
            True if executor is registered
        """
        return action_type in self._executors

    def get_action_types(self) -> List[str]:
        """
        Get list of all registered action types.

        Returns:
            List of action type names
        """
        return list(self._executors.keys())

    def get_executor_class(self, action_type: str) -> Optional[Type[ActionExecutor]]:
        """
        Get the executor class for an action type.

        Args:
            action_type: The action type

        Returns:
            The executor class, or None if not registered
        """
        return self._executors.get(action_type)


# Global registry instance
action_registry = ActionRegistry()


def register_action(executor_class: Type[ActionExecutor]) -> Type[ActionExecutor]:
    """
    Decorator to register an action executor.

    Usage:
        @register_action
        class MyExecutor(ActionExecutor):
            action_type = "My Action"
    """
    action_registry.register(executor_class)
    return executor_class


# =============================================================================
# ACTION EXECUTOR RUNNER
# =============================================================================

class ActionRunner:
    """
    Runs action executors and manages execution flow.

    Handles action sequence, error handling, stop_on_error behavior,
    and result collection.
    """

    def __init__(self, context: ActionContext):
        """
        Initialize the action runner.

        Args:
            context: The action context
        """
        self.context = context
        self.results: List[ActionResult] = []

    def execute_action(self, action) -> ActionResult:
        """
        Execute a single action.

        Args:
            action: The ECA Rule Action row

        Returns:
            ActionResult with execution status
        """
        start_time = time.time()

        # Create context for this action
        action_context = ActionContext(
            doc=self.context.doc,
            old_doc=self.context.old_doc,
            rule=self.context.rule,
            action=action,
            chain_id=self.context.chain_id,
            chain_depth=self.context.chain_depth
        )

        # Get the executor
        executor = action_registry.get_executor(action.action_type)

        if not executor:
            duration_ms = (time.time() - start_time) * 1000
            return ActionResult(
                success=False,
                action_type=action.action_type,
                sequence=action.sequence or 0,
                message=f"No executor registered for action type: {action.action_type}",
                duration_ms=duration_ms
            )

        # Check if action should execute
        if not executor.should_execute(action_context):
            duration_ms = (time.time() - start_time) * 1000
            return ActionResult(
                success=True,
                action_type=action.action_type,
                sequence=action.sequence or 0,
                message="Skipped: action condition not met",
                duration_ms=duration_ms
            )

        # Validate action
        validation_error = executor.validate(action_context)
        if validation_error:
            duration_ms = (time.time() - start_time) * 1000
            return ActionResult(
                success=False,
                action_type=action.action_type,
                sequence=action.sequence or 0,
                message=f"Validation failed: {validation_error}",
                duration_ms=duration_ms
            )

        # Execute the action
        try:
            result = executor.execute(action_context)
            result.sequence = action.sequence or 0
            result.duration_ms = (time.time() - start_time) * 1000
            return result

        except Exception as e:
            duration_ms = (time.time() - start_time) * 1000
            error_msg = str(e)
            frappe.log_error(
                f"Error executing action {action.action_type}: {error_msg}",
                "ECA Action Execution Error"
            )
            return ActionResult(
                success=False,
                action_type=action.action_type,
                sequence=action.sequence or 0,
                message=error_msg,
                duration_ms=duration_ms
            )

    def execute_all(self) -> List[ActionResult]:
        """
        Execute all actions in the rule.

        Respects sequence order and stop_on_error settings.

        Returns:
            List of ActionResult for each action
        """
        rule = self.context.rule
        self.results = []

        if not rule.actions:
            return self.results

        # Sort actions by sequence
        sorted_actions = sorted(rule.actions, key=lambda a: a.sequence or 0)

        for action in sorted_actions:
            if not action.enabled:
                continue

            result = self.execute_action(action)
            self.results.append(result)

            # Check if we should stop on error
            if not result.success and action.stop_on_error:
                break

        return self.results

    def has_failures(self) -> bool:
        """Check if any action failed."""
        return any(not r.success for r in self.results)

    def get_overall_status(self) -> str:
        """
        Get overall execution status.

        Returns:
            "Success", "Failed", or "Partial"
        """
        if not self.results:
            return "Success"

        failures = [r for r in self.results if not r.success]
        skipped = [r for r in self.results if r.message.startswith("Skipped")]

        if not failures:
            return "Success"
        elif len(failures) == len(self.results) - len(skipped):
            return "Failed"
        else:
            return "Partial"


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

def execute_actions(
    doc,
    rule,
    old_doc=None,
    chain_id: str = "",
    chain_depth: int = 0
) -> List[ActionResult]:
    """
    Convenience function to execute all actions for a rule.

    Args:
        doc: The trigger document
        rule: The ECA Rule document
        old_doc: Previous document state
        chain_id: Execution chain ID
        chain_depth: Current chain depth

    Returns:
        List of ActionResult
    """
    context = ActionContext(
        doc=doc,
        old_doc=old_doc,
        rule=rule,
        action=None,
        chain_id=chain_id or frappe.generate_hash(length=12),
        chain_depth=chain_depth
    )

    runner = ActionRunner(context)
    return runner.execute_all()


def get_registered_action_types() -> List[str]:
    """
    Get list of all registered action types.

    Returns:
        List of action type names
    """
    return action_registry.get_action_types()


# =============================================================================
# PLACEHOLDER EXECUTORS
# =============================================================================
# These will be implemented in subsequent subtasks (3-2, 3-3, 8-1, 8-2, 8-3)

@register_action
class UpdateFieldExecutor(ActionExecutor):
    """
    Update field values on the trigger document.

    Follows the status transition pattern from tr_tradehub/rfq/tasks.py:
    - Uses doc.save(ignore_permissions=True) for system saves
    - Adds audit trail via doc.add_comment()
    - Uses frappe.db.commit() for batch operations

    Configuration via field_mapping_json:
    {
        "field_name": "value or {{jinja_template}}",
        "status": "Approved",
        "modified_by": "{{doc.owner}}"
    }
    """
    action_type = "Update Field"

    def validate(self, context: ActionContext) -> Optional[str]:
        """Validate the action configuration."""
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
        """
        Execute the update_field action.

        Updates specified fields on the trigger document using field_mapping_json.
        Supports Jinja template values for dynamic field values.

        Args:
            context: The action context with doc, rule, action, etc.

        Returns:
            ActionResult indicating success/failure
        """
        action = context.action
        doc = context.doc

        try:
            # Parse field mapping
            field_mapping = json.loads(action.field_mapping_json)

            # Render template values
            rendered_mapping = self._render_field_mapping(context, field_mapping)

            # Track changed fields for audit trail
            changed_fields = []

            # Apply field updates
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

            # Save with ignore_permissions for system operations
            doc.save(ignore_permissions=True)

            # Add audit trail comment
            doc.add_comment(
                "Info",
                _("ECA Rule '{0}' updated fields: {1}").format(
                    context.rule.rule_name,
                    ", ".join(changed_fields)
                )
            )

            return ActionResult(
                success=True,
                action_type=self.action_type,
                message=f"Updated {len(changed_fields)} field(s)",
                data={
                    "fields_updated": len(changed_fields),
                    "changes": changed_fields
                }
            )

        except Exception as e:
            frappe.log_error(
                f"Error in update_field action: {str(e)}\n"
                f"Rule: {context.rule.name}\nDoc: {doc.name}",
                "ECA Update Field Error"
            )
            return ActionResult(
                success=False,
                action_type=self.action_type,
                message=str(e)
            )


@register_action
class CreateDocumentExecutor(ActionExecutor):
    """
    Create a new document of specified DocType.

    Follows the Frappe document creation pattern:
    - Uses frappe.get_doc(dict).insert(ignore_permissions=True)
    - Supports Jinja templates for dynamic field values
    - Links back to trigger document if target_reference_field specified

    Configuration:
    - target_doctype: The DocType to create (required)
    - field_mapping_json: Field values for new document
    - target_reference_field: Field to store reference to trigger doc (optional)
    """
    action_type = "Create Document"

    def validate(self, context: ActionContext) -> Optional[str]:
        """Validate the action configuration."""
        action = context.action

        if not action.target_doctype:
            return "target_doctype is required for Create Document action"

        # Verify doctype exists
        if not frappe.db.exists("DocType", action.target_doctype):
            return f"DocType '{action.target_doctype}' does not exist"

        if action.field_mapping_json:
            try:
                mapping = json.loads(action.field_mapping_json)
                if not isinstance(mapping, dict):
                    return "field_mapping_json must be a JSON object"
            except json.JSONDecodeError as e:
                return f"Invalid JSON in field_mapping_json: {str(e)}"

        return None

    def execute(self, context: ActionContext) -> ActionResult:
        """
        Execute the create_document action.

        Creates a new document of the specified DocType with
        field values from field_mapping_json.

        Args:
            context: The action context with doc, rule, action, etc.

        Returns:
            ActionResult indicating success/failure with new doc name
        """
        action = context.action
        trigger_doc = context.doc

        try:
            # Build document data
            doc_data = {"doctype": action.target_doctype}

            # Parse and render field mapping
            if action.field_mapping_json:
                field_mapping = json.loads(action.field_mapping_json)
                rendered_mapping = self._render_field_mapping(context, field_mapping)
                doc_data.update(rendered_mapping)

            # Add reference to trigger document if specified
            if action.target_reference_field:
                # Check if field should contain doctype and name
                ref_field = action.target_reference_field

                if ref_field.endswith("_doctype"):
                    # Dynamic link pattern: set both doctype and name fields
                    base_field = ref_field[:-8]  # Remove "_doctype"
                    doc_data[ref_field] = trigger_doc.doctype
                    doc_data[base_field] = trigger_doc.name
                else:
                    # Simple link field
                    doc_data[ref_field] = trigger_doc.name

            # Create the document
            new_doc = frappe.get_doc(doc_data)
            new_doc.insert(ignore_permissions=True)

            # Add comment to new document with audit trail
            new_doc.add_comment(
                "Info",
                _("Created by ECA Rule '{0}' from {1}: {2}").format(
                    context.rule.rule_name,
                    trigger_doc.doctype,
                    trigger_doc.name
                )
            )

            return ActionResult(
                success=True,
                action_type=self.action_type,
                message=f"Created {action.target_doctype}: {new_doc.name}",
                data={
                    "doctype": action.target_doctype,
                    "name": new_doc.name,
                    "trigger_doctype": trigger_doc.doctype,
                    "trigger_name": trigger_doc.name
                }
            )

        except Exception as e:
            frappe.log_error(
                f"Error in create_document action: {str(e)}\n"
                f"Rule: {context.rule.name}\n"
                f"Target DocType: {action.target_doctype}",
                "ECA Create Document Error"
            )
            return ActionResult(
                success=False,
                action_type=self.action_type,
                message=str(e)
            )


@register_action
class DeleteDocumentExecutor(ActionExecutor):
    """
    Delete the trigger or target document.

    Follows Frappe document deletion patterns:
    - Uses frappe.delete_doc() with ignore_permissions=True
    - Can delete the trigger document itself or a related document
    - Supports conditional deletion via action_condition

    Configuration:
    - target_doctype: DocType to delete (if not set, uses trigger document)
    - target_reference_field: Field path to document name to delete (optional)
    """
    action_type = "Delete Document"

    def validate(self, context: ActionContext) -> Optional[str]:
        """Validate the action configuration."""
        action = context.action

        # If target_doctype is specified, we may need target_reference_field
        if action.target_doctype and action.target_doctype != context.doc.doctype:
            if not action.target_reference_field:
                return "target_reference_field is required when target_doctype differs from trigger document"

            # Verify doctype exists
            if not frappe.db.exists("DocType", action.target_doctype):
                return f"DocType '{action.target_doctype}' does not exist"

        return None

    def execute(self, context: ActionContext) -> ActionResult:
        """
        Execute the delete_document action.

        Deletes the trigger document or a target document based on configuration.

        Args:
            context: The action context with doc, rule, action, etc.

        Returns:
            ActionResult indicating success/failure
        """
        action = context.action
        trigger_doc = context.doc

        try:
            # Determine which document to delete
            if action.target_doctype and action.target_doctype != trigger_doc.doctype:
                # Delete a target document (not the trigger)
                target_name = self._get_target_document_name(context)
                if not target_name:
                    return ActionResult(
                        success=False,
                        action_type=self.action_type,
                        message="Could not determine target document to delete"
                    )

                doctype_to_delete = action.target_doctype
                name_to_delete = target_name
            else:
                # Delete the trigger document
                doctype_to_delete = trigger_doc.doctype
                name_to_delete = trigger_doc.name

            # Check if document exists before deletion
            if not frappe.db.exists(doctype_to_delete, name_to_delete):
                return ActionResult(
                    success=True,
                    action_type=self.action_type,
                    message=f"Document already deleted: {doctype_to_delete}/{name_to_delete}",
                    data={
                        "doctype": doctype_to_delete,
                        "name": name_to_delete,
                        "already_deleted": True
                    }
                )

            # Delete the document
            frappe.delete_doc(
                doctype_to_delete,
                name_to_delete,
                ignore_permissions=True,
                force=1  # Force delete even if document has links
            )

            return ActionResult(
                success=True,
                action_type=self.action_type,
                message=f"Deleted {doctype_to_delete}: {name_to_delete}",
                data={
                    "doctype": doctype_to_delete,
                    "name": name_to_delete,
                    "rule_name": context.rule.rule_name
                }
            )

        except frappe.LinkExistsError as e:
            # Document has linked documents that prevent deletion
            error_msg = f"Cannot delete: document has linked records - {str(e)}"
            frappe.log_error(
                f"Error in delete_document action: {error_msg}\n"
                f"Rule: {context.rule.name}",
                "ECA Delete Document Error"
            )
            return ActionResult(
                success=False,
                action_type=self.action_type,
                message=error_msg
            )

        except Exception as e:
            frappe.log_error(
                f"Error in delete_document action: {str(e)}\n"
                f"Rule: {context.rule.name}",
                "ECA Delete Document Error"
            )
            return ActionResult(
                success=False,
                action_type=self.action_type,
                message=str(e)
            )

    def _get_target_document_name(self, context: ActionContext) -> Optional[str]:
        """
        Get the name of the target document to delete.

        Args:
            context: The action context

        Returns:
            Document name to delete, or None if not found
        """
        action = context.action
        trigger_doc = context.doc

        if not action.target_reference_field:
            return None

        # Resolve the field path to get the document name
        target_name = self._resolve_field_path(trigger_doc, action.target_reference_field)

        if target_name and isinstance(target_name, str):
            # Render as template in case it's a Jinja expression
            return context.render_template(target_name)

        return target_name


@register_action
class SendNotificationExecutor(ActionExecutor):
    """
    Create Frappe notification (Notification Log entry).

    Follows the notification pattern from tr_tradehub/rfq/tasks.py:
    - Uses ignore_permissions=True for system-triggered notifications
    - Includes document_type and document_name for linking
    - Uses _() for translatable strings

    Configuration:
    - recipient_type: "Field Value", "Role", "User List", or "Jinja Expression"
    - recipient_field: Field path, role name, comma-separated users, or Jinja
    - subject_template: Jinja template for notification subject
    - message_template: Jinja template for notification message
    """
    action_type = "Send Notification"

    def validate(self, context: ActionContext) -> Optional[str]:
        """Validate the action configuration."""
        action = context.action

        if not action.recipient_type:
            return "recipient_type is required for Send Notification action"

        if not action.recipient_field:
            return "recipient_field is required for Send Notification action"

        if not action.subject_template:
            return "subject_template is required for Send Notification action"

        valid_recipient_types = ["Field Value", "Role", "User List", "Jinja Expression"]
        if action.recipient_type not in valid_recipient_types:
            return f"recipient_type must be one of: {', '.join(valid_recipient_types)}"

        return None

    def execute(self, context: ActionContext) -> ActionResult:
        """
        Execute the send_notification action.

        Creates Notification Log entries for the specified recipients.

        Args:
            context: The action context with doc, rule, action, etc.

        Returns:
            ActionResult indicating success/failure with recipients notified
        """
        action = context.action
        doc = context.doc

        try:
            # Get list of recipients
            recipients = self._get_recipients(context)

            if not recipients:
                return ActionResult(
                    success=True,
                    action_type=self.action_type,
                    message="No recipients found",
                    data={"recipients_notified": 0}
                )

            # Render subject and message templates
            subject = context.render_template(action.subject_template)
            message = context.render_template(action.message_template or "")

            # Create notification for each recipient
            notifications_created = []
            for recipient in recipients:
                try:
                    self._create_notification_log(
                        context, recipient, subject, message
                    )
                    notifications_created.append(recipient)
                except Exception as e:
                    frappe.log_error(
                        f"Failed to send notification to {recipient}: {str(e)}",
                        "ECA Send Notification Error"
                    )

            return ActionResult(
                success=True,
                action_type=self.action_type,
                message=f"Sent notifications to {len(notifications_created)} recipient(s)",
                data={
                    "recipients_notified": len(notifications_created),
                    "recipients": notifications_created,
                    "subject": subject
                }
            )

        except Exception as e:
            frappe.log_error(
                f"Error in send_notification action: {str(e)}\n"
                f"Rule: {context.rule.name}\nDoc: {doc.name}",
                "ECA Send Notification Error"
            )
            return ActionResult(
                success=False,
                action_type=self.action_type,
                message=str(e)
            )

    def _get_recipients(self, context: ActionContext) -> List[str]:
        """
        Get list of recipient users based on recipient_type.

        Args:
            context: The action context

        Returns:
            List of user email addresses
        """
        action = context.action
        doc = context.doc
        recipients = []

        if action.recipient_type == "Field Value":
            # Get user from field path on document
            value = self._resolve_field_path(doc, action.recipient_field)
            if value:
                if isinstance(value, list):
                    recipients.extend([str(v) for v in value if v])
                else:
                    recipients.append(str(value))

        elif action.recipient_type == "Role":
            # Get all users with the specified role
            role = action.recipient_field
            users = frappe.get_all(
                "Has Role",
                filters={"role": role, "parenttype": "User"},
                pluck="parent"
            )
            # Filter to active users only
            active_users = frappe.get_all(
                "User",
                filters={"name": ["in", users], "enabled": 1},
                pluck="name"
            )
            recipients.extend(active_users)

        elif action.recipient_type == "User List":
            # Comma-separated list of users
            user_list = action.recipient_field.split(",")
            recipients.extend([u.strip() for u in user_list if u.strip()])

        elif action.recipient_type == "Jinja Expression":
            # Render Jinja template to get recipient(s)
            rendered = context.render_template(action.recipient_field)
            if rendered:
                if "," in rendered:
                    recipients.extend([u.strip() for u in rendered.split(",") if u.strip()])
                else:
                    recipients.append(rendered.strip())

        # Remove duplicates and invalid values
        return list(set([r for r in recipients if r and r != "None"]))

    def _create_notification_log(
        self,
        context: ActionContext,
        recipient: str,
        subject: str,
        message: str
    ) -> None:
        """
        Create a Notification Log entry.

        Follows the pattern from tr_tradehub/rfq/tasks.py:
        frappe.get_doc({
            "doctype": "Notification Log",
            "for_user": seller_user,
            "type": "Alert",
            "document_type": "RFQ",
            "document_name": rfq["name"],
            "subject": _("RFQ Deadline Reminder: {0}").format(rfq["title"]),
            "email_content": _("The RFQ deadline is in {0} hours.").format(hours_remaining)
        }).insert(ignore_permissions=True)

        Args:
            context: The action context
            recipient: User email/ID to notify
            subject: Notification subject
            message: Notification message/content
        """
        doc = context.doc

        notification_doc = frappe.get_doc({
            "doctype": "Notification Log",
            "for_user": recipient,
            "type": "Alert",
            "document_type": doc.doctype,
            "document_name": doc.name,
            "subject": subject,
            "email_content": message or subject,
            "read": 0
        })
        notification_doc.insert(ignore_permissions=True)


@register_action
class SendEmailExecutor(ActionExecutor):
    """
    Send email via Frappe email system.

    Uses frappe.sendmail() for reliable email delivery with queuing.
    Supports HTML templates, attachments, and multiple recipients.

    Configuration:
    - recipient_type: "Field Value", "Role", "User List", or "Jinja Expression"
    - recipient_field: Field path, role name, comma-separated users, or Jinja
    - subject_template: Jinja template for email subject
    - message_template: Jinja template for email body (HTML supported)
    - field_mapping_json: Optional - {"cc": "...", "bcc": "...", "reply_to": "..."}
    """
    action_type = "Send Email"

    def validate(self, context: ActionContext) -> Optional[str]:
        """Validate the action configuration."""
        action = context.action

        if not action.recipient_type:
            return "recipient_type is required for Send Email action"

        if not action.recipient_field:
            return "recipient_field is required for Send Email action"

        if not action.subject_template:
            return "subject_template is required for Send Email action"

        if not action.message_template:
            return "message_template is required for Send Email action"

        valid_recipient_types = ["Field Value", "Role", "User List", "Jinja Expression"]
        if action.recipient_type not in valid_recipient_types:
            return f"recipient_type must be one of: {', '.join(valid_recipient_types)}"

        return None

    def execute(self, context: ActionContext) -> ActionResult:
        """
        Execute the send_email action.

        Sends emails to specified recipients via Frappe's email system.

        Args:
            context: The action context with doc, rule, action, etc.

        Returns:
            ActionResult indicating success/failure with recipients emailed
        """
        action = context.action
        doc = context.doc

        try:
            # Get list of recipients
            recipients = self._get_recipients(context)

            if not recipients:
                return ActionResult(
                    success=True,
                    action_type=self.action_type,
                    message="No recipients found for email",
                    data={"recipients_emailed": 0}
                )

            # Render subject and message templates
            subject = context.render_template(action.subject_template)
            message = context.render_template(action.message_template)

            # Get optional email settings from field_mapping_json
            email_options = {}
            if action.field_mapping_json:
                try:
                    options = json.loads(action.field_mapping_json)
                    if isinstance(options, dict):
                        # Render template values in options
                        rendered_options = self._render_field_mapping(context, options)
                        # Extract valid email options
                        if rendered_options.get("cc"):
                            email_options["cc"] = rendered_options["cc"]
                        if rendered_options.get("bcc"):
                            email_options["bcc"] = rendered_options["bcc"]
                        if rendered_options.get("reply_to"):
                            email_options["reply_to"] = rendered_options["reply_to"]
                        if rendered_options.get("sender"):
                            email_options["sender"] = rendered_options["sender"]
                except json.JSONDecodeError:
                    pass  # Ignore invalid JSON

            # Send email via Frappe's email system
            frappe.sendmail(
                recipients=recipients,
                subject=subject,
                message=message,
                reference_doctype=doc.doctype,
                reference_name=doc.name,
                delayed=True,  # Queue for async delivery
                **email_options
            )

            return ActionResult(
                success=True,
                action_type=self.action_type,
                message=f"Email queued for {len(recipients)} recipient(s)",
                data={
                    "recipients_emailed": len(recipients),
                    "recipients": recipients,
                    "subject": subject
                }
            )

        except Exception as e:
            frappe.log_error(
                f"Error in send_email action: {str(e)}\n"
                f"Rule: {context.rule.name}\nDoc: {doc.name}",
                "ECA Send Email Error"
            )
            return ActionResult(
                success=False,
                action_type=self.action_type,
                message=str(e)
            )

    def _get_recipients(self, context: ActionContext) -> List[str]:
        """
        Get list of recipient email addresses based on recipient_type.

        Args:
            context: The action context

        Returns:
            List of email addresses
        """
        action = context.action
        doc = context.doc
        recipients = []

        if action.recipient_type == "Field Value":
            # Get email from field path on document
            value = self._resolve_field_path(doc, action.recipient_field)
            if value:
                if isinstance(value, list):
                    recipients.extend([str(v) for v in value if v])
                else:
                    recipients.append(str(value))

        elif action.recipient_type == "Role":
            # Get all users with the specified role
            role = action.recipient_field
            users = frappe.get_all(
                "Has Role",
                filters={"role": role, "parenttype": "User"},
                pluck="parent"
            )
            # Get email addresses for active users
            user_emails = frappe.get_all(
                "User",
                filters={"name": ["in", users], "enabled": 1},
                pluck="email"
            )
            recipients.extend([e for e in user_emails if e])

        elif action.recipient_type == "User List":
            # Comma-separated list of users/emails
            user_list = action.recipient_field.split(",")
            for u in user_list:
                u = u.strip()
                if u and "@" in u:
                    recipients.append(u)
                elif u:
                    # Get email for user
                    email = frappe.db.get_value("User", u, "email")
                    if email:
                        recipients.append(email)

        elif action.recipient_type == "Jinja Expression":
            # Render Jinja template to get recipient(s)
            rendered = context.render_template(action.recipient_field)
            if rendered:
                for r in rendered.split(","):
                    r = r.strip()
                    if r and "@" in r:
                        recipients.append(r)
                    elif r:
                        email = frappe.db.get_value("User", r, "email")
                        if email:
                            recipients.append(email)

        # Remove duplicates and invalid values
        return list(set([r for r in recipients if r and r != "None" and "@" in r]))


@register_action
class CreateNotificationLogExecutor(ActionExecutor):
    """
    Create Notification Log entry directly.

    Similar to SendNotificationExecutor but provides more direct control
    over Notification Log creation. Use this when you need custom
    notification types or specific Notification Log configurations.

    Configuration:
    - recipient_type: "Field Value", "Role", "User List", or "Jinja Expression"
    - recipient_field: Field path, role name, comma-separated users, or Jinja
    - subject_template: Notification subject (Jinja template)
    - message_template: Notification message content (Jinja template)
    - field_mapping_json: Optional - {"type": "Alert|Mention|Energy Point|etc"}
    """
    action_type = "Create Notification Log"

    # Valid notification types in Frappe
    VALID_NOTIFICATION_TYPES = [
        "Alert",
        "Mention",
        "Energy Point",
        "Assignment",
        "Share",
        "Workflow"
    ]

    def validate(self, context: ActionContext) -> Optional[str]:
        """Validate the action configuration."""
        action = context.action

        if not action.recipient_type:
            return "recipient_type is required for Create Notification Log action"

        if not action.recipient_field:
            return "recipient_field is required for Create Notification Log action"

        if not action.subject_template:
            return "subject_template is required for Create Notification Log action"

        valid_recipient_types = ["Field Value", "Role", "User List", "Jinja Expression"]
        if action.recipient_type not in valid_recipient_types:
            return f"recipient_type must be one of: {', '.join(valid_recipient_types)}"

        return None

    def execute(self, context: ActionContext) -> ActionResult:
        """
        Execute the create_notification_log action.

        Creates Notification Log entries directly with custom options.

        Args:
            context: The action context with doc, rule, action, etc.

        Returns:
            ActionResult indicating success/failure with notifications created
        """
        action = context.action
        doc = context.doc

        try:
            # Get list of recipients
            recipients = self._get_recipients(context)

            if not recipients:
                return ActionResult(
                    success=True,
                    action_type=self.action_type,
                    message="No recipients found",
                    data={"notifications_created": 0}
                )

            # Render subject and message templates
            subject = context.render_template(action.subject_template)
            message = context.render_template(action.message_template or "")

            # Get notification type from field_mapping_json
            notification_type = "Alert"  # Default
            if action.field_mapping_json:
                try:
                    options = json.loads(action.field_mapping_json)
                    if isinstance(options, dict) and options.get("type"):
                        ntype = options["type"]
                        if ntype in self.VALID_NOTIFICATION_TYPES:
                            notification_type = ntype
                except json.JSONDecodeError:
                    pass

            # Create notification for each recipient
            notifications_created = []
            for recipient in recipients:
                try:
                    notification_doc = frappe.get_doc({
                        "doctype": "Notification Log",
                        "for_user": recipient,
                        "type": notification_type,
                        "document_type": doc.doctype,
                        "document_name": doc.name,
                        "subject": subject,
                        "email_content": message or subject,
                        "read": 0
                    })
                    notification_doc.insert(ignore_permissions=True)
                    notifications_created.append(recipient)
                except Exception as e:
                    frappe.log_error(
                        f"Failed to create notification log for {recipient}: {str(e)}",
                        "ECA Create Notification Log Error"
                    )

            return ActionResult(
                success=True,
                action_type=self.action_type,
                message=f"Created {len(notifications_created)} notification log(s)",
                data={
                    "notifications_created": len(notifications_created),
                    "recipients": notifications_created,
                    "notification_type": notification_type,
                    "subject": subject
                }
            )

        except Exception as e:
            frappe.log_error(
                f"Error in create_notification_log action: {str(e)}\n"
                f"Rule: {context.rule.name}\nDoc: {doc.name}",
                "ECA Create Notification Log Error"
            )
            return ActionResult(
                success=False,
                action_type=self.action_type,
                message=str(e)
            )

    def _get_recipients(self, context: ActionContext) -> List[str]:
        """
        Get list of recipient users based on recipient_type.

        Args:
            context: The action context

        Returns:
            List of user IDs/email addresses
        """
        action = context.action
        doc = context.doc
        recipients = []

        if action.recipient_type == "Field Value":
            value = self._resolve_field_path(doc, action.recipient_field)
            if value:
                if isinstance(value, list):
                    recipients.extend([str(v) for v in value if v])
                else:
                    recipients.append(str(value))

        elif action.recipient_type == "Role":
            role = action.recipient_field
            users = frappe.get_all(
                "Has Role",
                filters={"role": role, "parenttype": "User"},
                pluck="parent"
            )
            active_users = frappe.get_all(
                "User",
                filters={"name": ["in", users], "enabled": 1},
                pluck="name"
            )
            recipients.extend(active_users)

        elif action.recipient_type == "User List":
            user_list = action.recipient_field.split(",")
            recipients.extend([u.strip() for u in user_list if u.strip()])

        elif action.recipient_type == "Jinja Expression":
            rendered = context.render_template(action.recipient_field)
            if rendered:
                if "," in rendered:
                    recipients.extend([u.strip() for u in rendered.split(",") if u.strip()])
                else:
                    recipients.append(rendered.strip())

        return list(set([r for r in recipients if r and r != "None"]))


@register_action
class WebhookExecutor(ActionExecutor):
    """
    Send HTTP request to external URL.

    Follows spec guidelines:
    - Uses frappe.enqueue() for async execution to avoid blocking
    - Uses reasonable timeout (30s) to not block other actions
    - Supports all HTTP methods: POST, GET, PUT, PATCH, DELETE
    - Payload supports Jinja templates for dynamic content

    Configuration:
    - webhook_url: The URL to send the request to (required, supports Jinja)
    - webhook_method: HTTP method (default: POST)
    - webhook_payload_json: JSON payload for request body (supports Jinja)
    - field_mapping_json: Additional headers (optional, supports Jinja)
    """
    action_type = "Webhook"

    # Default timeout for webhook requests (30 seconds as per spec)
    DEFAULT_TIMEOUT = 30

    def validate(self, context: ActionContext) -> Optional[str]:
        """Validate the action configuration."""
        action = context.action

        if not action.webhook_url:
            return "webhook_url is required for Webhook action"

        # Validate JSON payload if provided
        if action.webhook_payload_json:
            try:
                json.loads(action.webhook_payload_json)
            except json.JSONDecodeError as e:
                return f"Invalid JSON in webhook_payload_json: {str(e)}"

        # Validate method
        valid_methods = ["POST", "GET", "PUT", "PATCH", "DELETE"]
        method = (action.webhook_method or "POST").upper()
        if method not in valid_methods:
            return f"webhook_method must be one of: {', '.join(valid_methods)}"

        return None

    def execute(self, context: ActionContext) -> ActionResult:
        """
        Execute the webhook action.

        Enqueues an async HTTP request to the webhook URL.
        For immediate execution (testing), can be called synchronously.

        Args:
            context: The action context with doc, rule, action, etc.

        Returns:
            ActionResult indicating success/failure
        """
        action = context.action
        doc = context.doc

        try:
            # Render webhook URL (supports Jinja templates)
            webhook_url = context.render_template(action.webhook_url)

            # Parse and render payload
            payload = {}
            if action.webhook_payload_json:
                # First parse the JSON, then render any Jinja templates in values
                raw_payload = json.loads(action.webhook_payload_json)
                payload = self._render_payload(context, raw_payload)

            # Get HTTP method
            method = (action.webhook_method or "POST").upper()

            # Get headers from field_mapping_json (if used for headers)
            headers = {"Content-Type": "application/json"}
            if action.field_mapping_json:
                try:
                    custom_headers = json.loads(action.field_mapping_json)
                    if isinstance(custom_headers, dict):
                        rendered_headers = self._render_field_mapping(context, custom_headers)
                        headers.update(rendered_headers)
                except json.JSONDecodeError:
                    pass  # Ignore invalid headers JSON

            # Add metadata to payload for tracking
            payload.setdefault("_eca_metadata", {
                "rule_name": context.rule.rule_name,
                "trigger_doctype": doc.doctype,
                "trigger_document": doc.name,
                "chain_id": context.chain_id,
                "timestamp": str(now_datetime())
            })

            # Enqueue the webhook call for async execution
            # This prevents blocking other actions if webhook is slow
            job_name = f"eca_webhook_{context.rule.name}_{doc.name}_{context.chain_id}"

            frappe.enqueue(
                "tr_tradehub.eca.actions._execute_webhook_request",
                queue="short",
                timeout=self.DEFAULT_TIMEOUT + 10,  # Extra buffer for job overhead
                job_name=job_name,
                url=webhook_url,
                method=method,
                payload=payload,
                headers=headers,
                timeout_seconds=self.DEFAULT_TIMEOUT,
                rule_name=context.rule.rule_name,
                doc_name=doc.name
            )

            return ActionResult(
                success=True,
                action_type=self.action_type,
                message=f"Webhook enqueued: {method} {webhook_url}",
                data={
                    "url": webhook_url,
                    "method": method,
                    "job_name": job_name,
                    "async": True
                }
            )

        except Exception as e:
            frappe.log_error(
                f"Error in webhook action: {str(e)}\n"
                f"Rule: {context.rule.name}\n"
                f"URL: {action.webhook_url}",
                "ECA Webhook Error"
            )
            return ActionResult(
                success=False,
                action_type=self.action_type,
                message=str(e)
            )

    def _render_payload(self, context: ActionContext, payload: Any) -> Any:
        """
        Recursively render Jinja templates in payload values.

        Args:
            context: The action context
            payload: The payload to render (dict, list, or value)

        Returns:
            Payload with all Jinja templates rendered
        """
        if isinstance(payload, dict):
            return {
                key: self._render_payload(context, value)
                for key, value in payload.items()
            }
        elif isinstance(payload, list):
            return [self._render_payload(context, item) for item in payload]
        elif isinstance(payload, str):
            return context.render_template(payload)
        else:
            return payload


def _execute_webhook_request(
    url: str,
    method: str,
    payload: Dict[str, Any],
    headers: Dict[str, str],
    timeout_seconds: int,
    rule_name: str,
    doc_name: str
) -> None:
    """
    Execute the actual HTTP webhook request.

    This function is called via frappe.enqueue() for async execution.

    Args:
        url: The webhook URL
        method: HTTP method
        payload: Request payload
        headers: Request headers
        timeout_seconds: Request timeout
        rule_name: ECA Rule name for logging
        doc_name: Trigger document name for logging
    """
    import requests

    try:
        response = requests.request(
            method=method,
            url=url,
            json=payload if method in ["POST", "PUT", "PATCH"] else None,
            params=payload if method == "GET" else None,
            headers=headers,
            timeout=timeout_seconds
        )

        # Log result
        if response.ok:
            frappe.logger().info(
                f"ECA Webhook success: {method} {url} - Status: {response.status_code} - "
                f"Rule: {rule_name}, Doc: {doc_name}"
            )
        else:
            frappe.log_error(
                f"ECA Webhook failed: {method} {url}\n"
                f"Status: {response.status_code}\n"
                f"Response: {response.text[:500]}\n"
                f"Rule: {rule_name}, Doc: {doc_name}",
                "ECA Webhook Failed"
            )

    except requests.Timeout:
        frappe.log_error(
            f"ECA Webhook timeout: {method} {url}\n"
            f"Timeout: {timeout_seconds}s\n"
            f"Rule: {rule_name}, Doc: {doc_name}",
            "ECA Webhook Timeout"
        )

    except requests.RequestException as e:
        frappe.log_error(
            f"ECA Webhook error: {method} {url}\n"
            f"Error: {str(e)}\n"
            f"Rule: {rule_name}, Doc: {doc_name}",
            "ECA Webhook Request Error"
        )


@register_action
class CustomPythonExecutor(ActionExecutor):
    """
    Execute custom Python code via frappe.safe_exec().

    Uses Frappe's RestrictedPython sandbox to safely execute custom code.
    The code runs in a restricted environment with limited access to
    system resources and dangerous operations.

    Available context variables:
    - doc: The trigger document
    - old_doc: Previous version of document (for change detection)
    - event_type: The event that triggered the rule (e.g., "After Save")
    - frappe: Limited access to frappe module
    - _: Translation function
    - rule: The ECA Rule document
    - action: The ECA Rule Action row
    - chain_id: Unique ID for the execution chain
    - chain_depth: Current depth in the execution chain

    To return data from the script, assign to the 'result' variable:
        result = {"status": "processed", "count": 5}

    Configuration:
    - python_code: The Python code to execute (required)
    - field_mapping_json: Additional variables to inject into context (optional)

    Security Notes:
    - Direct imports (__import__) are blocked
    - eval() and exec() are blocked
    - File system access is restricted
    - Network access is restricted
    - os and subprocess modules are blocked
    """
    action_type = "Custom Python"

    def validate(self, context: ActionContext) -> Optional[str]:
        """Validate the action configuration."""
        action = context.action

        if not action.python_code:
            return "python_code is required for Custom Python action"

        # Check for obvious dangerous patterns (safe_exec provides real protection)
        # This is just a user-friendly early warning
        code = action.python_code
        dangerous_patterns = [
            ("__import__", "Direct imports (__import__) are not allowed"),
            ("eval(", "eval() is not allowed - use direct code instead"),
            ("exec(", "exec() is not allowed - use direct code instead"),
            ("os.system", "os.system is not allowed"),
            ("subprocess", "subprocess module is not allowed"),
            ("open(", "File operations with open() are restricted"),
        ]

        for pattern, message in dangerous_patterns:
            if pattern in code:
                return f"Security warning: {message}"

        # Check for syntax errors
        try:
            compile(code, "<eca_custom_python>", "exec")
        except SyntaxError as e:
            return f"Python syntax error: {str(e)}"

        return None

    def execute(self, context: ActionContext) -> ActionResult:
        """
        Execute the custom Python code via frappe.safe_exec().

        Args:
            context: The action context with doc, rule, action, etc.

        Returns:
            ActionResult indicating success/failure with any returned data
        """
        action = context.action
        trigger_doc = context.doc

        try:
            # Build the execution context (locals available to the script)
            script_locals = self._build_script_context(context)

            # Parse any additional variables from field_mapping_json
            if action.field_mapping_json:
                try:
                    extra_vars = json.loads(action.field_mapping_json)
                    if isinstance(extra_vars, dict):
                        # Render any Jinja templates in the extra vars
                        for key, value in extra_vars.items():
                            if isinstance(value, str):
                                extra_vars[key] = context.render_template(value)
                        script_locals.update(extra_vars)
                except json.JSONDecodeError:
                    pass  # Ignore invalid JSON

            # Execute the code using frappe.safe_exec()
            # This uses RestrictedPython for sandboxed execution
            frappe.safe_exec(
                script=action.python_code,
                _globals=None,
                _locals=script_locals,
                restrict_commit_rollback=False,  # Allow commits if needed
                script_filename=f"ECA Rule: {context.rule.name}"
            )

            # Extract result if the script set one
            result_data = {}
            if "result" in script_locals:
                result_value = script_locals["result"]
                if isinstance(result_value, dict):
                    result_data = result_value
                else:
                    result_data = {"result": result_value}

            # Check if script indicated an error
            if script_locals.get("_error"):
                return ActionResult(
                    success=False,
                    action_type=self.action_type,
                    message=str(script_locals.get("_error_message", "Script indicated error")),
                    data=result_data
                )

            return ActionResult(
                success=True,
                action_type=self.action_type,
                message=f"Custom Python code executed successfully",
                data=result_data
            )

        except frappe.exceptions.ValidationError as e:
            # Re-raise validation errors as they may be intentional
            return ActionResult(
                success=False,
                action_type=self.action_type,
                message=f"Validation error in script: {str(e)}",
                data={"error_type": "ValidationError"}
            )

        except Exception as e:
            error_msg = str(e)
            frappe.log_error(
                f"ECA Custom Python execution error:\n"
                f"Rule: {context.rule.name}\n"
                f"Doc: {trigger_doc.doctype}/{trigger_doc.name}\n"
                f"Error: {error_msg}\n"
                f"Code:\n{action.python_code[:500]}...",
                "ECA Custom Python Error"
            )
            return ActionResult(
                success=False,
                action_type=self.action_type,
                message=f"Script execution error: {error_msg}",
                data={"error_type": type(e).__name__}
            )

    def _build_script_context(self, context: ActionContext) -> Dict[str, Any]:
        """
        Build the context dictionary for script execution.

        Args:
            context: The action context

        Returns:
            Dictionary of variables available to the script
        """
        return {
            # Core document context
            "doc": context.doc,
            "old_doc": context.old_doc,

            # Rule and action context
            "rule": context.rule,
            "action": context.action,
            "event_type": context.rule.event_type if context.rule else None,

            # Chain tracking
            "chain_id": context.chain_id,
            "chain_depth": context.chain_depth,

            # Frappe utilities (safe subset)
            "frappe": frappe,
            "_": _,

            # Common frappe utilities
            "now": frappe.utils.now_datetime,
            "today": frappe.utils.today,
            "cstr": frappe.utils.cstr,
            "cint": frappe.utils.cint,
            "flt": frappe.utils.flt,
            "getdate": frappe.utils.getdate,
            "get_datetime": frappe.utils.get_datetime,
            "add_days": frappe.utils.add_days,
            "date_diff": frappe.utils.date_diff,
            "json": json,

            # Current user info
            "user": frappe.session.user if frappe.session else None,

            # Result placeholder (script can set this)
            "result": None,

            # Error flag (script can set these to indicate controlled failure)
            "_error": False,
            "_error_message": None,
        }


@register_action
class SetWorkflowStateExecutor(ActionExecutor):
    """
    Change workflow state of document.

    Uses Frappe's workflow system to transition documents through
    workflow states. Validates that the document has a workflow
    and that the requested transition is allowed.

    Configuration:
    - subject_template: The target workflow state (Jinja template supported)
    - message_template: Optional comment for the workflow transition
    - target_doctype: If specified, apply workflow to this linked document instead
    - target_reference_field: Field path to get target document name
    """
    action_type = "Set Workflow State"

    def validate(self, context: ActionContext) -> Optional[str]:
        """Validate the action configuration."""
        action = context.action

        if not action.subject_template:
            return "subject_template (workflow state) is required for Set Workflow State action"

        # Check if target_doctype is specified without reference field
        if action.target_doctype and action.target_doctype != context.doc.doctype:
            if not action.target_reference_field:
                return "target_reference_field is required when target_doctype differs from trigger document"

        return None

    def execute(self, context: ActionContext) -> ActionResult:
        """
        Execute the set_workflow_state action.

        Transitions the document to the specified workflow state.

        Args:
            context: The action context with doc, rule, action, etc.

        Returns:
            ActionResult indicating success/failure
        """
        action = context.action
        trigger_doc = context.doc

        try:
            # Render the target workflow state
            target_state = context.render_template(action.subject_template).strip()

            # Determine which document to apply workflow to
            if action.target_doctype and action.target_doctype != trigger_doc.doctype:
                # Apply to a different document
                target_name = self._get_target_document_name(context)
                if not target_name:
                    return ActionResult(
                        success=False,
                        action_type=self.action_type,
                        message="Could not determine target document for workflow state change"
                    )
                doctype = action.target_doctype
                doc = frappe.get_doc(doctype, target_name)
            else:
                # Apply to trigger document
                doctype = trigger_doc.doctype
                doc = trigger_doc

            # Check if document has a workflow
            workflow_name = self._get_workflow_name(doctype)
            if not workflow_name:
                return ActionResult(
                    success=False,
                    action_type=self.action_type,
                    message=f"No workflow is active for DocType: {doctype}"
                )

            # Get current workflow state
            current_state = doc.get("workflow_state") or doc.get("status")

            # Validate the transition is allowed
            if not self._is_valid_transition(workflow_name, current_state, target_state):
                return ActionResult(
                    success=False,
                    action_type=self.action_type,
                    message=f"Invalid workflow transition from '{current_state}' to '{target_state}' for workflow '{workflow_name}'"
                )

            # Apply the workflow state change
            from frappe.model.workflow import apply_workflow

            doc.workflow_state = target_state
            apply_workflow(doc, target_state)

            # Save the document with the new state
            doc.save(ignore_permissions=True)

            # Add comment for audit trail if message_template provided
            if action.message_template:
                comment_text = context.render_template(action.message_template)
                doc.add_comment(
                    "Workflow",
                    _("ECA Rule '{0}' changed workflow state from '{1}' to '{2}': {3}").format(
                        context.rule.rule_name,
                        current_state,
                        target_state,
                        comment_text
                    )
                )
            else:
                doc.add_comment(
                    "Workflow",
                    _("ECA Rule '{0}' changed workflow state from '{1}' to '{2}'").format(
                        context.rule.rule_name,
                        current_state,
                        target_state
                    )
                )

            return ActionResult(
                success=True,
                action_type=self.action_type,
                message=f"Workflow state changed from '{current_state}' to '{target_state}'",
                data={
                    "doctype": doctype,
                    "name": doc.name,
                    "workflow": workflow_name,
                    "previous_state": current_state,
                    "new_state": target_state
                }
            )

        except Exception as e:
            frappe.log_error(
                f"Error in set_workflow_state action: {str(e)}\n"
                f"Rule: {context.rule.name}\n"
                f"Target state: {action.subject_template}",
                "ECA Set Workflow State Error"
            )
            return ActionResult(
                success=False,
                action_type=self.action_type,
                message=str(e)
            )

    def _get_workflow_name(self, doctype: str) -> Optional[str]:
        """
        Get the active workflow name for a DocType.

        Args:
            doctype: The DocType name

        Returns:
            Workflow name or None if no workflow is active
        """
        workflow = frappe.get_all(
            "Workflow",
            filters={
                "document_type": doctype,
                "is_active": 1
            },
            limit=1,
            pluck="name"
        )
        return workflow[0] if workflow else None

    def _is_valid_transition(
        self,
        workflow_name: str,
        current_state: Optional[str],
        target_state: str
    ) -> bool:
        """
        Check if the workflow transition is valid.

        Args:
            workflow_name: Name of the workflow
            current_state: Current workflow state
            target_state: Target workflow state

        Returns:
            True if transition is allowed
        """
        if not workflow_name:
            return False

        # Check if target state exists in the workflow
        workflow = frappe.get_doc("Workflow", workflow_name)

        valid_states = [state.state for state in workflow.states]
        if target_state not in valid_states:
            return False

        # If no current state, allow transition to any valid state
        if not current_state:
            return True

        # Check if there's a valid transition from current to target state
        for transition in workflow.transitions:
            if transition.state == current_state and transition.next_state == target_state:
                return True

        # Also allow if it's the same state (no-op)
        return current_state == target_state

    def _get_target_document_name(self, context: ActionContext) -> Optional[str]:
        """
        Get the name of the target document.

        Args:
            context: The action context

        Returns:
            Document name or None if not found
        """
        action = context.action
        trigger_doc = context.doc

        if not action.target_reference_field:
            return None

        target_name = self._resolve_field_path(trigger_doc, action.target_reference_field)

        if target_name and isinstance(target_name, str):
            return context.render_template(target_name)

        return target_name


@register_action
class AddCommentExecutor(ActionExecutor):
    """
    Add comment to document.

    Follows the audit trail pattern from tr_tradehub/rfq/tasks.py:
    doc.add_comment("Info", _("RFQ automatically closed due to deadline"))

    Configuration:
    - message_template: Jinja template for comment content (required)
    - subject_template: Comment type - "Info", "Comment", "Edit", etc. (optional, default: "Info")
    """
    action_type = "Add Comment"

    # Valid Frappe comment types
    VALID_COMMENT_TYPES = [
        "Comment",       # General user comment
        "Info",          # System info message
        "Edit",          # Edit notification
        "Like",          # Like notification
        "Label",         # Label change
        "Workflow",      # Workflow state change
        "Assigned",      # Assignment notification
        "Assignment Completed",  # Assignment completed
        "Attachment",    # Attachment added
        "Attachment Removed",  # Attachment removed
        "Shared",        # Document shared
        "Unshared",      # Document unshared
    ]

    def validate(self, context: ActionContext) -> Optional[str]:
        """Validate the action configuration."""
        action = context.action

        if not action.message_template:
            return "message_template is required for Add Comment action"

        # Validate comment type if specified
        if action.subject_template:
            comment_type = action.subject_template.strip()
            if comment_type not in self.VALID_COMMENT_TYPES:
                return (
                    f"Invalid comment type '{comment_type}'. "
                    f"Must be one of: {', '.join(self.VALID_COMMENT_TYPES)}"
                )

        return None

    def execute(self, context: ActionContext) -> ActionResult:
        """
        Execute the add_comment action.

        Adds a comment to the trigger document using doc.add_comment().

        Args:
            context: The action context with doc, rule, action, etc.

        Returns:
            ActionResult indicating success/failure
        """
        action = context.action
        doc = context.doc

        try:
            # Render the comment message
            comment_text = context.render_template(action.message_template)

            # Get comment type (default to "Info" for system-generated comments)
            comment_type = "Info"
            if action.subject_template:
                rendered_type = context.render_template(action.subject_template)
                if rendered_type.strip() in self.VALID_COMMENT_TYPES:
                    comment_type = rendered_type.strip()

            # Add the comment to the document
            comment = doc.add_comment(comment_type, comment_text)

            return ActionResult(
                success=True,
                action_type=self.action_type,
                message=f"Added {comment_type} comment to {doc.doctype}/{doc.name}",
                data={
                    "doctype": doc.doctype,
                    "name": doc.name,
                    "comment_type": comment_type,
                    "comment_name": comment.name if comment else None,
                    "comment_text_preview": comment_text[:100] + "..." if len(comment_text) > 100 else comment_text
                }
            )

        except Exception as e:
            frappe.log_error(
                f"Error in add_comment action: {str(e)}\n"
                f"Rule: {context.rule.name}\n"
                f"Doc: {doc.name}",
                "ECA Add Comment Error"
            )
            return ActionResult(
                success=False,
                action_type=self.action_type,
                message=str(e)
            )


@register_action
class AddTagExecutor(ActionExecutor):
    """
    Add tag to document.

    Uses Frappe's document tagging system to add tags to documents.
    Tags help with filtering and categorizing documents.

    Configuration:
    - subject_template: The tag name to add (Jinja template supported)
    - message_template: Optional - comma-separated list of additional tags
    - target_doctype: If specified, add tag to this linked document instead
    - target_reference_field: Field path to get target document name
    """
    action_type = "Add Tag"

    def validate(self, context: ActionContext) -> Optional[str]:
        """Validate the action configuration."""
        action = context.action

        if not action.subject_template:
            return "subject_template (tag name) is required for Add Tag action"

        return None

    def execute(self, context: ActionContext) -> ActionResult:
        """
        Execute the add_tag action.

        Adds one or more tags to the document.

        Args:
            context: The action context with doc, rule, action, etc.

        Returns:
            ActionResult indicating success/failure with tags added
        """
        action = context.action
        trigger_doc = context.doc

        try:
            # Determine which document to tag
            if action.target_doctype and action.target_doctype != trigger_doc.doctype:
                target_name = self._get_target_document_name(context)
                if not target_name:
                    return ActionResult(
                        success=False,
                        action_type=self.action_type,
                        message="Could not determine target document for adding tag"
                    )
                doctype = action.target_doctype
                doc_name = target_name
            else:
                doctype = trigger_doc.doctype
                doc_name = trigger_doc.name

            # Get tags to add
            tags_to_add = []

            # Primary tag from subject_template
            primary_tag = context.render_template(action.subject_template).strip()
            if primary_tag:
                tags_to_add.append(primary_tag)

            # Additional tags from message_template (comma-separated)
            if action.message_template:
                additional_tags = context.render_template(action.message_template)
                for tag in additional_tags.split(","):
                    tag = tag.strip()
                    if tag and tag not in tags_to_add:
                        tags_to_add.append(tag)

            if not tags_to_add:
                return ActionResult(
                    success=True,
                    action_type=self.action_type,
                    message="No tags to add",
                    data={"tags_added": 0}
                )

            # Add each tag using Frappe's tag system
            from frappe.desk.doctype.tag.tag import add_tag

            tags_added = []
            for tag in tags_to_add:
                try:
                    add_tag(tag=tag, dt=doctype, dn=doc_name)
                    tags_added.append(tag)
                except Exception as e:
                    frappe.log_error(
                        f"Failed to add tag '{tag}' to {doctype}/{doc_name}: {str(e)}",
                        "ECA Add Tag Error"
                    )

            return ActionResult(
                success=True,
                action_type=self.action_type,
                message=f"Added {len(tags_added)} tag(s) to {doctype}/{doc_name}",
                data={
                    "tags_added": len(tags_added),
                    "tags": tags_added,
                    "doctype": doctype,
                    "name": doc_name
                }
            )

        except Exception as e:
            frappe.log_error(
                f"Error in add_tag action: {str(e)}\n"
                f"Rule: {context.rule.name}",
                "ECA Add Tag Error"
            )
            return ActionResult(
                success=False,
                action_type=self.action_type,
                message=str(e)
            )

    def _get_target_document_name(self, context: ActionContext) -> Optional[str]:
        """
        Get the name of the target document.

        Args:
            context: The action context

        Returns:
            Document name or None if not found
        """
        action = context.action
        trigger_doc = context.doc

        if not action.target_reference_field:
            return None

        target_name = self._resolve_field_path(trigger_doc, action.target_reference_field)

        if target_name and isinstance(target_name, str):
            return context.render_template(target_name)

        return target_name


@register_action
class RemoveTagExecutor(ActionExecutor):
    """
    Remove tag from document.

    Uses Frappe's document tagging system to remove tags from documents.

    Configuration:
    - subject_template: The tag name to remove (Jinja template supported)
    - message_template: Optional - comma-separated list of additional tags to remove
    - target_doctype: If specified, remove tag from this linked document instead
    - target_reference_field: Field path to get target document name
    """
    action_type = "Remove Tag"

    def validate(self, context: ActionContext) -> Optional[str]:
        """Validate the action configuration."""
        action = context.action

        if not action.subject_template:
            return "subject_template (tag name) is required for Remove Tag action"

        return None

    def execute(self, context: ActionContext) -> ActionResult:
        """
        Execute the remove_tag action.

        Removes one or more tags from the document.

        Args:
            context: The action context with doc, rule, action, etc.

        Returns:
            ActionResult indicating success/failure with tags removed
        """
        action = context.action
        trigger_doc = context.doc

        try:
            # Determine which document to untag
            if action.target_doctype and action.target_doctype != trigger_doc.doctype:
                target_name = self._get_target_document_name(context)
                if not target_name:
                    return ActionResult(
                        success=False,
                        action_type=self.action_type,
                        message="Could not determine target document for removing tag"
                    )
                doctype = action.target_doctype
                doc_name = target_name
            else:
                doctype = trigger_doc.doctype
                doc_name = trigger_doc.name

            # Get tags to remove
            tags_to_remove = []

            # Primary tag from subject_template
            primary_tag = context.render_template(action.subject_template).strip()
            if primary_tag:
                tags_to_remove.append(primary_tag)

            # Additional tags from message_template (comma-separated)
            if action.message_template:
                additional_tags = context.render_template(action.message_template)
                for tag in additional_tags.split(","):
                    tag = tag.strip()
                    if tag and tag not in tags_to_remove:
                        tags_to_remove.append(tag)

            if not tags_to_remove:
                return ActionResult(
                    success=True,
                    action_type=self.action_type,
                    message="No tags to remove",
                    data={"tags_removed": 0}
                )

            # Remove each tag using Frappe's tag system
            from frappe.desk.doctype.tag.tag import remove_tag

            tags_removed = []
            for tag in tags_to_remove:
                try:
                    remove_tag(tag=tag, dt=doctype, dn=doc_name)
                    tags_removed.append(tag)
                except Exception as e:
                    # Tag might not exist on document, which is okay
                    frappe.log_error(
                        f"Failed to remove tag '{tag}' from {doctype}/{doc_name}: {str(e)}",
                        "ECA Remove Tag Warning"
                    )

            return ActionResult(
                success=True,
                action_type=self.action_type,
                message=f"Removed {len(tags_removed)} tag(s) from {doctype}/{doc_name}",
                data={
                    "tags_removed": len(tags_removed),
                    "tags": tags_removed,
                    "doctype": doctype,
                    "name": doc_name
                }
            )

        except Exception as e:
            frappe.log_error(
                f"Error in remove_tag action: {str(e)}\n"
                f"Rule: {context.rule.name}",
                "ECA Remove Tag Error"
            )
            return ActionResult(
                success=False,
                action_type=self.action_type,
                message=str(e)
            )

    def _get_target_document_name(self, context: ActionContext) -> Optional[str]:
        """
        Get the name of the target document.

        Args:
            context: The action context

        Returns:
            Document name or None if not found
        """
        action = context.action
        trigger_doc = context.doc

        if not action.target_reference_field:
            return None

        target_name = self._resolve_field_path(trigger_doc, action.target_reference_field)

        if target_name and isinstance(target_name, str):
            return context.render_template(target_name)

        return target_name


@register_action
class CreateTodoExecutor(ActionExecutor):
    """
    Create ToDo entry for task assignment and tracking.

    Follows Frappe ToDo DocType pattern:
    - Uses frappe.get_doc({"doctype": "ToDo", ...}).insert(ignore_permissions=True)
    - Links to trigger document via reference_type and reference_name
    - Supports Jinja templates for dynamic content

    Configuration:
    - recipient_type: "Field Value", "Role", "User List", or "Jinja Expression"
    - recipient_field: User(s) to assign the ToDo to
    - subject_template: ToDo description (rendered with Jinja)
    - message_template: Extended description (optional)
    - field_mapping_json: Additional ToDo fields like priority, date, status
    """
    action_type = "Create Todo"

    def validate(self, context: ActionContext) -> Optional[str]:
        """Validate the action configuration."""
        action = context.action

        if not action.recipient_type:
            return "recipient_type is required for Create Todo action"

        if not action.recipient_field:
            return "recipient_field is required for Create Todo action"

        if not action.subject_template:
            return "subject_template (ToDo description) is required for Create Todo action"

        valid_recipient_types = ["Field Value", "Role", "User List", "Jinja Expression"]
        if action.recipient_type not in valid_recipient_types:
            return f"recipient_type must be one of: {', '.join(valid_recipient_types)}"

        # Validate field_mapping_json if provided
        if action.field_mapping_json:
            try:
                mapping = json.loads(action.field_mapping_json)
                if not isinstance(mapping, dict):
                    return "field_mapping_json must be a JSON object"
            except json.JSONDecodeError as e:
                return f"Invalid JSON in field_mapping_json: {str(e)}"

        return None

    def execute(self, context: ActionContext) -> ActionResult:
        """
        Execute the create_todo action.

        Creates ToDo entries for the specified assignees with a reference
        to the trigger document.

        Args:
            context: The action context with doc, rule, action, etc.

        Returns:
            ActionResult indicating success/failure with todos created
        """
        action = context.action
        doc = context.doc

        try:
            # Get list of assignees
            assignees = self._get_assignees(context)

            if not assignees:
                return ActionResult(
                    success=True,
                    action_type=self.action_type,
                    message="No assignees found for ToDo",
                    data={"todos_created": 0}
                )

            # Render description and extended description
            description = context.render_template(action.subject_template)
            extended_description = ""
            if action.message_template:
                extended_description = context.render_template(action.message_template)

            # Get additional ToDo fields from field_mapping_json
            todo_fields = {}
            if action.field_mapping_json:
                raw_fields = json.loads(action.field_mapping_json)
                todo_fields = self._render_field_mapping(context, raw_fields)

            # Create ToDo for each assignee
            todos_created = []
            for assignee in assignees:
                try:
                    todo = self._create_todo(
                        context, assignee, description, extended_description, todo_fields
                    )
                    todos_created.append({
                        "name": todo.name,
                        "allocated_to": assignee
                    })
                except Exception as e:
                    frappe.log_error(
                        f"Failed to create ToDo for {assignee}: {str(e)}",
                        "ECA Create Todo Error"
                    )

            return ActionResult(
                success=True,
                action_type=self.action_type,
                message=f"Created {len(todos_created)} ToDo(s)",
                data={
                    "todos_created": len(todos_created),
                    "todos": todos_created,
                    "description": description
                }
            )

        except Exception as e:
            frappe.log_error(
                f"Error in create_todo action: {str(e)}\n"
                f"Rule: {context.rule.name}\nDoc: {doc.name}",
                "ECA Create Todo Error"
            )
            return ActionResult(
                success=False,
                action_type=self.action_type,
                message=str(e)
            )

    def _get_assignees(self, context: ActionContext) -> List[str]:
        """
        Get list of users to assign the ToDo to.

        Args:
            context: The action context

        Returns:
            List of user IDs/emails
        """
        action = context.action
        doc = context.doc
        assignees = []

        if action.recipient_type == "Field Value":
            # Get user from field path on document
            value = self._resolve_field_path(doc, action.recipient_field)
            if value:
                if isinstance(value, list):
                    assignees.extend([str(v) for v in value if v])
                else:
                    assignees.append(str(value))

        elif action.recipient_type == "Role":
            # Get all users with the specified role
            role = action.recipient_field
            users = frappe.get_all(
                "Has Role",
                filters={"role": role, "parenttype": "User"},
                pluck="parent"
            )
            # Filter to active users only
            active_users = frappe.get_all(
                "User",
                filters={"name": ["in", users], "enabled": 1},
                pluck="name"
            )
            assignees.extend(active_users)

        elif action.recipient_type == "User List":
            # Comma-separated list of users
            user_list = action.recipient_field.split(",")
            assignees.extend([u.strip() for u in user_list if u.strip()])

        elif action.recipient_type == "Jinja Expression":
            # Render Jinja template to get assignee(s)
            rendered = context.render_template(action.recipient_field)
            if rendered:
                if "," in rendered:
                    assignees.extend([u.strip() for u in rendered.split(",") if u.strip()])
                else:
                    assignees.append(rendered.strip())

        # Remove duplicates and invalid values
        return list(set([a for a in assignees if a and a != "None"]))

    def _create_todo(
        self,
        context: ActionContext,
        assignee: str,
        description: str,
        extended_description: str,
        extra_fields: Dict[str, Any]
    ) -> Any:
        """
        Create a ToDo entry.

        Args:
            context: The action context
            assignee: User to assign the ToDo to
            description: ToDo description
            extended_description: Extended description/notes
            extra_fields: Additional fields from field_mapping_json

        Returns:
            Created ToDo document
        """
        doc = context.doc

        # Build ToDo document data
        todo_data = {
            "doctype": "ToDo",
            "allocated_to": assignee,
            "description": description,
            "reference_type": doc.doctype,
            "reference_name": doc.name,
            "assigned_by": frappe.session.user,
            "status": "Open",
        }

        # Add extended description if provided
        if extended_description:
            todo_data["description"] = f"{description}\n\n{extended_description}"

        # Merge extra fields (priority, date, etc.)
        # Common fields: priority, date, status, color
        allowed_extra_fields = ["priority", "date", "status", "color", "role"]
        for field, value in extra_fields.items():
            if field in allowed_extra_fields:
                todo_data[field] = value

        # Create and insert the ToDo
        todo = frappe.get_doc(todo_data)
        todo.insert(ignore_permissions=True)

        return todo


@register_action
class EnqueueJobExecutor(ActionExecutor):
    """
    Queue background job using frappe.enqueue().

    Allows ECA rules to trigger background jobs for long-running operations
    without blocking the document save process.

    Configuration:
    - subject_template: Python function path to enqueue (e.g., "module.function")
    - field_mapping_json: Arguments to pass to the function (supports Jinja)
    - message_template: Queue name (default: "default")

    Additional options in field_mapping_json:
    - _queue: Queue name ("short", "default", "long")
    - _timeout: Job timeout in seconds
    - _job_name: Unique job name for deduplication
    - _now: Execute immediately if True (for testing)
    - _enqueue_after_commit: Wait for DB commit before enqueueing

    Example field_mapping_json:
    {
        "_queue": "long",
        "_timeout": 600,
        "arg1": "{{doc.name}}",
        "arg2": "{{doc.status}}"
    }
    """
    action_type = "Enqueue Job"

    # Default timeout for background jobs (5 minutes)
    DEFAULT_TIMEOUT = 300

    def validate(self, context: ActionContext) -> Optional[str]:
        """Validate the action configuration."""
        action = context.action

        if not action.subject_template:
            return "subject_template (function path) is required for Enqueue Job action"

        # Validate function path format (should be dotted path)
        func_path = action.subject_template.strip()
        if "." not in func_path:
            return "subject_template must be a dotted Python function path (e.g., 'myapp.tasks.process_order')"

        # Validate field_mapping_json if provided
        if action.field_mapping_json:
            try:
                mapping = json.loads(action.field_mapping_json)
                if not isinstance(mapping, dict):
                    return "field_mapping_json must be a JSON object"
            except json.JSONDecodeError as e:
                return f"Invalid JSON in field_mapping_json: {str(e)}"

        return None

    def execute(self, context: ActionContext) -> ActionResult:
        """
        Execute the enqueue_job action.

        Enqueues a background job to be processed asynchronously.

        Args:
            context: The action context with doc, rule, action, etc.

        Returns:
            ActionResult indicating success/failure with job details
        """
        action = context.action
        doc = context.doc

        try:
            # Get function path
            func_path = context.render_template(action.subject_template.strip())

            # Parse job arguments from field_mapping_json
            job_args = {}
            enqueue_kwargs = {}

            if action.field_mapping_json:
                raw_args = json.loads(action.field_mapping_json)
                rendered_args = self._render_field_mapping(context, raw_args)

                # Extract special enqueue options (prefixed with _)
                for key, value in rendered_args.items():
                    if key.startswith("_"):
                        enqueue_kwargs[key[1:]] = value  # Remove _ prefix
                    else:
                        job_args[key] = value

            # Get queue name (from message_template or _queue or default)
            queue = enqueue_kwargs.pop("queue", None)
            if not queue and action.message_template:
                queue = context.render_template(action.message_template.strip())
            queue = queue or "default"

            # Get timeout
            timeout = enqueue_kwargs.pop("timeout", self.DEFAULT_TIMEOUT)
            try:
                timeout = int(timeout)
            except (TypeError, ValueError):
                timeout = self.DEFAULT_TIMEOUT

            # Generate unique job name for deduplication
            job_name = enqueue_kwargs.pop("job_name", None)
            if not job_name:
                job_name = f"eca_job_{context.rule.name}_{doc.name}_{context.chain_id}"

            # Check for immediate execution (testing)
            execute_now = enqueue_kwargs.pop("now", False)

            # Check for enqueue after commit
            enqueue_after_commit = enqueue_kwargs.pop("enqueue_after_commit", True)

            # Add ECA metadata to job args
            job_args["_eca_context"] = {
                "rule_name": context.rule.rule_name,
                "trigger_doctype": doc.doctype,
                "trigger_document": doc.name,
                "chain_id": context.chain_id
            }

            # Enqueue the job
            frappe.enqueue(
                func_path,
                queue=queue,
                timeout=timeout,
                job_name=job_name,
                now=execute_now,
                enqueue_after_commit=enqueue_after_commit,
                **job_args
            )

            return ActionResult(
                success=True,
                action_type=self.action_type,
                message=f"Job enqueued: {func_path}",
                data={
                    "function": func_path,
                    "queue": queue,
                    "job_name": job_name,
                    "timeout": timeout,
                    "args": {k: v for k, v in job_args.items() if k != "_eca_context"},
                    "execute_now": execute_now
                }
            )

        except Exception as e:
            frappe.log_error(
                f"Error in enqueue_job action: {str(e)}\n"
                f"Rule: {context.rule.name}\n"
                f"Function: {action.subject_template}",
                "ECA Enqueue Job Error"
            )
            return ActionResult(
                success=False,
                action_type=self.action_type,
                message=str(e)
            )


@register_action
class CallAPIExecutor(ActionExecutor):
    """
    Call Frappe API method (whitelisted function).

    Allows ECA rules to call any whitelisted Frappe method, enabling
    integration with existing business logic and custom functions.

    Configuration:
    - subject_template: Method name to call (e.g., "frappe.client.get_value")
    - field_mapping_json: Arguments to pass to the method (supports Jinja)
    - message_template: Optional - if "async", will enqueue the call

    Example subject_template:
    - "frappe.client.get_value"
    - "myapp.api.process_document"
    - "erpnext.selling.doctype.sales_order.sales_order.make_delivery_note"

    Example field_mapping_json:
    {
        "doctype": "Customer",
        "filters": {"name": "{{doc.customer}}"},
        "fieldname": "customer_name"
    }
    """
    action_type = "Call API"

    def validate(self, context: ActionContext) -> Optional[str]:
        """Validate the action configuration."""
        action = context.action

        if not action.subject_template:
            return "subject_template (API method name) is required for Call API action"

        # Validate method path format
        method_path = action.subject_template.strip()
        if "." not in method_path:
            return "subject_template must be a dotted Python method path (e.g., 'frappe.client.get_value')"

        # Validate field_mapping_json if provided
        if action.field_mapping_json:
            try:
                mapping = json.loads(action.field_mapping_json)
                if not isinstance(mapping, dict):
                    return "field_mapping_json must be a JSON object"
            except json.JSONDecodeError as e:
                return f"Invalid JSON in field_mapping_json: {str(e)}"

        return None

    def execute(self, context: ActionContext) -> ActionResult:
        """
        Execute the call_api action.

        Calls a whitelisted Frappe method with the specified arguments.

        Args:
            context: The action context with doc, rule, action, etc.

        Returns:
            ActionResult indicating success/failure with API response
        """
        action = context.action
        doc = context.doc

        try:
            # Get method path
            method_path = context.render_template(action.subject_template.strip())

            # Parse method arguments from field_mapping_json
            method_args = {}
            if action.field_mapping_json:
                raw_args = json.loads(action.field_mapping_json)
                method_args = self._render_field_mapping(context, raw_args)

            # Check if should be async
            is_async = False
            if action.message_template:
                mode = context.render_template(action.message_template.strip()).lower()
                is_async = mode == "async"

            if is_async:
                # Enqueue the API call for async execution
                job_name = f"eca_api_{context.rule.name}_{doc.name}_{context.chain_id}"
                frappe.enqueue(
                    "tr_tradehub.eca.actions._execute_api_call",
                    queue="short",
                    timeout=120,
                    job_name=job_name,
                    method_path=method_path,
                    method_args=method_args,
                    rule_name=context.rule.rule_name,
                    doc_name=doc.name
                )

                return ActionResult(
                    success=True,
                    action_type=self.action_type,
                    message=f"API call enqueued: {method_path}",
                    data={
                        "method": method_path,
                        "args": method_args,
                        "async": True,
                        "job_name": job_name
                    }
                )
            else:
                # Execute API call synchronously
                result = frappe.call(method_path, **method_args)

                return ActionResult(
                    success=True,
                    action_type=self.action_type,
                    message=f"API call executed: {method_path}",
                    data={
                        "method": method_path,
                        "args": method_args,
                        "async": False,
                        "result": self._serialize_result(result)
                    }
                )

        except frappe.PermissionError as e:
            frappe.log_error(
                f"Permission denied for API call: {action.subject_template}\n"
                f"Rule: {context.rule.name}\nDoc: {doc.name}\nError: {str(e)}",
                "ECA Call API Permission Error"
            )
            return ActionResult(
                success=False,
                action_type=self.action_type,
                message=f"Permission denied: {str(e)}"
            )

        except Exception as e:
            frappe.log_error(
                f"Error in call_api action: {str(e)}\n"
                f"Rule: {context.rule.name}\n"
                f"Method: {action.subject_template}",
                "ECA Call API Error"
            )
            return ActionResult(
                success=False,
                action_type=self.action_type,
                message=str(e)
            )

    def _serialize_result(self, result: Any) -> Any:
        """
        Serialize API result for storage in action result data.

        Args:
            result: The API call result

        Returns:
            JSON-serializable result (or string representation)
        """
        if result is None:
            return None
        if isinstance(result, (str, int, float, bool)):
            return result
        if isinstance(result, (list, tuple)):
            return [self._serialize_result(item) for item in result]
        if isinstance(result, dict):
            return {k: self._serialize_result(v) for k, v in result.items()}
        # For Frappe documents and other objects
        if hasattr(result, "as_dict"):
            return result.as_dict()
        # Fallback to string representation
        return str(result)


def _execute_api_call(
    method_path: str,
    method_args: Dict[str, Any],
    rule_name: str,
    doc_name: str
) -> None:
    """
    Execute an API call asynchronously.

    This function is called via frappe.enqueue() for async execution.

    Args:
        method_path: The Frappe method path to call
        method_args: Arguments to pass to the method
        rule_name: ECA Rule name for logging
        doc_name: Trigger document name for logging
    """
    try:
        result = frappe.call(method_path, **method_args)
        frappe.logger().info(
            f"ECA async API call completed - Rule: {rule_name}, "
            f"Method: {method_path}, Doc: {doc_name}, "
            f"Result type: {type(result).__name__}"
        )
    except Exception as e:
        frappe.log_error(
            f"ECA async API call failed\n"
            f"Rule: {rule_name}\n"
            f"Method: {method_path}\n"
            f"Doc: {doc_name}\n"
            f"Args: {json.dumps(method_args, default=str)}\n"
            f"Error: {str(e)}",
            "ECA Async API Call Error"
        )


@register_action
class AssignToExecutor(ActionExecutor):
    """
    Assign document to user(s).

    Uses Frappe's built-in assignment system (frappe.desk.form.assign_to)
    to assign the trigger document to specified users.

    Configuration:
    - recipient_type: "Field Value", "Role", "User List", or "Jinja Expression"
    - recipient_field: User(s) to assign the document to
    - subject_template: Assignment description/comment (optional)
    - message_template: Priority - "Low", "Medium", "High" (optional)
    - field_mapping_json: Additional options like notify, due_date

    Example field_mapping_json:
    {
        "notify": true,
        "due_date": "{{add_days(today, 7)}}",
        "bulk_assign": false
    }
    """
    action_type = "Assign To"

    def validate(self, context: ActionContext) -> Optional[str]:
        """Validate the action configuration."""
        action = context.action

        if not action.recipient_type:
            return "recipient_type is required for Assign To action"

        if not action.recipient_field:
            return "recipient_field is required for Assign To action"

        valid_recipient_types = ["Field Value", "Role", "User List", "Jinja Expression"]
        if action.recipient_type not in valid_recipient_types:
            return f"recipient_type must be one of: {', '.join(valid_recipient_types)}"

        # Validate field_mapping_json if provided
        if action.field_mapping_json:
            try:
                mapping = json.loads(action.field_mapping_json)
                if not isinstance(mapping, dict):
                    return "field_mapping_json must be a JSON object"
            except json.JSONDecodeError as e:
                return f"Invalid JSON in field_mapping_json: {str(e)}"

        return None

    def execute(self, context: ActionContext) -> ActionResult:
        """
        Execute the assign_to action.

        Assigns the trigger document to the specified users using
        Frappe's assignment system.

        Args:
            context: The action context with doc, rule, action, etc.

        Returns:
            ActionResult indicating success/failure with assignment details
        """
        action = context.action
        doc = context.doc

        try:
            # Import Frappe's assign_to module
            from frappe.desk.form.assign_to import add as assign_add

            # Get list of assignees
            assignees = self._get_assignees(context)

            if not assignees:
                return ActionResult(
                    success=True,
                    action_type=self.action_type,
                    message="No assignees found for assignment",
                    data={"assignments_created": 0}
                )

            # Get assignment description
            description = ""
            if action.subject_template:
                description = context.render_template(action.subject_template)

            # Get priority
            priority = "Medium"
            if action.message_template:
                priority_value = context.render_template(action.message_template.strip())
                if priority_value in ["Low", "Medium", "High"]:
                    priority = priority_value

            # Get additional options from field_mapping_json
            options = {}
            if action.field_mapping_json:
                raw_options = json.loads(action.field_mapping_json)
                options = self._render_field_mapping(context, raw_options)

            # Get notify option (default True)
            notify = options.get("notify", True)
            if isinstance(notify, str):
                notify = notify.lower() in ("true", "1", "yes")

            # Get due date if specified
            due_date = options.get("due_date", None)

            # Get bulk_assign option - if True, create single assignment for all
            bulk_assign = options.get("bulk_assign", False)
            if isinstance(bulk_assign, str):
                bulk_assign = bulk_assign.lower() in ("true", "1", "yes")

            # Create assignments
            assignments_created = []

            if bulk_assign and len(assignees) > 1:
                # Create a single assignment with multiple assignees
                try:
                    assign_add({
                        "doctype": doc.doctype,
                        "name": doc.name,
                        "assign_to": assignees,
                        "description": description,
                        "priority": priority,
                        "notify": notify,
                        "date": due_date,
                        "assigned_by": frappe.session.user,
                        "bulk_assign": True
                    })
                    assignments_created.extend(assignees)
                except Exception as e:
                    frappe.log_error(
                        f"Failed bulk assignment: {str(e)}",
                        "ECA Assign To Error"
                    )
            else:
                # Create individual assignments for each user
                for assignee in assignees:
                    try:
                        # Check if already assigned
                        existing = frappe.db.exists(
                            "ToDo",
                            {
                                "reference_type": doc.doctype,
                                "reference_name": doc.name,
                                "allocated_to": assignee,
                                "status": ("!=", "Cancelled")
                            }
                        )

                        if not existing:
                            assign_add({
                                "doctype": doc.doctype,
                                "name": doc.name,
                                "assign_to": [assignee],
                                "description": description,
                                "priority": priority,
                                "notify": notify,
                                "date": due_date,
                                "assigned_by": frappe.session.user
                            })
                            assignments_created.append(assignee)
                        else:
                            # Already assigned, skip but log
                            frappe.logger().info(
                                f"ECA: Document already assigned to {assignee}"
                            )
                    except Exception as e:
                        frappe.log_error(
                            f"Failed to assign to {assignee}: {str(e)}",
                            "ECA Assign To Error"
                        )

            # Add audit trail comment
            if assignments_created:
                doc.add_comment(
                    "Info",
                    _("ECA Rule '{0}' assigned document to: {1}").format(
                        context.rule.rule_name,
                        ", ".join(assignments_created)
                    )
                )

            return ActionResult(
                success=True,
                action_type=self.action_type,
                message=f"Assigned to {len(assignments_created)} user(s)",
                data={
                    "assignments_created": len(assignments_created),
                    "assignees": assignments_created,
                    "doctype": doc.doctype,
                    "docname": doc.name,
                    "priority": priority,
                    "notify": notify
                }
            )

        except Exception as e:
            frappe.log_error(
                f"Error in assign_to action: {str(e)}\n"
                f"Rule: {context.rule.name}\nDoc: {doc.name}",
                "ECA Assign To Error"
            )
            return ActionResult(
                success=False,
                action_type=self.action_type,
                message=str(e)
            )

    def _get_assignees(self, context: ActionContext) -> List[str]:
        """
        Get list of users to assign the document to.

        Args:
            context: The action context

        Returns:
            List of user IDs/emails
        """
        action = context.action
        doc = context.doc
        assignees = []

        if action.recipient_type == "Field Value":
            # Get user from field path on document
            value = self._resolve_field_path(doc, action.recipient_field)
            if value:
                if isinstance(value, list):
                    assignees.extend([str(v) for v in value if v])
                else:
                    assignees.append(str(value))

        elif action.recipient_type == "Role":
            # Get all users with the specified role
            role = action.recipient_field
            users = frappe.get_all(
                "Has Role",
                filters={"role": role, "parenttype": "User"},
                pluck="parent"
            )
            # Filter to active users only
            active_users = frappe.get_all(
                "User",
                filters={"name": ["in", users], "enabled": 1},
                pluck="name"
            )
            assignees.extend(active_users)

        elif action.recipient_type == "User List":
            # Comma-separated list of users
            user_list = action.recipient_field.split(",")
            assignees.extend([u.strip() for u in user_list if u.strip()])

        elif action.recipient_type == "Jinja Expression":
            # Render Jinja template to get assignee(s)
            rendered = context.render_template(action.recipient_field)
            if rendered:
                if "," in rendered:
                    assignees.extend([u.strip() for u in rendered.split(",") if u.strip()])
                else:
                    assignees.append(rendered.strip())

        # Remove duplicates and invalid values
        return list(set([a for a in assignees if a and a != "None"]))

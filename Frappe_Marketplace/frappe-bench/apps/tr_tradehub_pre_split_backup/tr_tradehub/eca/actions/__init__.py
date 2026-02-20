# Copyright (c) 2026, TR TradeHub and contributors
# For license information, please see license.txt

"""
ECA Actions Module

This module provides action handlers for the ECA (Event-Condition-Action) engine.
Action handlers execute specific operations when ECA rules are triggered.

Supported Action Types:
- Send Email: Send emails using templates with Jinja variable substitution
- System Notification: Create system notifications for users
- Webhook: Make HTTP requests to external endpoints
- Set Field: Update field values on documents
- Create Document: Create new documents with template values
- Update Document: Update existing documents
- Delete Document: Delete documents
- Custom Method: Execute custom Python methods
- Log Message: Log messages to the error log

Base Classes:
- BaseActionHandler: Abstract base class for all action handlers
- ActionResult: Standard result structure for action execution

Registry:
- ACTION_HANDLERS: Registry mapping action types to handler classes

Usage:
    from tr_tradehub.eca.actions import get_action_handler, execute_action

    handler = get_action_handler('Send Email')
    result = handler.execute(action, doc, context)
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Type

try:
    import frappe
    from frappe import _
    from frappe.utils import now_datetime
except ImportError:
    frappe = None
    _ = str
    now_datetime = None

try:
    from jinja2.sandbox import SandboxedEnvironment
except ImportError:
    try:
        from jinja2 import Environment as SandboxedEnvironment
    except ImportError:
        SandboxedEnvironment = None


class ActionResult:
    """
    Standard result structure for action execution.

    Attributes:
        success: Whether the action executed successfully
        message: Human-readable message about the execution
        error: Error message if action failed
        data: Additional data from the action (optional)
    """

    def __init__(
        self,
        success: bool = True,
        message: Optional[str] = None,
        error: Optional[str] = None,
        data: Optional[Dict] = None
    ):
        self.success = success
        self.message = message
        self.error = error
        self.data = data or {}

    def to_dict(self) -> Dict:
        """Convert to dictionary for serialization."""
        result = {
            'success': self.success,
            'message': self.message
        }
        if self.error:
            result['error'] = self.error
        if self.data:
            result['data'] = self.data
        return result

    @classmethod
    def success_result(cls, message: str, data: Optional[Dict] = None) -> 'ActionResult':
        """Create a success result."""
        return cls(success=True, message=message, data=data)

    @classmethod
    def error_result(cls, error: str, message: Optional[str] = None) -> 'ActionResult':
        """Create an error result."""
        return cls(success=False, message=message, error=error)


class BaseActionHandler(ABC):
    """
    Abstract base class for ECA action handlers.

    All action handlers should inherit from this class and implement
    the execute() method. The base class provides common utilities
    for Jinja template rendering and context building.

    Subclasses must:
    - Set the `action_type` class attribute
    - Implement the `execute()` method
    - Optionally implement `validate()` for action validation

    Example:
        class EmailHandler(BaseActionHandler):
            action_type = 'Send Email'

            def execute(self, action, doc, context=None):
                # Send email logic
                return ActionResult.success_result('Email sent')
    """

    # Class attribute to identify the action type
    action_type: str = None

    def __init__(self):
        """Initialize the action handler."""
        self._jinja_env = None

    @abstractmethod
    def execute(self, action: Any, doc: Any, context: Optional[Dict] = None) -> ActionResult:
        """
        Execute the action.

        Args:
            action: ECA Rule Action child document containing action configuration
            doc: The document that triggered the ECA rule
            context: Optional additional context for template rendering

        Returns:
            ActionResult: Result of the action execution
        """
        pass

    def validate(self, action: Any) -> List[str]:
        """
        Validate action configuration.

        Override this method to provide action-specific validation.

        Args:
            action: ECA Rule Action child document

        Returns:
            List of validation error messages (empty if valid)
        """
        return []

    def get_jinja_env(self) -> Any:
        """
        Get the Jinja2 sandboxed environment for template rendering.

        Returns:
            SandboxedEnvironment instance
        """
        if self._jinja_env is None and SandboxedEnvironment:
            self._jinja_env = SandboxedEnvironment()
        return self._jinja_env

    def build_context(self, doc: Any, context: Optional[Dict] = None) -> Dict:
        """
        Build the template rendering context.

        Args:
            doc: The triggering document
            context: Optional additional context

        Returns:
            Dict containing template context variables
        """
        base_context = {
            'doc': doc.as_dict() if hasattr(doc, 'as_dict') else doc,
            'now': now_datetime() if now_datetime else None,
        }

        if frappe:
            base_context.update({
                'frappe': frappe,
                'utils': frappe.utils,
                'user': frappe.session.user if hasattr(frappe, 'session') else None,
            })

            # Add _doc_before_save if available
            if hasattr(doc, '_doc_before_save'):
                base_context['doc_before_save'] = doc._doc_before_save

        # Merge with additional context
        if context:
            base_context.update(context)

        return base_context

    def render_template(
        self,
        template: str,
        doc: Any,
        context: Optional[Dict] = None
    ) -> str:
        """
        Render a Jinja template with document context.

        Uses SandboxedEnvironment for security.

        Args:
            template: Jinja template string
            doc: The triggering document
            context: Optional additional context

        Returns:
            Rendered template string
        """
        if not template:
            return ''

        env = self.get_jinja_env()
        if not env:
            return template  # Return raw template if no Jinja env

        try:
            full_context = self.build_context(doc, context)
            jinja_template = env.from_string(template)
            return jinja_template.render(**full_context)
        except Exception as e:
            if frappe:
                frappe.log_error(
                    title="ECA Template Render Error",
                    message=f"Template: {template[:200]}\nError: {str(e)}"
                )
            return template  # Return raw template on error

    def parse_recipients(self, recipients_str: str) -> List[str]:
        """
        Parse a comma-separated list of recipients.

        Args:
            recipients_str: Comma-separated recipient string

        Returns:
            List of individual recipients
        """
        if not recipients_str:
            return []
        return [r.strip() for r in recipients_str.split(',') if r.strip()]

    def parse_json(self, json_str: str, default: Any = None) -> Any:
        """
        Safely parse a JSON string.

        Args:
            json_str: JSON string to parse
            default: Default value if parsing fails

        Returns:
            Parsed JSON object or default
        """
        if not json_str:
            return default

        import json
        try:
            return json.loads(json_str)
        except json.JSONDecodeError:
            return default


# Registry of action handlers
# Maps action type string to handler class
ACTION_HANDLERS: Dict[str, Type[BaseActionHandler]] = {}


def register_handler(handler_class: Type[BaseActionHandler]) -> Type[BaseActionHandler]:
    """
    Decorator to register an action handler.

    Usage:
        @register_handler
        class MyHandler(BaseActionHandler):
            action_type = 'My Action'
            ...

    Args:
        handler_class: Handler class to register

    Returns:
        The handler class (for decorator chaining)
    """
    if handler_class.action_type:
        ACTION_HANDLERS[handler_class.action_type] = handler_class
    return handler_class


def get_action_handler(action_type: str) -> Optional[BaseActionHandler]:
    """
    Get an action handler instance for the given action type.

    Args:
        action_type: Type of action (e.g., 'Send Email', 'Webhook')

    Returns:
        Handler instance or None if not found
    """
    handler_class = ACTION_HANDLERS.get(action_type)
    if handler_class:
        return handler_class()
    return None


def execute_action(
    action: Any,
    doc: Any,
    context: Optional[Dict] = None
) -> ActionResult:
    """
    Execute an action using the appropriate handler.

    This is the main entry point for action execution.

    Args:
        action: ECA Rule Action document
        doc: The triggering document
        context: Optional additional context

    Returns:
        ActionResult from the handler execution
    """
    handler = get_action_handler(action.action_type)

    if not handler:
        return ActionResult.error_result(
            error=f"No handler registered for action type: {action.action_type}",
            message=f"Unknown action type: {action.action_type}"
        )

    try:
        return handler.execute(action, doc, context)
    except Exception as e:
        if frappe:
            import traceback
            frappe.log_error(
                title=f"ECA Action Error: {action.action_type}",
                message=traceback.format_exc()
            )
        return ActionResult.error_result(
            error=str(e),
            message=f"Action execution failed: {action.action_type}"
        )


def get_available_action_types() -> List[str]:
    """
    Get list of all registered action types.

    Returns:
        List of action type names
    """
    return list(ACTION_HANDLERS.keys())


def validate_action(action: Any) -> List[str]:
    """
    Validate an action configuration.

    Args:
        action: ECA Rule Action document

    Returns:
        List of validation error messages
    """
    handler = get_action_handler(action.action_type)

    if not handler:
        return [f"Unknown action type: {action.action_type}"]

    return handler.validate(action)


# Export public API
__all__ = [
    'ActionResult',
    'BaseActionHandler',
    'ACTION_HANDLERS',
    'register_handler',
    'get_action_handler',
    'execute_action',
    'get_available_action_types',
    'validate_action',
]

# Aliases for backward compatibility with eca/__init__.py imports
ActionExecutor = BaseActionHandler
ActionContext = dict  # Simple alias
ActionRegistry = type(ACTION_HANDLERS)  # dict type
ActionRunner = None  # Not used

class _ActionRegistry:
    """Wrapper around ACTION_HANDLERS dict for compatibility."""
    _executors = ACTION_HANDLERS
    def register(self, cls):
        register_handler(cls)
    def get_executor(self, action_type):
        return get_action_handler(action_type)
    def get_executor_class(self, action_type):
        return ACTION_HANDLERS.get(action_type)

ActionRegistry = _ActionRegistry
action_registry = _ActionRegistry()

def register_action(cls):
    """Alias for register_handler — expected by eca/__init__.py."""
    return register_handler(cls)

def get_registered_action_types():
    return get_available_action_types()

def execute_actions(actions, doc, context=None):
    results = []
    for action in actions:
        results.append(execute_action(action, doc, context))
    return results

__all__ += [
    'ActionExecutor',
    'ActionContext',
    'ActionRegistry',
    'ActionRunner',
    'action_registry',
    'register_action',
    'get_registered_action_types',
    'execute_actions',
]

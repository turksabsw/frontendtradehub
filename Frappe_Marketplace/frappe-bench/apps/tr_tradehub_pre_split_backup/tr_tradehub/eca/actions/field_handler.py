# Copyright (c) 2026, TR TradeHub and contributors
# For license information, please see license.txt

"""
ECA Set Field Action Handler

Updates a target field on the document with a target value. Supports
Jinja template rendering for dynamic values based on document context.

Usage:
    from tr_tradehub.eca.actions.field_handler import FieldHandler, execute_set_field_action

    handler = FieldHandler()
    result = handler.execute(action, doc, context)
"""

import json
from typing import Any, Dict, List, Optional

try:
    import frappe
    from frappe import _
    from frappe.utils import cint, flt, cstr, getdate, get_datetime
except ImportError:
    frappe = None
    _ = str
    cint = int
    flt = float
    cstr = str
    getdate = None
    get_datetime = None

from . import ActionResult, BaseActionHandler, register_handler


@register_handler
class FieldHandler(BaseActionHandler):
    """
    Handler for Set Field actions.

    Updates a field on the trigger document with a specified value.
    Supports Jinja template rendering for dynamic value computation.

    Features:
    - Jinja template support for dynamic values
    - Type conversion based on field type
    - Validation of field existence
    - Support for nested dot notation fields (e.g., "meta.field")

    Fields used from ECA Rule Action:
    - target_field: Name of the field to update (required)
    - target_value: Value to set (supports Jinja expressions)
    """

    action_type = 'Set Field'

    def execute(self, action: Any, doc: Any, context: Optional[Dict] = None) -> ActionResult:
        """
        Execute the set field action.

        Args:
            action: ECA Rule Action child document with field configuration
            doc: The document that triggered the ECA rule
            context: Optional additional context for template rendering

        Returns:
            ActionResult with success/failure status and message
        """
        if not frappe:
            return ActionResult.error_result(
                error="Frappe not available",
                message="Cannot set field: Frappe framework not loaded"
            )

        try:
            # Build template context
            full_context = self.build_context(doc, context)

            # Get target field name
            target_field = getattr(action, 'target_field', None) or ''
            target_field = target_field.strip()

            if not target_field:
                return ActionResult.error_result(
                    error="No target field specified",
                    message="Set Field action failed: target_field is required"
                )

            # Validate that the field exists on the document
            if not self._field_exists(doc, target_field):
                return ActionResult.error_result(
                    error=f"Field '{target_field}' does not exist on {doc.doctype}",
                    message=f"Set Field action failed: Unknown field '{target_field}'"
                )

            # Get target value (can be empty string)
            target_value_template = getattr(action, 'target_value', '') or ''

            # Render Jinja template in target value
            rendered_value = self.render_template(target_value_template, doc, full_context)

            # Convert value based on field type
            converted_value = self._convert_value(doc, target_field, rendered_value)

            # Get the old value for logging
            old_value = self._get_field_value(doc, target_field)

            # Set the field value
            self._set_field_value(doc, target_field, converted_value)

            # Build success message
            return ActionResult.success_result(
                message=f"Set {target_field} = '{self._truncate_value(converted_value)}'",
                data={
                    'field': target_field,
                    'old_value': self._safe_serialize(old_value),
                    'new_value': self._safe_serialize(converted_value),
                    'doctype': doc.doctype,
                    'docname': doc.name
                }
            )

        except Exception as e:
            if frappe:
                frappe.log_error(
                    title="ECA Set Field Action Error",
                    message=f"Document: {doc.doctype} {doc.name}\nField: {getattr(action, 'target_field', 'N/A')}\nError: {str(e)}"
                )
            return ActionResult.error_result(
                error=str(e),
                message=f"Failed to set field: {str(e)}"
            )

    def validate(self, action: Any) -> List[str]:
        """
        Validate set field action configuration.

        Args:
            action: ECA Rule Action child document

        Returns:
            List of validation error messages
        """
        errors = []

        # Check for target field
        target_field = getattr(action, 'target_field', None)
        if not target_field or not target_field.strip():
            errors.append("Target Field is required for Set Field action")

        # Validate field name format (basic check)
        if target_field:
            target_field = target_field.strip()
            # Field names should be alphanumeric with underscores, or dot notation
            import re
            if not re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*(\.[a-zA-Z_][a-zA-Z0-9_]*)*$', target_field):
                errors.append(f"Invalid field name format: {target_field}")

        return errors

    def _field_exists(self, doc: Any, field_name: str) -> bool:
        """
        Check if a field exists on the document.

        Supports dot notation for nested fields.

        Args:
            doc: The document to check
            field_name: Name of the field (supports dot notation)

        Returns:
            True if the field exists
        """
        if not field_name:
            return False

        # Handle dot notation for nested access
        if '.' in field_name:
            parts = field_name.split('.', 1)
            first_part = parts[0]
            # Check if first part exists
            if hasattr(doc, first_part):
                nested = getattr(doc, first_part)
                if nested and len(parts) > 1:
                    # Recursively check nested field
                    return hasattr(nested, parts[1]) if hasattr(nested, '__dict__') else parts[1] in nested
            return False

        # Check if field exists on document
        if hasattr(doc, field_name):
            return True

        # Check in document's meta (Frappe DocType fields)
        if frappe and hasattr(doc, 'meta'):
            try:
                field = doc.meta.get_field(field_name)
                return field is not None
            except Exception:
                pass

        return False

    def _get_field_value(self, doc: Any, field_name: str) -> Any:
        """
        Get the current value of a field.

        Args:
            doc: The document
            field_name: Name of the field

        Returns:
            Current field value
        """
        # Handle dot notation
        if '.' in field_name:
            parts = field_name.split('.', 1)
            nested = getattr(doc, parts[0], None)
            if nested and len(parts) > 1:
                if hasattr(nested, '__dict__'):
                    return getattr(nested, parts[1], None)
                elif isinstance(nested, dict):
                    return nested.get(parts[1])
            return None

        return getattr(doc, field_name, None)

    def _set_field_value(self, doc: Any, field_name: str, value: Any) -> None:
        """
        Set a field value on the document.

        Args:
            doc: The document
            field_name: Name of the field
            value: Value to set
        """
        # Handle dot notation
        if '.' in field_name:
            parts = field_name.split('.', 1)
            nested = getattr(doc, parts[0], None)
            if nested and len(parts) > 1:
                if hasattr(nested, '__dict__'):
                    setattr(nested, parts[1], value)
                elif isinstance(nested, dict):
                    nested[parts[1]] = value
            return

        # Use Frappe's db_set if document is saved, otherwise setattr
        if frappe and hasattr(doc, 'db_set') and doc.name and not doc.get('__islocal'):
            # Document exists in DB - use db_set for immediate persistence
            # Also set in memory to keep doc in sync
            setattr(doc, field_name, value)
            doc.db_set(field_name, value, update_modified=False)
        else:
            # New document or no db_set - just set attribute
            setattr(doc, field_name, value)

    def _convert_value(self, doc: Any, field_name: str, value: str) -> Any:
        """
        Convert the string value to the appropriate type based on field definition.

        Args:
            doc: The document
            field_name: Name of the field
            value: String value to convert

        Returns:
            Converted value
        """
        if not frappe or not hasattr(doc, 'meta'):
            return value

        try:
            field = doc.meta.get_field(field_name)
            if not field:
                return value

            fieldtype = field.fieldtype

            # Handle empty/null values
            if value in (None, '', 'None', 'null'):
                if fieldtype in ('Int', 'Float', 'Currency', 'Percent'):
                    return 0
                elif fieldtype == 'Check':
                    return 0
                else:
                    return None

            # Convert based on fieldtype
            if fieldtype == 'Int':
                return cint(value)
            elif fieldtype in ('Float', 'Currency', 'Percent'):
                return flt(value)
            elif fieldtype == 'Check':
                # Handle various boolean representations
                if isinstance(value, bool):
                    return 1 if value else 0
                if isinstance(value, str):
                    return 1 if value.lower() in ('1', 'true', 'yes', 'on') else 0
                return cint(value)
            elif fieldtype == 'Date':
                if getdate:
                    return getdate(value)
                return value
            elif fieldtype == 'Datetime':
                if get_datetime:
                    return get_datetime(value)
                return value
            elif fieldtype in ('JSON', 'Code'):
                # If it looks like JSON, try to parse and re-serialize
                if value.strip().startswith(('{', '[')):
                    try:
                        parsed = json.loads(value)
                        return json.dumps(parsed)
                    except json.JSONDecodeError:
                        pass
                return value
            elif fieldtype in ('Data', 'Text', 'Small Text', 'Long Text', 'Text Editor', 'Markdown Editor'):
                return cstr(value)
            else:
                # For Link, Select, and other types - return as string
                return cstr(value)

        except Exception:
            # If conversion fails, return as-is
            return value

    def _truncate_value(self, value: Any, max_length: int = 50) -> str:
        """
        Truncate a value for display in messages.

        Args:
            value: Value to truncate
            max_length: Maximum length

        Returns:
            Truncated string representation
        """
        str_value = cstr(value) if value is not None else 'None'
        if len(str_value) > max_length:
            return str_value[:max_length] + '...'
        return str_value

    def _safe_serialize(self, value: Any) -> Any:
        """
        Safely serialize a value for JSON storage.

        Args:
            value: Value to serialize

        Returns:
            JSON-safe value
        """
        if value is None:
            return None

        # Handle date/datetime
        if hasattr(value, 'isoformat'):
            return value.isoformat()

        # Handle Frappe Document
        if hasattr(value, 'as_dict'):
            return value.name

        # Handle other complex types
        try:
            json.dumps(value)
            return value
        except (TypeError, ValueError):
            return str(value)


def execute_set_field_action(action: Any, doc: Any, context: Optional[Dict] = None) -> ActionResult:
    """
    Convenience function to execute set field action.

    This is the main entry point for set field action execution.

    Args:
        action: ECA Rule Action child document with field configuration
        doc: The document that triggered the ECA rule
        context: Optional additional context for template rendering

    Returns:
        ActionResult with success/failure status
    """
    handler = FieldHandler()
    return handler.execute(action, doc, context)


def validate_set_field_action(action: Any) -> List[str]:
    """
    Validate set field action configuration.

    Args:
        action: ECA Rule Action child document

    Returns:
        List of validation error messages
    """
    handler = FieldHandler()
    return handler.validate(action)


# Export public API
__all__ = [
    'FieldHandler',
    'execute_set_field_action',
    'validate_set_field_action',
]

# Copyright (c) 2026, TR TradeHub and contributors
# For license information, please see license.txt

"""
ECA Document Action Handler

Handles document operations for ECA rules:
- Create Document: Creates new documents of target_doctype with field values from Jinja templates
- Update Document: Updates existing documents based on criteria
- Delete Document: Deletes documents based on criteria

Usage:
    from tr_tradehub.eca.actions.document_handler import (
        DocumentHandler,
        execute_create_document_action,
        execute_update_document_action,
        execute_delete_document_action
    )

    handler = DocumentHandler()
    result = handler.execute(action, doc, context)
"""

import json
from typing import Any, Dict, List, Optional

try:
    import frappe
    from frappe import _
    from frappe.utils import cint, flt, cstr, getdate, get_datetime, now_datetime
except ImportError:
    frappe = None
    _ = str
    cint = int
    flt = float
    cstr = str
    getdate = None
    get_datetime = None
    now_datetime = None

from . import ActionResult, BaseActionHandler, register_handler


@register_handler
class CreateDocumentHandler(BaseActionHandler):
    """
    Handler for Create Document actions.

    Creates new documents of the specified target_doctype with field values
    that support Jinja template rendering for dynamic value computation.

    Features:
    - Create any DocType with field values from JSON template
    - Jinja template support for dynamic values
    - Optional linking to the parent document that triggered the rule
    - Type conversion based on target field types
    - Validation of target DocType and required fields

    Fields used from ECA Rule Action:
    - target_doctype: DocType to create (required)
    - document_values: JSON with field:value pairs (supports Jinja expressions)
    - link_to_parent: Check to link new doc to trigger doc
    - parent_field_name: Field in new doc to store parent reference
    """

    action_type = 'Create Document'

    def execute(self, action: Any, doc: Any, context: Optional[Dict] = None) -> ActionResult:
        """
        Execute the create document action.

        Args:
            action: ECA Rule Action child document with document configuration
            doc: The document that triggered the ECA rule
            context: Optional additional context for template rendering

        Returns:
            ActionResult with success/failure status and message
        """
        if not frappe:
            return ActionResult.error_result(
                error="Frappe not available",
                message="Cannot create document: Frappe framework not loaded"
            )

        try:
            # Build template context
            full_context = self.build_context(doc, context)

            # Get target DocType
            target_doctype = getattr(action, 'target_doctype', None)
            if not target_doctype:
                return ActionResult.error_result(
                    error="No target DocType specified",
                    message="Create Document action failed: target_doctype is required"
                )

            # Validate that the DocType exists
            if not frappe.db.exists("DocType", target_doctype):
                return ActionResult.error_result(
                    error=f"DocType '{target_doctype}' does not exist",
                    message=f"Create Document action failed: Unknown DocType '{target_doctype}'"
                )

            # Get document values JSON
            document_values_str = getattr(action, 'document_values', '') or '{}'

            # Parse and render document values
            field_values = self._parse_document_values(document_values_str, doc, full_context)

            if field_values is None:
                return ActionResult.error_result(
                    error="Invalid document values JSON",
                    message="Create Document action failed: Could not parse document_values"
                )

            # Add doctype to the values
            field_values['doctype'] = target_doctype

            # Handle link to parent document
            link_to_parent = getattr(action, 'link_to_parent', False)
            if link_to_parent:
                parent_field_name = getattr(action, 'parent_field_name', None)
                if parent_field_name:
                    # Set the parent reference field
                    field_values[parent_field_name] = doc.name

                    # If we also need to store the parent doctype
                    # Check if there's a corresponding doctype field
                    parent_doctype_field = parent_field_name.replace('_name', '_doctype')
                    target_meta = frappe.get_meta(target_doctype)
                    if target_meta.has_field(parent_doctype_field):
                        field_values[parent_doctype_field] = doc.doctype

            # Create the new document
            new_doc = frappe.get_doc(field_values)

            # Validate before insert
            new_doc.flags.ignore_permissions = True  # ECA actions run with elevated permissions
            new_doc.insert()

            # Build success message
            return ActionResult.success_result(
                message=f"Created {target_doctype}: {new_doc.name}",
                data={
                    'doctype': target_doctype,
                    'name': new_doc.name,
                    'linked_to': doc.name if link_to_parent else None,
                    'values': self._safe_serialize_values(field_values)
                }
            )

        except frappe.exceptions.MandatoryError as e:
            error_msg = f"Missing required field: {str(e)}"
            frappe.log_error(
                title="ECA Create Document Action Error",
                message=f"Document: {doc.doctype} {doc.name}\nTarget: {getattr(action, 'target_doctype', 'N/A')}\nError: {error_msg}"
            )
            return ActionResult.error_result(
                error=error_msg,
                message=f"Failed to create document: {error_msg}"
            )
        except frappe.exceptions.ValidationError as e:
            error_msg = f"Validation error: {str(e)}"
            frappe.log_error(
                title="ECA Create Document Action Error",
                message=f"Document: {doc.doctype} {doc.name}\nTarget: {getattr(action, 'target_doctype', 'N/A')}\nError: {error_msg}"
            )
            return ActionResult.error_result(
                error=error_msg,
                message=f"Failed to create document: {error_msg}"
            )
        except Exception as e:
            if frappe:
                import traceback
                frappe.log_error(
                    title="ECA Create Document Action Error",
                    message=f"Document: {doc.doctype} {doc.name}\nTarget: {getattr(action, 'target_doctype', 'N/A')}\nError: {str(e)}\n{traceback.format_exc()}"
                )
            return ActionResult.error_result(
                error=str(e),
                message=f"Failed to create document: {str(e)}"
            )

    def validate(self, action: Any) -> List[str]:
        """
        Validate create document action configuration.

        Args:
            action: ECA Rule Action child document

        Returns:
            List of validation error messages
        """
        errors = []

        # Check for target DocType
        target_doctype = getattr(action, 'target_doctype', None)
        if not target_doctype:
            errors.append("Target DocType is required for Create Document action")
        elif frappe:
            if not frappe.db.exists("DocType", target_doctype):
                errors.append(f"Target DocType '{target_doctype}' does not exist")

        # Check for document values
        document_values = getattr(action, 'document_values', None)
        if document_values:
            try:
                json.loads(document_values)
            except json.JSONDecodeError:
                errors.append("Document Values must be valid JSON")

        # Check parent field name if link_to_parent is enabled
        link_to_parent = getattr(action, 'link_to_parent', False)
        if link_to_parent:
            parent_field_name = getattr(action, 'parent_field_name', None)
            if not parent_field_name:
                errors.append("Parent Field Name is required when Link to Parent is enabled")

        return errors

    def _parse_document_values(
        self,
        values_str: str,
        doc: Any,
        context: Dict
    ) -> Optional[Dict]:
        """
        Parse document values JSON and render Jinja templates in values.

        Args:
            values_str: JSON string with field values
            doc: Trigger document
            context: Template context

        Returns:
            Dict of field values with rendered templates, or None if parsing fails
        """
        if not values_str or values_str.strip() == '':
            return {}

        try:
            # First, try to render the entire JSON string as a Jinja template
            # This allows for dynamic key-value pairs
            rendered_json = self.render_template(values_str, doc, context)

            # Parse the rendered JSON
            field_values = json.loads(rendered_json)

            if not isinstance(field_values, dict):
                return None

            # Process each value for any remaining Jinja templates
            processed_values = {}
            for key, value in field_values.items():
                if isinstance(value, str):
                    # Render Jinja templates in string values
                    processed_values[key] = self.render_template(value, doc, context)
                elif isinstance(value, dict):
                    # Recursively process nested dicts
                    processed_values[key] = self._process_nested_values(value, doc, context)
                elif isinstance(value, list):
                    # Process list items (for child tables)
                    processed_values[key] = [
                        self._process_nested_values(item, doc, context) if isinstance(item, dict)
                        else (self.render_template(item, doc, context) if isinstance(item, str) else item)
                        for item in value
                    ]
                else:
                    processed_values[key] = value

            return processed_values

        except json.JSONDecodeError:
            if frappe:
                frappe.log_error(
                    title="ECA Document Values Parse Error",
                    message=f"Could not parse JSON: {values_str[:500]}"
                )
            return None
        except Exception as e:
            if frappe:
                frappe.log_error(
                    title="ECA Document Values Process Error",
                    message=f"Error processing values: {str(e)}\nValues: {values_str[:500]}"
                )
            return None

    def _process_nested_values(self, values: Dict, doc: Any, context: Dict) -> Dict:
        """
        Process nested dictionary values, rendering Jinja templates.

        Args:
            values: Nested dictionary
            doc: Trigger document
            context: Template context

        Returns:
            Processed dictionary with rendered templates
        """
        processed = {}
        for key, value in values.items():
            if isinstance(value, str):
                processed[key] = self.render_template(value, doc, context)
            elif isinstance(value, dict):
                processed[key] = self._process_nested_values(value, doc, context)
            elif isinstance(value, list):
                processed[key] = [
                    self._process_nested_values(item, doc, context) if isinstance(item, dict)
                    else (self.render_template(item, doc, context) if isinstance(item, str) else item)
                    for item in value
                ]
            else:
                processed[key] = value
        return processed

    def _safe_serialize_values(self, values: Dict) -> Dict:
        """
        Safely serialize field values for logging.

        Args:
            values: Dictionary of field values

        Returns:
            Serializable dictionary
        """
        safe_values = {}
        for key, value in values.items():
            if key == 'doctype':
                continue  # Skip doctype in logging
            try:
                # Try to JSON serialize
                json.dumps(value)
                safe_values[key] = value
            except (TypeError, ValueError):
                # Convert to string if not serializable
                safe_values[key] = str(value)[:100]
        return safe_values


@register_handler
class UpdateDocumentHandler(BaseActionHandler):
    """
    Handler for Update Document actions.

    Updates existing documents based on specified criteria.

    Fields used from ECA Rule Action:
    - target_doctype: DocType to update (required)
    - document_values: JSON with field:value pairs to update (supports Jinja expressions)
    - The document to update is typically the trigger document or specified in document_values
    """

    action_type = 'Update Document'

    def execute(self, action: Any, doc: Any, context: Optional[Dict] = None) -> ActionResult:
        """
        Execute the update document action.

        Args:
            action: ECA Rule Action child document with update configuration
            doc: The document that triggered the ECA rule
            context: Optional additional context for template rendering

        Returns:
            ActionResult with success/failure status and message
        """
        if not frappe:
            return ActionResult.error_result(
                error="Frappe not available",
                message="Cannot update document: Frappe framework not loaded"
            )

        try:
            # Build template context
            full_context = self.build_context(doc, context)

            # Get target DocType (defaults to trigger document's type)
            target_doctype = getattr(action, 'target_doctype', None) or doc.doctype

            # Get document values JSON
            document_values_str = getattr(action, 'document_values', '') or '{}'

            # Parse and render document values
            create_handler = CreateDocumentHandler()
            field_values = create_handler._parse_document_values(document_values_str, doc, full_context)

            if field_values is None:
                return ActionResult.error_result(
                    error="Invalid document values JSON",
                    message="Update Document action failed: Could not parse document_values"
                )

            # Determine which document to update
            # If target_doctype matches trigger doc's type, update the trigger doc
            # Otherwise, look for 'name' in field_values
            if target_doctype == doc.doctype:
                target_doc = doc
                target_name = doc.name
            else:
                target_name = field_values.pop('name', None)
                if not target_name:
                    return ActionResult.error_result(
                        error="No document name specified",
                        message="Update Document action failed: 'name' field required in document_values for different DocType"
                    )

                if not frappe.db.exists(target_doctype, target_name):
                    return ActionResult.error_result(
                        error=f"Document '{target_doctype}/{target_name}' does not exist",
                        message=f"Update Document action failed: Document not found"
                    )

                target_doc = frappe.get_doc(target_doctype, target_name)

            # Update the fields
            updated_fields = []
            for field_name, field_value in field_values.items():
                if field_name in ('doctype', 'name'):
                    continue  # Skip meta fields

                if hasattr(target_doc, field_name):
                    old_value = getattr(target_doc, field_name, None)
                    setattr(target_doc, field_name, field_value)
                    updated_fields.append({
                        'field': field_name,
                        'old': self._truncate_value(old_value),
                        'new': self._truncate_value(field_value)
                    })

            if updated_fields:
                target_doc.flags.ignore_permissions = True
                target_doc.save()

            # Build success message
            return ActionResult.success_result(
                message=f"Updated {target_doctype}: {target_name} ({len(updated_fields)} fields)",
                data={
                    'doctype': target_doctype,
                    'name': target_name,
                    'updated_fields': updated_fields
                }
            )

        except Exception as e:
            if frappe:
                import traceback
                frappe.log_error(
                    title="ECA Update Document Action Error",
                    message=f"Document: {doc.doctype} {doc.name}\nTarget: {getattr(action, 'target_doctype', 'N/A')}\nError: {str(e)}\n{traceback.format_exc()}"
                )
            return ActionResult.error_result(
                error=str(e),
                message=f"Failed to update document: {str(e)}"
            )

    def validate(self, action: Any) -> List[str]:
        """
        Validate update document action configuration.

        Args:
            action: ECA Rule Action child document

        Returns:
            List of validation error messages
        """
        errors = []

        # Document values should be valid JSON if provided
        document_values = getattr(action, 'document_values', None)
        if document_values:
            try:
                json.loads(document_values)
            except json.JSONDecodeError:
                errors.append("Document Values must be valid JSON")

        return errors

    def _truncate_value(self, value: Any, max_length: int = 50) -> str:
        """Truncate value for display."""
        str_value = cstr(value) if value is not None else 'None'
        if len(str_value) > max_length:
            return str_value[:max_length] + '...'
        return str_value


@register_handler
class DeleteDocumentHandler(BaseActionHandler):
    """
    Handler for Delete Document actions.

    Deletes documents based on specified criteria.

    Fields used from ECA Rule Action:
    - target_doctype: DocType of document to delete (required)
    - document_values: JSON with 'name' field specifying which document to delete
    """

    action_type = 'Delete Document'

    def execute(self, action: Any, doc: Any, context: Optional[Dict] = None) -> ActionResult:
        """
        Execute the delete document action.

        Args:
            action: ECA Rule Action child document with delete configuration
            doc: The document that triggered the ECA rule
            context: Optional additional context for template rendering

        Returns:
            ActionResult with success/failure status and message
        """
        if not frappe:
            return ActionResult.error_result(
                error="Frappe not available",
                message="Cannot delete document: Frappe framework not loaded"
            )

        try:
            # Build template context
            full_context = self.build_context(doc, context)

            # Get target DocType
            target_doctype = getattr(action, 'target_doctype', None)
            if not target_doctype:
                return ActionResult.error_result(
                    error="No target DocType specified",
                    message="Delete Document action failed: target_doctype is required"
                )

            # Get document values JSON to find which document to delete
            document_values_str = getattr(action, 'document_values', '') or '{}'

            # Parse and render document values
            create_handler = CreateDocumentHandler()
            field_values = create_handler._parse_document_values(document_values_str, doc, full_context)

            if field_values is None:
                return ActionResult.error_result(
                    error="Invalid document values JSON",
                    message="Delete Document action failed: Could not parse document_values"
                )

            # Get document name to delete
            target_name = field_values.get('name')
            if not target_name:
                return ActionResult.error_result(
                    error="No document name specified",
                    message="Delete Document action failed: 'name' field required in document_values"
                )

            # Check if document exists
            if not frappe.db.exists(target_doctype, target_name):
                return ActionResult.error_result(
                    error=f"Document '{target_doctype}/{target_name}' does not exist",
                    message=f"Delete Document action failed: Document not found"
                )

            # Delete the document
            frappe.delete_doc(
                target_doctype,
                target_name,
                ignore_permissions=True,  # ECA actions run with elevated permissions
                force=True
            )

            # Build success message
            return ActionResult.success_result(
                message=f"Deleted {target_doctype}: {target_name}",
                data={
                    'doctype': target_doctype,
                    'name': target_name,
                    'deleted': True
                }
            )

        except Exception as e:
            if frappe:
                import traceback
                frappe.log_error(
                    title="ECA Delete Document Action Error",
                    message=f"Document: {doc.doctype} {doc.name}\nTarget: {getattr(action, 'target_doctype', 'N/A')}\nError: {str(e)}\n{traceback.format_exc()}"
                )
            return ActionResult.error_result(
                error=str(e),
                message=f"Failed to delete document: {str(e)}"
            )

    def validate(self, action: Any) -> List[str]:
        """
        Validate delete document action configuration.

        Args:
            action: ECA Rule Action child document

        Returns:
            List of validation error messages
        """
        errors = []

        # Check for target DocType
        target_doctype = getattr(action, 'target_doctype', None)
        if not target_doctype:
            errors.append("Target DocType is required for Delete Document action")

        # Document values should be valid JSON with 'name' field
        document_values = getattr(action, 'document_values', None)
        if document_values:
            try:
                parsed = json.loads(document_values)
                if 'name' not in parsed and '{{' not in document_values:
                    errors.append("Document Values must contain 'name' field to identify document to delete")
            except json.JSONDecodeError:
                errors.append("Document Values must be valid JSON")

        return errors


# Convenience alias for the main create document handler
DocumentHandler = CreateDocumentHandler


def execute_create_document_action(action: Any, doc: Any, context: Optional[Dict] = None) -> ActionResult:
    """
    Convenience function to execute create document action.

    This is the main entry point for create document action execution.

    Args:
        action: ECA Rule Action child document with document configuration
        doc: The document that triggered the ECA rule
        context: Optional additional context for template rendering

    Returns:
        ActionResult with success/failure status
    """
    handler = CreateDocumentHandler()
    return handler.execute(action, doc, context)


def execute_update_document_action(action: Any, doc: Any, context: Optional[Dict] = None) -> ActionResult:
    """
    Convenience function to execute update document action.

    Args:
        action: ECA Rule Action child document with update configuration
        doc: The document that triggered the ECA rule
        context: Optional additional context for template rendering

    Returns:
        ActionResult with success/failure status
    """
    handler = UpdateDocumentHandler()
    return handler.execute(action, doc, context)


def execute_delete_document_action(action: Any, doc: Any, context: Optional[Dict] = None) -> ActionResult:
    """
    Convenience function to execute delete document action.

    Args:
        action: ECA Rule Action child document with delete configuration
        doc: The document that triggered the ECA rule
        context: Optional additional context for template rendering

    Returns:
        ActionResult with success/failure status
    """
    handler = DeleteDocumentHandler()
    return handler.execute(action, doc, context)


def validate_create_document_action(action: Any) -> List[str]:
    """
    Validate create document action configuration.

    Args:
        action: ECA Rule Action child document

    Returns:
        List of validation error messages
    """
    handler = CreateDocumentHandler()
    return handler.validate(action)


def validate_update_document_action(action: Any) -> List[str]:
    """
    Validate update document action configuration.

    Args:
        action: ECA Rule Action child document

    Returns:
        List of validation error messages
    """
    handler = UpdateDocumentHandler()
    return handler.validate(action)


def validate_delete_document_action(action: Any) -> List[str]:
    """
    Validate delete document action configuration.

    Args:
        action: ECA Rule Action child document

    Returns:
        List of validation error messages
    """
    handler = DeleteDocumentHandler()
    return handler.validate(action)


# Export public API
__all__ = [
    'CreateDocumentHandler',
    'UpdateDocumentHandler',
    'DeleteDocumentHandler',
    'DocumentHandler',  # Alias for CreateDocumentHandler
    'execute_create_document_action',
    'execute_update_document_action',
    'execute_delete_document_action',
    'validate_create_document_action',
    'validate_update_document_action',
    'validate_delete_document_action',
]

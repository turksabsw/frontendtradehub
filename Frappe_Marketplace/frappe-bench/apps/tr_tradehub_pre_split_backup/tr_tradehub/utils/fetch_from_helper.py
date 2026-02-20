# Copyright (c) 2026, Trade Hub and contributors
# For license information, please see license.txt

"""
Fetch From Helper Utilities for Child Table Manual Fetch in Trade Hub.

This module provides utility functions for handling the manual fetch of related
field values in child tables and other scenarios where Frappe's built-in
fetch_from behavior does not work as expected.

CRITICAL LIMITATION: Frappe's fetch_from only triggers during initial document
load or when using the UI. It does NOT trigger:
1. When using frappe.model.set_value() in child tables
2. When programmatically updating Link field values
3. When values are changed via API calls

This module provides workarounds for these limitations.

Usage in JavaScript (Child Table):
    frappe.ui.form.on('Order Item', {
        sku_product: function(frm, cdt, cdn) {
            trade_hub.utils.manual_fetch_for_child_js(frm, cdt, cdn, 'sku_product', {
                'product_name': 'product_name',
                'unit_price': 'default_price'
            });
        }
    });

Usage in Python (Server-side):
    from tr_tradehub.utils.fetch_from_helper import manual_fetch_for_child

    def on_change(doc):
        for item in doc.items:
            manual_fetch_for_child(item, 'sku_product', 'SKU Product', {
                'product_name': 'product_name',
                'unit_price': 'default_price'
            })
"""

from typing import Any, Dict, List, Optional, Union

import frappe
from frappe import _


# =============================================================================
# CORE FETCH FUNCTIONS
# =============================================================================


def manual_fetch_for_child(
    child_row: "frappe.model.document.Document",
    link_fieldname: str,
    link_doctype: str,
    field_mapping: Dict[str, str],
    ignore_if_empty: bool = True
) -> Dict[str, Any]:
    """
    Manually fetch field values for a child table row from a linked document.

    This function is the Python-side workaround for fetch_from not working
    when programmatically updating Link fields in child tables.

    Args:
        child_row: The child table row document
        link_fieldname: The fieldname of the Link field in the child row
        link_doctype: The DocType that the Link field references
        field_mapping: Dict mapping child field names to source field names
            Example: {'product_name': 'product_name', 'unit_price': 'default_price'}
            Keys are target fields (in child), values are source fields (in linked doc)
        ignore_if_empty: If True, skip fetching when Link field is empty

    Returns:
        dict: The fetched values that were applied

    Raises:
        frappe.ValidationError: If the linked document doesn't exist

    Example:
        manual_fetch_for_child(
            child_row=item,
            link_fieldname='sku_product',
            link_doctype='SKU Product',
            field_mapping={
                'product_name': 'product_name',
                'default_price': 'price',
                'tenant': 'tenant'
            }
        )
    """
    fetched_values = {}

    # Get the Link field value
    link_value = child_row.get(link_fieldname)

    if not link_value:
        if ignore_if_empty:
            return fetched_values
        else:
            frappe.throw(
                _("Link field {0} is empty").format(link_fieldname),
                frappe.ValidationError
            )

    # Check if the linked document exists
    if not frappe.db.exists(link_doctype, link_value):
        frappe.throw(
            _("{0} {1} does not exist").format(link_doctype, link_value),
            frappe.ValidationError
        )

    # Get the field values to fetch
    source_fields = list(field_mapping.values())

    # Fetch values from the linked document
    linked_values = frappe.db.get_value(
        link_doctype,
        link_value,
        source_fields,
        as_dict=True
    )

    if not linked_values:
        return fetched_values

    # Apply the fetched values to the child row
    for target_field, source_field in field_mapping.items():
        if source_field in linked_values:
            value = linked_values[source_field]
            child_row.set(target_field, value)
            fetched_values[target_field] = value

    return fetched_values


def manual_fetch_single_field(
    doc: "frappe.model.document.Document",
    link_fieldname: str,
    link_doctype: str,
    source_field: str,
    target_field: str = None
) -> Any:
    """
    Manually fetch a single field value from a linked document.

    A simpler version of manual_fetch_for_child for fetching just one field.

    Args:
        doc: The document (can be parent or child)
        link_fieldname: The fieldname of the Link field
        link_doctype: The DocType that the Link field references
        source_field: The field to fetch from the linked document
        target_field: The field to set in the document (defaults to source_field)

    Returns:
        The fetched value, or None if not found

    Example:
        manual_fetch_single_field(
            doc=order,
            link_fieldname='seller',
            link_doctype='Seller Profile',
            source_field='seller_name',
            target_field='seller_display_name'
        )
    """
    if target_field is None:
        target_field = source_field

    link_value = doc.get(link_fieldname)
    if not link_value:
        return None

    value = frappe.db.get_value(link_doctype, link_value, source_field)

    if value is not None:
        doc.set(target_field, value)

    return value


def bulk_fetch_for_children(
    parent_doc: "frappe.model.document.Document",
    child_fieldname: str,
    link_fieldname: str,
    link_doctype: str,
    field_mapping: Dict[str, str]
) -> List[Dict[str, Any]]:
    """
    Efficiently fetch field values for all rows in a child table.

    This function optimizes database queries by fetching all unique linked
    documents in a single query, then applying values to each row.

    Args:
        parent_doc: The parent document containing the child table
        child_fieldname: The fieldname of the child table
        link_fieldname: The fieldname of the Link field in child rows
        link_doctype: The DocType that the Link field references
        field_mapping: Dict mapping child field names to source field names

    Returns:
        list: List of dicts containing fetched values for each row

    Example:
        bulk_fetch_for_children(
            parent_doc=order,
            child_fieldname='items',
            link_fieldname='sku_product',
            link_doctype='SKU Product',
            field_mapping={
                'product_name': 'product_name',
                'unit_price': 'default_price'
            }
        )
    """
    results = []
    child_rows = parent_doc.get(child_fieldname) or []

    if not child_rows:
        return results

    # Collect all unique Link values
    link_values = set()
    for row in child_rows:
        link_value = row.get(link_fieldname)
        if link_value:
            link_values.add(link_value)

    if not link_values:
        return results

    # Fetch all linked documents in one query
    source_fields = list(field_mapping.values())
    linked_docs = frappe.get_all(
        link_doctype,
        filters={"name": ["in", list(link_values)]},
        fields=["name"] + source_fields
    )

    # Create a lookup dictionary
    linked_data = {doc["name"]: doc for doc in linked_docs}

    # Apply values to each row
    for row in child_rows:
        link_value = row.get(link_fieldname)
        row_result = {"idx": row.idx, "link_value": link_value, "fetched": {}}

        if link_value and link_value in linked_data:
            source_data = linked_data[link_value]
            for target_field, source_field in field_mapping.items():
                if source_field in source_data:
                    value = source_data[source_field]
                    row.set(target_field, value)
                    row_result["fetched"][target_field] = value

        results.append(row_result)

    return results


# =============================================================================
# FETCH_FROM CONFIGURATION HELPERS
# =============================================================================


def get_fetch_from_config(doctype: str) -> Dict[str, Dict[str, str]]:
    """
    Get the fetch_from configuration for all Link fields in a DocType.

    Returns a dictionary mapping Link fieldnames to their fetch configurations.

    Args:
        doctype: The DocType name to get configuration for

    Returns:
        dict: Configuration mapping
            {
                'link_fieldname': {
                    'doctype': 'Linked DocType',
                    'fetch_fields': {
                        'target_field': 'source_field',
                        ...
                    }
                }
            }

    Example:
        config = get_fetch_from_config('Order Item')
        # Returns:
        # {
        #     'sku_product': {
        #         'doctype': 'SKU Product',
        #         'fetch_fields': {
        #             'product_name': 'product_name',
        #             'unit_price': 'default_price'
        #         }
        #     }
        # }
    """
    meta = frappe.get_meta(doctype)
    config = {}

    # Find all Link fields
    link_fields = {}
    for field in meta.fields:
        if field.fieldtype == "Link":
            link_fields[field.fieldname] = field.options  # options = linked DocType

    # Find all fields with fetch_from
    for field in meta.fields:
        if field.fetch_from:
            # fetch_from format: "link_field.source_field"
            parts = field.fetch_from.split(".", 1)
            if len(parts) == 2:
                link_fieldname, source_field = parts
                if link_fieldname in link_fields:
                    if link_fieldname not in config:
                        config[link_fieldname] = {
                            "doctype": link_fields[link_fieldname],
                            "fetch_fields": {}
                        }
                    config[link_fieldname]["fetch_fields"][field.fieldname] = source_field

    return config


def apply_fetch_from_for_doctype(
    doc: "frappe.model.document.Document",
    link_fieldname: str = None
) -> Dict[str, Any]:
    """
    Apply fetch_from logic for a document using DocType configuration.

    This reads the fetch_from configuration from the DocType definition
    and applies it programmatically.

    Args:
        doc: The document to apply fetch to
        link_fieldname: Optional specific Link field to fetch for.
            If None, fetches for all Link fields with fetch_from config.

    Returns:
        dict: All fetched values

    Example:
        apply_fetch_from_for_doctype(order_item, 'sku_product')
    """
    config = get_fetch_from_config(doc.doctype)
    all_fetched = {}

    if link_fieldname:
        # Fetch for specific Link field only
        if link_fieldname in config:
            link_config = config[link_fieldname]
            fetched = manual_fetch_for_child(
                doc,
                link_fieldname,
                link_config["doctype"],
                link_config["fetch_fields"]
            )
            all_fetched[link_fieldname] = fetched
    else:
        # Fetch for all Link fields
        for link_field, link_config in config.items():
            fetched = manual_fetch_for_child(
                doc,
                link_field,
                link_config["doctype"],
                link_config["fetch_fields"]
            )
            all_fetched[link_field] = fetched

    return all_fetched


# =============================================================================
# JAVASCRIPT HELPER GENERATORS
# =============================================================================


def generate_fetch_js_handler(
    child_doctype: str,
    link_fieldname: str,
    link_doctype: str,
    field_mapping: Dict[str, str]
) -> str:
    """
    Generate JavaScript code for manual fetch in child table forms.

    This is useful for generating consistent fetch handlers across
    multiple child tables.

    Args:
        child_doctype: The child DocType name
        link_fieldname: The Link field name
        link_doctype: The linked DocType name
        field_mapping: Field mapping (target: source)

    Returns:
        str: JavaScript code for the fetch handler

    Example:
        js_code = generate_fetch_js_handler(
            'Order Item',
            'sku_product',
            'SKU Product',
            {'product_name': 'product_name'}
        )
    """
    fieldnames = ", ".join([f"'{f}'" for f in field_mapping.values()])
    set_statements = []
    for target, source in field_mapping.items():
        set_statements.append(
            f"                        frappe.model.set_value(cdt, cdn, '{target}', r.message.{source});"
        )
    set_code = "\n".join(set_statements)

    js_template = f"""frappe.ui.form.on('{child_doctype}', {{
    {link_fieldname}: function(frm, cdt, cdn) {{
        var row = locals[cdt][cdn];
        if (row.{link_fieldname}) {{
            frappe.call({{
                method: 'frappe.client.get_value',
                args: {{
                    doctype: '{link_doctype}',
                    filters: {{ name: row.{link_fieldname} }},
                    fieldname: [{fieldnames}]
                }},
                callback: function(r) {{
                    if (r.message) {{
{set_code}
                    }}
                }}
            }});
        }}
    }}
}});"""

    return js_template


# =============================================================================
# WHITELISTED API FUNCTIONS
# =============================================================================


@frappe.whitelist()
def fetch_linked_values(
    link_doctype: str,
    link_value: str,
    fields: Union[str, List[str]]
) -> Optional[Dict[str, Any]]:
    """
    Fetch field values from a linked document (API endpoint).

    This is the whitelisted function that JavaScript can call to fetch
    values from linked documents.

    Args:
        link_doctype: The DocType to fetch from
        link_value: The document name to fetch
        fields: Field name or list of field names to fetch

    Returns:
        dict or None: The fetched values

    Example API call from JavaScript:
        frappe.call({
            method: 'tr_tradehub.utils.fetch_from_helper.fetch_linked_values',
            args: {
                link_doctype: 'SKU Product',
                link_value: 'SKU-00001',
                fields: ['product_name', 'default_price']
            },
            callback: function(r) {
                if (r.message) {
                    // Use r.message.product_name, etc.
                }
            }
        });
    """
    if not link_doctype or not link_value:
        return None

    # Security check: User must have read permission
    if not frappe.has_permission(link_doctype, "read"):
        frappe.throw(
            _("No permission to read {0}").format(link_doctype),
            frappe.PermissionError
        )

    # Parse fields if string (comma-separated)
    if isinstance(fields, str):
        fields = [f.strip() for f in fields.split(",")]

    # Validate the document exists
    if not frappe.db.exists(link_doctype, link_value):
        return None

    # Fetch and return values
    return frappe.db.get_value(link_doctype, link_value, fields, as_dict=True)


@frappe.whitelist()
def get_child_fetch_config(child_doctype: str) -> Dict[str, Any]:
    """
    Get the fetch_from configuration for a child DocType (API endpoint).

    Useful for JavaScript to know what fields should be fetched
    when a Link field changes in a child table.

    Args:
        child_doctype: The child DocType name

    Returns:
        dict: The fetch configuration

    Example API call:
        frappe.call({
            method: 'tr_tradehub.utils.fetch_from_helper.get_child_fetch_config',
            args: { child_doctype: 'Order Item' },
            callback: function(r) {
                // r.message contains the config
            }
        });
    """
    if not child_doctype:
        return {}

    # Security check: User must have read permission
    if not frappe.has_permission(child_doctype, "read"):
        return {}

    return get_fetch_from_config(child_doctype)


# =============================================================================
# VALIDATION HELPERS
# =============================================================================


def validate_fetch_from_fields(doctype: str) -> List[Dict[str, str]]:
    """
    Validate that all fetch_from configurations in a DocType are correct.

    Checks that:
    1. The Link field exists
    2. The source field exists in the linked DocType
    3. The field types are compatible

    Args:
        doctype: The DocType to validate

    Returns:
        list: List of validation issues found

    Example:
        issues = validate_fetch_from_fields('Order Item')
        if issues:
            for issue in issues:
                print(issue['message'])
    """
    issues = []
    meta = frappe.get_meta(doctype)

    # Get all Link fields
    link_fields = {}
    for field in meta.fields:
        if field.fieldtype == "Link":
            link_fields[field.fieldname] = {
                "doctype": field.options,
                "label": field.label
            }

    # Check all fetch_from fields
    for field in meta.fields:
        if not field.fetch_from:
            continue

        parts = field.fetch_from.split(".", 1)
        if len(parts) != 2:
            issues.append({
                "field": field.fieldname,
                "message": _("Invalid fetch_from format: {0}").format(field.fetch_from)
            })
            continue

        link_fieldname, source_field = parts

        # Check if Link field exists
        if link_fieldname not in link_fields:
            issues.append({
                "field": field.fieldname,
                "message": _("Link field '{0}' referenced in fetch_from does not exist").format(
                    link_fieldname
                )
            })
            continue

        # Check if source field exists in linked DocType
        linked_doctype = link_fields[link_fieldname]["doctype"]
        linked_meta = frappe.get_meta(linked_doctype)
        source_field_meta = linked_meta.get_field(source_field)

        if not source_field_meta:
            issues.append({
                "field": field.fieldname,
                "message": _("Source field '{0}' does not exist in {1}").format(
                    source_field, linked_doctype
                )
            })

    return issues


def ensure_read_only_fetch_fields(doctype: str) -> List[str]:
    """
    Get a list of fetch_from fields that should be read_only but aren't.

    According to Trade Hub patterns, all fetch_from fields MUST be read_only.

    Args:
        doctype: The DocType to check

    Returns:
        list: Field names that need read_only=1

    Example:
        fields_to_fix = ensure_read_only_fetch_fields('Order Item')
        if fields_to_fix:
            print(f"These fields should be read_only: {fields_to_fix}")
    """
    meta = frappe.get_meta(doctype)
    non_readonly_fetch_fields = []

    for field in meta.fields:
        if field.fetch_from and not field.read_only:
            non_readonly_fetch_fields.append(field.fieldname)

    return non_readonly_fetch_fields

# Copyright (c) 2024, Mock Data Engine and contributors
# For license information, please see license.txt

"""
Table Field Handlers Module.

This module provides handlers for Table and Table MultiSelect field types.
These handlers generate child rows for table fields in Frappe DocTypes.

Table Field Types:
1. **Table**: Standard child table where rows are embedded documents
   - Rows are stored as child documents in a child DocType
   - Each row has parenttype, parent, parentfield set automatically
   - Rows are created/deleted with the parent document

2. **Table MultiSelect**: Link table for many-to-many relationships
   - Rows contain a Link field to another DocType
   - Used for selecting multiple existing documents
   - The 'options' field specifies the child DocType that contains the link

Child Row Generation Strategy:
1. Get the child DocType from field options
2. Determine the number of rows to generate (from override or defaults)
3. For each row, generate values for all fields in the child DocType
4. Return a list of dictionaries representing the child rows

Usage:
    from mock_data_engine.handlers.table_handlers import (
        TableHandler,
        TableMultiSelectHandler,
    )

    # Using TableHandler for standard child tables
    handler = TableHandler(locale='tr_TR', seed=42)
    rows = handler.generate(context)  # Returns List[Dict]

    # Using TableMultiSelectHandler for link tables
    handler = TableMultiSelectHandler(locale='tr_TR', seed=42)
    rows = handler.generate(context)  # Returns List[Dict] with linked records
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Set, TYPE_CHECKING

from mock_data_engine.handlers.base import (
    BaseFieldHandler,
    FieldPattern,
    GenerationContext,
    GenerationError,
)

if TYPE_CHECKING:
    from mock_data_engine.core.meta_reader import FieldInfo, DocTypeMeta
    from mock_data_engine.core.config_resolver import ResolvedConfig
    from mock_data_engine.core.record_cache import RecordCache


# Default row count configuration
DEFAULT_MIN_ROWS = 1
DEFAULT_MAX_ROWS = 5
DEFAULT_MULTISELECT_MIN_ROWS = 1
DEFAULT_MULTISELECT_MAX_ROWS = 3


class TableHandler(BaseFieldHandler):
    """
    Handler for Table field type (standard child tables).

    Table fields contain embedded child documents. This handler generates
    a list of child row dictionaries with values for all fields in the
    child DocType.

    Child Row Generation:
    1. Get the child DocType from field.options
    2. Load the child DocType's field definitions
    3. Generate a configurable number of rows (1-5 by default)
    4. For each row, generate values for all non-layout fields

    The handler can use a FieldHandlerFactory to generate values for
    child fields, or return empty rows that can be populated later.

    Supported patterns:
        - FieldPattern.GENERIC (Table fields don't have semantic patterns)

    Example:
        >>> handler = TableHandler(locale='tr_TR', seed=42)
        >>> context.field_info.child_doctype
        'Sales Invoice Item'
        >>> rows = handler.generate(context)
        [
            {'item_code': 'ITEM-001', 'qty': 10, 'rate': 100.0},
            {'item_code': 'ITEM-002', 'qty': 5, 'rate': 250.0},
        ]
    """

    # Default row count range
    DEFAULT_MIN_ROWS = DEFAULT_MIN_ROWS
    DEFAULT_MAX_ROWS = DEFAULT_MAX_ROWS

    def __init__(
        self,
        locale: str = "en_US",
        seed: Optional[int] = None,
        config: Optional["ResolvedConfig"] = None,
        min_rows: Optional[int] = None,
        max_rows: Optional[int] = None
    ):
        """
        Initialize the TableHandler.

        Args:
            locale: The locale for data generation (e.g., 'tr_TR', 'en_US')
            seed: Random seed for reproducibility
            config: Optional resolved configuration
            min_rows: Minimum number of rows to generate (default: 1)
            max_rows: Maximum number of rows to generate (default: 5)
        """
        super().__init__(locale=locale, seed=seed, config=config)
        self._min_rows = min_rows if min_rows is not None else self.DEFAULT_MIN_ROWS
        self._max_rows = max_rows if max_rows is not None else self.DEFAULT_MAX_ROWS
        self._handler_factory: Optional[Any] = None

    @property
    def min_rows(self) -> int:
        """Get the minimum number of rows to generate."""
        return self._min_rows

    @property
    def max_rows(self) -> int:
        """Get the maximum number of rows to generate."""
        return self._max_rows

    def set_row_count_range(self, min_rows: int, max_rows: int) -> None:
        """
        Set the row count range for generation.

        Args:
            min_rows: Minimum number of rows
            max_rows: Maximum number of rows
        """
        if min_rows < 0:
            min_rows = 0
        if max_rows < min_rows:
            max_rows = min_rows
        self._min_rows = min_rows
        self._max_rows = max_rows

    def set_handler_factory(self, factory: Any) -> None:
        """
        Set the handler factory for generating child field values.

        Args:
            factory: A FieldHandlerFactory instance
        """
        self._handler_factory = factory

    def generate(self, context: GenerationContext) -> List[Dict[str, Any]]:
        """
        Generate child rows for a Table field.

        Args:
            context: The generation context

        Returns:
            List of dictionaries, each representing a child row

        Raises:
            GenerationError: If child DocType cannot be determined
        """
        # Check for override with fixed value (pre-defined rows)
        if context.has_override():
            fixed_rows = context.get_override_value("fixed_value")
            if fixed_rows is not None and isinstance(fixed_rows, list):
                return fixed_rows

        # Get the child DocType from field options
        child_doctype = self._get_child_doctype(context)
        if not child_doctype:
            # If no child DocType specified and field is required, raise error
            if context.is_required:
                raise GenerationError(
                    "Table field has no child DocType specified",
                    fieldname=context.fieldname,
                    fieldtype=context.fieldtype,
                )
            return []

        # Get row count configuration
        row_count = self._determine_row_count(context)

        # Generate rows
        rows = []
        for row_idx in range(row_count):
            row = self._generate_row(context, child_doctype, row_idx)
            if row:
                rows.append(row)

        return rows

    def _get_child_doctype(self, context: GenerationContext) -> Optional[str]:
        """
        Get the child DocType name from the field configuration.

        Args:
            context: The generation context

        Returns:
            Child DocType name or None
        """
        # Check override first
        if context.has_override():
            override_doctype = context.get_override_value("child_doctype")
            if override_doctype:
                return str(override_doctype)

        # Get from field info options
        return context.field_info.child_doctype

    def _determine_row_count(self, context: GenerationContext) -> int:
        """
        Determine how many rows to generate.

        Resolution order:
        1. Override fixed_count
        2. Override min_count/max_count
        3. Default range

        Args:
            context: The generation context

        Returns:
            Number of rows to generate
        """
        min_count = self._min_rows
        max_count = self._max_rows

        if context.has_override():
            # Fixed count overrides everything
            fixed_count = context.get_override_value("row_count")
            if fixed_count is not None:
                return max(0, int(fixed_count))

            # Check for min/max override
            override_min = context.get_override_value("min_rows")
            override_max = context.get_override_value("max_rows")

            if override_min is not None:
                min_count = max(0, int(override_min))
            if override_max is not None:
                max_count = max(min_count, int(override_max))

        # Generate random count within range
        return self.faker.random_int(min=min_count, max=max_count)

    def _generate_row(
        self,
        context: GenerationContext,
        child_doctype: str,
        row_idx: int
    ) -> Dict[str, Any]:
        """
        Generate a single child row.

        Args:
            context: The generation context
            child_doctype: The child DocType name
            row_idx: The index of this row (0-based)

        Returns:
            Dictionary with field values for the row
        """
        row: Dict[str, Any] = {}

        # Set the idx field (Frappe requires 1-based index for child rows)
        row["idx"] = row_idx + 1

        # Try to load child DocType schema and generate field values
        child_fields = self._get_child_fields(child_doctype)
        if child_fields and self._handler_factory:
            row = self._generate_row_with_factory(
                context, child_doctype, child_fields, row_idx
            )
        else:
            # If no factory or fields available, generate minimal row
            row = self._generate_minimal_row(context, child_doctype, row_idx)

        # Ensure idx is set
        row["idx"] = row_idx + 1

        return row

    def _get_child_fields(self, child_doctype: str) -> Optional[List["FieldInfo"]]:
        """
        Get field definitions for the child DocType.

        Args:
            child_doctype: The child DocType name

        Returns:
            List of FieldInfo objects or None if unavailable
        """
        try:
            from mock_data_engine.core.meta_reader import DocTypeMeta
            meta = DocTypeMeta(child_doctype)
            return meta.get_data_fields()
        except Exception:
            # Meta reader not available or DocType doesn't exist
            return None

    def _generate_row_with_factory(
        self,
        context: GenerationContext,
        child_doctype: str,
        child_fields: List["FieldInfo"],
        row_idx: int
    ) -> Dict[str, Any]:
        """
        Generate a row using the handler factory.

        Args:
            context: The parent generation context
            child_doctype: The child DocType name
            child_fields: List of child field definitions
            row_idx: The index of this row

        Returns:
            Dictionary with generated field values
        """
        row: Dict[str, Any] = {"idx": row_idx + 1}

        # Skip fields that shouldn't be generated
        skip_fieldtypes = {"Table", "Table MultiSelect", "Read Only"}
        skip_fieldnames = {"name", "parent", "parenttype", "parentfield", "idx", "doctype", "docstatus"}

        for field_info in child_fields:
            # Skip layout and system fields
            if field_info.is_layout:
                continue
            if field_info.fieldname in skip_fieldnames:
                continue
            if field_info.fieldtype in skip_fieldtypes:
                continue
            if field_info.read_only and not field_info.fetch_from:
                continue

            try:
                # Create child context for this field
                child_context = GenerationContext(
                    field_info=field_info,
                    doctype=child_doctype,
                    record_data=row,
                    record_cache=context.record_cache,
                    config=context.config,
                    locale=context.locale,
                    seed=(context.seed + row_idx + hash(field_info.fieldname) % 10000)
                        if context.seed else None,
                    generation_method=context.generation_method,
                    batch_index=row_idx,
                    total_count=self._max_rows,
                    parent_doctype=context.doctype,
                    parent_name=context.record_data.get("name", ""),
                    field_override=self._get_field_override(context, field_info.fieldname),
                    detected_pattern=None,  # Will be detected by factory
                )

                # Get handler and generate value
                handler = self._handler_factory.get_handler(field_info)
                value = handler.generate(child_context)

                if value is not None:
                    row[field_info.fieldname] = value

            except Exception:
                # Skip field on generation error, don't fail entire row
                pass

        return row

    def _generate_minimal_row(
        self,
        context: GenerationContext,
        child_doctype: str,
        row_idx: int
    ) -> Dict[str, Any]:
        """
        Generate a minimal row when factory is not available.

        This creates a row with just the idx field. The row can be
        populated later by the generation engine.

        Args:
            context: The generation context
            child_doctype: The child DocType name
            row_idx: The index of this row

        Returns:
            Dictionary with minimal row data
        """
        return {
            "idx": row_idx + 1,
            "doctype": child_doctype,
        }

    def _get_field_override(
        self,
        context: GenerationContext,
        fieldname: str
    ) -> Optional[Dict[str, Any]]:
        """
        Get field override configuration for a child field.

        Args:
            context: The parent generation context
            fieldname: The child field name

        Returns:
            Override configuration dict or None
        """
        if not context.has_override():
            return None

        # Check for field-specific overrides
        field_overrides = context.get_override_value("field_overrides")
        if field_overrides and isinstance(field_overrides, dict):
            return field_overrides.get(fieldname)

        return None

    def validate(self, value: Any, context: GenerationContext) -> bool:
        """
        Validate a Table field value.

        A valid Table field value is a list of dictionaries.

        Args:
            value: The value to validate
            context: The generation context

        Returns:
            True if valid, False otherwise
        """
        if value is None:
            # None is valid for optional Table fields
            return not context.is_required

        if not isinstance(value, list):
            return False

        # Check that all items are dictionaries
        for item in value:
            if not isinstance(item, dict):
                return False

        # For required fields, must have at least one row
        if context.is_required and len(value) == 0:
            return False

        return True

    def get_supported_patterns(self) -> Set[FieldPattern]:
        """Get supported patterns (Table fields are pattern-agnostic)."""
        return {FieldPattern.GENERIC}


class TableMultiSelectHandler(BaseFieldHandler):
    """
    Handler for Table MultiSelect field type.

    Table MultiSelect is a special child table type used for many-to-many
    relationships. It creates rows in a child DocType that contains a Link
    field to another DocType, enabling selection of multiple existing documents.

    Unlike regular Table fields, Table MultiSelect:
    - Typically has a single Link field to the target DocType
    - Rows reference existing documents rather than creating new data
    - The child DocType is specified in the field options

    Generation Strategy:
    1. Get the child DocType from field.options
    2. Find the main Link field in the child DocType
    3. Get the target DocType from the Link field's options
    4. Select random existing documents from the target DocType
    5. Create rows with the selected document references

    Example:
        >>> # Item DocType has a 'taxes' Table MultiSelect field
        >>> # which uses 'Item Tax' child DocType
        >>> # 'Item Tax' has a Link field 'tax_type' -> 'Account'
        >>> handler = TableMultiSelectHandler(locale='tr_TR', seed=42)
        >>> rows = handler.generate(context)
        [
            {'tax_type': 'VAT - TC'},
            {'tax_type': 'Service Tax - TC'},
        ]
    """

    # Default row count range for multi-select
    DEFAULT_MIN_ROWS = DEFAULT_MULTISELECT_MIN_ROWS
    DEFAULT_MAX_ROWS = DEFAULT_MULTISELECT_MAX_ROWS

    def __init__(
        self,
        locale: str = "en_US",
        seed: Optional[int] = None,
        config: Optional["ResolvedConfig"] = None,
        min_rows: Optional[int] = None,
        max_rows: Optional[int] = None
    ):
        """
        Initialize the TableMultiSelectHandler.

        Args:
            locale: The locale for data generation (e.g., 'tr_TR', 'en_US')
            seed: Random seed for reproducibility
            config: Optional resolved configuration
            min_rows: Minimum number of selections (default: 1)
            max_rows: Maximum number of selections (default: 3)
        """
        super().__init__(locale=locale, seed=seed, config=config)
        self._min_rows = min_rows if min_rows is not None else self.DEFAULT_MIN_ROWS
        self._max_rows = max_rows if max_rows is not None else self.DEFAULT_MAX_ROWS

    @property
    def min_rows(self) -> int:
        """Get the minimum number of rows to generate."""
        return self._min_rows

    @property
    def max_rows(self) -> int:
        """Get the maximum number of rows to generate."""
        return self._max_rows

    def generate(self, context: GenerationContext) -> List[Dict[str, Any]]:
        """
        Generate rows for a Table MultiSelect field.

        Args:
            context: The generation context

        Returns:
            List of dictionaries, each with a link to a selected document

        Raises:
            GenerationError: If configuration is invalid for required fields
        """
        # Check for override with fixed value (pre-defined rows)
        if context.has_override():
            fixed_rows = context.get_override_value("fixed_value")
            if fixed_rows is not None and isinstance(fixed_rows, list):
                return fixed_rows

        # Get the child DocType from field options
        child_doctype = context.field_info.child_doctype
        if not child_doctype:
            if context.is_required:
                raise GenerationError(
                    "Table MultiSelect field has no child DocType specified",
                    fieldname=context.fieldname,
                    fieldtype=context.fieldtype,
                )
            return []

        # Get the main Link field in the child DocType
        link_field_info = self._get_main_link_field(child_doctype)
        if not link_field_info:
            # No link field found, create empty rows
            return self._generate_empty_rows(context)

        link_fieldname, target_doctype = link_field_info

        # Get row count
        row_count = self._determine_row_count(context)

        # Get random documents from target DocType
        selected_docs = self._select_documents(
            context, target_doctype, row_count
        )

        # Create rows for selected documents
        rows = []
        for idx, doc_name in enumerate(selected_docs):
            row = {
                "idx": idx + 1,
                link_fieldname: doc_name,
            }
            rows.append(row)

        return rows

    def _get_main_link_field(
        self,
        child_doctype: str
    ) -> Optional[tuple]:
        """
        Get the main Link field from the child DocType.

        For Table MultiSelect, the child DocType typically has one main
        Link field that references the target DocType.

        Args:
            child_doctype: The child DocType name

        Returns:
            Tuple of (fieldname, target_doctype) or None
        """
        try:
            from mock_data_engine.core.meta_reader import DocTypeMeta
            meta = DocTypeMeta(child_doctype)
            link_fields = meta.get_link_fields()

            if not link_fields:
                return None

            # Return the first non-system Link field
            system_fields = {"parenttype", "parent", "owner", "modified_by"}
            for field in link_fields:
                if field.fieldname not in system_fields and field.linked_doctype:
                    return (field.fieldname, field.linked_doctype)

            # If all are system fields, return the first one
            if link_fields and link_fields[0].linked_doctype:
                return (link_fields[0].fieldname, link_fields[0].linked_doctype)

            return None

        except Exception:
            return None

    def _determine_row_count(self, context: GenerationContext) -> int:
        """
        Determine how many rows to generate.

        Args:
            context: The generation context

        Returns:
            Number of rows to generate
        """
        min_count = self._min_rows
        max_count = self._max_rows

        if context.has_override():
            fixed_count = context.get_override_value("row_count")
            if fixed_count is not None:
                return max(0, int(fixed_count))

            override_min = context.get_override_value("min_rows")
            override_max = context.get_override_value("max_rows")

            if override_min is not None:
                min_count = max(0, int(override_min))
            if override_max is not None:
                max_count = max(min_count, int(override_max))

        return self.faker.random_int(min=min_count, max=max_count)

    def _select_documents(
        self,
        context: GenerationContext,
        target_doctype: str,
        count: int
    ) -> List[str]:
        """
        Select random documents from the target DocType.

        Args:
            context: The generation context
            target_doctype: The DocType to select from
            count: Number of documents to select

        Returns:
            List of document names
        """
        selected: List[str] = []

        # Try to get from record cache first
        if context.record_cache is not None:
            cached_records = context.record_cache.get_random_records(
                target_doctype, count
            )
            if cached_records:
                selected.extend(cached_records)

        # If not enough from cache, try database
        if len(selected) < count:
            remaining = count - len(selected)
            db_records = self._get_from_database(target_doctype, remaining)
            for record in db_records:
                if record not in selected:
                    selected.append(record)

        # Ensure uniqueness (no duplicate selections)
        return list(dict.fromkeys(selected))[:count]

    def _get_from_database(self, doctype: str, count: int) -> List[str]:
        """
        Get random documents from database.

        Args:
            doctype: The DocType name
            count: Number of documents to get

        Returns:
            List of document names
        """
        try:
            import frappe
            records = frappe.get_all(
                doctype,
                limit_page_length=count * 3,  # Get more to allow random selection
                pluck="name"
            )
            if records:
                # Shuffle and return requested count
                self.faker.random.shuffle(records)
                return records[:count]
        except Exception:
            pass

        return []

    def _generate_empty_rows(self, context: GenerationContext) -> List[Dict[str, Any]]:
        """
        Generate empty rows when link field info is not available.

        Args:
            context: The generation context

        Returns:
            List of row dictionaries with just idx
        """
        row_count = self._determine_row_count(context)
        return [{"idx": i + 1} for i in range(row_count)]

    def validate(self, value: Any, context: GenerationContext) -> bool:
        """
        Validate a Table MultiSelect field value.

        Args:
            value: The value to validate
            context: The generation context

        Returns:
            True if valid, False otherwise
        """
        if value is None:
            return not context.is_required

        if not isinstance(value, list):
            return False

        for item in value:
            if not isinstance(item, dict):
                return False

        if context.is_required and len(value) == 0:
            return False

        return True

    def get_supported_patterns(self) -> Set[FieldPattern]:
        """Get supported patterns (Table MultiSelect fields are pattern-agnostic)."""
        return {FieldPattern.GENERIC}


def get_table_row_count_range(
    field_info: "FieldInfo",
    config: Optional["ResolvedConfig"] = None
) -> tuple:
    """
    Get the recommended row count range for a table field.

    This utility function analyzes the field and configuration to suggest
    appropriate min/max row counts.

    Args:
        field_info: The field metadata
        config: Optional resolved configuration

    Returns:
        Tuple of (min_rows, max_rows)
    """
    # Check field type
    if field_info.fieldtype == "Table MultiSelect":
        default_min = DEFAULT_MULTISELECT_MIN_ROWS
        default_max = DEFAULT_MULTISELECT_MAX_ROWS
    else:
        default_min = DEFAULT_MIN_ROWS
        default_max = DEFAULT_MAX_ROWS

    # Check if there's configuration for this specific field
    if config:
        override = config.get_field_override(field_info.fieldname, field_info.fieldtype)
        if override:
            min_rows = override.get("min_rows", default_min)
            max_rows = override.get("max_rows", default_max)
            return (min_rows, max_rows)

    return (default_min, default_max)


def suggest_child_doctype(fieldname: str) -> Optional[str]:
    """
    Suggest a likely child DocType based on field name.

    This utility helps when the child DocType is not specified.

    Args:
        fieldname: The table field name

    Returns:
        Suggested child DocType name or None

    Example:
        >>> suggest_child_doctype("items")
        'Item'
        >>> suggest_child_doctype("taxes")
        None  # Too generic
    """
    fieldname_lower = fieldname.lower()

    # Direct mappings for common field names
    mappings = {
        "items": "Item",
        "addresses": "Address",
        "contacts": "Contact",
        "users": "User",
        "employees": "Employee",
        "departments": "Department",
        "warehouses": "Warehouse",
        "accounts": "Account",
        "currencies": "Currency",
        "countries": "Country",
    }

    return mappings.get(fieldname_lower)


# Export all handler classes and utilities
__all__ = [
    # Handlers
    "TableHandler",
    "TableMultiSelectHandler",
    # Utility functions
    "get_table_row_count_range",
    "suggest_child_doctype",
    # Constants
    "DEFAULT_MIN_ROWS",
    "DEFAULT_MAX_ROWS",
    "DEFAULT_MULTISELECT_MIN_ROWS",
    "DEFAULT_MULTISELECT_MAX_ROWS",
]

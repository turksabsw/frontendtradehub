# Copyright (c) 2024, Mock Data Engine and contributors
# For license information, please see license.txt

"""
DocType Schema Introspection Module.

This module provides the DocTypeMeta class for extracting schema information
from Frappe DocTypes using frappe.get_meta(). It serves as the foundation
for the mock data generation engine by providing structured access to:

- Field definitions (name, type, options, constraints)
- Link field relationships (dependencies)
- Child table definitions
- Dynamic link fields
- Naming configuration (autoname, naming_rule, naming_series)

Usage:
    meta = DocTypeMeta("Customer")
    fields = meta.get_data_fields()
    link_fields = meta.get_link_fields()
    schema = meta.to_dict()
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, TYPE_CHECKING

if TYPE_CHECKING:
    pass

# Field types that are layout/UI only and should be skipped during generation
LAYOUT_FIELD_TYPES = frozenset({
    "Section Break",
    "Column Break",
    "Tab Break",
    "Fold",
    "Heading",
    "HTML",
    "Image",
    "Button",
})

# Field types that represent relationships to other DocTypes
LINK_FIELD_TYPES = frozenset({
    "Link",
    "Dynamic Link",
})

# Field types that represent child tables
TABLE_FIELD_TYPES = frozenset({
    "Table",
    "Table MultiSelect",
})

# Field types that store data (non-layout, non-computed)
DATA_FIELD_TYPES = frozenset({
    "Data",
    "Small Text",
    "Text",
    "Long Text",
    "Text Editor",
    "Code",
    "HTML Editor",
    "Markdown Editor",
    "Int",
    "Float",
    "Currency",
    "Percent",
    "Date",
    "Datetime",
    "Time",
    "Duration",
    "Select",
    "Link",
    "Dynamic Link",
    "Table",
    "Table MultiSelect",
    "Check",
    "Attach",
    "Attach Image",
    "Color",
    "Geolocation",
    "Signature",
    "JSON",
    "Barcode",
    "Read Only",
    "Password",
    "Rating",
    "Icon",
    "Autocomplete",
    "Phone",
})


@dataclass
class FieldInfo:
    """
    Structured representation of a DocType field.

    Attributes:
        fieldname: The programmatic name of the field
        fieldtype: The Frappe field type (Data, Link, Select, etc.)
        label: The human-readable label
        options: Field-specific options (e.g., DocType name for Link fields, newline-separated values for Select)
        reqd: Whether the field is required (mandatory)
        unique: Whether the field must be unique across all records
        default: The default value for the field
        length: Maximum length for string fields
        precision: Decimal precision for numeric fields
        read_only: Whether the field is read-only
        hidden: Whether the field is hidden
        set_only_once: Whether the field can only be set on creation
        allow_on_submit: Whether the field can be modified after submission
        in_list_view: Whether the field appears in list view
        in_standard_filter: Whether the field appears in standard filters
        mandatory_depends_on: Expression for conditional mandatory
        read_only_depends_on: Expression for conditional read-only
        depends_on: Expression for conditional visibility
        fetch_from: Field to fetch value from (for linked fields)
        fetch_if_empty: Whether to fetch only when field is empty
    """
    fieldname: str
    fieldtype: str
    label: str = ""
    options: str = ""
    reqd: bool = False
    unique: bool = False
    default: Optional[str] = None
    length: int = 0
    precision: str = ""
    read_only: bool = False
    hidden: bool = False
    set_only_once: bool = False
    allow_on_submit: bool = False
    in_list_view: bool = False
    in_standard_filter: bool = False
    mandatory_depends_on: str = ""
    read_only_depends_on: str = ""
    depends_on: str = ""
    fetch_from: str = ""
    fetch_if_empty: bool = False

    @property
    def is_layout(self) -> bool:
        """Check if this is a layout/UI field (not data)."""
        return self.fieldtype in LAYOUT_FIELD_TYPES

    @property
    def is_link(self) -> bool:
        """Check if this is a link field (Link or Dynamic Link)."""
        return self.fieldtype in LINK_FIELD_TYPES

    @property
    def is_table(self) -> bool:
        """Check if this is a child table field."""
        return self.fieldtype in TABLE_FIELD_TYPES

    @property
    def is_required(self) -> bool:
        """Check if this field is required."""
        return bool(self.reqd)

    @property
    def linked_doctype(self) -> Optional[str]:
        """Get the linked DocType name for Link fields."""
        if self.fieldtype == "Link" and self.options:
            return self.options
        return None

    @property
    def child_doctype(self) -> Optional[str]:
        """Get the child DocType name for Table fields."""
        if self.fieldtype in TABLE_FIELD_TYPES and self.options:
            return self.options
        return None

    @property
    def select_options(self) -> List[str]:
        """Get the list of options for Select fields."""
        if self.fieldtype == "Select" and self.options:
            return [opt.strip() for opt in self.options.split("\n") if opt.strip()]
        return []

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "fieldname": self.fieldname,
            "fieldtype": self.fieldtype,
            "label": self.label,
            "options": self.options,
            "reqd": self.reqd,
            "unique": self.unique,
            "default": self.default,
            "length": self.length,
            "precision": self.precision,
            "read_only": self.read_only,
            "hidden": self.hidden,
            "set_only_once": self.set_only_once,
            "fetch_from": self.fetch_from,
            "fetch_if_empty": self.fetch_if_empty,
        }

    @classmethod
    def from_frappe_field(cls, df: Any) -> "FieldInfo":
        """
        Create FieldInfo from a Frappe DocField object.

        Args:
            df: A Frappe DocField object from meta.fields

        Returns:
            FieldInfo instance with extracted field data
        """
        return cls(
            fieldname=getattr(df, "fieldname", ""),
            fieldtype=getattr(df, "fieldtype", ""),
            label=getattr(df, "label", "") or "",
            options=getattr(df, "options", "") or "",
            reqd=bool(getattr(df, "reqd", 0)),
            unique=bool(getattr(df, "unique", 0)),
            default=getattr(df, "default", None),
            length=int(getattr(df, "length", 0) or 0),
            precision=getattr(df, "precision", "") or "",
            read_only=bool(getattr(df, "read_only", 0)),
            hidden=bool(getattr(df, "hidden", 0)),
            set_only_once=bool(getattr(df, "set_only_once", 0)),
            allow_on_submit=bool(getattr(df, "allow_on_submit", 0)),
            in_list_view=bool(getattr(df, "in_list_view", 0)),
            in_standard_filter=bool(getattr(df, "in_standard_filter", 0)),
            mandatory_depends_on=getattr(df, "mandatory_depends_on", "") or "",
            read_only_depends_on=getattr(df, "read_only_depends_on", "") or "",
            depends_on=getattr(df, "depends_on", "") or "",
            fetch_from=getattr(df, "fetch_from", "") or "",
            fetch_if_empty=bool(getattr(df, "fetch_if_empty", 0)),
        )


@dataclass
class NamingConfig:
    """
    Configuration for how documents are named.

    Attributes:
        autoname: The autoname pattern (e.g., "naming_series:", "field:customer_name", "hash")
        naming_rule: The naming rule type
        name_case: Case transformation for names
        issingle: Whether this is a Single DocType
        istable: Whether this is a child table DocType
    """
    autoname: str = ""
    naming_rule: str = ""
    name_case: str = ""
    issingle: bool = False
    istable: bool = False

    @property
    def uses_naming_series(self) -> bool:
        """Check if DocType uses naming series."""
        return self.autoname.startswith("naming_series:")

    @property
    def uses_field_naming(self) -> bool:
        """Check if DocType uses a field for naming."""
        return self.autoname.startswith("field:")

    @property
    def naming_field(self) -> Optional[str]:
        """Get the field name used for naming, if applicable."""
        if self.uses_field_naming:
            return self.autoname.split(":", 1)[1]
        return None

    @property
    def uses_hash(self) -> bool:
        """Check if DocType uses hash-based naming."""
        return self.autoname == "hash"

    @property
    def uses_prompt(self) -> bool:
        """Check if DocType requires user input for naming."""
        return self.autoname == "prompt" or self.naming_rule == "Set by user"

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "autoname": self.autoname,
            "naming_rule": self.naming_rule,
            "name_case": self.name_case,
            "issingle": self.issingle,
            "istable": self.istable,
            "uses_naming_series": self.uses_naming_series,
            "uses_field_naming": self.uses_field_naming,
            "naming_field": self.naming_field,
            "uses_hash": self.uses_hash,
            "uses_prompt": self.uses_prompt,
        }


class DocTypeMeta:
    """
    DocType schema introspection class.

    This class wraps frappe.get_meta() to provide structured access to
    DocType schema information for mock data generation.

    Attributes:
        doctype: The name of the DocType

    Example:
        >>> meta = DocTypeMeta("Customer")
        >>> meta.doctype
        'Customer'
        >>> fields = meta.get_data_fields()
        >>> link_fields = meta.get_link_fields()
        >>> schema = meta.to_dict()
    """

    def __init__(self, doctype: str, use_cache: bool = True):
        """
        Initialize DocTypeMeta for a given DocType.

        Args:
            doctype: The name of the DocType to introspect
            use_cache: Whether to use Frappe's meta cache (default True)
        """
        self.doctype = doctype
        self._use_cache = use_cache
        self._meta: Optional[Any] = None
        self._fields: Optional[List[FieldInfo]] = None
        self._naming_config: Optional[NamingConfig] = None

    @property
    def meta(self) -> Any:
        """
        Get the Frappe Meta object (lazy loaded).

        Returns:
            Frappe Meta object for the DocType

        Raises:
            ImportError: If frappe is not available
            Exception: If DocType does not exist
        """
        if self._meta is None:
            try:
                import frappe
                self._meta = frappe.get_meta(self.doctype, cached=self._use_cache)
            except ImportError:
                raise ImportError(
                    "frappe module not available. "
                    "DocTypeMeta requires Frappe Framework to be installed."
                )
        return self._meta

    @property
    def fields(self) -> List[FieldInfo]:
        """
        Get all fields as FieldInfo objects (cached).

        Returns:
            List of FieldInfo objects for all fields in the DocType
        """
        if self._fields is None:
            self._fields = [
                FieldInfo.from_frappe_field(df)
                for df in self.meta.fields
            ]
        return self._fields

    @property
    def naming_config(self) -> NamingConfig:
        """
        Get the naming configuration for this DocType.

        Returns:
            NamingConfig object with naming details
        """
        if self._naming_config is None:
            self._naming_config = NamingConfig(
                autoname=getattr(self.meta, "autoname", "") or "",
                naming_rule=getattr(self.meta, "naming_rule", "") or "",
                name_case=getattr(self.meta, "name_case", "") or "",
                issingle=bool(getattr(self.meta, "issingle", 0)),
                istable=bool(getattr(self.meta, "istable", 0)),
            )
        return self._naming_config

    def get_data_fields(self, include_hidden: bool = False) -> List[FieldInfo]:
        """
        Get only data fields (excluding layout fields).

        Args:
            include_hidden: Whether to include hidden fields (default False)

        Returns:
            List of FieldInfo objects for data fields
        """
        return [
            f for f in self.fields
            if not f.is_layout
            and (include_hidden or not f.hidden)
        ]

    def get_required_fields(self) -> List[FieldInfo]:
        """
        Get all required (mandatory) fields.

        Returns:
            List of FieldInfo objects for required fields
        """
        return [f for f in self.get_data_fields() if f.is_required]

    def get_unique_fields(self) -> List[FieldInfo]:
        """
        Get all fields with unique constraint.

        Returns:
            List of FieldInfo objects for unique fields
        """
        return [f for f in self.get_data_fields() if f.unique]

    def get_link_fields(self) -> List[FieldInfo]:
        """
        Get all Link fields (references to other DocTypes).

        Returns:
            List of FieldInfo objects for Link fields
        """
        return [f for f in self.get_data_fields() if f.fieldtype == "Link"]

    def get_dynamic_link_fields(self) -> List[FieldInfo]:
        """
        Get all Dynamic Link fields.

        Returns:
            List of FieldInfo objects for Dynamic Link fields
        """
        return [f for f in self.get_data_fields() if f.fieldtype == "Dynamic Link"]

    def get_table_fields(self) -> List[FieldInfo]:
        """
        Get all Table fields (child tables).

        Returns:
            List of FieldInfo objects for Table fields
        """
        return [f for f in self.get_data_fields() if f.is_table]

    def get_select_fields(self) -> List[FieldInfo]:
        """
        Get all Select fields.

        Returns:
            List of FieldInfo objects for Select fields
        """
        return [f for f in self.get_data_fields() if f.fieldtype == "Select"]

    def get_fields_by_type(self, fieldtype: str) -> List[FieldInfo]:
        """
        Get all fields of a specific type.

        Args:
            fieldtype: The field type to filter by (e.g., "Data", "Int", "Currency")

        Returns:
            List of FieldInfo objects matching the field type
        """
        return [f for f in self.get_data_fields() if f.fieldtype == fieldtype]

    def get_field(self, fieldname: str) -> Optional[FieldInfo]:
        """
        Get a specific field by name.

        Args:
            fieldname: The programmatic name of the field

        Returns:
            FieldInfo object if found, None otherwise
        """
        for f in self.fields:
            if f.fieldname == fieldname:
                return f
        return None

    def get_dependencies(self) -> Set[str]:
        """
        Get all DocTypes that this DocType depends on (via Link fields).

        This is useful for dependency resolution during mock data generation.

        Returns:
            Set of DocType names that this DocType links to
        """
        dependencies = set()

        # Add Link field targets
        for f in self.get_link_fields():
            if f.linked_doctype:
                dependencies.add(f.linked_doctype)

        # Note: Dynamic Links are not included as their target is dynamic

        return dependencies

    def get_child_doctypes(self) -> Set[str]:
        """
        Get all child DocTypes (from Table fields).

        Returns:
            Set of child DocType names
        """
        children = set()
        for f in self.get_table_fields():
            if f.child_doctype:
                children.add(f.child_doctype)
        return children

    def get_fields_with_fetch(self) -> List[FieldInfo]:
        """
        Get all fields that fetch values from linked documents.

        Returns:
            List of FieldInfo objects that have fetch_from set
        """
        return [f for f in self.get_data_fields() if f.fetch_from]

    def has_field(self, fieldname: str) -> bool:
        """
        Check if DocType has a specific field.

        Args:
            fieldname: The programmatic name of the field

        Returns:
            True if field exists, False otherwise
        """
        return any(f.fieldname == fieldname for f in self.fields)

    @property
    def is_single(self) -> bool:
        """Check if this is a Single DocType (only one record exists)."""
        return self.naming_config.issingle

    @property
    def is_child_table(self) -> bool:
        """Check if this is a child table DocType."""
        return self.naming_config.istable

    @property
    def is_submittable(self) -> bool:
        """Check if this DocType is submittable."""
        return bool(getattr(self.meta, "is_submittable", 0))

    @property
    def module(self) -> str:
        """Get the module this DocType belongs to."""
        return getattr(self.meta, "module", "") or ""

    @property
    def title_field(self) -> Optional[str]:
        """Get the title field name if set."""
        return getattr(self.meta, "title_field", None)

    @property
    def search_fields(self) -> List[str]:
        """Get the search field names."""
        search_fields = getattr(self.meta, "search_fields", "") or ""
        return [f.strip() for f in search_fields.split(",") if f.strip()]

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert the DocType schema to a dictionary.

        This provides a complete snapshot of the DocType schema suitable
        for serialization, caching, or passing to generators.

        Returns:
            Dictionary containing:
                - name: DocType name
                - module: Module name
                - fields: List of field dictionaries
                - link_fields: List of link field info
                - table_fields: List of table field info
                - naming: Naming configuration
                - meta: Additional metadata
        """
        return {
            "name": self.doctype,
            "module": self.module,
            "fields": [
                f.to_dict() for f in self.get_data_fields(include_hidden=True)
            ],
            "required_fields": [f.fieldname for f in self.get_required_fields()],
            "unique_fields": [f.fieldname for f in self.get_unique_fields()],
            "link_fields": [
                {"fieldname": f.fieldname, "options": f.linked_doctype}
                for f in self.get_link_fields()
            ],
            "dynamic_link_fields": [
                {"fieldname": f.fieldname, "options": f.options}
                for f in self.get_dynamic_link_fields()
            ],
            "table_fields": [
                {"fieldname": f.fieldname, "options": f.child_doctype}
                for f in self.get_table_fields()
            ],
            "select_fields": [
                {"fieldname": f.fieldname, "options": f.select_options}
                for f in self.get_select_fields()
            ],
            "naming": self.naming_config.to_dict(),
            "dependencies": list(self.get_dependencies()),
            "child_doctypes": list(self.get_child_doctypes()),
            "meta": {
                "is_single": self.is_single,
                "is_child_table": self.is_child_table,
                "is_submittable": self.is_submittable,
                "title_field": self.title_field,
                "search_fields": self.search_fields,
            }
        }

    def __repr__(self) -> str:
        """String representation of DocTypeMeta."""
        return f"DocTypeMeta(doctype='{self.doctype}')"

    @staticmethod
    def get_all_doctypes(app: Optional[str] = None) -> List[str]:
        """
        Get all DocType names, optionally filtered by app.

        Args:
            app: Optional app name to filter by

        Returns:
            List of DocType names
        """
        try:
            import frappe
            filters = {}
            if app:
                # Get modules belonging to the app
                modules = frappe.get_all(
                    "Module Def",
                    filters={"app_name": app},
                    pluck="name"
                )
                if modules:
                    filters["module"] = ("in", modules)

            return frappe.get_all("DocType", filters=filters, pluck="name")
        except ImportError:
            raise ImportError(
                "frappe module not available. "
                "get_all_doctypes requires Frappe Framework to be installed."
            )

    @staticmethod
    def get_installed_apps() -> List[str]:
        """
        Get all installed apps in the current Frappe site.

        Returns:
            List of installed app names
        """
        try:
            import frappe
            return frappe.get_installed_apps()
        except ImportError:
            raise ImportError(
                "frappe module not available. "
                "get_installed_apps requires Frappe Framework to be installed."
            )


def extract_doctype_schema(doctype: str) -> Dict[str, Any]:
    """
    Extract complete schema for a DocType.

    This is a convenience function that creates a DocTypeMeta instance
    and returns its dictionary representation.

    Args:
        doctype: The name of the DocType

    Returns:
        Dictionary containing the complete DocType schema

    Example:
        >>> schema = extract_doctype_schema("Customer")
        >>> print(schema["name"])
        'Customer'
        >>> print(len(schema["fields"]))
        42
    """
    meta = DocTypeMeta(doctype)
    return meta.to_dict()

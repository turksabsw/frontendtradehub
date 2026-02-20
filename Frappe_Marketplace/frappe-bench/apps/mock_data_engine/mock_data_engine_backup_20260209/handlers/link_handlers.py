# Copyright (c) 2024, Mock Data Engine and contributors
# For license information, please see license.txt

"""
Link Field Handlers Module.

This module provides handlers for Link and Dynamic Link field types.
These handlers implement resolution strategies for referencing other DocTypes.

Link Resolution Strategies:
1. **Cache Lookup**: First attempt to get a random record from the RecordCache
2. **Database Fallback**: If cache is empty, attempt to fetch from database
3. **Dependency Creation**: If no records exist, indicate that dependency needs creation
4. **Circular Dependency Handling**: Return None for fields in circular dependency cycles
   (these will be backfilled in a second pass)

Handlers in this module:
- LinkHandler: Handler for Link field type (static reference to another DocType)
- DynamicLinkHandler: Handler for Dynamic Link field type (dynamic target DocType)

Usage:
    from mock_data_engine.mock_data_engine.handlers.link_handlers import (
        LinkHandler,
        DynamicLinkHandler,
    )

    # Using LinkHandler
    handler = LinkHandler(locale='tr_TR', seed=42)
    value = handler.generate(context)  # Returns a document name from the linked DocType

    # Using DynamicLinkHandler
    handler = DynamicLinkHandler(locale='tr_TR', seed=42)
    value = handler.generate(context)  # Returns a document name from the dynamic target
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional, Set, TYPE_CHECKING

from mock_data_engine.mock_data_engine.handlers.base import (
    BaseFieldHandler,
    FieldPattern,
    GenerationContext,
    GenerationError,
)

if TYPE_CHECKING:
    from mock_data_engine.mock_data_engine.core.config_resolver import ResolvedConfig
    from mock_data_engine.mock_data_engine.core.record_cache import RecordCache


class LinkResolutionStrategy(Enum):
    """
    Enumeration of strategies for resolving Link field values.

    These strategies define how the handler attempts to find a valid
    document reference for Link fields.
    """

    # Use only the record cache (fastest, no database access)
    CACHE_ONLY = "cache_only"

    # Use cache first, then fall back to database
    CACHE_THEN_DATABASE = "cache_then_database"

    # Use database first, then fall back to cache
    DATABASE_THEN_CACHE = "database_then_cache"

    # Use only the database (most accurate for existing data)
    DATABASE_ONLY = "database_only"

    # Create a new record if none exists (triggers dependency creation)
    CREATE_IF_MISSING = "create_if_missing"

    # Return None for missing records (useful for optional fields)
    NONE_IF_MISSING = "none_if_missing"


class LinkHandler(BaseFieldHandler):
    """
    Handler for Link field type.

    Link fields reference documents in other DocTypes. This handler
    resolves Link field values by looking up existing records from
    the record cache or database.

    Resolution Order:
    1. Check for override with fixed value
    2. Check if field is in a circular dependency (return None for backfill)
    3. Try to get a random record from the RecordCache
    4. Fall back to database lookup if cache is empty
    5. Return None if no records exist (field will be backfilled or left empty)

    Supported patterns:
        - FieldPattern.GENERIC (Link fields don't have semantic patterns)

    Example:
        >>> handler = LinkHandler(locale='tr_TR', seed=42)
        >>> # Assuming Customer records exist in cache
        >>> handler.generate(context)
        'CUST-00001'
    """

    # Default resolution strategy
    DEFAULT_STRATEGY = LinkResolutionStrategy.CACHE_THEN_DATABASE

    def __init__(
        self,
        locale: str = "en_US",
        seed: Optional[int] = None,
        config: Optional["ResolvedConfig"] = None,
        strategy: Optional[LinkResolutionStrategy] = None
    ):
        """
        Initialize the LinkHandler.

        Args:
            locale: The locale for data generation (e.g., 'tr_TR', 'en_US')
            seed: Random seed for reproducibility
            config: Optional resolved configuration
            strategy: Link resolution strategy (defaults to CACHE_THEN_DATABASE)
        """
        super().__init__(locale=locale, seed=seed, config=config)
        self._strategy = strategy or self.DEFAULT_STRATEGY

    @property
    def strategy(self) -> LinkResolutionStrategy:
        """Get the current resolution strategy."""
        return self._strategy

    def set_strategy(self, strategy: LinkResolutionStrategy) -> None:
        """
        Set the resolution strategy.

        Args:
            strategy: The new resolution strategy
        """
        self._strategy = strategy

    def generate(self, context: GenerationContext) -> Optional[str]:
        """
        Generate a value for a Link field.

        This method attempts to resolve a valid document reference
        using the configured resolution strategy.

        Args:
            context: The generation context

        Returns:
            A document name from the linked DocType, or None if no valid
            reference could be found

        Raises:
            GenerationError: If required field cannot be resolved and
                            no fallback strategy applies
        """
        # Check for override with fixed value
        if context.has_override():
            fixed_value = context.get_override_value("fixed_value")
            if fixed_value is not None:
                return str(fixed_value)

            # Check for specific target document override
            target_name = context.get_override_value("target_name")
            if target_name is not None:
                return str(target_name)

        # Get the linked DocType from field options
        linked_doctype = context.linked_doctype
        if not linked_doctype:
            # Invalid Link field configuration - no target DocType specified
            if context.is_required:
                raise GenerationError(
                    "Link field has no target DocType specified",
                    fieldname=context.fieldname,
                    fieldtype=context.fieldtype,
                )
            return None

        # Check for override with specific resolution strategy
        if context.has_override():
            strategy_name = context.get_override_value("resolution_strategy")
            if strategy_name:
                try:
                    strategy = LinkResolutionStrategy(strategy_name)
                except ValueError:
                    strategy = self._strategy
            else:
                strategy = self._strategy
        else:
            strategy = self._strategy

        # Attempt resolution based on strategy
        result = self._resolve_link(context, linked_doctype, strategy)

        # Handle required fields with no result
        if result is None and context.is_required:
            # For required fields, add to pending backfills if cache is available
            if context.record_cache is not None:
                context.record_cache.add_pending_backfill(
                    doctype=context.doctype,
                    name="",  # Will be set when record is created
                    fieldname=context.fieldname,
                    target_doctype=linked_doctype,
                )

        return result

    def _resolve_link(
        self,
        context: GenerationContext,
        linked_doctype: str,
        strategy: LinkResolutionStrategy
    ) -> Optional[str]:
        """
        Resolve a Link field value using the specified strategy.

        Args:
            context: The generation context
            linked_doctype: The target DocType name
            strategy: The resolution strategy to use

        Returns:
            A document name or None
        """
        if strategy == LinkResolutionStrategy.CACHE_ONLY:
            return self._resolve_from_cache(context, linked_doctype)

        elif strategy == LinkResolutionStrategy.DATABASE_ONLY:
            return self._resolve_from_database(linked_doctype)

        elif strategy == LinkResolutionStrategy.CACHE_THEN_DATABASE:
            result = self._resolve_from_cache(context, linked_doctype)
            if result is None:
                result = self._resolve_from_database(linked_doctype)
            return result

        elif strategy == LinkResolutionStrategy.DATABASE_THEN_CACHE:
            result = self._resolve_from_database(linked_doctype)
            if result is None:
                result = self._resolve_from_cache(context, linked_doctype)
            return result

        elif strategy == LinkResolutionStrategy.CREATE_IF_MISSING:
            result = self._resolve_from_cache(context, linked_doctype)
            if result is None:
                result = self._resolve_from_database(linked_doctype)
            if result is None:
                # Mark for dependency creation
                # This will be handled by the generation engine
                return None

        elif strategy == LinkResolutionStrategy.NONE_IF_MISSING:
            result = self._resolve_from_cache(context, linked_doctype)
            if result is None:
                result = self._resolve_from_database(linked_doctype)
            return result

        return None

    def _resolve_from_cache(
        self,
        context: GenerationContext,
        linked_doctype: str
    ) -> Optional[str]:
        """
        Resolve a Link field value from the record cache.

        Args:
            context: The generation context
            linked_doctype: The target DocType name

        Returns:
            A random document name from cache, or None if cache is empty
        """
        if context.record_cache is None:
            return None

        return context.record_cache.get_random_record(linked_doctype)

    def _resolve_from_database(self, linked_doctype: str) -> Optional[str]:
        """
        Resolve a Link field value from the database.

        Args:
            linked_doctype: The target DocType name

        Returns:
            A random document name from database, or None if no records exist
        """
        try:
            import frappe
            # Get a random document from the database
            # Using random ordering for variety
            records = frappe.get_all(
                linked_doctype,
                limit_page_length=100,
                pluck="name"
            )
            if records:
                return self.faker.random_element(records)
        except (ImportError, Exception):
            # Frappe not available or database error
            pass

        return None

    def validate(self, value: Any, context: GenerationContext) -> bool:
        """
        Validate a Link field value.

        A valid Link field value is a non-empty string that references
        an existing document.

        Args:
            value: The value to validate
            context: The generation context

        Returns:
            True if valid, False otherwise
        """
        if value is None:
            # None is valid for optional Link fields
            return not context.is_required

        if not isinstance(value, str):
            return False

        if not value.strip():
            return not context.is_required

        # For strict validation, could check if document exists
        # But this is typically done by Frappe during save
        return True

    def get_supported_patterns(self) -> Set[FieldPattern]:
        """Get supported patterns (Link fields are pattern-agnostic)."""
        return {FieldPattern.GENERIC}


class DynamicLinkHandler(BaseFieldHandler):
    """
    Handler for Dynamic Link field type.

    Dynamic Link fields reference documents where the target DocType
    is determined by another field in the same document. The field
    specified in the 'options' attribute of the Dynamic Link field
    contains the name of the target DocType.

    For example, if a Dynamic Link field has `options="link_doctype"`,
    then the value of the `link_doctype` field determines which DocType
    the Dynamic Link references.

    Resolution Order:
    1. Check for override with fixed value
    2. Get the target DocType from the linked field in record_data
    3. If target DocType is known, use LinkHandler resolution logic
    4. If target DocType is unknown, return None (cannot resolve)

    Supported patterns:
        - FieldPattern.GENERIC (Dynamic Link fields don't have semantic patterns)

    Example:
        >>> handler = DynamicLinkHandler(locale='tr_TR', seed=42)
        >>> # Assuming context has link_doctype='Customer' in record_data
        >>> handler.generate(context)
        'CUST-00001'
    """

    # Default resolution strategy (same as LinkHandler)
    DEFAULT_STRATEGY = LinkResolutionStrategy.CACHE_THEN_DATABASE

    def __init__(
        self,
        locale: str = "en_US",
        seed: Optional[int] = None,
        config: Optional["ResolvedConfig"] = None,
        strategy: Optional[LinkResolutionStrategy] = None
    ):
        """
        Initialize the DynamicLinkHandler.

        Args:
            locale: The locale for data generation (e.g., 'tr_TR', 'en_US')
            seed: Random seed for reproducibility
            config: Optional resolved configuration
            strategy: Link resolution strategy (defaults to CACHE_THEN_DATABASE)
        """
        super().__init__(locale=locale, seed=seed, config=config)
        self._strategy = strategy or self.DEFAULT_STRATEGY
        # Create a LinkHandler for actual resolution
        self._link_handler = LinkHandler(
            locale=locale,
            seed=seed,
            config=config,
            strategy=self._strategy
        )

    @property
    def strategy(self) -> LinkResolutionStrategy:
        """Get the current resolution strategy."""
        return self._strategy

    def set_strategy(self, strategy: LinkResolutionStrategy) -> None:
        """
        Set the resolution strategy.

        Args:
            strategy: The new resolution strategy
        """
        self._strategy = strategy
        self._link_handler.set_strategy(strategy)

    def generate(self, context: GenerationContext) -> Optional[str]:
        """
        Generate a value for a Dynamic Link field.

        This method determines the target DocType from another field
        in the same record, then resolves a valid document reference.

        Args:
            context: The generation context

        Returns:
            A document name from the dynamic target DocType, or None if
            no valid reference could be found

        Raises:
            GenerationError: If required field cannot be resolved and
                            no fallback strategy applies
        """
        # Check for override with fixed value
        if context.has_override():
            fixed_value = context.get_override_value("fixed_value")
            if fixed_value is not None:
                return str(fixed_value)

            # Check for specific target document override
            target_name = context.get_override_value("target_name")
            if target_name is not None:
                return str(target_name)

        # Get the field that specifies the target DocType
        # The 'options' field contains the name of the field that holds the DocType
        doctype_field = context.options
        if not doctype_field:
            # Invalid Dynamic Link configuration
            if context.is_required:
                raise GenerationError(
                    "Dynamic Link field has no doctype field specified in options",
                    fieldname=context.fieldname,
                    fieldtype=context.fieldtype,
                )
            return None

        # Get the target DocType from record_data
        target_doctype = context.get_existing_value(doctype_field)

        # If target DocType is not yet determined, check for override
        if not target_doctype and context.has_override():
            target_doctype = context.get_override_value("target_doctype")

        # If still no target DocType, we cannot resolve
        if not target_doctype:
            # For required fields, this might indicate a dependency issue
            # The target DocType field should be generated first
            if context.is_required:
                # Add to pending backfills if cache available
                if context.record_cache is not None:
                    context.record_cache.add_pending_backfill(
                        doctype=context.doctype,
                        name="",  # Will be set when record is created
                        fieldname=context.fieldname,
                        target_doctype="",  # Unknown at this point
                    )
            return None

        # Now resolve using the LinkHandler logic
        # We need to create a modified context with the target DocType
        return self._resolve_dynamic_link(context, target_doctype)

    def _resolve_dynamic_link(
        self,
        context: GenerationContext,
        target_doctype: str
    ) -> Optional[str]:
        """
        Resolve a Dynamic Link field value for a specific target DocType.

        Args:
            context: The generation context
            target_doctype: The target DocType name

        Returns:
            A document name or None
        """
        # Use the resolution strategy
        strategy = self._strategy

        # Check for override strategy
        if context.has_override():
            strategy_name = context.get_override_value("resolution_strategy")
            if strategy_name:
                try:
                    strategy = LinkResolutionStrategy(strategy_name)
                except ValueError:
                    pass

        # Attempt resolution
        result = None

        if strategy == LinkResolutionStrategy.CACHE_ONLY:
            result = self._resolve_from_cache(context, target_doctype)

        elif strategy == LinkResolutionStrategy.DATABASE_ONLY:
            result = self._resolve_from_database(target_doctype)

        elif strategy == LinkResolutionStrategy.CACHE_THEN_DATABASE:
            result = self._resolve_from_cache(context, target_doctype)
            if result is None:
                result = self._resolve_from_database(target_doctype)

        elif strategy == LinkResolutionStrategy.DATABASE_THEN_CACHE:
            result = self._resolve_from_database(target_doctype)
            if result is None:
                result = self._resolve_from_cache(context, target_doctype)

        elif strategy in (LinkResolutionStrategy.CREATE_IF_MISSING,
                         LinkResolutionStrategy.NONE_IF_MISSING):
            result = self._resolve_from_cache(context, target_doctype)
            if result is None:
                result = self._resolve_from_database(target_doctype)

        # Handle required fields with no result
        if result is None and context.is_required:
            if context.record_cache is not None:
                context.record_cache.add_pending_backfill(
                    doctype=context.doctype,
                    name="",
                    fieldname=context.fieldname,
                    target_doctype=target_doctype,
                )

        return result

    def _resolve_from_cache(
        self,
        context: GenerationContext,
        target_doctype: str
    ) -> Optional[str]:
        """
        Resolve a Dynamic Link field value from the record cache.

        Args:
            context: The generation context
            target_doctype: The target DocType name

        Returns:
            A random document name from cache, or None if cache is empty
        """
        if context.record_cache is None:
            return None

        return context.record_cache.get_random_record(target_doctype)

    def _resolve_from_database(self, target_doctype: str) -> Optional[str]:
        """
        Resolve a Dynamic Link field value from the database.

        Args:
            target_doctype: The target DocType name

        Returns:
            A random document name from database, or None if no records exist
        """
        try:
            import frappe
            records = frappe.get_all(
                target_doctype,
                limit_page_length=100,
                pluck="name"
            )
            if records:
                return self.faker.random_element(records)
        except (ImportError, Exception):
            pass

        return None

    def generate_with_doctype(
        self,
        context: GenerationContext,
        target_doctype: str
    ) -> Optional[str]:
        """
        Generate a Dynamic Link value for a known target DocType.

        This is useful when the target DocType is known externally
        (e.g., from configuration) and doesn't need to be resolved
        from record_data.

        Args:
            context: The generation context
            target_doctype: The known target DocType name

        Returns:
            A document name from the target DocType
        """
        return self._resolve_dynamic_link(context, target_doctype)

    def validate(self, value: Any, context: GenerationContext) -> bool:
        """
        Validate a Dynamic Link field value.

        A valid Dynamic Link field value is a non-empty string that
        references an existing document (when combined with the
        target DocType field).

        Args:
            value: The value to validate
            context: The generation context

        Returns:
            True if valid, False otherwise
        """
        if value is None:
            return not context.is_required

        if not isinstance(value, str):
            return False

        if not value.strip():
            return not context.is_required

        return True

    def get_supported_patterns(self) -> Set[FieldPattern]:
        """Get supported patterns (Dynamic Link fields are pattern-agnostic)."""
        return {FieldPattern.GENERIC}


def get_common_link_doctypes() -> List[str]:
    """
    Get a list of commonly linked DocTypes for testing/fallback.

    These are standard Frappe/ERPNext DocTypes that are frequently
    used as Link field targets.

    Returns:
        List of common DocType names
    """
    return [
        # Core
        "User",
        "Role",
        "DocType",
        # Setup
        "Company",
        "Currency",
        "Country",
        # CRM/Selling
        "Customer",
        "Lead",
        "Contact",
        "Address",
        # Stock
        "Item",
        "Warehouse",
        "Item Group",
        # Buying
        "Supplier",
        # Accounts
        "Account",
        "Cost Center",
        # HR
        "Employee",
        "Department",
    ]


def suggest_link_doctype_for_field(fieldname: str) -> Optional[str]:
    """
    Suggest a likely target DocType based on field name.

    This is useful for generating realistic Dynamic Link values
    when the target DocType field hasn't been generated yet.

    Args:
        fieldname: The field name to analyze

    Returns:
        A suggested DocType name, or None if no suggestion

    Example:
        >>> suggest_link_doctype_for_field("customer")
        'Customer'
        >>> suggest_link_doctype_for_field("party")
        'Customer'  # Could also be Supplier
    """
    fieldname_lower = fieldname.lower()

    # Direct mappings
    direct_mappings = {
        "customer": "Customer",
        "customer_name": "Customer",
        "supplier": "Supplier",
        "supplier_name": "Supplier",
        "employee": "Employee",
        "employee_id": "Employee",
        "employee_name": "Employee",
        "item": "Item",
        "item_code": "Item",
        "item_name": "Item",
        "company": "Company",
        "company_name": "Company",
        "warehouse": "Warehouse",
        "user": "User",
        "owner": "User",
        "modified_by": "User",
        "account": "Account",
        "cost_center": "Cost Center",
        "department": "Department",
        "lead": "Lead",
        "contact": "Contact",
        "address": "Address",
        "currency": "Currency",
        "country": "Country",
        "item_group": "Item Group",
    }

    if fieldname_lower in direct_mappings:
        return direct_mappings[fieldname_lower]

    # Partial matches
    partial_mappings = [
        ("customer", "Customer"),
        ("supplier", "Supplier"),
        ("employee", "Employee"),
        ("warehouse", "Warehouse"),
        ("company", "Company"),
        ("account", "Account"),
        ("item", "Item"),
        ("user", "User"),
        ("party", "Customer"),  # Party is often Customer
    ]

    for pattern, doctype in partial_mappings:
        if pattern in fieldname_lower:
            return doctype

    return None


# Export all handler classes and utilities
__all__ = [
    # Handlers
    "LinkHandler",
    "DynamicLinkHandler",
    # Resolution strategy enum
    "LinkResolutionStrategy",
    # Utility functions
    "get_common_link_doctypes",
    "suggest_link_doctype_for_field",
]

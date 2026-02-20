# Copyright (c) 2024, Mock Data Engine and contributors
# For license information, please see license.txt

"""
Field Handler Factory Module.

This module provides the FieldHandlerFactory class for creating appropriate
field handlers based on field type and detected patterns.

The factory implements:
1. Handler registration for all Frappe field types
2. Pattern-based handler selection for semantic field names
3. Lazy handler instantiation for efficiency
4. Handler caching to reuse instances

Usage:
    from mock_data_engine.handlers.factory import FieldHandlerFactory

    # Create factory with locale and seed
    factory = FieldHandlerFactory(locale='tr_TR', seed=42)

    # Get handler for a field
    handler = factory.get_handler(field_info)

    # Or use the convenience function
    handler = get_handler_for_field(field_info, locale='tr_TR')
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Set, Type, TYPE_CHECKING

from mock_data_engine.handlers.base import (
    BaseFieldHandler,
    FieldPattern,
    GenerationContext,
    PatternDetector,
)

if TYPE_CHECKING:
    from mock_data_engine.core.meta_reader import FieldInfo
    from mock_data_engine.core.config_resolver import ResolvedConfig


class DefaultHandler(BaseFieldHandler):
    """
    Default handler for unregistered field types.

    This handler is used when no specific handler is registered for a field type.
    It generates simple default values based on the field type category.
    """

    def generate(self, context: GenerationContext) -> Any:
        """
        Generate a default value based on field type.

        Args:
            context: The generation context

        Returns:
            A simple default value
        """
        fieldtype = context.fieldtype

        # Text-like fields
        if fieldtype in ("Data", "Small Text", "Text", "Long Text"):
            max_length = min(context.max_length, 50)
            return self.faker.text(max_nb_chars=max_length)

        # Numeric fields
        if fieldtype in ("Int",):
            return self.faker.random_int(min=1, max=1000)

        if fieldtype in ("Float", "Currency", "Percent"):
            return round(self.faker.pyfloat(min_value=0, max_value=10000), 2)

        # Date/Time fields
        if fieldtype == "Date":
            return self.faker.date()

        if fieldtype == "Datetime":
            return self.faker.date_time().isoformat()

        if fieldtype == "Time":
            return self.faker.time()

        # Boolean
        if fieldtype == "Check":
            return self.faker.boolean()

        # Select - use first option or empty
        if fieldtype == "Select":
            options = context.select_options
            if options:
                return self.faker.random_element(options)
            return ""

        # Default fallback
        return ""


class FieldHandlerFactory:
    """
    Factory for creating field type handlers.

    This factory manages handler registration and instantiation for all
    Frappe field types. It supports:

    1. **Type-based handlers**: One handler per Frappe field type
    2. **Pattern-based handlers**: Specialized handlers for detected patterns
    3. **Handler caching**: Reuses handler instances for efficiency
    4. **Lazy registration**: Handlers can be registered on-demand

    The factory follows this resolution order:
    1. Field override handler (from profile/settings)
    2. Pattern-specific handler (if pattern detected and handler registered)
    3. Field type handler (based on Frappe field type)
    4. Default handler (fallback)

    Attributes:
        locale: The locale for data generation
        seed: Random seed for reproducibility
        config: Optional resolved configuration

    Example:
        >>> factory = FieldHandlerFactory(locale='tr_TR', seed=42)
        >>> handler = factory.get_handler(field_info)
        >>> value = handler.generate(context)
    """

    # Default handler registrations (field type -> handler class)
    # These will be populated as handlers are implemented
    _default_handlers: Dict[str, Type[BaseFieldHandler]] = {}

    # Pattern handler registrations (pattern -> handler class)
    _pattern_handlers: Dict[FieldPattern, Type[BaseFieldHandler]] = {}

    def __init__(
        self,
        locale: str = "en_US",
        seed: Optional[int] = None,
        config: Optional["ResolvedConfig"] = None
    ):
        """
        Initialize the FieldHandlerFactory.

        Args:
            locale: The locale for data generation (e.g., 'tr_TR', 'en_US')
            seed: Random seed for reproducibility
            config: Optional resolved configuration
        """
        self._locale = locale
        self._seed = seed
        self._config = config

        # Pattern detector for field name analysis
        self._pattern_detector = PatternDetector(locale=locale)

        # Handler instance cache (handler_key -> handler instance)
        self._handler_cache: Dict[str, BaseFieldHandler] = {}

        # Type handler registrations (can be overridden per-instance)
        self._type_handlers: Dict[str, Type[BaseFieldHandler]] = dict(
            FieldHandlerFactory._default_handlers
        )

        # Pattern handler registrations (can be overridden per-instance)
        self._pattern_handlers_instance: Dict[FieldPattern, Type[BaseFieldHandler]] = dict(
            FieldHandlerFactory._pattern_handlers
        )

        # Default handler for unregistered types
        self._default_handler_class: Type[BaseFieldHandler] = DefaultHandler

    @property
    def locale(self) -> str:
        """Get the locale for data generation."""
        return self._locale

    @property
    def seed(self) -> Optional[int]:
        """Get the random seed."""
        return self._seed

    @property
    def config(self) -> Optional["ResolvedConfig"]:
        """Get the resolved configuration."""
        return self._config

    @property
    def pattern_detector(self) -> PatternDetector:
        """Get the pattern detector."""
        return self._pattern_detector

    def set_locale(self, locale: str) -> None:
        """
        Set the locale and update pattern detector.

        Args:
            locale: The new locale string
        """
        self._locale = locale
        self._pattern_detector.set_locale(locale)
        # Clear cache as handlers may need different locale
        self._handler_cache.clear()

    def register_handler(
        self,
        fieldtype: str,
        handler_class: Type[BaseFieldHandler]
    ) -> None:
        """
        Register a handler for a field type.

        Args:
            fieldtype: The Frappe field type (e.g., 'Data', 'Int', 'Link')
            handler_class: The handler class to use for this type

        Example:
            >>> factory.register_handler('Data', DataHandler)
        """
        self._type_handlers[fieldtype] = handler_class
        # Invalidate cache for this type
        self._invalidate_cache_for_type(fieldtype)

    def register_pattern_handler(
        self,
        pattern: FieldPattern,
        handler_class: Type[BaseFieldHandler]
    ) -> None:
        """
        Register a handler for a semantic pattern.

        Pattern handlers take precedence over type handlers when
        a pattern is detected in the field name.

        Args:
            pattern: The FieldPattern to handle
            handler_class: The handler class to use

        Example:
            >>> factory.register_pattern_handler(FieldPattern.EMAIL, EmailHandler)
        """
        self._pattern_handlers_instance[pattern] = handler_class
        # Invalidate cache for this pattern
        self._invalidate_cache_for_pattern(pattern)

    def unregister_handler(self, fieldtype: str) -> bool:
        """
        Unregister a handler for a field type.

        Args:
            fieldtype: The field type to unregister

        Returns:
            True if handler was unregistered, False if not found
        """
        if fieldtype in self._type_handlers:
            del self._type_handlers[fieldtype]
            self._invalidate_cache_for_type(fieldtype)
            return True
        return False

    def get_handler(
        self,
        field_info: "FieldInfo",
        override: Optional[Dict[str, Any]] = None
    ) -> BaseFieldHandler:
        """
        Get the appropriate handler for a field.

        This method resolves the handler using the following priority:
        1. Override-specified handler (from profile/settings)
        2. Pattern-specific handler (if pattern detected)
        3. Field type handler (based on Frappe field type)
        4. Default handler

        Args:
            field_info: The field metadata
            override: Optional override configuration for the field

        Returns:
            The appropriate BaseFieldHandler instance

        Example:
            >>> handler = factory.get_handler(email_field)
            >>> handler.__class__.__name__
            'EmailHandler'  # If pattern detected and handler registered
        """
        fieldtype = field_info.fieldtype
        fieldname = field_info.fieldname

        # Check for override-specified handler
        if override:
            override_handler = self._get_override_handler(override)
            if override_handler:
                return override_handler

        # For Select/Link fields, skip pattern detection - use type handler directly
        if fieldtype in ('Select', 'Link'):
            handler = self._get_type_handler(fieldtype)
            if handler:
                return handler

        # Detect pattern in field name
        pattern = self._pattern_detector.detect(fieldname, fieldtype, self._locale)

        # Try pattern-specific handler first
        if pattern != FieldPattern.GENERIC:
            handler = self._get_pattern_handler(pattern)
            if handler:
                return handler

        # Fall back to type-specific handler
        handler = self._get_type_handler(fieldtype)
        if handler:
            return handler

        # Final fallback to default handler
        return self._get_default_handler()

    def get_handler_for_context(
        self,
        context: GenerationContext
    ) -> BaseFieldHandler:
        """
        Get a handler for a generation context.

        This is a convenience method that extracts field info and override
        from the context and calls get_handler().

        Args:
            context: The generation context

        Returns:
            The appropriate handler for the context
        """
        return self.get_handler(
            field_info=context.field_info,
            override=context.field_override
        )

    def _get_override_handler(
        self,
        override: Dict[str, Any]
    ) -> Optional[BaseFieldHandler]:
        """
        Get handler based on override configuration.

        Args:
            override: The override configuration dict

        Returns:
            Handler instance if override specifies one, None otherwise
        """
        generator_type = override.get("generator_type")

        if not generator_type:
            return None

        # Map override generator types to handlers
        # These will be implemented in subsequent subtasks
        override_mapping = {
            "Fixed Value": "_create_fixed_value_handler",
            "Faker": "_create_faker_override_handler",
            "Range": "_create_range_handler",
            "Pattern": "_create_pattern_override_handler",
            "Select Options": "_create_select_options_handler",
            "Turkish Validator": "_create_turkish_validator_handler",
            "LLM": "_create_llm_handler",
            "Custom Function": "_create_custom_function_handler",
        }

        handler_method_name = override_mapping.get(generator_type)
        if handler_method_name and hasattr(self, handler_method_name):
            handler_method = getattr(self, handler_method_name)
            return handler_method(override)

        return None

    def _get_pattern_handler(
        self,
        pattern: FieldPattern
    ) -> Optional[BaseFieldHandler]:
        """
        Get handler for a detected pattern.

        Args:
            pattern: The detected FieldPattern

        Returns:
            Handler instance if registered for pattern, None otherwise
        """
        handler_class = self._pattern_handlers_instance.get(pattern)
        if handler_class is None:
            return None

        # Use cached instance if available
        cache_key = f"pattern:{pattern.value}"
        if cache_key in self._handler_cache:
            return self._handler_cache[cache_key]

        # Create and cache handler instance
        handler = handler_class(
            locale=self._locale,
            seed=self._seed,
            config=self._config
        )
        self._handler_cache[cache_key] = handler
        return handler

    def _get_type_handler(self, fieldtype: str) -> Optional[BaseFieldHandler]:
        """
        Get handler for a field type.

        Args:
            fieldtype: The Frappe field type

        Returns:
            Handler instance if registered for type, None otherwise
        """
        handler_class = self._type_handlers.get(fieldtype)
        if handler_class is None:
            return None

        # Use cached instance if available
        cache_key = f"type:{fieldtype}"
        if cache_key in self._handler_cache:
            return self._handler_cache[cache_key]

        # Create and cache handler instance
        handler = handler_class(
            locale=self._locale,
            seed=self._seed,
            config=self._config
        )
        self._handler_cache[cache_key] = handler
        return handler

    def _get_default_handler(self) -> BaseFieldHandler:
        """
        Get the default handler for unregistered types.

        Returns:
            The default handler instance
        """
        cache_key = "default"
        if cache_key in self._handler_cache:
            return self._handler_cache[cache_key]

        handler = self._default_handler_class(
            locale=self._locale,
            seed=self._seed,
            config=self._config
        )
        self._handler_cache[cache_key] = handler
        return handler

    def _invalidate_cache_for_type(self, fieldtype: str) -> None:
        """
        Invalidate cache for a specific field type.

        Args:
            fieldtype: The field type to invalidate
        """
        cache_key = f"type:{fieldtype}"
        if cache_key in self._handler_cache:
            del self._handler_cache[cache_key]

    def _invalidate_cache_for_pattern(self, pattern: FieldPattern) -> None:
        """
        Invalidate cache for a specific pattern.

        Args:
            pattern: The pattern to invalidate
        """
        cache_key = f"pattern:{pattern.value}"
        if cache_key in self._handler_cache:
            del self._handler_cache[cache_key]

    def clear_cache(self) -> None:
        """Clear all cached handler instances."""
        self._handler_cache.clear()

    def get_registered_types(self) -> Set[str]:
        """
        Get all registered field types.

        Returns:
            Set of field type names with registered handlers
        """
        return set(self._type_handlers.keys())

    def get_registered_patterns(self) -> Set[FieldPattern]:
        """
        Get all registered patterns.

        Returns:
            Set of FieldPattern values with registered handlers
        """
        return set(self._pattern_handlers_instance.keys())

    def has_handler_for_type(self, fieldtype: str) -> bool:
        """
        Check if a handler is registered for a field type.

        Args:
            fieldtype: The field type to check

        Returns:
            True if a handler is registered
        """
        return fieldtype in self._type_handlers

    def has_handler_for_pattern(self, pattern: FieldPattern) -> bool:
        """
        Check if a handler is registered for a pattern.

        Args:
            pattern: The pattern to check

        Returns:
            True if a handler is registered
        """
        return pattern in self._pattern_handlers_instance

    def detect_pattern(
        self,
        fieldname: str,
        fieldtype: str
    ) -> FieldPattern:
        """
        Detect the semantic pattern for a field.

        Args:
            fieldname: The field name
            fieldtype: The field type

        Returns:
            The detected FieldPattern
        """
        return self._pattern_detector.detect(fieldname, fieldtype, self._locale)

    def create_context(
        self,
        field_info: "FieldInfo",
        doctype: str,
        record_data: Optional[Dict[str, Any]] = None,
        record_cache: Optional[Any] = None,
        batch_index: int = 0,
        total_count: int = 1,
        parent_doctype: Optional[str] = None,
        parent_name: Optional[str] = None,
        field_override: Optional[Dict[str, Any]] = None
    ) -> GenerationContext:
        """
        Create a GenerationContext for a field.

        This convenience method creates a fully-populated GenerationContext
        with pattern detection already performed.

        Args:
            field_info: The field metadata
            doctype: The DocType being generated
            record_data: Already-generated field values for this record
            record_cache: Cache of previously created records
            batch_index: Current index within the batch
            total_count: Total records being generated
            parent_doctype: Parent DocType for child tables
            parent_name: Parent document name for child tables
            field_override: Optional override configuration

        Returns:
            A fully-populated GenerationContext
        """
        # Detect pattern for the field
        detected_pattern = self.detect_pattern(
            field_info.fieldname,
            field_info.fieldtype
        )

        return GenerationContext(
            field_info=field_info,
            doctype=doctype,
            record_data=record_data or {},
            record_cache=record_cache,
            config=self._config,
            locale=self._locale,
            seed=self._seed,
            generation_method="Faker",  # Default, can be updated
            batch_index=batch_index,
            total_count=total_count,
            parent_doctype=parent_doctype,
            parent_name=parent_name,
            field_override=field_override,
            detected_pattern=detected_pattern,
        )

    @classmethod
    def register_default_handler(
        cls,
        fieldtype: str,
        handler_class: Type[BaseFieldHandler]
    ) -> None:
        """
        Register a default handler for a field type (class-level).

        This registration applies to all factory instances.

        Args:
            fieldtype: The Frappe field type
            handler_class: The handler class to use
        """
        cls._default_handlers[fieldtype] = handler_class

    @classmethod
    def register_default_pattern_handler(
        cls,
        pattern: FieldPattern,
        handler_class: Type[BaseFieldHandler]
    ) -> None:
        """
        Register a default pattern handler (class-level).

        This registration applies to all factory instances.

        Args:
            pattern: The FieldPattern to handle
            handler_class: The handler class to use
        """
        cls._pattern_handlers[pattern] = handler_class

    @classmethod
    def get_default_handlers(cls) -> Dict[str, Type[BaseFieldHandler]]:
        """
        Get all default handler registrations.

        Returns:
            Dict mapping field types to handler classes
        """
        return dict(cls._default_handlers)

    @classmethod
    def get_default_pattern_handlers(cls) -> Dict[FieldPattern, Type[BaseFieldHandler]]:
        """
        Get all default pattern handler registrations.

        Returns:
            Dict mapping patterns to handler classes
        """
        return dict(cls._pattern_handlers)

    def __repr__(self) -> str:
        """String representation of the factory."""
        return (
            f"FieldHandlerFactory("
            f"locale='{self._locale}', "
            f"seed={self._seed}, "
            f"registered_types={len(self._type_handlers)}, "
            f"registered_patterns={len(self._pattern_handlers_instance)}"
            f")"
        )


def get_handler_for_field(
    field_info: "FieldInfo",
    locale: str = "en_US",
    seed: Optional[int] = None,
    config: Optional["ResolvedConfig"] = None,
    override: Optional[Dict[str, Any]] = None
) -> BaseFieldHandler:
    """
    Convenience function to get a handler for a field.

    This creates a factory instance and returns the appropriate handler.
    For repeated handler lookups, it's more efficient to create a factory
    and reuse it.

    Args:
        field_info: The field metadata
        locale: The locale for data generation
        seed: Random seed for reproducibility
        config: Optional resolved configuration
        override: Optional override configuration

    Returns:
        The appropriate handler for the field

    Example:
        >>> handler = get_handler_for_field(email_field, locale='tr_TR')
        >>> value = handler.generate(context)
    """
    factory = FieldHandlerFactory(locale=locale, seed=seed, config=config)
    return factory.get_handler(field_info, override=override)


def create_handler_factory(
    locale: str = "en_US",
    seed: Optional[int] = None,
    config: Optional["ResolvedConfig"] = None
) -> FieldHandlerFactory:
    """
    Factory function to create a FieldHandlerFactory.

    Args:
        locale: The locale for data generation
        seed: Random seed for reproducibility
        config: Optional resolved configuration

    Returns:
        A new FieldHandlerFactory instance

    Example:
        >>> factory = create_handler_factory(locale='tr_TR', seed=42)
        >>> handler = factory.get_handler(field_info)
    """
    return FieldHandlerFactory(locale=locale, seed=seed, config=config)


# Register default handlers for all Frappe field types
# These will use DefaultHandler until specific handlers are implemented
_FRAPPE_FIELD_TYPES = [
    # Text fields
    "Data",
    "Small Text",
    "Text",
    "Long Text",
    "Text Editor",
    "Code",
    "HTML Editor",
    "Markdown Editor",

    # Numeric fields
    "Int",
    "Float",
    "Currency",
    "Percent",
    "Rating",

    # Date/Time fields
    "Date",
    "Datetime",
    "Time",
    "Duration",

    # Selection fields
    "Select",
    "Check",

    # Link fields
    "Link",
    "Dynamic Link",
    "Table",
    "Table MultiSelect",

    # Attachment fields
    "Attach",
    "Attach Image",

    # Special fields
    "Color",
    "Geolocation",
    "Signature",
    "JSON",
    "Barcode",
    "Read Only",
    "Password",
    "Icon",
    "Autocomplete",
    "Phone",
]

# Register DefaultHandler for all types initially
# Specific handlers will be registered in subsequent subtasks
for _fieldtype in _FRAPPE_FIELD_TYPES:
    FieldHandlerFactory.register_default_handler(_fieldtype, DefaultHandler)

# Import and register specific handlers
# Data handlers (subtask-6-2)
try:
    from mock_data_engine.handlers.data_handlers import (
        DataHandler,
        EmailHandler,
        PhoneHandler,
        MobileHandler,
        URLHandler,
        WebsiteHandler,
        FirstNameHandler,
        LastNameHandler,
        FullNameHandler,
        CompanyHandler,
        AddressHandler,
        StreetHandler,
        CityHandler,
        StateHandler,
        CountryHandler,
        PostalCodeHandler,
        TitleHandler,
        CodeHandler,
    )

    # Register DataHandler for Data field type
    FieldHandlerFactory.register_default_handler("Data", DataHandler)

    # Register pattern handlers for semantic pattern detection
    FieldHandlerFactory.register_default_pattern_handler(FieldPattern.EMAIL, EmailHandler)
    FieldHandlerFactory.register_default_pattern_handler(FieldPattern.PHONE, PhoneHandler)
    FieldHandlerFactory.register_default_pattern_handler(FieldPattern.MOBILE, MobileHandler)
    FieldHandlerFactory.register_default_pattern_handler(FieldPattern.URL, URLHandler)
    FieldHandlerFactory.register_default_pattern_handler(FieldPattern.WEBSITE, WebsiteHandler)
    FieldHandlerFactory.register_default_pattern_handler(FieldPattern.FIRST_NAME, FirstNameHandler)
    FieldHandlerFactory.register_default_pattern_handler(FieldPattern.LAST_NAME, LastNameHandler)
    FieldHandlerFactory.register_default_pattern_handler(FieldPattern.FULL_NAME, FullNameHandler)
    FieldHandlerFactory.register_default_pattern_handler(FieldPattern.COMPANY, CompanyHandler)
    FieldHandlerFactory.register_default_pattern_handler(FieldPattern.COMPANY_NAME, CompanyHandler)
    FieldHandlerFactory.register_default_pattern_handler(FieldPattern.ADDRESS, AddressHandler)
    FieldHandlerFactory.register_default_pattern_handler(FieldPattern.STREET, StreetHandler)
    FieldHandlerFactory.register_default_pattern_handler(FieldPattern.CITY, CityHandler)
    FieldHandlerFactory.register_default_pattern_handler(FieldPattern.STATE, StateHandler)
    FieldHandlerFactory.register_default_pattern_handler(FieldPattern.COUNTRY, CountryHandler)
    FieldHandlerFactory.register_default_pattern_handler(FieldPattern.POSTAL_CODE, PostalCodeHandler)
    FieldHandlerFactory.register_default_pattern_handler(FieldPattern.ZIP_CODE, PostalCodeHandler)
    FieldHandlerFactory.register_default_pattern_handler(FieldPattern.TITLE, TitleHandler)
    FieldHandlerFactory.register_default_pattern_handler(FieldPattern.CODE, CodeHandler)
    FieldHandlerFactory.register_default_pattern_handler(FieldPattern.SKU, CodeHandler)
    FieldHandlerFactory.register_default_pattern_handler(FieldPattern.SERIAL, CodeHandler)
    FieldHandlerFactory.register_default_pattern_handler(FieldPattern.REFERENCE, CodeHandler)
except ImportError:
    # Data handlers not yet available, use DefaultHandler
    pass

# Numeric handlers (subtask-6-3)
try:
    from mock_data_engine.handlers.numeric_handlers import (
        IntHandler,
        FloatHandler,
        CurrencyHandler,
        PercentHandler,
        RatingHandler,
        QuantityHandler,
        AmountHandler,
        PriceHandler,
        CostHandler,
        TaxHandler,
        DiscountHandler,
    )

    # Register handlers for Frappe field types
    FieldHandlerFactory.register_default_handler("Int", IntHandler)
    FieldHandlerFactory.register_default_handler("Float", FloatHandler)
    FieldHandlerFactory.register_default_handler("Currency", CurrencyHandler)
    FieldHandlerFactory.register_default_handler("Percent", PercentHandler)
    FieldHandlerFactory.register_default_handler("Rating", RatingHandler)

    # Register pattern handlers for numeric semantic patterns
    FieldHandlerFactory.register_default_pattern_handler(FieldPattern.QUANTITY, QuantityHandler)
    FieldHandlerFactory.register_default_pattern_handler(FieldPattern.QTY, QuantityHandler)
    FieldHandlerFactory.register_default_pattern_handler(FieldPattern.COUNT, IntHandler)
    FieldHandlerFactory.register_default_pattern_handler(FieldPattern.AMOUNT, AmountHandler)
    FieldHandlerFactory.register_default_pattern_handler(FieldPattern.PRICE, PriceHandler)
    FieldHandlerFactory.register_default_pattern_handler(FieldPattern.COST, CostHandler)
    FieldHandlerFactory.register_default_pattern_handler(FieldPattern.TAX, TaxHandler)
    FieldHandlerFactory.register_default_pattern_handler(FieldPattern.DISCOUNT, DiscountHandler)
    FieldHandlerFactory.register_default_pattern_handler(FieldPattern.TOTAL, CurrencyHandler)
    FieldHandlerFactory.register_default_pattern_handler(FieldPattern.SUBTOTAL, CurrencyHandler)
    FieldHandlerFactory.register_default_pattern_handler(FieldPattern.PERCENTAGE, PercentHandler)
    FieldHandlerFactory.register_default_pattern_handler(FieldPattern.RATING, RatingHandler)
except ImportError:
    # Numeric handlers not yet available, use DefaultHandler
    pass

# Link handlers (subtask-6-5)
try:
    from mock_data_engine.handlers.link_handlers import (
        LinkHandler,
        DynamicLinkHandler,
    )

    # Register handlers for Link field types
    FieldHandlerFactory.register_default_handler("Link", LinkHandler)
    FieldHandlerFactory.register_default_handler("Dynamic Link", DynamicLinkHandler)
except ImportError:
    # Link handlers not yet available, use DefaultHandler
    pass

# Table handlers (subtask-6-6)
try:
    from mock_data_engine.handlers.table_handlers import (
        TableHandler,
        TableMultiSelectHandler,
    )

    # Register handlers for Table field types
    FieldHandlerFactory.register_default_handler("Table", TableHandler)
    FieldHandlerFactory.register_default_handler("Table MultiSelect", TableMultiSelectHandler)
except ImportError:
    # Table handlers not yet available, use DefaultHandler
    pass

# Text handlers (subtask-6-7)
try:
    from mock_data_engine.handlers.text_handlers import (
        SmallTextHandler,
        TextHandler,
        LongTextHandler,
        TextEditorHandler,
        CodeFieldHandler,
        MarkdownHandler,
    )

    # Register handlers for text field types
    FieldHandlerFactory.register_default_handler("Small Text", SmallTextHandler)
    FieldHandlerFactory.register_default_handler("Text", TextHandler)
    FieldHandlerFactory.register_default_handler("Long Text", LongTextHandler)
    FieldHandlerFactory.register_default_handler("Text Editor", TextEditorHandler)
    FieldHandlerFactory.register_default_handler("HTML Editor", TextEditorHandler)
    FieldHandlerFactory.register_default_handler("Code", CodeFieldHandler)
    FieldHandlerFactory.register_default_handler("Markdown Editor", MarkdownHandler)

    # Register pattern handlers for text semantic patterns
    FieldHandlerFactory.register_default_pattern_handler(FieldPattern.DESCRIPTION, TextHandler)
    FieldHandlerFactory.register_default_pattern_handler(FieldPattern.NOTES, TextHandler)
    FieldHandlerFactory.register_default_pattern_handler(FieldPattern.COMMENT, SmallTextHandler)
    FieldHandlerFactory.register_default_pattern_handler(FieldPattern.REMARKS, SmallTextHandler)
except ImportError:
    # Text handlers not yet available, use DefaultHandler
    pass

# Special handlers (subtask-6-8)
try:
    from mock_data_engine.handlers.special_handlers import (
        CheckHandler,
        SelectHandler,
        ColorHandler,
        AttachHandler,
        AttachImageHandler,
        GeolocationHandler,
        SignatureHandler,
        JSONHandler,
        BarcodeHandler,
    )

    # Register handlers for special field types
    FieldHandlerFactory.register_default_handler("Check", CheckHandler)
    FieldHandlerFactory.register_default_handler("Select", SelectHandler)
    FieldHandlerFactory.register_default_handler("Color", ColorHandler)
    FieldHandlerFactory.register_default_handler("Attach", AttachHandler)
    FieldHandlerFactory.register_default_handler("Attach Image", AttachImageHandler)
    FieldHandlerFactory.register_default_handler("Geolocation", GeolocationHandler)
    FieldHandlerFactory.register_default_handler("Signature", SignatureHandler)
    FieldHandlerFactory.register_default_handler("JSON", JSONHandler)
    FieldHandlerFactory.register_default_handler("Barcode", BarcodeHandler)

    # Register pattern handlers for special patterns
    FieldHandlerFactory.register_default_pattern_handler(FieldPattern.COLOR, ColorHandler)
    FieldHandlerFactory.register_default_pattern_handler(FieldPattern.IMAGE, AttachImageHandler)
    FieldHandlerFactory.register_default_pattern_handler(FieldPattern.PHOTO, AttachImageHandler)
    FieldHandlerFactory.register_default_pattern_handler(FieldPattern.LOGO, AttachImageHandler)
    FieldHandlerFactory.register_default_pattern_handler(FieldPattern.AVATAR, AttachImageHandler)
except ImportError:
    # Special handlers not yet available, use DefaultHandler
    pass

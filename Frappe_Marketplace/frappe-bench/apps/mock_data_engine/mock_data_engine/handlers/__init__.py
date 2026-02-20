# Copyright (c) 2024, Mock Data Engine and contributors
# For license information, please see license.txt

"""
Field Handlers Module for Mock Data Engine.

This module provides the field handler infrastructure for generating mock data
for all 30+ Frappe field types. The handler system uses a factory pattern with
automatic field name pattern detection.

Key Components:
- BaseFieldHandler: Abstract base class for all field handlers
- FieldHandlerFactory: Factory for creating appropriate handlers
- Pattern detection for semantic field name matching (email, phone, name, etc.)

Usage:
    from mock_data_engine.handlers import (
        FieldHandlerFactory,
        BaseFieldHandler,
        GenerationContext,
    )

    # Create a factory
    factory = FieldHandlerFactory(locale='tr_TR', seed=42)

    # Get handler for a field
    handler = factory.get_handler(field_info)

    # Generate value
    value = handler.generate(context)
"""

from mock_data_engine.handlers.base import (
    BaseFieldHandler,
    GenerationContext,
    PatternDetector,
    FieldPattern,
    FIELD_PATTERNS,
)
from mock_data_engine.handlers.factory import (
    FieldHandlerFactory,
    get_handler_for_field,
    create_handler_factory,
)
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
from mock_data_engine.handlers.date_handlers import (
    DateHandler,
    DatetimeHandler,
    TimeHandler,
    DurationHandler,
)
from mock_data_engine.handlers.link_handlers import (
    LinkHandler,
    DynamicLinkHandler,
    LinkResolutionStrategy,
)
from mock_data_engine.handlers.table_handlers import (
    TableHandler,
    TableMultiSelectHandler,
)
from mock_data_engine.handlers.text_handlers import (
    SmallTextHandler,
    TextHandler,
    LongTextHandler,
    TextEditorHandler,
    CodeFieldHandler,
    MarkdownHandler,
    HTMLEditorHandler,
)
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

__all__ = [
    # Base handler
    "BaseFieldHandler",
    "GenerationContext",
    # Pattern detection
    "PatternDetector",
    "FieldPattern",
    "FIELD_PATTERNS",
    # Factory
    "FieldHandlerFactory",
    "get_handler_for_field",
    "create_handler_factory",
    # Data field handlers
    "DataHandler",
    "EmailHandler",
    "PhoneHandler",
    "MobileHandler",
    "URLHandler",
    "WebsiteHandler",
    "FirstNameHandler",
    "LastNameHandler",
    "FullNameHandler",
    "CompanyHandler",
    "AddressHandler",
    "StreetHandler",
    "CityHandler",
    "StateHandler",
    "CountryHandler",
    "PostalCodeHandler",
    "TitleHandler",
    "CodeHandler",
    # Numeric field handlers
    "IntHandler",
    "FloatHandler",
    "CurrencyHandler",
    "PercentHandler",
    "RatingHandler",
    "QuantityHandler",
    "AmountHandler",
    "PriceHandler",
    "CostHandler",
    "TaxHandler",
    "DiscountHandler",
    # Date/Time field handlers
    "DateHandler",
    "DatetimeHandler",
    "TimeHandler",
    "DurationHandler",
    # Link field handlers
    "LinkHandler",
    "DynamicLinkHandler",
    "LinkResolutionStrategy",
    # Table field handlers
    "TableHandler",
    "TableMultiSelectHandler",
    # Text field handlers
    "SmallTextHandler",
    "TextHandler",
    "LongTextHandler",
    "TextEditorHandler",
    "CodeFieldHandler",
    "MarkdownHandler",
    "HTMLEditorHandler",
    # Special field handlers
    "CheckHandler",
    "SelectHandler",
    "ColorHandler",
    "AttachHandler",
    "AttachImageHandler",
    "GeolocationHandler",
    "SignatureHandler",
    "JSONHandler",
    "BarcodeHandler",
]

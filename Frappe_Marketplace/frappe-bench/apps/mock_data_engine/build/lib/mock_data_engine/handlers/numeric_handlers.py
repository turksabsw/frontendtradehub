# Copyright (c) 2024, Mock Data Engine and contributors
# For license information, please see license.txt

"""
Numeric Field Handlers Module.

This module provides handlers for numeric field types including Int, Float,
Currency, Percent, and Rating fields.

The handlers support pattern-based generation for detected semantic patterns
like quantity, price, cost, amount, tax, discount, etc.

Handlers in this module:
- IntHandler: Integer value generation
- FloatHandler: Floating point value generation
- CurrencyHandler: Currency/monetary value generation
- PercentHandler: Percentage value generation (0-100)
- RatingHandler: Rating value generation (typically 0-5)
- QuantityHandler: Quantity/count generation
- AmountHandler: General amount generation
- PriceHandler: Price value generation
- CostHandler: Cost value generation
- TaxHandler: Tax amount/rate generation
- DiscountHandler: Discount amount/rate generation

Usage:
    from mock_data_engine.mock_data_engine.handlers.numeric_handlers import (
        IntHandler,
        FloatHandler,
        CurrencyHandler,
        PercentHandler,
        RatingHandler,
    )

    # Using IntHandler directly
    handler = IntHandler(locale='tr_TR', seed=42)
    value = handler.generate(context)

    # Using CurrencyHandler for monetary values
    currency_handler = CurrencyHandler(locale='tr_TR', seed=42)
    price = currency_handler.generate(context)
"""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, Optional, Set, Union, TYPE_CHECKING

from mock_data_engine.mock_data_engine.handlers.base import (
    BaseFieldHandler,
    FieldPattern,
    GenerationContext,
    GenerationError,
)

if TYPE_CHECKING:
    from mock_data_engine.mock_data_engine.core.config_resolver import ResolvedConfig


class IntHandler(BaseFieldHandler):
    """
    Handler for integer field generation.

    Generates integer values with support for min/max range configuration,
    pattern-based defaults, and override settings.

    Supported patterns:
        - FieldPattern.QUANTITY
        - FieldPattern.QTY
        - FieldPattern.COUNT

    Example:
        >>> handler = IntHandler(locale='en_US')
        >>> handler.generate(context)
        42
    """

    # Default ranges for different patterns
    PATTERN_RANGES = {
        FieldPattern.QUANTITY: (1, 100),
        FieldPattern.QTY: (1, 100),
        FieldPattern.COUNT: (0, 1000),
    }

    def generate(self, context: GenerationContext) -> int:
        """
        Generate an integer value.

        Args:
            context: The generation context

        Returns:
            An integer value
        """
        # Check for override with fixed value
        if context.has_override():
            fixed_value = context.get_override_value("fixed_value")
            if fixed_value is not None:
                return int(fixed_value)

            # Check for range override
            min_val = context.get_override_value("min_value", 0)
            max_val = context.get_override_value("max_value", 10000)
            return self.faker.random_int(min=int(min_val), max=int(max_val))

        # Determine range based on detected pattern
        pattern = context.detected_pattern
        if pattern in self.PATTERN_RANGES:
            min_val, max_val = self.PATTERN_RANGES[pattern]
        else:
            # Default range for generic int fields
            min_val, max_val = 1, 10000

        return self.faker.random_int(min=min_val, max=max_val)

    def validate(self, value: Any, context: GenerationContext) -> bool:
        """Validate integer value."""
        if not isinstance(value, (int, float)):
            return False
        # Check if it's actually an integer (no decimal part)
        if isinstance(value, float) and not value.is_integer():
            return False
        return True

    def get_supported_patterns(self) -> Set[FieldPattern]:
        """Get supported patterns."""
        return {FieldPattern.QUANTITY, FieldPattern.QTY, FieldPattern.COUNT}


class FloatHandler(BaseFieldHandler):
    """
    Handler for floating point field generation.

    Generates float values with configurable precision, range, and
    pattern-based defaults for financial and measurement values.

    Supported patterns:
        - FieldPattern.AMOUNT
        - FieldPattern.GENERIC

    Example:
        >>> handler = FloatHandler(locale='en_US')
        >>> handler.generate(context)
        123.45
    """

    # Default settings
    DEFAULT_MIN = 0.0
    DEFAULT_MAX = 10000.0
    DEFAULT_PRECISION = 2

    def generate(self, context: GenerationContext) -> float:
        """
        Generate a floating point value.

        Args:
            context: The generation context

        Returns:
            A float value
        """
        # Check for override with fixed value
        if context.has_override():
            fixed_value = context.get_override_value("fixed_value")
            if fixed_value is not None:
                return float(fixed_value)

            # Check for range and precision override
            min_val = context.get_override_value("min_value", self.DEFAULT_MIN)
            max_val = context.get_override_value("max_value", self.DEFAULT_MAX)
            precision = context.get_override_value("precision", self.DEFAULT_PRECISION)
        else:
            min_val = self.DEFAULT_MIN
            max_val = self.DEFAULT_MAX
            precision = self.DEFAULT_PRECISION

        # Generate float using Faker
        value = self.faker.pyfloat(
            min_value=float(min_val),
            max_value=float(max_val),
            right_digits=int(precision)
        )

        return round(value, int(precision))

    def validate(self, value: Any, context: GenerationContext) -> bool:
        """Validate float value."""
        if not isinstance(value, (int, float)):
            return False
        return True

    def get_supported_patterns(self) -> Set[FieldPattern]:
        """Get supported patterns."""
        return {FieldPattern.AMOUNT, FieldPattern.GENERIC}


class CurrencyHandler(BaseFieldHandler):
    """
    Handler for currency/monetary field generation.

    Generates currency values with proper decimal precision (typically 2 places),
    realistic ranges based on detected patterns (price, cost, amount, etc.),
    and locale-aware formatting considerations.

    Supported patterns:
        - FieldPattern.PRICE
        - FieldPattern.COST
        - FieldPattern.AMOUNT
        - FieldPattern.TOTAL
        - FieldPattern.SUBTOTAL
        - FieldPattern.TAX
        - FieldPattern.DISCOUNT

    Example:
        >>> handler = CurrencyHandler(locale='tr_TR')
        >>> handler.generate(context)
        1250.99
    """

    # Default ranges for different patterns
    PATTERN_RANGES = {
        FieldPattern.PRICE: (1.0, 10000.0),
        FieldPattern.COST: (0.5, 5000.0),
        FieldPattern.AMOUNT: (1.0, 50000.0),
        FieldPattern.TOTAL: (10.0, 100000.0),
        FieldPattern.SUBTOTAL: (10.0, 90000.0),
        FieldPattern.TAX: (0.0, 10000.0),
        FieldPattern.DISCOUNT: (0.0, 5000.0),
    }

    # Standard currency precision (decimal places)
    CURRENCY_PRECISION = 2

    def generate(self, context: GenerationContext) -> float:
        """
        Generate a currency value.

        Args:
            context: The generation context

        Returns:
            A currency value as float with 2 decimal places
        """
        # Check for override with fixed value
        if context.has_override():
            fixed_value = context.get_override_value("fixed_value")
            if fixed_value is not None:
                return round(float(fixed_value), self.CURRENCY_PRECISION)

            # Check for range override
            min_val = context.get_override_value("min_value", 0.0)
            max_val = context.get_override_value("max_value", 10000.0)
            precision = context.get_override_value("precision", self.CURRENCY_PRECISION)
        else:
            # Determine range based on detected pattern
            pattern = context.detected_pattern
            if pattern in self.PATTERN_RANGES:
                min_val, max_val = self.PATTERN_RANGES[pattern]
            else:
                # Default range for generic currency fields
                min_val, max_val = 1.0, 10000.0
            precision = self.CURRENCY_PRECISION

        # Generate value
        value = self.faker.pyfloat(
            min_value=float(min_val),
            max_value=float(max_val),
            right_digits=int(precision)
        )

        return round(value, int(precision))

    def validate(self, value: Any, context: GenerationContext) -> bool:
        """Validate currency value."""
        if not isinstance(value, (int, float, Decimal)):
            return False
        # Currency should not be negative (in most cases)
        # Allow negative for special cases like discounts
        pattern = context.detected_pattern
        if pattern in (FieldPattern.DISCOUNT, FieldPattern.TAX):
            return True
        return float(value) >= 0

    def get_supported_patterns(self) -> Set[FieldPattern]:
        """Get supported patterns."""
        return {
            FieldPattern.PRICE,
            FieldPattern.COST,
            FieldPattern.AMOUNT,
            FieldPattern.TOTAL,
            FieldPattern.SUBTOTAL,
            FieldPattern.TAX,
            FieldPattern.DISCOUNT,
        }


class PercentHandler(BaseFieldHandler):
    """
    Handler for percentage field generation.

    Generates percentage values typically in the range 0-100.
    Supports different percentage contexts like tax rates, discount rates,
    progress percentages, etc.

    Supported patterns:
        - FieldPattern.PERCENTAGE
        - FieldPattern.PERCENT

    Example:
        >>> handler = PercentHandler(locale='en_US')
        >>> handler.generate(context)
        45.5
    """

    # Default range for percentages
    DEFAULT_MIN = 0.0
    DEFAULT_MAX = 100.0
    DEFAULT_PRECISION = 2

    def generate(self, context: GenerationContext) -> float:
        """
        Generate a percentage value.

        Args:
            context: The generation context

        Returns:
            A percentage value (0-100 range)
        """
        # Check for override with fixed value
        if context.has_override():
            fixed_value = context.get_override_value("fixed_value")
            if fixed_value is not None:
                return round(float(fixed_value), self.DEFAULT_PRECISION)

            # Check for range override
            min_val = context.get_override_value("min_value", self.DEFAULT_MIN)
            max_val = context.get_override_value("max_value", self.DEFAULT_MAX)
            precision = context.get_override_value("precision", self.DEFAULT_PRECISION)
        else:
            # Check fieldname for context-specific ranges
            fieldname = context.fieldname.lower()

            # Tax percentages are usually smaller ranges
            if "tax" in fieldname or "vat" in fieldname or "kdv" in fieldname:
                min_val, max_val = 0.0, 25.0
            # Discount percentages
            elif "discount" in fieldname or "indirim" in fieldname:
                min_val, max_val = 0.0, 50.0
            # Progress percentages
            elif "progress" in fieldname or "completion" in fieldname:
                min_val, max_val = 0.0, 100.0
            else:
                min_val, max_val = self.DEFAULT_MIN, self.DEFAULT_MAX

            precision = self.DEFAULT_PRECISION

        # Generate value
        value = self.faker.pyfloat(
            min_value=float(min_val),
            max_value=float(max_val),
            right_digits=int(precision)
        )

        return round(value, int(precision))

    def validate(self, value: Any, context: GenerationContext) -> bool:
        """Validate percentage value."""
        if not isinstance(value, (int, float)):
            return False
        # Check if percentage is in valid range
        return 0 <= float(value) <= 100

    def get_supported_patterns(self) -> Set[FieldPattern]:
        """Get supported patterns."""
        return {FieldPattern.PERCENTAGE, FieldPattern.PERCENT}


class RatingHandler(BaseFieldHandler):
    """
    Handler for rating field generation.

    Generates rating values typically in a star-rating format (0-5).
    Frappe's Rating field uses a 0-1 scale internally but often
    represents a 5-star rating.

    Supported patterns:
        - FieldPattern.RATING

    Example:
        >>> handler = RatingHandler(locale='en_US')
        >>> handler.generate(context)
        0.8  # Represents 4 stars out of 5
    """

    # Frappe Rating field uses 0-1 scale (representing 0-5 stars)
    DEFAULT_MIN = 0.0
    DEFAULT_MAX = 1.0
    DEFAULT_PRECISION = 2

    def generate(self, context: GenerationContext) -> float:
        """
        Generate a rating value.

        Frappe's Rating field uses a 0-1 scale:
        - 0.0 = 0 stars
        - 0.2 = 1 star
        - 0.4 = 2 stars
        - 0.6 = 3 stars
        - 0.8 = 4 stars
        - 1.0 = 5 stars

        Args:
            context: The generation context

        Returns:
            A rating value (0-1 scale for Frappe)
        """
        # Check for override with fixed value
        if context.has_override():
            fixed_value = context.get_override_value("fixed_value")
            if fixed_value is not None:
                # Handle both 0-1 and 0-5 scale inputs
                value = float(fixed_value)
                if value > 1.0:
                    value = value / 5.0  # Convert 5-star scale to 0-1
                return min(1.0, max(0.0, round(value, self.DEFAULT_PRECISION)))

            # Check for range override
            min_val = context.get_override_value("min_value", self.DEFAULT_MIN)
            max_val = context.get_override_value("max_value", self.DEFAULT_MAX)

            # If override specifies 0-5 scale, convert
            if max_val > 1.0:
                min_val = float(min_val) / 5.0
                max_val = float(max_val) / 5.0
        else:
            min_val = self.DEFAULT_MIN
            max_val = self.DEFAULT_MAX

        # Check for whole star override
        whole_stars_only = context.get_override_value("whole_stars_only", False)

        if whole_stars_only:
            # Generate discrete star values (0, 0.2, 0.4, 0.6, 0.8, 1.0)
            star_values = [0.0, 0.2, 0.4, 0.6, 0.8, 1.0]
            valid_values = [v for v in star_values if min_val <= v <= max_val]
            if valid_values:
                return self.faker.random_element(valid_values)
            return 0.6  # Default to 3 stars

        # Generate continuous value
        value = self.faker.pyfloat(
            min_value=float(min_val),
            max_value=float(max_val),
            right_digits=self.DEFAULT_PRECISION
        )

        return round(value, self.DEFAULT_PRECISION)

    def validate(self, value: Any, context: GenerationContext) -> bool:
        """Validate rating value."""
        if not isinstance(value, (int, float)):
            return False
        # Frappe Rating should be 0-1
        return 0 <= float(value) <= 1

    def get_supported_patterns(self) -> Set[FieldPattern]:
        """Get supported patterns."""
        return {FieldPattern.RATING}


class QuantityHandler(BaseFieldHandler):
    """
    Handler for quantity field generation.

    Generates quantity values for inventory, order quantities, etc.
    Always returns positive integer values.

    Supported patterns:
        - FieldPattern.QUANTITY
        - FieldPattern.QTY
        - FieldPattern.COUNT

    Example:
        >>> handler = QuantityHandler(locale='en_US')
        >>> handler.generate(context)
        25
    """

    # Default range for quantities
    DEFAULT_MIN = 1
    DEFAULT_MAX = 100

    def generate(self, context: GenerationContext) -> int:
        """
        Generate a quantity value.

        Args:
            context: The generation context

        Returns:
            A positive integer quantity
        """
        # Check for override with fixed value
        if context.has_override():
            fixed_value = context.get_override_value("fixed_value")
            if fixed_value is not None:
                return max(0, int(fixed_value))

            # Check for range override
            min_val = context.get_override_value("min_value", self.DEFAULT_MIN)
            max_val = context.get_override_value("max_value", self.DEFAULT_MAX)
        else:
            # Check fieldname for context-specific ranges
            fieldname = context.fieldname.lower()

            # Stock quantities might be larger
            if "stock" in fieldname or "stok" in fieldname:
                min_val, max_val = 1, 1000
            # Order quantities are usually smaller
            elif "order" in fieldname or "siparis" in fieldname:
                min_val, max_val = 1, 50
            else:
                min_val, max_val = self.DEFAULT_MIN, self.DEFAULT_MAX

        return self.faker.random_int(min=int(min_val), max=int(max_val))

    def validate(self, value: Any, context: GenerationContext) -> bool:
        """Validate quantity value."""
        if not isinstance(value, (int, float)):
            return False
        # Quantity should be non-negative
        return float(value) >= 0

    def get_supported_patterns(self) -> Set[FieldPattern]:
        """Get supported patterns."""
        return {FieldPattern.QUANTITY, FieldPattern.QTY, FieldPattern.COUNT}


class AmountHandler(BaseFieldHandler):
    """
    Handler for general amount field generation.

    Generates numeric amounts that could be monetary, quantity-based,
    or other numeric values. Delegates to CurrencyHandler for monetary
    amounts and uses generic float generation otherwise.

    Supported patterns:
        - FieldPattern.AMOUNT

    Example:
        >>> handler = AmountHandler(locale='en_US')
        >>> handler.generate(context)
        1500.00
    """

    def __init__(
        self,
        locale: str = "en_US",
        seed: Optional[int] = None,
        config: Optional["ResolvedConfig"] = None
    ):
        """Initialize AmountHandler."""
        super().__init__(locale=locale, seed=seed, config=config)
        self._currency_handler: Optional[CurrencyHandler] = None

    @property
    def currency_handler(self) -> CurrencyHandler:
        """Get currency handler for monetary amounts."""
        if self._currency_handler is None:
            self._currency_handler = CurrencyHandler(
                locale=self._locale,
                seed=self._seed,
                config=self._config
            )
        return self._currency_handler

    def generate(self, context: GenerationContext) -> float:
        """
        Generate an amount value.

        Args:
            context: The generation context

        Returns:
            A numeric amount value
        """
        # Check for override with fixed value
        if context.has_override():
            fixed_value = context.get_override_value("fixed_value")
            if fixed_value is not None:
                return round(float(fixed_value), 2)

            # Check if this should be treated as currency
            is_currency = context.get_override_value("is_currency", True)
            if is_currency:
                return self.currency_handler.generate(context)

        # Default: treat as currency amount
        return self.currency_handler.generate(context)

    def validate(self, value: Any, context: GenerationContext) -> bool:
        """Validate amount value."""
        if not isinstance(value, (int, float)):
            return False
        return True

    def get_supported_patterns(self) -> Set[FieldPattern]:
        """Get supported patterns."""
        return {FieldPattern.AMOUNT}


class PriceHandler(BaseFieldHandler):
    """
    Handler for price field generation.

    Generates price values for products, services, etc.
    Ensures realistic price ranges and proper decimal precision.

    Supported patterns:
        - FieldPattern.PRICE

    Example:
        >>> handler = PriceHandler(locale='tr_TR')
        >>> handler.generate(context)
        299.99
    """

    # Default range for prices
    DEFAULT_MIN = 1.0
    DEFAULT_MAX = 10000.0
    PRECISION = 2

    def generate(self, context: GenerationContext) -> float:
        """
        Generate a price value.

        Args:
            context: The generation context

        Returns:
            A price value with 2 decimal places
        """
        # Check for override with fixed value
        if context.has_override():
            fixed_value = context.get_override_value("fixed_value")
            if fixed_value is not None:
                return round(float(fixed_value), self.PRECISION)

            # Check for range override
            min_val = context.get_override_value("min_value", self.DEFAULT_MIN)
            max_val = context.get_override_value("max_value", self.DEFAULT_MAX)
        else:
            # Check fieldname for context-specific ranges
            fieldname = context.fieldname.lower()

            # Unit prices might be smaller
            if "unit" in fieldname or "birim" in fieldname:
                min_val, max_val = 0.01, 1000.0
            # Retail prices
            elif "retail" in fieldname or "satis" in fieldname:
                min_val, max_val = 1.0, 50000.0
            # Wholesale prices
            elif "wholesale" in fieldname or "toptan" in fieldname:
                min_val, max_val = 0.5, 25000.0
            else:
                min_val, max_val = self.DEFAULT_MIN, self.DEFAULT_MAX

        # Generate price
        value = self.faker.pyfloat(
            min_value=float(min_val),
            max_value=float(max_val),
            right_digits=self.PRECISION
        )

        return round(value, self.PRECISION)

    def validate(self, value: Any, context: GenerationContext) -> bool:
        """Validate price value."""
        if not isinstance(value, (int, float)):
            return False
        # Price should be non-negative
        return float(value) >= 0

    def get_supported_patterns(self) -> Set[FieldPattern]:
        """Get supported patterns."""
        return {FieldPattern.PRICE}


class CostHandler(BaseFieldHandler):
    """
    Handler for cost field generation.

    Generates cost values for products, services, operations, etc.
    Similar to price but typically represents internal/purchase costs.

    Supported patterns:
        - FieldPattern.COST

    Example:
        >>> handler = CostHandler(locale='tr_TR')
        >>> handler.generate(context)
        150.00
    """

    # Default range for costs (typically lower than retail prices)
    DEFAULT_MIN = 0.5
    DEFAULT_MAX = 5000.0
    PRECISION = 2

    def generate(self, context: GenerationContext) -> float:
        """
        Generate a cost value.

        Args:
            context: The generation context

        Returns:
            A cost value with 2 decimal places
        """
        # Check for override with fixed value
        if context.has_override():
            fixed_value = context.get_override_value("fixed_value")
            if fixed_value is not None:
                return round(float(fixed_value), self.PRECISION)

            # Check for range override
            min_val = context.get_override_value("min_value", self.DEFAULT_MIN)
            max_val = context.get_override_value("max_value", self.DEFAULT_MAX)
        else:
            min_val, max_val = self.DEFAULT_MIN, self.DEFAULT_MAX

        # Generate cost
        value = self.faker.pyfloat(
            min_value=float(min_val),
            max_value=float(max_val),
            right_digits=self.PRECISION
        )

        return round(value, self.PRECISION)

    def validate(self, value: Any, context: GenerationContext) -> bool:
        """Validate cost value."""
        if not isinstance(value, (int, float)):
            return False
        # Cost should be non-negative
        return float(value) >= 0

    def get_supported_patterns(self) -> Set[FieldPattern]:
        """Get supported patterns."""
        return {FieldPattern.COST}


class TaxHandler(BaseFieldHandler):
    """
    Handler for tax-related field generation.

    Generates tax amounts or tax rates based on context.
    Supports both tax percentages and calculated tax amounts.

    Supported patterns:
        - FieldPattern.TAX

    Example:
        >>> handler = TaxHandler(locale='tr_TR')
        >>> handler.generate(context)
        18.0  # or 180.50 for tax amount
    """

    def generate(self, context: GenerationContext) -> float:
        """
        Generate a tax value.

        Args:
            context: The generation context

        Returns:
            A tax rate (%) or tax amount
        """
        # Check for override with fixed value
        if context.has_override():
            fixed_value = context.get_override_value("fixed_value")
            if fixed_value is not None:
                return round(float(fixed_value), 2)

            # Check if this is a rate or amount
            is_rate = context.get_override_value("is_rate", None)
            if is_rate is not None:
                if is_rate:
                    min_val = context.get_override_value("min_value", 0.0)
                    max_val = context.get_override_value("max_value", 25.0)
                else:
                    min_val = context.get_override_value("min_value", 0.0)
                    max_val = context.get_override_value("max_value", 5000.0)

                value = self.faker.pyfloat(
                    min_value=float(min_val),
                    max_value=float(max_val),
                    right_digits=2
                )
                return round(value, 2)

        # Auto-detect: if fieldname contains "rate", generate percentage
        fieldname = context.fieldname.lower()

        if "rate" in fieldname or "oran" in fieldname:
            # Generate tax rate percentage
            # Common Turkish tax rates: 1%, 8%, 18%, 20%
            if self._locale.lower().startswith("tr"):
                rates = [1.0, 8.0, 10.0, 18.0, 20.0]
                return self.faker.random_element(rates)
            else:
                # Generate realistic tax rate
                return round(self.faker.pyfloat(min_value=0.0, max_value=25.0, right_digits=2), 2)
        else:
            # Generate tax amount
            return round(self.faker.pyfloat(min_value=0.0, max_value=5000.0, right_digits=2), 2)

    def validate(self, value: Any, context: GenerationContext) -> bool:
        """Validate tax value."""
        if not isinstance(value, (int, float)):
            return False
        # Tax should be non-negative
        return float(value) >= 0

    def get_supported_patterns(self) -> Set[FieldPattern]:
        """Get supported patterns."""
        return {FieldPattern.TAX}


class DiscountHandler(BaseFieldHandler):
    """
    Handler for discount field generation.

    Generates discount amounts or discount percentages based on context.
    Supports both flat discounts and percentage discounts.

    Supported patterns:
        - FieldPattern.DISCOUNT

    Example:
        >>> handler = DiscountHandler(locale='en_US')
        >>> handler.generate(context)
        15.0  # 15% discount or 15.00 currency
    """

    def generate(self, context: GenerationContext) -> float:
        """
        Generate a discount value.

        Args:
            context: The generation context

        Returns:
            A discount rate (%) or discount amount
        """
        # Check for override with fixed value
        if context.has_override():
            fixed_value = context.get_override_value("fixed_value")
            if fixed_value is not None:
                return round(float(fixed_value), 2)

            # Check if this is a rate or amount
            is_rate = context.get_override_value("is_rate", None)
            if is_rate is not None:
                if is_rate:
                    min_val = context.get_override_value("min_value", 0.0)
                    max_val = context.get_override_value("max_value", 50.0)
                else:
                    min_val = context.get_override_value("min_value", 0.0)
                    max_val = context.get_override_value("max_value", 1000.0)

                value = self.faker.pyfloat(
                    min_value=float(min_val),
                    max_value=float(max_val),
                    right_digits=2
                )
                return round(value, 2)

        # Auto-detect: if fieldname contains "percent" or "rate", generate percentage
        fieldname = context.fieldname.lower()

        if any(x in fieldname for x in ["percent", "rate", "oran", "yuzde"]):
            # Generate discount percentage (usually 0-50%)
            return round(self.faker.pyfloat(min_value=0.0, max_value=50.0, right_digits=2), 2)
        else:
            # Generate discount amount
            return round(self.faker.pyfloat(min_value=0.0, max_value=1000.0, right_digits=2), 2)

    def validate(self, value: Any, context: GenerationContext) -> bool:
        """Validate discount value."""
        if not isinstance(value, (int, float)):
            return False
        # Discount should be non-negative
        return float(value) >= 0

    def get_supported_patterns(self) -> Set[FieldPattern]:
        """Get supported patterns."""
        return {FieldPattern.DISCOUNT}


# Export all handler classes
__all__ = [
    # Primary handlers (required by subtask)
    "IntHandler",
    "FloatHandler",
    "CurrencyHandler",
    "PercentHandler",
    "RatingHandler",
    # Pattern-specific handlers
    "QuantityHandler",
    "AmountHandler",
    "PriceHandler",
    "CostHandler",
    "TaxHandler",
    "DiscountHandler",
]

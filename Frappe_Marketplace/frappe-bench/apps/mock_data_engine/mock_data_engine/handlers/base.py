# Copyright (c) 2024, Mock Data Engine and contributors
# For license information, please see license.txt

"""
Base Field Handler Module.

This module provides the abstract base class for all field type handlers
and the pattern detection system for automatic field type inference.

The pattern detection system analyzes field names to infer semantic meaning
and select appropriate generation strategies. For example:
- Fields named "email", "email_id", "contact_email" -> email generator
- Fields named "phone", "mobile", "contact_phone" -> phone generator
- Fields named "city", "town" -> city name generator

Pattern Detection Priority:
1. Field mapping overrides (from profile/settings)
2. Field name pattern matching
3. Field type default handler

Usage:
    class EmailHandler(BaseFieldHandler):
        '''Handler for email fields.'''

        def generate(self, context: GenerationContext) -> str:
            return self.faker.email()

        def validate(self, value: Any) -> bool:
            return '@' in str(value)
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Pattern, Set, TYPE_CHECKING

if TYPE_CHECKING:
    from mock_data_engine.core.meta_reader import FieldInfo
    from mock_data_engine.core.record_cache import RecordCache
    from mock_data_engine.core.config_resolver import ResolvedConfig


class FieldPattern(Enum):
    """
    Enumeration of semantic field patterns for automatic detection.

    These patterns represent common field semantics that can be inferred
    from field names, allowing the generator to produce more realistic data.
    """

    # Person/Contact patterns
    FIRST_NAME = "first_name"
    LAST_NAME = "last_name"
    FULL_NAME = "full_name"
    EMAIL = "email"
    PHONE = "phone"
    MOBILE = "mobile"

    # Address patterns
    ADDRESS = "address"
    STREET = "street"
    CITY = "city"
    STATE = "state"
    COUNTRY = "country"
    POSTAL_CODE = "postal_code"
    ZIP_CODE = "zip_code"

    # Business patterns
    COMPANY = "company"
    COMPANY_NAME = "company_name"
    WEBSITE = "website"
    URL = "url"

    # Document patterns
    DESCRIPTION = "description"
    NOTES = "notes"
    COMMENT = "comment"
    REMARKS = "remarks"
    TITLE = "title"

    # Identifier patterns
    CODE = "code"
    SKU = "sku"
    SERIAL = "serial"
    REFERENCE = "reference"

    # Financial patterns
    AMOUNT = "amount"
    PRICE = "price"
    COST = "cost"
    TAX = "tax"
    DISCOUNT = "discount"
    TOTAL = "total"
    SUBTOTAL = "subtotal"

    # Quantity patterns
    QUANTITY = "quantity"
    QTY = "qty"
    COUNT = "count"

    # Date/Time patterns
    DATE = "date"
    START_DATE = "start_date"
    END_DATE = "end_date"
    BIRTH_DATE = "birth_date"
    CREATED = "created"
    MODIFIED = "modified"

    # Turkish-specific patterns
    TCKN = "tckn"
    VKN = "vkn"
    TAX_ID = "tax_id"
    IBAN = "iban"

    # Image patterns
    IMAGE = "image"
    PHOTO = "photo"
    LOGO = "logo"
    AVATAR = "avatar"

    # Other patterns
    COLOR = "color"
    STATUS = "status"
    PERCENTAGE = "percentage"
    PERCENT = "percent"
    RATING = "rating"

    # No specific pattern detected
    GENERIC = "generic"


# Field name patterns for detection
# Format: (pattern_enum, regex_pattern, priority)
# Lower priority = higher precedence
FIELD_PATTERNS: List[tuple] = [
    # Turkish identifiers (highest priority for Turkish locale)
    (FieldPattern.TCKN, re.compile(r"(tckn|tc_kimlik|tc_no|kimlik_no|citizen_id)", re.I), 1),
    (FieldPattern.VKN, re.compile(r"(vkn|vergi_no|vergi_kimlik|tax_number|tax_id)", re.I), 1),
    (FieldPattern.IBAN, re.compile(r"(iban|bank_account|hesap_no)", re.I), 2),

    # Person names (high priority)
    (FieldPattern.FIRST_NAME, re.compile(r"(first_?name|given_?name|ad|isim)$", re.I), 3),
    (FieldPattern.LAST_NAME, re.compile(r"(last_?name|surname|family_?name|soyad|soyisim)$", re.I), 3),
    (FieldPattern.FULL_NAME, re.compile(r"(full_?name|customer_?name|contact_?name|person_?name|ad_soyad)$", re.I), 3),

    # Contact information
    (FieldPattern.EMAIL, re.compile(r"(e?mail|email_?id|email_?address|contact_?email)", re.I), 4),
    (FieldPattern.PHONE, re.compile(r"(phone|telephone|tel|telefon)(?!.*mobile)", re.I), 4),
    (FieldPattern.MOBILE, re.compile(r"(mobile|cell|gsm|cep)", re.I), 4),

    # Address components
    (FieldPattern.STREET, re.compile(r"(street|sokak|cadde|road|lane)", re.I), 5),
    (FieldPattern.CITY, re.compile(r"(city|sehir|town|il(?!e))$", re.I), 5),
    (FieldPattern.STATE, re.compile(r"(state|province|region|bolge)$", re.I), 5),
    (FieldPattern.COUNTRY, re.compile(r"(country|ulke|nation)$", re.I), 5),
    (FieldPattern.POSTAL_CODE, re.compile(r"(postal|zip|pin_?code|posta_?kodu)", re.I), 5),
    (FieldPattern.ADDRESS, re.compile(r"(address|adres|location)(?!.*type)", re.I), 6),

    # Business
    (FieldPattern.COMPANY, re.compile(r"(company|firma|organization|organisation)(?!.*type)", re.I), 5),
    (FieldPattern.COMPANY_NAME, re.compile(r"(company_?name|firm_?name|org_?name)", re.I), 4),
    (FieldPattern.WEBSITE, re.compile(r"(website|web_?site|homepage)", re.I), 5),
    (FieldPattern.URL, re.compile(r"(url|link|href)$", re.I), 5),

    # Document content
    (FieldPattern.DESCRIPTION, re.compile(r"(description|desc|aciklama|summary)", re.I), 7),
    (FieldPattern.NOTES, re.compile(r"(notes?|notlar)$", re.I), 7),
    (FieldPattern.COMMENT, re.compile(r"(comments?|yorum)", re.I), 7),
    (FieldPattern.REMARKS, re.compile(r"(remarks?|observations?)", re.I), 7),
    (FieldPattern.TITLE, re.compile(r"(title|baslik|heading)$", re.I), 7),

    # Identifiers
    (FieldPattern.CODE, re.compile(r"(code|kod)$", re.I), 6),
    (FieldPattern.SKU, re.compile(r"(sku|stock_?code|stok_?kodu)", re.I), 5),
    (FieldPattern.SERIAL, re.compile(r"(serial|seri)(_?no|_?number)?", re.I), 6),
    (FieldPattern.REFERENCE, re.compile(r"(reference|ref|referans)(?!.*type)", re.I), 7),

    # Financial
    (FieldPattern.PRICE, re.compile(r"(price|fiyat|rate|birim_?fiyat)$", re.I), 6),
    (FieldPattern.COST, re.compile(r"(cost|maliyet)$", re.I), 6),
    (FieldPattern.TAX, re.compile(r"(tax(?!_id)|vergi|kdv)(?!.*type|.*no)", re.I), 6),
    (FieldPattern.DISCOUNT, re.compile(r"(discount|indirim)", re.I), 6),
    (FieldPattern.TOTAL, re.compile(r"(total|toplam|grand_?total)$", re.I), 6),
    (FieldPattern.SUBTOTAL, re.compile(r"(sub_?total|ara_?toplam)", re.I), 6),
    (FieldPattern.AMOUNT, re.compile(r"(amount|tutar|miktar)(?!.*type)", re.I), 7),

    # Quantities
    (FieldPattern.QUANTITY, re.compile(r"(quantity|adet|miktar)$", re.I), 6),
    (FieldPattern.QTY, re.compile(r"(qty|qte)$", re.I), 6),
    (FieldPattern.COUNT, re.compile(r"count$", re.I), 7),

    # Date/Time patterns
    (FieldPattern.BIRTH_DATE, re.compile(r"(birth_?date|dob|dogum_?tarihi)", re.I), 5),
    (FieldPattern.START_DATE, re.compile(r"(start_?date|begin_?date|baslangic)", re.I), 6),
    (FieldPattern.END_DATE, re.compile(r"(end_?date|finish_?date|bitis)", re.I), 6),
    (FieldPattern.CREATED, re.compile(r"(created|creation|olusturma)", re.I), 7),
    (FieldPattern.MODIFIED, re.compile(r"(modified|updated|guncelleme)", re.I), 7),
    (FieldPattern.DATE, re.compile(r"date$", re.I), 8),

    # Images
    (FieldPattern.IMAGE, re.compile(r"(image|img|resim|gorsel)$", re.I), 6),
    (FieldPattern.PHOTO, re.compile(r"(photo|foto|fotograf)", re.I), 6),
    (FieldPattern.LOGO, re.compile(r"(logo|amblem)", re.I), 6),
    (FieldPattern.AVATAR, re.compile(r"(avatar|profile_?pic|profil)", re.I), 6),

    # Other
    (FieldPattern.COLOR, re.compile(r"(color|colour|renk)$", re.I), 6),
    (FieldPattern.STATUS, re.compile(r"status$", re.I), 7),
    (FieldPattern.PERCENTAGE, re.compile(r"(percentage|percent|yuzde)", re.I), 6),
    (FieldPattern.RATING, re.compile(r"(rating|puan|score)$", re.I), 6),
]


@dataclass
class GenerationContext:
    """
    Context passed to field handlers during value generation.

    This context provides all the information a handler needs to generate
    an appropriate value, including:
    - The field metadata
    - The DocType being generated
    - Previously generated field values (for the current record)
    - The record cache (for Link field resolution)
    - Configuration settings

    Attributes:
        field_info: The field metadata from DocTypeMeta
        doctype: The DocType being generated
        record_data: Dict of already-generated field values for this record
        record_cache: Cache of previously created records
        config: Resolved configuration settings
        locale: The locale for data generation (e.g., 'tr_TR')
        seed: Random seed for reproducibility
        generation_method: Current generation method (Faker, LLM, Hybrid)
        batch_index: Current index within the batch
        total_count: Total records being generated
        parent_doctype: Parent DocType for child table records
        parent_name: Parent document name for child table records
        field_override: Optional override configuration for this field
        detected_pattern: Detected semantic pattern for the field
    """

    field_info: "FieldInfo"
    doctype: str
    record_data: Dict[str, Any] = field(default_factory=dict)
    record_cache: Optional["RecordCache"] = None
    config: Optional["ResolvedConfig"] = None
    locale: str = "en_US"
    seed: Optional[int] = None
    generation_method: str = "Faker"
    batch_index: int = 0
    total_count: int = 1
    parent_doctype: Optional[str] = None
    parent_name: Optional[str] = None
    field_override: Optional[Dict[str, Any]] = None
    detected_pattern: Optional[FieldPattern] = None

    @property
    def fieldname(self) -> str:
        """Get the field name."""
        return self.field_info.fieldname

    @property
    def fieldtype(self) -> str:
        """Get the field type."""
        return self.field_info.fieldtype

    @property
    def is_required(self) -> bool:
        """Check if the field is required."""
        return self.field_info.is_required

    @property
    def is_unique(self) -> bool:
        """Check if the field must be unique."""
        return self.field_info.unique

    @property
    def max_length(self) -> int:
        """Get the maximum length for string fields."""
        return self.field_info.length or 140  # Default Frappe Data field length

    @property
    def options(self) -> str:
        """Get the field options string."""
        return self.field_info.options

    @property
    def select_options(self) -> List[str]:
        """Get the list of options for Select fields."""
        return self.field_info.select_options

    @property
    def default_value(self) -> Optional[str]:
        """Get the field's default value."""
        return self.field_info.default

    @property
    def linked_doctype(self) -> Optional[str]:
        """Get the linked DocType for Link fields."""
        return self.field_info.linked_doctype

    @property
    def is_child_table(self) -> bool:
        """Check if this is a child table context."""
        return self.parent_doctype is not None

    def get_existing_value(self, fieldname: str) -> Any:
        """Get a previously generated value for the current record."""
        return self.record_data.get(fieldname)

    def has_override(self) -> bool:
        """Check if this field has an override configuration."""
        return self.field_override is not None

    def get_override_value(self, key: str, default: Any = None) -> Any:
        """Get a value from the field override configuration."""
        if self.field_override is None:
            return default
        return self.field_override.get(key, default)

    def should_skip(self) -> bool:
        """Check if this field should be skipped."""
        if self.field_override:
            return self.field_override.get("skip_field", False)
        return False

    def to_dict(self) -> Dict[str, Any]:
        """Convert context to dictionary for logging/debugging."""
        return {
            "fieldname": self.fieldname,
            "fieldtype": self.fieldtype,
            "doctype": self.doctype,
            "locale": self.locale,
            "batch_index": self.batch_index,
            "total_count": self.total_count,
            "is_required": self.is_required,
            "is_unique": self.is_unique,
            "detected_pattern": self.detected_pattern.value if self.detected_pattern else None,
            "has_override": self.has_override(),
            "is_child_table": self.is_child_table,
        }


class PatternDetector:
    """
    Detects semantic patterns in field names.

    This class analyzes field names using regex patterns to determine
    the semantic meaning of fields, enabling more appropriate data generation.

    The detector considers:
    1. Field name patterns (e.g., "email_id" -> EMAIL)
    2. Field type hints (e.g., Date fieldtype suggests date patterns)
    3. Locale-specific patterns (e.g., Turkish TCKN fields)

    Example:
        >>> detector = PatternDetector()
        >>> detector.detect("customer_email", "Data")
        FieldPattern.EMAIL
        >>> detector.detect("tckn_no", "Data", locale="tr_TR")
        FieldPattern.TCKN
    """

    def __init__(
        self,
        patterns: Optional[List[tuple]] = None,
        locale: str = "en_US"
    ):
        """
        Initialize the PatternDetector.

        Args:
            patterns: Optional custom pattern list (defaults to FIELD_PATTERNS)
            locale: The locale for locale-specific pattern detection
        """
        self._patterns = patterns or FIELD_PATTERNS
        self._locale = locale
        # Sort patterns by priority (lower = higher precedence)
        self._sorted_patterns = sorted(self._patterns, key=lambda x: x[2])
        # Cache for detected patterns
        self._cache: Dict[str, FieldPattern] = {}

    @property
    def locale(self) -> str:
        """Get the current locale."""
        return self._locale

    def set_locale(self, locale: str) -> None:
        """
        Set the locale for pattern detection.

        Args:
            locale: The locale string (e.g., 'tr_TR', 'en_US')
        """
        self._locale = locale

    def detect(
        self,
        fieldname: str,
        fieldtype: str,
        locale: Optional[str] = None,
        use_cache: bool = True
    ) -> FieldPattern:
        """
        Detect the semantic pattern for a field.

        Args:
            fieldname: The field name to analyze
            fieldtype: The Frappe field type
            locale: Optional locale override
            use_cache: Whether to use cached results

        Returns:
            The detected FieldPattern, or FieldPattern.GENERIC if none found

        Example:
            >>> detector = PatternDetector()
            >>> detector.detect("email_address", "Data")
            FieldPattern.EMAIL
        """
        effective_locale = locale or self._locale

        # Check cache first
        cache_key = f"{fieldname}:{fieldtype}:{effective_locale}"
        if use_cache and cache_key in self._cache:
            return self._cache[cache_key]

        # Try pattern matching
        detected = self._match_patterns(fieldname, fieldtype, effective_locale)

        # If no pattern matched, infer from field type
        if detected == FieldPattern.GENERIC:
            detected = self._infer_from_fieldtype(fieldtype)

        # Cache and return
        if use_cache:
            self._cache[cache_key] = detected

        return detected

    def _match_patterns(
        self,
        fieldname: str,
        fieldtype: str,
        locale: str
    ) -> FieldPattern:
        """
        Match field name against patterns.

        Args:
            fieldname: The field name to match
            fieldtype: The field type
            locale: The locale

        Returns:
            The matched FieldPattern or GENERIC
        """
        # Turkish-specific patterns have higher priority for Turkish locale
        is_turkish = locale.lower().startswith("tr")

        for pattern_enum, regex, priority in self._sorted_patterns:
            # Skip Turkish patterns for non-Turkish locales unless explicitly named
            if pattern_enum in (FieldPattern.TCKN, FieldPattern.VKN):
                if not is_turkish:
                    # Still match if the field is explicitly named tckn/vkn
                    explicit_turkish = bool(re.search(r"(tckn|vkn)", fieldname, re.I))
                    if not explicit_turkish:
                        continue

            if regex.search(fieldname):
                return pattern_enum

        return FieldPattern.GENERIC

    def _infer_from_fieldtype(self, fieldtype: str) -> FieldPattern:
        """
        Infer pattern from Frappe field type.

        Args:
            fieldtype: The Frappe field type

        Returns:
            A FieldPattern based on field type
        """
        type_mapping = {
            "Date": FieldPattern.DATE,
            "Datetime": FieldPattern.DATE,
            "Time": FieldPattern.DATE,
            "Color": FieldPattern.COLOR,
            "Rating": FieldPattern.RATING,
            "Percent": FieldPattern.PERCENTAGE,
            "Attach Image": FieldPattern.IMAGE,
        }
        return type_mapping.get(fieldtype, FieldPattern.GENERIC)

    def detect_batch(
        self,
        fields: List[tuple],
        locale: Optional[str] = None
    ) -> Dict[str, FieldPattern]:
        """
        Detect patterns for multiple fields.

        Args:
            fields: List of (fieldname, fieldtype) tuples
            locale: Optional locale override

        Returns:
            Dict mapping fieldname to detected pattern
        """
        return {
            fieldname: self.detect(fieldname, fieldtype, locale)
            for fieldname, fieldtype in fields
        }

    def get_patterns_for_locale(self, locale: str) -> Set[FieldPattern]:
        """
        Get patterns that are relevant for a specific locale.

        Args:
            locale: The locale string

        Returns:
            Set of FieldPatterns relevant for the locale
        """
        patterns = set(FieldPattern)

        if not locale.lower().startswith("tr"):
            # Remove Turkish-specific patterns for non-Turkish locales
            patterns.discard(FieldPattern.TCKN)
            patterns.discard(FieldPattern.VKN)

        return patterns

    def clear_cache(self) -> None:
        """Clear the pattern detection cache."""
        self._cache.clear()


class BaseFieldHandler(ABC):
    """
    Abstract base class for field type handlers.

    All field handlers must inherit from this class and implement
    the `generate` method. Handlers can optionally implement
    `validate` for output validation.

    The base class provides:
    - Pattern detection integration
    - Configuration access
    - Locale-aware generation support
    - Retry logic for unique field handling

    Subclasses should implement:
    - generate(): Generate a value for the field
    - validate() (optional): Validate a generated value
    - get_supported_patterns() (optional): List patterns this handler supports

    Example:
        class DataHandler(BaseFieldHandler):
            '''Handler for Data field type.'''

            def generate(self, context: GenerationContext) -> str:
                if context.detected_pattern == FieldPattern.EMAIL:
                    return self.faker.email()
                return self.faker.text(max_nb_chars=context.max_length)

    Attributes:
        locale: The locale for data generation
        seed: Random seed for reproducibility
    """

    # Class-level Faker seeding (as per spec: use class-level for reproducibility)
    _faker_seeded: bool = False
    _faker_seed: Optional[int] = None

    def __init__(
        self,
        locale: str = "en_US",
        seed: Optional[int] = None,
        config: Optional["ResolvedConfig"] = None
    ):
        """
        Initialize the field handler.

        Args:
            locale: The locale for data generation (e.g., 'tr_TR', 'en_US')
            seed: Random seed for reproducibility
            config: Optional resolved configuration
        """
        self._locale = locale
        self._seed = seed
        self._config = config
        self._faker: Optional[Any] = None
        self._pattern_detector: Optional[PatternDetector] = None

        # Set class-level Faker seed if provided
        if seed is not None and not BaseFieldHandler._faker_seeded:
            self._set_faker_seed(seed)

    @classmethod
    def _set_faker_seed(cls, seed: int) -> None:
        """
        Set Faker seed at class level for reproducibility.

        As per spec: Use Faker.seed() at class level, not instance level.

        Args:
            seed: The random seed value
        """
        try:
            from faker import Faker
            Faker.seed(seed)
            cls._faker_seeded = True
            cls._faker_seed = seed
        except ImportError:
            pass

    @property
    def locale(self) -> str:
        """Get the locale for data generation."""
        return self._locale

    @property
    def seed(self) -> Optional[int]:
        """Get the random seed."""
        return self._seed

    @property
    def faker(self) -> Any:
        """
        Get the Faker instance (lazy loaded).

        Returns:
            Faker instance configured with the handler's locale.

        Raises:
            ImportError: If Faker is not installed.
        """
        if self._faker is None:
            try:
                from faker import Faker
                self._faker = Faker(self._locale)
            except ImportError:
                raise ImportError(
                    "Faker library not installed. "
                    "Install with: pip install 'faker>=40.0.0'"
                )
        return self._faker

    @property
    def pattern_detector(self) -> PatternDetector:
        """Get the pattern detector instance (lazy loaded)."""
        if self._pattern_detector is None:
            self._pattern_detector = PatternDetector(locale=self._locale)
        return self._pattern_detector

    @property
    def config(self) -> Optional["ResolvedConfig"]:
        """Get the resolved configuration."""
        return self._config

    @abstractmethod
    def generate(self, context: GenerationContext) -> Any:
        """
        Generate a value for the field.

        This is the main method that subclasses must implement.
        It should return an appropriate value based on the field type
        and the generation context.

        Args:
            context: The generation context with field info and settings

        Returns:
            The generated value appropriate for the field type

        Raises:
            GenerationError: If value generation fails

        Example:
            def generate(self, context: GenerationContext) -> str:
                if context.detected_pattern == FieldPattern.EMAIL:
                    return self.faker.email()
                return self.faker.word()
        """
        pass

    def validate(self, value: Any, context: GenerationContext) -> bool:
        """
        Validate a generated value.

        Subclasses can override this to provide field-specific validation.
        The default implementation always returns True.

        Args:
            value: The generated value to validate
            context: The generation context

        Returns:
            True if the value is valid, False otherwise
        """
        return True

    def generate_with_retry(
        self,
        context: GenerationContext,
        max_retries: int = 3
    ) -> Any:
        """
        Generate a value with retry logic for unique fields.

        This method wraps generate() with retry logic to handle
        unique field constraints. If generate() produces a duplicate
        value for a unique field, it will retry up to max_retries times.

        Args:
            context: The generation context
            max_retries: Maximum number of retry attempts

        Returns:
            The generated value

        Raises:
            GenerationError: If max_retries exceeded for unique field
        """
        for attempt in range(max_retries + 1):
            value = self.generate(context)

            # If not a unique field, return immediately
            if not context.is_unique:
                return value

            # For unique fields, check for duplicates
            if self._is_unique_value(value, context):
                return value

            # Value is a duplicate, retry with modified context
            if attempt < max_retries:
                # Modify seed for next attempt
                if context.seed is not None:
                    context = GenerationContext(
                        field_info=context.field_info,
                        doctype=context.doctype,
                        record_data=context.record_data,
                        record_cache=context.record_cache,
                        config=context.config,
                        locale=context.locale,
                        seed=context.seed + attempt + 1,
                        generation_method=context.generation_method,
                        batch_index=context.batch_index,
                        total_count=context.total_count,
                        parent_doctype=context.parent_doctype,
                        parent_name=context.parent_name,
                        field_override=context.field_override,
                        detected_pattern=context.detected_pattern,
                    )

        # If all retries failed, append a unique suffix
        return self._make_unique(value, context)

    def _is_unique_value(self, value: Any, context: GenerationContext) -> bool:
        """
        Check if a value is unique (not already used).

        Args:
            value: The value to check
            context: The generation context

        Returns:
            True if the value is unique
        """
        # Check against record cache if available
        if context.record_cache is None:
            return True

        # Get all existing records for this DocType
        existing_records = context.record_cache.get_records(context.doctype)

        # Check if value already exists
        for record in existing_records:
            if record.data.get(context.fieldname) == value:
                return False

        return True

    def _make_unique(self, value: Any, context: GenerationContext) -> Any:
        """
        Make a value unique by appending a suffix.

        Args:
            value: The value to make unique
            context: The generation context

        Returns:
            The modified unique value
        """
        import uuid

        if isinstance(value, str):
            # Append short UUID suffix
            suffix = uuid.uuid4().hex[:8]
            max_len = context.max_length
            if max_len and len(value) + 9 > max_len:
                value = value[:max_len - 9]
            return f"{value}-{suffix}"

        # For non-string values, return as-is
        return value

    def detect_pattern(self, context: GenerationContext) -> FieldPattern:
        """
        Detect the semantic pattern for a field.

        Args:
            context: The generation context

        Returns:
            The detected FieldPattern
        """
        return self.pattern_detector.detect(
            context.fieldname,
            context.fieldtype,
            context.locale
        )

    def get_supported_patterns(self) -> Set[FieldPattern]:
        """
        Get the patterns this handler supports.

        Subclasses can override this to indicate which semantic patterns
        they can generate appropriate data for.

        Returns:
            Set of FieldPattern values this handler supports
        """
        return {FieldPattern.GENERIC}

    def can_handle_pattern(self, pattern: FieldPattern) -> bool:
        """
        Check if this handler can generate data for a pattern.

        Args:
            pattern: The FieldPattern to check

        Returns:
            True if this handler supports the pattern
        """
        return pattern in self.get_supported_patterns()

    def __repr__(self) -> str:
        """String representation of the handler."""
        return f"{self.__class__.__name__}(locale='{self._locale}')"


class GenerationError(Exception):
    """
    Exception raised when field value generation fails.

    Attributes:
        fieldname: The field that failed to generate
        fieldtype: The field type
        message: Error message
        original_error: The underlying exception if any
    """

    def __init__(
        self,
        message: str,
        fieldname: Optional[str] = None,
        fieldtype: Optional[str] = None,
        original_error: Optional[Exception] = None
    ):
        """
        Initialize GenerationError.

        Args:
            message: Error message
            fieldname: The field that failed
            fieldtype: The field type
            original_error: The underlying exception
        """
        self.fieldname = fieldname
        self.fieldtype = fieldtype
        self.message = message
        self.original_error = original_error

        # Build full message
        full_message = message
        if fieldname:
            full_message = f"[{fieldname}] {message}"
        if fieldtype:
            full_message = f"({fieldtype}) {full_message}"

        super().__init__(full_message)

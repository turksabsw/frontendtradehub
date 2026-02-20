# Copyright (c) 2024, Mock Data Engine and contributors
# For license information, please see license.txt

"""
Faker Provider Module.

This module provides locale-aware Faker instance management for the Mock Data Engine.
It implements a tiered generation strategy where Faker is used as the fast, primary
data source, with LLM providers available for higher-quality generation when needed.

Key Features:
- Multi-locale support (tr_TR, en_US, de_DE, fr_FR, etc.)
- Class-level seeding for reproducibility across instances
- Instance pooling for efficient memory usage
- Locale fallback chains for missing locale support
- Provider method caching for performance

Usage:
    # Basic usage
    faker = FakerProvider('tr_TR')
    name = faker.name()
    email = faker.email()

    # With seed for reproducibility
    faker = FakerProvider('en_US', seed=42)

    # Using the provider pool (recommended for multi-locale scenarios)
    pool = FakerProviderPool(default_locale='tr_TR', seed=42)
    turkish_name = pool.get('tr_TR').name()
    german_name = pool.get('de_DE').name()

Seeding:
    Per the specification, Faker seeding is done at the class level using
    Faker.seed(), NOT at the instance level. This ensures reproducibility
    across all Faker instances when the same seed is used.

    FakerProvider.set_global_seed(42)  # Sets seed for all Faker instances

Note:
    This module requires the `faker` package (>=40.0.0):
    pip install "faker>=40.0.0"
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set, TYPE_CHECKING, Union

# Supported locales with full or partial Faker support
SUPPORTED_LOCALES: Dict[str, str] = {
    # Turkish (primary target)
    "tr_TR": "Turkish (Turkey)",
    # English variants
    "en_US": "English (United States)",
    "en_GB": "English (United Kingdom)",
    "en_AU": "English (Australia)",
    "en_CA": "English (Canada)",
    "en_IN": "English (India)",
    # European languages
    "de_DE": "German (Germany)",
    "de_AT": "German (Austria)",
    "de_CH": "German (Switzerland)",
    "fr_FR": "French (France)",
    "fr_BE": "French (Belgium)",
    "fr_CA": "French (Canada)",
    "es_ES": "Spanish (Spain)",
    "es_MX": "Spanish (Mexico)",
    "it_IT": "Italian (Italy)",
    "pt_BR": "Portuguese (Brazil)",
    "pt_PT": "Portuguese (Portugal)",
    "nl_NL": "Dutch (Netherlands)",
    "nl_BE": "Dutch (Belgium)",
    "pl_PL": "Polish (Poland)",
    "ru_RU": "Russian (Russia)",
    # Asian languages
    "ja_JP": "Japanese (Japan)",
    "ko_KR": "Korean (South Korea)",
    "zh_CN": "Chinese (Simplified)",
    "zh_TW": "Chinese (Traditional)",
    # Other
    "ar_SA": "Arabic (Saudi Arabia)",
    "he_IL": "Hebrew (Israel)",
}

# Fallback chain for locales with limited support
LOCALE_FALLBACKS: Dict[str, List[str]] = {
    "tr_TR": ["tr_TR", "en_US"],
    "de_AT": ["de_AT", "de_DE", "en_US"],
    "de_CH": ["de_CH", "de_DE", "en_US"],
    "fr_BE": ["fr_BE", "fr_FR", "en_US"],
    "fr_CA": ["fr_CA", "fr_FR", "en_US"],
    "nl_BE": ["nl_BE", "nl_NL", "en_US"],
    "en_AU": ["en_AU", "en_GB", "en_US"],
    "en_CA": ["en_CA", "en_US"],
    "en_IN": ["en_IN", "en_US"],
    "es_MX": ["es_MX", "es_ES", "en_US"],
    "pt_PT": ["pt_PT", "pt_BR", "en_US"],
    "zh_TW": ["zh_TW", "zh_CN", "en_US"],
}

# Default locale when none specified
DEFAULT_LOCALE: str = "en_US"


class FakerFeature(Enum):
    """
    Enumeration of Faker features/providers.

    Used to check locale support for specific features.
    """

    PERSON = "person"
    ADDRESS = "address"
    COMPANY = "company"
    PHONE_NUMBER = "phone_number"
    SSN = "ssn"  # National ID (TCKN for Turkish)
    BANK = "bank"
    DATE = "date_time"
    INTERNET = "internet"
    TEXT = "text"
    LOREM = "lorem"
    CURRENCY = "currency"
    JOB = "job"
    AUTOMOTIVE = "automotive"
    BARCODE = "barcode"


@dataclass
class LocaleInfo:
    """
    Information about a Faker locale.

    Attributes:
        code: The locale code (e.g., 'tr_TR')
        name: Human-readable name
        supported_features: Set of fully supported features
        partial_features: Set of partially supported features
        fallback_locale: Locale to use for unsupported features
    """

    code: str
    name: str
    supported_features: Set[FakerFeature] = field(default_factory=set)
    partial_features: Set[FakerFeature] = field(default_factory=set)
    fallback_locale: Optional[str] = None

    def supports_feature(self, feature: FakerFeature) -> bool:
        """Check if this locale fully supports a feature."""
        return feature in self.supported_features

    def partially_supports_feature(self, feature: FakerFeature) -> bool:
        """Check if this locale has partial support for a feature."""
        return feature in self.partial_features

    def has_any_support(self, feature: FakerFeature) -> bool:
        """Check if this locale has any support (full or partial) for a feature."""
        return feature in self.supported_features or feature in self.partial_features


# Turkish locale has comprehensive support per Faker documentation
TURKISH_LOCALE_INFO = LocaleInfo(
    code="tr_TR",
    name="Turkish (Turkey)",
    supported_features={
        FakerFeature.PERSON,
        FakerFeature.ADDRESS,
        FakerFeature.COMPANY,
        FakerFeature.PHONE_NUMBER,
        FakerFeature.SSN,  # TCKN support
        FakerFeature.BANK,
        FakerFeature.DATE,
        FakerFeature.INTERNET,
        FakerFeature.TEXT,
        FakerFeature.LOREM,
        FakerFeature.CURRENCY,
        FakerFeature.JOB,
        FakerFeature.AUTOMOTIVE,
        FakerFeature.BARCODE,
    },
    partial_features=set(),
    fallback_locale="en_US",
)


class FakerProvider:
    """
    Locale-aware Faker instance management.

    This class wraps the Faker library to provide:
    - Locale-specific data generation
    - Class-level seeding for reproducibility
    - Caching and lazy loading of Faker instances
    - Fallback handling for unsupported locales
    - Type-safe access to Faker methods

    The provider implements the tiered generation strategy where Faker
    is the fast, primary source (Tier 1) and LLM providers are used
    for higher-quality generation (Tier 2).

    Attributes:
        locale: The locale for data generation (e.g., 'tr_TR')
        seed: Optional seed for reproducibility

    Example:
        >>> faker = FakerProvider('tr_TR', seed=42)
        >>> faker.name()
        'Ahmet Yilmaz'
        >>> faker.email()
        'ahmet.yilmaz@example.com.tr'

    Note:
        Seeding is done at the class level per specification.
        Use FakerProvider.set_global_seed() for reproducible results.
    """

    # Class-level state for global seeding
    _global_seed: Optional[int] = None
    _seed_applied: bool = False

    def __init__(
        self,
        locale: str = DEFAULT_LOCALE,
        seed: Optional[int] = None,
    ):
        """
        Initialize the FakerProvider.

        Args:
            locale: The locale for data generation (default: en_US)
            seed: Optional seed for reproducibility. If provided and no global
                  seed has been set, this will be used as the global seed.

        Raises:
            ImportError: If the Faker library is not installed.
        """
        self._locale = self._normalize_locale(locale)
        self._seed = seed
        self._faker: Optional[Any] = None
        self._fallback_faker: Optional[Any] = None
        self._random: Optional[random.Random] = None

        # Apply seed if provided
        if seed is not None:
            self.set_global_seed(seed)

    @classmethod
    def set_global_seed(cls, seed: int) -> None:
        """
        Set the global seed for all Faker instances.

        Per the specification: Use Faker.seed() at class level for
        reproducibility, not instance-level seeding.

        This method sets the seed globally for all Faker instances,
        ensuring reproducible results across the entire application.

        Args:
            seed: The seed value for random number generation.

        Example:
            >>> FakerProvider.set_global_seed(42)
            >>> faker1 = FakerProvider('tr_TR')
            >>> faker2 = FakerProvider('en_US')
            >>> # Both will produce reproducible results
        """
        try:
            from faker import Faker

            Faker.seed(seed)
            cls._global_seed = seed
            cls._seed_applied = True
        except ImportError:
            pass

    @classmethod
    def get_global_seed(cls) -> Optional[int]:
        """Get the currently set global seed, if any."""
        return cls._global_seed

    @classmethod
    def reset_seed(cls) -> None:
        """Reset the global seed state."""
        cls._global_seed = None
        cls._seed_applied = False

    @property
    def locale(self) -> str:
        """Get the current locale."""
        return self._locale

    @property
    def seed(self) -> Optional[int]:
        """Get the instance seed."""
        return self._seed

    @property
    def faker(self) -> Any:
        """
        Get the Faker instance (lazy loaded).

        Returns:
            The Faker instance configured for this provider's locale.

        Raises:
            ImportError: If Faker is not installed.
        """
        if self._faker is None:
            self._faker = self._create_faker_instance(self._locale)
        return self._faker

    @property
    def fallback_faker(self) -> Any:
        """
        Get the fallback Faker instance (lazy loaded).

        Used when the primary locale doesn't support a specific feature.

        Returns:
            The Faker instance for the fallback locale (en_US).
        """
        if self._fallback_faker is None:
            fallback_locale = self._get_fallback_locale(self._locale)
            if fallback_locale != self._locale:
                self._fallback_faker = self._create_faker_instance(fallback_locale)
            else:
                self._fallback_faker = self.faker
        return self._fallback_faker

    @property
    def random(self) -> random.Random:
        """
        Get a seeded Random instance for this provider.

        Returns:
            A Random instance seeded with the global or instance seed.
        """
        if self._random is None:
            self._random = random.Random()
            if self._global_seed is not None:
                self._random.seed(self._global_seed)
            elif self._seed is not None:
                self._random.seed(self._seed)
        return self._random

    def _normalize_locale(self, locale: str) -> str:
        """
        Normalize a locale string.

        Handles common variations like 'tr-TR' -> 'tr_TR'.

        Args:
            locale: The locale string to normalize.

        Returns:
            Normalized locale string.
        """
        # Replace hyphens with underscores
        normalized = locale.replace("-", "_")

        # Handle lowercase locales (e.g., 'tr_tr' -> 'tr_TR')
        parts = normalized.split("_")
        if len(parts) == 2:
            normalized = f"{parts[0].lower()}_{parts[1].upper()}"
        elif len(parts) == 1:
            # Try to expand short codes
            short_to_full = {
                "tr": "tr_TR",
                "en": "en_US",
                "de": "de_DE",
                "fr": "fr_FR",
                "es": "es_ES",
                "it": "it_IT",
                "pt": "pt_BR",
                "ru": "ru_RU",
                "ja": "ja_JP",
                "ko": "ko_KR",
                "zh": "zh_CN",
                "ar": "ar_SA",
                "nl": "nl_NL",
                "pl": "pl_PL",
            }
            normalized = short_to_full.get(normalized.lower(), normalized)

        return normalized

    def _create_faker_instance(self, locale: str) -> Any:
        """
        Create a Faker instance for the specified locale.

        Args:
            locale: The locale for the Faker instance.

        Returns:
            A Faker instance configured for the locale.

        Raises:
            ImportError: If Faker is not installed.
        """
        try:
            from faker import Faker

            return Faker(locale)
        except ImportError:
            raise ImportError(
                "Faker library not installed. "
                "Install with: pip install 'faker>=40.0.0'"
            )

    def _get_fallback_locale(self, locale: str) -> str:
        """
        Get the fallback locale for a given locale.

        Args:
            locale: The primary locale.

        Returns:
            The fallback locale, or the original if no fallback needed.
        """
        fallbacks = LOCALE_FALLBACKS.get(locale, [])
        if fallbacks and len(fallbacks) > 1:
            return fallbacks[1]  # First fallback after the primary
        return DEFAULT_LOCALE

    def is_locale_supported(self, locale: Optional[str] = None) -> bool:
        """
        Check if a locale is supported by Faker.

        Args:
            locale: The locale to check (default: this provider's locale)

        Returns:
            True if the locale is supported.
        """
        check_locale = locale or self._locale
        return check_locale in SUPPORTED_LOCALES

    def get_locale_info(self) -> LocaleInfo:
        """
        Get information about the current locale.

        Returns:
            LocaleInfo for the current locale.
        """
        if self._locale == "tr_TR":
            return TURKISH_LOCALE_INFO

        # Default locale info for other locales
        return LocaleInfo(
            code=self._locale,
            name=SUPPORTED_LOCALES.get(self._locale, self._locale),
            supported_features=set(FakerFeature),
            partial_features=set(),
            fallback_locale=self._get_fallback_locale(self._locale),
        )

    # =========================================================================
    # Person/Name Generation
    # =========================================================================

    def name(self) -> str:
        """Generate a full name."""
        return self.faker.name()

    def first_name(self, gender: Optional[str] = None) -> str:
        """
        Generate a first name.

        Args:
            gender: Optional gender hint ('male', 'female', or None for random)

        Returns:
            A first name appropriate for the locale.
        """
        if gender and hasattr(self.faker, f"first_name_{gender}"):
            return getattr(self.faker, f"first_name_{gender}")()
        return self.faker.first_name()

    def last_name(self) -> str:
        """Generate a last name."""
        return self.faker.last_name()

    def prefix(self) -> str:
        """Generate a name prefix (Mr., Ms., etc.)."""
        return self.faker.prefix()

    def suffix(self) -> str:
        """Generate a name suffix (Jr., PhD, etc.)."""
        return self.faker.suffix()

    # =========================================================================
    # Contact Information
    # =========================================================================

    def email(self, domain: Optional[str] = None) -> str:
        """
        Generate an email address.

        Args:
            domain: Optional domain to use (e.g., 'company.com')

        Returns:
            An email address.
        """
        if domain:
            return self.faker.email(domain=domain)
        return self.faker.email()

    def phone_number(self) -> str:
        """Generate a phone number."""
        return self.faker.phone_number()

    def msisdn(self) -> str:
        """Generate an MSISDN (mobile number in international format)."""
        return self.faker.msisdn()

    # =========================================================================
    # Address Generation
    # =========================================================================

    def address(self) -> str:
        """Generate a full address."""
        return self.faker.address()

    def street_address(self) -> str:
        """Generate a street address."""
        return self.faker.street_address()

    def city(self) -> str:
        """Generate a city name."""
        return self.faker.city()

    def state(self) -> str:
        """Generate a state/province name."""
        try:
            return self.faker.state()
        except AttributeError:
            return self.fallback_faker.state()

    def country(self) -> str:
        """Generate a country name."""
        return self.faker.country()

    def postcode(self) -> str:
        """Generate a postal/zip code."""
        return self.faker.postcode()

    def building_number(self) -> str:
        """Generate a building number."""
        return self.faker.building_number()

    # =========================================================================
    # Company/Business Generation
    # =========================================================================

    def company(self) -> str:
        """Generate a company name."""
        return self.faker.company()

    def company_suffix(self) -> str:
        """Generate a company suffix (Inc., Ltd., etc.)."""
        return self.faker.company_suffix()

    def catch_phrase(self) -> str:
        """Generate a company catch phrase."""
        return self.faker.catch_phrase()

    def bs(self) -> str:
        """Generate a business speak phrase."""
        return self.faker.bs()

    def job(self) -> str:
        """Generate a job title."""
        return self.faker.job()

    # =========================================================================
    # Internet/Web Generation
    # =========================================================================

    def url(self, schemes: Optional[List[str]] = None) -> str:
        """Generate a URL."""
        return self.faker.url()

    def domain_name(self) -> str:
        """Generate a domain name."""
        return self.faker.domain_name()

    def user_name(self) -> str:
        """Generate a username."""
        return self.faker.user_name()

    def password(self, length: int = 12, special_chars: bool = True) -> str:
        """Generate a password."""
        return self.faker.password(
            length=length, special_chars=special_chars
        )

    def ipv4(self) -> str:
        """Generate an IPv4 address."""
        return self.faker.ipv4()

    def ipv6(self) -> str:
        """Generate an IPv6 address."""
        return self.faker.ipv6()

    def mac_address(self) -> str:
        """Generate a MAC address."""
        return self.faker.mac_address()

    # =========================================================================
    # Text Generation
    # =========================================================================

    def text(self, max_nb_chars: int = 200) -> str:
        """
        Generate a text paragraph.

        Args:
            max_nb_chars: Maximum number of characters.

        Returns:
            Generated text.
        """
        return self.faker.text(max_nb_chars=max_nb_chars)

    def sentence(self, nb_words: int = 6) -> str:
        """Generate a sentence."""
        return self.faker.sentence(nb_words=nb_words)

    def paragraph(self, nb_sentences: int = 3) -> str:
        """Generate a paragraph."""
        return self.faker.paragraph(nb_sentences=nb_sentences)

    def paragraphs(self, nb: int = 3) -> List[str]:
        """Generate multiple paragraphs."""
        return self.faker.paragraphs(nb=nb)

    def word(self) -> str:
        """Generate a single word."""
        return self.faker.word()

    def words(self, nb: int = 3) -> List[str]:
        """Generate multiple words."""
        return self.faker.words(nb=nb)

    # =========================================================================
    # Date/Time Generation
    # =========================================================================

    def date(self, pattern: str = "%Y-%m-%d") -> str:
        """Generate a date string."""
        return self.faker.date(pattern=pattern)

    def date_of_birth(
        self,
        minimum_age: int = 18,
        maximum_age: int = 90,
    ) -> Any:
        """
        Generate a date of birth.

        Args:
            minimum_age: Minimum age in years.
            maximum_age: Maximum age in years.

        Returns:
            A date object.
        """
        return self.faker.date_of_birth(
            minimum_age=minimum_age,
            maximum_age=maximum_age,
        )

    def date_time(self) -> Any:
        """Generate a datetime object."""
        return self.faker.date_time()

    def time(self, pattern: str = "%H:%M:%S") -> str:
        """Generate a time string."""
        return self.faker.time(pattern=pattern)

    def date_between(
        self,
        start_date: str = "-30y",
        end_date: str = "today",
    ) -> Any:
        """
        Generate a date between two dates.

        Args:
            start_date: Start date (e.g., '-30y', '-1y', 'today')
            end_date: End date (e.g., '+30y', 'today', '+1y')

        Returns:
            A date object between the specified dates.
        """
        return self.faker.date_between(
            start_date=start_date,
            end_date=end_date,
        )

    # =========================================================================
    # Numeric Generation
    # =========================================================================

    def random_int(
        self,
        min_value: int = 0,
        max_value: int = 9999,
        step: int = 1,
    ) -> int:
        """
        Generate a random integer.

        Args:
            min_value: Minimum value (inclusive).
            max_value: Maximum value (inclusive).
            step: Step between possible values.

        Returns:
            A random integer.
        """
        return self.faker.random_int(min=min_value, max=max_value, step=step)

    def random_float(
        self,
        min_value: float = 0.0,
        max_value: float = 100.0,
        right_digits: int = 2,
    ) -> float:
        """
        Generate a random float.

        Args:
            min_value: Minimum value.
            max_value: Maximum value.
            right_digits: Number of decimal places.

        Returns:
            A random float.
        """
        return float(
            self.faker.pydecimal(
                left_digits=None,
                right_digits=right_digits,
                min_value=min_value,
                max_value=max_value,
            )
        )

    def pydecimal(
        self,
        left_digits: Optional[int] = None,
        right_digits: int = 2,
        min_value: Optional[float] = None,
        max_value: Optional[float] = None,
        positive: bool = False,
    ) -> Any:
        """
        Generate a decimal number.

        Args:
            left_digits: Number of digits before decimal.
            right_digits: Number of digits after decimal.
            min_value: Minimum value.
            max_value: Maximum value.
            positive: If True, only positive values.

        Returns:
            A Decimal object.
        """
        return self.faker.pydecimal(
            left_digits=left_digits,
            right_digits=right_digits,
            min_value=min_value,
            max_value=max_value,
            positive=positive,
        )

    # =========================================================================
    # Financial/Banking
    # =========================================================================

    def iban(self) -> str:
        """Generate an IBAN."""
        return self.faker.iban()

    def bban(self) -> str:
        """Generate a BBAN (Basic Bank Account Number)."""
        return self.faker.bban()

    def credit_card_number(self, card_type: Optional[str] = None) -> str:
        """Generate a credit card number."""
        return self.faker.credit_card_number(card_type=card_type)

    def credit_card_expire(self) -> str:
        """Generate a credit card expiration date."""
        return self.faker.credit_card_expire()

    def currency(self) -> tuple:
        """Generate a currency code and name."""
        return self.faker.currency()

    def currency_code(self) -> str:
        """Generate a currency code."""
        return self.faker.currency_code()

    def price(
        self,
        minimum: float = 10.0,
        maximum: float = 1000.0,
    ) -> float:
        """
        Generate a price value.

        Args:
            minimum: Minimum price.
            maximum: Maximum price.

        Returns:
            A price as a float with 2 decimal places.
        """
        return round(
            self.faker.pyfloat(
                min_value=minimum,
                max_value=maximum,
                positive=True,
            ),
            2,
        )

    # =========================================================================
    # Turkish-Specific (TCKN, VKN, etc.)
    # =========================================================================

    def ssn(self) -> str:
        """
        Generate a national ID (SSN/TCKN).

        For Turkish locale (tr_TR), this generates a valid TCKN.
        For other locales, it generates the appropriate national ID.

        Returns:
            A national ID string.

        Note:
            For Turkish TCKN validation/generation with proper checksum,
            use the turkish validators module instead.
        """
        return self.faker.ssn()

    # =========================================================================
    # Miscellaneous
    # =========================================================================

    def uuid4(self) -> str:
        """Generate a UUID4."""
        return self.faker.uuid4()

    def color(self) -> str:
        """Generate a color name."""
        return self.faker.color()

    def hex_color(self) -> str:
        """Generate a hex color code."""
        return self.faker.hex_color()

    def rgb_color(self) -> str:
        """Generate an RGB color string."""
        return self.faker.rgb_color()

    def file_name(self, extension: Optional[str] = None) -> str:
        """Generate a file name."""
        return self.faker.file_name(extension=extension)

    def file_extension(self) -> str:
        """Generate a file extension."""
        return self.faker.file_extension()

    def mime_type(self) -> str:
        """Generate a MIME type."""
        return self.faker.mime_type()

    def ean13(self) -> str:
        """Generate an EAN-13 barcode."""
        return self.faker.ean13()

    def ean8(self) -> str:
        """Generate an EAN-8 barcode."""
        return self.faker.ean8()

    def isbn13(self) -> str:
        """Generate an ISBN-13."""
        return self.faker.isbn13()

    def image_url(
        self,
        width: int = 640,
        height: int = 480,
    ) -> str:
        """
        Generate an image placeholder URL.

        Args:
            width: Image width in pixels.
            height: Image height in pixels.

        Returns:
            A placeholder image URL.
        """
        return self.faker.image_url(width=width, height=height)

    def random_element(self, elements: List[Any]) -> Any:
        """
        Select a random element from a list.

        Args:
            elements: List of elements to choose from.

        Returns:
            A randomly selected element.
        """
        return self.faker.random_element(elements=elements)

    def random_elements(
        self,
        elements: List[Any],
        length: Optional[int] = None,
        unique: bool = False,
    ) -> List[Any]:
        """
        Select multiple random elements from a list.

        Args:
            elements: List of elements to choose from.
            length: Number of elements to select (default: random).
            unique: If True, no duplicates allowed.

        Returns:
            List of randomly selected elements.
        """
        return list(
            self.faker.random_elements(
                elements=elements,
                length=length,
                unique=unique,
            )
        )

    def boolean(self, chance_of_getting_true: int = 50) -> bool:
        """
        Generate a random boolean.

        Args:
            chance_of_getting_true: Percentage chance of True (0-100).

        Returns:
            A random boolean.
        """
        return self.faker.boolean(chance_of_getting_true=chance_of_getting_true)

    def __repr__(self) -> str:
        """String representation of the provider."""
        return f"FakerProvider(locale='{self._locale}', seed={self._seed})"


class FakerProviderPool:
    """
    Pool of FakerProvider instances for multi-locale scenarios.

    This class manages multiple FakerProvider instances, allowing efficient
    reuse across locales. It's recommended for scenarios where data needs
    to be generated in multiple locales.

    Example:
        >>> pool = FakerProviderPool(default_locale='tr_TR', seed=42)
        >>> turkish_name = pool.get('tr_TR').name()
        >>> german_name = pool.get('de_DE').name()

    The pool ensures that:
    - Provider instances are reused for efficiency
    - Global seeding is applied consistently
    - Default locale is used when none specified

    Attributes:
        default_locale: The default locale for the pool
        seed: The seed for reproducibility
    """

    def __init__(
        self,
        default_locale: str = DEFAULT_LOCALE,
        seed: Optional[int] = None,
    ):
        """
        Initialize the FakerProviderPool.

        Args:
            default_locale: Default locale to use when none specified.
            seed: Optional seed for reproducibility.
        """
        self._default_locale = default_locale
        self._seed = seed
        self._providers: Dict[str, FakerProvider] = {}

        # Apply global seed if provided
        if seed is not None:
            FakerProvider.set_global_seed(seed)

    @property
    def default_locale(self) -> str:
        """Get the default locale."""
        return self._default_locale

    @property
    def seed(self) -> Optional[int]:
        """Get the seed."""
        return self._seed

    def get(self, locale: Optional[str] = None) -> FakerProvider:
        """
        Get a FakerProvider for the specified locale.

        Args:
            locale: The locale to get a provider for (default: pool default)

        Returns:
            A FakerProvider instance for the locale.
        """
        effective_locale = locale or self._default_locale

        if effective_locale not in self._providers:
            self._providers[effective_locale] = FakerProvider(
                locale=effective_locale,
                seed=self._seed,
            )

        return self._providers[effective_locale]

    def get_locales(self) -> List[str]:
        """Get list of currently loaded locales."""
        return list(self._providers.keys())

    def clear(self) -> None:
        """Clear all cached providers."""
        self._providers.clear()

    def __repr__(self) -> str:
        """String representation of the pool."""
        return (
            f"FakerProviderPool(default_locale='{self._default_locale}', "
            f"loaded_locales={list(self._providers.keys())})"
        )


# Module-level singleton for convenience
_default_pool: Optional[FakerProviderPool] = None


def create_faker_provider(
    locale: str = DEFAULT_LOCALE,
    seed: Optional[int] = None,
) -> FakerProvider:
    """
    Factory function to create a FakerProvider.

    This is the recommended way to create FakerProvider instances
    as it ensures proper initialization.

    Args:
        locale: The locale for data generation.
        seed: Optional seed for reproducibility.

    Returns:
        A configured FakerProvider instance.

    Example:
        >>> faker = create_faker_provider('tr_TR', seed=42)
        >>> faker.name()
        'Ahmet Yilmaz'
    """
    return FakerProvider(locale=locale, seed=seed)


def get_faker_provider(
    locale: Optional[str] = None,
    seed: Optional[int] = None,
) -> FakerProvider:
    """
    Get a FakerProvider from the global pool.

    This function provides access to a shared pool of providers,
    which is more efficient when using multiple locales.

    Args:
        locale: The locale for data generation (default: en_US)
        seed: Optional seed (only used on first call to initialize pool)

    Returns:
        A FakerProvider from the global pool.

    Example:
        >>> # Get Turkish provider
        >>> tr_faker = get_faker_provider('tr_TR')
        >>> tr_faker.name()
        'Ahmet Yilmaz'

        >>> # Get German provider from same pool
        >>> de_faker = get_faker_provider('de_DE')
        >>> de_faker.name()
        'Hans Mueller'
    """
    global _default_pool

    if _default_pool is None:
        _default_pool = FakerProviderPool(
            default_locale=locale or DEFAULT_LOCALE,
            seed=seed,
        )
    elif seed is not None and _default_pool.seed != seed:
        # Seed changed, recreate pool
        _default_pool = FakerProviderPool(
            default_locale=locale or DEFAULT_LOCALE,
            seed=seed,
        )

    return _default_pool.get(locale)

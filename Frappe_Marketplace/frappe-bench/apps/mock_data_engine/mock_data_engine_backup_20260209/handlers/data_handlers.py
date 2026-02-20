# Copyright (c) 2024, Mock Data Engine and contributors
# For license information, please see license.txt

"""
Data Field Handlers Module.

This module provides handlers for the Data field type and all related
semantic patterns including email, phone, URL, and name patterns.

The DataHandler serves as the primary handler for Data fieldtype and
dispatches to pattern-specific generation logic based on detected patterns.

Handlers in this module:
- DataHandler: Main handler for Data field type (dispatches by pattern)
- EmailHandler: Email address generation
- PhoneHandler: Phone number generation
- MobileHandler: Mobile phone number generation
- URLHandler: URL generation
- WebsiteHandler: Website URL generation
- FirstNameHandler: First name generation
- LastNameHandler: Last name generation
- FullNameHandler: Full name generation
- CompanyHandler: Company name generation
- AddressHandler: Full address generation
- StreetHandler: Street address generation
- CityHandler: City name generation
- StateHandler: State/Province generation
- CountryHandler: Country name generation
- PostalCodeHandler: Postal/ZIP code generation
- TitleHandler: Title/Heading generation
- CodeHandler: Alphanumeric code generation
- ReferenceHandler: Reference number generation

Usage:
    from mock_data_engine.mock_data_engine.handlers.data_handlers import (
        DataHandler,
        EmailHandler,
        PhoneHandler,
    )

    # Using DataHandler directly
    handler = DataHandler(locale='tr_TR', seed=42)
    value = handler.generate(context)

    # Using pattern-specific handler
    email_handler = EmailHandler(locale='tr_TR', seed=42)
    email = email_handler.generate(context)
"""

from __future__ import annotations

import re
import uuid
from typing import Any, Dict, List, Optional, Set, TYPE_CHECKING

from mock_data_engine.mock_data_engine.handlers.base import (
    BaseFieldHandler,
    FieldPattern,
    GenerationContext,
    GenerationError,
)

if TYPE_CHECKING:
    from mock_data_engine.mock_data_engine.core.config_resolver import ResolvedConfig


class EmailHandler(BaseFieldHandler):
    """
    Handler for email field generation.

    Generates valid email addresses using Faker, with support for
    locale-specific email providers.

    Supported patterns:
        - FieldPattern.EMAIL

    Example:
        >>> handler = EmailHandler(locale='tr_TR')
        >>> handler.generate(context)
        'ahmet.yilmaz@example.com'
    """

    def generate(self, context: GenerationContext) -> str:
        """
        Generate an email address.

        Args:
            context: The generation context

        Returns:
            A valid email address string
        """
        max_length = context.max_length or 140

        # Check for override with specific domain
        if context.has_override():
            domain = context.get_override_value("email_domain")
            if domain:
                username = self.faker.user_name()
                email = f"{username}@{domain}"
                return email[:max_length]

        # Use Faker email generation
        email = self.faker.email()

        # Ensure email fits within max_length
        if len(email) > max_length:
            # Truncate username part while keeping domain valid
            parts = email.split("@")
            if len(parts) == 2:
                username, domain = parts
                available_length = max_length - len(domain) - 1
                if available_length > 3:
                    username = username[:available_length]
                    email = f"{username}@{domain}"
                else:
                    # Fallback to simple email
                    email = f"u{context.batch_index}@x.co"[:max_length]

        return email

    def validate(self, value: Any, context: GenerationContext) -> bool:
        """Validate email format."""
        if not isinstance(value, str):
            return False
        # Basic email validation
        return "@" in value and "." in value.split("@")[-1]

    def get_supported_patterns(self) -> Set[FieldPattern]:
        """Get supported patterns."""
        return {FieldPattern.EMAIL}


class PhoneHandler(BaseFieldHandler):
    """
    Handler for phone number generation.

    Generates phone numbers using Faker with locale-specific formatting.
    For Turkish locale, generates valid Turkish phone number formats.

    Supported patterns:
        - FieldPattern.PHONE

    Example:
        >>> handler = PhoneHandler(locale='tr_TR')
        >>> handler.generate(context)
        '+90 212 555 1234'
    """

    def generate(self, context: GenerationContext) -> str:
        """
        Generate a phone number.

        Args:
            context: The generation context

        Returns:
            A formatted phone number string
        """
        max_length = context.max_length or 20

        # Check for override with specific format
        if context.has_override():
            phone_format = context.get_override_value("phone_format")
            if phone_format:
                return self._generate_from_format(phone_format, max_length)

        # Use locale-specific generation
        if self._locale.lower().startswith("tr"):
            return self._generate_turkish_phone(max_length)

        # Standard Faker phone number
        phone = self.faker.phone_number()
        return phone[:max_length]

    def _generate_turkish_phone(self, max_length: int) -> str:
        """Generate a Turkish phone number."""
        # Turkish landline format: +90 2XX XXX XXXX or 0212 XXX XXXX
        area_codes = ["212", "216", "312", "232", "224", "262", "242", "322", "352"]
        area_code = self.faker.random_element(area_codes)
        number_part = "".join([str(self.faker.random_digit()) for _ in range(7)])
        phone = f"0{area_code} {number_part[:3]} {number_part[3:]}"
        return phone[:max_length]

    def _generate_from_format(self, phone_format: str, max_length: int) -> str:
        """Generate phone from a format string (# = digit)."""
        result = ""
        for char in phone_format:
            if char == "#":
                result += str(self.faker.random_digit())
            else:
                result += char
        return result[:max_length]

    def validate(self, value: Any, context: GenerationContext) -> bool:
        """Validate phone number format."""
        if not isinstance(value, str):
            return False
        # Basic validation: contains digits
        return bool(re.search(r"\d", value))

    def get_supported_patterns(self) -> Set[FieldPattern]:
        """Get supported patterns."""
        return {FieldPattern.PHONE}


class MobileHandler(BaseFieldHandler):
    """
    Handler for mobile phone number generation.

    Generates mobile phone numbers with locale-specific formatting.
    For Turkish locale, generates valid GSM numbers starting with 05XX.

    Supported patterns:
        - FieldPattern.MOBILE

    Example:
        >>> handler = MobileHandler(locale='tr_TR')
        >>> handler.generate(context)
        '0532 123 4567'
    """

    def generate(self, context: GenerationContext) -> str:
        """
        Generate a mobile phone number.

        Args:
            context: The generation context

        Returns:
            A formatted mobile phone number string
        """
        max_length = context.max_length or 20

        # Use locale-specific generation
        if self._locale.lower().startswith("tr"):
            return self._generate_turkish_mobile(max_length)

        # Standard Faker phone number
        phone = self.faker.phone_number()
        return phone[:max_length]

    def _generate_turkish_mobile(self, max_length: int) -> str:
        """Generate a Turkish mobile (GSM) number."""
        # Turkish mobile format: 05XX XXX XXXX
        gsm_prefixes = ["530", "531", "532", "533", "534", "535", "536", "537", "538", "539",
                        "540", "541", "542", "543", "544", "545", "546", "547", "548", "549",
                        "550", "551", "552", "553", "554", "555", "556", "557", "558", "559"]
        prefix = self.faker.random_element(gsm_prefixes)
        number_part = "".join([str(self.faker.random_digit()) for _ in range(7)])
        phone = f"0{prefix} {number_part[:3]} {number_part[3:]}"
        return phone[:max_length]

    def validate(self, value: Any, context: GenerationContext) -> bool:
        """Validate mobile number format."""
        if not isinstance(value, str):
            return False
        return bool(re.search(r"\d", value))

    def get_supported_patterns(self) -> Set[FieldPattern]:
        """Get supported patterns."""
        return {FieldPattern.MOBILE}


class URLHandler(BaseFieldHandler):
    """
    Handler for URL generation.

    Generates valid URLs using Faker.

    Supported patterns:
        - FieldPattern.URL

    Example:
        >>> handler = URLHandler(locale='en_US')
        >>> handler.generate(context)
        'https://www.example.com/path'
    """

    def generate(self, context: GenerationContext) -> str:
        """
        Generate a URL.

        Args:
            context: The generation context

        Returns:
            A valid URL string
        """
        max_length = context.max_length or 140

        # Check for override with specific base URL
        if context.has_override():
            base_url = context.get_override_value("base_url")
            if base_url:
                path = self.faker.uri_path()
                url = f"{base_url.rstrip('/')}/{path}"
                return url[:max_length]

        # Use Faker URL generation
        url = self.faker.url()
        return url[:max_length]

    def validate(self, value: Any, context: GenerationContext) -> bool:
        """Validate URL format."""
        if not isinstance(value, str):
            return False
        return value.startswith(("http://", "https://", "ftp://"))

    def get_supported_patterns(self) -> Set[FieldPattern]:
        """Get supported patterns."""
        return {FieldPattern.URL}


class WebsiteHandler(BaseFieldHandler):
    """
    Handler for website URL generation.

    Generates website URLs, typically company homepage URLs.

    Supported patterns:
        - FieldPattern.WEBSITE

    Example:
        >>> handler = WebsiteHandler(locale='en_US')
        >>> handler.generate(context)
        'https://www.acme-corp.com'
    """

    def generate(self, context: GenerationContext) -> str:
        """
        Generate a website URL.

        Args:
            context: The generation context

        Returns:
            A website URL string
        """
        max_length = context.max_length or 140

        # Check if company name is available in record data for consistency
        company_name = context.get_existing_value("company_name")
        if company_name:
            # Generate URL from company name
            slug = re.sub(r"[^a-zA-Z0-9]+", "-", company_name.lower()).strip("-")
            tld = self.faker.random_element([".com", ".net", ".org", ".co"])
            url = f"https://www.{slug}{tld}"
            return url[:max_length]

        # Use Faker URL generation for company
        domain = self.faker.domain_name()
        url = f"https://www.{domain}"
        return url[:max_length]

    def validate(self, value: Any, context: GenerationContext) -> bool:
        """Validate website URL format."""
        if not isinstance(value, str):
            return False
        return value.startswith(("http://", "https://"))

    def get_supported_patterns(self) -> Set[FieldPattern]:
        """Get supported patterns."""
        return {FieldPattern.WEBSITE}


class FirstNameHandler(BaseFieldHandler):
    """
    Handler for first name generation.

    Generates first names using Faker with locale support.

    Supported patterns:
        - FieldPattern.FIRST_NAME

    Example:
        >>> handler = FirstNameHandler(locale='tr_TR')
        >>> handler.generate(context)
        'Ahmet'
    """

    def generate(self, context: GenerationContext) -> str:
        """
        Generate a first name.

        Args:
            context: The generation context

        Returns:
            A first name string
        """
        max_length = context.max_length or 140

        # Check for gender override
        if context.has_override():
            gender = context.get_override_value("gender")
            if gender == "male":
                name = self.faker.first_name_male()
            elif gender == "female":
                name = self.faker.first_name_female()
            else:
                name = self.faker.first_name()
        else:
            name = self.faker.first_name()

        return name[:max_length]

    def validate(self, value: Any, context: GenerationContext) -> bool:
        """Validate first name format."""
        if not isinstance(value, str):
            return False
        return len(value.strip()) > 0

    def get_supported_patterns(self) -> Set[FieldPattern]:
        """Get supported patterns."""
        return {FieldPattern.FIRST_NAME}


class LastNameHandler(BaseFieldHandler):
    """
    Handler for last name generation.

    Generates last names using Faker with locale support.

    Supported patterns:
        - FieldPattern.LAST_NAME

    Example:
        >>> handler = LastNameHandler(locale='tr_TR')
        >>> handler.generate(context)
        'Yilmaz'
    """

    def generate(self, context: GenerationContext) -> str:
        """
        Generate a last name.

        Args:
            context: The generation context

        Returns:
            A last name string
        """
        max_length = context.max_length or 140
        name = self.faker.last_name()
        return name[:max_length]

    def validate(self, value: Any, context: GenerationContext) -> bool:
        """Validate last name format."""
        if not isinstance(value, str):
            return False
        return len(value.strip()) > 0

    def get_supported_patterns(self) -> Set[FieldPattern]:
        """Get supported patterns."""
        return {FieldPattern.LAST_NAME}


class FullNameHandler(BaseFieldHandler):
    """
    Handler for full name generation.

    Generates full names (first + last name) using Faker with locale support.
    Can use existing first_name/last_name values from record data for consistency.

    Supported patterns:
        - FieldPattern.FULL_NAME

    Example:
        >>> handler = FullNameHandler(locale='tr_TR')
        >>> handler.generate(context)
        'Ahmet Yilmaz'
    """

    def generate(self, context: GenerationContext) -> str:
        """
        Generate a full name.

        Args:
            context: The generation context

        Returns:
            A full name string
        """
        max_length = context.max_length or 140

        # Check if first_name/last_name already generated for consistency
        first_name = context.get_existing_value("first_name")
        last_name = context.get_existing_value("last_name")

        if first_name and last_name:
            full_name = f"{first_name} {last_name}"
        elif first_name:
            full_name = f"{first_name} {self.faker.last_name()}"
        elif last_name:
            full_name = f"{self.faker.first_name()} {last_name}"
        else:
            full_name = self.faker.name()

        return full_name[:max_length]

    def validate(self, value: Any, context: GenerationContext) -> bool:
        """Validate full name format."""
        if not isinstance(value, str):
            return False
        return len(value.strip()) > 0

    def get_supported_patterns(self) -> Set[FieldPattern]:
        """Get supported patterns."""
        return {FieldPattern.FULL_NAME}


class CompanyHandler(BaseFieldHandler):
    """
    Handler for company name generation.

    Generates company names using Faker with locale support.

    Supported patterns:
        - FieldPattern.COMPANY
        - FieldPattern.COMPANY_NAME

    Example:
        >>> handler = CompanyHandler(locale='tr_TR')
        >>> handler.generate(context)
        'Yilmaz Holding A.S.'
    """

    def generate(self, context: GenerationContext) -> str:
        """
        Generate a company name.

        Args:
            context: The generation context

        Returns:
            A company name string
        """
        max_length = context.max_length or 140

        # Check for industry override for more contextual names
        if context.has_override():
            industry = context.get_override_value("industry")
            if industry:
                # Generate industry-appropriate company name
                suffix = self._get_industry_suffix(industry)
                base_name = self.faker.last_name()
                company_name = f"{base_name} {suffix}"
                return company_name[:max_length]

        company_name = self.faker.company()
        return company_name[:max_length]

    def _get_industry_suffix(self, industry: str) -> str:
        """Get industry-appropriate company suffix."""
        industry_suffixes = {
            "technology": ["Tech", "Systems", "Software", "Solutions"],
            "retail": ["Store", "Market", "Retail", "Trading"],
            "manufacturing": ["Manufacturing", "Industries", "Production"],
            "finance": ["Financial", "Investment", "Capital", "Bank"],
            "healthcare": ["Medical", "Healthcare", "Clinic", "Hospital"],
        }
        suffixes = industry_suffixes.get(industry.lower(), ["Co.", "Inc.", "Ltd."])
        return self.faker.random_element(suffixes)

    def validate(self, value: Any, context: GenerationContext) -> bool:
        """Validate company name format."""
        if not isinstance(value, str):
            return False
        return len(value.strip()) > 0

    def get_supported_patterns(self) -> Set[FieldPattern]:
        """Get supported patterns."""
        return {FieldPattern.COMPANY, FieldPattern.COMPANY_NAME}


class AddressHandler(BaseFieldHandler):
    """
    Handler for full address generation.

    Generates complete addresses using Faker with locale support.

    Supported patterns:
        - FieldPattern.ADDRESS

    Example:
        >>> handler = AddressHandler(locale='tr_TR')
        >>> handler.generate(context)
        'Ataturk Cad. No: 123, Kadikoy, Istanbul'
    """

    def generate(self, context: GenerationContext) -> str:
        """
        Generate a full address.

        Args:
            context: The generation context

        Returns:
            A complete address string
        """
        max_length = context.max_length or 255

        # Check for existing address components
        street = context.get_existing_value("street")
        city = context.get_existing_value("city")
        state = context.get_existing_value("state")
        postal_code = context.get_existing_value("postal_code")

        if street and city:
            # Build from existing components
            address_parts = [street]
            if state:
                address_parts.append(state)
            address_parts.append(city)
            if postal_code:
                address_parts.append(postal_code)
            address = ", ".join(address_parts)
        else:
            address = self.faker.address()

        return address[:max_length]

    def validate(self, value: Any, context: GenerationContext) -> bool:
        """Validate address format."""
        if not isinstance(value, str):
            return False
        return len(value.strip()) > 0

    def get_supported_patterns(self) -> Set[FieldPattern]:
        """Get supported patterns."""
        return {FieldPattern.ADDRESS}


class StreetHandler(BaseFieldHandler):
    """
    Handler for street address generation.

    Generates street addresses using Faker with locale support.

    Supported patterns:
        - FieldPattern.STREET

    Example:
        >>> handler = StreetHandler(locale='tr_TR')
        >>> handler.generate(context)
        'Ataturk Caddesi No: 42'
    """

    def generate(self, context: GenerationContext) -> str:
        """
        Generate a street address.

        Args:
            context: The generation context

        Returns:
            A street address string
        """
        max_length = context.max_length or 140
        street = self.faker.street_address()
        return street[:max_length]

    def validate(self, value: Any, context: GenerationContext) -> bool:
        """Validate street address format."""
        if not isinstance(value, str):
            return False
        return len(value.strip()) > 0

    def get_supported_patterns(self) -> Set[FieldPattern]:
        """Get supported patterns."""
        return {FieldPattern.STREET}


class CityHandler(BaseFieldHandler):
    """
    Handler for city name generation.

    Generates city names using Faker with locale support.

    Supported patterns:
        - FieldPattern.CITY

    Example:
        >>> handler = CityHandler(locale='tr_TR')
        >>> handler.generate(context)
        'Istanbul'
    """

    def generate(self, context: GenerationContext) -> str:
        """
        Generate a city name.

        Args:
            context: The generation context

        Returns:
            A city name string
        """
        max_length = context.max_length or 140
        city = self.faker.city()
        return city[:max_length]

    def validate(self, value: Any, context: GenerationContext) -> bool:
        """Validate city name format."""
        if not isinstance(value, str):
            return False
        return len(value.strip()) > 0

    def get_supported_patterns(self) -> Set[FieldPattern]:
        """Get supported patterns."""
        return {FieldPattern.CITY}


class StateHandler(BaseFieldHandler):
    """
    Handler for state/province generation.

    Generates state or province names using Faker with locale support.

    Supported patterns:
        - FieldPattern.STATE

    Example:
        >>> handler = StateHandler(locale='en_US')
        >>> handler.generate(context)
        'California'
    """

    def generate(self, context: GenerationContext) -> str:
        """
        Generate a state/province name.

        Args:
            context: The generation context

        Returns:
            A state or province name string
        """
        max_length = context.max_length or 140

        # Try state, fall back to city for locales without states
        try:
            state = self.faker.state()
        except AttributeError:
            # Some locales don't have states
            state = self.faker.city()

        return state[:max_length]

    def validate(self, value: Any, context: GenerationContext) -> bool:
        """Validate state name format."""
        if not isinstance(value, str):
            return False
        return len(value.strip()) > 0

    def get_supported_patterns(self) -> Set[FieldPattern]:
        """Get supported patterns."""
        return {FieldPattern.STATE}


class CountryHandler(BaseFieldHandler):
    """
    Handler for country name generation.

    Generates country names using Faker with locale support.

    Supported patterns:
        - FieldPattern.COUNTRY

    Example:
        >>> handler = CountryHandler(locale='tr_TR')
        >>> handler.generate(context)
        'Turkiye'
    """

    def generate(self, context: GenerationContext) -> str:
        """
        Generate a country name.

        Args:
            context: The generation context

        Returns:
            A country name string
        """
        max_length = context.max_length or 140
        country = self.faker.country()
        return country[:max_length]

    def validate(self, value: Any, context: GenerationContext) -> bool:
        """Validate country name format."""
        if not isinstance(value, str):
            return False
        return len(value.strip()) > 0

    def get_supported_patterns(self) -> Set[FieldPattern]:
        """Get supported patterns."""
        return {FieldPattern.COUNTRY}


class PostalCodeHandler(BaseFieldHandler):
    """
    Handler for postal/ZIP code generation.

    Generates postal codes using Faker with locale support.

    Supported patterns:
        - FieldPattern.POSTAL_CODE
        - FieldPattern.ZIP_CODE

    Example:
        >>> handler = PostalCodeHandler(locale='tr_TR')
        >>> handler.generate(context)
        '34100'
    """

    def generate(self, context: GenerationContext) -> str:
        """
        Generate a postal code.

        Args:
            context: The generation context

        Returns:
            A postal code string
        """
        max_length = context.max_length or 20
        postal_code = self.faker.postcode()
        return postal_code[:max_length]

    def validate(self, value: Any, context: GenerationContext) -> bool:
        """Validate postal code format."""
        if not isinstance(value, str):
            return False
        return len(value.strip()) > 0

    def get_supported_patterns(self) -> Set[FieldPattern]:
        """Get supported patterns."""
        return {FieldPattern.POSTAL_CODE, FieldPattern.ZIP_CODE}


class TitleHandler(BaseFieldHandler):
    """
    Handler for title/heading generation.

    Generates short titles or headings using Faker.

    Supported patterns:
        - FieldPattern.TITLE

    Example:
        >>> handler = TitleHandler(locale='en_US')
        >>> handler.generate(context)
        'Product Launch Campaign'
    """

    def generate(self, context: GenerationContext) -> str:
        """
        Generate a title.

        Args:
            context: The generation context

        Returns:
            A title string
        """
        max_length = context.max_length or 140

        # Check for title type override
        if context.has_override():
            title_type = context.get_override_value("title_type")
            if title_type == "catch_phrase":
                title = self.faker.catch_phrase()
            elif title_type == "bs":
                title = self.faker.bs().title()
            elif title_type == "job":
                title = self.faker.job()
            else:
                title = self.faker.sentence(nb_words=4).rstrip(".")
        else:
            # Generate a short phrase as title
            title = self.faker.sentence(nb_words=4).rstrip(".")

        return title[:max_length]

    def validate(self, value: Any, context: GenerationContext) -> bool:
        """Validate title format."""
        if not isinstance(value, str):
            return False
        return len(value.strip()) > 0

    def get_supported_patterns(self) -> Set[FieldPattern]:
        """Get supported patterns."""
        return {FieldPattern.TITLE}


class CodeHandler(BaseFieldHandler):
    """
    Handler for code/identifier generation.

    Generates alphanumeric codes for various purposes.

    Supported patterns:
        - FieldPattern.CODE
        - FieldPattern.SKU
        - FieldPattern.SERIAL
        - FieldPattern.REFERENCE

    Example:
        >>> handler = CodeHandler(locale='en_US')
        >>> handler.generate(context)
        'PRD-2024-A1B2C3'
    """

    def generate(self, context: GenerationContext) -> str:
        """
        Generate a code/identifier.

        Args:
            context: The generation context

        Returns:
            An alphanumeric code string
        """
        max_length = context.max_length or 20

        # Check for code format override
        if context.has_override():
            code_format = context.get_override_value("code_format")
            if code_format:
                return self._generate_from_format(code_format, max_length)

            code_prefix = context.get_override_value("code_prefix", "")
            code_length = context.get_override_value("code_length", 8)
        else:
            code_prefix = ""
            code_length = 8

        # Determine code pattern based on detected pattern
        pattern = context.detected_pattern

        if pattern == FieldPattern.SKU:
            # SKU format: PREFIX-XXXX-XXXX
            code = self._generate_sku()
        elif pattern == FieldPattern.SERIAL:
            # Serial format: XXXXXXXXXX (alphanumeric)
            code = self._generate_serial(code_length)
        elif pattern == FieldPattern.REFERENCE:
            # Reference format: REF-YYYYMMDD-XXXXX
            code = self._generate_reference()
        else:
            # Generic code format
            code = self._generate_generic_code(code_prefix, code_length)

        return code[:max_length]

    def _generate_sku(self) -> str:
        """Generate SKU-style code."""
        prefix = "".join(self.faker.random_letters(3)).upper()
        part1 = "".join([str(self.faker.random_digit()) for _ in range(4)])
        part2 = "".join([str(self.faker.random_digit()) for _ in range(4)])
        return f"{prefix}-{part1}-{part2}"

    def _generate_serial(self, length: int) -> str:
        """Generate serial number."""
        chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
        return "".join(self.faker.random_element(chars) for _ in range(length))

    def _generate_reference(self) -> str:
        """Generate reference number."""
        date_part = self.faker.date_this_year().strftime("%Y%m%d")
        random_part = "".join([str(self.faker.random_digit()) for _ in range(5)])
        return f"REF-{date_part}-{random_part}"

    def _generate_generic_code(self, prefix: str, length: int) -> str:
        """Generate generic alphanumeric code."""
        chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
        random_part = "".join(self.faker.random_element(chars) for _ in range(length))
        if prefix:
            return f"{prefix}-{random_part}"
        return random_part

    def _generate_from_format(self, code_format: str, max_length: int) -> str:
        """Generate code from format string (# = digit, @ = letter)."""
        result = ""
        for char in code_format:
            if char == "#":
                result += str(self.faker.random_digit())
            elif char == "@":
                result += self.faker.random_letter().upper()
            else:
                result += char
        return result[:max_length]

    def validate(self, value: Any, context: GenerationContext) -> bool:
        """Validate code format."""
        if not isinstance(value, str):
            return False
        return len(value.strip()) > 0

    def get_supported_patterns(self) -> Set[FieldPattern]:
        """Get supported patterns."""
        return {FieldPattern.CODE, FieldPattern.SKU, FieldPattern.SERIAL, FieldPattern.REFERENCE}


class DataHandler(BaseFieldHandler):
    """
    Main handler for Data field type.

    This handler serves as the primary handler for Frappe's Data fieldtype.
    It dispatches to pattern-specific handlers when a semantic pattern is
    detected, or generates generic text for unmatched fields.

    The handler uses the PatternDetector to identify field semantics and
    delegates to appropriate sub-handlers for:
    - Email addresses
    - Phone numbers
    - URLs and websites
    - Names (first, last, full)
    - Company names
    - Addresses and address components
    - Codes and identifiers

    If no specific pattern is detected, generates appropriate random text
    that fits within the field's length constraints.

    Example:
        >>> handler = DataHandler(locale='tr_TR', seed=42)
        >>> # For an email field
        >>> handler.generate(email_context)
        'ahmet.yilmaz@example.com'
        >>> # For a generic data field
        >>> handler.generate(generic_context)
        'Lorem ipsum dolor sit amet'
    """

    # Pattern to handler class mapping
    PATTERN_HANDLERS = {
        FieldPattern.EMAIL: EmailHandler,
        FieldPattern.PHONE: PhoneHandler,
        FieldPattern.MOBILE: MobileHandler,
        FieldPattern.URL: URLHandler,
        FieldPattern.WEBSITE: WebsiteHandler,
        FieldPattern.FIRST_NAME: FirstNameHandler,
        FieldPattern.LAST_NAME: LastNameHandler,
        FieldPattern.FULL_NAME: FullNameHandler,
        FieldPattern.COMPANY: CompanyHandler,
        FieldPattern.COMPANY_NAME: CompanyHandler,
        FieldPattern.ADDRESS: AddressHandler,
        FieldPattern.STREET: StreetHandler,
        FieldPattern.CITY: CityHandler,
        FieldPattern.STATE: StateHandler,
        FieldPattern.COUNTRY: CountryHandler,
        FieldPattern.POSTAL_CODE: PostalCodeHandler,
        FieldPattern.ZIP_CODE: PostalCodeHandler,
        FieldPattern.TITLE: TitleHandler,
        FieldPattern.CODE: CodeHandler,
        FieldPattern.SKU: CodeHandler,
        FieldPattern.SERIAL: CodeHandler,
        FieldPattern.REFERENCE: CodeHandler,
    }

    def __init__(
        self,
        locale: str = "en_US",
        seed: Optional[int] = None,
        config: Optional["ResolvedConfig"] = None
    ):
        """
        Initialize the DataHandler.

        Args:
            locale: The locale for data generation
            seed: Random seed for reproducibility
            config: Optional resolved configuration
        """
        super().__init__(locale=locale, seed=seed, config=config)
        # Handler instance cache
        self._handler_cache: Dict[FieldPattern, BaseFieldHandler] = {}

    def generate(self, context: GenerationContext) -> str:
        """
        Generate a value for a Data field.

        This method dispatches to pattern-specific handlers when a semantic
        pattern is detected, or generates generic text otherwise.

        Args:
            context: The generation context

        Returns:
            A string value appropriate for the field

        Raises:
            GenerationError: If generation fails
        """
        # Check for override with fixed value
        if context.has_override():
            fixed_value = context.get_override_value("fixed_value")
            if fixed_value is not None:
                return str(fixed_value)[:context.max_length]

        # Get detected pattern
        pattern = context.detected_pattern
        if pattern is None:
            pattern = self.detect_pattern(context)

        # Try pattern-specific handler
        if pattern != FieldPattern.GENERIC and pattern in self.PATTERN_HANDLERS:
            handler = self._get_pattern_handler(pattern)
            try:
                return handler.generate(context)
            except Exception:
                # Fall back to generic generation on handler error
                pass

        # Generic text generation
        return self._generate_generic_text(context)

    def _get_pattern_handler(self, pattern: FieldPattern) -> BaseFieldHandler:
        """
        Get or create a handler for a pattern.

        Args:
            pattern: The FieldPattern to handle

        Returns:
            The appropriate handler instance
        """
        if pattern not in self._handler_cache:
            handler_class = self.PATTERN_HANDLERS.get(pattern)
            if handler_class:
                self._handler_cache[pattern] = handler_class(
                    locale=self._locale,
                    seed=self._seed,
                    config=self._config
                )
        return self._handler_cache.get(pattern)

    def _generate_generic_text(self, context: GenerationContext) -> str:
        """
        Generate generic text for Data fields without specific patterns.

        Args:
            context: The generation context

        Returns:
            A generic text string
        """
        max_length = context.max_length or 140

        # For very short fields, use a word
        if max_length <= 20:
            text = self.faker.word().capitalize()
        # For short fields, use a short phrase
        elif max_length <= 50:
            text = self.faker.sentence(nb_words=3).rstrip(".")
        # For medium fields, use a sentence
        elif max_length <= 100:
            text = self.faker.sentence(nb_words=6).rstrip(".")
        # For longer fields, use longer text
        else:
            text = self.faker.text(max_nb_chars=min(max_length, 200))

        return text[:max_length]

    def validate(self, value: Any, context: GenerationContext) -> bool:
        """
        Validate a Data field value.

        Args:
            value: The value to validate
            context: The generation context

        Returns:
            True if valid, False otherwise
        """
        if not isinstance(value, str):
            return False

        # Check length constraint
        max_length = context.max_length or 140
        if len(value) > max_length:
            return False

        # Pattern-specific validation
        pattern = context.detected_pattern
        if pattern and pattern in self.PATTERN_HANDLERS:
            handler = self._get_pattern_handler(pattern)
            if handler:
                return handler.validate(value, context)

        return True

    def get_supported_patterns(self) -> Set[FieldPattern]:
        """Get all patterns supported by this handler."""
        return set(self.PATTERN_HANDLERS.keys()) | {FieldPattern.GENERIC}


# Export all handler classes
__all__ = [
    # Main handler
    "DataHandler",
    # Pattern-specific handlers
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
]

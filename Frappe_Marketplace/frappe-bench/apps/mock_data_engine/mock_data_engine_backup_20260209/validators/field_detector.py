# Copyright (c) 2024, Mock Data Engine and contributors
# For license information, please see license.txt

"""
Turkish Field Detector Module.

This module provides automatic detection of Turkish-specific field types
based on field name patterns. It analyzes field names using regex patterns
to identify fields that should be populated with Turkish-specific data like
TCKN (citizen ID), VKN (tax ID), IBAN, phone numbers, etc.

The detector follows a priority-based matching system:
1. Exact matches (e.g., "tckn" exactly)
2. Suffix matches (e.g., "customer_tckn")
3. Contains matches (e.g., "tc_kimlik_no")
4. Semantic inference from field type

Usage:
    from mock_data_engine.mock_data_engine.validators.field_detector import (
        TurkishFieldDetector,
        detect_turkish_field,
    )

    # Using the class
    detector = TurkishFieldDetector()
    field_type = detector.detect("tckn_no", "Data")  # Returns "tckn"
    field_type = detector.detect("vergi_no", "Data")  # Returns "vkn"
    field_type = detector.detect("customer_iban", "Data")  # Returns "iban"

    # Using the convenience function
    field_type = detect_turkish_field("telefon", "Data")  # Returns "phone"

Supported Turkish Field Types:
    - tckn: Turkish Citizen Identity Number (T.C. Kimlik Numarasi)
    - vkn: Tax Identification Number (Vergi Kimlik Numarasi)
    - iban: Turkish IBAN (International Bank Account Number)
    - phone: Turkish mobile phone number
    - landline: Turkish landline phone number
    - city: Turkish city (il)
    - postal_code: Turkish postal code
    - address: Turkish address
    - neighborhood: Turkish neighborhood (mahalle)
    - district: Turkish district (ilce)
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional, Pattern, Set, Tuple


class TurkishFieldType(Enum):
    """
    Enumeration of Turkish-specific field types.

    These represent the different types of Turkish data that can be
    automatically detected from field names.
    """

    # Identity/Tax Numbers
    TCKN = "tckn"
    VKN = "vkn"

    # Banking
    IBAN = "iban"
    BANK_ACCOUNT = "bank_account"

    # Contact
    PHONE = "phone"
    MOBILE = "mobile"
    LANDLINE = "landline"
    FAX = "fax"

    # Address Components
    ADDRESS = "address"
    CITY = "city"
    DISTRICT = "district"
    NEIGHBORHOOD = "neighborhood"
    POSTAL_CODE = "postal_code"
    STREET = "street"

    # Vehicle/Plate
    PLATE_CODE = "plate_code"

    # Not a Turkish-specific field
    NONE = "none"


@dataclass
class FieldPatternRule:
    """
    A pattern matching rule for field detection.

    Attributes:
        field_type: The TurkishFieldType this rule detects
        pattern: Compiled regex pattern
        priority: Lower number = higher priority (matched first)
        description: Human-readable description of the pattern
    """

    field_type: TurkishFieldType
    pattern: Pattern[str]
    priority: int
    description: str = ""


# Pattern rules for Turkish field detection
# Format: (field_type, regex_pattern, priority, description)
# Lower priority = higher precedence (matched first)
TURKISH_FIELD_PATTERNS: List[Tuple[TurkishFieldType, str, int, str]] = [
    # TCKN patterns (highest priority)
    (TurkishFieldType.TCKN, r"^tckn$", 1, "Exact match: tckn"),
    (TurkishFieldType.TCKN, r"^tc_?kimlik$", 1, "TC Kimlik"),
    (TurkishFieldType.TCKN, r"^tc_?no$", 1, "TC No"),
    (TurkishFieldType.TCKN, r"tckn[_\s]?(no|number|numarasi)?$", 2, "TCKN with suffix"),
    (TurkishFieldType.TCKN, r"tc[_\s]?kimlik[_\s]?(no|numarasi)?$", 2, "TC Kimlik No"),
    (TurkishFieldType.TCKN, r"kimlik[_\s]?(no|numarasi)$", 3, "Kimlik No"),
    (TurkishFieldType.TCKN, r"citizen[_\s]?(id|no|number)$", 3, "Citizen ID"),
    (TurkishFieldType.TCKN, r"vatandas[_\s]?(no|numarasi)?$", 3, "Vatandas No"),
    (TurkishFieldType.TCKN, r"(customer|employee|person)[_\s]?tckn$", 3, "Entity TCKN"),

    # VKN patterns
    (TurkishFieldType.VKN, r"^vkn$", 1, "Exact match: vkn"),
    (TurkishFieldType.VKN, r"^vergi[_\s]?no$", 1, "Vergi No"),
    (TurkishFieldType.VKN, r"vkn[_\s]?(no|number)?$", 2, "VKN with suffix"),
    (TurkishFieldType.VKN, r"vergi[_\s]?kimlik[_\s]?(no|numarasi)?$", 2, "Vergi Kimlik No"),
    (TurkishFieldType.VKN, r"tax[_\s]?(id|no|number)$", 3, "Tax ID/Number"),
    (TurkishFieldType.VKN, r"(company|firma|sirket)[_\s]?vkn$", 3, "Company VKN"),
    (TurkishFieldType.VKN, r"kurumsal[_\s]?(vergi|vkn)$", 3, "Kurumsal Vergi"),

    # IBAN patterns
    (TurkishFieldType.IBAN, r"^iban$", 1, "Exact match: iban"),
    (TurkishFieldType.IBAN, r"^tr_?iban$", 1, "TR IBAN"),
    (TurkishFieldType.IBAN, r"iban[_\s]?(no|number)?$", 2, "IBAN with suffix"),
    (TurkishFieldType.IBAN, r"hesap[_\s]?no$", 3, "Hesap No (account number)"),
    (TurkishFieldType.IBAN, r"bank[_\s]?iban$", 3, "Bank IBAN"),
    (TurkishFieldType.IBAN, r"(banka|bank)[_\s]?hesap[_\s]?(no|numarasi)?$", 3, "Banka Hesap No"),

    # Bank Account (non-IBAN)
    (TurkishFieldType.BANK_ACCOUNT, r"^bank[_\s]?account$", 2, "Bank Account"),
    (TurkishFieldType.BANK_ACCOUNT, r"hesap[_\s]?numarasi$", 3, "Hesap Numarasi"),

    # Mobile Phone patterns
    (TurkishFieldType.MOBILE, r"^gsm$", 1, "Exact match: gsm"),
    (TurkishFieldType.MOBILE, r"^cep$", 1, "Exact match: cep"),
    (TurkishFieldType.MOBILE, r"^mobile$", 1, "Exact match: mobile"),
    (TurkishFieldType.MOBILE, r"cep[_\s]?(tel|telefon|no)?$", 2, "Cep Telefon"),
    (TurkishFieldType.MOBILE, r"gsm[_\s]?(no|number)?$", 2, "GSM No"),
    (TurkishFieldType.MOBILE, r"mobile[_\s]?(phone|no|number)?$", 2, "Mobile Phone"),
    (TurkishFieldType.MOBILE, r"cell[_\s]?(phone|no)?$", 3, "Cell Phone"),

    # General Phone patterns
    (TurkishFieldType.PHONE, r"^telefon$", 1, "Exact match: telefon"),
    (TurkishFieldType.PHONE, r"^tel$", 1, "Exact match: tel"),
    (TurkishFieldType.PHONE, r"^phone$", 1, "Exact match: phone"),
    (TurkishFieldType.PHONE, r"telefon[_\s]?(no|numarasi)?$", 2, "Telefon No"),
    (TurkishFieldType.PHONE, r"phone[_\s]?(no|number)?$", 2, "Phone Number"),
    (TurkishFieldType.PHONE, r"(contact|iletisim)[_\s]?(tel|phone)?$", 3, "Contact Phone"),

    # Landline patterns
    (TurkishFieldType.LANDLINE, r"^sabit$", 1, "Exact match: sabit"),
    (TurkishFieldType.LANDLINE, r"sabit[_\s]?(tel|telefon|hat)?$", 2, "Sabit Telefon"),
    (TurkishFieldType.LANDLINE, r"landline$", 2, "Landline"),
    (TurkishFieldType.LANDLINE, r"work[_\s]?(phone|tel)$", 3, "Work Phone"),
    (TurkishFieldType.LANDLINE, r"is[_\s]?telefon(u|i)?$", 3, "Is Telefonu"),

    # Fax patterns
    (TurkishFieldType.FAX, r"^fax$", 1, "Exact match: fax"),
    (TurkishFieldType.FAX, r"^faks$", 1, "Exact match: faks"),
    (TurkishFieldType.FAX, r"fax[_\s]?(no|number)?$", 2, "Fax No"),
    (TurkishFieldType.FAX, r"faks[_\s]?(no|numarasi)?$", 2, "Faks No"),

    # City patterns
    (TurkishFieldType.CITY, r"^sehir$", 1, "Exact match: sehir"),
    (TurkishFieldType.CITY, r"^il$", 1, "Exact match: il"),
    (TurkishFieldType.CITY, r"^city$", 1, "Exact match: city"),
    (TurkishFieldType.CITY, r"sehir[_\s]?(adi|ismi)?$", 2, "Sehir Adi"),
    (TurkishFieldType.CITY, r"il[_\s]?(adi)?$", 2, "Il Adi"),
    (TurkishFieldType.CITY, r"(turkish|tr)[_\s]?city$", 3, "Turkish City"),

    # District patterns
    (TurkishFieldType.DISTRICT, r"^ilce$", 1, "Exact match: ilce"),
    (TurkishFieldType.DISTRICT, r"^district$", 1, "Exact match: district"),
    (TurkishFieldType.DISTRICT, r"ilce[_\s]?(adi|ismi)?$", 2, "Ilce Adi"),
    (TurkishFieldType.DISTRICT, r"(semt|bolge)$", 3, "Semt/Bolge"),

    # Neighborhood patterns
    (TurkishFieldType.NEIGHBORHOOD, r"^mahalle$", 1, "Exact match: mahalle"),
    (TurkishFieldType.NEIGHBORHOOD, r"mahalle[_\s]?(adi|ismi)?$", 2, "Mahalle Adi"),
    (TurkishFieldType.NEIGHBORHOOD, r"neighborhood$", 2, "Neighborhood"),

    # Postal Code patterns
    (TurkishFieldType.POSTAL_CODE, r"^posta[_\s]?kodu$", 1, "Posta Kodu"),
    (TurkishFieldType.POSTAL_CODE, r"^postal[_\s]?code$", 1, "Postal Code"),
    (TurkishFieldType.POSTAL_CODE, r"^pk$", 1, "Exact match: pk"),
    (TurkishFieldType.POSTAL_CODE, r"(turkish|tr)[_\s]?postal$", 2, "Turkish Postal"),
    (TurkishFieldType.POSTAL_CODE, r"zip[_\s]?(code)?$", 3, "Zip Code"),

    # Street patterns
    (TurkishFieldType.STREET, r"^sokak$", 1, "Exact match: sokak"),
    (TurkishFieldType.STREET, r"^cadde$", 1, "Exact match: cadde"),
    (TurkishFieldType.STREET, r"sokak[_\s]?(adi)?$", 2, "Sokak Adi"),
    (TurkishFieldType.STREET, r"cadde[_\s]?(adi)?$", 2, "Cadde Adi"),
    (TurkishFieldType.STREET, r"(street|road)[_\s]?(name)?$", 3, "Street Name"),

    # Address patterns
    (TurkishFieldType.ADDRESS, r"^adres$", 1, "Exact match: adres"),
    (TurkishFieldType.ADDRESS, r"^address$", 1, "Exact match: address"),
    (TurkishFieldType.ADDRESS, r"(full|tam|acik)[_\s]?adres$", 2, "Full Address"),
    (TurkishFieldType.ADDRESS, r"(turkish|tr)[_\s]?address$", 2, "Turkish Address"),
    (TurkishFieldType.ADDRESS, r"(teslimat|delivery)[_\s]?adres(i)?$", 3, "Delivery Address"),
    (TurkishFieldType.ADDRESS, r"(fatura|billing)[_\s]?adres(i)?$", 3, "Billing Address"),

    # Plate Code patterns
    (TurkishFieldType.PLATE_CODE, r"^plaka$", 1, "Exact match: plaka"),
    (TurkishFieldType.PLATE_CODE, r"^plate$", 1, "Exact match: plate"),
    (TurkishFieldType.PLATE_CODE, r"plaka[_\s]?(kodu|no)?$", 2, "Plaka Kodu"),
    (TurkishFieldType.PLATE_CODE, r"plate[_\s]?(code|no)?$", 2, "Plate Code"),
    (TurkishFieldType.PLATE_CODE, r"il[_\s]?plaka$", 3, "Il Plaka"),
]


class TurkishFieldDetector:
    """
    Detector for Turkish-specific field types based on field name patterns.

    This class analyzes field names using regex patterns to automatically
    detect what type of Turkish data should be generated for a field.
    It supports TCKN, VKN, IBAN, phone numbers, addresses, and more.

    The detector uses a priority-based matching system where lower priority
    numbers indicate higher precedence. This allows exact matches to take
    precedence over partial matches.

    Attributes:
        locale: The locale for detection (only 'tr' locales fully supported)

    Example:
        >>> detector = TurkishFieldDetector()
        >>> detector.detect("tckn_no", "Data")
        'tckn'
        >>> detector.detect("vergi_kimlik_no", "Data")
        'vkn'
        >>> detector.detect("customer_iban", "Data")
        'iban'
        >>> detector.detect("random_field", "Data")
        None
    """

    def __init__(
        self,
        locale: str = "tr_TR",
        custom_patterns: Optional[List[Tuple[TurkishFieldType, str, int, str]]] = None,
    ):
        """
        Initialize the TurkishFieldDetector.

        Args:
            locale: The locale for detection. Turkish-specific detection is
                   most accurate for 'tr' or 'tr_TR' locales.
            custom_patterns: Optional additional patterns to add to detection.
                           Format: [(TurkishFieldType, regex_pattern, priority, description)]
        """
        self._locale = locale
        self._rules: List[FieldPatternRule] = []
        self._cache: Dict[str, Optional[str]] = {}

        # Build pattern rules
        self._build_rules(custom_patterns)

    def _build_rules(
        self,
        custom_patterns: Optional[List[Tuple[TurkishFieldType, str, int, str]]] = None,
    ) -> None:
        """
        Build compiled pattern rules from pattern definitions.

        Args:
            custom_patterns: Optional additional patterns to include
        """
        # Combine default and custom patterns
        all_patterns = list(TURKISH_FIELD_PATTERNS)
        if custom_patterns:
            all_patterns.extend(custom_patterns)

        # Build rules with compiled regex
        for field_type, pattern_str, priority, description in all_patterns:
            try:
                compiled = re.compile(pattern_str, re.IGNORECASE)
                self._rules.append(
                    FieldPatternRule(
                        field_type=field_type,
                        pattern=compiled,
                        priority=priority,
                        description=description,
                    )
                )
            except re.error:
                # Skip invalid regex patterns
                continue

        # Sort by priority (lower = higher precedence)
        self._rules.sort(key=lambda r: r.priority)

    @property
    def locale(self) -> str:
        """Get the current locale."""
        return self._locale

    def set_locale(self, locale: str) -> None:
        """
        Set the locale for detection.

        Args:
            locale: The locale string (e.g., 'tr_TR', 'tr')
        """
        self._locale = locale
        # Clear cache when locale changes
        self._cache.clear()

    def detect(
        self,
        fieldname: str,
        fieldtype: str,
        use_cache: bool = True,
    ) -> Optional[str]:
        """
        Detect the Turkish field type for a given field.

        Analyzes the field name against known Turkish field patterns
        and returns the detected type if a match is found.

        Args:
            fieldname: The field name to analyze
            fieldtype: The Frappe field type (e.g., "Data", "Link")
            use_cache: Whether to use cached results for performance

        Returns:
            The detected field type as a string (e.g., "tckn", "vkn", "iban"),
            or None if no Turkish field type was detected.

        Example:
            >>> detector = TurkishFieldDetector()
            >>> detector.detect("tckn_no", "Data")
            'tckn'
            >>> detector.detect("customer_email", "Data")
            None
        """
        # Normalize field name
        fieldname_lower = fieldname.lower().strip()

        # Check cache
        cache_key = f"{fieldname_lower}:{fieldtype}"
        if use_cache and cache_key in self._cache:
            return self._cache[cache_key]

        # Try pattern matching
        detected = self._match_patterns(fieldname_lower, fieldtype)

        # Cache result
        if use_cache:
            self._cache[cache_key] = detected

        return detected

    def _match_patterns(
        self,
        fieldname: str,
        fieldtype: str,
    ) -> Optional[str]:
        """
        Match field name against Turkish patterns.

        Args:
            fieldname: Normalized (lowercase) field name
            fieldtype: The field type

        Returns:
            Detected field type string or None
        """
        # Skip certain field types that can't be Turkish identifiers
        skip_fieldtypes = {
            "Link",
            "Table",
            "Table MultiSelect",
            "Check",
            "Select",
            "Attach",
            "Attach Image",
            "Section Break",
            "Column Break",
            "Tab Break",
        }

        if fieldtype in skip_fieldtypes:
            return None

        # Try each rule in priority order
        for rule in self._rules:
            if rule.pattern.search(fieldname):
                return rule.field_type.value

        return None

    def detect_with_confidence(
        self,
        fieldname: str,
        fieldtype: str,
    ) -> Tuple[Optional[str], float]:
        """
        Detect Turkish field type with a confidence score.

        Returns both the detected type and a confidence score (0.0 to 1.0)
        indicating how confident the detection is.

        Confidence levels:
        - 1.0: Exact match (e.g., field named exactly "tckn")
        - 0.8: Strong pattern match with Turkish keywords
        - 0.6: Pattern match with common variations
        - 0.4: Weak pattern match
        - 0.0: No match

        Args:
            fieldname: The field name to analyze
            fieldtype: The Frappe field type

        Returns:
            Tuple of (detected_type, confidence_score)

        Example:
            >>> detector = TurkishFieldDetector()
            >>> detector.detect_with_confidence("tckn", "Data")
            ('tckn', 1.0)
            >>> detector.detect_with_confidence("customer_tc_no", "Data")
            ('tckn', 0.8)
        """
        fieldname_lower = fieldname.lower().strip()

        # Skip certain field types
        skip_fieldtypes = {
            "Link", "Table", "Table MultiSelect", "Check", "Select",
            "Attach", "Attach Image", "Section Break", "Column Break", "Tab Break",
        }

        if fieldtype in skip_fieldtypes:
            return (None, 0.0)

        # Try each rule and calculate confidence
        for rule in self._rules:
            if rule.pattern.search(fieldname_lower):
                # Calculate confidence based on priority
                if rule.priority == 1:
                    confidence = 1.0
                elif rule.priority == 2:
                    confidence = 0.8
                elif rule.priority == 3:
                    confidence = 0.6
                else:
                    confidence = 0.4

                return (rule.field_type.value, confidence)

        return (None, 0.0)

    def detect_all(
        self,
        fieldname: str,
        fieldtype: str,
    ) -> List[Tuple[str, float]]:
        """
        Detect all possible Turkish field types for a field.

        Returns all matching field types with their confidence scores,
        sorted by confidence (highest first).

        This is useful when a field name might match multiple patterns.

        Args:
            fieldname: The field name to analyze
            fieldtype: The Frappe field type

        Returns:
            List of (field_type, confidence) tuples, sorted by confidence

        Example:
            >>> detector = TurkishFieldDetector()
            >>> detector.detect_all("phone_no", "Data")
            [('phone', 0.8), ('mobile', 0.6)]
        """
        fieldname_lower = fieldname.lower().strip()
        matches: List[Tuple[str, float]] = []

        skip_fieldtypes = {
            "Link", "Table", "Table MultiSelect", "Check", "Select",
            "Attach", "Attach Image", "Section Break", "Column Break", "Tab Break",
        }

        if fieldtype in skip_fieldtypes:
            return matches

        seen_types: Set[str] = set()

        for rule in self._rules:
            if rule.pattern.search(fieldname_lower):
                field_type_str = rule.field_type.value

                # Avoid duplicates
                if field_type_str in seen_types:
                    continue
                seen_types.add(field_type_str)

                # Calculate confidence
                if rule.priority == 1:
                    confidence = 1.0
                elif rule.priority == 2:
                    confidence = 0.8
                elif rule.priority == 3:
                    confidence = 0.6
                else:
                    confidence = 0.4

                matches.append((field_type_str, confidence))

        # Sort by confidence (highest first)
        matches.sort(key=lambda x: -x[1])
        return matches

    def get_supported_types(self) -> Set[str]:
        """
        Get the set of all Turkish field types this detector supports.

        Returns:
            Set of field type strings

        Example:
            >>> detector = TurkishFieldDetector()
            >>> "tckn" in detector.get_supported_types()
            True
        """
        return {ft.value for ft in TurkishFieldType if ft != TurkishFieldType.NONE}

    def get_patterns_for_type(self, field_type: str) -> List[str]:
        """
        Get all regex patterns that detect a specific field type.

        This is useful for understanding what patterns will match a type.

        Args:
            field_type: The field type string (e.g., "tckn")

        Returns:
            List of regex pattern strings

        Example:
            >>> detector = TurkishFieldDetector()
            >>> patterns = detector.get_patterns_for_type("tckn")
            >>> len(patterns) > 0
            True
        """
        try:
            target_type = TurkishFieldType(field_type)
        except ValueError:
            return []

        return [
            rule.pattern.pattern
            for rule in self._rules
            if rule.field_type == target_type
        ]

    def add_pattern(
        self,
        field_type: str,
        pattern: str,
        priority: int = 5,
        description: str = "",
    ) -> bool:
        """
        Add a custom pattern for detection.

        This allows extending the detector with domain-specific patterns.

        Args:
            field_type: The field type string (must be a valid TurkishFieldType value)
            pattern: The regex pattern string
            priority: Pattern priority (lower = higher precedence)
            description: Human-readable description

        Returns:
            True if pattern was added successfully, False otherwise

        Example:
            >>> detector = TurkishFieldDetector()
            >>> detector.add_pattern("tckn", r"custom_tckn_field$", priority=2)
            True
        """
        try:
            ft = TurkishFieldType(field_type)
            compiled = re.compile(pattern, re.IGNORECASE)
            self._rules.append(
                FieldPatternRule(
                    field_type=ft,
                    pattern=compiled,
                    priority=priority,
                    description=description,
                )
            )
            # Re-sort by priority
            self._rules.sort(key=lambda r: r.priority)
            # Clear cache
            self._cache.clear()
            return True
        except (ValueError, re.error):
            return False

    def clear_cache(self) -> None:
        """Clear the detection cache."""
        self._cache.clear()

    def __repr__(self) -> str:
        """String representation."""
        return f"TurkishFieldDetector(locale='{self._locale}', rules={len(self._rules)})"


# Module-level convenience functions

# Default detector instance
_default_detector: Optional[TurkishFieldDetector] = None


def _get_detector() -> TurkishFieldDetector:
    """Get or create the default TurkishFieldDetector instance."""
    global _default_detector
    if _default_detector is None:
        _default_detector = TurkishFieldDetector()
    return _default_detector


def detect_turkish_field(
    fieldname: str,
    fieldtype: str = "Data",
) -> Optional[str]:
    """
    Detect if a field should contain Turkish-specific data.

    This is a convenience function that uses the default detector instance.

    Args:
        fieldname: The field name to analyze
        fieldtype: The Frappe field type (default: "Data")

    Returns:
        The detected Turkish field type (e.g., "tckn", "vkn", "iban"),
        or None if no Turkish field type was detected.

    Example:
        >>> detect_turkish_field("tckn_no")
        'tckn'
        >>> detect_turkish_field("vergi_no")
        'vkn'
        >>> detect_turkish_field("email")
        None
    """
    return _get_detector().detect(fieldname, fieldtype)


def detect_turkish_field_with_confidence(
    fieldname: str,
    fieldtype: str = "Data",
) -> Tuple[Optional[str], float]:
    """
    Detect Turkish field type with confidence score.

    This is a convenience function that uses the default detector instance.

    Args:
        fieldname: The field name to analyze
        fieldtype: The Frappe field type (default: "Data")

    Returns:
        Tuple of (detected_type, confidence_score)

    Example:
        >>> detect_turkish_field_with_confidence("tckn")
        ('tckn', 1.0)
        >>> detect_turkish_field_with_confidence("tc_kimlik_no")
        ('tckn', 0.8)
    """
    return _get_detector().detect_with_confidence(fieldname, fieldtype)


def is_turkish_field(fieldname: str, fieldtype: str = "Data") -> bool:
    """
    Check if a field is a Turkish-specific field.

    Args:
        fieldname: The field name to check
        fieldtype: The Frappe field type (default: "Data")

    Returns:
        True if the field is a Turkish-specific field, False otherwise

    Example:
        >>> is_turkish_field("tckn_no")
        True
        >>> is_turkish_field("customer_name")
        False
    """
    return _get_detector().detect(fieldname, fieldtype) is not None


def get_turkish_field_types() -> Set[str]:
    """
    Get all supported Turkish field types.

    Returns:
        Set of field type strings

    Example:
        >>> types = get_turkish_field_types()
        >>> "tckn" in types
        True
        >>> "vkn" in types
        True
    """
    return _get_detector().get_supported_types()


# Export all public symbols
__all__ = [
    # Classes
    "TurkishFieldDetector",
    "TurkishFieldType",
    "FieldPatternRule",
    # Constants
    "TURKISH_FIELD_PATTERNS",
    # Functions
    "detect_turkish_field",
    "detect_turkish_field_with_confidence",
    "is_turkish_field",
    "get_turkish_field_types",
]

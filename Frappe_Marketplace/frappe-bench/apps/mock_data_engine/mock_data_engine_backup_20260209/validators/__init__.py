# Copyright (c) 2024, Mock Data Engine and contributors
# For license information, please see license.txt

"""
Validators Module.

This module provides validators and generators for various identification
numbers and codes, particularly Turkish-specific identifiers.

Available validators:
- Turkish TCKN (Turkish Citizen Identity Number)
- Turkish VKN (Tax Identification Number)
- Turkish IBAN (International Bank Account Number)
- Turkish Phone Numbers
- Turkish Addresses, Cities, Postal Codes

Field Detection:
- TurkishFieldDetector for automatic detection of Turkish field types

Usage:
    from mock_data_engine.mock_data_engine.validators.turkish import (
        generate_valid_tckn,
        validate_tckn,
        generate_valid_vkn,
        validate_vkn,
    )

    # Generate a valid TCKN
    tckn = generate_valid_tckn()

    # Validate a TCKN
    is_valid = validate_tckn("12345678901")

    # Detect Turkish field types
    from mock_data_engine.mock_data_engine.validators.field_detector import (
        TurkishFieldDetector,
        detect_turkish_field,
    )

    detector = TurkishFieldDetector()
    field_type = detector.detect("tckn_no", "Data")  # Returns "tckn"
"""

from mock_data_engine.mock_data_engine.validators.turkish import (
    # TCKN
    generate_valid_tckn,
    validate_tckn,
    TCKNValidator,
    # VKN
    generate_valid_vkn,
    validate_vkn,
    VKNValidator,
    # IBAN
    generate_valid_turkish_iban,
    validate_turkish_iban,
    TurkishIBANValidator,
    # Phone
    generate_turkish_phone,
    validate_turkish_phone,
    TurkishPhoneGenerator,
    # City
    generate_turkish_city,
    TurkishCityGenerator,
    # Postal Code
    generate_turkish_postal_code,
    validate_turkish_postal_code,
    TurkishPostalCodeGenerator,
    # Address
    generate_turkish_address,
    TurkishAddressGenerator,
)

from mock_data_engine.mock_data_engine.validators.field_detector import (
    TurkishFieldDetector,
    TurkishFieldType,
    detect_turkish_field,
    detect_turkish_field_with_confidence,
    is_turkish_field,
    get_turkish_field_types,
)

__all__ = [
    # TCKN
    "generate_valid_tckn",
    "validate_tckn",
    "TCKNValidator",
    # VKN
    "generate_valid_vkn",
    "validate_vkn",
    "VKNValidator",
    # IBAN
    "generate_valid_turkish_iban",
    "validate_turkish_iban",
    "TurkishIBANValidator",
    # Phone
    "generate_turkish_phone",
    "validate_turkish_phone",
    "TurkishPhoneGenerator",
    # City
    "generate_turkish_city",
    "TurkishCityGenerator",
    # Postal Code
    "generate_turkish_postal_code",
    "validate_turkish_postal_code",
    "TurkishPostalCodeGenerator",
    # Address
    "generate_turkish_address",
    "TurkishAddressGenerator",
    # Field Detector
    "TurkishFieldDetector",
    "TurkishFieldType",
    "detect_turkish_field",
    "detect_turkish_field_with_confidence",
    "is_turkish_field",
    "get_turkish_field_types",
]

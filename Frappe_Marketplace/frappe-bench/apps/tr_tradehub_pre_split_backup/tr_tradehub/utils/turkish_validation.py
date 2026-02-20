# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

"""
Turkish Tax ID Validation Module

This module provides validation functions for Turkish tax identification numbers:
- VKN (Vergi Kimlik Numarasi): 10-digit tax ID for companies/businesses
- TCKN (Turkiye Cumhuriyeti Kimlik Numarasi): 11-digit national ID for individuals

Both validation algorithms follow the official Turkish government specifications.
"""

import frappe
from frappe import _


def validate_vkn(vkn: str) -> bool:
    """
    Validate a Turkish VKN (Vergi Kimlik Numarasi) - Company Tax ID.

    VKN is a 10-digit number used by businesses in Turkey.
    The algorithm uses a weighted sum and modulo operations for validation.

    Args:
        vkn: The VKN to validate (string of 10 digits)

    Returns:
        bool: True if valid, False otherwise

    Example:
        >>> validate_vkn("1234567890")
        False
        >>> validate_vkn("0123456789")
        # Returns True/False based on algorithm
    """
    if not vkn:
        return False

    # Remove any whitespace and convert to string
    vkn = str(vkn).strip().replace(" ", "")

    # VKN must be exactly 10 digits
    if len(vkn) != 10:
        return False

    # VKN must contain only digits
    if not vkn.isdigit():
        return False

    try:
        # VKN validation algorithm
        # Based on Turkish Revenue Administration (GIB) specification
        digits = [int(d) for d in vkn]

        # The algorithm calculates check values for each position
        total = 0
        for i in range(9):
            # Add digit to (10 - position) and take mod 10
            tmp = (digits[i] + (10 - i - 1)) % 10
            # If result is 9, use 9, otherwise take mod 9
            if tmp == 9:
                v = tmp
            else:
                v = (tmp * (2 ** (10 - i - 1))) % 9
            total += v

        # Calculate check digit
        check_digit = (10 - (total % 10)) % 10

        # Compare with last digit
        return check_digit == digits[9]

    except (ValueError, IndexError):
        return False


def validate_tckn(tckn: str) -> bool:
    """
    Validate a Turkish TCKN (TC Kimlik Numarasi) - National ID.

    TCKN is an 11-digit number assigned to Turkish citizens.
    The algorithm uses two separate checks on odd and even positioned digits.

    Rules:
    1. Must be exactly 11 digits
    2. First digit cannot be 0
    3. Sum of odd-positioned digits (1,3,5,7,9) * 7 minus sum of even-positioned
       digits (2,4,6,8) mod 10 must equal the 10th digit
    4. Sum of first 10 digits mod 10 must equal the 11th digit

    Args:
        tckn: The TCKN to validate (string of 11 digits)

    Returns:
        bool: True if valid, False otherwise

    Example:
        >>> validate_tckn("12345678901")
        False
        >>> validate_tckn("10000000146")
        # Returns True (valid TCKN)
    """
    if not tckn:
        return False

    # Remove any whitespace and convert to string
    tckn = str(tckn).strip().replace(" ", "")

    # TCKN must be exactly 11 digits
    if len(tckn) != 11:
        return False

    # TCKN must contain only digits
    if not tckn.isdigit():
        return False

    # First digit cannot be 0
    if tckn[0] == "0":
        return False

    try:
        digits = [int(d) for d in tckn]

        # First check: 10th digit validation
        # Sum of odd-positioned digits (1st, 3rd, 5th, 7th, 9th)
        odd_sum = digits[0] + digits[2] + digits[4] + digits[6] + digits[8]
        # Sum of even-positioned digits (2nd, 4th, 6th, 8th)
        even_sum = digits[1] + digits[3] + digits[5] + digits[7]

        # Calculate 10th digit: (odd_sum * 7 - even_sum) mod 10
        check_10 = (odd_sum * 7 - even_sum) % 10
        if check_10 < 0:
            check_10 += 10

        if check_10 != digits[9]:
            return False

        # Second check: 11th digit validation
        # Sum of first 10 digits mod 10
        first_10_sum = sum(digits[:10])
        check_11 = first_10_sum % 10

        if check_11 != digits[10]:
            return False

        return True

    except (ValueError, IndexError):
        return False


def validate_tax_id(tax_id: str, tax_id_type: str = None) -> dict:
    """
    Validate a Turkish tax ID and return detailed validation result.

    This function can automatically detect the tax ID type based on length,
    or validate against a specified type.

    Args:
        tax_id: The tax ID to validate
        tax_id_type: Optional type ("VKN" or "TCKN"). If not provided,
                     the type will be auto-detected based on length.

    Returns:
        dict: Validation result with keys:
            - valid (bool): Whether the tax ID is valid
            - tax_id_type (str): The type of tax ID ("VKN", "TCKN", or "Unknown")
            - message (str): Human-readable validation message
            - formatted (str): The cleaned/formatted tax ID

    Example:
        >>> validate_tax_id("1234567890", "VKN")
        {"valid": False, "tax_id_type": "VKN", "message": "Invalid VKN", ...}
    """
    if not tax_id:
        return {
            "valid": False,
            "tax_id_type": "Unknown",
            "message": _("Tax ID is required"),
            "formatted": ""
        }

    # Clean the input
    cleaned = str(tax_id).strip().replace(" ", "")

    # Detect type if not specified
    detected_type = tax_id_type
    if not detected_type:
        detected_type = detect_tax_id_type(cleaned)

    # Validate based on type
    if detected_type == "VKN":
        is_valid = validate_vkn(cleaned)
        message = _("Valid VKN") if is_valid else _("Invalid VKN - checksum verification failed")
    elif detected_type == "TCKN":
        is_valid = validate_tckn(cleaned)
        if not is_valid:
            if len(cleaned) != 11:
                message = _("Invalid TCKN - must be 11 digits")
            elif cleaned[0] == "0":
                message = _("Invalid TCKN - cannot start with 0")
            else:
                message = _("Invalid TCKN - checksum verification failed")
        else:
            message = _("Valid TCKN")
    else:
        is_valid = False
        message = _("Unknown tax ID format - must be 10 digits (VKN) or 11 digits (TCKN)")

    return {
        "valid": is_valid,
        "tax_id_type": detected_type,
        "message": message,
        "formatted": cleaned
    }


def detect_tax_id_type(tax_id: str) -> str:
    """
    Detect the type of Turkish tax ID based on its format.

    Args:
        tax_id: The tax ID to analyze

    Returns:
        str: "VKN" for 10 digits, "TCKN" for 11 digits, "Unknown" otherwise
    """
    if not tax_id:
        return "Unknown"

    cleaned = str(tax_id).strip().replace(" ", "")

    if not cleaned.isdigit():
        return "Unknown"

    if len(cleaned) == 10:
        return "VKN"
    elif len(cleaned) == 11:
        return "TCKN"
    else:
        return "Unknown"


@frappe.whitelist()
def validate_tax_id_api(tax_id: str, tax_id_type: str = None) -> dict:
    """
    API endpoint for validating Turkish tax IDs.

    This is a whitelisted function that can be called from the client-side
    to validate tax IDs in real-time.

    Args:
        tax_id: The tax ID to validate
        tax_id_type: Optional type ("VKN" or "TCKN")

    Returns:
        dict: Validation result (see validate_tax_id for format)
    """
    return validate_tax_id(tax_id, tax_id_type)


@frappe.whitelist()
def get_validation_status(tax_id: str, tax_id_type: str = None) -> dict:
    """
    Get validation status with visual indicator information.

    This function is designed for use with UI components that need
    to display visual feedback about validation status.

    Args:
        tax_id: The tax ID to validate
        tax_id_type: Optional type ("VKN" or "TCKN")

    Returns:
        dict: Validation result with additional UI metadata:
            - valid (bool): Whether the tax ID is valid
            - tax_id_type (str): Detected or specified type
            - message (str): Human-readable message
            - indicator (str): Frappe indicator color ("green", "red", "orange")
            - icon (str): Icon suggestion for UI ("fa-check-circle", "fa-times-circle")
    """
    result = validate_tax_id(tax_id, tax_id_type)

    if result["valid"]:
        result["indicator"] = "green"
        result["icon"] = "fa-check-circle"
    elif result["tax_id_type"] == "Unknown":
        result["indicator"] = "orange"
        result["icon"] = "fa-question-circle"
    else:
        result["indicator"] = "red"
        result["icon"] = "fa-times-circle"

    return result

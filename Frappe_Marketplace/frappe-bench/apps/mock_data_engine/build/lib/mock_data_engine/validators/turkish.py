# Copyright (c) 2024, Mock Data Engine and contributors
# For license information, please see license.txt

"""
Turkish Validators Module.

This module provides validators and generators for Turkish-specific
identification numbers including TCKN (Turkish Citizen Identity Number),
VKN (Tax Identification Number), and IBAN (International Bank Account Number).

TCKN (T.C. Kimlik Numarasi) Algorithm:
- 11 digits total
- First digit cannot be 0 (must be 1-9)
- Digits 2-9 can be any digit (0-9)
- Digit 10 (first checksum): ((sum of odd positions * 7) - sum of even positions) mod 10
  Formula: ((d1+d3+d5+d7+d9) * 7 - (d2+d4+d6+d8)) mod 10
- Digit 11 (second checksum): (sum of first 10 digits) mod 10
  Formula: (d1+d2+d3+d4+d5+d6+d7+d8+d9+d10) mod 10

VKN (Vergi Kimlik Numarasi) Algorithm:
- 10 digits total
- First 9 digits can be any digit (0-9)
- Digit 10 (checksum): calculated using weighted modular arithmetic
  For each digit d[i] (i = 0 to 8):
    - tmp = (d[i] + (9 - i)) mod 10
    - If tmp != 0: v = (tmp * 2^(9-i)) mod 9, if v == 0 then v = 9
    - If tmp == 0: v = 0
  - Checksum = (10 - (sum of all v) mod 10) mod 10

Turkish IBAN Algorithm:
- 26 characters total
- Format: TR + 2 check digits + 5-digit bank code + 1 reserved digit (0) + 16-digit account
- Check digits calculated using ISO 7064 Mod 97-10 algorithm:
  1. Move country code (TR) and check digits to end
  2. Replace letters with numbers (A=10, B=11, ..., Z=35)
  3. Calculate: check_digits = 98 - (numeric_string mod 97)

Usage:
    from mock_data_engine.mock_data_engine.validators.turkish import (
        generate_valid_tckn,
        validate_tckn,
        TCKNValidator,
        generate_valid_vkn,
        validate_vkn,
        VKNValidator,
        generate_valid_turkish_iban,
        validate_turkish_iban,
        TurkishIBANValidator,
    )

    # Generate a valid TCKN
    tckn = generate_valid_tckn()
    print(tckn)  # e.g., '12345678901'

    # Validate a TCKN
    is_valid = validate_tckn("12345678901")

    # Using the class-based validator
    validator = TCKNValidator()
    tckn = validator.generate()
    is_valid = validator.validate(tckn)

    # Generate a valid VKN
    vkn = generate_valid_vkn()
    print(vkn)  # e.g., '1234567890'

    # Validate a VKN
    is_valid = validate_vkn("1234567890")

    # Using the class-based validator
    vkn_validator = VKNValidator()
    vkn = vkn_validator.generate()
    is_valid = vkn_validator.validate(vkn)

    # Generate a valid Turkish IBAN
    iban = generate_valid_turkish_iban()
    print(iban)  # e.g., 'TR330006100519786457841326'

    # Validate a Turkish IBAN
    is_valid = validate_turkish_iban("TR330006100519786457841326")

    # Using the class-based validator
    iban_validator = TurkishIBANValidator()
    iban = iban_validator.generate()
    is_valid = iban_validator.validate(iban)
"""

from __future__ import annotations

import random
from typing import Optional, Union


class TCKNValidator:
    """
    Validator and generator for Turkish Citizen Identity Numbers (TCKN).

    TCKN (T.C. Kimlik Numarasi) is an 11-digit identification number
    assigned to Turkish citizens. The number follows a specific checksum
    algorithm that can be used for validation.

    The algorithm works as follows:
    - First 9 digits can be any number (first digit cannot be 0)
    - Digit 10 = ((sum_odd * 7) - sum_even) mod 10
      where sum_odd = d1+d3+d5+d7+d9 and sum_even = d2+d4+d6+d8
    - Digit 11 = (sum of first 10 digits) mod 10

    Attributes:
        seed: Optional random seed for reproducible generation

    Example:
        >>> validator = TCKNValidator(seed=42)
        >>> tckn = validator.generate()
        >>> validator.validate(tckn)
        True
    """

    def __init__(self, seed: Optional[int] = None):
        """
        Initialize the TCKN validator.

        Args:
            seed: Optional random seed for reproducible generation
        """
        self._seed = seed
        self._random = random.Random(seed)

    def generate(self) -> str:
        """
        Generate a valid TCKN.

        Returns:
            An 11-digit valid TCKN string

        Example:
            >>> validator = TCKNValidator()
            >>> tckn = validator.generate()
            >>> len(tckn)
            11
        """
        # Generate first 9 digits (first digit must be 1-9, rest 0-9)
        digits = [self._random.randint(1, 9)]  # First digit: 1-9
        for _ in range(8):
            digits.append(self._random.randint(0, 9))  # Digits 2-9: 0-9

        # Calculate checksum digit 10
        # Sum of odd position digits (1, 3, 5, 7, 9)
        sum_odd = digits[0] + digits[2] + digits[4] + digits[6] + digits[8]
        # Sum of even position digits (2, 4, 6, 8)
        sum_even = digits[1] + digits[3] + digits[5] + digits[7]

        # Digit 10 formula: ((sum_odd * 7) - sum_even) mod 10
        digit_10 = ((sum_odd * 7) - sum_even) % 10
        digits.append(digit_10)

        # Calculate checksum digit 11
        # Sum of first 10 digits mod 10
        digit_11 = sum(digits) % 10
        digits.append(digit_11)

        return "".join(str(d) for d in digits)

    def validate(self, tckn: Union[str, int]) -> bool:
        """
        Validate a TCKN.

        Performs the following validations:
        1. Must be exactly 11 digits
        2. First digit cannot be 0
        3. Must contain only digits
        4. Checksum digit 10 must be valid
        5. Checksum digit 11 must be valid

        Args:
            tckn: The TCKN to validate (string or integer)

        Returns:
            True if the TCKN is valid, False otherwise

        Example:
            >>> validator = TCKNValidator()
            >>> validator.validate("12345678901")  # Check if valid
            True or False
            >>> validator.validate(12345678901)  # Also accepts integers
            True or False
        """
        # Convert to string if integer
        tckn_str = str(tckn).strip()

        # Check length
        if len(tckn_str) != 11:
            return False

        # Check all characters are digits
        if not tckn_str.isdigit():
            return False

        # First digit cannot be 0
        if tckn_str[0] == "0":
            return False

        # Convert to list of integers
        digits = [int(d) for d in tckn_str]

        # Validate checksum digit 10
        sum_odd = digits[0] + digits[2] + digits[4] + digits[6] + digits[8]
        sum_even = digits[1] + digits[3] + digits[5] + digits[7]
        expected_digit_10 = ((sum_odd * 7) - sum_even) % 10

        if digits[9] != expected_digit_10:
            return False

        # Validate checksum digit 11
        expected_digit_11 = sum(digits[:10]) % 10

        if digits[10] != expected_digit_11:
            return False

        return True

    def calculate_checksums(self, first_nine: str) -> tuple:
        """
        Calculate the checksum digits for a given first 9 digits.

        This is useful for manually constructing TCKNs or understanding
        the checksum algorithm.

        Args:
            first_nine: The first 9 digits of the TCKN

        Returns:
            Tuple of (digit_10, digit_11)

        Raises:
            ValueError: If first_nine is not exactly 9 digits

        Example:
            >>> validator = TCKNValidator()
            >>> validator.calculate_checksums("123456789")
            (4, 0)  # Example output
        """
        if len(first_nine) != 9 or not first_nine.isdigit():
            raise ValueError("first_nine must be exactly 9 digits")

        if first_nine[0] == "0":
            raise ValueError("First digit cannot be 0")

        digits = [int(d) for d in first_nine]

        # Calculate digit 10
        sum_odd = digits[0] + digits[2] + digits[4] + digits[6] + digits[8]
        sum_even = digits[1] + digits[3] + digits[5] + digits[7]
        digit_10 = ((sum_odd * 7) - sum_even) % 10

        # Calculate digit 11
        digit_11 = (sum(digits) + digit_10) % 10

        return (digit_10, digit_11)

    def set_seed(self, seed: int) -> None:
        """
        Set the random seed for reproducible generation.

        Args:
            seed: The random seed value
        """
        self._seed = seed
        self._random = random.Random(seed)


class VKNValidator:
    """
    Validator and generator for Turkish Tax Identification Numbers (VKN).

    VKN (Vergi Kimlik Numarasi) is a 10-digit identification number
    assigned to Turkish businesses and tax entities. The number follows
    a specific checksum algorithm that can be used for validation.

    The algorithm works as follows:
    - First 9 digits can be any number (0-9)
    - Digit 10 (checksum) is calculated using weighted modular arithmetic:
      For each digit d[i] (i = 0 to 8):
        - tmp = (d[i] + (9 - i)) mod 10
        - If tmp != 0: v = (tmp * 2^(9-i)) mod 9, if v == 0 then v = 9
        - If tmp == 0: v = 0
      - Checksum = (10 - (sum of all v) mod 10) mod 10

    Attributes:
        seed: Optional random seed for reproducible generation

    Example:
        >>> validator = VKNValidator(seed=42)
        >>> vkn = validator.generate()
        >>> validator.validate(vkn)
        True
    """

    def __init__(self, seed: Optional[int] = None):
        """
        Initialize the VKN validator.

        Args:
            seed: Optional random seed for reproducible generation
        """
        self._seed = seed
        self._random = random.Random(seed)

    def generate(self) -> str:
        """
        Generate a valid VKN.

        Returns:
            A 10-digit valid VKN string

        Example:
            >>> validator = VKNValidator()
            >>> vkn = validator.generate()
            >>> len(vkn)
            10
        """
        # Generate first 9 digits (all can be 0-9)
        digits = [self._random.randint(0, 9) for _ in range(9)]

        # Calculate checksum digit 10
        checksum = self._calculate_checksum(digits)
        digits.append(checksum)

        return "".join(str(d) for d in digits)

    def _calculate_checksum(self, first_nine: list) -> int:
        """
        Calculate the VKN checksum digit.

        The VKN checksum algorithm uses weighted modular arithmetic:
        For each position i (0-8), calculate a weighted value and sum them.
        The checksum is (10 - sum mod 10) mod 10.

        Args:
            first_nine: List of 9 integer digits

        Returns:
            The checksum digit (0-9)
        """
        total = 0

        for i in range(9):
            digit = first_nine[i]
            # tmp = (digit + (9 - i)) mod 10
            tmp = (digit + (9 - i)) % 10

            if tmp != 0:
                # v = (tmp * 2^(9-i)) mod 9
                # If result is 0, use 9 instead
                power = pow(2, 9 - i)
                v = (tmp * power) % 9
                if v == 0:
                    v = 9
                total += v
            # If tmp == 0, contribution is 0 (no addition needed)

        # Checksum = (10 - (total mod 10)) mod 10
        checksum = (10 - (total % 10)) % 10
        return checksum

    def validate(self, vkn: Union[str, int]) -> bool:
        """
        Validate a VKN.

        Performs the following validations:
        1. Must be exactly 10 digits
        2. Must contain only digits
        3. Checksum digit must be valid

        Args:
            vkn: The VKN to validate (string or integer)

        Returns:
            True if the VKN is valid, False otherwise

        Example:
            >>> validator = VKNValidator()
            >>> validator.validate("1234567890")  # Check if valid
            True or False
            >>> validator.validate(1234567890)  # Also accepts integers
            True or False
        """
        # Convert to string if integer
        vkn_str = str(vkn).strip()

        # Handle leading zeros by padding if needed
        if len(vkn_str) < 10 and vkn_str.isdigit():
            vkn_str = vkn_str.zfill(10)

        # Check length
        if len(vkn_str) != 10:
            return False

        # Check all characters are digits
        if not vkn_str.isdigit():
            return False

        # Convert to list of integers
        digits = [int(d) for d in vkn_str]

        # Calculate expected checksum
        expected_checksum = self._calculate_checksum(digits[:9])

        # Validate checksum
        return digits[9] == expected_checksum

    def calculate_checksum(self, first_nine: str) -> int:
        """
        Calculate the checksum digit for a given first 9 digits.

        This is useful for manually constructing VKNs or understanding
        the checksum algorithm.

        Args:
            first_nine: The first 9 digits of the VKN

        Returns:
            The checksum digit (0-9)

        Raises:
            ValueError: If first_nine is not exactly 9 digits

        Example:
            >>> validator = VKNValidator()
            >>> validator.calculate_checksum("123456789")
            4  # Example output
        """
        # Handle leading zeros by padding if needed
        first_nine = first_nine.zfill(9) if len(first_nine) < 9 else first_nine

        if len(first_nine) != 9 or not first_nine.isdigit():
            raise ValueError("first_nine must be exactly 9 digits")

        digits = [int(d) for d in first_nine]
        return self._calculate_checksum(digits)

    def set_seed(self, seed: int) -> None:
        """
        Set the random seed for reproducible generation.

        Args:
            seed: The random seed value
        """
        self._seed = seed
        self._random = random.Random(seed)


# Turkish Bank Codes - major banks in Turkey
TURKISH_BANK_CODES = [
    "00010",  # Ziraat Bankası
    "00012",  # Halkbank
    "00015",  # Vakıfbank
    "00032",  # Türk Ekonomi Bankası (TEB)
    "00046",  # Akbank
    "00059",  # Şekerbank
    "00062",  # Garanti BBVA
    "00064",  # İş Bankası
    "00067",  # Yapı Kredi
    "00099",  # ING Bank
    "00111",  # QNB Finansbank
    "00134",  # Denizbank
    "00203",  # Albaraka Türk
    "00205",  # Kuveyt Türk
    "00206",  # Türkiye Finans
]


class TurkishIBANValidator:
    """
    Validator and generator for Turkish International Bank Account Numbers (IBAN).

    Turkish IBAN format (26 characters total):
    - TR: Country code (2 characters)
    - Check digits: 2 digits (calculated using ISO 7064 Mod 97-10)
    - Bank code: 5 digits
    - Reserved digit: 1 digit (always 0)
    - Account number: 16 digits

    The check digits are calculated using the ISO 7064 Mod 97-10 algorithm:
    1. Move country code and check digits to the end of the BBAN
    2. Replace each letter with two digits (A=10, B=11, ..., Z=35)
    3. Calculate: check_digits = 98 - (numeric_string mod 97)

    Attributes:
        seed: Optional random seed for reproducible generation
        bank_codes: List of valid Turkish bank codes to use for generation

    Example:
        >>> validator = TurkishIBANValidator(seed=42)
        >>> iban = validator.generate()
        >>> validator.validate(iban)
        True
    """

    def __init__(
        self,
        seed: Optional[int] = None,
        bank_codes: Optional[list] = None,
    ):
        """
        Initialize the Turkish IBAN validator.

        Args:
            seed: Optional random seed for reproducible generation
            bank_codes: Optional list of bank codes to use. If not provided,
                       uses the default TURKISH_BANK_CODES list.
        """
        self._seed = seed
        self._random = random.Random(seed)
        self._bank_codes = bank_codes if bank_codes is not None else TURKISH_BANK_CODES

    def generate(self, bank_code: Optional[str] = None) -> str:
        """
        Generate a valid Turkish IBAN.

        Args:
            bank_code: Optional 5-digit bank code. If not provided,
                      a random bank code from the configured list is used.

        Returns:
            A 26-character valid Turkish IBAN string

        Example:
            >>> validator = TurkishIBANValidator()
            >>> iban = validator.generate()
            >>> len(iban)
            26
            >>> iban.startswith('TR')
            True
        """
        # Select or validate bank code
        if bank_code is None:
            bank_code = self._random.choice(self._bank_codes)
        else:
            # Ensure bank code is 5 digits
            bank_code = str(bank_code).zfill(5)

        # Reserved digit (always 0 for Turkish IBANs)
        reserved = "0"

        # Generate 16-digit account number
        account_number = "".join(
            str(self._random.randint(0, 9)) for _ in range(16)
        )

        # BBAN (Basic Bank Account Number) = bank_code + reserved + account_number
        bban = bank_code + reserved + account_number

        # Calculate check digits
        check_digits = self._calculate_check_digits(bban)

        # Construct full IBAN
        return f"TR{check_digits}{bban}"

    def _calculate_check_digits(self, bban: str) -> str:
        """
        Calculate the IBAN check digits using ISO 7064 Mod 97-10 algorithm.

        The algorithm:
        1. Append country code (TR) and placeholder check digits (00) to BBAN
        2. Convert the string to numeric (letters become 2-digit numbers: A=10, ..., Z=35)
        3. Calculate check_digits = 98 - (numeric_string mod 97)

        Args:
            bban: The 22-character Basic Bank Account Number

        Returns:
            Two-digit check digit string (zero-padded if needed)
        """
        # Rearrange: BBAN + "TR" + "00" (placeholder check digits)
        rearranged = bban + "TR00"

        # Convert to numeric string (letters to numbers)
        numeric_string = self._letters_to_digits(rearranged)

        # Calculate check digits
        remainder = int(numeric_string) % 97
        check_digits = 98 - remainder

        # Return zero-padded 2-digit string
        return str(check_digits).zfill(2)

    def _letters_to_digits(self, s: str) -> str:
        """
        Convert letters to their numeric equivalents for IBAN calculation.

        A=10, B=11, C=12, ..., Z=35
        Digits remain unchanged.

        Args:
            s: String containing letters and/or digits

        Returns:
            String with letters replaced by their numeric equivalents
        """
        result = []
        for char in s:
            if char.isalpha():
                # A=10, B=11, ..., Z=35
                result.append(str(ord(char.upper()) - ord("A") + 10))
            else:
                result.append(char)
        return "".join(result)

    def validate(self, iban: str) -> bool:
        """
        Validate a Turkish IBAN.

        Performs the following validations:
        1. Must start with 'TR' (case-insensitive)
        2. Must be exactly 26 characters
        3. Characters 3-26 must be digits
        4. Check digits must be valid (ISO 7064 Mod 97-10)

        Args:
            iban: The IBAN to validate (string)

        Returns:
            True if the IBAN is valid, False otherwise

        Example:
            >>> validator = TurkishIBANValidator()
            >>> validator.validate("TR330006100519786457841326")
            True
            >>> validator.validate("TR000006100519786457841326")
            False
        """
        # Remove spaces and convert to uppercase
        iban_str = str(iban).replace(" ", "").upper()

        # Check length
        if len(iban_str) != 26:
            return False

        # Check country code
        if not iban_str.startswith("TR"):
            return False

        # Check that remaining characters are digits
        if not iban_str[2:].isdigit():
            return False

        # Extract components
        check_digits = iban_str[2:4]
        bban = iban_str[4:]

        # Validate check digits
        # Rearrange: BBAN + country code + check digits
        rearranged = bban + "TR" + check_digits

        # Convert to numeric string
        numeric_string = self._letters_to_digits(rearranged)

        # Valid IBAN: numeric_string mod 97 == 1
        return int(numeric_string) % 97 == 1

    def get_bank_code(self, iban: str) -> Optional[str]:
        """
        Extract the bank code from a Turkish IBAN.

        Args:
            iban: A valid Turkish IBAN

        Returns:
            The 5-digit bank code, or None if IBAN is invalid

        Example:
            >>> validator = TurkishIBANValidator()
            >>> validator.get_bank_code("TR330006100519786457841326")
            '00061'
        """
        iban_str = str(iban).replace(" ", "").upper()

        if len(iban_str) != 26 or not iban_str.startswith("TR"):
            return None

        return iban_str[4:9]

    def get_account_number(self, iban: str) -> Optional[str]:
        """
        Extract the account number from a Turkish IBAN.

        Args:
            iban: A valid Turkish IBAN

        Returns:
            The 16-digit account number, or None if IBAN is invalid

        Example:
            >>> validator = TurkishIBANValidator()
            >>> validator.get_account_number("TR330006100519786457841326")
            '9786457841326'
        """
        iban_str = str(iban).replace(" ", "").upper()

        if len(iban_str) != 26 or not iban_str.startswith("TR"):
            return None

        # Account number starts after bank code (5) and reserved (1)
        return iban_str[10:]

    def format_iban(self, iban: str, separator: str = " ") -> str:
        """
        Format an IBAN with separators for display.

        Args:
            iban: The IBAN to format
            separator: The separator to use (default is space)

        Returns:
            Formatted IBAN string (groups of 4 characters)

        Example:
            >>> validator = TurkishIBANValidator()
            >>> validator.format_iban("TR330006100519786457841326")
            'TR33 0006 1005 1978 6457 8413 26'
        """
        iban_str = str(iban).replace(" ", "").upper()
        return separator.join(
            iban_str[i : i + 4] for i in range(0, len(iban_str), 4)
        )

    def set_seed(self, seed: int) -> None:
        """
        Set the random seed for reproducible generation.

        Args:
            seed: The random seed value
        """
        self._seed = seed
        self._random = random.Random(seed)


# Module-level convenience functions

# Module-level validator instances for convenience functions
_default_tckn_validator: Optional[TCKNValidator] = None
_default_vkn_validator: Optional[VKNValidator] = None
_default_iban_validator: Optional[TurkishIBANValidator] = None


def _get_tckn_validator() -> TCKNValidator:
    """Get or create the default TCKN validator instance."""
    global _default_tckn_validator
    if _default_tckn_validator is None:
        _default_tckn_validator = TCKNValidator()
    return _default_tckn_validator


def _get_vkn_validator() -> VKNValidator:
    """Get or create the default VKN validator instance."""
    global _default_vkn_validator
    if _default_vkn_validator is None:
        _default_vkn_validator = VKNValidator()
    return _default_vkn_validator


def _get_iban_validator() -> TurkishIBANValidator:
    """Get or create the default Turkish IBAN validator instance."""
    global _default_iban_validator
    if _default_iban_validator is None:
        _default_iban_validator = TurkishIBANValidator()
    return _default_iban_validator


def generate_valid_tckn(seed: Optional[int] = None) -> str:
    """
    Generate a valid Turkish Citizen Identity Number (TCKN).

    This is a convenience function that creates and uses a TCKNValidator
    instance. For repeated generation, consider using the TCKNValidator
    class directly.

    Args:
        seed: Optional random seed for reproducible generation.
              If provided, creates a new validator with this seed.
              If None, uses the default validator.

    Returns:
        An 11-digit valid TCKN string

    Example:
        >>> tckn = generate_valid_tckn()
        >>> len(tckn)
        11
        >>> validate_tckn(tckn)
        True

        >>> # Reproducible generation
        >>> tckn1 = generate_valid_tckn(seed=42)
        >>> tckn2 = generate_valid_tckn(seed=42)
        >>> tckn1 == tckn2
        True
    """
    if seed is not None:
        validator = TCKNValidator(seed=seed)
        return validator.generate()

    return _get_tckn_validator().generate()


def validate_tckn(tckn: Union[str, int]) -> bool:
    """
    Validate a Turkish Citizen Identity Number (TCKN).

    Performs comprehensive validation including:
    - Length check (must be 11 digits)
    - First digit check (cannot be 0)
    - Digit-only check
    - Checksum validation (digits 10 and 11)

    Args:
        tckn: The TCKN to validate (string or integer)

    Returns:
        True if the TCKN is valid, False otherwise

    Example:
        >>> validate_tckn("12345678901")  # Check if valid
        True or False
        >>> validate_tckn(12345678901)  # Also accepts integers
        True or False

        >>> # Generated TCKNs are always valid
        >>> tckn = generate_valid_tckn()
        >>> validate_tckn(tckn)
        True
    """
    return _get_tckn_validator().validate(tckn)


def generate_valid_vkn(seed: Optional[int] = None) -> str:
    """
    Generate a valid Turkish Tax Identification Number (VKN).

    This is a convenience function that creates and uses a VKNValidator
    instance. For repeated generation, consider using the VKNValidator
    class directly.

    Args:
        seed: Optional random seed for reproducible generation.
              If provided, creates a new validator with this seed.
              If None, uses the default validator.

    Returns:
        A 10-digit valid VKN string

    Example:
        >>> vkn = generate_valid_vkn()
        >>> len(vkn)
        10
        >>> validate_vkn(vkn)
        True

        >>> # Reproducible generation
        >>> vkn1 = generate_valid_vkn(seed=42)
        >>> vkn2 = generate_valid_vkn(seed=42)
        >>> vkn1 == vkn2
        True
    """
    if seed is not None:
        validator = VKNValidator(seed=seed)
        return validator.generate()

    return _get_vkn_validator().generate()


def validate_vkn(vkn: Union[str, int]) -> bool:
    """
    Validate a Turkish Tax Identification Number (VKN).

    Performs comprehensive validation including:
    - Length check (must be 10 digits)
    - Digit-only check
    - Checksum validation

    Args:
        vkn: The VKN to validate (string or integer)

    Returns:
        True if the VKN is valid, False otherwise

    Example:
        >>> validate_vkn("1234567890")  # Check if valid
        True or False
        >>> validate_vkn(1234567890)  # Also accepts integers
        True or False

        >>> # Generated VKNs are always valid
        >>> vkn = generate_valid_vkn()
        >>> validate_vkn(vkn)
        True
    """
    return _get_vkn_validator().validate(vkn)


def generate_valid_turkish_iban(
    seed: Optional[int] = None,
    bank_code: Optional[str] = None,
) -> str:
    """
    Generate a valid Turkish International Bank Account Number (IBAN).

    This is a convenience function that creates and uses a TurkishIBANValidator
    instance. For repeated generation, consider using the TurkishIBANValidator
    class directly.

    Args:
        seed: Optional random seed for reproducible generation.
              If provided, creates a new validator with this seed.
              If None, uses the default validator.
        bank_code: Optional 5-digit bank code. If not provided,
                  a random bank code from major Turkish banks is used.

    Returns:
        A 26-character valid Turkish IBAN string

    Example:
        >>> iban = generate_valid_turkish_iban()
        >>> len(iban)
        26
        >>> iban.startswith('TR')
        True
        >>> validate_turkish_iban(iban)
        True

        >>> # Reproducible generation
        >>> iban1 = generate_valid_turkish_iban(seed=42)
        >>> iban2 = generate_valid_turkish_iban(seed=42)
        >>> iban1 == iban2
        True

        >>> # Specify bank code
        >>> iban = generate_valid_turkish_iban(bank_code="00064")  # İş Bankası
        >>> iban[4:9]
        '00064'
    """
    if seed is not None:
        validator = TurkishIBANValidator(seed=seed)
        return validator.generate(bank_code=bank_code)

    return _get_iban_validator().generate(bank_code=bank_code)


def validate_turkish_iban(iban: str) -> bool:
    """
    Validate a Turkish International Bank Account Number (IBAN).

    Performs comprehensive validation including:
    - Country code check (must start with 'TR')
    - Length check (must be 26 characters)
    - Check digit validation (ISO 7064 Mod 97-10)

    Args:
        iban: The IBAN to validate (string)

    Returns:
        True if the IBAN is valid, False otherwise

    Example:
        >>> validate_turkish_iban("TR330006100519786457841326")
        True
        >>> validate_turkish_iban("TR000006100519786457841326")
        False

        >>> # Generated IBANs are always valid
        >>> iban = generate_valid_turkish_iban()
        >>> validate_turkish_iban(iban)
        True
    """
    return _get_iban_validator().validate(iban)


# Turkish Mobile Operator Prefixes
TURKISH_MOBILE_PREFIXES = [
    # Turkcell prefixes
    "530", "531", "532", "533", "534", "535", "536", "537", "538", "539",
    "540", "541", "542", "543", "544", "545", "546", "547", "548", "549",
    "550", "551", "552", "553", "554", "555", "556", "557", "558", "559",
    # Vodafone prefixes
    "505", "506", "507", "508",
    "540", "541", "542",
    # Türk Telekom prefixes
    "501", "502", "503", "504",
    "559",
    "560", "561", "562",
]

# Turkish Cities with Plate Codes
# Plate code is the index in this list (1-indexed)
TURKISH_CITIES = [
    "Adana", "Adıyaman", "Afyonkarahisar", "Ağrı", "Amasya",
    "Ankara", "Antalya", "Artvin", "Aydın", "Balıkesir",
    "Bilecik", "Bingöl", "Bitlis", "Bolu", "Burdur",
    "Bursa", "Çanakkale", "Çankırı", "Çorum", "Denizli",
    "Diyarbakır", "Edirne", "Elazığ", "Erzincan", "Erzurum",
    "Eskişehir", "Gaziantep", "Giresun", "Gümüşhane", "Hakkari",
    "Hatay", "Isparta", "Mersin", "İstanbul", "İzmir",
    "Kars", "Kastamonu", "Kayseri", "Kırklareli", "Kırşehir",
    "Kocaeli", "Konya", "Kütahya", "Malatya", "Manisa",
    "Kahramanmaraş", "Mardin", "Muğla", "Muş", "Nevşehir",
    "Niğde", "Ordu", "Rize", "Sakarya", "Samsun",
    "Siirt", "Sinop", "Sivas", "Tekirdağ", "Tokat",
    "Trabzon", "Tunceli", "Şanlıurfa", "Uşak", "Van",
    "Yozgat", "Zonguldak", "Aksaray", "Bayburt", "Karaman",
    "Kırıkkale", "Batman", "Şırnak", "Bartın", "Ardahan",
    "Iğdır", "Yalova", "Karabük", "Kilis", "Osmaniye",
    "Düzce",
]

# Turkish Neighborhood Names
TURKISH_NEIGHBORHOODS = [
    "Cumhuriyet", "Atatürk", "Fatih", "Yıldırım", "Zafer",
    "Karşıyaka", "Bahçelievler", "Yenimahalle", "Merkez", "Kültür",
    "Şehit", "Güneş", "Akdeniz", "Mimar Sinan", "İnönü",
    "Sakarya", "Çamlık", "Gazi", "Esentepe", "Yeşilova",
    "Kurtuluş", "Hürriyet", "Barış", "Bağlar", "Yeni",
    "Emek", "Gültepe", "Altıntaş", "Mithatpaşa", "Fevzi Çakmak",
]

# Turkish Street Types
TURKISH_STREET_TYPES = [
    "Caddesi", "Sokak", "Bulvarı", "Sokağı", "Mevkii",
]

# Turkish Street Names
TURKISH_STREET_NAMES = [
    "Atatürk", "İstiklal", "Cumhuriyet", "Gazi Mustafa Kemal",
    "Barbaros", "Fatih Sultan Mehmet", "Süleyman Demirel",
    "Adnan Menderes", "İsmet İnönü", "Turgut Özal",
    "Menderes", "Çiçek", "Gül", "Bahar", "Yıldız",
    "Güneş", "Ay", "Deniz", "Orman", "Vatan",
    "Millet", "Hürriyet", "Barış", "Zafer", "Kurtuluş",
    "Lale", "Menekşe", "Papatya", "Karanfil", "Zambak",
]


class TurkishPhoneGenerator:
    """
    Generator for Turkish mobile phone numbers.

    Turkish mobile phone numbers have the following format:
    - 10 digits total
    - Start with '05' (0 is country code, 5 indicates mobile)
    - Third digit indicates operator (3-5 range)
    - Remaining 7 digits are subscriber number

    Format: 05XX XXX XX XX

    Attributes:
        seed: Optional random seed for reproducible generation

    Example:
        >>> generator = TurkishPhoneGenerator(seed=42)
        >>> phone = generator.generate()
        >>> phone.startswith('05')
        True
    """

    def __init__(self, seed: Optional[int] = None):
        """
        Initialize the Turkish phone generator.

        Args:
            seed: Optional random seed for reproducible generation
        """
        self._seed = seed
        self._random = random.Random(seed)

    def generate(self, formatted: bool = False) -> str:
        """
        Generate a valid Turkish mobile phone number.

        Args:
            formatted: If True, return formatted number (05XX XXX XX XX)
                      If False, return plain 10-digit number (default)

        Returns:
            A valid Turkish mobile phone number string

        Example:
            >>> generator = TurkishPhoneGenerator()
            >>> phone = generator.generate()
            >>> len(phone)
            10
            >>> phone.startswith('05')
            True
            >>> formatted = generator.generate(formatted=True)
            >>> len(formatted)
            13  # '05XX XXX XX XX'
        """
        # Select a random mobile prefix
        prefix = self._random.choice(TURKISH_MOBILE_PREFIXES)

        # Generate remaining 7 digits
        subscriber = "".join(str(self._random.randint(0, 9)) for _ in range(7))

        # Construct full number
        phone = f"0{prefix}{subscriber}"

        if formatted:
            # Format as 05XX XXX XX XX
            return f"{phone[:4]} {phone[4:7]} {phone[7:9]} {phone[9:]}"

        return phone

    def validate(self, phone: str) -> bool:
        """
        Validate a Turkish mobile phone number.

        Performs the following validations:
        1. Must be 10 digits (after removing formatting)
        2. Must start with '05'
        3. Third and fourth digits must form a valid operator prefix

        Args:
            phone: The phone number to validate

        Returns:
            True if the phone number is valid, False otherwise

        Example:
            >>> generator = TurkishPhoneGenerator()
            >>> generator.validate("05321234567")
            True
            >>> generator.validate("0212 123 45 67")  # Landline
            False
        """
        # Remove common formatting characters
        phone_str = str(phone).replace(" ", "").replace("-", "").replace("(", "").replace(")", "")

        # Check length
        if len(phone_str) != 10:
            return False

        # Check starts with 05
        if not phone_str.startswith("05"):
            return False

        # Check all characters are digits
        if not phone_str.isdigit():
            return False

        # Check prefix is valid
        prefix = phone_str[1:4]  # Extract 5XX part
        return prefix in TURKISH_MOBILE_PREFIXES

    def set_seed(self, seed: int) -> None:
        """
        Set the random seed for reproducible generation.

        Args:
            seed: The random seed value
        """
        self._seed = seed
        self._random = random.Random(seed)


class TurkishCityGenerator:
    """
    Generator for Turkish city names and plate codes.

    Turkey has 81 provinces (il), each with a unique plate code (01-81).
    This generator can produce city names or plate codes.

    Attributes:
        seed: Optional random seed for reproducible generation

    Example:
        >>> generator = TurkishCityGenerator(seed=42)
        >>> city = generator.generate()
        >>> city in TURKISH_CITIES
        True
    """

    def __init__(self, seed: Optional[int] = None):
        """
        Initialize the Turkish city generator.

        Args:
            seed: Optional random seed for reproducible generation
        """
        self._seed = seed
        self._random = random.Random(seed)

    def generate(self) -> str:
        """
        Generate a random Turkish city name.

        Returns:
            A Turkish city name string

        Example:
            >>> generator = TurkishCityGenerator()
            >>> city = generator.generate()
            >>> isinstance(city, str)
            True
        """
        return self._random.choice(TURKISH_CITIES)

    def generate_with_plate_code(self) -> tuple:
        """
        Generate a Turkish city with its plate code.

        Returns:
            Tuple of (city_name, plate_code)

        Example:
            >>> generator = TurkishCityGenerator()
            >>> city, plate = generator.generate_with_plate_code()
            >>> 1 <= plate <= 81
            True
        """
        index = self._random.randint(0, len(TURKISH_CITIES) - 1)
        city = TURKISH_CITIES[index]
        plate_code = index + 1  # Plate codes are 1-indexed
        return (city, plate_code)

    def get_plate_code(self, city: str) -> Optional[int]:
        """
        Get the plate code for a given city.

        Args:
            city: The city name

        Returns:
            The plate code (1-81) or None if city not found

        Example:
            >>> generator = TurkishCityGenerator()
            >>> generator.get_plate_code("İstanbul")
            34
            >>> generator.get_plate_code("Ankara")
            6
        """
        try:
            index = TURKISH_CITIES.index(city)
            return index + 1
        except ValueError:
            return None

    def get_city_by_plate(self, plate_code: int) -> Optional[str]:
        """
        Get the city name for a given plate code.

        Args:
            plate_code: The plate code (1-81)

        Returns:
            The city name or None if plate code invalid

        Example:
            >>> generator = TurkishCityGenerator()
            >>> generator.get_city_by_plate(34)
            'İstanbul'
            >>> generator.get_city_by_plate(6)
            'Ankara'
        """
        if 1 <= plate_code <= len(TURKISH_CITIES):
            return TURKISH_CITIES[plate_code - 1]
        return None

    def set_seed(self, seed: int) -> None:
        """
        Set the random seed for reproducible generation.

        Args:
            seed: The random seed value
        """
        self._seed = seed
        self._random = random.Random(seed)


class TurkishPostalCodeGenerator:
    """
    Generator for Turkish postal codes.

    Turkish postal codes are 5 digits:
    - First two digits correspond to the city plate code (01-81)
    - Last three digits are the district/area code (000-999)

    Format: XXYYY where XX is plate code, YYY is area code

    Attributes:
        seed: Optional random seed for reproducible generation

    Example:
        >>> generator = TurkishPostalCodeGenerator(seed=42)
        >>> postal_code = generator.generate()
        >>> len(postal_code)
        5
    """

    def __init__(self, seed: Optional[int] = None):
        """
        Initialize the Turkish postal code generator.

        Args:
            seed: Optional random seed for reproducible generation
        """
        self._seed = seed
        self._random = random.Random(seed)

    def generate(self, city: Optional[str] = None, plate_code: Optional[int] = None) -> str:
        """
        Generate a valid Turkish postal code.

        Args:
            city: Optional city name to generate postal code for
            plate_code: Optional plate code to use (1-81)
            If neither is provided, generates for a random city

        Returns:
            A 5-digit postal code string

        Example:
            >>> generator = TurkishPostalCodeGenerator()
            >>> postal = generator.generate()
            >>> len(postal)
            5
            >>> postal = generator.generate(city="İstanbul")
            >>> postal.startswith('34')
            True
        """
        # Determine plate code
        if plate_code is not None:
            if not 1 <= plate_code <= 81:
                raise ValueError("Plate code must be between 1 and 81")
            pc = plate_code
        elif city is not None:
            city_gen = TurkishCityGenerator()
            pc = city_gen.get_plate_code(city)
            if pc is None:
                raise ValueError(f"Unknown city: {city}")
        else:
            # Random plate code
            pc = self._random.randint(1, 81)

        # Generate area code (000-999)
        area_code = self._random.randint(0, 999)

        # Format: plate code (2 digits, zero-padded) + area code (3 digits, zero-padded)
        return f"{pc:02d}{area_code:03d}"

    def validate(self, postal_code: str) -> bool:
        """
        Validate a Turkish postal code.

        Performs the following validations:
        1. Must be exactly 5 digits
        2. First two digits must be valid plate code (01-81)

        Args:
            postal_code: The postal code to validate

        Returns:
            True if the postal code is valid, False otherwise

        Example:
            >>> generator = TurkishPostalCodeGenerator()
            >>> generator.validate("34000")
            True
            >>> generator.validate("99000")  # Invalid plate code
            False
        """
        postal_str = str(postal_code).strip()

        # Check length
        if len(postal_str) != 5:
            return False

        # Check all characters are digits
        if not postal_str.isdigit():
            return False

        # Check plate code is valid (01-81)
        plate_code = int(postal_str[:2])
        return 1 <= plate_code <= 81

    def get_city(self, postal_code: str) -> Optional[str]:
        """
        Get the city name for a given postal code.

        Args:
            postal_code: The postal code

        Returns:
            The city name or None if postal code invalid

        Example:
            >>> generator = TurkishPostalCodeGenerator()
            >>> generator.get_city("34000")
            'İstanbul'
        """
        if not self.validate(postal_code):
            return None

        plate_code = int(postal_code[:2])
        city_gen = TurkishCityGenerator()
        return city_gen.get_city_by_plate(plate_code)

    def set_seed(self, seed: int) -> None:
        """
        Set the random seed for reproducible generation.

        Args:
            seed: The random seed value
        """
        self._seed = seed
        self._random = random.Random(seed)


class TurkishAddressGenerator:
    """
    Generator for Turkish addresses.

    Generates complete Turkish addresses including:
    - Neighborhood (Mahalle)
    - Street name and type (Cadde/Sokak)
    - Building number
    - Floor and apartment number (optional)
    - Postal code
    - City

    Attributes:
        seed: Optional random seed for reproducible generation

    Example:
        >>> generator = TurkishAddressGenerator(seed=42)
        >>> address = generator.generate()
        >>> 'Mahallesi' in address
        True
    """

    def __init__(self, seed: Optional[int] = None):
        """
        Initialize the Turkish address generator.

        Args:
            seed: Optional random seed for reproducible generation
        """
        self._seed = seed
        self._random = random.Random(seed)
        self._city_gen = TurkishCityGenerator(seed)
        self._postal_gen = TurkishPostalCodeGenerator(seed)

    def generate(
        self,
        city: Optional[str] = None,
        include_apartment: bool = True,
        formatted: bool = True,
    ) -> Union[str, dict]:
        """
        Generate a valid Turkish address.

        Args:
            city: Optional city name. If not provided, generates random city.
            include_apartment: If True, includes floor/apartment details.
            formatted: If True, returns formatted string.
                      If False, returns dict with address components.

        Returns:
            Formatted address string or dict with components

        Example:
            >>> generator = TurkishAddressGenerator()
            >>> address = generator.generate()
            >>> isinstance(address, str)
            True
            >>> components = generator.generate(formatted=False)
            >>> 'city' in components
            True
        """
        # Generate city if not provided
        if city is None:
            city, plate_code = self._city_gen.generate_with_plate_code()
        else:
            plate_code = self._city_gen.get_plate_code(city)
            if plate_code is None:
                raise ValueError(f"Unknown city: {city}")

        # Generate address components
        neighborhood = self._random.choice(TURKISH_NEIGHBORHOODS)
        street_name = self._random.choice(TURKISH_STREET_NAMES)
        street_type = self._random.choice(TURKISH_STREET_TYPES)
        building_no = self._random.randint(1, 200)

        # Generate postal code for this city
        postal_code = self._postal_gen.generate(plate_code=plate_code)

        # Build address components dict
        components = {
            "neighborhood": neighborhood,
            "street_name": street_name,
            "street_type": street_type,
            "building_no": building_no,
            "postal_code": postal_code,
            "city": city,
        }

        if include_apartment:
            floor = self._random.randint(0, 15)  # 0 = ground floor
            apartment = self._random.randint(1, 12)
            components["floor"] = floor
            components["apartment"] = apartment

        if not formatted:
            return components

        # Format address string
        address_parts = [
            f"{neighborhood} Mahallesi",
            f"{street_name} {street_type} No: {building_no}",
        ]

        if include_apartment:
            floor_str = "Zemin Kat" if components["floor"] == 0 else f"{components['floor']}. Kat"
            address_parts.append(f"{floor_str} Daire: {components['apartment']}")

        address_parts.append(f"{postal_code} {city}")

        return ", ".join(address_parts)

    def generate_simple(self, city: Optional[str] = None) -> str:
        """
        Generate a simple Turkish address (neighborhood, street, building only).

        Args:
            city: Optional city name

        Returns:
            Simple formatted address string

        Example:
            >>> generator = TurkishAddressGenerator()
            >>> address = generator.generate_simple()
            >>> 'Mahallesi' in address
            True
        """
        if city is None:
            city = self._city_gen.generate()

        neighborhood = self._random.choice(TURKISH_NEIGHBORHOODS)
        street_name = self._random.choice(TURKISH_STREET_NAMES)
        street_type = self._random.choice(TURKISH_STREET_TYPES)
        building_no = self._random.randint(1, 200)

        return f"{neighborhood} Mahallesi, {street_name} {street_type} No: {building_no}, {city}"

    def set_seed(self, seed: int) -> None:
        """
        Set the random seed for reproducible generation.

        Args:
            seed: The random seed value
        """
        self._seed = seed
        self._random = random.Random(seed)
        self._city_gen.set_seed(seed)
        self._postal_gen.set_seed(seed)


# Module-level generator instances for convenience functions
_default_phone_generator: Optional[TurkishPhoneGenerator] = None
_default_city_generator: Optional[TurkishCityGenerator] = None
_default_postal_generator: Optional[TurkishPostalCodeGenerator] = None
_default_address_generator: Optional[TurkishAddressGenerator] = None


def _get_phone_generator() -> TurkishPhoneGenerator:
    """Get or create the default Turkish phone generator instance."""
    global _default_phone_generator
    if _default_phone_generator is None:
        _default_phone_generator = TurkishPhoneGenerator()
    return _default_phone_generator


def _get_city_generator() -> TurkishCityGenerator:
    """Get or create the default Turkish city generator instance."""
    global _default_city_generator
    if _default_city_generator is None:
        _default_city_generator = TurkishCityGenerator()
    return _default_city_generator


def _get_postal_generator() -> TurkishPostalCodeGenerator:
    """Get or create the default Turkish postal code generator instance."""
    global _default_postal_generator
    if _default_postal_generator is None:
        _default_postal_generator = TurkishPostalCodeGenerator()
    return _default_postal_generator


def _get_address_generator() -> TurkishAddressGenerator:
    """Get or create the default Turkish address generator instance."""
    global _default_address_generator
    if _default_address_generator is None:
        _default_address_generator = TurkishAddressGenerator()
    return _default_address_generator


def generate_turkish_phone(seed: Optional[int] = None, formatted: bool = False) -> str:
    """
    Generate a valid Turkish mobile phone number.

    This is a convenience function that creates and uses a TurkishPhoneGenerator
    instance. For repeated generation, consider using the TurkishPhoneGenerator
    class directly.

    Args:
        seed: Optional random seed for reproducible generation.
        formatted: If True, return formatted number (05XX XXX XX XX)

    Returns:
        A valid Turkish mobile phone number string

    Example:
        >>> phone = generate_turkish_phone()
        >>> phone.startswith('05')
        True
        >>> len(phone)
        10

        >>> # Reproducible generation
        >>> phone1 = generate_turkish_phone(seed=42)
        >>> phone2 = generate_turkish_phone(seed=42)
        >>> phone1 == phone2
        True
    """
    if seed is not None:
        generator = TurkishPhoneGenerator(seed=seed)
        return generator.generate(formatted=formatted)

    return _get_phone_generator().generate(formatted=formatted)


def validate_turkish_phone(phone: str) -> bool:
    """
    Validate a Turkish mobile phone number.

    Args:
        phone: The phone number to validate

    Returns:
        True if the phone number is valid, False otherwise

    Example:
        >>> validate_turkish_phone("05321234567")
        True
        >>> validate_turkish_phone("0212 123 45 67")  # Landline
        False
    """
    return _get_phone_generator().validate(phone)


def generate_turkish_city(seed: Optional[int] = None) -> str:
    """
    Generate a random Turkish city name.

    This is a convenience function that creates and uses a TurkishCityGenerator
    instance.

    Args:
        seed: Optional random seed for reproducible generation.

    Returns:
        A Turkish city name string

    Example:
        >>> city = generate_turkish_city()
        >>> city in TURKISH_CITIES
        True
    """
    if seed is not None:
        generator = TurkishCityGenerator(seed=seed)
        return generator.generate()

    return _get_city_generator().generate()


def generate_turkish_postal_code(
    seed: Optional[int] = None,
    city: Optional[str] = None,
) -> str:
    """
    Generate a valid Turkish postal code.

    This is a convenience function that creates and uses a TurkishPostalCodeGenerator
    instance.

    Args:
        seed: Optional random seed for reproducible generation.
        city: Optional city name to generate postal code for.

    Returns:
        A 5-digit postal code string

    Example:
        >>> postal = generate_turkish_postal_code()
        >>> len(postal)
        5
        >>> postal = generate_turkish_postal_code(city="İstanbul")
        >>> postal.startswith('34')
        True
    """
    if seed is not None:
        generator = TurkishPostalCodeGenerator(seed=seed)
        return generator.generate(city=city)

    return _get_postal_generator().generate(city=city)


def validate_turkish_postal_code(postal_code: str) -> bool:
    """
    Validate a Turkish postal code.

    Args:
        postal_code: The postal code to validate

    Returns:
        True if the postal code is valid, False otherwise

    Example:
        >>> validate_turkish_postal_code("34000")
        True
        >>> validate_turkish_postal_code("99000")
        False
    """
    return _get_postal_generator().validate(postal_code)


def generate_turkish_address(
    seed: Optional[int] = None,
    city: Optional[str] = None,
    include_apartment: bool = True,
) -> str:
    """
    Generate a valid Turkish address.

    This is a convenience function that creates and uses a TurkishAddressGenerator
    instance.

    Args:
        seed: Optional random seed for reproducible generation.
        city: Optional city name for the address.
        include_apartment: If True, includes floor/apartment details.

    Returns:
        A formatted Turkish address string

    Example:
        >>> address = generate_turkish_address()
        >>> 'Mahallesi' in address
        True
        >>> address = generate_turkish_address(city="İstanbul")
        >>> 'İstanbul' in address
        True
    """
    if seed is not None:
        generator = TurkishAddressGenerator(seed=seed)
        return generator.generate(city=city, include_apartment=include_apartment)

    return _get_address_generator().generate(city=city, include_apartment=include_apartment)


# Export all public symbols
__all__ = [
    # TCKN
    "TCKNValidator",
    "generate_valid_tckn",
    "validate_tckn",
    # VKN
    "VKNValidator",
    "generate_valid_vkn",
    "validate_vkn",
    # IBAN
    "TurkishIBANValidator",
    "generate_valid_turkish_iban",
    "validate_turkish_iban",
    "TURKISH_BANK_CODES",
    # Phone
    "TurkishPhoneGenerator",
    "generate_turkish_phone",
    "validate_turkish_phone",
    "TURKISH_MOBILE_PREFIXES",
    # City
    "TurkishCityGenerator",
    "generate_turkish_city",
    "TURKISH_CITIES",
    # Postal Code
    "TurkishPostalCodeGenerator",
    "generate_turkish_postal_code",
    "validate_turkish_postal_code",
    # Address
    "TurkishAddressGenerator",
    "generate_turkish_address",
    "TURKISH_NEIGHBORHOODS",
    "TURKISH_STREET_TYPES",
    "TURKISH_STREET_NAMES",
]

# Copyright (c) 2024, Mock Data Engine and contributors
# For license information, please see license.txt

"""
AI Response Processor for Mock Data Engine.

This module provides utilities for parsing, validating, and extracting data
from AI/LLM responses. It handles various response formats and ensures
generated content meets expected criteria.

Key Features:
- JSON response parsing with fallback handling
- Structured data extraction from text responses
- Response validation against expected formats
- Content cleaning and normalization
- Type coercion for different field types

Usage:
    from mock_data_engine.mock_data_engine.providers.response_processor import (
        AIResponseProcessor,
        ResponseFormat,
        ParsedResponse,
        ResponseValidationError,
    )

    # Create processor
    processor = AIResponseProcessor()

    # Parse JSON response
    result = processor.parse_response(
        content='{"name": "Ahmet Yilmaz", "age": 35}',
        expected_format=ResponseFormat.JSON,
    )

    # Extract single value
    name = processor.extract_value(
        content="Generated name: Ahmet Yilmaz",
        value_type="string",
    )

    # Validate response
    is_valid = processor.validate_response(
        content="Valid company name",
        validation_rules={"min_length": 3, "max_length": 100},
    )

Note:
    The processor uses defensive parsing and provides fallbacks
    when AI responses don't match expected formats exactly.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Pattern, Tuple, Type, Union


# =============================================================================
# Constants
# =============================================================================

# Common patterns for extracting values from text
JSON_PATTERN = re.compile(r'```(?:json)?\s*([\s\S]*?)\s*```', re.IGNORECASE)
JSON_OBJECT_PATTERN = re.compile(r'\{[^{}]*\}', re.DOTALL)
JSON_ARRAY_PATTERN = re.compile(r'\[[^\[\]]*\]', re.DOTALL)

# Patterns for extracting specific value types
NUMBER_PATTERN = re.compile(r'-?\d+(?:\.\d+)?')
INTEGER_PATTERN = re.compile(r'-?\d+')
EMAIL_PATTERN = re.compile(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}')
URL_PATTERN = re.compile(r'https?://[^\s<>"{}|\\^`\[\]]+')
PHONE_PATTERN = re.compile(r'[\+]?[\d\s\-\(\)\.]{7,20}')

# Common unwanted patterns to clean from responses
UNWANTED_PATTERNS = [
    re.compile(r'^["\'`]|["\'`]$'),  # Surrounding quotes
    re.compile(r'^\s*Here\s+is\s+.*?:\s*', re.IGNORECASE),  # "Here is..."
    re.compile(r'^\s*The\s+.*?(?:is|are):\s*', re.IGNORECASE),  # "The X is..."
    re.compile(r'^\s*Generated\s+.*?:\s*', re.IGNORECASE),  # "Generated..."
    re.compile(r'^\s*Result:\s*', re.IGNORECASE),  # "Result:"
    re.compile(r'^\s*Output:\s*', re.IGNORECASE),  # "Output:"
    re.compile(r'^\s*Answer:\s*', re.IGNORECASE),  # "Answer:"
]


# =============================================================================
# Enums
# =============================================================================


class ResponseFormat(Enum):
    """
    Enumeration of expected response formats from AI providers.

    These formats indicate how the AI response should be parsed.
    """

    TEXT = "text"
    JSON = "json"
    JSON_ARRAY = "json_array"
    NUMBER = "number"
    INTEGER = "integer"
    BOOLEAN = "boolean"
    LIST = "list"
    KEY_VALUE = "key_value"

    @classmethod
    def from_string(cls, value: str) -> "ResponseFormat":
        """
        Convert a string to ResponseFormat.

        Args:
            value: The string value to convert.

        Returns:
            The corresponding ResponseFormat.

        Raises:
            ValueError: If the value is not a valid format.
        """
        value_lower = value.lower().strip()
        for fmt in cls:
            if fmt.value == value_lower:
                return fmt
        raise ValueError(
            f"Unknown response format: {value}. "
            f"Supported: {[f.value for f in cls]}"
        )


# =============================================================================
# Exceptions
# =============================================================================


class ResponseProcessingError(Exception):
    """
    Base exception for response processing errors.

    Attributes:
        message: The error message.
        content: The original content that caused the error.
    """

    def __init__(
        self,
        message: str,
        content: Optional[str] = None,
    ):
        """
        Initialize ResponseProcessingError.

        Args:
            message: The error message.
            content: The original content.
        """
        self.message = message
        self.content = content
        super().__init__(message)


class ResponseParseError(ResponseProcessingError):
    """Raised when response parsing fails."""

    pass


class ResponseValidationError(ResponseProcessingError):
    """Raised when response validation fails."""

    pass


class ResponseExtractionError(ResponseProcessingError):
    """Raised when value extraction fails."""

    pass


# =============================================================================
# Data Classes
# =============================================================================


@dataclass
class ParsedResponse:
    """
    Result of parsing an AI response.

    Attributes:
        content: The original raw content.
        parsed_value: The parsed value (could be dict, list, string, etc.).
        format_detected: The detected format of the response.
        is_valid: Whether the response was successfully parsed.
        extraction_method: How the value was extracted.
        warnings: Any warnings during parsing.
    """

    content: str
    parsed_value: Any
    format_detected: ResponseFormat
    is_valid: bool = True
    extraction_method: str = "direct"
    warnings: List[str] = field(default_factory=list)

    def as_string(self) -> str:
        """Get the parsed value as a string."""
        if isinstance(self.parsed_value, str):
            return self.parsed_value
        elif isinstance(self.parsed_value, (dict, list)):
            return json.dumps(self.parsed_value, ensure_ascii=False)
        return str(self.parsed_value)

    def as_dict(self) -> Optional[Dict[str, Any]]:
        """Get the parsed value as a dictionary if possible."""
        if isinstance(self.parsed_value, dict):
            return self.parsed_value
        return None

    def as_list(self) -> Optional[List[Any]]:
        """Get the parsed value as a list if possible."""
        if isinstance(self.parsed_value, list):
            return self.parsed_value
        return None

    def to_dict(self) -> Dict[str, Any]:
        """Convert the result to a dictionary."""
        return {
            "content": self.content,
            "parsed_value": self.parsed_value,
            "format_detected": self.format_detected.value,
            "is_valid": self.is_valid,
            "extraction_method": self.extraction_method,
            "warnings": self.warnings,
        }


@dataclass
class ValidationResult:
    """
    Result of validating an AI response.

    Attributes:
        is_valid: Whether the response passed validation.
        errors: List of validation errors.
        warnings: List of validation warnings.
        cleaned_value: The cleaned/normalized value.
    """

    is_valid: bool
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    cleaned_value: Optional[Any] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert the result to a dictionary."""
        return {
            "is_valid": self.is_valid,
            "errors": self.errors,
            "warnings": self.warnings,
            "cleaned_value": self.cleaned_value,
        }


# =============================================================================
# AIResponseProcessor Implementation
# =============================================================================


class AIResponseProcessor:
    """
    Processor for parsing, validating, and extracting data from AI responses.

    This class provides utilities for handling various response formats
    from LLM providers. It includes defensive parsing, validation,
    and extraction capabilities.

    Key Capabilities:
    - Parse JSON responses with fallback handling
    - Extract structured data from text responses
    - Validate responses against rules/schemas
    - Clean and normalize content
    - Type coercion for different field types

    Usage:
        >>> processor = AIResponseProcessor()
        >>> result = processor.parse_response(
        ...     content='{"name": "Test"}',
        ...     expected_format=ResponseFormat.JSON,
        ... )
        >>> print(result.parsed_value)
        {"name": "Test"}

    Attributes:
        strict_mode: If True, raises errors on parsing failures.
                     If False (default), returns fallback values.
    """

    def __init__(self, strict_mode: bool = False):
        """
        Initialize the AIResponseProcessor.

        Args:
            strict_mode: If True, raises exceptions on parsing failures.
                         If False, attempts fallback parsing.
        """
        self._strict_mode = strict_mode

    @property
    def strict_mode(self) -> bool:
        """Get the strict mode setting."""
        return self._strict_mode

    # -------------------------------------------------------------------------
    # Response Parsing
    # -------------------------------------------------------------------------

    def parse_response(
        self,
        content: str,
        expected_format: ResponseFormat = ResponseFormat.TEXT,
        schema: Optional[Dict[str, Any]] = None,
    ) -> ParsedResponse:
        """
        Parse an AI response into structured data.

        This method attempts to parse the response according to the
        expected format, with fallback handling for malformed responses.

        Args:
            content: The raw response content from the AI.
            expected_format: The expected format of the response.
            schema: Optional schema for validation (for JSON format).

        Returns:
            ParsedResponse with the parsed value and metadata.

        Raises:
            ResponseParseError: If parsing fails in strict mode.

        Example:
            >>> processor.parse_response(
            ...     content='```json\\n{"name": "Test"}\\n```',
            ...     expected_format=ResponseFormat.JSON,
            ... )
        """
        if not content:
            return ParsedResponse(
                content=content,
                parsed_value=None,
                format_detected=ResponseFormat.TEXT,
                is_valid=False,
                warnings=["Empty content received"],
            )

        # Clean the content first
        cleaned_content = self._clean_content(content)

        # Parse based on expected format
        parser_map: Dict[ResponseFormat, Callable] = {
            ResponseFormat.TEXT: self._parse_text,
            ResponseFormat.JSON: self._parse_json,
            ResponseFormat.JSON_ARRAY: self._parse_json_array,
            ResponseFormat.NUMBER: self._parse_number,
            ResponseFormat.INTEGER: self._parse_integer,
            ResponseFormat.BOOLEAN: self._parse_boolean,
            ResponseFormat.LIST: self._parse_list,
            ResponseFormat.KEY_VALUE: self._parse_key_value,
        }

        parser = parser_map.get(expected_format, self._parse_text)
        return parser(content, cleaned_content, schema)

    def _parse_text(
        self,
        original: str,
        cleaned: str,
        schema: Optional[Dict[str, Any]] = None,
    ) -> ParsedResponse:
        """Parse content as plain text."""
        return ParsedResponse(
            content=original,
            parsed_value=cleaned,
            format_detected=ResponseFormat.TEXT,
            is_valid=True,
            extraction_method="text_clean",
        )

    def _parse_json(
        self,
        original: str,
        cleaned: str,
        schema: Optional[Dict[str, Any]] = None,
    ) -> ParsedResponse:
        """
        Parse content as JSON with fallback handling.

        Tries multiple strategies:
        1. Direct JSON parse
        2. Extract from markdown code block
        3. Find JSON object in text
        """
        warnings: List[str] = []

        # Strategy 1: Direct parse
        try:
            parsed = json.loads(cleaned)
            return ParsedResponse(
                content=original,
                parsed_value=parsed,
                format_detected=ResponseFormat.JSON,
                is_valid=True,
                extraction_method="direct_json",
            )
        except json.JSONDecodeError:
            pass

        # Strategy 2: Extract from markdown code block
        match = JSON_PATTERN.search(original)
        if match:
            try:
                parsed = json.loads(match.group(1).strip())
                warnings.append("Extracted JSON from markdown code block")
                return ParsedResponse(
                    content=original,
                    parsed_value=parsed,
                    format_detected=ResponseFormat.JSON,
                    is_valid=True,
                    extraction_method="markdown_extraction",
                    warnings=warnings,
                )
            except json.JSONDecodeError:
                pass

        # Strategy 3: Find JSON object in text
        match = JSON_OBJECT_PATTERN.search(original)
        if match:
            try:
                parsed = json.loads(match.group())
                warnings.append("Extracted JSON object from surrounding text")
                return ParsedResponse(
                    content=original,
                    parsed_value=parsed,
                    format_detected=ResponseFormat.JSON,
                    is_valid=True,
                    extraction_method="object_extraction",
                    warnings=warnings,
                )
            except json.JSONDecodeError:
                pass

        # All strategies failed
        if self._strict_mode:
            raise ResponseParseError(
                "Failed to parse content as JSON",
                content=original,
            )

        # Return as text fallback
        return ParsedResponse(
            content=original,
            parsed_value=cleaned,
            format_detected=ResponseFormat.TEXT,
            is_valid=False,
            extraction_method="text_fallback",
            warnings=["Failed to parse as JSON, returned as text"],
        )

    def _parse_json_array(
        self,
        original: str,
        cleaned: str,
        schema: Optional[Dict[str, Any]] = None,
    ) -> ParsedResponse:
        """Parse content as JSON array."""
        warnings: List[str] = []

        # Try direct parse first
        try:
            parsed = json.loads(cleaned)
            if isinstance(parsed, list):
                return ParsedResponse(
                    content=original,
                    parsed_value=parsed,
                    format_detected=ResponseFormat.JSON_ARRAY,
                    is_valid=True,
                    extraction_method="direct_json",
                )
        except json.JSONDecodeError:
            pass

        # Try extracting array from text
        match = JSON_ARRAY_PATTERN.search(original)
        if match:
            try:
                parsed = json.loads(match.group())
                if isinstance(parsed, list):
                    warnings.append("Extracted JSON array from text")
                    return ParsedResponse(
                        content=original,
                        parsed_value=parsed,
                        format_detected=ResponseFormat.JSON_ARRAY,
                        is_valid=True,
                        extraction_method="array_extraction",
                        warnings=warnings,
                    )
            except json.JSONDecodeError:
                pass

        if self._strict_mode:
            raise ResponseParseError(
                "Failed to parse content as JSON array",
                content=original,
            )

        return ParsedResponse(
            content=original,
            parsed_value=[cleaned] if cleaned else [],
            format_detected=ResponseFormat.LIST,
            is_valid=False,
            extraction_method="text_fallback",
            warnings=["Failed to parse as JSON array, returned as single-item list"],
        )

    def _parse_number(
        self,
        original: str,
        cleaned: str,
        schema: Optional[Dict[str, Any]] = None,
    ) -> ParsedResponse:
        """Parse content as a number (float)."""
        # Try direct conversion
        try:
            value = float(cleaned)
            return ParsedResponse(
                content=original,
                parsed_value=value,
                format_detected=ResponseFormat.NUMBER,
                is_valid=True,
                extraction_method="direct_parse",
            )
        except ValueError:
            pass

        # Extract number from text
        match = NUMBER_PATTERN.search(original)
        if match:
            try:
                value = float(match.group())
                return ParsedResponse(
                    content=original,
                    parsed_value=value,
                    format_detected=ResponseFormat.NUMBER,
                    is_valid=True,
                    extraction_method="regex_extraction",
                    warnings=["Extracted number from text"],
                )
            except ValueError:
                pass

        if self._strict_mode:
            raise ResponseParseError(
                "Failed to parse content as number",
                content=original,
            )

        return ParsedResponse(
            content=original,
            parsed_value=0.0,
            format_detected=ResponseFormat.NUMBER,
            is_valid=False,
            extraction_method="default_fallback",
            warnings=["Failed to parse number, returned 0.0"],
        )

    def _parse_integer(
        self,
        original: str,
        cleaned: str,
        schema: Optional[Dict[str, Any]] = None,
    ) -> ParsedResponse:
        """Parse content as an integer."""
        # Try direct conversion
        try:
            # Handle float strings by truncating
            if "." in cleaned:
                value = int(float(cleaned))
            else:
                value = int(cleaned)
            return ParsedResponse(
                content=original,
                parsed_value=value,
                format_detected=ResponseFormat.INTEGER,
                is_valid=True,
                extraction_method="direct_parse",
            )
        except ValueError:
            pass

        # Extract integer from text
        match = INTEGER_PATTERN.search(original)
        if match:
            try:
                value = int(match.group())
                return ParsedResponse(
                    content=original,
                    parsed_value=value,
                    format_detected=ResponseFormat.INTEGER,
                    is_valid=True,
                    extraction_method="regex_extraction",
                    warnings=["Extracted integer from text"],
                )
            except ValueError:
                pass

        if self._strict_mode:
            raise ResponseParseError(
                "Failed to parse content as integer",
                content=original,
            )

        return ParsedResponse(
            content=original,
            parsed_value=0,
            format_detected=ResponseFormat.INTEGER,
            is_valid=False,
            extraction_method="default_fallback",
            warnings=["Failed to parse integer, returned 0"],
        )

    def _parse_boolean(
        self,
        original: str,
        cleaned: str,
        schema: Optional[Dict[str, Any]] = None,
    ) -> ParsedResponse:
        """Parse content as a boolean."""
        cleaned_lower = cleaned.lower().strip()

        # True values
        if cleaned_lower in ("true", "yes", "1", "on", "enabled", "evet"):
            return ParsedResponse(
                content=original,
                parsed_value=True,
                format_detected=ResponseFormat.BOOLEAN,
                is_valid=True,
                extraction_method="direct_parse",
            )

        # False values
        if cleaned_lower in ("false", "no", "0", "off", "disabled", "hayir"):
            return ParsedResponse(
                content=original,
                parsed_value=False,
                format_detected=ResponseFormat.BOOLEAN,
                is_valid=True,
                extraction_method="direct_parse",
            )

        if self._strict_mode:
            raise ResponseParseError(
                "Failed to parse content as boolean",
                content=original,
            )

        # Default to False for unrecognized
        return ParsedResponse(
            content=original,
            parsed_value=False,
            format_detected=ResponseFormat.BOOLEAN,
            is_valid=False,
            extraction_method="default_fallback",
            warnings=["Unrecognized boolean value, defaulted to False"],
        )

    def _parse_list(
        self,
        original: str,
        cleaned: str,
        schema: Optional[Dict[str, Any]] = None,
    ) -> ParsedResponse:
        """Parse content as a list."""
        warnings: List[str] = []

        # Try JSON array first
        try:
            parsed = json.loads(cleaned)
            if isinstance(parsed, list):
                return ParsedResponse(
                    content=original,
                    parsed_value=parsed,
                    format_detected=ResponseFormat.LIST,
                    is_valid=True,
                    extraction_method="json_parse",
                )
        except json.JSONDecodeError:
            pass

        # Try splitting by newlines or commas
        if "\n" in cleaned:
            items = [
                line.strip().lstrip("- ").lstrip("* ").strip()
                for line in cleaned.split("\n")
                if line.strip() and not line.strip().startswith("#")
            ]
            if items:
                warnings.append("Parsed list from newline-separated text")
                return ParsedResponse(
                    content=original,
                    parsed_value=items,
                    format_detected=ResponseFormat.LIST,
                    is_valid=True,
                    extraction_method="newline_split",
                    warnings=warnings,
                )

        # Try comma separation
        if "," in cleaned:
            items = [item.strip() for item in cleaned.split(",") if item.strip()]
            if len(items) > 1:
                warnings.append("Parsed list from comma-separated text")
                return ParsedResponse(
                    content=original,
                    parsed_value=items,
                    format_detected=ResponseFormat.LIST,
                    is_valid=True,
                    extraction_method="comma_split",
                    warnings=warnings,
                )

        # Return as single-item list
        return ParsedResponse(
            content=original,
            parsed_value=[cleaned] if cleaned else [],
            format_detected=ResponseFormat.LIST,
            is_valid=True,
            extraction_method="single_item",
            warnings=["Content returned as single-item list"],
        )

    def _parse_key_value(
        self,
        original: str,
        cleaned: str,
        schema: Optional[Dict[str, Any]] = None,
    ) -> ParsedResponse:
        """Parse content as key-value pairs."""
        # Try JSON first
        try:
            parsed = json.loads(cleaned)
            if isinstance(parsed, dict):
                return ParsedResponse(
                    content=original,
                    parsed_value=parsed,
                    format_detected=ResponseFormat.KEY_VALUE,
                    is_valid=True,
                    extraction_method="json_parse",
                )
        except json.JSONDecodeError:
            pass

        # Try parsing key: value or key = value format
        result: Dict[str, str] = {}
        warnings: List[str] = []

        for line in cleaned.split("\n"):
            line = line.strip()
            if not line:
                continue

            # Try key: value format
            if ":" in line:
                key, _, value = line.partition(":")
                result[key.strip()] = value.strip()
            # Try key = value format
            elif "=" in line:
                key, _, value = line.partition("=")
                result[key.strip()] = value.strip()

        if result:
            warnings.append("Parsed key-value pairs from text")
            return ParsedResponse(
                content=original,
                parsed_value=result,
                format_detected=ResponseFormat.KEY_VALUE,
                is_valid=True,
                extraction_method="text_parse",
                warnings=warnings,
            )

        if self._strict_mode:
            raise ResponseParseError(
                "Failed to parse content as key-value pairs",
                content=original,
            )

        return ParsedResponse(
            content=original,
            parsed_value={"value": cleaned},
            format_detected=ResponseFormat.KEY_VALUE,
            is_valid=False,
            extraction_method="default_fallback",
            warnings=["Failed to parse key-value, wrapped in dict"],
        )

    # -------------------------------------------------------------------------
    # Content Cleaning
    # -------------------------------------------------------------------------

    def _clean_content(self, content: str) -> str:
        """
        Clean and normalize content.

        Removes common AI response artifacts and normalizes whitespace.

        Args:
            content: The raw content to clean.

        Returns:
            Cleaned content string.
        """
        if not content:
            return ""

        cleaned = content.strip()

        # Remove common prefixes
        for pattern in UNWANTED_PATTERNS:
            cleaned = pattern.sub("", cleaned).strip()

        # Remove surrounding quotes if present
        if len(cleaned) >= 2:
            if (cleaned[0] == '"' and cleaned[-1] == '"') or \
               (cleaned[0] == "'" and cleaned[-1] == "'"):
                cleaned = cleaned[1:-1]

        return cleaned.strip()

    def clean_for_field_type(
        self,
        content: str,
        field_type: str,
    ) -> str:
        """
        Clean content based on target field type.

        Args:
            content: The content to clean.
            field_type: The Frappe field type (e.g., "Data", "Int", "Currency").

        Returns:
            Cleaned content appropriate for the field type.
        """
        cleaned = self._clean_content(content)

        if field_type in ("Int", "Long Int"):
            # Extract integer
            match = INTEGER_PATTERN.search(cleaned)
            return match.group() if match else "0"

        elif field_type in ("Float", "Currency", "Percent"):
            # Extract number
            match = NUMBER_PATTERN.search(cleaned)
            return match.group() if match else "0.0"

        elif field_type == "Check":
            # Boolean field
            lower = cleaned.lower()
            return "1" if lower in ("true", "yes", "1", "on", "evet") else "0"

        elif field_type in ("Phone", "Link Dynamic"):
            # Extract phone number
            match = PHONE_PATTERN.search(cleaned)
            return match.group() if match else cleaned

        elif field_type == "Email":
            # Extract email
            match = EMAIL_PATTERN.search(cleaned)
            return match.group() if match else cleaned

        elif field_type in ("Data", "Small Text", "Text", "Long Text", "Text Editor"):
            # Keep text as is (already cleaned)
            return cleaned

        return cleaned

    # -------------------------------------------------------------------------
    # Value Extraction
    # -------------------------------------------------------------------------

    def extract_value(
        self,
        content: str,
        value_type: str = "string",
        pattern: Optional[str] = None,
    ) -> Any:
        """
        Extract a single value from AI response content.

        Args:
            content: The response content.
            value_type: Type of value to extract ("string", "number", "integer",
                        "boolean", "email", "url", "phone").
            pattern: Optional regex pattern for custom extraction.

        Returns:
            The extracted value.

        Raises:
            ResponseExtractionError: If extraction fails in strict mode.
        """
        cleaned = self._clean_content(content)

        if pattern:
            # Custom pattern extraction
            compiled = re.compile(pattern)
            match = compiled.search(cleaned)
            if match:
                return match.group(1) if match.groups() else match.group()
            if self._strict_mode:
                raise ResponseExtractionError(
                    f"Pattern not found: {pattern}",
                    content=content,
                )
            return cleaned

        # Type-based extraction
        extractors: Dict[str, Tuple[Pattern, Any]] = {
            "number": (NUMBER_PATTERN, 0.0),
            "integer": (INTEGER_PATTERN, 0),
            "email": (EMAIL_PATTERN, ""),
            "url": (URL_PATTERN, ""),
            "phone": (PHONE_PATTERN, ""),
        }

        if value_type in extractors:
            regex, default = extractors[value_type]
            match = regex.search(cleaned)
            if match:
                value = match.group()
                if value_type == "number":
                    return float(value)
                elif value_type == "integer":
                    return int(value)
                return value
            return default

        if value_type == "boolean":
            return cleaned.lower() in ("true", "yes", "1", "on", "evet")

        # Default: return string
        return cleaned

    def extract_multiple_values(
        self,
        content: str,
        keys: List[str],
    ) -> Dict[str, Any]:
        """
        Extract multiple named values from AI response.

        Attempts to find key-value pairs in the response.

        Args:
            content: The response content.
            keys: List of keys to extract.

        Returns:
            Dictionary with extracted values (keys not found will be None).
        """
        # First try JSON parsing
        try:
            parsed = json.loads(self._clean_content(content))
            if isinstance(parsed, dict):
                return {key: parsed.get(key) for key in keys}
        except json.JSONDecodeError:
            pass

        # Fall back to text pattern matching
        result: Dict[str, Any] = {key: None for key in keys}

        for key in keys:
            # Try various patterns
            patterns = [
                rf'"{key}"\s*:\s*"([^"]*)"',  # JSON-style
                rf"'{key}'\s*:\s*'([^']*)'",  # Single quote JSON
                rf'{key}\s*:\s*([^\n,}}]+)',  # Key: value
                rf'{key}\s*=\s*([^\n,]+)',    # Key = value
            ]

            for pattern in patterns:
                match = re.search(pattern, content, re.IGNORECASE)
                if match:
                    result[key] = match.group(1).strip().strip('"\'')
                    break

        return result

    # -------------------------------------------------------------------------
    # Validation
    # -------------------------------------------------------------------------

    def validate_response(
        self,
        content: str,
        validation_rules: Optional[Dict[str, Any]] = None,
    ) -> ValidationResult:
        """
        Validate AI response against specified rules.

        Args:
            content: The response content to validate.
            validation_rules: Dictionary of validation rules:
                - min_length: Minimum content length
                - max_length: Maximum content length
                - required: Whether content is required (non-empty)
                - pattern: Regex pattern to match
                - allowed_values: List of allowed values
                - type: Expected type ("string", "number", "email", etc.)

        Returns:
            ValidationResult with validation status and details.
        """
        if not validation_rules:
            return ValidationResult(
                is_valid=bool(content),
                cleaned_value=self._clean_content(content) if content else None,
            )

        errors: List[str] = []
        warnings: List[str] = []
        cleaned = self._clean_content(content) if content else ""

        # Required check
        if validation_rules.get("required", False) and not cleaned:
            errors.append("Content is required but empty")

        # Length checks
        if "min_length" in validation_rules:
            min_len = validation_rules["min_length"]
            if len(cleaned) < min_len:
                errors.append(f"Content too short: {len(cleaned)} < {min_len}")

        if "max_length" in validation_rules:
            max_len = validation_rules["max_length"]
            if len(cleaned) > max_len:
                warnings.append(f"Content truncated from {len(cleaned)} to {max_len}")
                cleaned = cleaned[:max_len]

        # Pattern check
        if "pattern" in validation_rules:
            pattern = validation_rules["pattern"]
            if not re.search(pattern, cleaned):
                errors.append(f"Content does not match pattern: {pattern}")

        # Allowed values check
        if "allowed_values" in validation_rules:
            allowed = validation_rules["allowed_values"]
            if cleaned not in allowed:
                errors.append(f"Value not in allowed list: {allowed}")

        # Type check
        if "type" in validation_rules:
            type_name = validation_rules["type"]
            type_check_errors = self._validate_type(cleaned, type_name)
            errors.extend(type_check_errors)

        return ValidationResult(
            is_valid=len(errors) == 0,
            errors=errors,
            warnings=warnings,
            cleaned_value=cleaned,
        )

    def _validate_type(self, content: str, type_name: str) -> List[str]:
        """
        Validate content matches expected type.

        Args:
            content: The content to validate.
            type_name: Expected type name.

        Returns:
            List of error messages (empty if valid).
        """
        errors: List[str] = []

        if type_name == "email":
            if not EMAIL_PATTERN.match(content):
                errors.append("Invalid email format")

        elif type_name == "url":
            if not URL_PATTERN.match(content):
                errors.append("Invalid URL format")

        elif type_name == "phone":
            if not PHONE_PATTERN.match(content):
                errors.append("Invalid phone format")

        elif type_name == "number":
            try:
                float(content)
            except ValueError:
                errors.append("Invalid number format")

        elif type_name == "integer":
            try:
                int(content)
            except ValueError:
                errors.append("Invalid integer format")

        return errors

    # -------------------------------------------------------------------------
    # Utility Methods
    # -------------------------------------------------------------------------

    def truncate_content(
        self,
        content: str,
        max_length: int,
        suffix: str = "...",
    ) -> str:
        """
        Truncate content to maximum length.

        Args:
            content: The content to truncate.
            max_length: Maximum length.
            suffix: Suffix to add if truncated.

        Returns:
            Truncated content.
        """
        if len(content) <= max_length:
            return content

        truncate_at = max_length - len(suffix)
        if truncate_at <= 0:
            return content[:max_length]

        return content[:truncate_at] + suffix

    def normalize_whitespace(self, content: str) -> str:
        """
        Normalize whitespace in content.

        Args:
            content: The content to normalize.

        Returns:
            Content with normalized whitespace.
        """
        # Replace multiple whitespace with single space
        normalized = re.sub(r'\s+', ' ', content)
        return normalized.strip()

    def __repr__(self) -> str:
        """String representation of the processor."""
        return f"AIResponseProcessor(strict_mode={self._strict_mode})"


# =============================================================================
# Factory Functions
# =============================================================================


def create_response_processor(
    strict_mode: bool = False,
) -> AIResponseProcessor:
    """
    Factory function to create an AIResponseProcessor instance.

    Args:
        strict_mode: If True, raises exceptions on parsing failures.

    Returns:
        Configured AIResponseProcessor instance.

    Example:
        >>> processor = create_response_processor(strict_mode=True)
        >>> result = processor.parse_response('{"key": "value"}')
    """
    return AIResponseProcessor(strict_mode=strict_mode)


# =============================================================================
# Module Exports
# =============================================================================

__all__ = [
    # Main class
    "AIResponseProcessor",
    # Factory function
    "create_response_processor",
    # Data classes
    "ParsedResponse",
    "ValidationResult",
    # Enums
    "ResponseFormat",
    # Exceptions
    "ResponseProcessingError",
    "ResponseParseError",
    "ResponseValidationError",
    "ResponseExtractionError",
]

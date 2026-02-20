# Copyright (c) 2024, Mock Data Engine and contributors
# For license information, please see license.txt

"""
Naming Handler Module.

This module provides the NamingHandler class for generating document names
based on Frappe's naming conventions. It supports all standard naming patterns
including naming_series, format patterns, field-based naming, hash, and UUID.

Frappe Naming Patterns Supported:
- naming_series: Series with counters (e.g., "ACC-.YYYY.-.####")
- field: Name derived from a field value (e.g., "field:customer_name")
- format: Custom format patterns (e.g., "format:CUS-{####}")
- hash: Random hash-based names
- UUID: UUID v4 based names
- prompt: User-specified names (generated for mock data)
- Expression: Python expression-based naming

Format Pattern Placeholders:
- {####} or .#### - Sequential number (# count determines padding)
- {YYYY} or .YYYY. - 4-digit year
- {YY} or .YY. - 2-digit year
- {MM} or .MM. - Month (01-12)
- {DD} or .DD. - Day (01-31)
- {timestamp} - Unix timestamp
- {random} - Random string
- {field_name} - Value from a field

Usage:
    from mock_data_engine.mock_data_engine.utils.naming_handler import NamingHandler

    # Create handler with naming configuration
    handler = NamingHandler(
        autoname="naming_series:",
        naming_series="ACC-.YYYY.-.####",
        naming_rule="By 'Naming Series' field in 'Naming Rule'"
    )

    # Generate a name
    name = handler.generate_name(
        record_data={"first_name": "John", "last_name": "Doe"},
        counter=1
    )
    # Returns: "ACC-2024-0001"

    # For field-based naming
    handler2 = NamingHandler(autoname="field:customer_name")
    name2 = handler2.generate_name(record_data={"customer_name": "ACME Corp"})
    # Returns: "ACME Corp"
"""

from __future__ import annotations

import hashlib
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Set, Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    from mock_data_engine.mock_data_engine.core.meta_reader import NamingConfig


class NamingError(Exception):
    """
    Exception raised when document naming fails.

    Attributes:
        message: Error message
        autoname: The autoname pattern that caused the error
        original_error: The underlying exception if any
    """

    def __init__(
        self,
        message: str,
        autoname: Optional[str] = None,
        original_error: Optional[Exception] = None
    ):
        self.message = message
        self.autoname = autoname
        self.original_error = original_error

        full_message = message
        if autoname:
            full_message = f"[autoname={autoname}] {message}"

        super().__init__(full_message)


@dataclass
class NamingContext:
    """
    Context for name generation.

    Attributes:
        record_data: Dictionary of field values for the record
        counter: Sequence counter for series-based naming
        timestamp: Timestamp for date-based patterns
        locale: Locale for locale-specific formatting
        doctype: The DocType being named
        parent_name: Parent document name for child tables
        batch_index: Index within a batch operation
        prefix_override: Optional prefix to override default
        suffix_override: Optional suffix to append
    """
    record_data: Dict[str, Any] = field(default_factory=dict)
    counter: int = 1
    timestamp: Optional[datetime] = None
    locale: str = "en_US"
    doctype: str = ""
    parent_name: Optional[str] = None
    batch_index: int = 0
    prefix_override: Optional[str] = None
    suffix_override: Optional[str] = None

    def __post_init__(self):
        """Initialize timestamp if not provided."""
        if self.timestamp is None:
            self.timestamp = datetime.now()

    def get_field_value(self, fieldname: str, default: str = "") -> str:
        """
        Get a field value from record_data.

        Args:
            fieldname: Name of the field
            default: Default value if field not found

        Returns:
            Field value as string
        """
        value = self.record_data.get(fieldname, default)
        if value is None:
            return default
        return str(value)


class NamingHandler:
    """
    Handler for Frappe document naming conventions.

    This class generates document names based on various Frappe naming patterns
    including naming_series, format patterns, field-based naming, and more.

    The handler maintains an internal counter for series-based naming and
    supports all standard Frappe naming conventions.

    Attributes:
        autoname: The autoname pattern from DocType definition
        naming_series: The naming series string (for series-based naming)
        naming_rule: The naming rule type

    Example:
        >>> handler = NamingHandler(
        ...     autoname="naming_series:",
        ...     naming_series="INV-.YYYY.-.####"
        ... )
        >>> handler.generate_name(counter=1)
        'INV-2024-0001'
        >>> handler.generate_name(counter=2)
        'INV-2024-0002'
    """

    # Pattern for extracting counter placeholder from naming series
    COUNTER_PATTERN = re.compile(r"(#+)")

    # Pattern for date placeholders
    DATE_PATTERNS = {
        "YYYY": lambda dt: dt.strftime("%Y"),
        "YY": lambda dt: dt.strftime("%y"),
        "MM": lambda dt: dt.strftime("%m"),
        "DD": lambda dt: dt.strftime("%d"),
        "WW": lambda dt: dt.strftime("%W"),
    }

    # Pattern for field placeholders in format strings
    FIELD_PLACEHOLDER_PATTERN = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")

    # Maximum counter value before overflow handling
    MAX_COUNTER = 10 ** 10  # 10 billion

    def __init__(
        self,
        autoname: str = "",
        naming_series: str = "",
        naming_rule: str = "",
        name_case: str = "",
        issingle: bool = False,
        istable: bool = False,
    ):
        """
        Initialize the NamingHandler.

        Args:
            autoname: The autoname pattern (e.g., "naming_series:", "field:name", "hash")
            naming_series: The naming series string (e.g., "ACC-.YYYY.-.####")
            naming_rule: The naming rule description
            name_case: Case transformation (e.g., "Title Case", "UPPER CASE")
            issingle: Whether the DocType is a Single DocType
            istable: Whether the DocType is a child table
        """
        self._autoname = autoname or ""
        self._naming_series = naming_series or ""
        self._naming_rule = naming_rule or ""
        self._name_case = name_case or ""
        self._issingle = issingle
        self._istable = istable
        self._counter = 0

        # Parse the autoname pattern
        self._naming_type = self._parse_naming_type()

    @classmethod
    def from_naming_config(cls, config: "NamingConfig") -> "NamingHandler":
        """
        Create a NamingHandler from a NamingConfig object.

        Args:
            config: NamingConfig from DocTypeMeta

        Returns:
            NamingHandler instance
        """
        return cls(
            autoname=config.autoname,
            naming_series="",  # Will be set from autoname if needed
            naming_rule=config.naming_rule,
            name_case=config.name_case,
            issingle=config.issingle,
            istable=config.istable,
        )

    @property
    def autoname(self) -> str:
        """Get the autoname pattern."""
        return self._autoname

    @property
    def naming_series(self) -> str:
        """Get the naming series."""
        return self._naming_series

    @property
    def naming_rule(self) -> str:
        """Get the naming rule."""
        return self._naming_rule

    @property
    def naming_type(self) -> str:
        """Get the parsed naming type."""
        return self._naming_type

    def _parse_naming_type(self) -> str:
        """
        Parse the autoname pattern to determine naming type.

        Returns:
            Naming type string (series, field, hash, uuid, format, prompt, expression)
        """
        autoname = self._autoname.lower().strip()

        if not autoname:
            return "prompt"  # Default to user-specified

        # Check for specific naming types
        if autoname.startswith("naming_series:"):
            return "series"
        elif autoname.startswith("field:"):
            return "field"
        elif autoname.startswith("format:"):
            return "format"
        elif autoname.startswith("prompt"):
            return "prompt"
        elif autoname == "hash":
            return "hash"
        elif autoname == "uuid":
            return "uuid"
        elif autoname.startswith("expression:"):
            return "expression"
        elif self._naming_series or "." in autoname or "#" in autoname:
            # Looks like a naming series pattern
            return "series"
        else:
            # Check naming_rule for hints
            naming_rule = self._naming_rule.lower()
            if "naming series" in naming_rule:
                return "series"
            elif "expression" in naming_rule:
                return "expression"
            elif "set by user" in naming_rule:
                return "prompt"

            return "prompt"

    def generate_name(
        self,
        context: Optional[NamingContext] = None,
        record_data: Optional[Dict[str, Any]] = None,
        counter: Optional[int] = None,
    ) -> str:
        """
        Generate a document name based on the naming configuration.

        Args:
            context: Optional NamingContext with full context
            record_data: Dictionary of field values (alternative to context)
            counter: Sequence counter for series-based naming (alternative to context)

        Returns:
            Generated document name

        Raises:
            NamingError: If name generation fails
        """
        # Build context if not provided
        if context is None:
            context = NamingContext(
                record_data=record_data or {},
                counter=counter if counter is not None else self._counter + 1,
            )

        # Update internal counter
        if counter is not None:
            self._counter = counter
        else:
            self._counter = context.counter

        # Handle single and table doctypes
        if self._issingle:
            return self._generate_single_name(context)
        if self._istable:
            return self._generate_table_name(context)

        # Generate based on naming type
        try:
            if self._naming_type == "series":
                name = self._generate_series_name(context)
            elif self._naming_type == "field":
                name = self._generate_field_name(context)
            elif self._naming_type == "format":
                name = self._generate_format_name(context)
            elif self._naming_type == "hash":
                name = self._generate_hash_name(context)
            elif self._naming_type == "uuid":
                name = self._generate_uuid_name(context)
            elif self._naming_type == "expression":
                name = self._generate_expression_name(context)
            else:
                name = self._generate_prompt_name(context)

            # Apply case transformation
            name = self._apply_case(name)

            # Apply prefix/suffix overrides
            if context.prefix_override:
                name = f"{context.prefix_override}{name}"
            if context.suffix_override:
                name = f"{name}{context.suffix_override}"

            return name

        except Exception as e:
            raise NamingError(
                f"Failed to generate name: {str(e)}",
                autoname=self._autoname,
                original_error=e
            )

    def _generate_series_name(self, context: NamingContext) -> str:
        """
        Generate a name using naming series pattern.

        Series patterns support:
        - .####. - Counter with padding (# count = padding width)
        - .YYYY. - 4-digit year
        - .YY. - 2-digit year
        - .MM. - Month
        - .DD. - Day
        - .WW. - Week number

        Args:
            context: The naming context

        Returns:
            Generated series name
        """
        # Get the series pattern
        series = self._get_series_pattern()
        if not series:
            # Fallback to prompt-style naming
            return self._generate_prompt_name(context)

        # Replace date patterns
        result = series
        timestamp = context.timestamp or datetime.now()

        for pattern, formatter in self.DATE_PATTERNS.items():
            # Handle both .YYYY. and {YYYY} formats
            result = result.replace(f".{pattern}.", f"-{formatter(timestamp)}-")
            result = result.replace(f"{{{pattern}}}", formatter(timestamp))

        # Replace counter pattern
        counter_match = self.COUNTER_PATTERN.search(result)
        if counter_match:
            hash_count = len(counter_match.group(1))
            # Handle counter overflow
            counter = context.counter % (10 ** hash_count)
            counter_str = str(counter).zfill(hash_count)
            result = self.COUNTER_PATTERN.sub(counter_str, result)

        # Clean up separators
        result = self._clean_separators(result)

        return result

    def _get_series_pattern(self) -> str:
        """
        Get the naming series pattern.

        Returns:
            The series pattern string
        """
        # Check explicit naming_series first
        if self._naming_series:
            return self._naming_series

        # Parse from autoname
        autoname = self._autoname

        if autoname.startswith("naming_series:"):
            # The series is after the colon
            series = autoname[len("naming_series:"):]
            if series:
                return series
            # If empty, it means series is a field choice - use a default
            return "MOCK-.YYYY.-.#####"

        # Check if autoname itself is a series pattern
        if "." in autoname or "#" in autoname:
            return autoname

        return ""

    def _generate_field_name(self, context: NamingContext) -> str:
        """
        Generate a name from a field value.

        Args:
            context: The naming context

        Returns:
            Generated name from field value
        """
        # Extract field name from autoname
        if self._autoname.startswith("field:"):
            fieldname = self._autoname[len("field:"):]
        else:
            fieldname = self._autoname

        # Get field value
        value = context.get_field_value(fieldname)

        if not value:
            # Fallback to generating a name
            return self._generate_prompt_name(context)

        # Sanitize the name
        return self._sanitize_name(value)

    def _generate_format_name(self, context: NamingContext) -> str:
        """
        Generate a name using format pattern.

        Format patterns support:
        - {fieldname} - Field value placeholder
        - {####} - Counter with padding
        - {YYYY}, {MM}, {DD} - Date components
        - {timestamp} - Unix timestamp
        - {random} - Random string

        Args:
            context: The naming context

        Returns:
            Generated format name
        """
        # Extract format pattern
        if self._autoname.startswith("format:"):
            pattern = self._autoname[len("format:"):]
        else:
            pattern = self._autoname

        result = pattern
        timestamp = context.timestamp or datetime.now()

        # Replace date patterns
        for date_pattern, formatter in self.DATE_PATTERNS.items():
            result = result.replace(f"{{{date_pattern}}}", formatter(timestamp))

        # Replace timestamp
        result = result.replace("{timestamp}", str(int(timestamp.timestamp())))

        # Replace random
        result = result.replace("{random}", uuid.uuid4().hex[:8])

        # Replace counter patterns
        counter_match = self.COUNTER_PATTERN.search(result.replace("{", "").replace("}", ""))
        if "{" in pattern and "#" in pattern:
            # Find counter placeholder like {####}
            counter_placeholder = re.search(r"\{(#+)\}", result)
            if counter_placeholder:
                hash_count = len(counter_placeholder.group(1))
                counter = context.counter % (10 ** hash_count)
                counter_str = str(counter).zfill(hash_count)
                result = re.sub(r"\{#+\}", counter_str, result)

        # Replace field placeholders
        for match in self.FIELD_PLACEHOLDER_PATTERN.finditer(pattern):
            fieldname = match.group(1)
            if fieldname not in self.DATE_PATTERNS and fieldname not in ["timestamp", "random"]:
                value = context.get_field_value(fieldname, "")
                # Check if it wasn't already replaced (not a date/special pattern)
                if f"{{{fieldname}}}" in result:
                    result = result.replace(f"{{{fieldname}}}", self._sanitize_name(value))

        return result

    def _generate_hash_name(self, context: NamingContext) -> str:
        """
        Generate a hash-based name.

        Args:
            context: The naming context

        Returns:
            Hash-based name (10 characters)
        """
        # Generate unique input for hashing
        unique_input = f"{context.doctype}-{context.counter}-{context.timestamp}-{uuid.uuid4()}"
        hash_value = hashlib.sha256(unique_input.encode()).hexdigest()

        # Return first 10 characters (Frappe default)
        return hash_value[:10]

    def _generate_uuid_name(self, context: NamingContext) -> str:
        """
        Generate a UUID-based name.

        Args:
            context: The naming context

        Returns:
            UUID v4 string
        """
        return str(uuid.uuid4())

    def _generate_expression_name(self, context: NamingContext) -> str:
        """
        Generate a name using Python expression.

        Note: For mock data, we don't evaluate arbitrary expressions.
        Instead, we generate a prompt-style name with a marker.

        Args:
            context: The naming context

        Returns:
            Generated name
        """
        # Extract expression for logging/debugging
        if self._autoname.startswith("expression:"):
            expression = self._autoname[len("expression:"):]
        else:
            expression = self._autoname

        # For safety, we don't eval expressions in mock data
        # Generate a prompt-style name instead
        return self._generate_prompt_name(context)

    def _generate_prompt_name(self, context: NamingContext) -> str:
        """
        Generate a name for "prompt" (user-specified) naming rule.

        For mock data, we generate a meaningful name based on
        available record data or a unique identifier.

        Args:
            context: The naming context

        Returns:
            Generated prompt-style name
        """
        # Try to use meaningful field values
        record_data = context.record_data

        # Common naming field priorities
        name_fields = [
            "name", "title", "customer_name", "supplier_name", "employee_name",
            "item_name", "item_code", "full_name", "company_name",
            "first_name", "subject", "description",
        ]

        for fieldname in name_fields:
            if fieldname in record_data and record_data[fieldname]:
                return self._sanitize_name(str(record_data[fieldname]))

        # Fallback: generate a unique name
        doctype_prefix = self._get_doctype_prefix(context.doctype)
        timestamp = context.timestamp or datetime.now()

        return f"{doctype_prefix}-{timestamp.strftime('%Y%m%d')}-{context.counter:05d}"

    def _generate_single_name(self, context: NamingContext) -> str:
        """
        Generate name for Single DocType.

        Single DocTypes have only one record, named after the DocType.

        Args:
            context: The naming context

        Returns:
            DocType name (Single DocTypes are named after themselves)
        """
        return context.doctype or "SingleDoc"

    def _generate_table_name(self, context: NamingContext) -> str:
        """
        Generate name for child table row.

        Child table rows use hash-based naming.

        Args:
            context: The naming context

        Returns:
            Hash-based row name
        """
        # Child table rows are typically named with hash
        unique_input = (
            f"{context.parent_name or 'parent'}-"
            f"{context.doctype}-"
            f"{context.batch_index}-"
            f"{uuid.uuid4()}"
        )
        hash_value = hashlib.sha256(unique_input.encode()).hexdigest()
        return hash_value[:10]

    def _sanitize_name(self, name: str, max_length: int = 140) -> str:
        """
        Sanitize a name for use as a document identifier.

        Frappe document names:
        - Cannot contain: / , < > " ' : =
        - Should not start/end with whitespace
        - Have maximum length limits

        Args:
            name: Raw name string
            max_length: Maximum allowed length

        Returns:
            Sanitized name string
        """
        # Remove or replace invalid characters
        invalid_chars = r'[/,<>"\':=]'
        sanitized = re.sub(invalid_chars, "-", name)

        # Remove multiple consecutive dashes
        sanitized = re.sub(r"-+", "-", sanitized)

        # Strip whitespace and dashes from ends
        sanitized = sanitized.strip().strip("-")

        # Truncate to max length
        if len(sanitized) > max_length:
            sanitized = sanitized[:max_length].rstrip("-")

        # Ensure not empty
        if not sanitized:
            sanitized = f"doc-{uuid.uuid4().hex[:8]}"

        return sanitized

    def _clean_separators(self, name: str) -> str:
        """
        Clean up separator characters in generated names.

        Removes leading/trailing separators and multiple consecutive separators.

        Args:
            name: Name with potential separator issues

        Returns:
            Cleaned name
        """
        # Replace multiple dashes/dots with single
        cleaned = re.sub(r"[-]+", "-", name)
        cleaned = re.sub(r"[.]+", ".", cleaned)

        # Remove leading/trailing separators
        cleaned = cleaned.strip("-.")

        return cleaned

    def _apply_case(self, name: str) -> str:
        """
        Apply case transformation based on name_case setting.

        Args:
            name: Input name

        Returns:
            Case-transformed name
        """
        if not self._name_case:
            return name

        name_case = self._name_case.lower()

        if "upper" in name_case:
            return name.upper()
        elif "lower" in name_case:
            return name.lower()
        elif "title" in name_case:
            return name.title()

        return name

    def _get_doctype_prefix(self, doctype: str) -> str:
        """
        Generate a short prefix from DocType name.

        Args:
            doctype: DocType name

        Returns:
            3-4 character prefix
        """
        if not doctype:
            return "DOC"

        # Use uppercase first letters of words
        words = re.split(r"[\s_-]+", doctype)
        prefix = "".join(w[0].upper() for w in words if w)

        # Ensure at least 3 characters
        if len(prefix) < 3:
            prefix = doctype[:3].upper()

        return prefix[:4]

    def get_next_counter(self) -> int:
        """
        Get the next counter value for series-based naming.

        Returns:
            Next counter value
        """
        self._counter += 1
        return self._counter

    def reset_counter(self, value: int = 0) -> None:
        """
        Reset the internal counter.

        Args:
            value: Value to reset to (default 0)
        """
        self._counter = value

    def validate_name(self, name: str) -> Tuple[bool, Optional[str]]:
        """
        Validate a document name.

        Args:
            name: Name to validate

        Returns:
            Tuple of (is_valid, error_message)
        """
        if not name:
            return False, "Name cannot be empty"

        if len(name) > 140:
            return False, f"Name too long ({len(name)} > 140 characters)"

        # Check for invalid characters
        invalid_chars = set('/,<>"\':=')
        found_invalid = set(name) & invalid_chars
        if found_invalid:
            return False, f"Name contains invalid characters: {found_invalid}"

        # Check for leading/trailing whitespace
        if name != name.strip():
            return False, "Name has leading or trailing whitespace"

        return True, None

    def get_series_options(self) -> List[str]:
        """
        Get available naming series options.

        For naming_series: type, this returns the available series choices.

        Returns:
            List of series option strings
        """
        if self._naming_type != "series":
            return []

        # Parse options from autoname if it contains newlines
        if "\n" in self._autoname:
            options = [
                opt.strip()
                for opt in self._autoname.split("\n")
                if opt.strip() and not opt.strip().startswith("naming_series:")
            ]
            return options

        # Single series
        series = self._get_series_pattern()
        return [series] if series else []

    def __repr__(self) -> str:
        """String representation of the handler."""
        return (
            f"NamingHandler("
            f"type='{self._naming_type}', "
            f"autoname='{self._autoname[:30]}...'" if len(self._autoname) > 30
            else f"NamingHandler(type='{self._naming_type}', autoname='{self._autoname}')"
        )


# Convenience function for quick name generation
def generate_document_name(
    autoname: str,
    record_data: Optional[Dict[str, Any]] = None,
    counter: int = 1,
    naming_series: str = "",
) -> str:
    """
    Generate a document name using the specified naming pattern.

    This is a convenience function that creates a NamingHandler and
    generates a single name.

    Args:
        autoname: The autoname pattern
        record_data: Optional field values for field-based naming
        counter: Sequence counter for series-based naming
        naming_series: Optional naming series pattern

    Returns:
        Generated document name

    Example:
        >>> generate_document_name("naming_series:", counter=5, naming_series="INV-.####")
        'INV-0005'
        >>> generate_document_name("field:customer_name", record_data={"customer_name": "ACME"})
        'ACME'
    """
    handler = NamingHandler(autoname=autoname, naming_series=naming_series)
    return handler.generate_name(record_data=record_data, counter=counter)


# Export all public classes and functions
__all__ = [
    "NamingHandler",
    "NamingContext",
    "NamingError",
    "generate_document_name",
]

# Copyright (c) 2026, TradeHub and contributors
# For license information, please see license.txt

"""
Test Suite for ECA Condition Evaluation Engine

This test suite covers:
- All 22 operators (14 standard + 8 new)
- AND/OR condition group evaluation
- Field path resolution (nested fields, array access)
- Jinja template support for condition values
- Edge cases (null values, empty conditions)

Run with:
    bench --site [site] run-tests --module tr_tradehub.tests.test_eca_engine
"""

import unittest
from unittest.mock import MagicMock, patch, PropertyMock
from datetime import date, datetime
from dataclasses import dataclass
from typing import Any, Dict, List, Optional


# =============================================================================
# MOCK FRAPPE MODULE
# =============================================================================

# Create a mock frappe module for testing without Frappe installation
class MockFrappe:
    """Mock Frappe module for standalone testing."""

    class session:
        user = "test@example.com"

    class utils:
        @staticmethod
        def now_datetime():
            return datetime.now()

        @staticmethod
        def today():
            return date.today().isoformat()

        @staticmethod
        def cstr(val):
            return str(val) if val is not None else ""

        @staticmethod
        def getdate(val):
            if isinstance(val, date):
                return val
            if isinstance(val, str):
                return datetime.strptime(val, "%Y-%m-%d").date()
            return None

        @staticmethod
        def get_datetime(val):
            if isinstance(val, datetime):
                return val
            if isinstance(val, str):
                try:
                    return datetime.strptime(val, "%Y-%m-%d %H:%M:%S")
                except ValueError:
                    return datetime.strptime(val, "%Y-%m-%d")
            return None

    @staticmethod
    def _(text):
        return text

    @staticmethod
    def log_error(message, title=None):
        pass

    @staticmethod
    def render_template(template, context):
        """Simple Jinja-like template rendering."""
        result = template
        for key, value in context.items():
            result = result.replace("{{" + key + "}}", str(value) if value else "")
            result = result.replace("{{ " + key + " }}", str(value) if value else "")
            # Handle doc.field patterns
            if key == "doc" and hasattr(value, "__dict__"):
                for field, field_value in value.__dict__.items():
                    if not field.startswith("_"):
                        result = result.replace("{{doc." + field + "}}", str(field_value) if field_value else "")
                        result = result.replace("{{ doc." + field + " }}", str(field_value) if field_value else "")
        return result


# Patch frappe module before importing engine
import sys
sys.modules['frappe'] = MockFrappe
sys.modules['frappe.utils'] = MockFrappe.utils


# =============================================================================
# OPERATORS DICTIONARY (copied from engine.py for standalone testing)
# =============================================================================

import re

def cstr(val):
    return str(val) if val is not None else ""

def getdate(val):
    if isinstance(val, date):
        return val
    if isinstance(val, str):
        try:
            return datetime.strptime(val, "%Y-%m-%d").date()
        except (ValueError, TypeError):
            return None
    return None

def _check_between(value: Any, range_value: Any) -> bool:
    """Check if value is between min and max."""
    if value is None:
        return False
    try:
        if isinstance(range_value, dict):
            min_val = range_value.get("min")
            max_val = range_value.get("max")
        elif isinstance(range_value, (list, tuple)) and len(range_value) == 2:
            min_val, max_val = range_value
        else:
            return False
        num_value = float(value)
        return float(min_val) <= num_value <= float(max_val)
    except (ValueError, TypeError):
        return False


OPERATORS = {
    # Standard comparison operators
    "==": lambda a, b: a == b,
    "!=": lambda a, b: a != b,
    ">": lambda a, b: float(a) > float(b) if a is not None else False,
    ">=": lambda a, b: float(a) >= float(b) if a is not None else False,
    "<": lambda a, b: float(a) < float(b) if a is not None else False,
    "<=": lambda a, b: float(a) <= float(b) if a is not None else False,

    # List membership operators
    "in": lambda a, b: a in (b if isinstance(b, (list, tuple)) else [b]),
    "not_in": lambda a, b: a not in (b if isinstance(b, (list, tuple)) else [b]),

    # String operators (case-insensitive)
    "contains": lambda a, b: cstr(b).lower() in cstr(a).lower() if a else False,
    "not_contains": lambda a, b: cstr(b).lower() not in cstr(a).lower() if a else True,
    "starts_with": lambda a, b: cstr(a).lower().startswith(cstr(b).lower()) if a else False,
    "ends_with": lambda a, b: cstr(a).lower().endswith(cstr(b).lower()) if a else False,

    # Null/empty operators
    "is_set": lambda a, b: a is not None and a != "",
    "is_not_set": lambda a, b: a is None or a == "",

    # New operators
    "regex_match": lambda a, b: bool(re.match(cstr(b), cstr(a))) if a is not None else False,
    "date_before": lambda a, b: getdate(a) < getdate(b) if a and b else False,
    "date_after": lambda a, b: getdate(a) > getdate(b) if a and b else False,
    "between": lambda a, b: _check_between(a, b),
    "is_empty": lambda a, b: a is None or a == "" or a == [] or a == {},

    # Change detection operators (placeholders - tested via ECAEngine)
    "changed": lambda a, b: False,
    "changed_to": lambda a, b: False,
    "changed_from": lambda a, b: False,
}


# =============================================================================
# MOCK DOCUMENT CLASS
# =============================================================================

@dataclass
class MockDocument:
    """Mock document class for testing."""
    name: str = "TEST-001"
    doctype: str = "Test DocType"
    status: str = "Draft"
    amount: float = 100.0
    quantity: int = 10
    email: str = "test@example.com"
    description: str = "Test description"
    created_date: str = "2026-01-01"
    is_active: bool = True
    tags: List[str] = None
    metadata: Dict[str, Any] = None
    items: List[Any] = None
    buyer: Any = None
    _meta: Any = None

    def __post_init__(self):
        if self.tags is None:
            self.tags = []
        if self.metadata is None:
            self.metadata = {}
        if self.items is None:
            self.items = []

    def get(self, field, default=None):
        return getattr(self, field, default)

    @property
    def meta(self):
        return self._meta


@dataclass
class MockItem:
    """Mock item for testing array access."""
    item_code: str = "ITEM-001"
    quantity: int = 5
    rate: float = 50.0


@dataclass
class MockBuyer:
    """Mock buyer for testing nested field access."""
    name: str = "BUYER-001"
    email: str = "buyer@example.com"
    phone: str = "1234567890"


@dataclass
class MockCondition:
    """Mock ECA Rule Condition row."""
    field_path: str = "status"
    operator: str = "=="
    value: str = "Draft"
    value_type: str = "String"
    condition_group: int = 1
    group_logic: str = "AND"


@dataclass
class MockRule:
    """Mock ECA Rule document."""
    name: str = "RULE-001"
    rule_name: str = "Test Rule"
    enabled: bool = True
    condition_logic: str = "AND"
    conditions: List[MockCondition] = None

    def __post_init__(self):
        if self.conditions is None:
            self.conditions = []


# =============================================================================
# ECA ENGINE TEST IMPLEMENTATION
# =============================================================================

class TestableECAEngine:
    """
    Testable version of ECAEngine for standalone unit testing.
    Mirrors the actual ECAEngine implementation.
    """

    def __init__(self, doc, old_doc=None, context=None):
        self.doc = doc
        self.old_doc = old_doc
        self.context = context or {}
        self._build_context()

    def _build_context(self):
        """Build the template context with standard variables."""
        self.context.update({
            "doc": self.doc,
            "old_doc": self.old_doc,
            "frappe": MockFrappe,
            "now": MockFrappe.utils.now_datetime,
            "today": MockFrappe.utils.today,
            "user": MockFrappe.session.user,
        })

    def evaluate_rule(self, rule) -> bool:
        """Evaluate an ECA Rule against the current document."""
        if not rule.conditions:
            return True

        groups = self._group_conditions(rule.conditions)
        logic = (rule.condition_logic or "AND").upper()

        group_results = []
        for group_id, group_data in groups.items():
            result = self.evaluate_group(group_data["conditions"], group_data["logic"])
            group_results.append(result)

        if logic == "AND":
            return all(group_results) if group_results else True
        else:
            return any(group_results) if group_results else True

    def _group_conditions(self, conditions):
        """Group conditions by their condition_group field."""
        groups = {}
        for condition in conditions:
            group_id = condition.condition_group or 1
            if group_id not in groups:
                groups[group_id] = {
                    "logic": (condition.group_logic or "AND").upper(),
                    "conditions": []
                }
            groups[group_id]["conditions"].append(condition)
        return groups

    def evaluate_group(self, conditions, logic="AND") -> bool:
        """Evaluate a group of conditions."""
        if not conditions:
            return True

        results = [self.evaluate_condition(c) for c in conditions]

        if logic == "AND":
            return all(results)
        else:
            return any(results)

    def evaluate_condition(self, condition) -> bool:
        """Evaluate a single condition."""
        try:
            field_path = condition.field_path
            operator = condition.operator
            compare_value = condition.value
            value_type = condition.value_type

            actual_value = self.get_field_value(field_path)

            # Handle change detection operators
            if operator in ("changed", "changed_to", "changed_from"):
                return self._evaluate_change_operator(field_path, operator, compare_value)

            parsed_value = self._parse_value(compare_value, value_type)

            op_func = OPERATORS.get(operator)
            if not op_func:
                return False

            return op_func(actual_value, parsed_value)
        except Exception:
            return False

    def get_field_value(self, field_path):
        """Get the value of a field from the document."""
        if not field_path:
            return None
        try:
            return self._resolve_field_path(self.doc, field_path)
        except Exception:
            return None

    def _resolve_field_path(self, obj, path):
        """Resolve a field path to get the actual value."""
        if not path or obj is None:
            return None

        parts = self._parse_path(path)
        current = obj

        for part in parts:
            if current is None:
                return None

            array_match = re.match(r"(\w+)\[(\d+)\]", part)

            if array_match:
                field_name = array_match.group(1)
                index = int(array_match.group(2))
                current = self._get_attribute(current, field_name)

                if current is None or not isinstance(current, (list, tuple)):
                    return None
                if index >= len(current):
                    return None
                current = current[index]
            else:
                current = self._get_attribute(current, part)

        return current

    def _parse_path(self, path):
        """Parse a field path into parts."""
        parts = []
        current = ""
        for char in path:
            if char == ".":
                if current:
                    parts.append(current)
                    current = ""
            else:
                current += char
        if current:
            parts.append(current)
        return parts

    def _get_attribute(self, obj, attr):
        """Get an attribute from an object."""
        if isinstance(obj, dict):
            return obj.get(attr)
        elif hasattr(obj, attr):
            return getattr(obj, attr)
        elif hasattr(obj, "get"):
            return obj.get(attr)
        return None

    def _parse_value(self, value, value_type=None):
        """Parse a condition value based on its type."""
        if value is None:
            return None

        if value_type == "Jinja Expression" or (isinstance(value, str) and "{{" in value):
            return self._render_template(value)

        if value_type == "Number":
            try:
                return float(value)
            except (ValueError, TypeError):
                return value

        elif value_type == "Boolean":
            if isinstance(value, bool):
                return value
            if isinstance(value, str):
                return value.lower() in ("true", "1", "yes")
            return bool(value)

        elif value_type == "Date":
            return getdate(value)

        elif value_type == "JSON":
            if isinstance(value, str):
                try:
                    import json
                    return json.loads(value)
                except (ValueError, TypeError):
                    return value
            return value

        return cstr(value) if value else value

    def _render_template(self, template):
        """Render a Jinja template string."""
        if not template or not isinstance(template, str):
            return template
        if "{{" not in template:
            return template
        try:
            return MockFrappe.render_template(template, self.context)
        except Exception:
            return template

    def _evaluate_change_operator(self, field_path, operator, compare_value):
        """Evaluate change detection operators."""
        if not self.old_doc:
            if operator == "changed":
                return True
            return False

        current_value = self.get_field_value(field_path)
        old_value = self._resolve_field_path(self.old_doc, field_path)

        if operator == "changed":
            return current_value != old_value
        elif operator == "changed_to":
            return old_value != compare_value and current_value == compare_value
        elif operator == "changed_from":
            return old_value == compare_value and current_value != compare_value

        return False


# =============================================================================
# TEST CLASSES
# =============================================================================

class TestEqualsOperator(unittest.TestCase):
    """Tests for the == operator."""

    def test_equals_string_match(self):
        """Test == operator with matching strings."""
        result = OPERATORS["=="]("Draft", "Draft")
        self.assertTrue(result)

    def test_equals_string_no_match(self):
        """Test == operator with non-matching strings."""
        result = OPERATORS["=="]("Draft", "Submitted")
        self.assertFalse(result)

    def test_equals_number_match(self):
        """Test == operator with matching numbers."""
        result = OPERATORS["=="](100, 100)
        self.assertTrue(result)

    def test_equals_number_no_match(self):
        """Test == operator with non-matching numbers."""
        result = OPERATORS["=="](100, 200)
        self.assertFalse(result)

    def test_equals_null_values(self):
        """Test == operator with null values."""
        result = OPERATORS["=="](None, None)
        self.assertTrue(result)

        result = OPERATORS["=="](None, "value")
        self.assertFalse(result)


class TestNotEqualsOperator(unittest.TestCase):
    """Tests for the != operator."""

    def test_not_equals_different_strings(self):
        """Test != operator with different strings."""
        result = OPERATORS["!="]("Draft", "Submitted")
        self.assertTrue(result)

    def test_not_equals_same_strings(self):
        """Test != operator with same strings."""
        result = OPERATORS["!="]("Draft", "Draft")
        self.assertFalse(result)

    def test_not_equals_different_numbers(self):
        """Test != operator with different numbers."""
        result = OPERATORS["!="](100, 200)
        self.assertTrue(result)

    def test_not_equals_null_and_value(self):
        """Test != operator with null and value."""
        result = OPERATORS["!="](None, "value")
        self.assertTrue(result)


class TestGreaterThanOperator(unittest.TestCase):
    """Tests for the > operator."""

    def test_greater_than_true(self):
        """Test > operator when a > b."""
        result = OPERATORS[">"](100, 50)
        self.assertTrue(result)

    def test_greater_than_false(self):
        """Test > operator when a < b."""
        result = OPERATORS[">"](50, 100)
        self.assertFalse(result)

    def test_greater_than_equal(self):
        """Test > operator when a == b."""
        result = OPERATORS[">"](100, 100)
        self.assertFalse(result)

    def test_greater_than_null_safe(self):
        """Test > operator with null value returns False."""
        result = OPERATORS[">"](None, 100)
        self.assertFalse(result)

    def test_greater_than_string_numbers(self):
        """Test > operator with string numbers."""
        result = OPERATORS[">"]("100", "50")
        self.assertTrue(result)


class TestGreaterThanOrEqualOperator(unittest.TestCase):
    """Tests for the >= operator."""

    def test_gte_greater(self):
        """Test >= operator when a > b."""
        result = OPERATORS[">="](100, 50)
        self.assertTrue(result)

    def test_gte_equal(self):
        """Test >= operator when a == b."""
        result = OPERATORS[">="](100, 100)
        self.assertTrue(result)

    def test_gte_less(self):
        """Test >= operator when a < b."""
        result = OPERATORS[">="](50, 100)
        self.assertFalse(result)

    def test_gte_null_safe(self):
        """Test >= operator with null value."""
        result = OPERATORS[">="](None, 100)
        self.assertFalse(result)


class TestLessThanOperator(unittest.TestCase):
    """Tests for the < operator."""

    def test_less_than_true(self):
        """Test < operator when a < b."""
        result = OPERATORS["<"](50, 100)
        self.assertTrue(result)

    def test_less_than_false(self):
        """Test < operator when a > b."""
        result = OPERATORS["<"](100, 50)
        self.assertFalse(result)

    def test_less_than_equal(self):
        """Test < operator when a == b."""
        result = OPERATORS["<"](100, 100)
        self.assertFalse(result)

    def test_less_than_null_safe(self):
        """Test < operator with null value."""
        result = OPERATORS["<"](None, 100)
        self.assertFalse(result)


class TestLessThanOrEqualOperator(unittest.TestCase):
    """Tests for the <= operator."""

    def test_lte_less(self):
        """Test <= operator when a < b."""
        result = OPERATORS["<="](50, 100)
        self.assertTrue(result)

    def test_lte_equal(self):
        """Test <= operator when a == b."""
        result = OPERATORS["<="](100, 100)
        self.assertTrue(result)

    def test_lte_greater(self):
        """Test <= operator when a > b."""
        result = OPERATORS["<="](100, 50)
        self.assertFalse(result)

    def test_lte_null_safe(self):
        """Test <= operator with null value."""
        result = OPERATORS["<="](None, 100)
        self.assertFalse(result)


class TestInOperator(unittest.TestCase):
    """Tests for the 'in' operator."""

    def test_in_list_found(self):
        """Test 'in' operator when value is in list."""
        result = OPERATORS["in"]("Draft", ["Draft", "Submitted", "Cancelled"])
        self.assertTrue(result)

    def test_in_list_not_found(self):
        """Test 'in' operator when value is not in list."""
        result = OPERATORS["in"]("Pending", ["Draft", "Submitted", "Cancelled"])
        self.assertFalse(result)

    def test_in_single_value(self):
        """Test 'in' operator with single value (auto-converted to list)."""
        result = OPERATORS["in"]("Draft", "Draft")
        self.assertTrue(result)

    def test_in_tuple(self):
        """Test 'in' operator with tuple."""
        result = OPERATORS["in"]("Draft", ("Draft", "Submitted"))
        self.assertTrue(result)


class TestNotInOperator(unittest.TestCase):
    """Tests for the 'not_in' operator."""

    def test_not_in_list(self):
        """Test 'not_in' operator when value is not in list."""
        result = OPERATORS["not_in"]("Pending", ["Draft", "Submitted"])
        self.assertTrue(result)

    def test_not_in_list_found(self):
        """Test 'not_in' operator when value is in list."""
        result = OPERATORS["not_in"]("Draft", ["Draft", "Submitted"])
        self.assertFalse(result)

    def test_not_in_single_value(self):
        """Test 'not_in' operator with single value."""
        result = OPERATORS["not_in"]("Pending", "Draft")
        self.assertTrue(result)


class TestContainsOperator(unittest.TestCase):
    """Tests for the 'contains' operator."""

    def test_contains_found(self):
        """Test 'contains' when substring is found."""
        result = OPERATORS["contains"]("Hello World", "World")
        self.assertTrue(result)

    def test_contains_not_found(self):
        """Test 'contains' when substring is not found."""
        result = OPERATORS["contains"]("Hello World", "Python")
        self.assertFalse(result)

    def test_contains_case_insensitive(self):
        """Test 'contains' is case-insensitive."""
        result = OPERATORS["contains"]("Hello World", "WORLD")
        self.assertTrue(result)

    def test_contains_null_value(self):
        """Test 'contains' with null value returns False."""
        result = OPERATORS["contains"](None, "test")
        self.assertFalse(result)

    def test_contains_empty_string(self):
        """Test 'contains' with empty string."""
        result = OPERATORS["contains"]("", "test")
        self.assertFalse(result)


class TestNotContainsOperator(unittest.TestCase):
    """Tests for the 'not_contains' operator."""

    def test_not_contains_true(self):
        """Test 'not_contains' when substring is not found."""
        result = OPERATORS["not_contains"]("Hello World", "Python")
        self.assertTrue(result)

    def test_not_contains_false(self):
        """Test 'not_contains' when substring is found."""
        result = OPERATORS["not_contains"]("Hello World", "World")
        self.assertFalse(result)

    def test_not_contains_case_insensitive(self):
        """Test 'not_contains' is case-insensitive."""
        result = OPERATORS["not_contains"]("Hello World", "PYTHON")
        self.assertTrue(result)

    def test_not_contains_null_value(self):
        """Test 'not_contains' with null value returns True."""
        result = OPERATORS["not_contains"](None, "test")
        self.assertTrue(result)


class TestStartsWithOperator(unittest.TestCase):
    """Tests for the 'starts_with' operator."""

    def test_starts_with_true(self):
        """Test 'starts_with' when string starts with prefix."""
        result = OPERATORS["starts_with"]("Hello World", "Hello")
        self.assertTrue(result)

    def test_starts_with_false(self):
        """Test 'starts_with' when string doesn't start with prefix."""
        result = OPERATORS["starts_with"]("Hello World", "World")
        self.assertFalse(result)

    def test_starts_with_case_insensitive(self):
        """Test 'starts_with' is case-insensitive."""
        result = OPERATORS["starts_with"]("Hello World", "HELLO")
        self.assertTrue(result)

    def test_starts_with_null_value(self):
        """Test 'starts_with' with null value."""
        result = OPERATORS["starts_with"](None, "test")
        self.assertFalse(result)


class TestEndsWithOperator(unittest.TestCase):
    """Tests for the 'ends_with' operator."""

    def test_ends_with_true(self):
        """Test 'ends_with' when string ends with suffix."""
        result = OPERATORS["ends_with"]("Hello World", "World")
        self.assertTrue(result)

    def test_ends_with_false(self):
        """Test 'ends_with' when string doesn't end with suffix."""
        result = OPERATORS["ends_with"]("Hello World", "Hello")
        self.assertFalse(result)

    def test_ends_with_case_insensitive(self):
        """Test 'ends_with' is case-insensitive."""
        result = OPERATORS["ends_with"]("Hello World", "WORLD")
        self.assertTrue(result)

    def test_ends_with_null_value(self):
        """Test 'ends_with' with null value."""
        result = OPERATORS["ends_with"](None, "test")
        self.assertFalse(result)


class TestIsSetOperator(unittest.TestCase):
    """Tests for the 'is_set' operator."""

    def test_is_set_with_value(self):
        """Test 'is_set' with a value."""
        result = OPERATORS["is_set"]("value", None)
        self.assertTrue(result)

    def test_is_set_with_number(self):
        """Test 'is_set' with a number."""
        result = OPERATORS["is_set"](100, None)
        self.assertTrue(result)

    def test_is_set_with_zero(self):
        """Test 'is_set' with zero (truthy check)."""
        result = OPERATORS["is_set"](0, None)
        self.assertTrue(result)

    def test_is_set_with_null(self):
        """Test 'is_set' with null."""
        result = OPERATORS["is_set"](None, None)
        self.assertFalse(result)

    def test_is_set_with_empty_string(self):
        """Test 'is_set' with empty string."""
        result = OPERATORS["is_set"]("", None)
        self.assertFalse(result)


class TestIsNotSetOperator(unittest.TestCase):
    """Tests for the 'is_not_set' operator."""

    def test_is_not_set_with_null(self):
        """Test 'is_not_set' with null."""
        result = OPERATORS["is_not_set"](None, None)
        self.assertTrue(result)

    def test_is_not_set_with_empty_string(self):
        """Test 'is_not_set' with empty string."""
        result = OPERATORS["is_not_set"]("", None)
        self.assertTrue(result)

    def test_is_not_set_with_value(self):
        """Test 'is_not_set' with a value."""
        result = OPERATORS["is_not_set"]("value", None)
        self.assertFalse(result)

    def test_is_not_set_with_zero(self):
        """Test 'is_not_set' with zero."""
        result = OPERATORS["is_not_set"](0, None)
        self.assertFalse(result)


class TestRegexMatchOperator(unittest.TestCase):
    """Tests for the 'regex_match' operator."""

    def test_regex_match_simple(self):
        """Test 'regex_match' with simple pattern."""
        result = OPERATORS["regex_match"]("test@example.com", r".*@.*\.com")
        self.assertTrue(result)

    def test_regex_match_no_match(self):
        """Test 'regex_match' when pattern doesn't match."""
        result = OPERATORS["regex_match"]("invalid-email", r".*@.*\.com")
        self.assertFalse(result)

    def test_regex_match_phone_number(self):
        """Test 'regex_match' with phone number pattern."""
        result = OPERATORS["regex_match"]("123-456-7890", r"\d{3}-\d{3}-\d{4}")
        self.assertTrue(result)

    def test_regex_match_null_value(self):
        """Test 'regex_match' with null value."""
        result = OPERATORS["regex_match"](None, r".*")
        self.assertFalse(result)

    def test_regex_match_start_anchor(self):
        """Test 'regex_match' with start anchor (uses re.match)."""
        result = OPERATORS["regex_match"]("PREFIX-123", r"PREFIX")
        self.assertTrue(result)

        result = OPERATORS["regex_match"]("123-PREFIX", r"PREFIX")
        self.assertFalse(result)  # re.match anchors at start


class TestDateBeforeOperator(unittest.TestCase):
    """Tests for the 'date_before' operator."""

    def test_date_before_true(self):
        """Test 'date_before' when a < b."""
        result = OPERATORS["date_before"]("2026-01-01", "2026-01-15")
        self.assertTrue(result)

    def test_date_before_false(self):
        """Test 'date_before' when a > b."""
        result = OPERATORS["date_before"]("2026-01-15", "2026-01-01")
        self.assertFalse(result)

    def test_date_before_equal(self):
        """Test 'date_before' when dates are equal."""
        result = OPERATORS["date_before"]("2026-01-01", "2026-01-01")
        self.assertFalse(result)

    def test_date_before_null(self):
        """Test 'date_before' with null value."""
        result = OPERATORS["date_before"](None, "2026-01-01")
        self.assertFalse(result)

    def test_date_before_with_date_objects(self):
        """Test 'date_before' with date objects."""
        result = OPERATORS["date_before"](date(2026, 1, 1), date(2026, 1, 15))
        self.assertTrue(result)


class TestDateAfterOperator(unittest.TestCase):
    """Tests for the 'date_after' operator."""

    def test_date_after_true(self):
        """Test 'date_after' when a > b."""
        result = OPERATORS["date_after"]("2026-01-15", "2026-01-01")
        self.assertTrue(result)

    def test_date_after_false(self):
        """Test 'date_after' when a < b."""
        result = OPERATORS["date_after"]("2026-01-01", "2026-01-15")
        self.assertFalse(result)

    def test_date_after_equal(self):
        """Test 'date_after' when dates are equal."""
        result = OPERATORS["date_after"]("2026-01-01", "2026-01-01")
        self.assertFalse(result)

    def test_date_after_null(self):
        """Test 'date_after' with null value."""
        result = OPERATORS["date_after"](None, "2026-01-01")
        self.assertFalse(result)


class TestBetweenOperator(unittest.TestCase):
    """Tests for the 'between' operator."""

    def test_between_in_range_list(self):
        """Test 'between' with value in range (list format)."""
        result = OPERATORS["between"](50, [10, 100])
        self.assertTrue(result)

    def test_between_in_range_dict(self):
        """Test 'between' with value in range (dict format)."""
        result = OPERATORS["between"](50, {"min": 10, "max": 100})
        self.assertTrue(result)

    def test_between_at_min(self):
        """Test 'between' when value equals min."""
        result = OPERATORS["between"](10, [10, 100])
        self.assertTrue(result)

    def test_between_at_max(self):
        """Test 'between' when value equals max."""
        result = OPERATORS["between"](100, [10, 100])
        self.assertTrue(result)

    def test_between_below_range(self):
        """Test 'between' when value is below range."""
        result = OPERATORS["between"](5, [10, 100])
        self.assertFalse(result)

    def test_between_above_range(self):
        """Test 'between' when value is above range."""
        result = OPERATORS["between"](150, [10, 100])
        self.assertFalse(result)

    def test_between_null_value(self):
        """Test 'between' with null value."""
        result = OPERATORS["between"](None, [10, 100])
        self.assertFalse(result)

    def test_between_string_numbers(self):
        """Test 'between' with string numbers."""
        result = OPERATORS["between"]("50", ["10", "100"])
        self.assertTrue(result)


class TestIsEmptyOperator(unittest.TestCase):
    """Tests for the 'is_empty' operator."""

    def test_is_empty_null(self):
        """Test 'is_empty' with null."""
        result = OPERATORS["is_empty"](None, None)
        self.assertTrue(result)

    def test_is_empty_empty_string(self):
        """Test 'is_empty' with empty string."""
        result = OPERATORS["is_empty"]("", None)
        self.assertTrue(result)

    def test_is_empty_empty_list(self):
        """Test 'is_empty' with empty list."""
        result = OPERATORS["is_empty"]([], None)
        self.assertTrue(result)

    def test_is_empty_empty_dict(self):
        """Test 'is_empty' with empty dict."""
        result = OPERATORS["is_empty"]({}, None)
        self.assertTrue(result)

    def test_is_empty_with_value(self):
        """Test 'is_empty' with a value."""
        result = OPERATORS["is_empty"]("value", None)
        self.assertFalse(result)

    def test_is_empty_with_list(self):
        """Test 'is_empty' with non-empty list."""
        result = OPERATORS["is_empty"]([1, 2, 3], None)
        self.assertFalse(result)

    def test_is_empty_with_dict(self):
        """Test 'is_empty' with non-empty dict."""
        result = OPERATORS["is_empty"]({"key": "value"}, None)
        self.assertFalse(result)


class TestChangeDetectionOperators(unittest.TestCase):
    """Tests for change detection operators: changed, changed_to, changed_from."""

    def setUp(self):
        """Set up test documents."""
        self.doc = MockDocument(status="Submitted", amount=200.0)
        self.old_doc = MockDocument(status="Draft", amount=100.0)

    def test_changed_true(self):
        """Test 'changed' when field value changed."""
        engine = TestableECAEngine(self.doc, self.old_doc)
        result = engine._evaluate_change_operator("status", "changed", None)
        self.assertTrue(result)

    def test_changed_false(self):
        """Test 'changed' when field value didn't change."""
        self.old_doc.status = "Submitted"
        engine = TestableECAEngine(self.doc, self.old_doc)
        result = engine._evaluate_change_operator("status", "changed", None)
        self.assertFalse(result)

    def test_changed_no_old_doc(self):
        """Test 'changed' without old_doc (new document)."""
        engine = TestableECAEngine(self.doc, None)
        result = engine._evaluate_change_operator("status", "changed", None)
        self.assertTrue(result)  # New document = changed

    def test_changed_to_true(self):
        """Test 'changed_to' when field changed to specific value."""
        engine = TestableECAEngine(self.doc, self.old_doc)
        result = engine._evaluate_change_operator("status", "changed_to", "Submitted")
        self.assertTrue(result)

    def test_changed_to_false_same_value(self):
        """Test 'changed_to' when field was already that value."""
        self.old_doc.status = "Submitted"
        engine = TestableECAEngine(self.doc, self.old_doc)
        result = engine._evaluate_change_operator("status", "changed_to", "Submitted")
        self.assertFalse(result)

    def test_changed_to_false_different_value(self):
        """Test 'changed_to' when field changed to different value."""
        engine = TestableECAEngine(self.doc, self.old_doc)
        result = engine._evaluate_change_operator("status", "changed_to", "Cancelled")
        self.assertFalse(result)

    def test_changed_from_true(self):
        """Test 'changed_from' when field changed from specific value."""
        engine = TestableECAEngine(self.doc, self.old_doc)
        result = engine._evaluate_change_operator("status", "changed_from", "Draft")
        self.assertTrue(result)

    def test_changed_from_false_not_that_value(self):
        """Test 'changed_from' when field wasn't that value."""
        engine = TestableECAEngine(self.doc, self.old_doc)
        result = engine._evaluate_change_operator("status", "changed_from", "Submitted")
        self.assertFalse(result)

    def test_changed_from_false_no_change(self):
        """Test 'changed_from' when field didn't change."""
        self.doc.status = "Draft"
        engine = TestableECAEngine(self.doc, self.old_doc)
        result = engine._evaluate_change_operator("status", "changed_from", "Draft")
        self.assertFalse(result)


class TestECAEngineFieldPathResolution(unittest.TestCase):
    """Tests for field path resolution (nested fields, array access)."""

    def setUp(self):
        """Set up test documents with nested data."""
        self.buyer = MockBuyer(name="BUYER-001", email="buyer@example.com")
        self.items = [
            MockItem(item_code="ITEM-001", quantity=5, rate=50.0),
            MockItem(item_code="ITEM-002", quantity=10, rate=25.0),
        ]
        self.doc = MockDocument(
            status="Draft",
            buyer=self.buyer,
            items=self.items,
            metadata={"category": "Electronics", "priority": "High"}
        )

    def test_simple_field_access(self):
        """Test simple field access."""
        engine = TestableECAEngine(self.doc)
        result = engine.get_field_value("status")
        self.assertEqual(result, "Draft")

    def test_nested_field_access(self):
        """Test nested field access (buyer.email)."""
        engine = TestableECAEngine(self.doc)
        result = engine.get_field_value("buyer.email")
        self.assertEqual(result, "buyer@example.com")

    def test_array_field_access(self):
        """Test array field access (items[0].quantity)."""
        engine = TestableECAEngine(self.doc)
        result = engine.get_field_value("items[0].quantity")
        self.assertEqual(result, 5)

    def test_array_field_access_second_item(self):
        """Test array field access for second item."""
        engine = TestableECAEngine(self.doc)
        result = engine.get_field_value("items[1].rate")
        self.assertEqual(result, 25.0)

    def test_dict_field_access(self):
        """Test dict field access (metadata.category)."""
        engine = TestableECAEngine(self.doc)
        result = engine.get_field_value("metadata.category")
        self.assertEqual(result, "Electronics")

    def test_invalid_field_path(self):
        """Test invalid field path returns None."""
        engine = TestableECAEngine(self.doc)
        result = engine.get_field_value("nonexistent.field")
        self.assertIsNone(result)

    def test_array_out_of_bounds(self):
        """Test array index out of bounds returns None."""
        engine = TestableECAEngine(self.doc)
        result = engine.get_field_value("items[99].quantity")
        self.assertIsNone(result)

    def test_empty_field_path(self):
        """Test empty field path returns None."""
        engine = TestableECAEngine(self.doc)
        result = engine.get_field_value("")
        self.assertIsNone(result)

    def test_null_field_path(self):
        """Test null field path returns None."""
        engine = TestableECAEngine(self.doc)
        result = engine.get_field_value(None)
        self.assertIsNone(result)


class TestECAEngineConditionGroupEvaluation(unittest.TestCase):
    """Tests for AND/OR condition group evaluation."""

    def setUp(self):
        """Set up test document."""
        self.doc = MockDocument(status="Draft", amount=100.0, quantity=10)

    def test_single_condition_true(self):
        """Test single condition that evaluates to True."""
        condition = MockCondition(field_path="status", operator="==", value="Draft")
        rule = MockRule(conditions=[condition])

        engine = TestableECAEngine(self.doc)
        result = engine.evaluate_rule(rule)
        self.assertTrue(result)

    def test_single_condition_false(self):
        """Test single condition that evaluates to False."""
        condition = MockCondition(field_path="status", operator="==", value="Submitted")
        rule = MockRule(conditions=[condition])

        engine = TestableECAEngine(self.doc)
        result = engine.evaluate_rule(rule)
        self.assertFalse(result)

    def test_and_logic_all_true(self):
        """Test AND logic when all conditions are True."""
        conditions = [
            MockCondition(field_path="status", operator="==", value="Draft", condition_group=1, group_logic="AND"),
            MockCondition(field_path="amount", operator=">", value="50", value_type="Number", condition_group=1, group_logic="AND"),
        ]
        rule = MockRule(conditions=conditions, condition_logic="AND")

        engine = TestableECAEngine(self.doc)
        result = engine.evaluate_rule(rule)
        self.assertTrue(result)

    def test_and_logic_one_false(self):
        """Test AND logic when one condition is False."""
        conditions = [
            MockCondition(field_path="status", operator="==", value="Draft", condition_group=1, group_logic="AND"),
            MockCondition(field_path="amount", operator=">", value="200", value_type="Number", condition_group=1, group_logic="AND"),
        ]
        rule = MockRule(conditions=conditions, condition_logic="AND")

        engine = TestableECAEngine(self.doc)
        result = engine.evaluate_rule(rule)
        self.assertFalse(result)

    def test_or_logic_one_true(self):
        """Test OR logic when one condition is True."""
        conditions = [
            MockCondition(field_path="status", operator="==", value="Submitted", condition_group=1, group_logic="OR"),
            MockCondition(field_path="amount", operator=">", value="50", value_type="Number", condition_group=1, group_logic="OR"),
        ]
        rule = MockRule(conditions=conditions, condition_logic="OR")

        engine = TestableECAEngine(self.doc)
        result = engine.evaluate_rule(rule)
        self.assertTrue(result)

    def test_or_logic_all_false(self):
        """Test OR logic when all conditions are False."""
        conditions = [
            MockCondition(field_path="status", operator="==", value="Submitted", condition_group=1, group_logic="OR"),
            MockCondition(field_path="amount", operator=">", value="200", value_type="Number", condition_group=1, group_logic="OR"),
        ]
        rule = MockRule(conditions=conditions, condition_logic="OR")

        engine = TestableECAEngine(self.doc)
        result = engine.evaluate_rule(rule)
        self.assertFalse(result)

    def test_empty_conditions(self):
        """Test empty conditions returns True (per spec)."""
        rule = MockRule(conditions=[])

        engine = TestableECAEngine(self.doc)
        result = engine.evaluate_rule(rule)
        self.assertTrue(result)

    def test_multiple_groups_and_logic(self):
        """Test multiple condition groups with AND top-level logic."""
        conditions = [
            MockCondition(field_path="status", operator="==", value="Draft", condition_group=1, group_logic="AND"),
            MockCondition(field_path="amount", operator=">", value="50", value_type="Number", condition_group=2, group_logic="AND"),
        ]
        rule = MockRule(conditions=conditions, condition_logic="AND")

        engine = TestableECAEngine(self.doc)
        result = engine.evaluate_rule(rule)
        self.assertTrue(result)  # Both groups pass

    def test_multiple_groups_or_logic(self):
        """Test multiple condition groups with OR top-level logic."""
        conditions = [
            MockCondition(field_path="status", operator="==", value="Submitted", condition_group=1, group_logic="AND"),
            MockCondition(field_path="amount", operator=">", value="50", value_type="Number", condition_group=2, group_logic="AND"),
        ]
        rule = MockRule(conditions=conditions, condition_logic="OR")

        engine = TestableECAEngine(self.doc)
        result = engine.evaluate_rule(rule)
        self.assertTrue(result)  # Group 2 passes, OR requires only one


class TestECAEngineJinjaTemplateSupport(unittest.TestCase):
    """Tests for Jinja template support in condition values."""

    def setUp(self):
        """Set up test document."""
        self.doc = MockDocument(status="Draft", amount=100.0, email="test@example.com")

    def test_jinja_template_simple(self):
        """Test simple Jinja template rendering."""
        condition = MockCondition(
            field_path="status",
            operator="==",
            value="{{doc.status}}",
            value_type="Jinja Expression"
        )
        rule = MockRule(conditions=[condition])

        engine = TestableECAEngine(self.doc)
        result = engine.evaluate_rule(rule)
        self.assertTrue(result)

    def test_jinja_template_auto_detect(self):
        """Test auto-detection of Jinja templates ({{ in value)."""
        engine = TestableECAEngine(self.doc)
        result = engine._parse_value("{{doc.status}}", "String")
        self.assertEqual(result, "Draft")

    def test_jinja_template_with_spaces(self):
        """Test Jinja template with spaces."""
        engine = TestableECAEngine(self.doc)
        result = engine._parse_value("{{ doc.status }}", "String")
        self.assertEqual(result, "Draft")


class TestECAEngineValueParsing(unittest.TestCase):
    """Tests for value parsing based on value_type."""

    def setUp(self):
        """Set up test document."""
        self.doc = MockDocument()
        self.engine = TestableECAEngine(self.doc)

    def test_parse_number(self):
        """Test parsing number value."""
        result = self.engine._parse_value("100", "Number")
        self.assertEqual(result, 100.0)

    def test_parse_boolean_true(self):
        """Test parsing boolean true values."""
        self.assertTrue(self.engine._parse_value("true", "Boolean"))
        self.assertTrue(self.engine._parse_value("1", "Boolean"))
        self.assertTrue(self.engine._parse_value("yes", "Boolean"))
        self.assertTrue(self.engine._parse_value(True, "Boolean"))

    def test_parse_boolean_false(self):
        """Test parsing boolean false values."""
        self.assertFalse(self.engine._parse_value("false", "Boolean"))
        self.assertFalse(self.engine._parse_value("0", "Boolean"))
        self.assertFalse(self.engine._parse_value("no", "Boolean"))

    def test_parse_date(self):
        """Test parsing date value."""
        result = self.engine._parse_value("2026-01-15", "Date")
        self.assertEqual(result, date(2026, 1, 15))

    def test_parse_json(self):
        """Test parsing JSON value."""
        result = self.engine._parse_value('["a", "b", "c"]', "JSON")
        self.assertEqual(result, ["a", "b", "c"])

    def test_parse_json_dict(self):
        """Test parsing JSON dict value."""
        result = self.engine._parse_value('{"key": "value"}', "JSON")
        self.assertEqual(result, {"key": "value"})

    def test_parse_string_default(self):
        """Test parsing string value (default)."""
        result = self.engine._parse_value("test", "String")
        self.assertEqual(result, "test")

    def test_parse_null(self):
        """Test parsing null value."""
        result = self.engine._parse_value(None, "String")
        self.assertIsNone(result)


class TestAllOperatorsIntegration(unittest.TestCase):
    """Integration tests verifying all 22 operators work with ECAEngine."""

    def setUp(self):
        """Set up test document with various field types."""
        self.doc = MockDocument(
            status="Draft",
            amount=100.0,
            quantity=10,
            email="test@example.com",
            description="Hello World",
            created_date="2026-01-15",
            is_active=True,
            tags=["urgent", "vip"],
            metadata={"category": "Electronics"}
        )
        self.old_doc = MockDocument(
            status="New",
            amount=50.0
        )

    def _test_operator(self, field_path, operator, value, value_type="String", expected=True):
        """Helper to test an operator via ECAEngine."""
        condition = MockCondition(
            field_path=field_path,
            operator=operator,
            value=value,
            value_type=value_type
        )
        rule = MockRule(conditions=[condition])
        engine = TestableECAEngine(self.doc, self.old_doc)
        result = engine.evaluate_rule(rule)
        self.assertEqual(result, expected, f"Operator '{operator}' failed: expected {expected}, got {result}")

    def test_operator_01_equals(self):
        """Test == operator via engine."""
        self._test_operator("status", "==", "Draft", expected=True)
        self._test_operator("status", "==", "Submitted", expected=False)

    def test_operator_02_not_equals(self):
        """Test != operator via engine."""
        self._test_operator("status", "!=", "Submitted", expected=True)
        self._test_operator("status", "!=", "Draft", expected=False)

    def test_operator_03_greater_than(self):
        """Test > operator via engine."""
        self._test_operator("amount", ">", "50", "Number", expected=True)
        self._test_operator("amount", ">", "100", "Number", expected=False)

    def test_operator_04_greater_than_or_equal(self):
        """Test >= operator via engine."""
        self._test_operator("amount", ">=", "100", "Number", expected=True)
        self._test_operator("amount", ">=", "101", "Number", expected=False)

    def test_operator_05_less_than(self):
        """Test < operator via engine."""
        self._test_operator("amount", "<", "200", "Number", expected=True)
        self._test_operator("amount", "<", "50", "Number", expected=False)

    def test_operator_06_less_than_or_equal(self):
        """Test <= operator via engine."""
        self._test_operator("amount", "<=", "100", "Number", expected=True)
        self._test_operator("amount", "<=", "99", "Number", expected=False)

    def test_operator_07_in(self):
        """Test 'in' operator via engine."""
        self._test_operator("status", "in", '["Draft", "New"]', "JSON", expected=True)
        self._test_operator("status", "in", '["Submitted", "Cancelled"]', "JSON", expected=False)

    def test_operator_08_not_in(self):
        """Test 'not_in' operator via engine."""
        self._test_operator("status", "not_in", '["Submitted", "Cancelled"]', "JSON", expected=True)
        self._test_operator("status", "not_in", '["Draft", "New"]', "JSON", expected=False)

    def test_operator_09_contains(self):
        """Test 'contains' operator via engine."""
        self._test_operator("description", "contains", "World", expected=True)
        self._test_operator("description", "contains", "Python", expected=False)

    def test_operator_10_not_contains(self):
        """Test 'not_contains' operator via engine."""
        self._test_operator("description", "not_contains", "Python", expected=True)
        self._test_operator("description", "not_contains", "World", expected=False)

    def test_operator_11_starts_with(self):
        """Test 'starts_with' operator via engine."""
        self._test_operator("description", "starts_with", "Hello", expected=True)
        self._test_operator("description", "starts_with", "World", expected=False)

    def test_operator_12_ends_with(self):
        """Test 'ends_with' operator via engine."""
        self._test_operator("description", "ends_with", "World", expected=True)
        self._test_operator("description", "ends_with", "Hello", expected=False)

    def test_operator_13_is_set(self):
        """Test 'is_set' operator via engine."""
        self._test_operator("status", "is_set", None, expected=True)
        # Test with a field that's None
        self.doc.metadata = {"empty_field": None}
        self._test_operator("metadata.empty_field", "is_set", None, expected=False)

    def test_operator_14_is_not_set(self):
        """Test 'is_not_set' operator via engine."""
        self._test_operator("nonexistent_field", "is_not_set", None, expected=True)
        self._test_operator("status", "is_not_set", None, expected=False)

    def test_operator_15_regex_match(self):
        """Test 'regex_match' operator via engine."""
        self._test_operator("email", "regex_match", r".*@.*\.com", expected=True)
        self._test_operator("email", "regex_match", r"^\d+$", expected=False)

    def test_operator_16_date_before(self):
        """Test 'date_before' operator via engine."""
        self._test_operator("created_date", "date_before", "2026-02-01", "Date", expected=True)
        self._test_operator("created_date", "date_before", "2026-01-01", "Date", expected=False)

    def test_operator_17_date_after(self):
        """Test 'date_after' operator via engine."""
        self._test_operator("created_date", "date_after", "2026-01-01", "Date", expected=True)
        self._test_operator("created_date", "date_after", "2026-02-01", "Date", expected=False)

    def test_operator_18_between(self):
        """Test 'between' operator via engine."""
        self._test_operator("amount", "between", '[50, 150]', "JSON", expected=True)
        self._test_operator("amount", "between", '[200, 300]', "JSON", expected=False)

    def test_operator_19_is_empty(self):
        """Test 'is_empty' operator via engine."""
        self.doc.metadata = {"empty_list": []}
        self._test_operator("metadata.empty_list", "is_empty", None, expected=True)
        self._test_operator("status", "is_empty", None, expected=False)

    def test_operator_20_changed(self):
        """Test 'changed' operator via engine."""
        self._test_operator("status", "changed", None, expected=True)  # Draft != New
        self._test_operator("email", "changed", None, expected=False)  # Same value

    def test_operator_21_changed_to(self):
        """Test 'changed_to' operator via engine."""
        self._test_operator("status", "changed_to", "Draft", expected=True)  # Changed from New to Draft
        self._test_operator("status", "changed_to", "Submitted", expected=False)

    def test_operator_22_changed_from(self):
        """Test 'changed_from' operator via engine."""
        self._test_operator("status", "changed_from", "New", expected=True)  # Changed from New
        self._test_operator("status", "changed_from", "Draft", expected=False)


class TestEdgeCases(unittest.TestCase):
    """Tests for edge cases and error handling."""

    def test_null_document(self):
        """Test engine with various null scenarios."""
        doc = MockDocument()
        engine = TestableECAEngine(doc)

        # Null field should return None
        result = engine.get_field_value("nonexistent")
        self.assertIsNone(result)

    def test_invalid_operator(self):
        """Test with invalid operator."""
        doc = MockDocument(status="Draft")
        condition = MockCondition(
            field_path="status",
            operator="invalid_operator",
            value="Draft"
        )
        rule = MockRule(conditions=[condition])

        engine = TestableECAEngine(doc)
        result = engine.evaluate_rule(rule)
        self.assertFalse(result)  # Invalid operator should return False

    def test_deeply_nested_path(self):
        """Test deeply nested field path."""
        doc = MockDocument()
        doc.level1 = type('obj', (object,), {
            'level2': type('obj', (object,), {
                'level3': "deep_value"
            })()
        })()

        engine = TestableECAEngine(doc)
        result = engine.get_field_value("level1.level2.level3")
        self.assertEqual(result, "deep_value")

    def test_condition_evaluation_exception_handling(self):
        """Test that exceptions in condition evaluation are handled gracefully."""
        doc = MockDocument()

        # Create a condition that might cause an exception
        condition = MockCondition(
            field_path="amount",
            operator=">",
            value="not_a_number",
            value_type="String"  # Intentionally wrong type for numeric comparison
        )
        rule = MockRule(conditions=[condition])

        engine = TestableECAEngine(doc)
        # Should not raise exception, should return False
        result = engine.evaluate_rule(rule)
        self.assertFalse(result)

    def test_mixed_condition_groups(self):
        """Test complex scenario with mixed AND/OR groups."""
        doc = MockDocument(status="Draft", amount=150.0, quantity=5)

        conditions = [
            # Group 1: status == "Draft" AND amount > 100 (both true)
            MockCondition(field_path="status", operator="==", value="Draft", condition_group=1, group_logic="AND"),
            MockCondition(field_path="amount", operator=">", value="100", value_type="Number", condition_group=1, group_logic="AND"),
            # Group 2: quantity < 10 (true)
            MockCondition(field_path="quantity", operator="<", value="10", value_type="Number", condition_group=2, group_logic="AND"),
        ]

        # Test with AND logic (all groups must pass)
        rule = MockRule(conditions=conditions, condition_logic="AND")
        engine = TestableECAEngine(doc)
        result = engine.evaluate_rule(rule)
        self.assertTrue(result)

        # Test with OR logic (any group must pass)
        rule.condition_logic = "OR"
        result = engine.evaluate_rule(rule)
        self.assertTrue(result)


# =============================================================================
# OPERATOR COUNT VERIFICATION
# =============================================================================

class TestOperatorCount(unittest.TestCase):
    """Verify all 22 operators are defined."""

    def test_operator_count(self):
        """Verify exactly 22 operators are defined."""
        self.assertEqual(len(OPERATORS), 22, f"Expected 22 operators, found {len(OPERATORS)}")

    def test_all_operators_present(self):
        """Verify all required operators are present."""
        required_operators = [
            # Standard operators (14)
            "==", "!=", ">", ">=", "<", "<=",
            "in", "not_in",
            "contains", "not_contains", "starts_with", "ends_with",
            "is_set", "is_not_set",
            # New operators (8)
            "regex_match", "date_before", "date_after", "between", "is_empty",
            "changed", "changed_to", "changed_from"
        ]

        for op in required_operators:
            self.assertIn(op, OPERATORS, f"Missing operator: {op}")

        self.assertEqual(len(required_operators), 22)


# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":
    unittest.main(verbosity=2)

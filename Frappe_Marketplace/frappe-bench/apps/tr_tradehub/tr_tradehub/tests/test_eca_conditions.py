# Copyright (c) 2026, TR TradeHub and contributors
# For license information, please see license.txt

"""
Unit tests for ECA Condition Evaluation

Tests the ECA condition evaluation system including:
- All 18 field condition operators (equals, not_equals, greater_than, etc.)
- Change detection operators (changed, changed_from, changed_to)
- Jinja template conditions with SandboxedEnvironment
- Python expression conditions with sandboxed execution
- Condition logic combinations (AND, OR, Custom)
- Value types (Static, Field Reference, Jinja Expression)
- Nested field value access
- Edge cases and error handling
"""

import json
import frappe
from frappe.tests.utils import FrappeTestCase
from unittest.mock import MagicMock, patch

from tr_tradehub.eca.dispatcher import ECADispatcher


class MockCondition:
    """Mock condition object for testing"""

    def __init__(
        self,
        field_name,
        operator,
        value=None,
        value_type='Static',
        logic_operator='AND'
    ):
        self.field_name = field_name
        self.operator = operator
        self.value = value
        self.value_type = value_type
        self.logic_operator = logic_operator


class MockRule:
    """Mock rule object for testing"""

    def __init__(
        self,
        conditions=None,
        jinja_condition=None,
        python_condition=None,
        condition_logic='AND'
    ):
        self.name = 'test_rule'
        self.rule_name = 'Test Rule'
        self.conditions = conditions or []
        self.jinja_condition = jinja_condition
        self.python_condition = python_condition
        self.condition_logic = condition_logic


class MockDocument:
    """Mock Frappe document for testing"""

    def __init__(self, doctype='Test DocType', name='TEST-001', **fields):
        self.doctype = doctype
        self.name = name
        self._doc_before_save = {}

        # Set default fields
        self._fields = {
            'status': 'Draft',
            'priority': 'Medium',
            'amount': 100.0,
            'count': 5,
            'description': 'Test description for testing',
            'tags': 'tag1, tag2, tag3',
            'is_active': 1,
            'email': 'test@example.com',
            'percentage': 75.5,
            'empty_field': None,
            'empty_string': '',
            'empty_list': [],
            **fields
        }

        for key, value in self._fields.items():
            setattr(self, key, value)

    def as_dict(self):
        """Return document as dictionary"""
        result = {
            'doctype': self.doctype,
            'name': self.name,
        }
        result.update(self._fields)
        return result

    def set_previous_value(self, field, old_value):
        """Set previous value for change detection tests"""
        self._doc_before_save[field] = old_value


class TestECAConditionOperators(FrappeTestCase):
    """Test cases for individual ECA condition operators"""

    def _create_dispatcher(self, doc=None, **doc_fields):
        """Helper to create ECA dispatcher with mock document"""
        if doc is None:
            doc = MockDocument(**doc_fields)
        return ECADispatcher(doc, 'after_save')

    # =========================================================================
    # EQUALS OPERATOR TESTS
    # =========================================================================

    def test_equals_string_match(self):
        """Test equals operator with matching strings"""
        dispatcher = self._create_dispatcher(status='Active')
        condition = MockCondition('status', 'equals', 'Active')

        result = dispatcher._evaluate_single_condition(condition)

        self.assertTrue(result)

    def test_equals_string_no_match(self):
        """Test equals operator with non-matching strings"""
        dispatcher = self._create_dispatcher(status='Active')
        condition = MockCondition('status', 'equals', 'Inactive')

        result = dispatcher._evaluate_single_condition(condition)

        self.assertFalse(result)

    def test_equals_numeric_match(self):
        """Test equals operator with matching numbers"""
        dispatcher = self._create_dispatcher(amount=100.0)
        condition = MockCondition('amount', 'equals', '100')

        result = dispatcher._evaluate_single_condition(condition)

        self.assertTrue(result)

    def test_equals_numeric_float_int(self):
        """Test equals operator with float and int comparison"""
        dispatcher = self._create_dispatcher(count=5)
        condition = MockCondition('count', 'equals', '5.0')

        result = dispatcher._evaluate_single_condition(condition)

        self.assertTrue(result)

    def test_equals_null_values(self):
        """Test equals operator with null values"""
        dispatcher = self._create_dispatcher(empty_field=None)
        condition = MockCondition('empty_field', 'equals', None)

        result = dispatcher._evaluate_single_condition(condition)

        self.assertTrue(result)

    def test_equals_case_sensitive(self):
        """Test equals operator is case sensitive"""
        dispatcher = self._create_dispatcher(status='Active')
        condition = MockCondition('status', 'equals', 'active')

        result = dispatcher._evaluate_single_condition(condition)

        # String comparison via cstr, which preserves case, but values compared
        self.assertFalse(result)

    # =========================================================================
    # NOT_EQUALS OPERATOR TESTS
    # =========================================================================

    def test_not_equals_match(self):
        """Test not_equals operator returns True for different values"""
        dispatcher = self._create_dispatcher(status='Active')
        condition = MockCondition('status', 'not_equals', 'Inactive')

        result = dispatcher._evaluate_single_condition(condition)

        self.assertTrue(result)

    def test_not_equals_same_value(self):
        """Test not_equals operator returns False for same values"""
        dispatcher = self._create_dispatcher(status='Active')
        condition = MockCondition('status', 'not_equals', 'Active')

        result = dispatcher._evaluate_single_condition(condition)

        self.assertFalse(result)

    def test_not_equals_numeric(self):
        """Test not_equals operator with numeric values"""
        dispatcher = self._create_dispatcher(amount=100)
        condition = MockCondition('amount', 'not_equals', '50')

        result = dispatcher._evaluate_single_condition(condition)

        self.assertTrue(result)

    # =========================================================================
    # GREATER_THAN OPERATOR TESTS
    # =========================================================================

    def test_greater_than_true(self):
        """Test greater_than operator returns True when field > value"""
        dispatcher = self._create_dispatcher(amount=100)
        condition = MockCondition('amount', 'greater_than', '50')

        result = dispatcher._evaluate_single_condition(condition)

        self.assertTrue(result)

    def test_greater_than_equal(self):
        """Test greater_than operator returns False when field == value"""
        dispatcher = self._create_dispatcher(amount=100)
        condition = MockCondition('amount', 'greater_than', '100')

        result = dispatcher._evaluate_single_condition(condition)

        self.assertFalse(result)

    def test_greater_than_false(self):
        """Test greater_than operator returns False when field < value"""
        dispatcher = self._create_dispatcher(amount=50)
        condition = MockCondition('amount', 'greater_than', '100')

        result = dispatcher._evaluate_single_condition(condition)

        self.assertFalse(result)

    def test_greater_than_float(self):
        """Test greater_than operator with float values"""
        dispatcher = self._create_dispatcher(percentage=75.5)
        condition = MockCondition('percentage', 'greater_than', '75.4')

        result = dispatcher._evaluate_single_condition(condition)

        self.assertTrue(result)

    def test_greater_than_negative(self):
        """Test greater_than operator with negative values"""
        dispatcher = self._create_dispatcher(amount=-10)
        condition = MockCondition('amount', 'greater_than', '-20')

        result = dispatcher._evaluate_single_condition(condition)

        self.assertTrue(result)

    # =========================================================================
    # LESS_THAN OPERATOR TESTS
    # =========================================================================

    def test_less_than_true(self):
        """Test less_than operator returns True when field < value"""
        dispatcher = self._create_dispatcher(amount=50)
        condition = MockCondition('amount', 'less_than', '100')

        result = dispatcher._evaluate_single_condition(condition)

        self.assertTrue(result)

    def test_less_than_equal(self):
        """Test less_than operator returns False when field == value"""
        dispatcher = self._create_dispatcher(amount=100)
        condition = MockCondition('amount', 'less_than', '100')

        result = dispatcher._evaluate_single_condition(condition)

        self.assertFalse(result)

    def test_less_than_false(self):
        """Test less_than operator returns False when field > value"""
        dispatcher = self._create_dispatcher(amount=150)
        condition = MockCondition('amount', 'less_than', '100')

        result = dispatcher._evaluate_single_condition(condition)

        self.assertFalse(result)

    # =========================================================================
    # GREATER_THAN_OR_EQUALS OPERATOR TESTS
    # =========================================================================

    def test_greater_than_or_equals_greater(self):
        """Test greater_than_or_equals when field > value"""
        dispatcher = self._create_dispatcher(amount=150)
        condition = MockCondition('amount', 'greater_than_or_equals', '100')

        result = dispatcher._evaluate_single_condition(condition)

        self.assertTrue(result)

    def test_greater_than_or_equals_equal(self):
        """Test greater_than_or_equals when field == value"""
        dispatcher = self._create_dispatcher(amount=100)
        condition = MockCondition('amount', 'greater_than_or_equals', '100')

        result = dispatcher._evaluate_single_condition(condition)

        self.assertTrue(result)

    def test_greater_than_or_equals_less(self):
        """Test greater_than_or_equals when field < value"""
        dispatcher = self._create_dispatcher(amount=50)
        condition = MockCondition('amount', 'greater_than_or_equals', '100')

        result = dispatcher._evaluate_single_condition(condition)

        self.assertFalse(result)

    # =========================================================================
    # LESS_THAN_OR_EQUALS OPERATOR TESTS
    # =========================================================================

    def test_less_than_or_equals_less(self):
        """Test less_than_or_equals when field < value"""
        dispatcher = self._create_dispatcher(amount=50)
        condition = MockCondition('amount', 'less_than_or_equals', '100')

        result = dispatcher._evaluate_single_condition(condition)

        self.assertTrue(result)

    def test_less_than_or_equals_equal(self):
        """Test less_than_or_equals when field == value"""
        dispatcher = self._create_dispatcher(amount=100)
        condition = MockCondition('amount', 'less_than_or_equals', '100')

        result = dispatcher._evaluate_single_condition(condition)

        self.assertTrue(result)

    def test_less_than_or_equals_greater(self):
        """Test less_than_or_equals when field > value"""
        dispatcher = self._create_dispatcher(amount=150)
        condition = MockCondition('amount', 'less_than_or_equals', '100')

        result = dispatcher._evaluate_single_condition(condition)

        self.assertFalse(result)

    # =========================================================================
    # CONTAINS OPERATOR TESTS
    # =========================================================================

    def test_contains_substring_found(self):
        """Test contains operator finds substring"""
        dispatcher = self._create_dispatcher(description='This is a test description')
        condition = MockCondition('description', 'contains', 'test')

        result = dispatcher._evaluate_single_condition(condition)

        self.assertTrue(result)

    def test_contains_substring_not_found(self):
        """Test contains operator returns False when substring not found"""
        dispatcher = self._create_dispatcher(description='This is a test description')
        condition = MockCondition('description', 'contains', 'missing')

        result = dispatcher._evaluate_single_condition(condition)

        self.assertFalse(result)

    def test_contains_full_match(self):
        """Test contains operator with full string match"""
        dispatcher = self._create_dispatcher(status='Active')
        condition = MockCondition('status', 'contains', 'Active')

        result = dispatcher._evaluate_single_condition(condition)

        self.assertTrue(result)

    def test_contains_empty_substring(self):
        """Test contains operator with empty substring"""
        dispatcher = self._create_dispatcher(description='Test')
        condition = MockCondition('description', 'contains', '')

        result = dispatcher._evaluate_single_condition(condition)

        # Empty string is always contained in any string
        self.assertTrue(result)

    def test_contains_case_sensitive(self):
        """Test contains operator is case sensitive"""
        dispatcher = self._create_dispatcher(description='Test Description')
        condition = MockCondition('description', 'contains', 'TEST')

        result = dispatcher._evaluate_single_condition(condition)

        self.assertFalse(result)

    # =========================================================================
    # NOT_CONTAINS OPERATOR TESTS
    # =========================================================================

    def test_not_contains_true(self):
        """Test not_contains operator returns True when substring not found"""
        dispatcher = self._create_dispatcher(description='Test description')
        condition = MockCondition('description', 'not_contains', 'missing')

        result = dispatcher._evaluate_single_condition(condition)

        self.assertTrue(result)

    def test_not_contains_false(self):
        """Test not_contains operator returns False when substring found"""
        dispatcher = self._create_dispatcher(description='Test description')
        condition = MockCondition('description', 'not_contains', 'Test')

        result = dispatcher._evaluate_single_condition(condition)

        self.assertFalse(result)

    # =========================================================================
    # STARTS_WITH OPERATOR TESTS
    # =========================================================================

    def test_starts_with_true(self):
        """Test starts_with operator returns True for matching prefix"""
        dispatcher = self._create_dispatcher(email='test@example.com')
        condition = MockCondition('email', 'starts_with', 'test')

        result = dispatcher._evaluate_single_condition(condition)

        self.assertTrue(result)

    def test_starts_with_false(self):
        """Test starts_with operator returns False for non-matching prefix"""
        dispatcher = self._create_dispatcher(email='test@example.com')
        condition = MockCondition('email', 'starts_with', 'admin')

        result = dispatcher._evaluate_single_condition(condition)

        self.assertFalse(result)

    def test_starts_with_case_sensitive(self):
        """Test starts_with operator is case sensitive"""
        dispatcher = self._create_dispatcher(email='Test@example.com')
        condition = MockCondition('email', 'starts_with', 'test')

        result = dispatcher._evaluate_single_condition(condition)

        self.assertFalse(result)

    def test_starts_with_empty_prefix(self):
        """Test starts_with with empty prefix"""
        dispatcher = self._create_dispatcher(email='test@example.com')
        condition = MockCondition('email', 'starts_with', '')

        result = dispatcher._evaluate_single_condition(condition)

        # Empty string is a prefix of any string
        self.assertTrue(result)

    # =========================================================================
    # ENDS_WITH OPERATOR TESTS
    # =========================================================================

    def test_ends_with_true(self):
        """Test ends_with operator returns True for matching suffix"""
        dispatcher = self._create_dispatcher(email='test@example.com')
        condition = MockCondition('email', 'ends_with', '.com')

        result = dispatcher._evaluate_single_condition(condition)

        self.assertTrue(result)

    def test_ends_with_false(self):
        """Test ends_with operator returns False for non-matching suffix"""
        dispatcher = self._create_dispatcher(email='test@example.com')
        condition = MockCondition('email', 'ends_with', '.org')

        result = dispatcher._evaluate_single_condition(condition)

        self.assertFalse(result)

    def test_ends_with_case_sensitive(self):
        """Test ends_with operator is case sensitive"""
        dispatcher = self._create_dispatcher(email='test@example.COM')
        condition = MockCondition('email', 'ends_with', '.com')

        result = dispatcher._evaluate_single_condition(condition)

        self.assertFalse(result)

    # =========================================================================
    # IS_SET OPERATOR TESTS
    # =========================================================================

    def test_is_set_with_value(self):
        """Test is_set operator returns True when field has value"""
        dispatcher = self._create_dispatcher(status='Active')
        condition = MockCondition('status', 'is_set')

        result = dispatcher._evaluate_single_condition(condition)

        self.assertTrue(result)

    def test_is_set_null_value(self):
        """Test is_set operator returns False for None value"""
        dispatcher = self._create_dispatcher(empty_field=None)
        condition = MockCondition('empty_field', 'is_set')

        result = dispatcher._evaluate_single_condition(condition)

        self.assertFalse(result)

    def test_is_set_empty_string(self):
        """Test is_set operator returns False for empty string"""
        dispatcher = self._create_dispatcher(empty_string='')
        condition = MockCondition('empty_string', 'is_set')

        result = dispatcher._evaluate_single_condition(condition)

        self.assertFalse(result)

    def test_is_set_empty_list(self):
        """Test is_set operator returns False for empty list"""
        dispatcher = self._create_dispatcher(empty_list=[])
        condition = MockCondition('empty_list', 'is_set')

        result = dispatcher._evaluate_single_condition(condition)

        self.assertFalse(result)

    def test_is_set_zero_value(self):
        """Test is_set operator returns True for zero"""
        dispatcher = self._create_dispatcher(count=0)
        condition = MockCondition('count', 'is_set')

        result = dispatcher._evaluate_single_condition(condition)

        # Zero is a valid value, so is_set should return True
        # But based on the dispatcher logic: value is not None and value != '' and value != []
        # 0 passes this check
        self.assertTrue(result)

    def test_is_set_false_boolean(self):
        """Test is_set operator with False boolean"""
        dispatcher = self._create_dispatcher(is_active=False)
        condition = MockCondition('is_active', 'is_set')

        result = dispatcher._evaluate_single_condition(condition)

        # False is a valid value (not None, not '', not [])
        self.assertTrue(result)

    # =========================================================================
    # IS_NOT_SET OPERATOR TESTS
    # =========================================================================

    def test_is_not_set_null_value(self):
        """Test is_not_set operator returns True for None value"""
        dispatcher = self._create_dispatcher(empty_field=None)
        condition = MockCondition('empty_field', 'is_not_set')

        result = dispatcher._evaluate_single_condition(condition)

        self.assertTrue(result)

    def test_is_not_set_empty_string(self):
        """Test is_not_set operator returns True for empty string"""
        dispatcher = self._create_dispatcher(empty_string='')
        condition = MockCondition('empty_string', 'is_not_set')

        result = dispatcher._evaluate_single_condition(condition)

        self.assertTrue(result)

    def test_is_not_set_empty_list(self):
        """Test is_not_set operator returns True for empty list"""
        dispatcher = self._create_dispatcher(empty_list=[])
        condition = MockCondition('empty_list', 'is_not_set')

        result = dispatcher._evaluate_single_condition(condition)

        self.assertTrue(result)

    def test_is_not_set_with_value(self):
        """Test is_not_set operator returns False when field has value"""
        dispatcher = self._create_dispatcher(status='Active')
        condition = MockCondition('status', 'is_not_set')

        result = dispatcher._evaluate_single_condition(condition)

        self.assertFalse(result)

    # =========================================================================
    # CHANGED OPERATOR TESTS
    # =========================================================================

    def test_changed_true(self):
        """Test changed operator returns True when field value changed"""
        doc = MockDocument(status='Active')
        doc.set_previous_value('status', 'Draft')

        dispatcher = self._create_dispatcher(doc=doc)
        condition = MockCondition('status', 'changed')

        result = dispatcher._evaluate_single_condition(condition)

        self.assertTrue(result)

    def test_changed_false_same_value(self):
        """Test changed operator returns False when value unchanged"""
        doc = MockDocument(status='Active')
        doc.set_previous_value('status', 'Active')

        dispatcher = self._create_dispatcher(doc=doc)
        condition = MockCondition('status', 'changed')

        result = dispatcher._evaluate_single_condition(condition)

        self.assertFalse(result)

    def test_changed_no_previous_value(self):
        """Test changed operator returns False without _doc_before_save"""
        doc = MockDocument(status='Active')
        # Don't set _doc_before_save
        del doc._doc_before_save

        dispatcher = self._create_dispatcher(doc=doc)
        condition = MockCondition('status', 'changed')

        result = dispatcher._evaluate_single_condition(condition)

        self.assertFalse(result)

    def test_changed_numeric_value(self):
        """Test changed operator with numeric values"""
        doc = MockDocument(amount=150)
        doc.set_previous_value('amount', 100)

        dispatcher = self._create_dispatcher(doc=doc)
        condition = MockCondition('amount', 'changed')

        result = dispatcher._evaluate_single_condition(condition)

        self.assertTrue(result)

    def test_changed_null_to_value(self):
        """Test changed operator when field goes from None to value"""
        doc = MockDocument(status='Active')
        doc.set_previous_value('status', None)

        dispatcher = self._create_dispatcher(doc=doc)
        condition = MockCondition('status', 'changed')

        result = dispatcher._evaluate_single_condition(condition)

        self.assertTrue(result)

    # =========================================================================
    # CHANGED_FROM OPERATOR TESTS
    # =========================================================================

    def test_changed_from_true(self):
        """Test changed_from returns True when field changed from specific value"""
        doc = MockDocument(status='Active')
        doc.set_previous_value('status', 'Draft')

        dispatcher = self._create_dispatcher(doc=doc)
        condition = MockCondition('status', 'changed_from', 'Draft')

        result = dispatcher._evaluate_single_condition(condition)

        self.assertTrue(result)

    def test_changed_from_false_different_old_value(self):
        """Test changed_from returns False when old value differs"""
        doc = MockDocument(status='Active')
        doc.set_previous_value('status', 'Pending')

        dispatcher = self._create_dispatcher(doc=doc)
        condition = MockCondition('status', 'changed_from', 'Draft')

        result = dispatcher._evaluate_single_condition(condition)

        self.assertFalse(result)

    def test_changed_from_false_no_change(self):
        """Test changed_from returns False when value unchanged"""
        doc = MockDocument(status='Draft')
        doc.set_previous_value('status', 'Draft')

        dispatcher = self._create_dispatcher(doc=doc)
        condition = MockCondition('status', 'changed_from', 'Draft')

        result = dispatcher._evaluate_single_condition(condition)

        # Old value matches but new value is the same, so no change from
        self.assertFalse(result)

    def test_changed_from_no_previous(self):
        """Test changed_from returns False without _doc_before_save"""
        doc = MockDocument(status='Active')
        del doc._doc_before_save

        dispatcher = self._create_dispatcher(doc=doc)
        condition = MockCondition('status', 'changed_from', 'Draft')

        result = dispatcher._evaluate_single_condition(condition)

        self.assertFalse(result)

    # =========================================================================
    # CHANGED_TO OPERATOR TESTS
    # =========================================================================

    def test_changed_to_true(self):
        """Test changed_to returns True when field changed to specific value"""
        doc = MockDocument(status='Active')
        doc.set_previous_value('status', 'Draft')

        dispatcher = self._create_dispatcher(doc=doc)
        condition = MockCondition('status', 'changed_to', 'Active')

        result = dispatcher._evaluate_single_condition(condition)

        self.assertTrue(result)

    def test_changed_to_false_different_new_value(self):
        """Test changed_to returns False when new value differs"""
        doc = MockDocument(status='Pending')
        doc.set_previous_value('status', 'Draft')

        dispatcher = self._create_dispatcher(doc=doc)
        condition = MockCondition('status', 'changed_to', 'Active')

        result = dispatcher._evaluate_single_condition(condition)

        self.assertFalse(result)

    def test_changed_to_false_no_change(self):
        """Test changed_to returns False when value already was target"""
        doc = MockDocument(status='Active')
        doc.set_previous_value('status', 'Active')

        dispatcher = self._create_dispatcher(doc=doc)
        condition = MockCondition('status', 'changed_to', 'Active')

        result = dispatcher._evaluate_single_condition(condition)

        # New value matches but old value was the same, so no change to
        self.assertFalse(result)

    def test_changed_to_no_previous(self):
        """Test changed_to returns False without _doc_before_save"""
        doc = MockDocument(status='Active')
        del doc._doc_before_save

        dispatcher = self._create_dispatcher(doc=doc)
        condition = MockCondition('status', 'changed_to', 'Active')

        result = dispatcher._evaluate_single_condition(condition)

        self.assertFalse(result)

    # =========================================================================
    # IN_LIST OPERATOR TESTS
    # =========================================================================

    def test_in_list_comma_separated(self):
        """Test in_list operator with comma-separated values"""
        dispatcher = self._create_dispatcher(status='Active')
        condition = MockCondition('status', 'in_list', 'Draft, Active, Completed')

        result = dispatcher._evaluate_single_condition(condition)

        self.assertTrue(result)

    def test_in_list_json_array(self):
        """Test in_list operator with JSON array"""
        dispatcher = self._create_dispatcher(status='Active')
        condition = MockCondition('status', 'in_list', '["Draft", "Active", "Completed"]')

        result = dispatcher._evaluate_single_condition(condition)

        self.assertTrue(result)

    def test_in_list_not_found(self):
        """Test in_list operator returns False when value not in list"""
        dispatcher = self._create_dispatcher(status='Pending')
        condition = MockCondition('status', 'in_list', 'Draft, Active, Completed')

        result = dispatcher._evaluate_single_condition(condition)

        self.assertFalse(result)

    def test_in_list_numeric(self):
        """Test in_list operator with numeric values"""
        dispatcher = self._create_dispatcher(priority=2)
        condition = MockCondition('priority', 'in_list', '1, 2, 3')

        result = dispatcher._evaluate_single_condition(condition)

        self.assertTrue(result)

    def test_in_list_empty_list(self):
        """Test in_list operator with empty list"""
        dispatcher = self._create_dispatcher(status='Active')
        condition = MockCondition('status', 'in_list', '')

        result = dispatcher._evaluate_single_condition(condition)

        self.assertFalse(result)

    def test_in_list_single_value(self):
        """Test in_list operator with single value"""
        dispatcher = self._create_dispatcher(status='Active')
        condition = MockCondition('status', 'in_list', 'Active')

        result = dispatcher._evaluate_single_condition(condition)

        self.assertTrue(result)

    # =========================================================================
    # NOT_IN_LIST OPERATOR TESTS
    # =========================================================================

    def test_not_in_list_true(self):
        """Test not_in_list returns True when value not in list"""
        dispatcher = self._create_dispatcher(status='Pending')
        condition = MockCondition('status', 'not_in_list', 'Draft, Active')

        result = dispatcher._evaluate_single_condition(condition)

        self.assertTrue(result)

    def test_not_in_list_false(self):
        """Test not_in_list returns False when value in list"""
        dispatcher = self._create_dispatcher(status='Active')
        condition = MockCondition('status', 'not_in_list', 'Draft, Active')

        result = dispatcher._evaluate_single_condition(condition)

        self.assertFalse(result)

    def test_not_in_list_json_array(self):
        """Test not_in_list with JSON array"""
        dispatcher = self._create_dispatcher(status='Pending')
        condition = MockCondition('status', 'not_in_list', '["Draft", "Active"]')

        result = dispatcher._evaluate_single_condition(condition)

        self.assertTrue(result)

    # =========================================================================
    # REGEX_MATCH OPERATOR TESTS
    # =========================================================================

    def test_regex_match_simple_pattern(self):
        """Test regex_match with simple pattern"""
        dispatcher = self._create_dispatcher(email='test@example.com')
        condition = MockCondition('email', 'regex_match', r'^test@')

        result = dispatcher._evaluate_single_condition(condition)

        self.assertTrue(result)

    def test_regex_match_email_pattern(self):
        """Test regex_match with email pattern"""
        dispatcher = self._create_dispatcher(email='test@example.com')
        condition = MockCondition('email', 'regex_match', r'^[\w.+-]+@[\w.-]+\.[a-zA-Z]{2,}$')

        result = dispatcher._evaluate_single_condition(condition)

        self.assertTrue(result)

    def test_regex_match_no_match(self):
        """Test regex_match returns False when pattern doesn't match"""
        dispatcher = self._create_dispatcher(email='invalid-email')
        condition = MockCondition('email', 'regex_match', r'^[\w.+-]+@[\w.-]+\.[a-zA-Z]{2,}$')

        result = dispatcher._evaluate_single_condition(condition)

        self.assertFalse(result)

    def test_regex_match_phone_pattern(self):
        """Test regex_match with phone number pattern"""
        dispatcher = self._create_dispatcher(phone='+1-555-123-4567')
        condition = MockCondition('phone', 'regex_match', r'^\+\d{1,3}-\d{3}-\d{3}-\d{4}$')

        result = dispatcher._evaluate_single_condition(condition)

        self.assertTrue(result)

    def test_regex_match_case_sensitive(self):
        """Test regex_match is case sensitive by default"""
        dispatcher = self._create_dispatcher(status='ACTIVE')
        condition = MockCondition('status', 'regex_match', r'^active$')

        result = dispatcher._evaluate_single_condition(condition)

        self.assertFalse(result)

    def test_regex_match_special_characters(self):
        """Test regex_match with special characters"""
        dispatcher = self._create_dispatcher(code='ABC-123')
        condition = MockCondition('code', 'regex_match', r'^[A-Z]+-\d+$')

        result = dispatcher._evaluate_single_condition(condition)

        self.assertTrue(result)

    # =========================================================================
    # UNKNOWN OPERATOR TESTS
    # =========================================================================

    def test_unknown_operator_returns_false(self):
        """Test that unknown operators return False"""
        dispatcher = self._create_dispatcher(status='Active')
        condition = MockCondition('status', 'unknown_operator', 'Active')

        result = dispatcher._evaluate_single_condition(condition)

        self.assertFalse(result)

    # =========================================================================
    # NESTED FIELD ACCESS TESTS
    # =========================================================================

    def test_get_field_value_simple(self):
        """Test simple field value retrieval"""
        dispatcher = self._create_dispatcher(status='Active')

        value = dispatcher._get_field_value('status')

        self.assertEqual(value, 'Active')

    def test_get_field_value_missing_field(self):
        """Test retrieval of missing field returns None"""
        dispatcher = self._create_dispatcher()

        value = dispatcher._get_field_value('nonexistent_field')

        self.assertIsNone(value)

    def test_get_field_value_empty_name(self):
        """Test empty field name returns None"""
        dispatcher = self._create_dispatcher()

        value = dispatcher._get_field_value('')

        self.assertIsNone(value)

    def test_get_field_value_none_name(self):
        """Test None field name returns None"""
        dispatcher = self._create_dispatcher()

        value = dispatcher._get_field_value(None)

        self.assertIsNone(value)


class TestECAConditionValueTypes(FrappeTestCase):
    """Test cases for ECA condition value types (Static, Field Reference, Jinja)"""

    def _create_dispatcher(self, doc=None, **doc_fields):
        """Helper to create ECA dispatcher with mock document"""
        if doc is None:
            doc = MockDocument(**doc_fields)
        return ECADispatcher(doc, 'after_save')

    def test_value_type_static(self):
        """Test Static value type uses value as-is"""
        dispatcher = self._create_dispatcher(status='Active')
        condition = MockCondition('status', 'equals', 'Active', value_type='Static')

        compare_value = dispatcher._get_compare_value(condition)

        self.assertEqual(compare_value, 'Active')

    def test_value_type_field_reference(self):
        """Test Field Reference value type fetches from another field"""
        dispatcher = self._create_dispatcher(status='Active', expected_status='Active')
        condition = MockCondition('status', 'equals', 'expected_status', value_type='Field Reference')

        compare_value = dispatcher._get_compare_value(condition)

        self.assertEqual(compare_value, 'Active')

    def test_value_type_field_reference_missing(self):
        """Test Field Reference returns None for missing field"""
        dispatcher = self._create_dispatcher(status='Active')
        condition = MockCondition('status', 'equals', 'missing_field', value_type='Field Reference')

        compare_value = dispatcher._get_compare_value(condition)

        self.assertIsNone(compare_value)

    def test_value_type_jinja_expression(self):
        """Test Jinja Expression value type renders template"""
        dispatcher = self._create_dispatcher(status='Active', prefix='Status: ')
        condition = MockCondition(
            'combined', 'equals',
            '{{ doc.prefix }}{{ doc.status }}',
            value_type='Jinja Expression'
        )

        compare_value = dispatcher._get_compare_value(condition)

        self.assertEqual(compare_value, 'Status: Active')

    def test_value_type_none_defaults_to_static(self):
        """Test None value_type defaults to Static"""
        dispatcher = self._create_dispatcher(status='Active')
        condition = MockCondition('status', 'equals', 'Active')
        condition.value_type = None

        compare_value = dispatcher._get_compare_value(condition)

        self.assertEqual(compare_value, 'Active')


class TestECAJinjaConditions(FrappeTestCase):
    """Test cases for ECA Jinja template condition evaluation"""

    def _create_dispatcher(self, doc=None, **doc_fields):
        """Helper to create ECA dispatcher with mock document"""
        if doc is None:
            doc = MockDocument(**doc_fields)
        return ECADispatcher(doc, 'after_save')

    def test_jinja_condition_true(self):
        """Test Jinja condition evaluates to True"""
        dispatcher = self._create_dispatcher(amount=100)
        rule = MockRule(jinja_condition='{{ doc.amount > 50 }}')

        details = []
        result = dispatcher._evaluate_jinja_condition(rule, details)

        self.assertTrue(result)
        self.assertEqual(len(details), 1)
        self.assertEqual(details[0]['type'], 'jinja')
        self.assertTrue(details[0]['passed'])

    def test_jinja_condition_false(self):
        """Test Jinja condition evaluates to False"""
        dispatcher = self._create_dispatcher(amount=30)
        rule = MockRule(jinja_condition='{{ doc.amount > 50 }}')

        details = []
        result = dispatcher._evaluate_jinja_condition(rule, details)

        self.assertFalse(result)

    def test_jinja_condition_empty(self):
        """Test empty Jinja condition returns True"""
        dispatcher = self._create_dispatcher()
        rule = MockRule(jinja_condition=None)

        details = []
        result = dispatcher._evaluate_jinja_condition(rule, details)

        self.assertTrue(result)
        self.assertEqual(len(details), 0)

    def test_jinja_condition_with_frappe_utils(self):
        """Test Jinja condition can access frappe utilities"""
        dispatcher = self._create_dispatcher()
        rule = MockRule(jinja_condition='{{ frappe is defined }}')

        details = []
        result = dispatcher._evaluate_jinja_condition(rule, details)

        self.assertTrue(result)

    def test_jinja_condition_with_doc_before_save(self):
        """Test Jinja condition can access doc_before_save"""
        doc = MockDocument(status='Active')
        doc.set_previous_value('status', 'Draft')
        dispatcher = self._create_dispatcher(doc=doc)
        rule = MockRule(jinja_condition='{{ doc_before_save.status == "Draft" }}')

        details = []
        result = dispatcher._evaluate_jinja_condition(rule, details)

        self.assertTrue(result)

    def test_jinja_condition_string_false(self):
        """Test Jinja condition handles string 'false' correctly"""
        dispatcher = self._create_dispatcher()
        rule = MockRule(jinja_condition='false')

        details = []
        result = dispatcher._evaluate_jinja_condition(rule, details)

        self.assertFalse(result)

    def test_jinja_condition_string_true(self):
        """Test Jinja condition handles string 'true' correctly"""
        dispatcher = self._create_dispatcher()
        rule = MockRule(jinja_condition='true')

        details = []
        result = dispatcher._evaluate_jinja_condition(rule, details)

        self.assertTrue(result)

    def test_jinja_condition_empty_string(self):
        """Test Jinja condition handles empty string result as False"""
        dispatcher = self._create_dispatcher()
        rule = MockRule(jinja_condition='{{ "" }}')

        details = []
        result = dispatcher._evaluate_jinja_condition(rule, details)

        self.assertFalse(result)

    def test_jinja_condition_error_handling(self):
        """Test Jinja condition handles errors gracefully"""
        dispatcher = self._create_dispatcher()
        rule = MockRule(jinja_condition='{{ undefined_variable.something }}')

        details = []
        result = dispatcher._evaluate_jinja_condition(rule, details)

        self.assertFalse(result)
        self.assertEqual(len(details), 1)
        self.assertIn('error', details[0])

    def test_jinja_condition_complex_logic(self):
        """Test Jinja condition with complex logic"""
        dispatcher = self._create_dispatcher(
            amount=100,
            status='Active',
            is_active=1
        )
        rule = MockRule(
            jinja_condition='{{ doc.amount >= 100 and doc.status == "Active" and doc.is_active }}'
        )

        details = []
        result = dispatcher._evaluate_jinja_condition(rule, details)

        self.assertTrue(result)


class TestECAPythonConditions(FrappeTestCase):
    """Test cases for ECA Python expression condition evaluation"""

    def _create_dispatcher(self, doc=None, **doc_fields):
        """Helper to create ECA dispatcher with mock document"""
        if doc is None:
            doc = MockDocument(**doc_fields)
        return ECADispatcher(doc, 'after_save')

    def test_python_condition_true(self):
        """Test Python condition evaluates to True"""
        dispatcher = self._create_dispatcher(amount=100)
        rule = MockRule(python_condition='doc.get("amount") > 50')

        details = []
        result = dispatcher._evaluate_python_condition(rule, details)

        self.assertTrue(result)
        self.assertEqual(len(details), 1)
        self.assertEqual(details[0]['type'], 'python')
        self.assertTrue(details[0]['passed'])

    def test_python_condition_false(self):
        """Test Python condition evaluates to False"""
        dispatcher = self._create_dispatcher(amount=30)
        rule = MockRule(python_condition='doc.get("amount") > 50')

        details = []
        result = dispatcher._evaluate_python_condition(rule, details)

        self.assertFalse(result)

    def test_python_condition_empty(self):
        """Test empty Python condition returns True"""
        dispatcher = self._create_dispatcher()
        rule = MockRule(python_condition=None)

        details = []
        result = dispatcher._evaluate_python_condition(rule, details)

        self.assertTrue(result)
        self.assertEqual(len(details), 0)

    def test_python_condition_with_safe_builtins(self):
        """Test Python condition has access to safe built-ins"""
        dispatcher = self._create_dispatcher(items=[1, 2, 3])
        rule = MockRule(python_condition='len(doc.get("items", [])) == 3')

        details = []
        result = dispatcher._evaluate_python_condition(rule, details)

        self.assertTrue(result)

    def test_python_condition_with_cint(self):
        """Test Python condition has access to cint utility"""
        dispatcher = self._create_dispatcher(count='5')
        rule = MockRule(python_condition='cint(doc.get("count")) == 5')

        details = []
        result = dispatcher._evaluate_python_condition(rule, details)

        self.assertTrue(result)

    def test_python_condition_with_flt(self):
        """Test Python condition has access to flt utility"""
        dispatcher = self._create_dispatcher(amount='100.50')
        rule = MockRule(python_condition='flt(doc.get("amount")) > 100')

        details = []
        result = dispatcher._evaluate_python_condition(rule, details)

        self.assertTrue(result)

    def test_python_condition_error_handling(self):
        """Test Python condition handles errors gracefully"""
        dispatcher = self._create_dispatcher()
        rule = MockRule(python_condition='undefined_variable.something')

        details = []
        result = dispatcher._evaluate_python_condition(rule, details)

        self.assertFalse(result)
        self.assertEqual(len(details), 1)
        self.assertIn('error', details[0])

    def test_python_condition_with_doc_before_save(self):
        """Test Python condition can access doc_before_save"""
        doc = MockDocument(status='Active')
        doc.set_previous_value('status', 'Draft')
        dispatcher = self._create_dispatcher(doc=doc)
        rule = MockRule(
            python_condition='doc_before_save.get("status") == "Draft" and doc.get("status") == "Active"'
        )

        details = []
        result = dispatcher._evaluate_python_condition(rule, details)

        self.assertTrue(result)

    def test_python_condition_with_min_max(self):
        """Test Python condition with min/max functions"""
        dispatcher = self._create_dispatcher(values=[10, 20, 30])
        rule = MockRule(python_condition='max(doc.get("values", [])) == 30')

        details = []
        result = dispatcher._evaluate_python_condition(rule, details)

        self.assertTrue(result)

    def test_python_condition_with_any_all(self):
        """Test Python condition with any/all functions"""
        dispatcher = self._create_dispatcher(flags=[True, True, False])
        rule = MockRule(python_condition='any(doc.get("flags", []))')

        details = []
        result = dispatcher._evaluate_python_condition(rule, details)

        self.assertTrue(result)


class TestECAConditionLogic(FrappeTestCase):
    """Test cases for ECA condition logic combinations (AND, OR, Custom)"""

    def _create_dispatcher(self, doc=None, **doc_fields):
        """Helper to create ECA dispatcher with mock document"""
        if doc is None:
            doc = MockDocument(**doc_fields)
        return ECADispatcher(doc, 'after_save')

    # =========================================================================
    # AND LOGIC TESTS
    # =========================================================================

    def test_and_logic_all_true(self):
        """Test AND logic returns True when all conditions are True"""
        dispatcher = self._create_dispatcher(status='Active', amount=100)
        rule = MockRule(
            conditions=[
                MockCondition('status', 'equals', 'Active'),
                MockCondition('amount', 'greater_than', '50', logic_operator='AND'),
            ],
            condition_logic='AND'
        )

        result, details = dispatcher._evaluate_conditions(rule)

        self.assertTrue(result)

    def test_and_logic_one_false(self):
        """Test AND logic returns False when one condition is False"""
        dispatcher = self._create_dispatcher(status='Active', amount=30)
        rule = MockRule(
            conditions=[
                MockCondition('status', 'equals', 'Active'),
                MockCondition('amount', 'greater_than', '50', logic_operator='AND'),
            ],
            condition_logic='AND'
        )

        result, details = dispatcher._evaluate_conditions(rule)

        self.assertFalse(result)

    def test_and_logic_all_false(self):
        """Test AND logic returns False when all conditions are False"""
        dispatcher = self._create_dispatcher(status='Draft', amount=30)
        rule = MockRule(
            conditions=[
                MockCondition('status', 'equals', 'Active'),
                MockCondition('amount', 'greater_than', '50', logic_operator='AND'),
            ],
            condition_logic='AND'
        )

        result, details = dispatcher._evaluate_conditions(rule)

        self.assertFalse(result)

    def test_and_logic_with_jinja(self):
        """Test AND logic combines field conditions with Jinja"""
        dispatcher = self._create_dispatcher(status='Active', amount=100)
        rule = MockRule(
            conditions=[MockCondition('status', 'equals', 'Active')],
            jinja_condition='{{ doc.amount > 50 }}',
            condition_logic='AND'
        )

        result, details = dispatcher._evaluate_conditions(rule)

        self.assertTrue(result)

    def test_and_logic_with_python(self):
        """Test AND logic combines field conditions with Python"""
        dispatcher = self._create_dispatcher(status='Active', amount=100)
        rule = MockRule(
            conditions=[MockCondition('status', 'equals', 'Active')],
            python_condition='doc.get("amount") > 50',
            condition_logic='AND'
        )

        result, details = dispatcher._evaluate_conditions(rule)

        self.assertTrue(result)

    # =========================================================================
    # OR LOGIC TESTS
    # =========================================================================

    def test_or_logic_all_true(self):
        """Test OR logic returns True when all conditions are True"""
        dispatcher = self._create_dispatcher(status='Active', amount=100)
        rule = MockRule(
            conditions=[
                MockCondition('status', 'equals', 'Active'),
                MockCondition('amount', 'greater_than', '50', logic_operator='OR'),
            ],
            condition_logic='OR'
        )

        result, details = dispatcher._evaluate_conditions(rule)

        self.assertTrue(result)

    def test_or_logic_one_true(self):
        """Test OR logic returns True when at least one condition is True"""
        dispatcher = self._create_dispatcher(status='Active', amount=30)
        rule = MockRule(
            conditions=[
                MockCondition('status', 'equals', 'Active'),
                MockCondition('amount', 'greater_than', '50', logic_operator='OR'),
            ],
            condition_logic='OR'
        )

        result, details = dispatcher._evaluate_conditions(rule)

        self.assertTrue(result)

    def test_or_logic_all_false(self):
        """Test OR logic returns False when all conditions are False"""
        dispatcher = self._create_dispatcher(status='Draft', amount=30)
        rule = MockRule(
            conditions=[
                MockCondition('status', 'equals', 'Active'),
                MockCondition('amount', 'greater_than', '50', logic_operator='OR'),
            ],
            condition_logic='OR'
        )

        # For OR with only field conditions
        # Note: The OR logic in dispatcher combines results differently
        # Each individual field condition evaluates separately
        result, details = dispatcher._evaluate_conditions(rule)

        # OR logic: at least one of field conditions OR jinja OR python must be true
        # Since no jinja/python and all field conditions are false, result should be false
        self.assertFalse(result)

    def test_or_logic_no_conditions(self):
        """Test OR logic with no conditions returns True"""
        dispatcher = self._create_dispatcher()
        rule = MockRule(
            conditions=[],
            jinja_condition=None,
            python_condition=None,
            condition_logic='OR'
        )

        result, details = dispatcher._evaluate_conditions(rule)

        # No conditions = always true
        self.assertTrue(result)

    # =========================================================================
    # CUSTOM LOGIC TESTS
    # =========================================================================

    def test_custom_logic_defaults_to_and(self):
        """Test Custom logic defaults to AND behavior"""
        dispatcher = self._create_dispatcher(status='Active', amount=100)
        rule = MockRule(
            conditions=[
                MockCondition('status', 'equals', 'Active'),
                MockCondition('amount', 'greater_than', '50', logic_operator='AND'),
            ],
            condition_logic='Custom'
        )

        result, details = dispatcher._evaluate_conditions(rule)

        self.assertTrue(result)

    # =========================================================================
    # NO CONDITIONS TESTS
    # =========================================================================

    def test_no_conditions_returns_true(self):
        """Test evaluation with no conditions returns True"""
        dispatcher = self._create_dispatcher()
        rule = MockRule(
            conditions=[],
            jinja_condition=None,
            python_condition=None,
            condition_logic='AND'
        )

        result, details = dispatcher._evaluate_conditions(rule)

        self.assertTrue(result)

    def test_only_jinja_condition(self):
        """Test evaluation with only Jinja condition"""
        dispatcher = self._create_dispatcher(amount=100)
        rule = MockRule(
            conditions=[],
            jinja_condition='{{ doc.amount > 50 }}',
            condition_logic='AND'
        )

        result, details = dispatcher._evaluate_conditions(rule)

        self.assertTrue(result)

    def test_only_python_condition(self):
        """Test evaluation with only Python condition"""
        dispatcher = self._create_dispatcher(amount=100)
        rule = MockRule(
            conditions=[],
            python_condition='doc.get("amount") > 50',
            condition_logic='AND'
        )

        result, details = dispatcher._evaluate_conditions(rule)

        self.assertTrue(result)


class TestECAFieldConditionLogic(FrappeTestCase):
    """Test cases for logic operators between field conditions"""

    def _create_dispatcher(self, doc=None, **doc_fields):
        """Helper to create ECA dispatcher with mock document"""
        if doc is None:
            doc = MockDocument(**doc_fields)
        return ECADispatcher(doc, 'after_save')

    def test_field_conditions_and_chain(self):
        """Test AND chain between field conditions"""
        dispatcher = self._create_dispatcher(status='Active', amount=100, priority='High')
        rule = MockRule(
            conditions=[
                MockCondition('status', 'equals', 'Active', logic_operator='AND'),
                MockCondition('amount', 'greater_than', '50', logic_operator='AND'),
                MockCondition('priority', 'equals', 'High', logic_operator='AND'),
            ],
            condition_logic='AND'
        )

        result, details = dispatcher._evaluate_conditions(rule)

        self.assertTrue(result)

    def test_field_conditions_or_chain(self):
        """Test OR chain between field conditions"""
        dispatcher = self._create_dispatcher(status='Draft', amount=100, priority='Low')
        rule = MockRule(
            conditions=[
                MockCondition('status', 'equals', 'Active', logic_operator='OR'),
                MockCondition('amount', 'greater_than', '50', logic_operator='OR'),
                MockCondition('priority', 'equals', 'High', logic_operator='OR'),
            ],
            condition_logic='AND'
        )

        # Even though one field condition is true (amount > 50),
        # the overall result depends on the field_conditions_result
        result, details = dispatcher._evaluate_conditions(rule)

        # At least one field condition is true
        self.assertTrue(result)

    def test_field_conditions_mixed_logic(self):
        """Test mixed AND/OR chain between field conditions"""
        dispatcher = self._create_dispatcher(status='Active', amount=30, priority='High')
        rule = MockRule(
            conditions=[
                MockCondition('status', 'equals', 'Active', logic_operator='AND'),  # True
                MockCondition('amount', 'greater_than', '50', logic_operator='OR'),  # False but OR
                MockCondition('priority', 'equals', 'High', logic_operator='AND'),  # True
            ],
            condition_logic='AND'
        )

        # (True AND False) OR True = True
        # Actually the logic is: result = (True) AND (False) -> False, then False OR True -> True
        result, details = dispatcher._evaluate_conditions(rule)

        self.assertTrue(result)


class TestECAConditionEdgeCases(FrappeTestCase):
    """Test cases for ECA condition edge cases and error handling"""

    def _create_dispatcher(self, doc=None, **doc_fields):
        """Helper to create ECA dispatcher with mock document"""
        if doc is None:
            doc = MockDocument(**doc_fields)
        return ECADispatcher(doc, 'after_save')

    def test_condition_with_none_field_value(self):
        """Test condition evaluation with None field value"""
        dispatcher = self._create_dispatcher(empty_field=None)
        condition = MockCondition('empty_field', 'equals', None)

        result = dispatcher._evaluate_single_condition(condition)

        self.assertTrue(result)

    def test_compare_equal_type_coercion(self):
        """Test _compare_equal handles type coercion"""
        dispatcher = self._create_dispatcher(count=100)

        # String "100" should equal number 100
        result = dispatcher._compare_equal(100, "100")

        self.assertTrue(result)

    def test_compare_equal_float_int(self):
        """Test _compare_equal handles float/int comparison"""
        dispatcher = self._create_dispatcher()

        result = dispatcher._compare_equal(100.0, 100)

        self.assertTrue(result)

    def test_condition_exception_handling(self):
        """Test condition evaluation handles exceptions gracefully"""
        dispatcher = self._create_dispatcher()

        # Create a condition that might cause an exception
        condition = MockCondition('status', 'greater_than', 'not_a_number')

        # Should not raise, should return False
        result = dispatcher._evaluate_single_condition(condition)

        self.assertFalse(result)

    def test_value_in_list_with_tuples(self):
        """Test _value_in_list handles tuple values"""
        dispatcher = self._create_dispatcher(status='Active')

        result = dispatcher._value_in_list('Active', ('Draft', 'Active', 'Completed'))

        self.assertTrue(result)

    def test_condition_details_structure(self):
        """Test that condition details have correct structure"""
        dispatcher = self._create_dispatcher(status='Active')
        rule = MockRule(
            conditions=[MockCondition('status', 'equals', 'Active')]
        )

        result, details = dispatcher._evaluate_conditions(rule)

        self.assertTrue(result)
        self.assertEqual(len(details), 1)

        detail = details[0]
        self.assertEqual(detail['type'], 'field')
        self.assertEqual(detail['field'], 'status')
        self.assertEqual(detail['operator'], 'equals')
        self.assertEqual(detail['expected'], 'Active')
        self.assertEqual(detail['actual'], 'Active')
        self.assertTrue(detail['passed'])

    def test_jinja_expression_truncation_in_log(self):
        """Test long Jinja expressions are truncated in details"""
        dispatcher = self._create_dispatcher()
        long_expression = '{{ ' + 'a' * 200 + ' }}'
        rule = MockRule(jinja_condition=long_expression)

        details = []
        dispatcher._evaluate_jinja_condition(rule, details)

        # Expression should be truncated to 100 chars in log
        self.assertTrue(len(details[0]['expression']) <= 100)

    def test_python_expression_truncation_in_log(self):
        """Test long Python expressions are truncated in details"""
        dispatcher = self._create_dispatcher()
        long_expression = 'x = ' + '"a"' * 50
        rule = MockRule(python_condition=long_expression)

        details = []
        dispatcher._evaluate_python_condition(rule, details)

        # Expression should be truncated to 100 chars in log
        self.assertTrue(len(details[0]['expression']) <= 100)

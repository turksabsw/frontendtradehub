# Copyright (c) 2026, TR TradeHub and contributors
# For license information, please see license.txt

"""
Unit tests for ECA Circular Trigger Prevention

Tests the ECA circular trigger prevention mechanism including:
- frappe.flags.in_eca_execution prevents infinite loops
- Flag is set correctly during ECA execution
- Flag is cleared after execution (even on error)
- Nested dispatcher calls are properly skipped
- The evaluate_rules() entry point also respects the flag
- Actions that modify documents don't trigger recursive ECA evaluation
"""

import json
import frappe
from frappe.tests.utils import FrappeTestCase
from unittest.mock import MagicMock, patch, PropertyMock

from tr_tradehub.eca.dispatcher import ECADispatcher, evaluate_rules


class MockAction:
    """Mock action object for testing"""

    def __init__(
        self,
        action_type='Send Email',
        is_active=True,
        execution_order=0,
        stop_on_error=False,
        async_execution=False,
        **kwargs
    ):
        self.action_type = action_type
        self.is_active = is_active
        self.execution_order = execution_order
        self.stop_on_error = stop_on_error
        self.async_execution = async_execution

        # Set additional properties from kwargs
        for key, value in kwargs.items():
            setattr(self, key, value)


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
        name='test_rule',
        rule_name='Test Rule',
        conditions=None,
        actions=None,
        jinja_condition=None,
        python_condition=None,
        condition_logic='AND',
        is_active=True,
        enable_logging=False,
        log_level='Info',
        log_condition_results=False,
        log_action_results=False
    ):
        self.name = name
        self.rule_name = rule_name
        self.conditions = conditions or []
        self.actions = actions or []
        self.jinja_condition = jinja_condition
        self.python_condition = python_condition
        self.condition_logic = condition_logic
        self.is_active = is_active
        self.enable_logging = enable_logging
        self.log_level = log_level
        self.log_condition_results = log_condition_results
        self.log_action_results = log_action_results

    def matches_filter(self, doc):
        """Mock filter matching - always returns True for testing"""
        return True

    def check_rate_limit(self, doc_name, user):
        """Mock rate limit check - always allows for testing"""
        return True, None

    def update_last_execution(self):
        """Mock update last execution"""
        pass


class MockDocument:
    """Mock Frappe document for testing"""

    def __init__(self, doctype='Test DocType', name='TEST-001', **fields):
        self.doctype = doctype
        self.name = name
        self._doc_before_save = {}

        # Set default fields
        self._fields = {
            'status': 'Draft',
            'amount': 100.0,
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


class TestECACircularTriggerPrevention(FrappeTestCase):
    """Test cases for ECA circular trigger prevention mechanism"""

    def setUp(self):
        """Reset flags before each test"""
        super().setUp()
        # Ensure flag is cleared before each test
        frappe.flags.in_eca_execution = False

    def tearDown(self):
        """Cleanup after each test"""
        super().tearDown()
        # Always clear the flag after tests
        frappe.flags.in_eca_execution = False

    # =========================================================================
    # BASIC FLAG BEHAVIOR TESTS
    # =========================================================================

    def test_flag_initially_false(self):
        """Test that in_eca_execution flag is initially False or not set"""
        # Flag should be False or not exist at start
        flag_value = getattr(frappe.flags, 'in_eca_execution', False)
        self.assertFalse(flag_value)

    def test_flag_set_during_dispatch(self):
        """Test that in_eca_execution flag is set during dispatch"""
        doc = MockDocument()
        dispatcher = ECADispatcher(doc, 'after_save')

        # Track if flag was set during execution
        flag_was_set = []

        # Mock _get_matching_rules to capture flag state
        original_get_matching_rules = dispatcher._get_matching_rules

        def mock_get_matching_rules():
            flag_was_set.append(frappe.flags.in_eca_execution)
            return []

        dispatcher._get_matching_rules = mock_get_matching_rules

        # Execute dispatch
        dispatcher.dispatch()

        # Flag should have been True during execution
        self.assertEqual(len(flag_was_set), 1)
        self.assertTrue(flag_was_set[0])

    def test_flag_cleared_after_dispatch(self):
        """Test that in_eca_execution flag is cleared after dispatch"""
        doc = MockDocument()
        dispatcher = ECADispatcher(doc, 'after_save')

        # Mock _get_matching_rules to return empty list
        dispatcher._get_matching_rules = lambda: []

        # Execute dispatch
        dispatcher.dispatch()

        # Flag should be cleared after execution
        self.assertFalse(frappe.flags.in_eca_execution)

    def test_flag_cleared_even_on_error(self):
        """Test that in_eca_execution flag is cleared even when error occurs"""
        doc = MockDocument()
        dispatcher = ECADispatcher(doc, 'after_save')

        # Mock _get_matching_rules to raise an error
        def raise_error():
            raise ValueError("Test error")

        dispatcher._get_matching_rules = raise_error

        # Execute dispatch - should not raise
        results = dispatcher.dispatch()

        # Flag should still be cleared after error
        self.assertFalse(frappe.flags.in_eca_execution)

    # =========================================================================
    # CIRCULAR TRIGGER PREVENTION TESTS
    # =========================================================================

    def test_dispatch_skipped_when_flag_set(self):
        """Test that dispatch is skipped when in_eca_execution flag is already set"""
        doc = MockDocument()
        dispatcher = ECADispatcher(doc, 'after_save')

        # Set the flag to simulate being in ECA execution
        frappe.flags.in_eca_execution = True

        # Track if _get_matching_rules was called
        get_rules_called = []

        original_get_matching_rules = dispatcher._get_matching_rules

        def mock_get_matching_rules():
            get_rules_called.append(True)
            return []

        dispatcher._get_matching_rules = mock_get_matching_rules

        # Execute dispatch
        results = dispatcher.dispatch()

        # Should return empty results without processing
        self.assertEqual(results, [])
        self.assertEqual(len(get_rules_called), 0)

    def test_nested_dispatch_prevented(self):
        """Test that nested dispatch calls are prevented"""
        doc = MockDocument(status='Active')

        # Create a mock rule with action that tries to trigger another dispatch
        nested_dispatch_attempts = []

        def action_that_triggers_dispatch(action, inner_doc):
            """Action handler that attempts to trigger nested dispatch"""
            # Try to dispatch again - this should be blocked
            nested_dispatcher = ECADispatcher(inner_doc, 'after_save')
            nested_results = nested_dispatcher.dispatch()
            nested_dispatch_attempts.append({
                'was_blocked': len(nested_results) == 0,
                'flag_was_set': frappe.flags.in_eca_execution
            })
            return {'success': True, 'message': 'Action executed'}

        rule = MockRule(
            conditions=[MockCondition('status', 'equals', 'Active')],
            actions=[MockAction(action_type='Custom Method')]
        )

        dispatcher = ECADispatcher(doc, 'after_save')

        # Mock methods
        dispatcher._get_matching_rules = lambda: [rule]
        dispatcher._get_legacy_action_handler = lambda t: action_that_triggers_dispatch

        # Execute dispatch
        with patch.object(dispatcher, '_log_execution'):
            results = dispatcher.dispatch()

        # Verify nested dispatch was blocked
        self.assertEqual(len(nested_dispatch_attempts), 1)
        self.assertTrue(nested_dispatch_attempts[0]['was_blocked'])
        self.assertTrue(nested_dispatch_attempts[0]['flag_was_set'])

    def test_recursive_rule_evaluation_prevented(self):
        """Test that recursive rule evaluation is prevented"""
        doc = MockDocument()

        # Counter to track how many times dispatch was called
        dispatch_count = []

        class CountingDispatcher(ECADispatcher):
            def dispatch(self):
                dispatch_count.append(1)
                # Call parent dispatch
                return super().dispatch()

        # First dispatch - should work
        dispatcher1 = CountingDispatcher(doc, 'after_save')
        dispatcher1._get_matching_rules = lambda: []
        dispatcher1.dispatch()

        # Set flag manually to simulate being in ECA
        frappe.flags.in_eca_execution = True

        # Second dispatch - should be blocked
        dispatcher2 = CountingDispatcher(doc, 'after_save')
        dispatcher2._get_matching_rules = lambda: []
        result2 = dispatcher2.dispatch()

        # First dispatch should have been tracked
        self.assertEqual(len(dispatch_count), 1)
        # Second dispatch should return empty (blocked)
        self.assertEqual(result2, [])

    # =========================================================================
    # EVALUATE_RULES ENTRY POINT TESTS
    # =========================================================================

    def test_evaluate_rules_skipped_when_flag_set(self):
        """Test that evaluate_rules entry point respects the flag"""
        doc = MockDocument()

        # Set the flag
        frappe.flags.in_eca_execution = True

        # Track if any database calls are made
        with patch('frappe.db.count') as mock_count:
            mock_count.return_value = 10  # Simulate rules exist

            # Call evaluate_rules
            evaluate_rules(doc, 'after_save')

            # Should not have checked for rules at all
            mock_count.assert_not_called()

    def test_evaluate_rules_proceeds_when_flag_not_set(self):
        """Test that evaluate_rules proceeds when flag is not set"""
        doc = MockDocument(doctype='PIM Product')

        with patch('frappe.db.count') as mock_count:
            mock_count.return_value = 0  # No rules exist

            # Call evaluate_rules
            evaluate_rules(doc, 'after_save')

            # Should have checked for rules
            mock_count.assert_called_once()

    # =========================================================================
    # SKIP DOCTYPES TESTS
    # =========================================================================

    def test_eca_rule_doctype_skipped(self):
        """Test that ECA Rule DocType is skipped to prevent loops"""
        doc = MockDocument(doctype='ECA Rule')

        with patch('frappe.db.count') as mock_count:
            evaluate_rules(doc, 'after_save')

            # Should not check for rules on ECA Rule DocType
            mock_count.assert_not_called()

    def test_eca_rule_log_doctype_skipped(self):
        """Test that ECA Rule Log DocType is skipped to prevent loops"""
        doc = MockDocument(doctype='ECA Rule Log')

        with patch('frappe.db.count') as mock_count:
            evaluate_rules(doc, 'after_save')

            # Should not check for rules on ECA Rule Log DocType
            mock_count.assert_not_called()

    def test_error_log_doctype_skipped(self):
        """Test that Error Log DocType is skipped"""
        doc = MockDocument(doctype='Error Log')

        with patch('frappe.db.count') as mock_count:
            evaluate_rules(doc, 'after_save')

            # Should not check for rules on Error Log DocType
            mock_count.assert_not_called()

    # =========================================================================
    # MULTIPLE CONCURRENT DISPATCHERS TESTS
    # =========================================================================

    def test_flag_shared_between_dispatchers(self):
        """Test that the flag is shared between dispatcher instances"""
        doc1 = MockDocument(name='DOC-001')
        doc2 = MockDocument(name='DOC-002')

        dispatcher1 = ECADispatcher(doc1, 'after_save')
        dispatcher2 = ECADispatcher(doc2, 'after_save')

        # Start first dispatcher
        flag_states = []

        def capture_flag_state():
            flag_states.append(frappe.flags.in_eca_execution)
            return []

        dispatcher1._get_matching_rules = capture_flag_state

        # Mock second dispatcher to try running inside first
        original_dispatch = dispatcher2.dispatch

        def try_nested_dispatch():
            flag_states.append(('nested_attempt', frappe.flags.in_eca_execution))
            return original_dispatch()

        dispatcher2._get_matching_rules = lambda: []

        # Execute first dispatcher
        dispatcher1.dispatch()

        # Verify flag was True during first dispatch
        self.assertTrue(flag_states[0])

    def test_flag_isolation_between_sequential_dispatches(self):
        """Test that sequential dispatches work correctly"""
        doc1 = MockDocument(name='DOC-001')
        doc2 = MockDocument(name='DOC-002')

        dispatcher1 = ECADispatcher(doc1, 'after_save')
        dispatcher2 = ECADispatcher(doc2, 'after_save')

        dispatcher1._get_matching_rules = lambda: []
        dispatcher2._get_matching_rules = lambda: []

        # First dispatch
        result1 = dispatcher1.dispatch()

        # Flag should be cleared
        self.assertFalse(frappe.flags.in_eca_execution)

        # Second dispatch should work
        result2 = dispatcher2.dispatch()

        # Both should complete successfully
        self.assertEqual(result1, [])
        self.assertEqual(result2, [])

    # =========================================================================
    # ACTION DOCUMENT MODIFICATION TESTS
    # =========================================================================

    def test_set_field_action_does_not_trigger_eca(self):
        """Test that Set Field action doesn't trigger recursive ECA"""
        doc = MockDocument(status='Active')

        # Track if nested dispatch is attempted
        nested_attempts = []

        rule = MockRule(
            conditions=[MockCondition('status', 'equals', 'Active')],
            actions=[MockAction(
                action_type='Set Field',
                target_field='description',
                target_value='Updated by ECA'
            )]
        )

        dispatcher = ECADispatcher(doc, 'after_save')

        # Mock the set field action to simulate document modification
        def mock_set_field_action(action, inner_doc):
            # Check if flag is set (it should be)
            nested_attempts.append({
                'flag_set': frappe.flags.in_eca_execution
            })
            return {'success': True, 'message': 'Field set'}

        dispatcher._get_matching_rules = lambda: [rule]
        dispatcher._get_legacy_action_handler = lambda t: mock_set_field_action if t == 'Set Field' else None

        with patch.object(dispatcher, '_log_execution'):
            results = dispatcher.dispatch()

        # Flag should have been set during action execution
        self.assertEqual(len(nested_attempts), 1)
        self.assertTrue(nested_attempts[0]['flag_set'])

    def test_create_document_action_does_not_trigger_eca(self):
        """Test that Create Document action doesn't trigger recursive ECA"""
        doc = MockDocument(status='Active')

        rule = MockRule(
            conditions=[MockCondition('status', 'equals', 'Active')],
            actions=[MockAction(
                action_type='Create Document',
                target_doctype='Test Child',
                document_values='{"title": "Test"}'
            )]
        )

        dispatcher = ECADispatcher(doc, 'after_save')

        # Track nested dispatch attempts
        nested_dispatch_blocked = []

        def mock_create_document_action(action, inner_doc):
            # Try to trigger another dispatch
            nested_dispatcher = ECADispatcher(inner_doc, 'after_insert')
            nested_result = nested_dispatcher.dispatch()

            nested_dispatch_blocked.append(len(nested_result) == 0)
            return {'success': True, 'message': 'Document created'}

        dispatcher._get_matching_rules = lambda: [rule]
        dispatcher._get_legacy_action_handler = lambda t: mock_create_document_action if t == 'Create Document' else None

        with patch.object(dispatcher, '_log_execution'):
            results = dispatcher.dispatch()

        # Nested dispatch should have been blocked
        self.assertEqual(len(nested_dispatch_blocked), 1)
        self.assertTrue(nested_dispatch_blocked[0])

    # =========================================================================
    # FLAG STATE PRESERVATION TESTS
    # =========================================================================

    def test_flag_restored_after_nested_attempt(self):
        """Test that flag remains set after nested dispatch attempt"""
        doc = MockDocument(status='Active')

        flag_states_during_execution = []

        rule = MockRule(
            conditions=[MockCondition('status', 'equals', 'Active')],
            actions=[MockAction(action_type='Custom Method')]
        )

        dispatcher = ECADispatcher(doc, 'after_save')

        def action_with_nested_attempt(action, inner_doc):
            # Capture flag before nested attempt
            flag_states_during_execution.append(('before_nested', frappe.flags.in_eca_execution))

            # Try nested dispatch
            nested_dispatcher = ECADispatcher(inner_doc, 'after_save')
            nested_dispatcher._get_matching_rules = lambda: []
            nested_dispatcher.dispatch()

            # Capture flag after nested attempt
            flag_states_during_execution.append(('after_nested', frappe.flags.in_eca_execution))

            return {'success': True}

        dispatcher._get_matching_rules = lambda: [rule]
        dispatcher._get_legacy_action_handler = lambda t: action_with_nested_attempt

        with patch.object(dispatcher, '_log_execution'):
            dispatcher.dispatch()

        # Flag should have been True both before and after nested attempt
        self.assertEqual(flag_states_during_execution[0], ('before_nested', True))
        self.assertEqual(flag_states_during_execution[1], ('after_nested', True))

    def test_flag_correctly_restored_on_exception_in_action(self):
        """Test that flag is correctly restored when action raises exception"""
        doc = MockDocument(status='Active')

        rule = MockRule(
            conditions=[MockCondition('status', 'equals', 'Active')],
            actions=[MockAction(action_type='Custom Method')]
        )

        dispatcher = ECADispatcher(doc, 'after_save')

        def action_that_raises(action, inner_doc):
            raise ValueError("Action failed")

        dispatcher._get_matching_rules = lambda: [rule]
        dispatcher._get_legacy_action_handler = lambda t: action_that_raises

        with patch.object(dispatcher, '_log_execution'):
            with patch('frappe.log_error'):
                results = dispatcher.dispatch()

        # Flag should be cleared after dispatch completes
        self.assertFalse(frappe.flags.in_eca_execution)


class TestECACircularTriggerEdgeCases(FrappeTestCase):
    """Test edge cases for ECA circular trigger prevention"""

    def setUp(self):
        """Reset flags before each test"""
        super().setUp()
        frappe.flags.in_eca_execution = False

    def tearDown(self):
        """Cleanup after each test"""
        super().tearDown()
        frappe.flags.in_eca_execution = False

    def test_deeply_nested_dispatch_attempts(self):
        """Test that deeply nested dispatch attempts are all blocked"""
        doc = MockDocument()

        nesting_depth = 0
        max_depth_reached = [0]

        def recursive_action(action, inner_doc):
            nonlocal nesting_depth
            nesting_depth += 1
            max_depth_reached[0] = max(max_depth_reached[0], nesting_depth)

            # Try recursive dispatch
            nested_dispatcher = ECADispatcher(inner_doc, 'after_save')
            nested_dispatcher._get_matching_rules = lambda: []
            nested_dispatcher.dispatch()

            nesting_depth -= 1
            return {'success': True}

        rule = MockRule(
            conditions=[],
            actions=[MockAction(action_type='Custom Method')]
        )

        dispatcher = ECADispatcher(doc, 'after_save')
        dispatcher._get_matching_rules = lambda: [rule]
        dispatcher._get_legacy_action_handler = lambda t: recursive_action

        with patch.object(dispatcher, '_log_execution'):
            dispatcher.dispatch()

        # Should only reach depth 1 (the initial call)
        self.assertEqual(max_depth_reached[0], 1)

    def test_flag_not_leaked_to_unrelated_code(self):
        """Test that flag doesn't affect unrelated code paths"""
        doc = MockDocument()

        unrelated_code_executed = []

        def unrelated_function():
            # This should not be blocked by ECA flag
            unrelated_code_executed.append(True)

        dispatcher = ECADispatcher(doc, 'after_save')

        def action_with_unrelated_call(action, inner_doc):
            unrelated_function()
            return {'success': True}

        rule = MockRule(
            conditions=[],
            actions=[MockAction(action_type='Custom Method')]
        )

        dispatcher._get_matching_rules = lambda: [rule]
        dispatcher._get_legacy_action_handler = lambda t: action_with_unrelated_call

        with patch.object(dispatcher, '_log_execution'):
            dispatcher.dispatch()

        # Unrelated function should have executed
        self.assertEqual(len(unrelated_code_executed), 1)

    def test_multiple_rules_single_dispatch(self):
        """Test that multiple rules in single dispatch work correctly"""
        doc = MockDocument(status='Active')

        rules_processed = []

        rule1 = MockRule(name='rule1', conditions=[])
        rule2 = MockRule(name='rule2', conditions=[])
        rule3 = MockRule(name='rule3', conditions=[])

        dispatcher = ECADispatcher(doc, 'after_save')
        dispatcher._get_matching_rules = lambda: [rule1, rule2, rule3]

        # Track which rules are processed
        original_process_rule = dispatcher._process_rule

        def mock_process_rule(rule):
            rules_processed.append(rule.name)
            return {
                'rule': rule.name,
                'status': 'Success',
                'condition_result': True,
                'actions_executed': 0
            }

        dispatcher._process_rule = mock_process_rule

        results = dispatcher.dispatch()

        # All three rules should have been processed
        self.assertEqual(len(rules_processed), 3)
        self.assertIn('rule1', rules_processed)
        self.assertIn('rule2', rules_processed)
        self.assertIn('rule3', rules_processed)

    def test_flag_behavior_with_async_actions(self):
        """Test flag behavior with async action execution"""
        doc = MockDocument(status='Active')

        # Simulate async action that would be queued
        action = MockAction(
            action_type='Send Email',
            async_execution=True,
            recipients='test@example.com'
        )

        rule = MockRule(
            conditions=[MockCondition('status', 'equals', 'Active')],
            actions=[action]
        )

        dispatcher = ECADispatcher(doc, 'after_save')
        dispatcher._get_matching_rules = lambda: [rule]

        # Mock the enqueue to track calls
        with patch('frappe.enqueue') as mock_enqueue:
            mock_enqueue.return_value = None

            with patch.object(dispatcher, '_log_execution'):
                results = dispatcher.dispatch()

            # Flag should be cleared after dispatch
            self.assertFalse(frappe.flags.in_eca_execution)

    def test_flag_cleared_after_rate_limit_skip(self):
        """Test flag is cleared after rule is skipped due to rate limit"""
        doc = MockDocument()

        rule = MockRule()

        # Override rate limit check to return False
        rule.check_rate_limit = lambda doc_name, user: (False, "Rate limited")

        dispatcher = ECADispatcher(doc, 'after_save')
        dispatcher._get_matching_rules = lambda: [rule]

        with patch.object(dispatcher, '_log_execution'):
            results = dispatcher.dispatch()

        # Flag should be cleared
        self.assertFalse(frappe.flags.in_eca_execution)

    def test_flag_cleared_after_condition_not_met(self):
        """Test flag is cleared after rule condition is not met"""
        doc = MockDocument(status='Draft')

        rule = MockRule(
            conditions=[MockCondition('status', 'equals', 'Active')]
        )

        dispatcher = ECADispatcher(doc, 'after_save')
        dispatcher._get_matching_rules = lambda: [rule]

        with patch.object(dispatcher, '_log_execution'):
            results = dispatcher.dispatch()

        # Flag should be cleared
        self.assertFalse(frappe.flags.in_eca_execution)

        # Should have one skipped result
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['status'], 'Skipped')


class TestECACircularTriggerWithRealScenarios(FrappeTestCase):
    """Test realistic scenarios for ECA circular trigger prevention"""

    def setUp(self):
        """Reset flags before each test"""
        super().setUp()
        frappe.flags.in_eca_execution = False

    def tearDown(self):
        """Cleanup after each test"""
        super().tearDown()
        frappe.flags.in_eca_execution = False

    def test_scenario_order_status_change_with_email(self):
        """
        Scenario: Order status changes trigger email notification.
        The email action should not trigger another ECA evaluation.
        """
        order = MockDocument(
            doctype='Sales Order',
            name='SO-001',
            status='Submitted'
        )
        order.set_previous_value = lambda f, v: setattr(order, '_doc_before_save', {f: v})
        order.set_previous_value('status', 'Draft')

        # Create rule that triggers on status change
        rule = MockRule(
            name='order_status_email',
            conditions=[MockCondition('status', 'changed_to', 'Submitted')],
            actions=[MockAction(
                action_type='Send Email',
                recipients='admin@example.com'
            )]
        )

        dispatcher = ECADispatcher(order, 'on_update')
        dispatch_called_during_action = []

        def mock_email_action(action, doc):
            # During email action, try to dispatch again
            dispatch_called_during_action.append(frappe.flags.in_eca_execution)
            return {'success': True, 'message': 'Email sent'}

        dispatcher._get_matching_rules = lambda: [rule]
        dispatcher._get_legacy_action_handler = lambda t: mock_email_action if t == 'Send Email' else None

        with patch.object(dispatcher, '_log_execution'):
            results = dispatcher.dispatch()

        # Action should have seen flag as True (preventing nested triggers)
        self.assertEqual(len(dispatch_called_during_action), 1)
        self.assertTrue(dispatch_called_during_action[0])

    def test_scenario_product_price_update_webhook(self):
        """
        Scenario: Product price update triggers webhook to external system.
        The webhook response handling should not cause infinite loops.
        """
        product = MockDocument(
            doctype='PIM Product',
            name='PROD-001',
            price=150.00
        )
        product._doc_before_save = {'price': 100.00}

        rule = MockRule(
            name='price_update_webhook',
            conditions=[MockCondition('price', 'changed')],
            actions=[MockAction(
                action_type='Webhook',
                webhook_url='https://api.example.com/price-update',
                webhook_method='POST'
            )]
        )

        dispatcher = ECADispatcher(product, 'after_save')
        webhook_executed = []

        def mock_webhook_action(action, doc):
            webhook_executed.append(True)
            # Simulate webhook that might try to update the document back
            # This should NOT trigger another ECA evaluation
            return {'success': True, 'message': 'Webhook sent'}

        dispatcher._get_matching_rules = lambda: [rule]
        dispatcher._get_legacy_action_handler = lambda t: mock_webhook_action if t == 'Webhook' else None

        with patch.object(dispatcher, '_log_execution'):
            results = dispatcher.dispatch()

        # Webhook should have been called exactly once
        self.assertEqual(len(webhook_executed), 1)

        # Flag should be cleared after completion
        self.assertFalse(frappe.flags.in_eca_execution)

    def test_scenario_cascading_document_updates(self):
        """
        Scenario: Parent document update triggers child document update.
        Child update should not trigger parent ECA evaluation again.
        """
        parent = MockDocument(
            doctype='Parent DocType',
            name='PARENT-001',
            status='Updated'
        )

        rule = MockRule(
            name='cascade_update',
            conditions=[MockCondition('status', 'equals', 'Updated')],
            actions=[MockAction(
                action_type='Update Document',
                target_doctype='Child DocType',
                document_values='{"name": "CHILD-001", "parent_status": "Updated"}'
            )]
        )

        dispatcher = ECADispatcher(parent, 'after_save')
        nested_dispatch_blocked = []

        def mock_update_action(action, doc):
            # Simulate the document update triggering another dispatch
            child = MockDocument(doctype='Child DocType', name='CHILD-001')
            nested_dispatcher = ECADispatcher(child, 'after_save')
            nested_dispatcher._get_matching_rules = lambda: []

            nested_result = nested_dispatcher.dispatch()
            nested_dispatch_blocked.append(len(nested_result) == 0)

            return {'success': True, 'message': 'Document updated'}

        dispatcher._get_matching_rules = lambda: [rule]
        dispatcher._get_legacy_action_handler = lambda t: mock_update_action if t == 'Update Document' else None

        with patch.object(dispatcher, '_log_execution'):
            results = dispatcher.dispatch()

        # Nested dispatch should have been blocked
        self.assertEqual(len(nested_dispatch_blocked), 1)
        self.assertTrue(nested_dispatch_blocked[0])

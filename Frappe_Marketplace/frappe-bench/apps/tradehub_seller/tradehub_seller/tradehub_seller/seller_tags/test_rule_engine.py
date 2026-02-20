# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

"""
Tests for Rule Engine

Tests AND/OR condition evaluation with various operators.
"""

import unittest
from tradehub_seller.tradehub_seller.seller_tags.rule_engine import (
    evaluate_condition,
    evaluate_group,
    evaluate_conditions,
    OPERATORS,
    RuleEngine
)


class TestConditionEvaluation(unittest.TestCase):
    """Test single condition evaluation."""

    def test_equals_operator(self):
        """Test == operator."""
        condition = {"field": "status", "operator": "==", "value": "Active"}
        metrics = {"status": "Active"}
        self.assertTrue(evaluate_condition(condition, metrics))

        metrics = {"status": "Inactive"}
        self.assertFalse(evaluate_condition(condition, metrics))

    def test_not_equals_operator(self):
        """Test != operator."""
        condition = {"field": "status", "operator": "!=", "value": "Inactive"}
        metrics = {"status": "Active"}
        self.assertTrue(evaluate_condition(condition, metrics))

        metrics = {"status": "Inactive"}
        self.assertFalse(evaluate_condition(condition, metrics))

    def test_greater_than_operator(self):
        """Test > operator."""
        condition = {"field": "total_orders", "operator": ">", "value": 100}
        metrics = {"total_orders": 150}
        self.assertTrue(evaluate_condition(condition, metrics))

        metrics = {"total_orders": 100}
        self.assertFalse(evaluate_condition(condition, metrics))

        metrics = {"total_orders": 50}
        self.assertFalse(evaluate_condition(condition, metrics))

    def test_greater_than_or_equal_operator(self):
        """Test >= operator."""
        condition = {"field": "avg_rating", "operator": ">=", "value": 4.5}
        metrics = {"avg_rating": 4.5}
        self.assertTrue(evaluate_condition(condition, metrics))

        metrics = {"avg_rating": 4.8}
        self.assertTrue(evaluate_condition(condition, metrics))

        metrics = {"avg_rating": 4.4}
        self.assertFalse(evaluate_condition(condition, metrics))

    def test_less_than_operator(self):
        """Test < operator."""
        condition = {"field": "cancellation_rate", "operator": "<", "value": 5}
        metrics = {"cancellation_rate": 3}
        self.assertTrue(evaluate_condition(condition, metrics))

        metrics = {"cancellation_rate": 5}
        self.assertFalse(evaluate_condition(condition, metrics))

    def test_less_than_or_equal_operator(self):
        """Test <= operator."""
        condition = {"field": "return_rate", "operator": "<=", "value": 10}
        metrics = {"return_rate": 10}
        self.assertTrue(evaluate_condition(condition, metrics))

        metrics = {"return_rate": 11}
        self.assertFalse(evaluate_condition(condition, metrics))

    def test_in_operator(self):
        """Test in operator."""
        condition = {"field": "status", "operator": "in", "value": ["Active", "Verified"]}
        metrics = {"status": "Active"}
        self.assertTrue(evaluate_condition(condition, metrics))

        metrics = {"status": "Pending"}
        self.assertFalse(evaluate_condition(condition, metrics))

    def test_not_in_operator(self):
        """Test not_in operator."""
        condition = {"field": "status", "operator": "not_in", "value": ["Suspended", "Banned"]}
        metrics = {"status": "Active"}
        self.assertTrue(evaluate_condition(condition, metrics))

        metrics = {"status": "Banned"}
        self.assertFalse(evaluate_condition(condition, metrics))

    def test_contains_operator(self):
        """Test contains operator."""
        condition = {"field": "name", "operator": "contains", "value": "Shop"}
        metrics = {"name": "Best Shop Ever"}
        self.assertTrue(evaluate_condition(condition, metrics))

        metrics = {"name": "Store Name"}
        self.assertFalse(evaluate_condition(condition, metrics))

    def test_is_set_operator(self):
        """Test is_set operator."""
        condition = {"field": "email", "operator": "is_set", "value": None}
        metrics = {"email": "test@example.com"}
        self.assertTrue(evaluate_condition(condition, metrics))

        metrics = {"email": None}
        self.assertFalse(evaluate_condition(condition, metrics))

        metrics = {"email": ""}
        self.assertFalse(evaluate_condition(condition, metrics))

    def test_is_not_set_operator(self):
        """Test is_not_set operator."""
        condition = {"field": "phone", "operator": "is_not_set", "value": None}
        metrics = {"phone": None}
        self.assertTrue(evaluate_condition(condition, metrics))

        metrics = {"phone": "1234567890"}
        self.assertFalse(evaluate_condition(condition, metrics))

    def test_none_value_handling(self):
        """Test handling of None values in metrics."""
        condition = {"field": "missing_field", "operator": ">=", "value": 10}
        metrics = {"other_field": 100}
        self.assertFalse(evaluate_condition(condition, metrics))


class TestGroupEvaluation(unittest.TestCase):
    """Test group evaluation with AND/OR logic."""

    def test_and_group_all_true(self):
        """Test AND group with all conditions true."""
        group = {
            "group_logic": "AND",
            "conditions": [
                {"field": "total_orders", "operator": ">=", "value": 100},
                {"field": "avg_rating", "operator": ">=", "value": 4.5}
            ]
        }
        metrics = {"total_orders": 150, "avg_rating": 4.8}
        self.assertTrue(evaluate_group(group, metrics))

    def test_and_group_one_false(self):
        """Test AND group with one condition false."""
        group = {
            "group_logic": "AND",
            "conditions": [
                {"field": "total_orders", "operator": ">=", "value": 100},
                {"field": "avg_rating", "operator": ">=", "value": 4.5}
            ]
        }
        metrics = {"total_orders": 150, "avg_rating": 4.0}
        self.assertFalse(evaluate_group(group, metrics))

    def test_or_group_one_true(self):
        """Test OR group with one condition true."""
        group = {
            "group_logic": "OR",
            "conditions": [
                {"field": "verification_status", "operator": "==", "value": "Verified"},
                {"field": "premium_seller", "operator": "==", "value": 1}
            ]
        }
        metrics = {"verification_status": "Pending", "premium_seller": 1}
        self.assertTrue(evaluate_group(group, metrics))

    def test_or_group_all_false(self):
        """Test OR group with all conditions false."""
        group = {
            "group_logic": "OR",
            "conditions": [
                {"field": "verification_status", "operator": "==", "value": "Verified"},
                {"field": "premium_seller", "operator": "==", "value": 1}
            ]
        }
        metrics = {"verification_status": "Pending", "premium_seller": 0}
        self.assertFalse(evaluate_group(group, metrics))

    def test_empty_group(self):
        """Test empty group returns True."""
        group = {"group_logic": "AND", "conditions": []}
        metrics = {}
        self.assertTrue(evaluate_group(group, metrics))


class TestRuleEvaluation(unittest.TestCase):
    """Test full rule evaluation with nested groups."""

    def test_and_rule_all_groups_pass(self):
        """Test AND rule with all groups passing."""
        rule = {
            "logic": "AND",
            "groups": [
                {
                    "group_logic": "AND",
                    "conditions": [
                        {"field": "total_orders", "operator": ">=", "value": 100}
                    ]
                },
                {
                    "group_logic": "OR",
                    "conditions": [
                        {"field": "verification_status", "operator": "==", "value": "Verified"},
                        {"field": "active_days", "operator": ">=", "value": 180}
                    ]
                }
            ]
        }
        metrics = {
            "total_orders": 150,
            "verification_status": "Pending",
            "active_days": 200
        }
        self.assertTrue(evaluate_conditions(rule, metrics))

    def test_and_rule_one_group_fails(self):
        """Test AND rule with one group failing."""
        rule = {
            "logic": "AND",
            "groups": [
                {
                    "group_logic": "AND",
                    "conditions": [
                        {"field": "total_orders", "operator": ">=", "value": 100}
                    ]
                },
                {
                    "group_logic": "OR",
                    "conditions": [
                        {"field": "verification_status", "operator": "==", "value": "Verified"},
                        {"field": "active_days", "operator": ">=", "value": 180}
                    ]
                }
            ]
        }
        metrics = {
            "total_orders": 50,  # This fails
            "verification_status": "Verified",
            "active_days": 200
        }
        self.assertFalse(evaluate_conditions(rule, metrics))

    def test_or_rule_one_group_passes(self):
        """Test OR rule with one group passing."""
        rule = {
            "logic": "OR",
            "groups": [
                {
                    "group_logic": "AND",
                    "conditions": [
                        {"field": "total_orders", "operator": ">=", "value": 1000}
                    ]
                },
                {
                    "group_logic": "AND",
                    "conditions": [
                        {"field": "premium_seller", "operator": "==", "value": 1}
                    ]
                }
            ]
        }
        metrics = {"total_orders": 50, "premium_seller": 1}
        self.assertTrue(evaluate_conditions(rule, metrics))

    def test_complex_nested_rule(self):
        """Test complex rule with multiple groups and conditions."""
        rule = {
            "logic": "AND",
            "groups": [
                {
                    "group_logic": "AND",
                    "conditions": [
                        {"field": "total_orders", "operator": ">=", "value": 50},
                        {"field": "avg_rating", "operator": ">=", "value": 4.5},
                        {"field": "cancellation_rate", "operator": "<=", "value": 5}
                    ]
                },
                {
                    "group_logic": "OR",
                    "conditions": [
                        {"field": "verification_status", "operator": "==", "value": "Verified"},
                        {"field": "active_days", "operator": ">=", "value": 180}
                    ]
                }
            ]
        }
        # All conditions pass
        metrics = {
            "total_orders": 100,
            "avg_rating": 4.8,
            "cancellation_rate": 2,
            "verification_status": "Verified",
            "active_days": 90
        }
        self.assertTrue(evaluate_conditions(rule, metrics))

        # One condition in first group fails
        metrics["avg_rating"] = 4.0
        self.assertFalse(evaluate_conditions(rule, metrics))

    def test_empty_rule(self):
        """Test empty rule returns True."""
        rule = {"logic": "AND", "groups": []}
        metrics = {}
        self.assertTrue(evaluate_conditions(rule, metrics))


class TestRuleEngine(unittest.TestCase):
    """Test RuleEngine class."""

    def setUp(self):
        self.engine = RuleEngine()

    def test_clear_cache(self):
        """Test cache clearing."""
        self.engine.evaluation_cache["test"] = True
        self.engine.clear_cache()
        self.assertEqual(self.engine.evaluation_cache, {})


if __name__ == "__main__":
    unittest.main()

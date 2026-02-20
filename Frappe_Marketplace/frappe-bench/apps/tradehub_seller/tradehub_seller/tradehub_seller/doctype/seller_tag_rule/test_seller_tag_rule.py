# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

"""
Tests for Seller Tag Rule DocType
"""

import frappe
from frappe.tests.utils import FrappeTestCase
import json


class TestSellerTagRule(FrappeTestCase):
    """Test cases for Seller Tag Rule DocType."""

    @classmethod
    def setUpClass(cls):
        """Set up test fixtures."""
        super().setUpClass()
        # Create test tag
        if not frappe.db.exists("Seller Tag", "TEST_RULE_TAG"):
            frappe.get_doc({
                "doctype": "Seller Tag",
                "tag_name": "Test Rule Tag",
                "tag_code": "TEST_RULE_TAG",
                "status": "Active",
                "tag_type": "Achievement"
            }).insert()

    def tearDown(self):
        """Clean up test data."""
        for doc in frappe.get_all("Seller Tag Rule", filters={"rule_name": ["like", "Test%"]}):
            try:
                frappe.delete_doc("Seller Tag Rule", doc.name, force=True)
            except Exception:
                pass

    def test_rule_creation(self):
        """Test basic rule creation."""
        rule_json = {
            "logic": "AND",
            "groups": [
                {
                    "group_logic": "AND",
                    "conditions": [
                        {"field": "total_orders", "operator": ">=", "value": 100}
                    ]
                }
            ]
        }

        doc = frappe.get_doc({
            "doctype": "Seller Tag Rule",
            "rule_name": "Test Rule",
            "target_tag": "TEST_RULE_TAG",
            "enabled": 1,
            "rule_json": json.dumps(rule_json)
        })
        doc.insert()

        self.assertEqual(doc.enabled, 1)
        self.assertEqual(doc.target_tag, "TEST_RULE_TAG")

    def test_invalid_json(self):
        """Test invalid JSON is rejected."""
        doc = frappe.get_doc({
            "doctype": "Seller Tag Rule",
            "rule_name": "Test Invalid JSON",
            "target_tag": "TEST_RULE_TAG",
            "enabled": 1,
            "rule_json": "{ invalid json }"
        })

        self.assertRaises(frappe.exceptions.ValidationError, doc.insert)

    def test_invalid_logic(self):
        """Test invalid logic value is rejected."""
        rule_json = {
            "logic": "INVALID",  # Should be AND or OR
            "groups": []
        }

        doc = frappe.get_doc({
            "doctype": "Seller Tag Rule",
            "rule_name": "Test Invalid Logic",
            "target_tag": "TEST_RULE_TAG",
            "enabled": 1,
            "rule_json": json.dumps(rule_json)
        })

        self.assertRaises(frappe.exceptions.ValidationError, doc.insert)

    def test_invalid_operator(self):
        """Test invalid operator is rejected."""
        rule_json = {
            "logic": "AND",
            "groups": [
                {
                    "group_logic": "AND",
                    "conditions": [
                        {"field": "total_orders", "operator": "INVALID", "value": 100}
                    ]
                }
            ]
        }

        doc = frappe.get_doc({
            "doctype": "Seller Tag Rule",
            "rule_name": "Test Invalid Operator",
            "target_tag": "TEST_RULE_TAG",
            "enabled": 1,
            "rule_json": json.dumps(rule_json)
        })

        self.assertRaises(frappe.exceptions.ValidationError, doc.insert)

    def test_missing_field(self):
        """Test missing field in condition is rejected."""
        rule_json = {
            "logic": "AND",
            "groups": [
                {
                    "group_logic": "AND",
                    "conditions": [
                        {"operator": ">=", "value": 100}  # Missing field
                    ]
                }
            ]
        }

        doc = frappe.get_doc({
            "doctype": "Seller Tag Rule",
            "rule_name": "Test Missing Field",
            "target_tag": "TEST_RULE_TAG",
            "enabled": 1,
            "rule_json": json.dumps(rule_json)
        })

        self.assertRaises(frappe.exceptions.ValidationError, doc.insert)

    def test_complex_rule_validation(self):
        """Test complex rule with multiple groups validates successfully."""
        rule_json = {
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

        doc = frappe.get_doc({
            "doctype": "Seller Tag Rule",
            "rule_name": "Test Complex Rule",
            "target_tag": "TEST_RULE_TAG",
            "enabled": 1,
            "rule_json": json.dumps(rule_json)
        })
        doc.insert()

        # Verify it was saved correctly
        saved_rule = json.loads(doc.rule_json)
        self.assertEqual(saved_rule["logic"], "AND")
        self.assertEqual(len(saved_rule["groups"]), 2)

    def test_is_set_operator_no_value_required(self):
        """Test is_set operator doesn't require value."""
        rule_json = {
            "logic": "AND",
            "groups": [
                {
                    "group_logic": "AND",
                    "conditions": [
                        {"field": "email", "operator": "is_set"}
                    ]
                }
            ]
        }

        doc = frappe.get_doc({
            "doctype": "Seller Tag Rule",
            "rule_name": "Test Is Set",
            "target_tag": "TEST_RULE_TAG",
            "enabled": 1,
            "rule_json": json.dumps(rule_json)
        })
        doc.insert()

        self.assertIsNotNone(doc.name)

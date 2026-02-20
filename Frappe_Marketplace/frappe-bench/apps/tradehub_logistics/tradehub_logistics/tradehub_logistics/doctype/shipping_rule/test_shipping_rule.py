# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

import frappe
import unittest
from frappe.utils import flt, cint, nowdate, add_days


class TestShippingRule(unittest.TestCase):
    """Test cases for Shipping Rule DocType."""

    def setUp(self):
        """Set up test fixtures."""
        # Clean up any existing test data
        for rule in frappe.get_all(
            "Shipping Rule",
            filters={"rule_name": ["like", "Test%"]}
        ):
            frappe.delete_doc("Shipping Rule", rule.name, force=True)

    def tearDown(self):
        """Clean up test data."""
        for rule in frappe.get_all(
            "Shipping Rule",
            filters={"rule_name": ["like", "Test%"]}
        ):
            frappe.delete_doc("Shipping Rule", rule.name, force=True)

    def test_create_fixed_rate_rule(self):
        """Test creating a fixed rate shipping rule."""
        rule = frappe.get_doc({
            "doctype": "Shipping Rule",
            "rule_name": "Test Fixed Rate",
            "rule_type": "Flat Rate",
            "calculation_method": "Fixed",
            "base_rate": 25.00,
            "currency": "TRY",
            "is_active": 1
        })
        rule.insert()

        self.assertEqual(rule.rule_name, "Test Fixed Rate")
        self.assertEqual(rule.calculation_method, "Fixed")
        self.assertEqual(flt(rule.base_rate), 25.00)
        self.assertTrue(rule.is_active)

    def test_create_weight_based_rule(self):
        """Test creating a weight-based shipping rule."""
        rule = frappe.get_doc({
            "doctype": "Shipping Rule",
            "rule_name": "Test Weight Based",
            "rule_type": "Weight Based",
            "calculation_method": "Weight Based",
            "base_rate": 10.00,
            "per_kg_rate": 5.00,
            "currency": "TRY",
            "is_active": 1
        })
        rule.insert()

        self.assertEqual(rule.calculation_method, "Weight Based")
        self.assertEqual(flt(rule.per_kg_rate), 5.00)

    def test_calculate_fixed_shipping(self):
        """Test fixed rate shipping calculation."""
        rule = frappe.get_doc({
            "doctype": "Shipping Rule",
            "rule_name": "Test Calc Fixed",
            "rule_type": "Flat Rate",
            "calculation_method": "Fixed",
            "base_rate": 20.00,
            "currency": "TRY",
            "is_active": 1
        })
        rule.insert()

        order_data = {
            "order_amount": 100,
            "total_weight": 2,
            "item_count": 3,
            "destination": {
                "country": "Turkey",
                "city": "Istanbul"
            },
            "categories": []
        }

        result = rule.calculate_shipping(order_data)

        self.assertIsNotNone(result)
        self.assertEqual(result["shipping_amount"], 20.00)
        self.assertEqual(result["rule_name"], "Test Calc Fixed")

    def test_calculate_weight_based_shipping(self):
        """Test weight-based shipping calculation."""
        rule = frappe.get_doc({
            "doctype": "Shipping Rule",
            "rule_name": "Test Calc Weight",
            "rule_type": "Weight Based",
            "calculation_method": "Weight Based",
            "base_rate": 10.00,
            "per_kg_rate": 5.00,
            "currency": "TRY",
            "is_active": 1,
            "tax_rate": 0  # No tax for simplicity
        })
        rule.insert()

        order_data = {
            "order_amount": 100,
            "total_weight": 3,  # 3 kg
            "item_count": 1,
            "destination": {
                "country": "Turkey",
                "city": "Ankara"
            },
            "categories": []
        }

        result = rule.calculate_shipping(order_data)

        # Base (10) + Weight (3 * 5) = 25
        self.assertIsNotNone(result)
        self.assertEqual(result["breakdown"]["base_rate"], 25.00)

    def test_free_shipping_threshold(self):
        """Test free shipping threshold."""
        rule = frappe.get_doc({
            "doctype": "Shipping Rule",
            "rule_name": "Test Free Shipping",
            "rule_type": "Standard",
            "calculation_method": "Fixed",
            "base_rate": 15.00,
            "currency": "TRY",
            "is_active": 1,
            "free_shipping_enabled": 1,
            "free_shipping_threshold": 100.00
        })
        rule.insert()

        # Order above threshold - should be free
        order_data = {
            "order_amount": 150,
            "total_weight": 1,
            "item_count": 1,
            "destination": {
                "country": "Turkey",
                "city": "Istanbul"
            },
            "categories": []
        }

        result = rule.calculate_shipping(order_data)
        self.assertTrue(result["is_free_shipping"])
        self.assertEqual(result["shipping_amount"], 0)

        # Order below threshold - should have shipping cost
        order_data["order_amount"] = 50
        result = rule.calculate_shipping(order_data)
        self.assertFalse(result["is_free_shipping"])
        self.assertGreater(result["shipping_amount"], 0)

    def test_zone_applicability(self):
        """Test zone-based shipping rule."""
        rule = frappe.get_doc({
            "doctype": "Shipping Rule",
            "rule_name": "Test Zone Rule",
            "rule_type": "Standard",
            "calculation_method": "Fixed",
            "base_rate": 20.00,
            "currency": "TRY",
            "is_active": 1,
            "zones": [
                {
                    "country": "Turkey",
                    "city": "Istanbul"
                }
            ]
        })
        rule.insert()

        # Istanbul - should be applicable
        self.assertTrue(rule.is_zone_applicable({
            "country": "Turkey",
            "city": "Istanbul"
        }))

        # Ankara - should not be applicable
        self.assertFalse(rule.is_zone_applicable({
            "country": "Turkey",
            "city": "Ankara"
        }))

    def test_postal_code_range(self):
        """Test postal code range filtering."""
        rule = frappe.get_doc({
            "doctype": "Shipping Rule",
            "rule_name": "Test Postal Range",
            "rule_type": "Standard",
            "calculation_method": "Fixed",
            "base_rate": 25.00,
            "currency": "TRY",
            "is_active": 1,
            "zones": [
                {
                    "country": "Turkey",
                    "postal_code_from": "34000",
                    "postal_code_to": "34999"
                }
            ]
        })
        rule.insert()

        # Within range
        self.assertTrue(rule.is_zone_applicable({
            "country": "Turkey",
            "postal_code": "34500"
        }))

        # Outside range
        self.assertFalse(rule.is_zone_applicable({
            "country": "Turkey",
            "postal_code": "06000"
        }))

    def test_category_restrictions(self):
        """Test category-based rule restrictions."""
        rule = frappe.get_doc({
            "doctype": "Shipping Rule",
            "rule_name": "Test Category Rule",
            "rule_type": "Standard",
            "calculation_method": "Fixed",
            "base_rate": 30.00,
            "currency": "TRY",
            "is_active": 1,
            "apply_to_all_categories": 0,
            "allowed_categories": "Electronics, Computers"
        })
        rule.insert()

        # Allowed category
        self.assertTrue(rule.is_category_applicable(["Electronics"]))

        # Not allowed category
        self.assertFalse(rule.is_category_applicable(["Furniture"]))

    def test_order_amount_conditions(self):
        """Test order amount conditions."""
        rule = frappe.get_doc({
            "doctype": "Shipping Rule",
            "rule_name": "Test Amount Conditions",
            "rule_type": "Standard",
            "calculation_method": "Fixed",
            "base_rate": 15.00,
            "currency": "TRY",
            "is_active": 1,
            "min_order_amount": 50,
            "max_order_amount": 500
        })
        rule.insert()

        # Within range
        self.assertTrue(rule.is_valid_for_order({
            "order_amount": 100,
            "categories": []
        }))

        # Below minimum
        self.assertFalse(rule.is_valid_for_order({
            "order_amount": 30,
            "categories": []
        }))

        # Above maximum
        self.assertFalse(rule.is_valid_for_order({
            "order_amount": 600,
            "categories": []
        }))

    def test_express_delivery(self):
        """Test express delivery surcharge."""
        rule = frappe.get_doc({
            "doctype": "Shipping Rule",
            "rule_name": "Test Express",
            "rule_type": "Standard",
            "calculation_method": "Fixed",
            "base_rate": 20.00,
            "currency": "TRY",
            "is_active": 1,
            "tax_rate": 0,
            "express_available": 1,
            "express_surcharge": 15.00,
            "express_days": 1,
            "estimated_days_min": 3,
            "estimated_days_max": 5
        })
        rule.insert()

        order_data = {
            "order_amount": 100,
            "total_weight": 1,
            "item_count": 1,
            "destination": {
                "country": "Turkey",
                "city": "Istanbul"
            },
            "categories": [],
            "express": False
        }

        # Standard delivery
        result = rule.calculate_shipping(order_data)
        self.assertEqual(result["shipping_amount"], 20.00)
        self.assertEqual(result["estimated_days_min"], 3)

        # Express delivery
        order_data["express"] = True
        result = rule.calculate_shipping(order_data)
        self.assertEqual(result["shipping_amount"], 35.00)  # 20 + 15
        self.assertEqual(result["estimated_days_min"], 1)

    def test_validity_period(self):
        """Test rule validity period."""
        rule = frappe.get_doc({
            "doctype": "Shipping Rule",
            "rule_name": "Test Validity",
            "rule_type": "Standard",
            "calculation_method": "Fixed",
            "base_rate": 20.00,
            "currency": "TRY",
            "is_active": 1,
            "valid_from": add_days(nowdate(), -5),
            "valid_to": add_days(nowdate(), 5)
        })
        rule.insert()

        # Should be valid
        self.assertTrue(rule.is_valid_for_order({
            "order_amount": 100,
            "categories": []
        }))

        # Update to expired
        rule.valid_to = add_days(nowdate(), -1)
        rule.save()

        self.assertFalse(rule.is_valid_for_order({
            "order_amount": 100,
            "categories": []
        }))

    def test_tiered_pricing(self):
        """Test tiered pricing calculation."""
        rule = frappe.get_doc({
            "doctype": "Shipping Rule",
            "rule_name": "Test Tiered",
            "rule_type": "Weight Based",
            "calculation_method": "Weight Tiered",
            "currency": "TRY",
            "is_active": 1,
            "tax_rate": 0,
            "rate_tiers": [
                {
                    "threshold_from": 0,
                    "threshold_to": 5,
                    "rate": 15,
                    "rate_type": "Fixed"
                },
                {
                    "threshold_from": 5,
                    "threshold_to": 10,
                    "rate": 25,
                    "rate_type": "Fixed"
                },
                {
                    "threshold_from": 10,
                    "threshold_to": 0,  # 0 = unlimited
                    "rate": 35,
                    "rate_type": "Fixed"
                }
            ]
        })
        rule.insert()

        # First tier (0-5 kg)
        self.assertEqual(rule.get_tiered_rate(3), 15)

        # Second tier (5-10 kg)
        self.assertEqual(rule.get_tiered_rate(7), 25)

        # Third tier (10+ kg)
        self.assertEqual(rule.get_tiered_rate(15), 35)


if __name__ == "__main__":
    unittest.main()

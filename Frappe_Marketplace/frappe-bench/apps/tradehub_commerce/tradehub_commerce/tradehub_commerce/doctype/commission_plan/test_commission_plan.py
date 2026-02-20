# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

import frappe
import unittest
from frappe.utils import nowdate, add_months, add_days
from tradehub_commerce.tradehub_commerce.doctype.commission_plan.commission_plan import (
    CommissionPlan,
    get_commission_plan,
    get_default_commission_plan,
    calculate_commission,
    get_available_plans,
    compare_plans
)


class TestCommissionPlan(unittest.TestCase):
    """Test cases for Commission Plan DocType."""

    def setUp(self):
        """Set up test fixtures."""
        # Clean up any existing test data
        self.cleanup_test_data()

    def tearDown(self):
        """Clean up after tests."""
        self.cleanup_test_data()

    def cleanup_test_data(self):
        """Remove test commission plans."""
        test_plans = frappe.get_all(
            "Commission Plan",
            filters={"plan_name": ["like", "Test%"]},
            pluck="name"
        )
        for plan in test_plans:
            frappe.delete_doc("Commission Plan", plan, force=True)

    def create_test_plan(self, **kwargs):
        """Helper to create a test commission plan."""
        default_data = {
            "doctype": "Commission Plan",
            "plan_name": "Test Standard Plan",
            "plan_type": "Standard",
            "status": "Active",
            "base_commission_rate": 10,
            "effective_from": nowdate(),
            "commission_calculation_type": "Percentage"
        }
        default_data.update(kwargs)
        plan = frappe.get_doc(default_data)
        plan.insert()
        return plan

    # Basic CRUD Tests
    def test_commission_plan_creation(self):
        """Test basic commission plan creation."""
        plan = self.create_test_plan()

        self.assertIsNotNone(plan.name)
        self.assertEqual(plan.plan_name, "Test Standard Plan")
        self.assertEqual(plan.base_commission_rate, 10)
        self.assertEqual(plan.status, "Active")
        self.assertIsNotNone(plan.plan_code)

    def test_plan_code_auto_generation(self):
        """Test that plan code is auto-generated if not provided."""
        plan = self.create_test_plan()
        self.assertIsNotNone(plan.plan_code)
        self.assertTrue(plan.plan_code.startswith("STANDARD_"))

    def test_plan_code_uniqueness(self):
        """Test that plan codes must be unique."""
        plan1 = self.create_test_plan(plan_name="Test Plan 1")

        with self.assertRaises(frappe.exceptions.UniqueValidationError):
            frappe.get_doc({
                "doctype": "Commission Plan",
                "plan_name": "Test Plan 2",
                "plan_code": plan1.plan_code,  # Duplicate code
                "plan_type": "Standard",
                "status": "Active",
                "base_commission_rate": 10,
                "effective_from": nowdate()
            }).insert()

    # Commission Rate Validation Tests
    def test_commission_rate_validation(self):
        """Test commission rate boundary validation."""
        # Invalid negative rate
        with self.assertRaises(frappe.exceptions.ValidationError):
            self.create_test_plan(base_commission_rate=-5)

        # Invalid rate > 100
        with self.assertRaises(frappe.exceptions.ValidationError):
            self.create_test_plan(base_commission_rate=150)

    def test_min_max_commission_validation(self):
        """Test minimum/maximum commission validation."""
        # Min > Max should fail
        with self.assertRaises(frappe.exceptions.ValidationError):
            self.create_test_plan(
                plan_name="Test Invalid MinMax",
                minimum_commission=100,
                maximum_commission=50
            )

    # Commission Calculation Tests
    def test_percentage_commission_calculation(self):
        """Test basic percentage commission calculation."""
        plan = self.create_test_plan(
            plan_name="Test Percentage Plan",
            base_commission_rate=10,
            commission_calculation_type="Percentage"
        )

        result = plan.calculate_commission(order_value=1000)

        self.assertEqual(result["commission_amount"], 100)  # 10% of 1000
        self.assertEqual(result["seller_amount"], 900)  # 1000 - 100
        self.assertEqual(result["effective_rate"], 10)

    def test_fixed_commission_calculation(self):
        """Test fixed commission calculation."""
        plan = self.create_test_plan(
            plan_name="Test Fixed Plan",
            base_commission_rate=0,
            fixed_commission_amount=50,
            commission_calculation_type="Fixed"
        )

        result = plan.calculate_commission(order_value=1000)

        self.assertEqual(result["commission_amount"], 50)
        self.assertEqual(result["seller_amount"], 950)

    def test_percentage_plus_fixed_calculation(self):
        """Test percentage + fixed commission calculation."""
        plan = self.create_test_plan(
            plan_name="Test Combo Plan",
            base_commission_rate=10,
            fixed_commission_amount=5,
            commission_calculation_type="Percentage + Fixed"
        )

        result = plan.calculate_commission(order_value=1000)

        # 10% of 1000 = 100, plus 5 fixed = 105
        self.assertEqual(result["commission_amount"], 105)
        self.assertEqual(result["seller_amount"], 895)

    def test_minimum_commission_applied(self):
        """Test that minimum commission is applied when calculated amount is lower."""
        plan = self.create_test_plan(
            plan_name="Test Min Commission",
            base_commission_rate=5,
            minimum_commission=50
        )

        # 5% of 100 = 5, but minimum is 50
        result = plan.calculate_commission(order_value=100)

        self.assertEqual(result["commission_amount"], 50)
        self.assertTrue(result["breakdown"].get("applied_minimum"))

    def test_maximum_commission_applied(self):
        """Test that maximum commission is applied when calculated amount is higher."""
        plan = self.create_test_plan(
            plan_name="Test Max Commission",
            base_commission_rate=20,
            maximum_commission=100
        )

        # 20% of 1000 = 200, but maximum is 100
        result = plan.calculate_commission(order_value=1000)

        self.assertEqual(result["commission_amount"], 100)
        self.assertTrue(result["breakdown"].get("applied_maximum"))

    def test_shipping_deduction_from_commission_base(self):
        """Test shipping cost deduction from commission base."""
        plan = self.create_test_plan(
            plan_name="Test Shipping Deduction",
            base_commission_rate=10,
            deduct_shipping_from_commission=1
        )

        # Order 1000 with 100 shipping, commission base = 900
        result = plan.calculate_commission(order_value=1000, shipping_cost=100)

        self.assertEqual(result["commission_amount"], 90)  # 10% of 900
        self.assertEqual(result["breakdown"]["shipping_deducted"], 100)
        self.assertEqual(result["breakdown"]["commission_base"], 900)

    # Date Validation Tests
    def test_effective_date_validation(self):
        """Test effective date range validation."""
        # From date after Until date should fail
        with self.assertRaises(frappe.exceptions.ValidationError):
            self.create_test_plan(
                plan_name="Test Invalid Dates",
                effective_from=add_months(nowdate(), 1),
                effective_until=nowdate(),
                is_perpetual=0
            )

    def test_perpetual_plan(self):
        """Test perpetual plan clears effective_until date."""
        plan = self.create_test_plan(
            plan_name="Test Perpetual",
            is_perpetual=1,
            effective_until=add_months(nowdate(), 6)
        )

        # Perpetual should clear the end date
        self.assertIsNone(plan.effective_until)

    # Volume Tier Tests
    def test_volume_tier_validation(self):
        """Test volume tier threshold order validation."""
        # Thresholds not in ascending order should warn
        plan = frappe.get_doc({
            "doctype": "Commission Plan",
            "plan_name": "Test Volume Tiers",
            "plan_type": "Standard",
            "status": "Active",
            "base_commission_rate": 15,
            "effective_from": nowdate(),
            "enable_volume_tiers": 1,
            "volume_tier_1_threshold": 10000,
            "volume_tier_1_rate": 12,
            "volume_tier_2_threshold": 5000,  # Less than tier 1 - invalid
            "volume_tier_2_rate": 10
        })

        with self.assertRaises(frappe.exceptions.ValidationError):
            plan.insert()

    # Default Plan Tests
    def test_default_plan_uniqueness(self):
        """Test only one default plan per tenant."""
        plan1 = self.create_test_plan(
            plan_name="Test Default 1",
            is_default=1
        )

        plan2 = self.create_test_plan(
            plan_name="Test Default 2",
            is_default=1
        )

        # Reload plan1 to see updated value
        plan1.reload()

        # plan1 should no longer be default
        self.assertEqual(plan1.is_default, 0)
        self.assertEqual(plan2.is_default, 1)

    # Status Tests
    def test_is_active_method(self):
        """Test is_active status check."""
        # Active plan with current dates
        plan = self.create_test_plan(plan_name="Test Active Check")
        self.assertTrue(plan.is_active())

        # Draft plan
        plan.status = "Draft"
        plan.save()
        self.assertFalse(plan.is_active())

        # Future effective_from
        plan.status = "Active"
        plan.effective_from = add_months(nowdate(), 1)
        plan.save()
        self.assertFalse(plan.is_active())

    def test_suspend_and_activate(self):
        """Test plan suspension and activation."""
        plan = self.create_test_plan(plan_name="Test Suspend")

        plan.suspend()
        self.assertEqual(plan.status, "Suspended")

        plan.activate()
        self.assertEqual(plan.status, "Active")

    # API Tests
    def test_get_commission_plan_api(self):
        """Test get_commission_plan API endpoint."""
        plan = self.create_test_plan(plan_name="Test API Plan")

        result = get_commission_plan(plan_name=plan.name)

        self.assertEqual(result["plan_name"], "Test API Plan")
        self.assertEqual(result["base_rate"], 10)

    def test_get_commission_plan_by_code(self):
        """Test getting plan by code."""
        plan = self.create_test_plan(plan_name="Test By Code")

        result = get_commission_plan(plan_code=plan.plan_code)

        self.assertEqual(result["plan_name"], "Test By Code")

    def test_calculate_commission_api(self):
        """Test calculate_commission API endpoint."""
        plan = self.create_test_plan(
            plan_name="Test Calc API",
            base_commission_rate=15
        )

        result = calculate_commission(
            plan_name=plan.name,
            order_value=500
        )

        self.assertEqual(result["commission_amount"], 75)  # 15% of 500
        self.assertEqual(result["seller_amount"], 425)

    def test_compare_plans_api(self):
        """Test compare_plans API endpoint."""
        import json

        plan1 = self.create_test_plan(
            plan_name="Test Compare 1",
            base_commission_rate=10
        )
        plan2 = self.create_test_plan(
            plan_name="Test Compare 2",
            base_commission_rate=15
        )

        result = compare_plans(
            plan_names=json.dumps([plan1.name, plan2.name]),
            order_value=1000
        )

        self.assertEqual(len(result), 2)
        # Results should be sorted by seller_amount (highest first)
        self.assertEqual(result[0]["commission_amount"], 100)  # 10% plan
        self.assertEqual(result[1]["commission_amount"], 150)  # 15% plan

    # Plan Summary Tests
    def test_get_plan_summary(self):
        """Test get_plan_summary method."""
        plan = self.create_test_plan(
            plan_name="Test Summary",
            enable_category_rates=1,
            enable_volume_tiers=1
        )

        summary = plan.get_plan_summary()

        self.assertEqual(summary["plan_name"], "Test Summary")
        self.assertEqual(summary["base_rate"], 10)
        self.assertEqual(summary["has_category_rates"], 1)
        self.assertEqual(summary["has_volume_tiers"], 1)
        self.assertTrue(summary["is_active"])


def run_tests():
    """Run all commission plan tests."""
    unittest.main(module=__name__, exit=False, verbosity=2)


if __name__ == "__main__":
    run_tests()

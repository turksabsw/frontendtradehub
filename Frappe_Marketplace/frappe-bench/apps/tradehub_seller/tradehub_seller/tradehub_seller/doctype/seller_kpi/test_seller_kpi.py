# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

import frappe
import unittest
from frappe.utils import nowdate, add_days, add_months, get_first_day, get_last_day, flt


class TestSellerKPI(unittest.TestCase):
    """Unit tests for Seller KPI DocType."""

    @classmethod
    def setUpClass(cls):
        """Set up test fixtures."""
        # Create a test seller profile if needed
        cls.test_seller = cls._get_or_create_test_seller()

    @classmethod
    def tearDownClass(cls):
        """Clean up test data."""
        # Clean up test KPIs
        frappe.db.delete("Seller KPI", {"seller": cls.test_seller})
        frappe.db.commit()

    @classmethod
    def _get_or_create_test_seller(cls):
        """Get or create a test seller profile."""
        # Check if test seller exists
        test_seller_name = frappe.db.exists("Seller Profile", {"seller_name": "Test KPI Seller"})

        if test_seller_name:
            return test_seller_name

        # Create test user if needed
        test_email = "test_kpi_seller@example.com"
        if not frappe.db.exists("User", test_email):
            user = frappe.get_doc({
                "doctype": "User",
                "email": test_email,
                "first_name": "Test",
                "last_name": "KPI Seller",
                "enabled": 1
            })
            user.insert(ignore_permissions=True)

        # Create test seller
        seller = frappe.get_doc({
            "doctype": "Seller Profile",
            "seller_name": "Test KPI Seller",
            "user": test_email,
            "seller_type": "Individual",
            "status": "Active",
            "contact_email": test_email,
            "address_line_1": "Test Address",
            "city": "Istanbul",
            "country": "Turkey"
        })
        seller.insert(ignore_permissions=True)
        frappe.db.commit()

        return seller.name

    def tearDown(self):
        """Clean up after each test."""
        frappe.db.rollback()

    def test_kpi_creation(self):
        """Test creating a basic Seller KPI record."""
        today = nowdate()
        period_start = get_first_day(today)
        period_end = get_last_day(today)

        kpi = frappe.get_doc({
            "doctype": "Seller KPI",
            "seller": self.test_seller,
            "kpi_type": "Order Fulfillment Rate",
            "kpi_category": "Fulfillment",
            "period_type": "Monthly",
            "period_start": period_start,
            "period_end": period_end,
            "target_value": 95,
            "actual_value": 92
        })
        kpi.insert(ignore_permissions=True)

        self.assertIsNotNone(kpi.name)
        self.assertEqual(kpi.seller, self.test_seller)
        self.assertEqual(kpi.kpi_type, "Order Fulfillment Rate")
        self.assertEqual(kpi.target_value, 95)
        self.assertEqual(kpi.actual_value, 92)

        # Clean up
        kpi.delete(ignore_permissions=True)

    def test_default_thresholds(self):
        """Test that default thresholds are set based on KPI type."""
        today = nowdate()
        period_start = get_first_day(today)
        period_end = get_last_day(today)

        kpi = frappe.get_doc({
            "doctype": "Seller KPI",
            "seller": self.test_seller,
            "kpi_type": "Order Fulfillment Rate",
            "kpi_category": "Fulfillment",
            "period_type": "Monthly",
            "period_start": period_start,
            "period_end": period_end
        })
        kpi.insert(ignore_permissions=True)

        # Check defaults for Order Fulfillment Rate
        self.assertEqual(kpi.target_value, 95)
        self.assertEqual(kpi.warning_threshold, 90)
        self.assertEqual(kpi.critical_threshold, 80)
        self.assertEqual(kpi.target_type, "Higher is Better")

        # Clean up
        kpi.delete(ignore_permissions=True)

    def test_period_label_generation(self):
        """Test that period labels are generated correctly."""
        today = nowdate()

        # Test Monthly
        monthly_kpi = frappe.get_doc({
            "doctype": "Seller KPI",
            "seller": self.test_seller,
            "kpi_type": "Return Rate",
            "kpi_category": "Quality",
            "period_type": "Monthly",
            "period_start": get_first_day(today),
            "period_end": get_last_day(today),
            "target_value": 5,
            "actual_value": 3
        })
        monthly_kpi.insert(ignore_permissions=True)

        self.assertIsNotNone(monthly_kpi.period_label)
        self.assertIn("202", monthly_kpi.period_label)  # Contains year

        # Clean up
        monthly_kpi.delete(ignore_permissions=True)

    def test_performance_evaluation_higher_is_better(self):
        """Test performance evaluation for 'Higher is Better' KPIs."""
        today = nowdate()
        period_start = get_first_day(today)
        period_end = get_last_day(today)

        # Test exceeding target
        exceeding_kpi = frappe.get_doc({
            "doctype": "Seller KPI",
            "seller": self.test_seller,
            "kpi_type": "Order Fulfillment Rate",
            "kpi_category": "Fulfillment",
            "period_type": "Monthly",
            "period_start": period_start,
            "period_end": period_end,
            "target_value": 90,
            "actual_value": 99,
            "warning_threshold": 80,
            "critical_threshold": 70
        })
        exceeding_kpi.insert(ignore_permissions=True)
        self.assertEqual(exceeding_kpi.status, "Exceeding")
        self.assertEqual(exceeding_kpi.performance_grade, "A+")
        exceeding_kpi.delete(ignore_permissions=True)

        # Test meeting target
        meeting_kpi = frappe.get_doc({
            "doctype": "Seller KPI",
            "seller": self.test_seller,
            "kpi_type": "Order Fulfillment Rate",
            "kpi_category": "Fulfillment",
            "period_type": "Monthly",
            "period_start": period_start,
            "period_end": period_end,
            "target_value": 90,
            "actual_value": 92,
            "warning_threshold": 80,
            "critical_threshold": 70
        })
        meeting_kpi.insert(ignore_permissions=True)
        self.assertEqual(meeting_kpi.status, "On Track")
        self.assertEqual(meeting_kpi.performance_grade, "A")
        meeting_kpi.delete(ignore_permissions=True)

        # Test at risk
        at_risk_kpi = frappe.get_doc({
            "doctype": "Seller KPI",
            "seller": self.test_seller,
            "kpi_type": "Order Fulfillment Rate",
            "kpi_category": "Fulfillment",
            "period_type": "Monthly",
            "period_start": period_start,
            "period_end": period_end,
            "target_value": 90,
            "actual_value": 85,
            "warning_threshold": 80,
            "critical_threshold": 70
        })
        at_risk_kpi.insert(ignore_permissions=True)
        self.assertEqual(at_risk_kpi.status, "At Risk")
        at_risk_kpi.delete(ignore_permissions=True)

        # Test critical
        critical_kpi = frappe.get_doc({
            "doctype": "Seller KPI",
            "seller": self.test_seller,
            "kpi_type": "Order Fulfillment Rate",
            "kpi_category": "Fulfillment",
            "period_type": "Monthly",
            "period_start": period_start,
            "period_end": period_end,
            "target_value": 90,
            "actual_value": 60,
            "warning_threshold": 80,
            "critical_threshold": 70
        })
        critical_kpi.insert(ignore_permissions=True)
        self.assertEqual(critical_kpi.status, "Critical")
        self.assertEqual(critical_kpi.performance_grade, "F")
        critical_kpi.delete(ignore_permissions=True)

    def test_performance_evaluation_lower_is_better(self):
        """Test performance evaluation for 'Lower is Better' KPIs."""
        today = nowdate()
        period_start = get_first_day(today)
        period_end = get_last_day(today)

        # Test exceeding target (lower is better, so under target is exceeding)
        exceeding_kpi = frappe.get_doc({
            "doctype": "Seller KPI",
            "seller": self.test_seller,
            "kpi_type": "Return Rate",
            "kpi_category": "Quality",
            "period_type": "Monthly",
            "period_start": period_start,
            "period_end": period_end,
            "target_value": 5,
            "actual_value": 2,
            "warning_threshold": 10,
            "critical_threshold": 15,
            "target_type": "Lower is Better"
        })
        exceeding_kpi.insert(ignore_permissions=True)
        self.assertEqual(exceeding_kpi.status, "Exceeding")
        exceeding_kpi.delete(ignore_permissions=True)

        # Test critical (for lower is better, high value is critical)
        critical_kpi = frappe.get_doc({
            "doctype": "Seller KPI",
            "seller": self.test_seller,
            "kpi_type": "Return Rate",
            "kpi_category": "Quality",
            "period_type": "Monthly",
            "period_start": period_start,
            "period_end": period_end,
            "target_value": 5,
            "actual_value": 20,
            "warning_threshold": 10,
            "critical_threshold": 15,
            "target_type": "Lower is Better"
        })
        critical_kpi.insert(ignore_permissions=True)
        self.assertEqual(critical_kpi.status, "Critical")
        critical_kpi.delete(ignore_permissions=True)

    def test_derived_values_calculation(self):
        """Test that derived values are calculated correctly."""
        today = nowdate()
        period_start = get_first_day(today)
        period_end = get_last_day(today)

        kpi = frappe.get_doc({
            "doctype": "Seller KPI",
            "seller": self.test_seller,
            "kpi_type": "On-Time Delivery Rate",
            "kpi_category": "Delivery",
            "period_type": "Monthly",
            "period_start": period_start,
            "period_end": period_end,
            "target_value": 95,
            "actual_value": 90
        })
        kpi.insert(ignore_permissions=True)

        # Check derived values
        self.assertIsNotNone(kpi.percentage_of_target)
        self.assertEqual(kpi.percentage_of_target, round((90 / 95) * 100, 2))

        self.assertIsNotNone(kpi.deviation_from_target)
        self.assertEqual(kpi.deviation_from_target, -5)  # 90 - 95 = -5

        # Clean up
        kpi.delete(ignore_permissions=True)

    def test_score_contribution_calculation(self):
        """Test score contribution calculation."""
        today = nowdate()
        period_start = get_first_day(today)
        period_end = get_last_day(today)

        # Test perfect score
        perfect_kpi = frappe.get_doc({
            "doctype": "Seller KPI",
            "seller": self.test_seller,
            "kpi_type": "Order Fulfillment Rate",
            "kpi_category": "Fulfillment",
            "period_type": "Monthly",
            "period_start": period_start,
            "period_end": period_end,
            "target_value": 95,
            "actual_value": 100,
            "target_type": "Higher is Better"
        })
        perfect_kpi.insert(ignore_permissions=True)
        self.assertEqual(perfect_kpi.score_contribution, 100)
        perfect_kpi.delete(ignore_permissions=True)

    def test_action_required_flag(self):
        """Test that action_required flag is set for critical KPIs."""
        today = nowdate()
        period_start = get_first_day(today)
        period_end = get_last_day(today)

        critical_kpi = frappe.get_doc({
            "doctype": "Seller KPI",
            "seller": self.test_seller,
            "kpi_type": "Order Fulfillment Rate",
            "kpi_category": "Fulfillment",
            "period_type": "Monthly",
            "period_start": period_start,
            "period_end": period_end,
            "target_value": 95,
            "actual_value": 50,
            "warning_threshold": 90,
            "critical_threshold": 80
        })
        critical_kpi.insert(ignore_permissions=True)

        self.assertEqual(critical_kpi.action_required, 1)
        self.assertIsNotNone(critical_kpi.recommended_action)
        self.assertIsNotNone(critical_kpi.action_deadline)

        critical_kpi.delete(ignore_permissions=True)

    def test_kpi_get_summary(self):
        """Test the get_summary method."""
        today = nowdate()
        period_start = get_first_day(today)
        period_end = get_last_day(today)

        kpi = frappe.get_doc({
            "doctype": "Seller KPI",
            "seller": self.test_seller,
            "kpi_type": "Customer Satisfaction",
            "kpi_category": "Service",
            "period_type": "Monthly",
            "period_start": period_start,
            "period_end": period_end,
            "target_value": 4.5,
            "actual_value": 4.8
        })
        kpi.insert(ignore_permissions=True)

        summary = kpi.get_summary()

        self.assertIn("name", summary)
        self.assertIn("seller", summary)
        self.assertIn("kpi_type", summary)
        self.assertIn("status", summary)
        self.assertIn("actual_value", summary)
        self.assertIn("target_value", summary)
        self.assertIn("performance_grade", summary)

        kpi.delete(ignore_permissions=True)

    def test_kpi_get_detailed_report(self):
        """Test the get_detailed_report method."""
        today = nowdate()
        period_start = get_first_day(today)
        period_end = get_last_day(today)

        kpi = frappe.get_doc({
            "doctype": "Seller KPI",
            "seller": self.test_seller,
            "kpi_type": "Response Time",
            "kpi_category": "Service",
            "period_type": "Monthly",
            "period_start": period_start,
            "period_end": period_end,
            "target_value": 24,
            "actual_value": 18
        })
        kpi.insert(ignore_permissions=True)

        report = kpi.get_detailed_report()

        self.assertIn("basic", report)
        self.assertIn("period", report)
        self.assertIn("targets", report)
        self.assertIn("values", report)
        self.assertIn("evaluation", report)
        self.assertIn("comparison", report)
        self.assertIn("statistics", report)

        kpi.delete(ignore_permissions=True)

    def test_record_action(self):
        """Test recording an action for a KPI."""
        today = nowdate()
        period_start = get_first_day(today)
        period_end = get_last_day(today)

        kpi = frappe.get_doc({
            "doctype": "Seller KPI",
            "seller": self.test_seller,
            "kpi_type": "Cancellation Rate",
            "kpi_category": "Quality",
            "period_type": "Monthly",
            "period_start": period_start,
            "period_end": period_end,
            "target_value": 3,
            "actual_value": 8
        })
        kpi.insert(ignore_permissions=True)

        kpi.record_action("Implemented better inventory management")

        self.assertEqual(kpi.action_taken, "Implemented better inventory management")
        self.assertIsNotNone(kpi.action_taken_at)
        self.assertIsNotNone(kpi.action_taken_by)

        kpi.delete(ignore_permissions=True)

    def test_period_validation(self):
        """Test that invalid periods are rejected."""
        today = nowdate()

        # Period end before start should fail
        kpi = frappe.get_doc({
            "doctype": "Seller KPI",
            "seller": self.test_seller,
            "kpi_type": "Order Fulfillment Rate",
            "kpi_category": "Fulfillment",
            "period_type": "Monthly",
            "period_start": today,
            "period_end": add_days(today, -10),  # End before start
            "target_value": 95,
            "actual_value": 90
        })

        self.assertRaises(frappe.ValidationError, kpi.insert)

    def test_api_create_seller_kpi(self):
        """Test the create_seller_kpi API endpoint."""
        from tradehub_seller.tradehub_seller.doctype.seller_kpi.seller_kpi import create_seller_kpi

        result = create_seller_kpi(
            seller=self.test_seller,
            kpi_type="Dispute Rate",
            period_type="Monthly"
        )

        self.assertIsNotNone(result)
        self.assertIn("name", result)
        self.assertEqual(result["kpi_type"], "Dispute Rate")

        # Clean up
        frappe.delete_doc("Seller KPI", result["name"], ignore_permissions=True)

    def test_api_get_seller_kpis(self):
        """Test the get_seller_kpis API endpoint."""
        from tradehub_seller.tradehub_seller.doctype.seller_kpi.seller_kpi import (
            create_seller_kpi, get_seller_kpis
        )

        today = nowdate()
        period_start = get_first_day(today)
        period_end = get_last_day(today)

        # Create a few KPIs
        kpi1 = frappe.get_doc({
            "doctype": "Seller KPI",
            "seller": self.test_seller,
            "kpi_type": "Order Fulfillment Rate",
            "kpi_category": "Fulfillment",
            "period_type": "Monthly",
            "period_start": period_start,
            "period_end": period_end,
            "target_value": 95,
            "actual_value": 92,
            "status": "Active"
        })
        kpi1.insert(ignore_permissions=True)

        kpi2 = frappe.get_doc({
            "doctype": "Seller KPI",
            "seller": self.test_seller,
            "kpi_type": "Return Rate",
            "kpi_category": "Quality",
            "period_type": "Monthly",
            "period_start": period_start,
            "period_end": period_end,
            "target_value": 5,
            "actual_value": 3,
            "status": "Active"
        })
        kpi2.insert(ignore_permissions=True)

        # Test API
        kpis = get_seller_kpis(seller=self.test_seller)

        self.assertIsInstance(kpis, list)
        self.assertGreaterEqual(len(kpis), 2)

        # Clean up
        kpi1.delete(ignore_permissions=True)
        kpi2.delete(ignore_permissions=True)

    def test_api_get_kpi_dashboard(self):
        """Test the get_kpi_dashboard API endpoint."""
        from tradehub_seller.tradehub_seller.doctype.seller_kpi.seller_kpi import get_kpi_dashboard

        today = nowdate()
        period_start = get_first_day(today)
        period_end = get_last_day(today)

        # Create a current period KPI
        kpi = frappe.get_doc({
            "doctype": "Seller KPI",
            "seller": self.test_seller,
            "kpi_type": "Customer Satisfaction",
            "kpi_category": "Service",
            "period_type": "Monthly",
            "period_start": period_start,
            "period_end": period_end,
            "target_value": 4.5,
            "actual_value": 4.2,
            "status": "At Risk",
            "is_current_period": 1
        })
        kpi.insert(ignore_permissions=True)

        # Test API
        dashboard = get_kpi_dashboard(seller=self.test_seller)

        self.assertIn("seller", dashboard)
        self.assertIn("total_kpis", dashboard)
        self.assertIn("health_score", dashboard)
        self.assertIn("status_distribution", dashboard)
        self.assertIn("by_category", dashboard)

        # Clean up
        kpi.delete(ignore_permissions=True)

    def test_api_get_seller_kpi_summary(self):
        """Test the get_seller_kpi_summary API endpoint."""
        from tradehub_seller.tradehub_seller.doctype.seller_kpi.seller_kpi import get_seller_kpi_summary

        summary = get_seller_kpi_summary(seller=self.test_seller)

        self.assertIn("seller", summary)
        self.assertIn("health_score", summary)
        self.assertIn("total_kpis", summary)
        self.assertIn("critical_kpis", summary)
        self.assertIn("at_risk_kpis", summary)
        self.assertIn("key_metrics", summary)

    def test_kpi_types_have_defaults(self):
        """Test that all KPI types have default thresholds defined."""
        today = nowdate()
        period_start = get_first_day(today)
        period_end = get_last_day(today)

        kpi_types = [
            "Order Fulfillment Rate",
            "On-Time Delivery Rate",
            "Return Rate",
            "Cancellation Rate",
            "Response Time",
            "Customer Satisfaction",
            "Complaint Rate",
            "Dispute Rate",
            "Refund Rate"
        ]

        for kpi_type in kpi_types:
            kpi = frappe.get_doc({
                "doctype": "Seller KPI",
                "seller": self.test_seller,
                "kpi_type": kpi_type,
                "kpi_category": "Fulfillment",
                "period_type": "Monthly",
                "period_start": period_start,
                "period_end": period_end
            })
            kpi.insert(ignore_permissions=True)

            # All KPIs should have default target value
            self.assertIsNotNone(kpi.target_value, f"{kpi_type} should have default target")
            self.assertGreater(flt(kpi.target_value), 0, f"{kpi_type} target should be > 0")

            kpi.delete(ignore_permissions=True)


def run_tests():
    """Run all tests."""
    suite = unittest.TestLoader().loadTestsFromTestCase(TestSellerKPI)
    runner = unittest.TextTestRunner(verbosity=2)
    runner.run(suite)


if __name__ == "__main__":
    run_tests()

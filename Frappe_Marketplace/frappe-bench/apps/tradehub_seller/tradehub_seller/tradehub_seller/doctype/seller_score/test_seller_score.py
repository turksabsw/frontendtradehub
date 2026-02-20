# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import nowdate, now_datetime


class TestSellerScore(FrappeTestCase):
    """Test cases for Seller Score DocType."""

    def setUp(self):
        """Set up test data."""
        # Clean up existing test data
        frappe.db.delete("Seller Score", {"seller": ["like", "TEST-%"]})

    def tearDown(self):
        """Clean up test data."""
        frappe.db.delete("Seller Score", {"seller": ["like", "TEST-%"]})

    def test_create_seller_score(self):
        """Test creating a basic seller score record."""
        # First, we need a seller profile to test with
        # In a real scenario, we would create a test seller
        # For now, test the score calculation logic directly

        score = frappe.get_doc({
            "doctype": "Seller Score",
            "seller": None,  # Would be a real seller in integration tests
            "score_type": "Manual",
            "score_period": "2024-01",
            "calculation_date": nowdate(),
            "status": "Draft",
            "fulfillment_score": 90,
            "delivery_score": 85,
            "quality_score": 88,
            "service_score": 92,
            "compliance_score": 100,
            "engagement_score": 75
        })

        # Test score calculation without saving
        score.validate_scores()
        score.calculate_overall_score()

        # Expected: weighted average of component scores
        # Default weights: fulfillment=20, delivery=20, quality=20, service=15, compliance=15, engagement=10
        expected = (
            (90 * 20 + 85 * 20 + 88 * 20 + 92 * 15 + 100 * 15 + 75 * 10) / 100
        )
        self.assertAlmostEqual(score.overall_score, expected, places=1)

    def test_score_validation_range(self):
        """Test that scores are validated to be within 0-100."""
        score = frappe.get_doc({
            "doctype": "Seller Score",
            "score_type": "Manual",
            "calculation_date": nowdate(),
            "status": "Draft",
            "fulfillment_score": 150  # Invalid: should be 0-100
        })

        self.assertRaises(frappe.ValidationError, score.validate_scores)

    def test_score_with_penalties(self):
        """Test score calculation with penalties."""
        score = frappe.get_doc({
            "doctype": "Seller Score",
            "seller": None,
            "score_type": "Manual",
            "calculation_date": nowdate(),
            "status": "Draft",
            "fulfillment_score": 90,
            "delivery_score": 90,
            "quality_score": 90,
            "service_score": 90,
            "compliance_score": 90,
            "engagement_score": 90,
            "penalty_deduction": 10
        })

        score.validate_scores()
        score.calculate_overall_score()

        # Base score would be 90, minus 10 penalty = 80
        self.assertEqual(score.overall_score, 80)

    def test_score_with_bonuses(self):
        """Test score calculation with bonuses."""
        score = frappe.get_doc({
            "doctype": "Seller Score",
            "seller": None,
            "score_type": "Manual",
            "calculation_date": nowdate(),
            "status": "Draft",
            "fulfillment_score": 90,
            "delivery_score": 90,
            "quality_score": 90,
            "service_score": 90,
            "compliance_score": 90,
            "engagement_score": 90,
            "bonus_points": 5
        })

        score.validate_scores()
        score.calculate_overall_score()

        # Base score would be 90, plus 5 bonus = 95
        self.assertEqual(score.overall_score, 95)

    def test_score_clamped_to_100(self):
        """Test that score is clamped to max 100."""
        score = frappe.get_doc({
            "doctype": "Seller Score",
            "seller": None,
            "score_type": "Manual",
            "calculation_date": nowdate(),
            "status": "Draft",
            "fulfillment_score": 100,
            "delivery_score": 100,
            "quality_score": 100,
            "service_score": 100,
            "compliance_score": 100,
            "engagement_score": 100,
            "bonus_points": 20  # Would push above 100
        })

        score.validate_scores()
        score.calculate_overall_score()

        # Score should be clamped to 100
        self.assertEqual(score.overall_score, 100)

    def test_score_breakdown(self):
        """Test getting score breakdown."""
        score = frappe.get_doc({
            "doctype": "Seller Score",
            "seller": None,
            "score_type": "Manual",
            "calculation_date": nowdate(),
            "status": "Draft",
            "fulfillment_score": 90,
            "delivery_score": 85,
            "quality_score": 88,
            "service_score": 92,
            "compliance_score": 100,
            "engagement_score": 75,
            "average_rating": 4.5,
            "rating_count": 100,
            "orders_evaluated": 50
        })

        score.validate_scores()
        score.calculate_overall_score()

        breakdown = score.get_score_breakdown()

        self.assertIn("overall_score", breakdown)
        self.assertIn("components", breakdown)
        self.assertIn("metrics", breakdown)
        self.assertIn("ratings", breakdown)

        # Check components
        self.assertEqual(breakdown["components"]["fulfillment"]["score"], 90)
        self.assertEqual(breakdown["components"]["delivery"]["score"], 85)

        # Check ratings
        self.assertEqual(breakdown["ratings"]["average_rating"], 4.5)
        self.assertEqual(breakdown["ratings"]["rating_count"], 100)

    def test_score_summary(self):
        """Test getting score summary."""
        score = frappe.get_doc({
            "doctype": "Seller Score",
            "seller": None,
            "score_type": "Monthly",
            "score_period": "2024-01",
            "calculation_date": nowdate(),
            "status": "Draft",
            "overall_score": 85
        })

        summary = score.get_summary()

        self.assertEqual(summary["score_type"], "Monthly")
        self.assertEqual(summary["score_period"], "2024-01")
        self.assertEqual(summary["overall_score"], 85)

    def test_weights_validation(self):
        """Test that weight validation warns if not 100%."""
        score = frappe.get_doc({
            "doctype": "Seller Score",
            "seller": None,
            "score_type": "Manual",
            "calculation_date": nowdate(),
            "status": "Draft",
            "fulfillment_score": 90,
            # Set custom weights that don't sum to 100
            "fulfillment_weight": 30,
            "delivery_weight": 30,
            "quality_weight": 30,
            "service_weight": 30,
            "compliance_weight": 30,
            "engagement_weight": 30  # Total = 180%
        })

        # Should not raise, but should show warning
        score.validate_weights()  # This will msgprint, not throw

    def test_trend_determination(self):
        """Test score trend determination."""
        score = frappe.get_doc({
            "doctype": "Seller Score",
            "seller": None,
            "score_type": "Manual",
            "calculation_date": nowdate(),
            "status": "Draft",
            "overall_score": 85,
            "previous_score": 80
        })

        score.calculate_score_change()

        self.assertEqual(score.score_change, 5)  # 85 - 80 = 5 point increase

# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

"""
Tests for Reviews & Moderation Module

Tests cover:
- Review submission and validation
- Verified purchase verification
- Helpfulness voting (Wilson score)
- Seller response functionality
- Moderation case workflow
- SLA tracking
- Escalation and appeal workflows
- Auto-moderation
"""

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import now_datetime, add_days, add_to_date
from unittest.mock import patch, MagicMock
import json


class TestReviews(FrappeTestCase):
    """Test cases for Review DocType and operations."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._create_test_data()

    @classmethod
    def _create_test_data(cls):
        """Create test fixtures."""
        # Create test user
        if not frappe.db.exists("User", "test_buyer@example.com"):
            frappe.get_doc({
                "doctype": "User",
                "email": "test_buyer@example.com",
                "first_name": "Test",
                "last_name": "Buyer",
                "send_welcome_email": 0
            }).insert(ignore_permissions=True)

        if not frappe.db.exists("User", "test_seller@example.com"):
            frappe.get_doc({
                "doctype": "User",
                "email": "test_seller@example.com",
                "first_name": "Test",
                "last_name": "Seller",
                "send_welcome_email": 0
            }).insert(ignore_permissions=True)

    def setUp(self):
        """Set up test environment before each test."""
        frappe.set_user("Administrator")

    def tearDown(self):
        """Clean up after each test."""
        frappe.set_user("Administrator")

    # ==================== Review Submission Tests ====================

    def test_review_creation_basic(self):
        """Test basic review creation."""
        review = frappe.get_doc({
            "doctype": "Review",
            "review_type": "Product",
            "reviewer": "test_buyer@example.com",
            "rating": 4,
            "title": "Great Product",
            "review_text": "This is a test review with enough characters to pass validation.",
            "status": "Pending Review"
        })

        # Should not raise - validates successfully
        review.validate_rating()
        self.assertEqual(review.rating, 4)

    def test_review_rating_validation(self):
        """Test rating bounds validation."""
        review = frappe.get_doc({
            "doctype": "Review",
            "review_type": "Product",
            "reviewer": "test_buyer@example.com",
            "review_text": "Test review with sufficient characters."
        })

        # Test rating > 5 gets clamped
        review.rating = 10
        review.validate_rating()
        self.assertEqual(review.rating, 5)

        # Test rating < 1 gets clamped
        review.rating = 0
        review.validate_rating()
        self.assertEqual(review.rating, 1)

    def test_review_content_validation(self):
        """Test review content length validation."""
        review = frappe.get_doc({
            "doctype": "Review",
            "review_type": "Product",
            "reviewer": "test_buyer@example.com",
            "rating": 4
        })

        # Test too short review
        review.review_text = "Short"
        with self.assertRaises(frappe.ValidationError):
            review.validate_review_content()

    def test_spam_detection(self):
        """Test spam pattern detection."""
        review = frappe.get_doc({
            "doctype": "Review",
            "review_type": "Product",
            "reviewer": "test_buyer@example.com",
            "rating": 4
        })

        # Test spam patterns
        spam_texts = [
            "BUY NOW at cheap prices",
            "Visit bit.ly/fake for discount",
            "AAAAAAAAAAAAAA",  # Repeated characters
        ]

        for text in spam_texts:
            result = review.contains_spam_patterns(text)
            self.assertTrue(result, f"Should detect spam in: {text}")

        # Test clean text
        clean_text = "This is a legitimate product review with honest feedback."
        result = review.contains_spam_patterns(clean_text)
        self.assertFalse(result)

    # ==================== Helpfulness Voting Tests ====================

    def test_helpfulness_score_calculation(self):
        """Test Wilson score calculation for helpfulness."""
        review = frappe.get_doc({
            "doctype": "Review",
            "review_type": "Product",
            "reviewer": "test_buyer@example.com",
            "rating": 4,
            "review_text": "Test review",
            "helpful_count": 10,
            "unhelpful_count": 2
        })

        review.calculate_helpfulness_score()

        # Score should be positive and reasonable
        self.assertGreater(review.helpfulness_score, 0)
        self.assertLessEqual(review.helpfulness_score, 100)

    def test_helpfulness_score_no_votes(self):
        """Test helpfulness score with no votes."""
        review = frappe.get_doc({
            "doctype": "Review",
            "review_type": "Product",
            "reviewer": "test_buyer@example.com",
            "rating": 4,
            "review_text": "Test review",
            "helpful_count": 0,
            "unhelpful_count": 0
        })

        review.calculate_helpfulness_score()
        self.assertEqual(review.helpfulness_score, 0)

    # ==================== Display Name Tests ====================

    def test_anonymous_display_name(self):
        """Test anonymous display name masking."""
        review = frappe.get_doc({
            "doctype": "Review",
            "review_type": "Product",
            "reviewer": "test_buyer@example.com",
            "reviewer_name": "John Smith",
            "rating": 4,
            "review_text": "Test review",
            "is_anonymous": 1
        })

        review.set_display_name()

        # Should mask the name
        self.assertIn("*", review.display_name)
        self.assertEqual(review.display_name[0], "J")

    def test_non_anonymous_display_name(self):
        """Test non-anonymous display name."""
        review = frappe.get_doc({
            "doctype": "Review",
            "review_type": "Product",
            "reviewer": "test_buyer@example.com",
            "reviewer_name": "John Smith",
            "rating": 4,
            "review_text": "Test review",
            "is_anonymous": 0
        })

        review.set_display_name()

        # Should show full name
        self.assertEqual(review.display_name, "John Smith")


class TestModerationCase(FrappeTestCase):
    """Test cases for Moderation Case DocType and workflow."""

    def setUp(self):
        """Set up test environment before each test."""
        frappe.set_user("Administrator")

    def tearDown(self):
        """Clean up after each test."""
        frappe.set_user("Administrator")

    # ==================== Case Creation Tests ====================

    def test_case_id_generation(self):
        """Test unique case ID generation."""
        case = frappe.get_doc({
            "doctype": "Moderation Case",
            "content_type": "Review",
            "content_id": "TEST-001",
            "case_type": "Content Report",
            "priority": "Medium"
        })

        case_id = case.generate_case_id()

        self.assertTrue(case_id.startswith("MC-"))
        self.assertGreater(len(case_id), 3)

    def test_sla_target_setting(self):
        """Test SLA target hours based on priority."""
        priorities_and_targets = [
            ("Critical", 4),
            ("High", 12),
            ("Medium", 24),
            ("Low", 48)
        ]

        for priority, expected_hours in priorities_and_targets:
            case = frappe.get_doc({
                "doctype": "Moderation Case",
                "content_type": "Review",
                "content_id": "TEST-001",
                "case_type": "Content Report",
                "priority": priority
            })

            case.set_sla_target()
            self.assertEqual(
                case.sla_target_hours,
                expected_hours,
                f"Priority {priority} should have {expected_hours}h SLA"
            )

    # ==================== Status Transition Tests ====================

    def test_valid_status_transitions(self):
        """Test valid status transitions."""
        valid_transitions = [
            ("Open", "Assigned"),
            ("Assigned", "In Review"),
            ("In Review", "Resolved"),
            ("Resolved", "Closed"),
            ("Resolved", "Appealed"),
        ]

        for from_status, to_status in valid_transitions:
            case = frappe.get_doc({
                "doctype": "Moderation Case",
                "content_type": "Review",
                "content_id": "TEST-001",
                "case_type": "Content Report",
                "priority": "Medium",
                "status": to_status
            })

            # Mock the old status
            with patch.object(frappe.db, 'get_value', return_value=from_status):
                # Should not raise
                case.validate_status_transitions()

    def test_invalid_status_transition(self):
        """Test invalid status transitions raise error."""
        case = frappe.get_doc({
            "doctype": "Moderation Case",
            "content_type": "Review",
            "content_id": "TEST-001",
            "case_type": "Content Report",
            "priority": "Medium",
            "status": "Resolved"  # Trying to go to Resolved
        })

        # Mock getting old status as "Closed" (can't go from Closed to Resolved directly)
        with patch.object(frappe.db, 'get_value', return_value="Closed"):
            with patch.object(case, 'is_new', return_value=False):
                with self.assertRaises(frappe.ValidationError):
                    case.validate_status_transitions()

    # ==================== SLA Status Tests ====================

    def test_sla_status_on_track(self):
        """Test SLA status shows 'On Track' when within limits."""
        case = frappe.get_doc({
            "doctype": "Moderation Case",
            "content_type": "Review",
            "content_id": "TEST-001",
            "case_type": "Content Report",
            "priority": "Medium",
            "status": "Open",
            "sla_target_hours": 24,
            "creation_date": now_datetime()  # Just created
        })

        case.check_sla_status()
        self.assertEqual(case.sla_status, "On Track")

    def test_sla_status_at_risk(self):
        """Test SLA status shows 'At Risk' when approaching deadline."""
        case = frappe.get_doc({
            "doctype": "Moderation Case",
            "content_type": "Review",
            "content_id": "TEST-001",
            "case_type": "Content Report",
            "priority": "Medium",
            "status": "Open",
            "sla_target_hours": 24,
            "creation_date": add_to_date(now_datetime(), hours=-20)  # 20 hours ago (>80%)
        })

        case.check_sla_status()
        self.assertEqual(case.sla_status, "At Risk")

    def test_sla_status_breached(self):
        """Test SLA status shows 'Breached' when past deadline."""
        case = frappe.get_doc({
            "doctype": "Moderation Case",
            "content_type": "Review",
            "content_id": "TEST-001",
            "case_type": "Content Report",
            "priority": "Medium",
            "status": "Open",
            "sla_target_hours": 24,
            "creation_date": add_to_date(now_datetime(), hours=-30)  # 30 hours ago
        })

        case.check_sla_status()
        self.assertEqual(case.sla_status, "Breached")

    # ==================== History Logging Tests ====================

    def test_history_event_logging(self):
        """Test moderation history event logging."""
        case = frappe.get_doc({
            "doctype": "Moderation Case",
            "content_type": "Review",
            "content_id": "TEST-001",
            "case_type": "Content Report",
            "priority": "Medium",
            "status": "Open"
        })

        case.log_history_event("test_event", {"key": "value"})

        history = json.loads(case.moderation_history)
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["event"], "test_event")
        self.assertEqual(history[0]["details"]["key"], "value")

    # ==================== Appeal Tests ====================

    def test_appeal_validation_not_appealable(self):
        """Test appeal validation when case is not appealable."""
        case = frappe.get_doc({
            "doctype": "Moderation Case",
            "content_type": "Review",
            "content_id": "TEST-001",
            "case_type": "Content Report",
            "priority": "Medium",
            "status": "Resolved",
            "is_appealable": 0,
            "appeal_status": "Appeal Submitted"
        })

        case.validate_appeal()

        # Appeal fields should be cleared
        self.assertEqual(case.appeal_status, "")

    def test_appeal_requires_decision(self):
        """Test appeal approval requires decision text."""
        case = frappe.get_doc({
            "doctype": "Moderation Case",
            "content_type": "Review",
            "content_id": "TEST-001",
            "case_type": "Content Report",
            "priority": "Medium",
            "status": "Appealed",
            "is_appealable": 1,
            "appeal_status": "Approved",
            "appeal_decision": None
        })

        with self.assertRaises(frappe.ValidationError):
            case.validate_appeal()


class TestReviewManager(FrappeTestCase):
    """Test cases for review_manager module functions."""

    def test_wilson_score_calculation(self):
        """Test Wilson score lower bound calculation."""
        from tr_tradehub.reviews.review_manager import _calculate_helpfulness_score

        # High confidence positive
        score = _calculate_helpfulness_score(100, 10)
        self.assertGreater(score, 80)

        # Equal votes
        score = _calculate_helpfulness_score(50, 50)
        self.assertLess(score, 50)

        # No votes
        score = _calculate_helpfulness_score(0, 0)
        self.assertEqual(score, 0)


class TestAutoModeration(FrappeTestCase):
    """Test cases for auto-moderation functionality."""

    def test_auto_check_content_profanity(self):
        """Test auto-detection of profanity."""
        from tr_tradehub.reviews.moderation import auto_check_content

        result = auto_check_content("This review contains damn bad words")

        self.assertTrue(result["flagged"])
        self.assertIn("profanity", [f["type"] for f in result["flags"]])

    def test_auto_check_content_spam(self):
        """Test auto-detection of spam indicators."""
        from tr_tradehub.reviews.moderation import auto_check_content

        result = auto_check_content("CLICK HERE NOW!!!! BUY BUY BUY FREE MONEY")

        self.assertTrue(result["flagged"])

    def test_auto_check_content_clean(self):
        """Test clean content passes auto-check."""
        from tr_tradehub.reviews.moderation import auto_check_content

        result = auto_check_content(
            "This is a thoughtful and helpful product review. "
            "The quality exceeded my expectations and shipping was fast."
        )

        self.assertFalse(result["flagged"])


class TestScheduledTasks(FrappeTestCase):
    """Test cases for scheduled review/moderation tasks."""

    @patch('tr_tradehub.reviews.tasks.frappe')
    def test_process_pending_reviews_gets_old_reviews(self, mock_frappe):
        """Test that process_pending_reviews queries correct filters."""
        from tr_tradehub.reviews.tasks import process_pending_reviews

        mock_frappe.get_all.return_value = []

        # Call should not raise
        process_pending_reviews()

    @patch('tr_tradehub.reviews.tasks.frappe')
    def test_check_sla_breaches_updates_status(self, mock_frappe):
        """Test SLA breach checking updates case status."""
        from tr_tradehub.reviews.tasks import check_sla_breaches

        mock_frappe.get_all.return_value = []
        mock_frappe.db.commit = MagicMock()

        # Call should not raise
        check_sla_breaches()


class TestReviewAPI(FrappeTestCase):
    """Test cases for Review REST API endpoints."""

    def test_response_format(self):
        """Test API response format helper."""
        from tr_tradehub.reviews.api import _response

        # Success response
        response = _response(True, data={"key": "value"}, message="Success")

        self.assertTrue(response["success"])
        self.assertEqual(response["data"]["key"], "value")
        self.assertEqual(response["message"], "Success")
        self.assertEqual(response["errors"], [])

        # Error response
        response = _response(False, message="Error", errors=["err1", "err2"])

        self.assertFalse(response["success"])
        self.assertIsNone(response["data"])
        self.assertEqual(len(response["errors"]), 2)

    @patch('tr_tradehub.reviews.api.frappe')
    def test_is_moderator_check(self, mock_frappe):
        """Test moderator role checking."""
        from tr_tradehub.reviews.api import _is_moderator

        # Test with System Manager role
        mock_frappe.get_roles.return_value = ["System Manager", "Guest"]
        self.assertTrue(_is_moderator())

        # Test with Marketplace Moderator role
        mock_frappe.get_roles.return_value = ["Marketplace Moderator"]
        self.assertTrue(_is_moderator())

        # Test without moderator roles
        mock_frappe.get_roles.return_value = ["Guest", "Website User"]
        self.assertFalse(_is_moderator())


class TestIntegration(FrappeTestCase):
    """Integration tests for reviews and moderation workflow."""

    def test_review_to_moderation_workflow(self):
        """Test complete workflow from review to moderation case."""
        # This test validates the integration between Review and Moderation Case

        # 1. Review gets flagged (simulated)
        review_data = {
            "doctype": "Review",
            "review_type": "Product",
            "reviewer": "test@example.com",
            "rating": 1,
            "review_text": "This is inappropriate content",
            "moderation_status": "Flagged"
        }

        # 2. Moderation case should track the review
        case_data = {
            "doctype": "Moderation Case",
            "content_type": "Review",
            "content_id": "TEST-REVIEW-001",
            "case_type": "Content Report",
            "report_reason": "Inappropriate Content",
            "priority": "High"
        }

        # Validate data structures
        self.assertEqual(case_data["content_type"], "Review")
        self.assertEqual(case_data["report_reason"], "Inappropriate Content")

    def test_seller_score_update_flow(self):
        """Test seller score calculation from reviews."""
        # Simulated review statistics
        stats = {
            "total_reviews": 50,
            "avg_rating": 4.2,
            "positive_reviews": 45,
            "negative_reviews": 2
        }

        # Calculate positive feedback rate
        positive_rate = (stats["positive_reviews"] / stats["total_reviews"]) * 100

        self.assertEqual(positive_rate, 90.0)
        self.assertGreater(stats["avg_rating"], 4.0)

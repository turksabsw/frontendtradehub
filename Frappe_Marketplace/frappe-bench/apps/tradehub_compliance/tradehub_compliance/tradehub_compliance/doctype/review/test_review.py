# Copyright (c) 2024, TR TradeHub and Contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import nowdate, add_days, now_datetime


class TestReview(FrappeTestCase):
    """Test cases for Review DocType."""

    def setUp(self):
        """Set up test data."""
        # Create test user if not exists
        if not frappe.db.exists("User", "test_reviewer@test.com"):
            frappe.get_doc({
                "doctype": "User",
                "email": "test_reviewer@test.com",
                "first_name": "Test",
                "last_name": "Reviewer",
                "send_welcome_email": 0
            }).insert(ignore_permissions=True)

    def tearDown(self):
        """Clean up test data."""
        # Delete test reviews
        frappe.db.delete("Review", {"reviewer": "test_reviewer@test.com"})
        frappe.db.commit()

    def test_review_creation(self):
        """Test basic review creation."""
        review = frappe.get_doc({
            "doctype": "Review",
            "review_type": "Seller",
            "reviewer": "test_reviewer@test.com",
            "rating": 4,
            "title": "Great seller experience",
            "review_text": "This seller was very helpful and responsive. The product arrived quickly and was as described.",
            "status": "Draft"
        })

        # Should not have listing for seller review
        review.seller = None  # Seller is mandatory for seller reviews

        # For seller review, seller is required
        # Let's test product review instead without requiring existing listing
        review.review_type = "Order Experience"
        review.seller = None

        review.insert(ignore_permissions=True)

        self.assertIsNotNone(review.name)
        self.assertIsNotNone(review.review_id)
        self.assertEqual(review.status, "Draft")
        self.assertEqual(review.rating, 4)

    def test_review_id_generation(self):
        """Test that review ID is auto-generated."""
        from tradehub_compliance.tradehub_compliance.doctype.review.review import Review

        review = Review({"doctype": "Review"})
        review_id = review.generate_review_id()

        self.assertIsNotNone(review_id)
        self.assertTrue(review_id.startswith("RVW-"))
        self.assertEqual(len(review_id), 14)  # RVW- + 10 chars

    def test_rating_validation(self):
        """Test rating validation."""
        review = frappe.get_doc({
            "doctype": "Review",
            "review_type": "Order Experience",
            "reviewer": "test_reviewer@test.com",
            "title": "Test Review",
            "review_text": "This is a valid review text with more than twenty characters.",
            "status": "Draft"
        })

        # Test rating boundary - too high
        review.rating = 10
        review.validate_rating()
        self.assertEqual(review.rating, 5)

        # Test rating boundary - too low
        review.rating = -1
        review.validate_rating()
        self.assertEqual(review.rating, 1)

        # Test valid rating
        review.rating = 3
        review.validate_rating()
        self.assertEqual(review.rating, 3)

    def test_review_text_validation(self):
        """Test review text minimum length validation."""
        review = frappe.get_doc({
            "doctype": "Review",
            "review_type": "Order Experience",
            "reviewer": "test_reviewer@test.com",
            "rating": 4,
            "title": "Test",
            "review_text": "Too short",
            "status": "Draft"
        })

        with self.assertRaises(frappe.ValidationError):
            review.validate_review_content()

    def test_display_name_anonymous(self):
        """Test display name masking for anonymous reviews."""
        review = frappe.get_doc({
            "doctype": "Review",
            "review_type": "Order Experience",
            "reviewer": "test_reviewer@test.com",
            "reviewer_name": "John Smith",
            "rating": 4,
            "title": "Good experience",
            "review_text": "This was a great experience overall. Highly recommended!",
            "is_anonymous": 1,
            "status": "Draft"
        })

        review.set_display_name()
        self.assertEqual(review.display_name, "J***h")

    def test_display_name_non_anonymous(self):
        """Test display name for non-anonymous reviews."""
        review = frappe.get_doc({
            "doctype": "Review",
            "review_type": "Order Experience",
            "reviewer": "test_reviewer@test.com",
            "reviewer_name": "John Smith",
            "rating": 4,
            "title": "Good experience",
            "review_text": "This was a great experience overall. Highly recommended!",
            "is_anonymous": 0,
            "status": "Draft"
        })

        review.set_display_name()
        self.assertEqual(review.display_name, "John Smith")

    def test_helpfulness_score_calculation(self):
        """Test helpfulness score calculation."""
        review = frappe.get_doc({
            "doctype": "Review",
            "review_type": "Order Experience",
            "reviewer": "test_reviewer@test.com",
            "rating": 5,
            "title": "Excellent",
            "review_text": "This is an excellent review that helps others make decisions.",
            "status": "Draft",
            "helpful_count": 8,
            "unhelpful_count": 2
        })

        review.calculate_helpfulness_score()
        self.assertEqual(review.helpfulness_score, 80.0)  # 8/10 * 100

    def test_helpfulness_score_no_votes(self):
        """Test helpfulness score with no votes."""
        review = frappe.get_doc({
            "doctype": "Review",
            "review_type": "Order Experience",
            "reviewer": "test_reviewer@test.com",
            "rating": 5,
            "title": "New Review",
            "review_text": "This is a brand new review with no votes yet.",
            "status": "Draft",
            "helpful_count": 0,
            "unhelpful_count": 0
        })

        review.calculate_helpfulness_score()
        self.assertEqual(review.helpfulness_score, 0)

    def test_spam_detection(self):
        """Test spam pattern detection."""
        review = frappe.get_doc({
            "doctype": "Review",
            "review_type": "Order Experience",
            "reviewer": "test_reviewer@test.com",
            "rating": 5,
            "status": "Draft"
        })

        # Test spam patterns
        self.assertTrue(review.contains_spam_patterns("Buy now at http://spam.com"))
        self.assertTrue(review.contains_spam_patterns("Check bit.ly/spam for discount"))
        self.assertTrue(review.contains_spam_patterns("AAAAAAAAAAAA repeated text"))
        self.assertFalse(review.contains_spam_patterns("This is a legitimate review"))

    def test_detailed_ratings_validation(self):
        """Test detailed ratings boundary validation."""
        review = frappe.get_doc({
            "doctype": "Review",
            "review_type": "Order Experience",
            "reviewer": "test_reviewer@test.com",
            "rating": 4,
            "title": "Test",
            "review_text": "This is a test review with enough characters to pass validation.",
            "status": "Draft",
            "product_quality_rating": 10,  # Invalid - too high
            "value_for_money_rating": -5,  # Invalid - negative
            "shipping_rating": 3,  # Valid
            "seller_communication_rating": 0,  # Valid
            "accuracy_rating": 5  # Valid
        })

        review.validate_detailed_ratings()

        self.assertEqual(review.product_quality_rating, 5)  # Capped at 5
        self.assertEqual(review.value_for_money_rating, 0)  # Capped at 0
        self.assertEqual(review.shipping_rating, 3)  # Unchanged
        self.assertEqual(review.accuracy_rating, 5)  # Unchanged

    def test_check_review_eligibility_static(self):
        """Test static eligibility check method."""
        from tradehub_compliance.tradehub_compliance.doctype.review.review import Review

        # Test without listing/seller
        result = Review.check_review_eligibility(
            "test_reviewer@test.com",
            listing=None,
            seller=None
        )

        self.assertFalse(result["eligible"])
        self.assertIn("required", result["reason"].lower())

    def test_get_display_data(self):
        """Test get_display_data method."""
        review = frappe.get_doc({
            "doctype": "Review",
            "review_type": "Order Experience",
            "reviewer": "test_reviewer@test.com",
            "rating": 4,
            "title": "Good Product",
            "review_text": "This product is really good. I recommend it to everyone.",
            "pros": "Good quality\nFast shipping",
            "cons": "A bit expensive",
            "status": "Published",
            "is_verified_purchase": 1,
            "helpful_count": 5,
            "unhelpful_count": 1
        })

        review.insert(ignore_permissions=True)
        data = review.get_display_data()

        self.assertEqual(data["rating"], 4)
        self.assertEqual(data["title"], "Good Product")
        self.assertTrue(data["is_verified_purchase"])
        self.assertEqual(data["helpful_count"], 5)
        self.assertIn("detailed_ratings", data)

    def test_review_status_workflow(self):
        """Test review status transitions."""
        review = frappe.get_doc({
            "doctype": "Review",
            "review_type": "Order Experience",
            "reviewer": "test_reviewer@test.com",
            "rating": 4,
            "title": "Workflow Test",
            "review_text": "Testing the review workflow with all status transitions.",
            "status": "Draft"
        })
        review.insert(ignore_permissions=True)

        # Test submit for review
        review.submit_for_review()
        self.assertEqual(review.status, "Pending Review")
        self.assertEqual(review.moderation_status, "Pending")

        # Test approve
        review.approve()
        self.assertEqual(review.status, "Published")
        self.assertEqual(review.moderation_status, "Approved")
        self.assertIsNotNone(review.published_at)

    def test_review_rejection(self):
        """Test review rejection."""
        review = frappe.get_doc({
            "doctype": "Review",
            "review_type": "Order Experience",
            "reviewer": "test_reviewer@test.com",
            "rating": 1,
            "title": "Rejection Test",
            "review_text": "This review will be rejected during the test.",
            "status": "Pending Review",
            "moderation_status": "Pending"
        })
        review.insert(ignore_permissions=True)

        # Test reject
        review.reject(reason="Spam", notes="Contains promotional content")
        self.assertEqual(review.status, "Rejected")
        self.assertEqual(review.moderation_status, "Rejected")
        self.assertEqual(review.rejection_reason, "Spam")

    def test_flag_review(self):
        """Test flagging a review."""
        review = frappe.get_doc({
            "doctype": "Review",
            "review_type": "Order Experience",
            "reviewer": "test_reviewer@test.com",
            "rating": 3,
            "title": "Flag Test",
            "review_text": "This review will be flagged multiple times for testing.",
            "status": "Published",
            "moderation_status": "Approved"
        })
        review.insert(ignore_permissions=True)

        # Flag multiple times
        review.flag(flag_type="spam", reporter="user1@test.com")
        self.assertEqual(review.report_count, 1)

        review.flag(flag_type="inappropriate", reporter="user2@test.com")
        self.assertEqual(review.report_count, 2)

        review.flag(flag_type="fake", reporter="user3@test.com")
        self.assertEqual(review.report_count, 3)
        self.assertEqual(review.moderation_status, "Flagged")

    def test_seller_response(self):
        """Test adding seller response to review."""
        review = frappe.get_doc({
            "doctype": "Review",
            "review_type": "Order Experience",
            "reviewer": "test_reviewer@test.com",
            "rating": 2,
            "title": "Response Test",
            "review_text": "This review needs a response from the seller.",
            "status": "Published"
        })
        review.insert(ignore_permissions=True)

        # Add response (with permission override for test)
        frappe.set_user("Administrator")
        result = review.add_seller_response("Thank you for your feedback. We apologize for the inconvenience.")

        self.assertEqual(result["status"], "success")
        self.assertTrue(review.has_seller_response)
        self.assertIsNotNone(review.seller_response)
        self.assertIsNotNone(review.seller_response_at)

    def test_edit_seller_response(self):
        """Test editing seller response."""
        review = frappe.get_doc({
            "doctype": "Review",
            "review_type": "Order Experience",
            "reviewer": "test_reviewer@test.com",
            "rating": 2,
            "title": "Edit Response Test",
            "review_text": "Testing seller response editing functionality here.",
            "status": "Published",
            "has_seller_response": 1,
            "seller_response": "Initial response"
        })
        review.insert(ignore_permissions=True)

        result = review.edit_seller_response("Updated response with more details")

        self.assertEqual(result["status"], "success")
        self.assertEqual(review.seller_response, "Updated response with more details")

    def test_remove_seller_response(self):
        """Test removing seller response."""
        review = frappe.get_doc({
            "doctype": "Review",
            "review_type": "Order Experience",
            "reviewer": "test_reviewer@test.com",
            "rating": 2,
            "title": "Remove Response Test",
            "review_text": "Testing seller response removal functionality here.",
            "status": "Published",
            "has_seller_response": 1,
            "seller_response": "Response to remove"
        })
        review.insert(ignore_permissions=True)

        result = review.remove_seller_response()

        self.assertEqual(result["status"], "success")
        self.assertFalse(review.has_seller_response)
        self.assertIsNone(review.seller_response)

    def test_hide_review(self):
        """Test hiding a review."""
        review = frappe.get_doc({
            "doctype": "Review",
            "review_type": "Order Experience",
            "reviewer": "test_reviewer@test.com",
            "rating": 3,
            "title": "Hide Test",
            "review_text": "This review will be hidden from public view.",
            "status": "Published"
        })
        review.insert(ignore_permissions=True)

        review.hide(reason="Under investigation")
        self.assertEqual(review.status, "Hidden")
        self.assertIn("Hidden:", review.moderation_notes)

    def test_remove_review(self):
        """Test soft-deleting a review."""
        review = frappe.get_doc({
            "doctype": "Review",
            "review_type": "Order Experience",
            "reviewer": "test_reviewer@test.com",
            "rating": 1,
            "title": "Remove Test",
            "review_text": "This review will be removed (soft deleted).",
            "status": "Published"
        })
        review.insert(ignore_permissions=True)

        review.remove(reason="Violates community guidelines")
        self.assertEqual(review.status, "Removed")

    def test_api_create_review(self):
        """Test create_review API endpoint."""
        from tradehub_compliance.tradehub_compliance.doctype.review.review import check_review_eligibility

        # Test eligibility check (without actual listing/seller)
        result = check_review_eligibility(listing=None, seller=None)

        self.assertFalse(result["eligible"])

    def test_api_get_review_statistics(self):
        """Test get_review_statistics API endpoint."""
        from tradehub_compliance.tradehub_compliance.doctype.review.review import get_review_statistics

        stats = get_review_statistics(days=30)

        self.assertIn("total_reviews", stats)
        self.assertIn("pending_moderation", stats)
        self.assertIn("average_rating", stats)
        self.assertIn("verified_percentage", stats)

    def test_media_validation_image_limit(self):
        """Test image limit validation."""
        import json

        review = frappe.get_doc({
            "doctype": "Review",
            "review_type": "Order Experience",
            "reviewer": "test_reviewer@test.com",
            "rating": 5,
            "title": "Media Test",
            "review_text": "Testing media validation with too many images.",
            "status": "Draft",
            "images": json.dumps([
                "/files/img1.jpg",
                "/files/img2.jpg",
                "/files/img3.jpg",
                "/files/img4.jpg",
                "/files/img5.jpg",
                "/files/img6.jpg"  # 6th image - should fail
            ])
        })

        with self.assertRaises(frappe.ValidationError):
            review.validate_media()

    def test_video_url_validation(self):
        """Test video URL validation."""
        review = frappe.get_doc({
            "doctype": "Review",
            "review_type": "Order Experience",
            "reviewer": "test_reviewer@test.com",
            "rating": 5,
            "title": "Video Test",
            "review_text": "Testing video URL validation functionality here.",
            "status": "Draft"
        })

        # Valid YouTube URL
        review.video_url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
        review.validate_media()  # Should not raise

        # Invalid URL
        review.video_url = "https://somesite.com/video.mp4"
        with self.assertRaises(frappe.ValidationError):
            review.validate_media()

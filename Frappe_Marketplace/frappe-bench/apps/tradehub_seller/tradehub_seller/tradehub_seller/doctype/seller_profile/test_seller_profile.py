# Copyright (c) 2024, TR TradeHub and Contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase


class TestSellerProfile(FrappeTestCase):
    """Test cases for Seller Profile DocType."""

    def setUp(self):
        """Set up test fixtures."""
        # Create test user if not exists
        if not frappe.db.exists("User", "test_seller@example.com"):
            test_user = frappe.get_doc({
                "doctype": "User",
                "email": "test_seller@example.com",
                "first_name": "Test",
                "last_name": "Seller",
                "send_welcome_email": 0
            })
            test_user.insert(ignore_permissions=True)

    def tearDown(self):
        """Clean up test data."""
        # Delete test seller profiles
        for seller in frappe.get_all("Seller Profile", filters={"seller_name": ["like", "Test%"]}):
            frappe.delete_doc("Seller Profile", seller.name, force=True)

    def test_seller_profile_creation(self):
        """Test basic seller profile creation."""
        seller = frappe.get_doc({
            "doctype": "Seller Profile",
            "seller_name": "Test Seller",
            "user": "test_seller@example.com",
            "seller_type": "Individual",
            "contact_email": "test_seller@example.com",
            "address_line_1": "Test Address",
            "city": "Istanbul",
            "country": "Turkey"
        })
        seller.insert(ignore_permissions=True)

        self.assertIsNotNone(seller.name)
        self.assertEqual(seller.status, "Pending")
        self.assertEqual(seller.verification_status, "Pending")
        self.assertIsNotNone(seller.joined_at)

    def test_vkn_validation_valid(self):
        """Test valid VKN validation."""
        from tradehub_seller.tradehub_seller.doctype.seller_profile.seller_profile import SellerProfile

        seller = SellerProfile({})

        # Valid VKN example (synthetic)
        # Note: Real VKN should be used in production tests
        valid_vkn = "1234567890"  # Placeholder - use real test VKN
        # The actual test would use a known-valid VKN

    def test_vkn_validation_invalid_length(self):
        """Test VKN validation with invalid length."""
        seller = frappe.get_doc({
            "doctype": "Seller Profile",
            "seller_name": "Test Seller Invalid VKN",
            "user": "test_seller@example.com",
            "seller_type": "Business",
            "contact_email": "test_seller@example.com",
            "address_line_1": "Test Address",
            "city": "Istanbul",
            "country": "Turkey",
            "tax_id": "12345",  # Invalid - too short
            "tax_id_type": "VKN"
        })

        with self.assertRaises(frappe.ValidationError):
            seller.insert(ignore_permissions=True)

    def test_tckn_validation_valid(self):
        """Test valid TCKN validation."""
        from tradehub_seller.tradehub_seller.doctype.seller_profile.seller_profile import SellerProfile

        seller = SellerProfile({})

        # Test TCKN: 10000000146 is a known valid test TCKN
        valid_tckn = "10000000146"
        result = seller.validate_tckn_checksum(valid_tckn)
        self.assertTrue(result)

    def test_tckn_validation_invalid(self):
        """Test invalid TCKN validation."""
        from tradehub_seller.tradehub_seller.doctype.seller_profile.seller_profile import SellerProfile

        seller = SellerProfile({})

        # Invalid TCKN (wrong checksum)
        invalid_tckn = "10000000147"
        result = seller.validate_tckn_checksum(invalid_tckn)
        self.assertFalse(result)

    def test_tckn_validation_starts_with_zero(self):
        """Test TCKN validation when starting with zero (invalid)."""
        from tradehub_seller.tradehub_seller.doctype.seller_profile.seller_profile import SellerProfile

        seller = SellerProfile({})

        # TCKN cannot start with 0
        invalid_tckn = "01234567890"
        result = seller.validate_tckn_checksum(invalid_tckn)
        self.assertFalse(result)

    def test_iban_validation_valid(self):
        """Test valid Turkish IBAN validation."""
        from tradehub_seller.tradehub_seller.doctype.seller_profile.seller_profile import SellerProfile

        seller = SellerProfile({})

        # Valid Turkish IBAN format (test IBAN)
        valid_iban = "TR330006100519786457841326"
        result = seller.validate_iban_checksum(valid_iban)
        self.assertTrue(result)

    def test_iban_validation_invalid(self):
        """Test invalid IBAN validation."""
        from tradehub_seller.tradehub_seller.doctype.seller_profile.seller_profile import SellerProfile

        seller = SellerProfile({})

        # Invalid IBAN (wrong checksum)
        invalid_iban = "TR330006100519786457841327"
        result = seller.validate_iban_checksum(invalid_iban)
        self.assertFalse(result)

    def test_seller_verification_workflow(self):
        """Test seller verification workflow."""
        seller = frappe.get_doc({
            "doctype": "Seller Profile",
            "seller_name": "Test Verification Seller",
            "user": "test_seller@example.com",
            "seller_type": "Individual",
            "contact_email": "test_seller@example.com",
            "address_line_1": "Test Address",
            "city": "Istanbul",
            "country": "Turkey"
        })
        seller.insert(ignore_permissions=True)

        # Initial status
        self.assertEqual(seller.verification_status, "Pending")
        self.assertFalse(seller.can_sell)

        # Mark as verified
        seller.mark_verified()

        self.assertEqual(seller.verification_status, "Verified")
        self.assertEqual(seller.status, "Active")
        self.assertTrue(seller.can_sell)
        self.assertTrue(seller.can_withdraw)
        self.assertTrue(seller.can_create_listings)
        self.assertIsNotNone(seller.verified_at)

    def test_seller_rejection_workflow(self):
        """Test seller rejection workflow."""
        seller = frappe.get_doc({
            "doctype": "Seller Profile",
            "seller_name": "Test Rejection Seller",
            "user": "test_seller@example.com",
            "seller_type": "Individual",
            "contact_email": "test_seller@example.com",
            "address_line_1": "Test Address",
            "city": "Istanbul",
            "country": "Turkey"
        })
        seller.insert(ignore_permissions=True)

        # Reject with reason
        seller.mark_rejected("Invalid documents provided")

        self.assertEqual(seller.verification_status, "Rejected")
        self.assertIn("Rejected:", seller.verification_notes)

    def test_seller_suspension(self):
        """Test seller suspension."""
        seller = frappe.get_doc({
            "doctype": "Seller Profile",
            "seller_name": "Test Suspension Seller",
            "user": "test_seller@example.com",
            "seller_type": "Individual",
            "contact_email": "test_seller@example.com",
            "address_line_1": "Test Address",
            "city": "Istanbul",
            "country": "Turkey"
        })
        seller.insert(ignore_permissions=True)
        seller.mark_verified()

        # Suspend seller
        seller.suspend("Policy violation")

        self.assertEqual(seller.status, "Suspended")
        self.assertTrue(seller.is_restricted)
        self.assertFalse(seller.can_sell)

    def test_vacation_mode(self):
        """Test vacation mode functionality."""
        seller = frappe.get_doc({
            "doctype": "Seller Profile",
            "seller_name": "Test Vacation Seller",
            "user": "test_seller@example.com",
            "seller_type": "Individual",
            "contact_email": "test_seller@example.com",
            "address_line_1": "Test Address",
            "city": "Istanbul",
            "country": "Turkey",
            "status": "Active"
        })
        seller.insert(ignore_permissions=True)

        # Enable vacation mode
        seller.vacation_mode = 1
        seller.save()

        self.assertEqual(seller.status, "Vacation")

        # Disable vacation mode
        seller.vacation_mode = 0
        seller.save()

        self.assertEqual(seller.status, "Active")

    def test_badge_management(self):
        """Test badge add/remove functionality."""
        seller = frappe.get_doc({
            "doctype": "Seller Profile",
            "seller_name": "Test Badge Seller",
            "user": "test_seller@example.com",
            "seller_type": "Individual",
            "contact_email": "test_seller@example.com",
            "address_line_1": "Test Address",
            "city": "Istanbul",
            "country": "Turkey"
        })
        seller.insert(ignore_permissions=True)

        # Add badge
        result = seller.add_badge("top_rated", "Top Rated Seller", "Achieved 4.9+ rating")
        self.assertTrue(result)
        self.assertTrue(seller.has_badge("top_rated"))

        # Try to add same badge again
        result = seller.add_badge("top_rated", "Top Rated Seller")
        self.assertFalse(result)

        # Remove badge
        seller.remove_badge("top_rated")
        self.assertFalse(seller.has_badge("top_rated"))

    def test_score_calculation(self):
        """Test seller score calculation."""
        seller = frappe.get_doc({
            "doctype": "Seller Profile",
            "seller_name": "Test Score Seller",
            "user": "test_seller@example.com",
            "seller_type": "Individual",
            "contact_email": "test_seller@example.com",
            "address_line_1": "Test Address",
            "city": "Istanbul",
            "country": "Turkey",
            "average_rating": 4.5,
            "order_fulfillment_rate": 95,
            "on_time_delivery_rate": 90,
            "return_rate": 5,
            "cancellation_rate": 2,
            "positive_feedback_rate": 92
        })
        seller.insert(ignore_permissions=True)

        score = seller.recalculate_score()

        # Score should be a positive number
        self.assertGreater(score, 0)
        self.assertLessEqual(score, 100)

    def test_can_accept_orders(self):
        """Test order acceptance eligibility."""
        seller = frappe.get_doc({
            "doctype": "Seller Profile",
            "seller_name": "Test Orders Seller",
            "user": "test_seller@example.com",
            "seller_type": "Individual",
            "contact_email": "test_seller@example.com",
            "address_line_1": "Test Address",
            "city": "Istanbul",
            "country": "Turkey"
        })
        seller.insert(ignore_permissions=True)

        # Pending seller cannot accept orders
        self.assertFalse(seller.can_accept_orders())

        # Verify and activate
        seller.mark_verified()
        self.assertTrue(seller.can_accept_orders())

        # Vacation mode
        seller.vacation_mode = 1
        seller.save()
        self.assertFalse(seller.can_accept_orders())


class TestSellerProfileAPI(FrappeTestCase):
    """Test cases for Seller Profile API endpoints."""

    def test_validate_tckn_api(self):
        """Test TCKN validation API."""
        from tradehub_seller.tradehub_seller.doctype.seller_profile.seller_profile import validate_tax_id

        # Valid TCKN
        result = validate_tax_id("10000000146", "TCKN")
        self.assertTrue(result["is_valid"])

        # Invalid TCKN
        result = validate_tax_id("10000000147", "TCKN")
        self.assertFalse(result["is_valid"])

    def test_validate_iban_api(self):
        """Test IBAN validation API."""
        from tradehub_seller.tradehub_seller.doctype.seller_profile.seller_profile import validate_iban

        # Valid IBAN
        result = validate_iban("TR330006100519786457841326")
        self.assertTrue(result["is_valid"])

        # Invalid IBAN (wrong length)
        result = validate_iban("TR33000610051978645784")
        self.assertFalse(result["is_valid"])

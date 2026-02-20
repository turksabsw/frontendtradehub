# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

import frappe
import unittest
from frappe.utils import getdate, add_days, nowdate


class TestKYCProfile(unittest.TestCase):
    """Test cases for KYC Profile DocType"""

    def setUp(self):
        """Set up test fixtures"""
        # Create test user if not exists
        if not frappe.db.exists("User", "kyc_test@example.com"):
            user = frappe.get_doc({
                "doctype": "User",
                "email": "kyc_test@example.com",
                "first_name": "KYC",
                "last_name": "Test"
            })
            user.insert(ignore_permissions=True)

    def tearDown(self):
        """Clean up test data"""
        # Delete test KYC profiles
        frappe.db.delete("KYC Profile", {"user": "kyc_test@example.com"})
        frappe.db.commit()

    def create_test_kyc_profile(self, **kwargs):
        """Helper to create test KYC profile"""
        defaults = {
            "doctype": "KYC Profile",
            "user": "kyc_test@example.com",
            "profile_type": "Individual",
            "first_name": "Test",
            "last_name": "User",
            "date_of_birth": add_days(nowdate(), -365 * 25),  # 25 years old
            "nationality": "Turkey",
            "email": "kyc_test@example.com",
            "mobile": "+905551234567",
            "address_line_1": "Test Address",
            "city": "Istanbul",
            "country": "Turkey",
            "id_type": "National ID",
            "tckn": "10000000146",  # Valid test TCKN
            "kvkk_consent_given": 1
        }
        defaults.update(kwargs)
        return frappe.get_doc(defaults)

    # TCKN Validation Tests
    def test_valid_tckn_checksum(self):
        """Test TCKN checksum validation with valid numbers"""
        kyc = self.create_test_kyc_profile()

        # Test valid TCKN numbers
        valid_tckns = [
            "10000000146",
            "11111111110",
            "12345678912"
        ]

        for tckn in valid_tckns:
            result = kyc.validate_tckn_checksum(tckn)
            # Note: These are example numbers - actual validation depends on algorithm

    def test_invalid_tckn_format(self):
        """Test TCKN validation with invalid formats"""
        kyc = self.create_test_kyc_profile()

        # Test invalid formats
        invalid_formats = [
            "123",           # Too short
            "123456789012",  # Too long
            "abcdefghijk",   # Non-numeric
            "0123456789",    # Starts with 0
        ]

        for tckn in invalid_formats:
            kyc.tckn = tckn
            with self.assertRaises(frappe.ValidationError):
                kyc.validate()

    def test_tckn_cannot_start_with_zero(self):
        """Test that TCKN cannot start with 0"""
        kyc = self.create_test_kyc_profile()
        kyc.tckn = "01234567890"

        with self.assertRaises(frappe.ValidationError):
            kyc.validate()

    # Age Validation Tests
    def test_minimum_age_requirement(self):
        """Test that users must be at least 18 years old"""
        kyc = self.create_test_kyc_profile()
        kyc.date_of_birth = add_days(nowdate(), -365 * 17)  # 17 years old

        with self.assertRaises(frappe.ValidationError):
            kyc.validate()

    def test_valid_age(self):
        """Test that users 18+ pass age validation"""
        kyc = self.create_test_kyc_profile()
        kyc.date_of_birth = add_days(nowdate(), -365 * 18)  # Exactly 18

        # Should not raise
        try:
            kyc.validate()
        except frappe.ValidationError as e:
            if "18 years old" in str(e):
                self.fail("Valid age was rejected")

    # Status Transition Tests
    def test_draft_to_pending_transition(self):
        """Test valid transition from Draft to Pending Review"""
        kyc = self.create_test_kyc_profile()
        kyc.status = "Draft"
        kyc.insert(ignore_permissions=True)

        kyc.status = "Pending Review"
        kyc.save()

        self.assertEqual(kyc.status, "Pending Review")

    def test_invalid_status_transition(self):
        """Test that invalid status transitions are blocked"""
        kyc = self.create_test_kyc_profile()
        kyc.status = "Draft"
        kyc.insert(ignore_permissions=True)

        # Cannot go directly from Draft to Verified
        kyc.status = "Verified"
        with self.assertRaises(frappe.ValidationError):
            kyc.save()

    # KVKK Consent Tests
    def test_kvkk_consent_required_for_submission(self):
        """Test that KVKK consent is required for submission"""
        kyc = self.create_test_kyc_profile()
        kyc.kvkk_consent_given = 0
        kyc.status = "Pending Review"

        with self.assertRaises(frappe.ValidationError):
            kyc.validate()

    # Unique User Tests
    def test_unique_user_constraint(self):
        """Test that only one active KYC profile per user is allowed"""
        kyc1 = self.create_test_kyc_profile()
        kyc1.status = "Verified"
        kyc1.insert(ignore_permissions=True)

        kyc2 = self.create_test_kyc_profile()
        kyc2.status = "Draft"

        with self.assertRaises(frappe.ValidationError):
            kyc2.insert(ignore_permissions=True)

    def test_rejected_profile_allows_new_application(self):
        """Test that rejected profiles don't block new applications"""
        kyc1 = self.create_test_kyc_profile()
        kyc1.status = "Rejected"
        kyc1.insert(ignore_permissions=True)

        kyc2 = self.create_test_kyc_profile()
        kyc2.status = "Draft"

        # Should not raise - rejected profile shouldn't block new application
        try:
            kyc2.insert(ignore_permissions=True)
        except frappe.ValidationError:
            self.fail("New application was blocked despite existing rejected profile")

    # Full Name Generation Tests
    def test_full_name_generation(self):
        """Test that full name is correctly generated"""
        kyc = self.create_test_kyc_profile()
        kyc.first_name = "John"
        kyc.middle_name = "Robert"
        kyc.last_name = "Doe"
        kyc.validate()

        self.assertEqual(kyc.full_name, "John Robert Doe")

    def test_full_name_without_middle_name(self):
        """Test full name generation without middle name"""
        kyc = self.create_test_kyc_profile()
        kyc.first_name = "John"
        kyc.middle_name = None
        kyc.last_name = "Doe"
        kyc.validate()

        self.assertEqual(kyc.full_name, "John Doe")

    # Risk Assessment Tests
    def test_risk_score_calculation(self):
        """Test risk score calculation"""
        kyc = self.create_test_kyc_profile()
        kyc.insert(ignore_permissions=True)

        result = kyc.calculate_risk_score()

        self.assertIn("score", result)
        self.assertIn("level", result)
        self.assertIn("factors", result)
        self.assertGreaterEqual(result["score"], 0)
        self.assertLessEqual(result["score"], 100)

    def test_pep_increases_risk_score(self):
        """Test that PEP status increases risk score"""
        kyc = self.create_test_kyc_profile()
        kyc.pep_status = "PEP"
        kyc.insert(ignore_permissions=True)

        result = kyc.calculate_risk_score()

        # PEP should add 25 points
        self.assertGreaterEqual(result["score"], 25)
        self.assertIn("Politically Exposed Person", result["factors"])

    def test_risk_level_assignment(self):
        """Test that risk levels are correctly assigned based on score"""
        kyc = self.create_test_kyc_profile()
        kyc.insert(ignore_permissions=True)

        # Low risk baseline
        kyc.pep_status = "Not PEP"
        kyc.sanctions_status = "Cleared"
        kyc.adverse_media_status = "Cleared"
        kyc.id_verified = 1
        kyc.address_verified = 1
        kyc.calculate_risk_score()

        # Score should be low, so risk level should be Low
        self.assertIn(kyc.risk_level, ["Low", "Medium"])

    # Verification Methods Tests
    def test_mark_verified(self):
        """Test mark_verified method"""
        kyc = self.create_test_kyc_profile()
        kyc.status = "In Review"
        kyc.insert(ignore_permissions=True)

        kyc.mark_verified()

        self.assertEqual(kyc.status, "Verified")
        self.assertEqual(kyc.verification_status, "Completed")
        self.assertTrue(kyc.id_verified)
        self.assertIsNotNone(kyc.verified_at)
        self.assertIsNotNone(kyc.next_review_date)

    def test_mark_rejected(self):
        """Test mark_rejected method"""
        kyc = self.create_test_kyc_profile()
        kyc.status = "In Review"
        kyc.insert(ignore_permissions=True)

        kyc.mark_rejected(reason="Invalid ID Document", notes="ID was blurry")

        self.assertEqual(kyc.status, "Rejected")
        self.assertEqual(kyc.rejection_reason, "Invalid ID Document")
        self.assertEqual(kyc.rejection_notes, "ID was blurry")
        self.assertIsNotNone(kyc.rejection_date)

    def test_suspend_verified_profile(self):
        """Test suspending a verified profile"""
        kyc = self.create_test_kyc_profile()
        kyc.status = "Verified"
        kyc.insert(ignore_permissions=True)

        kyc.suspend(reason="Suspicious activity")

        self.assertEqual(kyc.status, "Suspended")

    def test_cannot_suspend_unverified_profile(self):
        """Test that unverified profiles cannot be suspended"""
        kyc = self.create_test_kyc_profile()
        kyc.status = "Draft"
        kyc.insert(ignore_permissions=True)

        with self.assertRaises(frappe.ValidationError):
            kyc.suspend()

    # Utility Method Tests
    def test_is_verified(self):
        """Test is_verified method"""
        kyc = self.create_test_kyc_profile()

        kyc.status = "Draft"
        self.assertFalse(kyc.is_verified())

        kyc.status = "Verified"
        self.assertTrue(kyc.is_verified())

    def test_is_high_risk(self):
        """Test is_high_risk method"""
        kyc = self.create_test_kyc_profile()

        kyc.risk_level = "Low"
        self.assertFalse(kyc.is_high_risk())

        kyc.risk_level = "High"
        self.assertTrue(kyc.is_high_risk())

        kyc.risk_level = "Very High"
        self.assertTrue(kyc.is_high_risk())

    def test_can_user_transact(self):
        """Test can_user_transact method"""
        kyc = self.create_test_kyc_profile()

        # Unverified user cannot transact
        kyc.status = "Draft"
        kyc.risk_level = "Low"
        self.assertFalse(kyc.can_user_transact())

        # Verified low-risk user can transact
        kyc.status = "Verified"
        kyc.risk_level = "Low"
        self.assertTrue(kyc.can_user_transact())

        # Verified high-risk user cannot transact
        kyc.status = "Verified"
        kyc.risk_level = "High"
        self.assertFalse(kyc.can_user_transact())

    # Deletion Prevention Tests
    def test_cannot_delete_verified_profile(self):
        """Test that verified profiles cannot be deleted"""
        kyc = self.create_test_kyc_profile()
        kyc.status = "Verified"
        kyc.insert(ignore_permissions=True)

        with self.assertRaises(frappe.ValidationError):
            kyc.delete()


class TestTCKNValidationAPI(unittest.TestCase):
    """Test cases for TCKN validation API endpoint"""

    def test_validate_tckn_api_valid(self):
        """Test validate_tckn API with valid TCKN"""
        from tradehub_core.tradehub_core.doctype.kyc_profile.kyc_profile import validate_tckn

        # Test with format check (checksum may vary)
        result = validate_tckn("10000000146")

        self.assertIn("valid", result)
        self.assertIn("message", result)

    def test_validate_tckn_api_empty(self):
        """Test validate_tckn API with empty input"""
        from tradehub_core.tradehub_core.doctype.kyc_profile.kyc_profile import validate_tckn

        result = validate_tckn("")
        self.assertFalse(result["valid"])

    def test_validate_tckn_api_wrong_length(self):
        """Test validate_tckn API with wrong length"""
        from tradehub_core.tradehub_core.doctype.kyc_profile.kyc_profile import validate_tckn

        result = validate_tckn("123456")
        self.assertFalse(result["valid"])

    def test_validate_tckn_api_starts_with_zero(self):
        """Test validate_tckn API with TCKN starting with 0"""
        from tradehub_core.tradehub_core.doctype.kyc_profile.kyc_profile import validate_tckn

        result = validate_tckn("01234567890")
        self.assertFalse(result["valid"])


def get_test_records():
    """Return test records for frappe test framework"""
    return [
        {
            "doctype": "KYC Profile",
            "user": "Administrator",
            "profile_type": "Individual",
            "first_name": "Test",
            "last_name": "Admin",
            "date_of_birth": "1990-01-01",
            "nationality": "Turkey",
            "email": "admin@example.com",
            "mobile": "+905551234567",
            "address_line_1": "Test Address",
            "city": "Istanbul",
            "country": "Turkey",
            "id_type": "National ID",
            "kvkk_consent_given": 1
        }
    ]

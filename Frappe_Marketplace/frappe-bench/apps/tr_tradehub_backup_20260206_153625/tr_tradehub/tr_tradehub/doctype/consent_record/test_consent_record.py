# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import nowdate, now_datetime, add_days


class TestConsentRecord(FrappeTestCase):
    """Test cases for Consent Record DocType."""

    def setUp(self):
        """Set up test fixtures."""
        # Create a test user if not exists
        if not frappe.db.exists("User", "test_consent@example.com"):
            test_user = frappe.get_doc({
                "doctype": "User",
                "email": "test_consent@example.com",
                "first_name": "Test",
                "last_name": "Consent User",
                "enabled": 1,
                "send_welcome_email": 0
            })
            test_user.insert(ignore_permissions=True)
        self.test_user = "test_consent@example.com"

    def tearDown(self):
        """Clean up test data."""
        # Delete test consent records
        frappe.db.delete("Consent Record", {"user": self.test_user})
        frappe.db.commit()

    def create_consent_record(self, consent_type="Data Processing", purpose="Testing", **kwargs):
        """Helper to create a consent record."""
        consent = frappe.get_doc({
            "doctype": "Consent Record",
            "user": self.test_user,
            "consent_type": consent_type,
            "purpose": purpose,
            "legal_basis": kwargs.get("legal_basis", "Consent"),
            "is_given": kwargs.get("is_given", 1),
            "given_at": kwargs.get("given_at", now_datetime()),
            "given_via": kwargs.get("given_via", "Web Form"),
            **{k: v for k, v in kwargs.items() if k not in ["legal_basis", "is_given", "given_at", "given_via"]}
        })
        consent.insert(ignore_permissions=True)
        return consent

    def test_consent_record_creation(self):
        """Test creating a basic consent record."""
        consent = self.create_consent_record()

        self.assertEqual(consent.consent_type, "Data Processing")
        self.assertEqual(consent.purpose, "Testing")
        self.assertEqual(consent.user, self.test_user)
        self.assertTrue(consent.is_given)
        self.assertEqual(consent.status, "Active")

    def test_consent_record_status_default(self):
        """Test that consent status defaults correctly."""
        consent = self.create_consent_record()
        self.assertEqual(consent.status, "Active")

    def test_consent_requires_user(self):
        """Test that consent record requires a user."""
        with self.assertRaises(frappe.exceptions.MandatoryError):
            consent = frappe.get_doc({
                "doctype": "Consent Record",
                "consent_type": "Data Processing",
                "purpose": "Testing"
            })
            consent.insert()

    def test_consent_requires_consent_type(self):
        """Test that consent record requires consent type."""
        with self.assertRaises(frappe.exceptions.MandatoryError):
            consent = frappe.get_doc({
                "doctype": "Consent Record",
                "user": self.test_user,
                "purpose": "Testing"
            })
            consent.insert()

    def test_consent_withdrawal(self):
        """Test consent withdrawal."""
        consent = self.create_consent_record()
        consent_name = consent.name

        # Reload and withdraw
        consent = frappe.get_doc("Consent Record", consent_name)
        result = consent.withdraw_consent(reason="No longer interested")

        self.assertEqual(result["status"], "success")
        self.assertTrue(consent.is_withdrawn)
        self.assertEqual(consent.status, "Withdrawn")
        self.assertIsNotNone(consent.withdrawn_at)
        self.assertEqual(consent.withdrawal_reason, "No longer interested")

    def test_double_withdrawal_error(self):
        """Test that withdrawing already withdrawn consent throws error."""
        consent = self.create_consent_record()
        consent.withdraw_consent(reason="First withdrawal")

        with self.assertRaises(frappe.exceptions.ValidationError):
            consent.withdraw_consent(reason="Second withdrawal")

    def test_consent_expiry(self):
        """Test consent with expiry date."""
        consent = self.create_consent_record(
            has_expiry=1,
            expiry_date=add_days(nowdate(), 30)
        )

        self.assertTrue(consent.has_expiry)
        self.assertIsNotNone(consent.expiry_date)
        self.assertTrue(consent.is_active())

    def test_expired_consent(self):
        """Test that expired consent is not active."""
        consent = self.create_consent_record(
            has_expiry=1,
            expiry_date=add_days(nowdate(), -1)  # Yesterday
        )

        self.assertFalse(consent.is_active())
        self.assertEqual(consent.status, "Expired")

    def test_third_party_consent_validation(self):
        """Test third party consent requires third party name."""
        with self.assertRaises(frappe.exceptions.ValidationError):
            consent = frappe.get_doc({
                "doctype": "Consent Record",
                "user": self.test_user,
                "consent_type": "Third Party Sharing",
                "purpose": "Share with partner",
                "is_given": 1,
                "given_via": "Web Form"
            })
            consent.insert()

    def test_third_party_consent_with_name(self):
        """Test third party consent with valid data."""
        consent = self.create_consent_record(
            consent_type="Third Party Sharing",
            purpose="Share with partner",
            involves_third_party=1,
            third_party_name="Partner Corp"
        )

        self.assertTrue(consent.involves_third_party)
        self.assertEqual(consent.third_party_name, "Partner Corp")

    def test_consent_verification(self):
        """Test consent verification (double opt-in)."""
        consent = self.create_consent_record(
            consent_type="Marketing Communications",
            status="Pending Verification"
        )
        consent.verification_reference = "test_token_123"
        consent.save()

        # Verify consent
        result = consent.verify_consent(verification_token="test_token_123")

        self.assertEqual(result["status"], "success")
        self.assertTrue(consent.is_verified)
        self.assertTrue(consent.double_opt_in_completed)
        self.assertEqual(consent.status, "Active")

    def test_invalid_verification_token(self):
        """Test that invalid verification token is rejected."""
        consent = self.create_consent_record(
            consent_type="Marketing Communications",
            status="Pending Verification"
        )
        consent.verification_reference = "correct_token"
        consent.save()

        with self.assertRaises(frappe.exceptions.ValidationError):
            consent.verify_consent(verification_token="wrong_token")

    def test_consent_renewal(self):
        """Test consent renewal."""
        consent = self.create_consent_record(
            has_expiry=1,
            expiry_date=add_days(nowdate(), -1)
        )
        # Force status to expired
        consent.status = "Expired"
        consent.is_given = 0
        consent.save()

        # Renew consent
        new_expiry = add_days(nowdate(), 365)
        result = consent.renew_consent(new_expiry_date=new_expiry)

        self.assertEqual(result["status"], "success")
        self.assertEqual(consent.status, "Active")
        self.assertTrue(consent.is_given)
        self.assertEqual(str(consent.expiry_date), str(new_expiry))

    def test_consent_status_transitions(self):
        """Test valid and invalid status transitions."""
        consent = self.create_consent_record()

        # Valid transition: Active -> Withdrawn
        consent.is_withdrawn = 1
        consent.status = "Withdrawn"
        consent.save()  # Should not raise

        # Invalid transition: Withdrawn -> Active (should fail)
        with self.assertRaises(frappe.exceptions.ValidationError):
            consent.status = "Active"
            consent.save()

    def test_consent_cannot_be_deleted(self):
        """Test that consent records cannot be deleted."""
        consent = self.create_consent_record()

        with self.assertRaises(frappe.exceptions.ValidationError):
            consent.delete()

    def test_get_consent_summary(self):
        """Test get_consent_summary method."""
        consent = self.create_consent_record()
        summary = consent.get_consent_summary()

        self.assertEqual(summary["consent_type"], "Data Processing")
        self.assertEqual(summary["status"], "Active")
        self.assertTrue(summary["is_active"])
        self.assertIn("given_at", summary)

    def test_is_active_method(self):
        """Test is_active method for various states."""
        # Active consent
        consent1 = self.create_consent_record()
        self.assertTrue(consent1.is_active())

        # Withdrawn consent
        consent2 = self.create_consent_record(purpose="Test 2")
        consent2.withdraw_consent()
        self.assertFalse(consent2.is_active())

    def test_requires_double_opt_in(self):
        """Test requires_double_opt_in for different consent types."""
        # Marketing should require double opt-in
        consent1 = self.create_consent_record(consent_type="Marketing Communications")
        self.assertTrue(consent1.requires_double_opt_in())

        # Data Processing should not require double opt-in
        consent2 = self.create_consent_record(consent_type="Data Processing", purpose="Test 2")
        self.assertFalse(consent2.requires_double_opt_in())

    def test_data_deletion_request(self):
        """Test data deletion request on withdrawal."""
        consent = self.create_consent_record()
        consent.withdraw_consent(reason="Delete my data", request_deletion=True)

        self.assertTrue(consent.data_deletion_requested)


class TestConsentRecordAPI(FrappeTestCase):
    """Test cases for Consent Record API endpoints."""

    def setUp(self):
        """Set up test fixtures."""
        # Create a test user if not exists
        if not frappe.db.exists("User", "test_api_consent@example.com"):
            test_user = frappe.get_doc({
                "doctype": "User",
                "email": "test_api_consent@example.com",
                "first_name": "Test",
                "last_name": "API User",
                "enabled": 1,
                "send_welcome_email": 0
            })
            test_user.insert(ignore_permissions=True)
        self.test_user = "test_api_consent@example.com"

        # Set session user
        frappe.set_user(self.test_user)

    def tearDown(self):
        """Clean up test data."""
        frappe.set_user("Administrator")
        frappe.db.delete("Consent Record", {"user": self.test_user})
        frappe.db.commit()

    def test_record_consent_api(self):
        """Test record_consent API endpoint."""
        from tr_tradehub.doctype.consent_record.consent_record import record_consent

        result = record_consent(
            consent_type="Data Processing",
            purpose="Process my data",
            legal_basis="Consent"
        )

        self.assertEqual(result["status"], "success")
        self.assertIn("consent_name", result)

        # Verify consent was created
        consent = frappe.get_doc("Consent Record", result["consent_name"])
        self.assertEqual(consent.user, self.test_user)
        self.assertEqual(consent.consent_type, "Data Processing")

    def test_get_user_consents_api(self):
        """Test get_user_consents API endpoint."""
        from tr_tradehub.doctype.consent_record.consent_record import get_user_consents, record_consent

        # Create some consents
        record_consent(consent_type="Data Processing", purpose="Test 1")
        record_consent(consent_type="Marketing Communications", purpose="Test 2")

        # Get consents
        consents = get_user_consents()

        self.assertGreaterEqual(len(consents), 1)

    def test_check_consent_api(self):
        """Test check_consent API endpoint."""
        from tr_tradehub.doctype.consent_record.consent_record import check_consent, record_consent

        # No consent initially
        result = check_consent("Analytics")
        self.assertFalse(result["has_consent"])

        # Record consent
        record_consent(consent_type="Analytics", purpose="Website analytics")

        # Check again
        result = check_consent("Analytics")
        self.assertTrue(result["has_consent"])

    def test_withdraw_consent_api(self):
        """Test withdraw_consent API endpoint."""
        from tr_tradehub.doctype.consent_record.consent_record import (
            record_consent, withdraw_consent
        )

        # Record consent
        result = record_consent(consent_type="Newsletter", purpose="Send newsletters")
        consent_name = result["consent_name"]

        # Withdraw consent
        result = withdraw_consent(consent_name, reason="Too many emails")

        self.assertEqual(result["status"], "success")

        # Verify withdrawal
        consent = frappe.get_doc("Consent Record", consent_name)
        self.assertTrue(consent.is_withdrawn)
        self.assertEqual(consent.status, "Withdrawn")

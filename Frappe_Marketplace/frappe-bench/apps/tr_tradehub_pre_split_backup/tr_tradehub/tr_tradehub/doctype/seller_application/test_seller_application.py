# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import nowdate, add_days


class TestSellerApplication(FrappeTestCase):
    """Test cases for Seller Application DocType."""

    def setUp(self):
        """Set up test fixtures."""
        # Create test user if not exists
        if not frappe.db.exists("User", "test_applicant@example.com"):
            frappe.get_doc({
                "doctype": "User",
                "email": "test_applicant@example.com",
                "first_name": "Test",
                "last_name": "Applicant",
                "enabled": 1,
                "send_welcome_email": 0
            }).insert(ignore_permissions=True)

    def tearDown(self):
        """Clean up test data."""
        # Delete test applications
        frappe.db.delete("Seller Application", {"applicant_user": "test_applicant@example.com"})
        frappe.db.delete("Seller Profile", {"user": "test_applicant@example.com"})

    def create_test_application(self, **kwargs):
        """Helper to create a test seller application."""
        default_data = {
            "doctype": "Seller Application",
            "applicant_user": "test_applicant@example.com",
            "business_name": "Test Business",
            "seller_type": "Individual",
            "contact_name": "Test Contact",
            "contact_email": "test@example.com",
            "contact_phone": "+905551234567",
            "address_line_1": "Test Address 123",
            "city": "Istanbul",
            "country": "Turkey",
            "bank_name": "Test Bank",
            "iban": "TR330006100519786457841326",  # Valid test IBAN
            "account_holder_name": "Test Account Holder",
            "identity_document": "National ID Card",
            "identity_document_number": "12345678901",
            "identity_document_expiry": add_days(nowdate(), 365),
            "identity_document_attachment": "/test/attachment.pdf",
            "terms_accepted": 1,
            "privacy_accepted": 1,
            "kvkk_accepted": 1,
            "commission_accepted": 1,
            "return_policy_accepted": 1
        }
        default_data.update(kwargs)
        return frappe.get_doc(default_data)

    def test_create_application(self):
        """Test creating a new seller application."""
        application = self.create_test_application()
        application.insert(ignore_permissions=True)

        self.assertEqual(application.status, "Draft")
        self.assertEqual(application.workflow_state, "Draft")
        self.assertIsNotNone(application.name)

    def test_submit_application(self):
        """Test submitting a seller application."""
        application = self.create_test_application()
        application.insert(ignore_permissions=True)

        application.submit_application()

        self.assertEqual(application.status, "Submitted")
        self.assertEqual(application.workflow_state, "Pending Review")
        self.assertIsNotNone(application.submitted_at)

    def test_start_review(self):
        """Test starting review of an application."""
        application = self.create_test_application()
        application.insert(ignore_permissions=True)
        application.submit_application()

        application.start_review()

        self.assertEqual(application.status, "Under Review")
        self.assertEqual(application.workflow_state, "In Review")
        self.assertIsNotNone(application.review_started_at)

    def test_approve_application(self):
        """Test approving a seller application."""
        application = self.create_test_application()
        application.insert(ignore_permissions=True)
        application.submit_application()
        application.start_review()

        seller_profile = application.approve()

        self.assertEqual(application.status, "Approved")
        self.assertIsNotNone(application.approved_at)
        self.assertIsNotNone(application.seller_profile)
        self.assertEqual(seller_profile.user, application.applicant_user)

    def test_reject_application(self):
        """Test rejecting a seller application."""
        application = self.create_test_application()
        application.insert(ignore_permissions=True)
        application.submit_application()
        application.start_review()

        application.reject("Incomplete Documents", "Missing tax certificate")

        self.assertEqual(application.status, "Rejected")
        self.assertEqual(application.rejection_reason, "Incomplete Documents")
        self.assertIsNotNone(application.reviewed_at)

    def test_request_revision(self):
        """Test requesting revision for an application."""
        application = self.create_test_application()
        application.insert(ignore_permissions=True)
        application.submit_application()
        application.start_review()

        application.request_revision("Please update your business address")

        self.assertEqual(application.status, "Revision Required")
        self.assertEqual(application.revision_requested, 1)
        self.assertIsNotNone(application.revision_notes)

    def test_cancel_application(self):
        """Test cancelling an application."""
        application = self.create_test_application()
        application.insert(ignore_permissions=True)

        application.cancel("Changed my mind")

        self.assertEqual(application.status, "Cancelled")

    def test_vkn_validation(self):
        """Test VKN (Company Tax ID) validation."""
        application = self.create_test_application()

        # Valid VKN
        self.assertTrue(application.validate_vkn_checksum("1234567890"))

        # Invalid VKN (wrong checksum)
        self.assertFalse(application.validate_vkn_checksum("1234567891"))

        # Invalid length
        self.assertFalse(application.validate_vkn_checksum("123456789"))

    def test_tckn_validation(self):
        """Test TCKN (Individual Tax ID) validation."""
        application = self.create_test_application()

        # Valid TCKN example: 10000000146
        # (This is a known valid test TCKN)
        self.assertTrue(application.validate_tckn_checksum("10000000146"))

        # Invalid TCKN (starts with 0)
        self.assertFalse(application.validate_tckn_checksum("01234567890"))

        # Invalid length
        self.assertFalse(application.validate_tckn_checksum("1234567890"))

    def test_iban_validation(self):
        """Test Turkish IBAN validation."""
        application = self.create_test_application()

        # Valid Turkish IBAN
        self.assertTrue(application.validate_iban_checksum("TR330006100519786457841326"))

        # Invalid checksum
        self.assertFalse(application.validate_iban_checksum("TR330006100519786457841327"))

    def test_duplicate_application_prevention(self):
        """Test that duplicate applications are prevented."""
        application1 = self.create_test_application()
        application1.insert(ignore_permissions=True)

        application2 = self.create_test_application()

        with self.assertRaises(frappe.ValidationError):
            application2.insert(ignore_permissions=True)

    def test_invalid_status_transition(self):
        """Test that invalid status transitions are prevented."""
        application = self.create_test_application()
        application.insert(ignore_permissions=True)

        # Cannot approve from Draft status
        with self.assertRaises(frappe.ValidationError):
            application.approve()

    def test_application_history_tracking(self):
        """Test that application history is tracked correctly."""
        application = self.create_test_application()
        application.insert(ignore_permissions=True)

        # Should have creation entry
        self.assertEqual(len(application.application_history), 1)
        self.assertEqual(application.application_history[0].action, "Created")

        application.submit_application()

        # Should have submission entry
        self.assertEqual(len(application.application_history), 2)
        self.assertEqual(application.application_history[1].action, "Submitted")

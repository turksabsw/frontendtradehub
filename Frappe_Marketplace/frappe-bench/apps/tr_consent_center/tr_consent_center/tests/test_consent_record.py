# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

"""
Tests for Consent Record DocType

Tests retention policy enforcement and status transitions.
"""

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import today, add_years, add_days, getdate


class TestConsentRecord(FrappeTestCase):
    """Test cases for Consent Record DocType."""

    def setUp(self):
        """Set up test fixtures."""
        # Create test topic if not exists
        if not frappe.db.exists("Consent Topic", "Test Record Topic"):
            frappe.get_doc({
                "doctype": "Consent Topic",
                "topic_name": "Test Record Topic",
                "topic_code": "TEST_RECORD",
                "category": "Communication",
                "legal_basis": "Consent",
                "requires_explicit_consent": 1,
                "enabled": 1
            }).insert()

        # Create test user if not exists
        if not frappe.db.exists("User", "testuser@example.com"):
            frappe.get_doc({
                "doctype": "User",
                "email": "testuser@example.com",
                "first_name": "Test",
                "last_name": "User",
                "send_welcome_email": 0
            }).insert()

    def tearDown(self):
        """Clean up test data."""
        # Delete test consent records
        for doc in frappe.get_all("Consent Record", filters={"party": "testuser@example.com"}):
            try:
                # Bypass retention check for cleanup
                frappe.db.set_value("Consent Record", doc.name, "retention_until", add_days(today(), -1))
                frappe.delete_doc("Consent Record", doc.name, force=True)
            except Exception:
                pass

    def test_retention_until_auto_calculated(self):
        """Test that retention_until is auto-calculated as 5 years from grant."""
        doc = frappe.get_doc({
            "doctype": "Consent Record",
            "party_type": "User",
            "party": "testuser@example.com",
            "consent_topic": "Test Record Topic",
            "status": "Active"
        })
        doc.insert()

        expected_retention = add_years(today(), 5)
        self.assertEqual(getdate(doc.retention_until), getdate(expected_retention))

    def test_cannot_delete_before_retention(self):
        """Test that record cannot be deleted before retention period ends."""
        doc = frappe.get_doc({
            "doctype": "Consent Record",
            "party_type": "User",
            "party": "testuser@example.com",
            "consent_topic": "Test Record Topic",
            "status": "Active"
        })
        doc.insert()

        # Try to delete - should fail
        self.assertRaises(
            frappe.exceptions.ValidationError,
            frappe.delete_doc,
            "Consent Record",
            doc.name
        )

    def test_status_transition_active_to_revoked(self):
        """Test valid status transition from Active to Revoked."""
        doc = frappe.get_doc({
            "doctype": "Consent Record",
            "party_type": "User",
            "party": "testuser@example.com",
            "consent_topic": "Test Record Topic",
            "status": "Active"
        })
        doc.insert()

        # Change to Revoked - should work
        doc.status = "Revoked"
        doc.revocation_reason = "User requested"
        doc.save()

        self.assertEqual(doc.status, "Revoked")
        self.assertIsNotNone(doc.revoked_at)

    def test_status_transition_revoked_to_active_blocked(self):
        """Test that Revoked status cannot be changed."""
        doc = frappe.get_doc({
            "doctype": "Consent Record",
            "party_type": "User",
            "party": "testuser@example.com",
            "consent_topic": "Test Record Topic",
            "status": "Active"
        })
        doc.insert()

        # Revoke
        doc.status = "Revoked"
        doc.save()

        # Try to reactivate - should fail
        doc.status = "Active"
        self.assertRaises(frappe.exceptions.ValidationError, doc.save)

    def test_pending_to_active_on_verification(self):
        """Test status transition from Pending to Active on verification."""
        doc = frappe.get_doc({
            "doctype": "Consent Record",
            "party_type": "User",
            "party": "testuser@example.com",
            "consent_topic": "Test Record Topic",
            "status": "Pending"
        })
        doc.insert()

        # Verify - should transition to Active
        doc.status = "Active"
        doc.is_verified = 1
        doc.save()

        self.assertEqual(doc.status, "Active")
        self.assertTrue(doc.is_verified)

    def test_audit_log_created_on_insert(self):
        """Test that audit log is created when consent record is inserted."""
        doc = frappe.get_doc({
            "doctype": "Consent Record",
            "party_type": "User",
            "party": "testuser@example.com",
            "consent_topic": "Test Record Topic",
            "status": "Active"
        })
        doc.insert()

        # Check for audit log
        audit_log = frappe.get_all(
            "Consent Audit Log",
            filters={
                "consent_record": doc.name,
                "action": "Created"
            }
        )

        self.assertTrue(len(audit_log) > 0)

    def test_audit_log_created_on_status_change(self):
        """Test that audit log is created on status change."""
        doc = frappe.get_doc({
            "doctype": "Consent Record",
            "party_type": "User",
            "party": "testuser@example.com",
            "consent_topic": "Test Record Topic",
            "status": "Active"
        })
        doc.insert()

        # Change status
        doc.status = "Revoked"
        doc.save()

        # Check for status change audit log
        audit_log = frappe.get_all(
            "Consent Audit Log",
            filters={
                "consent_record": doc.name,
                "action": "Status Change"
            }
        )

        self.assertTrue(len(audit_log) > 0)

    def test_party_name_auto_fetched(self):
        """Test that party_name is auto-fetched from party."""
        doc = frappe.get_doc({
            "doctype": "Consent Record",
            "party_type": "User",
            "party": "testuser@example.com",
            "consent_topic": "Test Record Topic",
            "status": "Active"
        })
        doc.insert()

        # party_name should be set
        self.assertIsNotNone(doc.party_name)


def run_tests():
    """Run all tests."""
    frappe.flags.in_test = True
    test = TestConsentRecord()
    test.setUp()

    try:
        test.test_retention_until_auto_calculated()
        print("✓ test_retention_until_auto_calculated passed")

        test.test_status_transition_active_to_revoked()
        print("✓ test_status_transition_active_to_revoked passed")

        test.test_audit_log_created_on_insert()
        print("✓ test_audit_log_created_on_insert passed")

    except Exception as e:
        print(f"✗ Test failed: {str(e)}")

    finally:
        test.tearDown()

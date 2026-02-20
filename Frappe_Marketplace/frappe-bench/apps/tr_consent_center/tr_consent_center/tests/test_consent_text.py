# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

"""
Tests for Consent Text DocType

Tests versioning behavior and SHA256 hash calculation.
"""

import frappe
from frappe.tests.utils import FrappeTestCase
import hashlib


class TestConsentText(FrappeTestCase):
    """Test cases for Consent Text DocType."""

    def setUp(self):
        """Set up test fixtures."""
        # Create test topic if not exists
        if not frappe.db.exists("Consent Topic", "Test Topic"):
            frappe.get_doc({
                "doctype": "Consent Topic",
                "topic_name": "Test Topic",
                "topic_code": "TEST_TOPIC",
                "category": "Communication",
                "legal_basis": "Consent",
                "requires_explicit_consent": 1,
                "enabled": 1
            }).insert()

    def tearDown(self):
        """Clean up test data."""
        # Delete test consent texts
        for doc in frappe.get_all("Consent Text", filters={"title": ["like", "Test%"]}):
            try:
                frappe.delete_doc("Consent Text", doc.name, force=True)
            except Exception:
                pass

    def test_version_starts_at_one(self):
        """Test that version starts at 1 for new consent text."""
        doc = frappe.get_doc({
            "doctype": "Consent Text",
            "title": "Test Consent Text v1",
            "consent_topic": "Test Topic",
            "content": "This is the initial consent text content.",
            "status": "Draft"
        })
        doc.insert()

        self.assertEqual(doc.version, 1)

    def test_sha256_hash_calculated(self):
        """Test that SHA256 hash is calculated on insert."""
        content = "This is test content for hash calculation."
        expected_hash = hashlib.sha256(content.encode('utf-8')).hexdigest()

        doc = frappe.get_doc({
            "doctype": "Consent Text",
            "title": "Test Hash Calculation",
            "consent_topic": "Test Topic",
            "content": content,
            "status": "Draft"
        })
        doc.insert()

        self.assertEqual(doc.content_hash, expected_hash)

    def test_version_increments_on_content_change(self):
        """Test that version increments when content changes."""
        doc = frappe.get_doc({
            "doctype": "Consent Text",
            "title": "Test Version Increment",
            "consent_topic": "Test Topic",
            "content": "Original content",
            "status": "Draft"
        })
        doc.insert()

        self.assertEqual(doc.version, 1)

        # Change content
        doc.content = "Modified content"
        doc.save()

        self.assertEqual(doc.version, 2)

    def test_hash_changes_on_content_change(self):
        """Test that hash changes when content changes."""
        doc = frappe.get_doc({
            "doctype": "Consent Text",
            "title": "Test Hash Change",
            "consent_topic": "Test Topic",
            "content": "Original content",
            "status": "Draft"
        })
        doc.insert()

        original_hash = doc.content_hash

        # Change content
        doc.content = "Modified content"
        doc.save()

        self.assertNotEqual(doc.content_hash, original_hash)

    def test_version_unchanged_for_non_content_changes(self):
        """Test that version doesn't increment for non-content changes."""
        doc = frappe.get_doc({
            "doctype": "Consent Text",
            "title": "Test No Version Change",
            "consent_topic": "Test Topic",
            "content": "Content that stays the same",
            "status": "Draft"
        })
        doc.insert()

        self.assertEqual(doc.version, 1)

        # Change non-content field
        doc.content_summary = "This is a summary"
        doc.save()

        # Version should still be 1
        self.assertEqual(doc.version, 1)

    def test_cannot_edit_active_content(self):
        """Test that content cannot be edited when status is Active."""
        doc = frappe.get_doc({
            "doctype": "Consent Text",
            "title": "Test Active Content Edit",
            "consent_topic": "Test Topic",
            "content": "Active consent text",
            "status": "Active",
            "is_current": 1
        })
        doc.insert()

        # Try to change content
        doc.content = "Changed content"

        # Should throw an error
        self.assertRaises(frappe.exceptions.ValidationError, doc.save)

    def test_only_one_current_per_topic(self):
        """Test that only one consent text can be current per topic."""
        # Create first current text
        doc1 = frappe.get_doc({
            "doctype": "Consent Text",
            "title": "Test Current 1",
            "consent_topic": "Test Topic",
            "content": "First current text",
            "status": "Active",
            "is_current": 1
        })
        doc1.insert()

        # Try to create second current text for same topic
        doc2 = frappe.get_doc({
            "doctype": "Consent Text",
            "title": "Test Current 2",
            "consent_topic": "Test Topic",
            "content": "Second current text",
            "status": "Active",
            "is_current": 1
        })

        # Should throw an error
        self.assertRaises(frappe.exceptions.ValidationError, doc2.insert)


def run_tests():
    """Run all tests."""
    frappe.flags.in_test = True
    test = TestConsentText()
    test.setUp()

    try:
        test.test_version_starts_at_one()
        print("✓ test_version_starts_at_one passed")

        test.test_sha256_hash_calculated()
        print("✓ test_sha256_hash_calculated passed")

        test.test_version_increments_on_content_change()
        print("✓ test_version_increments_on_content_change passed")

        test.test_hash_changes_on_content_change()
        print("✓ test_hash_changes_on_content_change passed")

    except Exception as e:
        print(f"✗ Test failed: {str(e)}")

    finally:
        test.tearDown()

# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

"""
Tests for Seller Tag DocType
"""

import frappe
from frappe.tests.utils import FrappeTestCase


class TestSellerTag(FrappeTestCase):
    """Test cases for Seller Tag DocType."""

    def tearDown(self):
        """Clean up test data."""
        for doc in frappe.get_all("Seller Tag", filters={"tag_code": ["like", "TEST%"]}):
            try:
                frappe.delete_doc("Seller Tag", doc.name, force=True)
            except Exception:
                pass

    def test_tag_creation(self):
        """Test basic tag creation."""
        doc = frappe.get_doc({
            "doctype": "Seller Tag",
            "tag_name": "Test Tag",
            "tag_code": "TEST_TAG",
            "status": "Active",
            "tag_type": "Achievement"
        })
        doc.insert()

        self.assertEqual(doc.tag_code, "TEST_TAG")
        self.assertEqual(doc.status, "Active")

    def test_tag_code_uppercase(self):
        """Test tag code is converted to uppercase."""
        doc = frappe.get_doc({
            "doctype": "Seller Tag",
            "tag_name": "Test Lowercase",
            "tag_code": "test_lowercase_code",
            "status": "Active",
            "tag_type": "Achievement"
        })
        doc.insert()

        self.assertEqual(doc.tag_code, "TEST_LOWERCASE_CODE")

    def test_tag_code_space_replacement(self):
        """Test tag code spaces are replaced with underscores."""
        doc = frappe.get_doc({
            "doctype": "Seller Tag",
            "tag_name": "Test Spaces",
            "tag_code": "test with spaces",
            "status": "Active",
            "tag_type": "Achievement"
        })
        doc.insert()

        self.assertEqual(doc.tag_code, "TEST_WITH_SPACES")

    def test_unique_tag_code(self):
        """Test tag code must be unique."""
        doc1 = frappe.get_doc({
            "doctype": "Seller Tag",
            "tag_name": "Test Unique 1",
            "tag_code": "TEST_UNIQUE",
            "status": "Active",
            "tag_type": "Achievement"
        })
        doc1.insert()

        doc2 = frappe.get_doc({
            "doctype": "Seller Tag",
            "tag_name": "Test Unique 2",
            "tag_code": "TEST_UNIQUE",
            "status": "Active",
            "tag_type": "Achievement"
        })

        self.assertRaises(frappe.exceptions.DuplicateEntryError, doc2.insert)

    def test_tag_types(self):
        """Test all tag types are valid."""
        tag_types = ["Achievement", "Badge", "Certification", "Warning", "Special"]

        for i, tag_type in enumerate(tag_types):
            doc = frappe.get_doc({
                "doctype": "Seller Tag",
                "tag_name": f"Test Type {i}",
                "tag_code": f"TEST_TYPE_{i}",
                "status": "Active",
                "tag_type": tag_type
            })
            doc.insert()
            self.assertEqual(doc.tag_type, tag_type)

    def test_default_display_settings(self):
        """Test default display settings."""
        doc = frappe.get_doc({
            "doctype": "Seller Tag",
            "tag_name": "Test Defaults",
            "tag_code": "TEST_DEFAULTS",
            "status": "Active",
            "tag_type": "Achievement"
        })
        doc.insert()

        self.assertEqual(doc.show_on_profile, 1)
        self.assertEqual(doc.show_on_listings, 1)
        self.assertEqual(doc.show_on_storefront, 1)

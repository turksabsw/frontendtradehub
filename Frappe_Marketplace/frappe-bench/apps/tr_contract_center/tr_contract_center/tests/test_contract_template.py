# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

"""
Tests for Contract Template DocType
"""

import frappe
from frappe.tests.utils import FrappeTestCase
import hashlib


class TestContractTemplate(FrappeTestCase):
    """Test cases for Contract Template DocType."""

    def tearDown(self):
        """Clean up test data."""
        for doc in frappe.get_all("Contract Template", filters={"title": ["like", "Test%"]}):
            try:
                frappe.delete_doc("Contract Template", doc.name, force=True)
            except Exception:
                pass

    def test_version_starts_at_one(self):
        """Test that version starts at 1."""
        doc = frappe.get_doc({
            "doctype": "Contract Template",
            "title": "Test Template v1",
            "content": "Initial contract content.",
            "status": "Draft",
            "contract_type": "Terms of Service"
        })
        doc.insert()

        self.assertEqual(doc.version, 1)

    def test_sha256_hash_calculated(self):
        """Test SHA256 hash calculation."""
        content = "Contract content for hash test."
        expected_hash = hashlib.sha256(content.encode('utf-8')).hexdigest()

        doc = frappe.get_doc({
            "doctype": "Contract Template",
            "title": "Test Hash Template",
            "content": content,
            "status": "Draft",
            "contract_type": "Terms of Service"
        })
        doc.insert()

        self.assertEqual(doc.content_hash, expected_hash)

    def test_version_increments_on_content_change(self):
        """Test version increment on content change."""
        doc = frappe.get_doc({
            "doctype": "Contract Template",
            "title": "Test Version Increment",
            "content": "Original content",
            "status": "Draft",
            "contract_type": "Terms of Service"
        })
        doc.insert()

        self.assertEqual(doc.version, 1)

        doc.content = "Modified content"
        doc.save()

        self.assertEqual(doc.version, 2)

    def test_cannot_edit_published_content(self):
        """Test that published template content cannot be edited."""
        doc = frappe.get_doc({
            "doctype": "Contract Template",
            "title": "Test Published Edit",
            "content": "Published content",
            "status": "Published",
            "contract_type": "Terms of Service"
        })
        doc.insert()

        doc.content = "Trying to change published content"
        self.assertRaises(frappe.exceptions.ValidationError, doc.save)

    def test_template_code_uppercase(self):
        """Test that template code is converted to uppercase."""
        doc = frappe.get_doc({
            "doctype": "Contract Template",
            "title": "Test Code Uppercase",
            "template_code": "my_template_code",
            "content": "Content",
            "status": "Draft",
            "contract_type": "Terms of Service"
        })
        doc.insert()

        self.assertEqual(doc.template_code, "MY_TEMPLATE_CODE")

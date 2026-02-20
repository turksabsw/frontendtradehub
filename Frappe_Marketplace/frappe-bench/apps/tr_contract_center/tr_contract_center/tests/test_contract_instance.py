# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

"""
Tests for Contract Instance DocType
"""

import frappe
from frappe.tests.utils import FrappeTestCase


class TestContractInstance(FrappeTestCase):
    """Test cases for Contract Instance DocType."""

    def setUp(self):
        """Set up test fixtures."""
        # Create test template
        if not frappe.db.exists("Contract Template", {"title": "Test Contract Template"}):
            frappe.get_doc({
                "doctype": "Contract Template",
                "title": "Test Contract Template",
                "template_code": "TEST_CONTRACT",
                "content": "This is a test contract. Party: {{party_name}}",
                "status": "Published",
                "contract_type": "Terms of Service",
                "valid_days": 30
            }).insert()

        # Create test user
        if not frappe.db.exists("User", "contracttest@example.com"):
            frappe.get_doc({
                "doctype": "User",
                "email": "contracttest@example.com",
                "first_name": "Contract",
                "last_name": "Test",
                "send_welcome_email": 0
            }).insert()

    def tearDown(self):
        """Clean up test data."""
        for doc in frappe.get_all("Contract Instance", filters={"party": "contracttest@example.com"}):
            try:
                frappe.delete_doc("Contract Instance", doc.name, force=True)
            except Exception:
                pass

    def test_template_snapshot_on_create(self):
        """Test that template content is snapshotted on creation."""
        template = frappe.get_doc("Contract Template", {"template_code": "TEST_CONTRACT"})

        doc = frappe.get_doc({
            "doctype": "Contract Instance",
            "template": template.name,
            "party_type": "User",
            "party": "contracttest@example.com",
            "status": "Draft"
        })
        doc.insert()

        self.assertEqual(doc.template_version_snapshot, template.version)
        self.assertEqual(doc.template_content_snapshot, template.content)
        self.assertEqual(doc.content_hash_snapshot, template.content_hash)

    def test_status_workflow(self):
        """Test valid status transitions."""
        template = frappe.get_doc("Contract Template", {"template_code": "TEST_CONTRACT"})

        doc = frappe.get_doc({
            "doctype": "Contract Instance",
            "template": template.name,
            "party_type": "User",
            "party": "contracttest@example.com",
            "status": "Draft"
        })
        doc.insert()

        # Draft -> Sent
        doc.status = "Sent"
        doc.save()
        self.assertEqual(doc.status, "Sent")
        self.assertIsNotNone(doc.sent_at)

        # Sent -> Pending Signature
        doc.status = "Pending Signature"
        doc.save()
        self.assertEqual(doc.status, "Pending Signature")

    def test_invalid_status_transition(self):
        """Test invalid status transitions."""
        template = frappe.get_doc("Contract Template", {"template_code": "TEST_CONTRACT"})

        doc = frappe.get_doc({
            "doctype": "Contract Instance",
            "template": template.name,
            "party_type": "User",
            "party": "contracttest@example.com",
            "status": "Draft"
        })
        doc.insert()

        # Draft -> Signed should fail (must go through workflow)
        doc.status = "Signed"
        self.assertRaises(frappe.exceptions.ValidationError, doc.save)

    def test_wet_signature_requires_pdf(self):
        """Test that wet signature requires signed PDF."""
        template = frappe.get_doc("Contract Template", {"template_code": "TEST_CONTRACT"})

        doc = frappe.get_doc({
            "doctype": "Contract Instance",
            "template": template.name,
            "party_type": "User",
            "party": "contracttest@example.com",
            "status": "Pending Signature",
            "signature_method": "Wet"
        })
        doc.insert()

        # Try to sign without PDF
        doc.status = "Signed"
        self.assertRaises(frappe.exceptions.ValidationError, doc.save)

    def test_party_name_auto_fetched(self):
        """Test that party name is auto-fetched."""
        template = frappe.get_doc("Contract Template", {"template_code": "TEST_CONTRACT"})

        doc = frappe.get_doc({
            "doctype": "Contract Instance",
            "template": template.name,
            "party_type": "User",
            "party": "contracttest@example.com",
            "status": "Draft"
        })
        doc.insert()

        self.assertIsNotNone(doc.party_name)

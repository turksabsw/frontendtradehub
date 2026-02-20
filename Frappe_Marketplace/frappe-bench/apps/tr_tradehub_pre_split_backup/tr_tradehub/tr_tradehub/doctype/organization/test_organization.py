# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

import frappe
from frappe.tests.utils import FrappeTestCase


class TestOrganization(FrappeTestCase):
    """Test cases for Organization DocType."""

    def setUp(self):
        """Set up test fixtures."""
        # Clean up any existing test organizations
        frappe.db.delete("Organization", {"organization_name": ["like", "Test%"]})

    def tearDown(self):
        """Clean up test data."""
        frappe.db.delete("Organization", {"organization_name": ["like", "Test%"]})

    def test_create_organization(self):
        """Test basic organization creation."""
        org = frappe.get_doc({
            "doctype": "Organization",
            "organization_name": "Test Company Ltd",
            "organization_type": "Company",
            "status": "Pending Verification",
            "primary_contact_name": "John Doe",
            "email": "john@testcompany.com",
            "address_line_1": "123 Test Street",
            "city": "Istanbul",
            "country": "Turkey",
            "tax_id": "1234567890",  # Valid 10-digit VKN (dummy)
            "tax_office": "Istanbul Tax Office"
        })
        org.insert()

        self.assertTrue(org.name)
        self.assertEqual(org.organization_name, "Test Company Ltd")
        self.assertEqual(org.organization_type, "Company")
        self.assertEqual(org.status, "Pending Verification")

    def test_tax_id_validation_length(self):
        """Test that tax ID must be exactly 10 digits."""
        org = frappe.get_doc({
            "doctype": "Organization",
            "organization_name": "Test Company",
            "organization_type": "Company",
            "primary_contact_name": "John Doe",
            "email": "john@test.com",
            "address_line_1": "Test Address",
            "city": "Istanbul",
            "country": "Turkey",
            "tax_id": "123456789",  # 9 digits - invalid
            "tax_office": "Test Office"
        })

        with self.assertRaises(frappe.ValidationError):
            org.insert()

    def test_tax_id_validation_digits_only(self):
        """Test that tax ID must contain only digits."""
        org = frappe.get_doc({
            "doctype": "Organization",
            "organization_name": "Test Company",
            "organization_type": "Company",
            "primary_contact_name": "John Doe",
            "email": "john@test.com",
            "address_line_1": "Test Address",
            "city": "Istanbul",
            "country": "Turkey",
            "tax_id": "123456789A",  # Contains letter - invalid
            "tax_office": "Test Office"
        })

        with self.assertRaises(frappe.ValidationError):
            org.insert()

    def test_mersis_validation(self):
        """Test MERSIS number validation (16 digits)."""
        org = frappe.get_doc({
            "doctype": "Organization",
            "organization_name": "Test MERSIS Company",
            "organization_type": "Company",
            "primary_contact_name": "John Doe",
            "email": "john@test.com",
            "address_line_1": "Test Address",
            "city": "Istanbul",
            "country": "Turkey",
            "tax_id": "1234567890",
            "tax_office": "Test Office",
            "mersis_number": "123456"  # Too short - invalid
        })

        with self.assertRaises(frappe.ValidationError):
            org.insert()

    def test_e_invoice_alias_validation(self):
        """Test E-Invoice alias format validation."""
        org = frappe.get_doc({
            "doctype": "Organization",
            "organization_name": "Test E-Invoice Company",
            "organization_type": "Company",
            "primary_contact_name": "John Doe",
            "email": "john@test.com",
            "address_line_1": "Test Address",
            "city": "Istanbul",
            "country": "Turkey",
            "tax_id": "1234567890",
            "tax_office": "Test Office",
            "e_invoice_registered": 1,
            "e_invoice_alias": "INVALID_ALIAS"  # Must start with PK: or GB:
        })

        with self.assertRaises(frappe.ValidationError):
            org.insert()

    def test_valid_e_invoice_alias(self):
        """Test valid E-Invoice alias formats."""
        org = frappe.get_doc({
            "doctype": "Organization",
            "organization_name": "Test E-Invoice Valid",
            "organization_type": "Company",
            "primary_contact_name": "John Doe",
            "email": "john@test.com",
            "address_line_1": "Test Address",
            "city": "Istanbul",
            "country": "Turkey",
            "tax_id": "1234567890",
            "tax_office": "Test Office",
            "e_invoice_registered": 1,
            "e_invoice_alias": "pk:1234567890"
        })
        org.insert()

        # Alias should be uppercased
        self.assertEqual(org.e_invoice_alias, "PK:1234567890")

    def test_organization_status_methods(self):
        """Test organization status check methods."""
        org = frappe.get_doc({
            "doctype": "Organization",
            "organization_name": "Test Status Company",
            "organization_type": "Company",
            "status": "Pending Verification",
            "verification_status": "Pending",
            "primary_contact_name": "John Doe",
            "email": "john@test.com",
            "address_line_1": "Test Address",
            "city": "Istanbul",
            "country": "Turkey",
            "tax_id": "1234567890",
            "tax_office": "Test Office"
        })
        org.insert()

        # Should not be active initially
        self.assertFalse(org.is_active())
        self.assertFalse(org.is_verified())
        self.assertFalse(org.can_buy())
        self.assertFalse(org.can_sell())

        # Mark as verified
        org.mark_verified()
        org.reload()

        self.assertTrue(org.is_active())
        self.assertTrue(org.is_verified())
        self.assertTrue(org.can_buy())

    def test_member_management(self):
        """Test organization member management."""
        org = frappe.get_doc({
            "doctype": "Organization",
            "organization_name": "Test Member Company",
            "organization_type": "Company",
            "primary_contact_name": "John Doe",
            "email": "john@test.com",
            "address_line_1": "Test Address",
            "city": "Istanbul",
            "country": "Turkey",
            "tax_id": "1234567890",
            "tax_office": "Test Office"
        })
        org.insert()

        # Add a member
        org.add_member("Administrator", role="Admin", is_admin=True)
        org.reload()

        self.assertEqual(len(org.organization_members), 1)
        self.assertTrue(org.is_member("Administrator"))
        self.assertEqual(org.get_member_role("Administrator"), "Admin")

        # Remove member
        org.remove_member("Administrator")
        org.reload()

        self.assertEqual(len(org.organization_members), 0)
        self.assertFalse(org.is_member("Administrator"))

    def test_duplicate_member_prevention(self):
        """Test that duplicate members cannot be added."""
        org = frappe.get_doc({
            "doctype": "Organization",
            "organization_name": "Test Duplicate Member",
            "organization_type": "Company",
            "primary_contact_name": "John Doe",
            "email": "john@test.com",
            "address_line_1": "Test Address",
            "city": "Istanbul",
            "country": "Turkey",
            "tax_id": "1234567890",
            "tax_office": "Test Office"
        })
        org.insert()

        org.add_member("Administrator")

        with self.assertRaises(frappe.ValidationError):
            org.add_member("Administrator")

    def test_founded_year_validation(self):
        """Test that founded year must be reasonable."""
        org = frappe.get_doc({
            "doctype": "Organization",
            "organization_name": "Test Founded Year",
            "organization_type": "Company",
            "primary_contact_name": "John Doe",
            "email": "john@test.com",
            "address_line_1": "Test Address",
            "city": "Istanbul",
            "country": "Turkey",
            "tax_id": "1234567890",
            "tax_office": "Test Office",
            "founded_year": 1500  # Too old - invalid
        })

        with self.assertRaises(frappe.ValidationError):
            org.insert()

    def test_credit_limit_functionality(self):
        """Test credit limit and available credit calculation."""
        org = frappe.get_doc({
            "doctype": "Organization",
            "organization_name": "Test Credit Company",
            "organization_type": "Company",
            "status": "Active",
            "verification_status": "Verified",
            "primary_contact_name": "John Doe",
            "email": "john@test.com",
            "address_line_1": "Test Address",
            "city": "Istanbul",
            "country": "Turkey",
            "tax_id": "1234567890",
            "tax_office": "Test Office",
            "credit_limit": 50000,
            "is_approved_buyer": 1,
            "can_use_credit": 1
        })
        org.insert()

        # Should be able to use credit
        available = org.get_available_credit()
        self.assertEqual(available, 50000)


def get_test_org_data():
    """Return test organization data for use in other test files."""
    return {
        "doctype": "Organization",
        "organization_name": "Test Organization",
        "organization_type": "Company",
        "status": "Active",
        "verification_status": "Verified",
        "primary_contact_name": "Test Contact",
        "email": "test@testorg.com",
        "address_line_1": "Test Address",
        "city": "Istanbul",
        "country": "Turkey",
        "tax_id": "1234567890",
        "tax_office": "Test Tax Office",
        "is_approved_buyer": 1
    }

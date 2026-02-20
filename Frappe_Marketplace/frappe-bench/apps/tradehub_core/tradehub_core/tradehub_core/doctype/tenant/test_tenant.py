# Copyright (c) 2024, TR TradeHub and Contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase


class TestTenant(FrappeTestCase):
    """Test cases for Tenant DocType."""

    def setUp(self):
        """Set up test data."""
        # Clean up any existing test tenants
        for tenant in frappe.get_all("Tenant", filters={"tenant_name": ["like", "Test Tenant%"]}):
            frappe.delete_doc("Tenant", tenant.name, force=True)

    def tearDown(self):
        """Clean up test data."""
        for tenant in frappe.get_all("Tenant", filters={"tenant_name": ["like", "Test Tenant%"]}):
            frappe.delete_doc("Tenant", tenant.name, force=True)

    def test_tenant_creation(self):
        """Test basic tenant creation."""
        tenant = frappe.get_doc({
            "doctype": "Tenant",
            "tenant_name": "Test Tenant Basic",
            "company_name": "Test Company Ltd",
            "contact_email": "test@testcompany.com",
            "status": "Active",
            "subscription_tier": "Basic"
        })
        tenant.insert()

        self.assertTrue(tenant.name)
        self.assertEqual(tenant.tenant_name, "Test Tenant Basic")
        self.assertEqual(tenant.subscription_tier, "Basic")

    def test_tenant_naming(self):
        """Test tenant auto-naming pattern."""
        tenant = frappe.get_doc({
            "doctype": "Tenant",
            "tenant_name": "Test Tenant Naming",
            "company_name": "Test Company",
            "contact_email": "test@test.com",
            "status": "Active",
            "subscription_tier": "Basic"
        })
        tenant.insert()

        # Should follow TEN-.##### pattern
        self.assertTrue(tenant.name.startswith("TEN-"))

    def test_tier_defaults(self):
        """Test that subscription tier sets appropriate defaults."""
        tenant = frappe.get_doc({
            "doctype": "Tenant",
            "tenant_name": "Test Tenant Tier",
            "company_name": "Test Company",
            "contact_email": "test@test.com",
            "status": "Active",
            "subscription_tier": "Professional"
        })
        tenant.insert()

        # Professional tier defaults
        self.assertEqual(tenant.max_sellers, 50)
        self.assertEqual(tenant.max_listings_per_seller, 500)
        self.assertEqual(tenant.commission_rate, 7.5)

    def test_tax_id_validation_valid_vkn(self):
        """Test valid VKN (10 digits) passes validation."""
        tenant = frappe.get_doc({
            "doctype": "Tenant",
            "tenant_name": "Test Tenant VKN",
            "company_name": "Test Company",
            "contact_email": "test@test.com",
            "status": "Active",
            "subscription_tier": "Basic",
            "tax_id": "1234567890"  # Valid 10-digit VKN
        })
        tenant.insert()
        self.assertEqual(tenant.tax_id, "1234567890")

    def test_tax_id_validation_valid_tckn(self):
        """Test valid TCKN (11 digits) passes validation."""
        tenant = frappe.get_doc({
            "doctype": "Tenant",
            "tenant_name": "Test Tenant TCKN",
            "company_name": "Test Company",
            "contact_email": "test@test.com",
            "status": "Active",
            "subscription_tier": "Basic",
            "tax_id": "12345678901"  # Valid 11-digit TCKN
        })
        tenant.insert()
        self.assertEqual(tenant.tax_id, "12345678901")

    def test_tax_id_validation_invalid_length(self):
        """Test invalid tax ID length raises error."""
        tenant = frappe.get_doc({
            "doctype": "Tenant",
            "tenant_name": "Test Tenant Invalid Tax",
            "company_name": "Test Company",
            "contact_email": "test@test.com",
            "status": "Active",
            "subscription_tier": "Basic",
            "tax_id": "123456789"  # Invalid 9-digit
        })
        with self.assertRaises(frappe.ValidationError):
            tenant.insert()

    def test_tax_id_validation_non_numeric(self):
        """Test non-numeric tax ID raises error."""
        tenant = frappe.get_doc({
            "doctype": "Tenant",
            "tenant_name": "Test Tenant Non Numeric",
            "company_name": "Test Company",
            "contact_email": "test@test.com",
            "status": "Active",
            "subscription_tier": "Basic",
            "tax_id": "123ABC7890"  # Contains letters
        })
        with self.assertRaises(frappe.ValidationError):
            tenant.insert()

    def test_subscription_date_validation(self):
        """Test subscription end date cannot be before start date."""
        tenant = frappe.get_doc({
            "doctype": "Tenant",
            "tenant_name": "Test Tenant Dates",
            "company_name": "Test Company",
            "contact_email": "test@test.com",
            "status": "Active",
            "subscription_tier": "Basic",
            "subscription_start_date": "2024-12-01",
            "subscription_end_date": "2024-01-01"  # Before start
        })
        with self.assertRaises(frappe.ValidationError):
            tenant.insert()

    def test_is_active_check(self):
        """Test is_active method."""
        tenant = frappe.get_doc({
            "doctype": "Tenant",
            "tenant_name": "Test Tenant Active Check",
            "company_name": "Test Company",
            "contact_email": "test@test.com",
            "status": "Active",
            "subscription_tier": "Basic"
        })
        tenant.insert()

        self.assertTrue(tenant.is_active())

        # Suspend the tenant
        tenant.status = "Suspended"
        tenant.save()
        self.assertFalse(tenant.is_active())

    def test_negative_limits_validation(self):
        """Test that negative limits raise validation error."""
        tenant = frappe.get_doc({
            "doctype": "Tenant",
            "tenant_name": "Test Tenant Negative",
            "company_name": "Test Company",
            "contact_email": "test@test.com",
            "status": "Active",
            "subscription_tier": "Basic",
            "max_sellers": -5
        })
        with self.assertRaises(frappe.ValidationError):
            tenant.insert()

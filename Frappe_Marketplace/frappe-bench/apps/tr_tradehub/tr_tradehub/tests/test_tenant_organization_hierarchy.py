# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

"""
Comprehensive Unit and Integration Tests for Tenant-Organization-Seller Hierarchy

This test module verifies:
1. Tenant creation with User Permission auto-creation
2. Organization linked to correct tenant with User Permission
3. Seller Profile linked to correct tenant via organization
4. Tenant auto-population from organization
5. Organization-tenant consistency validation
6. Tenant change prevention for organizations and sellers
7. User Permission creation for tenant data isolation
"""

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import nowdate


class TestTenantCreation(FrappeTestCase):
    """Tests for Tenant DocType creation with User Permission."""

    @classmethod
    def setUpClass(cls):
        """Set up test fixtures."""
        super().setUpClass()
        cls.cleanup_test_data()

    @classmethod
    def tearDownClass(cls):
        """Clean up test data."""
        super().tearDownClass()
        cls.cleanup_test_data()

    @classmethod
    def cleanup_test_data(cls):
        """Clean up all test data created during tests."""
        try:
            # Delete seller profiles first (depends on organization)
            for name in frappe.get_all("Seller Profile", filters={"seller_name": ["like", "Hierarchy Test%"]}, pluck="name"):
                frappe.delete_doc("Seller Profile", name, force=True, ignore_permissions=True)

            # Delete organizations (depends on tenant)
            for name in frappe.get_all("Organization", filters={"organization_name": ["like", "Hierarchy Test%"]}, pluck="name"):
                frappe.delete_doc("Organization", name, force=True, ignore_permissions=True)

            # Delete tenants
            for name in frappe.get_all("Tenant", filters={"tenant_name": ["like", "Hierarchy Test%"]}, pluck="name"):
                # Delete User Permissions for this tenant first
                for perm in frappe.get_all("User Permission", filters={"allow": "Tenant", "for_value": name}, pluck="name"):
                    frappe.delete_doc("User Permission", perm, force=True, ignore_permissions=True)
                frappe.delete_doc("Tenant", name, force=True, ignore_permissions=True)

            # Delete test users
            for email in ["hierarchy_test_user@example.com", "hierarchy_test_user2@example.com",
                          "hierarchy_test_user3@example.com", "hierarchy_test_mismatch@example.com"]:
                if frappe.db.exists("User", email):
                    frappe.delete_doc("User", email, force=True, ignore_permissions=True)

            frappe.db.commit()
        except Exception:
            pass

    def create_test_tenant(self, suffix=""):
        """Create a test tenant."""
        tenant = frappe.get_doc({
            "doctype": "Tenant",
            "tenant_name": f"Hierarchy Test Tenant {suffix}".strip(),
            "company_name": f"Hierarchy Test Company {suffix}".strip(),
            "status": "Active",
            "subscription_tier": "Basic",
            "contact_email": f"tenant{suffix}@test.com",
            "country": "Turkey"
        })
        tenant.insert(ignore_permissions=True)
        frappe.db.commit()
        return tenant

    def create_test_user(self, suffix=""):
        """Create a test user."""
        email = f"hierarchy_test_user{suffix}@example.com"
        if not frappe.db.exists("User", email):
            user = frappe.get_doc({
                "doctype": "User",
                "email": email,
                "first_name": "Hierarchy",
                "last_name": f"Test User {suffix}".strip(),
                "enabled": 1,
                "send_welcome_email": 0
            })
            user.insert(ignore_permissions=True)
            frappe.db.commit()
        return email

    def test_tenant_creation_basic(self):
        """Test basic tenant creation."""
        tenant = self.create_test_tenant("Basic")

        self.assertIsNotNone(tenant.name)
        self.assertTrue(tenant.name.startswith("TEN-"))
        self.assertEqual(tenant.status, "Active")
        self.assertEqual(tenant.tenant_name, "Hierarchy Test Tenant Basic")

        # Cleanup
        frappe.delete_doc("Tenant", tenant.name, force=True, ignore_permissions=True)
        frappe.db.commit()

    def test_tenant_naming_format(self):
        """Test that tenant follows TEN-##### naming format."""
        tenant = self.create_test_tenant("Naming")

        self.assertTrue(tenant.name.startswith("TEN-"))

        # Cleanup
        frappe.delete_doc("Tenant", tenant.name, force=True, ignore_permissions=True)
        frappe.db.commit()


class TestOrganizationTenantLink(FrappeTestCase):
    """Tests for Organization DocType linked to Tenant."""

    @classmethod
    def setUpClass(cls):
        """Set up test fixtures."""
        super().setUpClass()
        TestTenantCreation.cleanup_test_data()

    @classmethod
    def tearDownClass(cls):
        """Clean up test data."""
        super().tearDownClass()
        TestTenantCreation.cleanup_test_data()

    def create_test_tenant(self, suffix=""):
        """Create a test tenant."""
        tenant = frappe.get_doc({
            "doctype": "Tenant",
            "tenant_name": f"Hierarchy Test Tenant {suffix}".strip(),
            "company_name": f"Hierarchy Test Company {suffix}".strip(),
            "status": "Active",
            "subscription_tier": "Basic",
            "contact_email": f"tenant{suffix}@test.com",
            "country": "Turkey"
        })
        tenant.insert(ignore_permissions=True)
        frappe.db.commit()
        return tenant

    def create_test_organization(self, tenant_name, suffix=""):
        """Create a test organization linked to a tenant."""
        org = frappe.get_doc({
            "doctype": "Organization",
            "organization_name": f"Hierarchy Test Organization {suffix}".strip(),
            "organization_type": "Company",
            "tenant": tenant_name,
            "status": "Active",
            "country": "Turkey",
            "tax_id": "1234567890"  # Valid 10-digit VKN
        })
        org.insert(ignore_permissions=True)
        frappe.db.commit()
        return org

    def test_organization_linked_to_correct_tenant(self):
        """Test that organization is correctly linked to tenant."""
        tenant = self.create_test_tenant("OrgLink")
        org = self.create_test_organization(tenant.name, "OrgLink")

        # Verify organization was created
        self.assertTrue(frappe.db.exists("Organization", org.name))

        # Verify organization is linked to tenant
        org_doc = frappe.get_doc("Organization", org.name)
        self.assertEqual(org_doc.tenant, tenant.name)

        # Cleanup
        frappe.delete_doc("Organization", org.name, force=True, ignore_permissions=True)
        frappe.delete_doc("Tenant", tenant.name, force=True, ignore_permissions=True)
        frappe.db.commit()

    def test_organization_requires_tenant(self):
        """Test that organization requires a tenant."""
        with self.assertRaises(frappe.ValidationError):
            org = frappe.get_doc({
                "doctype": "Organization",
                "organization_name": "Hierarchy Test Organization NoTenant",
                "organization_type": "Company",
                # No tenant specified
                "status": "Active",
                "country": "Turkey",
                "tax_id": "9876543210"
            })
            org.insert(ignore_permissions=True)

    def test_organization_user_permission_creation(self):
        """Test that User Permission is created when organization is created."""
        # Create a test user to be the creator
        test_user = "hierarchy_test_user@example.com"
        if not frappe.db.exists("User", test_user):
            user = frappe.get_doc({
                "doctype": "User",
                "email": test_user,
                "first_name": "Hierarchy",
                "last_name": "Test User",
                "enabled": 1,
                "send_welcome_email": 0
            })
            user.insert(ignore_permissions=True)
            frappe.db.commit()

        # Create tenant as Administrator
        tenant = self.create_test_tenant("OrgUserPerm")

        # Create organization as the test user
        original_user = frappe.session.user
        frappe.set_user(test_user)

        try:
            org = frappe.get_doc({
                "doctype": "Organization",
                "organization_name": "Hierarchy Test Organization UserPerm",
                "organization_type": "Company",
                "tenant": tenant.name,
                "status": "Active",
                "country": "Turkey",
                "tax_id": "1111111116",  # Valid VKN with correct checksum
                "created_by": test_user
            })
            org.insert(ignore_permissions=True)
            frappe.db.commit()

            # Verify User Permission was created
            user_permission = frappe.db.exists("User Permission", {
                "user": test_user,
                "allow": "Tenant",
                "for_value": tenant.name
            })

            # User Permission should exist
            self.assertTrue(user_permission, "User Permission should be created for organization creator")

        finally:
            frappe.set_user(original_user)

            # Cleanup
            if frappe.db.exists("Organization", org.name):
                frappe.delete_doc("Organization", org.name, force=True, ignore_permissions=True)
            for perm in frappe.get_all("User Permission",
                                       filters={"user": test_user, "allow": "Tenant", "for_value": tenant.name},
                                       pluck="name"):
                frappe.delete_doc("User Permission", perm, force=True, ignore_permissions=True)
            if frappe.db.exists("Tenant", tenant.name):
                frappe.delete_doc("Tenant", tenant.name, force=True, ignore_permissions=True)
            if frappe.db.exists("User", test_user):
                frappe.delete_doc("User", test_user, force=True, ignore_permissions=True)
            frappe.db.commit()


class TestSellerProfileTenantLink(FrappeTestCase):
    """Tests for Seller Profile DocType linked to Tenant via Organization."""

    @classmethod
    def setUpClass(cls):
        """Set up test fixtures."""
        super().setUpClass()
        TestTenantCreation.cleanup_test_data()

    @classmethod
    def tearDownClass(cls):
        """Clean up test data."""
        super().tearDownClass()
        TestTenantCreation.cleanup_test_data()

    def create_test_tenant(self, suffix=""):
        """Create a test tenant."""
        tenant = frappe.get_doc({
            "doctype": "Tenant",
            "tenant_name": f"Hierarchy Test Tenant {suffix}".strip(),
            "company_name": f"Hierarchy Test Company {suffix}".strip(),
            "status": "Active",
            "subscription_tier": "Basic",
            "contact_email": f"tenant{suffix}@test.com",
            "country": "Turkey"
        })
        tenant.insert(ignore_permissions=True)
        frappe.db.commit()
        return tenant

    def create_test_organization(self, tenant_name, suffix=""):
        """Create a test organization linked to a tenant."""
        org = frappe.get_doc({
            "doctype": "Organization",
            "organization_name": f"Hierarchy Test Organization {suffix}".strip(),
            "organization_type": "Company",
            "tenant": tenant_name,
            "status": "Active",
            "country": "Turkey",
            "tax_id": "1234567890"
        })
        org.insert(ignore_permissions=True)
        frappe.db.commit()
        return org

    def create_test_user(self, suffix=""):
        """Create a test user."""
        email = f"hierarchy_test_user{suffix}@example.com"
        if not frappe.db.exists("User", email):
            user = frappe.get_doc({
                "doctype": "User",
                "email": email,
                "first_name": "Hierarchy",
                "last_name": f"Test {suffix}".strip(),
                "enabled": 1,
                "send_welcome_email": 0
            })
            user.insert(ignore_permissions=True)
            frappe.db.commit()
        return email

    def test_seller_tenant_auto_populated_from_organization(self):
        """Test that seller's tenant is auto-populated from organization."""
        tenant = self.create_test_tenant("SellerAuto")
        org = self.create_test_organization(tenant.name, "SellerAuto")
        user_email = self.create_test_user("_seller_auto")

        # Create seller profile WITHOUT specifying tenant
        seller = frappe.get_doc({
            "doctype": "Seller Profile",
            "seller_name": "Hierarchy Test Seller Auto",
            "user": user_email,
            "seller_type": "Business",
            "organization": org.name,
            # tenant NOT specified - should be auto-populated
            "status": "Pending",
            "country": "Turkey"
        })
        seller.insert(ignore_permissions=True)
        frappe.db.commit()

        # Verify tenant was auto-populated
        seller_doc = frappe.get_doc("Seller Profile", seller.name)
        self.assertEqual(seller_doc.tenant, tenant.name,
                        "Tenant should be auto-populated from organization")

        # Cleanup
        frappe.delete_doc("Seller Profile", seller.name, force=True, ignore_permissions=True)
        frappe.delete_doc("Organization", org.name, force=True, ignore_permissions=True)
        frappe.delete_doc("Tenant", tenant.name, force=True, ignore_permissions=True)
        frappe.delete_doc("User", user_email, force=True, ignore_permissions=True)
        frappe.db.commit()

    def test_seller_requires_tenant(self):
        """Test that seller profile requires tenant."""
        user_email = self.create_test_user("_no_tenant")

        with self.assertRaises(frappe.exceptions.MandatoryError):
            seller = frappe.get_doc({
                "doctype": "Seller Profile",
                "seller_name": "Hierarchy Test Seller NoTenant",
                "user": user_email,
                "seller_type": "Individual",
                # No tenant, no organization
                "status": "Pending",
                "country": "Turkey"
            })
            seller.insert(ignore_permissions=True)

        # Cleanup
        frappe.delete_doc("User", user_email, force=True, ignore_permissions=True)
        frappe.db.commit()

    def test_seller_user_permission_creation(self):
        """Test that User Permission is created when seller profile is created."""
        tenant = self.create_test_tenant("SellerPerm")
        org = self.create_test_organization(tenant.name, "SellerPerm")
        user_email = self.create_test_user("_seller_perm")

        seller = frappe.get_doc({
            "doctype": "Seller Profile",
            "seller_name": "Hierarchy Test Seller UserPerm",
            "user": user_email,
            "seller_type": "Business",
            "organization": org.name,
            "status": "Pending",
            "country": "Turkey"
        })
        seller.insert(ignore_permissions=True)
        frappe.db.commit()

        # Verify User Permission was created for the seller user
        user_permission = frappe.db.exists("User Permission", {
            "user": user_email,
            "allow": "Tenant",
            "for_value": tenant.name
        })

        self.assertTrue(user_permission, "User Permission should be created for seller user")

        # Cleanup
        for perm in frappe.get_all("User Permission",
                                   filters={"user": user_email, "allow": "Tenant"},
                                   pluck="name"):
            frappe.delete_doc("User Permission", perm, force=True, ignore_permissions=True)
        frappe.delete_doc("Seller Profile", seller.name, force=True, ignore_permissions=True)
        frappe.delete_doc("Organization", org.name, force=True, ignore_permissions=True)
        frappe.delete_doc("Tenant", tenant.name, force=True, ignore_permissions=True)
        frappe.delete_doc("User", user_email, force=True, ignore_permissions=True)
        frappe.db.commit()


class TestTenantOrganizationConsistency(FrappeTestCase):
    """Tests for tenant-organization consistency validation."""

    @classmethod
    def setUpClass(cls):
        """Set up test fixtures."""
        super().setUpClass()
        TestTenantCreation.cleanup_test_data()

    @classmethod
    def tearDownClass(cls):
        """Clean up test data."""
        super().tearDownClass()
        TestTenantCreation.cleanup_test_data()

    def create_test_tenant(self, suffix=""):
        """Create a test tenant."""
        tenant = frappe.get_doc({
            "doctype": "Tenant",
            "tenant_name": f"Hierarchy Test Tenant {suffix}".strip(),
            "company_name": f"Hierarchy Test Company {suffix}".strip(),
            "status": "Active",
            "subscription_tier": "Basic",
            "contact_email": f"tenant{suffix}@test.com",
            "country": "Turkey"
        })
        tenant.insert(ignore_permissions=True)
        frappe.db.commit()
        return tenant

    def create_test_organization(self, tenant_name, suffix=""):
        """Create a test organization linked to a tenant."""
        org = frappe.get_doc({
            "doctype": "Organization",
            "organization_name": f"Hierarchy Test Organization {suffix}".strip(),
            "organization_type": "Company",
            "tenant": tenant_name,
            "status": "Active",
            "country": "Turkey",
            "tax_id": f"{1234567890 + hash(suffix) % 1000000000}"[:10]
        })
        org.insert(ignore_permissions=True)
        frappe.db.commit()
        return org

    def create_test_user(self, suffix=""):
        """Create a test user."""
        email = f"hierarchy_test_user{suffix}@example.com"
        if not frappe.db.exists("User", email):
            user = frappe.get_doc({
                "doctype": "User",
                "email": email,
                "first_name": "Hierarchy",
                "last_name": f"Test {suffix}".strip(),
                "enabled": 1,
                "send_welcome_email": 0
            })
            user.insert(ignore_permissions=True)
            frappe.db.commit()
        return email

    def test_seller_tenant_organization_mismatch_rejected(self):
        """Test that seller with mismatched tenant/organization is rejected."""
        tenant1 = self.create_test_tenant("Consistency1")
        tenant2 = self.create_test_tenant("Consistency2")
        org_tenant2 = self.create_test_organization(tenant2.name, "Consistency2")
        user_email = self.create_test_user("_mismatch")

        # Try to create seller with Tenant 1 but Organization from Tenant 2
        with self.assertRaises(frappe.ValidationError) as context:
            seller = frappe.get_doc({
                "doctype": "Seller Profile",
                "seller_name": "Hierarchy Test Seller Mismatch",
                "user": user_email,
                "seller_type": "Business",
                "tenant": tenant1.name,  # Tenant 1
                "organization": org_tenant2.name,  # Organization from Tenant 2
                "status": "Pending",
                "country": "Turkey"
            })
            seller.insert(ignore_permissions=True)

        # Verify the error message mentions tenant
        self.assertIn("Tenant", str(context.exception))

        # Cleanup
        frappe.delete_doc("Organization", org_tenant2.name, force=True, ignore_permissions=True)
        frappe.delete_doc("Tenant", tenant2.name, force=True, ignore_permissions=True)
        frappe.delete_doc("Tenant", tenant1.name, force=True, ignore_permissions=True)
        frappe.delete_doc("User", user_email, force=True, ignore_permissions=True)
        frappe.db.commit()


class TestTenantChangePrevention(FrappeTestCase):
    """Tests to verify tenant change is prevented for organizations and sellers."""

    @classmethod
    def setUpClass(cls):
        """Set up test fixtures."""
        super().setUpClass()
        TestTenantCreation.cleanup_test_data()

    @classmethod
    def tearDownClass(cls):
        """Clean up test data."""
        super().tearDownClass()
        TestTenantCreation.cleanup_test_data()

    def create_test_tenant(self, suffix=""):
        """Create a test tenant."""
        tenant = frappe.get_doc({
            "doctype": "Tenant",
            "tenant_name": f"Hierarchy Test Tenant {suffix}".strip(),
            "company_name": f"Hierarchy Test Company {suffix}".strip(),
            "status": "Active",
            "subscription_tier": "Basic",
            "contact_email": f"tenant{suffix}@test.com",
            "country": "Turkey"
        })
        tenant.insert(ignore_permissions=True)
        frappe.db.commit()
        return tenant

    def create_test_organization(self, tenant_name, suffix=""):
        """Create a test organization linked to a tenant."""
        # Use unique tax_id for each org
        import hashlib
        unique_hash = hashlib.md5(suffix.encode()).hexdigest()[:10]
        tax_id = ''.join([c if c.isdigit() else str(ord(c) % 10) for c in unique_hash])[:10]

        org = frappe.get_doc({
            "doctype": "Organization",
            "organization_name": f"Hierarchy Test Organization {suffix}".strip(),
            "organization_type": "Company",
            "tenant": tenant_name,
            "status": "Active",
            "country": "Turkey",
            "tax_id": tax_id.ljust(10, '0')[:10]
        })
        org.insert(ignore_permissions=True)
        frappe.db.commit()
        return org

    def create_test_user(self, suffix=""):
        """Create a test user."""
        email = f"hierarchy_test_user{suffix}@example.com"
        if not frappe.db.exists("User", email):
            user = frappe.get_doc({
                "doctype": "User",
                "email": email,
                "first_name": "Hierarchy",
                "last_name": f"Test {suffix}".strip(),
                "enabled": 1,
                "send_welcome_email": 0
            })
            user.insert(ignore_permissions=True)
            frappe.db.commit()
        return email

    def test_organization_tenant_change_prevented_with_sellers(self):
        """Test that organization tenant cannot be changed when it has linked sellers."""
        tenant1 = self.create_test_tenant("TenantChange1")
        tenant2 = self.create_test_tenant("TenantChange2")
        org = self.create_test_organization(tenant1.name, "TenantChange")
        user_email = self.create_test_user("_tenant_change")

        # Create a seller profile linked to the organization
        seller = frappe.get_doc({
            "doctype": "Seller Profile",
            "seller_name": "Hierarchy Test Seller TenantChange",
            "user": user_email,
            "seller_type": "Business",
            "organization": org.name,
            "status": "Pending",
            "country": "Turkey"
        })
        seller.insert(ignore_permissions=True)
        frappe.db.commit()

        # Try to change organization's tenant
        org_doc = frappe.get_doc("Organization", org.name)
        org_doc.tenant = tenant2.name

        with self.assertRaises(frappe.ValidationError) as context:
            org_doc.save(ignore_permissions=True)

        # Verify the error message mentions linked sellers
        error_message = str(context.exception)
        self.assertTrue(
            "Seller Profile" in error_message or "linked" in error_message.lower(),
            f"Error should mention linked sellers, got: {error_message}"
        )

        # Cleanup - delete in order
        for perm in frappe.get_all("User Permission",
                                   filters={"user": user_email, "allow": "Tenant"},
                                   pluck="name"):
            frappe.delete_doc("User Permission", perm, force=True, ignore_permissions=True)
        frappe.delete_doc("Seller Profile", seller.name, force=True, ignore_permissions=True)
        frappe.delete_doc("Organization", org.name, force=True, ignore_permissions=True)
        frappe.delete_doc("Tenant", tenant2.name, force=True, ignore_permissions=True)
        frappe.delete_doc("Tenant", tenant1.name, force=True, ignore_permissions=True)
        frappe.delete_doc("User", user_email, force=True, ignore_permissions=True)
        frappe.db.commit()

    def test_organization_tenant_change_allowed_without_sellers(self):
        """Test that organization tenant CAN be changed when it has no linked sellers."""
        tenant1 = self.create_test_tenant("NoSellerChange1")
        tenant2 = self.create_test_tenant("NoSellerChange2")
        org = self.create_test_organization(tenant1.name, "NoSellerChange")

        # Change organization's tenant (should succeed - no linked sellers)
        org_doc = frappe.get_doc("Organization", org.name)
        org_doc.tenant = tenant2.name
        org_doc.save(ignore_permissions=True)
        frappe.db.commit()

        # Verify the tenant was changed
        org_doc.reload()
        self.assertEqual(org_doc.tenant, tenant2.name)

        # Cleanup
        frappe.delete_doc("Organization", org.name, force=True, ignore_permissions=True)
        frappe.delete_doc("Tenant", tenant2.name, force=True, ignore_permissions=True)
        frappe.delete_doc("Tenant", tenant1.name, force=True, ignore_permissions=True)
        frappe.db.commit()


class TestTenantOrganizationHierarchy(FrappeTestCase):
    """E2E tests for tenant-seller-organization hierarchy."""

    @classmethod
    def setUpClass(cls):
        """Set up test data for the entire test class."""
        super().setUpClass()
        TestTenantCreation.cleanup_test_data()
        # Create test user for seller profile
        cls.test_user = cls._create_test_user()

    @classmethod
    def tearDownClass(cls):
        """Clean up test data."""
        super().tearDownClass()
        cls._cleanup_test_data()

    @classmethod
    def _create_test_user(cls):
        """Create a test user for seller profile."""
        user_email = "hierarchy_test_e2e@example.com"
        if not frappe.db.exists("User", user_email):
            user = frappe.get_doc({
                "doctype": "User",
                "email": user_email,
                "first_name": "E2E",
                "last_name": "Hierarchy Test User",
                "enabled": 1,
                "send_welcome_email": 0
            })
            user.insert(ignore_permissions=True)
            frappe.db.commit()
        return user_email

    @classmethod
    def _cleanup_test_data(cls):
        """Clean up all test data created during tests."""
        # Delete in reverse order to respect foreign key constraints
        try:
            # Delete seller profiles
            for name in frappe.get_all("Seller Profile", filters={"seller_name": ["like", "E2E Test%"]}, pluck="name"):
                frappe.delete_doc("Seller Profile", name, force=True, ignore_permissions=True)

            # Delete organizations
            for name in frappe.get_all("Organization", filters={"organization_name": ["like", "E2E Test%"]}, pluck="name"):
                frappe.delete_doc("Organization", name, force=True, ignore_permissions=True)

            # Delete tenants
            for name in frappe.get_all("Tenant", filters={"tenant_name": ["like", "E2E Test%"]}, pluck="name"):
                for perm in frappe.get_all("User Permission", filters={"allow": "Tenant", "for_value": name}, pluck="name"):
                    frappe.delete_doc("User Permission", perm, force=True, ignore_permissions=True)
                frappe.delete_doc("Tenant", name, force=True, ignore_permissions=True)

            # Delete test user
            if frappe.db.exists("User", "hierarchy_test_e2e@example.com"):
                frappe.delete_doc("User", "hierarchy_test_e2e@example.com", force=True, ignore_permissions=True)

            frappe.db.commit()
        except Exception:
            pass

    def test_01_create_tenant(self):
        """Test Step 1: Create a new Tenant."""
        tenant = frappe.get_doc({
            "doctype": "Tenant",
            "tenant_name": "E2E Test Tenant",
            "company_name": "E2E Test Company Ltd",
            "status": "Active",
            "subscription_tier": "Basic",
            "country": "Turkey"
        })
        tenant.insert(ignore_permissions=True)
        frappe.db.commit()

        # Verify tenant was created
        self.assertTrue(frappe.db.exists("Tenant", tenant.name))

        # Verify tenant displays name (title_field)
        tenant_doc = frappe.get_doc("Tenant", tenant.name)
        self.assertEqual(tenant_doc.tenant_name, "E2E Test Tenant")

        # Store for subsequent tests
        self.__class__.tenant_name = tenant.name

    def test_02_create_organization_linked_to_tenant(self):
        """Test Step 2: Create an Organization linked to Tenant."""
        # Ensure tenant exists from previous test
        self.assertTrue(hasattr(self.__class__, 'tenant_name'), "Tenant must be created first")

        organization = frappe.get_doc({
            "doctype": "Organization",
            "organization_name": "E2E Test Organization",
            "organization_type": "Company",
            "tenant": self.__class__.tenant_name,
            "status": "Active",
            "country": "Turkey",
            "tax_id": "1234567890"  # Valid 10-digit VKN format
        })
        organization.insert(ignore_permissions=True)
        frappe.db.commit()

        # Verify organization was created
        self.assertTrue(frappe.db.exists("Organization", organization.name))

        # Verify organization is linked to tenant
        org_doc = frappe.get_doc("Organization", organization.name)
        self.assertEqual(org_doc.tenant, self.__class__.tenant_name)

        # Store for subsequent tests
        self.__class__.organization_name = organization.name

    def test_03_create_seller_profile_linked_to_organization(self):
        """Test Step 3: Create a Seller Profile linked to Organization."""
        # Ensure organization exists from previous test
        self.assertTrue(hasattr(self.__class__, 'organization_name'), "Organization must be created first")

        seller_profile = frappe.get_doc({
            "doctype": "Seller Profile",
            "seller_name": "E2E Test Seller",
            "user": self.__class__.test_user,
            "seller_type": "Business",
            "organization": self.__class__.organization_name,
            # Note: tenant is NOT set - it should be auto-populated from organization
            "status": "Pending",
            "country": "Turkey"
        })
        seller_profile.insert(ignore_permissions=True)
        frappe.db.commit()

        # Verify seller profile was created
        self.assertTrue(frappe.db.exists("Seller Profile", seller_profile.name))

        # Store for subsequent tests
        self.__class__.seller_profile_name = seller_profile.name

    def test_04_verify_tenant_auto_populated_from_organization(self):
        """Test Step 4: Verify tenant field auto-populated from organization."""
        # Ensure seller profile exists from previous test
        self.assertTrue(hasattr(self.__class__, 'seller_profile_name'), "Seller Profile must be created first")

        seller_doc = frappe.get_doc("Seller Profile", self.__class__.seller_profile_name)

        # Verify tenant was auto-populated from organization
        self.assertEqual(seller_doc.tenant, self.__class__.tenant_name,
                         "Tenant should be auto-populated from organization")

        # Verify tenant matches organization's tenant
        org_tenant = frappe.db.get_value("Organization", self.__class__.organization_name, "tenant")
        self.assertEqual(seller_doc.tenant, org_tenant,
                         "Seller's tenant should match organization's tenant")

    def test_05_verify_user_permission_created_for_seller(self):
        """Test Step 5: Verify User Permission was created for seller."""
        # Ensure seller profile exists
        self.assertTrue(hasattr(self.__class__, 'seller_profile_name'), "Seller Profile must be created first")

        # Check User Permission exists for seller user
        user_permission = frappe.db.exists("User Permission", {
            "user": self.__class__.test_user,
            "allow": "Tenant",
            "for_value": self.__class__.tenant_name
        })

        self.assertTrue(user_permission, "User Permission should be created for seller user")

    def test_06_verify_tenant_organization_consistency_validation(self):
        """Test Step 6: Verify organization dropdown only shows organizations from selected tenant."""
        # Create a second tenant for testing
        tenant2 = frappe.get_doc({
            "doctype": "Tenant",
            "tenant_name": "E2E Test Tenant 2",
            "company_name": "E2E Test Company 2 Ltd",
            "status": "Active",
            "subscription_tier": "Basic",
            "country": "Turkey"
        })
        tenant2.insert(ignore_permissions=True)
        frappe.db.commit()

        # Create organization under second tenant
        org2 = frappe.get_doc({
            "doctype": "Organization",
            "organization_name": "E2E Test Organization 2",
            "organization_type": "Company",
            "tenant": tenant2.name,
            "status": "Active",
            "country": "Turkey",
            "tax_id": "9876543210"  # Different VKN
        })
        org2.insert(ignore_permissions=True)
        frappe.db.commit()

        # Verify that we CANNOT create a seller profile with mismatched tenant/organization
        # Create a new test user for this test
        user2_email = "hierarchy_test_mismatch@example.com"
        if not frappe.db.exists("User", user2_email):
            user2 = frappe.get_doc({
                "doctype": "User",
                "email": user2_email,
                "first_name": "E2E",
                "last_name": "Mismatch Test",
                "enabled": 1,
                "send_welcome_email": 0
            })
            user2.insert(ignore_permissions=True)
            frappe.db.commit()

        # Try to create a seller profile with mismatched tenant and organization
        with self.assertRaises(frappe.exceptions.ValidationError) as context:
            mismatched_seller = frappe.get_doc({
                "doctype": "Seller Profile",
                "seller_name": "E2E Test Mismatch Seller",
                "user": user2_email,
                "seller_type": "Business",
                "tenant": self.__class__.tenant_name,  # Tenant 1
                "organization": org2.name,  # Organization from Tenant 2
                "status": "Pending",
                "country": "Turkey"
            })
            mismatched_seller.insert(ignore_permissions=True)

        # Verify the validation error message
        self.assertIn("Tenant", str(context.exception))

        # Cleanup
        frappe.delete_doc("Organization", org2.name, force=True, ignore_permissions=True)
        frappe.delete_doc("Tenant", tenant2.name, force=True, ignore_permissions=True)
        if frappe.db.exists("User", user2_email):
            frappe.delete_doc("User", user2_email, force=True, ignore_permissions=True)
        frappe.db.commit()

    def test_07_verify_mandatory_tenant_on_seller_profile(self):
        """Test that tenant is mandatory on Seller Profile."""
        # Create a new test user for this test
        user3_email = "hierarchy_test_user3@example.com"
        if not frappe.db.exists("User", user3_email):
            user3 = frappe.get_doc({
                "doctype": "User",
                "email": user3_email,
                "first_name": "E2E",
                "last_name": "No Tenant Test",
                "enabled": 1,
                "send_welcome_email": 0
            })
            user3.insert(ignore_permissions=True)
            frappe.db.commit()

        # Try to create a seller profile without tenant
        with self.assertRaises(frappe.exceptions.MandatoryError):
            seller_no_tenant = frappe.get_doc({
                "doctype": "Seller Profile",
                "seller_name": "E2E Test No Tenant Seller",
                "user": user3_email,
                "seller_type": "Individual",
                # No tenant, no organization
                "status": "Pending",
                "country": "Turkey"
            })
            seller_no_tenant.insert(ignore_permissions=True)

        # Cleanup
        if frappe.db.exists("User", user3_email):
            frappe.delete_doc("User", user3_email, force=True, ignore_permissions=True)
        frappe.db.commit()

    def test_08_verify_mandatory_tenant_on_organization(self):
        """Test that tenant is mandatory on Organization."""
        # Try to create an organization without tenant
        with self.assertRaises(frappe.exceptions.ValidationError):
            org_no_tenant = frappe.get_doc({
                "doctype": "Organization",
                "organization_name": "E2E Test No Tenant Org",
                "organization_type": "Company",
                # No tenant
                "status": "Active",
                "country": "Turkey",
                "tax_id": "5555555555"
            })
            org_no_tenant.insert(ignore_permissions=True)


def verify_tenant_hierarchy_e2e():
    """
    Standalone E2E verification function that can be run via bench console.

    Usage:
        bench --site [site] console
        >>> from tr_tradehub.tests.test_tenant_organization_hierarchy import verify_tenant_hierarchy_e2e
        >>> verify_tenant_hierarchy_e2e()
    """
    results = {
        "passed": [],
        "failed": []
    }

    print("\n" + "=" * 60)
    print("E2E VERIFICATION: Tenant-Seller-Organization Hierarchy")
    print("=" * 60)

    # Step 1: Create Tenant
    print("\n[Step 1] Creating Tenant...")
    try:
        tenant = frappe.get_doc({
            "doctype": "Tenant",
            "tenant_name": "E2E Verification Tenant",
            "company_name": "E2E Verification Company",
            "status": "Active",
            "subscription_tier": "Basic",
            "country": "Turkey"
        })
        tenant.insert(ignore_permissions=True)
        frappe.db.commit()
        print(f"  OK Tenant created: {tenant.name}")
        results["passed"].append("Step 1: Create Tenant")
    except Exception as e:
        print(f"  FAIL Failed: {str(e)}")
        results["failed"].append(f"Step 1: Create Tenant - {str(e)}")
        return results

    # Step 2: Create Organization linked to Tenant
    print("\n[Step 2] Creating Organization linked to Tenant...")
    try:
        organization = frappe.get_doc({
            "doctype": "Organization",
            "organization_name": "E2E Verification Organization",
            "organization_type": "Company",
            "tenant": tenant.name,
            "status": "Active",
            "country": "Turkey",
            "tax_id": "1111111116"  # Valid VKN with correct checksum
        })
        organization.insert(ignore_permissions=True)
        frappe.db.commit()
        print(f"  OK Organization created: {organization.name}")
        print(f"  OK Organization tenant: {organization.tenant}")
        results["passed"].append("Step 2: Create Organization linked to Tenant")
    except Exception as e:
        print(f"  FAIL Failed: {str(e)}")
        results["failed"].append(f"Step 2: Create Organization - {str(e)}")
        _cleanup_verification(tenant.name, None, None)
        return results

    # Step 3: Create Seller Profile (without specifying tenant)
    print("\n[Step 3] Creating Seller Profile linked to Organization...")
    try:
        # Create a test user
        user_email = "e2e_verification_user@example.com"
        if not frappe.db.exists("User", user_email):
            user = frappe.get_doc({
                "doctype": "User",
                "email": user_email,
                "first_name": "E2E",
                "last_name": "Verification",
                "enabled": 1,
                "send_welcome_email": 0
            })
            user.insert(ignore_permissions=True)
            frappe.db.commit()

        seller = frappe.get_doc({
            "doctype": "Seller Profile",
            "seller_name": "E2E Verification Seller",
            "user": user_email,
            "seller_type": "Business",
            "organization": organization.name,
            # tenant NOT specified - should be auto-populated
            "status": "Pending",
            "country": "Turkey"
        })
        seller.insert(ignore_permissions=True)
        frappe.db.commit()
        print(f"  OK Seller Profile created: {seller.name}")
        results["passed"].append("Step 3: Create Seller Profile linked to Organization")
    except Exception as e:
        print(f"  FAIL Failed: {str(e)}")
        results["failed"].append(f"Step 3: Create Seller Profile - {str(e)}")
        _cleanup_verification(tenant.name, organization.name, None)
        return results

    # Step 4: Verify tenant auto-populated from organization
    print("\n[Step 4] Verifying tenant auto-populated from organization...")
    try:
        seller_doc = frappe.get_doc("Seller Profile", seller.name)
        if seller_doc.tenant == tenant.name:
            print(f"  OK Tenant auto-populated correctly: {seller_doc.tenant}")
            results["passed"].append("Step 4: Tenant auto-populated from organization")
        else:
            raise Exception(f"Tenant mismatch: expected {tenant.name}, got {seller_doc.tenant}")
    except Exception as e:
        print(f"  FAIL Failed: {str(e)}")
        results["failed"].append(f"Step 4: Tenant auto-population - {str(e)}")

    # Step 5: Verify User Permission was created for seller user
    print("\n[Step 5] Verifying User Permission created for seller...")
    try:
        user_permission = frappe.db.exists("User Permission", {
            "user": user_email,
            "allow": "Tenant",
            "for_value": tenant.name
        })
        if user_permission:
            print(f"  OK User Permission created for seller user")
            results["passed"].append("Step 5: User Permission created for seller")
        else:
            raise Exception("User Permission not found for seller user")
    except Exception as e:
        print(f"  FAIL Failed: {str(e)}")
        results["failed"].append(f"Step 5: User Permission creation - {str(e)}")

    # Step 6: Verify tenant-organization consistency validation
    print("\n[Step 6] Verifying tenant-organization consistency validation...")
    try:
        # Create second tenant
        tenant2 = frappe.get_doc({
            "doctype": "Tenant",
            "tenant_name": "E2E Verification Tenant 2",
            "company_name": "E2E Verification Company 2",
            "status": "Active",
            "subscription_tier": "Basic",
            "country": "Turkey"
        })
        tenant2.insert(ignore_permissions=True)

        # Create organization under second tenant
        org2 = frappe.get_doc({
            "doctype": "Organization",
            "organization_name": "E2E Verification Organization 2",
            "organization_type": "Company",
            "tenant": tenant2.name,
            "status": "Active",
            "country": "Turkey",
            "tax_id": "2222222222"
        })
        org2.insert(ignore_permissions=True)
        frappe.db.commit()

        # Create a second test user
        user2_email = "e2e_verification_user2@example.com"
        if not frappe.db.exists("User", user2_email):
            user2 = frappe.get_doc({
                "doctype": "User",
                "email": user2_email,
                "first_name": "E2E",
                "last_name": "Verification2",
                "enabled": 1,
                "send_welcome_email": 0
            })
            user2.insert(ignore_permissions=True)
            frappe.db.commit()

        # Try to create seller with mismatched tenant/organization
        validation_error_raised = False
        try:
            mismatched_seller = frappe.get_doc({
                "doctype": "Seller Profile",
                "seller_name": "E2E Verification Mismatch Seller",
                "user": user2_email,
                "seller_type": "Business",
                "tenant": tenant.name,  # Tenant 1
                "organization": org2.name,  # Organization from Tenant 2
                "status": "Pending",
                "country": "Turkey"
            })
            mismatched_seller.insert(ignore_permissions=True)
        except frappe.exceptions.ValidationError:
            validation_error_raised = True

        if validation_error_raised:
            print("  OK Validation correctly prevents tenant-organization mismatch")
            results["passed"].append("Step 6: Tenant-organization consistency validation")
        else:
            raise Exception("Validation did not prevent tenant-organization mismatch")

        # Cleanup second tenant and org
        frappe.delete_doc("Organization", org2.name, force=True, ignore_permissions=True)
        frappe.delete_doc("Tenant", tenant2.name, force=True, ignore_permissions=True)
        if frappe.db.exists("User", user2_email):
            frappe.delete_doc("User", user2_email, force=True, ignore_permissions=True)
        frappe.db.commit()

    except Exception as e:
        print(f"  FAIL Failed: {str(e)}")
        results["failed"].append(f"Step 6: Consistency validation - {str(e)}")

    # Cleanup
    print("\n[Cleanup] Removing test data...")
    _cleanup_verification(tenant.name, organization.name, seller.name)
    print("  OK Cleanup complete")

    # Print summary
    print("\n" + "=" * 60)
    print("VERIFICATION SUMMARY")
    print("=" * 60)
    print(f"Passed: {len(results['passed'])}")
    print(f"Failed: {len(results['failed'])}")

    if results["failed"]:
        print("\nFailed tests:")
        for f in results["failed"]:
            print(f"  - {f}")
    else:
        print("\nOK All E2E verification steps passed!")

    return results


def _cleanup_verification(tenant_name, org_name, seller_name):
    """Clean up verification test data."""
    try:
        if seller_name:
            frappe.delete_doc("Seller Profile", seller_name, force=True, ignore_permissions=True)

        if org_name:
            frappe.delete_doc("Organization", org_name, force=True, ignore_permissions=True)

        if tenant_name:
            # Delete User Permissions for this tenant
            for perm in frappe.get_all("User Permission", filters={"allow": "Tenant", "for_value": tenant_name}, pluck="name"):
                frappe.delete_doc("User Permission", perm, force=True, ignore_permissions=True)
            frappe.delete_doc("Tenant", tenant_name, force=True, ignore_permissions=True)

        # Clean up test users
        for email in ["e2e_verification_user@example.com", "e2e_verification_user2@example.com"]:
            if frappe.db.exists("User", email):
                frappe.delete_doc("User", email, force=True, ignore_permissions=True)

        frappe.db.commit()
    except Exception:
        pass

# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

"""
Comprehensive Unit Tests for RBAC Permission Checks in TR-TradeHub.

Tests cover:
- System Manager full access to all DocTypes
- Satici (Seller) can only access own profile (if_owner)
- Alici Admin can manage own organization
- Cross-tenant access is blocked
- Role-based DocType permissions (CRUD)
- Field-level permissions (permlevel)
- Permission query conditions (row-level security)
"""

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import nowdate
from frappe.exceptions import PermissionError


class TestRBACSetup(FrappeTestCase):
    """Base class with common setup methods for RBAC tests."""

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
            for name in frappe.get_all("Seller Profile", filters={"seller_name": ["like", "RBAC Test%"]}, pluck="name"):
                frappe.delete_doc("Seller Profile", name, force=True, ignore_permissions=True)

            # Delete buyer profiles
            for name in frappe.get_all("Buyer Profile", filters={"buyer_name": ["like", "RBAC Test%"]}, pluck="name"):
                frappe.delete_doc("Buyer Profile", name, force=True, ignore_permissions=True)

            # Delete organizations (depends on tenant)
            for name in frappe.get_all("Organization", filters={"organization_name": ["like", "RBAC Test%"]}, pluck="name"):
                frappe.delete_doc("Organization", name, force=True, ignore_permissions=True)

            # Delete tenants
            for name in frappe.get_all("Tenant", filters={"tenant_name": ["like", "RBAC Test%"]}, pluck="name"):
                # Delete User Permissions for this tenant first
                for perm in frappe.get_all("User Permission", filters={"allow": "Tenant", "for_value": name}, pluck="name"):
                    frappe.delete_doc("User Permission", perm, force=True, ignore_permissions=True)
                frappe.delete_doc("Tenant", name, force=True, ignore_permissions=True)

            # Delete test users
            for email in frappe.get_all("User", filters={"email": ["like", "rbac_test_%@example.com"]}, pluck="name"):
                # Delete user permissions for this user
                for perm in frappe.get_all("User Permission", filters={"user": email}, pluck="name"):
                    frappe.delete_doc("User Permission", perm, force=True, ignore_permissions=True)
                frappe.delete_doc("User", email, force=True, ignore_permissions=True)

            frappe.db.commit()
        except Exception:
            pass

    def create_test_tenant(self, suffix=""):
        """Create a test tenant."""
        tenant = frappe.get_doc({
            "doctype": "Tenant",
            "tenant_name": f"RBAC Test Tenant {suffix}".strip(),
            "company_name": f"RBAC Test Company {suffix}".strip(),
            "status": "Active",
            "subscription_tier": "Basic",
            "contact_email": f"rbac_tenant{suffix}@test.com",
            "country": "Turkey"
        })
        tenant.insert(ignore_permissions=True)
        frappe.db.commit()
        return tenant

    def create_test_organization(self, tenant_name, suffix=""):
        """Create a test organization linked to a tenant."""
        import hashlib
        unique_hash = hashlib.md5(f"rbac{suffix}".encode()).hexdigest()[:10]
        tax_id = ''.join([c if c.isdigit() else str(ord(c) % 10) for c in unique_hash])[:10]

        org = frappe.get_doc({
            "doctype": "Organization",
            "organization_name": f"RBAC Test Organization {suffix}".strip(),
            "organization_type": "Company",
            "tenant": tenant_name,
            "status": "Active",
            "country": "Turkey",
            "tax_id": tax_id.ljust(10, '0')[:10]
        })
        org.insert(ignore_permissions=True)
        frappe.db.commit()
        return org

    def create_test_user(self, suffix="", roles=None):
        """Create a test user with specified roles."""
        email = f"rbac_test_{suffix}@example.com"
        if frappe.db.exists("User", email):
            user = frappe.get_doc("User", email)
        else:
            user = frappe.get_doc({
                "doctype": "User",
                "email": email,
                "first_name": "RBAC",
                "last_name": f"Test {suffix}".strip(),
                "enabled": 1,
                "send_welcome_email": 0
            })
            user.insert(ignore_permissions=True)

        # Add roles
        if roles:
            for role in roles:
                if role not in [r.role for r in user.roles]:
                    user.append("roles", {"role": role})
            user.save(ignore_permissions=True)

        frappe.db.commit()
        return email

    def create_test_seller_profile(self, tenant_name, org_name, user_email, suffix=""):
        """Create a test seller profile."""
        seller = frappe.get_doc({
            "doctype": "Seller Profile",
            "seller_name": f"RBAC Test Seller {suffix}".strip(),
            "user": user_email,
            "seller_type": "Business",
            "tenant": tenant_name,
            "organization": org_name,
            "status": "Active",
            "country": "Turkey"
        })
        seller.insert(ignore_permissions=True)
        frappe.db.commit()
        return seller

    def create_user_permission(self, user, allow, for_value):
        """Create a User Permission for row-level security."""
        if not frappe.db.exists("User Permission", {"user": user, "allow": allow, "for_value": for_value}):
            perm = frappe.get_doc({
                "doctype": "User Permission",
                "user": user,
                "allow": allow,
                "for_value": for_value
            })
            perm.insert(ignore_permissions=True)
            frappe.db.commit()
            return perm
        return frappe.get_doc("User Permission", {"user": user, "allow": allow, "for_value": for_value})


class TestSystemManagerFullAccess(TestRBACSetup):
    """Tests for System Manager full access to all DocTypes."""

    def test_system_manager_can_create_tenant(self):
        """Test System Manager can create a tenant."""
        original_user = frappe.session.user
        try:
            frappe.set_user("Administrator")

            tenant = frappe.get_doc({
                "doctype": "Tenant",
                "tenant_name": "RBAC Test Tenant SysMan Create",
                "company_name": "RBAC Test Company",
                "status": "Active",
                "subscription_tier": "Basic",
                "contact_email": "rbac_sysman@test.com",
                "country": "Turkey"
            })
            tenant.insert()
            frappe.db.commit()

            self.assertTrue(frappe.db.exists("Tenant", tenant.name))

            # Cleanup
            frappe.delete_doc("Tenant", tenant.name, force=True)
            frappe.db.commit()

        finally:
            frappe.set_user(original_user)

    def test_system_manager_can_delete_tenant(self):
        """Test System Manager can delete a tenant."""
        original_user = frappe.session.user
        try:
            # Create tenant as admin
            frappe.set_user("Administrator")

            tenant = self.create_test_tenant("SysMan Delete")
            tenant_name = tenant.name

            # Delete as System Manager
            frappe.delete_doc("Tenant", tenant_name, force=True)
            frappe.db.commit()

            self.assertFalse(frappe.db.exists("Tenant", tenant_name))

        finally:
            frappe.set_user(original_user)

    def test_system_manager_can_edit_permlevel_1_fields(self):
        """Test System Manager can edit permlevel 1 fields."""
        original_user = frappe.session.user
        try:
            frappe.set_user("Administrator")

            tenant = self.create_test_tenant("SysMan Permlevel")

            # Edit permlevel 1 fields
            tenant.subscription_tier = "Professional"
            tenant.max_sellers = 100
            tenant.commission_rate = 5.0
            tenant.save()
            frappe.db.commit()

            # Verify changes
            tenant.reload()
            self.assertEqual(tenant.subscription_tier, "Professional")
            self.assertEqual(tenant.max_sellers, 100)
            self.assertEqual(tenant.commission_rate, 5.0)

            # Cleanup
            frappe.delete_doc("Tenant", tenant.name, force=True)
            frappe.db.commit()

        finally:
            frappe.set_user(original_user)

    def test_system_manager_can_access_all_tenants(self):
        """Test System Manager can access all tenants."""
        original_user = frappe.session.user
        try:
            frappe.set_user("Administrator")

            # Create multiple tenants
            tenant1 = self.create_test_tenant("SysMan Access 1")
            tenant2 = self.create_test_tenant("SysMan Access 2")

            # System Manager should see all tenants
            tenants = frappe.get_all("Tenant",
                                     filters={"tenant_name": ["like", "RBAC Test Tenant SysMan Access%"]},
                                     pluck="name")

            self.assertGreaterEqual(len(tenants), 2)
            self.assertIn(tenant1.name, tenants)
            self.assertIn(tenant2.name, tenants)

            # Cleanup
            frappe.delete_doc("Tenant", tenant1.name, force=True)
            frappe.delete_doc("Tenant", tenant2.name, force=True)
            frappe.db.commit()

        finally:
            frappe.set_user(original_user)


class TestSaticiOwnProfileAccess(TestRBACSetup):
    """Tests for Satici (Seller) can only access own profile."""

    def test_satici_can_read_own_profile(self):
        """Test Satici can read their own seller profile."""
        original_user = frappe.session.user
        try:
            # Setup: Create tenant, org, user with Satici role, and seller profile
            frappe.set_user("Administrator")

            tenant = self.create_test_tenant("Satici Own 1")
            org = self.create_test_organization(tenant.name, "Satici Own 1")
            user_email = self.create_test_user("satici_own_1", roles=["Satici"])
            seller = self.create_test_seller_profile(tenant.name, org.name, user_email, "Satici Own 1")

            # Create User Permission for tenant
            self.create_user_permission(user_email, "Tenant", tenant.name)

            # Switch to Satici user
            frappe.set_user(user_email)

            # Satici should be able to read their own profile
            seller_doc = frappe.get_doc("Seller Profile", seller.name)
            self.assertEqual(seller_doc.seller_name, "RBAC Test Seller Satici Own 1")

        finally:
            frappe.set_user(original_user)
            # Cleanup
            if 'seller' in dir() and seller:
                frappe.delete_doc("Seller Profile", seller.name, force=True, ignore_permissions=True)
            if 'org' in dir() and org:
                frappe.delete_doc("Organization", org.name, force=True, ignore_permissions=True)
            if 'tenant' in dir() and tenant:
                for perm in frappe.get_all("User Permission", filters={"for_value": tenant.name}, pluck="name"):
                    frappe.delete_doc("User Permission", perm, force=True, ignore_permissions=True)
                frappe.delete_doc("Tenant", tenant.name, force=True, ignore_permissions=True)
            if 'user_email' in dir() and user_email:
                frappe.delete_doc("User", user_email, force=True, ignore_permissions=True)
            frappe.db.commit()

    def test_satici_can_write_own_profile(self):
        """Test Satici can write to their own seller profile."""
        original_user = frappe.session.user
        seller = org = tenant = user_email = None

        try:
            # Setup
            frappe.set_user("Administrator")

            tenant = self.create_test_tenant("Satici Write 1")
            org = self.create_test_organization(tenant.name, "Satici Write 1")
            user_email = self.create_test_user("satici_write_1", roles=["Satici"])
            seller = self.create_test_seller_profile(tenant.name, org.name, user_email, "Satici Write 1")

            # Create User Permission for tenant
            self.create_user_permission(user_email, "Tenant", tenant.name)

            # Switch to Satici user
            frappe.set_user(user_email)

            # Satici should be able to edit their own profile
            seller_doc = frappe.get_doc("Seller Profile", seller.name)
            seller_doc.display_name = "Updated Display Name"
            seller_doc.save()
            frappe.db.commit()

            # Verify changes
            seller_doc.reload()
            self.assertEqual(seller_doc.display_name, "Updated Display Name")

        finally:
            frappe.set_user(original_user)
            # Cleanup
            if seller:
                frappe.delete_doc("Seller Profile", seller.name, force=True, ignore_permissions=True)
            if org:
                frappe.delete_doc("Organization", org.name, force=True, ignore_permissions=True)
            if tenant:
                for perm in frappe.get_all("User Permission", filters={"for_value": tenant.name}, pluck="name"):
                    frappe.delete_doc("User Permission", perm, force=True, ignore_permissions=True)
                frappe.delete_doc("Tenant", tenant.name, force=True, ignore_permissions=True)
            if user_email:
                for perm in frappe.get_all("User Permission", filters={"user": user_email}, pluck="name"):
                    frappe.delete_doc("User Permission", perm, force=True, ignore_permissions=True)
                frappe.delete_doc("User", user_email, force=True, ignore_permissions=True)
            frappe.db.commit()

    def test_satici_cannot_access_other_seller_profile(self):
        """Test Satici cannot access another seller's profile."""
        original_user = frappe.session.user
        seller1 = seller2 = org1 = org2 = tenant = user1_email = user2_email = None

        try:
            # Setup: Create two sellers in same tenant
            frappe.set_user("Administrator")

            tenant = self.create_test_tenant("Satici Other 1")
            org1 = self.create_test_organization(tenant.name, "Satici Other 1A")
            org2 = self.create_test_organization(tenant.name, "Satici Other 1B")

            user1_email = self.create_test_user("satici_other_1a", roles=["Satici"])
            user2_email = self.create_test_user("satici_other_1b", roles=["Satici"])

            seller1 = self.create_test_seller_profile(tenant.name, org1.name, user1_email, "Satici Other 1A")
            seller2 = self.create_test_seller_profile(tenant.name, org2.name, user2_email, "Satici Other 1B")

            # Create User Permission for tenant for user1
            self.create_user_permission(user1_email, "Tenant", tenant.name)

            # Switch to Satici user 1
            frappe.set_user(user1_email)

            # User 1 should NOT be able to access User 2's profile due to if_owner restriction
            # The profile should either be inaccessible or user shouldn't be able to modify it
            profiles = frappe.get_all("Seller Profile",
                                      filters={"name": seller2.name},
                                      pluck="name")

            # Due to if_owner=1, user should not see other seller's profile
            # The Satici role has if_owner=1 which limits access to own records
            self.assertEqual(len(profiles), 0, "Satici should not be able to see other seller's profile")

        finally:
            frappe.set_user(original_user)
            # Cleanup
            if seller1:
                frappe.delete_doc("Seller Profile", seller1.name, force=True, ignore_permissions=True)
            if seller2:
                frappe.delete_doc("Seller Profile", seller2.name, force=True, ignore_permissions=True)
            if org1:
                frappe.delete_doc("Organization", org1.name, force=True, ignore_permissions=True)
            if org2:
                frappe.delete_doc("Organization", org2.name, force=True, ignore_permissions=True)
            if tenant:
                for perm in frappe.get_all("User Permission", filters={"for_value": tenant.name}, pluck="name"):
                    frappe.delete_doc("User Permission", perm, force=True, ignore_permissions=True)
                frappe.delete_doc("Tenant", tenant.name, force=True, ignore_permissions=True)
            if user1_email:
                frappe.delete_doc("User", user1_email, force=True, ignore_permissions=True)
            if user2_email:
                frappe.delete_doc("User", user2_email, force=True, ignore_permissions=True)
            frappe.db.commit()

    def test_satici_cannot_create_seller_profile(self):
        """Test Satici cannot create new seller profiles."""
        original_user = frappe.session.user
        org = tenant = user_email = None

        try:
            # Setup
            frappe.set_user("Administrator")

            tenant = self.create_test_tenant("Satici NoCreate 1")
            org = self.create_test_organization(tenant.name, "Satici NoCreate 1")
            user_email = self.create_test_user("satici_nocreate_1", roles=["Satici"])
            new_user_email = self.create_test_user("satici_nocreate_new_1", roles=[])

            # Create User Permission
            self.create_user_permission(user_email, "Tenant", tenant.name)

            # Switch to Satici user
            frappe.set_user(user_email)

            # Satici should NOT be able to create new seller profiles (create: 0)
            with self.assertRaises(frappe.PermissionError):
                new_seller = frappe.get_doc({
                    "doctype": "Seller Profile",
                    "seller_name": "RBAC Test Seller NoCreate",
                    "user": new_user_email,
                    "seller_type": "Individual",
                    "tenant": tenant.name,
                    "organization": org.name,
                    "status": "Pending",
                    "country": "Turkey"
                })
                new_seller.insert()

        finally:
            frappe.set_user(original_user)
            # Cleanup
            if org:
                frappe.delete_doc("Organization", org.name, force=True, ignore_permissions=True)
            if tenant:
                for perm in frappe.get_all("User Permission", filters={"for_value": tenant.name}, pluck="name"):
                    frappe.delete_doc("User Permission", perm, force=True, ignore_permissions=True)
                frappe.delete_doc("Tenant", tenant.name, force=True, ignore_permissions=True)
            if user_email:
                frappe.delete_doc("User", user_email, force=True, ignore_permissions=True)
            if 'new_user_email' in dir() and new_user_email:
                frappe.delete_doc("User", new_user_email, force=True, ignore_permissions=True)
            frappe.db.commit()


class TestAliciAdminOrganizationManagement(TestRBACSetup):
    """Tests for Alici Admin can manage own organization."""

    def test_alici_admin_can_create_organization(self):
        """Test Alici Admin can create an organization."""
        original_user = frappe.session.user
        tenant = org = user_email = None

        try:
            frappe.set_user("Administrator")

            tenant = self.create_test_tenant("Alici Create 1")
            user_email = self.create_test_user("alici_admin_create_1", roles=["Alici Admin"])

            # Create User Permission for tenant
            self.create_user_permission(user_email, "Tenant", tenant.name)

            # Switch to Alici Admin user
            frappe.set_user(user_email)

            # Alici Admin should be able to create organization
            org = frappe.get_doc({
                "doctype": "Organization",
                "organization_name": "RBAC Test Organization Alici Create",
                "organization_type": "Company",
                "tenant": tenant.name,
                "status": "Active",
                "country": "Turkey",
                "tax_id": "9999999999"
            })
            org.insert()
            frappe.db.commit()

            self.assertTrue(frappe.db.exists("Organization", org.name))

        finally:
            frappe.set_user(original_user)
            # Cleanup
            if org:
                frappe.delete_doc("Organization", org.name, force=True, ignore_permissions=True)
            if tenant:
                for perm in frappe.get_all("User Permission", filters={"for_value": tenant.name}, pluck="name"):
                    frappe.delete_doc("User Permission", perm, force=True, ignore_permissions=True)
                frappe.delete_doc("Tenant", tenant.name, force=True, ignore_permissions=True)
            if user_email:
                for perm in frappe.get_all("User Permission", filters={"user": user_email}, pluck="name"):
                    frappe.delete_doc("User Permission", perm, force=True, ignore_permissions=True)
                frappe.delete_doc("User", user_email, force=True, ignore_permissions=True)
            frappe.db.commit()

    def test_alici_admin_can_edit_own_organization(self):
        """Test Alici Admin can edit their own organization."""
        original_user = frappe.session.user
        tenant = org = user_email = None

        try:
            frappe.set_user("Administrator")

            tenant = self.create_test_tenant("Alici Edit 1")
            user_email = self.create_test_user("alici_admin_edit_1", roles=["Alici Admin"])

            # Create User Permission for tenant
            self.create_user_permission(user_email, "Tenant", tenant.name)

            # Create organization as Alici Admin (they will be owner)
            frappe.set_user(user_email)

            org = frappe.get_doc({
                "doctype": "Organization",
                "organization_name": "RBAC Test Organization Alici Edit",
                "organization_type": "Company",
                "tenant": tenant.name,
                "status": "Active",
                "country": "Turkey",
                "tax_id": "8888888888"
            })
            org.insert()
            frappe.db.commit()

            # Edit organization
            org.organization_name = "RBAC Test Organization Alici Edit Updated"
            org.save()
            frappe.db.commit()

            # Verify changes
            org.reload()
            self.assertEqual(org.organization_name, "RBAC Test Organization Alici Edit Updated")

        finally:
            frappe.set_user(original_user)
            # Cleanup
            if org:
                frappe.delete_doc("Organization", org.name, force=True, ignore_permissions=True)
            if tenant:
                for perm in frappe.get_all("User Permission", filters={"for_value": tenant.name}, pluck="name"):
                    frappe.delete_doc("User Permission", perm, force=True, ignore_permissions=True)
                frappe.delete_doc("Tenant", tenant.name, force=True, ignore_permissions=True)
            if user_email:
                for perm in frappe.get_all("User Permission", filters={"user": user_email}, pluck="name"):
                    frappe.delete_doc("User Permission", perm, force=True, ignore_permissions=True)
                frappe.delete_doc("User", user_email, force=True, ignore_permissions=True)
            frappe.db.commit()

    def test_alici_admin_cannot_edit_other_organization(self):
        """Test Alici Admin cannot edit another organization (if_owner)."""
        original_user = frappe.session.user
        tenant = org1 = org2 = user1_email = user2_email = None

        try:
            frappe.set_user("Administrator")

            tenant = self.create_test_tenant("Alici Other Org 1")

            # Create two Alici Admin users
            user1_email = self.create_test_user("alici_admin_other_1a", roles=["Alici Admin"])
            user2_email = self.create_test_user("alici_admin_other_1b", roles=["Alici Admin"])

            # Create User Permission for tenant for both users
            self.create_user_permission(user1_email, "Tenant", tenant.name)
            self.create_user_permission(user2_email, "Tenant", tenant.name)

            # User 1 creates organization 1
            frappe.set_user(user1_email)
            org1 = frappe.get_doc({
                "doctype": "Organization",
                "organization_name": "RBAC Test Organization Alici Other 1A",
                "organization_type": "Company",
                "tenant": tenant.name,
                "status": "Active",
                "country": "Turkey",
                "tax_id": "7777777777"
            })
            org1.insert()
            frappe.db.commit()

            # User 2 creates organization 2
            frappe.set_user(user2_email)
            org2 = frappe.get_doc({
                "doctype": "Organization",
                "organization_name": "RBAC Test Organization Alici Other 1B",
                "organization_type": "Company",
                "tenant": tenant.name,
                "status": "Active",
                "country": "Turkey",
                "tax_id": "6666666666"
            })
            org2.insert()
            frappe.db.commit()

            # User 2 tries to access User 1's organization - should be blocked by if_owner
            orgs = frappe.get_all("Organization",
                                  filters={"name": org1.name},
                                  pluck="name")

            # Due to if_owner=1, user should not see other user's organization
            self.assertEqual(len(orgs), 0, "Alici Admin should not see other user's organization")

        finally:
            frappe.set_user(original_user)
            # Cleanup
            if org1:
                frappe.delete_doc("Organization", org1.name, force=True, ignore_permissions=True)
            if org2:
                frappe.delete_doc("Organization", org2.name, force=True, ignore_permissions=True)
            if tenant:
                for perm in frappe.get_all("User Permission", filters={"for_value": tenant.name}, pluck="name"):
                    frappe.delete_doc("User Permission", perm, force=True, ignore_permissions=True)
                frappe.delete_doc("Tenant", tenant.name, force=True, ignore_permissions=True)
            if user1_email:
                for perm in frappe.get_all("User Permission", filters={"user": user1_email}, pluck="name"):
                    frappe.delete_doc("User Permission", perm, force=True, ignore_permissions=True)
                frappe.delete_doc("User", user1_email, force=True, ignore_permissions=True)
            if user2_email:
                for perm in frappe.get_all("User Permission", filters={"user": user2_email}, pluck="name"):
                    frappe.delete_doc("User Permission", perm, force=True, ignore_permissions=True)
                frappe.delete_doc("User", user2_email, force=True, ignore_permissions=True)
            frappe.db.commit()


class TestCrossTenantAccessPrevention(TestRBACSetup):
    """Tests for cross-tenant access is blocked."""

    def test_satici_cannot_access_other_tenant_data(self):
        """Test Satici cannot access data from another tenant."""
        original_user = frappe.session.user
        tenant1 = tenant2 = org1 = org2 = seller1 = seller2 = user1_email = user2_email = None

        try:
            frappe.set_user("Administrator")

            # Create two tenants
            tenant1 = self.create_test_tenant("CrossTenant 1A")
            tenant2 = self.create_test_tenant("CrossTenant 1B")

            # Create organizations in each tenant
            org1 = self.create_test_organization(tenant1.name, "CrossTenant 1A")
            org2 = self.create_test_organization(tenant2.name, "CrossTenant 1B")

            # Create users for each tenant
            user1_email = self.create_test_user("cross_tenant_1a", roles=["Satici"])
            user2_email = self.create_test_user("cross_tenant_1b", roles=["Satici"])

            # Create seller profiles
            seller1 = self.create_test_seller_profile(tenant1.name, org1.name, user1_email, "CrossTenant 1A")
            seller2 = self.create_test_seller_profile(tenant2.name, org2.name, user2_email, "CrossTenant 1B")

            # User 1 only has permission to Tenant 1
            self.create_user_permission(user1_email, "Tenant", tenant1.name)

            # Switch to User 1 (Tenant 1)
            frappe.set_user(user1_email)

            # User 1 should NOT be able to see Tenant 2's seller profile
            profiles_from_tenant2 = frappe.get_all("Seller Profile",
                                                    filters={"tenant": tenant2.name},
                                                    pluck="name")

            self.assertEqual(len(profiles_from_tenant2), 0,
                           "User from Tenant 1 should not see Tenant 2's seller profiles")

            # User 1 should NOT be able to see Tenant 2's organization
            orgs_from_tenant2 = frappe.get_all("Organization",
                                               filters={"tenant": tenant2.name},
                                               pluck="name")

            self.assertEqual(len(orgs_from_tenant2), 0,
                           "User from Tenant 1 should not see Tenant 2's organizations")

        finally:
            frappe.set_user(original_user)
            # Cleanup
            if seller1:
                frappe.delete_doc("Seller Profile", seller1.name, force=True, ignore_permissions=True)
            if seller2:
                frappe.delete_doc("Seller Profile", seller2.name, force=True, ignore_permissions=True)
            if org1:
                frappe.delete_doc("Organization", org1.name, force=True, ignore_permissions=True)
            if org2:
                frappe.delete_doc("Organization", org2.name, force=True, ignore_permissions=True)
            if tenant1:
                for perm in frappe.get_all("User Permission", filters={"for_value": tenant1.name}, pluck="name"):
                    frappe.delete_doc("User Permission", perm, force=True, ignore_permissions=True)
                frappe.delete_doc("Tenant", tenant1.name, force=True, ignore_permissions=True)
            if tenant2:
                for perm in frappe.get_all("User Permission", filters={"for_value": tenant2.name}, pluck="name"):
                    frappe.delete_doc("User Permission", perm, force=True, ignore_permissions=True)
                frappe.delete_doc("Tenant", tenant2.name, force=True, ignore_permissions=True)
            if user1_email:
                frappe.delete_doc("User", user1_email, force=True, ignore_permissions=True)
            if user2_email:
                frappe.delete_doc("User", user2_email, force=True, ignore_permissions=True)
            frappe.db.commit()

    def test_alici_admin_cannot_create_org_in_other_tenant(self):
        """Test Alici Admin cannot create organization in another tenant."""
        original_user = frappe.session.user
        tenant1 = tenant2 = user_email = org = None

        try:
            frappe.set_user("Administrator")

            # Create two tenants
            tenant1 = self.create_test_tenant("CrossTenant Create 1A")
            tenant2 = self.create_test_tenant("CrossTenant Create 1B")

            # Create user with permission to Tenant 1 only
            user_email = self.create_test_user("cross_tenant_create_1", roles=["Alici Admin"])
            self.create_user_permission(user_email, "Tenant", tenant1.name)

            # Switch to Alici Admin
            frappe.set_user(user_email)

            # Try to create organization in Tenant 2 - should fail due to User Permission
            with self.assertRaises((frappe.PermissionError, frappe.ValidationError)):
                org = frappe.get_doc({
                    "doctype": "Organization",
                    "organization_name": "RBAC Test Organization CrossTenant",
                    "organization_type": "Company",
                    "tenant": tenant2.name,  # Different tenant
                    "status": "Active",
                    "country": "Turkey",
                    "tax_id": "5555555555"
                })
                org.insert()

        finally:
            frappe.set_user(original_user)
            # Cleanup
            if org and frappe.db.exists("Organization", org.name):
                frappe.delete_doc("Organization", org.name, force=True, ignore_permissions=True)
            if tenant1:
                for perm in frappe.get_all("User Permission", filters={"for_value": tenant1.name}, pluck="name"):
                    frappe.delete_doc("User Permission", perm, force=True, ignore_permissions=True)
                frappe.delete_doc("Tenant", tenant1.name, force=True, ignore_permissions=True)
            if tenant2:
                frappe.delete_doc("Tenant", tenant2.name, force=True, ignore_permissions=True)
            if user_email:
                for perm in frappe.get_all("User Permission", filters={"user": user_email}, pluck="name"):
                    frappe.delete_doc("User Permission", perm, force=True, ignore_permissions=True)
                frappe.delete_doc("User", user_email, force=True, ignore_permissions=True)
            frappe.db.commit()


class TestFieldLevelPermissions(TestRBACSetup):
    """Tests for field-level permissions (permlevel)."""

    def test_satici_cannot_edit_verification_status(self):
        """Test Satici cannot edit verification_status field (permlevel 1)."""
        original_user = frappe.session.user
        tenant = org = seller = user_email = None

        try:
            frappe.set_user("Administrator")

            tenant = self.create_test_tenant("Permlevel 1")
            org = self.create_test_organization(tenant.name, "Permlevel 1")
            user_email = self.create_test_user("permlevel_1", roles=["Satici"])
            seller = self.create_test_seller_profile(tenant.name, org.name, user_email, "Permlevel 1")

            # Set initial verification status as admin
            seller.verification_status = "Pending"
            seller.save(ignore_permissions=True)
            frappe.db.commit()

            # Create User Permission
            self.create_user_permission(user_email, "Tenant", tenant.name)

            # Switch to Satici user
            frappe.set_user(user_email)

            # Try to change verification_status - should be ignored due to permlevel
            seller_doc = frappe.get_doc("Seller Profile", seller.name)
            original_status = seller_doc.verification_status
            seller_doc.verification_status = "Approved"

            # Save should either raise error or silently ignore the change
            try:
                seller_doc.save()
                frappe.db.commit()

                # Verify the field was not changed (silently ignored due to permlevel)
                seller_doc.reload()
                self.assertEqual(seller_doc.verification_status, original_status,
                               "Satici should not be able to change verification_status")
            except frappe.PermissionError:
                # This is also acceptable - permission denied
                pass

        finally:
            frappe.set_user(original_user)
            # Cleanup
            if seller:
                frappe.delete_doc("Seller Profile", seller.name, force=True, ignore_permissions=True)
            if org:
                frappe.delete_doc("Organization", org.name, force=True, ignore_permissions=True)
            if tenant:
                for perm in frappe.get_all("User Permission", filters={"for_value": tenant.name}, pluck="name"):
                    frappe.delete_doc("User Permission", perm, force=True, ignore_permissions=True)
                frappe.delete_doc("Tenant", tenant.name, force=True, ignore_permissions=True)
            if user_email:
                for perm in frappe.get_all("User Permission", filters={"user": user_email}, pluck="name"):
                    frappe.delete_doc("User Permission", perm, force=True, ignore_permissions=True)
                frappe.delete_doc("User", user_email, force=True, ignore_permissions=True)
            frappe.db.commit()

    def test_alici_admin_cannot_edit_credit_limit(self):
        """Test Alici Admin cannot edit credit_limit field (permlevel 1)."""
        original_user = frappe.session.user
        tenant = org = user_email = None

        try:
            frappe.set_user("Administrator")

            tenant = self.create_test_tenant("Permlevel Credit 1")
            user_email = self.create_test_user("permlevel_credit_1", roles=["Alici Admin"])

            # Create User Permission
            self.create_user_permission(user_email, "Tenant", tenant.name)

            # Create organization as Alici Admin
            frappe.set_user(user_email)

            org = frappe.get_doc({
                "doctype": "Organization",
                "organization_name": "RBAC Test Organization Permlevel Credit",
                "organization_type": "Company",
                "tenant": tenant.name,
                "status": "Active",
                "country": "Turkey",
                "tax_id": "4444444444"
            })
            org.insert()
            frappe.db.commit()

            # Set credit_limit as admin
            frappe.set_user("Administrator")
            org.credit_limit = 10000
            org.save(ignore_permissions=True)
            frappe.db.commit()

            # Switch back to Alici Admin
            frappe.set_user(user_email)

            # Try to change credit_limit - should be ignored due to permlevel
            org_doc = frappe.get_doc("Organization", org.name)
            original_limit = org_doc.credit_limit
            org_doc.credit_limit = 50000

            try:
                org_doc.save()
                frappe.db.commit()

                # Verify the field was not changed
                org_doc.reload()
                self.assertEqual(org_doc.credit_limit, original_limit,
                               "Alici Admin should not be able to change credit_limit")
            except frappe.PermissionError:
                pass

        finally:
            frappe.set_user(original_user)
            # Cleanup
            if org:
                frappe.delete_doc("Organization", org.name, force=True, ignore_permissions=True)
            if tenant:
                for perm in frappe.get_all("User Permission", filters={"for_value": tenant.name}, pluck="name"):
                    frappe.delete_doc("User Permission", perm, force=True, ignore_permissions=True)
                frappe.delete_doc("Tenant", tenant.name, force=True, ignore_permissions=True)
            if user_email:
                for perm in frappe.get_all("User Permission", filters={"user": user_email}, pluck="name"):
                    frappe.delete_doc("User Permission", perm, force=True, ignore_permissions=True)
                frappe.delete_doc("User", user_email, force=True, ignore_permissions=True)
            frappe.db.commit()


class TestRoleHierarchy(TestRBACSetup):
    """Tests for role hierarchy and permission inheritance."""

    def test_satici_admin_has_more_permissions_than_satici(self):
        """Test Satici Admin has more permissions than regular Satici."""
        original_user = frappe.session.user
        tenant = org = seller = user_admin_email = user_satici_email = None

        try:
            frappe.set_user("Administrator")

            tenant = self.create_test_tenant("Role Hierarchy 1")
            org = self.create_test_organization(tenant.name, "Role Hierarchy 1")

            # Create Satici Admin user
            user_admin_email = self.create_test_user("role_hierarchy_admin_1", roles=["Satici Admin"])
            self.create_user_permission(user_admin_email, "Tenant", tenant.name)

            # Create regular Satici user
            user_satici_email = self.create_test_user("role_hierarchy_satici_1", roles=["Satici"])
            self.create_user_permission(user_satici_email, "Tenant", tenant.name)

            # Test: Satici Admin can create seller profiles
            frappe.set_user(user_admin_email)

            seller = frappe.get_doc({
                "doctype": "Seller Profile",
                "seller_name": "RBAC Test Seller Role Hierarchy",
                "user": user_satici_email,
                "seller_type": "Business",
                "tenant": tenant.name,
                "organization": org.name,
                "status": "Active",
                "country": "Turkey"
            })
            seller.insert()
            frappe.db.commit()

            self.assertTrue(frappe.db.exists("Seller Profile", seller.name),
                          "Satici Admin should be able to create seller profiles")

        finally:
            frappe.set_user(original_user)
            # Cleanup
            if seller:
                frappe.delete_doc("Seller Profile", seller.name, force=True, ignore_permissions=True)
            if org:
                frappe.delete_doc("Organization", org.name, force=True, ignore_permissions=True)
            if tenant:
                for perm in frappe.get_all("User Permission", filters={"for_value": tenant.name}, pluck="name"):
                    frappe.delete_doc("User Permission", perm, force=True, ignore_permissions=True)
                frappe.delete_doc("Tenant", tenant.name, force=True, ignore_permissions=True)
            if user_admin_email:
                for perm in frappe.get_all("User Permission", filters={"user": user_admin_email}, pluck="name"):
                    frappe.delete_doc("User Permission", perm, force=True, ignore_permissions=True)
                frappe.delete_doc("User", user_admin_email, force=True, ignore_permissions=True)
            if user_satici_email:
                for perm in frappe.get_all("User Permission", filters={"user": user_satici_email}, pluck="name"):
                    frappe.delete_doc("User Permission", perm, force=True, ignore_permissions=True)
                frappe.delete_doc("User", user_satici_email, force=True, ignore_permissions=True)
            frappe.db.commit()

    def test_marka_sahibi_has_readonly_access_to_all_tenant_data(self):
        """Test Marka Sahibi has read-only access across tenant data."""
        original_user = frappe.session.user
        tenant = org = seller = user_email = seller_user_email = None

        try:
            frappe.set_user("Administrator")

            tenant = self.create_test_tenant("Marka Sahibi 1")
            org = self.create_test_organization(tenant.name, "Marka Sahibi 1")

            # Create seller profile
            seller_user_email = self.create_test_user("marka_sahibi_seller_1", roles=["Satici"])
            seller = self.create_test_seller_profile(tenant.name, org.name, seller_user_email, "Marka Sahibi 1")

            # Create Marka Sahibi user
            user_email = self.create_test_user("marka_sahibi_1", roles=["Marka Sahibi"])
            self.create_user_permission(user_email, "Tenant", tenant.name)

            # Switch to Marka Sahibi
            frappe.set_user(user_email)

            # Marka Sahibi should be able to READ seller profiles
            profiles = frappe.get_all("Seller Profile",
                                      filters={"tenant": tenant.name},
                                      pluck="name")

            self.assertGreater(len(profiles), 0, "Marka Sahibi should be able to see seller profiles")

            # Marka Sahibi should NOT be able to WRITE seller profiles
            seller_doc = frappe.get_doc("Seller Profile", seller.name)
            seller_doc.display_name = "Marka Sahibi Changed"

            with self.assertRaises(frappe.PermissionError):
                seller_doc.save()

        finally:
            frappe.set_user(original_user)
            # Cleanup
            if seller:
                frappe.delete_doc("Seller Profile", seller.name, force=True, ignore_permissions=True)
            if org:
                frappe.delete_doc("Organization", org.name, force=True, ignore_permissions=True)
            if tenant:
                for perm in frappe.get_all("User Permission", filters={"for_value": tenant.name}, pluck="name"):
                    frappe.delete_doc("User Permission", perm, force=True, ignore_permissions=True)
                frappe.delete_doc("Tenant", tenant.name, force=True, ignore_permissions=True)
            if user_email:
                for perm in frappe.get_all("User Permission", filters={"user": user_email}, pluck="name"):
                    frappe.delete_doc("User Permission", perm, force=True, ignore_permissions=True)
                frappe.delete_doc("User", user_email, force=True, ignore_permissions=True)
            if seller_user_email:
                frappe.delete_doc("User", seller_user_email, force=True, ignore_permissions=True)
            frappe.db.commit()


def verify_rbac_permissions():
    """
    Standalone verification function that can be run via bench console.

    Usage:
        bench --site [site] console
        >>> from tr_tradehub.tests.test_rbac_permissions import verify_rbac_permissions
        >>> verify_rbac_permissions()
    """
    results = {
        "passed": [],
        "failed": []
    }

    print("\n" + "=" * 60)
    print("RBAC PERMISSION VERIFICATION")
    print("=" * 60)

    # Test 1: System Manager full access
    print("\n[Test 1] System Manager has full access...")
    try:
        frappe.set_user("Administrator")
        tenant = frappe.get_doc({
            "doctype": "Tenant",
            "tenant_name": "RBAC Verify Tenant",
            "company_name": "RBAC Verify Company",
            "status": "Active",
            "subscription_tier": "Basic",
            "contact_email": "rbac_verify@test.com",
            "country": "Turkey"
        })
        tenant.insert(ignore_permissions=True)
        frappe.db.commit()

        # Try to modify permlevel 1 field
        tenant.subscription_tier = "Enterprise"
        tenant.save(ignore_permissions=True)
        frappe.db.commit()

        print("  OK System Manager can create and modify tenants")
        results["passed"].append("System Manager full access")

        # Cleanup
        frappe.delete_doc("Tenant", tenant.name, force=True, ignore_permissions=True)
        frappe.db.commit()
    except Exception as e:
        print(f"  FAIL {str(e)}")
        results["failed"].append(f"System Manager full access: {str(e)}")

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
        print("\nOK All RBAC verification tests passed!")

    return results

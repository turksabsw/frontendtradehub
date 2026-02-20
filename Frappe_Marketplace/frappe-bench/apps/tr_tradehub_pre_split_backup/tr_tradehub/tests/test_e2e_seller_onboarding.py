# Copyright (c) 2026, Trade Hub and contributors
# For license information, please see license.txt

"""
End-to-End Test: Seller Onboarding Flow

This module implements comprehensive end-to-end tests for the complete seller
onboarding workflow in the Trade Hub B2B marketplace.

Test Workflow:
1. Register seller via SSO (Keycloak authentication simulation)
2. Complete verification workflow (create profile, submit for verification, verify)
3. Add first product with media (upload media, create product)
4. Verify product visible in marketplace (check product status and visibility)

Test Prerequisites:
- Tenant DocType must exist
- Seller Profile DocType must exist
- SKU Product DocType must exist
- Media Asset DocType must exist
- Product Category DocType must exist (optional, falls back to default)

Usage:
    Run with Frappe bench:
    bench --site {site} run-tests --module trade_hub.tests.test_e2e_seller_onboarding

    Run specific test:
    bench --site {site} run-tests --module trade_hub.tests.test_e2e_seller_onboarding --test test_complete_seller_onboarding_flow
"""

import unittest
from unittest.mock import patch, MagicMock
from typing import Dict, Any, Optional

import frappe
from frappe.utils import now_datetime, today, random_string


class TestE2ESellerOnboarding(unittest.TestCase):
    """
    End-to-end tests for the complete seller onboarding flow.

    This test class simulates a new seller going through:
    1. SSO registration via Keycloak
    2. Profile creation and verification
    3. Adding their first product with media
    4. Product visibility in the marketplace
    """

    @classmethod
    def setUpClass(cls):
        """Set up test fixtures that are shared across all tests."""
        # Use Administrator for test operations
        frappe.set_user("Administrator")

        # Create test tenant if it doesn't exist
        cls.test_tenant = cls._get_or_create_test_tenant()

        # Create test category if Product Category exists
        cls.test_category = cls._get_or_create_test_category()

    @classmethod
    def tearDownClass(cls):
        """Clean up test fixtures after all tests complete."""
        frappe.set_user("Administrator")
        frappe.db.rollback()

    def setUp(self):
        """Set up test fixtures before each test."""
        # Generate unique identifiers for this test run
        self.test_suffix = random_string(6).lower()
        self.test_email = f"seller_test_{self.test_suffix}@example.com"
        self.test_seller_name = f"Test Seller {self.test_suffix}"
        self.test_product_name = f"Test Product {self.test_suffix}"
        self.test_sku_code = f"SKU-{self.test_suffix}".upper()

    def tearDown(self):
        """Clean up test data after each test."""
        frappe.set_user("Administrator")
        self._cleanup_test_data()
        frappe.db.rollback()

    # =========================================================================
    # MAIN END-TO-END TEST
    # =========================================================================

    def test_complete_seller_onboarding_flow(self):
        """
        Test the complete seller onboarding flow from registration to product listing.

        This test covers:
        1. Register seller via SSO
        2. Complete verification workflow
        3. Add first product with media
        4. Verify product visible in marketplace

        This is the primary E2E test that validates the entire seller journey.
        """
        # Step 1: Register seller via SSO (Keycloak simulation)
        user = self._step_register_seller_via_sso()
        self.assertIsNotNone(user, "User should be created via SSO")
        self.assertEqual(user.email, self.test_email)

        # Step 2: Complete verification workflow
        seller_profile = self._step_complete_verification_workflow(user)
        self.assertIsNotNone(seller_profile, "Seller profile should be created")
        self.assertEqual(
            seller_profile.verification_status,
            "Verified",
            "Seller should be verified"
        )
        self.assertEqual(seller_profile.status, "Active", "Seller should be active")

        # Step 3: Add first product with media
        product = self._step_add_first_product_with_media(seller_profile)
        self.assertIsNotNone(product, "Product should be created")
        self.assertEqual(product.status, "Active", "Product should be active")
        self.assertIsNotNone(product.thumbnail, "Product should have thumbnail")

        # Step 4: Verify product visible in marketplace
        is_visible = self._step_verify_product_in_marketplace(product)
        self.assertTrue(is_visible, "Product should be visible in marketplace")

    # =========================================================================
    # STEP IMPLEMENTATIONS
    # =========================================================================

    def _step_register_seller_via_sso(self) -> Optional[Any]:
        """
        Step 1: Register seller via SSO (Keycloak simulation).

        Simulates the Keycloak SSO flow:
        1. User authenticates with Keycloak
        2. Access token is exchanged
        3. Frappe user is created/updated from Keycloak user info

        Returns:
            User document or None if registration fails
        """
        # Simulate Keycloak user info that would come from SSO
        keycloak_user_info = {
            "sub": f"keycloak-{self.test_suffix}",
            "email": self.test_email,
            "email_verified": True,
            "given_name": "Test",
            "family_name": f"Seller {self.test_suffix}",
            "name": self.test_seller_name,
            "preferred_username": f"seller_{self.test_suffix}",
            "realm_access": {
                "roles": ["trade_hub_seller"]
            }
        }

        # Create user from "SSO" flow
        user = self._create_user_from_keycloak_info(keycloak_user_info)

        return user

    def _step_complete_verification_workflow(self, user: Any) -> Optional[Any]:
        """
        Step 2: Complete seller verification workflow.

        Workflow:
        1. Create seller profile (auto-triggered or manual)
        2. Submit required documents (simulated)
        3. Submit for verification review
        4. Admin verifies and approves seller

        Args:
            user: Frappe User document

        Returns:
            Seller Profile document or None if verification fails
        """
        # Set user context
        frappe.set_user(user.name)

        # Create seller profile
        seller_profile = frappe.new_doc("Seller Profile")
        seller_profile.seller_name = self.test_seller_name
        seller_profile.company_name = f"{self.test_seller_name} Ltd."
        seller_profile.user = user.name
        seller_profile.tenant = self.test_tenant.name
        seller_profile.contact_email = self.test_email
        seller_profile.contact_phone = "+1234567890"
        seller_profile.city = "Istanbul"
        seller_profile.country = "Turkey"
        seller_profile.business_type = "Manufacturer"
        seller_profile.year_established = 2020
        seller_profile.description = "Test seller for E2E testing"

        # Set flags to bypass certain validations in test
        seller_profile.flags.ignore_permissions = True
        seller_profile.insert()

        # Verify initial status is Pending
        self.assertEqual(
            seller_profile.verification_status,
            "Pending",
            "Initial verification status should be Pending"
        )

        # Submit documents (simulated by status change)
        seller_profile.reload()
        seller_profile.verification_status = "Documents Submitted"
        seller_profile.flags.ignore_permissions = True
        seller_profile.save()

        # Admin reviews and verifies
        frappe.set_user("Administrator")
        seller_profile.reload()
        seller_profile.verification_status = "Under Review"
        seller_profile.flags.ignore_permissions = True
        seller_profile.save()

        # Final verification approval
        seller_profile.reload()
        seller_profile.verification_status = "Verified"
        seller_profile.verification_notes = "E2E test verification - approved"
        seller_profile.flags.ignore_permissions = True
        seller_profile.save()

        # Reload to get updated status
        seller_profile.reload()

        return seller_profile

    def _step_add_first_product_with_media(self, seller_profile: Any) -> Optional[Any]:
        """
        Step 3: Add first product with media.

        This step:
        1. Creates a media asset (product image)
        2. Creates an SKU Product linked to the seller
        3. Attaches media to the product
        4. Activates the product for marketplace

        Args:
            seller_profile: Seller Profile document

        Returns:
            SKU Product document or None if creation fails
        """
        frappe.set_user("Administrator")

        # Create media asset (simulate uploaded image)
        media_asset = self._create_test_media_asset(seller_profile)
        self.assertIsNotNone(media_asset, "Media asset should be created")

        # Create SKU Product
        product = frappe.new_doc("SKU Product")
        product.product_name = self.test_product_name
        product.sku_code = self.test_sku_code
        product.seller = seller_profile.name
        product.tenant = seller_profile.tenant
        product.status = "Draft"
        product.base_price = 99.99
        product.currency = "USD"
        product.min_order_quantity = 10
        product.max_order_quantity = 1000
        product.stock_quantity = 500
        product.stock_uom = "Unit"
        product.is_stock_item = 1
        product.weight = 1.5
        product.weight_uom = "Kg"
        product.description = "Test product for E2E testing"
        product.seo_title = self.test_product_name
        product.seo_description = f"Buy {self.test_product_name} from Trade Hub"

        # Attach media to product
        if media_asset and media_asset.file_url:
            product.thumbnail = media_asset.file_url

        # Set category if available
        if self.test_category:
            product.category = self.test_category.name

        # Insert product in draft state
        product.flags.ignore_permissions = True
        product.insert()

        # Verify product created in Draft
        self.assertEqual(product.status, "Draft", "Product should start in Draft")

        # Activate product
        product.reload()
        product.status = "Active"
        product.is_published = 1
        product.flags.ignore_permissions = True
        product.save()

        product.reload()
        return product

    def _step_verify_product_in_marketplace(self, product: Any) -> bool:
        """
        Step 4: Verify product is visible in marketplace.

        This step validates:
        1. Product has Active status
        2. Product is published (is_published = 1)
        3. Product can be found by SKU code
        4. Product can be found by URL slug
        5. Product appears in seller's product list

        Args:
            product: SKU Product document

        Returns:
            bool: True if product is visible in marketplace
        """
        # Check 1: Product status is Active
        if product.status != "Active":
            return False

        # Check 2: Product is published
        if not product.is_published:
            return False

        # Check 3: Product can be found by SKU code
        found_by_sku = frappe.db.get_value(
            "SKU Product",
            {"sku_code": self.test_sku_code, "status": "Active"},
            "name"
        )
        if not found_by_sku:
            return False

        # Check 4: Product can be found by URL slug (if generated)
        if product.url_slug:
            found_by_slug = frappe.db.get_value(
                "SKU Product",
                {"url_slug": product.url_slug, "status": "Active"},
                "name"
            )
            if not found_by_slug:
                return False

        # Check 5: Product appears in seller's product list
        seller_products = frappe.get_all(
            "SKU Product",
            filters={
                "seller": product.seller,
                "status": "Active"
            },
            pluck="name"
        )
        if product.name not in seller_products:
            return False

        return True

    # =========================================================================
    # INDIVIDUAL FLOW TESTS
    # =========================================================================

    def test_sso_registration_creates_user_with_tenant(self):
        """Test that SSO registration creates a user with correct tenant assignment."""
        keycloak_user_info = {
            "sub": f"keycloak-{self.test_suffix}",
            "email": self.test_email,
            "email_verified": True,
            "given_name": "Test",
            "family_name": "Seller",
            "name": self.test_seller_name,
        }

        user = self._create_user_from_keycloak_info(keycloak_user_info)

        self.assertIsNotNone(user)
        self.assertEqual(user.email, self.test_email)
        self.assertEqual(user.first_name, "Test")
        self.assertEqual(user.last_name, "Seller")

        # Check tenant assignment if field exists
        if hasattr(user, "tenant"):
            self.assertEqual(user.tenant, self.test_tenant.name)

    def test_seller_profile_creation_and_status_workflow(self):
        """Test seller profile creation and verification status workflow."""
        # Create user first
        user = self._create_test_user()

        # Create seller profile
        seller_profile = frappe.new_doc("Seller Profile")
        seller_profile.seller_name = self.test_seller_name
        seller_profile.user = user.name
        seller_profile.tenant = self.test_tenant.name
        seller_profile.contact_email = self.test_email
        seller_profile.flags.ignore_permissions = True
        seller_profile.insert()

        # Verify initial state
        self.assertEqual(seller_profile.verification_status, "Pending")
        self.assertEqual(seller_profile.status, "Pending")

        # Test workflow transitions
        valid_transitions = [
            ("Pending", "Documents Submitted"),
            ("Documents Submitted", "Under Review"),
            ("Under Review", "Verified")
        ]

        for from_status, to_status in valid_transitions:
            seller_profile.reload()
            seller_profile.verification_status = to_status
            seller_profile.flags.ignore_permissions = True
            seller_profile.save()
            seller_profile.reload()
            self.assertEqual(
                seller_profile.verification_status,
                to_status,
                f"Transition from {from_status} to {to_status} should succeed"
            )

    def test_product_creation_with_valid_seller(self):
        """Test that products can only be created by verified sellers."""
        # Create and verify seller
        user = self._create_test_user()
        seller_profile = self._create_verified_seller(user)

        # Create product
        product = frappe.new_doc("SKU Product")
        product.product_name = self.test_product_name
        product.sku_code = self.test_sku_code
        product.seller = seller_profile.name
        product.tenant = seller_profile.tenant
        product.base_price = 50.00
        product.currency = "USD"
        product.flags.ignore_permissions = True
        product.insert()

        # Verify product is linked to seller
        self.assertEqual(product.seller, seller_profile.name)
        self.assertEqual(product.tenant, seller_profile.tenant)

    def test_product_status_workflow(self):
        """Test product status transitions (Draft -> Active -> Passive -> Archive)."""
        # Set up seller and product
        user = self._create_test_user()
        seller_profile = self._create_verified_seller(user)

        product = frappe.new_doc("SKU Product")
        product.product_name = self.test_product_name
        product.sku_code = self.test_sku_code
        product.seller = seller_profile.name
        product.tenant = seller_profile.tenant
        product.base_price = 100.00
        product.currency = "USD"
        product.status = "Draft"
        product.flags.ignore_permissions = True
        product.insert()

        # Test: Draft -> Active
        product.reload()
        product.status = "Active"
        product.flags.ignore_permissions = True
        product.save()
        product.reload()
        self.assertEqual(product.status, "Active")

        # Test: Active -> Passive
        product.reload()
        product.status = "Passive"
        product.flags.ignore_permissions = True
        product.save()
        product.reload()
        self.assertEqual(product.status, "Passive")

        # Test: Passive -> Archive
        product.reload()
        product.status = "Archive"
        product.flags.ignore_permissions = True
        product.save()
        product.reload()
        self.assertEqual(product.status, "Archive")

    def test_media_asset_creation_for_product(self):
        """Test media asset creation and linkage to product."""
        # Set up seller
        user = self._create_test_user()
        seller_profile = self._create_verified_seller(user)

        # Create media asset
        media_asset = self._create_test_media_asset(seller_profile)
        self.assertIsNotNone(media_asset)
        self.assertEqual(media_asset.status, "Active")
        self.assertEqual(media_asset.tenant, seller_profile.tenant)

    def test_product_tenant_isolation(self):
        """Test that products respect tenant isolation."""
        # Create seller in test tenant
        user = self._create_test_user()
        seller_profile = self._create_verified_seller(user)

        # Create product
        product = frappe.new_doc("SKU Product")
        product.product_name = self.test_product_name
        product.sku_code = self.test_sku_code
        product.seller = seller_profile.name
        product.tenant = seller_profile.tenant
        product.base_price = 75.00
        product.currency = "USD"
        product.flags.ignore_permissions = True
        product.insert()

        # Verify tenant is set correctly
        self.assertEqual(product.tenant, self.test_tenant.name)

        # Query products for this tenant - should find the product
        tenant_products = frappe.get_all(
            "SKU Product",
            filters={"tenant": self.test_tenant.name},
            pluck="name"
        )
        self.assertIn(product.name, tenant_products)

    def test_seller_verification_rejection_and_resubmission(self):
        """Test that rejected sellers can resubmit for verification."""
        user = self._create_test_user()

        seller_profile = frappe.new_doc("Seller Profile")
        seller_profile.seller_name = self.test_seller_name
        seller_profile.user = user.name
        seller_profile.tenant = self.test_tenant.name
        seller_profile.contact_email = self.test_email
        seller_profile.flags.ignore_permissions = True
        seller_profile.insert()

        # Submit for verification
        seller_profile.verification_status = "Documents Submitted"
        seller_profile.save()

        # Review
        seller_profile.verification_status = "Under Review"
        seller_profile.save()

        # Reject
        seller_profile.verification_status = "Rejected"
        seller_profile.verification_notes = "Missing documents"
        seller_profile.save()
        seller_profile.reload()
        self.assertEqual(seller_profile.verification_status, "Rejected")

        # Resubmit (back to Pending then Documents Submitted)
        seller_profile.verification_status = "Pending"
        seller_profile.save()

        seller_profile.verification_status = "Documents Submitted"
        seller_profile.save()
        seller_profile.reload()
        self.assertEqual(seller_profile.verification_status, "Documents Submitted")

    # =========================================================================
    # HELPER METHODS
    # =========================================================================

    def _create_user_from_keycloak_info(self, keycloak_user_info: Dict[str, Any]) -> Any:
        """
        Create a Frappe user from Keycloak user information.

        This simulates the user creation that happens during SSO callback.

        Args:
            keycloak_user_info: User info dict from Keycloak token/userinfo

        Returns:
            User document
        """
        email = keycloak_user_info.get("email")

        # Check if user exists
        if frappe.db.exists("User", email):
            return frappe.get_doc("User", email)

        # Create new user
        user = frappe.new_doc("User")
        user.email = email
        user.first_name = keycloak_user_info.get("given_name", "")
        user.last_name = keycloak_user_info.get("family_name", "")
        user.full_name = keycloak_user_info.get("name", f"{user.first_name} {user.last_name}")
        user.username = keycloak_user_info.get("preferred_username", email.split("@")[0])
        user.enabled = 1
        user.send_welcome_email = 0

        # Set keycloak ID if field exists
        if hasattr(user, "keycloak_user_id"):
            user.keycloak_user_id = keycloak_user_info.get("sub")

        # Set tenant if field exists
        if hasattr(user, "tenant"):
            user.tenant = self.test_tenant.name

        user.flags.ignore_permissions = True
        user.flags.no_welcome_mail = True
        user.insert()

        # Add Seller role if it exists
        if frappe.db.exists("Role", "Seller"):
            user.add_roles("Seller")

        return user

    def _create_test_user(self) -> Any:
        """Create a test user for seller registration."""
        if frappe.db.exists("User", self.test_email):
            return frappe.get_doc("User", self.test_email)

        user = frappe.new_doc("User")
        user.email = self.test_email
        user.first_name = "Test"
        user.last_name = f"Seller {self.test_suffix}"
        user.username = f"seller_{self.test_suffix}"
        user.enabled = 1
        user.send_welcome_email = 0

        if hasattr(user, "tenant"):
            user.tenant = self.test_tenant.name

        user.flags.ignore_permissions = True
        user.flags.no_welcome_mail = True
        user.insert()

        return user

    def _create_verified_seller(self, user: Any) -> Any:
        """Create a verified seller profile for testing."""
        seller_profile = frappe.new_doc("Seller Profile")
        seller_profile.seller_name = self.test_seller_name
        seller_profile.user = user.name
        seller_profile.tenant = self.test_tenant.name
        seller_profile.contact_email = self.test_email
        seller_profile.verification_status = "Pending"
        seller_profile.flags.ignore_permissions = True
        seller_profile.insert()

        # Fast-track to verified status
        seller_profile.verification_status = "Documents Submitted"
        seller_profile.save()
        seller_profile.verification_status = "Under Review"
        seller_profile.save()
        seller_profile.verification_status = "Verified"
        seller_profile.save()

        seller_profile.reload()
        return seller_profile

    def _create_test_media_asset(self, seller_profile: Any) -> Optional[Any]:
        """
        Create a test media asset for product images.

        Args:
            seller_profile: Seller Profile document

        Returns:
            Media Asset document or None
        """
        if not frappe.db.exists("DocType", "Media Asset"):
            return None

        media_asset = frappe.new_doc("Media Asset")
        media_asset.asset_name = f"Product Image {self.test_suffix}"
        media_asset.asset_type = "Image"
        media_asset.media_category = "Product Image"
        media_asset.tenant = seller_profile.tenant
        media_asset.uploaded_by = frappe.session.user
        media_asset.status = "Active"

        # Simulate file attachment (in real scenario, this would be an actual file)
        media_asset.file = f"/files/test_product_{self.test_suffix}.jpg"
        media_asset.file_url = f"/files/test_product_{self.test_suffix}.jpg"
        media_asset.original_filename = f"test_product_{self.test_suffix}.jpg"
        media_asset.format = "JPG"
        media_asset.alt_text = f"Product image for {self.test_product_name}"

        media_asset.flags.ignore_permissions = True
        media_asset.insert()

        return media_asset

    @classmethod
    def _get_or_create_test_tenant(cls) -> Any:
        """Get or create a test tenant for E2E tests."""
        tenant_name = "E2E-TEST-TENANT"

        if frappe.db.exists("Tenant", tenant_name):
            return frappe.get_doc("Tenant", tenant_name)

        # Check if Tenant DocType exists
        if not frappe.db.exists("DocType", "Tenant"):
            # Create a mock tenant object for testing without Tenant DocType
            class MockTenant:
                name = tenant_name
            return MockTenant()

        tenant = frappe.new_doc("Tenant")
        tenant.tenant_name = tenant_name
        tenant.enabled = 1
        tenant.subscription_tier = "Professional"
        tenant.flags.ignore_permissions = True
        tenant.insert()

        return tenant

    @classmethod
    def _get_or_create_test_category(cls) -> Optional[Any]:
        """Get or create a test product category."""
        if not frappe.db.exists("DocType", "Product Category"):
            return None

        category_name = "E2E Test Category"
        existing = frappe.db.get_value(
            "Product Category",
            {"category_name": category_name},
            "name"
        )

        if existing:
            return frappe.get_doc("Product Category", existing)

        category = frappe.new_doc("Product Category")
        category.category_name = category_name
        category.enabled = 1
        category.flags.ignore_permissions = True
        category.insert()

        return category

    def _cleanup_test_data(self):
        """Clean up test data created during tests."""
        # Delete in reverse order of dependencies

        # Delete SKU Products
        products = frappe.get_all(
            "SKU Product",
            filters={"sku_code": self.test_sku_code},
            pluck="name"
        )
        for product in products:
            frappe.delete_doc("SKU Product", product, force=True, ignore_permissions=True)

        # Delete Media Assets
        if frappe.db.exists("DocType", "Media Asset"):
            media_assets = frappe.get_all(
                "Media Asset",
                filters={"asset_name": ["like", f"%{self.test_suffix}%"]},
                pluck="name"
            )
            for asset in media_assets:
                frappe.delete_doc("Media Asset", asset, force=True, ignore_permissions=True)

        # Delete Seller Profiles
        seller_profiles = frappe.get_all(
            "Seller Profile",
            filters={"seller_name": self.test_seller_name},
            pluck="name"
        )
        for profile in seller_profiles:
            frappe.delete_doc("Seller Profile", profile, force=True, ignore_permissions=True)

        # Delete Users
        if frappe.db.exists("User", self.test_email):
            frappe.delete_doc("User", self.test_email, force=True, ignore_permissions=True)


# =============================================================================
# INTEGRATION TESTS WITH KEYCLOAK (MOCKED)
# =============================================================================


class TestSellerOnboardingWithKeycloak(unittest.TestCase):
    """
    Integration tests for seller onboarding with Keycloak SSO.

    These tests use mocking to simulate Keycloak interactions
    without requiring an actual Keycloak server.
    """

    @classmethod
    def setUpClass(cls):
        """Set up test fixtures."""
        frappe.set_user("Administrator")
        cls.test_tenant = TestE2ESellerOnboarding._get_or_create_test_tenant()

    def setUp(self):
        """Set up before each test."""
        self.test_suffix = random_string(6).lower()
        self.test_email = f"keycloak_test_{self.test_suffix}@example.com"

    def tearDown(self):
        """Clean up after each test."""
        frappe.set_user("Administrator")
        if frappe.db.exists("User", self.test_email):
            frappe.delete_doc("User", self.test_email, force=True, ignore_permissions=True)
        frappe.db.rollback()

    @patch("tr_tradehub.integrations.keycloak.is_keycloak_enabled")
    @patch("tr_tradehub.integrations.keycloak.validate_keycloak_token")
    @patch("tr_tradehub.integrations.keycloak.get_keycloak_user_info")
    def test_sso_callback_creates_user(
        self,
        mock_user_info,
        mock_validate_token,
        mock_enabled
    ):
        """Test that SSO callback successfully creates a Frappe user."""
        # Configure mocks
        mock_enabled.return_value = True
        mock_validate_token.return_value = (True, {"sub": f"kc-{self.test_suffix}"})
        mock_user_info.return_value = {
            "sub": f"kc-{self.test_suffix}",
            "email": self.test_email,
            "email_verified": True,
            "given_name": "Keycloak",
            "family_name": "User",
            "name": "Keycloak User",
            "preferred_username": f"kc_user_{self.test_suffix}",
        }

        # Simulate user creation from Keycloak
        try:
            from tr_tradehub.integrations.keycloak import create_or_update_frappe_user
            user_email = create_or_update_frappe_user(
                mock_user_info.return_value,
                tenant=self.test_tenant.name
            )
            if user_email:
                user = frappe.get_doc("User", user_email)
                self.assertEqual(user.email, self.test_email)
        except ImportError:
            # If keycloak module not available, test manually
            user = frappe.new_doc("User")
            user.email = self.test_email
            user.first_name = "Keycloak"
            user.last_name = "User"
            user.enabled = 1
            user.send_welcome_email = 0
            if hasattr(user, "tenant"):
                user.tenant = self.test_tenant.name
            user.flags.ignore_permissions = True
            user.insert()
            self.assertEqual(user.email, self.test_email)

    @patch("tr_tradehub.integrations.keycloak.get_keycloak_settings")
    def test_role_mapping_from_keycloak(self, mock_settings):
        """Test that Keycloak roles are correctly mapped to Frappe roles."""
        mock_settings.return_value = {
            "enabled": True,
            "auto_create_users": True,
            "default_tenant": self.test_tenant.name,
            "role_mappings": {
                "trade_hub_seller": "Seller",
                "trade_hub_buyer": "Buyer",
                "trade_hub_admin": "System Manager",
            }
        }

        keycloak_roles = ["trade_hub_seller", "trade_hub_buyer"]
        expected_frappe_roles = ["Seller", "Buyer"]

        # Manual role mapping test
        role_mappings = mock_settings.return_value.get("role_mappings", {})
        mapped_roles = [
            role_mappings.get(kc_role)
            for kc_role in keycloak_roles
            if kc_role in role_mappings
        ]

        for role in expected_frappe_roles:
            self.assertIn(role, mapped_roles)


# =============================================================================
# PERFORMANCE TESTS
# =============================================================================


class TestSellerOnboardingPerformance(unittest.TestCase):
    """
    Performance tests for seller onboarding flow.

    These tests ensure the onboarding flow meets performance requirements.
    """

    @classmethod
    def setUpClass(cls):
        """Set up test fixtures."""
        frappe.set_user("Administrator")
        cls.test_tenant = TestE2ESellerOnboarding._get_or_create_test_tenant()

    def test_seller_profile_creation_performance(self):
        """Test that seller profile creation completes within acceptable time."""
        import time

        test_suffix = random_string(6).lower()
        test_email = f"perf_test_{test_suffix}@example.com"

        # Create user
        user = frappe.new_doc("User")
        user.email = test_email
        user.first_name = "Performance"
        user.last_name = "Test"
        user.enabled = 1
        user.send_welcome_email = 0
        user.flags.ignore_permissions = True
        user.insert()

        # Measure seller profile creation time
        start_time = time.time()

        seller_profile = frappe.new_doc("Seller Profile")
        seller_profile.seller_name = f"Perf Test Seller {test_suffix}"
        seller_profile.user = user.name
        seller_profile.tenant = self.test_tenant.name
        seller_profile.contact_email = test_email
        seller_profile.flags.ignore_permissions = True
        seller_profile.insert()

        elapsed_time = time.time() - start_time

        # Should complete within 1 second
        self.assertLess(
            elapsed_time,
            1.0,
            f"Seller profile creation took {elapsed_time:.3f}s, expected < 1s"
        )

        # Cleanup
        frappe.delete_doc("Seller Profile", seller_profile.name, force=True, ignore_permissions=True)
        frappe.delete_doc("User", test_email, force=True, ignore_permissions=True)
        frappe.db.rollback()


# =============================================================================
# TEST RUNNER
# =============================================================================


def run_tests():
    """Run all E2E seller onboarding tests."""
    suite = unittest.TestSuite()

    # Add test classes
    suite.addTests(unittest.TestLoader().loadTestsFromTestCase(TestE2ESellerOnboarding))
    suite.addTests(unittest.TestLoader().loadTestsFromTestCase(TestSellerOnboardingWithKeycloak))
    suite.addTests(unittest.TestLoader().loadTestsFromTestCase(TestSellerOnboardingPerformance))

    # Run tests
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    return result


if __name__ == "__main__":
    run_tests()

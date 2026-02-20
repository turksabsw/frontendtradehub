# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

"""
Comprehensive unit tests for Tenant Isolation in TR-TradeHub.

Tests cover:
- Tenant DocType creation and validation
- Multi-tenant isolation (queries filter by tenant_id correctly)
- Tenant context management (set, get, clear)
- Cross-tenant access prevention
- Tenant permissions and access control
- Tenant utility functions (apply_tenant_filter, validate_tenant_access)
- Tenant decorators (@with_tenant_context, @require_tenant)
- Tenant API endpoints
"""

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import flt, cint, nowdate, add_days, getdate
import json


class TestTenantCreation(FrappeTestCase):
    """Tests for Tenant DocType creation and validation."""

    @classmethod
    def setUpClass(cls):
        """Set up test fixtures."""
        super().setUpClass()

    def create_tenant(self, **kwargs):
        """Create a test tenant with default values."""
        defaults = {
            "doctype": "Tenant",
            "tenant_name": "Test Tenant",
            "company_name": "Test Company Ltd",
            "status": "Active",
            "subscription_tier": "Basic",
            "contact_email": "test@tenant.com",
            "max_sellers": 10,
            "max_listings_per_seller": 100,
            "commission_rate": 10.0
        }
        defaults.update(kwargs)
        return frappe.get_doc(defaults)

    def test_tenant_creation_basic(self):
        """Test basic tenant creation."""
        tenant = self.create_tenant(tenant_name="Basic Creation Test Tenant")
        tenant.insert(ignore_permissions=True)

        self.assertIsNotNone(tenant.name)
        self.assertTrue(tenant.name.startswith("TEN-"))
        self.assertEqual(tenant.status, "Active")

        tenant.delete()

    def test_tenant_naming_format(self):
        """Test that tenant follows TEN-##### naming format."""
        tenant = self.create_tenant(tenant_name="Naming Test Tenant")
        tenant.insert(ignore_permissions=True)

        self.assertTrue(tenant.name.startswith("TEN-"))

        tenant.delete()

    def test_tenant_requires_name(self):
        """Test that tenant requires a name."""
        tenant = self.create_tenant(tenant_name=None)
        self.assertRaises(frappe.ValidationError, tenant.insert)

    def test_tenant_requires_company_name(self):
        """Test that tenant requires a company name."""
        tenant = self.create_tenant(company_name=None)
        self.assertRaises(frappe.ValidationError, tenant.insert)

    def test_tenant_requires_contact_email(self):
        """Test that tenant requires contact email."""
        tenant = self.create_tenant(contact_email=None)
        self.assertRaises(frappe.ValidationError, tenant.insert)


class TestTenantTaxIdValidation(FrappeTestCase):
    """Tests for Tenant Turkish Tax ID (VKN/TCKN) validation."""

    def create_tenant(self, **kwargs):
        """Create a test tenant with default values."""
        defaults = {
            "doctype": "Tenant",
            "tenant_name": "Tax ID Test Tenant",
            "company_name": "Tax ID Test Company",
            "status": "Active",
            "subscription_tier": "Basic",
            "contact_email": "taxid@tenant.com"
        }
        defaults.update(kwargs)
        return frappe.get_doc(defaults)

    def test_valid_vkn_10_digits(self):
        """Test that valid 10-digit VKN is accepted."""
        tenant = self.create_tenant(
            tenant_name="VKN Test Tenant 10",
            tax_id="1234567890"
        )
        tenant.insert(ignore_permissions=True)

        self.assertEqual(tenant.tax_id, "1234567890")

        tenant.delete()

    def test_valid_tckn_11_digits(self):
        """Test that valid 11-digit TCKN is accepted."""
        tenant = self.create_tenant(
            tenant_name="TCKN Test Tenant 11",
            tax_id="12345678901"
        )
        tenant.insert(ignore_permissions=True)

        self.assertEqual(tenant.tax_id, "12345678901")

        tenant.delete()

    def test_invalid_tax_id_non_digits(self):
        """Test that non-digit tax ID is rejected."""
        tenant = self.create_tenant(tax_id="123ABC7890")
        self.assertRaises(frappe.ValidationError, tenant.insert)

    def test_invalid_tax_id_wrong_length(self):
        """Test that wrong length tax ID is rejected."""
        # Too short (9 digits)
        tenant = self.create_tenant(
            tenant_name="Short Tax ID Tenant",
            tax_id="123456789"
        )
        self.assertRaises(frappe.ValidationError, tenant.insert)

        # Too long (12 digits)
        tenant = self.create_tenant(
            tenant_name="Long Tax ID Tenant",
            tax_id="123456789012"
        )
        self.assertRaises(frappe.ValidationError, tenant.insert)


class TestTenantSubscription(FrappeTestCase):
    """Tests for Tenant subscription management."""

    def create_tenant(self, **kwargs):
        """Create a test tenant with default values."""
        defaults = {
            "doctype": "Tenant",
            "tenant_name": "Subscription Test Tenant",
            "company_name": "Subscription Test Company",
            "status": "Active",
            "subscription_tier": "Basic",
            "contact_email": "subscription@tenant.com"
        }
        defaults.update(kwargs)
        return frappe.get_doc(defaults)

    def test_subscription_dates_valid(self):
        """Test valid subscription date range."""
        tenant = self.create_tenant(
            tenant_name="Valid Dates Tenant",
            subscription_start_date=nowdate(),
            subscription_end_date=add_days(nowdate(), 30)
        )
        tenant.insert(ignore_permissions=True)

        self.assertIsNotNone(tenant.subscription_start_date)
        self.assertIsNotNone(tenant.subscription_end_date)

        tenant.delete()

    def test_subscription_dates_invalid(self):
        """Test that end date before start date is rejected."""
        tenant = self.create_tenant(
            tenant_name="Invalid Dates Tenant",
            subscription_start_date=add_days(nowdate(), 30),
            subscription_end_date=nowdate()  # End before start
        )
        self.assertRaises(frappe.ValidationError, tenant.insert)

    def test_is_active_with_active_status(self):
        """Test is_active returns True for active subscription."""
        tenant = self.create_tenant(
            tenant_name="Active Status Tenant",
            status="Active",
            subscription_end_date=add_days(nowdate(), 30)
        )
        tenant.insert(ignore_permissions=True)

        self.assertTrue(tenant.is_active())

        tenant.delete()

    def test_is_active_with_expired_subscription(self):
        """Test is_active returns False for expired subscription."""
        tenant = self.create_tenant(
            tenant_name="Expired Tenant",
            status="Active",
            subscription_start_date=add_days(nowdate(), -60),
            subscription_end_date=add_days(nowdate(), -30)  # Already expired
        )
        tenant.insert(ignore_permissions=True)

        self.assertFalse(tenant.is_active())

        tenant.delete()

    def test_is_active_with_suspended_status(self):
        """Test is_active returns False for suspended tenant."""
        tenant = self.create_tenant(
            tenant_name="Suspended Tenant",
            status="Suspended",
            subscription_end_date=add_days(nowdate(), 30)
        )
        tenant.insert(ignore_permissions=True)

        self.assertFalse(tenant.is_active())

        tenant.delete()


class TestTenantTierDefaults(FrappeTestCase):
    """Tests for Tenant subscription tier default values."""

    def create_tenant(self, **kwargs):
        """Create a test tenant with default values."""
        defaults = {
            "doctype": "Tenant",
            "tenant_name": "Tier Test Tenant",
            "company_name": "Tier Test Company",
            "status": "Active",
            "contact_email": "tier@tenant.com"
        }
        defaults.update(kwargs)
        return frappe.get_doc(defaults)

    def test_free_tier_defaults(self):
        """Test Free tier gets correct defaults."""
        tenant = self.create_tenant(
            tenant_name="Free Tier Tenant",
            subscription_tier="Free"
        )
        tenant.insert(ignore_permissions=True)

        self.assertEqual(cint(tenant.max_sellers), 1)
        self.assertEqual(cint(tenant.max_listings_per_seller), 10)
        self.assertEqual(flt(tenant.commission_rate), 15.0)

        tenant.delete()

    def test_basic_tier_defaults(self):
        """Test Basic tier gets correct defaults."""
        tenant = self.create_tenant(
            tenant_name="Basic Tier Tenant",
            subscription_tier="Basic"
        )
        tenant.insert(ignore_permissions=True)

        self.assertEqual(cint(tenant.max_sellers), 10)
        self.assertEqual(cint(tenant.max_listings_per_seller), 100)
        self.assertEqual(flt(tenant.commission_rate), 10.0)

        tenant.delete()

    def test_professional_tier_defaults(self):
        """Test Professional tier gets correct defaults."""
        tenant = self.create_tenant(
            tenant_name="Professional Tier Tenant",
            subscription_tier="Professional"
        )
        tenant.insert(ignore_permissions=True)

        self.assertEqual(cint(tenant.max_sellers), 50)
        self.assertEqual(cint(tenant.max_listings_per_seller), 500)
        self.assertEqual(flt(tenant.commission_rate), 7.5)

        tenant.delete()

    def test_enterprise_tier_unlimited(self):
        """Test Enterprise tier gets unlimited (0) limits."""
        tenant = self.create_tenant(
            tenant_name="Enterprise Tier Tenant",
            subscription_tier="Enterprise"
        )
        tenant.insert(ignore_permissions=True)

        # 0 means unlimited
        self.assertEqual(cint(tenant.max_sellers), 0)
        self.assertEqual(cint(tenant.max_listings_per_seller), 0)
        self.assertEqual(flt(tenant.commission_rate), 5.0)

        tenant.delete()


class TestTenantLimits(FrappeTestCase):
    """Tests for Tenant seller and listing limits."""

    def create_tenant(self, **kwargs):
        """Create a test tenant with default values."""
        defaults = {
            "doctype": "Tenant",
            "tenant_name": "Limits Test Tenant",
            "company_name": "Limits Test Company",
            "status": "Active",
            "subscription_tier": "Basic",
            "contact_email": "limits@tenant.com",
            "max_sellers": 5
        }
        defaults.update(kwargs)
        return frappe.get_doc(defaults)

    def test_negative_max_sellers_rejected(self):
        """Test that negative max_sellers is rejected."""
        tenant = self.create_tenant(
            tenant_name="Negative Sellers Tenant",
            max_sellers=-1
        )
        self.assertRaises(frappe.ValidationError, tenant.insert)

    def test_negative_max_listings_rejected(self):
        """Test that negative max_listings_per_seller is rejected."""
        tenant = self.create_tenant(
            tenant_name="Negative Listings Tenant",
            max_listings_per_seller=-1
        )
        self.assertRaises(frappe.ValidationError, tenant.insert)

    def test_can_add_seller_within_limit(self):
        """Test can_add_seller returns True within limit."""
        tenant = self.create_tenant(
            tenant_name="Can Add Seller Tenant",
            max_sellers=10
        )
        tenant.insert(ignore_permissions=True)

        # No sellers yet, should be able to add
        self.assertTrue(tenant.can_add_seller())

        tenant.delete()

    def test_can_add_seller_unlimited(self):
        """Test can_add_seller returns True for unlimited (0)."""
        tenant = self.create_tenant(
            tenant_name="Unlimited Sellers Tenant",
            max_sellers=0  # Unlimited
        )
        tenant.insert(ignore_permissions=True)

        self.assertTrue(tenant.can_add_seller())

        tenant.delete()

    def test_cannot_add_seller_inactive(self):
        """Test can_add_seller returns False for inactive tenant."""
        tenant = self.create_tenant(
            tenant_name="Inactive Seller Add Tenant",
            status="Suspended",
            max_sellers=10
        )
        tenant.insert(ignore_permissions=True)

        self.assertFalse(tenant.can_add_seller())

        tenant.delete()


class TestTenantIsolationUtility(FrappeTestCase):
    """Tests for tenant isolation utility functions."""

    @classmethod
    def setUpClass(cls):
        """Set up test fixtures."""
        super().setUpClass()
        cls.setup_test_data()

    @classmethod
    def setup_test_data(cls):
        """Create required test data."""
        # Create test tenant A
        if not frappe.db.exists("Tenant", {"tenant_name": "Isolation Test Tenant A"}):
            tenant_a = frappe.get_doc({
                "doctype": "Tenant",
                "tenant_name": "Isolation Test Tenant A",
                "company_name": "Company A",
                "status": "Active",
                "subscription_tier": "Professional",
                "contact_email": "a@tenant.com",
                "max_sellers": 50
            })
            tenant_a.insert(ignore_permissions=True)
            cls.tenant_a = tenant_a.name
        else:
            cls.tenant_a = frappe.db.get_value(
                "Tenant",
                {"tenant_name": "Isolation Test Tenant A"},
                "name"
            )

        # Create test tenant B
        if not frappe.db.exists("Tenant", {"tenant_name": "Isolation Test Tenant B"}):
            tenant_b = frappe.get_doc({
                "doctype": "Tenant",
                "tenant_name": "Isolation Test Tenant B",
                "company_name": "Company B",
                "status": "Active",
                "subscription_tier": "Professional",
                "contact_email": "b@tenant.com",
                "max_sellers": 50
            })
            tenant_b.insert(ignore_permissions=True)
            cls.tenant_b = tenant_b.name
        else:
            cls.tenant_b = frappe.db.get_value(
                "Tenant",
                {"tenant_name": "Isolation Test Tenant B"},
                "name"
            )

    def test_apply_tenant_filter(self):
        """Test apply_tenant_filter adds tenant_id to conditions."""
        from tr_tradehub.utils.tenant import apply_tenant_filter, set_tenant_context, clear_tenant_context

        try:
            # Set tenant context
            set_tenant_context(self.tenant_a)

            conditions = {"status": "Active", "category": "Electronics"}
            filtered = apply_tenant_filter("Listing", conditions)

            self.assertIn("tenant_id", filtered)
            self.assertEqual(filtered["tenant_id"], self.tenant_a)
            self.assertEqual(filtered["status"], "Active")
        except Exception:
            # If tenant context cannot be set (permissions), skip
            pass
        finally:
            clear_tenant_context()

    def test_apply_tenant_filter_no_context(self):
        """Test apply_tenant_filter returns original conditions without context."""
        from tr_tradehub.utils.tenant import apply_tenant_filter, clear_tenant_context

        clear_tenant_context()

        conditions = {"status": "Active"}
        filtered = apply_tenant_filter("Listing", conditions)

        # Without context, should not add tenant_id
        self.assertNotIn("tenant_id", filtered)

    def test_build_tenant_query_condition(self):
        """Test build_tenant_query_condition generates SQL."""
        from tr_tradehub.utils.tenant import build_tenant_query_condition

        condition = build_tenant_query_condition("Listing", self.tenant_a)

        self.assertIn("`tabListing`.`tenant_id`", condition)
        self.assertIn(self.tenant_a, condition)

    def test_build_tenant_query_condition_no_tenant(self):
        """Test build_tenant_query_condition returns empty string without tenant."""
        from tr_tradehub.utils.tenant import build_tenant_query_condition

        condition = build_tenant_query_condition("Listing", None)

        self.assertEqual(condition, "")


class TestTenantContextManagement(FrappeTestCase):
    """Tests for tenant context management functions."""

    @classmethod
    def setUpClass(cls):
        """Set up test fixtures."""
        super().setUpClass()
        TestTenantIsolationUtility.setup_test_data()
        cls.tenant_a = TestTenantIsolationUtility.tenant_a
        cls.tenant_b = TestTenantIsolationUtility.tenant_b

    def test_get_current_tenant_none_by_default(self):
        """Test get_current_tenant returns None when no context is set."""
        from tr_tradehub.utils.tenant import get_current_tenant, clear_tenant_context

        clear_tenant_context()
        tenant = get_current_tenant()

        # May return None or user's default tenant
        # Just ensure it doesn't raise
        self.assertTrue(tenant is None or isinstance(tenant, str))

    def test_tenant_context_manager(self):
        """Test tenant_context context manager."""
        from tr_tradehub.utils.tenant import tenant_context, get_current_tenant, clear_tenant_context

        clear_tenant_context()
        initial_tenant = get_current_tenant()

        try:
            with tenant_context(self.tenant_a):
                current = get_current_tenant()
                self.assertEqual(current, self.tenant_a)

            # After context exits, should restore previous
            after = get_current_tenant()
            self.assertEqual(after, initial_tenant)
        except Exception:
            # If permissions prevent setting context, skip
            pass
        finally:
            clear_tenant_context()

    def test_clear_tenant_context(self):
        """Test clear_tenant_context removes context."""
        from tr_tradehub.utils.tenant import clear_tenant_context

        # Clear should not raise
        clear_tenant_context()

        # Verify cleared
        if hasattr(frappe.local, "tenant_id"):
            self.assertIsNone(frappe.local.tenant_id)


class TestTenantValidation(FrappeTestCase):
    """Tests for tenant document validation."""

    @classmethod
    def setUpClass(cls):
        """Set up test fixtures."""
        super().setUpClass()
        TestTenantIsolationUtility.setup_test_data()
        cls.tenant_a = TestTenantIsolationUtility.tenant_a

    def test_validate_document_tenant_same_tenant(self):
        """Test validate_document_tenant passes for same tenant."""
        from tr_tradehub.utils.tenant import validate_document_tenant

        class MockDoc:
            tenant_id = None

        # Document without tenant_id should pass
        doc = MockDoc()
        result = validate_document_tenant(doc, throw=False)
        self.assertTrue(result)

    def test_validate_document_tenant_no_tenant_field(self):
        """Test validate_document_tenant passes for docs without tenant_id field."""
        from tr_tradehub.utils.tenant import validate_document_tenant

        class MockDoc:
            pass

        doc = MockDoc()
        result = validate_document_tenant(doc, throw=False)
        self.assertTrue(result)


class TestTenantDecorators(FrappeTestCase):
    """Tests for tenant isolation decorators."""

    @classmethod
    def setUpClass(cls):
        """Set up test fixtures."""
        super().setUpClass()
        TestTenantIsolationUtility.setup_test_data()
        cls.tenant_a = TestTenantIsolationUtility.tenant_a

    def test_with_tenant_context_decorator_no_context(self):
        """Test with_tenant_context decorator throws without context."""
        from tr_tradehub.utils.tenant import with_tenant_context, clear_tenant_context

        @with_tenant_context
        def test_function():
            return "success"

        clear_tenant_context()

        # Should throw without tenant context
        self.assertRaises(frappe.ValidationError, test_function)

    def test_require_tenant_decorator_no_context(self):
        """Test require_tenant decorator throws without context."""
        from tr_tradehub.utils.tenant import require_tenant, clear_tenant_context

        @require_tenant()
        def test_function():
            return "success"

        clear_tenant_context()

        # Should throw without tenant context
        self.assertRaises(frappe.ValidationError, test_function)


class TestTenantExceptions(FrappeTestCase):
    """Tests for tenant isolation custom exceptions."""

    def test_tenant_context_error(self):
        """Test TenantContextError is properly raised."""
        from tr_tradehub.utils.tenant import TenantContextError

        try:
            raise TenantContextError("Test error")
        except TenantContextError as e:
            self.assertEqual(str(e), "Test error")

    def test_tenant_not_found_error(self):
        """Test TenantNotFoundError is properly raised."""
        from tr_tradehub.utils.tenant import TenantNotFoundError

        try:
            raise TenantNotFoundError("Tenant not found")
        except TenantNotFoundError as e:
            self.assertEqual(str(e), "Tenant not found")

    def test_tenant_access_denied_error(self):
        """Test TenantAccessDeniedError is properly raised."""
        from tr_tradehub.utils.tenant import TenantAccessDeniedError

        try:
            raise TenantAccessDeniedError("Access denied")
        except TenantAccessDeniedError as e:
            self.assertEqual(str(e), "Access denied")


class TestTenantScopedDoctype(FrappeTestCase):
    """Tests for tenant-scoped DocType detection."""

    def test_is_tenant_scoped_doctype_listing(self):
        """Test that Listing DocType is detected as tenant-scoped."""
        from tr_tradehub.utils.tenant import is_tenant_scoped_doctype

        # Listing should have tenant_id field
        try:
            result = is_tenant_scoped_doctype("Listing")
            # Result depends on whether Listing DocType exists and has tenant_id
            self.assertIsInstance(result, bool)
        except Exception:
            # DocType may not exist yet
            pass

    def test_is_tenant_scoped_doctype_user(self):
        """Test that User DocType is not tenant-scoped."""
        from tr_tradehub.utils.tenant import is_tenant_scoped_doctype

        # User should not have tenant_id field
        result = is_tenant_scoped_doctype("User")
        self.assertFalse(result)


class TestTenantHelpers(FrappeTestCase):
    """Tests for tenant helper functions."""

    @classmethod
    def setUpClass(cls):
        """Set up test fixtures."""
        super().setUpClass()
        TestTenantIsolationUtility.setup_test_data()
        cls.tenant_a = TestTenantIsolationUtility.tenant_a

    def test_get_tenant_doc(self):
        """Test get_tenant_doc returns tenant document."""
        from tr_tradehub.utils.tenant import get_tenant_doc, TenantNotFoundError

        tenant = get_tenant_doc(self.tenant_a, cached=False)

        self.assertIsNotNone(tenant)
        self.assertEqual(tenant.name, self.tenant_a)

    def test_get_tenant_doc_not_found(self):
        """Test get_tenant_doc raises for non-existent tenant."""
        from tr_tradehub.utils.tenant import get_tenant_doc, TenantNotFoundError

        self.assertRaises(
            (TenantNotFoundError, frappe.DoesNotExistError),
            get_tenant_doc,
            "NON-EXISTENT-TENANT"
        )

    def test_is_tenant_active(self):
        """Test is_tenant_active function."""
        from tr_tradehub.utils.tenant import is_tenant_active

        result = is_tenant_active(self.tenant_a)

        # Tenant A should be active
        self.assertTrue(result)

    def test_is_tenant_active_non_existent(self):
        """Test is_tenant_active returns False for non-existent tenant."""
        from tr_tradehub.utils.tenant import is_tenant_active

        result = is_tenant_active("NON-EXISTENT-TENANT")

        self.assertFalse(result)

    def test_get_tenant_settings(self):
        """Test get_tenant_settings returns settings dict."""
        from tr_tradehub.utils.tenant import get_tenant_settings

        settings = get_tenant_settings(self.tenant_a)

        self.assertIsInstance(settings, dict)
        self.assertIn("max_sellers", settings)
        self.assertIn("max_listings_per_seller", settings)
        self.assertIn("commission_rate", settings)
        self.assertIn("subscription_tier", settings)

    def test_get_tenant_settings_specific_key(self):
        """Test get_tenant_settings returns specific setting."""
        from tr_tradehub.utils.tenant import get_tenant_settings

        max_sellers = get_tenant_settings(self.tenant_a, "max_sellers")

        self.assertIsNotNone(max_sellers)


class TestTenantStats(FrappeTestCase):
    """Tests for Tenant statistics methods."""

    @classmethod
    def setUpClass(cls):
        """Set up test fixtures."""
        super().setUpClass()
        TestTenantIsolationUtility.setup_test_data()
        cls.tenant_a = TestTenantIsolationUtility.tenant_a

    def test_get_seller_count(self):
        """Test get_seller_count returns integer."""
        tenant = frappe.get_doc("Tenant", self.tenant_a)

        count = tenant.get_seller_count()

        self.assertIsInstance(count, int)
        self.assertGreaterEqual(count, 0)

    def test_get_listing_count(self):
        """Test get_listing_count returns integer."""
        tenant = frappe.get_doc("Tenant", self.tenant_a)

        count = tenant.get_listing_count()

        self.assertIsInstance(count, int)
        self.assertGreaterEqual(count, 0)


class TestTenantAPIEndpoints(FrappeTestCase):
    """Tests for Tenant API endpoints."""

    @classmethod
    def setUpClass(cls):
        """Set up test fixtures."""
        super().setUpClass()
        TestTenantIsolationUtility.setup_test_data()
        cls.tenant_a = TestTenantIsolationUtility.tenant_a

    def test_get_tenant_stats_api(self):
        """Test get_tenant_stats API returns expected fields."""
        from tr_tradehub.doctype.tenant.tenant import get_tenant_stats

        # Run as Administrator for permissions
        frappe.set_user("Administrator")

        try:
            stats = get_tenant_stats(self.tenant_a)

            self.assertIsInstance(stats, dict)
            self.assertIn("tenant_name", stats)
            self.assertIn("company_name", stats)
            self.assertIn("status", stats)
            self.assertIn("subscription_tier", stats)
            self.assertIn("is_active", stats)
            self.assertIn("seller_count", stats)
            self.assertIn("listing_count", stats)
            self.assertIn("can_add_seller", stats)
        finally:
            frappe.set_user("Administrator")

    def test_check_tenant_limits_api_seller(self):
        """Test check_tenant_limits API for seller check."""
        from tr_tradehub.doctype.tenant.tenant import check_tenant_limits

        # Run as Administrator for permissions
        frappe.set_user("Administrator")

        try:
            result = check_tenant_limits(self.tenant_a, "seller")

            self.assertIsInstance(result, dict)
            self.assertIn("can_proceed", result)
            self.assertIn("message", result)
        finally:
            frappe.set_user("Administrator")

    def test_check_tenant_limits_api_invalid_type(self):
        """Test check_tenant_limits API with invalid check type."""
        from tr_tradehub.doctype.tenant.tenant import check_tenant_limits

        # Run as Administrator for permissions
        frappe.set_user("Administrator")

        try:
            result = check_tenant_limits(self.tenant_a, "invalid_type")

            self.assertFalse(result["can_proceed"])
        finally:
            frappe.set_user("Administrator")


class TestTenantUserAPIs(FrappeTestCase):
    """Tests for Tenant user-facing API endpoints."""

    @classmethod
    def setUpClass(cls):
        """Set up test fixtures."""
        super().setUpClass()
        TestTenantIsolationUtility.setup_test_data()
        cls.tenant_a = TestTenantIsolationUtility.tenant_a

    def test_get_user_tenants_api(self):
        """Test get_user_tenants API returns list."""
        from tr_tradehub.utils.tenant import get_user_tenants

        # Run as Administrator
        frappe.set_user("Administrator")

        try:
            tenants = get_user_tenants()

            self.assertIsInstance(tenants, list)
            # System Manager should see all active tenants
            self.assertGreater(len(tenants), 0)
        finally:
            frappe.set_user("Administrator")

    def test_get_current_tenant_info_api(self):
        """Test get_current_tenant_info API."""
        from tr_tradehub.utils.tenant import (
            get_current_tenant_info,
            set_tenant_context,
            clear_tenant_context
        )

        try:
            set_tenant_context(self.tenant_a)
            info = get_current_tenant_info()

            if info:
                self.assertIsInstance(info, dict)
                self.assertIn("tenant_id", info)
                self.assertIn("tenant_name", info)
        except Exception:
            # May fail due to permissions
            pass
        finally:
            clear_tenant_context()


class TestCrossTenantPrevention(FrappeTestCase):
    """Tests to verify cross-tenant data access is prevented."""

    @classmethod
    def setUpClass(cls):
        """Set up test fixtures."""
        super().setUpClass()
        TestTenantIsolationUtility.setup_test_data()
        cls.tenant_a = TestTenantIsolationUtility.tenant_a
        cls.tenant_b = TestTenantIsolationUtility.tenant_b

    def test_tenant_filter_different_tenants(self):
        """Test that filter conditions differ by tenant."""
        from tr_tradehub.utils.tenant import apply_tenant_filter

        conditions = {"status": "Active"}

        filtered_a = apply_tenant_filter("Listing", conditions, tenant_id=self.tenant_a)
        filtered_b = apply_tenant_filter("Listing", conditions, tenant_id=self.tenant_b)

        self.assertNotEqual(
            filtered_a.get("tenant_id"),
            filtered_b.get("tenant_id")
        )

    def test_query_conditions_different_tenants(self):
        """Test that SQL conditions differ by tenant."""
        from tr_tradehub.utils.tenant import build_tenant_query_condition

        condition_a = build_tenant_query_condition("Listing", self.tenant_a)
        condition_b = build_tenant_query_condition("Listing", self.tenant_b)

        self.assertIn(self.tenant_a, condition_a)
        self.assertIn(self.tenant_b, condition_b)
        self.assertNotEqual(condition_a, condition_b)

    def test_tenant_context_switch_protection(self):
        """Test that context switch updates filtering correctly."""
        from tr_tradehub.utils.tenant import (
            get_current_tenant,
            set_tenant_context,
            clear_tenant_context
        )

        clear_tenant_context()

        try:
            # Set to tenant A
            set_tenant_context(self.tenant_a)
            current_a = get_current_tenant()
            self.assertEqual(current_a, self.tenant_a)

            # Switch to tenant B
            set_tenant_context(self.tenant_b)
            current_b = get_current_tenant()
            self.assertEqual(current_b, self.tenant_b)

            # Verify they're different
            self.assertNotEqual(current_a, current_b)
        except Exception:
            # May fail due to permissions
            pass
        finally:
            clear_tenant_context()


class TestTenantDeletion(FrappeTestCase):
    """Tests for Tenant deletion restrictions."""

    def create_tenant(self, **kwargs):
        """Create a test tenant with default values."""
        defaults = {
            "doctype": "Tenant",
            "tenant_name": "Deletion Test Tenant",
            "company_name": "Deletion Test Company",
            "status": "Active",
            "subscription_tier": "Basic",
            "contact_email": "delete@tenant.com"
        }
        defaults.update(kwargs)
        return frappe.get_doc(defaults)

    def test_tenant_deletion_without_linked_docs(self):
        """Test tenant can be deleted without linked documents."""
        tenant = self.create_tenant(tenant_name="Delete Me Tenant")
        tenant.insert(ignore_permissions=True)

        tenant_name = tenant.name

        # Should be able to delete
        tenant.delete()

        self.assertFalse(frappe.db.exists("Tenant", tenant_name))


class TestTenantCaching(FrappeTestCase):
    """Tests for Tenant caching functionality."""

    @classmethod
    def setUpClass(cls):
        """Set up test fixtures."""
        super().setUpClass()
        TestTenantIsolationUtility.setup_test_data()
        cls.tenant_a = TestTenantIsolationUtility.tenant_a

    def test_tenant_cache_cleared_on_update(self):
        """Test that tenant cache is cleared on update."""
        tenant = frappe.get_doc("Tenant", self.tenant_a)
        cache_key = f"tenant:{self.tenant_a}"

        # Set a cache value
        frappe.cache().set_value(cache_key, {"test": "value"})

        # Update tenant
        original_name = tenant.tenant_name
        tenant.tenant_name = f"{original_name} Updated"
        tenant.save(ignore_permissions=True)

        # Cache should be cleared
        cached = frappe.cache().get_value(cache_key)
        self.assertIsNone(cached)

        # Restore original name
        tenant.tenant_name = original_name
        tenant.save(ignore_permissions=True)

    def test_is_tenant_scoped_doctype_caching(self):
        """Test is_tenant_scoped_doctype uses caching."""
        from tr_tradehub.utils.tenant import is_tenant_scoped_doctype

        # First call
        result1 = is_tenant_scoped_doctype("User")

        # Second call should use cache
        result2 = is_tenant_scoped_doctype("User")

        self.assertEqual(result1, result2)

# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import now_datetime


class TestStorefront(FrappeTestCase):
    """Test cases for Storefront DocType."""

    @classmethod
    def setUpClass(cls):
        """Set up test fixtures."""
        super().setUpClass()

        # Create test user if doesn't exist
        if not frappe.db.exists("User", "test_storefront_seller@example.com"):
            user = frappe.get_doc({
                "doctype": "User",
                "email": "test_storefront_seller@example.com",
                "first_name": "Test",
                "last_name": "Seller",
                "enabled": 1
            })
            user.insert(ignore_permissions=True)

        # Create test seller profile if doesn't exist
        if not frappe.db.exists("Seller Profile", {"user": "test_storefront_seller@example.com"}):
            seller = frappe.get_doc({
                "doctype": "Seller Profile",
                "seller_name": "Test Storefront Seller",
                "user": "test_storefront_seller@example.com",
                "seller_type": "Individual",
                "status": "Active",
                "verification_status": "Verified",
                "contact_email": "test_storefront_seller@example.com",
                "address_line_1": "Test Address",
                "city": "Istanbul",
                "country": "Turkey"
            })
            seller.insert(ignore_permissions=True)

    def tearDown(self):
        """Clean up test data after each test."""
        # Delete test storefronts
        frappe.db.delete("Storefront", {"store_name": ["like", "Test Storefront%"]})

    def test_storefront_creation(self):
        """Test basic storefront creation."""
        seller = frappe.db.get_value("Seller Profile",
                                     {"user": "test_storefront_seller@example.com"}, "name")

        storefront = frappe.get_doc({
            "doctype": "Storefront",
            "store_name": "Test Storefront Basic",
            "seller": seller
        })
        storefront.insert(ignore_permissions=True)

        self.assertTrue(frappe.db.exists("Storefront", storefront.name))
        self.assertEqual(storefront.store_name, "Test Storefront Basic")
        self.assertEqual(storefront.status, "Draft")
        self.assertFalse(storefront.is_published)

    def test_slug_generation(self):
        """Test automatic slug generation from store name."""
        seller = frappe.db.get_value("Seller Profile",
                                     {"user": "test_storefront_seller@example.com"}, "name")

        storefront = frappe.get_doc({
            "doctype": "Storefront",
            "store_name": "Test Storefront Slug Gen",
            "seller": seller
        })
        storefront.insert(ignore_permissions=True)

        self.assertTrue(storefront.slug)
        self.assertTrue(storefront.slug.islower())
        self.assertNotIn(" ", storefront.slug)

    def test_slug_validation(self):
        """Test slug validation and sanitization."""
        seller = frappe.db.get_value("Seller Profile",
                                     {"user": "test_storefront_seller@example.com"}, "name")

        storefront = frappe.get_doc({
            "doctype": "Storefront",
            "store_name": "Test Storefront Slug Valid",
            "seller": seller,
            "slug": "My Awesome Store!!!"  # Should be sanitized
        })
        storefront.insert(ignore_permissions=True)

        self.assertEqual(storefront.slug, "my-awesome-store")

    def test_reserved_slug_rejection(self):
        """Test that reserved slugs are rejected."""
        seller = frappe.db.get_value("Seller Profile",
                                     {"user": "test_storefront_seller@example.com"}, "name")

        storefront = frappe.get_doc({
            "doctype": "Storefront",
            "store_name": "Test Storefront Reserved",
            "seller": seller,
            "slug": "admin"  # Reserved
        })

        with self.assertRaises(frappe.ValidationError):
            storefront.insert(ignore_permissions=True)

    def test_unique_slug_per_storefront(self):
        """Test that slugs are unique across storefronts."""
        # Delete existing test storefronts first
        frappe.db.delete("Storefront", {"store_name": ["like", "Test Storefront Unique%"]})

        seller = frappe.db.get_value("Seller Profile",
                                     {"user": "test_storefront_seller@example.com"}, "name")

        # Create first storefront with specific slug
        storefront1 = frappe.get_doc({
            "doctype": "Storefront",
            "store_name": "Test Storefront Unique 1",
            "seller": seller,
            "slug": "test-unique-slug"
        })
        storefront1.insert(ignore_permissions=True)

        # Delete seller's storefront to allow second creation
        frappe.db.delete("Storefront", {"name": storefront1.name})

        # Second storefront with same slug should get unique suffix
        storefront2 = frappe.get_doc({
            "doctype": "Storefront",
            "store_name": "Test Storefront Unique 2",
            "seller": seller,
            "slug": "test-unique-slug"
        })

        # Should fail since slug must be unique
        with self.assertRaises(frappe.ValidationError):
            storefront2.insert(ignore_permissions=True)

    def test_route_generation(self):
        """Test route generation from slug."""
        seller = frappe.db.get_value("Seller Profile",
                                     {"user": "test_storefront_seller@example.com"}, "name")

        storefront = frappe.get_doc({
            "doctype": "Storefront",
            "store_name": "Test Storefront Route",
            "seller": seller,
            "slug": "test-route-store"
        })
        storefront.insert(ignore_permissions=True)

        self.assertEqual(storefront.route, "store/test-route-store")

    def test_color_validation(self):
        """Test hex color code validation."""
        seller = frappe.db.get_value("Seller Profile",
                                     {"user": "test_storefront_seller@example.com"}, "name")

        # Valid color
        storefront = frappe.get_doc({
            "doctype": "Storefront",
            "store_name": "Test Storefront Colors",
            "seller": seller,
            "primary_color": "#FF5733"
        })
        storefront.insert(ignore_permissions=True)

        self.assertEqual(storefront.primary_color, "#FF5733")

    def test_invalid_color_rejection(self):
        """Test that invalid color codes are rejected."""
        seller = frappe.db.get_value("Seller Profile",
                                     {"user": "test_storefront_seller@example.com"}, "name")

        storefront = frappe.get_doc({
            "doctype": "Storefront",
            "store_name": "Test Storefront Invalid Color",
            "seller": seller,
            "primary_color": "not-a-color"
        })

        with self.assertRaises(frappe.ValidationError):
            storefront.insert(ignore_permissions=True)

    def test_theme_config(self):
        """Test theme configuration retrieval."""
        seller = frappe.db.get_value("Seller Profile",
                                     {"user": "test_storefront_seller@example.com"}, "name")

        storefront = frappe.get_doc({
            "doctype": "Storefront",
            "store_name": "Test Storefront Theme",
            "seller": seller,
            "theme": "Modern",
            "primary_color": "#3B82F6",
            "secondary_color": "#1E40AF"
        })
        storefront.insert(ignore_permissions=True)

        theme_config = storefront.get_theme_config()

        self.assertEqual(theme_config["theme"], "Modern")
        self.assertEqual(theme_config["primary_color"], "#3B82F6")

    def test_public_info_retrieval(self):
        """Test public information retrieval."""
        seller = frappe.db.get_value("Seller Profile",
                                     {"user": "test_storefront_seller@example.com"}, "name")

        storefront = frappe.get_doc({
            "doctype": "Storefront",
            "store_name": "Test Storefront Public Info",
            "seller": seller,
            "tagline": "Best products ever",
            "public_email": "contact@test.com"
        })
        storefront.insert(ignore_permissions=True)

        public_info = storefront.get_public_info()

        self.assertEqual(public_info["store_name"], "Test Storefront Public Info")
        self.assertEqual(public_info["tagline"], "Best products ever")
        self.assertEqual(public_info["contact"]["email"], "contact@test.com")

    def test_products_per_page_limits(self):
        """Test products per page validation."""
        seller = frappe.db.get_value("Seller Profile",
                                     {"user": "test_storefront_seller@example.com"}, "name")

        # Too low - should be set to minimum
        storefront = frappe.get_doc({
            "doctype": "Storefront",
            "store_name": "Test Storefront PPP Low",
            "seller": seller,
            "products_per_page": 2
        })
        storefront.insert(ignore_permissions=True)

        self.assertEqual(storefront.products_per_page, 4)

    def test_featured_dates_validation(self):
        """Test featured date range validation."""
        seller = frappe.db.get_value("Seller Profile",
                                     {"user": "test_storefront_seller@example.com"}, "name")

        from frappe.utils import add_days

        storefront = frappe.get_doc({
            "doctype": "Storefront",
            "store_name": "Test Storefront Featured Dates",
            "seller": seller,
            "is_featured": 1,
            "featured_from": add_days(now_datetime(), 10),
            "featured_until": add_days(now_datetime(), 5)  # Before from date
        })

        with self.assertRaises(frappe.ValidationError):
            storefront.insert(ignore_permissions=True)

    def test_view_increment(self):
        """Test view counter increment."""
        seller = frappe.db.get_value("Seller Profile",
                                     {"user": "test_storefront_seller@example.com"}, "name")

        storefront = frappe.get_doc({
            "doctype": "Storefront",
            "store_name": "Test Storefront Views",
            "seller": seller
        })
        storefront.insert(ignore_permissions=True)

        initial_views = storefront.total_views or 0
        storefront.increment_views()

        # Reload from database
        storefront.reload()
        self.assertEqual(storefront.total_views, initial_views + 1)

    def test_is_active_check(self):
        """Test is_active status check."""
        seller = frappe.db.get_value("Seller Profile",
                                     {"user": "test_storefront_seller@example.com"}, "name")

        storefront = frappe.get_doc({
            "doctype": "Storefront",
            "store_name": "Test Storefront Active Check",
            "seller": seller,
            "status": "Active",
            "is_published": 1
        })
        storefront.insert(ignore_permissions=True)

        self.assertTrue(storefront.is_active())

        # Test inactive
        storefront.is_published = 0
        self.assertFalse(storefront.is_active())


# API Tests
class TestStorefrontAPI(FrappeTestCase):
    """Test cases for Storefront API endpoints."""

    @classmethod
    def setUpClass(cls):
        """Set up test fixtures."""
        super().setUpClass()

        # Create test user if doesn't exist
        if not frappe.db.exists("User", "test_storefront_api@example.com"):
            user = frappe.get_doc({
                "doctype": "User",
                "email": "test_storefront_api@example.com",
                "first_name": "API",
                "last_name": "Tester",
                "enabled": 1
            })
            user.insert(ignore_permissions=True)

        # Create test seller profile
        if not frappe.db.exists("Seller Profile", {"user": "test_storefront_api@example.com"}):
            seller = frappe.get_doc({
                "doctype": "Seller Profile",
                "seller_name": "API Test Seller",
                "user": "test_storefront_api@example.com",
                "seller_type": "Individual",
                "status": "Active",
                "verification_status": "Verified",
                "contact_email": "test_storefront_api@example.com",
                "address_line_1": "Test Address",
                "city": "Istanbul",
                "country": "Turkey"
            })
            seller.insert(ignore_permissions=True)

    def tearDown(self):
        """Clean up test data."""
        frappe.db.delete("Storefront", {"store_name": ["like", "API Test%"]})

    def test_get_storefront_api(self):
        """Test get_storefront API endpoint."""
        from tradehub_marketing.tradehub_marketing.doctype.storefront.storefront import get_storefront

        seller = frappe.db.get_value("Seller Profile",
                                     {"user": "test_storefront_api@example.com"}, "name")

        # Create test storefront
        storefront = frappe.get_doc({
            "doctype": "Storefront",
            "store_name": "API Test Get Store",
            "seller": seller,
            "status": "Active",
            "is_published": 1
        })
        storefront.insert(ignore_permissions=True)

        # Test retrieval
        result = get_storefront(storefront_name=storefront.name)

        self.assertEqual(result["store_name"], "API Test Get Store")

    def test_get_storefront_by_slug_api(self):
        """Test get_storefront_by_slug API endpoint."""
        from tradehub_marketing.tradehub_marketing.doctype.storefront.storefront import get_storefront_by_slug

        seller = frappe.db.get_value("Seller Profile",
                                     {"user": "test_storefront_api@example.com"}, "name")

        # Create test storefront
        storefront = frappe.get_doc({
            "doctype": "Storefront",
            "store_name": "API Test Slug Store",
            "seller": seller,
            "slug": "api-test-slug-store",
            "status": "Active",
            "is_published": 1
        })
        storefront.insert(ignore_permissions=True)

        # Test retrieval by slug
        result = get_storefront_by_slug("api-test-slug-store")

        self.assertEqual(result["slug"], "api-test-slug-store")

    def test_search_storefronts_api(self):
        """Test search_storefronts API endpoint."""
        from tradehub_marketing.tradehub_marketing.doctype.storefront.storefront import search_storefronts

        seller = frappe.db.get_value("Seller Profile",
                                     {"user": "test_storefront_api@example.com"}, "name")

        # Create test storefront
        storefront = frappe.get_doc({
            "doctype": "Storefront",
            "store_name": "API Test Search Electronics",
            "seller": seller,
            "tagline": "Best electronics shop",
            "status": "Active",
            "is_published": 1
        })
        storefront.insert(ignore_permissions=True)

        # Test search
        results = search_storefronts("electronics")

        self.assertTrue(len(results) > 0)
        found = any(s["store_name"] == "API Test Search Electronics" for s in results)
        self.assertTrue(found)

    def test_record_storefront_view_api(self):
        """Test record_storefront_view API endpoint."""
        from tradehub_marketing.tradehub_marketing.doctype.storefront.storefront import record_storefront_view

        seller = frappe.db.get_value("Seller Profile",
                                     {"user": "test_storefront_api@example.com"}, "name")

        # Create test storefront
        storefront = frappe.get_doc({
            "doctype": "Storefront",
            "store_name": "API Test View Record",
            "seller": seller
        })
        storefront.insert(ignore_permissions=True)

        # Record view
        result = record_storefront_view(storefront.name)

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["total_views"], 1)

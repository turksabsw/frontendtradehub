# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

"""
Comprehensive unit tests for the Listing DocType.

Tests cover:
- Listing creation and validation
- Pricing logic (B2B, B2C, bulk pricing, sales)
- Inventory management (stock updates, reservations)
- Status transitions (publish, pause, archive, suspend)
- Moderation workflow (approve, reject, flag)
- Quality score calculation
- Route/SEO generation
- Auction listing validation
- Visibility logic
"""

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import flt, cint, now_datetime, add_days
import json


class TestListingCreation(FrappeTestCase):
    """Tests for Listing creation and basic validation."""

    @classmethod
    def setUpClass(cls):
        """Set up test fixtures."""
        super().setUpClass()
        cls.setup_test_data()

    @classmethod
    def setup_test_data(cls):
        """Create required test data."""
        # Create test category
        if not frappe.db.exists("Category", "Test Electronics"):
            category = frappe.get_doc({
                "doctype": "Category",
                "category_name": "Test Electronics",
                "is_active": 1,
                "commission_rate": 12.0
            })
            category.insert(ignore_permissions=True)

        # Create test user
        if not frappe.db.exists("User", "listing_test_seller@example.com"):
            user = frappe.get_doc({
                "doctype": "User",
                "email": "listing_test_seller@example.com",
                "first_name": "Listing",
                "last_name": "Seller",
                "send_welcome_email": 0
            })
            user.insert(ignore_permissions=True)

        # Create test seller profile
        if not frappe.db.exists("Seller Profile", {"user": "listing_test_seller@example.com"}):
            seller = frappe.get_doc({
                "doctype": "Seller Profile",
                "seller_name": "Listing Test Seller",
                "user": "listing_test_seller@example.com",
                "seller_type": "Individual",
                "status": "Active",
                "verification_status": "Verified",
                "contact_email": "listing_test_seller@example.com",
                "address_line_1": "Test Address 123",
                "city": "Istanbul",
                "country": "Turkey",
                "can_sell": 1,
                "can_create_listings": 1,
                "max_listings": 100
            })
            seller.insert(ignore_permissions=True)

    def get_test_seller(self):
        """Get the test seller profile name."""
        return frappe.db.get_value(
            "Seller Profile",
            {"user": "listing_test_seller@example.com"},
            "name"
        )

    def create_listing(self, **kwargs):
        """Create a test listing with default values."""
        defaults = {
            "doctype": "Listing",
            "title": "Test Product for Unit Tests",
            "seller": self.get_test_seller(),
            "category": "Test Electronics",
            "base_price": 100.0,
            "selling_price": 100.0,
            "currency": "TRY",
            "stock_qty": 10,
            "stock_uom": "Nos",
            "min_order_qty": 1
        }
        defaults.update(kwargs)
        return frappe.get_doc(defaults)

    def test_listing_creation_basic(self):
        """Test basic listing creation."""
        listing = self.create_listing(title="Basic Creation Test")
        listing.insert(ignore_permissions=True)

        self.assertIsNotNone(listing.name)
        self.assertIsNotNone(listing.listing_code)
        self.assertEqual(listing.status, "Draft")
        self.assertEqual(listing.title, "Basic Creation Test")

        listing.delete()

    def test_listing_code_format(self):
        """Test that listing code follows expected format."""
        listing = self.create_listing(title="Code Format Test")
        listing.insert(ignore_permissions=True)

        self.assertTrue(listing.listing_code.startswith("LST-"))
        self.assertEqual(len(listing.listing_code), 12)  # LST- + 8 chars

        listing.delete()

    def test_listing_requires_seller(self):
        """Test that listing requires a valid seller."""
        listing = self.create_listing(seller=None)
        self.assertRaises(frappe.ValidationError, listing.insert)

    def test_listing_requires_category(self):
        """Test that listing requires a valid category."""
        listing = self.create_listing(category=None)
        self.assertRaises(frappe.ValidationError, listing.insert)


class TestListingPricing(FrappeTestCase):
    """Tests for Listing pricing logic."""

    @classmethod
    def setUpClass(cls):
        """Set up test fixtures."""
        super().setUpClass()
        TestListingCreation.setup_test_data()

    def get_test_seller(self):
        """Get the test seller profile name."""
        return frappe.db.get_value(
            "Seller Profile",
            {"user": "listing_test_seller@example.com"},
            "name"
        )

    def create_listing(self, **kwargs):
        """Create a test listing with default values."""
        defaults = {
            "doctype": "Listing",
            "title": "Pricing Test Product",
            "seller": self.get_test_seller(),
            "category": "Test Electronics",
            "base_price": 100.0,
            "selling_price": 100.0,
            "currency": "TRY",
            "stock_qty": 10,
            "stock_uom": "Nos",
            "min_order_qty": 1
        }
        defaults.update(kwargs)
        return frappe.get_doc(defaults)

    def test_price_validation_negative_base_price(self):
        """Test that negative base price is rejected."""
        listing = self.create_listing(base_price=-50)
        self.assertRaises(frappe.ValidationError, listing.insert)

    def test_price_validation_selling_greater_than_base(self):
        """Test that selling price cannot exceed base price."""
        listing = self.create_listing(base_price=100, selling_price=150)
        self.assertRaises(frappe.ValidationError, listing.insert)

    def test_price_validation_compare_at_price(self):
        """Test compare_at_price validation."""
        listing = self.create_listing(
            selling_price=100,
            compare_at_price=80  # Less than selling price
        )
        self.assertRaises(frappe.ValidationError, listing.insert)

    def test_discount_percentage_calculation(self):
        """Test discount percentage calculation."""
        listing = self.create_listing(
            selling_price=80,
            compare_at_price=100
        )
        listing.insert(ignore_permissions=True)

        self.assertEqual(listing.get_discount_percentage(), 20.0)

        listing.delete()

    def test_b2c_price(self):
        """Test B2C price retrieval."""
        listing = self.create_listing(selling_price=100)
        listing.insert(ignore_permissions=True)

        self.assertEqual(listing.get_price(1, "B2C"), 100.0)

        listing.delete()

    def test_b2b_price_enabled(self):
        """Test B2B price when enabled."""
        listing = self.create_listing(
            selling_price=100,
            b2b_enabled=1,
            wholesale_min_qty=10,
            wholesale_price=80
        )
        listing.insert(ignore_permissions=True)

        # Below min qty should return regular price
        self.assertEqual(listing.get_price(5, "B2B"), 100.0)

        # At or above min qty should return wholesale price
        self.assertEqual(listing.get_price(10, "B2B"), 80.0)
        self.assertEqual(listing.get_price(15, "B2B"), 80.0)

        listing.delete()

    def test_bulk_pricing_tiers(self):
        """Test bulk pricing tier functionality."""
        listing = self.create_listing(
            selling_price=100,
            b2b_enabled=1,
            wholesale_min_qty=5,
            wholesale_price=90,
            bulk_pricing_enabled=1,
            bulk_pricing_tiers=json.dumps([
                {"min_qty": 10, "max_qty": 50, "price": 85},
                {"min_qty": 51, "max_qty": 100, "price": 75}
            ])
        )
        listing.insert(ignore_permissions=True)

        # Test tier prices
        self.assertEqual(listing.get_bulk_tier_price(10), 85.0)
        self.assertEqual(listing.get_bulk_tier_price(25), 85.0)
        self.assertEqual(listing.get_bulk_tier_price(60), 75.0)

        listing.delete()

    def test_sale_price_active(self):
        """Test sale price when sale is active."""
        listing = self.create_listing(
            selling_price=80,
            compare_at_price=100,
            is_on_sale=1,
            sale_start_date=add_days(now_datetime(), -1),
            sale_end_date=add_days(now_datetime(), 7)
        )
        listing.insert(ignore_permissions=True)

        self.assertTrue(listing.is_sale_active())
        self.assertEqual(listing.get_price(), 80.0)

        listing.delete()

    def test_sale_price_not_started(self):
        """Test sale price when sale hasn't started."""
        listing = self.create_listing(
            selling_price=80,
            is_on_sale=1,
            sale_start_date=add_days(now_datetime(), 1),  # Future date
            sale_end_date=add_days(now_datetime(), 7)
        )
        listing.insert(ignore_permissions=True)

        self.assertFalse(listing.is_sale_active())

        listing.delete()


class TestListingInventory(FrappeTestCase):
    """Tests for Listing inventory management."""

    @classmethod
    def setUpClass(cls):
        """Set up test fixtures."""
        super().setUpClass()
        TestListingCreation.setup_test_data()

    def get_test_seller(self):
        """Get the test seller profile name."""
        return frappe.db.get_value(
            "Seller Profile",
            {"user": "listing_test_seller@example.com"},
            "name"
        )

    def create_listing(self, **kwargs):
        """Create a test listing with default values."""
        defaults = {
            "doctype": "Listing",
            "title": "Inventory Test Product",
            "seller": self.get_test_seller(),
            "category": "Test Electronics",
            "base_price": 100.0,
            "selling_price": 100.0,
            "currency": "TRY",
            "stock_qty": 50,
            "stock_uom": "Nos",
            "min_order_qty": 1
        }
        defaults.update(kwargs)
        return frappe.get_doc(defaults)

    def test_available_qty_calculation(self):
        """Test available quantity calculation."""
        listing = self.create_listing(stock_qty=100)
        listing.insert(ignore_permissions=True)

        self.assertEqual(flt(listing.available_qty), 100.0)
        self.assertEqual(flt(listing.reserved_qty), 0.0)

        listing.delete()

    def test_stock_update_add(self):
        """Test adding stock."""
        listing = self.create_listing(stock_qty=50)
        listing.insert(ignore_permissions=True)

        listing.update_stock(25)
        listing.reload()

        self.assertEqual(flt(listing.stock_qty), 75.0)

        listing.delete()

    def test_stock_update_subtract(self):
        """Test subtracting stock."""
        listing = self.create_listing(stock_qty=50)
        listing.insert(ignore_permissions=True)

        listing.update_stock(-20)
        listing.reload()

        self.assertEqual(flt(listing.stock_qty), 30.0)

        listing.delete()

    def test_stock_update_negative_result(self):
        """Test that stock cannot go negative."""
        listing = self.create_listing(stock_qty=10)
        listing.insert(ignore_permissions=True)

        self.assertRaises(frappe.ValidationError, listing.update_stock, -20)

        listing.delete()

    def test_reserve_stock(self):
        """Test stock reservation."""
        listing = self.create_listing(stock_qty=100)
        listing.insert(ignore_permissions=True)

        listing.reserve_stock(20)
        listing.reload()

        self.assertEqual(flt(listing.reserved_qty), 20.0)

        listing.delete()

    def test_release_reservation(self):
        """Test releasing stock reservation."""
        listing = self.create_listing(stock_qty=100)
        listing.insert(ignore_permissions=True)

        listing.reserve_stock(30)
        listing.reload()
        self.assertEqual(flt(listing.reserved_qty), 30.0)

        listing.release_reservation(15)
        listing.reload()
        self.assertEqual(flt(listing.reserved_qty), 15.0)

        listing.delete()

    def test_out_of_stock_status(self):
        """Test automatic out of stock status."""
        listing = self.create_listing(
            stock_qty=5,
            track_inventory=1,
            allow_backorders=0
        )
        listing.insert(ignore_permissions=True)
        listing.submit()

        # Reduce stock to 0
        listing.update_stock(-5)
        listing.reload()

        self.assertEqual(listing.status, "Out of Stock")

        # Add stock back
        listing.update_stock(10)
        listing.reload()

        self.assertEqual(listing.status, "Active")

        listing.cancel()
        listing.delete()


class TestListingStatus(FrappeTestCase):
    """Tests for Listing status transitions."""

    @classmethod
    def setUpClass(cls):
        """Set up test fixtures."""
        super().setUpClass()
        TestListingCreation.setup_test_data()

    def get_test_seller(self):
        """Get the test seller profile name."""
        return frappe.db.get_value(
            "Seller Profile",
            {"user": "listing_test_seller@example.com"},
            "name"
        )

    def create_listing(self, **kwargs):
        """Create a test listing with default values."""
        defaults = {
            "doctype": "Listing",
            "title": "Status Test Product",
            "seller": self.get_test_seller(),
            "category": "Test Electronics",
            "base_price": 100.0,
            "selling_price": 100.0,
            "currency": "TRY",
            "stock_qty": 10,
            "stock_uom": "Nos",
            "min_order_qty": 1
        }
        defaults.update(kwargs)
        return frappe.get_doc(defaults)

    def test_pause_unpause_cycle(self):
        """Test pause and unpause cycle."""
        listing = self.create_listing()
        listing.insert(ignore_permissions=True)
        listing.submit()

        # Pause
        listing.pause()
        listing.reload()
        self.assertEqual(listing.status, "Paused")

        # Unpause
        listing.unpause()
        listing.reload()
        self.assertEqual(listing.status, "Active")

        listing.cancel()
        listing.delete()

    def test_archive(self):
        """Test archive functionality."""
        listing = self.create_listing()
        listing.insert(ignore_permissions=True)
        listing.submit()

        listing.archive()
        listing.reload()

        self.assertEqual(listing.status, "Archived")
        self.assertEqual(listing.is_visible, 0)

        listing.cancel()
        listing.delete()

    def test_suspend(self):
        """Test suspend functionality."""
        listing = self.create_listing()
        listing.insert(ignore_permissions=True)
        listing.submit()

        listing.suspend("Policy violation")
        listing.reload()

        self.assertEqual(listing.status, "Suspended")
        self.assertEqual(listing.is_visible, 0)
        self.assertIn("Suspended", listing.moderation_notes)

        listing.cancel()
        listing.delete()


class TestListingModeration(FrappeTestCase):
    """Tests for Listing moderation workflow."""

    @classmethod
    def setUpClass(cls):
        """Set up test fixtures."""
        super().setUpClass()
        TestListingCreation.setup_test_data()

    def get_test_seller(self):
        """Get the test seller profile name."""
        return frappe.db.get_value(
            "Seller Profile",
            {"user": "listing_test_seller@example.com"},
            "name"
        )

    def create_listing(self, **kwargs):
        """Create a test listing with default values."""
        defaults = {
            "doctype": "Listing",
            "title": "Moderation Test Product",
            "seller": self.get_test_seller(),
            "category": "Test Electronics",
            "base_price": 100.0,
            "selling_price": 100.0,
            "currency": "TRY",
            "stock_qty": 10,
            "stock_uom": "Nos",
            "min_order_qty": 1
        }
        defaults.update(kwargs)
        return frappe.get_doc(defaults)

    def test_approve_listing(self):
        """Test listing approval."""
        listing = self.create_listing(requires_approval=1)
        listing.insert(ignore_permissions=True)
        listing.submit()

        # Should be pending review
        self.assertEqual(listing.status, "Pending Review")
        self.assertEqual(listing.moderation_status, "Pending")

        # Approve
        listing.approve()
        listing.reload()

        self.assertEqual(listing.moderation_status, "Approved")
        self.assertEqual(listing.status, "Active")
        self.assertIsNotNone(listing.moderated_at)
        self.assertIsNotNone(listing.moderated_by)

        listing.cancel()
        listing.delete()

    def test_reject_listing(self):
        """Test listing rejection."""
        listing = self.create_listing(requires_approval=1)
        listing.insert(ignore_permissions=True)
        listing.submit()

        # Reject
        listing.reject("Content violates guidelines")
        listing.reload()

        self.assertEqual(listing.moderation_status, "Rejected")
        self.assertEqual(listing.status, "Rejected")
        self.assertEqual(listing.rejection_reason, "Content violates guidelines")
        self.assertEqual(listing.is_visible, 0)

        listing.cancel()
        listing.delete()

    def test_flag_listing(self):
        """Test flagging listing for review."""
        listing = self.create_listing()
        listing.insert(ignore_permissions=True)
        listing.submit()

        listing.flag("Suspicious content reported")
        listing.reload()

        self.assertEqual(listing.moderation_status, "Flagged")
        self.assertIn("Flagged", listing.moderation_notes)

        listing.cancel()
        listing.delete()


class TestListingQuality(FrappeTestCase):
    """Tests for Listing quality score calculation."""

    @classmethod
    def setUpClass(cls):
        """Set up test fixtures."""
        super().setUpClass()
        TestListingCreation.setup_test_data()

    def get_test_seller(self):
        """Get the test seller profile name."""
        return frappe.db.get_value(
            "Seller Profile",
            {"user": "listing_test_seller@example.com"},
            "name"
        )

    def create_listing(self, **kwargs):
        """Create a test listing with default values."""
        defaults = {
            "doctype": "Listing",
            "title": "Quality Test",
            "seller": self.get_test_seller(),
            "category": "Test Electronics",
            "base_price": 100.0,
            "selling_price": 100.0,
            "currency": "TRY",
            "stock_qty": 10,
            "stock_uom": "Nos",
            "min_order_qty": 1
        }
        defaults.update(kwargs)
        return frappe.get_doc(defaults)

    def test_minimal_listing_low_score(self):
        """Test that minimal listing gets low quality score."""
        listing = self.create_listing(title="Short")
        listing.insert(ignore_permissions=True)

        self.assertLess(listing.quality_score, 50)

        listing.delete()

    def test_complete_listing_high_score(self):
        """Test that complete listing gets higher quality score."""
        listing = self.create_listing(
            title="This is a very detailed and descriptive product title",
            description="This is a comprehensive product description with all the details that a buyer would need. It includes features, benefits, specifications, and use cases. The description is thorough and helps buyers make informed decisions.",
            short_description="High quality product with great features",
            brand="Premium Brand",
            sku="TEST-SKU-001",
            meta_title="SEO Optimized Product Title",
            meta_description="SEO meta description for search engines",
            meta_keywords="keyword1, keyword2, keyword3",
            weight=1.5,
            barcode="1234567890123"
        )
        listing.insert(ignore_permissions=True)

        self.assertGreater(listing.quality_score, 50)

        listing.delete()


class TestListingRoutes(FrappeTestCase):
    """Tests for Listing SEO route generation."""

    @classmethod
    def setUpClass(cls):
        """Set up test fixtures."""
        super().setUpClass()
        TestListingCreation.setup_test_data()

    def get_test_seller(self):
        """Get the test seller profile name."""
        return frappe.db.get_value(
            "Seller Profile",
            {"user": "listing_test_seller@example.com"},
            "name"
        )

    def create_listing(self, **kwargs):
        """Create a test listing with default values."""
        defaults = {
            "doctype": "Listing",
            "title": "Route Test Product",
            "seller": self.get_test_seller(),
            "category": "Test Electronics",
            "base_price": 100.0,
            "selling_price": 100.0,
            "currency": "TRY",
            "stock_qty": 10,
            "stock_uom": "Nos",
            "min_order_qty": 1
        }
        defaults.update(kwargs)
        return frappe.get_doc(defaults)

    def test_route_generation(self):
        """Test SEO-friendly route is generated."""
        listing = self.create_listing(title="Amazing Product With Features")
        listing.insert(ignore_permissions=True)

        self.assertIsNotNone(listing.route)
        self.assertTrue(listing.route.startswith("products/"))
        self.assertIn(listing.listing_code, listing.route)

        listing.delete()

    def test_route_special_characters(self):
        """Test that special characters are removed from route."""
        listing = self.create_listing(
            title="Amazing Product! With @Special# Characters$"
        )
        listing.insert(ignore_permissions=True)

        self.assertNotIn("!", listing.route)
        self.assertNotIn("@", listing.route)
        self.assertNotIn("#", listing.route)
        self.assertNotIn("$", listing.route)

        listing.delete()


class TestListingAuction(FrappeTestCase):
    """Tests for Auction listing validation."""

    @classmethod
    def setUpClass(cls):
        """Set up test fixtures."""
        super().setUpClass()
        TestListingCreation.setup_test_data()

    def get_test_seller(self):
        """Get the test seller profile name."""
        return frappe.db.get_value(
            "Seller Profile",
            {"user": "listing_test_seller@example.com"},
            "name"
        )

    def create_listing(self, **kwargs):
        """Create a test listing with default values."""
        defaults = {
            "doctype": "Listing",
            "title": "Auction Test Product",
            "seller": self.get_test_seller(),
            "category": "Test Electronics",
            "base_price": 100.0,
            "selling_price": 100.0,
            "currency": "TRY",
            "stock_qty": 1,
            "stock_uom": "Nos",
            "min_order_qty": 1
        }
        defaults.update(kwargs)
        return frappe.get_doc(defaults)

    def test_auction_listing_valid(self):
        """Test valid auction listing creation."""
        listing = self.create_listing(
            listing_type="Auction",
            auction_start_date=now_datetime(),
            auction_end_date=add_days(now_datetime(), 7),
            starting_bid=50,
            reserve_price=100,
            buy_now_price=200,
            bid_increment=5
        )
        listing.insert(ignore_permissions=True)

        self.assertEqual(listing.is_auction, 1)
        self.assertIsNotNone(listing.auction_start_date)
        self.assertIsNotNone(listing.auction_end_date)

        listing.delete()

    def test_auction_invalid_dates(self):
        """Test auction with invalid date range."""
        listing = self.create_listing(
            listing_type="Auction",
            auction_start_date=add_days(now_datetime(), 7),
            auction_end_date=now_datetime(),  # End before start
            starting_bid=50
        )
        self.assertRaises(frappe.ValidationError, listing.insert)

    def test_auction_requires_starting_bid(self):
        """Test that auction requires starting bid."""
        listing = self.create_listing(
            listing_type="Auction",
            auction_start_date=now_datetime(),
            auction_end_date=add_days(now_datetime(), 7),
            starting_bid=0  # Invalid
        )
        self.assertRaises(frappe.ValidationError, listing.insert)


class TestListingVisibility(FrappeTestCase):
    """Tests for Listing visibility logic."""

    @classmethod
    def setUpClass(cls):
        """Set up test fixtures."""
        super().setUpClass()
        TestListingCreation.setup_test_data()

    def get_test_seller(self):
        """Get the test seller profile name."""
        return frappe.db.get_value(
            "Seller Profile",
            {"user": "listing_test_seller@example.com"},
            "name"
        )

    def create_listing(self, **kwargs):
        """Create a test listing with default values."""
        defaults = {
            "doctype": "Listing",
            "title": "Visibility Test Product",
            "seller": self.get_test_seller(),
            "category": "Test Electronics",
            "base_price": 100.0,
            "selling_price": 100.0,
            "currency": "TRY",
            "stock_qty": 10,
            "stock_uom": "Nos",
            "min_order_qty": 1
        }
        defaults.update(kwargs)
        return frappe.get_doc(defaults)

    def test_draft_not_visible(self):
        """Test that draft listing is not visible to buyers."""
        listing = self.create_listing()
        listing.insert(ignore_permissions=True)

        self.assertFalse(listing.is_visible_to_buyer())

        listing.delete()

    def test_active_visible(self):
        """Test that active listing is visible to buyers."""
        listing = self.create_listing()
        listing.insert(ignore_permissions=True)
        listing.submit()
        listing.reload()

        self.assertTrue(listing.is_visible_to_buyer())

        listing.cancel()
        listing.delete()

    def test_hidden_not_visible(self):
        """Test that hidden listing is not visible."""
        listing = self.create_listing()
        listing.insert(ignore_permissions=True)
        listing.submit()

        listing.db_set("is_visible", 0)
        listing.reload()

        self.assertFalse(listing.is_visible_to_buyer())

        listing.cancel()
        listing.delete()


class TestListingStatistics(FrappeTestCase):
    """Tests for Listing statistics tracking."""

    @classmethod
    def setUpClass(cls):
        """Set up test fixtures."""
        super().setUpClass()
        TestListingCreation.setup_test_data()

    def get_test_seller(self):
        """Get the test seller profile name."""
        return frappe.db.get_value(
            "Seller Profile",
            {"user": "listing_test_seller@example.com"},
            "name"
        )

    def create_listing(self, **kwargs):
        """Create a test listing with default values."""
        defaults = {
            "doctype": "Listing",
            "title": "Stats Test Product",
            "seller": self.get_test_seller(),
            "category": "Test Electronics",
            "base_price": 100.0,
            "selling_price": 100.0,
            "currency": "TRY",
            "stock_qty": 10,
            "stock_uom": "Nos",
            "min_order_qty": 1
        }
        defaults.update(kwargs)
        return frappe.get_doc(defaults)

    def test_view_count_increment(self):
        """Test view count increment."""
        listing = self.create_listing()
        listing.insert(ignore_permissions=True)

        initial_views = cint(listing.view_count)
        listing.increment_view_count()
        listing.reload()

        self.assertEqual(cint(listing.view_count), initial_views + 1)

        listing.delete()

    def test_wishlist_count(self):
        """Test wishlist count operations."""
        listing = self.create_listing()
        listing.insert(ignore_permissions=True)

        initial_count = cint(listing.wishlist_count)

        listing.increment_wishlist_count()
        listing.reload()
        self.assertEqual(cint(listing.wishlist_count), initial_count + 1)

        listing.decrement_wishlist_count()
        listing.reload()
        self.assertEqual(cint(listing.wishlist_count), initial_count)

        listing.delete()

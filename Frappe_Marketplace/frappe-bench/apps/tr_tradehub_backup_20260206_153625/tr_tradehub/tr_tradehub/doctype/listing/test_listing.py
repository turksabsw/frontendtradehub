# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import flt, cint, now_datetime


class TestListing(FrappeTestCase):
    """Test cases for the Listing DocType."""

    @classmethod
    def setUpClass(cls):
        """Set up test fixtures."""
        super().setUpClass()

        # Create test category if not exists
        if not frappe.db.exists("Category", "Test Category"):
            category = frappe.get_doc({
                "doctype": "Category",
                "category_name": "Test Category",
                "is_active": 1,
                "commission_rate": 10.0
            })
            category.insert(ignore_permissions=True)

        # Create test user if not exists
        if not frappe.db.exists("User", "test_seller@example.com"):
            user = frappe.get_doc({
                "doctype": "User",
                "email": "test_seller@example.com",
                "first_name": "Test",
                "last_name": "Seller",
                "send_welcome_email": 0
            })
            user.insert(ignore_permissions=True)

        # Create test seller profile if not exists
        if not frappe.db.exists("Seller Profile", {"user": "test_seller@example.com"}):
            seller = frappe.get_doc({
                "doctype": "Seller Profile",
                "seller_name": "Test Seller",
                "user": "test_seller@example.com",
                "seller_type": "Individual",
                "status": "Active",
                "verification_status": "Verified",
                "contact_email": "test_seller@example.com",
                "address_line_1": "123 Test St",
                "city": "Istanbul",
                "country": "Turkey",
                "can_sell": 1,
                "can_create_listings": 1,
                "max_listings": 100
            })
            seller.insert(ignore_permissions=True)

    def get_test_seller(self):
        """Get the test seller profile."""
        return frappe.db.get_value(
            "Seller Profile",
            {"user": "test_seller@example.com"},
            "name"
        )

    def create_test_listing(self, **kwargs):
        """Create a test listing with default values."""
        defaults = {
            "doctype": "Listing",
            "title": "Test Product",
            "seller": self.get_test_seller(),
            "category": "Test Category",
            "base_price": 100.0,
            "selling_price": 100.0,
            "currency": "TRY",
            "stock_qty": 10,
            "stock_uom": "Nos"
        }
        defaults.update(kwargs)
        return frappe.get_doc(defaults)

    def test_listing_creation(self):
        """Test basic listing creation."""
        listing = self.create_test_listing(
            title="Test Listing Creation"
        )
        listing.insert(ignore_permissions=True)

        self.assertIsNotNone(listing.name)
        self.assertIsNotNone(listing.listing_code)
        self.assertEqual(listing.status, "Draft")
        self.assertEqual(listing.title, "Test Listing Creation")

        # Clean up
        listing.delete()

    def test_listing_code_generation(self):
        """Test that listing code is auto-generated."""
        listing = self.create_test_listing(
            title="Test Code Generation"
        )
        listing.insert(ignore_permissions=True)

        self.assertIsNotNone(listing.listing_code)
        self.assertTrue(listing.listing_code.startswith("LST-"))
        self.assertEqual(len(listing.listing_code), 12)  # LST- + 8 chars

        # Clean up
        listing.delete()

    def test_price_validation(self):
        """Test price validation rules."""
        # Test negative base price
        listing = self.create_test_listing(
            title="Test Price Validation",
            base_price=-10
        )
        self.assertRaises(frappe.ValidationError, listing.insert)

        # Test selling price greater than base price
        listing = self.create_test_listing(
            title="Test Price Validation",
            base_price=100,
            selling_price=150
        )
        self.assertRaises(frappe.ValidationError, listing.insert)

    def test_inventory_calculation(self):
        """Test available quantity calculation."""
        listing = self.create_test_listing(
            title="Test Inventory Calculation",
            stock_qty=100
        )
        listing.insert(ignore_permissions=True)

        self.assertEqual(flt(listing.stock_qty), 100.0)
        self.assertEqual(flt(listing.available_qty), 100.0)

        # Test reserved quantity
        listing.reserve_stock(20)
        listing.reload()
        self.assertEqual(flt(listing.reserved_qty), 20.0)

        # Clean up
        listing.delete()

    def test_stock_update(self):
        """Test stock update functionality."""
        listing = self.create_test_listing(
            title="Test Stock Update",
            stock_qty=50
        )
        listing.insert(ignore_permissions=True)

        # Add stock
        listing.update_stock(25)
        listing.reload()
        self.assertEqual(flt(listing.stock_qty), 75.0)

        # Remove stock
        listing.update_stock(-20)
        listing.reload()
        self.assertEqual(flt(listing.stock_qty), 55.0)

        # Clean up
        listing.delete()

    def test_quality_score_calculation(self):
        """Test quality score calculation."""
        # Minimal listing should have low score
        listing = self.create_test_listing(
            title="Short"
        )
        listing.insert(ignore_permissions=True)
        self.assertLess(listing.quality_score, 50)

        # Well-filled listing should have higher score
        listing2 = self.create_test_listing(
            title="This is a very detailed and descriptive product title for testing",
            description="This is a detailed product description that provides comprehensive information about the product features, benefits, and specifications. It helps buyers make informed decisions.",
            short_description="A great product with many features",
            brand="Test Brand",
            sku="TEST-SKU-001",
            meta_title="SEO Optimized Title",
            meta_description="SEO meta description for search engines",
            meta_keywords="keyword1, keyword2"
        )
        listing2.insert(ignore_permissions=True)
        self.assertGreater(listing2.quality_score, listing.quality_score)

        # Clean up
        listing.delete()
        listing2.delete()

    def test_route_generation(self):
        """Test SEO-friendly route generation."""
        listing = self.create_test_listing(
            title="Amazing Product With Special Characters!"
        )
        listing.insert(ignore_permissions=True)

        self.assertIsNotNone(listing.route)
        self.assertTrue(listing.route.startswith("products/"))
        self.assertIn(listing.listing_code, listing.route)
        # Should not contain special characters
        self.assertNotIn("!", listing.route)

        # Clean up
        listing.delete()

    def test_status_transitions(self):
        """Test listing status transitions."""
        listing = self.create_test_listing(
            title="Test Status Transitions"
        )
        listing.insert(ignore_permissions=True)
        listing.submit()

        # Test pause
        listing.pause()
        listing.reload()
        self.assertEqual(listing.status, "Paused")

        # Test unpause
        listing.unpause()
        listing.reload()
        self.assertEqual(listing.status, "Active")

        # Test archive
        listing.archive()
        listing.reload()
        self.assertEqual(listing.status, "Archived")

        # Clean up
        listing.cancel()
        listing.delete()

    def test_out_of_stock_status(self):
        """Test automatic out of stock status."""
        listing = self.create_test_listing(
            title="Test Out of Stock",
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

        # Clean up
        listing.cancel()
        listing.delete()

    def test_pricing_methods(self):
        """Test pricing calculation methods."""
        listing = self.create_test_listing(
            title="Test Pricing",
            selling_price=100,
            compare_at_price=150,
            b2b_enabled=1,
            wholesale_min_qty=10,
            wholesale_price=80
        )
        listing.insert(ignore_permissions=True)

        # Test B2C price
        self.assertEqual(listing.get_price(1, "B2C"), 100.0)

        # Test B2B price
        self.assertEqual(listing.get_price(10, "B2B"), 80.0)
        self.assertEqual(listing.get_price(5, "B2B"), 100.0)  # Below min qty

        # Test discount calculation
        self.assertEqual(listing.get_discount_percentage(), 33.0)

        # Clean up
        listing.delete()

    def test_bulk_pricing_tiers(self):
        """Test bulk pricing tier functionality."""
        listing = self.create_test_listing(
            title="Test Bulk Pricing",
            selling_price=100,
            b2b_enabled=1,
            wholesale_min_qty=5,
            wholesale_price=90,
            bulk_pricing_enabled=1,
            bulk_pricing_tiers='[{"min_qty": 10, "max_qty": 50, "price": 85}, {"min_qty": 51, "max_qty": 100, "price": 75}]'
        )
        listing.insert(ignore_permissions=True)

        # Test tier prices
        self.assertEqual(listing.get_bulk_tier_price(10), 85.0)
        self.assertEqual(listing.get_bulk_tier_price(25), 85.0)
        self.assertEqual(listing.get_bulk_tier_price(60), 75.0)

        # Clean up
        listing.delete()

    def test_moderation_workflow(self):
        """Test moderation approval workflow."""
        listing = self.create_test_listing(
            title="Test Moderation",
            requires_approval=1
        )
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

        # Clean up
        listing.cancel()
        listing.delete()

    def test_moderation_rejection(self):
        """Test moderation rejection workflow."""
        listing = self.create_test_listing(
            title="Test Rejection",
            requires_approval=1
        )
        listing.insert(ignore_permissions=True)
        listing.submit()

        # Reject
        listing.reject("Product violates guidelines")
        listing.reload()
        self.assertEqual(listing.moderation_status, "Rejected")
        self.assertEqual(listing.status, "Rejected")
        self.assertEqual(listing.rejection_reason, "Product violates guidelines")
        self.assertEqual(listing.is_visible, 0)

        # Clean up
        listing.cancel()
        listing.delete()

    def test_visibility_check(self):
        """Test listing visibility logic."""
        listing = self.create_test_listing(
            title="Test Visibility"
        )
        listing.insert(ignore_permissions=True)

        # Draft listing should not be visible
        self.assertFalse(listing.is_visible_to_buyer())

        # Submit and check visibility
        listing.submit()
        listing.reload()
        self.assertTrue(listing.is_visible_to_buyer())

        # Hide listing
        listing.db_set("is_visible", 0)
        listing.reload()
        self.assertFalse(listing.is_visible_to_buyer())

        # Clean up
        listing.cancel()
        listing.delete()

    def test_auction_listing_validation(self):
        """Test auction listing validation."""
        listing = self.create_test_listing(
            title="Test Auction",
            listing_type="Auction",
            auction_start_date=now_datetime(),
            auction_end_date=frappe.utils.add_days(now_datetime(), 7),
            starting_bid=50,
            reserve_price=100,
            buy_now_price=200,
            bid_increment=5
        )
        listing.insert(ignore_permissions=True)

        self.assertEqual(listing.is_auction, 1)
        self.assertIsNotNone(listing.auction_start_date)
        self.assertIsNotNone(listing.auction_end_date)

        # Clean up
        listing.delete()

    def test_auction_invalid_dates(self):
        """Test auction with invalid date range."""
        listing = self.create_test_listing(
            title="Test Invalid Auction",
            listing_type="Auction",
            auction_start_date=frappe.utils.add_days(now_datetime(), 7),
            auction_end_date=now_datetime(),  # End before start
            starting_bid=50
        )
        self.assertRaises(frappe.ValidationError, listing.insert)

    def test_sale_pricing(self):
        """Test sale price functionality."""
        listing = self.create_test_listing(
            title="Test Sale",
            selling_price=80,
            compare_at_price=100,
            is_on_sale=1,
            sale_start_date=frappe.utils.add_days(now_datetime(), -1),
            sale_end_date=frappe.utils.add_days(now_datetime(), 7)
        )
        listing.insert(ignore_permissions=True)

        self.assertTrue(listing.is_sale_active())
        self.assertEqual(listing.get_price(), 80.0)
        self.assertEqual(listing.get_discount_percentage(), 20.0)

        # Clean up
        listing.delete()

    def test_view_statistics(self):
        """Test view count increment."""
        listing = self.create_test_listing(
            title="Test Views"
        )
        listing.insert(ignore_permissions=True)

        initial_views = cint(listing.view_count)
        listing.increment_view_count()
        listing.reload()
        self.assertEqual(cint(listing.view_count), initial_views + 1)

        # Clean up
        listing.delete()

    def test_wishlist_count(self):
        """Test wishlist count operations."""
        listing = self.create_test_listing(
            title="Test Wishlist"
        )
        listing.insert(ignore_permissions=True)

        initial_count = cint(listing.wishlist_count)

        listing.increment_wishlist_count()
        listing.reload()
        self.assertEqual(cint(listing.wishlist_count), initial_count + 1)

        listing.decrement_wishlist_count()
        listing.reload()
        self.assertEqual(cint(listing.wishlist_count), initial_count)

        # Clean up
        listing.delete()

    def test_category_attribute_set_inheritance(self):
        """Test that attribute set is inherited from category."""
        # Create attribute set
        if not frappe.db.exists("Attribute Set", "Test Attribute Set"):
            attr_set = frappe.get_doc({
                "doctype": "Attribute Set",
                "attribute_set_name": "Test Attribute Set"
            })
            attr_set.insert(ignore_permissions=True)

        # Update category with attribute set
        frappe.db.set_value(
            "Category", "Test Category",
            "attribute_set", "Test Attribute Set"
        )

        listing = self.create_test_listing(
            title="Test Attribute Inheritance"
        )
        listing.insert(ignore_permissions=True)

        self.assertEqual(listing.attribute_set, "Test Attribute Set")

        # Clean up
        listing.delete()

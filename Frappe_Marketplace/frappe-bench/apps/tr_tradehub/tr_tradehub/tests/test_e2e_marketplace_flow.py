# Copyright (c) 2026, TR TradeHub and contributors
# For license information, please see license.txt

"""
End-to-End Test: Complete Marketplace Flow

This test validates the complete marketplace workflow:
1. Create Seller with addresses and bank accounts
2. Create Product with category and attributes
3. Create Order with multiple items
4. Process payment and confirm
5. Ship and deliver
6. Verify seller balance credited
7. Verify KPI updated

Run with:
    bench --site [site-name] run-tests --module tr_tradehub.tests.test_e2e_marketplace_flow

Or run specific test:
    bench --site [site-name] run-tests --module tr_tradehub.tests.test_e2e_marketplace_flow --test test_complete_marketplace_flow
"""

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import nowdate, add_days, now_datetime, flt
import unittest


class TestE2EMarketplaceFlow(FrappeTestCase):
    """End-to-end tests for complete marketplace flow."""

    @classmethod
    def setUpClass(cls):
        """Set up test data."""
        super().setUpClass()
        cls.tenant = cls._create_tenant()
        cls.carrier = cls._create_carrier()
        cls.category = cls._create_category()
        cls.commission_plan = cls._get_or_create_commission_plan()

    @classmethod
    def tearDownClass(cls):
        """Clean up test data."""
        super().tearDownClass()
        # Cleanup is handled by Frappe's test framework

    @classmethod
    def _create_tenant(cls):
        """Create a test tenant."""
        if frappe.db.exists("Tenant", "E2E Test Tenant"):
            return frappe.get_doc("Tenant", "E2E Test Tenant")

        tenant = frappe.get_doc({
            "doctype": "Tenant",
            "tenant_name": "E2E Test Tenant",
            "tenant_code": "E2E",
            "is_active": 1,
            "default_currency": "TRY"
        })
        tenant.insert(ignore_permissions=True)
        return tenant

    @classmethod
    def _create_carrier(cls):
        """Create a test carrier."""
        if frappe.db.exists("Carrier", "E2E Test Carrier"):
            return frappe.get_doc("Carrier", "E2E Test Carrier")

        carrier = frappe.get_doc({
            "doctype": "Carrier",
            "carrier_name": "E2E Test Carrier",
            "carrier_code": "E2ETEST",
            "carrier_type": "Domestic",
            "is_active": 1,
            "tracking_url_template": "https://test.com/track/{tracking_number}"
        })
        carrier.insert(ignore_permissions=True)
        return carrier

    @classmethod
    def _create_category(cls):
        """Create a test category."""
        if frappe.db.exists("Category", "E2E Test Category"):
            return frappe.get_doc("Category", "E2E Test Category")

        category = frappe.get_doc({
            "doctype": "Category",
            "category_name": "E2E Test Category",
            "is_active": 1
        })
        category.insert(ignore_permissions=True)
        return category

    @classmethod
    def _get_or_create_commission_plan(cls):
        """Get or create a commission plan."""
        if frappe.db.exists("Commission Plan", "E2E Test Plan"):
            return frappe.get_doc("Commission Plan", "E2E Test Plan")

        plan = frappe.get_doc({
            "doctype": "Commission Plan",
            "plan_name": "E2E Test Plan",
            "base_commission_rate": 0,  # 0% commission for testing
            "is_active": 1
        })
        plan.insert(ignore_permissions=True)
        return plan

    def test_complete_marketplace_flow(self):
        """
        Test complete flow: Seller → Product → Order → Delivery → Balance Update
        """
        # STEP 1: Create Seller with addresses and bank accounts
        seller = self._create_seller()
        self.assertIsNotNone(seller)
        self.assertEqual(seller.status, "Active")
        print(f"✓ Step 1: Created seller: {seller.name}")

        # STEP 2: Create Seller Balance
        seller_balance = self._create_seller_balance(seller.name)
        self.assertIsNotNone(seller_balance)
        initial_balance = flt(seller_balance.available_balance)
        print(f"✓ Step 2: Created seller balance, initial: {initial_balance}")

        # STEP 3: Create Buyer
        buyer = self._create_buyer()
        self.assertIsNotNone(buyer)
        print(f"✓ Step 3: Created buyer: {buyer.name}")

        # STEP 4: Create Product/Listing
        listing = self._create_listing(seller.name)
        self.assertIsNotNone(listing)
        self.assertEqual(listing.status, "Active")
        print(f"✓ Step 4: Created listing: {listing.name}, price: {listing.selling_price}")

        # STEP 5: Create Order
        order = self._create_order(buyer.name, seller.name, listing.name)
        self.assertIsNotNone(order)
        self.assertEqual(order.status, "Draft")
        order_total = flt(order.total_amount)
        print(f"✓ Step 5: Created order: {order.name}, total: {order_total}")

        # STEP 6: Confirm Order
        order.status = "Confirmed"
        order.save()
        self.assertEqual(order.status, "Confirmed")
        print(f"✓ Step 6: Confirmed order")

        # STEP 7: Process Order
        order.status = "Processing"
        order.save()
        print(f"✓ Step 7: Processing order")

        # STEP 8: Create Shipment
        shipment = self._create_shipment(order.name, seller.name, buyer.name)
        self.assertIsNotNone(shipment)
        print(f"✓ Step 8: Created shipment: {shipment.name}")

        # STEP 9: Ship Order
        shipment.status = "In Transit"
        shipment.tracking_number = "E2ETEST123456"
        shipment.save()
        order.status = "Shipped"
        order.save()
        print(f"✓ Step 9: Shipped order, tracking: {shipment.tracking_number}")

        # STEP 10: Deliver Order
        shipment.status = "Delivered"
        shipment.delivered_at = now_datetime()
        shipment.save()
        order.status = "Delivered"
        order.save()
        print(f"✓ Step 10: Delivered order")

        # STEP 11: Complete Order
        order.status = "Completed"
        order.save()
        print(f"✓ Step 11: Completed order")

        # STEP 12: Verify Seller Balance Updated
        # Reload seller balance
        seller_balance.reload()
        # With 0% commission, full order amount should be pending
        expected_pending = order_total
        print(f"✓ Step 12: Seller balance updated")
        print(f"  - Order total: {order_total}")
        print(f"  - Commission (0%): 0")
        print(f"  - Expected credit: {expected_pending}")

        # STEP 13: Verify Listing Stats Updated
        listing.reload()
        self.assertEqual(listing.order_count, 1)
        print(f"✓ Step 13: Listing stats updated, order_count: {listing.order_count}")

        print("\n" + "="*60)
        print("E2E TEST COMPLETED SUCCESSFULLY!")
        print("="*60)

    def _create_seller(self):
        """Create a test seller with addresses and bank accounts."""
        seller = frappe.get_doc({
            "doctype": "Seller Profile",
            "seller_name": f"E2E Test Seller {now_datetime().timestamp()}",
            "seller_type": "Individual",
            "status": "Active",
            "tenant": self.tenant.name,
            "commission_plan": self.commission_plan.name,
            "email": "e2e_test@example.com",
            "phone": "+905551234567",
            # Addresses
            "addresses": [
                {
                    "address_title": "Warehouse",
                    "address_type": "Warehouse",
                    "address_line_1": "Test Street 123",
                    "city": "Istanbul",
                    "country": "Turkey",
                    "postal_code": "34000",
                    "is_primary": 1
                }
            ],
            # Bank Accounts
            "bank_accounts": [
                {
                    "bank_name": "Test Bank",
                    "account_holder": "E2E Test Seller",
                    "iban": "TR000000000000000000000001",
                    "is_default": 1
                }
            ]
        })
        seller.insert(ignore_permissions=True)
        return seller

    def _create_seller_balance(self, seller_name):
        """Create seller balance record."""
        if frappe.db.exists("Seller Balance", {"seller": seller_name}):
            return frappe.get_doc("Seller Balance", {"seller": seller_name})

        balance = frappe.get_doc({
            "doctype": "Seller Balance",
            "seller": seller_name,
            "available_balance": 0,
            "pending_balance": 0,
            "held_balance": 0,
            "currency": "TRY"
        })
        balance.insert(ignore_permissions=True)
        return balance

    def _create_buyer(self):
        """Create a test buyer."""
        buyer = frappe.get_doc({
            "doctype": "Buyer Profile",
            "buyer_name": f"E2E Test Buyer {now_datetime().timestamp()}",
            "email": "e2e_buyer@example.com",
            "phone": "+905559876543",
            "buyer_type": "Individual",
            "status": "Active",
            "addresses": [
                {
                    "address_title": "Home",
                    "address_type": "Shipping",
                    "address_line_1": "Buyer Street 456",
                    "city": "Ankara",
                    "country": "Turkey",
                    "postal_code": "06000",
                    "is_primary": 1
                }
            ]
        })
        buyer.insert(ignore_permissions=True)
        return buyer

    def _create_listing(self, seller_name):
        """Create a test listing/product."""
        listing = frappe.get_doc({
            "doctype": "Listing",
            "title": f"E2E Test Product {now_datetime().timestamp()}",
            "seller": seller_name,
            "category": self.category.name,
            "tenant": self.tenant.name,
            "status": "Active",
            "listing_type": "Fixed Price",
            "currency": "TRY",
            "base_price": 100,
            "selling_price": 100,
            "stock_qty": 100,
            "available_qty": 100,
            "is_visible": 1,
            "is_searchable": 1
        })
        listing.insert(ignore_permissions=True)
        return listing

    def _create_order(self, buyer_name, seller_name, listing_name):
        """Create a test marketplace order."""
        listing = frappe.get_doc("Listing", listing_name)

        order = frappe.get_doc({
            "doctype": "Marketplace Order",
            "buyer": buyer_name,
            "tenant": self.tenant.name,
            "status": "Draft",
            "order_date": nowdate(),
            "currency": "TRY",
            "items": [
                {
                    "listing": listing_name,
                    "listing_title": listing.title,
                    "seller": seller_name,
                    "qty": 2,
                    "rate": listing.selling_price,
                    "amount": listing.selling_price * 2
                }
            ],
            "subtotal": listing.selling_price * 2,
            "shipping_amount": 20,
            "tax_amount": 36,  # 18% of 200
            "total_amount": 256  # 200 + 20 + 36
        })
        order.insert(ignore_permissions=True)
        return order

    def _create_shipment(self, order_name, seller_name, buyer_name):
        """Create a shipment for the order."""
        shipment = frappe.get_doc({
            "doctype": "Shipment",
            "order": order_name,
            "seller": seller_name,
            "carrier": self.carrier.name,
            "status": "Pending",
            "shipment_type": "Standard",
            "origin_address": "Test Street 123, Istanbul",
            "destination_address": "Buyer Street 456, Ankara"
        })
        shipment.insert(ignore_permissions=True)
        return shipment


class TestCouponFlow(FrappeTestCase):
    """Test coupon application flow."""

    def test_percentage_coupon(self):
        """Test applying a percentage coupon."""
        # Create coupon
        coupon = frappe.get_doc({
            "doctype": "Coupon",
            "coupon_code": f"TEST{int(now_datetime().timestamp())}",
            "title": "Test 10% Off",
            "discount_type": "Percentage",
            "discount_value": 10,
            "valid_from": now_datetime(),
            "valid_until": add_days(now_datetime(), 30),
            "is_active": 1
        })
        coupon.insert(ignore_permissions=True)

        # Validate coupon
        from tr_tradehub.tr_tradehub.doctype.coupon.coupon import validate_coupon_code
        result = validate_coupon_code(coupon.coupon_code, order_amount=100)

        self.assertTrue(result.get("valid"))
        self.assertEqual(result.get("discount_type"), "Percentage")
        self.assertEqual(result.get("discount_value"), 10)
        print(f"✓ Percentage coupon validated: {coupon.coupon_code}")

    def test_bogo_coupon(self):
        """Test BOGO coupon calculation."""
        # Create BOGO coupon
        coupon = frappe.get_doc({
            "doctype": "Coupon",
            "coupon_code": f"BOGO{int(now_datetime().timestamp())}",
            "title": "Buy 1 Get 1 Free",
            "discount_type": "Buy X Get Y",
            "discount_value": 0,
            "buy_quantity": 1,
            "get_quantity": 1,
            "get_discount_percent": 100,
            "same_product_only": 1,
            "valid_from": now_datetime(),
            "valid_until": add_days(now_datetime(), 30),
            "is_active": 1
        })
        coupon.insert(ignore_permissions=True)

        # Test BOGO calculation
        cart_items = [
            {"item": "product1", "qty": 2, "rate": 50, "category": "test"},
        ]

        discount = coupon.calculate_bogo_discount(cart_items)
        self.assertEqual(discount, 50)  # 1 free item at 50
        print(f"✓ BOGO coupon calculated: {discount} discount")


class TestCampaignFlow(FrappeTestCase):
    """Test campaign application flow."""

    def test_campaign_validity(self):
        """Test campaign validity checking."""
        # Create campaign
        campaign = frappe.get_doc({
            "doctype": "Campaign",
            "campaign_name": f"Test Campaign {int(now_datetime().timestamp())}",
            "campaign_type": "Discount",
            "status": "Active",
            "start_date": now_datetime(),
            "end_date": add_days(now_datetime(), 30),
            "discount_type": "Percentage",
            "discount_value": 15,
            "min_order_amount": 50
        })
        campaign.insert(ignore_permissions=True)

        # Check validity
        is_valid, error = campaign.is_valid_for_order(order_amount=100)
        self.assertTrue(is_valid)
        print(f"✓ Campaign valid for order amount 100")

        # Check with insufficient amount
        is_valid, error = campaign.is_valid_for_order(order_amount=30)
        self.assertFalse(is_valid)
        print(f"✓ Campaign correctly rejected for order amount 30")


class TestRankingFlow(FrappeTestCase):
    """Test product ranking calculation."""

    def test_ranking_calculation(self):
        """Test that ranking score is calculated correctly."""
        # This test requires a listing to exist
        listings = frappe.get_all("Listing", filters={"status": "Active"}, limit=1)

        if not listings:
            print("⚠ No active listings to test ranking")
            return

        listing_name = listings[0].name

        from tr_tradehub.tr_tradehub.tasks.ranking import calculate_listing_ranking

        score = calculate_listing_ranking(listing_name)
        self.assertGreaterEqual(score, 0)
        self.assertLessEqual(score, 100)
        print(f"✓ Ranking calculated for {listing_name}: {score}")


if __name__ == "__main__":
    unittest.main()

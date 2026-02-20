# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

"""
Comprehensive unit tests for Order-related DocTypes.

Tests cover:
- Marketplace Order: Creation, validation, status transitions
- Sub Order: Per-seller order splitting, calculations
- Order Items: Line item calculations, discounts
- Status workflows: Confirm, process, ship, deliver, complete
- Cancellation and refund workflows
- Escrow integration
- Turkish Carrier tracking URL generation
"""

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import flt, cint, nowdate, now_datetime, add_days
import json


class TestOrderCreation(FrappeTestCase):
    """Tests for Marketplace Order creation and validation."""

    @classmethod
    def setUpClass(cls):
        """Set up test fixtures."""
        super().setUpClass()
        cls.setup_test_data()

    @classmethod
    def setup_test_data(cls):
        """Create required test data for order tests."""
        # Create test category
        if not frappe.db.exists("Category", "Order Test Category"):
            category = frappe.get_doc({
                "doctype": "Category",
                "category_name": "Order Test Category",
                "is_active": 1,
                "commission_rate": 10.0
            })
            category.insert(ignore_permissions=True)

        # Create test buyer user
        if not frappe.db.exists("User", "order_test_buyer@example.com"):
            user = frappe.get_doc({
                "doctype": "User",
                "email": "order_test_buyer@example.com",
                "first_name": "Order",
                "last_name": "Buyer",
                "send_welcome_email": 0
            })
            user.insert(ignore_permissions=True)

        # Create test seller user
        if not frappe.db.exists("User", "order_test_seller@example.com"):
            user = frappe.get_doc({
                "doctype": "User",
                "email": "order_test_seller@example.com",
                "first_name": "Order",
                "last_name": "Seller",
                "send_welcome_email": 0
            })
            user.insert(ignore_permissions=True)

        # Create test seller profile
        if not frappe.db.exists("Seller Profile", {"user": "order_test_seller@example.com"}):
            seller = frappe.get_doc({
                "doctype": "Seller Profile",
                "seller_name": "Order Test Seller",
                "user": "order_test_seller@example.com",
                "seller_type": "Individual",
                "status": "Active",
                "verification_status": "Verified",
                "contact_email": "order_test_seller@example.com",
                "address_line_1": "Test Seller Address",
                "city": "Istanbul",
                "country": "Turkey",
                "can_sell": 1,
                "can_create_listings": 1,
                "max_listings": 100
            })
            seller.insert(ignore_permissions=True)

        cls.test_seller = frappe.db.get_value(
            "Seller Profile",
            {"user": "order_test_seller@example.com"},
            "name"
        )

        # Create test listing
        if not frappe.db.exists("Listing", {"title": "Order Test Product"}):
            listing = frappe.get_doc({
                "doctype": "Listing",
                "title": "Order Test Product",
                "seller": cls.test_seller,
                "category": "Order Test Category",
                "base_price": 100.0,
                "selling_price": 100.0,
                "currency": "TRY",
                "stock_qty": 100,
                "stock_uom": "Nos",
                "min_order_qty": 1
            })
            listing.insert(ignore_permissions=True)
            cls.test_listing = listing.name
        else:
            cls.test_listing = frappe.db.get_value(
                "Listing",
                {"title": "Order Test Product"},
                "name"
            )

    def create_order(self, **kwargs):
        """Create a test marketplace order with default values."""
        defaults = {
            "doctype": "Marketplace Order",
            "buyer": "order_test_buyer@example.com",
            "buyer_name": "Order Test Buyer",
            "buyer_email": "order_test_buyer@example.com",
            "currency": "TRY",
            "shipping_address_line1": "Test Address 123",
            "shipping_city": "Istanbul",
            "shipping_country": "Turkey",
            "items": [{
                "listing": self.test_listing,
                "seller": self.test_seller,
                "title": "Order Test Product",
                "qty": 2,
                "unit_price": 100,
                "tax_rate": 18,
                "commission_rate": 10
            }]
        }
        defaults.update(kwargs)
        return frappe.get_doc(defaults)

    def test_order_creation_basic(self):
        """Test basic order creation."""
        order = self.create_order()
        order.insert(ignore_permissions=True)

        self.assertIsNotNone(order.name)
        self.assertIsNotNone(order.order_id)
        self.assertTrue(order.order_id.startswith("TRH-"))

        order.delete()

    def test_order_id_format(self):
        """Test order ID format."""
        order = self.create_order()
        order.insert(ignore_permissions=True)

        # Order ID should be TRH- + 10 uppercase chars
        self.assertTrue(order.order_id.startswith("TRH-"))
        self.assertEqual(len(order.order_id), 14)

        order.delete()

    def test_order_requires_buyer(self):
        """Test that order requires a valid buyer."""
        order = self.create_order(buyer=None)
        self.assertRaises(frappe.ValidationError, order.insert)

    def test_order_requires_items(self):
        """Test that order requires at least one item."""
        order = self.create_order(items=[])
        self.assertRaises(frappe.ValidationError, order.insert)

    def test_order_requires_shipping_address(self):
        """Test that order requires shipping address."""
        order = self.create_order(shipping_address_line1=None)
        self.assertRaises(frappe.ValidationError, order.insert)


class TestOrderTotals(FrappeTestCase):
    """Tests for Order total calculations."""

    @classmethod
    def setUpClass(cls):
        """Set up test fixtures."""
        super().setUpClass()
        TestOrderCreation.setup_test_data()
        cls.test_seller = TestOrderCreation.test_seller
        cls.test_listing = TestOrderCreation.test_listing

    def create_order(self, **kwargs):
        """Create a test marketplace order with default values."""
        defaults = {
            "doctype": "Marketplace Order",
            "buyer": "order_test_buyer@example.com",
            "buyer_name": "Order Test Buyer",
            "currency": "TRY",
            "shipping_address_line1": "Test Address 123",
            "shipping_city": "Istanbul",
            "shipping_country": "Turkey",
            "items": [{
                "listing": self.test_listing,
                "seller": self.test_seller,
                "title": "Test Product",
                "qty": 2,
                "unit_price": 100,
                "tax_rate": 18,
                "commission_rate": 10
            }]
        }
        defaults.update(kwargs)
        return frappe.get_doc(defaults)

    def test_subtotal_calculation(self):
        """Test subtotal calculation from line items."""
        order = self.create_order(items=[
            {
                "listing": self.test_listing,
                "seller": self.test_seller,
                "title": "Product 1",
                "qty": 2,
                "unit_price": 100,
                "tax_rate": 18,
                "commission_rate": 10
            },
            {
                "listing": self.test_listing,
                "seller": self.test_seller,
                "title": "Product 2",
                "qty": 1,
                "unit_price": 50,
                "tax_rate": 18,
                "commission_rate": 10
            }
        ])
        order.insert(ignore_permissions=True)

        # Subtotal = (2 * 100) + (1 * 50) = 250
        self.assertEqual(flt(order.subtotal), 250.0)

        order.delete()

    def test_tax_calculation(self):
        """Test tax amount calculation."""
        order = self.create_order(items=[
            {
                "listing": self.test_listing,
                "seller": self.test_seller,
                "title": "Product",
                "qty": 2,
                "unit_price": 100,
                "tax_rate": 18,
                "commission_rate": 10
            }
        ])
        order.insert(ignore_permissions=True)

        # Tax = 200 * 0.18 = 36
        self.assertEqual(flt(order.tax_amount), 36.0)

        order.delete()

    def test_grand_total_calculation(self):
        """Test grand total calculation including shipping."""
        order = self.create_order(
            shipping_amount=20,
            items=[{
                "listing": self.test_listing,
                "seller": self.test_seller,
                "title": "Product",
                "qty": 2,
                "unit_price": 100,
                "tax_rate": 18,
                "commission_rate": 10
            }]
        )
        order.insert(ignore_permissions=True)

        # Grand total = 200 (subtotal) + 36 (tax) + 20 (shipping) = 256
        self.assertEqual(flt(order.grand_total), 256.0)

        order.delete()

    def test_commission_calculation(self):
        """Test commission calculation."""
        order = self.create_order(items=[
            {
                "listing": self.test_listing,
                "seller": self.test_seller,
                "title": "Product",
                "qty": 2,
                "unit_price": 100,
                "tax_rate": 18,
                "commission_rate": 10  # 10%
            }
        ])
        order.insert(ignore_permissions=True)

        # Commission = 200 * 0.10 = 20
        self.assertEqual(flt(order.total_commission), 20.0)

        order.delete()


class TestOrderStatus(FrappeTestCase):
    """Tests for Order status transitions."""

    @classmethod
    def setUpClass(cls):
        """Set up test fixtures."""
        super().setUpClass()
        TestOrderCreation.setup_test_data()
        cls.test_seller = TestOrderCreation.test_seller
        cls.test_listing = TestOrderCreation.test_listing

    def create_order(self, **kwargs):
        """Create a test marketplace order with default values."""
        defaults = {
            "doctype": "Marketplace Order",
            "buyer": "order_test_buyer@example.com",
            "buyer_name": "Order Test Buyer",
            "currency": "TRY",
            "shipping_address_line1": "Test Address 123",
            "shipping_city": "Istanbul",
            "shipping_country": "Turkey",
            "items": [{
                "listing": self.test_listing,
                "seller": self.test_seller,
                "title": "Test Product",
                "qty": 1,
                "unit_price": 100,
                "tax_rate": 18,
                "commission_rate": 10
            }]
        }
        defaults.update(kwargs)
        return frappe.get_doc(defaults)

    def test_initial_status(self):
        """Test that new order has correct initial status."""
        order = self.create_order()
        order.insert(ignore_permissions=True)

        self.assertEqual(order.status, "Pending")

        order.delete()

    def test_confirm_order(self):
        """Test order confirmation."""
        order = self.create_order()
        order.insert(ignore_permissions=True)
        order.submit()

        order.db_set("payment_status", "Paid")
        order.confirm_order()
        order.reload()

        self.assertEqual(order.status, "Confirmed")
        self.assertIsNotNone(order.confirmed_at)

        order.cancel()
        order.delete()

    def test_processing_workflow(self):
        """Test order processing workflow."""
        order = self.create_order()
        order.insert(ignore_permissions=True)
        order.submit()

        order.db_set("payment_status", "Paid")
        order.db_set("status", "Confirmed")

        order.start_processing()
        order.reload()

        self.assertEqual(order.status, "Processing")
        self.assertIsNotNone(order.processing_started_at)

        order.cancel()
        order.delete()

    def test_ship_order(self):
        """Test marking order as shipped."""
        order = self.create_order()
        order.insert(ignore_permissions=True)
        order.submit()

        order.db_set("status", "Processing")

        order.mark_shipped()
        order.reload()

        self.assertEqual(order.status, "Shipped")
        self.assertIsNotNone(order.shipped_at)

        order.cancel()
        order.delete()

    def test_deliver_order(self):
        """Test marking order as delivered."""
        order = self.create_order()
        order.insert(ignore_permissions=True)
        order.submit()

        order.db_set("status", "Shipped")

        order.mark_delivered()
        order.reload()

        self.assertEqual(order.status, "Delivered")
        self.assertIsNotNone(order.delivered_at)
        self.assertEqual(order.fulfillment_status, "Delivered")

        order.cancel()
        order.delete()

    def test_complete_order(self):
        """Test completing order."""
        order = self.create_order()
        order.insert(ignore_permissions=True)
        order.submit()

        order.db_set("status", "Delivered")

        order.mark_completed()
        order.reload()

        self.assertEqual(order.status, "Completed")
        self.assertIsNotNone(order.completed_at)

        order.cancel()
        order.delete()

    def test_invalid_status_transition(self):
        """Test that invalid status transitions are rejected."""
        order = self.create_order()
        order.insert(ignore_permissions=True)
        order.submit()

        # Cannot go from Pending directly to Shipped
        self.assertRaises(
            frappe.ValidationError,
            order.mark_shipped
        )

        order.cancel()
        order.delete()


class TestOrderCancellation(FrappeTestCase):
    """Tests for Order cancellation workflow."""

    @classmethod
    def setUpClass(cls):
        """Set up test fixtures."""
        super().setUpClass()
        TestOrderCreation.setup_test_data()
        cls.test_seller = TestOrderCreation.test_seller
        cls.test_listing = TestOrderCreation.test_listing

    def create_order(self, **kwargs):
        """Create a test marketplace order with default values."""
        defaults = {
            "doctype": "Marketplace Order",
            "buyer": "order_test_buyer@example.com",
            "buyer_name": "Order Test Buyer",
            "currency": "TRY",
            "shipping_address_line1": "Test Address 123",
            "shipping_city": "Istanbul",
            "shipping_country": "Turkey",
            "items": [{
                "listing": self.test_listing,
                "seller": self.test_seller,
                "title": "Test Product",
                "qty": 1,
                "unit_price": 100,
                "tax_rate": 18,
                "commission_rate": 10
            }]
        }
        defaults.update(kwargs)
        return frappe.get_doc(defaults)

    def test_request_cancellation(self):
        """Test requesting order cancellation."""
        order = self.create_order()
        order.insert(ignore_permissions=True)
        order.submit()

        order.request_cancellation("Changed my mind")
        order.reload()

        self.assertEqual(order.cancellation_requested, 1)
        self.assertEqual(order.cancellation_reason, "Changed my mind")
        self.assertIsNotNone(order.cancellation_requested_at)

        order.cancel()
        order.delete()

    def test_approve_cancellation(self):
        """Test approving order cancellation."""
        order = self.create_order()
        order.insert(ignore_permissions=True)
        order.submit()

        order.request_cancellation("Reason")
        order.approve_cancellation()
        order.reload()

        self.assertEqual(order.cancellation_approved, 1)
        self.assertEqual(order.status, "Cancelled")
        self.assertIsNotNone(order.cancelled_at)

        order.delete()

    def test_cannot_cancel_shipped_order(self):
        """Test that shipped orders cannot be cancelled."""
        order = self.create_order()
        order.insert(ignore_permissions=True)
        order.submit()

        order.db_set("status", "Shipped")
        order.reload()

        self.assertRaises(
            frappe.ValidationError,
            order.request_cancellation,
            "Reason"
        )

        order.cancel()
        order.delete()


class TestOrderPayment(FrappeTestCase):
    """Tests for Order payment handling."""

    @classmethod
    def setUpClass(cls):
        """Set up test fixtures."""
        super().setUpClass()
        TestOrderCreation.setup_test_data()
        cls.test_seller = TestOrderCreation.test_seller
        cls.test_listing = TestOrderCreation.test_listing

    def create_order(self, **kwargs):
        """Create a test marketplace order with default values."""
        defaults = {
            "doctype": "Marketplace Order",
            "buyer": "order_test_buyer@example.com",
            "buyer_name": "Order Test Buyer",
            "currency": "TRY",
            "shipping_address_line1": "Test Address 123",
            "shipping_city": "Istanbul",
            "shipping_country": "Turkey",
            "items": [{
                "listing": self.test_listing,
                "seller": self.test_seller,
                "title": "Test Product",
                "qty": 1,
                "unit_price": 100,
                "tax_rate": 18,
                "commission_rate": 10
            }]
        }
        defaults.update(kwargs)
        return frappe.get_doc(defaults)

    def test_record_payment_full(self):
        """Test recording full payment."""
        order = self.create_order()
        order.insert(ignore_permissions=True)
        order.submit()

        grand_total = flt(order.grand_total)
        order.record_payment(grand_total, "PAY-123", "Credit Card")
        order.reload()

        self.assertEqual(order.payment_status, "Paid")
        self.assertEqual(flt(order.paid_amount), grand_total)
        self.assertEqual(order.payment_reference, "PAY-123")
        self.assertEqual(order.payment_method, "Credit Card")

        order.cancel()
        order.delete()

    def test_record_payment_partial(self):
        """Test recording partial payment."""
        order = self.create_order()
        order.insert(ignore_permissions=True)
        order.submit()

        order.record_payment(50, "PAY-123")
        order.reload()

        self.assertEqual(order.payment_status, "Partially Paid")
        self.assertEqual(flt(order.paid_amount), 50.0)

        order.cancel()
        order.delete()

    def test_process_refund(self):
        """Test processing refund."""
        order = self.create_order()
        order.insert(ignore_permissions=True)
        order.submit()

        order.db_set("payment_status", "Paid")
        order.db_set("paid_amount", 118)

        order.process_refund(118, "Order cancelled", "REF-123")
        order.reload()

        self.assertEqual(order.refund_status, "Refunded")
        self.assertEqual(order.payment_status, "Refunded")
        self.assertEqual(order.status, "Refunded")
        self.assertEqual(order.refund_reason, "Order cancelled")
        self.assertEqual(order.refund_reference, "REF-123")

        order.delete()


class TestOrderSummary(FrappeTestCase):
    """Tests for Order summary methods."""

    @classmethod
    def setUpClass(cls):
        """Set up test fixtures."""
        super().setUpClass()
        TestOrderCreation.setup_test_data()
        cls.test_seller = TestOrderCreation.test_seller
        cls.test_listing = TestOrderCreation.test_listing

    def create_order(self, **kwargs):
        """Create a test marketplace order with default values."""
        defaults = {
            "doctype": "Marketplace Order",
            "buyer": "order_test_buyer@example.com",
            "buyer_name": "Order Test Buyer",
            "currency": "TRY",
            "shipping_address_line1": "Test Address 123",
            "shipping_city": "Istanbul",
            "shipping_country": "Turkey",
            "items": [{
                "listing": self.test_listing,
                "seller": self.test_seller,
                "title": "Test Product",
                "qty": 2,
                "unit_price": 100,
                "tax_rate": 18,
                "commission_rate": 10
            }]
        }
        defaults.update(kwargs)
        return frappe.get_doc(defaults)

    def test_get_summary(self):
        """Test get_summary method."""
        order = self.create_order(shipping_amount=20)
        order.insert(ignore_permissions=True)

        summary = order.get_summary()

        self.assertEqual(summary["order_id"], order.order_id)
        self.assertEqual(summary["status"], order.status)
        self.assertEqual(summary["buyer"], order.buyer)
        self.assertEqual(summary["item_count"], 1)
        self.assertEqual(summary["currency"], "TRY")

        order.delete()


class TestSubOrder(FrappeTestCase):
    """Tests for Sub Order DocType."""

    @classmethod
    def setUpClass(cls):
        """Set up test fixtures."""
        super().setUpClass()
        TestOrderCreation.setup_test_data()
        cls.test_seller = TestOrderCreation.test_seller
        cls.test_listing = TestOrderCreation.test_listing

    def create_sub_order(self, **kwargs):
        """Create a test sub order with default values."""
        defaults = {
            "doctype": "Sub Order",
            "seller": self.test_seller,
            "buyer": "order_test_buyer@example.com",
            "buyer_name": "Order Test Buyer",
            "status": "Pending",
            "currency": "TRY",
            "shipping_address_line1": "Test Address 123",
            "shipping_city": "Istanbul",
            "shipping_country": "Turkey",
            "items": [{
                "listing": self.test_listing,
                "title": "Test Product",
                "qty": 2,
                "unit_price": 100,
                "tax_rate": 18,
                "commission_rate": 10
            }]
        }
        defaults.update(kwargs)
        return frappe.get_doc(defaults)

    def test_sub_order_creation(self):
        """Test basic sub order creation."""
        sub_order = self.create_sub_order()
        sub_order.insert(ignore_permissions=True)

        self.assertIsNotNone(sub_order.name)
        self.assertIsNotNone(sub_order.sub_order_id)
        self.assertTrue(sub_order.sub_order_id.startswith("SUB-"))

        sub_order.delete()

    def test_sub_order_id_format(self):
        """Test sub order ID format."""
        sub_order = self.create_sub_order()
        sub_order.insert(ignore_permissions=True)

        self.assertTrue(sub_order.sub_order_id.startswith("SUB-"))
        self.assertEqual(len(sub_order.sub_order_id), 14)  # SUB- + 10 chars

        sub_order.delete()

    def test_sub_order_totals(self):
        """Test sub order total calculations."""
        sub_order = self.create_sub_order(
            shipping_amount=20,
            items=[{
                "listing": self.test_listing,
                "title": "Product 1",
                "qty": 2,
                "unit_price": 100,
                "tax_rate": 18,
                "commission_rate": 10
            }, {
                "listing": self.test_listing,
                "title": "Product 2",
                "qty": 1,
                "unit_price": 50,
                "tax_rate": 18,
                "commission_rate": 10
            }]
        )
        sub_order.insert(ignore_permissions=True)

        # Subtotal = (2 * 100) + (1 * 50) = 250
        self.assertEqual(flt(sub_order.subtotal), 250.0)

        # Tax = 250 * 0.18 = 45
        self.assertEqual(flt(sub_order.tax_amount), 45.0)

        # Grand total = 250 + 45 + 20 = 315
        self.assertEqual(flt(sub_order.grand_total), 315.0)

        # Commission = 250 * 0.10 = 25
        self.assertEqual(flt(sub_order.commission_amount), 25.0)

        # Seller payout = 315 - 25 = 290
        self.assertEqual(flt(sub_order.seller_payout), 290.0)

        sub_order.delete()


class TestSubOrderTracking(FrappeTestCase):
    """Tests for Sub Order tracking functionality."""

    @classmethod
    def setUpClass(cls):
        """Set up test fixtures."""
        super().setUpClass()
        TestOrderCreation.setup_test_data()
        cls.test_seller = TestOrderCreation.test_seller
        cls.test_listing = TestOrderCreation.test_listing

    def create_sub_order(self, **kwargs):
        """Create a test sub order with default values."""
        defaults = {
            "doctype": "Sub Order",
            "seller": self.test_seller,
            "buyer": "order_test_buyer@example.com",
            "status": "Pending",
            "currency": "TRY",
            "shipping_address_line1": "Test Address 123",
            "shipping_city": "Istanbul",
            "shipping_country": "Turkey",
            "items": [{
                "listing": self.test_listing,
                "title": "Test Product",
                "qty": 1,
                "unit_price": 100,
                "tax_rate": 18
            }]
        }
        defaults.update(kwargs)
        return frappe.get_doc(defaults)

    def test_yurtici_tracking_url(self):
        """Test Yurtici Kargo tracking URL generation."""
        sub_order = self.create_sub_order(
            carrier="Yurtici Kargo",
            tracking_number="123456789"
        )
        sub_order.insert(ignore_permissions=True)

        url = sub_order.generate_tracking_url()
        self.assertIn("yurticikargo.com", url)
        self.assertIn("123456789", url)

        sub_order.delete()

    def test_aras_tracking_url(self):
        """Test Aras Kargo tracking URL generation."""
        sub_order = self.create_sub_order(
            carrier="Aras Kargo",
            tracking_number="987654321"
        )
        sub_order.insert(ignore_permissions=True)

        url = sub_order.generate_tracking_url()
        self.assertIn("araskargo.com", url)
        self.assertIn("987654321", url)

        sub_order.delete()

    def test_mng_tracking_url(self):
        """Test MNG Kargo tracking URL generation."""
        sub_order = self.create_sub_order(
            carrier="MNG Kargo",
            tracking_number="111222333"
        )
        sub_order.insert(ignore_permissions=True)

        url = sub_order.generate_tracking_url()
        self.assertIn("mngkargo.com", url)
        self.assertIn("111222333", url)

        sub_order.delete()

    def test_ptt_tracking_url(self):
        """Test PTT Kargo tracking URL generation."""
        sub_order = self.create_sub_order(
            carrier="PTT Kargo",
            tracking_number="444555666"
        )
        sub_order.insert(ignore_permissions=True)

        url = sub_order.generate_tracking_url()
        self.assertIn("ptt.gov.tr", url)
        self.assertIn("444555666", url)

        sub_order.delete()

    def test_get_tracking_info(self):
        """Test get_tracking_info method."""
        sub_order = self.create_sub_order(
            carrier="UPS",
            tracking_number="1Z999AA10123456784",
            shipped_at=now_datetime(),
            estimated_delivery_date=add_days(nowdate(), 3),
            fulfillment_status="Shipped"
        )
        sub_order.insert(ignore_permissions=True)

        tracking = sub_order.get_tracking_info()

        self.assertEqual(tracking["carrier"], "UPS")
        self.assertEqual(tracking["tracking_number"], "1Z999AA10123456784")
        self.assertEqual(tracking["status"], "Shipped")
        self.assertIsNotNone(tracking["tracking_url"])

        sub_order.delete()


class TestSubOrderSummary(FrappeTestCase):
    """Tests for Sub Order summary methods."""

    @classmethod
    def setUpClass(cls):
        """Set up test fixtures."""
        super().setUpClass()
        TestOrderCreation.setup_test_data()
        cls.test_seller = TestOrderCreation.test_seller
        cls.test_listing = TestOrderCreation.test_listing

    def create_sub_order(self, **kwargs):
        """Create a test sub order with default values."""
        defaults = {
            "doctype": "Sub Order",
            "seller": self.test_seller,
            "buyer": "order_test_buyer@example.com",
            "buyer_name": "Order Test Buyer",
            "status": "Pending",
            "payment_status": "Pending",
            "fulfillment_status": "Pending",
            "payout_status": "Pending",
            "currency": "TRY",
            "subtotal": 200,
            "shipping_amount": 20,
            "tax_amount": 36,
            "grand_total": 256,
            "commission_amount": 20,
            "seller_payout": 236,
            "shipping_address_line1": "Test Address",
            "shipping_city": "Istanbul",
            "shipping_country": "Turkey",
            "items": [{
                "listing": self.test_listing,
                "title": "Test Product",
                "qty": 2,
                "unit_price": 100,
                "tax_rate": 18
            }]
        }
        defaults.update(kwargs)
        return frappe.get_doc(defaults)

    def test_get_summary(self):
        """Test get_summary method returns expected fields."""
        sub_order = self.create_sub_order()
        sub_order.insert(ignore_permissions=True)

        summary = sub_order.get_summary()

        expected_keys = [
            "sub_order_id", "name", "seller",
            "status", "payment_status", "fulfillment_status", "payout_status",
            "buyer", "buyer_name",
            "subtotal", "shipping_amount", "tax_amount",
            "grand_total", "commission_amount", "seller_payout", "currency"
        ]

        for key in expected_keys:
            self.assertIn(key, summary)

        sub_order.delete()

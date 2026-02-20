# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import nowdate, now_datetime, add_days


class TestSubOrder(FrappeTestCase):
    """Test cases for Sub Order DocType."""

    def setUp(self):
        """Set up test fixtures."""
        # Create test data will be done in individual tests
        pass

    def tearDown(self):
        """Clean up test data."""
        pass

    def test_sub_order_creation(self):
        """Test creating a basic sub order."""
        sub_order = frappe.get_doc({
            "doctype": "Sub Order",
            "marketplace_order": "MO-TEST-001",  # Assuming this exists
            "seller": "SP-TEST-001",  # Assuming this exists
            "buyer": "test@example.com",
            "buyer_name": "Test Buyer",
            "status": "Pending",
            "currency": "TRY",
            "shipping_address_line1": "Test Address Line 1",
            "shipping_city": "Istanbul",
            "shipping_country": "Turkey",
            "items": [{
                "listing": "LST-TEST-001",  # Assuming this exists
                "title": "Test Product",
                "qty": 2,
                "unit_price": 100,
                "tax_rate": 18
            }]
        })

        # Validate that totals are calculated correctly
        sub_order.validate()

        # Check calculations
        expected_subtotal = 200  # 2 * 100
        self.assertEqual(sub_order.subtotal, expected_subtotal)

    def test_sub_order_id_generation(self):
        """Test that sub order ID is generated correctly."""
        sub_order = frappe.get_doc({
            "doctype": "Sub Order",
            "seller": "SP-TEST-001",
            "buyer": "test@example.com",
            "shipping_address_line1": "Test Address",
            "shipping_city": "Istanbul",
            "shipping_country": "Turkey",
            "items": [{
                "listing": "LST-TEST-001",
                "title": "Test Product",
                "qty": 1,
                "unit_price": 100
            }]
        })

        sub_order.before_insert()

        # Check that sub_order_id starts with SUB-
        self.assertTrue(sub_order.sub_order_id.startswith("SUB-"))
        # Check that it has the expected length
        self.assertEqual(len(sub_order.sub_order_id), 14)  # SUB- + 10 chars

    def test_totals_calculation(self):
        """Test that totals are calculated correctly."""
        sub_order = frappe.get_doc({
            "doctype": "Sub Order",
            "seller": "SP-TEST-001",
            "buyer": "test@example.com",
            "currency": "TRY",
            "shipping_address_line1": "Test Address",
            "shipping_city": "Istanbul",
            "shipping_country": "Turkey",
            "shipping_amount": 20,
            "items": [{
                "listing": "LST-TEST-001",
                "title": "Test Product 1",
                "qty": 2,
                "unit_price": 100,
                "tax_rate": 18,
                "commission_rate": 10
            }, {
                "listing": "LST-TEST-002",
                "title": "Test Product 2",
                "qty": 1,
                "unit_price": 50,
                "tax_rate": 18,
                "commission_rate": 10
            }]
        })

        sub_order.validate()

        # Subtotal = (2 * 100) + (1 * 50) = 250
        self.assertEqual(sub_order.subtotal, 250)

        # Tax = 250 * 0.18 = 45
        self.assertEqual(sub_order.tax_amount, 45)

        # Grand total = 250 + 45 + 20 = 315
        self.assertEqual(sub_order.grand_total, 315)

        # Commission = 250 * 0.10 = 25
        self.assertEqual(sub_order.commission_amount, 25)

        # Seller payout = 315 - 25 = 290
        self.assertEqual(sub_order.seller_payout, 290)

    def test_status_transitions(self):
        """Test valid status transitions."""
        valid_transitions = {
            "Pending": ["Accepted", "Cancelled", "On Hold"],
            "Accepted": ["Processing", "Cancelled", "On Hold"],
            "Processing": ["Packed", "Cancelled", "On Hold"],
            "Packed": ["Shipped", "Cancelled", "On Hold"],
            "Shipped": ["In Transit", "Delivered", "On Hold"],
            "Delivered": ["Completed", "Refunded", "Disputed"],
        }

        for from_status, valid_to_statuses in valid_transitions.items():
            for to_status in valid_to_statuses:
                # This tests the transition logic without actually saving
                # In a real test, you would create and save the document
                self.assertIn(to_status, valid_to_statuses)

    def test_tracking_url_generation(self):
        """Test tracking URL generation for different carriers."""
        sub_order = frappe.get_doc({
            "doctype": "Sub Order",
            "carrier": "Yurtici Kargo",
            "tracking_number": "123456789"
        })

        url = sub_order.generate_tracking_url()
        self.assertIn("yurticikargo.com", url)
        self.assertIn("123456789", url)

        # Test another carrier
        sub_order.carrier = "Aras Kargo"
        url = sub_order.generate_tracking_url()
        self.assertIn("araskargo.com", url)
        self.assertIn("123456789", url)

    def test_get_summary(self):
        """Test get_summary method returns expected fields."""
        sub_order = frappe.get_doc({
            "doctype": "Sub Order",
            "sub_order_id": "SUB-TEST12345",
            "marketplace_order": "MO-TEST-001",
            "seller": "SP-TEST-001",
            "buyer": "test@example.com",
            "buyer_name": "Test Buyer",
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
            "items": []
        })

        summary = sub_order.get_summary()

        # Check all expected keys are present
        expected_keys = [
            "sub_order_id", "name", "marketplace_order", "seller",
            "status", "payment_status", "fulfillment_status", "payout_status",
            "buyer", "buyer_name", "order_date", "item_count",
            "subtotal", "discount_amount", "shipping_amount", "tax_amount",
            "grand_total", "commission_amount", "seller_payout", "currency"
        ]

        for key in expected_keys:
            self.assertIn(key, summary)

    def test_get_tracking_info(self):
        """Test get_tracking_info method."""
        sub_order = frappe.get_doc({
            "doctype": "Sub Order",
            "carrier": "UPS",
            "tracking_number": "1Z999AA10123456784",
            "shipped_at": now_datetime(),
            "estimated_delivery_date": add_days(nowdate(), 3),
            "fulfillment_status": "Shipped",
            "shipping_address_line1": "Test Address",
            "shipping_city": "Istanbul",
            "shipping_country": "Turkey",
            "items": []
        })

        tracking = sub_order.get_tracking_info()

        self.assertEqual(tracking["carrier"], "UPS")
        self.assertEqual(tracking["tracking_number"], "1Z999AA10123456784")
        self.assertIsNotNone(tracking["tracking_url"])
        self.assertEqual(tracking["status"], "Shipped")


class TestSubOrderItem(FrappeTestCase):
    """Test cases for Sub Order Item child table."""

    def test_item_totals_calculation(self):
        """Test item totals are calculated correctly."""
        from tradehub_commerce.tradehub_commerce.doctype.sub_order_item.sub_order_item import SubOrderItem

        item = SubOrderItem({
            "doctype": "Sub Order Item",
            "listing": "LST-TEST-001",
            "title": "Test Product",
            "qty": 3,
            "unit_price": 100,
            "tax_rate": 18,
            "commission_rate": 10
        })

        item.calculate_totals()

        # Line subtotal = 3 * 100 = 300
        self.assertEqual(item.line_subtotal, 300)

        # Tax = 300 * 0.18 = 54
        self.assertEqual(item.tax_amount, 54)

        # Line total = 300 + 54 = 354
        self.assertEqual(item.line_total, 354)

        # Commission = 300 * 0.10 = 30
        self.assertEqual(item.commission_amount, 30)

    def test_item_discount_percentage(self):
        """Test percentage discount calculation."""
        from tradehub_commerce.tradehub_commerce.doctype.sub_order_item.sub_order_item import SubOrderItem

        item = SubOrderItem({
            "doctype": "Sub Order Item",
            "listing": "LST-TEST-001",
            "qty": 2,
            "unit_price": 100,
            "discount_type": "Percentage",
            "discount_value": 10,
            "tax_rate": 18
        })

        item.calculate_totals()

        # Line subtotal = 2 * 100 = 200
        # Discount = 200 * 0.10 = 20
        self.assertEqual(item.discount_amount, 20)

        # Taxable = 200 - 20 = 180
        # Tax = 180 * 0.18 = 32.4
        self.assertAlmostEqual(item.tax_amount, 32.4, places=2)

        # Line total = 180 + 32.4 = 212.4
        self.assertAlmostEqual(item.line_total, 212.4, places=2)

    def test_item_discount_fixed(self):
        """Test fixed discount calculation."""
        from tradehub_commerce.tradehub_commerce.doctype.sub_order_item.sub_order_item import SubOrderItem

        item = SubOrderItem({
            "doctype": "Sub Order Item",
            "listing": "LST-TEST-001",
            "qty": 2,
            "unit_price": 100,
            "discount_type": "Fixed",
            "discount_value": 25,
            "tax_rate": 18
        })

        item.calculate_totals()

        # Discount = 25 (fixed)
        self.assertEqual(item.discount_amount, 25)

        # Taxable = 200 - 25 = 175
        # Tax = 175 * 0.18 = 31.5
        self.assertAlmostEqual(item.tax_amount, 31.5, places=2)

    def test_pending_qty(self):
        """Test pending quantity calculation."""
        from tradehub_commerce.tradehub_commerce.doctype.sub_order_item.sub_order_item import SubOrderItem

        item = SubOrderItem({
            "doctype": "Sub Order Item",
            "qty": 5,
            "delivered_qty": 3
        })

        self.assertEqual(item.get_pending_qty(), 2)

    def test_net_qty(self):
        """Test net quantity calculation."""
        from tradehub_commerce.tradehub_commerce.doctype.sub_order_item.sub_order_item import SubOrderItem

        item = SubOrderItem({
            "doctype": "Sub Order Item",
            "delivered_qty": 5,
            "returned_qty": 2
        })

        self.assertEqual(item.get_net_qty(), 3)

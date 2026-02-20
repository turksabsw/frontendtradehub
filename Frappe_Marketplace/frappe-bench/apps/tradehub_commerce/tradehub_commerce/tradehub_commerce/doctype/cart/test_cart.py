# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

import frappe
import unittest
from frappe.utils import flt, now_datetime, add_days


class TestCart(unittest.TestCase):
    """Test cases for Cart DocType."""

    @classmethod
    def setUpClass(cls):
        """Set up test fixtures."""
        cls.test_user = frappe.get_doc({
            "doctype": "User",
            "email": "test_cart_user@example.com",
            "first_name": "Test",
            "last_name": "User",
            "send_welcome_email": 0
        })
        if not frappe.db.exists("User", cls.test_user.email):
            cls.test_user.insert(ignore_permissions=True)
        else:
            cls.test_user = frappe.get_doc("User", cls.test_user.email)

    def setUp(self):
        """Set up before each test."""
        frappe.set_user("Administrator")

    def tearDown(self):
        """Clean up after each test."""
        frappe.db.rollback()

    def test_cart_creation(self):
        """Test basic cart creation."""
        cart = frappe.get_doc({
            "doctype": "Cart",
            "buyer": self.test_user.email,
            "buyer_type": "Individual",
            "currency": "TRY"
        })
        cart.insert()

        self.assertIsNotNone(cart.name)
        self.assertIsNotNone(cart.cart_id)
        self.assertTrue(cart.cart_id.startswith("CART-"))
        self.assertEqual(cart.status, "Active")
        self.assertEqual(cart.buyer, self.test_user.email)

    def test_cart_id_generation(self):
        """Test unique cart ID generation."""
        cart1 = frappe.get_doc({
            "doctype": "Cart",
            "buyer_type": "Guest",
            "currency": "TRY"
        })
        cart1.insert()

        cart2 = frappe.get_doc({
            "doctype": "Cart",
            "buyer_type": "Guest",
            "currency": "TRY"
        })
        cart2.insert()

        self.assertNotEqual(cart1.cart_id, cart2.cart_id)

    def test_cart_expiry_guest(self):
        """Test guest cart expiry (24 hours)."""
        cart = frappe.get_doc({
            "doctype": "Cart",
            "buyer_type": "Guest",
            "currency": "TRY"
        })
        cart.insert()

        # Guest carts should expire in 24 hours
        self.assertIsNotNone(cart.expires_at)

    def test_cart_expiry_registered(self):
        """Test registered user cart expiry (7 days)."""
        cart = frappe.get_doc({
            "doctype": "Cart",
            "buyer": self.test_user.email,
            "buyer_type": "Individual",
            "currency": "TRY"
        })
        cart.insert()

        # Registered user carts should expire in 7 days
        self.assertIsNotNone(cart.expires_at)

    def test_cart_totals_calculation(self):
        """Test cart totals are calculated correctly."""
        cart = frappe.get_doc({
            "doctype": "Cart",
            "buyer_type": "Guest",
            "currency": "TRY"
        })
        cart.insert()

        # Add items manually (in real scenario, add_item method would be used)
        cart.append("items", {
            "listing": "TEST-LISTING",  # Would need real listing
            "seller": "TEST-SELLER",
            "title": "Test Product",
            "qty": 2,
            "unit_price": 100,
            "tax_rate": 18,
            "price_includes_tax": 1
        })

        cart.calculate_totals()

        # 2 items at 100 each = 200 subtotal
        self.assertEqual(flt(cart.subtotal), 200)

    def test_cart_status_transitions(self):
        """Test valid cart status transitions."""
        cart = frappe.get_doc({
            "doctype": "Cart",
            "buyer_type": "Guest",
            "currency": "TRY"
        })
        cart.insert()

        # Active cart can become Checkout
        self.assertEqual(cart.status, "Active")

        cart.status = "Checkout"
        cart.save()
        self.assertEqual(cart.status, "Checkout")

        # Checkout can become Abandoned
        cart.status = "Abandoned"
        cart.save()
        self.assertEqual(cart.status, "Abandoned")

    def test_cart_clear(self):
        """Test clearing cart items."""
        cart = frappe.get_doc({
            "doctype": "Cart",
            "buyer_type": "Guest",
            "currency": "TRY"
        })
        cart.insert()

        cart.clear_cart()

        self.assertEqual(len(cart.items), 0)
        self.assertEqual(flt(cart.subtotal), 0)
        self.assertEqual(flt(cart.grand_total), 0)

    def test_cart_summary(self):
        """Test cart summary generation."""
        cart = frappe.get_doc({
            "doctype": "Cart",
            "buyer_type": "Guest",
            "currency": "TRY"
        })
        cart.insert()

        summary = cart.get_summary()

        self.assertIn("cart_id", summary)
        self.assertIn("status", summary)
        self.assertIn("item_count", summary)
        self.assertIn("subtotal", summary)
        self.assertIn("grand_total", summary)
        self.assertIn("currency", summary)

    def test_cart_item_count(self):
        """Test get_item_count method."""
        cart = frappe.get_doc({
            "doctype": "Cart",
            "buyer_type": "Guest",
            "currency": "TRY"
        })
        cart.insert()

        # Empty cart
        self.assertEqual(cart.get_item_count(), 0)

    def test_cart_seller_count(self):
        """Test get_seller_count method."""
        cart = frappe.get_doc({
            "doctype": "Cart",
            "buyer_type": "Guest",
            "currency": "TRY"
        })
        cart.insert()

        # Empty cart
        self.assertEqual(cart.get_seller_count(), 0)

    def test_b2b_cart(self):
        """Test B2B cart settings."""
        cart = frappe.get_doc({
            "doctype": "Cart",
            "buyer_type": "Organization",
            "is_b2b_cart": 1,
            "buyer_organization_type": "Wholesale",
            "currency": "TRY"
        })
        cart.insert()

        self.assertEqual(cart.is_b2b_cart, 1)
        self.assertEqual(cart.buyer_organization_type, "Wholesale")

    def test_cart_mark_abandoned(self):
        """Test marking cart as abandoned."""
        cart = frappe.get_doc({
            "doctype": "Cart",
            "buyer_type": "Guest",
            "currency": "TRY"
        })
        cart.insert()

        cart.mark_abandoned()

        self.assertEqual(cart.status, "Abandoned")
        self.assertIsNotNone(cart.abandoned_at)

    def test_cart_cache_clearing(self):
        """Test cart cache clearing method."""
        cart = frappe.get_doc({
            "doctype": "Cart",
            "buyer": self.test_user.email,
            "buyer_type": "Individual",
            "currency": "TRY"
        })
        cart.insert()

        # Should not raise an error
        cart.clear_cart_cache()


class TestCartLine(unittest.TestCase):
    """Test cases for Cart Line DocType (child table)."""

    def test_cart_line_totals_calculation(self):
        """Test cart line totals calculation."""
        from tradehub_commerce.tradehub_commerce.doctype.cart_line.cart_line import CartLine

        line = CartLine({
            "doctype": "Cart Line",
            "listing": "TEST-LISTING",
            "qty": 2,
            "unit_price": 100,
            "tax_rate": 18,
            "price_includes_tax": 1
        })

        line.calculate_totals()

        # Line total should be qty * unit_price = 200
        self.assertEqual(flt(line.line_total), 200)

    def test_cart_line_discount_percentage(self):
        """Test percentage discount calculation."""
        from tradehub_commerce.tradehub_commerce.doctype.cart_line.cart_line import CartLine

        line = CartLine({
            "doctype": "Cart Line",
            "listing": "TEST-LISTING",
            "qty": 1,
            "unit_price": 100,
            "tax_rate": 18,
            "price_includes_tax": 1,
            "discount_type": "Percentage",
            "discount_value": 10
        })

        line.calculate_discount()

        # 10% off 100 = 10 discount, 90 discounted price
        self.assertEqual(flt(line.discount_amount), 10)  # Per qty
        self.assertEqual(flt(line.discounted_price), 90)

    def test_cart_line_discount_fixed(self):
        """Test fixed amount discount calculation."""
        from tradehub_commerce.tradehub_commerce.doctype.cart_line.cart_line import CartLine

        line = CartLine({
            "doctype": "Cart Line",
            "listing": "TEST-LISTING",
            "qty": 1,
            "unit_price": 100,
            "tax_rate": 18,
            "price_includes_tax": 1,
            "discount_type": "Fixed Amount",
            "discount_value": 15
        })

        line.calculate_discount()

        # 15 off 100 = 85 discounted price
        self.assertEqual(flt(line.discount_amount), 15)  # Per qty
        self.assertEqual(flt(line.discounted_price), 85)

    def test_cart_line_tax_inclusive(self):
        """Test tax calculation with inclusive pricing."""
        from tradehub_commerce.tradehub_commerce.doctype.cart_line.cart_line import CartLine

        line = CartLine({
            "doctype": "Cart Line",
            "listing": "TEST-LISTING",
            "qty": 1,
            "unit_price": 118,  # 100 + 18% VAT
            "tax_rate": 18,
            "price_includes_tax": 1
        })

        line.calculate_totals()

        # Extract tax from 118: 118 / 1.18 = 100 taxable, 18 tax
        self.assertAlmostEqual(flt(line.taxable_amount), 100, places=0)
        self.assertAlmostEqual(flt(line.tax_amount), 18, places=0)
        self.assertEqual(flt(line.line_total), 118)

    def test_cart_line_tax_exclusive(self):
        """Test tax calculation with exclusive pricing."""
        from tradehub_commerce.tradehub_commerce.doctype.cart_line.cart_line import CartLine

        line = CartLine({
            "doctype": "Cart Line",
            "listing": "TEST-LISTING",
            "qty": 1,
            "unit_price": 100,
            "tax_rate": 18,
            "price_includes_tax": 0
        })

        line.calculate_totals()

        # Add tax to 100: 100 taxable, 18 tax, 118 total
        self.assertEqual(flt(line.taxable_amount), 100)
        self.assertEqual(flt(line.tax_amount), 18)
        self.assertEqual(flt(line.line_total), 118)

    def test_cart_line_display_data(self):
        """Test get_display_data method."""
        from tradehub_commerce.tradehub_commerce.doctype.cart_line.cart_line import CartLine

        line = CartLine({
            "doctype": "Cart Line",
            "listing": "TEST-LISTING",
            "title": "Test Product",
            "qty": 2,
            "unit_price": 100,
            "currency": "TRY"
        })

        data = line.get_display_data()

        self.assertIn("listing", data)
        self.assertIn("title", data)
        self.assertIn("qty", data)
        self.assertIn("unit_price", data)
        self.assertIn("currency", data)

    def test_cart_line_savings(self):
        """Test savings calculation."""
        from tradehub_commerce.tradehub_commerce.doctype.cart_line.cart_line import CartLine

        line = CartLine({
            "doctype": "Cart Line",
            "listing": "TEST-LISTING",
            "qty": 2,
            "unit_price": 80,
            "compare_at_price": 100,
            "currency": "TRY"
        })

        savings = line.get_savings()

        self.assertTrue(savings["has_savings"])
        self.assertEqual(savings["unit_savings"], 20)
        self.assertEqual(savings["total_savings"], 40)  # 20 * 2 qty
        self.assertEqual(savings["savings_percent"], 20)  # 20%


def run_tests():
    """Run all cart tests."""
    import unittest
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    suite.addTests(loader.loadTestsFromTestCase(TestCart))
    suite.addTests(loader.loadTestsFromTestCase(TestCartLine))

    runner = unittest.TextTestRunner(verbosity=2)
    runner.run(suite)


if __name__ == "__main__":
    run_tests()

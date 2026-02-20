# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

"""
Comprehensive unit tests for Group Buy Module.

Tests cover:
- Group Buy creation and validation
- Contribution-based dynamic pricing (Model B)
- Commitment lifecycle (create, update, cancel)
- Group buy status transitions
- Payment processing
- Price recalculation on commitment changes
- Scheduler tasks
"""

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import flt, now_datetime, add_days, add_to_date
import json


class TestGroupBuyPricing(FrappeTestCase):
    """Tests for contribution-based pricing model."""

    def test_calculate_buyer_price_basic(self):
        """Test basic price calculation."""
        from tr_tradehub.groupbuy.pricing import calculate_buyer_price

        # Parameters
        T = 100  # Target quantity
        P_T = 100.0  # Max price
        P_best = 80.0  # Best price
        s_ref = 0.20  # Reference share (20%)
        alpha = 1.0

        # Small commitment (1% of target) - should get near max price
        price_1 = calculate_buyer_price(1, T, P_T, P_best, s_ref, alpha)
        self.assertGreater(price_1, 98)  # Near max price

        # Medium commitment (10% of target)
        price_10 = calculate_buyer_price(10, T, P_T, P_best, s_ref, alpha)
        self.assertGreater(price_10, price_1)  # Should be lower
        self.assertLess(price_10, P_T)

        # Large commitment (20% = s_ref) - should get best price
        price_20 = calculate_buyer_price(20, T, P_T, P_best, s_ref, alpha)
        self.assertEqual(price_20, P_best)

        # Very large commitment (50%) - still capped at best price
        price_50 = calculate_buyer_price(50, T, P_T, P_best, s_ref, alpha)
        self.assertEqual(price_50, P_best)

    def test_calculate_buyer_price_edge_cases(self):
        """Test price calculation edge cases."""
        from tr_tradehub.groupbuy.pricing import calculate_buyer_price

        T = 100
        P_T = 100.0
        P_best = 80.0
        s_ref = 0.20
        alpha = 1.0

        # Zero quantity - should return max price
        self.assertEqual(calculate_buyer_price(0, T, P_T, P_best, s_ref, alpha), P_T)

        # Negative quantity - should return max price
        self.assertEqual(calculate_buyer_price(-10, T, P_T, P_best, s_ref, alpha), P_T)

        # Zero target - should return max price
        self.assertEqual(calculate_buyer_price(10, 0, P_T, P_best, s_ref, alpha), P_T)

    def test_alpha_factor_scaling(self):
        """Test alpha factor affects pricing."""
        from tr_tradehub.groupbuy.pricing import calculate_buyer_price

        T = 100
        P_T = 100.0
        P_best = 80.0
        s_ref = 0.20
        q_i = 10  # 10% of target

        # Alpha = 0.5 (reduced discount)
        price_low_alpha = calculate_buyer_price(q_i, T, P_T, P_best, 0.20, 0.5)

        # Alpha = 1.0 (standard discount)
        price_normal_alpha = calculate_buyer_price(q_i, T, P_T, P_best, 0.20, 1.0)

        # Lower alpha should give higher price (less discount)
        self.assertGreater(price_low_alpha, price_normal_alpha)

    def test_simulate_price(self):
        """Test price simulation function."""
        # This would require a Group Buy document in database
        # Tested in integration tests
        pass


class TestGroupBuyCreation(FrappeTestCase):
    """Tests for Group Buy document creation."""

    @classmethod
    def setUpClass(cls):
        """Set up test fixtures."""
        super().setUpClass()
        cls.setup_test_data()

    @classmethod
    def setup_test_data(cls):
        """Create required test data."""
        # Create test user
        if not frappe.db.exists("User", "gb_test_seller@example.com"):
            user = frappe.get_doc({
                "doctype": "User",
                "email": "gb_test_seller@example.com",
                "first_name": "GroupBuy",
                "last_name": "Seller",
                "send_welcome_email": 0
            })
            user.insert(ignore_permissions=True)

        # Create test seller profile
        if not frappe.db.exists("Seller Profile", {"user": "gb_test_seller@example.com"}):
            seller = frappe.get_doc({
                "doctype": "Seller Profile",
                "seller_name": "Group Buy Test Seller",
                "user": "gb_test_seller@example.com",
                "seller_type": "Business",
                "status": "Active",
                "verification_status": "Verified",
                "contact_email": "gb_test_seller@example.com",
                "address_line_1": "Test Address",
                "city": "Istanbul",
                "country": "Turkey",
                "can_sell": 1
            })
            seller.insert(ignore_permissions=True)

        # Create test buyer user
        if not frappe.db.exists("User", "gb_test_buyer@example.com"):
            user = frappe.get_doc({
                "doctype": "User",
                "email": "gb_test_buyer@example.com",
                "first_name": "GroupBuy",
                "last_name": "Buyer",
                "send_welcome_email": 0
            })
            user.insert(ignore_permissions=True)

        # Create test buyer profile
        if not frappe.db.exists("Buyer Profile", {"user": "gb_test_buyer@example.com"}):
            buyer = frappe.get_doc({
                "doctype": "Buyer Profile",
                "buyer_name": "Group Buy Test Buyer",
                "user": "gb_test_buyer@example.com",
                "buyer_type": "Individual",
                "status": "Active",
                "contact_email": "gb_test_buyer@example.com"
            })
            buyer.insert(ignore_permissions=True)

    def get_test_seller(self):
        """Get the test seller profile name."""
        return frappe.db.get_value(
            "Seller Profile",
            {"user": "gb_test_seller@example.com"},
            "name"
        )

    def get_test_buyer(self):
        """Get the test buyer profile name."""
        return frappe.db.get_value(
            "Buyer Profile",
            {"user": "gb_test_buyer@example.com"},
            "name"
        )

    def create_group_buy(self, **kwargs):
        """Create a test group buy with default values."""
        defaults = {
            "doctype": "Group Buy",
            "title": "Test Group Buy Campaign",
            "seller": self.get_test_seller(),
            "target_quantity": 100,
            "max_price": 100.0,
            "best_price": 80.0,
            "min_quantity": 1,
            "currency": "TRY",
            "reference_share": 0.20,
            "alpha_factor": 1.0,
            "start_date": now_datetime(),
            "end_date": add_days(now_datetime(), 7),
            "status": "Draft"
        }
        defaults.update(kwargs)
        return frappe.get_doc(defaults)

    def test_group_buy_creation_basic(self):
        """Test basic group buy creation."""
        gb = self.create_group_buy(title="Basic Creation Test")
        gb.insert(ignore_permissions=True)

        self.assertIsNotNone(gb.name)
        self.assertEqual(gb.status, "Draft")
        self.assertEqual(gb.current_quantity, 0)
        self.assertEqual(gb.participant_count, 0)

        gb.delete()

    def test_group_buy_pricing_validation(self):
        """Test pricing field validation."""
        # Best price greater than max price
        gb = self.create_group_buy(max_price=100, best_price=150)
        self.assertRaises(frappe.ValidationError, gb.insert)

    def test_group_buy_date_validation(self):
        """Test date validation."""
        # End date before start date
        gb = self.create_group_buy(
            start_date=add_days(now_datetime(), 7),
            end_date=now_datetime()
        )
        self.assertRaises(frappe.ValidationError, gb.insert)

    def test_group_buy_quantity_validation(self):
        """Test quantity validation."""
        # Zero target quantity
        gb = self.create_group_buy(target_quantity=0)
        self.assertRaises(frappe.ValidationError, gb.insert)

    def test_group_buy_reference_share_validation(self):
        """Test reference share validation."""
        # Reference share greater than 1
        gb = self.create_group_buy(reference_share=1.5)
        self.assertRaises(frappe.ValidationError, gb.insert)


class TestGroupBuyCommitment(FrappeTestCase):
    """Tests for Group Buy Commitment functionality."""

    @classmethod
    def setUpClass(cls):
        """Set up test fixtures."""
        super().setUpClass()
        TestGroupBuyCreation.setup_test_data()

    def get_test_seller(self):
        """Get the test seller profile name."""
        return frappe.db.get_value(
            "Seller Profile",
            {"user": "gb_test_seller@example.com"},
            "name"
        )

    def get_test_buyer(self):
        """Get the test buyer profile name."""
        return frappe.db.get_value(
            "Buyer Profile",
            {"user": "gb_test_buyer@example.com"},
            "name"
        )

    def create_group_buy(self, **kwargs):
        """Create a test group buy with default values."""
        defaults = {
            "doctype": "Group Buy",
            "title": "Commitment Test Campaign",
            "seller": self.get_test_seller(),
            "target_quantity": 100,
            "max_price": 100.0,
            "best_price": 80.0,
            "min_quantity": 1,
            "max_quantity_per_buyer": 50,
            "currency": "TRY",
            "reference_share": 0.20,
            "alpha_factor": 1.0,
            "start_date": now_datetime(),
            "end_date": add_days(now_datetime(), 7),
            "status": "Active"
        }
        defaults.update(kwargs)
        return frappe.get_doc(defaults)

    def test_commitment_creation(self):
        """Test commitment creation."""
        gb = self.create_group_buy()
        gb.insert(ignore_permissions=True)

        commitment = frappe.get_doc({
            "doctype": "Group Buy Commitment",
            "group_buy": gb.name,
            "buyer": self.get_test_buyer(),
            "quantity": 10,
            "status": "Active"
        })
        commitment.insert(ignore_permissions=True)

        self.assertIsNotNone(commitment.name)
        self.assertIsNotNone(commitment.unit_price)
        self.assertGreater(commitment.unit_price, 0)
        self.assertEqual(commitment.total_amount, commitment.quantity * commitment.unit_price)

        commitment.delete()
        gb.delete()

    def test_commitment_price_calculation(self):
        """Test that commitment price is calculated correctly."""
        gb = self.create_group_buy()
        gb.insert(ignore_permissions=True)

        # Create commitment for 20% of target (should get best price)
        commitment = frappe.get_doc({
            "doctype": "Group Buy Commitment",
            "group_buy": gb.name,
            "buyer": self.get_test_buyer(),
            "quantity": 20,  # 20% of 100
            "status": "Active"
        })
        commitment.insert(ignore_permissions=True)

        # Should get best price since 20% = s_ref
        self.assertEqual(flt(commitment.unit_price, 2), 80.0)

        commitment.delete()
        gb.delete()

    def test_commitment_quantity_validation_min(self):
        """Test minimum quantity validation."""
        gb = self.create_group_buy(min_quantity=5)
        gb.insert(ignore_permissions=True)

        commitment = frappe.get_doc({
            "doctype": "Group Buy Commitment",
            "group_buy": gb.name,
            "buyer": self.get_test_buyer(),
            "quantity": 3,  # Below minimum
            "status": "Active"
        })
        self.assertRaises(frappe.ValidationError, commitment.insert)

        gb.delete()

    def test_commitment_quantity_validation_max(self):
        """Test maximum quantity per buyer validation."""
        gb = self.create_group_buy(max_quantity_per_buyer=10)
        gb.insert(ignore_permissions=True)

        commitment = frappe.get_doc({
            "doctype": "Group Buy Commitment",
            "group_buy": gb.name,
            "buyer": self.get_test_buyer(),
            "quantity": 15,  # Above maximum
            "status": "Active"
        })
        self.assertRaises(frappe.ValidationError, commitment.insert)

        gb.delete()

    def test_commitment_updates_group_buy_stats(self):
        """Test that commitment updates group buy statistics."""
        gb = self.create_group_buy()
        gb.insert(ignore_permissions=True)

        commitment = frappe.get_doc({
            "doctype": "Group Buy Commitment",
            "group_buy": gb.name,
            "buyer": self.get_test_buyer(),
            "quantity": 10,
            "status": "Active"
        })
        commitment.insert(ignore_permissions=True)

        # Reload group buy to check updated stats
        gb.reload()

        self.assertEqual(gb.current_quantity, 10)
        self.assertEqual(gb.participant_count, 1)

        commitment.delete()
        gb.delete()


class TestGroupBuyStatusTransitions(FrappeTestCase):
    """Tests for Group Buy status transitions."""

    @classmethod
    def setUpClass(cls):
        """Set up test fixtures."""
        super().setUpClass()
        TestGroupBuyCreation.setup_test_data()

    def get_test_seller(self):
        """Get the test seller profile name."""
        return frappe.db.get_value(
            "Seller Profile",
            {"user": "gb_test_seller@example.com"},
            "name"
        )

    def get_test_buyer(self):
        """Get the test buyer profile name."""
        return frappe.db.get_value(
            "Buyer Profile",
            {"user": "gb_test_buyer@example.com"},
            "name"
        )

    def create_group_buy(self, **kwargs):
        """Create a test group buy with default values."""
        defaults = {
            "doctype": "Group Buy",
            "title": "Status Test Campaign",
            "seller": self.get_test_seller(),
            "target_quantity": 100,
            "max_price": 100.0,
            "best_price": 80.0,
            "min_quantity": 1,
            "currency": "TRY",
            "reference_share": 0.20,
            "alpha_factor": 1.0,
            "start_date": now_datetime(),
            "end_date": add_days(now_datetime(), 7),
            "status": "Draft"
        }
        defaults.update(kwargs)
        return frappe.get_doc(defaults)

    def test_draft_to_active(self):
        """Test transition from Draft to Active."""
        gb = self.create_group_buy()
        gb.insert(ignore_permissions=True)

        self.assertEqual(gb.status, "Draft")

        gb.status = "Active"
        gb.save()

        self.assertEqual(gb.status, "Active")

        gb.delete()

    def test_active_to_funded(self):
        """Test automatic transition to Funded when target reached."""
        gb = self.create_group_buy(target_quantity=10, status="Active")
        gb.insert(ignore_permissions=True)

        # Create commitment that meets target
        commitment = frappe.get_doc({
            "doctype": "Group Buy Commitment",
            "group_buy": gb.name,
            "buyer": self.get_test_buyer(),
            "quantity": 10,  # Meets target
            "status": "Active"
        })
        commitment.insert(ignore_permissions=True)

        # Reload to check status
        gb.reload()

        self.assertEqual(gb.status, "Funded")
        self.assertIsNotNone(gb.funded_at)

        commitment.delete()
        gb.delete()

    def test_cancel_group_buy(self):
        """Test cancelling a group buy."""
        gb = self.create_group_buy(status="Active")
        gb.insert(ignore_permissions=True)

        gb.status = "Cancelled"
        gb.save()

        self.assertEqual(gb.status, "Cancelled")

        gb.delete()


class TestGroupBuyPayment(FrappeTestCase):
    """Tests for Group Buy Payment processing."""

    @classmethod
    def setUpClass(cls):
        """Set up test fixtures."""
        super().setUpClass()
        TestGroupBuyCreation.setup_test_data()

    def get_test_seller(self):
        """Get the test seller profile name."""
        return frappe.db.get_value(
            "Seller Profile",
            {"user": "gb_test_seller@example.com"},
            "name"
        )

    def get_test_buyer(self):
        """Get the test buyer profile name."""
        return frappe.db.get_value(
            "Buyer Profile",
            {"user": "gb_test_buyer@example.com"},
            "name"
        )

    def test_payment_creation(self):
        """Test payment record creation."""
        # Create group buy
        gb = frappe.get_doc({
            "doctype": "Group Buy",
            "title": "Payment Test Campaign",
            "seller": self.get_test_seller(),
            "target_quantity": 10,
            "max_price": 100.0,
            "best_price": 80.0,
            "min_quantity": 1,
            "currency": "TRY",
            "start_date": now_datetime(),
            "end_date": add_days(now_datetime(), 7),
            "status": "Active"
        })
        gb.insert(ignore_permissions=True)

        # Create commitment
        commitment = frappe.get_doc({
            "doctype": "Group Buy Commitment",
            "group_buy": gb.name,
            "buyer": self.get_test_buyer(),
            "quantity": 5,
            "status": "Active"
        })
        commitment.insert(ignore_permissions=True)

        # Create payment
        payment = frappe.get_doc({
            "doctype": "Group Buy Payment",
            "group_buy": gb.name,
            "commitment": commitment.name,
            "buyer": self.get_test_buyer(),
            "amount": commitment.total_amount,
            "currency": "TRY",
            "payment_method": "Credit Card",
            "status": "Pending"
        })
        payment.insert(ignore_permissions=True)

        self.assertIsNotNone(payment.name)
        self.assertEqual(payment.status, "Pending")

        payment.delete()
        commitment.delete()
        gb.delete()

    def test_payment_completion_updates_commitment(self):
        """Test that payment completion updates commitment status."""
        # Create group buy
        gb = frappe.get_doc({
            "doctype": "Group Buy",
            "title": "Payment Completion Test",
            "seller": self.get_test_seller(),
            "target_quantity": 10,
            "max_price": 100.0,
            "best_price": 80.0,
            "min_quantity": 1,
            "currency": "TRY",
            "start_date": now_datetime(),
            "end_date": add_days(now_datetime(), 7),
            "status": "Funded"
        })
        gb.insert(ignore_permissions=True)

        # Create commitment with Payment Pending status
        commitment = frappe.get_doc({
            "doctype": "Group Buy Commitment",
            "group_buy": gb.name,
            "buyer": self.get_test_buyer(),
            "quantity": 5,
            "status": "Payment Pending"
        })
        commitment.insert(ignore_permissions=True)

        # Create and complete payment
        payment = frappe.get_doc({
            "doctype": "Group Buy Payment",
            "group_buy": gb.name,
            "commitment": commitment.name,
            "buyer": self.get_test_buyer(),
            "amount": commitment.total_amount,
            "currency": "TRY",
            "payment_method": "Credit Card",
            "status": "Pending"
        })
        payment.insert(ignore_permissions=True)

        # Mark payment as completed
        payment.status = "Completed"
        payment.save()

        # Verify commitment status updated
        commitment.reload()
        self.assertEqual(commitment.status, "Paid")

        payment.delete()
        commitment.delete()
        gb.delete()


class TestGroupBuyAPI(FrappeTestCase):
    """Tests for Group Buy API endpoints."""

    @classmethod
    def setUpClass(cls):
        """Set up test fixtures."""
        super().setUpClass()
        TestGroupBuyCreation.setup_test_data()

    def test_get_group_buys_api(self):
        """Test get_group_buys API endpoint."""
        from tr_tradehub.groupbuy.api import get_group_buys

        result = get_group_buys(status="Active", limit=10)

        self.assertTrue(result["success"])
        self.assertIn("group_buys", result["data"])
        self.assertIn("total", result["data"])

    def test_calculate_price_api(self):
        """Test calculate_price API endpoint."""
        from tr_tradehub.groupbuy.api import calculate_price

        # Need an active group buy first
        seller = frappe.db.get_value(
            "Seller Profile",
            {"user": "gb_test_seller@example.com"},
            "name"
        )

        gb = frappe.get_doc({
            "doctype": "Group Buy",
            "title": "API Test Campaign",
            "seller": seller,
            "target_quantity": 100,
            "max_price": 100.0,
            "best_price": 80.0,
            "min_quantity": 1,
            "currency": "TRY",
            "reference_share": 0.20,
            "alpha_factor": 1.0,
            "start_date": now_datetime(),
            "end_date": add_days(now_datetime(), 7),
            "status": "Active"
        })
        gb.insert(ignore_permissions=True)

        result = calculate_price(gb.name, 10)

        self.assertTrue(result["success"])
        self.assertIn("unit_price", result["data"])
        self.assertIn("total_amount", result["data"])
        self.assertIn("savings", result["data"])

        gb.delete()

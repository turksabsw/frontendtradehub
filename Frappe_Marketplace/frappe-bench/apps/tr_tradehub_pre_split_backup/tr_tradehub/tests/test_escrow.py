# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

"""
Comprehensive unit tests for the Escrow Account DocType.

Tests cover:
- Escrow account creation and validation
- Fund holding workflow
- Release workflow (full and partial)
- Refund workflow
- Dispute handling
- Hold extensions
- Payout processing
- Status transitions
- Fee calculations
"""

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import flt, cint, now_datetime, add_days, nowdate
import json


class TestEscrowCreation(FrappeTestCase):
    """Tests for Escrow Account creation and validation."""

    @classmethod
    def setUpClass(cls):
        """Set up test fixtures."""
        super().setUpClass()
        cls.setup_test_data()

    @classmethod
    def setup_test_data(cls):
        """Create required test data for escrow tests."""
        # Create test buyer user
        if not frappe.db.exists("User", "escrow_test_buyer@example.com"):
            user = frappe.get_doc({
                "doctype": "User",
                "email": "escrow_test_buyer@example.com",
                "first_name": "Escrow",
                "last_name": "Buyer",
                "send_welcome_email": 0
            })
            user.insert(ignore_permissions=True)

        # Create test seller user
        if not frappe.db.exists("User", "escrow_test_seller@example.com"):
            user = frappe.get_doc({
                "doctype": "User",
                "email": "escrow_test_seller@example.com",
                "first_name": "Escrow",
                "last_name": "Seller",
                "send_welcome_email": 0
            })
            user.insert(ignore_permissions=True)

        # Create test seller profile
        if not frappe.db.exists("Seller Profile", {"user": "escrow_test_seller@example.com"}):
            seller = frappe.get_doc({
                "doctype": "Seller Profile",
                "seller_name": "Escrow Test Seller",
                "user": "escrow_test_seller@example.com",
                "seller_type": "Individual",
                "status": "Active",
                "verification_status": "Verified",
                "contact_email": "escrow_test_seller@example.com",
                "address_line_1": "Test Seller Address",
                "city": "Istanbul",
                "country": "Turkey",
                "can_sell": 1
            })
            seller.insert(ignore_permissions=True)

        cls.test_seller = frappe.db.get_value(
            "Seller Profile",
            {"user": "escrow_test_seller@example.com"},
            "name"
        )
        cls.test_buyer = "escrow_test_buyer@example.com"

    def create_escrow(self, **kwargs):
        """Create a test escrow account with default values."""
        defaults = {
            "doctype": "Escrow Account",
            "total_amount": 1000.0,
            "seller": self.test_seller,
            "buyer": self.test_buyer,
            "currency": "TRY",
            "escrow_type": "Order Payment",
            "auto_release_enabled": 1,
            "auto_release_days": 7,
            "max_extensions_allowed": 3
        }
        defaults.update(kwargs)
        return frappe.get_doc(defaults)

    def test_escrow_creation_basic(self):
        """Test basic escrow account creation."""
        escrow = self.create_escrow()
        escrow.insert(ignore_permissions=True)

        self.assertIsNotNone(escrow.name)
        self.assertIsNotNone(escrow.escrow_id)
        self.assertTrue(escrow.escrow_id.startswith("esc_"))
        self.assertEqual(escrow.status, "Pending")

        escrow.delete()

    def test_escrow_id_format(self):
        """Test escrow ID format."""
        escrow = self.create_escrow()
        escrow.insert(ignore_permissions=True)

        self.assertTrue(escrow.escrow_id.startswith("esc_"))
        self.assertEqual(len(escrow.escrow_id), 28)  # esc_ + 24 hex chars

        escrow.delete()

    def test_escrow_requires_seller(self):
        """Test that escrow requires a valid seller."""
        escrow = self.create_escrow(seller=None)
        self.assertRaises(frappe.ValidationError, escrow.insert)

    def test_escrow_requires_buyer(self):
        """Test that escrow requires a valid buyer."""
        escrow = self.create_escrow(buyer=None)
        self.assertRaises(frappe.ValidationError, escrow.insert)

    def test_escrow_requires_positive_amount(self):
        """Test that escrow requires positive total amount."""
        escrow = self.create_escrow(total_amount=0)
        self.assertRaises(frappe.ValidationError, escrow.insert)

        escrow = self.create_escrow(total_amount=-100)
        self.assertRaises(frappe.ValidationError, escrow.insert)

    def test_escrow_initial_amounts(self):
        """Test that initial amounts are set correctly."""
        escrow = self.create_escrow(total_amount=1000)
        escrow.insert(ignore_permissions=True)

        self.assertEqual(flt(escrow.held_amount), 1000.0)
        self.assertEqual(flt(escrow.released_amount), 0.0)
        self.assertEqual(flt(escrow.refunded_amount), 0.0)

        escrow.delete()


class TestEscrowFundHolding(FrappeTestCase):
    """Tests for Escrow fund holding workflow."""

    @classmethod
    def setUpClass(cls):
        """Set up test fixtures."""
        super().setUpClass()
        TestEscrowCreation.setup_test_data()
        cls.test_seller = TestEscrowCreation.test_seller
        cls.test_buyer = TestEscrowCreation.test_buyer

    def create_escrow(self, **kwargs):
        """Create a test escrow account with default values."""
        defaults = {
            "doctype": "Escrow Account",
            "total_amount": 1000.0,
            "seller": self.test_seller,
            "buyer": self.test_buyer,
            "currency": "TRY",
            "escrow_type": "Order Payment",
            "auto_release_enabled": 1,
            "auto_release_days": 7,
            "max_extensions_allowed": 3
        }
        defaults.update(kwargs)
        return frappe.get_doc(defaults)

    def test_hold_funds(self):
        """Test holding funds in escrow."""
        escrow = self.create_escrow(total_amount=1000)
        escrow.insert(ignore_permissions=True)

        escrow.hold_funds(payment_intent="PI-123")
        escrow.reload()

        self.assertEqual(escrow.status, "Funds Held")
        self.assertEqual(flt(escrow.held_amount), 1000.0)
        self.assertEqual(escrow.payment_intent, "PI-123")

        escrow.delete()

    def test_hold_funds_wrong_status(self):
        """Test that hold_funds fails from wrong status."""
        escrow = self.create_escrow(total_amount=1000)
        escrow.insert(ignore_permissions=True)

        escrow.db_set("status", "Funds Held")
        escrow.reload()

        self.assertRaises(
            frappe.ValidationError,
            escrow.hold_funds
        )

        escrow.delete()


class TestEscrowRelease(FrappeTestCase):
    """Tests for Escrow release workflow."""

    @classmethod
    def setUpClass(cls):
        """Set up test fixtures."""
        super().setUpClass()
        TestEscrowCreation.setup_test_data()
        cls.test_seller = TestEscrowCreation.test_seller
        cls.test_buyer = TestEscrowCreation.test_buyer

    def create_escrow(self, **kwargs):
        """Create a test escrow account with default values."""
        defaults = {
            "doctype": "Escrow Account",
            "total_amount": 1000.0,
            "seller": self.test_seller,
            "buyer": self.test_buyer,
            "currency": "TRY",
            "escrow_type": "Order Payment",
            "auto_release_enabled": 1,
            "auto_release_days": 7,
            "max_extensions_allowed": 3
        }
        defaults.update(kwargs)
        return frappe.get_doc(defaults)

    def test_full_release(self):
        """Test full fund release."""
        escrow = self.create_escrow(total_amount=1000)
        escrow.insert(ignore_permissions=True)
        escrow.hold_funds()
        escrow.reload()

        escrow.release_funds(trigger="Buyer Confirmed")
        escrow.reload()

        self.assertEqual(escrow.status, "Released")
        self.assertEqual(flt(escrow.held_amount), 0.0)
        self.assertEqual(flt(escrow.released_amount), 1000.0)
        self.assertEqual(escrow.release_trigger, "Buyer Confirmed")
        self.assertIsNotNone(escrow.closed_at)

        escrow.delete()

    def test_partial_release(self):
        """Test partial fund release."""
        escrow = self.create_escrow(total_amount=1000)
        escrow.insert(ignore_permissions=True)
        escrow.hold_funds()
        escrow.reload()

        escrow.release_funds(amount=400, trigger="Partial Delivery")
        escrow.reload()

        self.assertEqual(escrow.status, "Partially Released")
        self.assertEqual(flt(escrow.held_amount), 600.0)
        self.assertEqual(flt(escrow.released_amount), 400.0)

        escrow.delete()

    def test_release_remaining_after_partial(self):
        """Test releasing remaining funds after partial release."""
        escrow = self.create_escrow(total_amount=1000)
        escrow.insert(ignore_permissions=True)
        escrow.hold_funds()
        escrow.reload()

        # First partial release
        escrow.release_funds(amount=400)
        escrow.reload()
        self.assertEqual(escrow.status, "Partially Released")

        # Release remaining
        escrow.release_funds()
        escrow.reload()

        self.assertEqual(escrow.status, "Released")
        self.assertEqual(flt(escrow.held_amount), 0.0)
        self.assertEqual(flt(escrow.released_amount), 1000.0)

        escrow.delete()

    def test_cannot_release_more_than_held(self):
        """Test that cannot release more than held amount."""
        escrow = self.create_escrow(total_amount=1000)
        escrow.insert(ignore_permissions=True)
        escrow.hold_funds()
        escrow.reload()

        self.assertRaises(
            frappe.ValidationError,
            escrow.release_funds,
            1500
        )

        escrow.delete()

    def test_cannot_release_from_wrong_status(self):
        """Test that cannot release from wrong status."""
        escrow = self.create_escrow(total_amount=1000)
        escrow.insert(ignore_permissions=True)

        # Still in Pending status
        self.assertRaises(
            frappe.ValidationError,
            escrow.release_funds
        )

        escrow.delete()

    def test_confirm_delivery(self):
        """Test delivery confirmation."""
        escrow = self.create_escrow(total_amount=1000)
        escrow.insert(ignore_permissions=True)
        escrow.hold_funds()
        escrow.reload()

        escrow.confirm_delivery()
        escrow.reload()

        self.assertIsNotNone(escrow.delivery_confirmed_at)
        self.assertIsNotNone(escrow.scheduled_release_date)

        escrow.delete()

    def test_approve_release(self):
        """Test buyer approval of release."""
        escrow = self.create_escrow(total_amount=1000)
        escrow.insert(ignore_permissions=True)
        escrow.hold_funds()
        escrow.reload()

        escrow.approve_release()
        escrow.reload()

        self.assertEqual(escrow.status, "Released")
        self.assertEqual(escrow.release_trigger, "Buyer Confirmed")

        escrow.delete()


class TestEscrowRefund(FrappeTestCase):
    """Tests for Escrow refund workflow."""

    @classmethod
    def setUpClass(cls):
        """Set up test fixtures."""
        super().setUpClass()
        TestEscrowCreation.setup_test_data()
        cls.test_seller = TestEscrowCreation.test_seller
        cls.test_buyer = TestEscrowCreation.test_buyer

    def create_escrow(self, **kwargs):
        """Create a test escrow account with default values."""
        defaults = {
            "doctype": "Escrow Account",
            "total_amount": 1000.0,
            "seller": self.test_seller,
            "buyer": self.test_buyer,
            "currency": "TRY",
            "escrow_type": "Order Payment",
            "auto_release_enabled": 1,
            "auto_release_days": 7,
            "max_extensions_allowed": 3
        }
        defaults.update(kwargs)
        return frappe.get_doc(defaults)

    def test_full_refund(self):
        """Test full fund refund."""
        escrow = self.create_escrow(total_amount=1000)
        escrow.insert(ignore_permissions=True)
        escrow.hold_funds()
        escrow.reload()

        escrow.refund_funds(reason="Order cancelled")
        escrow.reload()

        self.assertEqual(escrow.status, "Refunded")
        self.assertEqual(flt(escrow.held_amount), 0.0)
        self.assertEqual(flt(escrow.refunded_amount), 1000.0)
        self.assertIsNotNone(escrow.closed_at)

        escrow.delete()

    def test_partial_refund(self):
        """Test partial fund refund."""
        escrow = self.create_escrow(total_amount=1000)
        escrow.insert(ignore_permissions=True)
        escrow.hold_funds()
        escrow.reload()

        escrow.refund_funds(amount=300, reason="Partial return")
        escrow.reload()

        self.assertEqual(escrow.status, "Partially Refunded")
        self.assertEqual(flt(escrow.held_amount), 700.0)
        self.assertEqual(flt(escrow.refunded_amount), 300.0)

        escrow.delete()

    def test_cannot_refund_more_than_held(self):
        """Test that cannot refund more than held amount."""
        escrow = self.create_escrow(total_amount=1000)
        escrow.insert(ignore_permissions=True)
        escrow.hold_funds()
        escrow.reload()

        self.assertRaises(
            frappe.ValidationError,
            escrow.refund_funds,
            1500
        )

        escrow.delete()

    def test_cannot_refund_from_pending(self):
        """Test that cannot refund from Pending status."""
        escrow = self.create_escrow(total_amount=1000)
        escrow.insert(ignore_permissions=True)

        self.assertRaises(
            frappe.ValidationError,
            escrow.refund_funds
        )

        escrow.delete()


class TestEscrowDispute(FrappeTestCase):
    """Tests for Escrow dispute handling."""

    @classmethod
    def setUpClass(cls):
        """Set up test fixtures."""
        super().setUpClass()
        TestEscrowCreation.setup_test_data()
        cls.test_seller = TestEscrowCreation.test_seller
        cls.test_buyer = TestEscrowCreation.test_buyer

    def create_escrow(self, **kwargs):
        """Create a test escrow account with default values."""
        defaults = {
            "doctype": "Escrow Account",
            "total_amount": 1000.0,
            "seller": self.test_seller,
            "buyer": self.test_buyer,
            "currency": "TRY",
            "escrow_type": "Order Payment",
            "auto_release_enabled": 1,
            "auto_release_days": 7,
            "max_extensions_allowed": 3
        }
        defaults.update(kwargs)
        return frappe.get_doc(defaults)

    def test_open_dispute(self):
        """Test opening a dispute."""
        escrow = self.create_escrow(total_amount=1000)
        escrow.insert(ignore_permissions=True)
        escrow.hold_funds()
        escrow.reload()

        escrow.open_dispute("Product not as described")
        escrow.reload()

        self.assertEqual(escrow.status, "Disputed")
        self.assertEqual(escrow.dispute_status, "Open")
        self.assertEqual(escrow.has_dispute, 1)
        self.assertIsNotNone(escrow.dispute_opened_at)
        # Hold should be extended during dispute
        self.assertEqual(escrow.hold_extended, 1)

        escrow.delete()

    def test_cannot_open_duplicate_dispute(self):
        """Test that cannot open duplicate dispute."""
        escrow = self.create_escrow(total_amount=1000)
        escrow.insert(ignore_permissions=True)
        escrow.hold_funds()
        escrow.reload()

        escrow.open_dispute("First dispute")
        escrow.reload()

        self.assertRaises(
            frappe.ValidationError,
            escrow.open_dispute,
            "Second dispute"
        )

        escrow.delete()

    def test_resolve_dispute_favor_buyer(self):
        """Test resolving dispute in favor of buyer (full refund)."""
        escrow = self.create_escrow(total_amount=1000)
        escrow.insert(ignore_permissions=True)
        escrow.hold_funds()
        escrow.reload()
        escrow.open_dispute("Issue")
        escrow.reload()

        escrow.resolve_dispute(
            "Buyer gets full refund",
            amount_to_buyer=1000,
            amount_to_seller=0
        )
        escrow.reload()

        self.assertEqual(escrow.dispute_status, "Resolved")
        self.assertEqual(escrow.dispute_resolution, "Buyer gets full refund")
        self.assertEqual(flt(escrow.refunded_amount), 1000.0)

        escrow.delete()

    def test_resolve_dispute_favor_seller(self):
        """Test resolving dispute in favor of seller (full release)."""
        escrow = self.create_escrow(total_amount=1000)
        escrow.insert(ignore_permissions=True)
        escrow.hold_funds()
        escrow.reload()
        escrow.open_dispute("Issue")
        escrow.reload()

        escrow.resolve_dispute(
            "Seller gets full payment",
            amount_to_buyer=0,
            amount_to_seller=1000
        )
        escrow.reload()

        self.assertEqual(escrow.dispute_status, "Resolved")
        self.assertEqual(flt(escrow.released_amount), 1000.0)

        escrow.delete()

    def test_resolve_dispute_split(self):
        """Test resolving dispute with split (partial refund/release)."""
        escrow = self.create_escrow(total_amount=1000)
        escrow.insert(ignore_permissions=True)
        escrow.hold_funds()
        escrow.reload()
        escrow.open_dispute("Issue")
        escrow.reload()

        escrow.resolve_dispute(
            "Split 50/50",
            amount_to_buyer=500,
            amount_to_seller=500
        )
        escrow.reload()

        self.assertEqual(escrow.dispute_status, "Resolved")
        self.assertEqual(flt(escrow.refunded_amount), 500.0)
        self.assertEqual(flt(escrow.released_amount), 500.0)

        escrow.delete()

    def test_cannot_release_during_active_dispute(self):
        """Test that cannot release funds during active dispute."""
        escrow = self.create_escrow(total_amount=1000)
        escrow.insert(ignore_permissions=True)
        escrow.hold_funds()
        escrow.reload()
        escrow.open_dispute("Issue")
        escrow.reload()

        self.assertRaises(
            frappe.ValidationError,
            escrow.release_funds
        )

        escrow.delete()


class TestEscrowHoldExtension(FrappeTestCase):
    """Tests for Escrow hold extension."""

    @classmethod
    def setUpClass(cls):
        """Set up test fixtures."""
        super().setUpClass()
        TestEscrowCreation.setup_test_data()
        cls.test_seller = TestEscrowCreation.test_seller
        cls.test_buyer = TestEscrowCreation.test_buyer

    def create_escrow(self, **kwargs):
        """Create a test escrow account with default values."""
        defaults = {
            "doctype": "Escrow Account",
            "total_amount": 1000.0,
            "seller": self.test_seller,
            "buyer": self.test_buyer,
            "currency": "TRY",
            "escrow_type": "Order Payment",
            "auto_release_enabled": 1,
            "auto_release_days": 7,
            "max_extensions_allowed": 3
        }
        defaults.update(kwargs)
        return frappe.get_doc(defaults)

    def test_extend_hold(self):
        """Test extending hold period."""
        escrow = self.create_escrow(total_amount=1000)
        escrow.insert(ignore_permissions=True)
        escrow.hold_funds()
        escrow.reload()

        original_release_date = escrow.scheduled_release_date

        escrow.extend_hold("Waiting for additional documents", days=14)
        escrow.reload()

        self.assertEqual(escrow.hold_extended, 1)
        self.assertEqual(escrow.hold_extension_count, 1)
        self.assertEqual(escrow.hold_extension_reason, "Waiting for additional documents")
        self.assertEqual(escrow.original_release_date, original_release_date)

        escrow.delete()

    def test_max_extensions_reached(self):
        """Test that max extensions limit is enforced."""
        escrow = self.create_escrow(total_amount=1000, max_extensions_allowed=2)
        escrow.insert(ignore_permissions=True)
        escrow.hold_funds()
        escrow.reload()

        # First extension
        escrow.extend_hold("Reason 1", days=7)
        escrow.reload()
        self.assertEqual(escrow.hold_extension_count, 1)

        # Second extension
        escrow.extend_hold("Reason 2", days=7)
        escrow.reload()
        self.assertEqual(escrow.hold_extension_count, 2)

        # Third extension should fail
        self.assertRaises(
            frappe.ValidationError,
            escrow.extend_hold,
            "Reason 3",
            7
        )

        escrow.delete()


class TestEscrowPayout(FrappeTestCase):
    """Tests for Escrow payout processing."""

    @classmethod
    def setUpClass(cls):
        """Set up test fixtures."""
        super().setUpClass()
        TestEscrowCreation.setup_test_data()
        cls.test_seller = TestEscrowCreation.test_seller
        cls.test_buyer = TestEscrowCreation.test_buyer

    def create_escrow(self, **kwargs):
        """Create a test escrow account with default values."""
        defaults = {
            "doctype": "Escrow Account",
            "total_amount": 1000.0,
            "seller": self.test_seller,
            "buyer": self.test_buyer,
            "currency": "TRY",
            "escrow_type": "Order Payment",
            "auto_release_enabled": 1,
            "auto_release_days": 7,
            "max_extensions_allowed": 3
        }
        defaults.update(kwargs)
        return frappe.get_doc(defaults)

    def test_schedule_payout(self):
        """Test payout scheduling."""
        escrow = self.create_escrow(total_amount=1000)
        escrow.insert(ignore_permissions=True)
        escrow.hold_funds()
        escrow.reload()
        escrow.release_funds()
        escrow.reload()

        self.assertEqual(escrow.payout_status, "Scheduled")

        escrow.delete()

    def test_process_payout(self):
        """Test payout processing."""
        escrow = self.create_escrow(total_amount=1000)
        escrow.insert(ignore_permissions=True)
        escrow.hold_funds()
        escrow.reload()
        escrow.release_funds()
        escrow.reload()

        escrow.process_payout(method="Bank Transfer", account="TR12345")
        escrow.reload()

        self.assertEqual(escrow.payout_status, "Processing")
        self.assertEqual(escrow.payout_method, "Bank Transfer")
        self.assertEqual(escrow.payout_account, "TR12345")

        escrow.delete()

    def test_complete_payout(self):
        """Test payout completion."""
        escrow = self.create_escrow(total_amount=1000)
        escrow.insert(ignore_permissions=True)
        escrow.hold_funds()
        escrow.reload()
        escrow.release_funds()
        escrow.reload()

        escrow.process_payout()
        escrow.reload()

        escrow.complete_payout(reference="PAY-REF-123")
        escrow.reload()

        self.assertEqual(escrow.payout_status, "Completed")
        self.assertEqual(escrow.payout_reference, "PAY-REF-123")
        self.assertIsNotNone(escrow.payout_date)

        escrow.delete()

    def test_fail_payout(self):
        """Test payout failure handling."""
        escrow = self.create_escrow(total_amount=1000)
        escrow.insert(ignore_permissions=True)
        escrow.hold_funds()
        escrow.reload()
        escrow.release_funds()
        escrow.reload()
        escrow.process_payout()
        escrow.reload()

        escrow.fail_payout("Bank rejected transfer")
        escrow.reload()

        self.assertEqual(escrow.payout_status, "Failed")
        self.assertEqual(escrow.payout_error, "Bank rejected transfer")

        escrow.delete()


class TestEscrowFees(FrappeTestCase):
    """Tests for Escrow fee calculations."""

    @classmethod
    def setUpClass(cls):
        """Set up test fixtures."""
        super().setUpClass()
        TestEscrowCreation.setup_test_data()
        cls.test_seller = TestEscrowCreation.test_seller
        cls.test_buyer = TestEscrowCreation.test_buyer

    def create_escrow(self, **kwargs):
        """Create a test escrow account with default values."""
        defaults = {
            "doctype": "Escrow Account",
            "total_amount": 1000.0,
            "seller": self.test_seller,
            "buyer": self.test_buyer,
            "currency": "TRY",
            "escrow_type": "Order Payment",
            "auto_release_enabled": 1,
            "auto_release_days": 7,
            "max_extensions_allowed": 3
        }
        defaults.update(kwargs)
        return frappe.get_doc(defaults)

    def test_fee_calculation(self):
        """Test total fee calculation."""
        escrow = self.create_escrow(
            total_amount=1000,
            commission_amount=100,
            platform_fee=20,
            processing_fee=10
        )
        escrow.insert(ignore_permissions=True)

        self.assertEqual(flt(escrow.total_fees), 130.0)
        self.assertEqual(flt(escrow.net_amount_to_seller), 870.0)

        escrow.delete()

    def test_net_amount_cannot_be_negative(self):
        """Test that net amount to seller cannot be negative."""
        escrow = self.create_escrow(
            total_amount=100,
            commission_amount=80,
            platform_fee=30,  # Total fees > total amount
            processing_fee=10
        )

        self.assertRaises(frappe.ValidationError, escrow.insert)


class TestEscrowStatusChecks(FrappeTestCase):
    """Tests for Escrow status check methods."""

    @classmethod
    def setUpClass(cls):
        """Set up test fixtures."""
        super().setUpClass()
        TestEscrowCreation.setup_test_data()
        cls.test_seller = TestEscrowCreation.test_seller
        cls.test_buyer = TestEscrowCreation.test_buyer

    def create_escrow(self, **kwargs):
        """Create a test escrow account with default values."""
        defaults = {
            "doctype": "Escrow Account",
            "total_amount": 1000.0,
            "seller": self.test_seller,
            "buyer": self.test_buyer,
            "currency": "TRY",
            "escrow_type": "Order Payment",
            "auto_release_enabled": 1,
            "auto_release_days": 7,
            "max_extensions_allowed": 3
        }
        defaults.update(kwargs)
        return frappe.get_doc(defaults)

    def test_is_releasable(self):
        """Test is_releasable check."""
        escrow = self.create_escrow(total_amount=1000)
        escrow.insert(ignore_permissions=True)

        # Not releasable in Pending
        self.assertFalse(escrow.is_releasable())

        escrow.hold_funds()
        escrow.reload()

        # Releasable in Funds Held
        self.assertTrue(escrow.is_releasable())

        escrow.delete()

    def test_is_releasable_with_dispute(self):
        """Test is_releasable with active dispute."""
        escrow = self.create_escrow(total_amount=1000)
        escrow.insert(ignore_permissions=True)
        escrow.hold_funds()
        escrow.reload()
        escrow.open_dispute("Issue")
        escrow.reload()

        # Not releasable with active dispute
        self.assertFalse(escrow.is_releasable())

        escrow.delete()

    def test_is_refundable(self):
        """Test is_refundable check."""
        escrow = self.create_escrow(total_amount=1000)
        escrow.insert(ignore_permissions=True)

        # Not refundable in Pending
        self.assertFalse(escrow.is_refundable())

        escrow.hold_funds()
        escrow.reload()

        # Refundable in Funds Held
        self.assertTrue(escrow.is_refundable())

        escrow.delete()

    def test_days_until_release(self):
        """Test days until release calculation."""
        escrow = self.create_escrow(total_amount=1000, auto_release_days=7)
        escrow.insert(ignore_permissions=True)
        escrow.hold_funds()
        escrow.reload()

        days = escrow.days_until_release()

        # Should be approximately 7 days
        self.assertIsNotNone(days)
        self.assertGreater(days, 0)
        self.assertLessEqual(days, 7)

        escrow.delete()


class TestEscrowSummary(FrappeTestCase):
    """Tests for Escrow summary methods."""

    @classmethod
    def setUpClass(cls):
        """Set up test fixtures."""
        super().setUpClass()
        TestEscrowCreation.setup_test_data()
        cls.test_seller = TestEscrowCreation.test_seller
        cls.test_buyer = TestEscrowCreation.test_buyer

    def create_escrow(self, **kwargs):
        """Create a test escrow account with default values."""
        defaults = {
            "doctype": "Escrow Account",
            "total_amount": 1000.0,
            "seller": self.test_seller,
            "buyer": self.test_buyer,
            "currency": "TRY",
            "escrow_type": "Order Payment",
            "auto_release_enabled": 1,
            "auto_release_days": 7,
            "max_extensions_allowed": 3
        }
        defaults.update(kwargs)
        return frappe.get_doc(defaults)

    def test_get_summary(self):
        """Test get_summary method."""
        escrow = self.create_escrow(total_amount=1000)
        escrow.insert(ignore_permissions=True)

        summary = escrow.get_summary()

        expected_keys = [
            "name", "escrow_id", "status", "total_amount",
            "held_amount", "released_amount", "refunded_amount",
            "net_amount_to_seller", "currency", "seller", "buyer",
            "has_dispute", "dispute_status", "payout_status"
        ]

        for key in expected_keys:
            self.assertIn(key, summary)

        self.assertEqual(summary["total_amount"], 1000.0)
        self.assertEqual(summary["currency"], "TRY")
        self.assertEqual(summary["status"], "Pending")

        escrow.delete()


class TestEscrowPartialReleases(FrappeTestCase):
    """Tests for Escrow partial release tracking."""

    @classmethod
    def setUpClass(cls):
        """Set up test fixtures."""
        super().setUpClass()
        TestEscrowCreation.setup_test_data()
        cls.test_seller = TestEscrowCreation.test_seller
        cls.test_buyer = TestEscrowCreation.test_buyer

    def create_escrow(self, **kwargs):
        """Create a test escrow account with default values."""
        defaults = {
            "doctype": "Escrow Account",
            "total_amount": 1000.0,
            "seller": self.test_seller,
            "buyer": self.test_buyer,
            "currency": "TRY",
            "escrow_type": "Order Payment",
            "auto_release_enabled": 1,
            "auto_release_days": 7,
            "max_extensions_allowed": 3
        }
        defaults.update(kwargs)
        return frappe.get_doc(defaults)

    def test_partial_release_tracking(self):
        """Test that partial releases are tracked."""
        escrow = self.create_escrow(total_amount=1000)
        escrow.insert(ignore_permissions=True)
        escrow.hold_funds()
        escrow.reload()

        # First partial release
        escrow.release_funds(amount=400, trigger="Milestone 1")
        escrow.reload()

        # Second partial release
        escrow.release_funds(amount=300, trigger="Milestone 2")
        escrow.reload()

        releases = escrow.get_partial_releases()

        self.assertEqual(len(releases), 2)
        self.assertEqual(flt(releases[0]["amount"]), 400.0)
        self.assertEqual(flt(releases[1]["amount"]), 300.0)
        self.assertEqual(releases[0]["type"], "release")
        self.assertEqual(releases[1]["type"], "release")

        escrow.delete()

    def test_mixed_release_refund_tracking(self):
        """Test tracking of mixed releases and refunds."""
        escrow = self.create_escrow(total_amount=1000)
        escrow.insert(ignore_permissions=True)
        escrow.hold_funds()
        escrow.reload()

        # Partial release
        escrow.release_funds(amount=600)
        escrow.reload()

        # Partial refund of remaining
        escrow.refund_funds(amount=400, reason="Partial return")
        escrow.reload()

        releases = escrow.get_partial_releases()

        self.assertEqual(len(releases), 2)
        self.assertEqual(releases[0]["type"], "release")
        self.assertEqual(releases[1]["type"], "refund")

        escrow.delete()

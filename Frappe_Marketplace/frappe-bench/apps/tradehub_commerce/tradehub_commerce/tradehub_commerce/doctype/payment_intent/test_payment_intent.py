# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import nowdate, now_datetime, add_days, flt, cint


class TestPaymentIntent(FrappeTestCase):
    """Test cases for Payment Intent DocType."""

    def setUp(self):
        """Set up test data."""
        # Create test user if not exists
        if not frappe.db.exists("User", "test_buyer@example.com"):
            user = frappe.get_doc({
                "doctype": "User",
                "email": "test_buyer@example.com",
                "first_name": "Test",
                "last_name": "Buyer",
                "enabled": 1,
                "send_welcome_email": 0
            })
            user.insert(ignore_permissions=True)

    def tearDown(self):
        """Clean up test data."""
        # Delete test payment intents
        frappe.db.delete("Payment Intent", {"buyer": "test_buyer@example.com"})
        frappe.db.commit()

    def create_test_payment_intent(self, **kwargs):
        """Helper to create a test payment intent."""
        data = {
            "doctype": "Payment Intent",
            "amount": 1000,
            "currency": "TRY",
            "buyer": "test_buyer@example.com",
            "payment_gateway": "iyzico",
            "payment_method": "Credit Card"
        }
        data.update(kwargs)

        intent = frappe.get_doc(data)
        intent.insert(ignore_permissions=True)
        return intent

    # =================================================================
    # Basic Creation Tests
    # =================================================================

    def test_payment_intent_creation(self):
        """Test basic payment intent creation."""
        intent = self.create_test_payment_intent()

        self.assertTrue(intent.name)
        self.assertTrue(intent.intent_id)
        self.assertEqual(intent.status, "Created")
        self.assertEqual(flt(intent.amount), 1000)
        self.assertEqual(intent.currency, "TRY")
        self.assertEqual(intent.buyer, "test_buyer@example.com")

    def test_intent_id_generation(self):
        """Test unique intent ID generation."""
        intent1 = self.create_test_payment_intent()
        intent2 = self.create_test_payment_intent()

        self.assertIsNotNone(intent1.intent_id)
        self.assertIsNotNone(intent2.intent_id)
        self.assertNotEqual(intent1.intent_id, intent2.intent_id)
        self.assertTrue(intent1.intent_id.startswith("pi_"))

    def test_default_expiration(self):
        """Test default expiration is set."""
        intent = self.create_test_payment_intent()

        self.assertIsNotNone(intent.expires_at)

    def test_net_amount_calculation(self):
        """Test net amount is calculated correctly."""
        intent = self.create_test_payment_intent(
            amount=1000,
            fee_amount=25
        )

        self.assertEqual(flt(intent.net_amount), 975)

    # =================================================================
    # Validation Tests
    # =================================================================

    def test_zero_amount_validation(self):
        """Test that zero amount fails validation."""
        with self.assertRaises(frappe.ValidationError):
            self.create_test_payment_intent(amount=0)

    def test_negative_amount_validation(self):
        """Test that negative amount fails validation."""
        with self.assertRaises(frappe.ValidationError):
            self.create_test_payment_intent(amount=-100)

    def test_buyer_required(self):
        """Test that buyer is required."""
        with self.assertRaises(frappe.ValidationError):
            frappe.get_doc({
                "doctype": "Payment Intent",
                "amount": 1000,
                "currency": "TRY"
            }).insert()

    def test_card_last_four_validation(self):
        """Test card last four digits validation."""
        # Valid 4 digits
        intent = self.create_test_payment_intent(card_last_four="1234")
        self.assertEqual(intent.card_last_four, "1234")

    def test_card_expiry_month_validation(self):
        """Test card expiry month validation."""
        # Valid month
        intent = self.create_test_payment_intent(card_expiry_month=12)
        self.assertEqual(intent.card_expiry_month, 12)

    # =================================================================
    # Status Transition Tests
    # =================================================================

    def test_status_transition_to_processing(self):
        """Test status transition to processing."""
        intent = self.create_test_payment_intent()

        intent.start_processing()

        self.assertEqual(intent.status, "Processing")
        self.assertIsNotNone(intent.processing_started_at)

    def test_status_transition_to_authorized(self):
        """Test status transition to authorized."""
        intent = self.create_test_payment_intent()
        intent.start_processing()

        intent.authorize(authorization_code="AUTH123")

        self.assertEqual(intent.status, "Authorized")
        self.assertEqual(intent.authorization_code, "AUTH123")
        self.assertIsNotNone(intent.authorized_at)

    def test_status_transition_to_captured(self):
        """Test status transition to captured."""
        intent = self.create_test_payment_intent()
        intent.start_processing()
        intent.authorize()

        intent.capture()

        self.assertEqual(intent.status, "Paid")
        self.assertEqual(flt(intent.captured_amount), 1000)
        self.assertIsNotNone(intent.captured_at)

    def test_partial_capture(self):
        """Test partial capture."""
        intent = self.create_test_payment_intent(amount=1000)
        intent.start_processing()
        intent.authorize()

        intent.capture(amount=500)

        self.assertEqual(intent.status, "Partially Paid")
        self.assertEqual(flt(intent.captured_amount), 500)

    def test_status_transition_to_paid(self):
        """Test status transition to paid."""
        intent = self.create_test_payment_intent()
        intent.start_processing()

        intent.mark_paid(payment_id="PAY123", reference="REF456")

        self.assertEqual(intent.status, "Paid")
        self.assertEqual(intent.gateway_payment_id, "PAY123")
        self.assertEqual(intent.gateway_reference, "REF456")
        self.assertIsNotNone(intent.completed_at)

    def test_status_transition_to_failed(self):
        """Test status transition to failed."""
        intent = self.create_test_payment_intent()
        intent.start_processing()

        intent.mark_failed(error_code="DECLINED", error_message="Card declined")

        self.assertEqual(intent.status, "Failed")
        self.assertEqual(intent.gateway_error_code, "DECLINED")
        self.assertEqual(intent.gateway_error_message, "Card declined")
        self.assertIsNotNone(intent.failed_at)

    def test_status_transition_to_cancelled(self):
        """Test status transition to cancelled."""
        intent = self.create_test_payment_intent()

        intent.cancel(reason="User requested")

        self.assertEqual(intent.status, "Cancelled")
        self.assertIsNotNone(intent.cancelled_at)

    def test_invalid_status_transition(self):
        """Test invalid status transitions are rejected."""
        intent = self.create_test_payment_intent()
        intent.start_processing()
        intent.mark_paid()

        # Cannot cancel a paid payment
        with self.assertRaises(frappe.ValidationError):
            intent.cancel()

    # =================================================================
    # 3D Secure Tests
    # =================================================================

    def test_3d_secure_initialization(self):
        """Test 3D Secure initialization."""
        intent = self.create_test_payment_intent()

        intent.init_3d_secure(
            callback_url="https://example.com/callback",
            html_content="<form>...</form>",
            version="2.0"
        )

        self.assertTrue(intent.requires_3d_secure)
        self.assertEqual(intent.three_d_status, "Initiated")
        self.assertEqual(intent.three_d_callback_url, "https://example.com/callback")
        self.assertEqual(intent.three_d_version, "2.0")
        self.assertEqual(intent.status, "Requires Action")

    def test_3d_secure_completion_success(self):
        """Test successful 3D Secure completion."""
        intent = self.create_test_payment_intent()
        intent.init_3d_secure(callback_url="https://example.com/callback")

        intent.complete_3d_secure(success=True, response={"authResult": "success"})

        self.assertEqual(intent.three_d_status, "Authenticated")
        self.assertTrue(intent.three_d_flow_completed)
        self.assertEqual(intent.status, "Processing")

    def test_3d_secure_completion_failure(self):
        """Test failed 3D Secure completion."""
        intent = self.create_test_payment_intent()
        intent.init_3d_secure(callback_url="https://example.com/callback")

        intent.complete_3d_secure(success=False)

        self.assertEqual(intent.three_d_status, "Failed")
        self.assertEqual(intent.status, "Failed")

    # =================================================================
    # Refund Tests
    # =================================================================

    def test_refund_request(self):
        """Test refund request."""
        intent = self.create_test_payment_intent(amount=1000)
        intent.start_processing()
        intent.mark_paid()

        intent.request_refund(amount=500, reason="Customer Request")

        self.assertEqual(intent.refund_status, "Requested")
        self.assertEqual(flt(intent.refund_amount), 500)
        self.assertEqual(intent.refund_reason, "Customer Request")

    def test_full_refund(self):
        """Test full refund."""
        intent = self.create_test_payment_intent(amount=1000)
        intent.start_processing()
        intent.mark_paid()
        intent.request_refund()

        intent.complete_refund(gateway_refund_id="REF123")

        self.assertEqual(intent.status, "Refunded")
        self.assertEqual(intent.refund_status, "Refunded")
        self.assertIsNotNone(intent.refunded_at)

    def test_partial_refund(self):
        """Test partial refund."""
        intent = self.create_test_payment_intent(amount=1000)
        intent.start_processing()
        intent.mark_paid()
        intent.request_refund(amount=300)

        intent.complete_refund()

        self.assertEqual(intent.status, "Partially Refunded")
        self.assertEqual(intent.refund_status, "Partially Refunded")

    def test_add_partial_refunds(self):
        """Test adding multiple partial refunds."""
        intent = self.create_test_payment_intent(amount=1000)
        intent.start_processing()
        intent.mark_paid()

        intent.add_partial_refund(amount=200, reference="REF1")
        intent.add_partial_refund(amount=300, reference="REF2")

        self.assertEqual(flt(intent.refund_amount), 500)

        import json
        refunds = json.loads(intent.partial_refunds)
        self.assertEqual(len(refunds), 2)

    def test_refund_exceeds_amount(self):
        """Test that refund cannot exceed payment amount."""
        intent = self.create_test_payment_intent(amount=1000)
        intent.start_processing()
        intent.mark_paid()

        with self.assertRaises(frappe.ValidationError):
            intent.request_refund(amount=1500)

    # =================================================================
    # Installment Tests
    # =================================================================

    def test_installment_validation(self):
        """Test installment validation."""
        intent = self.create_test_payment_intent(
            has_installments=1,
            installment_count=6,
            installment_fee=50
        )

        self.assertTrue(intent.has_installments)
        self.assertEqual(intent.installment_count, 6)
        self.assertEqual(flt(intent.installment_total), 1050)

    def test_installment_count_minimum(self):
        """Test minimum installment count validation."""
        with self.assertRaises(frappe.ValidationError):
            self.create_test_payment_intent(
                has_installments=1,
                installment_count=1
            )

    def test_installment_count_maximum(self):
        """Test maximum installment count validation."""
        with self.assertRaises(frappe.ValidationError):
            self.create_test_payment_intent(
                has_installments=1,
                installment_count=24
            )

    # =================================================================
    # Escrow Tests
    # =================================================================

    def test_escrow_hold(self):
        """Test escrow hold."""
        intent = self.create_test_payment_intent(escrow_enabled=1)
        intent.start_processing()
        intent.mark_paid()

        intent.hold_in_escrow()

        self.assertEqual(intent.escrow_status, "Held")
        self.assertIsNotNone(intent.escrow_held_at)
        self.assertIsNotNone(intent.escrow_release_date)

    def test_escrow_release(self):
        """Test escrow release."""
        intent = self.create_test_payment_intent(escrow_enabled=1)
        intent.start_processing()
        intent.mark_paid()
        intent.hold_in_escrow()

        intent.release_escrow()

        self.assertEqual(intent.escrow_status, "Released")
        self.assertIsNotNone(intent.escrow_released_at)

    # =================================================================
    # Risk & Fraud Tests
    # =================================================================

    def test_risk_score_calculation(self):
        """Test risk score calculation."""
        intent = self.create_test_payment_intent(
            buyer_type="Guest",
            amount=15000
        )

        score = intent.calculate_risk_score()

        self.assertGreater(score, 0)
        self.assertEqual(intent.risk_score, score)

    def test_high_risk_flagging(self):
        """Test high risk payment flagging."""
        intent = self.create_test_payment_intent()
        intent.db_set("retry_count", 5)  # Multiple failures

        score = intent.calculate_risk_score()

        self.assertTrue(intent.is_flagged)
        self.assertIn(intent.risk_level, ["High", "Critical"])

    def test_manual_flagging(self):
        """Test manual flagging for review."""
        intent = self.create_test_payment_intent()

        intent.flag_for_review(reason="Suspicious activity")

        self.assertTrue(intent.is_flagged)
        self.assertEqual(intent.fraud_check_status, "Review Required")

    # =================================================================
    # Webhook Tests
    # =================================================================

    def test_record_webhook(self):
        """Test webhook recording."""
        intent = self.create_test_payment_intent()

        intent.record_webhook(
            event_type="payment.success",
            payload={"paymentId": "123"},
            verified=True
        )

        self.assertIsNotNone(intent.last_webhook_at)
        self.assertEqual(intent.webhook_count, 1)
        self.assertEqual(intent.last_webhook_event, "payment.success")
        self.assertTrue(intent.webhook_verified)

    # =================================================================
    # Retry Tests
    # =================================================================

    def test_can_retry_after_failure(self):
        """Test retry eligibility after failure."""
        intent = self.create_test_payment_intent()
        intent.start_processing()
        intent.mark_failed()

        self.assertTrue(intent.can_retry())

    def test_cannot_retry_after_max_attempts(self):
        """Test retry blocked after max attempts."""
        intent = self.create_test_payment_intent()
        intent.db_set("retry_count", 3)
        intent.db_set("status", "Failed")

        self.assertFalse(intent.can_retry())

    def test_cannot_retry_paid_payment(self):
        """Test paid payment cannot be retried."""
        intent = self.create_test_payment_intent()
        intent.start_processing()
        intent.mark_paid()

        self.assertFalse(intent.can_retry())

    # =================================================================
    # API Tests
    # =================================================================

    def test_create_payment_intent_api(self):
        """Test payment intent creation via API."""
        from tradehub_commerce.tradehub_commerce.doctype.payment_intent.payment_intent import (
            create_payment_intent
        )

        result = create_payment_intent(
            amount=500,
            currency="TRY",
            buyer="test_buyer@example.com",
            payment_gateway="iyzico"
        )

        self.assertEqual(result["status"], "success")
        self.assertIn("intent_id", result)
        self.assertEqual(result["amount"], 500)

    def test_get_payment_intent_api(self):
        """Test getting payment intent via API."""
        from tradehub_commerce.tradehub_commerce.doctype.payment_intent.payment_intent import (
            get_payment_intent
        )

        intent = self.create_test_payment_intent()

        result = get_payment_intent(intent_id=intent.intent_id)

        self.assertEqual(result["intent_id"], intent.intent_id)
        self.assertEqual(result["status"], "Created")

    def test_update_payment_status_api(self):
        """Test status update via API."""
        from tradehub_commerce.tradehub_commerce.doctype.payment_intent.payment_intent import (
            update_payment_status
        )

        intent = self.create_test_payment_intent()

        result = update_payment_status(intent.name, "processing")

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["payment_status"], "Processing")

    def test_get_payment_statistics_api(self):
        """Test payment statistics API."""
        from tradehub_commerce.tradehub_commerce.doctype.payment_intent.payment_intent import (
            get_payment_statistics
        )

        # Create some test intents
        self.create_test_payment_intent()
        self.create_test_payment_intent()

        result = get_payment_statistics(days=30)

        self.assertIn("total_intents", result)
        self.assertIn("status_breakdown", result)

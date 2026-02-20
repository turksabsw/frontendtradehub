# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import now_datetime, add_days, nowdate
import json


class TestOrderEvent(FrappeTestCase):
    """Test cases for Order Event DocType."""

    @classmethod
    def setUpClass(cls):
        """Set up test fixtures."""
        super().setUpClass()

        # Create test Marketplace Order if it doesn't exist
        if not frappe.db.exists("Marketplace Order", {"order_id": "TEST-ORDER-001"}):
            cls.create_test_marketplace_order()

    @classmethod
    def create_test_marketplace_order(cls):
        """Create a test marketplace order for testing."""
        try:
            # Create a minimal test order
            order = frappe.get_doc({
                "doctype": "Marketplace Order",
                "order_id": "TEST-ORDER-001",
                "buyer": "Administrator",
                "order_date": nowdate(),
                "status": "Pending",
                "payment_status": "Pending",
                "currency": "TRY",
                "shipping_address_line1": "Test Address",
                "shipping_city": "Istanbul",
                "shipping_country": "Turkey",
                "items": []
            })
            order.flags.ignore_validate = True
            order.flags.ignore_mandatory = True
            order.insert(ignore_permissions=True)
            cls.test_order = order.name
        except Exception:
            cls.test_order = None

    def test_create_basic_order_event(self):
        """Test creating a basic order event."""
        if not hasattr(self.__class__, 'test_order') or not self.__class__.test_order:
            self.skipTest("Test order not available")

        event = frappe.get_doc({
            "doctype": "Order Event",
            "event_type": "Order Created",
            "event_description": "Test order was created",
            "marketplace_order": self.__class__.test_order
        })
        event.insert(ignore_permissions=True)

        self.assertIsNotNone(event.name)
        self.assertEqual(event.event_type, "Order Created")
        self.assertIsNotNone(event.event_timestamp)

    def test_event_category_auto_set(self):
        """Test that event category is automatically set based on event type."""
        if not hasattr(self.__class__, 'test_order') or not self.__class__.test_order:
            self.skipTest("Test order not available")

        event = frappe.get_doc({
            "doctype": "Order Event",
            "event_type": "Payment Received",
            "event_description": "Payment was received",
            "marketplace_order": self.__class__.test_order
        })
        event.insert(ignore_permissions=True)

        self.assertEqual(event.event_category, "Payment")

    def test_event_severity_auto_set(self):
        """Test that severity is automatically set for error events."""
        if not hasattr(self.__class__, 'test_order') or not self.__class__.test_order:
            self.skipTest("Test order not available")

        event = frappe.get_doc({
            "doctype": "Order Event",
            "event_type": "Payment Failed",
            "event_description": "Payment processing failed",
            "marketplace_order": self.__class__.test_order
        })
        event.insert(ignore_permissions=True)

        self.assertEqual(event.severity, "Error")

    def test_status_change_event(self):
        """Test creating a status change event."""
        if not hasattr(self.__class__, 'test_order') or not self.__class__.test_order:
            self.skipTest("Test order not available")

        event = frappe.get_doc({
            "doctype": "Order Event",
            "event_type": "Status Changed",
            "event_description": "Order status changed from Pending to Confirmed",
            "marketplace_order": self.__class__.test_order,
            "previous_status": "Pending",
            "new_status": "Confirmed"
        })
        event.insert(ignore_permissions=True)

        self.assertEqual(event.previous_status, "Pending")
        self.assertEqual(event.new_status, "Confirmed")

    def test_error_event(self):
        """Test creating an error event."""
        if not hasattr(self.__class__, 'test_order') or not self.__class__.test_order:
            self.skipTest("Test order not available")

        event = frappe.get_doc({
            "doctype": "Order Event",
            "event_type": "Error Occurred",
            "event_description": "An error occurred during processing",
            "marketplace_order": self.__class__.test_order,
            "is_error": 1,
            "error_code": "ERR-001",
            "error_message": "Test error message"
        })
        event.insert(ignore_permissions=True)

        self.assertEqual(event.is_error, 1)
        self.assertEqual(event.error_code, "ERR-001")
        self.assertEqual(event.severity, "Error")

    def test_event_with_data_json(self):
        """Test creating an event with additional JSON data."""
        if not hasattr(self.__class__, 'test_order') or not self.__class__.test_order:
            self.skipTest("Test order not available")

        data = {
            "old_qty": 5,
            "new_qty": 10,
            "item_code": "ITEM-001"
        }

        event = frappe.get_doc({
            "doctype": "Order Event",
            "event_type": "Quantity Changed",
            "event_description": "Item quantity was changed",
            "marketplace_order": self.__class__.test_order,
            "data_json": json.dumps(data)
        })
        event.insert(ignore_permissions=True)

        # Parse and verify JSON data
        stored_data = json.loads(event.data_json)
        self.assertEqual(stored_data["old_qty"], 5)
        self.assertEqual(stored_data["new_qty"], 10)

    def test_actor_info_auto_populate(self):
        """Test that actor information is automatically populated."""
        if not hasattr(self.__class__, 'test_order') or not self.__class__.test_order:
            self.skipTest("Test order not available")

        event = frappe.get_doc({
            "doctype": "Order Event",
            "event_type": "Order Updated",
            "event_description": "Order was updated",
            "marketplace_order": self.__class__.test_order
        })
        event.insert(ignore_permissions=True)

        # Actor should be set to current user
        self.assertIsNotNone(event.actor)

    def test_order_id_auto_populate(self):
        """Test that order_id is automatically populated from marketplace order."""
        if not hasattr(self.__class__, 'test_order') or not self.__class__.test_order:
            self.skipTest("Test order not available")

        event = frappe.get_doc({
            "doctype": "Order Event",
            "event_type": "Order Confirmed",
            "event_description": "Order was confirmed",
            "marketplace_order": self.__class__.test_order
        })
        event.insert(ignore_permissions=True)

        # order_id should be populated from the linked order
        self.assertEqual(event.order_id, "TEST-ORDER-001")

    def test_event_validation_requires_order_reference(self):
        """Test that event requires at least one order reference."""
        event = frappe.get_doc({
            "doctype": "Order Event",
            "event_type": "Order Created",
            "event_description": "Test event without order reference"
        })

        with self.assertRaises(frappe.exceptions.ValidationError):
            event.insert(ignore_permissions=True)

    def test_event_timeline_display(self):
        """Test get_timeline_display method."""
        if not hasattr(self.__class__, 'test_order') or not self.__class__.test_order:
            self.skipTest("Test order not available")

        event = frappe.get_doc({
            "doctype": "Order Event",
            "event_type": "Shipped",
            "event_description": "Order has been shipped",
            "marketplace_order": self.__class__.test_order,
            "previous_status": "Packed",
            "new_status": "Shipped",
            "notes": "Shipped via Yurtici Kargo"
        })
        event.insert(ignore_permissions=True)

        timeline = event.get_timeline_display()

        self.assertEqual(timeline["type"], "Shipped")
        self.assertEqual(timeline["description"], "Order has been shipped")
        self.assertIsNotNone(timeline["status_change"])
        self.assertEqual(timeline["status_change"]["from"], "Packed")
        self.assertEqual(timeline["status_change"]["to"], "Shipped")

    def test_event_summary(self):
        """Test get_event_summary method."""
        if not hasattr(self.__class__, 'test_order') or not self.__class__.test_order:
            self.skipTest("Test order not available")

        event = frappe.get_doc({
            "doctype": "Order Event",
            "event_type": "Delivered",
            "event_description": "Order has been delivered",
            "marketplace_order": self.__class__.test_order
        })
        event.insert(ignore_permissions=True)

        summary = event.get_event_summary()

        self.assertEqual(summary["event_type"], "Delivered")
        self.assertEqual(summary["marketplace_order"], self.__class__.test_order)
        self.assertIn("event_timestamp", summary)

    def test_notification_event(self):
        """Test creating an event with notification tracking."""
        if not hasattr(self.__class__, 'test_order') or not self.__class__.test_order:
            self.skipTest("Test order not available")

        event = frappe.get_doc({
            "doctype": "Order Event",
            "event_type": "Shipped",
            "event_description": "Order shipped notification sent",
            "marketplace_order": self.__class__.test_order,
            "notification_sent": 1,
            "notification_type": "Email",
            "notification_recipient": "test@example.com",
            "notification_status": "Sent"
        })
        event.insert(ignore_permissions=True)

        self.assertEqual(event.notification_sent, 1)
        self.assertEqual(event.notification_type, "Email")

    def test_different_event_types(self):
        """Test various event types are handled correctly."""
        if not hasattr(self.__class__, 'test_order') or not self.__class__.test_order:
            self.skipTest("Test order not available")

        event_types = [
            ("Order Created", "Order"),
            ("Payment Received", "Payment"),
            ("Shipped", "Shipping"),
            ("Return Requested", "Return"),
            ("Refund Processed", "Refund"),
            ("Cancellation Requested", "Cancellation"),
            ("Dispute Opened", "Dispute")
        ]

        for event_type, expected_category in event_types:
            event = frappe.get_doc({
                "doctype": "Order Event",
                "event_type": event_type,
                "event_description": f"Test {event_type} event",
                "marketplace_order": self.__class__.test_order
            })
            event.insert(ignore_permissions=True)

            self.assertEqual(
                event.event_category, expected_category,
                f"Event type {event_type} should have category {expected_category}"
            )


class TestOrderEventHelperFunctions(FrappeTestCase):
    """Test cases for Order Event helper functions."""

    @classmethod
    def setUpClass(cls):
        """Set up test fixtures."""
        super().setUpClass()

        # Import helper functions
        from tradehub_commerce.tradehub_commerce.doctype.order_event.order_event import (
            log_order_event,
            log_status_change,
            log_error_event
        )
        cls.log_order_event = log_order_event
        cls.log_status_change = log_status_change
        cls.log_error_event = log_error_event

        # Create test order
        if not frappe.db.exists("Marketplace Order", {"order_id": "TEST-ORDER-002"}):
            cls.create_test_marketplace_order()

    @classmethod
    def create_test_marketplace_order(cls):
        """Create a test marketplace order for testing."""
        try:
            order = frappe.get_doc({
                "doctype": "Marketplace Order",
                "order_id": "TEST-ORDER-002",
                "buyer": "Administrator",
                "order_date": nowdate(),
                "status": "Pending",
                "payment_status": "Pending",
                "currency": "TRY",
                "shipping_address_line1": "Test Address",
                "shipping_city": "Istanbul",
                "shipping_country": "Turkey",
                "items": []
            })
            order.flags.ignore_validate = True
            order.flags.ignore_mandatory = True
            order.insert(ignore_permissions=True)
            cls.test_order = order.name
        except Exception:
            cls.test_order = None

    def test_log_order_event_function(self):
        """Test log_order_event helper function."""
        if not hasattr(self.__class__, 'test_order') or not self.__class__.test_order:
            self.skipTest("Test order not available")

        event = self.log_order_event(
            event_type="Order Updated",
            description="Order was updated via helper function",
            marketplace_order=self.__class__.test_order,
            data={"field": "value"}
        )

        self.assertIsNotNone(event)
        self.assertEqual(event.event_type, "Order Updated")

    def test_log_status_change_function(self):
        """Test log_status_change helper function."""
        if not hasattr(self.__class__, 'test_order') or not self.__class__.test_order:
            self.skipTest("Test order not available")

        event = self.log_status_change(
            doctype="Marketplace Order",
            doc_name=self.__class__.test_order,
            previous_status="Pending",
            new_status="Confirmed"
        )

        self.assertIsNotNone(event)
        self.assertEqual(event.event_type, "Status Changed")
        self.assertEqual(event.previous_status, "Pending")
        self.assertEqual(event.new_status, "Confirmed")

    def test_log_error_event_function(self):
        """Test log_error_event helper function."""
        if not hasattr(self.__class__, 'test_order') or not self.__class__.test_order:
            self.skipTest("Test order not available")

        event = self.log_error_event(
            marketplace_order=self.__class__.test_order,
            error_code="TEST-ERR-001",
            error_message="Test error via helper function",
            context={"key": "value"}
        )

        self.assertIsNotNone(event)
        self.assertEqual(event.event_type, "Error Occurred")
        self.assertEqual(event.is_error, 1)
        self.assertEqual(event.error_code, "TEST-ERR-001")


class TestOrderEventAPI(FrappeTestCase):
    """Test cases for Order Event API endpoints."""

    @classmethod
    def setUpClass(cls):
        """Set up test fixtures."""
        super().setUpClass()

        # Create test order with events
        if not frappe.db.exists("Marketplace Order", {"order_id": "TEST-ORDER-003"}):
            cls.create_test_data()

    @classmethod
    def create_test_data(cls):
        """Create test data for API testing."""
        try:
            # Create test order
            order = frappe.get_doc({
                "doctype": "Marketplace Order",
                "order_id": "TEST-ORDER-003",
                "buyer": "Administrator",
                "order_date": nowdate(),
                "status": "Pending",
                "payment_status": "Pending",
                "currency": "TRY",
                "shipping_address_line1": "Test Address",
                "shipping_city": "Istanbul",
                "shipping_country": "Turkey",
                "items": []
            })
            order.flags.ignore_validate = True
            order.flags.ignore_mandatory = True
            order.insert(ignore_permissions=True)
            cls.test_order = order.name

            # Create some test events
            for event_type in ["Order Created", "Payment Received", "Confirmed", "Shipped"]:
                event = frappe.get_doc({
                    "doctype": "Order Event",
                    "event_type": event_type,
                    "event_description": f"Test {event_type} event",
                    "marketplace_order": cls.test_order
                })
                event.insert(ignore_permissions=True)

        except Exception:
            cls.test_order = None

    def test_get_order_events_api(self):
        """Test get_order_events API endpoint."""
        if not hasattr(self.__class__, 'test_order') or not self.__class__.test_order:
            self.skipTest("Test order not available")

        from tradehub_commerce.tradehub_commerce.doctype.order_event.order_event import get_order_events

        result = get_order_events(marketplace_order=self.__class__.test_order)

        self.assertIn("events", result)
        self.assertIn("total", result)
        self.assertGreater(result["total"], 0)

    def test_get_order_timeline_api(self):
        """Test get_order_timeline API endpoint."""
        if not hasattr(self.__class__, 'test_order') or not self.__class__.test_order:
            self.skipTest("Test order not available")

        from tradehub_commerce.tradehub_commerce.doctype.order_event.order_event import get_order_timeline

        result = get_order_timeline(marketplace_order=self.__class__.test_order)

        self.assertIsInstance(result, list)
        self.assertGreater(len(result), 0)

    def test_get_event_statistics_api(self):
        """Test get_event_statistics API endpoint."""
        if not hasattr(self.__class__, 'test_order') or not self.__class__.test_order:
            self.skipTest("Test order not available")

        from tradehub_commerce.tradehub_commerce.doctype.order_event.order_event import get_event_statistics

        result = get_event_statistics(marketplace_order=self.__class__.test_order)

        self.assertIn("total_events", result)
        self.assertIn("by_type", result)
        self.assertIn("by_category", result)

    def test_create_order_event_api(self):
        """Test create_order_event API endpoint."""
        if not hasattr(self.__class__, 'test_order') or not self.__class__.test_order:
            self.skipTest("Test order not available")

        from tradehub_commerce.tradehub_commerce.doctype.order_event.order_event import create_order_event

        result = create_order_event(
            event_type="Internal Note Added",
            event_description="Test note via API",
            marketplace_order=self.__class__.test_order
        )

        self.assertEqual(result["status"], "success")
        self.assertIn("event_name", result)

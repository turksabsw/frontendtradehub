# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

import frappe
import unittest
from frappe.utils import nowdate, now_datetime, add_days, getdate
import json


class TestTrackingEvent(unittest.TestCase):
    """Test cases for Tracking Event DocType."""

    @classmethod
    def setUpClass(cls):
        """Set up test fixtures."""
        # Create test tenant
        if not frappe.db.exists("Tenant", "test-tracking-tenant"):
            frappe.get_doc({
                "doctype": "Tenant",
                "tenant_name": "Test Tracking Tenant",
                "company_name": "Test Tracking Co",
                "subscription_tier": "Professional",
                "tax_id": "1234567890",  # 10-digit VKN
                "is_active": 1
            }).insert(ignore_permissions=True)

        # Create test seller profile
        if not frappe.db.exists("Seller Profile", "test-tracking-seller"):
            frappe.get_doc({
                "doctype": "Seller Profile",
                "seller_name": "Test Tracking Seller",
                "tenant": "test-tracking-tenant",
                "verification_status": "Verified",
                "is_active": 1
            }).insert(ignore_permissions=True)

        # Create test marketplace shipment
        if not frappe.db.exists("Marketplace Shipment", {"shipment_id": "TEST-SHIP-001"}):
            frappe.get_doc({
                "doctype": "Marketplace Shipment",
                "shipment_id": "TEST-SHIP-001",
                "carrier": "Yurtici Kargo",
                "tracking_number": "YK123456789TR",
                "status": "Pending",
                "sender_name": "Test Seller",
                "origin_address_line1": "Test Address 1",
                "origin_city": "Istanbul",
                "origin_country": "Turkey",
                "recipient_name": "Test Buyer",
                "destination_address_line1": "Test Address 2",
                "destination_city": "Ankara",
                "destination_country": "Turkey",
                "seller": "test-tracking-seller",
                "tenant": "test-tracking-tenant"
            }).insert(ignore_permissions=True)

        cls.shipment_name = frappe.db.get_value(
            "Marketplace Shipment",
            {"shipment_id": "TEST-SHIP-001"},
            "name"
        )

    def test_tracking_event_creation(self):
        """Test creating a basic tracking event."""
        event = frappe.get_doc({
            "doctype": "Tracking Event",
            "shipment": self.shipment_name,
            "event_type": "Shipment Created",
            "event_description": "Shipment has been created",
            "event_timestamp": now_datetime(),
            "city": "Istanbul",
            "country": "Turkey"
        })
        event.insert(ignore_permissions=True)

        self.assertIsNotNone(event.name)
        self.assertEqual(event.event_type, "Shipment Created")
        self.assertEqual(event.carrier, "Yurtici Kargo")
        self.assertEqual(event.tracking_number, "YK123456789TR")
        self.assertTrue(event.is_milestone)

        # Cleanup
        frappe.delete_doc("Tracking Event", event.name, force=True)

    def test_tracking_event_auto_populate(self):
        """Test that fields are auto-populated from shipment."""
        event = frappe.get_doc({
            "doctype": "Tracking Event",
            "shipment": self.shipment_name,
            "event_type": "Pickup Completed",
            "event_description": "Package picked up from seller"
        })
        event.insert(ignore_permissions=True)

        # Check auto-populated fields
        self.assertEqual(event.carrier, "Yurtici Kargo")
        self.assertEqual(event.tracking_number, "YK123456789TR")
        self.assertEqual(event.seller, "test-tracking-seller")
        self.assertEqual(event.tenant, "test-tracking-tenant")

        # Cleanup
        frappe.delete_doc("Tracking Event", event.name, force=True)

    def test_milestone_detection(self):
        """Test that milestone events are correctly identified."""
        milestone_events = [
            "Shipment Created",
            "Pickup Completed",
            "Out for Delivery",
            "Delivered"
        ]

        non_milestone_events = [
            "In Transit",
            "Arrived at Facility",
            "Status Update"
        ]

        for event_type in milestone_events:
            event = frappe.get_doc({
                "doctype": "Tracking Event",
                "shipment": self.shipment_name,
                "event_type": event_type,
                "event_description": f"Test {event_type}"
            })
            event.insert(ignore_permissions=True)
            self.assertTrue(event.is_milestone, f"{event_type} should be a milestone")
            frappe.delete_doc("Tracking Event", event.name, force=True)

        for event_type in non_milestone_events:
            event = frappe.get_doc({
                "doctype": "Tracking Event",
                "shipment": self.shipment_name,
                "event_type": event_type,
                "event_description": f"Test {event_type}"
            })
            event.insert(ignore_permissions=True)
            self.assertFalse(event.is_milestone, f"{event_type} should not be a milestone")
            frappe.delete_doc("Tracking Event", event.name, force=True)

    def test_exception_severity(self):
        """Test that exception events have correct severity."""
        exception_events = [
            ("Delivery Exception", "Error"),
            ("Address Issue", "Error"),
            ("Lost", "Critical"),
            ("Damaged", "Critical"),
            ("Delivery Attempted", "Warning"),
            ("Weather Delay", "Warning")
        ]

        for event_type, expected_severity in exception_events:
            event = frappe.get_doc({
                "doctype": "Tracking Event",
                "shipment": self.shipment_name,
                "event_type": event_type,
                "event_description": f"Test {event_type}"
            })
            event.insert(ignore_permissions=True)
            self.assertEqual(
                event.severity, expected_severity,
                f"{event_type} should have severity {expected_severity}"
            )
            frappe.delete_doc("Tracking Event", event.name, force=True)

    def test_sync_id_generation(self):
        """Test that sync_id is generated for deduplication."""
        event = frappe.get_doc({
            "doctype": "Tracking Event",
            "shipment": self.shipment_name,
            "event_type": "In Transit",
            "event_description": "Package in transit",
            "city": "Ankara"
        })
        event.insert(ignore_permissions=True)

        self.assertIsNotNone(event.sync_id)
        self.assertEqual(len(event.sync_id), 32)

        # Cleanup
        frappe.delete_doc("Tracking Event", event.name, force=True)

    def test_duplicate_prevention(self):
        """Test that duplicate events are prevented via sync_id."""
        sync_id = "test-sync-id-12345"

        event1 = frappe.get_doc({
            "doctype": "Tracking Event",
            "shipment": self.shipment_name,
            "event_type": "In Transit",
            "event_description": "Package in transit",
            "sync_id": sync_id
        })
        event1.insert(ignore_permissions=True)

        # Try to create duplicate
        event2 = frappe.get_doc({
            "doctype": "Tracking Event",
            "shipment": self.shipment_name,
            "event_type": "In Transit",
            "event_description": "Package in transit",
            "sync_id": sync_id
        })

        with self.assertRaises(frappe.ValidationError):
            event2.insert(ignore_permissions=True)

        # Cleanup
        frappe.delete_doc("Tracking Event", event1.name, force=True)

    def test_location_validation(self):
        """Test latitude/longitude validation."""
        # Valid coordinates
        event = frappe.get_doc({
            "doctype": "Tracking Event",
            "shipment": self.shipment_name,
            "event_type": "In Transit",
            "event_description": "Package in transit",
            "latitude": 41.0082,
            "longitude": 28.9784
        })
        event.insert(ignore_permissions=True)
        frappe.delete_doc("Tracking Event", event.name, force=True)

        # Invalid latitude
        event_invalid = frappe.get_doc({
            "doctype": "Tracking Event",
            "shipment": self.shipment_name,
            "event_type": "In Transit",
            "event_description": "Package in transit",
            "latitude": 100,  # Invalid: must be -90 to 90
            "longitude": 28.9784
        })

        with self.assertRaises(frappe.ValidationError):
            event_invalid.insert(ignore_permissions=True)

    def test_event_summary(self):
        """Test get_event_summary method."""
        event = frappe.get_doc({
            "doctype": "Tracking Event",
            "shipment": self.shipment_name,
            "event_type": "Delivered",
            "event_description": "Package delivered successfully",
            "city": "Ankara",
            "country": "Turkey",
            "facility_name": "Ankara Distribution Center"
        })
        event.insert(ignore_permissions=True)

        summary = event.get_event_summary()

        self.assertEqual(summary["event_type"], "Delivered")
        self.assertEqual(summary["location"]["city"], "Ankara")
        self.assertTrue(summary["is_milestone"])

        # Cleanup
        frappe.delete_doc("Tracking Event", event.name, force=True)

    def test_timeline_display(self):
        """Test get_timeline_display method."""
        event = frappe.get_doc({
            "doctype": "Tracking Event",
            "shipment": self.shipment_name,
            "event_type": "Out for Delivery",
            "event_description": "Package is out for delivery",
            "city": "Ankara",
            "facility_name": "Local Delivery Station"
        })
        event.insert(ignore_permissions=True)

        timeline = event.get_timeline_display()

        self.assertEqual(timeline["type"], "Out for Delivery")
        self.assertIn("Ankara", timeline["location"])
        self.assertEqual(timeline["icon"], "navigation")

        # Cleanup
        frappe.delete_doc("Tracking Event", event.name, force=True)


class TestTrackingEventHelperFunctions(unittest.TestCase):
    """Test cases for Tracking Event helper functions."""

    @classmethod
    def setUpClass(cls):
        """Set up test fixtures."""
        # Use existing test fixtures from TestTrackingEvent
        cls.shipment_name = frappe.db.get_value(
            "Marketplace Shipment",
            {"shipment_id": "TEST-SHIP-001"},
            "name"
        )

    def test_log_tracking_event(self):
        """Test log_tracking_event helper function."""
        from tradehub_logistics.tradehub_logistics.doctype.tracking_event.tracking_event import log_tracking_event

        event = log_tracking_event(
            shipment=self.shipment_name,
            event_type="In Transit",
            description="Package is moving",
            city="Bursa",
            country="Turkey",
            source="Manual Entry"
        )

        self.assertIsNotNone(event)
        self.assertEqual(event.event_type, "In Transit")
        self.assertEqual(event.city, "Bursa")

        # Cleanup
        frappe.delete_doc("Tracking Event", event.name, force=True)

    def test_get_shipment_tracking_history(self):
        """Test get_shipment_tracking_history function."""
        from tradehub_logistics.tradehub_logistics.doctype.tracking_event.tracking_event import (
            log_tracking_event,
            get_shipment_tracking_history
        )

        # Create multiple events
        events = []
        event_types = ["Pickup Completed", "In Transit", "Out for Delivery"]

        for i, event_type in enumerate(event_types):
            event = log_tracking_event(
                shipment=self.shipment_name,
                event_type=event_type,
                description=f"Test event {i+1}"
            )
            events.append(event)

        # Get history
        history = get_shipment_tracking_history(self.shipment_name)

        self.assertEqual(len(history), len(events))

        # Cleanup
        for event in events:
            frappe.delete_doc("Tracking Event", event.name, force=True)

    def test_get_latest_tracking_event(self):
        """Test get_latest_tracking_event function."""
        from tradehub_logistics.tradehub_logistics.doctype.tracking_event.tracking_event import (
            log_tracking_event,
            get_latest_tracking_event
        )

        # Create events
        event1 = log_tracking_event(
            shipment=self.shipment_name,
            event_type="Pickup Completed",
            description="First event"
        )
        event2 = log_tracking_event(
            shipment=self.shipment_name,
            event_type="Delivered",
            description="Latest event"
        )

        # Get latest
        latest = get_latest_tracking_event(self.shipment_name)

        self.assertEqual(latest["event_type"], "Delivered")

        # Cleanup
        frappe.delete_doc("Tracking Event", event1.name, force=True)
        frappe.delete_doc("Tracking Event", event2.name, force=True)

    def test_map_carrier_event_type(self):
        """Test map_carrier_event_type function."""
        from tradehub_logistics.tradehub_logistics.doctype.tracking_event.tracking_event import map_carrier_event_type

        # Test code mapping
        self.assertEqual(map_carrier_event_type("DL"), "Delivered")
        self.assertEqual(map_carrier_event_type("OD"), "Out for Delivery")
        self.assertEqual(map_carrier_event_type("IT"), "In Transit")
        self.assertEqual(map_carrier_event_type("PU"), "Pickup Completed")

        # Test description-based mapping
        self.assertEqual(
            map_carrier_event_type("", "Package was delivered"),
            "Delivered"
        )
        self.assertEqual(
            map_carrier_event_type("", "Out for delivery to recipient"),
            "Out for Delivery"
        )
        self.assertEqual(
            map_carrier_event_type("", "Package in transit"),
            "In Transit"
        )

        # Test fallback
        self.assertEqual(
            map_carrier_event_type("XX", "Unknown event"),
            "Status Update"
        )


class TestTrackingEventAPI(unittest.TestCase):
    """Test cases for Tracking Event API endpoints."""

    @classmethod
    def setUpClass(cls):
        """Set up test fixtures."""
        cls.shipment_name = frappe.db.get_value(
            "Marketplace Shipment",
            {"shipment_id": "TEST-SHIP-001"},
            "name"
        )

    def test_get_tracking_events_api(self):
        """Test get_tracking_events API endpoint."""
        from tradehub_logistics.tradehub_logistics.doctype.tracking_event.tracking_event import (
            log_tracking_event,
            get_tracking_events
        )

        # Create test event
        event = log_tracking_event(
            shipment=self.shipment_name,
            event_type="In Transit",
            description="API test event"
        )

        # Call API
        result = get_tracking_events(shipment=self.shipment_name)

        self.assertIn("events", result)
        self.assertIn("total", result)
        self.assertGreaterEqual(result["total"], 1)

        # Cleanup
        frappe.delete_doc("Tracking Event", event.name, force=True)

    def test_get_shipment_timeline_api(self):
        """Test get_shipment_timeline API endpoint."""
        from tradehub_logistics.tradehub_logistics.doctype.tracking_event.tracking_event import (
            log_tracking_event,
            get_shipment_timeline
        )

        # Create test events
        event1 = log_tracking_event(
            shipment=self.shipment_name,
            event_type="Pickup Completed",
            description="Picked up"
        )
        event2 = log_tracking_event(
            shipment=self.shipment_name,
            event_type="In Transit",
            description="In transit"
        )

        # Call API
        timeline = get_shipment_timeline(self.shipment_name)

        self.assertIsInstance(timeline, list)
        self.assertGreaterEqual(len(timeline), 2)

        # Cleanup
        frappe.delete_doc("Tracking Event", event1.name, force=True)
        frappe.delete_doc("Tracking Event", event2.name, force=True)

    def test_create_tracking_event_api(self):
        """Test create_tracking_event API endpoint."""
        from tradehub_logistics.tradehub_logistics.doctype.tracking_event.tracking_event import create_tracking_event

        result = create_tracking_event(
            shipment=self.shipment_name,
            event_type="Status Update",
            event_description="API created event",
            city="Izmir"
        )

        self.assertEqual(result["status"], "success")
        self.assertIn("event_name", result)

        # Cleanup
        frappe.delete_doc("Tracking Event", result["event_name"], force=True)

    def test_get_tracking_statistics_api(self):
        """Test get_tracking_statistics API endpoint."""
        from tradehub_logistics.tradehub_logistics.doctype.tracking_event.tracking_event import (
            log_tracking_event,
            get_tracking_statistics
        )

        # Create test events
        events = []
        for event_type in ["In Transit", "Delivery Exception", "Delivered"]:
            event = log_tracking_event(
                shipment=self.shipment_name,
                event_type=event_type,
                description=f"Stats test {event_type}"
            )
            events.append(event)

        # Call API
        stats = get_tracking_statistics(shipment=self.shipment_name, days=1)

        self.assertIn("total_events", stats)
        self.assertIn("exception_count", stats)
        self.assertIn("by_type", stats)

        # Cleanup
        for event in events:
            frappe.delete_doc("Tracking Event", event.name, force=True)


def tearDownModule():
    """Clean up test fixtures after all tests."""
    # Clean up tracking events
    events = frappe.get_all(
        "Tracking Event",
        filters={"shipment": ["like", "%TEST-SHIP%"]},
        fields=["name"]
    )
    for event in events:
        frappe.delete_doc("Tracking Event", event.name, force=True)

    # Clean up test shipment
    shipments = frappe.get_all(
        "Marketplace Shipment",
        filters={"shipment_id": ["like", "TEST-SHIP%"]},
        fields=["name"]
    )
    for shipment in shipments:
        frappe.delete_doc("Marketplace Shipment", shipment.name, force=True)

    # Clean up test seller profile
    if frappe.db.exists("Seller Profile", "test-tracking-seller"):
        frappe.delete_doc("Seller Profile", "test-tracking-seller", force=True)

    # Clean up test tenant
    if frappe.db.exists("Tenant", "test-tracking-tenant"):
        frappe.delete_doc("Tenant", "test-tracking-tenant", force=True)

    frappe.db.commit()

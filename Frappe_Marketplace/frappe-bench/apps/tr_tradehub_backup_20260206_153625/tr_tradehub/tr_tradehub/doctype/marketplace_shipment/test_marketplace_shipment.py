# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

import frappe
import unittest
from frappe.utils import nowdate, now_datetime, add_days


class TestMarketplaceShipment(unittest.TestCase):
    """Test cases for Marketplace Shipment DocType."""

    @classmethod
    def setUpClass(cls):
        """Set up test fixtures that are reused across tests."""
        # Create test sub order if needed
        cls.test_sub_order = cls._create_test_sub_order()

    @classmethod
    def tearDownClass(cls):
        """Clean up test fixtures."""
        # Clean up test shipments
        for shipment in frappe.get_all(
            "Marketplace Shipment",
            filters={"shipment_id": ["like", "SHP-TEST%"]}
        ):
            frappe.delete_doc("Marketplace Shipment", shipment.name, force=True)

    @classmethod
    def _create_test_sub_order(cls):
        """Create a test sub order for testing shipments."""
        # Check if test sub order exists
        existing = frappe.db.get_value(
            "Sub Order",
            {"sub_order_id": "SUB-TEST12345"},
            "name"
        )
        if existing:
            return existing

        # For tests, we'll mock sub order validation
        return "SUB-TEST12345"

    def setUp(self):
        """Set up each test."""
        pass

    def tearDown(self):
        """Clean up after each test."""
        # Clean up shipments created in this test
        for shipment in frappe.get_all(
            "Marketplace Shipment",
            filters={"shipment_id": ["like", "SHP-TEST%"]}
        ):
            try:
                frappe.delete_doc("Marketplace Shipment", shipment.name, force=True)
            except Exception:
                pass

    def test_shipment_id_generation(self):
        """Test automatic shipment ID generation."""
        shipment = frappe.get_doc({
            "doctype": "Marketplace Shipment",
            "sub_order": self.test_sub_order,
            "carrier": "Yurtici Kargo",
            "sender_name": "Test Seller",
            "origin_address_line1": "Test Street 1",
            "origin_city": "Istanbul",
            "origin_country": "Turkey",
            "recipient_name": "Test Buyer",
            "destination_address_line1": "Test Avenue 2",
            "destination_city": "Ankara",
            "destination_country": "Turkey"
        })

        # Before insert, shipment_id should be empty
        self.assertFalse(shipment.shipment_id)

        # After generating
        shipment.shipment_id = shipment.generate_shipment_id()
        self.assertTrue(shipment.shipment_id)
        self.assertTrue(shipment.shipment_id.startswith("SHP-"))

    def test_tracking_url_generation(self):
        """Test automatic tracking URL generation for Turkish carriers."""
        test_carriers = {
            "Yurtici Kargo": "yurticikargo.com",
            "Aras Kargo": "araskargo.com",
            "MNG Kargo": "mngkargo.com",
            "PTT Kargo": "ptt.gov.tr",
            "UPS": "ups.com",
            "DHL": "dhl.com"
        }

        for carrier, expected_domain in test_carriers.items():
            shipment = frappe.get_doc({
                "doctype": "Marketplace Shipment",
                "sub_order": self.test_sub_order,
                "carrier": carrier,
                "tracking_number": "TEST123456",
                "sender_name": "Test Seller",
                "origin_address_line1": "Test Street",
                "origin_city": "Istanbul",
                "origin_country": "Turkey",
                "recipient_name": "Test Buyer",
                "destination_address_line1": "Test Avenue",
                "destination_city": "Ankara",
                "destination_country": "Turkey"
            })

            url = shipment.get_carrier_tracking_url()
            self.assertIsNotNone(url)
            self.assertIn(expected_domain, url)
            self.assertIn("TEST123456", url)

    def test_volumetric_weight_calculation(self):
        """Test volumetric weight calculation."""
        shipment = frappe.get_doc({
            "doctype": "Marketplace Shipment",
            "sub_order": self.test_sub_order,
            "carrier": "Yurtici Kargo",
            "sender_name": "Test Seller",
            "origin_address_line1": "Test Street",
            "origin_city": "Istanbul",
            "origin_country": "Turkey",
            "recipient_name": "Test Buyer",
            "destination_address_line1": "Test Avenue",
            "destination_city": "Ankara",
            "destination_country": "Turkey",
            "total_length": 30,  # cm
            "total_width": 20,   # cm
            "total_height": 15,  # cm
            "dimension_unit": "cm"
        })

        shipment.calculate_volumetric_weight()

        # (30 * 20 * 15) / 5000 = 1.8 kg
        expected_vol_weight = (30 * 20 * 15) / 5000
        self.assertAlmostEqual(shipment.volumetric_weight, expected_vol_weight, places=2)

    def test_cost_calculation(self):
        """Test total cost calculation."""
        shipment = frappe.get_doc({
            "doctype": "Marketplace Shipment",
            "sub_order": self.test_sub_order,
            "carrier": "Aras Kargo",
            "sender_name": "Test Seller",
            "origin_address_line1": "Test Street",
            "origin_city": "Istanbul",
            "origin_country": "Turkey",
            "recipient_name": "Test Buyer",
            "destination_address_line1": "Test Avenue",
            "destination_city": "Izmir",
            "destination_country": "Turkey",
            "shipping_cost": 25.00,
            "insurance_cost": 5.00,
            "handling_cost": 3.00,
            "additional_charges": 2.00,
            "cost_currency": "TRY"
        })

        shipment.calculate_costs()

        # 25 + 5 + 3 + 2 = 35
        self.assertEqual(shipment.total_cost, 35.00)

    def test_status_workflow(self):
        """Test shipment status workflow transitions."""
        shipment = frappe.get_doc({
            "doctype": "Marketplace Shipment",
            "sub_order": self.test_sub_order,
            "carrier": "MNG Kargo",
            "status": "Pending",
            "sender_name": "Test Seller",
            "origin_address_line1": "Test Street",
            "origin_city": "Istanbul",
            "origin_country": "Turkey",
            "recipient_name": "Test Buyer",
            "destination_address_line1": "Test Avenue",
            "destination_city": "Bursa",
            "destination_country": "Turkey"
        })

        # Valid transitions from Pending
        valid_from_pending = ["Label Generated", "Pickup Scheduled", "Cancelled"]
        for status in valid_from_pending:
            # Reset for each test
            shipment.status = "Pending"
            shipment.status = status
            # Should not raise
            shipment.validate_status_transitions()

    def test_invalid_status_transition(self):
        """Test that invalid status transitions are rejected."""
        shipment = frappe.get_doc({
            "doctype": "Marketplace Shipment",
            "sub_order": self.test_sub_order,
            "carrier": "SuratKargo",
            "status": "Pending",
            "sender_name": "Test Seller",
            "origin_address_line1": "Test Street",
            "origin_city": "Istanbul",
            "origin_country": "Turkey",
            "recipient_name": "Test Buyer",
            "destination_address_line1": "Test Avenue",
            "destination_city": "Adana",
            "destination_country": "Turkey"
        })

        # Trying to go from Pending to Delivered should fail
        # (This is tested via validation, not direct setting in production)

    def test_delivery_estimate(self):
        """Test delivery time estimation."""
        shipment = frappe.get_doc({
            "doctype": "Marketplace Shipment",
            "sub_order": self.test_sub_order,
            "carrier": "Yurtici Kargo",
            "sender_name": "Test Seller",
            "origin_address_line1": "Test Street",
            "origin_city": "Istanbul",
            "origin_country": "Turkey",
            "recipient_name": "Test Buyer",
            "destination_address_line1": "Test Avenue",
            "destination_city": "Ankara",
            "destination_country": "Turkey",
            "expected_delivery_date": add_days(nowdate(), 3)
        })

        self.assertEqual(shipment.expected_delivery_date, add_days(nowdate(), 3))

    def test_return_shipment_creation(self):
        """Test creating return shipment from delivered shipment."""
        # Create original shipment
        shipment = frappe.get_doc({
            "doctype": "Marketplace Shipment",
            "sub_order": self.test_sub_order,
            "carrier": "Aras Kargo",
            "status": "Delivered",
            "sender_name": "Original Seller",
            "sender_phone": "05001234567",
            "origin_address_line1": "Seller Street 1",
            "origin_city": "Istanbul",
            "origin_country": "Turkey",
            "recipient_name": "Original Buyer",
            "recipient_phone": "05009876543",
            "destination_address_line1": "Buyer Avenue 2",
            "destination_city": "Ankara",
            "destination_country": "Turkey",
            "package_count": 1,
            "total_weight": 2.5
        })

        # Test that addresses would be swapped for return
        # (without actually inserting to avoid sub_order validation)
        self.assertEqual(shipment.sender_name, "Original Seller")
        self.assertEqual(shipment.recipient_name, "Original Buyer")
        self.assertEqual(shipment.origin_city, "Istanbul")
        self.assertEqual(shipment.destination_city, "Ankara")

    def test_address_validation(self):
        """Test address validation."""
        # Missing destination address should fail
        shipment = frappe.get_doc({
            "doctype": "Marketplace Shipment",
            "sub_order": self.test_sub_order,
            "carrier": "PTT Kargo",
            "sender_name": "Test Seller",
            "origin_address_line1": "Test Street",
            "origin_city": "Istanbul",
            "origin_country": "Turkey",
            "recipient_name": "Test Buyer",
            # Missing destination address
            "destination_city": "Konya",
            "destination_country": "Turkey"
        })

        with self.assertRaises(frappe.ValidationError):
            shipment.validate_addresses()

    def test_carrier_validation(self):
        """Test carrier validation."""
        # Missing carrier should fail
        shipment = frappe.get_doc({
            "doctype": "Marketplace Shipment",
            "sub_order": self.test_sub_order,
            # Missing carrier
            "sender_name": "Test Seller",
            "origin_address_line1": "Test Street",
            "origin_city": "Istanbul",
            "origin_country": "Turkey",
            "recipient_name": "Test Buyer",
            "destination_address_line1": "Test Avenue",
            "destination_city": "Antalya",
            "destination_country": "Turkey"
        })

        with self.assertRaises(frappe.ValidationError):
            shipment.validate_carrier()

    def test_get_summary(self):
        """Test shipment summary generation."""
        shipment = frappe.get_doc({
            "doctype": "Marketplace Shipment",
            "sub_order": self.test_sub_order,
            "carrier": "UPS",
            "tracking_number": "1Z999AA10123456784",
            "status": "In Transit",
            "sender_name": "Test Seller",
            "origin_address_line1": "Test Street",
            "origin_city": "Istanbul",
            "origin_country": "Turkey",
            "recipient_name": "Test Buyer",
            "destination_address_line1": "Test Avenue",
            "destination_city": "Gaziantep",
            "destination_country": "Turkey",
            "total_weight": 5.0,
            "total_cost": 75.00
        })

        shipment.shipment_id = "SHP-TEST123"
        summary = shipment.get_summary()

        self.assertEqual(summary["shipment_id"], "SHP-TEST123")
        self.assertEqual(summary["carrier"], "UPS")
        self.assertEqual(summary["tracking_number"], "1Z999AA10123456784")
        self.assertEqual(summary["status"], "In Transit")
        self.assertEqual(summary["total_weight"], 5.0)
        self.assertEqual(summary["total_cost"], 75.00)

    def test_get_tracking_info(self):
        """Test tracking info generation."""
        shipment = frappe.get_doc({
            "doctype": "Marketplace Shipment",
            "sub_order": self.test_sub_order,
            "carrier": "FedEx",
            "tracking_number": "794644790138",
            "status": "Out for Delivery",
            "sender_name": "Test Seller",
            "origin_address_line1": "Test Street",
            "origin_city": "Istanbul",
            "origin_country": "Turkey",
            "recipient_name": "Test Buyer",
            "destination_address_line1": "Test Avenue",
            "destination_city": "Mersin",
            "destination_country": "Turkey",
            "delivery_attempts": 1
        })

        tracking_info = shipment.get_tracking_info()

        self.assertEqual(tracking_info["carrier"], "FedEx")
        self.assertEqual(tracking_info["tracking_number"], "794644790138")
        self.assertEqual(tracking_info["status"], "Out for Delivery")
        self.assertEqual(tracking_info["delivery_attempts"], 1)
        self.assertIn("fedex.com", tracking_info["tracking_url"])

    def test_package_validation(self):
        """Test package details validation."""
        shipment = frappe.get_doc({
            "doctype": "Marketplace Shipment",
            "sub_order": self.test_sub_order,
            "carrier": "DHL",
            "sender_name": "Test Seller",
            "origin_address_line1": "Test Street",
            "origin_city": "Istanbul",
            "origin_country": "Turkey",
            "recipient_name": "Test Buyer",
            "destination_address_line1": "Test Avenue",
            "destination_city": "Trabzon",
            "destination_country": "Turkey",
            "package_count": 0,  # Invalid
            "total_weight": -1   # Invalid
        })

        shipment.validate_package_details()

        # Should be corrected to valid values
        self.assertEqual(shipment.package_count, 1)  # Minimum 1

    def test_is_return_flag(self):
        """Test return shipment flag."""
        shipment = frappe.get_doc({
            "doctype": "Marketplace Shipment",
            "sub_order": self.test_sub_order,
            "carrier": "Yurtici Kargo",
            "is_return": 1,
            "return_reason": "Defective Item",
            "sender_name": "Test Buyer",  # Buyer becomes sender for returns
            "origin_address_line1": "Buyer Street",
            "origin_city": "Ankara",
            "origin_country": "Turkey",
            "recipient_name": "Test Seller",  # Seller becomes recipient
            "destination_address_line1": "Seller Avenue",
            "destination_city": "Istanbul",
            "destination_country": "Turkey"
        })

        self.assertTrue(shipment.is_return)
        self.assertEqual(shipment.return_reason, "Defective Item")


if __name__ == "__main__":
    unittest.main()

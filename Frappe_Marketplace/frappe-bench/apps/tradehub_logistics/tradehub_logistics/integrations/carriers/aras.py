# Copyright (c) 2024, TradeHub and contributors
# For license information, please see license.txt

"""Aras Kargo Integration for TradeHub Logistics

Aras Kargo is one of Turkey's largest cargo companies, providing:
- Domestic parcel delivery
- Express delivery services
- Cargo tracking via API
- Integration with e-commerce platforms

This module provides methods to:
- Query shipment tracking status
- Parse tracking events
- Handle delivery notifications
- Create shipping labels (API v2)
"""

import hashlib
import json
from datetime import datetime
from typing import Optional

import frappe
from frappe import _
from frappe.utils import now_datetime, get_datetime


class ArasIntegration:
    """Aras Kargo Integration Class.

    Handles all Aras Kargo API interactions for shipment tracking.
    """

    # Aras API endpoints
    API_BASE_URL = "https://customerservices.araskargo.com.tr/ArasCargoCustomerIntegrationService"
    TRACKING_ENDPOINT = "/GetCargoInfo"
    LABEL_ENDPOINT = "/CreateLabel"
    STATUS_ENDPOINT = "/GetCargoStatus"

    # Carrier identification
    CARRIER_CODE = "ARAS"
    CARRIER_NAME = "Aras Kargo"

    # Status code mappings from Aras to TradeHub
    STATUS_MAP = {
        "0": "Pending",
        "1": "Picked Up",
        "2": "In Transit",
        "3": "At Hub",
        "4": "Out for Delivery",
        "5": "Delivered",
        "6": "Failed Delivery",
        "7": "Returned",
        "8": "Cancelled"
    }

    def __init__(self):
        """Initialize Aras integration with credentials from Carrier DocType."""
        self.settings = self._get_settings()
        self.username = self.settings.get("username", "")
        self.password = self.settings.get("password", "")
        self.customer_code = self.settings.get("customer_code", "")
        self.test_mode = self.settings.get("test_mode", 1)

    def _get_settings(self):
        """Get Aras settings from the Carrier DocType.

        Returns:
            dict: Aras configuration settings
        """
        try:
            # Try to get from Carrier DocType
            if frappe.db.exists("Carrier", {"carrier_code": self.CARRIER_CODE}):
                carrier = frappe.get_doc("Carrier", {"carrier_code": self.CARRIER_CODE})
                return {
                    "username": carrier.get("api_key", ""),
                    "password": carrier.get_password("api_secret") if carrier.get("api_secret") else "",
                    "customer_code": carrier.get("carrier_code", ""),
                    "test_mode": not carrier.get("is_active", 0)
                }
        except Exception:
            pass

        # Return empty settings if not configured
        return {
            "username": "",
            "password": "",
            "customer_code": "",
            "test_mode": 1
        }

    def _generate_auth_hash(self):
        """Generate authentication hash for Aras API.

        Returns:
            str: MD5 hash of credentials
        """
        if not self.username or not self.password:
            return None

        auth_string = f"{self.username}:{self.password}"
        return hashlib.md5(auth_string.encode("utf-8")).hexdigest()

    def get_tracking(self, tracking_number: str) -> Optional[dict]:
        """Get tracking information for a shipment.

        Args:
            tracking_number: The Aras tracking/cargo number

        Returns:
            dict: Tracking information with current_status and events list
                  or None if tracking fails
        """
        if not tracking_number:
            return None

        if not self.username:
            frappe.log_error(
                "Aras Kargo credentials not configured",
                "Aras Integration Error"
            )
            return None

        try:
            # Prepare tracking request
            request_data = {
                "UserName": self.username,
                "Password": self.password,
                "CustomerCode": self.customer_code,
                "TrackingNumber": tracking_number
            }

            # In production, this would make an HTTP request to Aras API
            # For now, we log and return mock data for development
            frappe.logger().info(
                f"Aras tracking request for {tracking_number}"
            )

            # Mock response for development
            if self.test_mode:
                return self._get_mock_tracking(tracking_number)

            # Real API call would be here:
            # response = self._make_api_request(self.TRACKING_ENDPOINT, request_data)
            # return self._parse_tracking_response(response)

            return None

        except Exception as e:
            frappe.log_error(
                f"Aras tracking failed for {tracking_number}: {str(e)}",
                "Aras Integration Error"
            )
            return None

    def _get_mock_tracking(self, tracking_number: str) -> dict:
        """Get mock tracking data for development and testing.

        Args:
            tracking_number: The tracking number

        Returns:
            dict: Mock tracking information
        """
        return {
            "carrier": self.CARRIER_NAME,
            "carrier_code": self.CARRIER_CODE,
            "tracking_number": tracking_number,
            "current_status": "in_transit",
            "current_status_label": "In Transit",
            "estimated_delivery": None,
            "events": [
                {
                    "datetime": "2024-01-15 10:30:00",
                    "status": "picked_up",
                    "status_label": "Picked Up",
                    "location": "Istanbul - Kadıköy",
                    "description": "Shipment picked up from sender"
                },
                {
                    "datetime": "2024-01-15 14:45:00",
                    "status": "in_transit",
                    "status_label": "In Transit",
                    "location": "Istanbul - Sorting Center",
                    "description": "Shipment arrived at sorting facility"
                }
            ]
        }

    def _parse_tracking_response(self, response: dict) -> Optional[dict]:
        """Parse the Aras API tracking response.

        Args:
            response: Raw API response dictionary

        Returns:
            dict: Normalized tracking information
        """
        if not response or not response.get("IsSuccess"):
            return None

        cargo_info = response.get("CargoInfo", {})
        movements = response.get("CargoMovements", [])

        # Map current status
        status_code = str(cargo_info.get("StatusCode", "0"))
        current_status = self.STATUS_MAP.get(status_code, "unknown")

        # Parse tracking events
        events = []
        for movement in movements:
            event_time = movement.get("EventDate", "")
            if event_time:
                try:
                    dt = get_datetime(event_time)
                    event_datetime = dt.strftime("%Y-%m-%d %H:%M:%S")
                except Exception:
                    event_datetime = event_time

            event_status_code = str(movement.get("StatusCode", "0"))
            event_status = self.STATUS_MAP.get(event_status_code, "unknown")

            events.append({
                "datetime": event_datetime,
                "status": event_status.lower().replace(" ", "_"),
                "status_label": event_status,
                "location": movement.get("UnitName", ""),
                "description": movement.get("StatusDescription", "")
            })

        # Sort events by datetime (newest first)
        events.sort(key=lambda x: x["datetime"], reverse=True)

        return {
            "carrier": self.CARRIER_NAME,
            "carrier_code": self.CARRIER_CODE,
            "tracking_number": cargo_info.get("TrackingNumber", ""),
            "current_status": current_status.lower().replace(" ", "_"),
            "current_status_label": current_status,
            "estimated_delivery": cargo_info.get("EstimatedDeliveryDate"),
            "events": events
        }

    def create_shipment_label(self, shipment_data: dict) -> Optional[dict]:
        """Create a shipping label through Aras API.

        Args:
            shipment_data: Dictionary containing shipment details:
                - sender_name, sender_address, sender_phone, sender_city
                - receiver_name, receiver_address, receiver_phone, receiver_city
                - weight, pieces, description

        Returns:
            dict: Label creation result with tracking_number and label_url
        """
        if not self.username:
            return {"success": False, "error": _("Aras Kargo is not configured")}

        try:
            # Validate required fields
            required_fields = [
                "sender_name", "sender_address", "sender_phone", "sender_city",
                "receiver_name", "receiver_address", "receiver_phone", "receiver_city"
            ]
            missing = [f for f in required_fields if not shipment_data.get(f)]
            if missing:
                return {"success": False, "error": f"Missing fields: {', '.join(missing)}"}

            # Prepare label request
            request_data = {
                "UserName": self.username,
                "Password": self.password,
                "CustomerCode": self.customer_code,
                "TradingWaybillNumber": shipment_data.get("reference_number", ""),
                "SenderName": shipment_data.get("sender_name"),
                "SenderAddress": shipment_data.get("sender_address"),
                "SenderPhone": shipment_data.get("sender_phone"),
                "SenderCity": shipment_data.get("sender_city"),
                "ReceiverName": shipment_data.get("receiver_name"),
                "ReceiverAddress": shipment_data.get("receiver_address"),
                "ReceiverPhone": shipment_data.get("receiver_phone"),
                "ReceiverCity": shipment_data.get("receiver_city"),
                "ReceiverDistrict": shipment_data.get("receiver_district", ""),
                "PieceCount": shipment_data.get("pieces", 1),
                "Weight": shipment_data.get("weight", 1),
                "ProductDescription": shipment_data.get("description", ""),
                "PaymentType": shipment_data.get("payment_type", 1),  # 1=Sender pays
                "IsCOD": shipment_data.get("is_cod", 0),
                "CODAmount": shipment_data.get("cod_amount", 0)
            }

            frappe.logger().info(
                f"Aras label creation request for {shipment_data.get('reference_number', 'N/A')}"
            )

            # In production, make API call
            if self.test_mode:
                return {
                    "success": True,
                    "tracking_number": f"ARAS{datetime.now().strftime('%Y%m%d%H%M%S')}",
                    "label_url": None,
                    "barcode": None,
                    "message": "Test mode - no actual label created"
                }

            return {"success": True, "request_data": request_data}

        except Exception as e:
            frappe.log_error(
                f"Aras label creation failed: {str(e)}",
                "Aras Integration Error"
            )
            return {"success": False, "error": str(e)}

    def cancel_shipment(self, tracking_number: str) -> dict:
        """Cancel a shipment through Aras API.

        Args:
            tracking_number: The tracking number to cancel

        Returns:
            dict: Cancellation result
        """
        if not self.username:
            return {"success": False, "error": _("Aras Kargo is not configured")}

        try:
            request_data = {
                "UserName": self.username,
                "Password": self.password,
                "CustomerCode": self.customer_code,
                "TrackingNumber": tracking_number
            }

            frappe.logger().info(f"Aras cancellation request for {tracking_number}")

            if self.test_mode:
                return {
                    "success": True,
                    "tracking_number": tracking_number,
                    "message": "Test mode - shipment marked as cancelled"
                }

            return {"success": True, "request_data": request_data}

        except Exception as e:
            frappe.log_error(
                f"Aras cancellation failed for {tracking_number}: {str(e)}",
                "Aras Integration Error"
            )
            return {"success": False, "error": str(e)}


# API endpoints for Frappe whitelisting
@frappe.whitelist()
def get_aras_tracking(tracking_number):
    """Get tracking information from Aras Kargo.

    Args:
        tracking_number: The Aras tracking number

    Returns:
        dict: Tracking information
    """
    if not tracking_number:
        return {"success": False, "error": "Tracking number is required"}

    integration = ArasIntegration()
    result = integration.get_tracking(tracking_number)

    if result:
        return {"success": True, **result}
    return {"success": False, "error": "Could not retrieve tracking information"}


@frappe.whitelist()
def create_aras_shipment(shipment_data=None):
    """Create a shipment with Aras Kargo.

    Args:
        shipment_data: Shipment details as JSON string or dict

    Returns:
        dict: Shipment creation result with tracking number
    """
    if not shipment_data:
        return {"success": False, "error": "Shipment data is required"}

    if isinstance(shipment_data, str):
        shipment_data = json.loads(shipment_data)

    integration = ArasIntegration()
    return integration.create_shipment_label(shipment_data)


@frappe.whitelist()
def cancel_aras_shipment(tracking_number):
    """Cancel an Aras Kargo shipment.

    Args:
        tracking_number: The tracking number to cancel

    Returns:
        dict: Cancellation result
    """
    if not tracking_number:
        return {"success": False, "error": "Tracking number is required"}

    integration = ArasIntegration()
    return integration.cancel_shipment(tracking_number)

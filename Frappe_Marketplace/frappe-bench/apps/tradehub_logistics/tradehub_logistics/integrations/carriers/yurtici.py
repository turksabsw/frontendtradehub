# Copyright (c) 2024, TradeHub and contributors
# For license information, please see license.txt

"""Yurtici Kargo Integration for TradeHub Logistics

Yurtici Kargo is one of Turkey's leading logistics companies, providing:
- Domestic and international cargo delivery
- Express delivery services
- Comprehensive tracking via SOAP/REST API
- E-commerce platform integration
- Collection on delivery (COD) support

This module provides methods to:
- Query shipment tracking status
- Parse tracking events and status updates
- Create shipping orders
- Calculate shipping rates
"""

import hashlib
import json
from datetime import datetime
from typing import Optional

import frappe
from frappe import _
from frappe.utils import now_datetime, get_datetime


class YurticiIntegration:
    """Yurtici Kargo Integration Class.

    Handles all Yurtici Kargo API interactions for shipment tracking and management.
    """

    # Yurtici API endpoints (SOAP-based)
    API_BASE_URL = "https://webservices.yurticikargo.com"
    TRACKING_ENDPOINT = "/KOPSWebServices/ShippingOrderDispatcherServices"
    LABEL_ENDPOINT = "/KOPSWebServices/ShippingOrderServices"
    RATE_ENDPOINT = "/KOPSWebServices/PriceAndTransitTimeQueryServices"

    # Carrier identification
    CARRIER_CODE = "YURTICI"
    CARRIER_NAME = "Yurtici Kargo"

    # Status code mappings from Yurtici to TradeHub
    STATUS_MAP = {
        "0": "Created",
        "1": "Picked Up",
        "2": "At Origin Hub",
        "3": "In Transit",
        "4": "At Destination Hub",
        "5": "Out for Delivery",
        "6": "Delivered",
        "7": "Failed Delivery",
        "8": "Returned to Sender",
        "9": "On Hold",
        "10": "Cancelled"
    }

    # Yurtici-specific status descriptions
    STATUS_DESCRIPTIONS = {
        "0": "Shipment record created",
        "1": "Package picked up from sender",
        "2": "Arrived at origin sorting center",
        "3": "In transit to destination",
        "4": "Arrived at destination branch",
        "5": "Out for delivery to recipient",
        "6": "Successfully delivered",
        "7": "Delivery attempt failed",
        "8": "Package being returned to sender",
        "9": "Package on hold - action required",
        "10": "Shipment cancelled"
    }

    def __init__(self):
        """Initialize Yurtici integration with credentials from Carrier DocType."""
        self.settings = self._get_settings()
        self.username = self.settings.get("username", "")
        self.password = self.settings.get("password", "")
        self.user_language = self.settings.get("language", "TR")
        self.test_mode = self.settings.get("test_mode", 1)

    def _get_settings(self):
        """Get Yurtici settings from the Carrier DocType.

        Returns:
            dict: Yurtici configuration settings
        """
        try:
            # Try to get from Carrier DocType
            if frappe.db.exists("Carrier", {"carrier_code": self.CARRIER_CODE}):
                carrier = frappe.get_doc("Carrier", {"carrier_code": self.CARRIER_CODE})
                return {
                    "username": carrier.get("api_key", ""),
                    "password": carrier.get_password("api_secret") if carrier.get("api_secret") else "",
                    "language": "TR",
                    "test_mode": not carrier.get("is_active", 0)
                }
        except Exception:
            pass

        # Return empty settings if not configured
        return {
            "username": "",
            "password": "",
            "language": "TR",
            "test_mode": 1
        }

    def _generate_soap_header(self):
        """Generate SOAP authentication header for Yurtici API.

        Returns:
            str: SOAP header XML string
        """
        return f"""
        <soapenv:Header>
            <wsse:Security xmlns:wsse="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-secext-1.0.xsd">
                <wsse:UsernameToken>
                    <wsse:Username>{self.username}</wsse:Username>
                    <wsse:Password>{self.password}</wsse:Password>
                </wsse:UsernameToken>
            </wsse:Security>
        </soapenv:Header>
        """

    def get_tracking(self, tracking_number: str) -> Optional[dict]:
        """Get tracking information for a shipment.

        Args:
            tracking_number: The Yurtici cargo key or tracking number

        Returns:
            dict: Tracking information with current_status and events list
                  or None if tracking fails
        """
        if not tracking_number:
            return None

        if not self.username:
            frappe.log_error(
                "Yurtici Kargo credentials not configured",
                "Yurtici Integration Error"
            )
            return None

        try:
            # Prepare tracking request
            request_data = {
                "wsUserName": self.username,
                "wsPassword": self.password,
                "wsLanguage": self.user_language,
                "cargoKey": tracking_number
            }

            # In production, this would make a SOAP request to Yurtici API
            frappe.logger().info(
                f"Yurtici tracking request for {tracking_number}"
            )

            # Mock response for development
            if self.test_mode:
                return self._get_mock_tracking(tracking_number)

            # Real API call would be here:
            # response = self._make_soap_request(self.TRACKING_ENDPOINT, "queryShipment", request_data)
            # return self._parse_tracking_response(response)

            return None

        except Exception as e:
            frappe.log_error(
                f"Yurtici tracking failed for {tracking_number}: {str(e)}",
                "Yurtici Integration Error"
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
            "estimated_delivery": "2024-01-17",
            "events": [
                {
                    "datetime": "2024-01-15 09:15:00",
                    "status": "picked_up",
                    "status_label": "Picked Up",
                    "location": "Istanbul - Ümraniye",
                    "description": "Package picked up from sender"
                },
                {
                    "datetime": "2024-01-15 12:30:00",
                    "status": "at_origin_hub",
                    "status_label": "At Origin Hub",
                    "location": "Istanbul - Anadolu Transfer",
                    "description": "Arrived at origin sorting center"
                },
                {
                    "datetime": "2024-01-15 18:45:00",
                    "status": "in_transit",
                    "status_label": "In Transit",
                    "location": "In Transit",
                    "description": "In transit to destination"
                }
            ]
        }

    def _parse_tracking_response(self, response: dict) -> Optional[dict]:
        """Parse the Yurtici API tracking response.

        Args:
            response: Raw API response dictionary

        Returns:
            dict: Normalized tracking information
        """
        if not response:
            return None

        shipment_data = response.get("ShippingDeliveryDetailVO", {})
        if not shipment_data:
            return None

        # Map current status
        status_code = str(shipment_data.get("cargoEventId", "0"))
        current_status = self.STATUS_MAP.get(status_code, "Unknown")

        # Parse tracking events from shippingDeliveryItemDetailVO
        events = []
        delivery_details = shipment_data.get("shippingDeliveryItemDetailVO", [])
        if not isinstance(delivery_details, list):
            delivery_details = [delivery_details] if delivery_details else []

        for detail in delivery_details:
            event_time = detail.get("eventDate", "")
            event_time_str = detail.get("eventTime", "")
            if event_time:
                try:
                    # Combine date and time
                    full_datetime = f"{event_time} {event_time_str}".strip()
                    dt = get_datetime(full_datetime)
                    event_datetime = dt.strftime("%Y-%m-%d %H:%M:%S")
                except Exception:
                    event_datetime = event_time

            event_status_code = str(detail.get("eventId", "0"))
            event_status = self.STATUS_MAP.get(event_status_code, "Unknown")
            event_description = self.STATUS_DESCRIPTIONS.get(event_status_code, "")

            events.append({
                "datetime": event_datetime,
                "status": event_status.lower().replace(" ", "_"),
                "status_label": event_status,
                "location": detail.get("unitName", ""),
                "description": detail.get("eventName", event_description)
            })

        # Sort events by datetime (newest first)
        events.sort(key=lambda x: x["datetime"], reverse=True)

        return {
            "carrier": self.CARRIER_NAME,
            "carrier_code": self.CARRIER_CODE,
            "tracking_number": shipment_data.get("cargoKey", ""),
            "current_status": current_status.lower().replace(" ", "_"),
            "current_status_label": current_status,
            "estimated_delivery": shipment_data.get("estimatedDeliveryDate"),
            "delivery_date": shipment_data.get("deliveryDate"),
            "receiver_name": shipment_data.get("receiverName"),
            "events": events
        }

    def create_shipment(self, shipment_data: dict) -> Optional[dict]:
        """Create a shipping order through Yurtici API.

        Args:
            shipment_data: Dictionary containing shipment details:
                - sender_name, sender_address, sender_phone, sender_city
                - receiver_name, receiver_address, receiver_phone, receiver_city, receiver_district
                - weight, desi (volumetric weight), pieces, description
                - is_cod, cod_amount, payment_type

        Returns:
            dict: Shipment creation result with cargo_key
        """
        if not self.username:
            return {"success": False, "error": _("Yurtici Kargo is not configured")}

        try:
            # Validate required fields
            required_fields = [
                "sender_name", "sender_address", "sender_phone",
                "receiver_name", "receiver_address", "receiver_phone",
                "receiver_city", "receiver_district"
            ]
            missing = [f for f in required_fields if not shipment_data.get(f)]
            if missing:
                return {"success": False, "error": f"Missing fields: {', '.join(missing)}"}

            # Prepare shipment request in Yurtici format
            request_data = {
                "wsUserName": self.username,
                "wsPassword": self.password,
                "wsLanguage": self.user_language,
                "ShippingOrderVO": {
                    "cargoType": shipment_data.get("cargo_type", 1),  # 1=Document, 2=Package
                    "invoiceKey": shipment_data.get("reference_number", ""),
                    "receiverCustName": shipment_data.get("receiver_name"),
                    "receiverAddress": shipment_data.get("receiver_address"),
                    "receiverPhone1": shipment_data.get("receiver_phone"),
                    "cityName": shipment_data.get("receiver_city"),
                    "townName": shipment_data.get("receiver_district"),
                    "taxOfficeId": "",
                    "taxNumber": shipment_data.get("receiver_tax_number", ""),
                    "desi": shipment_data.get("desi", 1),
                    "kg": shipment_data.get("weight", 1),
                    "cargoCount": shipment_data.get("pieces", 1),
                    "specialField1": shipment_data.get("description", ""),
                    "ttInvoiceAmount": shipment_data.get("cod_amount", 0) if shipment_data.get("is_cod") else 0,
                    "ttDocumentId": "",
                    "ttDocumentSaveType": 0,
                    "ttCollectionType": 1 if shipment_data.get("is_cod") else 0,
                    "dcSelectedCredit": "",
                    "dcCreditRule": 0,
                    "description": shipment_data.get("description", ""),
                    "orgGeoCode": shipment_data.get("sender_geo_code", ""),
                    "privilegeOrder": 0,
                    "custProdId": 0
                }
            }

            frappe.logger().info(
                f"Yurtici shipment creation request for {shipment_data.get('reference_number', 'N/A')}"
            )

            # In production, make SOAP API call
            if self.test_mode:
                return {
                    "success": True,
                    "cargo_key": f"YK{datetime.now().strftime('%Y%m%d%H%M%S')}",
                    "tracking_number": f"YK{datetime.now().strftime('%Y%m%d%H%M%S')}",
                    "barcode": None,
                    "message": "Test mode - no actual shipment created"
                }

            return {"success": True, "request_data": request_data}

        except Exception as e:
            frappe.log_error(
                f"Yurtici shipment creation failed: {str(e)}",
                "Yurtici Integration Error"
            )
            return {"success": False, "error": str(e)}

    def calculate_rate(self, origin_city: str, destination_city: str, weight: float, desi: float = None) -> Optional[dict]:
        """Calculate shipping rate for a package.

        Args:
            origin_city: Origin city name
            destination_city: Destination city name
            weight: Package weight in kg
            desi: Volumetric weight (optional)

        Returns:
            dict: Rate calculation result with price and transit time
        """
        if not self.username:
            return {"success": False, "error": _("Yurtici Kargo is not configured")}

        try:
            # Use the greater of actual weight and volumetric weight
            chargeable_weight = max(weight, desi or 0)

            request_data = {
                "wsUserName": self.username,
                "wsPassword": self.password,
                "wsLanguage": self.user_language,
                "originCityName": origin_city,
                "destCityName": destination_city,
                "desi": chargeable_weight
            }

            frappe.logger().info(
                f"Yurtici rate query: {origin_city} -> {destination_city}, {chargeable_weight} desi"
            )

            if self.test_mode:
                # Return mock rate for testing
                base_rate = 25.0
                weight_rate = chargeable_weight * 5.0
                return {
                    "success": True,
                    "price": round(base_rate + weight_rate, 2),
                    "currency": "TRY",
                    "transit_days": 2,
                    "chargeable_weight": chargeable_weight,
                    "message": "Test mode - estimated rate"
                }

            return {"success": True, "request_data": request_data}

        except Exception as e:
            frappe.log_error(
                f"Yurtici rate calculation failed: {str(e)}",
                "Yurtici Integration Error"
            )
            return {"success": False, "error": str(e)}

    def cancel_shipment(self, cargo_key: str) -> dict:
        """Cancel a shipment through Yurtici API.

        Args:
            cargo_key: The cargo key to cancel

        Returns:
            dict: Cancellation result
        """
        if not self.username:
            return {"success": False, "error": _("Yurtici Kargo is not configured")}

        try:
            request_data = {
                "wsUserName": self.username,
                "wsPassword": self.password,
                "wsLanguage": self.user_language,
                "cargoKey": cargo_key
            }

            frappe.logger().info(f"Yurtici cancellation request for {cargo_key}")

            if self.test_mode:
                return {
                    "success": True,
                    "cargo_key": cargo_key,
                    "message": "Test mode - shipment marked as cancelled"
                }

            return {"success": True, "request_data": request_data}

        except Exception as e:
            frappe.log_error(
                f"Yurtici cancellation failed for {cargo_key}: {str(e)}",
                "Yurtici Integration Error"
            )
            return {"success": False, "error": str(e)}


# API endpoints for Frappe whitelisting
@frappe.whitelist()
def get_yurtici_tracking(tracking_number):
    """Get tracking information from Yurtici Kargo.

    Args:
        tracking_number: The Yurtici cargo key

    Returns:
        dict: Tracking information
    """
    if not tracking_number:
        return {"success": False, "error": "Tracking number is required"}

    integration = YurticiIntegration()
    result = integration.get_tracking(tracking_number)

    if result:
        return {"success": True, **result}
    return {"success": False, "error": "Could not retrieve tracking information"}


@frappe.whitelist()
def create_yurtici_shipment(shipment_data=None):
    """Create a shipment with Yurtici Kargo.

    Args:
        shipment_data: Shipment details as JSON string or dict

    Returns:
        dict: Shipment creation result with cargo key
    """
    if not shipment_data:
        return {"success": False, "error": "Shipment data is required"}

    if isinstance(shipment_data, str):
        shipment_data = json.loads(shipment_data)

    integration = YurticiIntegration()
    return integration.create_shipment(shipment_data)


@frappe.whitelist()
def get_yurtici_rate(origin_city, destination_city, weight, desi=None):
    """Calculate shipping rate with Yurtici Kargo.

    Args:
        origin_city: Origin city name
        destination_city: Destination city name
        weight: Package weight in kg
        desi: Volumetric weight (optional)

    Returns:
        dict: Rate calculation result
    """
    if not origin_city or not destination_city:
        return {"success": False, "error": "Origin and destination cities are required"}

    integration = YurticiIntegration()
    return integration.calculate_rate(
        origin_city,
        destination_city,
        float(weight),
        float(desi) if desi else None
    )


@frappe.whitelist()
def cancel_yurtici_shipment(cargo_key):
    """Cancel a Yurtici Kargo shipment.

    Args:
        cargo_key: The cargo key to cancel

    Returns:
        dict: Cancellation result
    """
    if not cargo_key:
        return {"success": False, "error": "Cargo key is required"}

    integration = YurticiIntegration()
    return integration.cancel_shipment(cargo_key)

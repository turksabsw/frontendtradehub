# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

"""
Yurtici Kargo Integration for TR-TradeHub Marketplace

Yurtici Kargo is Turkey's leading logistics company providing:
- Domestic and international cargo services
- Express delivery
- Warehouse and fulfillment services
- E-commerce logistics

This module integrates with Yurtici Kargo's web services API for:
- Shipment creation with label generation
- Real-time tracking queries
- Pickup scheduling
- Shipment cancellation
- Delivery point lookups

API Documentation: https://www.yurticikargo.com/tr/entegrasyon-merkezi

Configuration (site_config.json):
{
    "yurtici_username": "your-username",
    "yurtici_password": "your-password",
    "yurtici_user_language": "TR",
    "yurtici_customer_code": "your-customer-code",
    "yurtici_base_url": "https://webservices.yurticikargo.com",
    "yurtici_test_mode": true  # Use sandbox environment
}
"""

import json
import hashlib
import base64
import hmac
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import Any, Dict, List, Optional, Union

import frappe
from frappe import _
from frappe.utils import flt, cint, now_datetime, get_url, getdate


# =============================================================================
# EXCEPTIONS
# =============================================================================


class YurticiError(Exception):
    """Base exception for Yurtici Kargo integration errors."""

    def __init__(
        self,
        message: str,
        error_code: str = None,
        error_message: str = None,
        request_id: str = None,
    ):
        self.message = message
        self.error_code = error_code
        self.error_message = error_message
        self.request_id = request_id
        super().__init__(self.message)

    def to_dict(self) -> Dict:
        return {
            "message": self.message,
            "error_code": self.error_code,
            "error_message": self.error_message,
            "request_id": self.request_id,
        }


class YurticiAuthenticationError(YurticiError):
    """Authentication/credential errors."""
    pass


class YurticiValidationError(YurticiError):
    """Request validation errors."""
    pass


class YurticiShipmentError(YurticiError):
    """Shipment processing errors."""
    pass


class YurticiTrackingError(YurticiError):
    """Tracking query errors."""
    pass


# =============================================================================
# CONFIGURATION
# =============================================================================


def get_yurtici_config() -> Dict[str, str]:
    """
    Get Yurtici Kargo configuration from site_config or TR TradeHub Settings.

    Returns:
        dict: Configuration with credentials and URLs

    Raises:
        YurticiError: If configuration is missing
    """
    # Try site_config first
    username = frappe.conf.get("yurtici_username")
    password = frappe.conf.get("yurtici_password")
    user_language = frappe.conf.get("yurtici_user_language", "TR")
    customer_code = frappe.conf.get("yurtici_customer_code")
    base_url = frappe.conf.get("yurtici_base_url", "https://webservices.yurticikargo.com")
    test_mode = frappe.conf.get("yurtici_test_mode", False)

    # Fall back to TR TradeHub Settings DocType
    if not username or not password:
        if frappe.db.exists("DocType", "TR TradeHub Settings"):
            settings = frappe.get_single("TR TradeHub Settings")
            username = username or settings.get("yurtici_username")
            password = password or settings.get_password("yurtici_password")
            user_language = settings.get("yurtici_user_language") or user_language
            customer_code = customer_code or settings.get("yurtici_customer_code")
            base_url = settings.get("yurtici_base_url") or base_url
            test_mode = settings.get("yurtici_test_mode", test_mode)

    if not username or not password:
        raise YurticiError(
            _("Yurtici Kargo credentials not configured. "
              "Please set yurtici_username and yurtici_password in site_config.json")
        )

    # Use test environment if in test mode
    if test_mode:
        base_url = "https://testwebservices.yurticikargo.com"

    return {
        "username": username,
        "password": password,
        "user_language": user_language,
        "customer_code": customer_code,
        "base_url": base_url.rstrip("/"),
        "test_mode": test_mode,
    }


# =============================================================================
# EVENT TYPE MAPPING
# =============================================================================


# Yurtici event codes to standard tracking event types
YURTICI_EVENT_MAPPING = {
    # Pickup events
    "TES": "Pickup Completed",
    "TSL": "Pickup Completed",
    "TESLIM_ALINDI": "Pickup Completed",

    # Transit events
    "SNT": "In Transit",
    "SANTIYE": "Arrived at Facility",
    "AKTARMA": "Departed Facility",
    "TRANSFER": "In Transit",
    "TRN": "In Transit",
    "ARR": "Arrived at Facility",
    "DEP": "Departed Facility",

    # Out for delivery
    "DAG": "Out for Delivery",
    "DAGITIM": "Out for Delivery",
    "OUT": "Out for Delivery",
    "OFD": "Out for Delivery",

    # Delivery events
    "TSL_OK": "Delivered",
    "TESLIM": "Delivered",
    "DLV": "Delivered",
    "TESLIM_EDILDI": "Delivered",
    "DEL": "Delivered",

    # Exception events
    "IPT": "Delivery Exception",
    "IPTAL": "Cancelled",
    "IADE": "Return Initiated",
    "RED": "Refused",
    "ADRES_HATA": "Address Issue",
    "ALICI_YOK": "Recipient Unavailable",
    "HASAR": "Damaged",
    "KAYIP": "Lost",
    "MUHATAP_YOK": "Recipient Unavailable",
    "KAPALI": "Recipient Unavailable",
    "EXC": "Delivery Exception",
    "HLD": "Package Held",

    # Return events
    "IADE_YOLDA": "Returning to Sender",
    "IADE_TESLIM": "Returned to Sender",
    "RTN": "Return Initiated",
    "RTS": "Returned to Sender",
}


# =============================================================================
# CLIENT CLASS
# =============================================================================


class YurticiClient:
    """
    Yurtici Kargo API Client for TR-TradeHub.

    Provides methods for:
    - Creating shipments with labels
    - Tracking shipments
    - Scheduling pickups
    - Cancelling shipments
    - Querying delivery points
    """

    def __init__(self, config: Dict[str, str] = None):
        """
        Initialize Yurtici client.

        Args:
            config: Optional config dict with credentials
        """
        self.config = config or get_yurtici_config()
        self.username = self.config["username"]
        self.password = self.config["password"]
        self.user_language = self.config["user_language"]
        self.customer_code = self.config["customer_code"]
        self.base_url = self.config["base_url"]
        self.test_mode = self.config.get("test_mode", False)

        # SOAP endpoints
        self.shipment_wsdl = f"{self.base_url}/ShippingOrderDispatcherServices/ShippingOrderDispatcherServices.ws?wsdl"
        self.tracking_wsdl = f"{self.base_url}/ShippingOrderDispatcherServices/ShippingOrderDispatcherServices.ws?wsdl"

    def _generate_request_id(self, prefix: str = "YK") -> str:
        """Generate unique request ID for tracking."""
        import secrets
        return f"{prefix}{secrets.token_hex(8).upper()}"

    def _make_request(
        self,
        endpoint: str,
        method: str,
        data: Dict,
        request_id: str = None,
    ) -> Dict:
        """
        Make HTTP request to Yurtici API.

        Args:
            endpoint: API endpoint path
            method: HTTP method
            data: Request payload
            request_id: Request tracking ID

        Returns:
            dict: API response

        Raises:
            YurticiError: If request fails
        """
        import requests

        request_id = request_id or self._generate_request_id()

        url = f"{self.base_url}{endpoint}"

        # Add authentication to payload
        auth_data = {
            "wsUserName": self.username,
            "wsPassword": self.password,
            "userLanguage": self.user_language,
            **data
        }

        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-Request-ID": request_id,
        }

        try:
            if method.upper() == "GET":
                response = requests.get(url, params=auth_data, headers=headers, timeout=30)
            else:
                response = requests.post(url, json=auth_data, headers=headers, timeout=30)

            response.raise_for_status()

            result = response.json()

            # Check for API-level errors
            if result.get("ErrorCode") or result.get("outResult") == "-1":
                error_code = result.get("ErrorCode") or result.get("outResult")
                error_msg = result.get("ErrorMessage") or result.get("outResultMessage", "Unknown error")
                raise YurticiShipmentError(
                    error_msg,
                    error_code=str(error_code),
                    error_message=error_msg,
                    request_id=request_id,
                )

            return result

        except requests.exceptions.RequestException as e:
            frappe.log_error(
                f"Yurtici API request error: {str(e)}",
                "Yurtici API Error"
            )
            raise YurticiError(
                _("Failed to connect to Yurtici Kargo API: {0}").format(str(e)),
                request_id=request_id,
            )

    def _make_soap_request(
        self,
        wsdl_url: str,
        operation: str,
        data: Dict,
        request_id: str = None,
    ) -> Dict:
        """
        Make SOAP request to Yurtici Web Services.

        Args:
            wsdl_url: WSDL URL
            operation: SOAP operation name
            data: Request parameters
            request_id: Request tracking ID

        Returns:
            dict: Parsed SOAP response

        Raises:
            YurticiError: If request fails
        """
        request_id = request_id or self._generate_request_id()

        try:
            # Try using zeep for SOAP
            try:
                from zeep import Client
                from zeep.helpers import serialize_object

                client = Client(wsdl_url)

                # Add authentication
                auth_data = {
                    "wsUserName": self.username,
                    "wsPassword": self.password,
                    "userLanguage": self.user_language,
                    **data
                }

                # Call the operation
                service_method = getattr(client.service, operation)
                response = service_method(**auth_data)

                # Serialize response
                result = serialize_object(response)
                return self._process_soap_response(result, operation, request_id)

            except ImportError:
                # Fall back to requests if zeep not available
                frappe.log_error(
                    "zeep library not installed. Run: bench pip install zeep",
                    "Yurtici Integration"
                )
                raise YurticiError(
                    _("SOAP library (zeep) not installed. Please run: bench pip install zeep"),
                    request_id=request_id,
                )

        except Exception as e:
            if isinstance(e, YurticiError):
                raise
            frappe.log_error(
                f"Yurtici SOAP request error: {str(e)}",
                f"Yurtici {operation}"
            )
            raise YurticiError(
                _("Yurtici API request failed: {0}").format(str(e)),
                request_id=request_id,
            )

    def _process_soap_response(
        self,
        response: Any,
        operation: str,
        request_id: str,
    ) -> Dict:
        """
        Process SOAP response and check for errors.

        Args:
            response: Raw SOAP response
            operation: Operation name for logging
            request_id: Request ID

        Returns:
            dict: Processed response

        Raises:
            YurticiError: If response indicates error
        """
        if isinstance(response, dict):
            result = response
        else:
            result = {"data": response}

        # Check for error indicators
        out_result = result.get("outResult") or result.get("OutResult")
        if out_result == "-1" or out_result == -1:
            error_msg = (
                result.get("outResultMessage") or
                result.get("OutResultMessage") or
                "Operation failed"
            )
            frappe.log_error(
                f"Yurtici {operation} failed: {error_msg}",
                f"Yurtici {operation} Error"
            )
            raise YurticiShipmentError(
                error_msg,
                error_code=str(out_result),
                error_message=error_msg,
                request_id=request_id,
            )

        return result

    # =========================================================================
    # SHIPMENT METHODS
    # =========================================================================

    def create_shipment(
        self,
        shipment: str,
        sender_info: Dict,
        receiver_info: Dict,
        package_info: Dict,
        cargo_type: str = "D",
        payment_type: str = "P",
        document_type: str = "N",
        special_field_1: str = None,
        special_field_2: str = None,
        special_field_3: str = None,
        ttDocumentId: str = None,
        dcSelectedCredit: str = None,
        dcCreditRule: str = None,
        description: str = None,
        request_id: str = None,
    ) -> Dict:
        """
        Create a new shipment with Yurtici Kargo.

        Args:
            shipment: TR-TradeHub Marketplace Shipment ID
            sender_info: Sender details dict with:
                - name: Sender name
                - phone: Phone number
                - address: Full address
                - city: City name
                - district: District name
                - postal_code: Postal code
                - email: Email (optional)
                - customer_code: Customer code (optional, uses default if not provided)
            receiver_info: Receiver details dict with same fields
            package_info: Package details dict with:
                - count: Number of packages (desi)
                - weight: Total weight in kg
                - description: Package content description
                - value: Declared value (optional)
            cargo_type: Cargo type (D=Document, P=Package)
            payment_type: Payment type (P=Prepaid, C=COD)
            document_type: Document type (N=Normal)
            special_field_1: Custom field 1
            special_field_2: Custom field 2
            special_field_3: Custom field 3
            ttDocumentId: TT document ID
            dcSelectedCredit: Selected credit
            dcCreditRule: Credit rule
            description: Shipment description
            request_id: Optional request tracking ID

        Returns:
            dict: Shipment creation result with tracking number
        """
        request_id = request_id or self._generate_request_id("SHP")

        # Build sender info
        sender_customer_code = sender_info.get("customer_code") or self.customer_code

        # Build shipment request
        shipment_data = {
            "invCustId": sender_customer_code,
            "cargoKey": shipment,
            "cargoType": cargo_type,
            "documentSave": document_type,
            "invoiceKey": shipment,
            "receiverCustName": receiver_info.get("name", ""),
            "receiverAddress": receiver_info.get("address", ""),
            "cityName": receiver_info.get("city", ""),
            "townName": receiver_info.get("district", ""),
            "receiverPhone1": self._format_phone(receiver_info.get("phone", "")),
            "receiverPhone2": self._format_phone(receiver_info.get("phone2", "")),
            "receiverPhone3": self._format_phone(receiver_info.get("phone3", "")),
            "emailAddress": receiver_info.get("email", ""),
            "taxOfficeId": "",
            "taxNumber": receiver_info.get("tax_id", ""),
            "taxOfficeName": "",
            "desi": str(package_info.get("count", 1)),
            "kg": str(package_info.get("weight", 1)),
            "cargoCount": str(package_info.get("package_count", 1)),
            "waybillNo": "",
            "ttDocumentId": ttDocumentId or "",
            "dcSelectedCredit": dcSelectedCredit or "",
            "dcCreditRule": dcCreditRule or "",
            "specialField1": special_field_1 or "",
            "specialField2": special_field_2 or shipment,
            "specialField3": special_field_3 or "",
            "description": description or package_info.get("description", ""),
            "orgGeoCode": sender_info.get("geo_code", ""),
            "privilegeOrder": "0",
            "custProdId": "0",
        }

        # Add COD amount if payment type is COD
        if payment_type == "C":
            shipment_data["codAmount"] = str(package_info.get("cod_amount", 0))

        try:
            result = self._make_soap_request(
                self.shipment_wsdl,
                "createShipment",
                shipment_data,
                request_id,
            )

            # Extract tracking number from response
            tracking_number = (
                result.get("jobId") or
                result.get("ShippingOrderDetailVO", {}).get("cargoKey") or
                result.get("cargoKey")
            )

            # Log success
            self._log_carrier_event(
                shipment,
                "shipment_created",
                {
                    "tracking_number": tracking_number,
                    "request_id": request_id,
                }
            )

            return {
                "success": True,
                "tracking_number": tracking_number,
                "cargo_key": result.get("cargoKey"),
                "job_id": result.get("jobId"),
                "request_id": request_id,
                "label_url": self._get_label_url(tracking_number),
                "tracking_url": self._get_tracking_url(tracking_number),
                "raw_response": result,
            }

        except YurticiError:
            raise
        except Exception as e:
            frappe.log_error(
                f"Yurtici create shipment error: {str(e)}",
                "Yurtici Create Shipment"
            )
            raise YurticiShipmentError(
                _("Failed to create shipment: {0}").format(str(e)),
                request_id=request_id,
            )

    def track_shipment(
        self,
        tracking_number: str,
        request_id: str = None,
    ) -> Dict:
        """
        Track a shipment by tracking number.

        Args:
            tracking_number: Yurtici tracking number (cargo key)
            request_id: Optional request tracking ID

        Returns:
            dict: Tracking information with events
        """
        request_id = request_id or self._generate_request_id("TRK")

        tracking_data = {
            "cargoKey": tracking_number,
        }

        try:
            result = self._make_soap_request(
                self.tracking_wsdl,
                "queryShipment",
                tracking_data,
                request_id,
            )

            # Parse tracking events
            events = self._parse_tracking_events(result)

            # Get current status
            current_status = self._determine_current_status(events)

            return {
                "success": True,
                "tracking_number": tracking_number,
                "status": current_status,
                "events": events,
                "delivered": current_status == "Delivered",
                "delivery_date": self._get_delivery_date(events),
                "receiver_name": result.get("receiverName"),
                "tracking_url": self._get_tracking_url(tracking_number),
                "raw_response": result,
            }

        except YurticiError:
            raise
        except Exception as e:
            frappe.log_error(
                f"Yurtici track shipment error: {str(e)}",
                "Yurtici Track Shipment"
            )
            raise YurticiTrackingError(
                _("Failed to track shipment: {0}").format(str(e)),
                request_id=request_id,
            )

    def get_shipment_info(
        self,
        tracking_number: str,
        request_id: str = None,
    ) -> Dict:
        """
        Get detailed shipment information.

        Args:
            tracking_number: Yurtici tracking number
            request_id: Optional request tracking ID

        Returns:
            dict: Detailed shipment information
        """
        request_id = request_id or self._generate_request_id("INF")

        query_data = {
            "cargoKey": tracking_number,
        }

        try:
            result = self._make_soap_request(
                self.tracking_wsdl,
                "queryShipmentInfo",
                query_data,
                request_id,
            )

            return {
                "success": True,
                "tracking_number": tracking_number,
                "cargo_key": result.get("cargoKey"),
                "status": result.get("status"),
                "sender_name": result.get("senderName"),
                "receiver_name": result.get("receiverName"),
                "receiver_address": result.get("receiverAddress"),
                "receiver_city": result.get("cityName"),
                "receiver_district": result.get("townName"),
                "package_count": result.get("cargoCount"),
                "weight": result.get("kg"),
                "desi": result.get("desi"),
                "created_date": result.get("createDate"),
                "delivery_date": result.get("deliveryDate"),
                "raw_response": result,
            }

        except YurticiError:
            raise
        except Exception as e:
            frappe.log_error(
                f"Yurtici get shipment info error: {str(e)}",
                "Yurtici Get Shipment Info"
            )
            raise YurticiTrackingError(
                _("Failed to get shipment info: {0}").format(str(e)),
                request_id=request_id,
            )

    def cancel_shipment(
        self,
        tracking_number: str,
        reason: str = None,
        request_id: str = None,
    ) -> Dict:
        """
        Cancel a shipment.

        Args:
            tracking_number: Yurtici tracking number
            reason: Cancellation reason
            request_id: Optional request tracking ID

        Returns:
            dict: Cancellation result
        """
        request_id = request_id or self._generate_request_id("CAN")

        cancel_data = {
            "cargoKey": tracking_number,
            "cancelReason": reason or "Customer request",
        }

        try:
            result = self._make_soap_request(
                self.shipment_wsdl,
                "cancelShipment",
                cancel_data,
                request_id,
            )

            self._log_carrier_event(
                tracking_number,
                "shipment_cancelled",
                {
                    "reason": reason,
                    "request_id": request_id,
                }
            )

            return {
                "success": True,
                "tracking_number": tracking_number,
                "cancelled": True,
                "message": result.get("outResultMessage", "Shipment cancelled"),
                "raw_response": result,
            }

        except YurticiError:
            raise
        except Exception as e:
            frappe.log_error(
                f"Yurtici cancel shipment error: {str(e)}",
                "Yurtici Cancel Shipment"
            )
            raise YurticiShipmentError(
                _("Failed to cancel shipment: {0}").format(str(e)),
                request_id=request_id,
            )

    def schedule_pickup(
        self,
        pickup_date: str,
        pickup_address: Dict,
        contact_name: str,
        contact_phone: str,
        package_count: int = 1,
        total_desi: float = 1,
        notes: str = None,
        pickup_time_from: str = None,
        pickup_time_to: str = None,
        request_id: str = None,
    ) -> Dict:
        """
        Schedule a pickup.

        Args:
            pickup_date: Pickup date (YYYY-MM-DD)
            pickup_address: Address dict with address, city, district
            contact_name: Contact person name
            contact_phone: Contact phone number
            package_count: Number of packages
            total_desi: Total desi (volumetric weight)
            notes: Special instructions
            pickup_time_from: Pickup time start (HH:MM)
            pickup_time_to: Pickup time end (HH:MM)
            request_id: Optional request tracking ID

        Returns:
            dict: Pickup scheduling result
        """
        request_id = request_id or self._generate_request_id("PIC")

        pickup_data = {
            "invCustId": self.customer_code,
            "pickupDate": pickup_date,
            "pickupAddress": pickup_address.get("address", ""),
            "cityName": pickup_address.get("city", ""),
            "townName": pickup_address.get("district", ""),
            "contactName": contact_name,
            "contactPhone": self._format_phone(contact_phone),
            "cargoCount": str(package_count),
            "desi": str(total_desi),
            "notes": notes or "",
        }

        if pickup_time_from:
            pickup_data["pickupTimeFrom"] = pickup_time_from
        if pickup_time_to:
            pickup_data["pickupTimeTo"] = pickup_time_to

        try:
            result = self._make_soap_request(
                self.shipment_wsdl,
                "createPickup",
                pickup_data,
                request_id,
            )

            return {
                "success": True,
                "pickup_id": result.get("pickupId"),
                "pickup_date": pickup_date,
                "status": "Scheduled",
                "message": result.get("outResultMessage", "Pickup scheduled"),
                "raw_response": result,
            }

        except YurticiError:
            raise
        except Exception as e:
            frappe.log_error(
                f"Yurtici schedule pickup error: {str(e)}",
                "Yurtici Schedule Pickup"
            )
            raise YurticiShipmentError(
                _("Failed to schedule pickup: {0}").format(str(e)),
                request_id=request_id,
            )

    def get_delivery_points(
        self,
        city: str = None,
        district: str = None,
        request_id: str = None,
    ) -> Dict:
        """
        Get available delivery/drop-off points.

        Args:
            city: Filter by city name
            district: Filter by district name
            request_id: Optional request tracking ID

        Returns:
            dict: List of delivery points
        """
        request_id = request_id or self._generate_request_id("DPT")

        query_data = {}
        if city:
            query_data["cityName"] = city
        if district:
            query_data["townName"] = district

        try:
            result = self._make_soap_request(
                self.tracking_wsdl,
                "getDeliveryPoints",
                query_data,
                request_id,
            )

            points = []
            raw_points = result.get("DeliveryPoints", [])
            if isinstance(raw_points, list):
                for point in raw_points:
                    points.append({
                        "id": point.get("pointId"),
                        "name": point.get("pointName"),
                        "address": point.get("address"),
                        "city": point.get("cityName"),
                        "district": point.get("townName"),
                        "phone": point.get("phone"),
                        "latitude": point.get("latitude"),
                        "longitude": point.get("longitude"),
                        "working_hours": point.get("workingHours"),
                    })

            return {
                "success": True,
                "count": len(points),
                "points": points,
            }

        except YurticiError:
            raise
        except Exception as e:
            frappe.log_error(
                f"Yurtici get delivery points error: {str(e)}",
                "Yurtici Get Delivery Points"
            )
            raise YurticiError(
                _("Failed to get delivery points: {0}").format(str(e)),
                request_id=request_id,
            )

    # =========================================================================
    # WEBHOOK METHODS
    # =========================================================================

    def verify_webhook(
        self,
        payload: str,
        signature: str = None,
    ) -> bool:
        """
        Verify webhook callback signature.

        Args:
            payload: Raw webhook payload
            signature: Signature from request header (if applicable)

        Returns:
            bool: True if signature is valid or verification not required
        """
        # Yurtici webhooks typically don't use signatures
        # Verification is done through IP whitelisting
        # This method is a placeholder for future implementation
        return True

    def parse_webhook_payload(self, payload: str) -> Dict:
        """
        Parse webhook payload from Yurtici.

        Args:
            payload: Raw webhook payload (JSON or XML)

        Returns:
            dict: Parsed webhook data
        """
        try:
            # Try JSON first
            try:
                data = json.loads(payload)
            except json.JSONDecodeError:
                # Try XML
                root = ET.fromstring(payload)
                data = self._xml_to_dict(root)

            event_code = data.get("eventCode") or data.get("status")
            event_type = YURTICI_EVENT_MAPPING.get(event_code, "Status Update")

            return {
                "tracking_number": data.get("cargoKey") or data.get("trackingNumber"),
                "event_code": event_code,
                "event_type": event_type,
                "event_date": data.get("eventDate") or data.get("updateDate"),
                "event_description": data.get("description") or data.get("statusDescription"),
                "location": {
                    "city": data.get("cityName"),
                    "district": data.get("townName"),
                    "facility": data.get("branchName"),
                },
                "receiver_name": data.get("receiverName"),
                "raw_data": data,
            }

        except Exception as e:
            frappe.log_error(
                f"Yurtici webhook parse error: {str(e)}",
                "Yurtici Webhook"
            )
            raise YurticiError(_("Invalid webhook payload: {0}").format(str(e)))

    # =========================================================================
    # HELPER METHODS
    # =========================================================================

    def _format_phone(self, phone: str) -> str:
        """Format phone number for Yurtici API."""
        if not phone:
            return ""

        # Remove non-digit characters
        digits = "".join(filter(str.isdigit, phone))

        # Turkish phone numbers
        if digits.startswith("90") and len(digits) == 12:
            return digits[2:]  # Remove country code
        elif digits.startswith("0") and len(digits) == 11:
            return digits[1:]  # Remove leading 0
        elif len(digits) == 10:
            return digits

        return digits

    def _get_tracking_url(self, tracking_number: str) -> str:
        """Get public tracking URL."""
        return f"https://www.yurticikargo.com/tr/online-servisler/gonderi-sorgula?code={tracking_number}"

    def _get_label_url(self, tracking_number: str) -> str:
        """Get shipment label URL."""
        return f"{self.base_url}/printLabel?cargoKey={tracking_number}"

    def _parse_tracking_events(self, result: Dict) -> List[Dict]:
        """Parse tracking events from API response."""
        events = []

        raw_events = result.get("ShippingDeliveryDetailVO", [])
        if not isinstance(raw_events, list):
            raw_events = [raw_events] if raw_events else []

        for event in raw_events:
            event_code = event.get("operationCode") or event.get("status")
            event_type = YURTICI_EVENT_MAPPING.get(event_code, "Status Update")

            events.append({
                "timestamp": event.get("operationDate") or event.get("eventDate"),
                "event_code": event_code,
                "event_type": event_type,
                "description": event.get("operationMessage") or event.get("description", ""),
                "location": {
                    "city": event.get("cityName"),
                    "facility": event.get("unitName") or event.get("branchName"),
                },
                "signed_by": event.get("receiverName") if event_type == "Delivered" else None,
            })

        # Sort by timestamp
        events.sort(key=lambda x: x.get("timestamp") or "", reverse=True)

        return events

    def _determine_current_status(self, events: List[Dict]) -> str:
        """Determine current status from events."""
        if not events:
            return "Unknown"

        # Priority order for status determination
        status_priority = [
            "Delivered",
            "Returned to Sender",
            "Returning to Sender",
            "Out for Delivery",
            "In Transit",
            "Pickup Completed",
            "Cancelled",
        ]

        for status in status_priority:
            for event in events:
                if event.get("event_type") == status:
                    return status

        return events[0].get("event_type", "Unknown")

    def _get_delivery_date(self, events: List[Dict]) -> str:
        """Extract delivery date from events."""
        for event in events:
            if event.get("event_type") == "Delivered":
                return event.get("timestamp")
        return None

    def _xml_to_dict(self, element: ET.Element) -> Dict:
        """Convert XML element to dictionary."""
        result = {}
        for child in element:
            if len(child) > 0:
                result[child.tag] = self._xml_to_dict(child)
            else:
                result[child.tag] = child.text
        return result

    def _log_carrier_event(self, ref: str, event_type: str, details: Dict):
        """Log carrier event for audit trail."""
        try:
            frappe.get_doc({
                "doctype": "Activity Log",
                "subject": f"Yurtici Kargo {event_type}",
                "content": json.dumps(details),
                "reference_doctype": "Marketplace Shipment",
                "reference_name": ref,
                "user": frappe.session.user or "System",
            }).insert(ignore_permissions=True)
        except Exception:
            pass  # Don't let logging errors affect shipment flow


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================


def create_shipment(**kwargs) -> Dict:
    """Convenience function to create a shipment."""
    client = YurticiClient()
    return client.create_shipment(**kwargs)


def track_shipment(tracking_number: str) -> Dict:
    """Convenience function to track a shipment."""
    client = YurticiClient()
    return client.track_shipment(tracking_number)


def get_shipment_info(tracking_number: str) -> Dict:
    """Convenience function to get shipment info."""
    client = YurticiClient()
    return client.get_shipment_info(tracking_number)


def cancel_shipment(tracking_number: str, reason: str = None) -> Dict:
    """Convenience function to cancel a shipment."""
    client = YurticiClient()
    return client.cancel_shipment(tracking_number, reason)


def schedule_pickup(**kwargs) -> Dict:
    """Convenience function to schedule pickup."""
    client = YurticiClient()
    return client.schedule_pickup(**kwargs)


def verify_webhook(payload: str, signature: str = None) -> bool:
    """Convenience function to verify webhook."""
    client = YurticiClient()
    return client.verify_webhook(payload, signature)


def get_delivery_points(city: str = None, district: str = None) -> Dict:
    """Convenience function to get delivery points."""
    client = YurticiClient()
    return client.get_delivery_points(city, district)


# =============================================================================
# FRAPPE API ENDPOINTS
# =============================================================================


@frappe.whitelist()
def api_track_shipment(tracking_number: str) -> Dict:
    """
    API endpoint to track a Yurtici shipment.

    Args:
        tracking_number: Yurtici tracking number

    Returns:
        dict: Tracking information
    """
    try:
        result = track_shipment(tracking_number)
        return result
    except YurticiError as e:
        frappe.throw(str(e.message))
    except Exception as e:
        frappe.log_error(str(e), "Yurtici Track API")
        frappe.throw(_("Failed to track shipment"))


@frappe.whitelist()
def api_get_delivery_points(city: str = None, district: str = None) -> Dict:
    """
    API endpoint to get delivery points.

    Args:
        city: Filter by city
        district: Filter by district

    Returns:
        dict: List of delivery points
    """
    try:
        result = get_delivery_points(city, district)
        return result
    except YurticiError as e:
        frappe.throw(str(e.message))
    except Exception as e:
        frappe.log_error(str(e), "Yurtici Delivery Points API")
        frappe.throw(_("Failed to get delivery points"))


@frappe.whitelist(allow_guest=True)
def handle_webhook():
    """
    API endpoint for Yurtici webhook callbacks.

    Returns:
        dict: Webhook processing result
    """
    try:
        payload = frappe.request.get_data(as_text=True)

        client = YurticiClient()

        # Verify webhook (IP-based in production)
        if not client.verify_webhook(payload):
            frappe.log_error(
                "Invalid webhook request",
                "Yurtici Webhook"
            )
            frappe.throw(_("Invalid webhook request"), frappe.AuthenticationError)

        # Parse payload
        webhook_data = client.parse_webhook_payload(payload)

        # Process webhook - update tracking events
        tracking_number = webhook_data.get("tracking_number")
        event_type = webhook_data.get("event_type")

        if tracking_number:
            _update_shipment_from_webhook(tracking_number, webhook_data)

        frappe.log_error(
            f"Yurtici webhook processed: {event_type} - {tracking_number}",
            "Yurtici Webhook Success"
        )

        return {"success": True, "event_type": event_type}

    except Exception as e:
        frappe.log_error(str(e), "Yurtici Webhook Error")
        raise


def _update_shipment_from_webhook(tracking_number: str, webhook_data: Dict):
    """Update shipment and create tracking event from webhook data."""
    try:
        # Find shipment by tracking number
        shipment_name = frappe.db.get_value(
            "Marketplace Shipment",
            {"tracking_number": tracking_number},
            "name"
        )

        if not shipment_name:
            return

        # Create tracking event
        from tr_tradehub.doctype.tracking_event.tracking_event import log_tracking_event

        location = webhook_data.get("location", {})

        log_tracking_event(
            shipment=shipment_name,
            event_type=webhook_data.get("event_type"),
            description=webhook_data.get("event_description", ""),
            event_timestamp=webhook_data.get("event_date"),
            city=location.get("city"),
            facility_name=location.get("facility"),
            carrier_event_code=webhook_data.get("event_code"),
            raw_event_data=webhook_data.get("raw_data"),
            source="Yurtici Webhook",
        )

    except Exception as e:
        frappe.log_error(
            f"Failed to update shipment from Yurtici webhook: {str(e)}",
            "Yurtici Webhook"
        )

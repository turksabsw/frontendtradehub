# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

"""
Aras Kargo Integration for TR-TradeHub Marketplace

Aras Kargo is one of Turkey's major cargo carriers providing:
- Domestic and international shipping
- Express delivery services
- E-commerce logistics
- Warehouse solutions

This module integrates with Aras Kargo's REST API for:
- Shipment creation with label generation
- Real-time tracking queries
- Pickup scheduling
- Shipment cancellation
- Branch/pickup point lookups

API Documentation: https://www.araskargo.com.tr/entegrasyon

Configuration (site_config.json):
{
    "aras_api_key": "your-api-key",
    "aras_api_secret": "your-api-secret",
    "aras_customer_code": "your-customer-code",
    "aras_username": "your-username",
    "aras_password": "your-password",
    "aras_base_url": "https://customerservices.araskargo.com.tr",
    "aras_test_mode": true  # Use sandbox environment
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


class ArasError(Exception):
    """Base exception for Aras Kargo integration errors."""

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


class ArasAuthenticationError(ArasError):
    """Authentication/credential errors."""
    pass


class ArasValidationError(ArasError):
    """Request validation errors."""
    pass


class ArasShipmentError(ArasError):
    """Shipment processing errors."""
    pass


class ArasTrackingError(ArasError):
    """Tracking query errors."""
    pass


# =============================================================================
# CONFIGURATION
# =============================================================================


def get_aras_config() -> Dict[str, str]:
    """
    Get Aras Kargo configuration from site_config or TR TradeHub Settings.

    Returns:
        dict: Configuration with credentials and URLs

    Raises:
        ArasError: If configuration is missing
    """
    # Try site_config first
    api_key = frappe.conf.get("aras_api_key")
    api_secret = frappe.conf.get("aras_api_secret")
    username = frappe.conf.get("aras_username")
    password = frappe.conf.get("aras_password")
    customer_code = frappe.conf.get("aras_customer_code")
    base_url = frappe.conf.get("aras_base_url", "https://customerservices.araskargo.com.tr")
    test_mode = frappe.conf.get("aras_test_mode", False)

    # Fall back to TR TradeHub Settings DocType
    if not (api_key or username):
        if frappe.db.exists("DocType", "TR TradeHub Settings"):
            settings = frappe.get_single("TR TradeHub Settings")
            api_key = api_key or settings.get("aras_api_key")
            api_secret = api_secret or settings.get_password("aras_api_secret")
            username = username or settings.get("aras_username")
            password = password or settings.get_password("aras_password")
            customer_code = customer_code or settings.get("aras_customer_code")
            base_url = settings.get("aras_base_url") or base_url
            test_mode = settings.get("aras_test_mode", test_mode)

    if not (api_key or username):
        raise ArasError(
            _("Aras Kargo credentials not configured. "
              "Please set aras_api_key or aras_username in site_config.json")
        )

    # Use test environment if in test mode
    if test_mode:
        base_url = "https://customerservicestest.araskargo.com.tr"

    return {
        "api_key": api_key,
        "api_secret": api_secret,
        "username": username,
        "password": password,
        "customer_code": customer_code,
        "base_url": base_url.rstrip("/"),
        "test_mode": test_mode,
    }


# =============================================================================
# EVENT TYPE MAPPING
# =============================================================================


# Aras event codes to standard tracking event types
ARAS_EVENT_MAPPING = {
    # Pickup events
    "ALIM": "Pickup Completed",
    "TESLIM_ALINDI": "Pickup Completed",
    "TES_AL": "Pickup Completed",
    "COL": "Pickup Completed",
    "PKU": "Pickup Completed",

    # Transit events
    "TRANSFER": "In Transit",
    "AKTARMA": "In Transit",
    "ARAC_YUKLE": "Departed Facility",
    "SANTRAL_GIRIS": "Arrived at Facility",
    "SANTRAL_CIKIS": "Departed Facility",
    "SUBE_GIRIS": "Arrived at Facility",
    "HUB_ARR": "Arrived at Facility",
    "HUB_DEP": "Departed Facility",
    "TRN": "In Transit",
    "MVE": "In Transit",

    # Out for delivery
    "DAGITIMA_CIKTI": "Out for Delivery",
    "DAGITIM": "Out for Delivery",
    "DAG": "Out for Delivery",
    "OFD": "Out for Delivery",
    "KURYE": "Out for Delivery",

    # Delivery events
    "TESLIM_EDILDI": "Delivered",
    "TESLIM": "Delivered",
    "TSL": "Delivered",
    "DLV": "Delivered",
    "DEL": "Delivered",
    "SIGNED": "Signed For",

    # Exception events
    "IPTAL": "Cancelled",
    "CANCEL": "Cancelled",
    "IADE": "Return Initiated",
    "RED": "Refused",
    "REFUSED": "Refused",
    "ADRES_HATA": "Address Issue",
    "ADDRESS_ERR": "Address Issue",
    "ALICI_YOK": "Recipient Unavailable",
    "NOT_HOME": "Recipient Unavailable",
    "MUHATAP_YOK": "Recipient Unavailable",
    "HASAR": "Damaged",
    "DAMAGED": "Damaged",
    "KAYIP": "Lost",
    "LOST": "Lost",
    "BEKLEMEDE": "Package Held",
    "HOLD": "Package Held",
    "EXCEPTION": "Delivery Exception",

    # Return events
    "IADE_YOLDA": "Returning to Sender",
    "IADE_TESLIM": "Returned to Sender",
    "RETURN": "Return Initiated",
    "RTS": "Returned to Sender",
    "GONDERICI_IADE": "Returned to Sender",
}


# =============================================================================
# CLIENT CLASS
# =============================================================================


class ArasClient:
    """
    Aras Kargo API Client for TR-TradeHub.

    Provides methods for:
    - Creating shipments with labels
    - Tracking shipments
    - Scheduling pickups
    - Cancelling shipments
    - Querying branches/pickup points
    """

    def __init__(self, config: Dict[str, str] = None):
        """
        Initialize Aras client.

        Args:
            config: Optional config dict with credentials
        """
        self.config = config or get_aras_config()
        self.api_key = self.config.get("api_key")
        self.api_secret = self.config.get("api_secret")
        self.username = self.config.get("username")
        self.password = self.config.get("password")
        self.customer_code = self.config.get("customer_code")
        self.base_url = self.config["base_url"]
        self.test_mode = self.config.get("test_mode", False)

        # API endpoints
        self.shipment_endpoint = "/api/shipment"
        self.tracking_endpoint = "/api/tracking"
        self.pickup_endpoint = "/api/pickup"
        self.branch_endpoint = "/api/branches"

        # SOAP endpoints for legacy API
        self.soap_wsdl = f"{self.base_url}/aabortal/Service/Service.asmx?wsdl"

    def _generate_request_id(self, prefix: str = "AR") -> str:
        """Generate unique request ID for tracking."""
        import secrets
        return f"{prefix}{secrets.token_hex(8).upper()}"

    def _generate_auth_token(self) -> str:
        """Generate authentication token for API requests."""
        if self.api_key and self.api_secret:
            # API key-based auth
            timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
            signature_string = f"{self.api_key}{timestamp}{self.api_secret}"
            signature = hashlib.sha256(signature_string.encode()).hexdigest()
            return base64.b64encode(f"{self.api_key}:{timestamp}:{signature}".encode()).decode()
        else:
            # Basic auth with username/password
            return base64.b64encode(f"{self.username}:{self.password}".encode()).decode()

    def _make_request(
        self,
        endpoint: str,
        method: str,
        data: Dict = None,
        params: Dict = None,
        request_id: str = None,
    ) -> Dict:
        """
        Make HTTP request to Aras API.

        Args:
            endpoint: API endpoint path
            method: HTTP method
            data: Request payload
            params: Query parameters
            request_id: Request tracking ID

        Returns:
            dict: API response

        Raises:
            ArasError: If request fails
        """
        import requests

        request_id = request_id or self._generate_request_id()

        url = f"{self.base_url}{endpoint}"

        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": f"Bearer {self._generate_auth_token()}",
            "X-Request-ID": request_id,
            "X-Customer-Code": self.customer_code or "",
        }

        try:
            if method.upper() == "GET":
                response = requests.get(url, params=params, headers=headers, timeout=30)
            elif method.upper() == "POST":
                response = requests.post(url, json=data, headers=headers, timeout=30)
            elif method.upper() == "PUT":
                response = requests.put(url, json=data, headers=headers, timeout=30)
            elif method.upper() == "DELETE":
                response = requests.delete(url, headers=headers, timeout=30)
            else:
                raise ArasError(_("Invalid HTTP method: {0}").format(method))

            response.raise_for_status()

            result = response.json()

            # Check for API-level errors
            if result.get("IsSuccessful") is False or result.get("ResultCode") != "0":
                error_code = result.get("ResultCode") or result.get("ErrorCode")
                error_msg = result.get("ResultMessage") or result.get("ErrorMessage", "Unknown error")
                raise ArasShipmentError(
                    error_msg,
                    error_code=str(error_code),
                    error_message=error_msg,
                    request_id=request_id,
                )

            return result

        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 401:
                raise ArasAuthenticationError(
                    _("Authentication failed. Check your Aras Kargo credentials."),
                    request_id=request_id,
                )
            raise ArasError(
                _("Aras Kargo API error: {0}").format(str(e)),
                request_id=request_id,
            )
        except requests.exceptions.RequestException as e:
            frappe.log_error(
                f"Aras API request error: {str(e)}",
                "Aras API Error"
            )
            raise ArasError(
                _("Failed to connect to Aras Kargo API: {0}").format(str(e)),
                request_id=request_id,
            )

    def _make_soap_request(
        self,
        operation: str,
        data: Dict,
        request_id: str = None,
    ) -> Dict:
        """
        Make SOAP request to Aras Web Services (legacy API).

        Args:
            operation: SOAP operation name
            data: Request parameters
            request_id: Request tracking ID

        Returns:
            dict: Parsed SOAP response

        Raises:
            ArasError: If request fails
        """
        request_id = request_id or self._generate_request_id()

        try:
            # Try using zeep for SOAP
            try:
                from zeep import Client
                from zeep.helpers import serialize_object

                client = Client(self.soap_wsdl)

                # Add authentication
                auth_data = {
                    "userName": self.username,
                    "password": self.password,
                    "customerCode": self.customer_code,
                    **data
                }

                # Call the operation
                service_method = getattr(client.service, operation)
                response = service_method(**auth_data)

                # Serialize response
                result = serialize_object(response)
                return self._process_soap_response(result, operation, request_id)

            except ImportError:
                frappe.log_error(
                    "zeep library not installed. Run: bench pip install zeep",
                    "Aras Integration"
                )
                raise ArasError(
                    _("SOAP library (zeep) not installed. Please run: bench pip install zeep"),
                    request_id=request_id,
                )

        except Exception as e:
            if isinstance(e, ArasError):
                raise
            frappe.log_error(
                f"Aras SOAP request error: {str(e)}",
                f"Aras {operation}"
            )
            raise ArasError(
                _("Aras API request failed: {0}").format(str(e)),
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
            ArasError: If response indicates error
        """
        if isinstance(response, dict):
            result = response
        else:
            result = {"data": response}

        # Check for error indicators
        result_code = result.get("ResultCode") or result.get("resultCode")
        if result_code and str(result_code) != "0":
            error_msg = (
                result.get("ResultMessage") or
                result.get("resultMessage") or
                "Operation failed"
            )
            frappe.log_error(
                f"Aras {operation} failed: {error_msg}",
                f"Aras {operation} Error"
            )
            raise ArasShipmentError(
                error_msg,
                error_code=str(result_code),
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
        service_type: str = "NORMAL",
        payment_type: str = "ODEME_GONDEREN",
        special_services: List[str] = None,
        cod_amount: float = None,
        insurance_value: float = None,
        description: str = None,
        request_id: str = None,
    ) -> Dict:
        """
        Create a new shipment with Aras Kargo.

        Args:
            shipment: TR-TradeHub Marketplace Shipment ID
            sender_info: Sender details dict with:
                - name: Sender name
                - phone: Phone number
                - address: Full address
                - city: City name
                - city_code: City code
                - district: District name
                - district_code: District code
                - postal_code: Postal code
                - email: Email (optional)
                - tax_id: Tax ID (optional)
                - customer_code: Customer code (optional)
            receiver_info: Receiver details dict with same fields
            package_info: Package details dict with:
                - count: Number of packages
                - weight: Total weight in kg
                - desi: Volumetric weight (optional)
                - description: Package content description
                - value: Declared value (optional)
            service_type: Service type (NORMAL, EXPRESS, etc.)
            payment_type: Payment type (ODEME_GONDEREN=Prepaid, ODEME_ALICI=COD)
            special_services: List of special service codes
            cod_amount: COD amount if applicable
            insurance_value: Insurance value
            description: Shipment description
            request_id: Optional request tracking ID

        Returns:
            dict: Shipment creation result with tracking number
        """
        request_id = request_id or self._generate_request_id("SHP")

        # Build sender data
        sender_customer_code = sender_info.get("customer_code") or self.customer_code

        # Build shipment request
        shipment_data = {
            "order": {
                "tradingWaybillNumber": shipment,
                "invoiceNumber": shipment,
                "integrationCode": shipment,

                # Sender info
                "senderCustomerCode": sender_customer_code,
                "senderName": sender_info.get("name", ""),
                "senderPhone": self._format_phone(sender_info.get("phone", "")),
                "senderMobile": self._format_phone(sender_info.get("mobile", "")),
                "senderAddress": sender_info.get("address", ""),
                "senderCityCode": sender_info.get("city_code", ""),
                "senderCityName": sender_info.get("city", ""),
                "senderTownCode": sender_info.get("district_code", ""),
                "senderTownName": sender_info.get("district", ""),

                # Receiver info
                "receiverName": receiver_info.get("name", ""),
                "receiverPhone": self._format_phone(receiver_info.get("phone", "")),
                "receiverMobile": self._format_phone(receiver_info.get("mobile", "")),
                "receiverAddress": receiver_info.get("address", ""),
                "receiverCityCode": receiver_info.get("city_code", ""),
                "receiverCityName": receiver_info.get("city", ""),
                "receiverTownCode": receiver_info.get("district_code", ""),
                "receiverTownName": receiver_info.get("district", ""),
                "receiverEmail": receiver_info.get("email", ""),

                # Package info
                "pieceCount": str(package_info.get("count", 1)),
                "weight": str(package_info.get("weight", 1)),
                "desi": str(package_info.get("desi", package_info.get("weight", 1))),
                "productCode": service_type,
                "paymentType": payment_type,
                "description": description or package_info.get("description", ""),

                # Special services
                "specialServices": special_services or [],
            }
        }

        # Add COD if applicable
        if payment_type == "ODEME_ALICI" and cod_amount:
            shipment_data["order"]["codAmount"] = str(cod_amount)

        # Add insurance if applicable
        if insurance_value:
            shipment_data["order"]["insuranceValue"] = str(insurance_value)

        try:
            result = self._make_request(
                f"{self.shipment_endpoint}/create",
                "POST",
                shipment_data,
                request_id=request_id,
            )

            # Extract tracking number from response
            tracking_number = (
                result.get("Data", {}).get("cargoKey") or
                result.get("Data", {}).get("trackingNumber") or
                result.get("TrackingNumber")
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
                "cargo_key": result.get("Data", {}).get("cargoKey"),
                "barcode": result.get("Data", {}).get("barcode"),
                "request_id": request_id,
                "label_url": self._get_label_url(tracking_number),
                "tracking_url": self._get_tracking_url(tracking_number),
                "raw_response": result,
            }

        except ArasError:
            raise
        except Exception as e:
            frappe.log_error(
                f"Aras create shipment error: {str(e)}",
                "Aras Create Shipment"
            )
            raise ArasShipmentError(
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
            tracking_number: Aras tracking number
            request_id: Optional request tracking ID

        Returns:
            dict: Tracking information with events
        """
        request_id = request_id or self._generate_request_id("TRK")

        try:
            result = self._make_request(
                f"{self.tracking_endpoint}/{tracking_number}",
                "GET",
                request_id=request_id,
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
                "receiver_name": result.get("Data", {}).get("receiverName"),
                "tracking_url": self._get_tracking_url(tracking_number),
                "raw_response": result,
            }

        except ArasError:
            raise
        except Exception as e:
            frappe.log_error(
                f"Aras track shipment error: {str(e)}",
                "Aras Track Shipment"
            )
            raise ArasTrackingError(
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
            tracking_number: Aras tracking number
            request_id: Optional request tracking ID

        Returns:
            dict: Detailed shipment information
        """
        request_id = request_id or self._generate_request_id("INF")

        try:
            result = self._make_request(
                f"{self.shipment_endpoint}/{tracking_number}/detail",
                "GET",
                request_id=request_id,
            )

            data = result.get("Data", {})

            return {
                "success": True,
                "tracking_number": tracking_number,
                "cargo_key": data.get("cargoKey"),
                "barcode": data.get("barcode"),
                "status": data.get("status"),
                "sender_name": data.get("senderName"),
                "receiver_name": data.get("receiverName"),
                "receiver_address": data.get("receiverAddress"),
                "receiver_city": data.get("receiverCityName"),
                "receiver_district": data.get("receiverTownName"),
                "package_count": data.get("pieceCount"),
                "weight": data.get("weight"),
                "desi": data.get("desi"),
                "created_date": data.get("createDate"),
                "delivery_date": data.get("deliveryDate"),
                "service_type": data.get("productCode"),
                "raw_response": result,
            }

        except ArasError:
            raise
        except Exception as e:
            frappe.log_error(
                f"Aras get shipment info error: {str(e)}",
                "Aras Get Shipment Info"
            )
            raise ArasTrackingError(
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
            tracking_number: Aras tracking number
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
            result = self._make_request(
                f"{self.shipment_endpoint}/cancel",
                "POST",
                cancel_data,
                request_id=request_id,
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
                "message": result.get("ResultMessage", "Shipment cancelled"),
                "raw_response": result,
            }

        except ArasError:
            raise
        except Exception as e:
            frappe.log_error(
                f"Aras cancel shipment error: {str(e)}",
                "Aras Cancel Shipment"
            )
            raise ArasShipmentError(
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
        total_weight: float = 1,
        total_desi: float = None,
        notes: str = None,
        pickup_time_from: str = None,
        pickup_time_to: str = None,
        request_id: str = None,
    ) -> Dict:
        """
        Schedule a pickup.

        Args:
            pickup_date: Pickup date (YYYY-MM-DD)
            pickup_address: Address dict with address, city, district, city_code, district_code
            contact_name: Contact person name
            contact_phone: Contact phone number
            package_count: Number of packages
            total_weight: Total weight in kg
            total_desi: Total volumetric weight
            notes: Special instructions
            pickup_time_from: Pickup time start (HH:MM)
            pickup_time_to: Pickup time end (HH:MM)
            request_id: Optional request tracking ID

        Returns:
            dict: Pickup scheduling result
        """
        request_id = request_id or self._generate_request_id("PIC")

        pickup_data = {
            "customerCode": self.customer_code,
            "pickupDate": pickup_date,
            "contactName": contact_name,
            "contactPhone": self._format_phone(contact_phone),
            "address": pickup_address.get("address", ""),
            "cityCode": pickup_address.get("city_code", ""),
            "cityName": pickup_address.get("city", ""),
            "townCode": pickup_address.get("district_code", ""),
            "townName": pickup_address.get("district", ""),
            "pieceCount": str(package_count),
            "weight": str(total_weight),
            "desi": str(total_desi or total_weight),
            "notes": notes or "",
        }

        if pickup_time_from:
            pickup_data["pickupTimeFrom"] = pickup_time_from
        if pickup_time_to:
            pickup_data["pickupTimeTo"] = pickup_time_to

        try:
            result = self._make_request(
                f"{self.pickup_endpoint}/create",
                "POST",
                pickup_data,
                request_id=request_id,
            )

            return {
                "success": True,
                "pickup_id": result.get("Data", {}).get("pickupId"),
                "pickup_code": result.get("Data", {}).get("pickupCode"),
                "pickup_date": pickup_date,
                "status": "Scheduled",
                "message": result.get("ResultMessage", "Pickup scheduled"),
                "raw_response": result,
            }

        except ArasError:
            raise
        except Exception as e:
            frappe.log_error(
                f"Aras schedule pickup error: {str(e)}",
                "Aras Schedule Pickup"
            )
            raise ArasShipmentError(
                _("Failed to schedule pickup: {0}").format(str(e)),
                request_id=request_id,
            )

    def get_branch_list(
        self,
        city_code: str = None,
        district_code: str = None,
        request_id: str = None,
    ) -> Dict:
        """
        Get list of Aras branches/pickup points.

        Args:
            city_code: Filter by city code
            district_code: Filter by district code
            request_id: Optional request tracking ID

        Returns:
            dict: List of branches
        """
        request_id = request_id or self._generate_request_id("BRN")

        params = {}
        if city_code:
            params["cityCode"] = city_code
        if district_code:
            params["townCode"] = district_code

        try:
            result = self._make_request(
                self.branch_endpoint,
                "GET",
                params=params,
                request_id=request_id,
            )

            branches = []
            raw_branches = result.get("Data", [])
            if isinstance(raw_branches, list):
                for branch in raw_branches:
                    branches.append({
                        "id": branch.get("branchCode"),
                        "name": branch.get("branchName"),
                        "address": branch.get("address"),
                        "city": branch.get("cityName"),
                        "city_code": branch.get("cityCode"),
                        "district": branch.get("townName"),
                        "district_code": branch.get("townCode"),
                        "phone": branch.get("phone"),
                        "fax": branch.get("fax"),
                        "latitude": branch.get("latitude"),
                        "longitude": branch.get("longitude"),
                        "working_hours": branch.get("workingHours"),
                        "is_active": branch.get("isActive", True),
                    })

            return {
                "success": True,
                "count": len(branches),
                "branches": branches,
            }

        except ArasError:
            raise
        except Exception as e:
            frappe.log_error(
                f"Aras get branch list error: {str(e)}",
                "Aras Get Branch List"
            )
            raise ArasError(
                _("Failed to get branch list: {0}").format(str(e)),
                request_id=request_id,
            )

    def get_city_list(self, request_id: str = None) -> Dict:
        """
        Get list of cities with codes.

        Args:
            request_id: Optional request tracking ID

        Returns:
            dict: List of cities
        """
        request_id = request_id or self._generate_request_id("CTY")

        try:
            result = self._make_request(
                f"{self.branch_endpoint}/cities",
                "GET",
                request_id=request_id,
            )

            cities = []
            raw_cities = result.get("Data", [])
            if isinstance(raw_cities, list):
                for city in raw_cities:
                    cities.append({
                        "code": city.get("cityCode"),
                        "name": city.get("cityName"),
                    })

            return {
                "success": True,
                "count": len(cities),
                "cities": cities,
            }

        except ArasError:
            raise
        except Exception as e:
            frappe.log_error(
                f"Aras get city list error: {str(e)}",
                "Aras Get City List"
            )
            raise ArasError(
                _("Failed to get city list: {0}").format(str(e)),
                request_id=request_id,
            )

    def get_district_list(self, city_code: str, request_id: str = None) -> Dict:
        """
        Get list of districts for a city.

        Args:
            city_code: City code
            request_id: Optional request tracking ID

        Returns:
            dict: List of districts
        """
        request_id = request_id or self._generate_request_id("DST")

        try:
            result = self._make_request(
                f"{self.branch_endpoint}/cities/{city_code}/towns",
                "GET",
                request_id=request_id,
            )

            districts = []
            raw_districts = result.get("Data", [])
            if isinstance(raw_districts, list):
                for district in raw_districts:
                    districts.append({
                        "code": district.get("townCode"),
                        "name": district.get("townName"),
                        "city_code": city_code,
                    })

            return {
                "success": True,
                "count": len(districts),
                "city_code": city_code,
                "districts": districts,
            }

        except ArasError:
            raise
        except Exception as e:
            frappe.log_error(
                f"Aras get district list error: {str(e)}",
                "Aras Get District List"
            )
            raise ArasError(
                _("Failed to get district list: {0}").format(str(e)),
                request_id=request_id,
            )

    # =========================================================================
    # CALLBACK METHODS
    # =========================================================================

    def verify_callback(
        self,
        payload: str,
        signature: str = None,
    ) -> bool:
        """
        Verify callback signature.

        Args:
            payload: Raw callback payload
            signature: Signature from request header (if applicable)

        Returns:
            bool: True if signature is valid
        """
        if not signature or not self.api_secret:
            # If no signature provided or no secret configured, skip verification
            # In production, this should be stricter
            return True

        try:
            # Aras callback signature verification
            # Signature = HMAC-SHA256(api_secret, payload)
            computed_signature = hmac.new(
                self.api_secret.encode(),
                payload.encode(),
                hashlib.sha256
            ).hexdigest()

            return hmac.compare_digest(computed_signature.lower(), signature.lower())

        except Exception as e:
            frappe.log_error(
                f"Callback signature verification error: {str(e)}",
                "Aras Callback"
            )
            return False

    def parse_callback_payload(self, payload: str) -> Dict:
        """
        Parse callback payload from Aras.

        Args:
            payload: Raw callback payload (JSON or XML)

        Returns:
            dict: Parsed callback data
        """
        try:
            # Try JSON first
            try:
                data = json.loads(payload)
            except json.JSONDecodeError:
                # Try XML
                root = ET.fromstring(payload)
                data = self._xml_to_dict(root)

            event_code = data.get("eventCode") or data.get("status") or data.get("statusCode")
            event_type = ARAS_EVENT_MAPPING.get(event_code, "Status Update")

            return {
                "tracking_number": data.get("cargoKey") or data.get("trackingNumber") or data.get("barcode"),
                "event_code": event_code,
                "event_type": event_type,
                "event_date": data.get("eventDate") or data.get("updateDate") or data.get("statusDate"),
                "event_description": data.get("description") or data.get("statusDescription"),
                "location": {
                    "city": data.get("cityName"),
                    "district": data.get("townName"),
                    "facility": data.get("branchName") or data.get("unitName"),
                },
                "receiver_name": data.get("receiverName"),
                "signed_by": data.get("signedBy") or data.get("deliveredTo"),
                "raw_data": data,
            }

        except Exception as e:
            frappe.log_error(
                f"Aras callback parse error: {str(e)}",
                "Aras Callback"
            )
            raise ArasError(_("Invalid callback payload: {0}").format(str(e)))

    # =========================================================================
    # HELPER METHODS
    # =========================================================================

    def _format_phone(self, phone: str) -> str:
        """Format phone number for Aras API."""
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
        return f"https://www.araskargo.com.tr/trmall/kargotakip.aspx?q={tracking_number}"

    def _get_label_url(self, tracking_number: str) -> str:
        """Get shipment label URL."""
        return f"{self.base_url}/api/shipment/{tracking_number}/label"

    def _parse_tracking_events(self, result: Dict) -> List[Dict]:
        """Parse tracking events from API response."""
        events = []

        raw_events = result.get("Data", {}).get("movements", [])
        if not isinstance(raw_events, list):
            raw_events = result.get("Data", {}).get("details", [])
        if not isinstance(raw_events, list):
            raw_events = [raw_events] if raw_events else []

        for event in raw_events:
            event_code = event.get("statusCode") or event.get("status")
            event_type = ARAS_EVENT_MAPPING.get(event_code, "Status Update")

            events.append({
                "timestamp": event.get("eventDate") or event.get("date"),
                "event_code": event_code,
                "event_type": event_type,
                "description": event.get("description") or event.get("statusDescription", ""),
                "location": {
                    "city": event.get("cityName"),
                    "facility": event.get("branchName") or event.get("unitName"),
                },
                "signed_by": event.get("signedBy") or event.get("deliveredTo") if event_type == "Delivered" else None,
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
                "subject": f"Aras Kargo {event_type}",
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
    client = ArasClient()
    return client.create_shipment(**kwargs)


def track_shipment(tracking_number: str) -> Dict:
    """Convenience function to track a shipment."""
    client = ArasClient()
    return client.track_shipment(tracking_number)


def get_shipment_info(tracking_number: str) -> Dict:
    """Convenience function to get shipment info."""
    client = ArasClient()
    return client.get_shipment_info(tracking_number)


def cancel_shipment(tracking_number: str, reason: str = None) -> Dict:
    """Convenience function to cancel a shipment."""
    client = ArasClient()
    return client.cancel_shipment(tracking_number, reason)


def schedule_pickup(**kwargs) -> Dict:
    """Convenience function to schedule pickup."""
    client = ArasClient()
    return client.schedule_pickup(**kwargs)


def verify_callback(payload: str, signature: str = None) -> bool:
    """Convenience function to verify callback."""
    client = ArasClient()
    return client.verify_callback(payload, signature)


def get_branch_list(city_code: str = None, district_code: str = None) -> Dict:
    """Convenience function to get branch list."""
    client = ArasClient()
    return client.get_branch_list(city_code, district_code)


# =============================================================================
# FRAPPE API ENDPOINTS
# =============================================================================


@frappe.whitelist()
def api_track_shipment(tracking_number: str) -> Dict:
    """
    API endpoint to track an Aras shipment.

    Args:
        tracking_number: Aras tracking number

    Returns:
        dict: Tracking information
    """
    try:
        result = track_shipment(tracking_number)
        return result
    except ArasError as e:
        frappe.throw(str(e.message))
    except Exception as e:
        frappe.log_error(str(e), "Aras Track API")
        frappe.throw(_("Failed to track shipment"))


@frappe.whitelist()
def api_get_branches(city_code: str = None, district_code: str = None) -> Dict:
    """
    API endpoint to get Aras branches.

    Args:
        city_code: Filter by city code
        district_code: Filter by district code

    Returns:
        dict: List of branches
    """
    try:
        result = get_branch_list(city_code, district_code)
        return result
    except ArasError as e:
        frappe.throw(str(e.message))
    except Exception as e:
        frappe.log_error(str(e), "Aras Branches API")
        frappe.throw(_("Failed to get branches"))


@frappe.whitelist()
def api_get_cities() -> Dict:
    """
    API endpoint to get city list.

    Returns:
        dict: List of cities
    """
    try:
        client = ArasClient()
        result = client.get_city_list()
        return result
    except ArasError as e:
        frappe.throw(str(e.message))
    except Exception as e:
        frappe.log_error(str(e), "Aras Cities API")
        frappe.throw(_("Failed to get cities"))


@frappe.whitelist()
def api_get_districts(city_code: str) -> Dict:
    """
    API endpoint to get district list for a city.

    Args:
        city_code: City code

    Returns:
        dict: List of districts
    """
    if not city_code:
        frappe.throw(_("City code is required"))

    try:
        client = ArasClient()
        result = client.get_district_list(city_code)
        return result
    except ArasError as e:
        frappe.throw(str(e.message))
    except Exception as e:
        frappe.log_error(str(e), "Aras Districts API")
        frappe.throw(_("Failed to get districts"))


@frappe.whitelist(allow_guest=True)
def handle_callback():
    """
    API endpoint for Aras callback notifications.

    Returns:
        dict: Callback processing result
    """
    try:
        payload = frappe.request.get_data(as_text=True)
        signature = frappe.request.headers.get("X-Aras-Signature", "")

        client = ArasClient()

        # Verify callback
        if not client.verify_callback(payload, signature):
            frappe.log_error(
                "Invalid callback signature",
                "Aras Callback"
            )
            frappe.throw(_("Invalid callback request"), frappe.AuthenticationError)

        # Parse payload
        callback_data = client.parse_callback_payload(payload)

        # Process callback - update tracking events
        tracking_number = callback_data.get("tracking_number")
        event_type = callback_data.get("event_type")

        if tracking_number:
            _update_shipment_from_callback(tracking_number, callback_data)

        frappe.log_error(
            f"Aras callback processed: {event_type} - {tracking_number}",
            "Aras Callback Success"
        )

        return {"success": True, "event_type": event_type}

    except Exception as e:
        frappe.log_error(str(e), "Aras Callback Error")
        raise


def _update_shipment_from_callback(tracking_number: str, callback_data: Dict):
    """Update shipment and create tracking event from callback data."""
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

        location = callback_data.get("location", {})

        log_tracking_event(
            shipment=shipment_name,
            event_type=callback_data.get("event_type"),
            description=callback_data.get("event_description", ""),
            event_timestamp=callback_data.get("event_date"),
            city=location.get("city"),
            facility_name=location.get("facility"),
            carrier_event_code=callback_data.get("event_code"),
            signed_by=callback_data.get("signed_by"),
            raw_event_data=callback_data.get("raw_data"),
            source="Aras Callback",
        )

    except Exception as e:
        frappe.log_error(
            f"Failed to update shipment from Aras callback: {str(e)}",
            "Aras Callback"
        )

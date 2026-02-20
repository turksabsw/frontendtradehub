# Copyright (c) 2026, Trade Hub and contributors
# For license information, please see license.txt

"""
Carrier DocType for Trade Hub B2B Marketplace.

This module implements the Carrier DocType that defines shipping carriers
such as FedEx, DHL, UPS, etc. Carriers can be global or tenant-specific
and define the configuration for each shipping provider.

Key Features:
- Support for various carrier types (Courier, Freight, Postal, Express, etc.)
- Service methods and capabilities (tracking, COD, insurance)
- Multi-tenant support (carriers can be global or tenant-specific)
- API integration configuration for automated shipping
- Rate settings and pricing configuration
- Standard carriers creation (DHL, FedEx, UPS, etc.)
- Turkish carrier support (Yurtiçi, Aras, MNG, PTT, Sürat)
- Webhook integration for tracking updates
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime, cint
import requests
import json
from typing import Dict, Optional, List


class Carrier(Document):
    """
    Carrier DocType defining shipping carriers.

    Carriers represent shipping providers that can be used for shipments.
    They define the carrier type, service methods, capabilities,
    rate settings, and API integration configuration.
    """

    def before_insert(self):
        """Set default values before inserting a new carrier."""
        self.set_tenant_from_user()
        self.generate_carrier_code()

    def validate(self):
        """Validate carrier data before saving."""
        self.validate_carrier_name()
        self.validate_carrier_code()
        self.validate_tenant_consistency()
        self.validate_default_carrier()
        self.validate_rate_settings()
        self.validate_tracking_url_template()

    def on_update(self):
        """Actions after carrier is updated."""
        self.clear_carrier_cache()

    def on_trash(self):
        """Prevent deletion of carrier with linked shipments."""
        self.check_linked_shipments()

    # =========================================================================
    # INITIALIZATION METHODS
    # =========================================================================

    def set_tenant_from_user(self):
        """Set tenant from current user if not already set."""
        if not self.tenant and not self.is_global:
            user_tenant = frappe.db.get_value("User", frappe.session.user, "tenant")
            if user_tenant:
                self.tenant = user_tenant

    def generate_carrier_code(self):
        """Generate carrier code from carrier name if not provided."""
        if not self.carrier_code and self.carrier_name:
            # Convert to uppercase and replace special characters
            code = self.carrier_name.upper()
            code = code.replace(" ", "-")
            # Remove special characters except hyphens
            code = "".join(c for c in code if c.isalnum() or c == "-")
            # Remove consecutive hyphens
            while "--" in code:
                code = code.replace("--", "-")
            code = code.strip("-")

            # Ensure uniqueness
            base_code = code
            counter = 1
            while frappe.db.exists("Carrier", {"carrier_code": code}):
                code = f"{base_code}-{counter}"
                counter += 1

            self.carrier_code = code

    # =========================================================================
    # VALIDATION METHODS
    # =========================================================================

    def validate_carrier_name(self):
        """Validate carrier name."""
        if not self.carrier_name:
            frappe.throw(_("Carrier Name is required"))

        # Check for invalid characters
        if any(char in self.carrier_name for char in ["<", ">", '"', "\\"]):
            frappe.throw(_("Carrier Name contains invalid characters"))

        # Check length
        if len(self.carrier_name) > 140:
            frappe.throw(_("Carrier Name cannot exceed 140 characters"))

        # Trim whitespace
        self.carrier_name = self.carrier_name.strip()

    def validate_carrier_code(self):
        """Validate carrier code."""
        if not self.carrier_code:
            frappe.throw(_("Carrier Code is required"))

        # Ensure uppercase
        self.carrier_code = self.carrier_code.upper()

        # Check for valid characters (alphanumeric and hyphens only)
        if not all(c.isalnum() or c == "-" for c in self.carrier_code):
            frappe.throw(
                _("Carrier Code can only contain letters, numbers, and hyphens")
            )

    def validate_tenant_consistency(self):
        """Ensure tenant consistency for carriers."""
        # Global carriers should not have tenant
        if self.is_global and self.tenant:
            self.tenant = None
            self.tenant_name = None

        # Non-global carriers need tenant
        if not self.is_global and not self.tenant:
            # Only admin can create global carriers
            if not frappe.has_permission("Tenant", "write"):
                frappe.throw(
                    _("Please select a tenant or mark the carrier as global")
                )

    def validate_default_carrier(self):
        """Ensure only one default carrier per tenant/global scope."""
        if self.is_default and self.enabled:
            # Check for existing default carrier
            filters = {"is_default": 1, "enabled": 1, "name": ["!=", self.name]}

            if self.is_global:
                filters["is_global"] = 1
            elif self.tenant:
                filters["tenant"] = self.tenant
            else:
                filters["is_global"] = 1

            existing_default = frappe.db.exists("Carrier", filters)
            if existing_default:
                # Unset the existing default
                frappe.db.set_value(
                    "Carrier", existing_default, "is_default", 0, update_modified=False
                )

    def validate_rate_settings(self):
        """Validate rate settings."""
        if self.min_weight and self.min_weight < 0:
            frappe.throw(_("Minimum Weight cannot be negative"))

        if self.max_weight and self.max_weight < 0:
            frappe.throw(_("Maximum Weight cannot be negative"))

        if self.min_weight and self.max_weight and self.min_weight > self.max_weight:
            frappe.throw(_("Minimum Weight cannot be greater than Maximum Weight"))

        if self.default_transit_days and self.default_transit_days < 0:
            frappe.throw(_("Default Transit Days cannot be negative"))

        if self.dimensional_divisor and self.dimensional_divisor <= 0:
            frappe.throw(_("Dimensional Divisor must be greater than zero"))

        if self.fuel_surcharge_percent and (
            self.fuel_surcharge_percent < 0 or self.fuel_surcharge_percent > 100
        ):
            frappe.throw(_("Fuel Surcharge must be between 0 and 100 percent"))

        if self.base_rate and self.base_rate < 0:
            frappe.throw(_("Base Rate cannot be negative"))

        if self.rate_per_kg and self.rate_per_kg < 0:
            frappe.throw(_("Rate per KG cannot be negative"))

    def validate_tracking_url_template(self):
        """Validate tracking URL template format."""
        if self.tracking_url_template:
            # Template should be a valid URL format
            template = self.tracking_url_template.strip()
            if not template.startswith(("http://", "https://")):
                frappe.throw(
                    _("Tracking URL Template must start with http:// or https://")
                )
            self.tracking_url_template = template

    # =========================================================================
    # LINKED DOCUMENT CHECKS
    # =========================================================================

    def check_linked_shipments(self):
        """Check for linked shipments before allowing deletion."""
        shipment_count = frappe.db.count("Shipment", {"carrier": self.name})

        if shipment_count > 0:
            frappe.throw(
                _(
                    "Cannot delete carrier with {0} linked shipment(s). "
                    "Please reassign shipments first."
                ).format(shipment_count)
            )

    # =========================================================================
    # SHIPMENT COUNT METHODS
    # =========================================================================

    def update_shipment_count(self):
        """Update the shipment count for this carrier."""
        count = frappe.db.count("Shipment", filters={"carrier": self.name})
        self.db_set("shipment_count", count, update_modified=False)

    def get_shipment_count(self):
        """
        Get count of shipments for this carrier.

        Returns:
            int: Number of shipments
        """
        return frappe.db.count("Shipment", filters={"carrier": self.name})

    # =========================================================================
    # TRACKING URL METHODS
    # =========================================================================

    def get_tracking_url(self, tracking_number):
        """
        Generate tracking URL for a given tracking number.

        Args:
            tracking_number: The shipment tracking number

        Returns:
            str: The tracking URL or None if template not configured
        """
        if not self.tracking_url_template or not tracking_number:
            return None

        return self.tracking_url_template.replace("{tracking_number}", tracking_number)

    # =========================================================================
    # SERVICE AREA METHODS
    # =========================================================================

    def serves_country(self, country_code):
        """
        Check if carrier serves a specific country.

        Args:
            country_code: ISO country code

        Returns:
            bool: True if carrier serves the country
        """
        if not country_code:
            return False

        country_code = country_code.upper()

        # Check excluded countries first
        if self.excluded_countries:
            excluded = [
                c.strip().upper()
                for c in self.excluded_countries.split("\n")
                if c.strip()
            ]
            if country_code in excluded:
                return False

        # If no service countries specified, serves all (except excluded)
        if not self.service_countries:
            return True

        # Check if country is in service list
        service_list = [
            c.strip().upper()
            for c in self.service_countries.split("\n")
            if c.strip()
        ]
        return country_code in service_list

    def get_service_countries_list(self):
        """
        Get list of service countries.

        Returns:
            list: List of country codes
        """
        if not self.service_countries:
            return []

        return [
            c.strip().upper()
            for c in self.service_countries.split("\n")
            if c.strip()
        ]

    def get_service_methods_list(self):
        """
        Get list of available service methods.

        Returns:
            list: List of service method names
        """
        if not self.service_methods:
            return []

        return [m.strip() for m in self.service_methods.split("\n") if m.strip()]

    # =========================================================================
    # RATE CALCULATION METHODS
    # =========================================================================

    def calculate_dimensional_weight(self, length, width, height):
        """
        Calculate dimensional weight based on package dimensions.

        Args:
            length: Package length
            width: Package width
            height: Package height

        Returns:
            float: Dimensional weight
        """
        if not all([length, width, height]):
            return 0

        divisor = self.dimensional_divisor or 5000
        return (length * width * height) / divisor

    def calculate_shipping_rate(self, actual_weight, length=0, width=0, height=0):
        """
        Calculate shipping rate based on weight and dimensions.

        Args:
            actual_weight: Actual package weight
            length: Package length (optional)
            width: Package width (optional)
            height: Package height (optional)

        Returns:
            dict: Rate calculation with base_rate, weight_charge, fuel_surcharge, total
        """
        # Calculate dimensional weight
        dim_weight = self.calculate_dimensional_weight(length, width, height)

        # Use the greater of actual or dimensional weight
        billable_weight = max(actual_weight or 0, dim_weight)

        # Calculate base charges
        base_rate = self.base_rate or 0
        weight_charge = billable_weight * (self.rate_per_kg or 0)

        # Calculate fuel surcharge
        subtotal = base_rate + weight_charge
        fuel_surcharge = subtotal * (self.fuel_surcharge_percent or 0) / 100

        # Calculate total
        total = subtotal + fuel_surcharge

        return {
            "actual_weight": actual_weight,
            "dimensional_weight": dim_weight,
            "billable_weight": billable_weight,
            "base_rate": base_rate,
            "weight_charge": weight_charge,
            "fuel_surcharge": fuel_surcharge,
            "total": total,
            "currency": self.currency or "USD",
        }

    # =========================================================================
    # CACHE MANAGEMENT
    # =========================================================================

    def clear_carrier_cache(self):
        """Clear cached carrier data."""
        cache_keys = [
            "carrier_list",
            f"carrier:{self.name}",
        ]
        if self.tenant:
            cache_keys.append(f"carrier_list:{self.tenant}")

        for key in cache_keys:
            frappe.cache().delete_value(key)

    # =========================================================================
    # API INTEGRATION METHODS
    # =========================================================================

    def test_api_connection(self) -> Dict:
        """
        Test API connection to the carrier.

        Returns:
            dict: Connection test result with status and message
        """
        if not self.has_api_integration:
            return {
                "status": "error",
                "message": _("API integration is not enabled for this carrier")
            }

        if not self.api_endpoint:
            return {
                "status": "error",
                "message": _("API endpoint is not configured")
            }

        try:
            # Build request based on API provider
            headers = self._get_api_headers()
            timeout = cint(self.api_timeout) or 30

            # Make a test request to the API endpoint
            response = requests.get(
                self.api_endpoint,
                headers=headers,
                timeout=timeout
            )

            # Update API status
            self.db_set("api_last_checked", now_datetime())

            if response.status_code == 200:
                self.db_set("api_status", "Online")
                self.db_set("api_error_message", None)
                return {
                    "status": "success",
                    "message": _("API connection successful"),
                    "response_code": response.status_code
                }
            else:
                self.db_set("api_status", "Error")
                self.db_set("api_error_message", f"HTTP {response.status_code}")
                return {
                    "status": "error",
                    "message": _("API returned error: {0}").format(response.status_code),
                    "response_code": response.status_code
                }

        except requests.Timeout:
            self.db_set("api_status", "Offline")
            self.db_set("api_error_message", "Connection timeout")
            return {
                "status": "error",
                "message": _("API connection timed out")
            }
        except requests.ConnectionError as e:
            self.db_set("api_status", "Offline")
            self.db_set("api_error_message", str(e)[:200])
            return {
                "status": "error",
                "message": _("Could not connect to API: {0}").format(str(e))
            }
        except Exception as e:
            self.db_set("api_status", "Error")
            self.db_set("api_error_message", str(e)[:200])
            frappe.log_error(
                f"Carrier API test failed for {self.name}: {str(e)}",
                "Carrier API Error"
            )
            return {
                "status": "error",
                "message": _("API error: {0}").format(str(e))
            }

    def _get_api_headers(self) -> Dict:
        """
        Build API headers based on carrier configuration.

        Returns:
            dict: Headers for API requests
        """
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json"
        }

        if self.api_key:
            api_key = self.get_password("api_key")
            if self.api_provider in ["Yurtici", "Aras", "MNG", "PTT", "Surat"]:
                # Turkish carriers often use different auth headers
                headers["Authorization"] = f"Bearer {api_key}"
                if self.api_account_number:
                    headers["X-Account-Number"] = self.api_account_number
            elif self.api_provider == "EasyPost":
                headers["Authorization"] = f"Basic {api_key}"
            elif self.api_provider in ["Shippo", "ShipStation", "ShipEngine"]:
                headers["Authorization"] = f"ShippoToken {api_key}"
            else:
                headers["Authorization"] = f"Bearer {api_key}"

        return headers

    def get_rates_from_api(
        self,
        origin_address: Dict,
        destination_address: Dict,
        package: Dict
    ) -> Dict:
        """
        Get shipping rates from carrier API.

        Args:
            origin_address: Origin address dict (city, country, postal_code)
            destination_address: Destination address dict
            package: Package details (weight, length, width, height)

        Returns:
            dict: Rate calculation result with available services and prices
        """
        if not self.has_api_integration or not self.supports_rate_api:
            # Fall back to local calculation
            return {
                "status": "fallback",
                "rates": [self.calculate_shipping_rate(
                    package.get("weight", 0),
                    package.get("length", 0),
                    package.get("width", 0),
                    package.get("height", 0)
                )],
                "message": _("Using local rate calculation")
            }

        try:
            headers = self._get_api_headers()
            timeout = cint(self.api_timeout) or 30

            # Build rate request based on provider
            rate_endpoint = f"{self.api_endpoint}/rates"
            payload = self._build_rate_request(origin_address, destination_address, package)

            response = requests.post(
                rate_endpoint,
                headers=headers,
                json=payload,
                timeout=timeout
            )

            if response.status_code == 200:
                rates = self._parse_rate_response(response.json())
                return {
                    "status": "success",
                    "rates": rates,
                    "carrier": self.carrier_name
                }
            else:
                frappe.log_error(
                    f"Rate API error for {self.name}: {response.text[:500]}",
                    "Carrier Rate API Error"
                )
                # Fall back to local calculation
                return {
                    "status": "fallback",
                    "rates": [self.calculate_shipping_rate(
                        package.get("weight", 0),
                        package.get("length", 0),
                        package.get("width", 0),
                        package.get("height", 0)
                    )],
                    "message": _("API error, using local calculation")
                }

        except Exception as e:
            frappe.log_error(
                f"Rate API exception for {self.name}: {str(e)}",
                "Carrier Rate API Error"
            )
            return {
                "status": "fallback",
                "rates": [self.calculate_shipping_rate(
                    package.get("weight", 0),
                    package.get("length", 0),
                    package.get("width", 0),
                    package.get("height", 0)
                )],
                "message": _("API exception, using local calculation")
            }

    def _build_rate_request(
        self,
        origin_address: Dict,
        destination_address: Dict,
        package: Dict
    ) -> Dict:
        """
        Build rate request payload based on API provider.

        Returns:
            dict: Rate request payload
        """
        if self.api_provider in ["Yurtici", "Aras", "MNG", "PTT", "Surat"]:
            # Turkish carrier format
            return {
                "origin": {
                    "city": origin_address.get("city"),
                    "district": origin_address.get("district"),
                    "postal_code": origin_address.get("postal_code")
                },
                "destination": {
                    "city": destination_address.get("city"),
                    "district": destination_address.get("district"),
                    "postal_code": destination_address.get("postal_code")
                },
                "package": {
                    "weight": package.get("weight", 0),
                    "length": package.get("length", 0),
                    "width": package.get("width", 0),
                    "height": package.get("height", 0),
                    "quantity": package.get("quantity", 1)
                },
                "service_type": package.get("service_type", "standard")
            }
        else:
            # International/standard format
            return {
                "shipment": {
                    "address_from": origin_address,
                    "address_to": destination_address,
                    "parcels": [{
                        "weight": package.get("weight", 0),
                        "length": package.get("length", 0),
                        "width": package.get("width", 0),
                        "height": package.get("height", 0),
                        "mass_unit": self.weight_uom or "kg",
                        "distance_unit": "cm"
                    }]
                }
            }

    def _parse_rate_response(self, response_data: Dict) -> List[Dict]:
        """
        Parse rate response from API.

        Returns:
            list: List of rate options
        """
        rates = []

        if self.api_provider in ["Yurtici", "Aras", "MNG", "PTT", "Surat"]:
            # Turkish carrier response format
            for rate in response_data.get("rates", []):
                rates.append({
                    "service": rate.get("service_name"),
                    "price": rate.get("price"),
                    "currency": rate.get("currency", "TRY"),
                    "transit_days": rate.get("transit_days"),
                    "carrier": self.carrier_name
                })
        else:
            # Standard response format
            for rate in response_data.get("rates", response_data.get("results", [])):
                rates.append({
                    "service": rate.get("servicelevel", {}).get("name", rate.get("service")),
                    "price": rate.get("amount", rate.get("price")),
                    "currency": rate.get("currency", self.currency or "USD"),
                    "transit_days": rate.get("estimated_days", rate.get("transit_days")),
                    "carrier": self.carrier_name
                })

        return rates or [{
            "service": "Standard",
            "price": 0,
            "currency": self.currency or "USD",
            "transit_days": self.default_transit_days,
            "carrier": self.carrier_name
        }]

    def create_shipment_label(
        self,
        shipment_data: Dict
    ) -> Dict:
        """
        Create shipping label via carrier API.

        Args:
            shipment_data: Shipment details including addresses and package info

        Returns:
            dict: Label creation result with tracking number and label URL
        """
        if not self.has_api_integration or not self.supports_label_api:
            return {
                "status": "error",
                "message": _("Label API is not enabled for this carrier")
            }

        try:
            headers = self._get_api_headers()
            timeout = cint(self.api_timeout) or 30

            label_endpoint = f"{self.api_endpoint}/shipments"
            payload = self._build_label_request(shipment_data)

            response = requests.post(
                label_endpoint,
                headers=headers,
                json=payload,
                timeout=timeout
            )

            if response.status_code in [200, 201]:
                result = self._parse_label_response(response.json())
                return {
                    "status": "success",
                    **result
                }
            else:
                error_msg = response.text[:500]
                frappe.log_error(
                    f"Label API error for {self.name}: {error_msg}",
                    "Carrier Label API Error"
                )
                return {
                    "status": "error",
                    "message": _("Label creation failed: {0}").format(error_msg)
                }

        except Exception as e:
            frappe.log_error(
                f"Label API exception for {self.name}: {str(e)}",
                "Carrier Label API Error"
            )
            return {
                "status": "error",
                "message": _("Label API error: {0}").format(str(e))
            }

    def _build_label_request(self, shipment_data: Dict) -> Dict:
        """
        Build label request payload based on API provider.

        Returns:
            dict: Label request payload
        """
        if self.api_provider in ["Yurtici", "Aras", "MNG", "PTT", "Surat"]:
            # Turkish carrier format
            return {
                "sender": shipment_data.get("sender", {}),
                "receiver": shipment_data.get("receiver", {}),
                "package": shipment_data.get("package", {}),
                "service_type": shipment_data.get("service_type", "standard"),
                "cod_amount": shipment_data.get("cod_amount", 0),
                "reference": shipment_data.get("reference", ""),
                "contents": shipment_data.get("contents", "")
            }
        else:
            return {
                "shipment": shipment_data.get("shipment", shipment_data),
                "carrier": self.api_provider.lower() if self.api_provider else "custom"
            }

    def _parse_label_response(self, response_data: Dict) -> Dict:
        """
        Parse label creation response from API.

        Returns:
            dict: Parsed label result
        """
        if self.api_provider in ["Yurtici", "Aras", "MNG", "PTT", "Surat"]:
            return {
                "tracking_number": response_data.get("tracking_number", response_data.get("barcode")),
                "label_url": response_data.get("label_url"),
                "label_data": response_data.get("label_base64"),
                "shipment_id": response_data.get("shipment_id")
            }
        else:
            return {
                "tracking_number": response_data.get("tracking_number", response_data.get("tracking_code")),
                "label_url": response_data.get("label_url", response_data.get("postage_label", {}).get("label_url")),
                "shipment_id": response_data.get("id", response_data.get("object_id"))
            }

    def get_tracking_from_api(self, tracking_number: str) -> Dict:
        """
        Get tracking information from carrier API.

        Args:
            tracking_number: The shipment tracking number

        Returns:
            dict: Tracking information with status and events
        """
        if not self.has_api_integration or not self.tracking_api_enabled:
            # Return URL-based tracking instead
            return {
                "status": "url_only",
                "tracking_url": self.get_tracking_url(tracking_number),
                "message": _("Use tracking URL for status updates")
            }

        try:
            headers = self._get_api_headers()
            timeout = cint(self.api_timeout) or 30

            tracking_endpoint = f"{self.api_endpoint}/tracking/{tracking_number}"

            response = requests.get(
                tracking_endpoint,
                headers=headers,
                timeout=timeout
            )

            if response.status_code == 200:
                result = self._parse_tracking_response(response.json())
                return {
                    "status": "success",
                    **result
                }
            else:
                return {
                    "status": "error",
                    "message": _("Tracking lookup failed"),
                    "tracking_url": self.get_tracking_url(tracking_number)
                }

        except Exception as e:
            frappe.log_error(
                f"Tracking API error for {self.name}: {str(e)}",
                "Carrier Tracking API Error"
            )
            return {
                "status": "error",
                "message": _("Tracking API error: {0}").format(str(e)),
                "tracking_url": self.get_tracking_url(tracking_number)
            }

    def _parse_tracking_response(self, response_data: Dict) -> Dict:
        """
        Parse tracking response from API.

        Returns:
            dict: Parsed tracking result
        """
        events = []

        if self.api_provider in ["Yurtici", "Aras", "MNG", "PTT", "Surat"]:
            # Turkish carrier tracking format
            for event in response_data.get("events", response_data.get("movements", [])):
                events.append({
                    "timestamp": event.get("date", event.get("timestamp")),
                    "status": event.get("status", event.get("description")),
                    "location": event.get("location", event.get("branch")),
                    "description": event.get("description", event.get("detail"))
                })

            return {
                "current_status": response_data.get("status", response_data.get("current_status")),
                "delivered": response_data.get("delivered", False),
                "delivery_date": response_data.get("delivery_date"),
                "events": events,
                "estimated_delivery": response_data.get("estimated_delivery")
            }
        else:
            # Standard tracking format
            for event in response_data.get("tracking_history", response_data.get("events", [])):
                events.append({
                    "timestamp": event.get("datetime", event.get("timestamp")),
                    "status": event.get("status_details", event.get("status")),
                    "location": event.get("location", {}).get("city") if isinstance(event.get("location"), dict) else event.get("location"),
                    "description": event.get("message", event.get("description"))
                })

            return {
                "current_status": response_data.get("tracking_status", {}).get("status") if isinstance(response_data.get("tracking_status"), dict) else response_data.get("status"),
                "delivered": response_data.get("tracking_status", {}).get("status") == "DELIVERED" if isinstance(response_data.get("tracking_status"), dict) else response_data.get("delivered", False),
                "events": events,
                "estimated_delivery": response_data.get("eta")
            }

    def process_webhook_event(self, event_type: str, payload: Dict) -> Dict:
        """
        Process incoming webhook event from carrier.

        Args:
            event_type: Type of webhook event (tracking_update, delivered, etc.)
            payload: Webhook event payload

        Returns:
            dict: Processing result
        """
        if not self.webhook_enabled:
            return {"status": "error", "message": _("Webhooks not enabled")}

        try:
            if event_type == "tracking_update":
                return self._process_tracking_webhook(payload)
            elif event_type == "delivered":
                return self._process_delivery_webhook(payload)
            elif event_type == "exception":
                return self._process_exception_webhook(payload)
            else:
                frappe.log_error(
                    f"Unknown webhook event type: {event_type}",
                    "Carrier Webhook"
                )
                return {"status": "ignored", "message": _("Unknown event type")}

        except Exception as e:
            frappe.log_error(
                f"Webhook processing error for {self.name}: {str(e)}",
                "Carrier Webhook Error"
            )
            return {"status": "error", "message": str(e)}

    def _process_tracking_webhook(self, payload: Dict) -> Dict:
        """Process tracking update webhook."""
        tracking_number = payload.get("tracking_number", payload.get("barcode"))
        status = payload.get("status")

        if not tracking_number:
            return {"status": "error", "message": _("Missing tracking number")}

        # Find and update the shipment
        shipment = frappe.db.get_value(
            "Shipment",
            {"tracking_number": tracking_number},
            "name"
        )

        if shipment:
            frappe.get_doc("Shipment", shipment).update_tracking_status(status, payload)
            return {"status": "success", "shipment": shipment}

        return {"status": "not_found", "message": _("Shipment not found")}

    def _process_delivery_webhook(self, payload: Dict) -> Dict:
        """Process delivery confirmation webhook."""
        tracking_number = payload.get("tracking_number", payload.get("barcode"))

        if not tracking_number:
            return {"status": "error", "message": _("Missing tracking number")}

        shipment = frappe.db.get_value(
            "Shipment",
            {"tracking_number": tracking_number},
            "name"
        )

        if shipment:
            doc = frappe.get_doc("Shipment", shipment)
            doc.db_set("status", "Delivered")
            doc.db_set("delivered_at", payload.get("delivered_at", now_datetime()))

            # Notify the sub order
            if doc.sub_order:
                sub_order = frappe.get_doc("Sub Order", doc.sub_order)
                sub_order.handle_delivery_confirmation()

            return {"status": "success", "shipment": shipment}

        return {"status": "not_found", "message": _("Shipment not found")}

    def _process_exception_webhook(self, payload: Dict) -> Dict:
        """Process delivery exception webhook."""
        tracking_number = payload.get("tracking_number", payload.get("barcode"))
        exception_type = payload.get("exception_type", "Unknown")
        exception_message = payload.get("message", payload.get("description", ""))

        if not tracking_number:
            return {"status": "error", "message": _("Missing tracking number")}

        shipment = frappe.db.get_value(
            "Shipment",
            {"tracking_number": tracking_number},
            "name"
        )

        if shipment:
            doc = frappe.get_doc("Shipment", shipment)
            doc.db_set("status", "Exception")
            doc.add_comment(
                "Comment",
                f"Delivery Exception: {exception_type} - {exception_message}"
            )
            return {"status": "success", "shipment": shipment}

        return {"status": "not_found", "message": _("Shipment not found")}


# =============================================================================
# WHITELISTED API FUNCTIONS
# =============================================================================


@frappe.whitelist()
def get_carrier_list(
    tenant=None,
    include_disabled=False,
    carrier_type=None,
    country=None,
):
    """
    Get list of carriers.

    Args:
        tenant: Optional tenant filter (None = global carriers only)
        include_disabled: Include disabled carriers
        carrier_type: Filter by carrier type
        country: Filter by country where carrier operates

    Returns:
        list: List of carrier documents
    """
    filters = {}

    if not include_disabled:
        filters["enabled"] = 1

    if carrier_type:
        filters["carrier_type"] = carrier_type

    fields = [
        "name",
        "carrier_name",
        "carrier_code",
        "carrier_type",
        "logo",
        "supports_tracking",
        "supports_cod",
        "supports_insurance",
        "default_transit_days",
        "display_order",
        "shipment_count",
        "is_default",
        "service_countries",
        "excluded_countries",
    ]

    if tenant:
        # Include tenant-specific and global carriers
        carriers = frappe.get_all(
            "Carrier",
            or_filters=[["tenant", "=", tenant], ["is_global", "=", 1]],
            filters=filters,
            fields=fields,
            order_by="display_order asc, carrier_name asc",
        )
    else:
        # Only global carriers
        filters["is_global"] = 1
        carriers = frappe.get_all(
            "Carrier",
            filters=filters,
            fields=fields,
            order_by="display_order asc, carrier_name asc",
        )

    # Filter by country if specified
    if country:
        country = country.upper()
        filtered_carriers = []
        for carrier in carriers:
            # Parse excluded countries
            excluded = []
            if carrier.excluded_countries:
                excluded = [
                    c.strip().upper()
                    for c in carrier.excluded_countries.split("\n")
                    if c.strip()
                ]

            if country in excluded:
                continue

            # If service countries specified, check if country is in list
            if carrier.service_countries:
                service_list = [
                    c.strip().upper()
                    for c in carrier.service_countries.split("\n")
                    if c.strip()
                ]
                if country not in service_list:
                    continue

            filtered_carriers.append(carrier)
        carriers = filtered_carriers

    return carriers


@frappe.whitelist()
def get_carrier(carrier_code):
    """
    Get carrier by code.

    Args:
        carrier_code: The unique code of the carrier

    Returns:
        dict: Carrier data
    """
    if not frappe.db.exists("Carrier", carrier_code):
        frappe.throw(_("Carrier {0} not found").format(carrier_code))

    carrier = frappe.get_doc("Carrier", carrier_code)

    return {
        "name": carrier.name,
        "carrier_name": carrier.carrier_name,
        "carrier_code": carrier.carrier_code,
        "carrier_type": carrier.carrier_type,
        "service_methods": carrier.get_service_methods_list(),
        "supports_tracking": carrier.supports_tracking,
        "supports_cod": carrier.supports_cod,
        "supports_insurance": carrier.supports_insurance,
        "logo": carrier.logo,
        "description": carrier.description,
        "website": carrier.website,
        "tracking_url_template": carrier.tracking_url_template,
        "default_transit_days": carrier.default_transit_days,
        "min_weight": carrier.min_weight,
        "max_weight": carrier.max_weight,
        "weight_uom": carrier.weight_uom,
        "dimensional_divisor": carrier.dimensional_divisor,
        "base_rate": carrier.base_rate,
        "rate_per_kg": carrier.rate_per_kg,
        "currency": carrier.currency,
        "fuel_surcharge_percent": carrier.fuel_surcharge_percent,
        "is_default": carrier.is_default,
    }


@frappe.whitelist()
def get_tracking_url(carrier_code, tracking_number):
    """
    Get tracking URL for a shipment.

    Args:
        carrier_code: The carrier code
        tracking_number: The tracking number

    Returns:
        str: The tracking URL or None
    """
    if not frappe.db.exists("Carrier", carrier_code):
        frappe.throw(_("Carrier {0} not found").format(carrier_code))

    carrier = frappe.get_doc("Carrier", carrier_code)
    return carrier.get_tracking_url(tracking_number)


@frappe.whitelist()
def calculate_shipping_rate(
    carrier_code, actual_weight, length=0, width=0, height=0
):
    """
    Calculate shipping rate for a carrier.

    Args:
        carrier_code: The carrier code
        actual_weight: Actual package weight
        length: Package length (optional)
        width: Package width (optional)
        height: Package height (optional)

    Returns:
        dict: Rate calculation details
    """
    if not frappe.db.exists("Carrier", carrier_code):
        frappe.throw(_("Carrier {0} not found").format(carrier_code))

    carrier = frappe.get_doc("Carrier", carrier_code)
    return carrier.calculate_shipping_rate(
        float(actual_weight or 0),
        float(length or 0),
        float(width or 0),
        float(height or 0),
    )


@frappe.whitelist()
def check_country_service(carrier_code, country_code):
    """
    Check if carrier serves a specific country.

    Args:
        carrier_code: The carrier code
        country_code: ISO country code

    Returns:
        bool: True if carrier serves the country
    """
    if not frappe.db.exists("Carrier", carrier_code):
        frappe.throw(_("Carrier {0} not found").format(carrier_code))

    carrier = frappe.get_doc("Carrier", carrier_code)
    return carrier.serves_country(country_code)


@frappe.whitelist()
def get_default_carrier(tenant=None):
    """
    Get the default carrier for a tenant.

    Args:
        tenant: Optional tenant filter

    Returns:
        dict: Default carrier data or None
    """
    filters = {"is_default": 1, "enabled": 1}

    if tenant:
        # Check tenant-specific first
        filters["tenant"] = tenant
        carrier = frappe.db.get_value(
            "Carrier",
            filters,
            ["name", "carrier_name", "carrier_code", "carrier_type"],
            as_dict=True,
        )
        if carrier:
            return carrier

        # Fall back to global default
        del filters["tenant"]
        filters["is_global"] = 1
    else:
        filters["is_global"] = 1

    return frappe.db.get_value(
        "Carrier",
        filters,
        ["name", "carrier_name", "carrier_code", "carrier_type"],
        as_dict=True,
    )


@frappe.whitelist()
def update_shipment_counts():
    """
    Update shipment counts for all carriers.
    Intended to be called via scheduler or manually.

    Returns:
        dict: Number of carriers updated
    """
    carriers = frappe.get_all("Carrier", fields=["name"])
    updated = 0

    for carrier_data in carriers:
        carrier = frappe.get_doc("Carrier", carrier_data.name)
        old_count = carrier.shipment_count or 0
        carrier.update_shipment_count()
        if carrier.shipment_count != old_count:
            updated += 1

    frappe.db.commit()

    return {"updated_count": updated, "total_carriers": len(carriers)}


@frappe.whitelist()
def create_standard_carriers():
    """
    Create standard shipping carriers commonly used in B2B trade.

    This creates predefined carriers for:
    - DHL Express
    - FedEx
    - UPS
    - TNT
    - USPS
    - PostNL
    - DB Schenker
    - Maersk

    Returns:
        dict: Summary of created carriers
    """
    # Check permission
    if not frappe.has_permission("Carrier", "create"):
        frappe.throw(_("Insufficient permissions to create carriers"))

    standard_carriers = [
        {
            "carrier_name": "DHL Express",
            "carrier_code": "DHL",
            "carrier_type": "Express",
            "service_methods": "Express Worldwide\nExpress 9:00\nExpress 12:00\nEconomy Select\nGlobal Forwarding",
            "supports_tracking": 1,
            "supports_cod": 1,
            "supports_insurance": 1,
            "default_transit_days": 3,
            "dimensional_divisor": 5000,
            "tracking_url_template": "https://www.dhl.com/en/express/tracking.html?AWB={tracking_number}",
            "website": "https://www.dhl.com",
            "is_global": 1,
            "display_order": 1,
        },
        {
            "carrier_name": "FedEx",
            "carrier_code": "FEDEX",
            "carrier_type": "Express",
            "service_methods": "International Priority\nInternational Economy\nFedEx Ground\nFedEx Freight\nFedEx Express Saver",
            "supports_tracking": 1,
            "supports_cod": 1,
            "supports_insurance": 1,
            "default_transit_days": 3,
            "dimensional_divisor": 5000,
            "tracking_url_template": "https://www.fedex.com/fedextrack/?trknbr={tracking_number}",
            "website": "https://www.fedex.com",
            "is_global": 1,
            "display_order": 2,
        },
        {
            "carrier_name": "UPS",
            "carrier_code": "UPS",
            "carrier_type": "Express",
            "service_methods": "UPS Express\nUPS Expedited\nUPS Standard\nUPS Ground\nUPS Freight",
            "supports_tracking": 1,
            "supports_cod": 1,
            "supports_insurance": 1,
            "default_transit_days": 4,
            "dimensional_divisor": 5000,
            "tracking_url_template": "https://www.ups.com/track?tracknum={tracking_number}",
            "website": "https://www.ups.com",
            "is_global": 1,
            "display_order": 3,
        },
        {
            "carrier_name": "TNT",
            "carrier_code": "TNT",
            "carrier_type": "Express",
            "service_methods": "Express\nEconomy Express\nGlobal Express",
            "supports_tracking": 1,
            "supports_cod": 0,
            "supports_insurance": 1,
            "default_transit_days": 4,
            "dimensional_divisor": 5000,
            "tracking_url_template": "https://www.tnt.com/express/en_gc/site/tracking.html?searchType=con&cons={tracking_number}",
            "website": "https://www.tnt.com",
            "is_global": 1,
            "display_order": 4,
        },
        {
            "carrier_name": "USPS",
            "carrier_code": "USPS",
            "carrier_type": "Postal",
            "service_methods": "Priority Mail International\nPriority Mail Express International\nFirst-Class Mail International\nGlobal Express Guaranteed",
            "supports_tracking": 1,
            "supports_cod": 0,
            "supports_insurance": 1,
            "default_transit_days": 7,
            "dimensional_divisor": 5000,
            "tracking_url_template": "https://tools.usps.com/go/TrackConfirmAction?tLabels={tracking_number}",
            "website": "https://www.usps.com",
            "domestic_only": 0,
            "service_countries": "US",
            "is_global": 1,
            "display_order": 5,
        },
        {
            "carrier_name": "PostNL",
            "carrier_code": "POSTNL",
            "carrier_type": "Postal",
            "service_methods": "Standard Parcel\nMailbox Parcel\nExpress Parcel\nInternational",
            "supports_tracking": 1,
            "supports_cod": 0,
            "supports_insurance": 1,
            "default_transit_days": 5,
            "dimensional_divisor": 5000,
            "tracking_url_template": "https://postnl.nl/tracktrace/?B={tracking_number}",
            "website": "https://www.postnl.nl",
            "service_regions": "Europe",
            "is_global": 1,
            "display_order": 6,
        },
        {
            "carrier_name": "DB Schenker",
            "carrier_code": "SCHENKER",
            "carrier_type": "Freight",
            "service_methods": "Land Transport\nAir Freight\nOcean Freight\nContract Logistics",
            "supports_tracking": 1,
            "supports_cod": 0,
            "supports_insurance": 1,
            "default_transit_days": 10,
            "dimensional_divisor": 6000,
            "tracking_url_template": "https://eschenker.dbschenker.com/app/tracking-public/?refNumber={tracking_number}",
            "website": "https://www.dbschenker.com",
            "is_global": 1,
            "display_order": 7,
        },
        {
            "carrier_name": "Maersk",
            "carrier_code": "MAERSK",
            "carrier_type": "Freight",
            "service_methods": "Ocean Freight FCL\nOcean Freight LCL\nAir Freight\nCustoms Services",
            "supports_tracking": 1,
            "supports_cod": 0,
            "supports_insurance": 1,
            "default_transit_days": 30,
            "dimensional_divisor": 6000,
            "tracking_url_template": "https://www.maersk.com/tracking/{tracking_number}",
            "website": "https://www.maersk.com",
            "is_global": 1,
            "display_order": 8,
        },
    ]

    created = []
    skipped = []

    for carrier_data in standard_carriers:
        if frappe.db.exists("Carrier", carrier_data["carrier_code"]):
            skipped.append(carrier_data["carrier_code"])
            continue

        carrier = frappe.new_doc("Carrier")
        for field, value in carrier_data.items():
            setattr(carrier, field, value)

        carrier.insert(ignore_permissions=True)
        created.append(carrier.carrier_code)

    frappe.db.commit()

    return {
        "created": created,
        "skipped": skipped,
        "message": _("Created {0} carriers, {1} already existed").format(
            len(created), len(skipped)
        ),
    }


@frappe.whitelist()
def get_carrier_types():
    """
    Get list of available carrier types.

    Returns:
        list: List of carrier type options
    """
    return [
        {"value": "Courier", "label": _("Courier")},
        {"value": "Freight", "label": _("Freight")},
        {"value": "Postal", "label": _("Postal")},
        {"value": "Express", "label": _("Express")},
        {"value": "Specialized", "label": _("Specialized")},
        {"value": "Local Delivery", "label": _("Local Delivery")},
        {"value": "Other", "label": _("Other")},
    ]


@frappe.whitelist()
def create_turkish_carriers():
    """
    Create standard Turkish shipping carriers.

    This creates predefined carriers for major Turkish cargo companies:
    - Yurtiçi Kargo
    - Aras Kargo
    - MNG Kargo
    - PTT Kargo
    - Sürat Kargo

    Returns:
        dict: Summary of created carriers
    """
    # Check permission
    if not frappe.has_permission("Carrier", "create"):
        frappe.throw(_("Insufficient permissions to create carriers"))

    turkish_carriers = [
        {
            "carrier_name": "Yurtiçi Kargo",
            "carrier_code": "YURTICI",
            "carrier_type": "Express",
            "service_methods": "Standart Kargo\nHızlı Kargo\nAynı Gün Teslimat\nKapıda Ödeme\nDepo Teslimat",
            "supports_tracking": 1,
            "supports_cod": 1,
            "supports_insurance": 1,
            "default_transit_days": 2,
            "dimensional_divisor": 3000,
            "tracking_url_template": "https://www.yurticikargo.com/tr/online-servisler/gonderi-sorgula?code={tracking_number}",
            "website": "https://www.yurticikargo.com",
            "country": "Turkey",
            "domestic_only": 1,
            "service_countries": "TR",
            "is_global": 1,
            "has_api_integration": 1,
            "api_provider": "Yurtici",
            "api_environment": "Production",
            "supports_rate_api": 1,
            "supports_label_api": 1,
            "tracking_api_enabled": 1,
            "tracking_update_frequency": 30,
            "currency": "TRY",
            "display_order": 10,
            "description": "Türkiye'nin önde gelen kargo şirketi. Geniş şube ağı ve hızlı teslimat seçenekleri sunmaktadır."
        },
        {
            "carrier_name": "Aras Kargo",
            "carrier_code": "ARAS",
            "carrier_type": "Express",
            "service_methods": "Standart Kargo\nEkspres Kargo\nMikro Kargo\nKapıda Ödeme\nPalet Taşıma",
            "supports_tracking": 1,
            "supports_cod": 1,
            "supports_insurance": 1,
            "default_transit_days": 2,
            "dimensional_divisor": 3000,
            "tracking_url_template": "https://www.araskargo.com.tr/trmWeb/gonderisorgula.aspx?q={tracking_number}",
            "website": "https://www.araskargo.com.tr",
            "country": "Turkey",
            "domestic_only": 1,
            "service_countries": "TR",
            "is_global": 1,
            "has_api_integration": 1,
            "api_provider": "Aras",
            "api_environment": "Production",
            "supports_rate_api": 1,
            "supports_label_api": 1,
            "tracking_api_enabled": 1,
            "tracking_update_frequency": 30,
            "currency": "TRY",
            "display_order": 11,
            "description": "Türkiye genelinde yaygın şube ağı ile hizmet veren kargo firması. Mikro kargo ve palet taşıma seçenekleri mevcuttur."
        },
        {
            "carrier_name": "MNG Kargo",
            "carrier_code": "MNG",
            "carrier_type": "Express",
            "service_methods": "Standart Kargo\nEkspres Kargo\nAynı Gün\nSözleşmeli Kargo\nKurumsal Çözümler",
            "supports_tracking": 1,
            "supports_cod": 1,
            "supports_insurance": 1,
            "default_transit_days": 2,
            "dimensional_divisor": 3000,
            "tracking_url_template": "https://www.mngkargo.com.tr/gonderi-takip?barcode={tracking_number}",
            "website": "https://www.mngkargo.com.tr",
            "country": "Turkey",
            "domestic_only": 1,
            "service_countries": "TR",
            "is_global": 1,
            "has_api_integration": 1,
            "api_provider": "MNG",
            "api_environment": "Production",
            "supports_rate_api": 1,
            "supports_label_api": 1,
            "tracking_api_enabled": 1,
            "tracking_update_frequency": 30,
            "currency": "TRY",
            "display_order": 12,
            "description": "Türkiye'nin köklü kargo firmalarından biri. Kurumsal çözümler ve sözleşmeli kargo hizmetleri sunmaktadır."
        },
        {
            "carrier_name": "PTT Kargo",
            "carrier_code": "PTT",
            "carrier_type": "Postal",
            "service_methods": "Standart Kargo\nAPS Kurye\nTaahhütlü Gönderi\nKapıda Ödeme\nYurtdışı Kargo",
            "supports_tracking": 1,
            "supports_cod": 1,
            "supports_insurance": 1,
            "default_transit_days": 3,
            "dimensional_divisor": 3000,
            "tracking_url_template": "https://gonderitakip.ptt.gov.tr/?barkod={tracking_number}",
            "website": "https://www.ptt.gov.tr",
            "country": "Turkey",
            "domestic_only": 0,
            "service_countries": "TR",
            "is_global": 1,
            "has_api_integration": 1,
            "api_provider": "PTT",
            "api_environment": "Production",
            "supports_rate_api": 1,
            "supports_label_api": 1,
            "tracking_api_enabled": 1,
            "tracking_update_frequency": 60,
            "currency": "TRY",
            "display_order": 13,
            "description": "Türkiye'nin resmi posta ve kargo hizmeti. En geniş şube ağına sahiptir ve yurtdışı gönderim hizmeti de sunmaktadır."
        },
        {
            "carrier_name": "Sürat Kargo",
            "carrier_code": "SURAT",
            "carrier_type": "Express",
            "service_methods": "Standart Kargo\nHızlı Kargo\nKapıda Ödeme\nDepo Teslimat\nKurumsal Kargo",
            "supports_tracking": 1,
            "supports_cod": 1,
            "supports_insurance": 1,
            "default_transit_days": 2,
            "dimensional_divisor": 3000,
            "tracking_url_template": "https://www.suratkargo.com.tr/gonderi-takip?barkod={tracking_number}",
            "website": "https://www.suratkargo.com.tr",
            "country": "Turkey",
            "domestic_only": 1,
            "service_countries": "TR",
            "is_global": 1,
            "has_api_integration": 1,
            "api_provider": "Surat",
            "api_environment": "Production",
            "supports_rate_api": 1,
            "supports_label_api": 1,
            "tracking_api_enabled": 1,
            "tracking_update_frequency": 30,
            "currency": "TRY",
            "display_order": 14,
            "description": "Hızlı ve güvenilir kargo hizmeti sunan Türk kargo şirketi. Kurumsal müşterilere özel çözümler sunmaktadır."
        },
    ]

    created = []
    skipped = []

    for carrier_data in turkish_carriers:
        if frappe.db.exists("Carrier", carrier_data["carrier_code"]):
            skipped.append(carrier_data["carrier_code"])
            continue

        carrier = frappe.new_doc("Carrier")
        for field, value in carrier_data.items():
            setattr(carrier, field, value)

        carrier.insert(ignore_permissions=True)
        created.append(carrier.carrier_code)

    frappe.db.commit()

    return {
        "created": created,
        "skipped": skipped,
        "message": _("Created {0} Turkish carriers, {1} already existed").format(
            len(created), len(skipped)
        ),
    }


@frappe.whitelist()
def test_carrier_api(carrier_code: str) -> Dict:
    """
    Test API connection for a carrier.

    Args:
        carrier_code: The carrier code

    Returns:
        dict: Connection test result
    """
    if not frappe.db.exists("Carrier", carrier_code):
        frappe.throw(_("Carrier {0} not found").format(carrier_code))

    carrier = frappe.get_doc("Carrier", carrier_code)
    return carrier.test_api_connection()


@frappe.whitelist()
def get_carrier_rates(
    carrier_code: str,
    origin_address: str,
    destination_address: str,
    package: str
) -> Dict:
    """
    Get shipping rates from carrier.

    Args:
        carrier_code: The carrier code
        origin_address: Origin address JSON string
        destination_address: Destination address JSON string
        package: Package details JSON string

    Returns:
        dict: Rate calculation result
    """
    if not frappe.db.exists("Carrier", carrier_code):
        frappe.throw(_("Carrier {0} not found").format(carrier_code))

    carrier = frappe.get_doc("Carrier", carrier_code)

    # Parse JSON strings
    origin = json.loads(origin_address) if isinstance(origin_address, str) else origin_address
    destination = json.loads(destination_address) if isinstance(destination_address, str) else destination_address
    pkg = json.loads(package) if isinstance(package, str) else package

    return carrier.get_rates_from_api(origin, destination, pkg)


@frappe.whitelist()
def create_shipping_label(
    carrier_code: str,
    shipment_data: str
) -> Dict:
    """
    Create shipping label via carrier API.

    Args:
        carrier_code: The carrier code
        shipment_data: Shipment details JSON string

    Returns:
        dict: Label creation result
    """
    if not frappe.db.exists("Carrier", carrier_code):
        frappe.throw(_("Carrier {0} not found").format(carrier_code))

    carrier = frappe.get_doc("Carrier", carrier_code)
    data = json.loads(shipment_data) if isinstance(shipment_data, str) else shipment_data

    return carrier.create_shipment_label(data)


@frappe.whitelist()
def get_tracking_info(carrier_code: str, tracking_number: str) -> Dict:
    """
    Get tracking information from carrier.

    Args:
        carrier_code: The carrier code
        tracking_number: The tracking number

    Returns:
        dict: Tracking information
    """
    if not frappe.db.exists("Carrier", carrier_code):
        frappe.throw(_("Carrier {0} not found").format(carrier_code))

    carrier = frappe.get_doc("Carrier", carrier_code)
    return carrier.get_tracking_from_api(tracking_number)


@frappe.whitelist(allow_guest=True)
def handle_carrier_webhook(carrier_code: str):
    """
    Handle incoming webhook from carrier.

    This endpoint receives webhook notifications from carriers
    for tracking updates, delivery confirmations, and exceptions.

    Args:
        carrier_code: The carrier code

    Returns:
        dict: Webhook processing result
    """
    if not frappe.db.exists("Carrier", carrier_code):
        frappe.throw(_("Carrier {0} not found").format(carrier_code))

    carrier = frappe.get_doc("Carrier", carrier_code)

    if not carrier.webhook_enabled:
        return {"status": "error", "message": _("Webhooks not enabled for this carrier")}

    # Get webhook payload
    try:
        payload = json.loads(frappe.request.data)
    except Exception:
        payload = frappe.form_dict

    # Verify webhook signature if secret is configured
    if carrier.webhook_secret:
        received_signature = frappe.get_request_header("X-Webhook-Signature")
        if not _verify_webhook_signature(carrier, payload, received_signature):
            frappe.log_error(
                f"Invalid webhook signature for carrier {carrier_code}",
                "Carrier Webhook Security"
            )
            return {"status": "error", "message": _("Invalid signature")}

    # Determine event type
    event_type = payload.get("event_type", payload.get("event", "tracking_update"))

    # Process the webhook
    result = carrier.process_webhook_event(event_type, payload)

    frappe.db.commit()
    return result


def _verify_webhook_signature(carrier, payload: Dict, received_signature: str) -> bool:
    """
    Verify webhook signature using HMAC.

    Args:
        carrier: Carrier document
        payload: Webhook payload
        received_signature: Received signature from header

    Returns:
        bool: True if signature is valid
    """
    import hmac
    import hashlib

    if not received_signature:
        return False

    secret = carrier.get_password("webhook_secret")
    if not secret:
        return True  # No secret configured, skip verification

    payload_str = json.dumps(payload, separators=(',', ':'), sort_keys=True)
    expected_signature = hmac.new(
        secret.encode(),
        payload_str.encode(),
        hashlib.sha256
    ).hexdigest()

    return hmac.compare_digest(expected_signature, received_signature)


@frappe.whitelist()
def get_all_carriers_for_checkout(
    country: str = None,
    weight: float = 0,
    tenant: str = None
) -> List[Dict]:
    """
    Get all available carriers for checkout display.

    Args:
        country: Destination country code
        weight: Package weight
        tenant: Optional tenant filter

    Returns:
        list: List of carrier options with rates
    """
    carriers = get_carrier_list(
        tenant=tenant,
        include_disabled=False,
        country=country
    )

    result = []
    for carrier_data in carriers:
        if not carrier_data.get("show_in_checkout", True):
            continue

        # Check weight limits
        if weight:
            min_weight = carrier_data.get("min_weight", 0)
            max_weight = carrier_data.get("max_weight", 0)

            if min_weight and weight < min_weight:
                continue
            if max_weight and weight > max_weight:
                continue

        result.append({
            "name": carrier_data.get("name"),
            "carrier_name": carrier_data.get("carrier_name"),
            "carrier_code": carrier_data.get("carrier_code"),
            "carrier_type": carrier_data.get("carrier_type"),
            "logo": carrier_data.get("logo"),
            "transit_days": carrier_data.get("default_transit_days"),
            "supports_tracking": carrier_data.get("supports_tracking"),
            "supports_cod": carrier_data.get("supports_cod"),
            "supports_insurance": carrier_data.get("supports_insurance"),
            "is_default": carrier_data.get("is_default"),
            "featured": carrier_data.get("featured", False)
        })

    return sorted(result, key=lambda x: (not x.get("featured"), not x.get("is_default"), x.get("carrier_name")))

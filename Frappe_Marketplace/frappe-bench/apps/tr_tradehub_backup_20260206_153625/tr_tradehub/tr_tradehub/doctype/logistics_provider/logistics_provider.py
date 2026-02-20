# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime


class LogisticsProvider(Document):
    """
    Logistics Provider DocType for managing shipping carriers and couriers.

    Provides master data for logistics providers including:
    - API configuration for automated shipping integration
    - Tracking URL templates for shipment tracking
    - Service area definitions (domestic/international)
    - Shipping method capabilities
    - Rate configuration
    - Performance metrics
    """

    def validate(self):
        """Validate provider data before save."""
        self.validate_provider_code()
        self.validate_api_configuration()
        self.validate_tracking_configuration()
        self.validate_packaging_limits()
        self.validate_default_provider()

    def validate_provider_code(self):
        """Ensure provider code is uppercase and alphanumeric."""
        if self.provider_code:
            # Convert to uppercase and remove spaces
            self.provider_code = self.provider_code.upper().replace(" ", "_")

            # Validate format (alphanumeric and underscores only)
            import re
            if not re.match(r'^[A-Z0-9_]+$', self.provider_code):
                frappe.throw(
                    _("Provider Code must contain only letters, numbers, and underscores"),
                    title=_("Invalid Provider Code")
                )

    def validate_api_configuration(self):
        """Validate API configuration when API is enabled."""
        if self.api_enabled:
            if not self.api_endpoint:
                frappe.throw(
                    _("API Endpoint is required when API is enabled"),
                    title=_("Missing API Configuration")
                )

            # Validate URL format
            if self.api_endpoint and not self.api_endpoint.startswith(('http://', 'https://')):
                frappe.throw(
                    _("API Endpoint must be a valid URL starting with http:// or https://"),
                    title=_("Invalid API Endpoint")
                )

            # Validate sandbox endpoint if sandbox mode is enabled
            if self.sandbox_mode and self.sandbox_endpoint:
                if not self.sandbox_endpoint.startswith(('http://', 'https://')):
                    frappe.throw(
                        _("Sandbox Endpoint must be a valid URL starting with http:// or https://"),
                        title=_("Invalid Sandbox Endpoint")
                    )

    def validate_tracking_configuration(self):
        """Validate tracking URL template."""
        if self.supports_tracking and self.tracking_url_template:
            # Check for placeholder
            if '{tracking_number}' not in self.tracking_url_template:
                frappe.msgprint(
                    _("Tracking URL template should contain {tracking_number} placeholder"),
                    indicator='orange',
                    title=_("Tracking URL Warning")
                )

            # Validate URL format
            if not self.tracking_url_template.startswith(('http://', 'https://')):
                frappe.throw(
                    _("Tracking URL template must start with http:// or https://"),
                    title=_("Invalid Tracking URL")
                )

    def validate_packaging_limits(self):
        """Validate packaging dimension limits."""
        # Ensure positive values
        for field in ['max_weight_kg', 'max_length_cm', 'max_width_cm', 'max_height_cm']:
            value = getattr(self, field, 0) or 0
            if value < 0:
                frappe.throw(
                    _("{0} cannot be negative").format(_(field.replace('_', ' ').title())),
                    title=_("Invalid Packaging Limit")
                )

        # Calculate max volume if not set
        if not self.max_volume_cm3 and all([self.max_length_cm, self.max_width_cm, self.max_height_cm]):
            self.max_volume_cm3 = self.max_length_cm * self.max_width_cm * self.max_height_cm

    def validate_default_provider(self):
        """Ensure only one default provider exists."""
        if self.is_default:
            # Check for existing default provider
            existing_default = frappe.db.get_value(
                "Logistics Provider",
                {
                    "is_default": 1,
                    "name": ("!=", self.name),
                    "status": "Active"
                },
                "name"
            )

            if existing_default:
                # Unset the other default
                frappe.db.set_value("Logistics Provider", existing_default, "is_default", 0)
                frappe.msgprint(
                    _("Removed default status from {0}").format(existing_default),
                    indicator='blue',
                    title=_("Default Provider Changed")
                )

    def get_tracking_url(self, tracking_number):
        """
        Generate tracking URL for a shipment.

        Args:
            tracking_number: The tracking number to look up

        Returns:
            str: Complete tracking URL or None if tracking not supported
        """
        if not self.supports_tracking or not self.tracking_url_template:
            return None

        return self.tracking_url_template.replace('{tracking_number}', str(tracking_number))

    def get_api_endpoint(self):
        """
        Get the appropriate API endpoint based on sandbox mode.

        Returns:
            str: API endpoint URL
        """
        if self.sandbox_mode and self.sandbox_endpoint:
            return self.sandbox_endpoint
        return self.api_endpoint

    def get_api_credentials(self):
        """
        Get API credentials as a dictionary.

        Returns:
            dict: API credentials (key, secret, username, password)
        """
        return {
            'api_key': self.get_password('api_key') if self.api_key else None,
            'api_secret': self.get_password('api_secret') if self.api_secret else None,
            'api_username': self.api_username,
            'api_password': self.get_password('api_password') if self.api_password else None
        }

    def can_ship_to(self, country_code):
        """
        Check if this provider can ship to a given country.

        Args:
            country_code: Two-letter country code (e.g., 'TR', 'US')

        Returns:
            bool: True if provider serves this country
        """
        # Domestic only check
        if self.service_type == "Domestic Only":
            # Assuming Turkey as default domestic country
            return country_code == "TR"

        # Check served countries
        if self.served_countries:
            served_list = [c.strip().upper() for c in self.served_countries.split(',')]
            return country_code.upper() in served_list

        # If international coverage and no specific list, assume global
        if self.international_coverage:
            return True

        return False

    def is_within_limits(self, weight_kg=0, length_cm=0, width_cm=0, height_cm=0, declared_value=0):
        """
        Check if a package is within provider's limits.

        Args:
            weight_kg: Package weight in kilograms
            length_cm: Package length in centimeters
            width_cm: Package width in centimeters
            height_cm: Package height in centimeters
            declared_value: Declared value of contents

        Returns:
            tuple: (is_valid, error_message)
        """
        errors = []

        if self.max_weight_kg and weight_kg > self.max_weight_kg:
            errors.append(_("Weight exceeds maximum of {0} KG").format(self.max_weight_kg))

        if self.max_length_cm and length_cm > self.max_length_cm:
            errors.append(_("Length exceeds maximum of {0} CM").format(self.max_length_cm))

        if self.max_width_cm and width_cm > self.max_width_cm:
            errors.append(_("Width exceeds maximum of {0} CM").format(self.max_width_cm))

        if self.max_height_cm and height_cm > self.max_height_cm:
            errors.append(_("Height exceeds maximum of {0} CM").format(self.max_height_cm))

        if self.max_volume_cm3:
            volume = length_cm * width_cm * height_cm
            if volume > self.max_volume_cm3:
                errors.append(_("Volume exceeds maximum of {0} CM3").format(self.max_volume_cm3))

        if self.max_declared_value and declared_value > self.max_declared_value:
            errors.append(_("Declared value exceeds maximum of {0}").format(self.max_declared_value))

        if errors:
            return False, ", ".join(errors)

        return True, None

    def calculate_volumetric_weight(self, length_cm, width_cm, height_cm):
        """
        Calculate volumetric weight for a package.

        Args:
            length_cm: Package length in centimeters
            width_cm: Package width in centimeters
            height_cm: Package height in centimeters

        Returns:
            float: Volumetric weight in kilograms
        """
        divisor = self.volumetric_divisor or 5000
        return (length_cm * width_cm * height_cm) / divisor

    def get_chargeable_weight(self, actual_weight_kg, length_cm, width_cm, height_cm):
        """
        Get the chargeable weight (higher of actual vs volumetric).

        Args:
            actual_weight_kg: Actual package weight
            length_cm: Package length
            width_cm: Package width
            height_cm: Package height

        Returns:
            float: Chargeable weight in kilograms
        """
        volumetric_weight = self.calculate_volumetric_weight(length_cm, width_cm, height_cm)

        if self.rate_calculation_method == "Weight Based":
            chargeable = actual_weight_kg
        elif self.rate_calculation_method == "Volumetric":
            chargeable = volumetric_weight
        elif self.rate_calculation_method == "Higher of Weight/Volume":
            chargeable = max(actual_weight_kg, volumetric_weight)
        else:
            chargeable = actual_weight_kg

        # Apply minimum chargeable weight
        min_weight = self.min_chargeable_weight or 0
        return max(chargeable, min_weight)

    def update_performance_metrics(self, shipment_count=0, issue_count=0, delivery_days=0):
        """
        Update provider performance metrics based on shipment data.

        Args:
            shipment_count: Number of new shipments to add
            issue_count: Number of issues to add
            delivery_days: Total delivery days for averaging
        """
        self.total_shipments = (self.total_shipments or 0) + shipment_count
        self.total_issues = (self.total_issues or 0) + issue_count

        if self.total_shipments > 0:
            # Update damage rate (issues / total)
            self.damage_rate = (self.total_issues / self.total_shipments) * 100

            # Update on-time delivery rate
            on_time_count = self.total_shipments - self.total_issues
            self.on_time_delivery_rate = (on_time_count / self.total_shipments) * 100

        # Update average delivery days (simple moving average)
        if delivery_days > 0 and shipment_count > 0:
            avg_new = delivery_days / shipment_count
            # Weight new average with existing
            if self.average_delivery_days:
                self.average_delivery_days = (self.average_delivery_days + avg_new) / 2
            else:
                self.average_delivery_days = avg_new

        self.last_used_at = now_datetime()
        self.save(ignore_permissions=True)


@frappe.whitelist()
def get_logistics_provider(provider_name):
    """
    Get logistics provider details by name or code.

    Args:
        provider_name: Provider name or code

    Returns:
        dict: Provider document data
    """
    # Try to find by name first
    if frappe.db.exists("Logistics Provider", provider_name):
        return frappe.get_doc("Logistics Provider", provider_name).as_dict()

    # Try to find by code
    provider = frappe.db.get_value(
        "Logistics Provider",
        {"provider_code": provider_name.upper()},
        "name"
    )

    if provider:
        return frappe.get_doc("Logistics Provider", provider).as_dict()

    frappe.throw(_("Logistics Provider not found: {0}").format(provider_name))


@frappe.whitelist()
def get_active_providers(service_type=None, provider_type=None, country=None):
    """
    Get list of active logistics providers.

    Args:
        service_type: Filter by service type (Domestic Only/International Only/Both)
        provider_type: Filter by provider type (Carrier/Courier/etc.)
        country: Filter by country coverage

    Returns:
        list: List of provider details
    """
    filters = {"status": "Active"}

    if service_type:
        filters["service_type"] = ["in", [service_type, "Both"]]

    if provider_type:
        filters["provider_type"] = provider_type

    providers = frappe.get_all(
        "Logistics Provider",
        filters=filters,
        fields=[
            "name", "provider_name", "provider_code", "provider_type",
            "service_type", "logo", "supports_tracking", "supports_cod",
            "supports_express", "average_delivery_days", "priority"
        ],
        order_by="priority asc"
    )

    # Filter by country if specified
    if country:
        filtered = []
        for p in providers:
            doc = frappe.get_doc("Logistics Provider", p.name)
            if doc.can_ship_to(country):
                filtered.append(p)
        providers = filtered

    return providers


@frappe.whitelist()
def get_default_provider():
    """
    Get the default logistics provider.

    Returns:
        dict: Default provider details or None
    """
    provider = frappe.db.get_value(
        "Logistics Provider",
        {"is_default": 1, "status": "Active"},
        "name"
    )

    if provider:
        return frappe.get_doc("Logistics Provider", provider).as_dict()

    # Fall back to highest priority active provider
    provider = frappe.db.get_value(
        "Logistics Provider",
        {"status": "Active"},
        "name",
        order_by="priority asc"
    )

    if provider:
        return frappe.get_doc("Logistics Provider", provider).as_dict()

    return None


@frappe.whitelist()
def get_tracking_url(provider_name, tracking_number):
    """
    Get tracking URL for a shipment.

    Args:
        provider_name: Logistics provider name or code
        tracking_number: Shipment tracking number

    Returns:
        str: Tracking URL or None
    """
    provider_data = get_logistics_provider(provider_name)
    doc = frappe.get_doc("Logistics Provider", provider_data.get("name"))
    return doc.get_tracking_url(tracking_number)


@frappe.whitelist()
def check_shipping_limits(provider_name, weight_kg=0, length_cm=0, width_cm=0, height_cm=0, declared_value=0):
    """
    Check if a package is within provider's shipping limits.

    Args:
        provider_name: Logistics provider name or code
        weight_kg: Package weight in kilograms
        length_cm: Package length in centimeters
        width_cm: Package width in centimeters
        height_cm: Package height in centimeters
        declared_value: Declared value of contents

    Returns:
        dict: {is_valid: bool, error: str or None, chargeable_weight: float}
    """
    provider_data = get_logistics_provider(provider_name)
    doc = frappe.get_doc("Logistics Provider", provider_data.get("name"))

    is_valid, error = doc.is_within_limits(
        weight_kg=float(weight_kg or 0),
        length_cm=float(length_cm or 0),
        width_cm=float(width_cm or 0),
        height_cm=float(height_cm or 0),
        declared_value=float(declared_value or 0)
    )

    chargeable_weight = doc.get_chargeable_weight(
        float(weight_kg or 0),
        float(length_cm or 0),
        float(width_cm or 0),
        float(height_cm or 0)
    )

    return {
        "is_valid": is_valid,
        "error": error,
        "chargeable_weight": chargeable_weight,
        "volumetric_weight": doc.calculate_volumetric_weight(
            float(length_cm or 0),
            float(width_cm or 0),
            float(height_cm or 0)
        )
    }


@frappe.whitelist()
def get_providers_for_shipping(
    destination_country,
    weight_kg=0,
    length_cm=0,
    width_cm=0,
    height_cm=0,
    declared_value=0,
    require_cod=False,
    require_tracking=False,
    require_insurance=False
):
    """
    Get providers that can handle a specific shipment.

    Args:
        destination_country: Destination country code
        weight_kg: Package weight
        length_cm: Package length
        width_cm: Package width
        height_cm: Package height
        declared_value: Declared value
        require_cod: Require COD support
        require_tracking: Require tracking support
        require_insurance: Require insurance support

    Returns:
        list: List of eligible providers with shipping info
    """
    providers = get_active_providers(country=destination_country)
    eligible = []

    for p in providers:
        doc = frappe.get_doc("Logistics Provider", p.name)

        # Check requirements
        if require_cod and not doc.supports_cod:
            continue
        if require_tracking and not doc.supports_tracking:
            continue
        if require_insurance and not doc.supports_insurance:
            continue

        # Check limits
        is_valid, error = doc.is_within_limits(
            weight_kg=float(weight_kg or 0),
            length_cm=float(length_cm or 0),
            width_cm=float(width_cm or 0),
            height_cm=float(height_cm or 0),
            declared_value=float(declared_value or 0)
        )

        if not is_valid:
            continue

        # Calculate chargeable weight
        chargeable_weight = doc.get_chargeable_weight(
            float(weight_kg or 0),
            float(length_cm or 0),
            float(width_cm or 0),
            float(height_cm or 0)
        )

        provider_info = {
            "name": p.name,
            "provider_name": p.provider_name,
            "provider_code": p.provider_code,
            "provider_type": p.provider_type,
            "logo": p.logo,
            "supports_tracking": p.supports_tracking,
            "supports_cod": p.supports_cod,
            "supports_express": p.supports_express,
            "average_delivery_days": p.average_delivery_days,
            "chargeable_weight": chargeable_weight,
            "is_default": doc.is_default
        }

        eligible.append(provider_info)

    return eligible

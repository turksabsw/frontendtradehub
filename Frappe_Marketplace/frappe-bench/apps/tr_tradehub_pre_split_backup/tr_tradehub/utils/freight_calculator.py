# Copyright (c) 2026, Trade Hub and contributors
# For license information, please see license.txt

"""
Freight Calculation Utilities for Trade Hub Logistics and Shipping.

This module provides utility functions for calculating freight costs, dimensional
weight, insurance costs, and total shipping costs for B2B shipments. It integrates
with the Carrier and Shipment DocTypes to provide accurate shipping calculations.

Key Features:
- Dimensional weight calculation based on carrier divisors
- Chargeable weight calculation (max of actual vs dimensional)
- Freight cost calculation using carrier base rates and per-kg rates
- Insurance cost calculation
- Total shipping cost aggregation
- Incoterm-aware cost breakdowns
- Zone-based pricing support
- Multi-carrier rate comparison

Usage:
    from tr_tradehub.utils.freight_calculator import (
        calculate_freight,
        calculate_dimensional_weight,
        calculate_total_shipping_cost,
        get_carrier_rates,
        compare_carrier_rates
    )

    # Basic freight calculation
    freight = calculate_freight(
        weight=50,
        carrier="FEDEX",
        origin_country="TR",
        destination_country="DE"
    )

    # Get total shipping cost
    total = calculate_total_shipping_cost(
        freight_cost=freight["freight_cost"],
        insurance_value=10000,
        insurance_rate=0.5
    )
"""

from typing import Any, Dict, List, Optional, Union
from decimal import Decimal, ROUND_HALF_UP

import frappe
from frappe import _
from frappe.utils import flt, cint

# =============================================================================
# CONSTANTS
# =============================================================================

# Standard dimensional weight divisors for different shipping modes
DIMENSIONAL_DIVISORS = {
    "air": 5000,       # cm3 to kg (IATA standard)
    "sea": 1000,       # cbm to metric tons
    "ground": 5000,    # cm3 to kg
    "express": 5000,   # cm3 to kg
    "courier": 5000,   # cm3 to kg
    "freight": 6000,   # cm3 to kg (often used for freight forwarding)
    "rail": 4000,      # cm3 to kg
    "default": 5000,   # fallback
}

# Weight unit conversion factors to kilograms
WEIGHT_CONVERSIONS = {
    "kg": 1.0,
    "kilogram": 1.0,
    "kilograms": 1.0,
    "g": 0.001,
    "gram": 0.001,
    "grams": 0.001,
    "lb": 0.453592,
    "lbs": 0.453592,
    "pound": 0.453592,
    "pounds": 0.453592,
    "oz": 0.0283495,
    "ounce": 0.0283495,
    "ounces": 0.0283495,
    "ton": 1000.0,
    "tons": 1000.0,
    "mt": 1000.0,
    "metric ton": 1000.0,
    "metric tons": 1000.0,
}

# Dimension unit conversion factors to centimeters
DIMENSION_CONVERSIONS = {
    "cm": 1.0,
    "centimeter": 1.0,
    "centimeters": 1.0,
    "m": 100.0,
    "meter": 100.0,
    "meters": 100.0,
    "mm": 0.1,
    "millimeter": 0.1,
    "millimeters": 0.1,
    "in": 2.54,
    "inch": 2.54,
    "inches": 2.54,
    "ft": 30.48,
    "foot": 30.48,
    "feet": 30.48,
}

# Incoterm cost responsibilities
# True = seller pays, False = buyer pays
INCOTERM_RESPONSIBILITIES = {
    "EXW": {
        "freight": False,
        "insurance": False,
        "customs_export": False,
        "customs_import": False,
        "delivery_to_destination": False,
    },
    "FOB": {
        "freight": False,
        "insurance": False,
        "customs_export": True,
        "customs_import": False,
        "delivery_to_destination": False,
    },
    "CIF": {
        "freight": True,
        "insurance": True,
        "customs_export": True,
        "customs_import": False,
        "delivery_to_destination": False,
    },
    "DDP": {
        "freight": True,
        "insurance": True,
        "customs_export": True,
        "customs_import": True,
        "delivery_to_destination": True,
    },
    "DAP": {
        "freight": True,
        "insurance": False,
        "customs_export": True,
        "customs_import": False,
        "delivery_to_destination": True,
    },
    "FCA": {
        "freight": False,
        "insurance": False,
        "customs_export": True,
        "customs_import": False,
        "delivery_to_destination": False,
    },
    "CPT": {
        "freight": True,
        "insurance": False,
        "customs_export": True,
        "customs_import": False,
        "delivery_to_destination": False,
    },
    "CIP": {
        "freight": True,
        "insurance": True,
        "customs_export": True,
        "customs_import": False,
        "delivery_to_destination": False,
    },
    "DAT": {
        "freight": True,
        "insurance": False,
        "customs_export": True,
        "customs_import": False,
        "delivery_to_destination": True,
    },
    "DPU": {
        "freight": True,
        "insurance": False,
        "customs_export": True,
        "customs_import": False,
        "delivery_to_destination": True,
    },
}


# =============================================================================
# UNIT CONVERSION FUNCTIONS
# =============================================================================


def convert_weight_to_kg(
    weight: float,
    from_unit: str = "kg"
) -> float:
    """
    Convert weight from any supported unit to kilograms.

    Args:
        weight: The weight value to convert
        from_unit: The source unit (kg, g, lb, oz, ton, etc.)

    Returns:
        float: Weight in kilograms

    Raises:
        frappe.ValidationError: If the unit is not supported

    Example:
        weight_kg = convert_weight_to_kg(100, "lb")
        # Returns 45.3592
    """
    if not weight:
        return 0.0

    unit_lower = from_unit.lower().strip()

    if unit_lower not in WEIGHT_CONVERSIONS:
        frappe.throw(
            _("Unsupported weight unit: {0}. Supported units: {1}").format(
                from_unit, ", ".join(WEIGHT_CONVERSIONS.keys())
            ),
            frappe.ValidationError
        )

    return flt(weight) * WEIGHT_CONVERSIONS[unit_lower]


def convert_dimension_to_cm(
    dimension: float,
    from_unit: str = "cm"
) -> float:
    """
    Convert dimension from any supported unit to centimeters.

    Args:
        dimension: The dimension value to convert
        from_unit: The source unit (cm, m, mm, in, ft)

    Returns:
        float: Dimension in centimeters

    Raises:
        frappe.ValidationError: If the unit is not supported

    Example:
        length_cm = convert_dimension_to_cm(10, "in")
        # Returns 25.4
    """
    if not dimension:
        return 0.0

    unit_lower = from_unit.lower().strip()

    if unit_lower not in DIMENSION_CONVERSIONS:
        frappe.throw(
            _("Unsupported dimension unit: {0}. Supported units: {1}").format(
                from_unit, ", ".join(DIMENSION_CONVERSIONS.keys())
            ),
            frappe.ValidationError
        )

    return flt(dimension) * DIMENSION_CONVERSIONS[unit_lower]


# =============================================================================
# DIMENSIONAL WEIGHT CALCULATION
# =============================================================================


def calculate_dimensional_weight(
    length: float,
    width: float,
    height: float,
    dimension_unit: str = "cm",
    divisor: Optional[int] = None,
    shipping_method: str = "air"
) -> float:
    """
    Calculate dimensional (volumetric) weight based on package dimensions.

    Dimensional weight = (Length x Width x Height) / Divisor

    The divisor varies by shipping method:
    - Air freight: 5000 (IATA standard)
    - Sea freight: 1000 (volume in cbm)
    - Ground: 5000

    Args:
        length: Package length
        width: Package width
        height: Package height
        dimension_unit: Unit of measurements (cm, m, in, etc.)
        divisor: Custom dimensional divisor (overrides shipping_method default)
        shipping_method: Shipping method for selecting default divisor

    Returns:
        float: Dimensional weight in kilograms

    Example:
        dim_weight = calculate_dimensional_weight(
            length=50, width=40, height=30,
            dimension_unit="cm",
            shipping_method="air"
        )
        # Returns 12.0 (50 * 40 * 30 / 5000 = 12 kg)
    """
    # Convert dimensions to centimeters
    length_cm = convert_dimension_to_cm(length, dimension_unit)
    width_cm = convert_dimension_to_cm(width, dimension_unit)
    height_cm = convert_dimension_to_cm(height, dimension_unit)

    # Get divisor
    if divisor is None:
        method_lower = shipping_method.lower().strip() if shipping_method else "default"
        divisor = DIMENSIONAL_DIVISORS.get(method_lower, DIMENSIONAL_DIVISORS["default"])

    # Calculate volume in cm3
    volume_cm3 = length_cm * width_cm * height_cm

    # Calculate dimensional weight
    if divisor and divisor > 0:
        dimensional_weight = volume_cm3 / divisor
    else:
        dimensional_weight = 0.0

    return flt(dimensional_weight, 3)


def calculate_chargeable_weight(
    actual_weight: float,
    dimensional_weight: float = 0.0,
    length: float = 0.0,
    width: float = 0.0,
    height: float = 0.0,
    weight_unit: str = "kg",
    dimension_unit: str = "cm",
    divisor: Optional[int] = None,
    shipping_method: str = "air"
) -> Dict[str, float]:
    """
    Calculate chargeable weight (the greater of actual or dimensional weight).

    Shipping carriers typically charge based on the higher of:
    - Actual weight of the package
    - Dimensional (volumetric) weight calculated from dimensions

    Args:
        actual_weight: The physical weight of the package
        dimensional_weight: Pre-calculated dimensional weight (if available)
        length: Package length (used if dimensional_weight not provided)
        width: Package width
        height: Package height
        weight_unit: Unit for actual weight
        dimension_unit: Unit for dimensions
        divisor: Custom dimensional divisor
        shipping_method: Shipping method for divisor selection

    Returns:
        dict: Contains actual_weight, dimensional_weight, chargeable_weight, and weight_type

    Example:
        result = calculate_chargeable_weight(
            actual_weight=8,
            length=50, width=40, height=30,
            dimension_unit="cm"
        )
        # Returns:
        # {
        #     "actual_weight": 8.0,
        #     "dimensional_weight": 12.0,
        #     "chargeable_weight": 12.0,
        #     "weight_type": "dimensional"
        # }
    """
    # Convert actual weight to kg
    actual_weight_kg = convert_weight_to_kg(actual_weight, weight_unit)

    # Calculate dimensional weight if not provided
    if dimensional_weight <= 0 and (length > 0 or width > 0 or height > 0):
        dimensional_weight = calculate_dimensional_weight(
            length=length,
            width=width,
            height=height,
            dimension_unit=dimension_unit,
            divisor=divisor,
            shipping_method=shipping_method
        )

    # Determine chargeable weight
    chargeable_weight = max(actual_weight_kg, dimensional_weight)
    weight_type = "dimensional" if dimensional_weight > actual_weight_kg else "actual"

    return {
        "actual_weight": flt(actual_weight_kg, 3),
        "dimensional_weight": flt(dimensional_weight, 3),
        "chargeable_weight": flt(chargeable_weight, 3),
        "weight_type": weight_type
    }


# =============================================================================
# FREIGHT COST CALCULATION
# =============================================================================


def calculate_freight(
    weight: float = 0.0,
    carrier: str = None,
    origin_country: str = None,
    destination_country: str = None,
    shipping_method: str = None,
    length: float = 0.0,
    width: float = 0.0,
    height: float = 0.0,
    weight_unit: str = "kg",
    dimension_unit: str = "cm",
    package_count: int = 1,
    base_rate: float = None,
    rate_per_kg: float = None,
    fuel_surcharge_percent: float = None,
    currency: str = None
) -> Dict[str, Any]:
    """
    Calculate freight cost for a shipment.

    This is the main freight calculation function that:
    1. Calculates dimensional weight from dimensions
    2. Determines chargeable weight
    3. Applies carrier rates (base + per-kg)
    4. Adds fuel surcharge
    5. Returns detailed cost breakdown

    Args:
        weight: Actual package weight
        carrier: Carrier code (e.g., "FEDEX", "DHL")
        origin_country: Origin country code
        destination_country: Destination country code
        shipping_method: Shipping method (Air, Ground, Sea, etc.)
        length: Package length
        width: Package width
        height: Package height
        weight_unit: Weight unit
        dimension_unit: Dimension unit
        package_count: Number of packages
        base_rate: Override carrier base rate
        rate_per_kg: Override carrier per-kg rate
        fuel_surcharge_percent: Override fuel surcharge
        currency: Currency for rates

    Returns:
        dict: Freight calculation result including:
            - chargeable_weight
            - base_cost
            - weight_cost
            - fuel_surcharge
            - freight_cost
            - currency
            - breakdown

    Example:
        freight = calculate_freight(
            weight=50,
            carrier="FEDEX",
            origin_country="TR",
            destination_country="DE",
            shipping_method="Air"
        )
    """
    result = {
        "actual_weight": 0.0,
        "dimensional_weight": 0.0,
        "chargeable_weight": 0.0,
        "weight_type": "actual",
        "base_cost": 0.0,
        "weight_cost": 0.0,
        "fuel_surcharge": 0.0,
        "freight_cost": 0.0,
        "currency": currency or "USD",
        "carrier": carrier,
        "shipping_method": shipping_method,
        "package_count": package_count,
        "breakdown": []
    }

    # Get carrier settings if carrier is provided
    carrier_settings = None
    if carrier:
        carrier_settings = get_carrier_settings(carrier)
        if carrier_settings:
            if base_rate is None:
                base_rate = flt(carrier_settings.get("base_rate", 0))
            if rate_per_kg is None:
                rate_per_kg = flt(carrier_settings.get("rate_per_kg", 0))
            if fuel_surcharge_percent is None:
                fuel_surcharge_percent = flt(carrier_settings.get("fuel_surcharge_percent", 0))
            if not currency:
                result["currency"] = carrier_settings.get("currency", "USD")

    # Default rates if not specified
    if base_rate is None:
        base_rate = 0.0
    if rate_per_kg is None:
        rate_per_kg = 0.0
    if fuel_surcharge_percent is None:
        fuel_surcharge_percent = 0.0

    # Get dimensional divisor from carrier or use default
    divisor = None
    if carrier_settings and carrier_settings.get("dimensional_divisor"):
        divisor = cint(carrier_settings.get("dimensional_divisor"))

    # Calculate chargeable weight
    weight_result = calculate_chargeable_weight(
        actual_weight=weight,
        length=length,
        width=width,
        height=height,
        weight_unit=weight_unit,
        dimension_unit=dimension_unit,
        divisor=divisor,
        shipping_method=shipping_method or "air"
    )

    result["actual_weight"] = weight_result["actual_weight"]
    result["dimensional_weight"] = weight_result["dimensional_weight"]
    result["chargeable_weight"] = weight_result["chargeable_weight"]
    result["weight_type"] = weight_result["weight_type"]

    # Calculate base cost (per package)
    base_cost = flt(base_rate) * cint(package_count)
    result["base_cost"] = flt(base_cost, 2)
    if base_cost > 0:
        result["breakdown"].append({
            "description": _("Base Rate ({0} packages)").format(package_count),
            "amount": base_cost
        })

    # Calculate weight-based cost
    weight_cost = flt(rate_per_kg) * result["chargeable_weight"]
    result["weight_cost"] = flt(weight_cost, 2)
    if weight_cost > 0:
        result["breakdown"].append({
            "description": _("Weight Charge ({0} kg x {1})").format(
                result["chargeable_weight"], rate_per_kg
            ),
            "amount": weight_cost
        })

    # Calculate subtotal before surcharges
    subtotal = base_cost + weight_cost

    # Calculate fuel surcharge
    fuel_surcharge = 0.0
    if fuel_surcharge_percent > 0 and subtotal > 0:
        fuel_surcharge = subtotal * (flt(fuel_surcharge_percent) / 100)
        result["fuel_surcharge"] = flt(fuel_surcharge, 2)
        result["breakdown"].append({
            "description": _("Fuel Surcharge ({0}%)").format(fuel_surcharge_percent),
            "amount": fuel_surcharge
        })

    # Calculate total freight cost
    freight_cost = subtotal + fuel_surcharge
    result["freight_cost"] = flt(freight_cost, 2)

    return result


def get_carrier_settings(carrier: str) -> Optional[Dict[str, Any]]:
    """
    Get carrier rate settings from the Carrier DocType.

    Args:
        carrier: Carrier code or name

    Returns:
        dict or None: Carrier settings including rates and divisors

    Example:
        settings = get_carrier_settings("FEDEX")
    """
    if not carrier:
        return None

    try:
        # Try to find by carrier_code first
        carrier_name = frappe.db.get_value(
            "Carrier",
            {"carrier_code": carrier, "enabled": 1},
            "name"
        )

        # If not found, try by name directly
        if not carrier_name:
            carrier_name = frappe.db.get_value(
                "Carrier",
                {"name": carrier, "enabled": 1},
                "name"
            )

        if not carrier_name:
            return None

        carrier_doc = frappe.db.get_value(
            "Carrier",
            carrier_name,
            [
                "carrier_name",
                "carrier_code",
                "carrier_type",
                "base_rate",
                "rate_per_kg",
                "dimensional_divisor",
                "fuel_surcharge_percent",
                "currency",
                "default_transit_days",
                "min_weight",
                "max_weight"
            ],
            as_dict=True
        )

        return carrier_doc

    except Exception:
        return None


# =============================================================================
# INSURANCE CALCULATION
# =============================================================================


def calculate_insurance_cost(
    cargo_value: float,
    insurance_rate: float = 0.5,
    minimum_premium: float = 0.0,
    currency: str = "USD"
) -> Dict[str, Any]:
    """
    Calculate shipping insurance cost based on cargo value.

    Insurance cost = Cargo Value x Insurance Rate / 100

    Args:
        cargo_value: Total value of the cargo being shipped
        insurance_rate: Insurance rate as percentage (default 0.5%)
        minimum_premium: Minimum insurance premium
        currency: Currency for the values

    Returns:
        dict: Insurance cost details

    Example:
        insurance = calculate_insurance_cost(
            cargo_value=10000,
            insurance_rate=0.5
        )
        # Returns {"insurance_cost": 50.0, ...}
    """
    if not cargo_value or cargo_value <= 0:
        return {
            "cargo_value": 0.0,
            "insurance_rate": insurance_rate,
            "insurance_cost": 0.0,
            "currency": currency
        }

    # Calculate insurance premium
    premium = flt(cargo_value) * (flt(insurance_rate) / 100)

    # Apply minimum premium
    if minimum_premium > 0 and premium < minimum_premium:
        premium = minimum_premium

    return {
        "cargo_value": flt(cargo_value, 2),
        "insurance_rate": flt(insurance_rate, 4),
        "insurance_cost": flt(premium, 2),
        "currency": currency
    }


# =============================================================================
# TOTAL SHIPPING COST CALCULATION
# =============================================================================


def calculate_total_shipping_cost(
    freight_cost: float = 0.0,
    insurance_cost: float = 0.0,
    customs_duty: float = 0.0,
    customs_tax: float = 0.0,
    handling_fee: float = 0.0,
    additional_fees: float = 0.0,
    currency: str = "USD"
) -> Dict[str, Any]:
    """
    Calculate total shipping cost by aggregating all components.

    Total = Freight + Insurance + Customs Duties + Taxes + Handling + Other

    Args:
        freight_cost: Base freight/shipping cost
        insurance_cost: Cargo insurance cost
        customs_duty: Import/export duties
        customs_tax: VAT or other taxes on import
        handling_fee: Terminal/handling fees
        additional_fees: Any other miscellaneous fees
        currency: Currency for all amounts

    Returns:
        dict: Total shipping cost with breakdown

    Example:
        total = calculate_total_shipping_cost(
            freight_cost=500,
            insurance_cost=50,
            customs_duty=100,
            customs_tax=20
        )
    """
    breakdown = []

    if freight_cost > 0:
        breakdown.append({
            "description": _("Freight Cost"),
            "amount": flt(freight_cost, 2)
        })

    if insurance_cost > 0:
        breakdown.append({
            "description": _("Insurance Cost"),
            "amount": flt(insurance_cost, 2)
        })

    if customs_duty > 0:
        breakdown.append({
            "description": _("Customs Duty"),
            "amount": flt(customs_duty, 2)
        })

    if customs_tax > 0:
        breakdown.append({
            "description": _("Customs Tax/VAT"),
            "amount": flt(customs_tax, 2)
        })

    if handling_fee > 0:
        breakdown.append({
            "description": _("Handling Fee"),
            "amount": flt(handling_fee, 2)
        })

    if additional_fees > 0:
        breakdown.append({
            "description": _("Additional Fees"),
            "amount": flt(additional_fees, 2)
        })

    total = (
        flt(freight_cost) +
        flt(insurance_cost) +
        flt(customs_duty) +
        flt(customs_tax) +
        flt(handling_fee) +
        flt(additional_fees)
    )

    return {
        "freight_cost": flt(freight_cost, 2),
        "insurance_cost": flt(insurance_cost, 2),
        "customs_duty": flt(customs_duty, 2),
        "customs_tax": flt(customs_tax, 2),
        "handling_fee": flt(handling_fee, 2),
        "additional_fees": flt(additional_fees, 2),
        "total_shipping_cost": flt(total, 2),
        "currency": currency,
        "breakdown": breakdown
    }


# =============================================================================
# INCOTERM COST CALCULATIONS
# =============================================================================


def get_incoterm_cost_breakdown(
    incoterm: str,
    freight_cost: float = 0.0,
    insurance_cost: float = 0.0,
    export_customs_cost: float = 0.0,
    import_customs_cost: float = 0.0,
    delivery_cost: float = 0.0,
    currency: str = "USD"
) -> Dict[str, Any]:
    """
    Get cost breakdown based on Incoterm responsibilities.

    Different Incoterms allocate shipping costs differently between buyer and seller:
    - EXW: Buyer pays everything
    - FOB: Seller pays to port of shipment
    - CIF: Seller pays freight and insurance
    - DDP: Seller pays everything including import duties

    Args:
        incoterm: The Incoterm code (EXW, FOB, CIF, DDP, etc.)
        freight_cost: Total freight cost
        insurance_cost: Total insurance cost
        export_customs_cost: Export customs and duties
        import_customs_cost: Import customs and duties
        delivery_cost: Final delivery cost
        currency: Currency for amounts

    Returns:
        dict: Cost breakdown by party (seller_pays, buyer_pays)

    Example:
        breakdown = get_incoterm_cost_breakdown(
            incoterm="CIF",
            freight_cost=500,
            insurance_cost=50,
            export_customs_cost=20,
            import_customs_cost=100
        )
    """
    incoterm_upper = incoterm.upper() if incoterm else "EXW"

    if incoterm_upper not in INCOTERM_RESPONSIBILITIES:
        incoterm_upper = "EXW"

    responsibilities = INCOTERM_RESPONSIBILITIES[incoterm_upper]

    seller_pays = {
        "freight": flt(freight_cost, 2) if responsibilities["freight"] else 0.0,
        "insurance": flt(insurance_cost, 2) if responsibilities["insurance"] else 0.0,
        "export_customs": flt(export_customs_cost, 2) if responsibilities["customs_export"] else 0.0,
        "import_customs": flt(import_customs_cost, 2) if responsibilities["customs_import"] else 0.0,
        "delivery": flt(delivery_cost, 2) if responsibilities["delivery_to_destination"] else 0.0,
    }
    seller_pays["total"] = flt(sum(seller_pays.values()), 2)

    buyer_pays = {
        "freight": flt(freight_cost, 2) if not responsibilities["freight"] else 0.0,
        "insurance": flt(insurance_cost, 2) if not responsibilities["insurance"] else 0.0,
        "export_customs": flt(export_customs_cost, 2) if not responsibilities["customs_export"] else 0.0,
        "import_customs": flt(import_customs_cost, 2) if not responsibilities["customs_import"] else 0.0,
        "delivery": flt(delivery_cost, 2) if not responsibilities["delivery_to_destination"] else 0.0,
    }
    buyer_pays["total"] = flt(sum(buyer_pays.values()), 2)

    return {
        "incoterm": incoterm_upper,
        "incoterm_description": get_incoterm_description(incoterm_upper),
        "seller_pays": seller_pays,
        "buyer_pays": buyer_pays,
        "total_shipping_cost": flt(
            freight_cost + insurance_cost + export_customs_cost +
            import_customs_cost + delivery_cost, 2
        ),
        "currency": currency,
        "responsibilities": responsibilities
    }


def get_incoterm_description(incoterm: str) -> str:
    """
    Get the full description of an Incoterm.

    Args:
        incoterm: The Incoterm code

    Returns:
        str: Full description of the Incoterm
    """
    descriptions = {
        "EXW": _("Ex Works - Buyer bears all costs and risks"),
        "FOB": _("Free On Board - Seller delivers to port, buyer pays freight"),
        "CIF": _("Cost, Insurance and Freight - Seller pays freight and insurance"),
        "DDP": _("Delivered Duty Paid - Seller pays all costs including import duties"),
        "DAP": _("Delivered at Place - Seller pays all costs except import duties"),
        "FCA": _("Free Carrier - Seller delivers to carrier at named place"),
        "CPT": _("Carriage Paid To - Seller pays freight to destination"),
        "CIP": _("Carriage and Insurance Paid To - Seller pays freight and insurance"),
        "DAT": _("Delivered at Terminal - Seller delivers unloaded at terminal"),
        "DPU": _("Delivered at Place Unloaded - Seller delivers and unloads"),
    }

    incoterm_upper = incoterm.upper() if incoterm else "EXW"
    return descriptions.get(incoterm_upper, _("Unknown Incoterm"))


# =============================================================================
# CARRIER COMPARISON
# =============================================================================


def compare_carrier_rates(
    weight: float,
    origin_country: str = None,
    destination_country: str = None,
    length: float = 0.0,
    width: float = 0.0,
    height: float = 0.0,
    weight_unit: str = "kg",
    dimension_unit: str = "cm",
    package_count: int = 1,
    tenant: str = None
) -> List[Dict[str, Any]]:
    """
    Compare freight rates across multiple available carriers.

    This function calculates freight costs for all enabled carriers
    and returns them sorted by cost (lowest first).

    Args:
        weight: Package weight
        origin_country: Origin country code
        destination_country: Destination country code
        length: Package length
        width: Package width
        height: Package height
        weight_unit: Weight unit
        dimension_unit: Dimension unit
        package_count: Number of packages
        tenant: Tenant for multi-tenant filtering

    Returns:
        list: List of carrier quotes sorted by freight cost

    Example:
        quotes = compare_carrier_rates(
            weight=50,
            origin_country="TR",
            destination_country="DE",
            length=50, width=40, height=30
        )
    """
    results = []

    # Build filters for carrier query
    filters = {"enabled": 1}
    if tenant:
        filters["tenant"] = tenant

    # Get all enabled carriers
    try:
        carriers = frappe.get_all(
            "Carrier",
            filters=filters,
            fields=[
                "name",
                "carrier_name",
                "carrier_code",
                "carrier_type",
                "base_rate",
                "rate_per_kg",
                "dimensional_divisor",
                "fuel_surcharge_percent",
                "currency",
                "default_transit_days"
            ]
        )
    except Exception:
        carriers = []

    # Calculate freight for each carrier
    for carrier in carriers:
        freight_result = calculate_freight(
            weight=weight,
            carrier=carrier.name,
            origin_country=origin_country,
            destination_country=destination_country,
            length=length,
            width=width,
            height=height,
            weight_unit=weight_unit,
            dimension_unit=dimension_unit,
            package_count=package_count,
            base_rate=flt(carrier.base_rate),
            rate_per_kg=flt(carrier.rate_per_kg),
            fuel_surcharge_percent=flt(carrier.fuel_surcharge_percent),
            currency=carrier.currency or "USD"
        )

        results.append({
            "carrier": carrier.name,
            "carrier_name": carrier.carrier_name,
            "carrier_code": carrier.carrier_code,
            "carrier_type": carrier.carrier_type,
            "transit_days": cint(carrier.default_transit_days),
            "freight_cost": freight_result["freight_cost"],
            "currency": freight_result["currency"],
            "chargeable_weight": freight_result["chargeable_weight"],
            "weight_type": freight_result["weight_type"],
            "breakdown": freight_result["breakdown"]
        })

    # Sort by freight cost (lowest first)
    results.sort(key=lambda x: x["freight_cost"])

    return results


# =============================================================================
# WHITELISTED API FUNCTIONS
# =============================================================================


@frappe.whitelist()
def api_calculate_freight(
    weight: float = 0,
    carrier: str = None,
    origin_country: str = None,
    destination_country: str = None,
    shipping_method: str = None,
    length: float = 0,
    width: float = 0,
    height: float = 0,
    weight_unit: str = "kg",
    dimension_unit: str = "cm",
    package_count: int = 1
) -> Dict[str, Any]:
    """
    API endpoint for freight calculation.

    Example API call:
        frappe.call({
            method: 'tr_tradehub.utils.freight_calculator.api_calculate_freight',
            args: {
                weight: 50,
                carrier: 'FEDEX',
                origin_country: 'TR',
                destination_country: 'DE',
                length: 50,
                width: 40,
                height: 30
            },
            callback: function(r) {
                console.log(r.message.freight_cost);
            }
        });
    """
    return calculate_freight(
        weight=flt(weight),
        carrier=carrier,
        origin_country=origin_country,
        destination_country=destination_country,
        shipping_method=shipping_method,
        length=flt(length),
        width=flt(width),
        height=flt(height),
        weight_unit=weight_unit,
        dimension_unit=dimension_unit,
        package_count=cint(package_count) or 1
    )


@frappe.whitelist()
def api_calculate_dimensional_weight(
    length: float,
    width: float,
    height: float,
    dimension_unit: str = "cm",
    shipping_method: str = "air",
    divisor: int = None
) -> float:
    """
    API endpoint for dimensional weight calculation.

    Example API call:
        frappe.call({
            method: 'tr_tradehub.utils.freight_calculator.api_calculate_dimensional_weight',
            args: {
                length: 50,
                width: 40,
                height: 30,
                dimension_unit: 'cm',
                shipping_method: 'air'
            },
            callback: function(r) {
                console.log(r.message);  // 12.0
            }
        });
    """
    return calculate_dimensional_weight(
        length=flt(length),
        width=flt(width),
        height=flt(height),
        dimension_unit=dimension_unit,
        divisor=cint(divisor) if divisor else None,
        shipping_method=shipping_method
    )


@frappe.whitelist()
def api_compare_carriers(
    weight: float = 0,
    origin_country: str = None,
    destination_country: str = None,
    length: float = 0,
    width: float = 0,
    height: float = 0,
    weight_unit: str = "kg",
    dimension_unit: str = "cm",
    package_count: int = 1
) -> List[Dict[str, Any]]:
    """
    API endpoint to compare carrier rates.

    Example API call:
        frappe.call({
            method: 'tr_tradehub.utils.freight_calculator.api_compare_carriers',
            args: {
                weight: 50,
                origin_country: 'TR',
                destination_country: 'DE'
            },
            callback: function(r) {
                r.message.forEach(function(carrier) {
                    console.log(carrier.carrier_name, carrier.freight_cost);
                });
            }
        });
    """
    from tr_tradehub.utils.tenant import get_current_tenant
    tenant = get_current_tenant()

    return compare_carrier_rates(
        weight=flt(weight),
        origin_country=origin_country,
        destination_country=destination_country,
        length=flt(length),
        width=flt(width),
        height=flt(height),
        weight_unit=weight_unit,
        dimension_unit=dimension_unit,
        package_count=cint(package_count) or 1,
        tenant=tenant
    )


@frappe.whitelist()
def api_get_incoterm_breakdown(
    incoterm: str,
    freight_cost: float = 0,
    insurance_cost: float = 0,
    export_customs_cost: float = 0,
    import_customs_cost: float = 0,
    delivery_cost: float = 0,
    currency: str = "USD"
) -> Dict[str, Any]:
    """
    API endpoint for Incoterm cost breakdown.

    Example API call:
        frappe.call({
            method: 'tr_tradehub.utils.freight_calculator.api_get_incoterm_breakdown',
            args: {
                incoterm: 'CIF',
                freight_cost: 500,
                insurance_cost: 50,
                export_customs_cost: 20,
                import_customs_cost: 100
            },
            callback: function(r) {
                console.log('Seller pays:', r.message.seller_pays.total);
                console.log('Buyer pays:', r.message.buyer_pays.total);
            }
        });
    """
    return get_incoterm_cost_breakdown(
        incoterm=incoterm,
        freight_cost=flt(freight_cost),
        insurance_cost=flt(insurance_cost),
        export_customs_cost=flt(export_customs_cost),
        import_customs_cost=flt(import_customs_cost),
        delivery_cost=flt(delivery_cost),
        currency=currency
    )


@frappe.whitelist()
def api_calculate_insurance(
    cargo_value: float,
    insurance_rate: float = 0.5,
    minimum_premium: float = 0,
    currency: str = "USD"
) -> Dict[str, Any]:
    """
    API endpoint for insurance cost calculation.

    Example API call:
        frappe.call({
            method: 'tr_tradehub.utils.freight_calculator.api_calculate_insurance',
            args: {
                cargo_value: 10000,
                insurance_rate: 0.5
            },
            callback: function(r) {
                console.log(r.message.insurance_cost);  // 50.0
            }
        });
    """
    return calculate_insurance_cost(
        cargo_value=flt(cargo_value),
        insurance_rate=flt(insurance_rate) or 0.5,
        minimum_premium=flt(minimum_premium),
        currency=currency
    )

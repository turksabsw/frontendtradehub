# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import (
    cint, flt, getdate, nowdate, now_datetime,
    add_days, get_datetime, date_diff
)


class ShippingRule(Document):
    """
    Shipping Rule DocType for TR-TradeHub.

    Defines shipping rates, zones, and calculation methods for the marketplace.
    Supports multiple rate calculation methods:
    - Fixed rate
    - Weight-based
    - Price percentage
    - Item count based
    - Tiered pricing

    Features:
    - Zone-based shipping
    - Free shipping thresholds
    - Express delivery options
    - Category restrictions
    - Carrier preferences
    - Turkish market support
    """

    def before_insert(self):
        """Set default values before creating a new shipping rule."""
        if not self.currency:
            self.currency = "TRY"

        # Set default priority if not set
        if not self.priority:
            self.priority = 10

    def validate(self):
        """Validate shipping rule data before saving."""
        self.validate_rule_name()
        self.validate_zones()
        self.validate_rates()
        self.validate_free_shipping()
        self.validate_conditions()
        self.validate_delivery_estimates()
        self.validate_validity_period()

    # =================================================================
    # Validation Methods
    # =================================================================

    def validate_rule_name(self):
        """Validate rule name."""
        if not self.rule_name:
            frappe.throw(_("Rule Name is required"))

        if len(self.rule_name) < 3:
            frappe.throw(_("Rule Name must be at least 3 characters"))

    def validate_zones(self):
        """Validate shipping zones."""
        if self.zones:
            # Check for duplicate zones
            zone_keys = []
            for zone in self.zones:
                key = f"{zone.country}:{zone.city or 'all'}:{zone.postal_code_from or ''}-{zone.postal_code_to or ''}"
                if key in zone_keys:
                    frappe.throw(
                        _("Duplicate zone configuration: {0}").format(key)
                    )
                zone_keys.append(key)

    def validate_rates(self):
        """Validate rate configuration."""
        # Ensure at least one rate is set
        if self.calculation_method == "Fixed":
            if flt(self.base_rate) < 0:
                frappe.throw(_("Base rate cannot be negative"))

        elif self.calculation_method == "Weight Based":
            if flt(self.per_kg_rate) < 0:
                frappe.throw(_("Per KG rate cannot be negative"))

        elif self.calculation_method == "Price Percentage":
            # Price percentage uses rate_tiers
            pass

        elif self.calculation_method == "Item Count":
            if flt(self.per_item_rate) < 0:
                frappe.throw(_("Per item rate cannot be negative"))

        elif self.calculation_method in ["Weight Tiered", "Price Tiered"]:
            if not self.rate_tiers:
                frappe.throw(
                    _("Rate tiers are required for tiered calculation methods")
                )
            self.validate_rate_tiers()

    def validate_rate_tiers(self):
        """Validate rate tier configuration."""
        if not self.rate_tiers:
            return

        # Sort tiers by threshold
        sorted_tiers = sorted(self.rate_tiers, key=lambda x: flt(x.threshold_from))

        prev_to = 0
        for tier in sorted_tiers:
            # Check for gaps or overlaps
            if flt(tier.threshold_from) < prev_to:
                frappe.throw(
                    _("Rate tier overlap detected at threshold {0}").format(
                        tier.threshold_from
                    )
                )

            if flt(tier.threshold_to) > 0 and flt(tier.threshold_to) <= flt(tier.threshold_from):
                frappe.throw(
                    _("Tier threshold_to must be greater than threshold_from")
                )

            prev_to = flt(tier.threshold_to) if flt(tier.threshold_to) > 0 else float('inf')

    def validate_free_shipping(self):
        """Validate free shipping configuration."""
        if self.free_shipping_enabled:
            if flt(self.free_shipping_threshold) <= 0:
                frappe.throw(
                    _("Free shipping threshold must be greater than 0")
                )

    def validate_conditions(self):
        """Validate order conditions."""
        if flt(self.max_order_amount) > 0:
            if flt(self.min_order_amount) > flt(self.max_order_amount):
                frappe.throw(
                    _("Minimum order amount cannot exceed maximum order amount")
                )

        if flt(self.max_weight) > 0:
            if flt(self.min_weight) > flt(self.max_weight):
                frappe.throw(
                    _("Minimum weight cannot exceed maximum weight")
                )

    def validate_delivery_estimates(self):
        """Validate delivery time estimates."""
        if cint(self.estimated_days_min) < 0:
            frappe.throw(_("Minimum delivery days cannot be negative"))

        if cint(self.estimated_days_max) < cint(self.estimated_days_min):
            frappe.throw(
                _("Maximum delivery days must be >= minimum delivery days")
            )

        if self.express_available:
            if cint(self.express_days) < 1:
                frappe.throw(_("Express days must be at least 1"))

    def validate_validity_period(self):
        """Validate validity period."""
        if self.valid_from and self.valid_to:
            if getdate(self.valid_to) < getdate(self.valid_from):
                frappe.throw(_("Valid To date must be after Valid From date"))

    # =================================================================
    # Calculation Methods
    # =================================================================

    def calculate_shipping(self, order_data):
        """
        Calculate shipping cost for an order.

        Args:
            order_data: dict with keys:
                - order_amount: Total order amount
                - total_weight: Total weight in kg
                - item_count: Number of items
                - destination: dict with country, city, postal_code
                - categories: list of category names
                - express: bool for express delivery

        Returns:
            dict: Shipping calculation result
        """
        # Check if rule is valid
        if not self.is_valid_for_order(order_data):
            return None

        # Check zone applicability
        if not self.is_zone_applicable(order_data.get("destination", {})):
            return None

        # Check free shipping
        if self.qualifies_for_free_shipping(order_data):
            return {
                "shipping_amount": 0,
                "is_free_shipping": True,
                "rule_name": self.rule_name,
                "carrier": self.default_carrier,
                "estimated_days_min": self.estimated_days_min,
                "estimated_days_max": self.estimated_days_max,
                "breakdown": {
                    "base_rate": 0,
                    "weight_charge": 0,
                    "handling_fee": 0,
                    "packaging_fee": 0,
                    "insurance": 0,
                    "express_surcharge": 0,
                    "tax": 0
                }
            }

        # Calculate base shipping
        shipping_amount = self.calculate_base_shipping(order_data)

        # Add handling fee
        handling = self.calculate_handling_fee(order_data)

        # Add packaging fee
        packaging = flt(self.packaging_fee)

        # Add insurance
        insurance = self.calculate_insurance(order_data)

        # Add express surcharge
        express_surcharge = 0
        if order_data.get("express") and self.express_available:
            express_surcharge = flt(self.express_surcharge)

        # Calculate subtotal
        subtotal = shipping_amount + handling + packaging + insurance + express_surcharge

        # Calculate tax
        tax = 0
        if not self.price_includes_tax and flt(self.tax_rate) > 0:
            tax = subtotal * (flt(self.tax_rate) / 100)

        total = subtotal + tax

        # Delivery estimate
        est_min = self.estimated_days_min
        est_max = self.estimated_days_max
        if order_data.get("express") and self.express_available:
            est_min = self.express_days
            est_max = self.express_days

        return {
            "shipping_amount": total,
            "is_free_shipping": False,
            "rule_name": self.rule_name,
            "carrier": self.default_carrier,
            "estimated_days_min": est_min,
            "estimated_days_max": est_max,
            "breakdown": {
                "base_rate": shipping_amount,
                "weight_charge": 0 if self.calculation_method != "Weight Based" else shipping_amount - flt(self.base_rate),
                "handling_fee": handling,
                "packaging_fee": packaging,
                "insurance": insurance,
                "express_surcharge": express_surcharge,
                "tax": tax
            }
        }

    def calculate_base_shipping(self, order_data):
        """Calculate base shipping amount."""
        if self.calculation_method == "Fixed":
            return flt(self.base_rate)

        elif self.calculation_method == "Weight Based":
            weight = flt(order_data.get("total_weight", 0))
            return flt(self.base_rate) + (weight * flt(self.per_kg_rate))

        elif self.calculation_method == "Price Percentage":
            amount = flt(order_data.get("order_amount", 0))
            rate = self.get_percentage_rate(amount)
            return amount * (rate / 100)

        elif self.calculation_method == "Item Count":
            count = cint(order_data.get("item_count", 1))
            return flt(self.base_rate) + (count * flt(self.per_item_rate))

        elif self.calculation_method == "Weight Tiered":
            weight = flt(order_data.get("total_weight", 0))
            return self.get_tiered_rate(weight)

        elif self.calculation_method == "Price Tiered":
            amount = flt(order_data.get("order_amount", 0))
            return self.get_tiered_rate(amount)

        elif self.calculation_method == "Combined":
            weight = flt(order_data.get("total_weight", 0))
            count = cint(order_data.get("item_count", 1))
            return (
                flt(self.base_rate)
                + (weight * flt(self.per_kg_rate))
                + (count * flt(self.per_item_rate))
            )

        return flt(self.base_rate)

    def get_tiered_rate(self, value):
        """Get rate from tiered pricing."""
        if not self.rate_tiers:
            return flt(self.base_rate)

        # Sort tiers by threshold
        sorted_tiers = sorted(self.rate_tiers, key=lambda x: flt(x.threshold_from))

        for tier in sorted_tiers:
            threshold_to = flt(tier.threshold_to) if flt(tier.threshold_to) > 0 else float('inf')
            if flt(tier.threshold_from) <= value < threshold_to:
                return flt(tier.rate)

        # Return last tier rate if value exceeds all tiers
        if sorted_tiers:
            return flt(sorted_tiers[-1].rate)

        return flt(self.base_rate)

    def get_percentage_rate(self, amount):
        """Get percentage rate for price-based calculation."""
        # Use rate tiers for percentage calculation
        if not self.rate_tiers:
            return 0

        sorted_tiers = sorted(self.rate_tiers, key=lambda x: flt(x.threshold_from))

        for tier in sorted_tiers:
            threshold_to = flt(tier.threshold_to) if flt(tier.threshold_to) > 0 else float('inf')
            if flt(tier.threshold_from) <= amount < threshold_to:
                return flt(tier.rate)

        if sorted_tiers:
            return flt(sorted_tiers[-1].rate)

        return 0

    def calculate_handling_fee(self, order_data):
        """Calculate handling fee."""
        if self.handling_fee_type == "Percentage":
            return flt(order_data.get("order_amount", 0)) * (flt(self.handling_fee) / 100)
        return flt(self.handling_fee)

    def calculate_insurance(self, order_data):
        """Calculate insurance amount."""
        if flt(self.insurance_rate) > 0:
            return flt(order_data.get("order_amount", 0)) * (flt(self.insurance_rate) / 100)
        return 0

    # =================================================================
    # Eligibility Methods
    # =================================================================

    def is_valid_for_order(self, order_data):
        """Check if this rule is valid for the given order."""
        # Check if rule is active
        if not self.is_active:
            return False

        # Check validity period
        today = getdate(nowdate())
        if self.valid_from and getdate(self.valid_from) > today:
            return False
        if self.valid_to and getdate(self.valid_to) < today:
            return False

        # Check order amount conditions
        order_amount = flt(order_data.get("order_amount", 0))
        if flt(self.min_order_amount) > 0 and order_amount < flt(self.min_order_amount):
            return False
        if flt(self.max_order_amount) > 0 and order_amount > flt(self.max_order_amount):
            return False

        # Check weight conditions
        total_weight = flt(order_data.get("total_weight", 0))
        if flt(self.min_weight) > 0 and total_weight < flt(self.min_weight):
            return False
        if flt(self.max_weight) > 0 and total_weight > flt(self.max_weight):
            return False

        # Check category restrictions
        if not self.is_category_applicable(order_data.get("categories", [])):
            return False

        return True

    def is_zone_applicable(self, destination):
        """Check if the destination is within applicable zones."""
        if not self.zones:
            # No zones defined = applies everywhere
            return True

        country = destination.get("country", "Turkey")
        city = destination.get("city", "")
        postal_code = destination.get("postal_code", "")

        for zone in self.zones:
            # Check country
            if zone.country and zone.country.lower() != country.lower():
                continue

            # Check city (if specified)
            if zone.city and zone.city.lower() != city.lower():
                continue

            # Check postal code range (if specified)
            if zone.postal_code_from or zone.postal_code_to:
                if not self.is_in_postal_range(
                    postal_code, zone.postal_code_from, zone.postal_code_to
                ):
                    continue

            # Zone matches
            return True

        return False

    def is_in_postal_range(self, postal_code, from_code, to_code):
        """Check if postal code is within range."""
        if not postal_code:
            return True

        try:
            code = int(postal_code.replace(" ", "").replace("-", ""))
            from_int = int(from_code.replace(" ", "").replace("-", "")) if from_code else 0
            to_int = int(to_code.replace(" ", "").replace("-", "")) if to_code else 99999
            return from_int <= code <= to_int
        except ValueError:
            # Non-numeric postal codes - do string comparison
            if from_code and to_code:
                return from_code <= postal_code <= to_code
            return True

    def is_category_applicable(self, categories):
        """Check if the rule applies to given categories."""
        if self.apply_to_all_categories:
            # Check excluded categories
            if self.excluded_categories:
                excluded = [c.strip().lower() for c in self.excluded_categories.split(",")]
                for cat in categories:
                    if cat.lower() in excluded:
                        return False
            return True

        # Check allowed categories
        if self.allowed_categories:
            allowed = [c.strip().lower() for c in self.allowed_categories.split(",")]
            for cat in categories:
                if cat.lower() in allowed:
                    return True
            return False

        return True

    def qualifies_for_free_shipping(self, order_data):
        """Check if order qualifies for free shipping."""
        if not self.free_shipping_enabled:
            return False

        order_amount = flt(order_data.get("order_amount", 0))
        if order_amount >= flt(self.free_shipping_threshold):
            return True

        # Check free shipping categories
        if self.free_shipping_categories:
            free_cats = [c.strip().lower() for c in self.free_shipping_categories.split(",")]
            categories = order_data.get("categories", [])
            for cat in categories:
                if cat.lower() in free_cats:
                    return True

        # Check free shipping items
        if self.free_shipping_items:
            free_items = [i.strip().lower() for i in self.free_shipping_items.split(",")]
            items = order_data.get("item_codes", [])
            for item in items:
                if item.lower() in free_items:
                    return True

        return False

    # =================================================================
    # Utility Methods
    # =================================================================

    def get_delivery_estimate(self, express=False):
        """Get delivery time estimate."""
        if express and self.express_available:
            return {
                "min_days": self.express_days,
                "max_days": self.express_days,
                "is_express": True
            }

        return {
            "min_days": self.estimated_days_min,
            "max_days": self.estimated_days_max,
            "is_express": False
        }

    def get_allowed_carriers_list(self):
        """Get list of allowed carriers."""
        if self.allowed_carriers:
            return [c.strip() for c in self.allowed_carriers.split(",")]
        elif self.default_carrier:
            return [self.default_carrier]
        return []

    def get_summary(self):
        """Get rule summary for display."""
        return {
            "name": self.name,
            "rule_name": self.rule_name,
            "rule_type": self.rule_type,
            "calculation_method": self.calculation_method,
            "is_active": self.is_active,
            "seller": self.seller,
            "base_rate": self.base_rate,
            "currency": self.currency,
            "free_shipping_enabled": self.free_shipping_enabled,
            "free_shipping_threshold": self.free_shipping_threshold,
            "estimated_days_min": self.estimated_days_min,
            "estimated_days_max": self.estimated_days_max,
            "express_available": self.express_available,
            "default_carrier": self.default_carrier
        }


# =================================================================
# API Endpoints
# =================================================================

@frappe.whitelist()
def calculate_shipping_cost(
    order_amount,
    total_weight=0,
    item_count=1,
    destination_country="Turkey",
    destination_city=None,
    postal_code=None,
    categories=None,
    express=False,
    seller=None
):
    """
    Calculate shipping cost for an order.

    Args:
        order_amount: Total order amount
        total_weight: Total weight in kg
        item_count: Number of items
        destination_country: Destination country
        destination_city: Destination city
        postal_code: Destination postal code
        categories: JSON array of category names
        express: Express delivery required
        seller: Seller profile name

    Returns:
        dict: Shipping calculation result
    """
    import json

    order_data = {
        "order_amount": flt(order_amount),
        "total_weight": flt(total_weight),
        "item_count": cint(item_count),
        "destination": {
            "country": destination_country or "Turkey",
            "city": destination_city or "",
            "postal_code": postal_code or ""
        },
        "categories": json.loads(categories) if isinstance(categories, str) else (categories or []),
        "express": cint(express)
    }

    # Get applicable shipping rules
    rules = get_applicable_shipping_rules(seller=seller)

    results = []
    for rule in rules:
        rule_doc = frappe.get_doc("Shipping Rule", rule.name)
        result = rule_doc.calculate_shipping(order_data)
        if result:
            results.append(result)

    if not results:
        return {
            "error": _("No shipping options available for this destination"),
            "options": []
        }

    # Sort by price (cheapest first)
    results.sort(key=lambda x: x["shipping_amount"])

    return {
        "options": results,
        "cheapest": results[0],
        "destination": order_data["destination"]
    }


@frappe.whitelist()
def get_applicable_shipping_rules(seller=None, destination_country="Turkey"):
    """
    Get all applicable shipping rules.

    Args:
        seller: Seller profile name
        destination_country: Destination country

    Returns:
        list: Applicable shipping rules
    """
    today = nowdate()

    filters = {
        "is_active": 1
    }

    or_filters = []

    # Get platform-wide rules and seller-specific rules
    if seller:
        or_filters = [
            {"seller": seller},
            {"seller": ["is", "not set"]}
        ]

    # Get rules
    rules = frappe.get_all(
        "Shipping Rule",
        filters=filters,
        or_filters=or_filters if or_filters else None,
        fields=["name", "rule_name", "rule_type", "priority", "seller",
                "base_rate", "currency", "estimated_days_min", "estimated_days_max",
                "free_shipping_enabled", "free_shipping_threshold",
                "express_available", "default_carrier"],
        order_by="priority DESC"
    )

    # Filter by validity period
    valid_rules = []
    for rule in rules:
        full_rule = frappe.get_doc("Shipping Rule", rule.name)

        if full_rule.valid_from and getdate(full_rule.valid_from) > getdate(today):
            continue
        if full_rule.valid_to and getdate(full_rule.valid_to) < getdate(today):
            continue

        valid_rules.append(rule)

    return valid_rules


@frappe.whitelist()
def get_shipping_rule(rule_name):
    """
    Get shipping rule details.

    Args:
        rule_name: Shipping Rule name

    Returns:
        dict: Shipping rule details
    """
    if not frappe.db.exists("Shipping Rule", rule_name):
        return {"error": _("Shipping Rule not found")}

    rule = frappe.get_doc("Shipping Rule", rule_name)
    return rule.get_summary()


@frappe.whitelist()
def get_seller_shipping_rules(seller):
    """
    Get shipping rules for a seller.

    Args:
        seller: Seller Profile name

    Returns:
        list: Seller's shipping rules
    """
    if not seller:
        return {"error": _("Seller is required")}

    rules = frappe.get_all(
        "Shipping Rule",
        filters={"seller": seller},
        fields=["name", "rule_name", "rule_type", "is_active", "priority",
                "base_rate", "currency", "free_shipping_enabled",
                "free_shipping_threshold", "default_carrier"],
        order_by="priority DESC"
    )

    return rules


@frappe.whitelist()
def create_shipping_rule(**kwargs):
    """
    Create a new shipping rule.

    Args:
        **kwargs: Shipping rule fields

    Returns:
        dict: Created shipping rule
    """
    # Validate required fields
    if not kwargs.get("rule_name"):
        frappe.throw(_("Rule Name is required"))

    if not kwargs.get("rule_type"):
        kwargs["rule_type"] = "Standard"

    # Check permission
    seller = kwargs.get("seller")
    if seller:
        seller_user = frappe.db.get_value("Seller Profile", seller, "user")
        if frappe.session.user != seller_user:
            if not frappe.has_permission("Shipping Rule", "create"):
                frappe.throw(_("Not permitted to create shipping rules"))

    rule = frappe.get_doc({
        "doctype": "Shipping Rule",
        **kwargs
    })
    rule.insert()

    return {
        "status": "success",
        "name": rule.name,
        "rule_name": rule.rule_name
    }


@frappe.whitelist()
def get_shipping_zones():
    """
    Get list of shipping zones/countries.

    Returns:
        list: Available shipping zones
    """
    # Try with is_active filter first, fall back if column doesn't exist
    try:
        zones = frappe.db.sql("""
            SELECT DISTINCT sz.country, sz.city
            FROM `tabShipping Zone` sz
            INNER JOIN `tabShipping Rule` sr ON sz.parent = sr.name
            WHERE sr.is_active = 1
            ORDER BY sz.country, sz.city
        """, as_dict=True)
        return zones
    except Exception as e:
        # Column might not exist, try without is_active filter
        if "is_active" in str(e).lower() or "Unknown column" in str(e):
            zones = frappe.db.sql("""
                SELECT DISTINCT sz.country, sz.city
                FROM `tabShipping Zone` sz
                INNER JOIN `tabShipping Rule` sr ON sz.parent = sr.name
                ORDER BY sz.country, sz.city
            """, as_dict=True)
            return zones
        else:
            # Re-raise if it's a different error
            raise


@frappe.whitelist()
def get_shipping_estimate(
    seller,
    destination_city,
    total_weight=0
):
    """
    Get shipping estimate for a seller's location.

    Args:
        seller: Seller Profile name
        destination_city: Destination city
        total_weight: Total weight in kg

    Returns:
        dict: Shipping estimate
    """
    rules = get_applicable_shipping_rules(seller=seller)

    estimates = []
    for rule in rules:
        rule_doc = frappe.get_doc("Shipping Rule", rule.name)

        # Check zone
        if not rule_doc.is_zone_applicable({
            "country": "Turkey",
            "city": destination_city
        }):
            continue

        est = rule_doc.get_delivery_estimate()
        estimates.append({
            "rule_name": rule.rule_name,
            "carrier": rule.default_carrier,
            "estimated_rate": rule.base_rate,
            "currency": rule.currency,
            "min_days": est["min_days"],
            "max_days": est["max_days"],
            "free_shipping_available": rule.free_shipping_enabled,
            "free_shipping_threshold": rule.free_shipping_threshold
        })

    return estimates

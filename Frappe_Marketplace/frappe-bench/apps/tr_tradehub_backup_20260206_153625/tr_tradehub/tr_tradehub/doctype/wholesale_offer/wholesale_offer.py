# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, now_datetime, getdate, get_datetime


class WholesaleOffer(Document):
    def before_insert(self):
        """Set defaults before inserting a new offer."""
        self.set_created_by()
        self.generate_offer_code()

    def validate(self):
        """Validate the wholesale offer."""
        self.validate_seller_tenant()
        self.validate_dates()
        self.validate_minimum_quantity()
        self.calculate_totals()
        self.update_status_based_on_dates()

    def before_save(self):
        """Before save hook."""
        self.set_published_at()

    def set_created_by(self):
        """Set the created_by field to the current user."""
        if not self.created_by:
            self.created_by = frappe.session.user

    def generate_offer_code(self):
        """Generate a unique offer code if not already set."""
        if not self.offer_code:
            # Generate offer code based on seller and timestamp
            import hashlib
            import time

            unique_string = f"{self.seller or ''}{time.time()}"
            hash_value = hashlib.md5(unique_string.encode()).hexdigest()[:8].upper()
            self.offer_code = f"WO-{hash_value}"

    def validate_seller_tenant(self):
        """Ensure tenant is populated from seller."""
        if self.seller and not self.tenant:
            seller_doc = frappe.get_doc("Seller Profile", self.seller)
            if seller_doc.tenant:
                self.tenant = seller_doc.tenant

    def validate_dates(self):
        """Validate that valid_until is after valid_from."""
        if self.valid_from and self.valid_until:
            if get_datetime(self.valid_until) <= get_datetime(self.valid_from):
                frappe.throw(
                    _("Valid Until date must be after Valid From date"),
                    title=_("Invalid Dates")
                )

    def validate_minimum_quantity(self):
        """Validate minimum quantity is positive."""
        if flt(self.minimum_quantity) <= 0:
            frappe.throw(
                _("Minimum Quantity must be greater than 0"),
                title=_("Invalid Minimum Quantity")
            )

    def calculate_totals(self):
        """Calculate totals from products child table."""
        total_products = 0
        total_quantity = 0.0
        total_value = 0.0

        if self.products:
            for product in self.products:
                total_products += 1
                total_quantity += flt(product.quantity)
                # Calculate product total_price
                product.total_price = flt(product.quantity) * flt(product.unit_price)
                total_value += flt(product.total_price)

        self.total_products = total_products
        self.total_quantity = total_quantity
        self.total_value = total_value

    def update_status_based_on_dates(self):
        """Update status based on validity dates if offer is active."""
        if self.status == "Active":
            current_time = now_datetime()
            valid_from = get_datetime(self.valid_from) if self.valid_from else None
            valid_until = get_datetime(self.valid_until) if self.valid_until else None

            if valid_until and current_time > valid_until:
                self.status = "Expired"
                self.is_active = 0
            elif valid_from and current_time < valid_from:
                # Offer not yet started, keep as Active but not active
                pass

    def set_published_at(self):
        """Set published_at when status changes to Active."""
        if self.status == "Active" and not self.published_at:
            self.published_at = now_datetime()


@frappe.whitelist()
def get_active_wholesale_offers(seller=None, buyer_level=None):
    """
    Get active wholesale offers, optionally filtered by seller and buyer level.

    Args:
        seller: Optional seller profile name to filter by
        buyer_level: Optional buyer level to check eligibility

    Returns:
        List of active wholesale offers
    """
    filters = {
        "status": "Active",
        "is_active": 1,
        "valid_from": ["<=", now_datetime()],
        "valid_until": [">=", now_datetime()]
    }

    if seller:
        filters["seller"] = seller

    offers = frappe.get_all(
        "Wholesale Offer",
        filters=filters,
        fields=[
            "name", "title", "offer_code", "seller", "seller_name",
            "description", "minimum_quantity", "minimum_order_value",
            "total_value", "valid_until", "pricing_type",
            "discount_percentage", "fixed_discount_amount"
        ],
        order_by="valid_until asc"
    )

    # Filter by buyer level if specified
    if buyer_level:
        filtered_offers = []
        for offer in offers:
            offer_doc = frappe.get_doc("Wholesale Offer", offer.name)
            if not offer_doc.target_buyer_levels:
                # No restriction, include offer
                filtered_offers.append(offer)
            elif buyer_level in offer_doc.target_buyer_levels:
                filtered_offers.append(offer)
        return filtered_offers

    return offers


@frappe.whitelist()
def get_wholesale_offer_products(offer_name):
    """
    Get products included in a wholesale offer.

    Args:
        offer_name: Name of the wholesale offer

    Returns:
        List of products with details
    """
    offer = frappe.get_doc("Wholesale Offer", offer_name)

    products = []
    for product in offer.products:
        products.append({
            "listing": product.listing,
            "listing_title": product.listing_title,
            "quantity": product.quantity,
            "unit_price": product.unit_price,
            "total_price": product.total_price
        })

    return products


@frappe.whitelist()
def check_offer_eligibility(offer_name, buyer=None, order_quantity=None, order_value=None):
    """
    Check if a buyer is eligible for a wholesale offer.

    Args:
        offer_name: Name of the wholesale offer
        buyer: Optional buyer user email
        order_quantity: Quantity to check against minimum
        order_value: Order value to check against minimum

    Returns:
        Dict with eligibility status and details
    """
    offer = frappe.get_doc("Wholesale Offer", offer_name)

    result = {
        "eligible": True,
        "reasons": []
    }

    # Check if offer is active
    if offer.status != "Active" or not offer.is_active:
        result["eligible"] = False
        result["reasons"].append(_("Offer is not currently active"))
        return result

    # Check validity period
    current_time = now_datetime()
    if get_datetime(offer.valid_from) > current_time:
        result["eligible"] = False
        result["reasons"].append(_("Offer has not started yet"))

    if get_datetime(offer.valid_until) < current_time:
        result["eligible"] = False
        result["reasons"].append(_("Offer has expired"))

    # Check usage limit
    if offer.usage_limit > 0 and offer.current_usage >= offer.usage_limit:
        result["eligible"] = False
        result["reasons"].append(_("Offer usage limit has been reached"))

    # Check minimum quantity
    if order_quantity and flt(order_quantity) < flt(offer.minimum_quantity):
        result["eligible"] = False
        result["reasons"].append(
            _("Order quantity ({0}) is below minimum required ({1})").format(
                order_quantity, offer.minimum_quantity
            )
        )

    # Check minimum order value
    if order_value and flt(offer.minimum_order_value) > 0:
        if flt(order_value) < flt(offer.minimum_order_value):
            result["eligible"] = False
            result["reasons"].append(
                _("Order value ({0}) is below minimum required ({1})").format(
                    order_value, offer.minimum_order_value
                )
            )

    # Check buyer level if specified
    if buyer and offer.target_buyer_levels:
        # Get buyer's level
        buyer_profile = frappe.db.get_value(
            "Premium Buyer",
            {"user": buyer},
            ["buyer_level"],
            as_dict=True
        )

        if buyer_profile and buyer_profile.buyer_level:
            if buyer_profile.buyer_level not in offer.target_buyer_levels:
                result["eligible"] = False
                result["reasons"].append(
                    _("Your buyer level is not eligible for this offer")
                )

    return result


@frappe.whitelist()
def increment_usage(offer_name):
    """
    Increment the usage count for a wholesale offer.

    Args:
        offer_name: Name of the wholesale offer
    """
    offer = frappe.get_doc("Wholesale Offer", offer_name)
    offer.current_usage = flt(offer.current_usage) + 1

    # Check if usage limit reached
    if offer.usage_limit > 0 and offer.current_usage >= offer.usage_limit:
        offer.status = "Completed"
        offer.is_active = 0

    offer.save(ignore_permissions=True)

    return {"success": True, "current_usage": offer.current_usage}


def get_permission_query_conditions(user):
    """
    Return permission query conditions for Wholesale Offer.
    Users can only see offers from their own tenant.
    """
    if "System Manager" in frappe.get_roles(user):
        return ""

    # Get user's tenant
    tenant = frappe.db.get_value(
        "Seller Profile",
        {"user": user},
        "tenant"
    )

    if tenant:
        return f"`tabWholesale Offer`.tenant = '{tenant}'"

    # Allow all users to see active offers (for buyers to browse)
    return "`tabWholesale Offer`.status = 'Active' AND `tabWholesale Offer`.is_active = 1"

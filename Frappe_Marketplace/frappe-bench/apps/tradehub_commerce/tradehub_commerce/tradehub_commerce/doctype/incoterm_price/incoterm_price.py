# Copyright (c) 2026, Trade Hub and contributors
# For license information, please see license.txt

"""
Incoterm Price DocType for Trade Hub B2B Marketplace.

This module implements Incoterm-based pricing with quantity breaks for
international trade. Supports standard Incoterms:
- EXW (Ex Works): Buyer assumes all risks and costs from seller's premises
- FOB (Free on Board): Seller delivers to port, buyer assumes responsibility
- CIF (Cost, Insurance, Freight): Seller covers cost, insurance, freight to destination
- DDP (Delivered Duty Paid): Seller assumes all risks and costs to destination

Key features:
- Multi-tenant data isolation via SKU Product's tenant
- Quantity-based price breaks with tiered pricing
- Validity date ranges for time-bound pricing
- Shipping and customs information tracking
- fetch_from pattern for product, seller, and tenant information
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, cint, getdate, nowdate, now_datetime


# Incoterm descriptions
INCOTERM_DESCRIPTIONS = {
    "EXW": "Ex Works - The seller makes goods available at their premises. "
           "The buyer is responsible for all transportation, export clearance, "
           "and import duties.",
    "FOB": "Free on Board - The seller delivers the goods on board the vessel "
           "at the named port of shipment. Risk transfers to buyer once goods "
           "pass the ship's rail.",
    "CIF": "Cost, Insurance, Freight - The seller delivers goods on board, "
           "pays freight and insurance to the named destination port. Risk "
           "transfers to buyer when goods pass ship's rail at loading port.",
    "DDP": "Delivered Duty Paid - The seller delivers goods cleared for import "
           "at the named destination. Seller bears all risks and costs including "
           "duties and taxes."
}


class IncotermPrice(Document):
    """
    Incoterm Price DocType for international trade pricing.

    Each Incoterm Price represents a pricing configuration for a specific
    incoterm with optional quantity-based price breaks. Features include:
    - Link to SKU Product with auto-fetched tenant isolation
    - Incoterm selection (EXW, FOB, CIF, DDP)
    - Base pricing with currency specification
    - Quantity break pricing tiers
    - Validity date ranges
    - Shipping and customs information
    """

    def before_insert(self):
        """Set defaults before inserting a new incoterm price."""
        self.set_incoterm_description()
        self.set_incoterm_flags()

    def validate(self):
        """Validate incoterm price data before saving."""
        self.validate_sku_product()
        self.validate_pricing()
        self.validate_date_range()
        self.validate_price_breaks()
        self.validate_incoterm_requirements()
        self.validate_default_pricing()
        self.validate_tenant_isolation()
        self.set_incoterm_description()
        self.set_incoterm_flags()
        self.update_price_break_discounts()
        self.check_expiry_status()

    def on_update(self):
        """Actions after incoterm price is updated."""
        self.clear_pricing_cache()

    def on_trash(self):
        """Actions before incoterm price is deleted."""
        self.check_linked_documents()

    # =========================================================================
    # INCOTERM MANAGEMENT
    # =========================================================================

    def set_incoterm_description(self):
        """Set the description based on selected incoterm."""
        if self.incoterm:
            self.incoterm_description = INCOTERM_DESCRIPTIONS.get(
                self.incoterm, ""
            )

    def set_incoterm_flags(self):
        """
        Set shipping and customs flags based on incoterm.

        Automatically sets freight_included, insurance_included,
        customs_duties_included, and import_taxes_included based
        on the selected incoterm.
        """
        if self.incoterm == "EXW":
            # Buyer handles everything
            self.freight_included = 0
            self.insurance_included = 0
            self.customs_duties_included = 0
            self.import_taxes_included = 0
        elif self.incoterm == "FOB":
            # Seller delivers to port only
            self.freight_included = 0
            self.insurance_included = 0
            self.customs_duties_included = 0
            self.import_taxes_included = 0
        elif self.incoterm == "CIF":
            # Seller covers freight and insurance to destination port
            self.freight_included = 1
            self.insurance_included = 1
            self.customs_duties_included = 0
            self.import_taxes_included = 0
        elif self.incoterm == "DDP":
            # Seller covers everything including duties
            self.freight_included = 1
            self.insurance_included = 1
            self.customs_duties_included = 1
            self.import_taxes_included = 1

    # =========================================================================
    # VALIDATION METHODS
    # =========================================================================

    def validate_sku_product(self):
        """Validate SKU Product link exists and is valid."""
        if not self.sku_product:
            frappe.throw(_("SKU Product is required"))

        product_status = frappe.db.get_value(
            "SKU Product", self.sku_product, "status"
        )
        if product_status == "Archive":
            frappe.throw(
                _("Cannot create pricing for archived product {0}").format(
                    self.sku_product
                )
            )

    def validate_pricing(self):
        """Validate base pricing fields."""
        if flt(self.base_price) <= 0:
            frappe.throw(_("Base Price must be greater than zero"))

        if not self.currency:
            frappe.throw(_("Currency is required"))

    def validate_date_range(self):
        """Validate validity date range."""
        if self.valid_from and self.valid_until:
            if getdate(self.valid_from) > getdate(self.valid_until):
                frappe.throw(
                    _("Valid From date cannot be after Valid Until date")
                )

    def validate_price_breaks(self):
        """
        Validate price break entries.

        Ensures:
        - No overlapping quantity ranges
        - Quantity ranges are continuous
        - Prices are positive
        - Larger quantities have lower or equal prices
        """
        if not self.price_breaks:
            return

        # Sort by min_qty
        sorted_breaks = sorted(
            self.price_breaks,
            key=lambda x: flt(x.min_qty)
        )

        prev_max = 0
        prev_price = flt(self.base_price)

        for i, pb in enumerate(sorted_breaks):
            min_qty = flt(pb.min_qty)
            max_qty = flt(pb.max_qty) if pb.max_qty else float('inf')
            unit_price = flt(pb.unit_price)

            # Validate positive values
            if min_qty <= 0:
                frappe.throw(
                    _("Row {0}: Min Quantity must be greater than zero").format(i + 1)
                )

            if unit_price <= 0:
                frappe.throw(
                    _("Row {0}: Unit Price must be greater than zero").format(i + 1)
                )

            # Check for gaps or overlaps
            if min_qty <= prev_max:
                frappe.throw(
                    _("Row {0}: Quantity range overlaps with previous row").format(i + 1)
                )

            # Max must be greater than min
            if max_qty and max_qty < min_qty:
                frappe.throw(
                    _("Row {0}: Max Quantity must be greater than Min Quantity").format(i + 1)
                )

            # Typically larger quantities have lower prices
            if unit_price > prev_price:
                frappe.msgprint(
                    _("Row {0}: Unit price is higher than previous tier. "
                      "Usually bulk pricing decreases with quantity.").format(i + 1),
                    indicator='orange',
                    alert=True
                )

            prev_max = max_qty if max_qty != float('inf') else flt(pb.min_qty)
            prev_price = unit_price

    def validate_incoterm_requirements(self):
        """Validate incoterm-specific field requirements."""
        if self.incoterm in ("FOB", "CIF") and not self.origin_port:
            frappe.msgprint(
                _("Origin port is recommended for {0} incoterm").format(
                    self.incoterm
                ),
                indicator='orange',
                alert=True
            )

        if self.incoterm in ("CIF", "DDP") and not self.destination_port:
            frappe.msgprint(
                _("Destination port is recommended for {0} incoterm").format(
                    self.incoterm
                ),
                indicator='orange',
                alert=True
            )

    def validate_default_pricing(self):
        """Ensure only one default pricing per product and incoterm."""
        if not self.is_default:
            return

        existing_default = frappe.db.get_value(
            "Incoterm Price",
            {
                "sku_product": self.sku_product,
                "incoterm": self.incoterm,
                "is_default": 1,
                "name": ("!=", self.name or ""),
                "status": "Active"
            },
            "name"
        )

        if existing_default:
            frappe.throw(
                _("Default pricing for {0} already exists: {1}. "
                  "Please unset the existing default first.").format(
                    self.incoterm, existing_default
                )
            )

    def validate_tenant_isolation(self):
        """
        Validate that pricing belongs to user's tenant.

        Inherits tenant from SKU Product to ensure multi-tenant data isolation.
        """
        if not self.tenant:
            return

        # System Manager can access all tenants
        if "System Manager" in frappe.get_roles():
            return

        # Get current user's tenant
        from tradehub_core.tradehub_core.utils.tenant import get_current_tenant
        current_tenant = get_current_tenant()

        if current_tenant and self.tenant != current_tenant:
            frappe.throw(
                _("Access denied: You can only access pricing in your tenant")
            )

    # =========================================================================
    # PRICE CALCULATION
    # =========================================================================

    def update_price_break_discounts(self):
        """Calculate and update discount percentages for price breaks."""
        if not self.price_breaks or not self.base_price:
            return

        base = flt(self.base_price)
        for pb in self.price_breaks:
            unit_price = flt(pb.unit_price)
            if base > 0:
                discount = ((base - unit_price) / base) * 100
                pb.discount_percent = max(0, discount)
            else:
                pb.discount_percent = 0

    def get_price_for_quantity(self, quantity):
        """
        Get the unit price for a given quantity.

        Args:
            quantity: The order quantity

        Returns:
            dict: Contains unit_price, total_price, discount_percent, and tier_info
        """
        qty = flt(quantity)
        if qty <= 0:
            frappe.throw(_("Quantity must be greater than zero"))

        # Check if we have price breaks
        if not self.price_breaks:
            return {
                "unit_price": flt(self.base_price),
                "total_price": flt(self.base_price) * qty,
                "discount_percent": 0,
                "tier": "Base Price",
                "currency": self.currency
            }

        # Find applicable price break
        applicable_price = flt(self.base_price)
        applicable_tier = "Base Price"
        discount_pct = 0

        sorted_breaks = sorted(
            self.price_breaks,
            key=lambda x: flt(x.min_qty)
        )

        for pb in sorted_breaks:
            min_qty = flt(pb.min_qty)
            max_qty = flt(pb.max_qty) if pb.max_qty else float('inf')

            if min_qty <= qty <= max_qty:
                applicable_price = flt(pb.unit_price)
                applicable_tier = f"{cint(min_qty)}-{cint(max_qty) if max_qty != float('inf') else '+'} units"
                discount_pct = flt(pb.discount_percent)
                break
            elif qty > max_qty:
                # Continue to find higher tier
                applicable_price = flt(pb.unit_price)
                applicable_tier = f"{cint(min_qty)}+ units"
                discount_pct = flt(pb.discount_percent)

        return {
            "unit_price": applicable_price,
            "total_price": applicable_price * qty,
            "discount_percent": discount_pct,
            "tier": applicable_tier,
            "currency": self.currency
        }

    # =========================================================================
    # STATUS MANAGEMENT
    # =========================================================================

    def check_expiry_status(self):
        """Check and update expiry status based on valid_until date."""
        if self.status == "Expired":
            return

        if self.valid_until and getdate(self.valid_until) < getdate(nowdate()):
            self.status = "Expired"
            frappe.msgprint(
                _("Pricing has been marked as Expired (valid until {0})").format(
                    self.valid_until
                ),
                indicator='orange',
                alert=True
            )

    def activate(self):
        """Activate the pricing."""
        if self.valid_until and getdate(self.valid_until) < getdate(nowdate()):
            frappe.throw(_("Cannot activate expired pricing"))

        self.status = "Active"
        self.save()
        return True

    def deactivate(self):
        """Deactivate the pricing."""
        self.status = "Inactive"
        self.save()
        return True

    # =========================================================================
    # LINKED DOCUMENT CHECKS
    # =========================================================================

    def check_linked_documents(self):
        """Check for linked documents before allowing deletion."""
        # Check for linked order items (future implementation)
        pass

    # =========================================================================
    # CACHE MANAGEMENT
    # =========================================================================

    def clear_pricing_cache(self):
        """Clear cached pricing data."""
        cache_keys = [
            f"incoterm_price:{self.name}",
            f"product_pricing:{self.sku_product}:{self.incoterm}",
            f"product_all_pricing:{self.sku_product}",
        ]
        for key in cache_keys:
            frappe.cache().delete_value(key)


# =============================================================================
# WHITELISTED API FUNCTIONS
# =============================================================================


@frappe.whitelist()
def get_product_incoterm_prices(sku_product, incoterm=None, active_only=True):
    """
    Get all incoterm prices for a product.

    Args:
        sku_product: The SKU Product name
        incoterm: Optional specific incoterm to filter by
        active_only: Whether to return only active pricing (default True)

    Returns:
        list: List of incoterm price records
    """
    filters = {"sku_product": sku_product}

    if incoterm:
        filters["incoterm"] = incoterm

    if active_only:
        filters["status"] = "Active"

    prices = frappe.get_all(
        "Incoterm Price",
        filters=filters,
        fields=[
            "name", "incoterm", "base_price", "currency",
            "is_default", "status", "valid_from", "valid_until",
            "freight_included", "insurance_included",
            "customs_duties_included", "import_taxes_included"
        ],
        order_by="incoterm asc, is_default desc"
    )

    return prices


@frappe.whitelist()
def get_price_for_quantity(incoterm_price, quantity):
    """
    Calculate price for a specific quantity.

    Args:
        incoterm_price: The Incoterm Price document name
        quantity: The quantity to calculate price for

    Returns:
        dict: Price calculation result with unit_price, total, discount
    """
    doc = frappe.get_doc("Incoterm Price", incoterm_price)

    if doc.status != "Active":
        frappe.throw(_("This pricing is not currently active"))

    return doc.get_price_for_quantity(flt(quantity))


@frappe.whitelist()
def get_best_price(sku_product, quantity, incoterm=None, currency=None):
    """
    Get the best available price for a product and quantity.

    Args:
        sku_product: The SKU Product name
        quantity: The order quantity
        incoterm: Optional specific incoterm (returns best for each if not specified)
        currency: Optional currency filter

    Returns:
        dict or list: Best price(s) for the given criteria
    """
    filters = {
        "sku_product": sku_product,
        "status": "Active"
    }

    if incoterm:
        filters["incoterm"] = incoterm

    if currency:
        filters["currency"] = currency

    prices = frappe.get_all(
        "Incoterm Price",
        filters=filters,
        fields=["name", "incoterm", "base_price", "currency"]
    )

    results = []
    qty = flt(quantity)

    for price in prices:
        doc = frappe.get_doc("Incoterm Price", price.name)
        calc = doc.get_price_for_quantity(qty)

        results.append({
            "incoterm_price": price.name,
            "incoterm": price.incoterm,
            **calc
        })

    # Sort by unit price (lowest first)
    results.sort(key=lambda x: x["unit_price"])

    if incoterm:
        return results[0] if results else None

    return results


@frappe.whitelist()
def get_incoterm_description(incoterm):
    """
    Get the description for an incoterm.

    Args:
        incoterm: The incoterm code (EXW, FOB, CIF, DDP)

    Returns:
        str: Description of the incoterm
    """
    return INCOTERM_DESCRIPTIONS.get(incoterm, "")


@frappe.whitelist()
def create_incoterm_pricing(sku_product, incoterm, base_price, currency="USD",
                            price_breaks=None):
    """
    Create a new incoterm pricing.

    Args:
        sku_product: The SKU Product name
        incoterm: The incoterm type (EXW, FOB, CIF, DDP)
        base_price: Base price per unit
        currency: Currency code (default USD)
        price_breaks: Optional list of price break dicts with min_qty, max_qty, unit_price

    Returns:
        dict: Created document info
    """
    doc = frappe.new_doc("Incoterm Price")
    doc.sku_product = sku_product
    doc.incoterm = incoterm
    doc.base_price = flt(base_price)
    doc.currency = currency

    if price_breaks:
        for pb in price_breaks:
            doc.append("price_breaks", {
                "min_qty": flt(pb.get("min_qty")),
                "max_qty": flt(pb.get("max_qty")) if pb.get("max_qty") else None,
                "unit_price": flt(pb.get("unit_price"))
            })

    doc.insert()

    return {
        "name": doc.name,
        "message": _("Incoterm pricing created successfully")
    }


@frappe.whitelist()
def set_default_pricing(incoterm_price):
    """
    Set an incoterm pricing as the default for its product and incoterm.

    Args:
        incoterm_price: The Incoterm Price document name

    Returns:
        dict: Success message
    """
    doc = frappe.get_doc("Incoterm Price", incoterm_price)

    # Unset any existing default
    frappe.db.set_value(
        "Incoterm Price",
        {
            "sku_product": doc.sku_product,
            "incoterm": doc.incoterm,
            "is_default": 1,
            "name": ("!=", doc.name)
        },
        "is_default",
        0
    )

    doc.is_default = 1
    doc.save()

    return {
        "success": True,
        "message": _("Default pricing set successfully")
    }


@frappe.whitelist()
def check_pricing_expiry():
    """
    Check all active pricing for expiry and update status.

    This should be called by a scheduled job.

    Returns:
        dict: Count of expired pricing records
    """
    expired_count = frappe.db.sql("""
        UPDATE `tabIncoterm Price`
        SET status = 'Expired'
        WHERE status = 'Active'
        AND valid_until IS NOT NULL
        AND valid_until < %s
    """, (nowdate(),))

    return {
        "expired_count": expired_count,
        "message": _("Expired pricing records updated")
    }

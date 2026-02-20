# Copyright (c) 2026, Trade Hub and contributors
# For license information, please see license.txt

"""
Lead Time DocType for Trade Hub B2B Marketplace.

This module implements lead time management for production and delivery scheduling.
Lead times are essential for B2B transactions where buyers need to know:
- How long production will take
- How long delivery will take
- Combined production + delivery time
- Capacity constraints that affect lead times

Key features:
- Multi-tenant data isolation via SKU Product's tenant
- Different lead time types (Production, Delivery, Combined, Custom)
- Quantity-based lead time configurations
- Production capacity tracking
- Regional lead time variations
- Validity date ranges for seasonal/promotional periods
- fetch_from pattern for product, seller, and tenant information
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, cint, getdate, nowdate, now_datetime


# Lead time type descriptions
LEAD_TIME_TYPE_DESCRIPTIONS = {
    "Production": "Time required to manufacture/produce the goods",
    "Delivery": "Time required for shipping/transportation only",
    "Production + Delivery": "Combined time for production and shipping",
    "Custom": "Custom lead time configuration for special requirements"
}


class LeadTime(Document):
    """
    Lead Time DocType for production and delivery scheduling.

    Each Lead Time represents a time configuration for a specific product,
    allowing sellers to define how long it takes to produce and/or deliver
    their products. Features include:
    - Link to SKU Product with auto-fetched tenant isolation
    - Lead time type selection (Production, Delivery, Combined, Custom)
    - Quantity-based configurations (different lead times for different quantities)
    - Production capacity constraints
    - Regional applicability
    - Validity date ranges
    - Priority-based selection when multiple lead times apply
    """

    def before_insert(self):
        """Set defaults before inserting a new lead time."""
        self.set_default_priority()

    def validate(self):
        """Validate lead time data before saving."""
        self.validate_sku_product()
        self.validate_lead_time_days()
        self.validate_quantity_range()
        self.validate_production_capacity()
        self.validate_date_range()
        self.validate_default_lead_time()
        self.validate_tenant_isolation()
        self.check_expiry_status()

    def on_update(self):
        """Actions after lead time is updated."""
        self.clear_lead_time_cache()

    def on_trash(self):
        """Actions before lead time is deleted."""
        self.check_linked_documents()

    # =========================================================================
    # DEFAULT SETTINGS
    # =========================================================================

    def set_default_priority(self):
        """Set default priority based on existing lead times for the product."""
        if self.priority:
            return

        # Get max priority for this product
        max_priority = frappe.db.get_value(
            "Lead Time",
            {"sku_product": self.sku_product},
            "MAX(priority)"
        )

        self.priority = cint(max_priority) + 1 if max_priority else 1

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
                _("Cannot create lead time for archived product {0}").format(
                    self.sku_product
                )
            )

    def validate_lead_time_days(self):
        """Validate lead time days is a positive value."""
        if cint(self.lead_time_days) <= 0:
            frappe.throw(_("Lead Time Days must be greater than zero"))

        # Warn for unusually long lead times
        if cint(self.lead_time_days) > 180:
            frappe.msgprint(
                _("Lead time of {0} days is unusually long. "
                  "Please verify this is correct.").format(self.lead_time_days),
                indicator='orange',
                alert=True
            )

    def validate_quantity_range(self):
        """Validate min/max order quantity range."""
        min_qty = flt(self.min_order_quantity)
        max_qty = flt(self.max_order_quantity)

        if min_qty < 0:
            frappe.throw(_("Min Order Quantity cannot be negative"))

        if min_qty == 0:
            self.min_order_quantity = 1

        if max_qty > 0 and max_qty < min_qty:
            frappe.throw(
                _("Max Order Quantity cannot be less than Min Order Quantity")
            )

    def validate_production_capacity(self):
        """Validate production capacity is reasonable."""
        if self.production_capacity and cint(self.production_capacity) < 0:
            frappe.throw(_("Production Capacity cannot be negative"))

        if self.production_capacity and cint(self.production_capacity) > 0:
            if not self.capacity_period:
                self.capacity_period = "Month"

    def validate_date_range(self):
        """Validate validity date range."""
        if self.valid_from and self.valid_until:
            if getdate(self.valid_from) > getdate(self.valid_until):
                frappe.throw(
                    _("Valid From date cannot be after Valid Until date")
                )

    def validate_default_lead_time(self):
        """Ensure only one default lead time per product."""
        if not self.is_default:
            return

        existing_default = frappe.db.get_value(
            "Lead Time",
            {
                "sku_product": self.sku_product,
                "is_default": 1,
                "name": ("!=", self.name or ""),
                "status": "Active"
            },
            "name"
        )

        if existing_default:
            frappe.throw(
                _("Default lead time already exists for this product: {0}. "
                  "Please unset the existing default first.").format(
                    existing_default
                )
            )

    def validate_tenant_isolation(self):
        """
        Validate that lead time belongs to user's tenant.

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
                _("Access denied: You can only access lead times in your tenant")
            )

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
                _("Lead time has been marked as Expired (valid until {0})").format(
                    self.valid_until
                ),
                indicator='orange',
                alert=True
            )

    def activate(self):
        """Activate the lead time."""
        if self.valid_until and getdate(self.valid_until) < getdate(nowdate()):
            frappe.throw(_("Cannot activate expired lead time"))

        self.status = "Active"
        self.save()
        return True

    def deactivate(self):
        """Deactivate the lead time."""
        self.status = "Inactive"
        self.save()
        return True

    # =========================================================================
    # LEAD TIME CALCULATION
    # =========================================================================

    def get_lead_time_for_quantity(self, quantity, region=None):
        """
        Check if this lead time configuration applies to a given quantity.

        Args:
            quantity: The order quantity
            region: Optional region code to check applicability

        Returns:
            dict: Lead time details if applicable, None otherwise
        """
        qty = flt(quantity)

        # Check quantity range
        min_qty = flt(self.min_order_quantity) or 1
        max_qty = flt(self.max_order_quantity) or float('inf')

        if not (min_qty <= qty <= max_qty):
            return None

        # Check region applicability
        if region and self.applies_to_region:
            regions = [r.strip().upper() for r in self.applies_to_region.split(',')]
            if region.upper() not in regions:
                return None

        # Check validity dates
        today = getdate(nowdate())
        if self.valid_from and getdate(self.valid_from) > today:
            return None
        if self.valid_until and getdate(self.valid_until) < today:
            return None

        return {
            "lead_time_days": cint(self.lead_time_days),
            "lead_time_type": self.lead_time_type,
            "production_capacity": cint(self.production_capacity) or None,
            "capacity_period": self.capacity_period,
            "priority": cint(self.priority),
            "notes": self.notes
        }

    def can_fulfill_order(self, quantity):
        """
        Check if an order of given quantity can be fulfilled within capacity.

        Args:
            quantity: The order quantity

        Returns:
            dict: Fulfillment status with details
        """
        qty = flt(quantity)

        if not self.production_capacity:
            return {
                "can_fulfill": True,
                "message": _("No capacity constraint defined"),
                "estimated_lead_time_days": cint(self.lead_time_days)
            }

        capacity = cint(self.production_capacity)

        if qty <= capacity:
            return {
                "can_fulfill": True,
                "message": _("Order can be fulfilled within normal lead time"),
                "estimated_lead_time_days": cint(self.lead_time_days)
            }

        # Calculate extended lead time for larger orders
        periods_needed = (qty + capacity - 1) // capacity  # Ceiling division
        extended_days = cint(self.lead_time_days) * periods_needed

        return {
            "can_fulfill": True,
            "message": _("Order exceeds single period capacity, requires extended lead time"),
            "estimated_lead_time_days": extended_days,
            "periods_needed": periods_needed,
            "capacity_per_period": capacity,
            "capacity_period": self.capacity_period
        }

    # =========================================================================
    # LINKED DOCUMENT CHECKS
    # =========================================================================

    def check_linked_documents(self):
        """Check for linked documents before allowing deletion."""
        # Future: Check for linked orders or quotes
        pass

    # =========================================================================
    # CACHE MANAGEMENT
    # =========================================================================

    def clear_lead_time_cache(self):
        """Clear cached lead time data."""
        cache_keys = [
            f"lead_time:{self.name}",
            f"product_lead_times:{self.sku_product}",
            f"product_default_lead_time:{self.sku_product}",
        ]
        for key in cache_keys:
            frappe.cache().delete_value(key)


# =============================================================================
# WHITELISTED API FUNCTIONS
# =============================================================================


@frappe.whitelist()
def get_product_lead_times(sku_product, active_only=True):
    """
    Get all lead time configurations for a product.

    Args:
        sku_product: The SKU Product name
        active_only: Whether to return only active lead times (default True)

    Returns:
        list: List of lead time records sorted by priority
    """
    filters = {"sku_product": sku_product}

    if active_only:
        filters["status"] = "Active"

    lead_times = frappe.get_all(
        "Lead Time",
        filters=filters,
        fields=[
            "name", "lead_time_type", "lead_time_days", "status",
            "is_default", "min_order_quantity", "max_order_quantity",
            "production_capacity", "capacity_period", "priority",
            "valid_from", "valid_until", "applies_to_region"
        ],
        order_by="priority asc, is_default desc"
    )

    return lead_times


@frappe.whitelist()
def get_lead_time_for_order(sku_product, quantity, region=None):
    """
    Get the applicable lead time for a specific order.

    Args:
        sku_product: The SKU Product name
        quantity: The order quantity
        region: Optional region code for region-specific lead times

    Returns:
        dict: Applicable lead time details or default product lead time
    """
    qty = flt(quantity)

    # Get all active lead times for the product, sorted by priority
    lead_times = frappe.get_all(
        "Lead Time",
        filters={
            "sku_product": sku_product,
            "status": "Active"
        },
        fields=["name"],
        order_by="priority asc, is_default desc"
    )

    # Find the first applicable lead time
    for lt in lead_times:
        doc = frappe.get_doc("Lead Time", lt.name)
        result = doc.get_lead_time_for_quantity(qty, region)
        if result:
            result["lead_time_name"] = lt.name
            return result

    # Fallback to product's default lead time
    default_days = frappe.db.get_value(
        "SKU Product", sku_product, "lead_time_days"
    )

    if default_days:
        return {
            "lead_time_days": cint(default_days),
            "lead_time_type": "Production",
            "lead_time_name": None,
            "is_product_default": True
        }

    # Ultimate fallback
    return {
        "lead_time_days": 7,
        "lead_time_type": "Production",
        "lead_time_name": None,
        "is_system_default": True
    }


@frappe.whitelist()
def get_default_lead_time(sku_product):
    """
    Get the default lead time for a product.

    Args:
        sku_product: The SKU Product name

    Returns:
        dict: Default lead time details
    """
    # First try to find a marked default
    default_lt = frappe.db.get_value(
        "Lead Time",
        {
            "sku_product": sku_product,
            "is_default": 1,
            "status": "Active"
        },
        ["name", "lead_time_days", "lead_time_type"],
        as_dict=True
    )

    if default_lt:
        return default_lt

    # Return the highest priority active lead time
    lead_times = frappe.get_all(
        "Lead Time",
        filters={
            "sku_product": sku_product,
            "status": "Active"
        },
        fields=["name", "lead_time_days", "lead_time_type"],
        order_by="priority asc",
        limit=1
    )

    if lead_times:
        return lead_times[0]

    # Fallback to product's lead_time_days field
    product_lead_time = frappe.db.get_value(
        "SKU Product", sku_product, "lead_time_days"
    )

    return {
        "name": None,
        "lead_time_days": cint(product_lead_time) or 7,
        "lead_time_type": "Production",
        "is_product_default": True
    }


@frappe.whitelist()
def create_lead_time(sku_product, lead_time_days, lead_time_type="Production",
                     min_order_quantity=1, max_order_quantity=None,
                     production_capacity=None, capacity_period="Month",
                     is_default=False):
    """
    Create a new lead time configuration.

    Args:
        sku_product: The SKU Product name
        lead_time_days: Number of days for lead time
        lead_time_type: Type of lead time (default Production)
        min_order_quantity: Minimum quantity for this lead time
        max_order_quantity: Maximum quantity (None = unlimited)
        production_capacity: Production capacity per period
        capacity_period: Period for capacity (Day/Week/Month)
        is_default: Whether this is the default lead time

    Returns:
        dict: Created document info
    """
    doc = frappe.new_doc("Lead Time")
    doc.sku_product = sku_product
    doc.lead_time_days = cint(lead_time_days)
    doc.lead_time_type = lead_time_type
    doc.min_order_quantity = flt(min_order_quantity) or 1
    doc.max_order_quantity = flt(max_order_quantity) if max_order_quantity else None
    doc.production_capacity = cint(production_capacity) if production_capacity else None
    doc.capacity_period = capacity_period
    doc.is_default = 1 if is_default else 0

    doc.insert()

    return {
        "name": doc.name,
        "message": _("Lead time created successfully")
    }


@frappe.whitelist()
def set_default_lead_time(lead_time):
    """
    Set a lead time as the default for its product.

    Args:
        lead_time: The Lead Time document name

    Returns:
        dict: Success message
    """
    doc = frappe.get_doc("Lead Time", lead_time)

    # Unset any existing default
    frappe.db.set_value(
        "Lead Time",
        {
            "sku_product": doc.sku_product,
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
        "message": _("Default lead time set successfully")
    }


@frappe.whitelist()
def check_lead_time_expiry():
    """
    Check all active lead times for expiry and update status.

    This should be called by a scheduled job.

    Returns:
        dict: Count of expired lead time records
    """
    expired_count = frappe.db.sql("""
        UPDATE `tabLead Time`
        SET status = 'Expired'
        WHERE status = 'Active'
        AND valid_until IS NOT NULL
        AND valid_until < %s
    """, (nowdate(),))

    return {
        "expired_count": expired_count,
        "message": _("Expired lead time records updated")
    }


@frappe.whitelist()
def calculate_delivery_date(sku_product, quantity, order_date=None, region=None):
    """
    Calculate the estimated delivery date for an order.

    Args:
        sku_product: The SKU Product name
        quantity: The order quantity
        order_date: Order date (default today)
        region: Optional region code

    Returns:
        dict: Delivery date calculation with details
    """
    from frappe.utils import add_days

    if not order_date:
        order_date = nowdate()

    # Get applicable lead time
    lead_time_info = get_lead_time_for_order(sku_product, quantity, region)
    lead_days = cint(lead_time_info.get("lead_time_days", 7))

    # Calculate delivery date
    delivery_date = add_days(getdate(order_date), lead_days)

    return {
        "order_date": order_date,
        "lead_time_days": lead_days,
        "estimated_delivery_date": str(delivery_date),
        "lead_time_type": lead_time_info.get("lead_time_type"),
        "lead_time_name": lead_time_info.get("lead_time_name"),
        "notes": lead_time_info.get("notes")
    }


@frappe.whitelist()
def get_lead_time_type_description(lead_time_type):
    """
    Get the description for a lead time type.

    Args:
        lead_time_type: The lead time type (Production, Delivery, etc.)

    Returns:
        str: Description of the lead time type
    """
    return LEAD_TIME_TYPE_DESCRIPTIONS.get(lead_time_type, "")

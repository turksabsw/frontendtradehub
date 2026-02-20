# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime, getdate, get_datetime


class Coupon(Document):
    def before_save(self):
        """Prepare coupon before saving"""
        self.normalize_coupon_code()
        self.populate_tenant_from_seller()
        self.update_status()

    def validate(self):
        """Validation rules for coupon"""
        self.validate_coupon_code()
        self.validate_discount_value()
        self.validate_dates()
        self.validate_usage_limits()
        self.validate_min_order_amount()
        self.validate_seller_tenant_consistency()

    def normalize_coupon_code(self):
        """Normalize coupon code to uppercase"""
        if self.coupon_code:
            self.coupon_code = self.coupon_code.strip().upper()

    def populate_tenant_from_seller(self):
        """Fetch tenant from seller profile and set it on this document"""
        if self.seller and not self.tenant:
            tenant = frappe.db.get_value("Seller Profile", self.seller, "tenant")
            if tenant:
                self.tenant = tenant

        # Also fetch seller_name if not set
        if self.seller and not self.seller_name:
            seller_name = frappe.db.get_value("Seller Profile", self.seller, "seller_name")
            if seller_name:
                self.seller_name = seller_name

    def validate_coupon_code(self):
        """Validate coupon code format"""
        if not self.coupon_code:
            frappe.throw(_("Coupon Code is required"))

        # Check minimum length
        if len(self.coupon_code) < 3:
            frappe.throw(_("Coupon Code must be at least 3 characters long"))

        # Check maximum length
        if len(self.coupon_code) > 50:
            frappe.throw(_("Coupon Code cannot exceed 50 characters"))

        # Alphanumeric and common characters only
        import re
        if not re.match(r'^[A-Z0-9_\-]+$', self.coupon_code):
            frappe.throw(
                _("Coupon Code can only contain uppercase letters, numbers, underscores, and hyphens")
            )

    def validate_discount_value(self):
        """Validate discount value based on discount type"""
        if self.discount_value is None:
            frappe.throw(_("Discount Value is required"))

        if self.discount_type == "Free Shipping":
            # Free shipping doesn't need a discount value
            return

        if self.discount_value <= 0:
            frappe.throw(_("Discount Value must be greater than 0"))

        if self.discount_type == "Percentage":
            if self.discount_value > 100:
                frappe.throw(_("Percentage discount cannot exceed 100%"))
            if self.discount_value < 0.01:
                frappe.throw(_("Percentage discount must be at least 0.01%"))

        if self.discount_type == "Fixed Amount":
            if self.discount_value < 0.01:
                frappe.throw(_("Fixed discount amount must be at least 0.01"))

    def validate_dates(self):
        """Validate date range"""
        if not self.valid_from or not self.valid_until:
            frappe.throw(_("Both Valid From and Valid Until dates are required"))

        valid_from = get_datetime(self.valid_from)
        valid_until = get_datetime(self.valid_until)

        if valid_until <= valid_from:
            frappe.throw(_("Valid Until must be after Valid From"))

        # Warn if coupon is already expired (but don't block)
        if valid_until < now_datetime():
            frappe.msgprint(
                _("Warning: This coupon has already expired"),
                indicator="orange"
            )

    def validate_usage_limits(self):
        """Validate usage limit settings"""
        if self.usage_limit and self.usage_limit < 0:
            frappe.throw(_("Usage Limit cannot be negative"))

        if self.usage_per_customer and self.usage_per_customer < 0:
            frappe.throw(_("Usage Per Customer cannot be negative"))

        if self.max_uses_per_order and self.max_uses_per_order < 1:
            frappe.throw(_("Max Uses Per Order must be at least 1"))

        # Check if used count exceeds limit
        if self.usage_limit and self.used_count and self.used_count >= self.usage_limit:
            frappe.msgprint(
                _("Warning: This coupon has reached its usage limit"),
                indicator="orange"
            )

    def validate_min_order_amount(self):
        """Validate minimum order amount"""
        if self.min_order_amount and self.min_order_amount < 0:
            frappe.throw(_("Minimum Order Amount cannot be negative"))

        # Validate max_discount_amount for percentage discounts
        if self.discount_type == "Percentage" and self.max_discount_amount:
            if self.max_discount_amount < 0:
                frappe.throw(_("Max Discount Amount cannot be negative"))

    def validate_seller_tenant_consistency(self):
        """Ensure tenant matches seller's tenant"""
        if self.seller and self.tenant:
            seller_tenant = frappe.db.get_value("Seller Profile", self.seller, "tenant")
            if seller_tenant and seller_tenant != self.tenant:
                frappe.throw(
                    _("Tenant '{0}' does not match the seller's tenant '{1}'").format(
                        self.tenant, seller_tenant
                    )
                )

    def update_status(self):
        """Automatically update status based on current state"""
        current_time = now_datetime()
        valid_from = get_datetime(self.valid_from) if self.valid_from else None
        valid_until = get_datetime(self.valid_until) if self.valid_until else None

        # If manually deactivated
        if not self.is_active:
            self.status = "Deactivated"
            return

        # Check if expired
        if valid_until and current_time > valid_until:
            self.status = "Expired"
            return

        # Check if usage limit reached
        if self.usage_limit and self.used_count and self.used_count >= self.usage_limit:
            self.status = "Used Up"
            return

        # Check if not yet started
        if valid_from and current_time < valid_from:
            self.status = "Draft"
            return

        # Otherwise it's active
        self.status = "Active"

    def increment_usage(self):
        """Increment the usage counter. Call this when coupon is applied to an order."""
        self.used_count = (self.used_count or 0) + 1
        self.update_status()
        self.db_update()

    def is_valid_for_use(self, buyer=None, order_amount=0, cart_items=None):
        """
        Check if coupon is valid for use.

        Args:
            buyer: Buyer Profile name or User name
            order_amount: Total order amount
            cart_items: List of cart items for product/category checks

        Returns:
            tuple: (is_valid, error_message)
        """
        current_time = now_datetime()
        valid_from = get_datetime(self.valid_from) if self.valid_from else None
        valid_until = get_datetime(self.valid_until) if self.valid_until else None

        # Check if active
        if not self.is_active:
            return False, _("This coupon is not active")

        # Check validity period
        if valid_from and current_time < valid_from:
            return False, _("This coupon is not yet valid")

        if valid_until and current_time > valid_until:
            return False, _("This coupon has expired")

        # Check usage limit
        if self.usage_limit and self.used_count and self.used_count >= self.usage_limit:
            return False, _("This coupon has reached its usage limit")

        # Check minimum order amount
        if self.min_order_amount and order_amount < self.min_order_amount:
            return False, _("Minimum order amount of {0} required").format(self.min_order_amount)

        # Check per-customer usage limit
        if buyer and self.usage_per_customer:
            customer_usage = self.get_customer_usage_count(buyer)
            if customer_usage >= self.usage_per_customer:
                return False, _("You have already used this coupon the maximum allowed times")

        # Check new customers only restriction
        if self.new_customers_only and buyer:
            if not self.is_new_customer(buyer):
                return False, _("This coupon is only valid for new customers")

        # Check minimum items requirement
        if self.requires_minimum_items and cart_items:
            item_count = len(cart_items) if cart_items else 0
            if item_count < (self.minimum_items or 1):
                return False, _("Minimum {0} items required in cart").format(self.minimum_items)

        return True, None

    def get_customer_usage_count(self, buyer):
        """Get how many times a customer has used this coupon"""
        # This would typically query the order/coupon usage log
        # Placeholder implementation - should be connected to actual order records
        return frappe.db.count(
            "Marketplace Order",
            filters={
                "buyer": buyer,
                "coupon_code": self.coupon_code,
                "docstatus": ["!=", 2]
            }
        ) if frappe.db.exists("DocType", "Marketplace Order") else 0

    def is_new_customer(self, buyer):
        """Check if buyer is a new customer (no previous orders)"""
        # Check if buyer has any completed orders
        if frappe.db.exists("DocType", "Marketplace Order"):
            order_count = frappe.db.count(
                "Marketplace Order",
                filters={
                    "buyer": buyer,
                    "docstatus": 1
                }
            )
            return order_count == 0
        return True

    def calculate_discount(self, order_amount, applicable_amount=None):
        """
        Calculate discount amount for a given order.

        Args:
            order_amount: Total order amount
            applicable_amount: Amount of items this coupon applies to (for partial discounts)

        Returns:
            float: Discount amount
        """
        if not applicable_amount:
            applicable_amount = order_amount

        if self.discount_type == "Percentage":
            discount = applicable_amount * (self.discount_value / 100)
            # Apply max discount cap if set
            if self.max_discount_amount and discount > self.max_discount_amount:
                discount = self.max_discount_amount
            return discount

        elif self.discount_type == "Fixed Amount":
            # Don't discount more than the applicable amount
            return min(self.discount_value, applicable_amount)

        elif self.discount_type == "Free Shipping":
            # Return 0 as discount - shipping is handled separately
            return 0

        return 0


@frappe.whitelist()
def validate_coupon_code(coupon_code, buyer=None, order_amount=0):
    """
    API endpoint to validate a coupon code.

    Args:
        coupon_code: The coupon code to validate
        buyer: Optional buyer profile/user
        order_amount: Optional order amount for minimum order check

    Returns:
        dict: Validation result with coupon details
    """
    if not coupon_code:
        return {"valid": False, "message": _("Coupon code is required")}

    coupon_code = coupon_code.strip().upper()

    if not frappe.db.exists("Coupon", coupon_code):
        return {"valid": False, "message": _("Invalid coupon code")}

    coupon = frappe.get_doc("Coupon", coupon_code)
    is_valid, error_message = coupon.is_valid_for_use(
        buyer=buyer,
        order_amount=float(order_amount) if order_amount else 0
    )

    if is_valid:
        return {
            "valid": True,
            "coupon_code": coupon.coupon_code,
            "title": coupon.title,
            "discount_type": coupon.discount_type,
            "discount_value": coupon.discount_value,
            "min_order_amount": coupon.min_order_amount,
            "max_discount_amount": coupon.max_discount_amount,
            "description": coupon.description
        }
    else:
        return {"valid": False, "message": error_message}


@frappe.whitelist()
def apply_coupon_to_order(coupon_code, order_name):
    """
    Apply a coupon to an order and increment usage.

    Args:
        coupon_code: The coupon code to apply
        order_name: The order to apply the coupon to

    Returns:
        dict: Result with discount amount
    """
    if not coupon_code or not order_name:
        return {"success": False, "message": _("Coupon code and order name are required")}

    coupon_code = coupon_code.strip().upper()

    if not frappe.db.exists("Coupon", coupon_code):
        return {"success": False, "message": _("Invalid coupon code")}

    coupon = frappe.get_doc("Coupon", coupon_code)

    # Get order details
    if not frappe.db.exists("Marketplace Order", order_name):
        return {"success": False, "message": _("Order not found")}

    order = frappe.get_doc("Marketplace Order", order_name)

    # Validate coupon for this order
    is_valid, error_message = coupon.is_valid_for_use(
        buyer=order.buyer,
        order_amount=order.total_amount if hasattr(order, 'total_amount') else 0
    )

    if not is_valid:
        return {"success": False, "message": error_message}

    # Calculate discount
    order_amount = order.total_amount if hasattr(order, 'total_amount') else 0
    discount_amount = coupon.calculate_discount(order_amount)

    # Increment usage
    coupon.increment_usage()

    return {
        "success": True,
        "discount_amount": discount_amount,
        "coupon_code": coupon.coupon_code,
        "discount_type": coupon.discount_type
    }

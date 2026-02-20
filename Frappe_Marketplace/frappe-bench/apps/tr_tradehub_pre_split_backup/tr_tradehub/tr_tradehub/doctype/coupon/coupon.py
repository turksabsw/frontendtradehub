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
        self.validate_bogo_configuration()
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

    def validate_bogo_configuration(self):
        """Validate Buy X Get Y configuration"""
        if self.discount_type != "Buy X Get Y":
            return

        # Validate buy quantity
        if not self.buy_quantity or self.buy_quantity < 1:
            frappe.throw(_("Buy Quantity must be at least 1 for BOGO coupons"))

        # Validate get quantity
        if not self.get_quantity or self.get_quantity < 1:
            frappe.throw(_("Get Quantity must be at least 1 for BOGO coupons"))

        # Validate get discount percent
        if self.get_discount_percent is None:
            self.get_discount_percent = 100  # Default to FREE
        elif self.get_discount_percent < 0 or self.get_discount_percent > 100:
            frappe.throw(_("Get Discount % must be between 0 and 100"))

        # Validate product configuration for non-same-product BOGO
        if not self.same_product_only:
            # If specific products are defined for "get", make sure "buy" products are also defined
            if self.bogo_get_products and not self.bogo_buy_products:
                frappe.msgprint(
                    _("Warning: 'Get Products' defined but 'Buy Products' is empty. BOGO will apply to all products."),
                    indicator="orange"
                )

        # Common BOGO patterns info
        total_items = self.buy_quantity + self.get_quantity
        if self.buy_quantity == 1 and self.get_quantity == 1 and self.get_discount_percent == 100:
            frappe.msgprint(_("This is a Buy 1 Get 1 FREE promotion"), indicator="green")
        elif self.buy_quantity == 2 and self.get_quantity == 1 and self.get_discount_percent == 100:
            frappe.msgprint(_("This is a Buy 2 Get 1 FREE promotion"), indicator="green")
        elif self.buy_quantity == 1 and self.get_quantity == 1 and self.get_discount_percent == 50:
            frappe.msgprint(_("This is a Buy 1 Get 1 at 50% off promotion"), indicator="green")

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

    def calculate_discount(self, order_amount, applicable_amount=None, cart_items=None):
        """
        Calculate discount amount for a given order.

        Args:
            order_amount: Total order amount
            applicable_amount: Amount of items this coupon applies to (for partial discounts)
            cart_items: List of cart items for BOGO calculation

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

        elif self.discount_type == "Buy X Get Y":
            return self.calculate_bogo_discount(cart_items)

        return 0

    def calculate_bogo_discount(self, cart_items):
        """
        Calculate BOGO (Buy X Get Y) discount for cart items.

        Args:
            cart_items: List of cart items with structure:
                [{"item": "product_name", "qty": 2, "rate": 100, "category": "category_name"}, ...]

        Returns:
            float: Total BOGO discount amount
        """
        if not cart_items:
            return 0

        buy_qty = self.buy_quantity or 1
        get_qty = self.get_quantity or 1
        get_discount = (self.get_discount_percent or 100) / 100
        total_needed = buy_qty + get_qty

        total_discount = 0

        if self.same_product_only:
            # BOGO applies per product - customer must buy X of same product to get Y of same product
            for item in cart_items:
                item_qty = item.get("qty", 0)
                item_rate = item.get("rate", 0)
                item_name = item.get("item") or item.get("listing")
                item_category = item.get("category")

                # Check if item qualifies for BOGO
                if not self._item_qualifies_for_bogo(item_name, item_category):
                    continue

                # Calculate how many BOGO sets can be applied
                bogo_sets = item_qty // total_needed

                if bogo_sets > 0:
                    # Discount applies to 'get_qty' items per set
                    discounted_items = bogo_sets * get_qty
                    item_discount = discounted_items * item_rate * get_discount
                    total_discount += item_discount
        else:
            # BOGO with different products - buy products can differ from get products
            # Sort items by rate (descending) to maximize customer benefit
            qualifying_buy_items = []
            qualifying_get_items = []

            for item in cart_items:
                item_name = item.get("item") or item.get("listing")
                item_category = item.get("category")
                item_qty = item.get("qty", 0)
                item_rate = item.get("rate", 0)

                # Check if item qualifies as "buy" item
                if self._item_qualifies_as_buy(item_name, item_category):
                    qualifying_buy_items.extend([item_rate] * int(item_qty))

                # Check if item qualifies as "get" item
                if self._item_qualifies_as_get(item_name, item_category):
                    qualifying_get_items.extend([item_rate] * int(item_qty))

            # Sort get items by rate ascending (cheapest first for customer benefit)
            qualifying_get_items.sort()

            # Calculate how many complete BOGO sets we can make
            bogo_sets = min(
                len(qualifying_buy_items) // buy_qty,
                len(qualifying_get_items) // get_qty
            ) if buy_qty > 0 and get_qty > 0 else 0

            # Apply discount to the cheapest 'get_qty * bogo_sets' items
            items_to_discount = bogo_sets * get_qty
            for i in range(items_to_discount):
                if i < len(qualifying_get_items):
                    total_discount += qualifying_get_items[i] * get_discount

        # Apply max discount cap if set
        if self.max_discount_amount and total_discount > self.max_discount_amount:
            total_discount = self.max_discount_amount

        return total_discount

    def _item_qualifies_for_bogo(self, item_name, item_category):
        """Check if an item qualifies for same-product BOGO"""
        # Check category restrictions
        if self.bogo_categories:
            bogo_category_names = [c.category for c in self.bogo_categories]
            if item_category and item_category not in bogo_category_names:
                return False

        # If no restrictions, all items qualify
        return True

    def _item_qualifies_as_buy(self, item_name, item_category):
        """Check if an item qualifies as a 'buy' item for BOGO"""
        # If specific buy products defined, check against them
        if self.bogo_buy_products:
            buy_product_names = [p.product for p in self.bogo_buy_products]
            if item_name and item_name not in buy_product_names:
                return False
            return True

        # Check category restrictions
        if self.bogo_categories:
            bogo_category_names = [c.category for c in self.bogo_categories]
            if item_category and item_category not in bogo_category_names:
                return False

        # If no restrictions, all items qualify
        return True

    def _item_qualifies_as_get(self, item_name, item_category):
        """Check if an item qualifies as a 'get' item for BOGO"""
        # If specific get products defined, check against them
        if self.bogo_get_products:
            get_product_names = [p.product for p in self.bogo_get_products]
            if item_name and item_name not in get_product_names:
                return False
            return True

        # If no specific get products, fall back to buy products logic
        return self._item_qualifies_as_buy(item_name, item_category)


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
def calculate_bogo_preview(coupon_code, cart_items):
    """
    Preview BOGO discount for given cart items before applying.

    Args:
        coupon_code: The BOGO coupon code
        cart_items: JSON string of cart items

    Returns:
        dict: BOGO discount breakdown
    """
    import json

    if not coupon_code:
        return {"success": False, "message": _("Coupon code is required")}

    coupon_code = coupon_code.strip().upper()

    if not frappe.db.exists("Coupon", coupon_code):
        return {"success": False, "message": _("Invalid coupon code")}

    coupon = frappe.get_doc("Coupon", coupon_code)

    if coupon.discount_type != "Buy X Get Y":
        return {"success": False, "message": _("This is not a BOGO coupon")}

    # Parse cart items
    if isinstance(cart_items, str):
        try:
            cart_items = json.loads(cart_items)
        except json.JSONDecodeError:
            return {"success": False, "message": _("Invalid cart items format")}

    # Calculate BOGO discount
    discount = coupon.calculate_bogo_discount(cart_items)
    buy_qty = coupon.buy_quantity or 1
    get_qty = coupon.get_quantity or 1
    get_discount_pct = coupon.get_discount_percent or 100

    return {
        "success": True,
        "coupon_code": coupon.coupon_code,
        "discount_type": "Buy X Get Y",
        "buy_quantity": buy_qty,
        "get_quantity": get_qty,
        "get_discount_percent": get_discount_pct,
        "same_product_only": coupon.same_product_only,
        "discount_amount": discount,
        "promotion_text": _("Buy {0}, Get {1} at {2}% off").format(
            buy_qty, get_qty, get_discount_pct
        ) if get_discount_pct < 100 else _("Buy {0}, Get {1} FREE").format(buy_qty, get_qty)
    }


@frappe.whitelist()
def get_available_bogo_coupons(seller=None, category=None):
    """
    Get all active BOGO coupons, optionally filtered by seller or category.

    Args:
        seller: Optional seller filter
        category: Optional category filter

    Returns:
        list: Available BOGO coupons
    """
    from frappe.utils import now_datetime

    filters = {
        "discount_type": "Buy X Get Y",
        "is_active": 1,
        "status": "Active",
        "valid_from": ["<=", now_datetime()],
        "valid_until": [">=", now_datetime()]
    }

    if seller:
        filters["seller"] = ["in", [seller, None, ""]]

    coupons = frappe.get_all(
        "Coupon",
        filters=filters,
        fields=[
            "coupon_code", "title", "buy_quantity", "get_quantity",
            "get_discount_percent", "same_product_only", "valid_until",
            "seller", "seller_name", "description"
        ]
    )

    # Add promotion text to each coupon
    for coupon in coupons:
        buy_qty = coupon.get("buy_quantity", 1)
        get_qty = coupon.get("get_quantity", 1)
        get_pct = coupon.get("get_discount_percent", 100)

        if get_pct >= 100:
            coupon["promotion_text"] = _("Buy {0}, Get {1} FREE").format(buy_qty, get_qty)
        else:
            coupon["promotion_text"] = _("Buy {0}, Get {1} at {2}% off").format(
                buy_qty, get_qty, get_pct
            )

    return coupons


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

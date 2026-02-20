# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import (
    cint, flt, getdate, nowdate, now_datetime,
    add_days, add_to_date, get_datetime
)
import json


class Cart(Document):
    """
    Shopping Cart DocType for TR-TradeHub marketplace.

    Carts support:
    - Multi-seller items with automatic grouping
    - B2B and B2C pricing
    - Guest and registered user carts
    - Cart abandonment tracking
    - Conversion to Marketplace Order
    - Stock reservation management
    """

    def before_insert(self):
        """Set default values before creating a new cart."""
        # Generate unique cart ID
        if not self.cart_id:
            self.cart_id = self.generate_cart_id()

        # Set buyer from current user if not guest
        if not self.buyer and frappe.session.user != "Guest":
            self.buyer = frappe.session.user
            self.buyer_type = "Individual"

        # Set default expiry (7 days from now for registered, 24 hours for guest)
        if not self.expires_at:
            if self.buyer_type == "Guest":
                self.expires_at = add_to_date(now_datetime(), hours=24)
            else:
                self.expires_at = add_days(now_datetime(), 7)

        # Set last activity
        self.last_activity = now_datetime()

        # Initialize seller summary
        if not self.seller_summary:
            self.seller_summary = "{}"

    def validate(self):
        """Validate cart data before saving."""
        self.validate_buyer()
        self.validate_tenant_consistency()
        self.validate_items()
        self.validate_status_transition()
        self.calculate_totals()
        self.update_seller_summary()
        self.check_expiry()

    def on_update(self):
        """Actions after cart is updated."""
        self.last_activity = now_datetime()
        self.clear_cart_cache()

    def on_trash(self):
        """Actions before cart is deleted."""
        # Release any reserved stock
        self.release_all_reservations()

    # =================================================================
    # Helper Methods
    # =================================================================

    def generate_cart_id(self):
        """Generate a unique cart identifier."""
        return f"CART-{frappe.generate_hash(length=10).upper()}"

    # =================================================================
    # Validation Methods
    # =================================================================

    def validate_buyer(self):
        """Validate buyer information."""
        if self.buyer_type == "Organization":
            if not self.organization:
                frappe.throw(_("Organization is required for organization purchases"))

            if not frappe.db.exists("Organization", self.organization):
                frappe.throw(
                    _("Organization {0} does not exist").format(self.organization)
                )

        if self.buyer and not frappe.db.exists("User", self.buyer):
            frappe.throw(_("Buyer user {0} does not exist").format(self.buyer))

    def validate_tenant_consistency(self):
        """
        Ensure tenant consistency across cart, organization, and cart items.

        This validation prevents data inconsistency where:
        1. A cart's organization could belong to a different tenant
        2. Cart items could have sellers from different tenants

        Such inconsistencies would break tenant isolation and data security.

        Raises:
            frappe.ValidationError: If organization or cart items belong to
            a different tenant than the cart.
        """
        # Validate organization tenant matches cart tenant
        if self.organization:
            org_tenant = frappe.db.get_value("Organization", self.organization, "tenant")

            # If cart has no tenant set but organization has one, use organization's tenant
            if not self.tenant and org_tenant:
                self.tenant = org_tenant
            # If both have tenant set, they must match
            elif self.tenant and org_tenant and self.tenant != org_tenant:
                org_name = frappe.db.get_value("Organization", self.organization, "organization_name")
                frappe.throw(
                    _("Tenant mismatch: Organization '{0}' belongs to tenant '{1}', "
                      "but cart is associated with tenant '{2}'. "
                      "Please select an organization from the same tenant.").format(
                        org_name or self.organization, org_tenant, self.tenant
                    )
                )

        # Validate all cart items' sellers belong to the cart's tenant
        if self.tenant and self.items:
            for item in self.items:
                if not item.seller:
                    continue

                seller_tenant = frappe.db.get_value("Seller Profile", item.seller, "tenant")
                if seller_tenant and seller_tenant != self.tenant:
                    seller_name = frappe.db.get_value("Seller Profile", item.seller, "seller_name")
                    listing_title = item.title or item.listing
                    frappe.throw(
                        _("Tenant mismatch: Item '{0}' from seller '{1}' belongs to a different tenant. "
                          "All cart items must be from sellers within the same tenant '{2}'.").format(
                            listing_title, seller_name or item.seller, self.tenant
                        )
                    )

    def validate_items(self):
        """Validate cart items."""
        if self.status == "Active":
            for item in self.items:
                # Validate listing exists and is active
                if not frappe.db.exists("Listing", item.listing):
                    frappe.throw(
                        _("Listing {0} does not exist").format(item.listing)
                    )

                listing = frappe.get_doc("Listing", item.listing)

                # Check listing is purchasable
                if listing.status not in ["Active", "Out of Stock"]:
                    frappe.throw(
                        _("Listing {0} is not available for purchase").format(
                            listing.title
                        )
                    )

                # Check stock availability
                if listing.track_inventory and not listing.allow_backorders:
                    if flt(item.qty) > flt(listing.available_qty):
                        frappe.throw(
                            _("Not enough stock for {0}. Available: {1}").format(
                                listing.title, listing.available_qty
                            )
                        )

                # Validate quantity limits
                if flt(item.qty) < flt(listing.min_order_qty):
                    frappe.throw(
                        _("Minimum order quantity for {0} is {1}").format(
                            listing.title, listing.min_order_qty
                        )
                    )

                if listing.max_order_qty and flt(listing.max_order_qty) > 0:
                    if flt(item.qty) > flt(listing.max_order_qty):
                        frappe.throw(
                            _("Maximum order quantity for {0} is {1}").format(
                                listing.title, listing.max_order_qty
                            )
                        )

    def validate_status_transition(self):
        """Validate cart status transitions."""
        if not self.is_new():
            old_status = frappe.db.get_value("Cart", self.name, "status")

            # Converted/Expired carts cannot be modified
            if old_status in ["Converted", "Expired", "Merged"]:
                if self.status != old_status:
                    frappe.throw(
                        _("Cannot change status of a {0} cart").format(old_status.lower())
                    )

    # =================================================================
    # Calculation Methods
    # =================================================================

    def calculate_totals(self):
        """Calculate all cart totals from line items."""
        subtotal = 0
        tax_amount = 0
        total_savings = 0

        for item in self.items:
            # Calculate line totals if not already set
            item.calculate_totals()

            subtotal += flt(item.line_total)
            tax_amount += flt(item.tax_amount)

            # Calculate savings from original price
            if item.compare_at_price and flt(item.compare_at_price) > 0:
                savings = (flt(item.compare_at_price) - flt(item.unit_price)) * flt(item.qty)
                total_savings += max(0, savings)

        self.subtotal = subtotal
        self.tax_amount = tax_amount

        # Calculate discount totals
        self.discount_amount = flt(self.coupon_discount) + flt(self.promotion_discount)
        self.total_savings = total_savings + flt(self.discount_amount)

        # Grand total
        self.grand_total = (
            flt(self.subtotal)
            - flt(self.discount_amount)
            + flt(self.shipping_amount)
            + (flt(self.tax_amount) if not self.price_includes_tax else 0)
        )

    def update_seller_summary(self):
        """Update seller-wise grouping and subtotals."""
        seller_data = {}

        for item in self.items:
            seller = item.seller
            if seller not in seller_data:
                seller_data[seller] = {
                    "seller": seller,
                    "seller_name": frappe.db.get_value(
                        "Seller Profile", seller, "seller_name"
                    ) or seller,
                    "items": [],
                    "item_count": 0,
                    "subtotal": 0,
                    "shipping_estimate": 0
                }

            seller_data[seller]["items"].append(item.name or item.listing)
            seller_data[seller]["item_count"] += 1
            seller_data[seller]["subtotal"] += flt(item.line_total)

        self.seller_summary = json.dumps(seller_data)

    def check_expiry(self):
        """Check if cart has expired."""
        if self.expires_at and get_datetime(self.expires_at) < now_datetime():
            if self.status == "Active":
                self.is_expired = 1
                self.status = "Expired"
                # Release reservations
                self.release_all_reservations()

    # =================================================================
    # Cart Item Management
    # =================================================================

    def add_item(self, listing, qty=1, variant=None, price=None):
        """
        Add an item to the cart.

        Args:
            listing: Listing name or code
            qty: Quantity to add
            variant: Listing Variant name (optional)
            price: Override price (optional)

        Returns:
            Cart Line: The added or updated cart line
        """
        if self.status != "Active":
            frappe.throw(_("Cannot add items to a {0} cart").format(self.status.lower()))

        # Get listing document
        listing_doc = frappe.get_doc("Listing", listing)

        # Check if item already exists in cart
        existing_line = None
        for item in self.items:
            if item.listing == listing_doc.name:
                if (variant and item.listing_variant == variant) or (not variant and not item.listing_variant):
                    existing_line = item
                    break

        if existing_line:
            # Update existing line quantity
            new_qty = flt(existing_line.qty) + flt(qty)
            existing_line.qty = new_qty
            existing_line.calculate_totals()
            cart_line = existing_line
        else:
            # Create new cart line
            cart_line = self.append("items", {
                "listing": listing_doc.name,
                "listing_variant": variant,
                "seller": listing_doc.seller,
                "title": listing_doc.title,
                "sku": listing_doc.sku,
                "qty": flt(qty),
                "unit_price": price or listing_doc.get_price(
                    qty=qty,
                    buyer_type="B2B" if self.is_b2b_cart else "B2C"
                ),
                "compare_at_price": listing_doc.compare_at_price,
                "currency": listing_doc.currency or self.currency,
                "stock_uom": listing_doc.stock_uom,
                "primary_image": listing_doc.primary_image,
                "tax_rate": listing_doc.tax_rate or self.default_tax_rate,
                "weight": listing_doc.weight,
                "weight_uom": listing_doc.weight_uom
            })
            cart_line.calculate_totals()

        self.calculate_totals()
        self.last_activity = now_datetime()

        return cart_line

    def update_item_qty(self, line_name, qty):
        """
        Update quantity of a cart item.

        Args:
            line_name: Cart Line name
            qty: New quantity

        Returns:
            Cart Line: The updated cart line or None if removed
        """
        if self.status != "Active":
            frappe.throw(_("Cannot update items in a {0} cart").format(self.status.lower()))

        for item in self.items:
            if item.name == line_name or item.listing == line_name:
                if flt(qty) <= 0:
                    # Remove item
                    self.remove_item(line_name)
                    return None
                else:
                    item.qty = flt(qty)
                    item.calculate_totals()
                    self.calculate_totals()
                    self.last_activity = now_datetime()
                    return item

        frappe.throw(_("Cart item not found"))

    def remove_item(self, line_name):
        """
        Remove an item from the cart.

        Args:
            line_name: Cart Line name or Listing name
        """
        if self.status != "Active":
            frappe.throw(_("Cannot remove items from a {0} cart").format(self.status.lower()))

        for i, item in enumerate(self.items):
            if item.name == line_name or item.listing == line_name:
                # Release any reservation
                if item.stock_reserved:
                    self.release_item_reservation(item)

                self.items.remove(item)
                self.calculate_totals()
                self.last_activity = now_datetime()
                return

        frappe.throw(_("Cart item not found"))

    def clear_cart(self):
        """Remove all items from the cart."""
        if self.status != "Active":
            frappe.throw(_("Cannot clear a {0} cart").format(self.status.lower()))

        # Release all reservations
        self.release_all_reservations()

        # Clear items
        self.items = []
        self.calculate_totals()
        self.last_activity = now_datetime()

    # =================================================================
    # Stock Reservation Methods
    # =================================================================

    def reserve_all_stock(self):
        """Reserve stock for all cart items."""
        for item in self.items:
            if not item.stock_reserved:
                self.reserve_item_stock(item)

    def reserve_item_stock(self, item):
        """Reserve stock for a single cart item."""
        if item.stock_reserved:
            return

        listing = frappe.get_doc("Listing", item.listing)

        if listing.track_inventory:
            try:
                listing.reserve_stock(flt(item.qty))
                item.stock_reserved = 1
                item.reserved_at = now_datetime()
            except Exception as e:
                frappe.log_error(
                    f"Failed to reserve stock for cart {self.name}: {str(e)}",
                    "Cart Stock Reservation Error"
                )

    def release_all_reservations(self):
        """Release all stock reservations."""
        for item in self.items:
            if item.stock_reserved:
                self.release_item_reservation(item)

    def release_item_reservation(self, item):
        """Release stock reservation for a single item."""
        if not item.stock_reserved:
            return

        try:
            listing = frappe.get_doc("Listing", item.listing)
            listing.release_reservation(flt(item.qty))
            item.stock_reserved = 0
            item.reserved_at = None
        except Exception as e:
            frappe.log_error(
                f"Failed to release stock reservation for cart {self.name}: {str(e)}",
                "Cart Stock Release Error"
            )

    # =================================================================
    # Checkout Methods
    # =================================================================

    def start_checkout(self):
        """Mark cart as in checkout process."""
        if self.status != "Active":
            frappe.throw(_("Only active carts can proceed to checkout"))

        if not self.items:
            frappe.throw(_("Cart is empty"))

        # Validate all items are still available
        self.validate_items()

        # Reserve stock
        self.reserve_all_stock()

        self.status = "Checkout"
        self.checkout_started_at = now_datetime()
        self.last_activity = now_datetime()
        self.save()

    def cancel_checkout(self):
        """Cancel checkout and return cart to active state."""
        if self.status != "Checkout":
            frappe.throw(_("Cart is not in checkout"))

        # Release reservations
        self.release_all_reservations()

        self.status = "Active"
        self.checkout_started_at = None
        self.last_activity = now_datetime()
        self.save()

    def convert_to_order(self, shipping_address=None, billing_address=None,
                          payment_method=None, notes=None):
        """
        Convert cart to Marketplace Order.

        Args:
            shipping_address: Shipping address details (dict)
            billing_address: Billing address details (dict)
            payment_method: Selected payment method
            notes: Order notes

        Returns:
            str: Created Marketplace Order name
        """
        if self.status not in ["Active", "Checkout"]:
            frappe.throw(_("Cannot convert a {0} cart to order").format(self.status.lower()))

        if not self.items:
            frappe.throw(_("Cart is empty"))

        # Ensure stock is reserved
        self.reserve_all_stock()

        # Create order data
        order_data = {
            "doctype": "Marketplace Order",
            "buyer": self.buyer,
            "buyer_type": self.buyer_type,
            "organization": self.organization,
            "tenant": self.tenant,
            "cart": self.name,
            "currency": self.currency,
            "subtotal": self.subtotal,
            "discount_amount": self.discount_amount,
            "shipping_amount": self.shipping_amount,
            "tax_amount": self.tax_amount,
            "grand_total": self.grand_total,
            "coupon_code": self.coupon_code,
            "coupon_discount": self.coupon_discount,
            "promotion_discount": self.promotion_discount,
            "is_b2b_order": self.is_b2b_cart,
            "order_notes": notes
        }

        # Add addresses if provided
        if shipping_address:
            order_data.update({
                "shipping_address_line1": shipping_address.get("address_line1"),
                "shipping_address_line2": shipping_address.get("address_line2"),
                "shipping_city": shipping_address.get("city"),
                "shipping_state": shipping_address.get("state"),
                "shipping_postal_code": shipping_address.get("postal_code"),
                "shipping_country": shipping_address.get("country", "Turkey"),
                "shipping_phone": shipping_address.get("phone")
            })

        if billing_address:
            order_data.update({
                "billing_address_line1": billing_address.get("address_line1"),
                "billing_address_line2": billing_address.get("address_line2"),
                "billing_city": billing_address.get("city"),
                "billing_state": billing_address.get("state"),
                "billing_postal_code": billing_address.get("postal_code"),
                "billing_country": billing_address.get("country", "Turkey")
            })

        try:
            order = frappe.get_doc(order_data)

            # Add order items from cart
            for item in self.items:
                order.append("items", {
                    "listing": item.listing,
                    "listing_variant": item.listing_variant,
                    "seller": item.seller,
                    "title": item.title,
                    "sku": item.sku,
                    "qty": item.qty,
                    "unit_price": item.unit_price,
                    "line_total": item.line_total,
                    "tax_rate": item.tax_rate,
                    "tax_amount": item.tax_amount,
                    "weight": item.weight,
                    "primary_image": item.primary_image
                })

            order.flags.ignore_permissions = True
            order.insert()

            # Update cart as converted
            self.status = "Converted"
            self.converted_to_order = 1
            self.marketplace_order = order.name
            self.converted_at = now_datetime()
            self.save()

            return order.name

        except Exception as e:
            frappe.log_error(
                f"Failed to convert cart {self.name} to order: {str(e)}",
                "Cart Conversion Error"
            )
            raise

    # =================================================================
    # Cart Abandonment Methods
    # =================================================================

    def mark_abandoned(self):
        """Mark cart as abandoned."""
        if self.status == "Active":
            self.status = "Abandoned"
            self.abandoned_at = now_datetime()
            self.release_all_reservations()
            self.save()

    def recover_cart(self):
        """Recover an abandoned cart."""
        if self.status != "Abandoned":
            frappe.throw(_("Cart is not abandoned"))

        # Check if items are still available
        valid_items = []
        for item in self.items:
            if frappe.db.exists("Listing", item.listing):
                listing = frappe.get_doc("Listing", item.listing)
                if listing.status in ["Active", "Out of Stock"]:
                    valid_items.append(item)

        if not valid_items:
            frappe.throw(_("No items in this cart are available anymore"))

        # Keep only valid items
        self.items = valid_items
        self.status = "Active"
        self.abandoned_at = None
        self.expires_at = add_days(now_datetime(), 7)
        self.last_activity = now_datetime()
        self.calculate_totals()
        self.save()

    # =================================================================
    # Merge Methods
    # =================================================================

    def merge_with(self, other_cart):
        """
        Merge another cart into this one.

        Args:
            other_cart: Cart to merge from
        """
        if self.status != "Active":
            frappe.throw(_("Can only merge into an active cart"))

        other = frappe.get_doc("Cart", other_cart)

        if other.status not in ["Active", "Abandoned"]:
            frappe.throw(_("Cannot merge a {0} cart").format(other.status.lower()))

        # Add items from other cart
        for item in other.items:
            self.add_item(
                listing=item.listing,
                qty=item.qty,
                variant=item.listing_variant
            )

        # Mark other cart as merged
        other.status = "Merged"
        other.release_all_reservations()
        other.save()

        self.calculate_totals()
        self.save()

    # =================================================================
    # Coupon Methods
    # =================================================================

    def apply_coupon(self, coupon_code):
        """
        Apply a coupon code to the cart.

        Args:
            coupon_code: Coupon code to apply

        Returns:
            dict: Discount information
        """
        if self.status != "Active":
            frappe.throw(_("Cannot apply coupon to a {0} cart").format(self.status.lower()))

        # TODO: Implement coupon validation and discount calculation
        # This should be expanded when Coupon DocType is created

        self.coupon_code = coupon_code
        self.calculate_totals()
        self.save()

        return {
            "success": True,
            "discount": self.coupon_discount,
            "message": _("Coupon applied successfully")
        }

    def remove_coupon(self):
        """Remove applied coupon from cart."""
        self.coupon_code = None
        self.coupon_discount = 0
        self.calculate_totals()
        self.save()

    # =================================================================
    # Utility Methods
    # =================================================================

    def get_item_count(self):
        """Get total number of items in cart."""
        return sum(flt(item.qty) for item in self.items)

    def get_seller_count(self):
        """Get number of unique sellers in cart."""
        sellers = set(item.seller for item in self.items)
        return len(sellers)

    def get_sellers(self):
        """Get list of unique sellers in cart."""
        sellers = {}
        for item in self.items:
            if item.seller not in sellers:
                sellers[item.seller] = {
                    "seller": item.seller,
                    "seller_name": frappe.db.get_value(
                        "Seller Profile", item.seller, "seller_name"
                    ),
                    "items": []
                }
            sellers[item.seller]["items"].append({
                "listing": item.listing,
                "title": item.title,
                "qty": item.qty,
                "line_total": item.line_total
            })

        return list(sellers.values())

    def get_summary(self):
        """Get cart summary for display."""
        return {
            "cart_id": self.cart_id,
            "status": self.status,
            "item_count": len(self.items),
            "total_quantity": self.get_item_count(),
            "seller_count": self.get_seller_count(),
            "subtotal": self.subtotal,
            "discount_amount": self.discount_amount,
            "shipping_amount": self.shipping_amount,
            "tax_amount": self.tax_amount,
            "grand_total": self.grand_total,
            "total_savings": self.total_savings,
            "currency": self.currency,
            "coupon_code": self.coupon_code,
            "is_b2b_cart": self.is_b2b_cart,
            "expires_at": self.expires_at
        }

    def clear_cart_cache(self):
        """Clear cached cart data."""
        if self.cart_id:
            frappe.cache().delete_value(f"cart:{self.cart_id}")

        if self.buyer:
            frappe.cache().delete_value(f"user_cart:{self.buyer}")

        if self.session_id:
            frappe.cache().delete_value(f"session_cart:{self.session_id}")


# =================================================================
# API Endpoints
# =================================================================

@frappe.whitelist(allow_guest=True)
def get_cart(cart_id=None, session_id=None):
    """
    Get cart by ID or session.

    Args:
        cart_id: Cart ID
        session_id: Session ID (for guest carts)

    Returns:
        dict: Cart data
    """
    filters = {"status": ["in", ["Active", "Checkout"]]}

    if cart_id:
        filters["cart_id"] = cart_id
    elif session_id:
        filters["session_id"] = session_id
    elif frappe.session.user != "Guest":
        filters["buyer"] = frappe.session.user
    else:
        return {"error": _("Cart not found")}

    cart_name = frappe.db.get_value("Cart", filters, "name")

    if not cart_name:
        return {"error": _("Cart not found")}

    cart = frappe.get_doc("Cart", cart_name)

    # Permission check
    if frappe.session.user != "Guest":
        if cart.buyer and cart.buyer != frappe.session.user:
            if not frappe.has_permission("Cart", "read"):
                return {"error": _("Not permitted to view this cart")}

    items = []
    for item in cart.items:
        items.append({
            "name": item.name,
            "listing": item.listing,
            "listing_variant": item.listing_variant,
            "seller": item.seller,
            "title": item.title,
            "sku": item.sku,
            "qty": item.qty,
            "unit_price": item.unit_price,
            "compare_at_price": item.compare_at_price,
            "line_total": item.line_total,
            "tax_amount": item.tax_amount,
            "primary_image": item.primary_image,
            "currency": item.currency
        })

    return {
        "name": cart.name,
        "cart_id": cart.cart_id,
        "status": cart.status,
        "buyer": cart.buyer,
        "buyer_type": cart.buyer_type,
        "items": items,
        "summary": cart.get_summary(),
        "sellers": cart.get_sellers()
    }


@frappe.whitelist(allow_guest=True)
def get_or_create_cart(session_id=None):
    """
    Get existing active cart or create new one.

    Args:
        session_id: Session ID for guest users

    Returns:
        dict: Cart data
    """
    filters = {"status": "Active"}

    if frappe.session.user != "Guest":
        filters["buyer"] = frappe.session.user
    elif session_id:
        filters["session_id"] = session_id
    else:
        # Create new guest cart
        return create_cart(session_id=frappe.generate_hash(length=20))

    cart_name = frappe.db.get_value("Cart", filters, "name")

    if cart_name:
        return get_cart(cart_id=frappe.db.get_value("Cart", cart_name, "cart_id"))

    # Create new cart
    return create_cart(session_id=session_id)


@frappe.whitelist(allow_guest=True)
def create_cart(session_id=None):
    """
    Create a new cart.

    Args:
        session_id: Session ID for guest users

    Returns:
        dict: Created cart data
    """
    cart_data = {"doctype": "Cart"}

    if frappe.session.user != "Guest":
        cart_data["buyer"] = frappe.session.user
        cart_data["buyer_type"] = "Individual"
    else:
        cart_data["buyer_type"] = "Guest"
        cart_data["session_id"] = session_id or frappe.generate_hash(length=20)

    # Capture session info
    if frappe.request:
        cart_data["ip_address"] = frappe.get_request_header("X-Forwarded-For") or frappe.local.request_ip
        cart_data["user_agent"] = frappe.get_request_header("User-Agent")

    cart = frappe.get_doc(cart_data)
    cart.flags.ignore_permissions = True
    cart.insert()

    return get_cart(cart_id=cart.cart_id)


@frappe.whitelist(allow_guest=True)
def add_to_cart(listing, qty=1, variant=None, cart_id=None, session_id=None):
    """
    Add item to cart.

    Args:
        listing: Listing name or code
        qty: Quantity to add
        variant: Listing Variant (optional)
        cart_id: Cart ID (optional)
        session_id: Session ID for guest (optional)

    Returns:
        dict: Updated cart data
    """
    # Get or create cart
    if cart_id:
        cart = frappe.get_doc("Cart", {"cart_id": cart_id})
    else:
        result = get_or_create_cart(session_id=session_id)
        if "error" in result:
            return result
        cart = frappe.get_doc("Cart", result["name"])

    # Validate listing
    listing_name = listing
    if not frappe.db.exists("Listing", listing):
        # Try by listing_code
        listing_name = frappe.db.get_value(
            "Listing", {"listing_code": listing}, "name"
        )
        if not listing_name:
            return {"error": _("Listing not found")}

    # Add item
    cart.add_item(listing=listing_name, qty=flt(qty), variant=variant)
    cart.flags.ignore_permissions = True
    cart.save()

    return get_cart(cart_id=cart.cart_id)


@frappe.whitelist(allow_guest=True)
def update_cart_item(cart_id, line_name, qty):
    """
    Update cart item quantity.

    Args:
        cart_id: Cart ID
        line_name: Cart Line name or Listing name
        qty: New quantity

    Returns:
        dict: Updated cart data
    """
    cart = frappe.get_doc("Cart", {"cart_id": cart_id})

    # Permission check
    if cart.buyer and cart.buyer != frappe.session.user:
        if frappe.session.user != "Guest":
            if not frappe.has_permission("Cart", "write"):
                return {"error": _("Not permitted to update this cart")}

    cart.update_item_qty(line_name, flt(qty))
    cart.flags.ignore_permissions = True
    cart.save()

    return get_cart(cart_id=cart_id)


@frappe.whitelist(allow_guest=True)
def remove_from_cart(cart_id, line_name):
    """
    Remove item from cart.

    Args:
        cart_id: Cart ID
        line_name: Cart Line name or Listing name

    Returns:
        dict: Updated cart data
    """
    cart = frappe.get_doc("Cart", {"cart_id": cart_id})

    # Permission check
    if cart.buyer and cart.buyer != frappe.session.user:
        if frappe.session.user != "Guest":
            if not frappe.has_permission("Cart", "write"):
                return {"error": _("Not permitted to update this cart")}

    cart.remove_item(line_name)
    cart.flags.ignore_permissions = True
    cart.save()

    return get_cart(cart_id=cart_id)


@frappe.whitelist(allow_guest=True)
def clear_cart_items(cart_id):
    """
    Clear all items from cart.

    Args:
        cart_id: Cart ID

    Returns:
        dict: Updated cart data
    """
    cart = frappe.get_doc("Cart", {"cart_id": cart_id})

    # Permission check
    if cart.buyer and cart.buyer != frappe.session.user:
        if frappe.session.user != "Guest":
            if not frappe.has_permission("Cart", "write"):
                return {"error": _("Not permitted to update this cart")}

    cart.clear_cart()
    cart.flags.ignore_permissions = True
    cart.save()

    return get_cart(cart_id=cart_id)


@frappe.whitelist(allow_guest=True)
def apply_coupon_to_cart(cart_id, coupon_code):
    """
    Apply coupon code to cart.

    Args:
        cart_id: Cart ID
        coupon_code: Coupon code

    Returns:
        dict: Result with discount info
    """
    cart = frappe.get_doc("Cart", {"cart_id": cart_id})

    # Permission check
    if cart.buyer and cart.buyer != frappe.session.user:
        if frappe.session.user != "Guest":
            if not frappe.has_permission("Cart", "write"):
                return {"error": _("Not permitted to update this cart")}

    result = cart.apply_coupon(coupon_code)

    return {
        "success": result.get("success"),
        "discount": result.get("discount"),
        "message": result.get("message"),
        "cart": get_cart(cart_id=cart_id)
    }


@frappe.whitelist()
def start_checkout(cart_id):
    """
    Start checkout process for cart.

    Args:
        cart_id: Cart ID

    Returns:
        dict: Checkout data
    """
    cart = frappe.get_doc("Cart", {"cart_id": cart_id})

    # Permission check
    if cart.buyer and cart.buyer != frappe.session.user:
        if not frappe.has_permission("Cart", "write"):
            return {"error": _("Not permitted to checkout this cart")}

    cart.start_checkout()

    return {
        "status": "success",
        "message": _("Checkout started"),
        "cart": get_cart(cart_id=cart_id)
    }


@frappe.whitelist()
def cancel_checkout(cart_id):
    """
    Cancel checkout and return to cart.

    Args:
        cart_id: Cart ID

    Returns:
        dict: Updated cart data
    """
    cart = frappe.get_doc("Cart", {"cart_id": cart_id})

    # Permission check
    if cart.buyer and cart.buyer != frappe.session.user:
        if not frappe.has_permission("Cart", "write"):
            return {"error": _("Not permitted to update this cart")}

    cart.cancel_checkout()

    return get_cart(cart_id=cart_id)


@frappe.whitelist()
def convert_cart_to_order(cart_id, shipping_address=None, billing_address=None,
                           payment_method=None, notes=None):
    """
    Convert cart to marketplace order.

    Args:
        cart_id: Cart ID
        shipping_address: Shipping address (JSON string or dict)
        billing_address: Billing address (JSON string or dict)
        payment_method: Payment method
        notes: Order notes

    Returns:
        dict: Created order info
    """
    cart = frappe.get_doc("Cart", {"cart_id": cart_id})

    # Permission check
    if cart.buyer and cart.buyer != frappe.session.user:
        if not frappe.has_permission("Cart", "write"):
            return {"error": _("Not permitted to checkout this cart")}

    # Parse addresses if JSON strings
    if isinstance(shipping_address, str):
        shipping_address = json.loads(shipping_address)
    if isinstance(billing_address, str):
        billing_address = json.loads(billing_address)

    order_name = cart.convert_to_order(
        shipping_address=shipping_address,
        billing_address=billing_address,
        payment_method=payment_method,
        notes=notes
    )

    return {
        "status": "success",
        "message": _("Order created successfully"),
        "order_name": order_name,
        "order_id": frappe.db.get_value("Marketplace Order", order_name, "order_id")
    }


@frappe.whitelist()
def merge_carts(target_cart_id, source_cart_id):
    """
    Merge source cart into target cart.

    Args:
        target_cart_id: Target cart ID
        source_cart_id: Source cart ID to merge from

    Returns:
        dict: Updated target cart data
    """
    target = frappe.get_doc("Cart", {"cart_id": target_cart_id})
    source = frappe.get_doc("Cart", {"cart_id": source_cart_id})

    # Permission check
    if target.buyer and target.buyer != frappe.session.user:
        if not frappe.has_permission("Cart", "write"):
            return {"error": _("Not permitted to update target cart")}

    target.merge_with(source.name)

    return get_cart(cart_id=target_cart_id)


@frappe.whitelist()
def get_abandoned_carts(days=7, page=1, page_size=20):
    """
    Get abandoned carts for recovery (admin function).

    Args:
        days: Days since abandoned
        page: Page number
        page_size: Results per page

    Returns:
        dict: Abandoned carts list
    """
    if not frappe.has_permission("Cart", "read"):
        return {"error": _("Not permitted")}

    filters = {
        "status": "Abandoned",
        "recovery_email_sent": 0,
        "buyer": ["is", "set"]  # Only registered users
    }

    start = (cint(page) - 1) * cint(page_size)

    carts = frappe.get_all(
        "Cart",
        filters=filters,
        fields=[
            "name", "cart_id", "buyer", "grand_total", "currency",
            "abandoned_at", "last_activity"
        ],
        order_by="abandoned_at DESC",
        start=start,
        limit_page_length=cint(page_size)
    )

    total = frappe.db.count("Cart", filters)

    return {
        "carts": carts,
        "total": total,
        "page": cint(page),
        "page_size": cint(page_size),
        "total_pages": (total + cint(page_size) - 1) // cint(page_size)
    }


@frappe.whitelist()
def get_cart_statistics():
    """
    Get cart statistics for dashboard.

    Returns:
        dict: Cart statistics
    """
    if not frappe.has_permission("Cart", "read"):
        return {"error": _("Not permitted")}

    stats = frappe.db.sql("""
        SELECT
            status,
            COUNT(*) as count,
            SUM(grand_total) as total_value
        FROM `tabCart`
        GROUP BY status
    """, as_dict=True)

    status_data = {s.status: {"count": s.count, "value": s.total_value} for s in stats}

    # Calculate conversion rate
    active = status_data.get("Active", {}).get("count", 0)
    converted = status_data.get("Converted", {}).get("count", 0)
    abandoned = status_data.get("Abandoned", {}).get("count", 0)

    total_started = active + converted + abandoned
    conversion_rate = (converted / total_started * 100) if total_started > 0 else 0
    abandonment_rate = (abandoned / total_started * 100) if total_started > 0 else 0

    return {
        "status_breakdown": status_data,
        "total_carts": sum(s.count for s in stats),
        "active_carts": status_data.get("Active", {}).get("count", 0),
        "converted_carts": converted,
        "abandoned_carts": abandoned,
        "conversion_rate": round(conversion_rate, 2),
        "abandonment_rate": round(abandonment_rate, 2),
        "total_active_value": status_data.get("Active", {}).get("value", 0),
        "total_converted_value": status_data.get("Converted", {}).get("value", 0)
    }


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def get_buyers_for_tenant(doctype, txt, searchfield, start, page_len, filters):
    """
    Custom query to get users who have a Buyer Profile in the specified tenant.

    This is used by the set_query filter on the buyer field in Cart DocType
    to ensure only buyers from the same tenant can be selected.

    Args:
        doctype: The doctype to search (User)
        txt: Search text
        searchfield: Field to search
        start: Start index for pagination
        page_len: Number of results per page
        filters: Dict containing 'tenant' filter

    Returns:
        list: List of tuples (user_name, full_name) for matching users
    """
    tenant = filters.get('tenant') if filters else None

    if not tenant:
        # If no tenant specified, return all users with Buyer Profiles
        return frappe.db.sql("""
            SELECT DISTINCT u.name, u.full_name
            FROM `tabUser` u
            INNER JOIN `tabBuyer Profile` bp ON bp.user = u.name
            WHERE u.enabled = 1
            AND (u.name LIKE %(txt)s OR u.full_name LIKE %(txt)s)
            ORDER BY u.full_name
            LIMIT %(start)s, %(page_len)s
        """, {
            'txt': f'%{txt}%',
            'start': start,
            'page_len': page_len
        })

    # Filter users who have a Buyer Profile in the specified tenant
    return frappe.db.sql("""
        SELECT DISTINCT u.name, u.full_name
        FROM `tabUser` u
        INNER JOIN `tabBuyer Profile` bp ON bp.user = u.name
        WHERE u.enabled = 1
        AND bp.tenant = %(tenant)s
        AND (u.name LIKE %(txt)s OR u.full_name LIKE %(txt)s)
        ORDER BY u.full_name
        LIMIT %(start)s, %(page_len)s
    """, {
        'tenant': tenant,
        'txt': f'%{txt}%',
        'start': start,
        'page_len': page_len
    })

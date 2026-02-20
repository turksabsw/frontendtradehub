# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import (
    cint, flt, getdate, nowdate, now_datetime,
    add_days, get_datetime, date_diff
)
import json

# Import ERPNext sync utilities
from tradehub_core.tradehub_core.utils.erpnext_sync import (
    create_sales_order_from_marketplace_order,
    sync_sales_order_from_marketplace_order,
    cancel_sales_order_for_marketplace_order,
    submit_sales_order_for_marketplace_order,
    is_erpnext_installed,
    ERPNextSyncError
)


class MarketplaceOrder(Document):
    """
    Marketplace Order DocType for TR-TradeHub.

    Master order containing all items from a cart checkout.
    Supports:
    - Multi-seller orders (items from different sellers)
    - ERPNext Sales Order integration
    - Sub Order splitting by seller
    - Escrow payment integration
    - E-Invoice (E-Fatura) for Turkish compliance
    - Full order lifecycle management
    """

    def before_insert(self):
        """Set default values before creating a new order."""
        # Generate unique order ID
        if not self.order_id:
            self.order_id = self.generate_order_id()

        # Set order date if not provided
        if not self.order_date:
            self.order_date = nowdate()

        # Set buyer details from user if not provided
        if self.buyer and not self.buyer_name:
            self.set_buyer_details()

        # Initialize seller summary
        if not self.seller_summary:
            self.seller_summary = "{}"

    def validate(self):
        """Validate order data before saving."""
        self.validate_buyer()
        self.validate_items()
        self.validate_addresses()
        self.validate_status_transitions()
        self.calculate_totals()
        self.update_seller_summary()
        self.validate_payment_status()

    def on_update(self):
        """Actions after order is updated."""
        self.clear_order_cache()

        # Sync to ERPNext if Sales Order exists
        if self.erpnext_sales_order:
            self.sync_to_erpnext_sales_order()

    def on_submit(self):
        """Actions when order is submitted."""
        # Create ERPNext Sales Order if not exists
        if not self.erpnext_sales_order:
            self.create_erpnext_sales_order()

        # Create Sub Orders for each seller
        self.create_sub_orders()

        # Set initial status
        if self.payment_status == "Paid":
            self.db_set("status", "Confirmed")
            self.db_set("confirmed_at", now_datetime())
        else:
            self.db_set("status", "Await Payment")

        # Update listing order counts
        self.update_listing_order_counts()

    def on_cancel(self):
        """Actions when order is cancelled."""
        self.db_set("status", "Cancelled")
        self.db_set("cancelled_at", now_datetime())

        # Release reserved stock
        self.release_reserved_stock()

        # Cancel Sub Orders
        self.cancel_sub_orders()

        # Cancel ERPNext Sales Order
        if self.erpnext_sales_order:
            self.cancel_erpnext_sales_order()

    # =================================================================
    # Helper Methods
    # =================================================================

    def generate_order_id(self):
        """Generate a unique customer-facing order identifier."""
        return f"TRH-{frappe.generate_hash(length=10).upper()}"

    def set_buyer_details(self):
        """Set buyer details from user record."""
        if not self.buyer:
            return

        user = frappe.get_doc("User", self.buyer)
        if not self.buyer_name:
            self.buyer_name = user.full_name
        if not self.buyer_email:
            self.buyer_email = user.email
        if not self.buyer_phone:
            self.buyer_phone = user.mobile_no or user.phone

    # =================================================================
    # Validation Methods
    # =================================================================

    def validate_buyer(self):
        """Validate buyer information."""
        if not self.buyer:
            frappe.throw(_("Buyer is required"))

        if not frappe.db.exists("User", self.buyer):
            frappe.throw(_("Buyer {0} does not exist").format(self.buyer))

        if self.buyer_type == "Organization":
            if not self.organization:
                frappe.throw(
                    _("Organization is required for organization orders")
                )

    def validate_items(self):
        """Validate order items."""
        if not self.items:
            frappe.throw(_("Order must have at least one item"))

        for item in self.items:
            # Validate listing exists
            if not frappe.db.exists("Listing", item.listing):
                frappe.throw(
                    _("Listing {0} does not exist").format(item.listing)
                )

            # Validate seller
            if not item.seller:
                listing = frappe.get_doc("Listing", item.listing)
                item.seller = listing.seller

            # Validate quantity
            if flt(item.qty) <= 0:
                frappe.throw(
                    _("Quantity must be greater than 0 for {0}").format(item.title)
                )

    def validate_addresses(self):
        """Validate shipping and billing addresses."""
        if not self.shipping_address_line1:
            frappe.throw(_("Shipping address is required"))

        if not self.shipping_city:
            frappe.throw(_("Shipping city is required"))

        if not self.shipping_country:
            self.shipping_country = "Turkey"

        # Copy shipping to billing if same_as_shipping
        if self.same_as_shipping:
            self.billing_address_name = self.shipping_address_name
            self.billing_address_line1 = self.shipping_address_line1
            self.billing_address_line2 = self.shipping_address_line2
            self.billing_city = self.shipping_city
            self.billing_state = self.shipping_state
            self.billing_postal_code = self.shipping_postal_code
            self.billing_country = self.shipping_country

    def validate_status_transitions(self):
        """Validate order status transitions."""
        if self.is_new():
            return

        old_status = frappe.db.get_value("Marketplace Order", self.name, "status")

        # Define valid transitions
        valid_transitions = {
            "Pending": ["Await Payment", "Confirmed", "Cancelled", "On Hold"],
            "Await Payment": ["Payment Received", "Cancelled", "On Hold"],
            "Payment Received": ["Confirmed", "Cancelled", "On Hold"],
            "Confirmed": ["Processing", "Cancelled", "On Hold"],
            "Processing": ["Packed", "Shipped", "Cancelled", "On Hold"],
            "Packed": ["Shipped", "Cancelled", "On Hold"],
            "Shipped": ["In Transit", "Delivered", "On Hold"],
            "In Transit": ["Out for Delivery", "Delivered", "On Hold"],
            "Out for Delivery": ["Delivered", "On Hold"],
            "Delivered": ["Completed", "Refunded", "Disputed"],
            "Completed": ["Refunded", "Disputed"],
            "Cancelled": ["Refunded"],
            "Refunded": [],
            "On Hold": ["Pending", "Confirmed", "Processing", "Cancelled"],
            "Disputed": ["Refunded", "Completed"]
        }

        if old_status and self.status != old_status:
            if self.status not in valid_transitions.get(old_status, []):
                frappe.throw(
                    _("Cannot change status from {0} to {1}").format(
                        old_status, self.status
                    )
                )

    def validate_payment_status(self):
        """Validate payment status consistency."""
        if self.payment_status == "Paid":
            if flt(self.paid_amount) <= 0:
                self.paid_amount = self.grand_total

    # =================================================================
    # Calculation Methods
    # =================================================================

    def calculate_totals(self):
        """Calculate all order totals from line items."""
        subtotal = 0
        tax_amount = 0
        total_commission = 0

        for item in self.items:
            # Ensure item totals are calculated
            item.calculate_totals()

            subtotal += flt(item.line_subtotal) - flt(item.discount_amount)
            tax_amount += flt(item.tax_amount)
            total_commission += flt(item.commission_amount)

        self.subtotal = subtotal
        self.tax_amount = tax_amount
        self.total_commission = total_commission

        # Calculate discount totals
        self.discount_amount = (
            flt(self.coupon_discount)
            + flt(self.promotion_discount)
            + flt(self.store_credit_used)
        )

        # Grand total
        self.grand_total = (
            flt(self.subtotal)
            - flt(self.discount_amount)
            + flt(self.shipping_amount)
            + (flt(self.tax_amount) if not self.price_includes_tax else 0)
        )

        # Commission rate (average)
        if flt(self.subtotal) > 0:
            self.commission_rate = (
                flt(self.total_commission) / flt(self.subtotal) * 100
            )

    def update_seller_summary(self):
        """Update seller-wise grouping and subtotals."""
        seller_data = {}
        seller_count = 0

        for item in self.items:
            seller = item.seller
            if seller not in seller_data:
                seller_count += 1
                seller_name = frappe.db.get_value(
                    "Seller Profile", seller, "seller_name"
                ) or seller
                seller_data[seller] = {
                    "seller": seller,
                    "seller_name": seller_name,
                    "items": [],
                    "item_count": 0,
                    "subtotal": 0,
                    "tax_amount": 0,
                    "commission_amount": 0,
                    "shipping_amount": 0
                }

            seller_data[seller]["items"].append(item.name or item.listing)
            seller_data[seller]["item_count"] += 1
            seller_data[seller]["subtotal"] += flt(item.line_subtotal) - flt(item.discount_amount)
            seller_data[seller]["tax_amount"] += flt(item.tax_amount)
            seller_data[seller]["commission_amount"] += flt(item.commission_amount)
            seller_data[seller]["shipping_amount"] += flt(item.shipping_amount)

        self.seller_count = seller_count
        self.seller_summary = json.dumps(seller_data)

    def update_fulfillment_counts(self):
        """Update fulfillment item counts."""
        packed = 0
        shipped = 0
        delivered = 0
        returned = 0
        total_items = len(self.items)

        for item in self.items:
            status = item.fulfillment_status
            if status in ["Packed", "Shipped", "In Transit", "Out for Delivery", "Delivered"]:
                packed += 1
            if status in ["Shipped", "In Transit", "Out for Delivery", "Delivered"]:
                shipped += 1
            if status == "Delivered":
                delivered += 1
            if status == "Returned":
                returned += 1

        self.db_set("items_packed", packed)
        self.db_set("items_shipped", shipped)
        self.db_set("items_delivered", delivered)
        self.db_set("items_returned", returned)

        # Check if fully fulfilled
        if delivered == total_items:
            self.db_set("fully_fulfilled", 1)
            self.db_set("fulfillment_status", "Delivered")
        elif delivered > 0:
            self.db_set("fulfillment_status", "Partially Delivered")
        elif shipped == total_items:
            self.db_set("fulfillment_status", "Shipped")
        elif shipped > 0:
            self.db_set("fulfillment_status", "Partially Shipped")
        elif packed == total_items:
            self.db_set("fulfillment_status", "Packed")
        elif packed > 0:
            self.db_set("fulfillment_status", "Partially Packed")

    # =================================================================
    # ERPNext Integration Methods
    # =================================================================

    def create_erpnext_sales_order(self):
        """
        Create a linked ERPNext Sales Order.

        Uses centralized sync utilities from tradehub_core.tradehub_core.utils.erpnext_sync
        for consistent handling across the platform.
        """
        if not is_erpnext_installed():
            frappe.log_error(
                "ERPNext is not installed - cannot create Sales Order",
                "Marketplace Order Sync Warning"
            )
            return None

        try:
            return create_sales_order_from_marketplace_order(self)
        except ERPNextSyncError as e:
            frappe.log_error(
                f"ERPNext sync error for order {self.name}: {str(e)}",
                "Marketplace Order ERPNext Sync Error"
            )
            return None
        except Exception as e:
            frappe.log_error(
                f"Failed to create ERPNext Sales Order for {self.name}: {str(e)}",
                "Marketplace Order ERPNext Sync Error"
            )
            return None

    def sync_to_erpnext_sales_order(self):
        """
        Sync order changes to linked ERPNext Sales Order.

        Uses centralized sync utilities for consistent handling.
        """
        if not is_erpnext_installed():
            return False

        if not self.erpnext_sales_order:
            return False

        try:
            return sync_sales_order_from_marketplace_order(self)
        except Exception as e:
            frappe.log_error(
                f"Failed to sync ERPNext Sales Order for {self.name}: {str(e)}",
                "Marketplace Order ERPNext Sync Error"
            )
            return False

    def cancel_erpnext_sales_order(self):
        """
        Cancel linked ERPNext Sales Order.

        Uses centralized sync utilities for consistent handling.
        """
        if not is_erpnext_installed():
            return True  # Nothing to cancel if ERPNext not installed

        if not self.erpnext_sales_order:
            return True

        try:
            return cancel_sales_order_for_marketplace_order(self)
        except Exception as e:
            frappe.log_error(
                f"Failed to cancel ERPNext Sales Order for {self.name}: {str(e)}",
                "Marketplace Order ERPNext Sync Error"
            )
            return False

    def submit_erpnext_sales_order(self):
        """
        Submit the linked ERPNext Sales Order.

        Useful when order is confirmed after payment.
        """
        if not is_erpnext_installed():
            return False

        if not self.erpnext_sales_order:
            return False

        try:
            return submit_sales_order_for_marketplace_order(self)
        except Exception as e:
            frappe.log_error(
                f"Failed to submit ERPNext Sales Order for {self.name}: {str(e)}",
                "Marketplace Order ERPNext Sync Error"
            )
            return False

    def get_or_create_erpnext_customer(self):
        """
        Get or create ERPNext Customer from buyer.

        This method is kept for backward compatibility but the actual
        customer creation is now handled by the centralized sync utilities.
        """
        if not is_erpnext_installed():
            return None

        # Import the helper function from sync utilities
        from tradehub_core.tradehub_core.utils.erpnext_sync import _get_or_create_customer_for_order

        try:
            return _get_or_create_customer_for_order(self)
        except Exception as e:
            frappe.log_error(
                f"Failed to get/create ERPNext Customer: {str(e)}",
                "Marketplace Order Customer Creation Error"
            )
            return None

    def get_default_warehouse(self):
        """Get default warehouse for order items."""
        # Import the helper function from sync utilities
        from tradehub_core.tradehub_core.utils.erpnext_sync import _get_default_warehouse

        return _get_default_warehouse() or "Stores - TC"  # Fallback

    # =================================================================
    # Sub Order Methods
    # =================================================================

    def create_sub_orders(self):
        """Create Sub Orders for each seller."""
        if not frappe.db.exists("DocType", "Sub Order"):
            return

        seller_items = {}

        # Group items by seller
        for item in self.items:
            seller = item.seller
            if seller not in seller_items:
                seller_items[seller] = []
            seller_items[seller].append(item)

        # Create Sub Order for each seller
        for seller, items in seller_items.items():
            try:
                sub_order_items = []
                subtotal = 0
                tax_amount = 0
                shipping_amount = 0
                commission_amount = 0

                for item in items:
                    sub_order_items.append({
                        "listing": item.listing,
                        "listing_variant": item.listing_variant,
                        "title": item.title,
                        "sku": item.sku,
                        "qty": item.qty,
                        "unit_price": item.unit_price,
                        "line_total": item.line_total,
                        "tax_amount": item.tax_amount,
                        "commission_amount": item.commission_amount
                    })
                    subtotal += flt(item.line_subtotal) - flt(item.discount_amount)
                    tax_amount += flt(item.tax_amount)
                    shipping_amount += flt(item.shipping_amount)
                    commission_amount += flt(item.commission_amount)

                sub_order = frappe.get_doc({
                    "doctype": "Sub Order",
                    "marketplace_order": self.name,
                    "seller": seller,
                    "buyer": self.buyer,
                    "status": "Pending",
                    "subtotal": subtotal,
                    "tax_amount": tax_amount,
                    "shipping_amount": shipping_amount,
                    "commission_amount": commission_amount,
                    "grand_total": subtotal + tax_amount + shipping_amount,
                    "seller_payout": subtotal + tax_amount + shipping_amount - commission_amount,
                    "currency": self.currency,
                    "shipping_address_line1": self.shipping_address_line1,
                    "shipping_address_line2": self.shipping_address_line2,
                    "shipping_city": self.shipping_city,
                    "shipping_state": self.shipping_state,
                    "shipping_postal_code": self.shipping_postal_code,
                    "shipping_country": self.shipping_country,
                    "shipping_phone": self.shipping_phone
                })
                sub_order.flags.ignore_permissions = True
                sub_order.insert()

                # Update item references
                for item in items:
                    item.db_set("sub_order", sub_order.name)

            except Exception as e:
                frappe.log_error(
                    f"Failed to create Sub Order for seller {seller}: {str(e)}",
                    "Marketplace Order Sub Order Error"
                )

    def cancel_sub_orders(self):
        """Cancel all sub orders for this marketplace order."""
        sub_orders = frappe.get_all(
            "Sub Order",
            filters={"marketplace_order": self.name},
            pluck="name"
        )

        for sub_order_name in sub_orders:
            try:
                sub_order = frappe.get_doc("Sub Order", sub_order_name)
                sub_order.db_set("status", "Cancelled")
            except Exception as e:
                frappe.log_error(
                    f"Failed to cancel Sub Order {sub_order_name}: {str(e)}",
                    "Marketplace Order Cancel Error"
                )

    # =================================================================
    # Stock Methods
    # =================================================================

    def release_reserved_stock(self):
        """Release reserved stock for all items."""
        for item in self.items:
            try:
                listing = frappe.get_doc("Listing", item.listing)
                listing.release_reservation(flt(item.qty))
            except Exception as e:
                frappe.log_error(
                    f"Failed to release stock for {item.listing}: {str(e)}",
                    "Marketplace Order Stock Release Error"
                )

    def update_listing_order_counts(self):
        """Update order counts for all listings in this order."""
        for item in self.items:
            try:
                listing = frappe.get_doc("Listing", item.listing)
                listing.increment_order_count()
            except Exception as e:
                frappe.log_error(
                    f"Failed to update order count for {item.listing}: {str(e)}",
                    "Marketplace Order Count Update Error"
                )

    # =================================================================
    # Status Methods
    # =================================================================

    def confirm_order(self):
        """Confirm the order after payment."""
        if self.status not in ["Pending", "Await Payment", "Payment Received"]:
            frappe.throw(_("Order cannot be confirmed from current status"))

        self.db_set("status", "Confirmed")
        self.db_set("confirmed_at", now_datetime())
        self.clear_order_cache()

        # Notify sellers
        self.notify_sellers_new_order()

    def start_processing(self):
        """Mark order as processing."""
        if self.status != "Confirmed":
            frappe.throw(_("Only confirmed orders can be processed"))

        self.db_set("status", "Processing")
        self.db_set("processing_started_at", now_datetime())
        self.clear_order_cache()

    def mark_shipped(self):
        """Mark order as shipped."""
        if self.status not in ["Processing", "Packed"]:
            frappe.throw(_("Order cannot be marked as shipped from current status"))

        self.db_set("status", "Shipped")
        self.db_set("shipped_at", now_datetime())
        self.db_set("fulfillment_status", "Shipped")
        self.clear_order_cache()

    def mark_delivered(self):
        """Mark order as delivered."""
        if self.status not in ["Shipped", "In Transit", "Out for Delivery"]:
            frappe.throw(_("Order cannot be marked as delivered from current status"))

        self.db_set("status", "Delivered")
        self.db_set("delivered_at", now_datetime())
        self.db_set("fulfillment_status", "Delivered")
        self.db_set("fully_fulfilled", 1)

        # Update all item statuses
        for item in self.items:
            item.db_set("fulfillment_status", "Delivered")
            item.db_set("delivered_qty", item.qty)

        self.clear_order_cache()

        # Schedule escrow release if applicable
        if self.escrow_status == "Held":
            self.schedule_escrow_release()

    def mark_completed(self):
        """Mark order as completed."""
        if self.status != "Delivered":
            frappe.throw(_("Only delivered orders can be completed"))

        self.db_set("status", "Completed")
        self.db_set("completed_at", now_datetime())
        self.clear_order_cache()

    def request_cancellation(self, reason=None):
        """Request cancellation of the order."""
        if self.status in ["Shipped", "In Transit", "Delivered", "Completed", "Cancelled"]:
            frappe.throw(
                _("Order cannot be cancelled in {0} status").format(self.status)
            )

        self.db_set("cancellation_requested", 1)
        self.db_set("cancellation_reason", reason)
        self.db_set("cancellation_requested_at", now_datetime())

    def approve_cancellation(self, approver=None):
        """Approve cancellation request."""
        if not self.cancellation_requested:
            frappe.throw(_("No cancellation request pending"))

        self.db_set("cancellation_approved", 1)
        self.db_set("cancellation_approved_by", approver or frappe.session.user)
        self.db_set("status", "Cancelled")
        self.db_set("cancelled_at", now_datetime())

        # Release stock
        self.release_reserved_stock()

        # Process refund if paid
        if self.payment_status == "Paid":
            self.db_set("refund_requested", 1)
            self.db_set("refund_amount", self.paid_amount)
            self.db_set("refund_reason", "Order Cancelled")
            self.db_set("refund_status", "Pending")

        self.clear_order_cache()

    def put_on_hold(self, reason=None):
        """Put order on hold."""
        old_status = self.status
        self.db_set("status", "On Hold")
        if reason:
            self.db_set("internal_notes", f"On hold: {reason}\n\n{self.internal_notes or ''}")
        self.clear_order_cache()

    def resume_from_hold(self, resume_status=None):
        """Resume order from hold status."""
        if self.status != "On Hold":
            frappe.throw(_("Order is not on hold"))

        # Determine resume status
        if resume_status:
            self.db_set("status", resume_status)
        elif self.payment_status == "Paid":
            self.db_set("status", "Confirmed")
        else:
            self.db_set("status", "Pending")

        self.clear_order_cache()

    # =================================================================
    # Payment Methods
    # =================================================================

    def record_payment(self, amount, payment_reference=None, payment_method=None):
        """Record payment received for the order."""
        self.db_set("paid_amount", flt(self.paid_amount) + flt(amount))
        self.db_set("paid_at", now_datetime())

        if payment_reference:
            self.db_set("payment_reference", payment_reference)

        if payment_method:
            self.db_set("payment_method", payment_method)

        # Update payment status
        if flt(self.paid_amount) >= flt(self.grand_total):
            self.db_set("payment_status", "Paid")
            # Auto-confirm if enabled
            if self.auto_confirm:
                self.confirm_order()
        elif flt(self.paid_amount) > 0:
            self.db_set("payment_status", "Partially Paid")
        else:
            self.db_set("payment_status", "Pending")

        self.clear_order_cache()

    def process_refund(self, amount=None, reason=None, reference=None):
        """Process refund for the order."""
        refund_amount = flt(amount) or flt(self.grand_total)

        self.db_set("refund_amount", refund_amount)
        self.db_set("refund_status", "Refunded")
        self.db_set("refunded_at", now_datetime())

        if reason:
            self.db_set("refund_reason", reason)

        if reference:
            self.db_set("refund_reference", reference)

        # Update statuses
        if flt(refund_amount) >= flt(self.paid_amount):
            self.db_set("payment_status", "Refunded")
            self.db_set("status", "Refunded")
        else:
            self.db_set("payment_status", "Partially Refunded")

        self.clear_order_cache()

    # =================================================================
    # Escrow Methods
    # =================================================================

    def schedule_escrow_release(self, days=None):
        """Schedule escrow release after delivery."""
        if not days:
            days = 7  # Default 7 days after delivery

        release_date = add_days(nowdate(), days)
        self.db_set("escrow_release_date", release_date)
        self.db_set("escrow_status", "Held")

    def release_escrow(self):
        """Release escrowed funds to sellers."""
        if self.escrow_status != "Held":
            frappe.throw(_("No escrow funds to release"))

        self.db_set("escrow_status", "Released")
        self.db_set("escrow_released_at", now_datetime())
        self.clear_order_cache()

        # TODO: Trigger seller payouts via Sub Orders

    # =================================================================
    # Notification Methods
    # =================================================================

    def notify_sellers_new_order(self):
        """Send notification to sellers about new order."""
        sellers = set(item.seller for item in self.items)

        for seller in sellers:
            try:
                seller_doc = frappe.get_doc("Seller Profile", seller)
                if seller_doc.user:
                    # Create notification
                    frappe.publish_realtime(
                        "new_order",
                        {
                            "order_id": self.order_id,
                            "order_name": self.name,
                            "grand_total": self.grand_total
                        },
                        user=seller_doc.user
                    )
            except Exception as e:
                frappe.log_error(
                    f"Failed to notify seller {seller}: {str(e)}",
                    "Order Notification Error"
                )

    # =================================================================
    # Utility Methods
    # =================================================================

    def clear_order_cache(self):
        """Clear cached order data."""
        frappe.cache().delete_value(f"order:{self.name}")
        if self.order_id:
            frappe.cache().delete_value(f"order_by_id:{self.order_id}")

    def get_summary(self):
        """Get order summary for display."""
        return {
            "order_id": self.order_id,
            "name": self.name,
            "status": self.status,
            "payment_status": self.payment_status,
            "fulfillment_status": self.fulfillment_status,
            "buyer": self.buyer,
            "buyer_name": self.buyer_name,
            "order_date": self.order_date,
            "item_count": len(self.items),
            "seller_count": self.seller_count,
            "subtotal": self.subtotal,
            "discount_amount": self.discount_amount,
            "shipping_amount": self.shipping_amount,
            "tax_amount": self.tax_amount,
            "grand_total": self.grand_total,
            "currency": self.currency,
            "paid_amount": self.paid_amount
        }

    def get_items_by_seller(self):
        """Get items grouped by seller."""
        seller_items = {}

        for item in self.items:
            seller = item.seller
            if seller not in seller_items:
                seller_items[seller] = {
                    "seller": seller,
                    "seller_name": frappe.db.get_value(
                        "Seller Profile", seller, "seller_name"
                    ),
                    "items": []
                }
            seller_items[seller]["items"].append(item.get_display_data())

        return list(seller_items.values())


# =================================================================
# API Endpoints
# =================================================================

@frappe.whitelist()
def get_order(order_name=None, order_id=None):
    """
    Get order details.

    Args:
        order_name: Frappe document name
        order_id: Customer-facing order ID

    Returns:
        dict: Order details
    """
    if not order_name and not order_id:
        frappe.throw(_("Either order_name or order_id is required"))

    if order_id and not order_name:
        order_name = frappe.db.get_value(
            "Marketplace Order", {"order_id": order_id}, "name"
        )

    if not order_name:
        return {"error": _("Order not found")}

    order = frappe.get_doc("Marketplace Order", order_name)

    # Permission check
    if frappe.session.user != "Administrator":
        if order.buyer != frappe.session.user:
            # Check if user is a seller with items in this order
            seller = frappe.db.get_value(
                "Seller Profile", {"user": frappe.session.user}, "name"
            )
            if not seller or seller not in [i.seller for i in order.items]:
                if not frappe.has_permission("Marketplace Order", "read"):
                    return {"error": _("Not permitted to view this order")}

    items = []
    for item in order.items:
        items.append(item.get_display_data())

    return {
        "name": order.name,
        "order_id": order.order_id,
        "status": order.status,
        "payment_status": order.payment_status,
        "fulfillment_status": order.fulfillment_status,
        "buyer": order.buyer,
        "buyer_name": order.buyer_name,
        "order_date": order.order_date,
        "items": items,
        "summary": order.get_summary(),
        "sellers": order.get_items_by_seller(),
        "shipping_address": {
            "name": order.shipping_address_name,
            "line1": order.shipping_address_line1,
            "line2": order.shipping_address_line2,
            "city": order.shipping_city,
            "state": order.shipping_state,
            "postal_code": order.shipping_postal_code,
            "country": order.shipping_country,
            "phone": order.shipping_phone
        }
    }


@frappe.whitelist()
def get_buyer_orders(buyer=None, status=None, page=1, page_size=20):
    """
    Get orders for a buyer.

    Args:
        buyer: User name (defaults to current user)
        status: Filter by status
        page: Page number
        page_size: Results per page

    Returns:
        dict: Orders with pagination
    """
    if not buyer:
        buyer = frappe.session.user

    if buyer != frappe.session.user:
        if not frappe.has_permission("Marketplace Order", "read"):
            frappe.throw(_("Not permitted to view these orders"))

    filters = {"buyer": buyer, "docstatus": ["!=", 2]}
    if status:
        filters["status"] = status

    start = (cint(page) - 1) * cint(page_size)
    total = frappe.db.count("Marketplace Order", filters)

    orders = frappe.get_all(
        "Marketplace Order",
        filters=filters,
        fields=[
            "name", "order_id", "status", "payment_status", "fulfillment_status",
            "order_date", "grand_total", "currency", "seller_count"
        ],
        order_by="creation DESC",
        start=start,
        limit_page_length=cint(page_size)
    )

    return {
        "orders": orders,
        "total": total,
        "page": cint(page),
        "page_size": cint(page_size),
        "total_pages": (total + cint(page_size) - 1) // cint(page_size)
    }


@frappe.whitelist()
def get_seller_orders(seller=None, status=None, page=1, page_size=20):
    """
    Get orders containing items from a seller.

    Args:
        seller: Seller Profile name
        status: Filter by status
        page: Page number
        page_size: Results per page

    Returns:
        dict: Orders with pagination
    """
    if not seller:
        seller = frappe.db.get_value(
            "Seller Profile", {"user": frappe.session.user}, "name"
        )

    if not seller:
        return {"error": _("Seller profile not found")}

    # Get orders that have items from this seller
    order_names = frappe.db.sql("""
        SELECT DISTINCT moi.parent
        FROM `tabMarketplace Order Item` moi
        JOIN `tabMarketplace Order` mo ON mo.name = moi.parent
        WHERE moi.seller = %(seller)s
        AND mo.docstatus != 2
        {status_filter}
        ORDER BY mo.creation DESC
        LIMIT %(start)s, %(limit)s
    """.format(
        status_filter=f"AND mo.status = %(status)s" if status else ""
    ), {
        "seller": seller,
        "status": status,
        "start": (cint(page) - 1) * cint(page_size),
        "limit": cint(page_size)
    }, as_dict=True)

    # Get total count
    total_result = frappe.db.sql("""
        SELECT COUNT(DISTINCT moi.parent) as total
        FROM `tabMarketplace Order Item` moi
        JOIN `tabMarketplace Order` mo ON mo.name = moi.parent
        WHERE moi.seller = %(seller)s
        AND mo.docstatus != 2
        {status_filter}
    """.format(
        status_filter=f"AND mo.status = %(status)s" if status else ""
    ), {"seller": seller, "status": status}, as_dict=True)

    total = total_result[0].total if total_result else 0

    orders = []
    for row in order_names:
        order = frappe.get_doc("Marketplace Order", row.parent)
        seller_items = [i for i in order.items if i.seller == seller]
        seller_total = sum(flt(i.line_total) for i in seller_items)

        orders.append({
            "name": order.name,
            "order_id": order.order_id,
            "status": order.status,
            "payment_status": order.payment_status,
            "order_date": order.order_date,
            "buyer": order.buyer,
            "buyer_name": order.buyer_name,
            "seller_item_count": len(seller_items),
            "seller_total": seller_total,
            "currency": order.currency
        })

    return {
        "orders": orders,
        "total": total,
        "page": cint(page),
        "page_size": cint(page_size),
        "total_pages": (total + cint(page_size) - 1) // cint(page_size)
    }


@frappe.whitelist()
def update_order_status(order_name, action, reason=None):
    """
    Update order status.

    Args:
        order_name: Order name
        action: Action (confirm, process, ship, deliver, complete, cancel, hold, resume)
        reason: Reason for status change

    Returns:
        dict: Updated status
    """
    order = frappe.get_doc("Marketplace Order", order_name)

    # Permission check
    if not frappe.has_permission("Marketplace Order", "write"):
        frappe.throw(_("Not permitted to update this order"))

    if action == "confirm":
        order.confirm_order()
    elif action == "process":
        order.start_processing()
    elif action == "ship":
        order.mark_shipped()
    elif action == "deliver":
        order.mark_delivered()
    elif action == "complete":
        order.mark_completed()
    elif action == "cancel":
        order.request_cancellation(reason)
    elif action == "approve_cancel":
        order.approve_cancellation()
    elif action == "hold":
        order.put_on_hold(reason)
    elif action == "resume":
        order.resume_from_hold()
    else:
        frappe.throw(_("Invalid action: {0}").format(action))

    return {
        "status": "success",
        "order_status": order.status,
        "message": _("Order status updated to {0}").format(order.status)
    }


@frappe.whitelist()
def get_order_statistics(seller=None, days=30):
    """
    Get order statistics.

    Args:
        seller: Filter by seller
        days: Number of days to analyze

    Returns:
        dict: Order statistics
    """
    from_date = add_days(nowdate(), -cint(days))

    if seller:
        # Seller-specific stats
        stats = frappe.db.sql("""
            SELECT
                mo.status,
                COUNT(DISTINCT mo.name) as order_count,
                SUM(moi.line_total) as total_value
            FROM `tabMarketplace Order` mo
            JOIN `tabMarketplace Order Item` moi ON moi.parent = mo.name
            WHERE moi.seller = %(seller)s
            AND mo.order_date >= %(from_date)s
            AND mo.docstatus != 2
            GROUP BY mo.status
        """, {"seller": seller, "from_date": from_date}, as_dict=True)
    else:
        # Platform-wide stats
        stats = frappe.db.sql("""
            SELECT
                status,
                COUNT(*) as order_count,
                SUM(grand_total) as total_value
            FROM `tabMarketplace Order`
            WHERE order_date >= %(from_date)s
            AND docstatus != 2
            GROUP BY status
        """, {"from_date": from_date}, as_dict=True)

    status_data = {s.status: {"count": s.order_count, "value": s.total_value} for s in stats}

    total_orders = sum(s.order_count for s in stats)
    total_value = sum(flt(s.total_value) for s in stats)

    return {
        "period_days": cint(days),
        "total_orders": total_orders,
        "total_value": total_value,
        "status_breakdown": status_data,
        "average_order_value": total_value / total_orders if total_orders > 0 else 0
    }

# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import (
    cint, flt, getdate, nowdate, now_datetime,
    add_days, get_datetime, date_diff
)


class SubOrder(Document):
    """
    Sub Order DocType for TR-TradeHub.

    Represents a seller's portion of a Marketplace Order.
    Each seller in a multi-seller order gets their own Sub Order
    to track fulfillment, shipping, and payout independently.

    Features:
    - Per-seller order management
    - Independent fulfillment tracking
    - Commission and payout calculation
    - Escrow integration
    - Turkish E-Invoice support
    - Return/refund handling
    - ERPNext integration
    """

    def before_insert(self):
        """Set default values before creating a new sub order."""
        # Generate unique sub order ID
        if not self.sub_order_id:
            self.sub_order_id = self.generate_sub_order_id()

        # Set order date from parent if not provided
        if not self.order_date and self.marketplace_order:
            self.order_date = frappe.db.get_value(
                "Marketplace Order", self.marketplace_order, "order_date"
            ) or nowdate()

        # Copy buyer details from parent order
        if self.marketplace_order and not self.buyer_name:
            self.copy_buyer_details()

    def validate(self):
        """Validate sub order data before saving."""
        self.validate_seller()
        self.validate_items()
        self.validate_addresses()
        self.validate_status_transitions()
        self.calculate_totals()

    def on_update(self):
        """Actions after sub order is updated."""
        self.clear_sub_order_cache()

        # Update parent order fulfillment status
        self.update_parent_order_status()

    # =================================================================
    # Helper Methods
    # =================================================================

    def generate_sub_order_id(self):
        """Generate a unique sub order identifier."""
        return f"SUB-{frappe.generate_hash(length=10).upper()}"

    def copy_buyer_details(self):
        """Copy buyer details from parent Marketplace Order."""
        if not self.marketplace_order:
            return

        parent = frappe.get_doc("Marketplace Order", self.marketplace_order)

        if not self.buyer:
            self.buyer = parent.buyer
        if not self.buyer_name:
            self.buyer_name = parent.buyer_name
        if not self.buyer_email:
            self.buyer_email = parent.buyer_email
        if not self.buyer_phone:
            self.buyer_phone = parent.buyer_phone
        if not self.buyer_tax_id:
            self.buyer_tax_id = parent.buyer_tax_id

        # Copy shipping address
        if not self.shipping_address_line1:
            self.shipping_address_name = parent.shipping_address_name
            self.shipping_address_line1 = parent.shipping_address_line1
            self.shipping_address_line2 = parent.shipping_address_line2
            self.shipping_city = parent.shipping_city
            self.shipping_state = parent.shipping_state
            self.shipping_postal_code = parent.shipping_postal_code
            self.shipping_country = parent.shipping_country
            self.shipping_phone = parent.shipping_phone

        # Copy invoice settings
        self.requires_invoice = parent.requires_invoice
        self.invoice_type = parent.invoice_type
        self.e_invoice_enabled = parent.e_invoice_enabled

    # =================================================================
    # Validation Methods
    # =================================================================

    def validate_seller(self):
        """Validate seller information."""
        if not self.seller:
            frappe.throw(_("Seller is required"))

        if not frappe.db.exists("Seller Profile", self.seller):
            frappe.throw(_("Seller Profile {0} does not exist").format(self.seller))

        # Verify seller is active
        seller_status = frappe.db.get_value(
            "Seller Profile", self.seller, "verification_status"
        )
        if seller_status not in ["Verified", "Active"]:
            frappe.msgprint(
                _("Warning: Seller {0} is not verified").format(self.seller)
            )

    def validate_items(self):
        """Validate sub order items."""
        if not self.items:
            frappe.throw(_("Sub Order must have at least one item"))

        for item in self.items:
            # Validate listing exists
            if not frappe.db.exists("Listing", item.listing):
                frappe.throw(
                    _("Listing {0} does not exist").format(item.listing)
                )

            # Validate quantity
            if flt(item.qty) <= 0:
                frappe.throw(
                    _("Quantity must be greater than 0 for {0}").format(item.title)
                )

            # Populate item details if missing
            if not item.title:
                listing = frappe.get_doc("Listing", item.listing)
                item.title = listing.title
                item.sku = listing.sku
                item.primary_image = listing.primary_image

    def validate_addresses(self):
        """Validate shipping address."""
        if not self.shipping_address_line1:
            frappe.throw(_("Shipping address is required"))

        if not self.shipping_city:
            frappe.throw(_("Shipping city is required"))

        if not self.shipping_country:
            self.shipping_country = "Turkey"

    def validate_status_transitions(self):
        """Validate sub order status transitions."""
        if self.is_new():
            return

        old_status = frappe.db.get_value("Sub Order", self.name, "status")

        # Define valid transitions
        valid_transitions = {
            "Pending": ["Accepted", "Cancelled", "On Hold"],
            "Accepted": ["Processing", "Cancelled", "On Hold"],
            "Processing": ["Packed", "Cancelled", "On Hold"],
            "Packed": ["Shipped", "Cancelled", "On Hold"],
            "Shipped": ["In Transit", "Delivered", "On Hold"],
            "In Transit": ["Out for Delivery", "Delivered", "On Hold"],
            "Out for Delivery": ["Delivered", "On Hold"],
            "Delivered": ["Completed", "Refunded", "Disputed"],
            "Completed": ["Refunded", "Disputed"],
            "Cancelled": ["Refunded"],
            "Refunded": [],
            "On Hold": ["Pending", "Accepted", "Processing", "Cancelled"],
            "Disputed": ["Refunded", "Completed"]
        }

        if old_status and self.status != old_status:
            if self.status not in valid_transitions.get(old_status, []):
                frappe.throw(
                    _("Cannot change status from {0} to {1}").format(
                        old_status, self.status
                    )
                )

    # =================================================================
    # Calculation Methods
    # =================================================================

    def calculate_totals(self):
        """Calculate all sub order totals from line items."""
        subtotal = 0
        tax_amount = 0
        discount_amount = 0
        shipping_amount = 0
        commission_amount = 0

        for item in self.items:
            # Ensure item totals are calculated
            item.calculate_totals()

            subtotal += flt(item.line_subtotal) - flt(item.discount_amount)
            tax_amount += flt(item.tax_amount)
            discount_amount += flt(item.discount_amount)
            shipping_amount += flt(item.shipping_amount)
            commission_amount += flt(item.commission_amount)

        self.subtotal = subtotal
        self.tax_amount = tax_amount
        self.discount_amount = discount_amount
        self.shipping_amount = shipping_amount or flt(self.shipping_amount)
        self.commission_amount = commission_amount

        # Grand total
        self.grand_total = (
            flt(self.subtotal)
            + flt(self.shipping_amount)
            + flt(self.tax_amount)
        )

        # Commission rate (average)
        if flt(self.subtotal) > 0:
            self.commission_rate = (
                flt(self.commission_amount) / flt(self.subtotal) * 100
            )

        # Seller payout = grand_total - commission
        self.seller_payout = flt(self.grand_total) - flt(self.commission_amount)

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
    # Status Methods
    # =================================================================

    def accept_order(self):
        """Accept the sub order for processing."""
        if self.status != "Pending":
            frappe.throw(_("Only pending orders can be accepted"))

        self.db_set("status", "Accepted")
        self.db_set("fulfillment_status", "Accepted")
        self.db_set("accepted_at", now_datetime())
        self.clear_sub_order_cache()

        # Notify buyer
        self.notify_buyer("order_accepted")

    def start_processing(self):
        """Mark sub order as processing."""
        if self.status not in ["Pending", "Accepted"]:
            frappe.throw(_("Cannot start processing from current status"))

        self.db_set("status", "Processing")
        self.db_set("fulfillment_status", "Processing")
        self.db_set("processing_started_at", now_datetime())
        self.clear_sub_order_cache()

    def mark_packed(self):
        """Mark sub order as packed."""
        if self.status not in ["Accepted", "Processing"]:
            frappe.throw(_("Order cannot be marked as packed from current status"))

        self.db_set("status", "Packed")
        self.db_set("fulfillment_status", "Packed")
        self.db_set("packed_at", now_datetime())

        # Update item statuses
        for item in self.items:
            item.db_set("fulfillment_status", "Packed")

        self.clear_sub_order_cache()

    def ship_order(self, carrier=None, tracking_number=None, tracking_url=None):
        """Mark sub order as shipped with tracking info."""
        if self.status not in ["Processing", "Packed"]:
            frappe.throw(_("Order cannot be shipped from current status"))

        if not tracking_number and not carrier:
            frappe.throw(_("Tracking number or carrier is required for shipping"))

        # Update shipment info
        if carrier:
            self.db_set("carrier", carrier)
        if tracking_number:
            self.db_set("tracking_number", tracking_number)
        if tracking_url:
            self.db_set("tracking_url", tracking_url)

        self.db_set("status", "Shipped")
        self.db_set("fulfillment_status", "Shipped")
        self.db_set("shipped_at", now_datetime())

        # Update item statuses
        for item in self.items:
            item.db_set("fulfillment_status", "Shipped")
            if tracking_number:
                item.db_set("tracking_number", tracking_number)
            if carrier:
                item.db_set("carrier", carrier)

        self.clear_sub_order_cache()

        # Notify buyer
        self.notify_buyer("order_shipped")

    def mark_in_transit(self):
        """Mark sub order as in transit."""
        if self.status != "Shipped":
            frappe.throw(_("Only shipped orders can be marked in transit"))

        self.db_set("status", "In Transit")
        self.db_set("fulfillment_status", "In Transit")

        for item in self.items:
            item.db_set("fulfillment_status", "In Transit")

        self.clear_sub_order_cache()

    def mark_out_for_delivery(self):
        """Mark sub order as out for delivery."""
        if self.status not in ["Shipped", "In Transit"]:
            frappe.throw(_("Cannot mark out for delivery from current status"))

        self.db_set("status", "Out for Delivery")
        self.db_set("fulfillment_status", "Out for Delivery")

        for item in self.items:
            item.db_set("fulfillment_status", "Out for Delivery")

        self.clear_sub_order_cache()

        # Notify buyer
        self.notify_buyer("out_for_delivery")

    def mark_delivered(self, delivery_date=None):
        """Mark sub order as delivered."""
        if self.status not in ["Shipped", "In Transit", "Out for Delivery"]:
            frappe.throw(_("Order cannot be marked as delivered from current status"))

        self.db_set("status", "Delivered")
        self.db_set("fulfillment_status", "Delivered")
        self.db_set("delivered_at", now_datetime())
        self.db_set("actual_delivery_date", delivery_date or nowdate())
        self.db_set("fully_fulfilled", 1)

        # Update all item statuses
        for item in self.items:
            item.db_set("fulfillment_status", "Delivered")
            item.db_set("delivered_qty", item.qty)

        self.clear_sub_order_cache()

        # Schedule escrow release if applicable
        if self.escrow_status == "Held":
            self.schedule_escrow_release()

        # Notify buyer
        self.notify_buyer("order_delivered")

        # Update parent order
        self.update_parent_order_status()

    def mark_completed(self):
        """Mark sub order as completed."""
        if self.status != "Delivered":
            frappe.throw(_("Only delivered orders can be completed"))

        self.db_set("status", "Completed")
        self.db_set("completed_at", now_datetime())
        self.clear_sub_order_cache()

        # Process seller payout if escrow released
        if self.escrow_status == "Released":
            self.schedule_seller_payout()

        # Update parent order
        self.update_parent_order_status()

    def put_on_hold(self, reason=None):
        """Put sub order on hold."""
        old_status = self.status
        self.db_set("status", "On Hold")
        if reason:
            notes = f"On hold: {reason}\n\n{self.internal_notes or ''}"
            self.db_set("internal_notes", notes)
        self.clear_sub_order_cache()

        # Notify seller
        self.notify_seller("order_on_hold")

    def resume_from_hold(self, resume_status=None):
        """Resume sub order from hold status."""
        if self.status != "On Hold":
            frappe.throw(_("Sub Order is not on hold"))

        # Determine resume status
        if resume_status:
            self.db_set("status", resume_status)
        elif self.accepted_at:
            self.db_set("status", "Accepted")
        else:
            self.db_set("status", "Pending")

        self.clear_sub_order_cache()

    # =================================================================
    # Cancellation Methods
    # =================================================================

    def request_cancellation(self, reason=None, requested_by="seller"):
        """Request cancellation of the sub order."""
        if self.status in ["Shipped", "In Transit", "Delivered", "Completed", "Cancelled"]:
            frappe.throw(
                _("Sub Order cannot be cancelled in {0} status").format(self.status)
            )

        self.db_set("cancellation_requested", 1)
        self.db_set("cancellation_reason", reason)
        self.db_set("cancellation_requested_at", now_datetime())
        self.clear_sub_order_cache()

        # Notify appropriate party
        if requested_by == "seller":
            self.notify_buyer("cancellation_requested")
        else:
            self.notify_seller("cancellation_requested")

    def approve_cancellation(self, approver=None):
        """Approve cancellation request."""
        if not self.cancellation_requested:
            frappe.throw(_("No cancellation request pending"))

        self.db_set("cancellation_approved", 1)
        self.db_set("cancellation_approved_by", approver or frappe.session.user)
        self.db_set("status", "Cancelled")
        self.db_set("fulfillment_status", "Cancelled")
        self.db_set("cancelled_at", now_datetime())

        # Update all item statuses
        for item in self.items:
            item.db_set("fulfillment_status", "Cancelled")

        # Release reserved stock
        self.release_reserved_stock()

        # Process refund if payment received
        if self.payment_status == "Paid":
            self.db_set("refund_requested", 1)
            self.db_set("refund_amount", self.grand_total)
            self.db_set("refund_reason", "Order Cancelled")
            self.db_set("refund_status", "Pending")

        self.clear_sub_order_cache()

        # Update parent order
        self.update_parent_order_status()

        # Notify parties
        self.notify_buyer("order_cancelled")
        self.notify_seller("order_cancelled")

    def reject_cancellation(self, reason=None):
        """Reject cancellation request."""
        if not self.cancellation_requested:
            frappe.throw(_("No cancellation request pending"))

        self.db_set("cancellation_requested", 0)
        self.db_set("cancellation_reason", None)
        self.db_set("cancellation_requested_at", None)

        if reason:
            notes = f"Cancellation rejected: {reason}\n\n{self.internal_notes or ''}"
            self.db_set("internal_notes", notes)

        self.clear_sub_order_cache()

    # =================================================================
    # Refund Methods
    # =================================================================

    def request_refund(self, amount=None, reason=None):
        """Request refund for the sub order."""
        if self.refund_requested:
            frappe.throw(_("Refund already requested"))

        refund_amount = flt(amount) or flt(self.grand_total)

        self.db_set("refund_requested", 1)
        self.db_set("refund_amount", refund_amount)
        self.db_set("refund_reason", reason)
        self.db_set("refund_status", "Pending")
        self.clear_sub_order_cache()

    def approve_refund(self):
        """Approve refund request."""
        if not self.refund_requested:
            frappe.throw(_("No refund request pending"))

        self.db_set("refund_status", "Approved")
        self.clear_sub_order_cache()

    def process_refund(self, reference=None):
        """Process approved refund."""
        if self.refund_status != "Approved":
            frappe.throw(_("Refund must be approved before processing"))

        self.db_set("refund_status", "Processing")

        # In a real implementation, this would call the payment gateway
        # For now, just mark as refunded
        self.complete_refund(reference)

    def complete_refund(self, reference=None):
        """Complete the refund."""
        self.db_set("refund_status", "Refunded")
        self.db_set("refunded_at", now_datetime())

        if reference:
            self.db_set("refund_reference", reference)

        # Update statuses
        if flt(self.refund_amount) >= flt(self.grand_total):
            self.db_set("payment_status", "Refunded")
            self.db_set("status", "Refunded")
        else:
            self.db_set("payment_status", "Partially Refunded")

        self.clear_sub_order_cache()

        # Update parent order
        self.update_parent_order_status()

        # Notify buyer
        self.notify_buyer("refund_processed")

    # =================================================================
    # Return Methods
    # =================================================================

    def request_return(self, reason=None):
        """Request return for delivered items."""
        if self.status != "Delivered":
            frappe.throw(_("Only delivered orders can be returned"))

        self.db_set("return_requested", 1)
        self.db_set("return_reason", reason)
        self.db_set("return_requested_at", now_datetime())
        self.db_set("return_status", "Pending")
        self.clear_sub_order_cache()

        # Notify seller
        self.notify_seller("return_requested")

    def approve_return(self):
        """Approve return request."""
        if not self.return_requested:
            frappe.throw(_("No return request pending"))

        self.db_set("return_status", "Approved")
        self.clear_sub_order_cache()

        # Notify buyer with return instructions
        self.notify_buyer("return_approved")

    def ship_return(self, tracking_number=None):
        """Mark return as shipped back."""
        if self.return_status != "Approved":
            frappe.throw(_("Return must be approved before shipping"))

        if tracking_number:
            self.db_set("return_tracking_number", tracking_number)

        self.db_set("return_status", "Shipped Back")
        self.clear_sub_order_cache()

    def receive_return(self):
        """Mark return as received by seller."""
        if self.return_status != "Shipped Back":
            frappe.throw(_("Return must be shipped before receiving"))

        self.db_set("return_status", "Received")
        self.db_set("return_received_at", now_datetime())

        # Update item quantities
        for item in self.items:
            item.db_set("returned_qty", item.qty)
            item.db_set("fulfillment_status", "Returned")

        self.update_fulfillment_counts()
        self.clear_sub_order_cache()

        # Trigger refund
        self.request_refund(reason="Item Returned")

    def complete_return(self):
        """Complete the return process."""
        if self.return_status != "Received":
            frappe.throw(_("Return must be received before completing"))

        self.db_set("return_status", "Completed")
        self.clear_sub_order_cache()

    # =================================================================
    # Escrow Methods
    # =================================================================

    def schedule_escrow_release(self, days=None):
        """Schedule escrow release after delivery."""
        if not days:
            # Default to 7 days after delivery
            days = 7

        release_date = add_days(nowdate(), days)
        self.db_set("escrow_release_date", release_date)
        self.db_set("escrow_status", "Held")
        self.clear_sub_order_cache()

    def release_escrow(self):
        """Release escrowed funds."""
        if self.escrow_status != "Held":
            frappe.throw(_("No escrow funds to release"))

        self.db_set("escrow_status", "Released")
        self.db_set("escrow_released_at", now_datetime())
        self.clear_sub_order_cache()

        # Schedule seller payout
        self.schedule_seller_payout()

    def dispute_escrow(self, reason=None):
        """Put escrow in dispute."""
        if self.escrow_status not in ["Held", "Pending"]:
            frappe.throw(_("Cannot dispute escrow in current status"))

        self.db_set("escrow_status", "Disputed")
        self.db_set("status", "Disputed")

        if reason:
            notes = f"Escrow disputed: {reason}\n\n{self.internal_notes or ''}"
            self.db_set("internal_notes", notes)

        self.clear_sub_order_cache()

    # =================================================================
    # Payout Methods
    # =================================================================

    def schedule_seller_payout(self):
        """Schedule payout to seller and credit seller balance."""
        if self.payout_status != "Pending":
            return

        try:
            # Credit seller balance and schedule escrow release
            from tradehub_core.tradehub_core.utils.seller_payout import on_sub_order_completed
            result = on_sub_order_completed(self.name)

            # Log the result
            frappe.log_error(
                f"Seller payout scheduled for {self.name}: {result}",
                "Seller Payout Scheduled"
            )

        except Exception as e:
            # Log error but don't fail the order completion
            frappe.log_error(
                f"Failed to credit seller balance for {self.name}: {str(e)}",
                "Seller Payout Error"
            )
            # Still update the status
            self.db_set("payout_status", "Scheduled")

        self.clear_sub_order_cache()

    def process_seller_payout(self, reference=None):
        """Process payout to seller - releases escrow to available balance."""
        if self.payout_status not in ["Scheduled", "Processing", "Released"]:
            frappe.throw(_("Payout cannot be processed from current status"))

        try:
            # Release escrow to seller's available balance
            from tradehub_core.tradehub_core.utils.seller_payout import release_escrow_to_balance
            result = release_escrow_to_balance(
                seller=self.seller,
                sub_order=self.name,
                amount=flt(self.seller_payout)
            )

            self.db_set("payout_status", "Paid")
            if reference:
                self.db_set("payout_reference", reference)

            frappe.log_error(
                f"Seller payout processed for {self.name}: {result}",
                "Seller Payout Processed"
            )

        except Exception as e:
            frappe.log_error(
                f"Failed to process payout for {self.name}: {str(e)}",
                "Seller Payout Process Error"
            )
            raise

        self.clear_sub_order_cache()

        # Notify seller
        self.notify_seller("payout_processed")

    # =================================================================
    # Stock Methods
    # =================================================================

    def release_reserved_stock(self):
        """Release reserved stock for all items."""
        for item in self.items:
            try:
                if frappe.db.exists("Listing", item.listing):
                    listing = frappe.get_doc("Listing", item.listing)
                    if hasattr(listing, 'release_reservation'):
                        listing.release_reservation(flt(item.qty))
            except Exception as e:
                frappe.log_error(
                    f"Failed to release stock for {item.listing}: {str(e)}",
                    "Sub Order Stock Release Error"
                )

    # =================================================================
    # Notification Methods
    # =================================================================

    def notify_buyer(self, event_type):
        """Send notification to buyer."""
        try:
            frappe.publish_realtime(
                f"sub_order_{event_type}",
                {
                    "sub_order_id": self.sub_order_id,
                    "sub_order_name": self.name,
                    "marketplace_order": self.marketplace_order,
                    "seller": self.seller,
                    "status": self.status
                },
                user=self.buyer
            )
        except Exception as e:
            frappe.log_error(
                f"Failed to notify buyer: {str(e)}",
                "Sub Order Notification Error"
            )

    def notify_seller(self, event_type):
        """Send notification to seller."""
        try:
            seller_user = frappe.db.get_value(
                "Seller Profile", self.seller, "user"
            )
            if seller_user:
                frappe.publish_realtime(
                    f"sub_order_{event_type}",
                    {
                        "sub_order_id": self.sub_order_id,
                        "sub_order_name": self.name,
                        "marketplace_order": self.marketplace_order,
                        "status": self.status
                    },
                    user=seller_user
                )
        except Exception as e:
            frappe.log_error(
                f"Failed to notify seller: {str(e)}",
                "Sub Order Notification Error"
            )

    # =================================================================
    # Parent Order Update Methods
    # =================================================================

    def update_parent_order_status(self):
        """Update parent Marketplace Order status based on sub orders."""
        if not self.marketplace_order:
            return

        try:
            # Get all sub orders for this marketplace order
            sub_orders = frappe.get_all(
                "Sub Order",
                filters={"marketplace_order": self.marketplace_order},
                fields=["status", "fulfillment_status"]
            )

            if not sub_orders:
                return

            # Determine aggregate status
            statuses = [so.status for so in sub_orders]
            fulfillment_statuses = [so.fulfillment_status for so in sub_orders]

            # All cancelled
            if all(s == "Cancelled" for s in statuses):
                parent_status = "Cancelled"
            # All completed
            elif all(s == "Completed" for s in statuses):
                parent_status = "Completed"
            # All delivered
            elif all(s in ["Delivered", "Completed"] for s in statuses):
                parent_status = "Delivered"
            # Any shipped
            elif any(s in ["Shipped", "In Transit", "Out for Delivery"] for s in statuses):
                parent_status = "Shipped"
            # Any processing
            elif any(s in ["Processing", "Packed"] for s in statuses):
                parent_status = "Processing"
            # Any disputed
            elif any(s == "Disputed" for s in statuses):
                parent_status = "Disputed"
            else:
                parent_status = None

            if parent_status:
                frappe.db.set_value(
                    "Marketplace Order",
                    self.marketplace_order,
                    "status",
                    parent_status
                )

            # Update fulfillment counts
            delivered_count = sum(
                1 for s in fulfillment_statuses if s == "Delivered"
            )
            if delivered_count == len(sub_orders):
                frappe.db.set_value(
                    "Marketplace Order",
                    self.marketplace_order,
                    "fulfillment_status",
                    "Delivered"
                )
                frappe.db.set_value(
                    "Marketplace Order",
                    self.marketplace_order,
                    "fully_fulfilled",
                    1
                )

        except Exception as e:
            frappe.log_error(
                f"Failed to update parent order status: {str(e)}",
                "Sub Order Parent Update Error"
            )

    # =================================================================
    # Utility Methods
    # =================================================================

    def clear_sub_order_cache(self):
        """Clear cached sub order data."""
        frappe.cache().delete_value(f"sub_order:{self.name}")
        if self.sub_order_id:
            frappe.cache().delete_value(f"sub_order_by_id:{self.sub_order_id}")

    def get_summary(self):
        """Get sub order summary for display."""
        return {
            "sub_order_id": self.sub_order_id,
            "name": self.name,
            "marketplace_order": self.marketplace_order,
            "seller": self.seller,
            "status": self.status,
            "payment_status": self.payment_status,
            "fulfillment_status": self.fulfillment_status,
            "payout_status": self.payout_status,
            "buyer": self.buyer,
            "buyer_name": self.buyer_name,
            "order_date": self.order_date,
            "item_count": len(self.items),
            "subtotal": self.subtotal,
            "discount_amount": self.discount_amount,
            "shipping_amount": self.shipping_amount,
            "tax_amount": self.tax_amount,
            "grand_total": self.grand_total,
            "commission_amount": self.commission_amount,
            "seller_payout": self.seller_payout,
            "currency": self.currency,
            "carrier": self.carrier,
            "tracking_number": self.tracking_number
        }

    def get_tracking_info(self):
        """Get tracking information."""
        return {
            "carrier": self.carrier,
            "tracking_number": self.tracking_number,
            "tracking_url": self.tracking_url or self.generate_tracking_url(),
            "shipped_at": self.shipped_at,
            "estimated_delivery_date": self.estimated_delivery_date,
            "actual_delivery_date": self.actual_delivery_date,
            "status": self.fulfillment_status
        }

    def generate_tracking_url(self):
        """Generate tracking URL based on carrier."""
        if not self.tracking_number or not self.carrier:
            return None

        carrier_urls = {
            "Yurtici Kargo": f"https://www.yurticikargo.com/tr/online-servisler/gonderi-sorgula?code={self.tracking_number}",
            "Aras Kargo": f"https://www.araskargo.com.tr/trmall/kargotakip.aspx?q={self.tracking_number}",
            "MNG Kargo": f"https://www.mngkargo.com.tr/gonderi-takip/?no={self.tracking_number}",
            "SuratKargo": f"https://www.suratkargo.com.tr/gonderi-takip?takipNo={self.tracking_number}",
            "PTT Kargo": f"https://gonderitakip.ptt.gov.tr/?barkod={self.tracking_number}",
            "UPS": f"https://www.ups.com/track?tracknum={self.tracking_number}",
            "DHL": f"https://www.dhl.com/tr-en/home/tracking.html?tracking-id={self.tracking_number}",
            "FedEx": f"https://www.fedex.com/fedextrack/?tracknumbers={self.tracking_number}"
        }

        return carrier_urls.get(self.carrier)


# =================================================================
# API Endpoints
# =================================================================

@frappe.whitelist()
def get_sub_order(sub_order_name=None, sub_order_id=None):
    """
    Get sub order details.

    Args:
        sub_order_name: Frappe document name
        sub_order_id: Customer-facing sub order ID

    Returns:
        dict: Sub order details
    """
    if not sub_order_name and not sub_order_id:
        frappe.throw(_("Either sub_order_name or sub_order_id is required"))

    if sub_order_id and not sub_order_name:
        sub_order_name = frappe.db.get_value(
            "Sub Order", {"sub_order_id": sub_order_id}, "name"
        )

    if not sub_order_name:
        return {"error": _("Sub Order not found")}

    sub_order = frappe.get_doc("Sub Order", sub_order_name)

    # Permission check
    if frappe.session.user != "Administrator":
        seller_user = frappe.db.get_value(
            "Seller Profile", sub_order.seller, "user"
        )
        if sub_order.buyer != frappe.session.user and seller_user != frappe.session.user:
            if not frappe.has_permission("Sub Order", "read"):
                return {"error": _("Not permitted to view this sub order")}

    items = []
    for item in sub_order.items:
        items.append(item.get_display_data())

    return {
        "name": sub_order.name,
        "sub_order_id": sub_order.sub_order_id,
        "marketplace_order": sub_order.marketplace_order,
        "seller": sub_order.seller,
        "status": sub_order.status,
        "payment_status": sub_order.payment_status,
        "fulfillment_status": sub_order.fulfillment_status,
        "payout_status": sub_order.payout_status,
        "buyer": sub_order.buyer,
        "buyer_name": sub_order.buyer_name,
        "order_date": sub_order.order_date,
        "items": items,
        "summary": sub_order.get_summary(),
        "tracking": sub_order.get_tracking_info(),
        "shipping_address": {
            "name": sub_order.shipping_address_name,
            "line1": sub_order.shipping_address_line1,
            "line2": sub_order.shipping_address_line2,
            "city": sub_order.shipping_city,
            "state": sub_order.shipping_state,
            "postal_code": sub_order.shipping_postal_code,
            "country": sub_order.shipping_country,
            "phone": sub_order.shipping_phone
        }
    }


@frappe.whitelist()
def get_seller_sub_orders(seller=None, status=None, page=1, page_size=20):
    """
    Get sub orders for a seller.

    Args:
        seller: Seller Profile name
        status: Filter by status
        page: Page number
        page_size: Results per page

    Returns:
        dict: Sub orders with pagination
    """
    if not seller:
        seller = frappe.db.get_value(
            "Seller Profile", {"user": frappe.session.user}, "name"
        )

    if not seller:
        return {"error": _("Seller profile not found")}

    filters = {"seller": seller}
    if status:
        filters["status"] = status

    start = (cint(page) - 1) * cint(page_size)
    total = frappe.db.count("Sub Order", filters)

    sub_orders = frappe.get_all(
        "Sub Order",
        filters=filters,
        fields=[
            "name", "sub_order_id", "marketplace_order", "status",
            "payment_status", "fulfillment_status", "payout_status",
            "order_date", "grand_total", "seller_payout", "currency",
            "buyer_name", "carrier", "tracking_number"
        ],
        order_by="creation DESC",
        start=start,
        limit_page_length=cint(page_size)
    )

    return {
        "sub_orders": sub_orders,
        "total": total,
        "page": cint(page),
        "page_size": cint(page_size),
        "total_pages": (total + cint(page_size) - 1) // cint(page_size)
    }


@frappe.whitelist()
def get_sub_orders_by_marketplace_order(marketplace_order):
    """
    Get all sub orders for a marketplace order.

    Args:
        marketplace_order: Marketplace Order name

    Returns:
        list: Sub orders for the marketplace order
    """
    if not marketplace_order:
        frappe.throw(_("Marketplace Order is required"))

    sub_orders = frappe.get_all(
        "Sub Order",
        filters={"marketplace_order": marketplace_order},
        fields=[
            "name", "sub_order_id", "seller", "status",
            "payment_status", "fulfillment_status", "payout_status",
            "grand_total", "seller_payout", "currency",
            "carrier", "tracking_number"
        ],
        order_by="creation ASC"
    )

    # Add seller names
    for so in sub_orders:
        so["seller_name"] = frappe.db.get_value(
            "Seller Profile", so["seller"], "seller_name"
        )

    return sub_orders


@frappe.whitelist()
def update_sub_order_status(sub_order_name, action, **kwargs):
    """
    Update sub order status.

    Args:
        sub_order_name: Sub Order name
        action: Action to perform
        **kwargs: Additional parameters (carrier, tracking_number, etc.)

    Returns:
        dict: Updated status
    """
    sub_order = frappe.get_doc("Sub Order", sub_order_name)

    # Permission check - only seller or admin can update
    seller_user = frappe.db.get_value("Seller Profile", sub_order.seller, "user")
    if frappe.session.user != seller_user:
        if not frappe.has_permission("Sub Order", "write"):
            frappe.throw(_("Not permitted to update this sub order"))

    if action == "accept":
        sub_order.accept_order()
    elif action == "process":
        sub_order.start_processing()
    elif action == "pack":
        sub_order.mark_packed()
    elif action == "ship":
        sub_order.ship_order(
            carrier=kwargs.get("carrier"),
            tracking_number=kwargs.get("tracking_number"),
            tracking_url=kwargs.get("tracking_url")
        )
    elif action == "in_transit":
        sub_order.mark_in_transit()
    elif action == "out_for_delivery":
        sub_order.mark_out_for_delivery()
    elif action == "deliver":
        sub_order.mark_delivered(delivery_date=kwargs.get("delivery_date"))
    elif action == "complete":
        sub_order.mark_completed()
    elif action == "cancel":
        sub_order.request_cancellation(
            reason=kwargs.get("reason"),
            requested_by=kwargs.get("requested_by", "seller")
        )
    elif action == "approve_cancel":
        sub_order.approve_cancellation()
    elif action == "hold":
        sub_order.put_on_hold(reason=kwargs.get("reason"))
    elif action == "resume":
        sub_order.resume_from_hold(resume_status=kwargs.get("resume_status"))
    else:
        frappe.throw(_("Invalid action: {0}").format(action))

    return {
        "status": "success",
        "sub_order_status": sub_order.status,
        "fulfillment_status": sub_order.fulfillment_status,
        "message": _("Sub Order status updated to {0}").format(sub_order.status)
    }


@frappe.whitelist()
def add_tracking(sub_order_name, carrier, tracking_number, tracking_url=None):
    """
    Add tracking information to a sub order.

    Args:
        sub_order_name: Sub Order name
        carrier: Shipping carrier
        tracking_number: Tracking number
        tracking_url: Optional tracking URL

    Returns:
        dict: Success status
    """
    sub_order = frappe.get_doc("Sub Order", sub_order_name)

    # Permission check
    seller_user = frappe.db.get_value("Seller Profile", sub_order.seller, "user")
    if frappe.session.user != seller_user:
        if not frappe.has_permission("Sub Order", "write"):
            frappe.throw(_("Not permitted to update this sub order"))

    sub_order.ship_order(
        carrier=carrier,
        tracking_number=tracking_number,
        tracking_url=tracking_url
    )

    return {
        "status": "success",
        "tracking": sub_order.get_tracking_info()
    }


@frappe.whitelist()
def get_sub_order_statistics(seller=None, days=30):
    """
    Get sub order statistics.

    Args:
        seller: Filter by seller
        days: Number of days to analyze

    Returns:
        dict: Sub order statistics
    """
    from_date = add_days(nowdate(), -cint(days))

    filters = {"order_date": [">=", from_date]}
    if seller:
        filters["seller"] = seller

    stats = frappe.db.sql("""
        SELECT
            status,
            COUNT(*) as order_count,
            SUM(grand_total) as total_value,
            SUM(seller_payout) as total_payout,
            SUM(commission_amount) as total_commission
        FROM `tabSub Order`
        WHERE order_date >= %(from_date)s
        {seller_filter}
        GROUP BY status
    """.format(
        seller_filter=f"AND seller = %(seller)s" if seller else ""
    ), {"from_date": from_date, "seller": seller}, as_dict=True)

    status_data = {
        s.status: {
            "count": s.order_count,
            "value": s.total_value,
            "payout": s.total_payout,
            "commission": s.total_commission
        } for s in stats
    }

    total_orders = sum(s.order_count for s in stats)
    total_value = sum(flt(s.total_value) for s in stats)
    total_payout = sum(flt(s.total_payout) for s in stats)
    total_commission = sum(flt(s.total_commission) for s in stats)

    return {
        "period_days": cint(days),
        "total_orders": total_orders,
        "total_value": total_value,
        "total_payout": total_payout,
        "total_commission": total_commission,
        "status_breakdown": status_data,
        "average_order_value": total_value / total_orders if total_orders > 0 else 0,
        "average_payout": total_payout / total_orders if total_orders > 0 else 0
    }

# Copyright (c) 2026, Trade Hub and contributors
# For license information, please see license.txt

"""
Order DocType for Trade Hub B2B Marketplace.

This module implements the order lifecycle management for B2B transactions.
Orders can be created directly, from RFQs, or from accepted quotations.

Status Workflow:
- Draft: Order is being prepared, not yet submitted
- Pending: Order submitted, waiting for seller confirmation
- Confirmed: Seller has confirmed the order
- Processing: Order is being processed/manufactured
- Ready to Ship: Order is ready for shipment
- Shipped: Order has been shipped
- Delivered: Order has been delivered to buyer
- Completed: Order completed successfully with buyer confirmation
- Cancelled: Order was cancelled
- Refunded: Payment refunded after cancellation
- On Hold: Order temporarily on hold

Key features:
- Multi-tenant data isolation via Buyer/Seller Profile's tenant
- Status workflow with validated transitions
- Payment tracking with multiple payment statuses
- Integration with RFQ, Quotation, and Sample Request
- ERPNext Sales Order/Purchase Order sync capability
- fetch_from pattern for buyer, seller, and tenant information
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import (
    flt, cint, getdate, nowdate, now_datetime,
    get_datetime, add_days, time_diff_in_hours
)


# Order Type descriptions
ORDER_TYPE_DESCRIPTIONS = {
    "Standard": "Standard order - regular purchase",
    "Bulk": "Bulk order - large quantity with potential volume discounts",
    "Sample": "Sample order - product samples for evaluation",
    "Custom Production": "Custom production order - special manufacturing requirements",
    "RFQ Order": "RFQ order - created from accepted RFQ quotation",
    "Repeat Order": "Repeat order - based on a previous order"
}

# Valid status transitions
STATUS_TRANSITIONS = {
    "Draft": ["Pending", "Cancelled"],
    "Pending": ["Confirmed", "Cancelled", "On Hold"],
    "Confirmed": ["Processing", "Cancelled", "On Hold"],
    "Processing": ["Ready to Ship", "Cancelled", "On Hold"],
    "Ready to Ship": ["Shipped", "Cancelled", "On Hold"],
    "Shipped": ["Delivered", "Cancelled"],
    "Delivered": ["Completed", "Refunded"],
    "Completed": ["Refunded"],
    "Cancelled": ["Refunded"],
    "Refunded": [],
    "On Hold": ["Pending", "Confirmed", "Processing", "Ready to Ship", "Cancelled"]
}

# Payment status descriptions
PAYMENT_STATUS_DESCRIPTIONS = {
    "Pending": "Payment not yet received",
    "Advance Received": "Advance payment received, balance pending",
    "Partially Paid": "Partial payment received",
    "Fully Paid": "Full payment received",
    "Overdue": "Payment is overdue",
    "Refunded": "Payment has been refunded"
}


class Order(Document):
    """
    Order DocType for B2B transactions.

    Each Order represents a purchase transaction between a buyer and seller.

    Features:
    - Link to Buyer Profile and Seller Profile with auto-fetched details
    - Multi-tenant isolation via tenant field
    - Full status workflow with validation
    - Payment tracking and management
    - Integration with RFQ, Quotation, and Sample Request
    - ERPNext document mapping
    """

    def before_insert(self):
        """Set defaults before inserting a new Order."""
        self.set_default_order_date()
        self.set_order_number()
        self.set_tenant_from_buyer()

    def validate(self):
        """Validate Order data before saving."""
        self.validate_buyer()
        self.validate_seller()
        self.validate_tenant_match()
        self.validate_status_transition()
        self.validate_tenant_isolation()
        self.calculate_totals()
        self.calculate_payment_amounts()
        self.update_dates_on_status_change()

    def on_update(self):
        """Actions after Order is updated."""
        self.update_linked_documents()
        self.send_status_notification()
        self.clear_order_cache()

    def on_trash(self):
        """Actions before Order is deleted."""
        self.check_status_for_deletion()

    # =========================================================================
    # DEFAULT SETTINGS
    # =========================================================================

    def set_default_order_date(self):
        """Set default order date to today if not provided."""
        if not self.order_date:
            self.order_date = nowdate()

    def set_order_number(self):
        """Set order number for display purposes."""
        if not self.order_number:
            self.order_number = self.name or ""

    def set_tenant_from_buyer(self):
        """
        Set tenant from buyer if not already set.
        This provides multi-tenant isolation.
        """
        if self.buyer and not self.tenant:
            buyer_tenant = frappe.db.get_value(
                "Buyer Profile", self.buyer, "tenant"
            )
            if buyer_tenant:
                self.tenant = buyer_tenant

    # =========================================================================
    # VALIDATION METHODS
    # =========================================================================

    def validate_buyer(self):
        """Validate buyer link exists and is valid."""
        if not self.buyer:
            frappe.throw(_("Buyer is required"))

        buyer_status = frappe.db.get_value(
            "Buyer Profile", self.buyer, "status"
        )
        if buyer_status and buyer_status not in ["Active", "Verified"]:
            frappe.throw(
                _("Cannot create Order: Buyer account status is {0}. "
                  "Only Active or Verified buyers can create orders.").format(
                    buyer_status
                )
            )

    def validate_seller(self):
        """Validate seller link exists and is valid."""
        if not self.seller:
            frappe.throw(_("Seller is required"))

        seller_status = frappe.db.get_value(
            "Seller Profile", self.seller, "status"
        )
        if seller_status and seller_status not in ["Active", "Verified"]:
            frappe.throw(
                _("Cannot create Order: Seller account status is {0}. "
                  "Only Active or Verified sellers can fulfill orders.").format(
                    seller_status
                )
            )

    def validate_tenant_match(self):
        """Validate that buyer and seller belong to same tenant."""
        if not self.buyer or not self.seller:
            return

        buyer_tenant = frappe.db.get_value("Buyer Profile", self.buyer, "tenant")
        seller_tenant = frappe.db.get_value("Seller Profile", self.seller, "tenant")

        if buyer_tenant and seller_tenant and buyer_tenant != seller_tenant:
            frappe.throw(
                _("Buyer and Seller must belong to the same tenant")
            )

    def validate_status_transition(self):
        """Validate status transitions are valid."""
        if self.is_new():
            return

        old_status = frappe.db.get_value("Order", self.name, "status")
        if old_status and old_status != self.status:
            valid_transitions = STATUS_TRANSITIONS.get(old_status, [])
            if self.status not in valid_transitions:
                frappe.throw(
                    _("Cannot change status from {0} to {1}. "
                      "Valid transitions are: {2}").format(
                        old_status, self.status,
                        ", ".join(valid_transitions) if valid_transitions else "None"
                    )
                )

    def validate_tenant_isolation(self):
        """
        Validate that Order belongs to user's tenant.
        Inherits tenant from Buyer Profile to ensure multi-tenant data isolation.
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
                _("Access denied: You can only access Orders in your tenant")
            )

    # =========================================================================
    # CALCULATION METHODS
    # =========================================================================

    def calculate_totals(self):
        """Calculate order totals from items."""
        subtotal = 0

        # Calculate subtotal from items
        if self.items:
            for item in self.items:
                item_amount = flt(item.quantity, 2) * flt(item.unit_price, 2)
                item.amount = item_amount
                subtotal += item_amount

        self.subtotal = subtotal

        # Calculate discount amount
        if self.discount_percentage:
            self.discount_amount = flt(subtotal * flt(self.discount_percentage) / 100, 2)
        else:
            self.discount_amount = 0

        # Calculate tax amount if tax rate is provided
        taxable_amount = subtotal - flt(self.discount_amount)
        if self.tax_rate:
            self.tax_amount = flt(taxable_amount * flt(self.tax_rate) / 100, 2)

        # Calculate total
        self.total_amount = flt(
            subtotal - flt(self.discount_amount) +
            flt(self.tax_amount) + flt(self.shipping_cost),
            2
        )

    def calculate_payment_amounts(self):
        """Calculate payment-related amounts."""
        # Calculate advance amount
        if self.advance_percentage:
            self.advance_amount = flt(
                flt(self.total_amount) * flt(self.advance_percentage) / 100, 2
            )

        # Calculate balance amount
        self.balance_amount = flt(
            flt(self.total_amount) - flt(self.paid_amount), 2
        )

        # Update payment status based on amounts
        if flt(self.paid_amount) >= flt(self.total_amount):
            if self.payment_status not in ["Refunded"]:
                self.payment_status = "Fully Paid"
        elif flt(self.paid_amount) > 0:
            if flt(self.paid_amount) >= flt(self.advance_amount) and self.advance_amount:
                self.payment_status = "Advance Received"
            else:
                self.payment_status = "Partially Paid"

    # =========================================================================
    # STATUS MANAGEMENT
    # =========================================================================

    def update_dates_on_status_change(self):
        """Update date fields based on status changes."""
        if self.is_new():
            return

        old_status = frappe.db.get_value("Order", self.name, "status")
        if old_status == self.status:
            return

        current_datetime = now_datetime()

        if self.status == "Confirmed":
            if not self.confirmed_date:
                self.confirmed_date = current_datetime

        elif self.status == "Processing":
            if not self.processing_start_date:
                self.processing_start_date = current_datetime

        elif self.status == "Shipped":
            if not self.shipped_date:
                self.shipped_date = current_datetime

        elif self.status == "Delivered":
            if not self.delivered_date:
                self.delivered_date = current_datetime

        elif self.status == "Completed":
            if not self.completed_date:
                self.completed_date = current_datetime

        elif self.status in ["Cancelled", "Refunded"]:
            if not self.cancellation_date:
                self.cancellation_date = current_datetime

    def set_status(self, new_status, reason=None):
        """
        Change the status of the Order.

        Args:
            new_status: The new status to set
            reason: Optional reason for status change

        Returns:
            bool: True if status was changed successfully
        """
        valid_transitions = STATUS_TRANSITIONS.get(self.status, [])
        if new_status not in valid_transitions:
            frappe.throw(
                _("Cannot change status from {0} to {1}").format(
                    self.status, new_status
                )
            )

        if reason:
            self.internal_notes = (self.internal_notes or "") + \
                f"\nStatus changed to {new_status}: {reason}"

        self.status = new_status
        self.save()
        return True

    def submit_order(self):
        """
        Submit the order for seller confirmation.

        Returns:
            bool: True if submitted successfully
        """
        if self.status != "Draft":
            frappe.throw(_("Only Draft orders can be submitted"))

        # Validate items exist
        if not self.items or len(self.items) == 0:
            frappe.throw(_("Cannot submit order without items"))

        # Validate total amount
        if flt(self.total_amount) <= 0:
            frappe.throw(_("Order total must be greater than zero"))

        return self.set_status("Pending")

    def confirm_order(self):
        """
        Seller confirms the order.

        Returns:
            bool: True if confirmed successfully
        """
        if self.status != "Pending":
            frappe.throw(_("Only Pending orders can be confirmed"))

        return self.set_status("Confirmed")

    def start_processing(self):
        """
        Start processing/manufacturing the order.

        Returns:
            bool: True if started successfully
        """
        if self.status != "Confirmed":
            frappe.throw(_("Only Confirmed orders can start processing"))

        return self.set_status("Processing")

    def mark_ready_to_ship(self):
        """
        Mark order as ready for shipment.

        Returns:
            bool: True if marked successfully
        """
        if self.status != "Processing":
            frappe.throw(_("Only Processing orders can be marked ready to ship"))

        return self.set_status("Ready to Ship")

    def ship_order(self, tracking_number=None, carrier=None):
        """
        Mark order as shipped.

        Args:
            tracking_number: Optional tracking number
            carrier: Optional shipping carrier

        Returns:
            bool: True if shipped successfully
        """
        if self.status != "Ready to Ship":
            frappe.throw(_("Only orders that are Ready to Ship can be shipped"))

        if tracking_number:
            self.tracking_number = tracking_number
        if carrier:
            self.shipping_carrier = carrier

        return self.set_status("Shipped")

    def mark_delivered(self):
        """
        Mark order as delivered.

        Returns:
            bool: True if marked successfully
        """
        if self.status != "Shipped":
            frappe.throw(_("Only Shipped orders can be marked as delivered"))

        return self.set_status("Delivered")

    def complete_order(self):
        """
        Mark order as completed.

        Returns:
            bool: True if completed successfully
        """
        if self.status != "Delivered":
            frappe.throw(_("Only Delivered orders can be completed"))

        return self.set_status("Completed")

    def cancel_order(self, reason=None, cancelled_by=None):
        """
        Cancel the order.

        Args:
            reason: Optional cancellation reason
            cancelled_by: Who cancelled (Buyer/Seller/System/Admin)

        Returns:
            bool: True if cancelled successfully
        """
        if self.status in ["Completed", "Refunded"]:
            frappe.throw(_("Cannot cancel {0} orders").format(self.status))

        if reason:
            self.cancellation_reason = reason
        if cancelled_by:
            self.cancelled_by = cancelled_by

        return self.set_status("Cancelled", reason)

    def hold_order(self, reason=None):
        """
        Put order on hold.

        Args:
            reason: Optional hold reason

        Returns:
            bool: True if put on hold successfully
        """
        if self.status in ["Shipped", "Delivered", "Completed", "Cancelled", "Refunded"]:
            frappe.throw(_("Cannot put {0} orders on hold").format(self.status))

        return self.set_status("On Hold", reason)

    def release_from_hold(self, target_status):
        """
        Release order from hold to specified status.

        Args:
            target_status: Status to return to

        Returns:
            bool: True if released successfully
        """
        if self.status != "On Hold":
            frappe.throw(_("Only orders on hold can be released"))

        valid_release_statuses = ["Pending", "Confirmed", "Processing", "Ready to Ship"]
        if target_status not in valid_release_statuses:
            frappe.throw(
                _("Can only release to: {0}").format(", ".join(valid_release_statuses))
            )

        return self.set_status(target_status)

    def process_refund(self, refund_amount=None, refund_status="Completed"):
        """
        Process refund for cancelled order.

        Args:
            refund_amount: Amount to refund (defaults to paid_amount)
            refund_status: Refund status (default Completed)

        Returns:
            bool: True if refund processed successfully
        """
        if self.status not in ["Cancelled", "Delivered", "Completed"]:
            frappe.throw(_("Can only process refunds for Cancelled, Delivered, or Completed orders"))

        self.refund_status = refund_status
        self.refund_amount = refund_amount or self.paid_amount

        return self.set_status("Refunded")

    # =========================================================================
    # PAYMENT MANAGEMENT
    # =========================================================================

    def record_payment(self, amount, payment_method=None, reference=None):
        """
        Record a payment against the order.

        Args:
            amount: Payment amount
            payment_method: Optional payment method
            reference: Optional payment reference

        Returns:
            dict: Payment details
        """
        if flt(amount) <= 0:
            frappe.throw(_("Payment amount must be greater than zero"))

        self.paid_amount = flt(self.paid_amount or 0) + flt(amount)
        self.last_payment_date = nowdate()

        if payment_method:
            self.payment_method = payment_method

        # Check if this is advance payment
        if not self.advance_paid and flt(self.paid_amount) >= flt(self.advance_amount):
            self.advance_paid = 1
            self.advance_paid_date = nowdate()

        self.save()

        return {
            "success": True,
            "paid_amount": self.paid_amount,
            "balance_amount": self.balance_amount,
            "payment_status": self.payment_status
        }

    # =========================================================================
    # LINKED DOCUMENT UPDATES
    # =========================================================================

    def update_linked_documents(self):
        """Update linked documents (RFQ, Quotation, Sample Request) on status change."""
        if self.is_new():
            return

        # Update RFQ if linked
        if self.rfq:
            frappe.db.set_value("RFQ", self.rfq, "linked_order", self.name)

        # Update Quotation if linked
        if self.quotation:
            frappe.db.set_value("Quotation", self.quotation, "linked_order", self.name)

        # Update Sample Request if linked (for sample credits)
        if self.sample_request:
            frappe.db.set_value("Sample Request", self.sample_request, "credited_order", self.name)

    # =========================================================================
    # NOTIFICATIONS
    # =========================================================================

    def send_status_notification(self):
        """Send notification on status change."""
        if self.is_new():
            return

        old_status = frappe.db.get_value("Order", self.name, "status")
        if old_status == self.status:
            return

        # Future: Implement notification system
        # This would send email/push notifications to relevant parties
        pass

    # =========================================================================
    # DELETION CHECKS
    # =========================================================================

    def check_status_for_deletion(self):
        """Check if Order can be deleted based on status."""
        if self.status not in ["Draft", "Cancelled"]:
            frappe.throw(
                _("Cannot delete Order with status {0}. "
                  "Only Draft or Cancelled orders can be deleted.").format(
                    self.status
                )
            )

    # =========================================================================
    # CACHE MANAGEMENT
    # =========================================================================

    def clear_order_cache(self):
        """Clear cached Order data."""
        cache_keys = [
            f"order:{self.name}",
            f"buyer_orders:{self.buyer}",
            f"seller_orders:{self.seller}",
            f"tenant_orders:{self.tenant}",
        ]
        for key in cache_keys:
            frappe.cache().delete_value(key)


# =============================================================================
# WHITELISTED API FUNCTIONS
# =============================================================================


@frappe.whitelist()
def get_order_list(buyer=None, seller=None, status=None, tenant=None,
                   order_type=None, limit=20, offset=0):
    """
    Get list of Orders with optional filters.

    Args:
        buyer: Optional buyer filter
        seller: Optional seller filter
        status: Optional status filter
        tenant: Optional tenant filter
        order_type: Optional order type filter
        limit: Number of records to return (default 20)
        offset: Starting position (default 0)

    Returns:
        list: List of Order records
    """
    filters = {}

    if buyer:
        filters["buyer"] = buyer
    if seller:
        filters["seller"] = seller
    if status:
        filters["status"] = status
    if tenant:
        filters["tenant"] = tenant
    if order_type:
        filters["order_type"] = order_type

    orders = frappe.get_all(
        "Order",
        filters=filters,
        fields=[
            "name", "order_number", "status", "order_type", "order_date",
            "buyer_name", "buyer_company", "seller_name", "seller_company",
            "total_amount", "currency", "payment_status", "priority"
        ],
        order_by="order_date desc",
        start=cint(offset),
        page_length=cint(limit)
    )

    return orders


@frappe.whitelist()
def get_order_details(order_name):
    """
    Get detailed Order information.

    Args:
        order_name: The Order document name

    Returns:
        dict: Order details with items and history
    """
    order = frappe.get_doc("Order", order_name)

    return {
        "order": order.as_dict(),
        "item_count": len(order.items) if order.items else 0
    }


@frappe.whitelist()
def create_order(buyer, seller, items, order_type="Standard",
                 currency="USD", payment_terms=None, incoterm="EXW",
                 delivery_address=None, delivery_city=None, delivery_country=None,
                 buyer_notes=None, rfq=None, quotation=None, sample_request=None):
    """
    Create a new Order.

    Args:
        buyer: The Buyer Profile name
        seller: The Seller Profile name
        items: List of items (required)
        order_type: Type of order (default Standard)
        currency: Currency (default USD)
        payment_terms: Payment terms
        incoterm: Incoterm (default EXW)
        delivery_address: Delivery address
        delivery_city: Delivery city
        delivery_country: Delivery country
        buyer_notes: Notes from buyer
        rfq: Optional linked RFQ
        quotation: Optional linked Quotation
        sample_request: Optional linked Sample Request

    Returns:
        dict: Created Order info
    """
    doc = frappe.new_doc("Order")
    doc.buyer = buyer
    doc.seller = seller
    doc.order_type = order_type
    doc.currency = currency
    doc.payment_terms = payment_terms
    doc.incoterm = incoterm
    doc.delivery_address = delivery_address
    doc.delivery_city = delivery_city
    doc.delivery_country = delivery_country
    doc.buyer_notes = buyer_notes

    # Set source information
    if rfq:
        doc.rfq = rfq
        doc.source_type = "RFQ"
    if quotation:
        doc.quotation = quotation
        doc.source_type = "Quotation"
    if sample_request:
        doc.sample_request = sample_request
        doc.source_type = "Sample Conversion"

    # Add items
    if items:
        for item in items:
            doc.append("items", item)

    doc.insert()

    return {
        "name": doc.name,
        "message": _("Order created successfully"),
        "status": doc.status
    }


@frappe.whitelist()
def submit_order(order_name):
    """
    Submit an Order for seller confirmation.

    Args:
        order_name: The Order document name

    Returns:
        dict: Success message
    """
    doc = frappe.get_doc("Order", order_name)
    doc.submit_order()

    return {
        "success": True,
        "message": _("Order submitted successfully"),
        "status": doc.status
    }


@frappe.whitelist()
def confirm_order(order_name):
    """
    Confirm an Order (seller action).

    Args:
        order_name: The Order document name

    Returns:
        dict: Success message
    """
    doc = frappe.get_doc("Order", order_name)
    doc.confirm_order()

    return {
        "success": True,
        "message": _("Order confirmed successfully"),
        "status": doc.status
    }


@frappe.whitelist()
def start_order_processing(order_name):
    """
    Start processing an Order.

    Args:
        order_name: The Order document name

    Returns:
        dict: Success message
    """
    doc = frappe.get_doc("Order", order_name)
    doc.start_processing()

    return {
        "success": True,
        "message": _("Order processing started"),
        "status": doc.status
    }


@frappe.whitelist()
def mark_order_ready_to_ship(order_name):
    """
    Mark Order as ready for shipment.

    Args:
        order_name: The Order document name

    Returns:
        dict: Success message
    """
    doc = frappe.get_doc("Order", order_name)
    doc.mark_ready_to_ship()

    return {
        "success": True,
        "message": _("Order marked ready to ship"),
        "status": doc.status
    }


@frappe.whitelist()
def ship_order(order_name, tracking_number=None, carrier=None):
    """
    Ship an Order.

    Args:
        order_name: The Order document name
        tracking_number: Optional tracking number
        carrier: Optional carrier name

    Returns:
        dict: Success message
    """
    doc = frappe.get_doc("Order", order_name)
    doc.ship_order(tracking_number, carrier)

    return {
        "success": True,
        "message": _("Order shipped"),
        "status": doc.status,
        "tracking_number": doc.tracking_number
    }


@frappe.whitelist()
def mark_order_delivered(order_name):
    """
    Mark Order as delivered.

    Args:
        order_name: The Order document name

    Returns:
        dict: Success message
    """
    doc = frappe.get_doc("Order", order_name)
    doc.mark_delivered()

    return {
        "success": True,
        "message": _("Order marked as delivered"),
        "status": doc.status
    }


@frappe.whitelist()
def complete_order(order_name):
    """
    Complete an Order.

    Args:
        order_name: The Order document name

    Returns:
        dict: Success message
    """
    doc = frappe.get_doc("Order", order_name)
    doc.complete_order()

    return {
        "success": True,
        "message": _("Order completed"),
        "status": doc.status
    }


@frappe.whitelist()
def cancel_order(order_name, reason=None, cancelled_by=None):
    """
    Cancel an Order.

    Args:
        order_name: The Order document name
        reason: Optional cancellation reason
        cancelled_by: Who cancelled (Buyer/Seller/System/Admin)

    Returns:
        dict: Success message
    """
    doc = frappe.get_doc("Order", order_name)
    doc.cancel_order(reason, cancelled_by)

    return {
        "success": True,
        "message": _("Order cancelled"),
        "status": doc.status
    }


@frappe.whitelist()
def hold_order(order_name, reason=None):
    """
    Put Order on hold.

    Args:
        order_name: The Order document name
        reason: Optional hold reason

    Returns:
        dict: Success message
    """
    doc = frappe.get_doc("Order", order_name)
    doc.hold_order(reason)

    return {
        "success": True,
        "message": _("Order put on hold"),
        "status": doc.status
    }


@frappe.whitelist()
def release_order_from_hold(order_name, target_status):
    """
    Release Order from hold.

    Args:
        order_name: The Order document name
        target_status: Status to return to

    Returns:
        dict: Success message
    """
    doc = frappe.get_doc("Order", order_name)
    doc.release_from_hold(target_status)

    return {
        "success": True,
        "message": _("Order released from hold"),
        "status": doc.status
    }


@frappe.whitelist()
def process_order_refund(order_name, refund_amount=None, refund_status="Completed"):
    """
    Process refund for an Order.

    Args:
        order_name: The Order document name
        refund_amount: Amount to refund
        refund_status: Refund status

    Returns:
        dict: Success message
    """
    doc = frappe.get_doc("Order", order_name)
    doc.process_refund(refund_amount, refund_status)

    return {
        "success": True,
        "message": _("Refund processed"),
        "status": doc.status,
        "refund_amount": doc.refund_amount
    }


@frappe.whitelist()
def record_order_payment(order_name, amount, payment_method=None, reference=None):
    """
    Record a payment for an Order.

    Args:
        order_name: The Order document name
        amount: Payment amount
        payment_method: Payment method
        reference: Payment reference

    Returns:
        dict: Payment result
    """
    doc = frappe.get_doc("Order", order_name)
    return doc.record_payment(flt(amount), payment_method, reference)


@frappe.whitelist()
def get_order_type_description(order_type):
    """
    Get the description for an Order type.

    Args:
        order_type: The Order type

    Returns:
        str: Description of the Order type
    """
    return ORDER_TYPE_DESCRIPTIONS.get(order_type, "")


@frappe.whitelist()
def get_buyer_orders(buyer, status=None, limit=20, offset=0):
    """
    Get orders for a specific buyer.

    Args:
        buyer: The Buyer Profile name
        status: Optional status filter
        limit: Number of records to return
        offset: Starting position

    Returns:
        list: List of orders
    """
    return get_order_list(buyer=buyer, status=status, limit=limit, offset=offset)


@frappe.whitelist()
def get_seller_orders(seller, status=None, limit=20, offset=0):
    """
    Get orders for a specific seller.

    Args:
        seller: The Seller Profile name
        status: Optional status filter
        limit: Number of records to return
        offset: Starting position

    Returns:
        list: List of orders
    """
    return get_order_list(seller=seller, status=status, limit=limit, offset=offset)


@frappe.whitelist()
def get_order_statistics(buyer=None, seller=None, tenant=None,
                         date_from=None, date_to=None):
    """
    Get Order statistics.

    Args:
        buyer: Optional buyer filter
        seller: Optional seller filter
        tenant: Optional tenant filter
        date_from: Start date
        date_to: End date

    Returns:
        dict: Statistics including counts, totals, etc.
    """
    filters = {}

    if buyer:
        filters["buyer"] = buyer
    if seller:
        filters["seller"] = seller
    if tenant:
        filters["tenant"] = tenant
    if date_from:
        filters["order_date"] = [">=", date_from]
    if date_to:
        if "order_date" in filters:
            filters["order_date"] = ["between", [date_from, date_to]]
        else:
            filters["order_date"] = ["<=", date_to]

    # Get counts by status
    status_counts = frappe.db.get_all(
        "Order",
        filters=filters,
        fields=["status", "count(*) as count"],
        group_by="status"
    )

    status_dict = {s.status: s.count for s in status_counts}
    total = sum(status_dict.values())

    # Get total revenue
    revenue = frappe.db.sql("""
        SELECT SUM(total_amount) as total_revenue
        FROM `tabOrder`
        WHERE status IN ('Delivered', 'Completed')
        {filters}
    """.format(
        filters="AND buyer = %(buyer)s" if buyer else ""
    ), {"buyer": buyer} if buyer else {}, as_dict=True)

    total_revenue = flt(revenue[0].total_revenue if revenue else 0, 2)

    # Get average order value
    avg_order = frappe.db.sql("""
        SELECT AVG(total_amount) as avg_value
        FROM `tabOrder`
        WHERE status NOT IN ('Draft', 'Cancelled', 'Refunded')
        {filters}
    """.format(
        filters="AND buyer = %(buyer)s" if buyer else ""
    ), {"buyer": buyer} if buyer else {}, as_dict=True)

    avg_order_value = flt(avg_order[0].avg_value if avg_order else 0, 2)

    return {
        "total_orders": total,
        "status_breakdown": status_dict,
        "pending_count": status_dict.get("Pending", 0),
        "processing_count": status_dict.get("Processing", 0),
        "completed_count": status_dict.get("Completed", 0),
        "cancelled_count": status_dict.get("Cancelled", 0),
        "total_revenue": total_revenue,
        "average_order_value": avg_order_value
    }


@frappe.whitelist()
def create_order_from_quotation(quotation_name):
    """
    Create an Order from a selected Quotation.

    Args:
        quotation_name: The Quotation document name

    Returns:
        dict: Created Order info
    """
    quotation = frappe.get_doc("Quotation", quotation_name)

    if quotation.status != "Selected":
        frappe.throw(_("Can only create order from Selected quotations"))

    if quotation.linked_order:
        frappe.throw(
            _("An order already exists for this quotation: {0}").format(
                quotation.linked_order
            )
        )

    # Create order
    order = frappe.new_doc("Order")
    order.buyer = quotation.rfq_buyer
    order.seller = quotation.seller
    order.rfq = quotation.rfq
    order.quotation = quotation_name
    order.source_type = "Quotation"
    order.order_type = "RFQ Order"
    order.currency = quotation.currency
    order.total_amount = quotation.total_amount
    order.payment_terms = quotation.payment_terms
    order.incoterm = quotation.incoterm
    order.delivery_days = quotation.delivery_days

    # Copy items from quotation
    if quotation.items:
        for qitem in quotation.items:
            order.append("items", {
                "sku_product": qitem.sku_product if hasattr(qitem, 'sku_product') else None,
                "product_name": qitem.product_name if hasattr(qitem, 'product_name') else qitem.item_name,
                "quantity": qitem.quantity,
                "unit_price": qitem.unit_price,
                "amount": qitem.amount
            })

    order.insert()

    # Update quotation
    quotation.linked_order = order.name
    quotation.save()

    return {
        "name": order.name,
        "message": _("Order created from quotation"),
        "status": order.status
    }

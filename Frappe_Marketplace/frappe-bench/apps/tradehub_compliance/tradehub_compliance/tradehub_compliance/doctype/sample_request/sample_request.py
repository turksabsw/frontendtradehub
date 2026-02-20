# Copyright (c) 2026, Trade Hub and contributors
# For license information, please see license.txt

"""
Sample Request DocType for Trade Hub B2B Marketplace.

This module implements the sample/prototype workflow for B2B transactions.
Buyers can request product samples before placing bulk orders, allowing them
to evaluate quality, specifications, and suitability.

Key features:
- Multi-tenant data isolation via SKU Product's tenant
- Sample types: Standard, Custom, Prototype, Pre-production
- Complete status workflow: Requested -> Under Review -> Approved/Rejected ->
  In Production -> Ready to Ship -> Shipped -> Delivered -> Completed
- Pricing with shipping cost calculation
- Payment tracking
- Credit to final order option (sample costs credited to bulk orders)
- Buyer feedback and quality rating
- fetch_from pattern for product, seller, buyer, and tenant information
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, cint, getdate, nowdate, now_datetime


# Sample type descriptions
SAMPLE_TYPE_DESCRIPTIONS = {
    "Standard": "Standard product sample - existing product from inventory",
    "Custom": "Custom sample - modified product based on buyer specifications",
    "Prototype": "Prototype sample - new product design for evaluation",
    "Pre-production": "Pre-production sample - sample from bulk production batch"
}

# Valid status transitions
STATUS_TRANSITIONS = {
    "Requested": ["Under Review", "Cancelled"],
    "Under Review": ["Approved", "Rejected", "Cancelled"],
    "Approved": ["In Production", "Ready to Ship", "Cancelled"],
    "Rejected": [],
    "In Production": ["Ready to Ship", "Cancelled"],
    "Ready to Ship": ["Shipped", "Cancelled"],
    "Shipped": ["Delivered"],
    "Delivered": ["Completed", "Cancelled"],
    "Completed": [],
    "Cancelled": []
}


class SampleRequest(Document):
    """
    Sample Request DocType for sample/prototype workflow.

    Each Sample Request represents a buyer's request to receive product
    samples before placing a bulk order. Features include:
    - Link to SKU Product with auto-fetched tenant isolation
    - Link to Buyer Profile for requester information
    - Sample type selection (Standard, Custom, Prototype, Pre-production)
    - Complete status workflow tracking
    - Pricing with automatic total calculation
    - Payment and shipping tracking
    - Credit to final order capability
    - Quality feedback collection
    """

    def before_insert(self):
        """Set defaults before inserting a new sample request."""
        self.set_default_request_date()

    def validate(self):
        """Validate sample request data before saving."""
        self.validate_sku_product()
        self.validate_buyer()
        self.validate_variant()
        self.validate_quantity()
        self.validate_pricing()
        self.validate_credit_percentage()
        self.validate_status_transition()
        self.validate_tenant_isolation()
        self.calculate_total_cost()
        self.update_dates_on_status_change()

    def on_update(self):
        """Actions after sample request is updated."""
        self.send_status_notification()
        self.clear_sample_cache()

    def on_trash(self):
        """Actions before sample request is deleted."""
        self.check_status_for_deletion()

    # =========================================================================
    # DEFAULT SETTINGS
    # =========================================================================

    def set_default_request_date(self):
        """Set default request date to today if not provided."""
        if not self.request_date:
            self.request_date = nowdate()

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
                _("Cannot request sample for archived product {0}").format(
                    self.sku_product
                )
            )

    def validate_buyer(self):
        """Validate buyer link exists and is valid."""
        if not self.buyer:
            frappe.throw(_("Buyer is required"))

        buyer_status = frappe.db.get_value(
            "Buyer Profile", self.buyer, "status"
        )
        if buyer_status and buyer_status not in ["Active", "Verified"]:
            frappe.msgprint(
                _("Warning: Buyer account status is {0}").format(buyer_status),
                indicator='orange',
                alert=True
            )

    def validate_variant(self):
        """Validate variant belongs to the selected product."""
        if not self.variant:
            return

        variant_product = frappe.db.get_value(
            "Product Variant", self.variant, "sku_product"
        )
        if variant_product != self.sku_product:
            frappe.throw(
                _("Selected variant does not belong to the selected product")
            )

    def validate_quantity(self):
        """Validate sample quantity is reasonable."""
        if cint(self.quantity) <= 0:
            frappe.throw(_("Quantity must be greater than zero"))

        # Warn for large sample quantities
        if cint(self.quantity) > 10:
            frappe.msgprint(
                _("Sample quantity of {0} is higher than typical. "
                  "Please verify this is correct.").format(self.quantity),
                indicator='orange',
                alert=True
            )

    def validate_pricing(self):
        """Validate pricing fields."""
        if flt(self.sample_price) < 0:
            frappe.throw(_("Sample Price cannot be negative"))

        if flt(self.shipping_cost) < 0:
            frappe.throw(_("Shipping Cost cannot be negative"))

        if not self.currency:
            self.currency = "USD"

    def validate_credit_percentage(self):
        """Validate credit percentage is within valid range."""
        if self.credit_to_order:
            if flt(self.credit_percentage) < 0 or flt(self.credit_percentage) > 100:
                frappe.throw(_("Credit Percentage must be between 0 and 100"))

    def validate_status_transition(self):
        """Validate status transitions are valid."""
        if self.is_new():
            return

        old_status = frappe.db.get_value("Sample Request", self.name, "status")
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
        Validate that sample request belongs to user's tenant.

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
                _("Access denied: You can only access sample requests in your tenant")
            )

    # =========================================================================
    # CALCULATIONS
    # =========================================================================

    def calculate_total_cost(self):
        """Calculate total cost from sample price and shipping."""
        sample_total = flt(self.sample_price) * cint(self.quantity)
        self.total_cost = sample_total + flt(self.shipping_cost)

    def calculate_creditable_amount(self):
        """
        Calculate the amount that can be credited to a future order.

        Returns:
            float: The creditable amount based on total cost and credit percentage
        """
        if not self.credit_to_order:
            return 0

        credit_pct = flt(self.credit_percentage) / 100
        return flt(self.total_cost) * credit_pct

    # =========================================================================
    # STATUS MANAGEMENT
    # =========================================================================

    def update_dates_on_status_change(self):
        """Update date fields based on status changes."""
        if not self.is_new():
            old_status = frappe.db.get_value("Sample Request", self.name, "status")
            if old_status == self.status:
                return

        today = nowdate()

        if self.status == "Approved":
            if not self.approved_date:
                self.approved_date = today

        elif self.status == "In Production":
            if not self.production_start_date:
                self.production_start_date = today

        elif self.status == "Shipped":
            if not self.shipped_date:
                self.shipped_date = today

        elif self.status == "Delivered":
            if not self.delivered_date:
                self.delivered_date = today

    def set_status(self, new_status):
        """
        Change the status of the sample request.

        Args:
            new_status: The new status to set

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

        self.status = new_status
        self.save()
        return True

    def approve(self):
        """Approve the sample request."""
        return self.set_status("Approved")

    def reject(self, reason=None):
        """
        Reject the sample request.

        Args:
            reason: Optional rejection reason
        """
        if reason:
            self.rejection_reason = reason
        return self.set_status("Rejected")

    def start_production(self):
        """Mark sample as in production."""
        return self.set_status("In Production")

    def mark_ready_to_ship(self):
        """Mark sample as ready to ship."""
        return self.set_status("Ready to Ship")

    def mark_shipped(self, tracking_number=None, carrier=None):
        """
        Mark sample as shipped.

        Args:
            tracking_number: Optional tracking number
            carrier: Optional carrier name
        """
        if tracking_number:
            self.tracking_number = tracking_number
        if carrier:
            self.carrier = carrier
        return self.set_status("Shipped")

    def mark_delivered(self):
        """Mark sample as delivered."""
        return self.set_status("Delivered")

    def complete(self, feedback=None, rating=None, decision=None):
        """
        Complete the sample request.

        Args:
            feedback: Optional buyer feedback
            rating: Optional quality rating (1-5)
            decision: Optional approval decision
        """
        if feedback:
            self.buyer_feedback = feedback
        if rating:
            self.quality_rating = rating
        if decision:
            self.approval_decision = decision
        return self.set_status("Completed")

    def cancel(self, reason=None):
        """
        Cancel the sample request.

        Args:
            reason: Optional cancellation reason
        """
        if reason:
            self.internal_notes = (self.internal_notes or "") + f"\nCancelled: {reason}"
        return self.set_status("Cancelled")

    # =========================================================================
    # CREDIT TO ORDER
    # =========================================================================

    def apply_credit_to_order(self, order_name):
        """
        Apply sample credit to an order.

        Args:
            order_name: The Order document name

        Returns:
            dict: Credit details
        """
        if not self.credit_to_order:
            frappe.throw(_("Credit to order is not enabled for this sample request"))

        if self.credited_order:
            frappe.throw(
                _("Credit has already been applied to order {0}").format(
                    self.credited_order
                )
            )

        if self.status != "Completed":
            frappe.throw(
                _("Sample request must be completed before applying credit")
            )

        creditable_amount = self.calculate_creditable_amount()
        if creditable_amount <= 0:
            frappe.throw(_("No credit amount available"))

        # Verify order exists and belongs to same buyer
        order_buyer = frappe.db.get_value("Order", order_name, "buyer")
        if order_buyer != self.buyer:
            frappe.throw(_("Order must belong to the same buyer"))

        self.credited_amount = creditable_amount
        self.credited_order = order_name
        self.save()

        return {
            "credited_amount": creditable_amount,
            "order": order_name,
            "currency": self.currency
        }

    # =========================================================================
    # NOTIFICATIONS
    # =========================================================================

    def send_status_notification(self):
        """Send notification on status change."""
        if self.is_new():
            return

        old_status = frappe.db.get_value("Sample Request", self.name, "status")
        if old_status == self.status:
            return

        # Future: Implement notification system
        # This would send email/push notifications to relevant parties
        pass

    # =========================================================================
    # DELETION CHECKS
    # =========================================================================

    def check_status_for_deletion(self):
        """Check if sample request can be deleted."""
        if self.status not in ["Requested", "Rejected", "Cancelled"]:
            frappe.throw(
                _("Cannot delete sample request with status {0}. "
                  "Only requests with status Requested, Rejected, or Cancelled "
                  "can be deleted.").format(self.status)
            )

        if self.credited_order:
            frappe.throw(
                _("Cannot delete sample request that has been credited to an order")
            )

    # =========================================================================
    # CACHE MANAGEMENT
    # =========================================================================

    def clear_sample_cache(self):
        """Clear cached sample request data."""
        cache_keys = [
            f"sample_request:{self.name}",
            f"buyer_sample_requests:{self.buyer}",
            f"product_sample_requests:{self.sku_product}",
        ]
        for key in cache_keys:
            frappe.cache().delete_value(key)


# =============================================================================
# WHITELISTED API FUNCTIONS
# =============================================================================


@frappe.whitelist()
def get_sample_requests_for_buyer(buyer, status=None):
    """
    Get all sample requests for a buyer.

    Args:
        buyer: The Buyer Profile name
        status: Optional status filter

    Returns:
        list: List of sample request records
    """
    filters = {"buyer": buyer}

    if status:
        filters["status"] = status

    requests = frappe.get_all(
        "Sample Request",
        filters=filters,
        fields=[
            "name", "request_date", "status", "sample_type",
            "sku_product", "product_name", "product_sku_code",
            "seller_name", "quantity", "total_cost", "currency",
            "credit_to_order", "tracking_number"
        ],
        order_by="request_date desc"
    )

    return requests


@frappe.whitelist()
def get_sample_requests_for_seller(seller, status=None):
    """
    Get all sample requests for a seller.

    Args:
        seller: The Seller Profile name
        status: Optional status filter

    Returns:
        list: List of sample request records
    """
    filters = {"seller": seller}

    if status:
        filters["status"] = status

    requests = frappe.get_all(
        "Sample Request",
        filters=filters,
        fields=[
            "name", "request_date", "status", "sample_type",
            "sku_product", "product_name", "product_sku_code",
            "buyer_name", "buyer_company", "quantity", "total_cost", "currency",
            "priority", "payment_status"
        ],
        order_by="priority desc, request_date desc"
    )

    return requests


@frappe.whitelist()
def get_sample_requests_for_product(sku_product, status=None):
    """
    Get all sample requests for a product.

    Args:
        sku_product: The SKU Product name
        status: Optional status filter

    Returns:
        list: List of sample request records
    """
    filters = {"sku_product": sku_product}

    if status:
        filters["status"] = status

    requests = frappe.get_all(
        "Sample Request",
        filters=filters,
        fields=[
            "name", "request_date", "status", "sample_type",
            "buyer_name", "buyer_company", "quantity", "total_cost",
            "approval_decision", "quality_rating"
        ],
        order_by="request_date desc"
    )

    return requests


@frappe.whitelist()
def create_sample_request(sku_product, buyer, sample_type="Standard",
                          quantity=1, specifications=None, variant=None,
                          sample_price=0, shipping_address=None,
                          credit_to_order=False):
    """
    Create a new sample request.

    Args:
        sku_product: The SKU Product name
        buyer: The Buyer Profile name
        sample_type: Type of sample (default Standard)
        quantity: Number of samples (default 1)
        specifications: Optional specifications
        variant: Optional Product Variant name
        sample_price: Price per sample unit
        shipping_address: Shipping address
        credit_to_order: Whether sample cost can be credited

    Returns:
        dict: Created document info
    """
    doc = frappe.new_doc("Sample Request")
    doc.sku_product = sku_product
    doc.buyer = buyer
    doc.sample_type = sample_type
    doc.quantity = cint(quantity) or 1
    doc.specifications = specifications
    doc.variant = variant
    doc.sample_price = flt(sample_price)
    doc.shipping_address = shipping_address
    doc.credit_to_order = 1 if credit_to_order else 0

    doc.insert()

    return {
        "name": doc.name,
        "message": _("Sample request created successfully"),
        "status": doc.status,
        "total_cost": doc.total_cost
    }


@frappe.whitelist()
def update_sample_status(sample_request, new_status, **kwargs):
    """
    Update the status of a sample request.

    Args:
        sample_request: The Sample Request document name
        new_status: The new status to set
        **kwargs: Additional fields to update (tracking_number, carrier, etc.)

    Returns:
        dict: Updated document info
    """
    doc = frappe.get_doc("Sample Request", sample_request)

    # Update additional fields if provided
    for key, value in kwargs.items():
        if hasattr(doc, key):
            setattr(doc, key, value)

    doc.status = new_status
    doc.save()

    return {
        "name": doc.name,
        "status": doc.status,
        "message": _("Sample request status updated to {0}").format(new_status)
    }


@frappe.whitelist()
def approve_sample_request(sample_request):
    """
    Approve a sample request.

    Args:
        sample_request: The Sample Request document name

    Returns:
        dict: Success message
    """
    doc = frappe.get_doc("Sample Request", sample_request)
    doc.approve()

    return {
        "success": True,
        "message": _("Sample request approved")
    }


@frappe.whitelist()
def reject_sample_request(sample_request, reason=None):
    """
    Reject a sample request.

    Args:
        sample_request: The Sample Request document name
        reason: Optional rejection reason

    Returns:
        dict: Success message
    """
    doc = frappe.get_doc("Sample Request", sample_request)
    doc.reject(reason)

    return {
        "success": True,
        "message": _("Sample request rejected")
    }


@frappe.whitelist()
def submit_sample_feedback(sample_request, feedback, rating=None, decision=None):
    """
    Submit buyer feedback for a sample.

    Args:
        sample_request: The Sample Request document name
        feedback: Buyer's feedback text
        rating: Optional quality rating (1-5)
        decision: Optional approval decision

    Returns:
        dict: Success message
    """
    doc = frappe.get_doc("Sample Request", sample_request)
    doc.buyer_feedback = feedback

    if rating:
        doc.quality_rating = flt(rating)

    if decision:
        doc.approval_decision = decision

    doc.save()

    return {
        "success": True,
        "message": _("Feedback submitted successfully")
    }


@frappe.whitelist()
def apply_sample_credit(sample_request, order_name):
    """
    Apply sample credit to an order.

    Args:
        sample_request: The Sample Request document name
        order_name: The Order document name

    Returns:
        dict: Credit details
    """
    doc = frappe.get_doc("Sample Request", sample_request)
    return doc.apply_credit_to_order(order_name)


@frappe.whitelist()
def get_sample_type_description(sample_type):
    """
    Get the description for a sample type.

    Args:
        sample_type: The sample type (Standard, Custom, etc.)

    Returns:
        str: Description of the sample type
    """
    return SAMPLE_TYPE_DESCRIPTIONS.get(sample_type, "")


@frappe.whitelist()
def get_pending_sample_requests(seller=None, days=30):
    """
    Get sample requests pending action.

    Args:
        seller: Optional seller filter
        days: Look back period in days (default 30)

    Returns:
        list: Sample requests needing attention
    """
    from frappe.utils import add_days

    filters = {
        "status": ["in", ["Requested", "Under Review", "Approved", "In Production"]],
        "request_date": [">=", add_days(nowdate(), -cint(days))]
    }

    if seller:
        filters["seller"] = seller

    requests = frappe.get_all(
        "Sample Request",
        filters=filters,
        fields=[
            "name", "request_date", "status", "sample_type",
            "product_name", "buyer_name", "buyer_company",
            "quantity", "priority", "total_cost"
        ],
        order_by="priority desc, request_date asc"
    )

    return requests


@frappe.whitelist()
def get_sample_statistics(seller=None, buyer=None, date_from=None, date_to=None):
    """
    Get sample request statistics.

    Args:
        seller: Optional seller filter
        buyer: Optional buyer filter
        date_from: Start date for statistics
        date_to: End date for statistics

    Returns:
        dict: Statistics including counts, conversion rates, etc.
    """
    filters = {}

    if seller:
        filters["seller"] = seller
    if buyer:
        filters["buyer"] = buyer
    if date_from:
        filters["request_date"] = [">=", date_from]
    if date_to:
        if "request_date" in filters:
            filters["request_date"] = ["between", [date_from, date_to]]
        else:
            filters["request_date"] = ["<=", date_to]

    # Get counts by status
    status_counts = frappe.db.get_all(
        "Sample Request",
        filters=filters,
        fields=["status", "count(*) as count"],
        group_by="status"
    )

    status_dict = {s.status: s.count for s in status_counts}

    total = sum(status_dict.values())
    completed = status_dict.get("Completed", 0)
    approved_for_production = frappe.db.count(
        "Sample Request",
        {**filters, "approval_decision": "Approved for Production"}
    )

    # Calculate average rating
    avg_rating = frappe.db.get_value(
        "Sample Request",
        {**filters, "quality_rating": [">", 0]},
        "AVG(quality_rating)"
    )

    return {
        "total_requests": total,
        "status_breakdown": status_dict,
        "completed_count": completed,
        "approved_for_production": approved_for_production,
        "completion_rate": (completed / total * 100) if total > 0 else 0,
        "conversion_rate": (approved_for_production / completed * 100) if completed > 0 else 0,
        "average_rating": flt(avg_rating, 2) if avg_rating else None
    }

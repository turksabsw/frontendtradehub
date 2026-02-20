# Copyright (c) 2026, Trade Hub and contributors
# For license information, please see license.txt

"""
Quotation DocType for Trade Hub B2B Marketplace.

This module implements seller quotations in response to RFQs. Sellers can create
and submit quotations with detailed pricing, delivery terms, and conditions.
Buyers can review, compare, and select the best quotation.

Status Workflow:
- Draft: Quotation is being prepared by seller
- Submitted: Quotation submitted to buyer for review
- Under Review: Buyer is actively reviewing the quotation
- Selected: Quotation has been selected as the winner
- Rejected: Quotation has been rejected by buyer
- Expired: Quotation validity date has passed
- Cancelled: Quotation cancelled by seller

Key features:
- Multi-tenant data isolation via Seller Profile's tenant
- Status workflow: Draft -> Submitted -> Under Review -> Selected/Rejected/Expired
- Detailed pricing with items, discounts, taxes, and shipping
- Delivery and payment terms specification
- Integration with RFQ and Order creation
- fetch_from pattern for RFQ, seller, and tenant information
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import (
    flt, cint, getdate, nowdate, now_datetime,
    get_datetime, add_days, date_diff
)


# Valid status transitions
STATUS_TRANSITIONS = {
    "Draft": ["Submitted", "Cancelled"],
    "Submitted": ["Under Review", "Expired", "Cancelled"],
    "Under Review": ["Selected", "Rejected", "Submitted", "Cancelled"],
    "Selected": [],
    "Rejected": [],
    "Expired": ["Draft", "Cancelled"],
    "Cancelled": []
}


class Quotation(Document):
    """
    Quotation DocType for seller responses to RFQs.

    Each Quotation represents a seller's offer in response to a buyer's
    Request for Quotation (RFQ), including detailed pricing, delivery
    terms, and conditions.

    Features:
    - Link to RFQ with auto-fetched buyer and deadline information
    - Link to Seller Profile with auto-fetched tenant isolation
    - Detailed item-level pricing with totals
    - Delivery, payment, and production terms
    - Status workflow with validation
    """

    def before_insert(self):
        """Set defaults before inserting a new Quotation."""
        self.set_default_dates()
        self.set_tenant_from_seller()
        self.generate_quotation_number()

    def validate(self):
        """Validate Quotation data before saving."""
        self.validate_seller()
        self.validate_rfq()
        self.validate_validity_date()
        self.validate_items()
        self.validate_pricing()
        self.validate_payment_terms()
        self.validate_status_transition()
        self.validate_tenant_isolation()
        self.calculate_totals()
        self.calculate_advance_amount()
        self.update_dates_on_status_change()
        self.check_validity_expiry()

    def on_update(self):
        """Actions after Quotation is updated."""
        self.update_rfq_statistics()
        self.send_status_notification()
        self.clear_quotation_cache()

    def on_trash(self):
        """Actions before Quotation is deleted."""
        self.check_status_for_deletion()
        self.check_linked_orders()

    # =========================================================================
    # DEFAULT SETTINGS
    # =========================================================================

    def set_default_dates(self):
        """Set default dates if not provided."""
        if not self.created_date:
            self.created_date = now_datetime()
        if not self.submission_date:
            self.submission_date = nowdate()

    def set_tenant_from_seller(self):
        """
        Set tenant from seller if not already set.
        This provides multi-tenant isolation.
        """
        if self.seller and not self.tenant:
            seller_tenant = frappe.db.get_value(
                "Seller Profile", self.seller, "tenant"
            )
            if seller_tenant:
                self.tenant = seller_tenant

    def generate_quotation_number(self):
        """Generate a unique quotation number if not set."""
        if not self.quotation_number:
            # Format: QUO-SELLER-YYYYMMDD-XXXXX
            seller_code = ""
            if self.seller:
                seller_code = frappe.db.get_value(
                    "Seller Profile", self.seller, "seller_code"
                ) or self.seller[:5]
                seller_code = seller_code.upper()[:5] + "-"

            date_str = nowdate().replace("-", "")
            count = frappe.db.count(
                "Quotation",
                {"creation": [">=", nowdate()]}
            ) + 1

            self.quotation_number = f"QUO-{seller_code}{date_str}-{count:05d}"

    # =========================================================================
    # VALIDATION METHODS
    # =========================================================================

    def validate_seller(self):
        """Validate seller link exists and is valid."""
        if not self.seller:
            frappe.throw(_("Seller is required"))

        seller_status = frappe.db.get_value(
            "Seller Profile", self.seller, "status"
        )
        if seller_status and seller_status not in ["Active", "Verified"]:
            frappe.throw(
                _("Cannot create quotation: Seller account status is {0}. "
                  "Only Active or Verified sellers can submit quotations.").format(
                    seller_status
                )
            )

    def validate_rfq(self):
        """Validate RFQ link and check if quotation is allowed."""
        if not self.rfq:
            frappe.throw(_("RFQ is required"))

        rfq_status = frappe.db.get_value("RFQ", self.rfq, "status")
        if rfq_status not in ["Active", "Evaluating"]:
            frappe.throw(
                _("Cannot submit quotation: RFQ status is {0}. "
                  "Can only submit quotations for Active or Evaluating RFQs.").format(
                    rfq_status
                )
            )

        # Check if RFQ deadline has passed (for new submissions)
        if self.status == "Draft" and self.is_new():
            rfq_deadline = frappe.db.get_value("RFQ", self.rfq, "submission_deadline")
            if rfq_deadline and get_datetime(rfq_deadline) < now_datetime():
                frappe.throw(
                    _("Cannot create quotation: RFQ submission deadline has passed")
                )

    def validate_validity_date(self):
        """Validate validity date is in the future for new quotations."""
        if not self.validity_date:
            frappe.throw(_("Validity Date is required"))

        if self.status == "Draft":
            validity_date = getdate(self.validity_date)
            if validity_date < getdate(nowdate()):
                frappe.throw(
                    _("Validity Date must be in the future")
                )

    def validate_items(self):
        """Validate quotation items."""
        if not self.items or len(self.items) == 0:
            frappe.throw(_("At least one item is required"))

        for idx, item in enumerate(self.items, 1):
            if not item.quantity or flt(item.quantity) <= 0:
                frappe.throw(
                    _("Row {0}: Quantity must be greater than 0").format(idx)
                )
            if not item.unit_price or flt(item.unit_price) < 0:
                frappe.throw(
                    _("Row {0}: Unit Price cannot be negative").format(idx)
                )

    def validate_pricing(self):
        """Validate pricing values."""
        if flt(self.discount_percentage) < 0 or flt(self.discount_percentage) > 100:
            frappe.throw(_("Discount percentage must be between 0 and 100"))

        if flt(self.tax_amount) < 0:
            frappe.throw(_("Tax Amount cannot be negative"))

        if flt(self.shipping_cost) < 0:
            frappe.throw(_("Shipping Cost cannot be negative"))

    def validate_payment_terms(self):
        """Validate payment terms."""
        if self.payment_terms == "Custom" and not self.payment_description:
            frappe.throw(
                _("Payment Description is required when Payment Terms is Custom")
            )

        if flt(self.advance_percentage) < 0 or flt(self.advance_percentage) > 100:
            frappe.throw(_("Advance Payment percentage must be between 0 and 100"))

    def validate_status_transition(self):
        """Validate status transitions are valid."""
        if self.is_new():
            return

        old_status = frappe.db.get_value("Quotation", self.name, "status")
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
        Validate that Quotation belongs to user's tenant.
        Inherits tenant from Seller Profile to ensure multi-tenant data isolation.
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
                _("Access denied: You can only access quotations in your tenant")
            )

    def check_validity_expiry(self):
        """Check if quotation has expired based on validity date."""
        if self.status in ["Draft", "Submitted", "Under Review"]:
            validity_date = getdate(self.validity_date)
            if validity_date < getdate(nowdate()):
                self.status = "Expired"
                frappe.msgprint(
                    _("Quotation has expired. Status changed to Expired."),
                    indicator='orange',
                    alert=True
                )

    # =========================================================================
    # CALCULATION METHODS
    # =========================================================================

    def calculate_totals(self):
        """Calculate subtotal, discount, and total amounts."""
        # Calculate subtotal from items
        subtotal = 0
        for item in self.items:
            item_amount = flt(item.quantity) * flt(item.unit_price)
            item.amount = item_amount
            subtotal += item_amount

        self.subtotal = subtotal

        # Calculate discount
        if flt(self.discount_percentage) > 0:
            self.discount_amount = subtotal * flt(self.discount_percentage) / 100
        else:
            self.discount_amount = 0

        # Calculate total
        self.total_amount = (
            subtotal
            - flt(self.discount_amount)
            + flt(self.tax_amount)
            + flt(self.shipping_cost)
        )

    def calculate_advance_amount(self):
        """Calculate advance payment amount."""
        if flt(self.advance_percentage) > 0 and flt(self.total_amount) > 0:
            self.advance_amount = flt(self.total_amount) * flt(self.advance_percentage) / 100
        else:
            self.advance_amount = 0

    # =========================================================================
    # STATUS MANAGEMENT
    # =========================================================================

    def update_dates_on_status_change(self):
        """Update date fields based on status changes."""
        if self.is_new():
            return

        old_status = frappe.db.get_value("Quotation", self.name, "status")
        if old_status == self.status:
            return

        current_datetime = now_datetime()

        if self.status == "Submitted":
            if not self.submitted_date:
                self.submitted_date = current_datetime

        elif self.status == "Under Review":
            if not self.reviewed_date:
                self.reviewed_date = current_datetime

        elif self.status in ["Selected", "Rejected"]:
            if not self.decided_date:
                self.decided_date = current_datetime

    def set_status(self, new_status, reason=None):
        """
        Change the status of the Quotation.

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
            if new_status == "Rejected":
                self.rejection_reason = reason
            else:
                self.seller_notes = (self.seller_notes or "") + \
                    f"\nStatus changed to {new_status}: {reason}"

        self.status = new_status
        self.save()
        return True

    def submit_quotation(self):
        """
        Submit the quotation to the buyer.

        Returns:
            bool: True if submitted successfully
        """
        if self.status != "Draft":
            frappe.throw(_("Only Draft quotations can be submitted"))

        # Validate required fields for submission
        if not self.items or len(self.items) == 0:
            frappe.throw(_("At least one item is required to submit"))
        if not self.validity_date:
            frappe.throw(_("Validity Date is required to submit"))

        return self.set_status("Submitted")

    def start_review(self):
        """
        Move quotation to Under Review status.

        Returns:
            bool: True if review started successfully
        """
        if self.status != "Submitted":
            frappe.throw(_("Only Submitted quotations can be reviewed"))

        return self.set_status("Under Review")

    def select(self, evaluation_score=None, evaluation_notes=None):
        """
        Select this quotation as the winner.

        Args:
            evaluation_score: Optional evaluation score
            evaluation_notes: Optional evaluation notes

        Returns:
            bool: True if selected successfully
        """
        if self.status not in ["Submitted", "Under Review"]:
            frappe.throw(_("Only Submitted or Under Review quotations can be selected"))

        if evaluation_score is not None:
            self.buyer_evaluation_score = evaluation_score
        if evaluation_notes:
            self.buyer_evaluation_notes = evaluation_notes

        result = self.set_status("Selected")

        # Update RFQ to mark this quotation as selected
        if self.rfq:
            frappe.db.set_value("RFQ", self.rfq, {
                "selected_quotation": self.name,
                "status": "Closed"
            })

        return result

    def reject(self, reason=None, evaluation_score=None, evaluation_notes=None):
        """
        Reject this quotation.

        Args:
            reason: Rejection reason
            evaluation_score: Optional evaluation score
            evaluation_notes: Optional evaluation notes

        Returns:
            bool: True if rejected successfully
        """
        if self.status not in ["Submitted", "Under Review"]:
            frappe.throw(_("Only Submitted or Under Review quotations can be rejected"))

        if evaluation_score is not None:
            self.buyer_evaluation_score = evaluation_score
        if evaluation_notes:
            self.buyer_evaluation_notes = evaluation_notes

        return self.set_status("Rejected", reason)

    def cancel(self, reason=None):
        """
        Cancel the quotation.

        Args:
            reason: Optional cancellation reason

        Returns:
            bool: True if cancelled successfully
        """
        if self.status in ["Selected"]:
            frappe.throw(_("Cannot cancel a Selected quotation"))

        return self.set_status("Cancelled", reason)

    def revise(self):
        """
        Revise an expired quotation (move back to Draft).

        Returns:
            bool: True if moved to draft successfully
        """
        if self.status != "Expired":
            frappe.throw(_("Only Expired quotations can be revised"))

        return self.set_status("Draft")

    # =========================================================================
    # RFQ INTEGRATION
    # =========================================================================

    def update_rfq_statistics(self):
        """Update RFQ statistics after quotation changes."""
        if not self.rfq:
            return

        # Trigger RFQ to update its statistics
        try:
            rfq_doc = frappe.get_doc("RFQ", self.rfq)
            rfq_doc.update_quotation_statistics()
            rfq_doc.db_update()
        except Exception:
            # Silently handle if RFQ update fails
            pass

    # =========================================================================
    # ORDER CREATION
    # =========================================================================

    def create_order(self):
        """
        Create an Order from this quotation.

        Returns:
            dict: Created order details
        """
        if self.status != "Selected":
            frappe.throw(_("Only Selected quotations can create orders"))

        if self.linked_order:
            frappe.throw(
                _("An order has already been created from this quotation: {0}").format(
                    self.linked_order
                )
            )

        # Get RFQ details for buyer info
        rfq = frappe.get_doc("RFQ", self.rfq)

        # Create order (placeholder - Order DocType will be created in Phase 7)
        order = frappe.new_doc("Order")
        order.buyer = rfq.buyer
        order.seller = self.seller
        order.rfq = self.rfq
        order.quotation = self.name
        order.currency = self.currency
        order.total_amount = self.total_amount
        order.incoterm = self.incoterm
        order.payment_terms = self.payment_terms

        # Copy items from quotation
        # (Implementation depends on Order Item structure)

        order.insert()

        # Update quotation
        self.linked_order = order.name
        self.save()

        # Update RFQ
        frappe.db.set_value("RFQ", self.rfq, {
            "linked_order": order.name,
            "order_created_date": now_datetime()
        })

        return {
            "order": order.name,
            "message": _("Order created successfully from quotation")
        }

    # =========================================================================
    # NOTIFICATIONS
    # =========================================================================

    def send_status_notification(self):
        """Send notification on status change."""
        if self.is_new():
            return

        old_status = frappe.db.get_value("Quotation", self.name, "status")
        if old_status == self.status:
            return

        # Future: Implement notification system
        # This would send email/push notifications to relevant parties
        pass

    # =========================================================================
    # DELETION CHECKS
    # =========================================================================

    def check_status_for_deletion(self):
        """Check if Quotation can be deleted based on status."""
        if self.status not in ["Draft", "Cancelled", "Expired"]:
            frappe.throw(
                _("Cannot delete quotation with status {0}. "
                  "Only Draft, Cancelled, or Expired quotations can be deleted.").format(
                    self.status
                )
            )

    def check_linked_orders(self):
        """Check for linked orders before deletion."""
        if self.linked_order:
            frappe.throw(
                _("Cannot delete quotation with linked order {0}. "
                  "Please delete the order first.").format(
                    self.linked_order
                )
            )

    # =========================================================================
    # CACHE MANAGEMENT
    # =========================================================================

    def clear_quotation_cache(self):
        """Clear cached Quotation data."""
        cache_keys = [
            f"quotation:{self.name}",
            f"seller_quotations:{self.seller}",
            f"rfq_quotations:{self.rfq}",
            f"tenant_quotations:{self.tenant}",
        ]
        for key in cache_keys:
            frappe.cache().delete_value(key)


# =============================================================================
# WHITELISTED API FUNCTIONS
# =============================================================================


@frappe.whitelist()
def get_quotation_list(rfq=None, seller=None, status=None, tenant=None, limit=20, offset=0):
    """
    Get list of Quotations with optional filters.

    Args:
        rfq: Optional RFQ filter
        seller: Optional seller filter
        status: Optional status filter
        tenant: Optional tenant filter
        limit: Number of records to return (default 20)
        offset: Starting position (default 0)

    Returns:
        list: List of Quotation records
    """
    filters = {}

    if rfq:
        filters["rfq"] = rfq
    if seller:
        filters["seller"] = seller
    if status:
        filters["status"] = status
    if tenant:
        filters["tenant"] = tenant

    quotations = frappe.get_all(
        "Quotation",
        filters=filters,
        fields=[
            "name", "quotation_number", "status", "rfq", "rfq_title",
            "seller", "seller_name", "submission_date", "validity_date",
            "total_amount", "currency", "delivery_days", "incoterm"
        ],
        order_by="submission_date desc",
        start=cint(offset),
        page_length=cint(limit)
    )

    return quotations


@frappe.whitelist()
def get_quotation_details(quotation_name):
    """
    Get detailed Quotation information.

    Args:
        quotation_name: The Quotation document name

    Returns:
        dict: Quotation details with items
    """
    quotation = frappe.get_doc("Quotation", quotation_name)

    return {
        "quotation": quotation.as_dict(),
        "items": [item.as_dict() for item in quotation.items],
        "item_count": len(quotation.items)
    }


@frappe.whitelist()
def create_quotation(rfq, seller, items, validity_date,
                     currency="USD", incoterm="EXW", delivery_days=None,
                     payment_terms=None, shipping_cost=0, tax_amount=0,
                     discount_percentage=0, seller_notes=None):
    """
    Create a new Quotation.

    Args:
        rfq: The RFQ document name
        seller: The Seller Profile name
        items: List of quotation items
        validity_date: Date until which quotation is valid
        currency: Currency (default USD)
        incoterm: Incoterm (default EXW)
        delivery_days: Estimated delivery days
        payment_terms: Payment terms
        shipping_cost: Shipping cost
        tax_amount: Tax amount
        discount_percentage: Discount percentage
        seller_notes: Seller notes

    Returns:
        dict: Created Quotation info
    """
    doc = frappe.new_doc("Quotation")
    doc.rfq = rfq
    doc.seller = seller
    doc.validity_date = validity_date
    doc.currency = currency
    doc.incoterm = incoterm
    doc.delivery_days = delivery_days
    doc.payment_terms = payment_terms
    doc.shipping_cost = flt(shipping_cost)
    doc.tax_amount = flt(tax_amount)
    doc.discount_percentage = flt(discount_percentage)
    doc.seller_notes = seller_notes

    # Add items
    if items:
        for item in items:
            doc.append("items", item)

    doc.insert()

    return {
        "name": doc.name,
        "quotation_number": doc.quotation_number,
        "message": _("Quotation created successfully"),
        "status": doc.status
    }


@frappe.whitelist()
def submit_quotation(quotation_name):
    """
    Submit a Quotation to the buyer.

    Args:
        quotation_name: The Quotation document name

    Returns:
        dict: Success message
    """
    doc = frappe.get_doc("Quotation", quotation_name)
    doc.submit_quotation()

    return {
        "success": True,
        "message": _("Quotation submitted successfully"),
        "status": doc.status
    }


@frappe.whitelist()
def start_quotation_review(quotation_name):
    """
    Start reviewing a Quotation.

    Args:
        quotation_name: The Quotation document name

    Returns:
        dict: Success message
    """
    doc = frappe.get_doc("Quotation", quotation_name)
    doc.start_review()

    return {
        "success": True,
        "message": _("Review started"),
        "status": doc.status
    }


@frappe.whitelist()
def select_quotation(quotation_name, evaluation_score=None, evaluation_notes=None):
    """
    Select a Quotation as the winner.

    Args:
        quotation_name: The Quotation document name
        evaluation_score: Optional evaluation score
        evaluation_notes: Optional evaluation notes

    Returns:
        dict: Success message
    """
    doc = frappe.get_doc("Quotation", quotation_name)
    doc.select(evaluation_score, evaluation_notes)

    return {
        "success": True,
        "message": _("Quotation selected"),
        "status": doc.status
    }


@frappe.whitelist()
def reject_quotation(quotation_name, reason=None, evaluation_score=None, evaluation_notes=None):
    """
    Reject a Quotation.

    Args:
        quotation_name: The Quotation document name
        reason: Rejection reason
        evaluation_score: Optional evaluation score
        evaluation_notes: Optional evaluation notes

    Returns:
        dict: Success message
    """
    doc = frappe.get_doc("Quotation", quotation_name)
    doc.reject(reason, evaluation_score, evaluation_notes)

    return {
        "success": True,
        "message": _("Quotation rejected"),
        "status": doc.status
    }


@frappe.whitelist()
def cancel_quotation(quotation_name, reason=None):
    """
    Cancel a Quotation.

    Args:
        quotation_name: The Quotation document name
        reason: Optional cancellation reason

    Returns:
        dict: Success message
    """
    doc = frappe.get_doc("Quotation", quotation_name)
    doc.cancel(reason)

    return {
        "success": True,
        "message": _("Quotation cancelled"),
        "status": doc.status
    }


@frappe.whitelist()
def create_order_from_quotation(quotation_name):
    """
    Create an order from a selected Quotation.

    Args:
        quotation_name: The Quotation document name

    Returns:
        dict: Order creation result
    """
    doc = frappe.get_doc("Quotation", quotation_name)
    return doc.create_order()


@frappe.whitelist()
def get_quotations_for_rfq(rfq_name, status=None):
    """
    Get all quotations for a specific RFQ.

    Args:
        rfq_name: The RFQ document name
        status: Optional status filter

    Returns:
        list: List of quotations
    """
    filters = {"rfq": rfq_name}
    if status:
        filters["status"] = status

    return frappe.get_all(
        "Quotation",
        filters=filters,
        fields=[
            "name", "quotation_number", "seller", "seller_name", "seller_company",
            "status", "total_amount", "currency", "delivery_days",
            "validity_date", "submission_date", "incoterm", "payment_terms"
        ],
        order_by="total_amount asc"
    )


@frappe.whitelist()
def get_quotations_for_seller(seller_name, status=None, limit=20, offset=0):
    """
    Get all quotations by a specific seller.

    Args:
        seller_name: The Seller Profile name
        status: Optional status filter
        limit: Number of records to return
        offset: Starting position

    Returns:
        list: List of quotations
    """
    filters = {"seller": seller_name}
    if status:
        filters["status"] = status

    return frappe.get_all(
        "Quotation",
        filters=filters,
        fields=[
            "name", "quotation_number", "rfq", "rfq_title", "rfq_buyer_company",
            "status", "total_amount", "currency", "delivery_days",
            "validity_date", "submission_date"
        ],
        order_by="submission_date desc",
        start=cint(offset),
        page_length=cint(limit)
    )


@frappe.whitelist()
def compare_quotations(rfq_name):
    """
    Get comparison data for all quotations on an RFQ.

    Args:
        rfq_name: The RFQ document name

    Returns:
        dict: Comparison data including summary stats
    """
    quotations = frappe.get_all(
        "Quotation",
        filters={
            "rfq": rfq_name,
            "status": ["not in", ["Draft", "Cancelled"]]
        },
        fields=[
            "name", "quotation_number", "seller", "seller_name",
            "total_amount", "currency", "delivery_days", "incoterm",
            "payment_terms", "validity_date", "status",
            "buyer_evaluation_score"
        ],
        order_by="total_amount asc"
    )

    if not quotations:
        return {
            "quotations": [],
            "summary": {
                "count": 0,
                "lowest": None,
                "highest": None,
                "average": None
            }
        }

    amounts = [flt(q.total_amount) for q in quotations if q.total_amount]

    return {
        "quotations": quotations,
        "summary": {
            "count": len(quotations),
            "lowest": min(amounts) if amounts else None,
            "highest": max(amounts) if amounts else None,
            "average": sum(amounts) / len(amounts) if amounts else None
        }
    }


@frappe.whitelist()
def get_quotation_statistics(seller=None, tenant=None, date_from=None, date_to=None):
    """
    Get Quotation statistics.

    Args:
        seller: Optional seller filter
        tenant: Optional tenant filter
        date_from: Start date
        date_to: End date

    Returns:
        dict: Statistics including counts, amounts, etc.
    """
    filters = {}

    if seller:
        filters["seller"] = seller
    if tenant:
        filters["tenant"] = tenant
    if date_from:
        filters["submission_date"] = [">=", date_from]
    if date_to:
        if "submission_date" in filters:
            filters["submission_date"] = ["between", [date_from, date_to]]
        else:
            filters["submission_date"] = ["<=", date_to]

    # Get counts by status
    status_counts = frappe.db.get_all(
        "Quotation",
        filters=filters,
        fields=["status", "count(*) as count"],
        group_by="status"
    )

    status_dict = {s.status: s.count for s in status_counts}
    total = sum(status_dict.values())

    # Calculate win rate
    selected_count = status_dict.get("Selected", 0)
    submitted_count = (
        selected_count +
        status_dict.get("Rejected", 0) +
        status_dict.get("Under Review", 0) +
        status_dict.get("Submitted", 0)
    )
    win_rate = (selected_count / submitted_count * 100) if submitted_count > 0 else 0

    # Get average quotation value
    avg_value = frappe.db.sql("""
        SELECT AVG(total_amount) as avg_value
        FROM `tabQuotation`
        WHERE status NOT IN ('Draft', 'Cancelled')
        {filters}
    """.format(filters="AND seller = %(seller)s" if seller else ""),
    {"seller": seller} if seller else {},
    as_dict=True)

    return {
        "total_quotations": total,
        "status_breakdown": status_dict,
        "submitted_count": submitted_count,
        "selected_count": selected_count,
        "rejected_count": status_dict.get("Rejected", 0),
        "win_rate": flt(win_rate, 2),
        "average_quotation_value": flt(
            avg_value[0].avg_value, 2
        ) if avg_value and avg_value[0].avg_value else 0
    }


@frappe.whitelist()
def check_quotation_validity(quotation_name):
    """
    Check if a quotation is still valid.

    Args:
        quotation_name: The Quotation document name

    Returns:
        dict: Validity status
    """
    doc = frappe.get_doc("Quotation", quotation_name)

    validity_date = getdate(doc.validity_date)
    today = getdate(nowdate())
    days_remaining = date_diff(validity_date, today)

    is_valid = validity_date >= today and doc.status not in ["Expired", "Cancelled", "Rejected"]

    return {
        "is_valid": is_valid,
        "validity_date": doc.validity_date,
        "days_remaining": max(0, days_remaining),
        "status": doc.status
    }


@frappe.whitelist()
def extend_quotation_validity(quotation_name, new_validity_date, reason=None):
    """
    Extend the validity date of a quotation.

    Args:
        quotation_name: The Quotation document name
        new_validity_date: New validity date
        reason: Optional reason for extension

    Returns:
        dict: Success message
    """
    doc = frappe.get_doc("Quotation", quotation_name)

    if doc.status in ["Selected", "Rejected", "Cancelled"]:
        frappe.throw(
            _("Cannot extend validity for {0} quotations").format(doc.status)
        )

    new_date = getdate(new_validity_date)
    old_date = getdate(doc.validity_date)

    if new_date <= old_date:
        frappe.throw(_("New validity date must be after current validity date"))

    if new_date <= getdate(nowdate()):
        frappe.throw(_("New validity date must be in the future"))

    doc.validity_date = new_validity_date

    # If was expired, move back to submitted
    if doc.status == "Expired":
        doc.status = "Submitted"

    if reason:
        doc.seller_notes = (doc.seller_notes or "") + \
            f"\nValidity extended to {new_validity_date}: {reason}"

    doc.save()

    return {
        "success": True,
        "message": _("Validity extended to {0}").format(new_validity_date),
        "new_validity_date": new_validity_date,
        "status": doc.status
    }

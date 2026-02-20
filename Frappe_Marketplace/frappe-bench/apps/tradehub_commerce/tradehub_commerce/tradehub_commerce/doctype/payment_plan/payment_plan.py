# Copyright (c) 2026, Trade Hub and contributors
# For license information, please see license.txt

"""
Payment Plan DocType for Trade Hub B2B Marketplace.

This module implements installment payment management for B2B transactions.
Payment plans allow buyers to pay for orders in multiple installments over time.

Status Workflow:
- Draft: Payment plan is being configured, not yet active
- Active: Payment plan is active and accepting payments
- Partially Paid: Some installments have been paid
- Completed: All installments paid in full
- Overdue: One or more installments are past due
- Defaulted: Payment plan has been defaulted due to non-payment
- Cancelled: Payment plan was cancelled

Key features:
- Multi-tenant data isolation via Order's tenant
- Flexible installment schedules (equal or custom amounts)
- Late fee management with grace periods
- Auto-generation of installment schedules
- Integration with Order payment tracking
- fetch_from pattern for order, buyer, seller, and tenant information
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import (
    flt, cint, getdate, nowdate, now_datetime,
    add_days, add_months, add_to_date, date_diff
)


# Plan type to number of installments mapping
PLAN_TYPE_INSTALLMENTS = {
    "2 Installments": 2,
    "3 Installments": 3,
    "4 Installments": 4,
    "6 Installments": 6,
    "12 Installments": 12
}

# Frequency to days mapping
FREQUENCY_DAYS = {
    "Weekly": 7,
    "Bi-Weekly": 14,
    "Monthly": 30,
    "Quarterly": 90
}

# Valid status transitions
STATUS_TRANSITIONS = {
    "Draft": ["Active", "Cancelled"],
    "Active": ["Partially Paid", "Completed", "Overdue", "Cancelled"],
    "Partially Paid": ["Completed", "Overdue", "Cancelled"],
    "Overdue": ["Partially Paid", "Completed", "Defaulted", "Cancelled"],
    "Defaulted": ["Cancelled"],
    "Completed": [],
    "Cancelled": []
}

# Installment status descriptions
INSTALLMENT_STATUS_DESCRIPTIONS = {
    "Pending": "Payment not yet due or received",
    "Partially Paid": "Partial payment received",
    "Paid": "Full payment received",
    "Overdue": "Payment is past due date",
    "Waived": "Installment has been waived"
}


class PaymentPlan(Document):
    """
    Payment Plan DocType for B2B installment payments.

    Each Payment Plan represents an agreement to pay an order amount
    in multiple installments over a specified period.

    Features:
    - Link to Order with auto-fetched buyer, seller, and tenant details
    - Multi-tenant isolation via order's tenant field
    - Flexible installment schedules
    - Late fee calculation and application
    - Payment tracking per installment
    """

    def before_insert(self):
        """Set defaults before inserting a new Payment Plan."""
        self.set_default_created_date()
        self.set_plan_code()
        self.set_tenant_from_order()
        self.set_currency_from_order()

    def validate(self):
        """Validate Payment Plan data before saving."""
        self.validate_order()
        self.validate_tenant_isolation()
        self.validate_status_transition()
        self.validate_total_amount()
        self.validate_dates()
        self.validate_installments()
        self.calculate_summary()
        self.update_payment_status()

    def on_update(self):
        """Actions after Payment Plan is updated."""
        self.update_order_payment_status()
        self.clear_payment_plan_cache()

    def on_trash(self):
        """Actions before Payment Plan is deleted."""
        self.check_status_for_deletion()

    # =========================================================================
    # DEFAULT SETTINGS
    # =========================================================================

    def set_default_created_date(self):
        """Set default created date to today if not provided."""
        if not self.created_date:
            self.created_date = nowdate()

    def set_plan_code(self):
        """Set plan code for display purposes."""
        if not self.plan_code:
            self.plan_code = self.name or ""

    def set_tenant_from_order(self):
        """
        Set tenant from order if not already set.
        This provides multi-tenant isolation.
        """
        if self.order and not self.tenant:
            order_tenant = frappe.db.get_value(
                "Order", self.order, "tenant"
            )
            if order_tenant:
                self.tenant = order_tenant

    def set_currency_from_order(self):
        """Set currency from order if not provided."""
        if self.order and not self.currency:
            order_currency = frappe.db.get_value(
                "Order", self.order, "currency"
            )
            if order_currency:
                self.currency = order_currency

    # =========================================================================
    # VALIDATION METHODS
    # =========================================================================

    def validate_order(self):
        """Validate order link exists and is valid."""
        if not self.order:
            frappe.throw(_("Order is required"))

        order_status = frappe.db.get_value(
            "Order", self.order, "status"
        )
        # Allow payment plans for orders in various states
        invalid_statuses = ["Draft", "Cancelled", "Refunded"]
        if order_status and order_status in invalid_statuses:
            frappe.throw(
                _("Cannot create Payment Plan for Order with status {0}").format(
                    order_status
                )
            )

        # Check if another payment plan already exists for this order
        if self.is_new():
            existing = frappe.db.exists(
                "Payment Plan",
                {
                    "order": self.order,
                    "status": ["not in", ["Cancelled", "Completed"]]
                }
            )
            if existing:
                frappe.throw(
                    _("An active payment plan already exists for this order: {0}").format(
                        existing
                    )
                )

    def validate_tenant_isolation(self):
        """
        Validate that Payment Plan belongs to user's tenant.
        Inherits tenant from Order to ensure multi-tenant data isolation.
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
                _("Access denied: You can only access Payment Plans in your tenant")
            )

    def validate_status_transition(self):
        """Validate status transitions are valid."""
        if self.is_new():
            return

        old_status = frappe.db.get_value("Payment Plan", self.name, "status")
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

    def validate_total_amount(self):
        """Validate total amount is positive and matches order."""
        if flt(self.total_amount) <= 0:
            frappe.throw(_("Total plan amount must be greater than zero"))

        if self.order and self.order_total:
            if flt(self.total_amount) > flt(self.order_total):
                frappe.throw(
                    _("Payment plan amount ({0}) cannot exceed order total ({1})").format(
                        self.total_amount, self.order_total
                    )
                )

    def validate_dates(self):
        """Validate start date and end date."""
        if not self.start_date:
            frappe.throw(_("Start date is required"))

        if self.end_date and getdate(self.end_date) < getdate(self.start_date):
            frappe.throw(_("End date cannot be before start date"))

    def validate_installments(self):
        """Validate installment schedule."""
        if not self.installments or len(self.installments) == 0:
            frappe.throw(_("At least one installment is required"))

        # Validate installment numbers are sequential
        installment_numbers = [inst.installment_number for inst in self.installments]
        expected_numbers = list(range(1, len(self.installments) + 1))
        if sorted(installment_numbers) != expected_numbers:
            frappe.throw(_("Installment numbers must be sequential starting from 1"))

        # Validate total installment amounts equal total amount
        total_installment_amount = sum(flt(inst.amount) for inst in self.installments)
        if abs(flt(total_installment_amount) - flt(self.total_amount)) > 0.01:
            frappe.throw(
                _("Sum of installment amounts ({0}) must equal total plan amount ({1})").format(
                    total_installment_amount, self.total_amount
                )
            )

        # Validate due dates are sequential
        prev_date = None
        for inst in sorted(self.installments, key=lambda x: x.installment_number):
            if not inst.due_date:
                frappe.throw(
                    _("Due date is required for installment {0}").format(
                        inst.installment_number
                    )
                )
            if prev_date and getdate(inst.due_date) <= prev_date:
                frappe.throw(
                    _("Due dates must be in sequential order. "
                      "Installment {0} has an earlier date than previous installment").format(
                        inst.installment_number
                    )
                )
            prev_date = getdate(inst.due_date)

        # Calculate total_due for each installment
        for inst in self.installments:
            inst.total_due = flt(inst.amount) + flt(inst.late_fee_amount)

    # =========================================================================
    # CALCULATION METHODS
    # =========================================================================

    def calculate_summary(self):
        """Calculate payment summary from installments."""
        if not self.installments:
            return

        paid_amount = 0
        paid_count = 0
        pending_count = 0
        overdue_count = 0
        next_due_date = None
        last_payment_date = None

        today = getdate(nowdate())

        for inst in self.installments:
            if inst.status == "Paid":
                paid_amount += flt(inst.paid_amount)
                paid_count += 1
                if inst.paid_date:
                    if not last_payment_date or getdate(inst.paid_date) > last_payment_date:
                        last_payment_date = getdate(inst.paid_date)
            elif inst.status == "Partially Paid":
                paid_amount += flt(inst.paid_amount)
                # Check if overdue
                if inst.due_date and getdate(inst.due_date) < today:
                    overdue_count += 1
                    inst.is_overdue = 1
                    inst.days_overdue = date_diff(today, getdate(inst.due_date))
                else:
                    pending_count += 1
                    if not next_due_date or getdate(inst.due_date) < next_due_date:
                        next_due_date = getdate(inst.due_date)
            elif inst.status == "Pending":
                # Check if overdue
                if inst.due_date and getdate(inst.due_date) < today:
                    overdue_count += 1
                    inst.is_overdue = 1
                    inst.days_overdue = date_diff(today, getdate(inst.due_date))
                    inst.status = "Overdue"
                else:
                    pending_count += 1
                    inst.is_overdue = 0
                    inst.days_overdue = 0
                    if not next_due_date or getdate(inst.due_date) < next_due_date:
                        next_due_date = getdate(inst.due_date)
            elif inst.status == "Overdue":
                overdue_count += 1
                inst.is_overdue = 1
                if inst.due_date:
                    inst.days_overdue = date_diff(today, getdate(inst.due_date))
            elif inst.status == "Waived":
                paid_count += 1  # Treat waived as paid for counting

        self.paid_amount = paid_amount
        self.pending_amount = flt(self.total_amount) - paid_amount
        self.paid_installments = paid_count
        self.pending_installments = pending_count
        self.overdue_installments = overdue_count
        self.next_due_date = next_due_date
        self.last_payment_date = last_payment_date

        # Calculate end date from last installment
        if self.installments:
            last_due_date = max(getdate(inst.due_date) for inst in self.installments)
            self.end_date = last_due_date

    def update_payment_status(self):
        """Update payment plan status based on installment states."""
        if self.status in ["Draft", "Cancelled"]:
            return

        if self.paid_installments == self.number_of_installments:
            self.status = "Completed"
        elif self.overdue_installments > 0:
            # Check if defaulted (e.g., more than 3 overdue installments)
            if self.overdue_installments >= 3:
                self.status = "Defaulted"
            else:
                self.status = "Overdue"
        elif self.paid_installments > 0:
            self.status = "Partially Paid"

    # =========================================================================
    # INSTALLMENT GENERATION
    # =========================================================================

    def generate_installments(self):
        """
        Generate installment schedule based on plan type and settings.

        Returns:
            bool: True if installments were generated successfully
        """
        # Determine number of installments
        if self.plan_type in PLAN_TYPE_INSTALLMENTS:
            num_installments = PLAN_TYPE_INSTALLMENTS[self.plan_type]
        elif self.plan_type == "Custom":
            num_installments = cint(self.number_of_installments) or 2
        else:  # Standard
            num_installments = cint(self.number_of_installments) or 2

        self.number_of_installments = num_installments

        # Calculate installment amount (equal split)
        installment_amount = flt(self.total_amount / num_installments, 2)
        remaining = flt(self.total_amount) - (installment_amount * num_installments)

        # Clear existing installments
        self.installments = []

        # Generate installments
        start_date = getdate(self.start_date)
        frequency = self.installment_frequency or "Monthly"

        for i in range(num_installments):
            # Calculate due date
            if frequency == "Weekly":
                due_date = add_days(start_date, i * 7)
            elif frequency == "Bi-Weekly":
                due_date = add_days(start_date, i * 14)
            elif frequency == "Monthly":
                due_date = add_months(start_date, i)
            elif frequency == "Quarterly":
                due_date = add_months(start_date, i * 3)
            else:  # Custom - default to monthly
                due_date = add_months(start_date, i)

            # Add remaining to last installment
            amount = installment_amount
            if i == num_installments - 1:
                amount += remaining

            self.append("installments", {
                "installment_number": i + 1,
                "due_date": due_date,
                "amount": amount,
                "status": "Pending",
                "paid_amount": 0,
                "late_fee_amount": 0,
                "total_due": amount
            })

        self.save()
        return True

    # =========================================================================
    # PAYMENT RECORDING
    # =========================================================================

    def record_installment_payment(
        self, installment_number, amount, payment_method=None, reference=None
    ):
        """
        Record a payment for a specific installment.

        Args:
            installment_number: The installment number to pay
            amount: Payment amount
            payment_method: Optional payment method
            reference: Optional payment reference

        Returns:
            dict: Payment result details
        """
        # Find the installment
        installment = None
        for inst in self.installments:
            if inst.installment_number == installment_number:
                installment = inst
                break

        if not installment:
            frappe.throw(
                _("Installment {0} not found").format(installment_number)
            )

        if installment.status in ["Paid", "Waived"]:
            frappe.throw(
                _("Installment {0} is already {1}").format(
                    installment_number, installment.status
                )
            )

        if flt(amount) <= 0:
            frappe.throw(_("Payment amount must be greater than zero"))

        # Calculate new paid amount
        new_paid_amount = flt(installment.paid_amount) + flt(amount)
        total_required = flt(installment.amount) + flt(installment.late_fee_amount)

        installment.paid_amount = min(new_paid_amount, total_required)
        installment.paid_date = nowdate()

        if payment_method:
            installment.payment_method = payment_method
        if reference:
            installment.payment_reference = reference

        # Update installment status
        if flt(installment.paid_amount) >= total_required:
            installment.status = "Paid"
        else:
            installment.status = "Partially Paid"

        self.save()

        return {
            "success": True,
            "installment_number": installment_number,
            "paid_amount": installment.paid_amount,
            "remaining": max(0, total_required - flt(installment.paid_amount)),
            "status": installment.status
        }

    def apply_late_fees(self):
        """
        Apply late fees to overdue installments.

        Returns:
            dict: Summary of late fees applied
        """
        if not self.auto_apply_late_fees:
            return {"success": False, "message": "Auto late fees not enabled"}

        today = getdate(nowdate())
        fees_applied = []

        for inst in self.installments:
            if inst.status not in ["Paid", "Waived"]:
                if inst.due_date and getdate(inst.due_date) < today:
                    # Check grace period
                    days_overdue = date_diff(today, getdate(inst.due_date))
                    if days_overdue > cint(self.grace_period_days):
                        # Calculate late fee
                        late_fee = 0
                        if self.late_fee_percentage:
                            late_fee += flt(inst.amount) * flt(self.late_fee_percentage) / 100
                        if self.late_fee_flat:
                            late_fee += flt(self.late_fee_flat)

                        if late_fee > 0 and flt(inst.late_fee_amount) < late_fee:
                            inst.late_fee_amount = late_fee
                            inst.total_due = flt(inst.amount) + late_fee
                            fees_applied.append({
                                "installment": inst.installment_number,
                                "late_fee": late_fee
                            })

        if fees_applied:
            self.save()

        return {
            "success": True,
            "fees_applied": fees_applied,
            "total_fees": sum(f["late_fee"] for f in fees_applied)
        }

    def waive_installment(self, installment_number, reason=None):
        """
        Waive an installment payment.

        Args:
            installment_number: The installment number to waive
            reason: Optional reason for waiving

        Returns:
            bool: True if waived successfully
        """
        # Find the installment
        installment = None
        for inst in self.installments:
            if inst.installment_number == installment_number:
                installment = inst
                break

        if not installment:
            frappe.throw(
                _("Installment {0} not found").format(installment_number)
            )

        if installment.status == "Paid":
            frappe.throw(
                _("Cannot waive a paid installment")
            )

        installment.status = "Waived"

        if reason:
            self.internal_notes = (self.internal_notes or "") + \
                f"\nInstallment {installment_number} waived: {reason}"

        self.save()
        return True

    # =========================================================================
    # STATUS MANAGEMENT
    # =========================================================================

    def activate_plan(self):
        """
        Activate the payment plan.

        Returns:
            bool: True if activated successfully
        """
        if self.status != "Draft":
            frappe.throw(_("Only Draft payment plans can be activated"))

        if not self.installments or len(self.installments) == 0:
            frappe.throw(_("Cannot activate without installments"))

        self.status = "Active"
        self.save()
        return True

    def cancel_plan(self, reason=None):
        """
        Cancel the payment plan.

        Args:
            reason: Optional cancellation reason

        Returns:
            bool: True if cancelled successfully
        """
        if self.status == "Completed":
            frappe.throw(_("Cannot cancel a completed payment plan"))

        if reason:
            self.internal_notes = (self.internal_notes or "") + \
                f"\nCancelled: {reason}"

        self.status = "Cancelled"
        self.save()
        return True

    # =========================================================================
    # LINKED DOCUMENT UPDATES
    # =========================================================================

    def update_order_payment_status(self):
        """Update the linked Order's payment status based on this plan."""
        if not self.order:
            return

        # Update order paid amount from payment plan
        if self.status in ["Active", "Partially Paid", "Completed", "Overdue"]:
            frappe.db.set_value(
                "Order", self.order,
                {
                    "paid_amount": self.paid_amount,
                    "last_payment_date": self.last_payment_date
                }
            )

    # =========================================================================
    # DELETION CHECKS
    # =========================================================================

    def check_status_for_deletion(self):
        """Check if Payment Plan can be deleted based on status."""
        if self.status not in ["Draft", "Cancelled"]:
            frappe.throw(
                _("Cannot delete Payment Plan with status {0}. "
                  "Only Draft or Cancelled plans can be deleted.").format(
                    self.status
                )
            )

    # =========================================================================
    # CACHE MANAGEMENT
    # =========================================================================

    def clear_payment_plan_cache(self):
        """Clear cached Payment Plan data."""
        cache_keys = [
            f"payment_plan:{self.name}",
            f"order_payment_plans:{self.order}",
            f"buyer_payment_plans:{self.buyer}",
            f"tenant_payment_plans:{self.tenant}",
        ]
        for key in cache_keys:
            frappe.cache().delete_value(key)


# =============================================================================
# WHITELISTED API FUNCTIONS
# =============================================================================


@frappe.whitelist()
def get_payment_plan_list(buyer=None, seller=None, order=None, status=None,
                          tenant=None, limit=20, offset=0):
    """
    Get list of Payment Plans with optional filters.

    Args:
        buyer: Optional buyer filter
        seller: Optional seller filter
        order: Optional order filter
        status: Optional status filter
        tenant: Optional tenant filter
        limit: Number of records to return (default 20)
        offset: Starting position (default 0)

    Returns:
        list: List of Payment Plan records
    """
    filters = {}

    if buyer:
        filters["buyer"] = buyer
    if seller:
        filters["seller"] = seller
    if order:
        filters["order"] = order
    if status:
        filters["status"] = status
    if tenant:
        filters["tenant"] = tenant

    plans = frappe.get_all(
        "Payment Plan",
        filters=filters,
        fields=[
            "name", "plan_code", "status", "plan_type",
            "order", "order_number", "buyer_name", "seller_name",
            "total_amount", "paid_amount", "pending_amount",
            "currency", "number_of_installments", "paid_installments",
            "next_due_date", "created_date"
        ],
        order_by="created_date desc",
        start=cint(offset),
        page_length=cint(limit)
    )

    return plans


@frappe.whitelist()
def get_payment_plan_details(plan_name):
    """
    Get detailed Payment Plan information.

    Args:
        plan_name: The Payment Plan document name

    Returns:
        dict: Payment Plan details with installments
    """
    plan = frappe.get_doc("Payment Plan", plan_name)

    return {
        "plan": plan.as_dict(),
        "installment_count": len(plan.installments) if plan.installments else 0
    }


@frappe.whitelist()
def create_payment_plan(order, plan_type="Standard", total_amount=None,
                        number_of_installments=2, installment_frequency="Monthly",
                        start_date=None, late_fee_percentage=0, late_fee_flat=0,
                        grace_period_days=7, auto_apply_late_fees=0,
                        buyer_notes=None):
    """
    Create a new Payment Plan for an order.

    Args:
        order: The Order document name (required)
        plan_type: Type of plan (Standard, 2/3/4/6/12 Installments, Custom)
        total_amount: Total amount (defaults to order balance)
        number_of_installments: Number of installments for Standard/Custom
        installment_frequency: Weekly/Bi-Weekly/Monthly/Quarterly/Custom
        start_date: Plan start date (defaults to today)
        late_fee_percentage: Percentage late fee
        late_fee_flat: Flat late fee amount
        grace_period_days: Days before late fees apply
        auto_apply_late_fees: Whether to auto-apply late fees
        buyer_notes: Optional buyer notes

    Returns:
        dict: Created Payment Plan info
    """
    # Get order details
    order_doc = frappe.get_doc("Order", order)

    if not total_amount:
        total_amount = flt(order_doc.balance_amount) or flt(order_doc.total_amount)

    doc = frappe.new_doc("Payment Plan")
    doc.order = order
    doc.plan_type = plan_type
    doc.total_amount = total_amount
    doc.currency = order_doc.currency
    doc.number_of_installments = number_of_installments
    doc.installment_frequency = installment_frequency
    doc.start_date = start_date or nowdate()
    doc.late_fee_percentage = late_fee_percentage
    doc.late_fee_flat = late_fee_flat
    doc.grace_period_days = grace_period_days
    doc.auto_apply_late_fees = auto_apply_late_fees
    doc.buyer_notes = buyer_notes

    doc.insert()

    # Generate installments
    doc.generate_installments()

    return {
        "name": doc.name,
        "message": _("Payment Plan created successfully"),
        "status": doc.status,
        "installments": len(doc.installments)
    }


@frappe.whitelist()
def activate_payment_plan(plan_name):
    """
    Activate a Payment Plan.

    Args:
        plan_name: The Payment Plan document name

    Returns:
        dict: Success message
    """
    doc = frappe.get_doc("Payment Plan", plan_name)
    doc.activate_plan()

    return {
        "success": True,
        "message": _("Payment Plan activated"),
        "status": doc.status
    }


@frappe.whitelist()
def cancel_payment_plan(plan_name, reason=None):
    """
    Cancel a Payment Plan.

    Args:
        plan_name: The Payment Plan document name
        reason: Optional cancellation reason

    Returns:
        dict: Success message
    """
    doc = frappe.get_doc("Payment Plan", plan_name)
    doc.cancel_plan(reason)

    return {
        "success": True,
        "message": _("Payment Plan cancelled"),
        "status": doc.status
    }


@frappe.whitelist()
def record_payment(plan_name, installment_number, amount,
                   payment_method=None, reference=None):
    """
    Record a payment for a specific installment.

    Args:
        plan_name: The Payment Plan document name
        installment_number: Installment number to pay
        amount: Payment amount
        payment_method: Optional payment method
        reference: Optional payment reference

    Returns:
        dict: Payment result
    """
    doc = frappe.get_doc("Payment Plan", plan_name)
    return doc.record_installment_payment(
        cint(installment_number), flt(amount), payment_method, reference
    )


@frappe.whitelist()
def waive_installment(plan_name, installment_number, reason=None):
    """
    Waive an installment payment.

    Args:
        plan_name: The Payment Plan document name
        installment_number: Installment number to waive
        reason: Optional reason for waiving

    Returns:
        dict: Success message
    """
    doc = frappe.get_doc("Payment Plan", plan_name)
    doc.waive_installment(cint(installment_number), reason)

    return {
        "success": True,
        "message": _("Installment {0} waived").format(installment_number)
    }


@frappe.whitelist()
def apply_late_fees(plan_name):
    """
    Apply late fees to overdue installments.

    Args:
        plan_name: The Payment Plan document name

    Returns:
        dict: Late fees application result
    """
    doc = frappe.get_doc("Payment Plan", plan_name)
    return doc.apply_late_fees()


@frappe.whitelist()
def regenerate_installments(plan_name):
    """
    Regenerate installment schedule for a plan.

    Args:
        plan_name: The Payment Plan document name

    Returns:
        dict: Success message
    """
    doc = frappe.get_doc("Payment Plan", plan_name)

    if doc.status not in ["Draft"]:
        frappe.throw(_("Can only regenerate installments for Draft plans"))

    doc.generate_installments()

    return {
        "success": True,
        "message": _("Installments regenerated"),
        "installment_count": len(doc.installments)
    }


@frappe.whitelist()
def get_order_payment_plans(order_name, include_cancelled=0):
    """
    Get all payment plans for an order.

    Args:
        order_name: The Order document name
        include_cancelled: Whether to include cancelled plans

    Returns:
        list: List of payment plans
    """
    filters = {"order": order_name}

    if not cint(include_cancelled):
        filters["status"] = ["!=", "Cancelled"]

    return frappe.get_all(
        "Payment Plan",
        filters=filters,
        fields=[
            "name", "plan_code", "status", "plan_type",
            "total_amount", "paid_amount", "pending_amount",
            "number_of_installments", "paid_installments",
            "overdue_installments", "next_due_date"
        ],
        order_by="created_date desc"
    )


@frappe.whitelist()
def get_overdue_plans(tenant=None, limit=50):
    """
    Get all overdue payment plans.

    Args:
        tenant: Optional tenant filter
        limit: Maximum number of records

    Returns:
        list: List of overdue payment plans
    """
    filters = {"status": ["in", ["Overdue", "Defaulted"]]}

    if tenant:
        filters["tenant"] = tenant

    return frappe.get_all(
        "Payment Plan",
        filters=filters,
        fields=[
            "name", "plan_code", "status", "order", "order_number",
            "buyer_name", "seller_name", "total_amount", "pending_amount",
            "overdue_installments", "next_due_date"
        ],
        order_by="overdue_installments desc",
        page_length=cint(limit)
    )


@frappe.whitelist()
def get_payment_plan_statistics(buyer=None, seller=None, tenant=None):
    """
    Get Payment Plan statistics.

    Args:
        buyer: Optional buyer filter
        seller: Optional seller filter
        tenant: Optional tenant filter

    Returns:
        dict: Statistics including counts and amounts
    """
    filters = {}

    if buyer:
        filters["buyer"] = buyer
    if seller:
        filters["seller"] = seller
    if tenant:
        filters["tenant"] = tenant

    # Get counts by status
    status_counts = frappe.db.get_all(
        "Payment Plan",
        filters=filters,
        fields=["status", "count(*) as count"],
        group_by="status"
    )

    status_dict = {s.status: s.count for s in status_counts}
    total = sum(status_dict.values())

    # Get total amounts
    amounts = frappe.db.sql("""
        SELECT
            SUM(total_amount) as total_plan_amount,
            SUM(paid_amount) as total_paid,
            SUM(pending_amount) as total_pending
        FROM `tabPayment Plan`
        WHERE status NOT IN ('Draft', 'Cancelled')
        {filters}
    """.format(
        filters="AND buyer = %(buyer)s" if buyer else ""
    ), {"buyer": buyer} if buyer else {}, as_dict=True)

    amount_data = amounts[0] if amounts else {}

    return {
        "total_plans": total,
        "status_breakdown": status_dict,
        "active_count": status_dict.get("Active", 0),
        "completed_count": status_dict.get("Completed", 0),
        "overdue_count": status_dict.get("Overdue", 0) + status_dict.get("Defaulted", 0),
        "total_plan_amount": flt(amount_data.get("total_plan_amount", 0), 2),
        "total_paid": flt(amount_data.get("total_paid", 0), 2),
        "total_pending": flt(amount_data.get("total_pending", 0), 2)
    }


@frappe.whitelist()
def check_and_update_overdue_plans():
    """
    Background job to check and update overdue payment plans.

    This function should be scheduled to run daily.

    Returns:
        dict: Summary of updates made
    """
    # Get all active or partially paid plans
    plans = frappe.get_all(
        "Payment Plan",
        filters={"status": ["in", ["Active", "Partially Paid"]]},
        pluck="name"
    )

    updated = 0
    for plan_name in plans:
        doc = frappe.get_doc("Payment Plan", plan_name)
        old_status = doc.status

        # Recalculate summary which updates overdue status
        doc.calculate_summary()
        doc.update_payment_status()

        if doc.status != old_status:
            doc.save()
            updated += 1

    return {
        "checked": len(plans),
        "updated": updated
    }

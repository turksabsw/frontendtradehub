# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

"""
RFQ Quote DocType Controller

Seller quotes with NDA check and deadline validation.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime


class RFQQuote(Document):
    """
    Controller for RFQ Quote DocType.

    Validates NDA signature and deadline before quote submission.
    """

    def before_insert(self):
        """Set submission timestamp."""
        if not self.submitted_at:
            self.submitted_at = now_datetime()

    def validate(self):
        """Validate quote data."""
        self.validate_nda_signed()
        self.validate_deadline()
        self.validate_duplicate_quote()
        self.validate_rfq_status()

    def validate_nda_signed(self):
        """Check NDA is signed if required."""
        rfq = frappe.get_doc("RFQ", self.rfq)

        if rfq.requires_nda:
            from tradehub_commerce.tradehub_commerce.rfq_utils.nda_integration import check_nda_signed

            if not check_nda_signed(self.rfq, self.seller):
                frappe.throw(
                    _("NDA must be signed before submitting a quote. "
                      "Please sign the NDA first.")
                )

    def validate_deadline(self):
        """Check RFQ deadline hasn't passed."""
        rfq = frappe.get_doc("RFQ", self.rfq)

        if rfq.deadline and now_datetime() > rfq.deadline:
            frappe.throw(_("Quote deadline has passed. Cannot submit quote."))

    def validate_duplicate_quote(self):
        """Check seller hasn't already submitted a quote."""
        if self.is_new():
            existing = frappe.db.exists(
                "RFQ Quote",
                {"rfq": self.rfq, "seller": self.seller}
            )
            if existing:
                frappe.throw(
                    _("You have already submitted a quote for this RFQ. "
                      "Use revision feature to update your quote.")
                )

    def validate_rfq_status(self):
        """Check RFQ is accepting quotes."""
        rfq = frappe.get_doc("RFQ", self.rfq)

        if rfq.status not in ["Published", "Quoting"]:
            frappe.throw(
                _("This RFQ is not accepting quotes. Current status: {0}").format(
                    rfq.status
                )
            )

    def after_insert(self):
        """Post-insert processing."""
        self._update_rfq_status()
        self._notify_buyer()

    def _update_rfq_status(self):
        """Update RFQ status to Quoting if first quote."""
        rfq = frappe.get_doc("RFQ", self.rfq)
        if rfq.status == "Published":
            rfq.status = "Quoting"
            rfq.save(ignore_permissions=True)

    def _notify_buyer(self):
        """Notify buyer about new quote."""
        rfq = frappe.get_doc("RFQ", self.rfq)
        buyer_user = frappe.db.get_value("Buyer Profile", rfq.buyer, "user")

        if buyer_user:
            # Create notification
            frappe.get_doc({
                "doctype": "Notification Log",
                "for_user": buyer_user,
                "type": "Alert",
                "document_type": "RFQ Quote",
                "document_name": self.name,
                "subject": _("New quote received for {0}").format(rfq.title),
                "email_content": _("A new quote has been submitted for your RFQ '{0}'").format(
                    rfq.title
                )
            }).insert(ignore_permissions=True)

    def on_update(self):
        """Handle status updates."""
        if self.has_value_changed("status"):
            self._handle_status_change()

    def _handle_status_change(self):
        """Handle status change side effects."""
        if self.status == "Accepted":
            self.accepted_at = now_datetime()
        elif self.status == "Rejected":
            self.rejected_at = now_datetime()

    @frappe.whitelist()
    def withdraw(self):
        """Withdraw the quote."""
        if self.status in ["Accepted", "Rejected"]:
            frappe.throw(_("Cannot withdraw an {0} quote").format(self.status.lower()))

        self.status = "Withdrawn"
        self.save()

        return {"success": True, "message": _("Quote withdrawn")}

    @frappe.whitelist()
    def create_revision(self, new_price=None, new_terms=None, new_delivery_days=None, reason=None):
        """
        Create a revision of this quote.

        Args:
            new_price: New quote price
            new_terms: New terms
            new_delivery_days: New delivery estimate
            reason: Reason for revision

        Returns:
            Revision document name
        """
        if self.status not in ["Submitted", "Under Review"]:
            frappe.throw(_("Cannot revise a quote in {0} status").format(self.status))

        # Calculate revision number
        revision_no = frappe.db.count(
            "RFQ Quote Revision",
            {"original_quote": self.name}
        ) + 1

        # Create revision record
        revision = frappe.get_doc({
            "doctype": "RFQ Quote Revision",
            "original_quote": self.name,
            "revision_no": revision_no,
            "previous_price": self.price,
            "new_price": new_price or self.price,
            "previous_terms": self.terms,
            "new_terms": new_terms or self.terms,
            "previous_delivery_days": self.delivery_days,
            "new_delivery_days": new_delivery_days or self.delivery_days,
            "reason": reason,
            "revised_by": frappe.session.user,
            "revised_at": now_datetime()
        })
        revision.insert()

        # Update quote
        if new_price:
            self.price = new_price
        if new_terms:
            self.terms = new_terms
        if new_delivery_days:
            self.delivery_days = new_delivery_days

        self.revision_count = revision_no
        self.last_revised_at = now_datetime()
        self.save()

        return revision.name

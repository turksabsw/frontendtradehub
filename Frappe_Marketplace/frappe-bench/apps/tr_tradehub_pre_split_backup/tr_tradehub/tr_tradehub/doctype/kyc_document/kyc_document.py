# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import getdate, nowdate, now_datetime


class KYCDocument(Document):
    """
    KYC Document child DocType controller.

    Manages verification documents for KYC profiles including:
    - Document type validation
    - Expiry date checking
    - Verification status tracking
    """

    def validate(self):
        """Validate document data."""
        self.validate_dates()
        self.check_document_expiry()

    def validate_dates(self):
        """Validate issue and expiry dates."""
        if self.issue_date and self.expiry_date:
            if getdate(self.expiry_date) <= getdate(self.issue_date):
                frappe.throw(
                    _("Expiry Date must be after Issue Date for document: {0}").format(
                        self.document_name or self.document_type
                    )
                )

        # Issue date should not be in the future
        if self.issue_date and getdate(self.issue_date) > getdate(nowdate()):
            frappe.throw(
                _("Issue Date cannot be in the future for document: {0}").format(
                    self.document_name or self.document_type
                )
            )

    def check_document_expiry(self):
        """Check if document is expired and update status."""
        if self.expiry_date:
            if getdate(self.expiry_date) < getdate(nowdate()):
                if self.verification_status not in ["Expired", "Rejected"]:
                    self.verification_status = "Expired"
                    frappe.msgprint(
                        msg=_("Document '{0}' has expired").format(
                            self.document_name or self.document_type
                        ),
                        title=_("Document Expired"),
                        indicator="orange",
                        alert=True
                    )

    def is_valid(self):
        """
        Check if document is valid (verified and not expired).

        Returns:
            bool: True if document is valid
        """
        if self.verification_status != "Verified":
            return False

        if self.expiry_date and getdate(self.expiry_date) < getdate(nowdate()):
            return False

        return True

    def days_until_expiry(self):
        """
        Calculate days until document expires.

        Returns:
            int: Days until expiry, or None if no expiry date
        """
        if not self.expiry_date:
            return None

        from frappe.utils import date_diff
        return date_diff(self.expiry_date, nowdate())

    def verify_document(self, user=None, notes=None):
        """
        Mark document as verified.

        Args:
            user: User who verified the document
            notes: Verification notes
        """
        self.verification_status = "Verified"
        self.verified_at = now_datetime()
        self.verified_by = user or frappe.session.user

        if notes:
            self.verification_notes = notes

    def reject_document(self, reason, user=None):
        """
        Mark document as rejected.

        Args:
            reason: Rejection reason
            user: User who rejected the document
        """
        self.verification_status = "Rejected"
        self.rejection_reason = reason
        self.verified_at = now_datetime()
        self.verified_by = user or frappe.session.user

# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import getdate, nowdate


class SellerCertification(Document):
    """
    Seller Certification child DocType controller.

    Manages certifications for Premium Sellers including quality,
    environmental, and industry-specific certifications.
    """

    def validate(self):
        """Validate the certification data."""
        self.validate_dates()
        self.check_expiry()

    def validate_dates(self):
        """Validate issue and expiry dates."""
        if self.issue_date and self.expiry_date:
            if getdate(self.expiry_date) < getdate(self.issue_date):
                frappe.throw(
                    _("Expiry Date cannot be before Issue Date for certification: {0}").format(
                        self.certification_name
                    )
                )

    def check_expiry(self):
        """Check if the certification is expired and show warning."""
        if self.expiry_date and getdate(self.expiry_date) < getdate(nowdate()):
            frappe.msgprint(
                msg=_("Certification '{0}' has expired on {1}").format(
                    self.certification_name, self.expiry_date
                ),
                title=_("Expired Certification"),
                indicator="orange",
                alert=True
            )

    def is_valid(self):
        """Check if the certification is currently valid."""
        if not self.expiry_date:
            return True
        return getdate(self.expiry_date) >= getdate(nowdate())

    def days_until_expiry(self):
        """Get the number of days until expiry."""
        if not self.expiry_date:
            return None
        delta = getdate(self.expiry_date) - getdate(nowdate())
        return delta.days

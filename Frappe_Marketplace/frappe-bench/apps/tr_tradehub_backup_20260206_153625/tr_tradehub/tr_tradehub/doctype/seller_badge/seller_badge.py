# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import getdate, nowdate


class SellerBadge(Document):
    """Seller Badge child table for tracking seller achievements and certifications."""

    def validate(self):
        """Validate badge data."""
        self.validate_badge_code()
        self.validate_dates()
        self.check_expiry()

    def validate_badge_code(self):
        """Ensure badge code is uppercase and contains only valid characters."""
        if self.badge_code:
            # Convert to uppercase and replace spaces with underscores
            self.badge_code = self.badge_code.upper().replace(" ", "_")
            # Remove any characters that are not alphanumeric or underscore
            import re
            self.badge_code = re.sub(r'[^A-Z0-9_]', '', self.badge_code)

    def validate_dates(self):
        """Validate earned_date and expires_on dates."""
        if self.earned_date and self.expires_on:
            if getdate(self.expires_on) < getdate(self.earned_date):
                frappe.throw(
                    _("Expires On date cannot be before Earned Date for badge {0}").format(
                        self.badge_name
                    )
                )

    def check_expiry(self):
        """Check if badge has expired and update is_active accordingly."""
        if self.expires_on and getdate(self.expires_on) < getdate(nowdate()):
            self.is_active = 0

# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

"""
RFQ (Request for Quote) DocType Controller

Main RFQ document with workflow management.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime, getdate, today
import hashlib


class RFQ(Document):
    """
    Controller for RFQ DocType.

    Workflow: Draft -> Published -> Quoting -> Negotiation -> Accepted/Ordered/Closed
    """

    def before_insert(self):
        """Generate RFQ code."""
        if not self.rfq_code:
            self.rfq_code = self._generate_rfq_code()

    def _generate_rfq_code(self):
        """Generate unique RFQ code."""
        # Format: RFQ-YYYYMMDD-XXXX (random suffix)
        import random
        import string
        date_part = today().replace("-", "")
        random_part = ''.join(random.choices(string.ascii_uppercase + string.digits, k=4))
        return f"RFQ-{date_part}-{random_part}"

    def validate(self):
        """Validate RFQ data."""
        self.validate_status_transition()
        self.validate_deadline()
        self.validate_nda_requirements()
        self.validate_targeting()

    def validate_status_transition(self):
        """Validate status transitions."""
        if self.is_new():
            return

        old_status = frappe.db.get_value("RFQ", self.name, "status")
        if old_status == self.status:
            return

        valid_transitions = {
            "Draft": ["Published", "Cancelled"],
            "Published": ["Quoting", "Negotiation", "Closed", "Cancelled"],
            "Quoting": ["Negotiation", "Closed", "Cancelled"],
            "Negotiation": ["Accepted", "Closed", "Cancelled"],
            "Accepted": ["Ordered", "Closed"],
            "Ordered": ["Closed"],
            "Closed": [],
            "Cancelled": []
        }

        if self.status not in valid_transitions.get(old_status, []):
            frappe.throw(
                _("Invalid status transition from {0} to {1}").format(
                    old_status, self.status
                )
            )

    def validate_deadline(self):
        """Validate deadline is in the future for publishing."""
        if self.status == "Published" and self.deadline:
            if self.deadline < now_datetime():
                frappe.throw(_("Deadline must be in the future"))

    def validate_nda_requirements(self):
        """Validate NDA template is set when required."""
        if self.requires_nda and not self.nda_template:
            frappe.throw(_("NDA template is required when NDA is enabled"))

    def validate_targeting(self):
        """Validate targeting configuration."""
        if self.target_type == "Selected" and not self.get("target_sellers"):
            frappe.throw(_("At least one seller must be selected for 'Selected' target type"))

        if self.target_type == "Category" and not self.get("target_categories"):
            frappe.throw(_("At least one category must be selected for 'Category' target type"))

    def before_save(self):
        """Handle status-specific logic."""
        if self.has_value_changed("status"):
            self._handle_status_change()

    def _handle_status_change(self):
        """Handle status change side effects."""
        if self.status == "Published":
            self.published_at = now_datetime()
            self._notify_target_sellers()

        elif self.status in ["Closed", "Cancelled"]:
            self.closed_at = now_datetime()

    def _notify_target_sellers(self):
        """Notify target sellers about new RFQ."""
        # TODO: Implement notification logic
        pass

    def on_update(self):
        """Post-save processing."""
        self._update_quote_count()

    def _update_quote_count(self):
        """Update quote statistics."""
        # This could update a denormalized quote count field
        pass

    @frappe.whitelist()
    def publish(self):
        """Publish the RFQ."""
        if self.status != "Draft":
            frappe.throw(_("Only draft RFQs can be published"))

        if not self.deadline:
            frappe.throw(_("Deadline is required to publish"))

        self.status = "Published"
        self.save()

        return {"success": True, "message": _("RFQ published successfully")}

    @frappe.whitelist()
    def close(self, reason=None):
        """Close the RFQ."""
        if self.status in ["Closed", "Cancelled"]:
            frappe.throw(_("RFQ is already closed"))

        self.status = "Closed"
        self.closed_reason = reason
        self.save()

        return {"success": True, "message": _("RFQ closed")}

    @frappe.whitelist()
    def cancel_rfq(self, reason=None):
        """Cancel the RFQ."""
        if self.status in ["Accepted", "Ordered", "Closed"]:
            frappe.throw(_("Cannot cancel RFQ in current status"))

        self.status = "Cancelled"
        self.closed_reason = reason
        self.save()

        # Notify sellers
        self._notify_cancellation()

        return {"success": True, "message": _("RFQ cancelled")}

    def _notify_cancellation(self):
        """Notify sellers about cancellation."""
        # TODO: Implement notification logic
        pass

    def get_quote_count(self):
        """Get number of quotes received."""
        return frappe.db.count("RFQ Quote", {"rfq": self.name})

    def get_quotes(self):
        """Get all quotes for this RFQ."""
        return frappe.get_all(
            "RFQ Quote",
            filters={"rfq": self.name},
            fields=["name", "seller", "price", "currency", "status", "creation"]
        )

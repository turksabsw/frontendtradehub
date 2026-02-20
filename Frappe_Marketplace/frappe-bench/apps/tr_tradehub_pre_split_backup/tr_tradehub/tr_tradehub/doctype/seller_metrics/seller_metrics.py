# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

"""
Seller Metrics DocType Controller

Materialized view for seller KPIs used in rule evaluation.
"""

import frappe
from frappe import _
from frappe.model.document import Document


class SellerMetrics(Document):
    """
    Controller for Seller Metrics DocType.

    Stores calculated seller KPIs for efficient rule evaluation.
    Records are created/updated by scheduled tasks.
    """

    def validate(self):
        """Validate metrics data."""
        self.validate_rates()

    def validate_rates(self):
        """Ensure rate fields are within valid ranges."""
        rate_fields = [
            "cancellation_rate",
            "return_rate",
            "on_time_delivery_rate",
            "positive_review_rate",
            "complaint_rate",
            "repeat_customer_rate"
        ]

        for field in rate_fields:
            value = self.get(field) or 0
            if value < 0:
                self.set(field, 0)
            elif value > 100:
                self.set(field, 100)

        # Validate avg_rating
        if self.avg_rating:
            if self.avg_rating < 0:
                self.avg_rating = 0
            elif self.avg_rating > 5:
                self.avg_rating = 5

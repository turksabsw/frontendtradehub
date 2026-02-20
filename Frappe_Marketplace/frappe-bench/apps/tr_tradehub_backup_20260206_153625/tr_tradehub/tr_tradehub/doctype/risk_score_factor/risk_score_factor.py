# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import now_datetime


class RiskScoreFactor(Document):
    """
    Risk Score Factor - Child table DocType for risk scoring factors

    Represents individual risk factors that contribute to the overall risk score.
    Each factor has a weight, normalized score, and calculated weighted score.
    """

    def validate(self):
        """Validate factor data before save"""
        self.validate_weight()
        self.validate_normalized_score()
        self.calculate_weighted_score()
        self.set_last_updated()

    def validate_weight(self):
        """Validate weight is within acceptable range (0-10)"""
        if self.weight is None:
            self.weight = 1.0

        if self.weight < 0:
            frappe.throw(_("Weight cannot be negative"))

        if self.weight > 10:
            frappe.msgprint(
                _("Weight {0} is unusually high. Typical weights are between 0 and 10.").format(self.weight),
                indicator="orange"
            )

    def validate_normalized_score(self):
        """Validate normalized score is within 0-100 range"""
        if self.normalized_score is None:
            self.normalized_score = 0

        if self.normalized_score < 0:
            self.normalized_score = 0
            frappe.msgprint(_("Normalized score adjusted to 0 (minimum)"), indicator="orange")

        if self.normalized_score > 100:
            self.normalized_score = 100
            frappe.msgprint(_("Normalized score adjusted to 100 (maximum)"), indicator="orange")

    def calculate_weighted_score(self):
        """Calculate the weighted score from normalized score and weight"""
        if self.normalized_score is not None and self.weight is not None:
            self.weighted_score = self.normalized_score * self.weight

    def set_last_updated(self):
        """Set the last updated timestamp"""
        self.last_updated = now_datetime()

    def get_contribution(self, total_weight):
        """
        Get this factor's contribution percentage to the overall score

        Args:
            total_weight: Sum of all factor weights

        Returns:
            Contribution percentage (0-100)
        """
        if not total_weight or total_weight == 0:
            return 0

        return (self.weight / total_weight) * 100

    def is_high_risk_factor(self):
        """Check if this factor indicates high risk"""
        return (
            self.impact in ["Negative", "Critical"] and
            self.normalized_score >= 70 and
            self.is_active
        )

    def is_positive_factor(self):
        """Check if this factor is positive"""
        return (
            self.impact == "Positive" and
            self.normalized_score >= 50 and
            self.is_active
        )

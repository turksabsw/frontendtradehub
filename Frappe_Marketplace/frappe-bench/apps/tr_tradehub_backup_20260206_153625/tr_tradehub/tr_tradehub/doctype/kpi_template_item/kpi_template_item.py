# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
import json


class KPITemplateItem(Document):
    """KPI Template Item child DocType for defining individual KPI metrics."""

    def validate(self):
        """Validate KPI template item data."""
        self.validate_kpi_code()
        self.validate_weight()
        self.validate_thresholds()
        self.validate_filter_criteria()
        self.validate_scoring()

    def validate_kpi_code(self):
        """Validate and format KPI code."""
        if self.kpi_code:
            import re
            # Auto-format to uppercase with underscores
            self.kpi_code = self.kpi_code.upper().replace(" ", "_").replace("-", "_")
            if not re.match(r'^[A-Z0-9_]+$', self.kpi_code):
                frappe.throw(_("KPI code should contain only letters, numbers, and underscores"))

    def validate_weight(self):
        """Validate weight is positive."""
        if self.weight is not None and self.weight < 0:
            frappe.throw(_("Weight cannot be negative"))

        if self.weight == 0:
            frappe.msgprint(
                _("KPI '{0}' has weight of 0 and will not contribute to the overall score").format(
                    self.kpi_name
                ),
                indicator="orange",
                alert=True
            )

    def validate_thresholds(self):
        """Validate threshold values based on threshold type."""
        if self.threshold_type == "Higher is Better":
            # Warning should be between critical and target
            if self.critical_threshold and self.target_value:
                if self.critical_threshold >= self.target_value:
                    frappe.msgprint(
                        _("Warning: Critical threshold should be less than target value for 'Higher is Better' KPIs"),
                        indicator="orange",
                        alert=True
                    )

            if self.warning_threshold:
                if self.critical_threshold and self.warning_threshold <= self.critical_threshold:
                    frappe.msgprint(
                        _("Warning threshold should be greater than critical threshold"),
                        indicator="orange",
                        alert=True
                    )
                if self.target_value and self.warning_threshold >= self.target_value:
                    frappe.msgprint(
                        _("Warning threshold should be less than target value"),
                        indicator="orange",
                        alert=True
                    )

        elif self.threshold_type == "Lower is Better":
            # Warning should be between target and critical
            if self.critical_threshold and self.target_value:
                if self.critical_threshold <= self.target_value:
                    frappe.msgprint(
                        _("Warning: Critical threshold should be greater than target value for 'Lower is Better' KPIs"),
                        indicator="orange",
                        alert=True
                    )

            if self.warning_threshold:
                if self.critical_threshold and self.warning_threshold >= self.critical_threshold:
                    frappe.msgprint(
                        _("Warning threshold should be less than critical threshold"),
                        indicator="orange",
                        alert=True
                    )
                if self.target_value and self.warning_threshold <= self.target_value:
                    frappe.msgprint(
                        _("Warning threshold should be greater than target value"),
                        indicator="orange",
                        alert=True
                    )

    def validate_filter_criteria(self):
        """Validate filter criteria is valid JSON."""
        if self.filter_criteria:
            try:
                parsed = json.loads(self.filter_criteria)
                if not isinstance(parsed, dict):
                    frappe.throw(_("Filter criteria must be a JSON object (dictionary)"))
            except json.JSONDecodeError as e:
                frappe.throw(_("Invalid JSON in filter criteria: {0}").format(str(e)))

    def validate_scoring(self):
        """Validate scoring settings."""
        if self.max_score is not None and self.max_score < 0:
            frappe.throw(_("Max score cannot be negative"))

        if self.bonus_multiplier is not None and self.bonus_multiplier < 0:
            frappe.throw(_("Bonus multiplier cannot be negative"))

        if self.decimal_places is not None and (self.decimal_places < 0 or self.decimal_places > 10):
            frappe.throw(_("Decimal places must be between 0 and 10"))

    def get_status(self, value):
        """
        Get status indicator based on value compared to thresholds.

        Args:
            value: The calculated KPI value

        Returns:
            str: 'success', 'warning', 'critical', or 'neutral'
        """
        if value is None:
            return "neutral"

        if self.threshold_type == "Higher is Better":
            if self.target_value and value >= self.target_value:
                return "success"
            elif self.critical_threshold and value <= self.critical_threshold:
                return "critical"
            elif self.warning_threshold and value <= self.warning_threshold:
                return "warning"
            return "neutral"

        elif self.threshold_type == "Lower is Better":
            if self.target_value and value <= self.target_value:
                return "success"
            elif self.critical_threshold and value >= self.critical_threshold:
                return "critical"
            elif self.warning_threshold and value >= self.warning_threshold:
                return "warning"
            return "neutral"

        elif self.threshold_type == "Range":
            # Assume target_value is the center, warning and critical are bounds
            if self.warning_threshold and self.critical_threshold:
                if abs(value - (self.target_value or 0)) <= self.warning_threshold:
                    return "success"
                elif abs(value - (self.target_value or 0)) >= self.critical_threshold:
                    return "critical"
                return "warning"

        elif self.threshold_type == "Exact":
            if self.target_value and value == self.target_value:
                return "success"
            return "warning"

        return "neutral"

    def calculate_score(self, value):
        """
        Calculate the score contribution from this KPI.

        Args:
            value: The calculated KPI value

        Returns:
            float: The calculated score (0 to max_score)
        """
        if value is None or not self.max_score:
            return 0

        max_score = self.max_score or 100
        target = self.target_value or 0

        if self.scoring_method == "Binary":
            # All or nothing based on meeting target
            if self.threshold_type == "Higher is Better":
                return max_score if value >= target else 0
            elif self.threshold_type == "Lower is Better":
                return max_score if value <= target else 0
            else:
                return max_score if value == target else 0

        elif self.scoring_method == "Linear":
            # Linear scaling from critical to target
            critical = self.critical_threshold or 0

            if self.threshold_type == "Higher is Better":
                if value >= target:
                    # At or above target - full score (possibly with bonus)
                    if self.bonus_multiplier and self.bonus_multiplier > 1 and target > 0:
                        bonus = min((value - target) / target * (self.bonus_multiplier - 1), self.bonus_multiplier - 1)
                        return min(max_score * (1 + bonus), max_score * self.bonus_multiplier)
                    return max_score
                elif value <= critical:
                    return 0
                else:
                    # Linear interpolation between critical and target
                    return max_score * (value - critical) / (target - critical) if target != critical else 0

            elif self.threshold_type == "Lower is Better":
                if value <= target:
                    # At or below target - full score (possibly with bonus)
                    if self.bonus_multiplier and self.bonus_multiplier > 1 and target > 0:
                        bonus = min((target - value) / target * (self.bonus_multiplier - 1), self.bonus_multiplier - 1)
                        return min(max_score * (1 + bonus), max_score * self.bonus_multiplier)
                    return max_score
                elif value >= critical:
                    return 0
                else:
                    # Linear interpolation between target and critical
                    return max_score * (critical - value) / (critical - target) if critical != target else 0

        elif self.scoring_method == "Step":
            # Step-based scoring using thresholds
            if self.threshold_type == "Higher is Better":
                if value >= target:
                    return max_score
                elif self.warning_threshold and value >= self.warning_threshold:
                    return max_score * 0.7
                elif self.critical_threshold and value >= self.critical_threshold:
                    return max_score * 0.3
                return 0
            else:
                if value <= target:
                    return max_score
                elif self.warning_threshold and value <= self.warning_threshold:
                    return max_score * 0.7
                elif self.critical_threshold and value <= self.critical_threshold:
                    return max_score * 0.3
                return 0

        # Default to linear calculation
        return max_score * min(1, max(0, value / target)) if target > 0 else 0

    def get_filter_dict(self):
        """Get filter criteria as a dictionary."""
        if not self.filter_criteria:
            return {}

        try:
            return json.loads(self.filter_criteria)
        except json.JSONDecodeError:
            return {}

    def format_value(self, value):
        """Format the value for display."""
        if value is None:
            return "-"

        decimal_places = self.decimal_places if self.decimal_places is not None else 2
        formatted = f"{value:.{decimal_places}f}"

        if self.unit:
            if self.unit == "%":
                formatted = f"{formatted}%"
            else:
                formatted = f"{formatted} {self.unit}"

        return formatted

    def to_dict(self):
        """Convert to dictionary for API responses."""
        return {
            "name": self.name,
            "kpi_name": self.kpi_name,
            "kpi_code": self.kpi_code,
            "metric_type": self.metric_type,
            "weight": self.weight,
            "is_active": self.is_active,
            "data_source": self.data_source,
            "formula": self.formula,
            "aggregation_method": self.aggregation_method,
            "threshold_type": self.threshold_type,
            "target_value": self.target_value,
            "warning_threshold": self.warning_threshold,
            "critical_threshold": self.critical_threshold,
            "max_score": self.max_score,
            "unit": self.unit,
            "description": self.description
        }

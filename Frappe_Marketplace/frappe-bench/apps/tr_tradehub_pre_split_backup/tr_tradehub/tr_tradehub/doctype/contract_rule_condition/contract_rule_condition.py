# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class ContractRuleCondition(Document):
    """Contract Rule Condition child table for defining contract trigger rules."""

    def validate(self):
        """Validate condition data."""
        self.validate_value_requirement()
        self.validate_numeric_fields()
        self.validate_in_operator_value()

    def validate_value_requirement(self):
        """Validate that value is provided when required by operator."""
        operators_requiring_value = ["=", "!=", ">", "<", ">=", "<=", "contains", "not contains", "in", "not in"]
        operators_not_requiring_value = ["is set", "is not set"]

        if self.operator in operators_requiring_value and not self.value:
            frappe.throw(
                _("Value is required for operator '{0}'").format(self.operator)
            )

        if self.operator in operators_not_requiring_value and self.value:
            frappe.msgprint(
                _("Value will be ignored for operator '{0}'").format(self.operator),
                alert=True
            )

    def validate_numeric_fields(self):
        """Validate that numeric operators are used with numeric fields."""
        numeric_fields = ["order_total", "days_since_registration", "total_orders", "total_revenue"]
        numeric_operators = [">", "<", ">=", "<="]

        if self.operator in numeric_operators and self.field not in numeric_fields:
            frappe.msgprint(
                _("Numeric operator '{0}' may not work correctly with field '{1}'").format(
                    self.operator, self.field
                ),
                alert=True
            )

        # Validate that value is numeric for numeric fields with comparison operators
        if self.field in numeric_fields and self.operator in numeric_operators:
            if self.value:
                try:
                    float(self.value)
                except ValueError:
                    frappe.throw(
                        _("Value must be a number for field '{0}' with operator '{1}'").format(
                            self.field, self.operator
                        )
                    )

    def validate_in_operator_value(self):
        """Validate value format for 'in' and 'not in' operators."""
        if self.operator in ["in", "not in"] and self.value:
            # Value should be comma-separated for 'in' operators
            # Just ensure it's not empty after stripping
            values = [v.strip() for v in self.value.split(",") if v.strip()]
            if not values:
                frappe.throw(
                    _("At least one value is required for operator '{0}'").format(self.operator)
                )

    def evaluate(self, context):
        """
        Evaluate this condition against the given context.

        Args:
            context (dict): Dictionary containing field values to evaluate against.
                           Example: {"user_type": "Seller", "order_total": 1000}

        Returns:
            bool: True if condition is met, False otherwise.
        """
        if not self.field or not self.operator:
            return False

        actual_value = context.get(self.field)

        # Handle 'is set' and 'is not set' operators
        if self.operator == "is set":
            return actual_value is not None and actual_value != ""
        elif self.operator == "is not set":
            return actual_value is None or actual_value == ""

        # If actual value is None, condition is not met (except for 'is not set')
        if actual_value is None:
            return False

        expected_value = self.value

        # Convert values for comparison
        if self.operator in [">", "<", ">=", "<="]:
            try:
                actual_value = float(actual_value) if actual_value else 0
                expected_value = float(expected_value) if expected_value else 0
            except (ValueError, TypeError):
                return False

        # Evaluate based on operator
        if self.operator == "=":
            return str(actual_value) == str(expected_value)
        elif self.operator == "!=":
            return str(actual_value) != str(expected_value)
        elif self.operator == ">":
            return actual_value > expected_value
        elif self.operator == "<":
            return actual_value < expected_value
        elif self.operator == ">=":
            return actual_value >= expected_value
        elif self.operator == "<=":
            return actual_value <= expected_value
        elif self.operator == "contains":
            return str(expected_value).lower() in str(actual_value).lower()
        elif self.operator == "not contains":
            return str(expected_value).lower() not in str(actual_value).lower()
        elif self.operator == "in":
            values = [v.strip().lower() for v in str(expected_value).split(",")]
            return str(actual_value).lower() in values
        elif self.operator == "not in":
            values = [v.strip().lower() for v in str(expected_value).split(",")]
            return str(actual_value).lower() not in values

        return False

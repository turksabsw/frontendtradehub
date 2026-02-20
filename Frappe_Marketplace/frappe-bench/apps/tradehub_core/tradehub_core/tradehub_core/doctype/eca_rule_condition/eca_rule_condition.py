# Copyright (c) 2026, TR TradeHub and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class ECARuleCondition(Document):
    """
    ECA Rule Condition Child Table

    Defines individual conditions for ECA rule evaluation.
    Conditions are evaluated in order with AND/OR logic operators.

    Supported Operators:
    - equals, not_equals: Equality comparison
    - greater_than, less_than, etc.: Numeric comparison
    - contains, not_contains: String contains check
    - starts_with, ends_with: String prefix/suffix check
    - is_set, is_not_set: Null/empty check
    - changed, changed_from, changed_to: Value change detection
    - in_list, not_in_list: List membership check
    - regex_match: Regular expression matching
    """

    def validate(self):
        """Validate the condition configuration"""
        self.validate_operator_value()

    def validate_operator_value(self):
        """Ensure value is provided for operators that require it"""
        # Operators that don't require a value
        no_value_operators = ["is_set", "is_not_set", "changed"]

        if self.operator not in no_value_operators and not self.value:
            frappe.throw(
                frappe._("Value is required for operator '{0}'").format(self.operator),
                title=frappe._("Missing Value")
            )

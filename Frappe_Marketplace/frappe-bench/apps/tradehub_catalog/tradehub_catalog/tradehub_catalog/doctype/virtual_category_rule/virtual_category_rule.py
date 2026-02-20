# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class VirtualCategoryRule(Document):
    """
    Virtual Category Rule child table for defining automatic category assignment conditions.

    Used by Virtual Categories (Category DocType with is_virtual=1) to automatically
    include products that match the defined rule conditions.
    """

    def validate(self):
        """Validate rule condition data."""
        self.validate_value_requirement()
        self.validate_numeric_fields()
        self.validate_in_operator_value()
        self.validate_weight()

    def validate_value_requirement(self):
        """Validate that value is provided when required by operator."""
        operators_requiring_value = [
            "=", "!=", ">", "<", ">=", "<=",
            "contains", "not contains", "in", "not in",
            "starts with", "ends with"
        ]
        operators_not_requiring_value = ["is set", "is not set", "is empty", "is not empty"]

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
        numeric_fields = [
            "price", "discount_percentage", "stock_qty",
            "rating", "review_count", "weight"
        ]
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
            values = [v.strip() for v in self.value.split(",") if v.strip()]
            if not values:
                frappe.throw(
                    _("At least one value is required for operator '{0}'").format(self.operator)
                )

    def validate_weight(self):
        """Validate that weight is a positive integer."""
        if self.weight is not None and self.weight < 0:
            frappe.throw(_("Weight must be a positive integer"))

    def is_rule_active(self):
        """Check if this rule is active."""
        return bool(self.is_active)

    def evaluate(self, context):
        """
        Evaluate this condition against the given product/listing context.

        Args:
            context (dict): Dictionary containing product/listing field values.
                           Example: {"category": "Electronics", "price": 100, "rating": 4.5}

        Returns:
            bool: True if condition is met, False otherwise.
        """
        # Skip inactive rules
        if not self.is_rule_active():
            return False

        if not self.field or not self.operator:
            return False

        actual_value = context.get(self.field)

        # Handle 'is set', 'is not set', 'is empty', 'is not empty' operators
        if self.operator == "is set":
            return actual_value is not None
        elif self.operator == "is not set":
            return actual_value is None
        elif self.operator == "is empty":
            return actual_value is None or actual_value == "" or actual_value == []
        elif self.operator == "is not empty":
            return actual_value is not None and actual_value != "" and actual_value != []

        # If actual value is None, condition is not met (except for special operators above)
        if actual_value is None:
            return False

        expected_value = self.value

        # Convert values for numeric comparison
        if self.operator in [">", "<", ">=", "<="]:
            try:
                actual_value = float(actual_value) if actual_value else 0
                expected_value = float(expected_value) if expected_value else 0
            except (ValueError, TypeError):
                return False

        # Evaluate based on operator
        if self.operator == "=":
            return str(actual_value).lower() == str(expected_value).lower()
        elif self.operator == "!=":
            return str(actual_value).lower() != str(expected_value).lower()
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
        elif self.operator == "starts with":
            return str(actual_value).lower().startswith(str(expected_value).lower())
        elif self.operator == "ends with":
            return str(actual_value).lower().endswith(str(expected_value).lower())
        elif self.operator == "in":
            values = [v.strip().lower() for v in str(expected_value).split(",")]
            return str(actual_value).lower() in values
        elif self.operator == "not in":
            values = [v.strip().lower() for v in str(expected_value).split(",")]
            return str(actual_value).lower() not in values

        return False

    def get_rule_weight(self):
        """Get the weight of this rule for scoring."""
        return self.weight or 1

    def to_dict(self):
        """Convert rule to dictionary representation."""
        return {
            "field": self.field,
            "operator": self.operator,
            "value": self.value,
            "logic": self.logic,
            "is_active": self.is_active,
            "weight": self.weight,
            "notes": self.notes
        }


def evaluate_rules(rules, context, match_type="all"):
    """
    Evaluate multiple rules against a context.

    Args:
        rules (list): List of VirtualCategoryRule objects.
        context (dict): Product/listing context to evaluate against.
        match_type (str): "all" for AND logic (all rules must match),
                         "any" for OR logic (any rule can match).

    Returns:
        tuple: (matches: bool, score: int, matched_rules: list)
    """
    if not rules:
        return False, 0, []

    matched_rules = []
    total_score = 0
    results = []

    for rule in rules:
        if not rule.is_rule_active():
            continue

        matches = rule.evaluate(context)
        results.append({
            "rule": rule,
            "matches": matches,
            "logic": rule.logic
        })

        if matches:
            matched_rules.append(rule)
            total_score += rule.get_rule_weight()

    if not results:
        return False, 0, []

    # Evaluate combined result based on logic operators
    if match_type == "any":
        final_match = any(r["matches"] for r in results)
    else:
        # Default to "all" - evaluate with AND/OR logic between consecutive rules
        final_match = evaluate_with_logic(results)

    return final_match, total_score, matched_rules


def evaluate_with_logic(results):
    """
    Evaluate results considering the logic operators between conditions.

    Args:
        results (list): List of dicts with "matches" and "logic" keys.

    Returns:
        bool: Final evaluation result.
    """
    if not results:
        return False

    # Start with the first result
    current_result = results[0]["matches"]

    for i in range(len(results) - 1):
        logic = results[i]["logic"]
        next_result = results[i + 1]["matches"]

        if logic == "OR":
            current_result = current_result or next_result
        else:  # AND
            current_result = current_result and next_result

    return current_result


def build_product_context(listing):
    """
    Build a context dictionary from a Listing document for rule evaluation.

    Args:
        listing: Listing document or dict.

    Returns:
        dict: Context with all evaluatable fields.
    """
    if isinstance(listing, dict):
        doc = listing
    else:
        doc = listing.as_dict() if hasattr(listing, "as_dict") else vars(listing)

    context = {
        "category": doc.get("category"),
        "parent_category": doc.get("parent_category"),
        "brand": doc.get("brand"),
        "seller": doc.get("seller"),
        "seller_level": doc.get("seller_level"),
        "price": doc.get("price") or doc.get("selling_price") or 0,
        "discount_percentage": doc.get("discount_percentage") or 0,
        "stock_qty": doc.get("stock_qty") or doc.get("available_qty") or 0,
        "rating": doc.get("rating") or doc.get("average_rating") or 0,
        "review_count": doc.get("review_count") or doc.get("total_reviews") or 0,
        "creation_date": doc.get("creation"),
        "last_modified": doc.get("modified"),
        "item_condition": doc.get("item_condition") or doc.get("condition"),
        "product_type": doc.get("product_type") or doc.get("listing_type"),
        "tags": doc.get("tags") or "",
        "location": doc.get("location") or doc.get("warehouse_location"),
        "country": doc.get("country"),
        "shipping_type": doc.get("shipping_type"),
        "has_variants": doc.get("has_variants") or 0,
        "is_featured": doc.get("is_featured") or 0,
        "is_bestseller": doc.get("is_bestseller") or 0,
        "is_new_arrival": doc.get("is_new_arrival") or 0,
    }

    return context

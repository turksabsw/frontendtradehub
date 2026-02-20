# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

"""
Seller Tag Rule DocType Controller

AND/OR condition rules for automatic seller tag assignment.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime
import json


class SellerTagRule(Document):
    """
    Controller for Seller Tag Rule DocType.

    Rules define conditions for automatic tag assignment using
    AND/OR logic with nested groups.
    """

    def before_insert(self):
        """Set initial values."""
        if not self.created_by:
            self.created_by = frappe.session.user
        if not self.created_at:
            self.created_at = now_datetime()

    def validate(self):
        """Validate rule data."""
        self.validate_rule_json()
        self.validate_target_tag()

    def validate_rule_json(self):
        """Validate the rule JSON structure."""
        if not self.rule_json:
            frappe.throw(_("Rule JSON is required"))

        try:
            rule_config = json.loads(self.rule_json)
        except json.JSONDecodeError as e:
            frappe.throw(_("Invalid JSON format: {0}").format(str(e)))

        # Validate structure
        if not isinstance(rule_config, dict):
            frappe.throw(_("Rule JSON must be an object"))

        # Validate logic field
        logic = rule_config.get("logic", "AND")
        if logic not in ["AND", "OR"]:
            frappe.throw(_("Logic must be 'AND' or 'OR'"))

        # Validate groups
        groups = rule_config.get("groups", [])
        if not isinstance(groups, list):
            frappe.throw(_("'groups' must be an array"))

        for i, group in enumerate(groups):
            self._validate_group(group, i)

    def _validate_group(self, group, index):
        """Validate a single group structure."""
        if not isinstance(group, dict):
            frappe.throw(_("Group {0} must be an object").format(index + 1))

        group_logic = group.get("group_logic", "AND")
        if group_logic not in ["AND", "OR"]:
            frappe.throw(
                _("Group {0}: group_logic must be 'AND' or 'OR'").format(index + 1)
            )

        conditions = group.get("conditions", [])
        if not isinstance(conditions, list):
            frappe.throw(
                _("Group {0}: 'conditions' must be an array").format(index + 1)
            )

        for j, condition in enumerate(conditions):
            self._validate_condition(condition, index, j)

    def _validate_condition(self, condition, group_index, cond_index):
        """Validate a single condition structure."""
        if not isinstance(condition, dict):
            frappe.throw(
                _("Group {0}, Condition {1}: must be an object").format(
                    group_index + 1, cond_index + 1
                )
            )

        required_fields = ["field", "operator"]
        for field in required_fields:
            if field not in condition:
                frappe.throw(
                    _("Group {0}, Condition {1}: '{2}' is required").format(
                        group_index + 1, cond_index + 1, field
                    )
                )

        # Validate operator
        valid_operators = [
            "==", "!=", ">", ">=", "<", "<=",
            "in", "not_in", "contains", "not_contains",
            "is_set", "is_not_set", "starts_with", "ends_with"
        ]
        operator = condition.get("operator")
        if operator not in valid_operators:
            frappe.throw(
                _("Group {0}, Condition {1}: invalid operator '{2}'").format(
                    group_index + 1, cond_index + 1, operator
                )
            )

        # Value is not required for is_set/is_not_set operators
        if operator not in ["is_set", "is_not_set"] and "value" not in condition:
            frappe.throw(
                _("Group {0}, Condition {1}: 'value' is required for operator '{2}'").format(
                    group_index + 1, cond_index + 1, operator
                )
            )

    def validate_target_tag(self):
        """Validate target tag exists and is active."""
        if self.target_tag:
            tag = frappe.get_doc("Seller Tag", self.target_tag)
            if tag.status != "Active":
                frappe.throw(
                    _("Target tag '{0}' is not active").format(self.target_tag)
                )

    @frappe.whitelist()
    def test_rule(self, seller_id=None):
        """
        Test this rule against a seller or sample data.

        Args:
            seller_id: Optional seller to test against

        Returns:
            Dict with test results
        """
        from tradehub_seller.tradehub_seller.seller_tags.rule_engine import evaluate_conditions
        from tradehub_seller.tradehub_seller.seller_tags.seller_metrics import get_seller_metrics

        result = {
            "success": False,
            "matched": False,
            "metrics": {},
            "errors": []
        }

        try:
            rule_config = json.loads(self.rule_json)
        except json.JSONDecodeError as e:
            result["errors"].append(f"Invalid JSON: {str(e)}")
            return result

        if seller_id:
            metrics = get_seller_metrics(seller_id)
            if not metrics:
                result["errors"].append(f"No metrics found for seller: {seller_id}")
                return result
            result["metrics"] = metrics
        else:
            # Use sample metrics for testing
            result["metrics"] = {
                "total_orders": 100,
                "avg_rating": 4.5,
                "verification_status": "Verified",
                "premium_seller": 1
            }
            metrics = result["metrics"]

        result["matched"] = evaluate_conditions(rule_config, metrics)
        result["success"] = True

        return result

    @frappe.whitelist()
    def evaluate_now(self):
        """
        Evaluate this rule for all active sellers immediately.

        Returns:
            Dict with evaluation results
        """
        from tradehub_seller.tradehub_seller.seller_tags.rule_engine import RuleEngine

        engine = RuleEngine()
        sellers = frappe.get_all(
            "Seller Profile",
            filters={"status": ["in", ["Active", "Verified"]]},
            fields=["name"]
        )

        assigned = 0
        removed = 0

        for seller in sellers:
            try:
                qualified = engine.evaluate_all_rules_for_seller(seller.name)
                if self.target_tag in qualified:
                    result = engine.apply_tag_assignment(
                        seller.name, self.target_tag, source="Rule"
                    )
                    if result:
                        assigned += 1
            except Exception as e:
                frappe.log_error(
                    f"Error evaluating rule for seller {seller.name}: {str(e)}",
                    "Rule Evaluation"
                )

        # Update statistics
        self.last_evaluated = now_datetime()
        self.last_evaluation_result = f"Evaluated {len(sellers)} sellers. Assigned: {assigned}"
        self.total_assignments = frappe.db.count(
            "Seller Tag Assignment",
            filters={"tag": self.target_tag, "source": "Rule"}
        )
        self.save(ignore_permissions=True)

        return {
            "total_sellers": len(sellers),
            "assigned": assigned,
            "removed": removed
        }


def get_rule_template():
    """
    Get a sample rule JSON template.

    Returns:
        Dict with sample rule structure
    """
    return {
        "rule_name": "Sample Rule",
        "target_tag": "SAMPLE_TAG",
        "logic": "AND",
        "groups": [
            {
                "group_logic": "AND",
                "conditions": [
                    {"field": "total_orders", "operator": ">=", "value": 100},
                    {"field": "avg_rating", "operator": ">=", "value": 4.5}
                ]
            },
            {
                "group_logic": "OR",
                "conditions": [
                    {"field": "verification_status", "operator": "==", "value": "Verified"},
                    {"field": "premium_seller", "operator": "==", "value": 1}
                ]
            }
        ],
        "evaluation_schedule": "daily"
    }

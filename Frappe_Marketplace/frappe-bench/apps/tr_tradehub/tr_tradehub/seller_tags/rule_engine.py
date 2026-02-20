# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

"""
Rule Engine - AND/OR Condition Evaluator

Recursive rule evaluation engine for seller tag assignment.
Supports nested groups with AND/OR logic.
"""

import frappe
from frappe import _
from typing import Dict, Any, List, Optional, Callable
import json


# Operator mapping for condition evaluation
OPERATORS: Dict[str, Callable[[Any, Any], bool]] = {
    "==": lambda a, b: a == b,
    "!=": lambda a, b: a != b,
    ">": lambda a, b: float(a) > float(b) if a is not None else False,
    ">=": lambda a, b: float(a) >= float(b) if a is not None else False,
    "<": lambda a, b: float(a) < float(b) if a is not None else False,
    "<=": lambda a, b: float(a) <= float(b) if a is not None else False,
    "in": lambda a, b: a in (b if isinstance(b, (list, tuple)) else [b]),
    "not_in": lambda a, b: a not in (b if isinstance(b, (list, tuple)) else [b]),
    "contains": lambda a, b: str(b).lower() in str(a).lower() if a else False,
    "not_contains": lambda a, b: str(b).lower() not in str(a).lower() if a else True,
    "is_set": lambda a, b: a is not None and a != "",
    "is_not_set": lambda a, b: a is None or a == "",
    "starts_with": lambda a, b: str(a).lower().startswith(str(b).lower()) if a else False,
    "ends_with": lambda a, b: str(a).lower().endswith(str(b).lower()) if a else False,
}


def evaluate_condition(condition: Dict[str, Any], metrics: Dict[str, Any]) -> bool:
    """
    Evaluate a single condition against seller metrics.

    Args:
        condition: Dict with field, operator, value keys
        metrics: Dict of seller metric values

    Returns:
        bool: True if condition is satisfied
    """
    field = condition.get("field")
    operator = condition.get("operator")
    target_value = condition.get("value")

    if not field or not operator:
        frappe.log_error(
            f"Invalid condition: missing field or operator. Condition: {condition}",
            "Rule Engine"
        )
        return False

    if operator not in OPERATORS:
        frappe.log_error(
            f"Unknown operator: {operator}",
            "Rule Engine"
        )
        return False

    field_value = metrics.get(field)

    try:
        result = OPERATORS[operator](field_value, target_value)
        return result
    except Exception as e:
        frappe.log_error(
            f"Error evaluating condition: {condition}, metrics: {metrics}, error: {str(e)}",
            "Rule Engine"
        )
        return False


def evaluate_group(group: Dict[str, Any], metrics: Dict[str, Any]) -> bool:
    """
    Evaluate a group of conditions with AND/OR logic.

    Args:
        group: Dict with group_logic and conditions keys
        metrics: Dict of seller metric values

    Returns:
        bool: True if group conditions are satisfied
    """
    group_logic = group.get("group_logic", "AND").upper()
    conditions = group.get("conditions", [])

    if not conditions:
        return True  # Empty group always passes

    condition_results = [
        evaluate_condition(condition, metrics)
        for condition in conditions
    ]

    if group_logic == "AND":
        return all(condition_results)
    else:  # OR
        return any(condition_results)


def evaluate_conditions(rule: Dict[str, Any], metrics: Dict[str, Any]) -> bool:
    """
    Evaluate rule conditions recursively with AND/OR logic.

    Args:
        rule: Dict with logic and groups keys
        metrics: Dict of seller metric values

    Returns:
        bool: True if all rule conditions are satisfied
    """
    logic = rule.get("logic", "AND").upper()
    groups = rule.get("groups", [])

    if not groups:
        return True  # No groups means rule always passes

    group_results = [
        evaluate_group(group, metrics)
        for group in groups
    ]

    if logic == "AND":
        return all(group_results)
    else:  # OR
        return any(group_results)


class RuleEngine:
    """
    Rule Engine for evaluating seller tag rules.

    Supports:
    - AND/OR logic at rule level
    - AND/OR logic at group level
    - Multiple operators (==, !=, >, >=, <, <=, in, not_in, contains, etc.)
    - Manual override priority (Manual > Rule)
    """

    def __init__(self):
        self.evaluation_cache: Dict[str, bool] = {}

    def clear_cache(self):
        """Clear the evaluation cache."""
        self.evaluation_cache = {}

    def evaluate_rule(self, rule_doc, metrics: Dict[str, Any]) -> bool:
        """
        Evaluate a Seller Tag Rule document against metrics.

        Args:
            rule_doc: Seller Tag Rule document or rule name
            metrics: Dict of seller metric values

        Returns:
            bool: True if rule conditions are satisfied
        """
        if isinstance(rule_doc, str):
            rule_doc = frappe.get_doc("Seller Tag Rule", rule_doc)

        if not rule_doc.enabled:
            return False

        # Parse rule JSON
        try:
            rule_config = json.loads(rule_doc.rule_json) if rule_doc.rule_json else {}
        except json.JSONDecodeError:
            frappe.log_error(
                f"Invalid JSON in rule: {rule_doc.name}",
                "Rule Engine"
            )
            return False

        return evaluate_conditions(rule_config, metrics)

    def evaluate_all_rules_for_seller(self, seller_id: str) -> List[str]:
        """
        Evaluate all enabled rules for a seller.

        Args:
            seller_id: Seller Profile name

        Returns:
            List of tag names that should be assigned
        """
        from tr_tradehub.seller_tags.seller_metrics import get_seller_metrics

        # Get current metrics
        metrics = get_seller_metrics(seller_id)
        if not metrics:
            return []

        # Get all enabled rules
        rules = frappe.get_all(
            "Seller Tag Rule",
            filters={"enabled": 1},
            fields=["name", "target_tag", "rule_json"]
        )

        tags_to_assign = []
        for rule in rules:
            try:
                rule_config = json.loads(rule.rule_json) if rule.rule_json else {}
                if evaluate_conditions(rule_config, metrics):
                    tags_to_assign.append(rule.target_tag)
            except Exception as e:
                frappe.log_error(
                    f"Error evaluating rule {rule.name}: {str(e)}",
                    "Rule Engine"
                )

        return tags_to_assign

    def apply_tag_assignment(
        self,
        seller: str,
        tag: str,
        source: str = "Rule"
    ) -> Optional[str]:
        """
        Apply a tag assignment respecting override priority.

        Priority: Manual > Rule

        Args:
            seller: Seller Profile name
            tag: Seller Tag name
            source: "Manual" or "Rule"

        Returns:
            Assignment name if created/updated, None if skipped
        """
        existing = frappe.get_all(
            "Seller Tag Assignment",
            filters={"seller": seller, "tag": tag},
            fields=["name", "source", "override_state"]
        )

        if existing:
            doc = frappe.get_doc("Seller Tag Assignment", existing[0].name)

            # Skip if manually forced off
            if doc.override_state == "ForcedOff":
                return None

            # Manual takes priority over Rule
            if source == "Rule" and doc.source == "Manual":
                return None

            # Update existing assignment
            if source == "Rule":
                doc.last_evaluated = frappe.utils.now_datetime()
                doc.save(ignore_permissions=True)
                return doc.name
        else:
            # Create new assignment
            doc = frappe.get_doc({
                "doctype": "Seller Tag Assignment",
                "seller": seller,
                "tag": tag,
                "source": source,
                "assigned_at": frappe.utils.now_datetime(),
                "last_evaluated": frappe.utils.now_datetime() if source == "Rule" else None
            })
            doc.insert(ignore_permissions=True)
            return doc.name

        return None

    def remove_unqualified_tags(
        self,
        seller: str,
        qualified_tags: List[str]
    ):
        """
        Remove rule-based tags that seller no longer qualifies for.

        Args:
            seller: Seller Profile name
            qualified_tags: List of tag names seller currently qualifies for
        """
        # Get all rule-based assignments for this seller
        assignments = frappe.get_all(
            "Seller Tag Assignment",
            filters={
                "seller": seller,
                "source": "Rule",
                "override_state": ["!=", "ForcedOn"]
            },
            fields=["name", "tag"]
        )

        for assignment in assignments:
            if assignment.tag not in qualified_tags:
                frappe.delete_doc(
                    "Seller Tag Assignment",
                    assignment.name,
                    ignore_permissions=True
                )

# Copyright (c) 2026, TradeHub and contributors
# For license information, please see license.txt

"""
ECA Condition Evaluation Engine

This module implements the condition evaluation engine for ECA rules,
supporting 22 operators, AND/OR grouping, field path resolution,
and Jinja template values.

Pattern Reference: tr_tradehub/seller_tags/rule_engine.py
"""

import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Union

import frappe
from frappe import _
from frappe.utils import cstr, getdate, get_datetime

# Import safety mechanisms
from tr_tradehub.eca.rate_limiter import (
    check_rate_limit,
    RateLimitResult,
    get_rate_limiter,
)
from tr_tradehub.eca.chain_tracker import (
    chain_context,
    get_chain_tracker,
    ChainTrackingResult,
)


# =============================================================================
# OPERATORS DICTIONARY - 22 Operators (14 from Seller Tag Rule + 8 new)
# =============================================================================

OPERATORS: Dict[str, Callable[[Any, Any], bool]] = {
    # Standard comparison operators (from Seller Tag Rule)
    "==": lambda a, b: a == b,
    "!=": lambda a, b: a != b,
    ">": lambda a, b: float(a) > float(b) if a is not None else False,
    ">=": lambda a, b: float(a) >= float(b) if a is not None else False,
    "<": lambda a, b: float(a) < float(b) if a is not None else False,
    "<=": lambda a, b: float(a) <= float(b) if a is not None else False,

    # List membership operators (from Seller Tag Rule)
    "in": lambda a, b: a in (b if isinstance(b, (list, tuple)) else [b]),
    "not_in": lambda a, b: a not in (b if isinstance(b, (list, tuple)) else [b]),

    # String operators (from Seller Tag Rule - case-insensitive)
    "contains": lambda a, b: cstr(b).lower() in cstr(a).lower() if a else False,
    "not_contains": lambda a, b: cstr(b).lower() not in cstr(a).lower() if a else True,
    "starts_with": lambda a, b: cstr(a).lower().startswith(cstr(b).lower()) if a else False,
    "ends_with": lambda a, b: cstr(a).lower().endswith(cstr(b).lower()) if a else False,

    # Null/empty operators (from Seller Tag Rule)
    "is_set": lambda a, b: a is not None and a != "",
    "is_not_set": lambda a, b: a is None or a == "",

    # New operators for ECA
    "regex_match": lambda a, b: bool(re.match(cstr(b), cstr(a))) if a is not None else False,
    "date_before": lambda a, b: getdate(a) < getdate(b) if a and b else False,
    "date_after": lambda a, b: getdate(a) > getdate(b) if a and b else False,
    "between": lambda a, b: _check_between(a, b),
    "is_empty": lambda a, b: a is None or a == "" or a == [] or a == {},

    # Change detection operators (require old_doc context)
    # These are special - they need access to both doc and old_doc
    # The actual implementation is in ECAEngine._evaluate_change_operator
    "changed": lambda a, b: False,  # Placeholder - handled specially
    "changed_to": lambda a, b: False,  # Placeholder - handled specially
    "changed_from": lambda a, b: False,  # Placeholder - handled specially
}


# =============================================================================
# EXECUTION RESULT
# =============================================================================

@dataclass
class ExecutionResult:
    """
    Result of a rule execution attempt.

    Attributes:
        executed: Whether the rule was executed
        condition_result: Result of condition evaluation
        rate_limited: Whether execution was blocked by rate limiting
        chain_blocked: Whether execution was blocked by chain tracking
        chain_id: The chain ID for this execution
        chain_depth: The chain depth at execution time
        rate_limit_info: Rate limit result details
        chain_info: Chain tracking result details
        error: Error message if execution failed
    """
    executed: bool = False
    condition_result: bool = False
    rate_limited: bool = False
    chain_blocked: bool = False
    chain_id: Optional[str] = None
    chain_depth: int = 0
    rate_limit_info: Optional[Dict[str, Any]] = None
    chain_info: Optional[Dict[str, Any]] = None
    error: Optional[str] = None

    def to_dict(self) -> dict:
        """Convert to dictionary for logging/serialization."""
        return {
            "executed": self.executed,
            "condition_result": self.condition_result,
            "rate_limited": self.rate_limited,
            "chain_blocked": self.chain_blocked,
            "chain_id": self.chain_id,
            "chain_depth": self.chain_depth,
            "rate_limit_info": self.rate_limit_info,
            "chain_info": self.chain_info,
            "error": self.error,
        }


def _check_between(value: Any, range_value: Any) -> bool:
    """
    Check if value is between min and max.

    Args:
        value: The value to check
        range_value: Either a list [min, max] or a dict {"min": x, "max": y}

    Returns:
        True if min <= value <= max, False otherwise
    """
    if value is None:
        return False

    try:
        if isinstance(range_value, dict):
            min_val = range_value.get("min")
            max_val = range_value.get("max")
        elif isinstance(range_value, (list, tuple)) and len(range_value) == 2:
            min_val, max_val = range_value
        else:
            return False

        # Try numeric comparison
        num_value = float(value)
        return float(min_val) <= num_value <= float(max_val)
    except (ValueError, TypeError):
        return False


# =============================================================================
# ECA ENGINE CLASS
# =============================================================================

class ECAEngine:
    """
    ECA Condition Evaluation Engine.

    Evaluates complex conditions with 22 operators, AND/OR grouping,
    field path resolution, and Jinja template support.

    Usage:
        engine = ECAEngine(doc, old_doc=old_doc)
        result = engine.evaluate_rule(rule)

    Attributes:
        doc: The current document being evaluated
        old_doc: The previous version of the document (for change detection)
        context: Template context for Jinja rendering
    """

    def __init__(
        self,
        doc: "frappe.model.document.Document",
        old_doc: Optional["frappe.model.document.Document"] = None,
        context: Optional[Dict[str, Any]] = None
    ):
        """
        Initialize the ECA Engine.

        Args:
            doc: The current document being evaluated
            old_doc: The previous document state (for change detection)
            context: Additional context for Jinja templates
        """
        self.doc = doc
        self.old_doc = old_doc
        self.context = context or {}
        self._build_context()

    def _build_context(self) -> None:
        """Build the template context with standard variables."""
        self.context.update({
            "doc": self.doc,
            "old_doc": self.old_doc,
            "frappe": frappe,
            "now": frappe.utils.now_datetime,
            "today": frappe.utils.today,
            "user": frappe.session.user if frappe.session else None,
        })

    def evaluate_rule(self, rule: "frappe.model.document.Document") -> bool:
        """
        Evaluate an ECA Rule against the current document.

        Args:
            rule: The ECA Rule document

        Returns:
            True if all conditions are met, False otherwise
        """
        if not rule.conditions:
            # Empty conditions = always pass
            return True

        # Group conditions by condition_group
        groups = self._group_conditions(rule.conditions)

        # Get the top-level logic
        logic = (rule.condition_logic or "AND").upper()

        # Evaluate all groups
        group_results = []
        for group_id, group_data in groups.items():
            result = self.evaluate_group(group_data["conditions"], group_data["logic"])
            group_results.append(result)

        # Apply top-level logic
        if logic == "AND":
            return all(group_results) if group_results else True
        else:  # OR
            return any(group_results) if group_results else True

    def _group_conditions(
        self, conditions: List
    ) -> Dict[int, Dict[str, Any]]:
        """
        Group conditions by their condition_group field.

        Args:
            conditions: List of ECA Rule Condition rows

        Returns:
            Dictionary mapping group_id to group data
        """
        groups: Dict[int, Dict[str, Any]] = {}

        for condition in conditions:
            group_id = condition.condition_group or 1

            if group_id not in groups:
                groups[group_id] = {
                    "logic": (condition.group_logic or "AND").upper(),
                    "conditions": []
                }

            groups[group_id]["conditions"].append(condition)

        return groups

    def evaluate_group(
        self, conditions: List, logic: str = "AND"
    ) -> bool:
        """
        Evaluate a group of conditions.

        Args:
            conditions: List of conditions to evaluate
            logic: "AND" or "OR" logic for combining results

        Returns:
            True if group conditions are met, False otherwise
        """
        if not conditions:
            # Empty group = pass
            return True

        results = []
        for condition in conditions:
            result = self.evaluate_condition(condition)
            results.append(result)

        if logic == "AND":
            return all(results)
        else:  # OR
            return any(results)

    def evaluate_condition(self, condition) -> bool:
        """
        Evaluate a single condition.

        Args:
            condition: An ECA Rule Condition row

        Returns:
            True if condition is met, False otherwise
        """
        try:
            field_path = condition.field_path
            operator = condition.operator
            compare_value = condition.value
            value_type = condition.value_type

            # Get the field value from the document
            actual_value = self.get_field_value(field_path)

            # Handle change detection operators specially
            if operator in ("changed", "changed_to", "changed_from"):
                return self._evaluate_change_operator(
                    field_path, operator, compare_value
                )

            # Parse the comparison value based on type
            parsed_value = self._parse_value(compare_value, value_type)

            # Get the operator function
            op_func = OPERATORS.get(operator)
            if not op_func:
                frappe.log_error(
                    f"Unknown operator: {operator}",
                    "ECA Engine Error"
                )
                return False

            # Execute the comparison
            return op_func(actual_value, parsed_value)

        except Exception as e:
            frappe.log_error(
                f"Error evaluating condition: {str(e)}\n"
                f"Field: {condition.field_path}, Operator: {condition.operator}",
                "ECA Engine Error"
            )
            return False

    def get_field_value(self, field_path: str) -> Any:
        """
        Get the value of a field from the document using dot/bracket notation.

        Supports:
        - Simple fields: "status"
        - Nested fields: "buyer.email"
        - Array access: "items[0].quantity"
        - Linked document fields: "customer.customer_name"

        Args:
            field_path: The field path to resolve

        Returns:
            The resolved field value, or None if not found
        """
        if not field_path:
            return None

        try:
            return self._resolve_field_path(self.doc, field_path)
        except Exception:
            return None

    def _resolve_field_path(self, obj: Any, path: str) -> Any:
        """
        Resolve a field path to get the actual value.

        Args:
            obj: The object to resolve from
            path: The field path (e.g., "buyer.email", "items[0].qty")

        Returns:
            The resolved value
        """
        if not path or obj is None:
            return None

        # Split path by dots, handling array notation
        parts = self._parse_path(path)
        current = obj

        for part in parts:
            if current is None:
                return None

            # Check for array index notation
            array_match = re.match(r"(\w+)\[(\d+)\]", part)

            if array_match:
                # Array access: field[index]
                field_name = array_match.group(1)
                index = int(array_match.group(2))

                # Get the array field
                current = self._get_attribute(current, field_name)

                if current is None or not isinstance(current, (list, tuple)):
                    return None

                if index >= len(current):
                    return None

                current = current[index]
            else:
                # Simple field access
                current = self._get_attribute(current, part)

                # If it's a Link field, try to fetch the linked document
                if isinstance(current, str) and self._is_link_field(obj, part):
                    linked_doctype = self._get_link_doctype(obj, part)
                    if linked_doctype:
                        try:
                            current = frappe.get_doc(linked_doctype, current)
                        except frappe.DoesNotExistError:
                            return None

        return current

    def _parse_path(self, path: str) -> List[str]:
        """
        Parse a field path into parts.

        Args:
            path: Field path like "buyer.email" or "items[0].qty"

        Returns:
            List of path parts
        """
        # Handle dot notation and array notation
        parts = []
        current = ""

        for char in path:
            if char == ".":
                if current:
                    parts.append(current)
                    current = ""
            else:
                current += char

        if current:
            parts.append(current)

        return parts

    def _get_attribute(self, obj: Any, attr: str) -> Any:
        """
        Get an attribute from an object (dict or object).

        Args:
            obj: The object to get attribute from
            attr: The attribute name

        Returns:
            The attribute value
        """
        if isinstance(obj, dict):
            return obj.get(attr)
        elif hasattr(obj, attr):
            return getattr(obj, attr)
        elif hasattr(obj, "get"):
            return obj.get(attr)
        return None

    def _is_link_field(self, obj: Any, field_name: str) -> bool:
        """
        Check if a field is a Link field.

        Args:
            obj: The document object
            field_name: The field name to check

        Returns:
            True if it's a Link field
        """
        if not hasattr(obj, "meta"):
            return False

        try:
            field = obj.meta.get_field(field_name)
            return field and field.fieldtype == "Link"
        except Exception:
            return False

    def _get_link_doctype(self, obj: Any, field_name: str) -> Optional[str]:
        """
        Get the DocType that a Link field points to.

        Args:
            obj: The document object
            field_name: The field name

        Returns:
            The linked DocType name, or None
        """
        if not hasattr(obj, "meta"):
            return None

        try:
            field = obj.meta.get_field(field_name)
            return field.options if field else None
        except Exception:
            return None

    def _parse_value(
        self, value: Any, value_type: Optional[str] = None
    ) -> Any:
        """
        Parse a condition value based on its type.

        Args:
            value: The raw value string
            value_type: The value type (String, Number, Boolean, etc.)

        Returns:
            The parsed value
        """
        if value is None:
            return None

        # Check if it's a Jinja expression
        if value_type == "Jinja Expression" or (
            isinstance(value, str) and "{{" in value
        ):
            return self._render_template(value)

        # Parse based on value type
        if value_type == "Number":
            try:
                return float(value)
            except (ValueError, TypeError):
                return value

        elif value_type == "Boolean":
            if isinstance(value, bool):
                return value
            if isinstance(value, str):
                return value.lower() in ("true", "1", "yes")
            return bool(value)

        elif value_type == "Date":
            return getdate(value)

        elif value_type == "Datetime":
            return get_datetime(value)

        elif value_type == "JSON":
            if isinstance(value, str):
                try:
                    import json
                    return json.loads(value)
                except (ValueError, TypeError):
                    return value
            return value

        # Default: return as string
        return cstr(value) if value else value

    def _render_template(self, template: str) -> Any:
        """
        Render a Jinja template string with the current context.

        Args:
            template: The Jinja template string

        Returns:
            The rendered value
        """
        if not template or not isinstance(template, str):
            return template

        if "{{" not in template:
            return template

        try:
            return frappe.render_template(template, self.context)
        except Exception as e:
            frappe.log_error(
                f"Error rendering template: {template}\nError: {str(e)}",
                "ECA Template Error"
            )
            return template

    def _evaluate_change_operator(
        self, field_path: str, operator: str, compare_value: Any
    ) -> bool:
        """
        Evaluate change detection operators.

        Args:
            field_path: The field to check for changes
            operator: One of "changed", "changed_to", "changed_from"
            compare_value: The value to compare against (for changed_to/changed_from)

        Returns:
            True if the change condition is met
        """
        if not self.old_doc:
            # No old document = first insert, treat as "changed"
            if operator == "changed":
                return True
            return False

        current_value = self.get_field_value(field_path)
        old_value = self._resolve_field_path(self.old_doc, field_path)

        if operator == "changed":
            return current_value != old_value

        elif operator == "changed_to":
            # Value changed FROM something else TO the specified value
            return old_value != compare_value and current_value == compare_value

        elif operator == "changed_from":
            # Value changed FROM the specified value TO something else
            return old_value == compare_value and current_value != compare_value

        return False

    def execute_rule_with_safety(
        self,
        rule: "frappe.model.document.Document",
        execute_actions_callback: Optional[Callable] = None
    ) -> ExecutionResult:
        """
        Execute a rule with rate limiting and chain tracking safety mechanisms.

        This is the main entry point for rule execution that:
        1. Checks rate limits before execution
        2. Uses chain tracking to prevent circular triggers
        3. Evaluates conditions if safety checks pass
        4. Optionally executes actions via callback

        Args:
            rule: The ECA Rule document
            execute_actions_callback: Optional callback to execute actions if conditions pass.
                                     Signature: callback(rule, doc, old_doc, chain_id, chain_depth)

        Returns:
            ExecutionResult with execution details
        """
        result = ExecutionResult()

        try:
            # Step 1: Check rate limiting
            rate_limit_result = check_rate_limit(rule, self.doc)
            result.rate_limit_info = rate_limit_result.to_dict()

            if not rate_limit_result.allowed:
                result.rate_limited = True
                result.error = rate_limit_result.reason
                return result

            # Step 2: Use chain tracking for circular prevention
            with chain_context(rule) as ctx:
                result.chain_id = ctx.chain_id
                result.chain_depth = ctx.chain_depth
                result.chain_info = {
                    "allowed": ctx.allowed,
                    "chain_id": ctx.chain_id,
                    "chain_depth": ctx.chain_depth,
                    "max_depth": ctx.max_depth,
                    "reason": ctx.reason,
                    "triggered_rules": ctx.triggered_rules,
                }

                if not ctx.allowed:
                    result.chain_blocked = True
                    result.error = ctx.reason
                    return result

                # Step 3: Evaluate conditions
                result.condition_result = self.evaluate_rule(rule)

                if result.condition_result and execute_actions_callback:
                    # Step 4: Execute actions via callback
                    execute_actions_callback(
                        rule,
                        self.doc,
                        self.old_doc,
                        ctx.chain_id,
                        ctx.chain_depth
                    )

                result.executed = True

        except Exception as e:
            result.error = str(e)
            frappe.log_error(
                f"Error executing rule with safety: {str(e)}",
                "ECA Engine Error"
            )

        return result


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def get_engine(
    doc: "frappe.model.document.Document",
    old_doc: Optional["frappe.model.document.Document"] = None
) -> ECAEngine:
    """
    Factory function to create an ECA Engine instance.

    Args:
        doc: The current document
        old_doc: The previous document state

    Returns:
        An ECAEngine instance
    """
    return ECAEngine(doc, old_doc)


def evaluate_conditions(
    doc: "frappe.model.document.Document",
    conditions: List,
    logic: str = "AND",
    old_doc: Optional["frappe.model.document.Document"] = None
) -> bool:
    """
    Convenience function to evaluate conditions without creating a rule.

    Args:
        doc: The document to evaluate
        conditions: List of condition dictionaries
        logic: Top-level logic ("AND" or "OR")
        old_doc: Previous document state

    Returns:
        True if conditions are met
    """
    engine = ECAEngine(doc, old_doc)
    return engine.evaluate_group(conditions, logic)

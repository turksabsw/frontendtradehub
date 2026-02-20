# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import getdate, nowdate, now_datetime


class ContractRule(Document):
    """Contract Rule for automated contract presentation based on trigger conditions."""

    def validate(self):
        """Validate rule data."""
        self.validate_dates()
        self.validate_priority()
        self.validate_auto_expire()
        self.validate_blocking_action()

    def validate_dates(self):
        """Validate valid_from and valid_until dates."""
        if self.valid_from and self.valid_until:
            if getdate(self.valid_until) < getdate(self.valid_from):
                frappe.throw(_("Valid Until date cannot be before Valid From date"))

    def validate_priority(self):
        """Ensure priority is within valid range."""
        if self.priority is not None:
            if self.priority < 1 or self.priority > 100:
                frappe.throw(_("Priority must be between 1 and 100"))

    def validate_auto_expire(self):
        """Validate auto_expire settings."""
        if self.auto_expire and not self.expire_after_days:
            frappe.throw(_("Please specify 'Expire After (Days)' when Auto Expire is enabled"))

        if self.auto_expire and self.expire_after_days and self.expire_after_days < 1:
            frappe.throw(_("Expire After (Days) must be at least 1"))

    def validate_blocking_action(self):
        """Validate blocking action settings."""
        if self.blocking_action and not self.contract_template:
            frappe.throw(_("Contract Template is required when Blocking Action is enabled"))

    def is_active(self):
        """Check if this rule is currently active."""
        if self.status != "Active":
            return False

        today = getdate(nowdate())

        if self.valid_from and getdate(self.valid_from) > today:
            return False

        if self.valid_until and getdate(self.valid_until) < today:
            return False

        return True

    def evaluate_context(self, context):
        """
        Evaluate if a context matches this rule's conditions.

        Args:
            context: Dictionary with context data (user_type, order_total, etc.)

        Returns:
            bool: True if context matches all conditions, False otherwise
        """
        if not self.is_active():
            return False

        # Check target filters first
        if not self.matches_target_filters(context):
            return False

        # If no conditions, rule matches all contexts
        if not self.conditions:
            return True

        # Evaluate conditions
        return self.evaluate_conditions(context)

    def matches_target_filters(self, context):
        """Check if context matches target filters."""
        if self.apply_to == "All Users":
            return True

        user_type = context.get("user_type")

        if self.apply_to == "Sellers Only":
            if user_type != "Seller":
                return False

        if self.apply_to == "Buyers Only":
            if user_type != "Buyer":
                return False

        if self.apply_to == "Specific User Type":
            entity_type = context.get("entity_type")  # Individual, Business, Enterprise
            if self.target_user_type and entity_type != self.target_user_type:
                return False

        if self.apply_to == "Specific Level":
            if user_type == "Seller":
                seller_level = context.get("seller_level")
                if self.target_seller_level and seller_level != self.target_seller_level:
                    return False
            elif user_type == "Buyer":
                buyer_level = context.get("buyer_level")
                if self.target_buyer_level and buyer_level != self.target_buyer_level:
                    return False

        return True

    def evaluate_conditions(self, context):
        """
        Evaluate all conditions against the context.

        Args:
            context (dict): Evaluation context with field values

        Returns:
            bool: True if conditions are met based on match_type
        """
        if not self.conditions:
            return True

        results = []
        for condition in self.conditions:
            result = condition.evaluate(context)
            results.append(result)

        if self.match_type == "All":
            return all(results)
        else:  # Any
            return any(results)

    def trigger(self, user, context=None):
        """
        Trigger this rule for a user.

        Args:
            user (str): User ID or email
            context (dict): Additional context for evaluation

        Returns:
            dict: Trigger result with contract details
        """
        if not self.is_active():
            return {"triggered": False, "reason": "Rule is not active"}

        # Update statistics
        self.last_triggered_at = now_datetime()
        self.trigger_count = (self.trigger_count or 0) + 1
        self.db_update()

        # Send notification if enabled
        if self.send_notification and self.notification_template:
            self._send_notification(user)

        return {
            "triggered": True,
            "contract_template": self.contract_template,
            "rule_name": self.rule_name,
            "blocking": self.blocking_action,
            "expire_after_days": self.expire_after_days if self.auto_expire else None
        }

    def _send_notification(self, user):
        """
        Send notification to user about contract requirement.

        Args:
            user (str): User ID or email
        """
        try:
            if self.notification_template:
                frappe.sendmail(
                    recipients=[user],
                    template=self.notification_template,
                    args={
                        "rule_name": self.rule_name,
                        "contract_template": self.contract_template,
                        "user": user
                    }
                )
        except Exception as e:
            frappe.log_error(
                message=str(e),
                title=_("Contract Rule Notification Error")
            )

    def record_acceptance(self):
        """Record a contract acceptance for this rule."""
        self.acceptance_count = (self.acceptance_count or 0) + 1
        self.db_update()

    def record_rejection(self):
        """Record a contract rejection for this rule."""
        self.rejection_count = (self.rejection_count or 0) + 1
        self.db_update()


@frappe.whitelist()
def get_applicable_rules(trigger_point, user=None, context=None):
    """
    Get all applicable contract rules for a trigger point.

    Args:
        trigger_point (str): The trigger point to check
        user (str): User to evaluate rules for
        context (dict): Additional context for evaluation

    Returns:
        list: List of applicable rule names with contract templates
    """
    if isinstance(context, str):
        import json
        context = json.loads(context)

    context = context or {}

    rules = frappe.get_all(
        "Contract Rule",
        filters={
            "status": "Active",
            "trigger_point": trigger_point
        },
        order_by="priority desc"
    )

    applicable = []
    for rule_data in rules:
        rule = frappe.get_doc("Contract Rule", rule_data.name)
        if rule.is_active() and rule.evaluate_context(context):
            applicable.append({
                "rule": rule.name,
                "rule_name": rule.rule_name,
                "contract_template": rule.contract_template,
                "blocking": rule.blocking_action,
                "priority": rule.priority
            })

    return applicable


@frappe.whitelist()
def trigger_rule(rule_name, user=None, context=None):
    """
    Trigger a specific contract rule.

    Args:
        rule_name (str): Name of the Contract Rule
        user (str): User to trigger for
        context (dict): Additional context

    Returns:
        dict: Trigger results
    """
    if isinstance(context, str):
        import json
        context = json.loads(context)

    user = user or frappe.session.user
    rule = frappe.get_doc("Contract Rule", rule_name)
    return rule.trigger(user, context)


@frappe.whitelist()
def check_blocking_contracts(trigger_point, user=None, context=None):
    """
    Check if there are any blocking contracts for a trigger point.

    Args:
        trigger_point (str): The trigger point to check
        user (str): User to check for
        context (dict): Additional context

    Returns:
        dict: Blocking status and contract details
    """
    if isinstance(context, str):
        import json
        context = json.loads(context)

    applicable = get_applicable_rules(trigger_point, user, context)

    blocking_contracts = [r for r in applicable if r.get("blocking")]

    if blocking_contracts:
        return {
            "blocked": True,
            "contracts": blocking_contracts,
            "message": _("You must accept the following contracts to proceed")
        }

    return {
        "blocked": False,
        "contracts": [],
        "message": None
    }


@frappe.whitelist()
def record_contract_response(rule_name, accepted=True):
    """
    Record a user's response to a contract rule.

    Args:
        rule_name (str): Name of the Contract Rule
        accepted (bool): Whether the contract was accepted

    Returns:
        dict: Response confirmation
    """
    rule = frappe.get_doc("Contract Rule", rule_name)

    if accepted:
        rule.record_acceptance()
        return {"status": "accepted", "message": _("Contract accepted successfully")}
    else:
        rule.record_rejection()
        return {"status": "rejected", "message": _("Contract rejected")}


@frappe.whitelist()
def test_rule_conditions(rule_name, context=None):
    """
    Test a rule against a given context without triggering it.

    Args:
        rule_name (str): Name of the Contract Rule
        context (dict): Context to test against

    Returns:
        dict: Test results including condition evaluation details
    """
    if isinstance(context, str):
        import json
        context = json.loads(context)

    context = context or {}

    rule = frappe.get_doc("Contract Rule", rule_name)

    condition_results = []
    for condition in rule.conditions:
        result = condition.evaluate(context)
        condition_results.append({
            "field": condition.field,
            "operator": condition.operator,
            "expected": condition.value,
            "actual": context.get(condition.field),
            "matched": result
        })

    overall_match = rule.evaluate_context(context)

    return {
        "rule": rule_name,
        "is_active": rule.is_active(),
        "matches": overall_match,
        "match_type": rule.match_type,
        "target_matches": rule.matches_target_filters(context),
        "condition_results": condition_results,
        "context": context
    }

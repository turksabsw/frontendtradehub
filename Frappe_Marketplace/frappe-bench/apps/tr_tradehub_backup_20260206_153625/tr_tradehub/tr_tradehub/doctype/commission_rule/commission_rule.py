# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import (
    cint, flt, getdate, nowdate, now_datetime, get_datetime,
    add_days, time_diff_in_hours
)
import json
from datetime import datetime, time as dt_time


class CommissionRule(Document):
    """
    Commission Rule DocType for TR-TradeHub.

    Defines specific commission rules that can be applied based on various
    criteria including:
    - Category-based commission
    - Seller tier-based commission
    - Volume-based commission
    - Promotional/seasonal commission
    - Time-based commission
    - Custom expression-based commission

    Rules are evaluated by priority and the first matching rule applies
    unless stacking is allowed.
    """

    def before_insert(self):
        """Set default values before creating a new rule."""
        if not self.created_by:
            self.created_by = frappe.session.user
        self.created_at = now_datetime()

        # Generate rule code if not provided
        if not self.rule_code:
            self.rule_code = self.generate_rule_code()

        # Set default effective_from to now if not specified
        if not self.effective_from:
            self.effective_from = now_datetime()

        # Initialize JSON fields
        if not self.day_of_week_restrictions:
            self.day_of_week_restrictions = "[]"
        if not self.restricted_sellers:
            self.restricted_sellers = "[]"
        if not self.excluded_sellers:
            self.excluded_sellers = "[]"
        if not self.restricted_categories:
            self.restricted_categories = "[]"
        if not self.excluded_categories:
            self.excluded_categories = "[]"
        if not self.override_by:
            self.override_by = "[]"

    def validate(self):
        """Validate commission rule data before saving."""
        self.validate_priority()
        self.validate_commission_settings()
        self.validate_dates()
        self.validate_conditions()
        self.validate_restrictions()
        self.validate_time_settings()
        self.validate_default_rule()
        self.modified_by_user = frappe.session.user
        self.modified_at_date = now_datetime()

    def on_update(self):
        """Actions after rule is updated."""
        self.clear_cache()

    def on_trash(self):
        """Check before deletion."""
        self.check_usage_before_delete()

    # =================================================================
    # Validation Methods
    # =================================================================

    def validate_priority(self):
        """Validate priority is within range."""
        if cint(self.priority) < 1 or cint(self.priority) > 1000:
            frappe.throw(_("Priority must be between 1 and 1000"))

    def validate_commission_settings(self):
        """Validate commission rate and amount settings."""
        if self.commission_type == "Percentage":
            if flt(self.commission_rate) < 0 or flt(self.commission_rate) > 100:
                frappe.throw(_("Commission rate must be between 0 and 100"))

        if self.commission_type == "Fixed Amount":
            if flt(self.fixed_commission) < 0:
                frappe.throw(_("Fixed commission cannot be negative"))

        if self.commission_type == "Percentage + Fixed":
            if flt(self.commission_rate) < 0 or flt(self.commission_rate) > 100:
                frappe.throw(_("Commission rate must be between 0 and 100"))
            if flt(self.fixed_commission) < 0:
                frappe.throw(_("Fixed commission cannot be negative"))

        # Validate min/max commission
        if flt(self.minimum_commission) < 0:
            frappe.throw(_("Minimum commission cannot be negative"))

        if flt(self.maximum_commission) < 0:
            frappe.throw(_("Maximum commission cannot be negative"))

        if flt(self.maximum_commission) > 0 and flt(self.minimum_commission) > flt(self.maximum_commission):
            frappe.throw(_("Minimum commission cannot be greater than maximum commission"))

    def validate_dates(self):
        """Validate effective dates."""
        if self.effective_from and self.effective_until:
            if get_datetime(self.effective_from) > get_datetime(self.effective_until):
                frappe.throw(_("Effective From cannot be after Effective Until"))

        # Clear effective_until if perpetual
        if cint(self.is_perpetual):
            self.effective_until = None

    def validate_conditions(self):
        """Validate rule conditions."""
        # Validate order value range
        if flt(self.min_order_value) > 0 and flt(self.max_order_value) > 0:
            if flt(self.min_order_value) > flt(self.max_order_value):
                frappe.throw(_("Min order value cannot be greater than max order value"))

        # Validate quantity range
        if cint(self.min_quantity) > 0 and cint(self.max_quantity) > 0:
            if cint(self.min_quantity) > cint(self.max_quantity):
                frappe.throw(_("Min quantity cannot be greater than max quantity"))

        # Validate category link
        if self.category and not frappe.db.exists("Category", self.category):
            frappe.throw(_("Category {0} does not exist").format(self.category))

        # Validate seller tier link
        if self.seller_tier and not frappe.db.exists("Seller Tier", self.seller_tier):
            frappe.throw(_("Seller Tier {0} does not exist").format(self.seller_tier))

    def validate_restrictions(self):
        """Validate seller and category restrictions."""
        # Validate JSON fields
        for field in ['restricted_sellers', 'excluded_sellers',
                      'restricted_categories', 'excluded_categories',
                      'day_of_week_restrictions', 'override_by']:
            value = getattr(self, field, None)
            if value:
                try:
                    parsed = json.loads(value)
                    if not isinstance(parsed, list):
                        frappe.throw(_("{0} must be a JSON array").format(field))
                except json.JSONDecodeError:
                    frappe.throw(_("{0} must be valid JSON").format(field))

        # Validate day of week values
        if self.day_of_week_restrictions:
            days = json.loads(self.day_of_week_restrictions)
            for day in days:
                if not isinstance(day, int) or day < 0 or day > 6:
                    frappe.throw(_("Day of week must be integer 0-6 (0=Monday)"))

    def validate_time_settings(self):
        """Validate time-based settings."""
        if self.time_start and self.time_end:
            # Time validation is handled by Frappe field type
            pass

    def validate_default_rule(self):
        """Ensure only one default rule per tenant/type combination."""
        if cint(self.is_default) and self.status == "Active":
            filters = {
                "is_default": 1,
                "status": "Active",
                "rule_type": self.rule_type,
                "name": ["!=", self.name]
            }

            if self.tenant:
                filters["tenant"] = self.tenant
            else:
                filters["tenant"] = ["is", "not set"]

            existing_default = frappe.db.exists("Commission Rule", filters)
            if existing_default:
                frappe.db.set_value("Commission Rule", existing_default, "is_default", 0)
                frappe.msgprint(
                    _("Previous default rule has been unset"),
                    indicator="blue"
                )

    # =================================================================
    # Helper Methods
    # =================================================================

    def generate_rule_code(self):
        """Generate a unique rule code."""
        base_code = self.rule_type.upper().replace(" ", "_")[:10]
        counter = 1
        code = f"{base_code}_{counter:03d}"

        while frappe.db.exists("Commission Rule", {"rule_code": code}):
            counter += 1
            code = f"{base_code}_{counter:03d}"

        return code

    def check_usage_before_delete(self):
        """Check if rule has been used before deletion."""
        if cint(self.usage_count) > 0:
            frappe.msgprint(
                _("Warning: This rule has been used {0} times. Deletion will remove usage history.").format(
                    self.usage_count
                ),
                indicator="orange"
            )

    def clear_cache(self):
        """Clear cached rule data."""
        frappe.cache().delete_value(f"commission_rule:{self.name}")
        frappe.cache().delete_value(f"commission_rule_code:{self.rule_code}")
        frappe.cache().delete_value("active_commission_rules")

    # =================================================================
    # Rule Evaluation Methods
    # =================================================================

    def is_active(self):
        """Check if the rule is currently active."""
        if self.status != "Active":
            return False

        now = now_datetime()

        # Check date validity
        if self.effective_from and get_datetime(self.effective_from) > now:
            return False

        if self.effective_until and get_datetime(self.effective_until) < now:
            return False

        # Check day of week
        if self.day_of_week_restrictions:
            days = json.loads(self.day_of_week_restrictions)
            if days and now.weekday() not in days:
                return False

        # Check time of day
        if self.time_start and self.time_end:
            current_time = now.time()
            start_time = datetime.strptime(str(self.time_start), "%H:%M:%S").time()
            end_time = datetime.strptime(str(self.time_end), "%H:%M:%S").time()

            if start_time <= end_time:
                if not (start_time <= current_time <= end_time):
                    return False
            else:
                # Crosses midnight
                if not (current_time >= start_time or current_time <= end_time):
                    return False

        return True

    def matches_context(self, ctx):
        """
        Check if this rule matches the given context.

        Args:
            ctx (dict): Context dictionary containing:
                - order_value: Order total
                - quantity: Total quantity
                - category: Product category
                - seller: Seller Profile name
                - seller_tier: Seller's tier
                - seller_type: Individual/Business/Enterprise
                - product_type: Physical/Digital/Service/Subscription
                - listing: Listing name

        Returns:
            bool: True if rule matches context
        """
        if not self.is_active():
            return False

        # Check apply_to conditions
        if self.apply_to != "All":
            if not self._check_apply_to(ctx):
                return False

        # Check additional conditions
        if self.category:
            if ctx.get("category") != self.category:
                # Check parent categories
                if not self._category_matches(ctx.get("category"), self.category):
                    return False

        if self.seller_tier:
            if ctx.get("seller_tier") != self.seller_tier:
                return False

        if self.seller_type:
            if ctx.get("seller_type") != self.seller_type:
                return False

        if self.product_type:
            if ctx.get("product_type") != self.product_type:
                return False

        # Check value ranges
        if flt(self.min_order_value) > 0:
            if flt(ctx.get("order_value", 0)) < flt(self.min_order_value):
                return False

        if flt(self.max_order_value) > 0:
            if flt(ctx.get("order_value", 0)) > flt(self.max_order_value):
                return False

        if cint(self.min_quantity) > 0:
            if cint(ctx.get("quantity", 0)) < cint(self.min_quantity):
                return False

        if cint(self.max_quantity) > 0:
            if cint(ctx.get("quantity", 0)) > cint(self.max_quantity):
                return False

        # Check seller restrictions
        if not self._check_seller_restrictions(ctx.get("seller")):
            return False

        # Check category restrictions
        if not self._check_category_restrictions(ctx.get("category")):
            return False

        # Check custom condition
        if self.condition_type == "Custom Expression" and self.custom_condition:
            if not self._evaluate_custom_condition(ctx):
                return False

        return True

    def _check_apply_to(self, ctx):
        """Check apply_to condition."""
        value = self.apply_to_value
        operator = self.apply_to_operator or "Equals"

        if self.apply_to == "Category":
            target = ctx.get("category", "")
        elif self.apply_to == "Seller":
            target = ctx.get("seller", "")
        elif self.apply_to == "Seller Tier":
            target = ctx.get("seller_tier", "")
        elif self.apply_to == "Product Type":
            target = ctx.get("product_type", "")
        elif self.apply_to == "Listing":
            target = ctx.get("listing", "")
        elif self.apply_to == "Order Value Range":
            # Handled by min/max order value
            return True
        elif self.apply_to == "Quantity Range":
            # Handled by min/max quantity
            return True
        else:
            return True

        return self._match_operator(target, value, operator)

    def _match_operator(self, target, value, operator):
        """Match value using operator."""
        if operator == "Equals":
            return target == value
        elif operator == "Not Equals":
            return target != value
        elif operator == "In List":
            try:
                values = json.loads(value) if value else []
                return target in values
            except:
                return target in [v.strip() for v in (value or "").split(",")]
        elif operator == "Not In List":
            try:
                values = json.loads(value) if value else []
                return target not in values
            except:
                return target not in [v.strip() for v in (value or "").split(",")]
        elif operator == "Contains":
            return value and value in (target or "")
        elif operator == "Starts With":
            return target and (target or "").startswith(value or "")

        return False

    def _category_matches(self, actual_category, rule_category):
        """Check if actual category matches rule category (including parents)."""
        if not actual_category:
            return False

        # Check direct match
        if actual_category == rule_category:
            return True

        # Check parent categories
        parent = frappe.db.get_value("Category", actual_category, "parent_category")
        while parent:
            if parent == rule_category:
                return True
            parent = frappe.db.get_value("Category", parent, "parent_category")

        return False

    def _check_seller_restrictions(self, seller):
        """Check seller restrictions."""
        if not seller:
            return True

        # Check restricted sellers (whitelist)
        if self.restricted_sellers:
            restricted = json.loads(self.restricted_sellers)
            if restricted and seller not in restricted:
                return False

        # Check excluded sellers (blacklist)
        if self.excluded_sellers:
            excluded = json.loads(self.excluded_sellers)
            if seller in excluded:
                return False

        return True

    def _check_category_restrictions(self, category):
        """Check category restrictions."""
        if not category:
            return True

        # Check restricted categories (whitelist)
        if self.restricted_categories:
            restricted = json.loads(self.restricted_categories)
            if restricted and category not in restricted:
                return False

        # Check excluded categories (blacklist)
        if self.excluded_categories:
            excluded = json.loads(self.excluded_categories)
            if category in excluded:
                return False

        return True

    def _evaluate_custom_condition(self, ctx):
        """
        Evaluate custom condition safely without using eval().

        Supports structured JSON conditions in the format:
        {
            "field": "ctx.order_value",
            "operator": ">",
            "value": 1000
        }

        Or compound conditions:
        {
            "and": [
                {"field": "ctx.order_value", "operator": ">", "value": 1000},
                {"field": "ctx.seller_tier", "operator": "==", "value": "Gold"}
            ]
        }

        Supported operators: ==, !=, >, >=, <, <=, in, not_in, contains
        """
        if not self.custom_condition:
            return True

        try:
            # Parse JSON condition
            condition = json.loads(self.custom_condition)
            return self._evaluate_condition_tree(condition, ctx)

        except json.JSONDecodeError:
            frappe.log_error(
                f"Commission rule custom condition must be valid JSON: {self.custom_condition}",
                "Commission Rule Evaluation Error"
            )
            return False
        except Exception as e:
            frappe.log_error(
                f"Commission rule custom condition error: {str(e)}",
                "Commission Rule Evaluation Error"
            )
            return False

    def _evaluate_condition_tree(self, condition, ctx):
        """
        Recursively evaluate condition tree.

        Args:
            condition: Condition dict or compound condition
            ctx: Context dictionary

        Returns:
            bool: Evaluation result
        """
        if not isinstance(condition, dict):
            return False

        # Handle compound conditions (and/or)
        if "and" in condition:
            return all(self._evaluate_condition_tree(c, ctx) for c in condition["and"])

        if "or" in condition:
            return any(self._evaluate_condition_tree(c, ctx) for c in condition["or"])

        if "not" in condition:
            return not self._evaluate_condition_tree(condition["not"], ctx)

        # Handle simple condition
        field = condition.get("field", "")
        operator = condition.get("operator", "==")
        compare_value = condition.get("value")

        # Get field value from context safely
        field_value = self._get_field_value(field, ctx)

        # Evaluate using safe operators
        return self._safe_compare(field_value, operator, compare_value)

    def _get_field_value(self, field_path, ctx):
        """
        Safely get a value from context using dot notation.

        Args:
            field_path: Dot-separated field path (e.g., "ctx.order_value")
            ctx: Context dictionary

        Returns:
            The field value or None if not found
        """
        if not field_path:
            return None

        # Remove 'ctx.' prefix if present
        if field_path.startswith("ctx."):
            field_path = field_path[4:]

        # Navigate through nested structure
        parts = field_path.split(".")
        value = ctx

        for part in parts:
            if isinstance(value, dict):
                value = value.get(part)
            else:
                return None

            if value is None:
                return None

        return value

    def _safe_compare(self, field_value, operator, compare_value):
        """
        Safely compare values using allowed operators only.

        Args:
            field_value: Value from context
            operator: Comparison operator
            compare_value: Value to compare against

        Returns:
            bool: Comparison result
        """
        operators = {
            "==": lambda a, b: a == b,
            "!=": lambda a, b: a != b,
            ">": lambda a, b: flt(a) > flt(b),
            ">=": lambda a, b: flt(a) >= flt(b),
            "<": lambda a, b: flt(a) < flt(b),
            "<=": lambda a, b: flt(a) <= flt(b),
            "in": lambda a, b: a in b if isinstance(b, (list, tuple)) else False,
            "not_in": lambda a, b: a not in b if isinstance(b, (list, tuple)) else True,
            "contains": lambda a, b: b in a if isinstance(a, (str, list, tuple)) else False,
            "starts_with": lambda a, b: str(a).startswith(str(b)) if a else False,
            "ends_with": lambda a, b: str(a).endswith(str(b)) if a else False,
        }

        if operator not in operators:
            frappe.log_error(
                f"Unknown operator in commission rule: {operator}",
                "Commission Rule Evaluation Error"
            )
            return False

        try:
            return operators[operator](field_value, compare_value)
        except Exception as e:
            frappe.log_error(
                f"Comparison error in commission rule: {str(e)}",
                "Commission Rule Evaluation Error"
            )
            return False

    # =================================================================
    # Commission Calculation Methods
    # =================================================================

    def calculate_commission(self, order_value, ctx=None):
        """
        Calculate commission based on this rule.

        Args:
            order_value: The base order value
            ctx: Optional context dictionary for advanced calculations

        Returns:
            dict: Commission calculation result
        """
        ctx = ctx or {}

        # Calculate commission base
        commission_base = flt(order_value)

        if cint(self.exclude_shipping):
            commission_base -= flt(ctx.get("shipping_cost", 0))

        if cint(self.exclude_tax):
            commission_base -= flt(ctx.get("tax_amount", 0))

        if cint(self.exclude_discounts):
            commission_base -= flt(ctx.get("discount_amount", 0))

        if cint(self.include_seller_discounts):
            commission_base += flt(ctx.get("seller_discount", 0))

        commission_base = max(commission_base, 0)

        # Calculate commission based on type
        commission_amount = 0

        if self.commission_type == "Percentage":
            commission_amount = commission_base * (flt(self.commission_rate) / 100)

        elif self.commission_type == "Fixed Amount":
            commission_amount = flt(self.fixed_commission)

        elif self.commission_type == "Percentage + Fixed":
            commission_amount = (
                commission_base * (flt(self.commission_rate) / 100) +
                flt(self.fixed_commission)
            )

        elif self.commission_type == "Tiered":
            # Tiered calculation would use Commission Plan tiers
            commission_amount = commission_base * (flt(self.commission_rate) / 100)

        elif self.commission_type == "Custom Formula":
            # Custom formula would be evaluated
            commission_amount = commission_base * (flt(self.commission_rate) / 100)

        # Apply min/max constraints
        if flt(self.minimum_commission) > 0:
            commission_amount = max(commission_amount, flt(self.minimum_commission))

        if flt(self.maximum_commission) > 0:
            commission_amount = min(commission_amount, flt(self.maximum_commission))

        commission_amount = round(commission_amount, 2)

        return {
            "commission_amount": commission_amount,
            "effective_rate": (commission_amount / commission_base * 100) if commission_base > 0 else 0,
            "commission_base": commission_base,
            "rule_name": self.rule_name,
            "rule_code": self.rule_code,
            "rule_type": self.rule_type
        }

    def record_usage(self, order_value, commission_amount, order_name=None):
        """
        Record that this rule was used.

        Args:
            order_value: Order value processed
            commission_amount: Commission calculated
            order_name: Sub Order name
        """
        # Update statistics
        new_count = cint(self.usage_count) + 1
        new_total_commission = flt(self.total_commission_generated) + flt(commission_amount)
        new_total_gmv = flt(self.total_gmv_processed) + flt(order_value)
        new_average = new_total_commission / new_count if new_count > 0 else 0

        self.db_set("usage_count", new_count, update_modified=False)
        self.db_set("total_commission_generated", new_total_commission, update_modified=False)
        self.db_set("total_gmv_processed", new_total_gmv, update_modified=False)
        self.db_set("average_commission_amount", new_average, update_modified=False)
        self.db_set("last_applied_date", now_datetime(), update_modified=False)

        if order_name:
            self.db_set("last_applied_order", order_name, update_modified=False)

    # =================================================================
    # Status Methods
    # =================================================================

    def activate(self):
        """Activate the rule."""
        if self.status == "Active":
            frappe.throw(_("Rule is already active"))

        self.status = "Active"
        self.save()
        frappe.msgprint(_("Commission rule activated"))

    def suspend(self, reason=None):
        """Suspend the rule."""
        self.status = "Suspended"
        if reason:
            self.notes = f"Suspended: {reason}\n{self.notes or ''}"
        self.save()
        frappe.msgprint(_("Commission rule suspended"))

    def archive(self):
        """Archive the rule."""
        self.status = "Archived"
        self.save()
        frappe.msgprint(_("Commission rule archived"))

    def expire(self):
        """Mark rule as expired."""
        self.status = "Expired"
        self.save()

    def get_summary(self):
        """Get rule summary for display."""
        return {
            "name": self.name,
            "rule_name": self.rule_name,
            "rule_code": self.rule_code,
            "rule_type": self.rule_type,
            "status": self.status,
            "priority": self.priority,
            "commission_type": self.commission_type,
            "commission_rate": self.commission_rate,
            "fixed_commission": self.fixed_commission,
            "category": self.category,
            "seller_tier": self.seller_tier,
            "is_active": self.is_active(),
            "usage_count": self.usage_count,
            "effective_from": str(self.effective_from) if self.effective_from else None,
            "effective_until": str(self.effective_until) if self.effective_until else None
        }


# =================================================================
# Module-Level Functions
# =================================================================

def get_applicable_rules(ctx, tenant=None, limit=None):
    """
    Get all commission rules applicable to a given context.

    Args:
        ctx: Context dictionary
        tenant: Optional tenant filter
        limit: Maximum number of rules to return

    Returns:
        list: List of applicable Commission Rule documents
    """
    # Get active rules ordered by priority
    filters = {"status": "Active"}
    if tenant:
        filters["tenant"] = ["in", [tenant, None, ""]]

    rules = frappe.get_all(
        "Commission Rule",
        filters=filters,
        fields=["name"],
        order_by="priority desc"
    )

    applicable = []
    for r in rules:
        rule = frappe.get_doc("Commission Rule", r.name)
        if rule.matches_context(ctx):
            applicable.append(rule)
            if limit and len(applicable) >= limit:
                break

    return applicable


def calculate_commission_with_rules(order_value, ctx, tenant=None):
    """
    Calculate commission using the rule engine.

    Args:
        order_value: Order total
        ctx: Context dictionary
        tenant: Optional tenant

    Returns:
        dict: Commission calculation result with applied rule info
    """
    # Get the first matching rule
    rules = get_applicable_rules(ctx, tenant, limit=1)

    if not rules:
        # Return default commission (10%)
        commission_amount = flt(order_value) * 0.10
        return {
            "commission_amount": round(commission_amount, 2),
            "effective_rate": 10.0,
            "commission_base": flt(order_value),
            "rule_name": "Default",
            "rule_code": "DEFAULT",
            "rule_type": "Standard",
            "is_default": True
        }

    rule = rules[0]
    result = rule.calculate_commission(order_value, ctx)
    result["is_default"] = False

    return result


# =================================================================
# API Endpoints
# =================================================================

@frappe.whitelist()
def get_commission_rule(rule_name=None, rule_code=None):
    """
    Get commission rule details.

    Args:
        rule_name: Name of the commission rule
        rule_code: Code of the commission rule

    Returns:
        dict: Commission rule summary
    """
    if not rule_name and not rule_code:
        frappe.throw(_("Please provide rule name or code"))

    if rule_code:
        rule_name = frappe.db.get_value("Commission Rule", {"rule_code": rule_code}, "name")

    if not rule_name or not frappe.db.exists("Commission Rule", rule_name):
        return {"error": _("Commission rule not found")}

    rule = frappe.get_doc("Commission Rule", rule_name)
    return rule.get_summary()


@frappe.whitelist()
def get_active_rules(tenant=None, rule_type=None):
    """
    Get all active commission rules.

    Args:
        tenant: Optional tenant filter
        rule_type: Optional rule type filter

    Returns:
        list: List of active rule summaries
    """
    filters = {"status": "Active"}

    if tenant:
        filters["tenant"] = ["in", [tenant, None, ""]]

    if rule_type:
        filters["rule_type"] = rule_type

    rules = frappe.get_all(
        "Commission Rule",
        filters=filters,
        fields=[
            "name", "rule_name", "rule_code", "rule_type", "priority",
            "commission_type", "commission_rate", "fixed_commission",
            "category", "seller_tier", "effective_from", "effective_until"
        ],
        order_by="priority desc"
    )

    # Check which rules are currently active
    for rule in rules:
        rule_doc = frappe.get_doc("Commission Rule", rule.name)
        rule["is_currently_active"] = rule_doc.is_active()

    return rules


@frappe.whitelist()
def calculate_commission(order_value, category=None, seller=None,
                        seller_tier=None, seller_type=None, tenant=None):
    """
    Calculate commission for given parameters using rule engine.

    Args:
        order_value: Order total
        category: Product category
        seller: Seller profile name
        seller_tier: Seller's tier
        seller_type: Seller type
        tenant: Tenant

    Returns:
        dict: Commission calculation result
    """
    ctx = {
        "order_value": flt(order_value),
        "category": category,
        "seller": seller,
        "seller_tier": seller_tier,
        "seller_type": seller_type
    }

    return calculate_commission_with_rules(flt(order_value), ctx, tenant)


@frappe.whitelist()
def test_rule(rule_name, order_value, category=None, seller=None,
              seller_tier=None, quantity=None):
    """
    Test a commission rule with given parameters.

    Args:
        rule_name: Commission rule name
        order_value: Order total to test
        category: Category to test
        seller: Seller to test
        seller_tier: Seller tier to test
        quantity: Quantity to test

    Returns:
        dict: Test result with match status and calculation
    """
    if not frappe.db.exists("Commission Rule", rule_name):
        return {"error": _("Rule not found")}

    rule = frappe.get_doc("Commission Rule", rule_name)

    ctx = {
        "order_value": flt(order_value),
        "category": category,
        "seller": seller,
        "seller_tier": seller_tier,
        "quantity": cint(quantity)
    }

    matches = rule.matches_context(ctx)

    result = {
        "rule_name": rule.rule_name,
        "rule_code": rule.rule_code,
        "matches": matches,
        "is_active": rule.is_active()
    }

    if matches:
        calculation = rule.calculate_commission(flt(order_value), ctx)
        result["calculation"] = calculation

    return result


@frappe.whitelist()
def get_rule_statistics(rule_name):
    """
    Get statistics for a commission rule.

    Args:
        rule_name: Commission rule name

    Returns:
        dict: Rule statistics
    """
    if not frappe.db.exists("Commission Rule", rule_name):
        return {"error": _("Rule not found")}

    rule = frappe.get_doc("Commission Rule", rule_name)

    return {
        "rule_name": rule.rule_name,
        "status": rule.status,
        "usage_count": rule.usage_count,
        "total_commission_generated": rule.total_commission_generated,
        "total_gmv_processed": rule.total_gmv_processed,
        "average_commission_amount": rule.average_commission_amount,
        "last_applied_date": str(rule.last_applied_date) if rule.last_applied_date else None,
        "effective_rate": (
            (rule.total_commission_generated / rule.total_gmv_processed * 100)
            if rule.total_gmv_processed > 0 else 0
        )
    }


@frappe.whitelist()
def expire_outdated_rules():
    """
    Expire rules that have passed their effective_until date.
    Called by scheduled job.

    Returns:
        dict: Number of rules expired
    """
    rules = frappe.db.sql("""
        SELECT name
        FROM `tabCommission Rule`
        WHERE status = 'Active'
        AND is_perpetual = 0
        AND effective_until < NOW()
    """, as_dict=True)

    expired = 0
    for r in rules:
        try:
            rule = frappe.get_doc("Commission Rule", r.name)
            rule.expire()
            expired += 1
        except Exception as e:
            frappe.log_error(
                f"Failed to expire rule {r.name}: {str(e)}",
                "Commission Rule Expiry Error"
            )

    return {"expired": expired}

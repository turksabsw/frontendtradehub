# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import nowdate, now_datetime, getdate, add_days, date_diff


class KPITemplate(Document):
    """KPI Template DocType for defining KPI metrics and evaluation criteria."""

    def validate(self):
        """Validate KPI template data."""
        self.validate_template_code()
        self.validate_default_template()
        self.validate_passing_score()
        self.validate_items()
        self.calculate_total_weight()
        self.set_display_name()

    def validate_template_code(self):
        """Validate and format template code."""
        if self.template_code:
            import re
            # Auto-format to uppercase
            self.template_code = self.template_code.upper().replace(" ", "_").replace("-", "_")
            if not re.match(r'^[A-Z0-9_]+$', self.template_code):
                frappe.throw(_("Template code should contain only letters, numbers, and underscores"))

    def validate_default_template(self):
        """Ensure only one template is marked as default per target type."""
        if self.is_default:
            existing_default = frappe.db.get_value(
                "KPI Template",
                {
                    "is_default": 1,
                    "target_type": self.target_type,
                    "name": ("!=", self.name)
                },
                "name"
            )
            if existing_default:
                frappe.throw(
                    _("Template '{0}' is already set as default for {1}. Only one template can be default per target type.").format(
                        existing_default, self.target_type
                    )
                )

    def validate_passing_score(self):
        """Validate passing score is within valid range."""
        if self.passing_score is not None:
            if self.passing_score < 0 or self.passing_score > 100:
                frappe.throw(_("Passing score must be between 0 and 100"))

    def validate_items(self):
        """Validate KPI items."""
        if not self.items or len(self.items) == 0:
            frappe.throw(_("At least one KPI metric item is required"))

        # Check for duplicate KPI codes
        kpi_codes = [item.kpi_code for item in self.items if item.kpi_code]
        if len(kpi_codes) != len(set(kpi_codes)):
            frappe.throw(_("KPI codes must be unique within a template"))

        # Warn about zero-weight items
        zero_weight_count = sum(1 for item in self.items if item.weight == 0)
        if zero_weight_count > 0:
            frappe.msgprint(
                _("{0} KPI item(s) have zero weight and will not contribute to the score").format(zero_weight_count),
                indicator="orange",
                alert=True
            )

    def calculate_total_weight(self):
        """Calculate and set total weight from items."""
        self.total_weight = sum(item.weight or 0 for item in self.items if item.is_active)

    def set_display_name(self):
        """Set display name if not provided."""
        if not self.display_name:
            self.display_name = self.template_name

    def before_save(self):
        """Actions before saving."""
        self.modified_at = now_datetime()
        if not self.created_at:
            self.created_at = now_datetime()

    def on_update(self):
        """Actions after update."""
        # Clear cache for KPI template lookups
        frappe.cache().delete_key("kpi_templates_list")

    def get_active_items(self):
        """Get list of active KPI items."""
        return [item for item in self.items if item.is_active]

    def get_item_by_code(self, kpi_code):
        """Get a specific KPI item by code."""
        for item in self.items:
            if item.kpi_code == kpi_code and item.is_active:
                return item
        return None

    def get_evaluation_period_dates(self, reference_date=None):
        """
        Get start and end dates for evaluation period.

        Args:
            reference_date: The reference date (defaults to today)

        Returns:
            tuple: (start_date, end_date)
        """
        if not reference_date:
            reference_date = getdate(nowdate())

        if self.evaluation_period == "Daily":
            return (reference_date, reference_date)

        elif self.evaluation_period == "Weekly":
            # Start from Monday of current week
            start_of_week = add_days(reference_date, -reference_date.weekday())
            return (start_of_week, add_days(start_of_week, 6))

        elif self.evaluation_period == "Monthly":
            # Start from first day of month
            start_of_month = reference_date.replace(day=1)
            # End on last day of month
            if reference_date.month == 12:
                end_of_month = reference_date.replace(month=12, day=31)
            else:
                end_of_month = add_days(reference_date.replace(month=reference_date.month + 1, day=1), -1)
            return (start_of_month, end_of_month)

        elif self.evaluation_period == "Quarterly":
            # Determine current quarter
            quarter = (reference_date.month - 1) // 3
            start_month = quarter * 3 + 1
            start_of_quarter = reference_date.replace(month=start_month, day=1)
            end_month = start_month + 2
            if end_month == 12:
                end_of_quarter = reference_date.replace(month=12, day=31)
            else:
                end_of_quarter = add_days(reference_date.replace(month=end_month + 1, day=1), -1)
            return (start_of_quarter, end_of_quarter)

        elif self.evaluation_period == "Yearly":
            start_of_year = reference_date.replace(month=1, day=1)
            end_of_year = reference_date.replace(month=12, day=31)
            return (start_of_year, end_of_year)

        elif self.evaluation_period == "Custom" and self.evaluation_period_value:
            start_date = add_days(reference_date, -self.evaluation_period_value + 1)
            return (start_date, reference_date)

        # Default to monthly
        start_of_month = reference_date.replace(day=1)
        if reference_date.month == 12:
            end_of_month = reference_date.replace(month=12, day=31)
        else:
            end_of_month = add_days(reference_date.replace(month=reference_date.month + 1, day=1), -1)
        return (start_of_month, end_of_month)

    def applies_to(self, profile_type, level=None, category=None):
        """
        Check if this template applies to a given profile.

        Args:
            profile_type: 'Seller' or 'Buyer'
            level: Optional level name
            category: Optional category name

        Returns:
            bool: True if template applies
        """
        # Check target type
        if self.target_type not in [profile_type, "Both"]:
            return False

        # Check applicable levels
        if self.applicable_levels:
            levels = [l.strip() for l in self.applicable_levels.split(",") if l.strip()]
            if level and level not in levels:
                return False

        # Check applicable categories
        if self.applicable_categories:
            categories = [c.strip() for c in self.applicable_categories.split(",") if c.strip()]
            if category and category not in categories:
                return False

        return True

    def can_evaluate(self, profile):
        """
        Check if a profile meets minimum requirements for evaluation.

        Args:
            profile: Seller Profile or Buyer Profile name

        Returns:
            tuple: (can_evaluate: bool, reason: str or None)
        """
        # Determine profile type
        if frappe.db.exists("Seller Profile", profile):
            profile_doc = frappe.get_doc("Seller Profile", profile)
            profile_type = "Seller"
        elif frappe.db.exists("User", profile):
            profile_doc = frappe.get_doc("User", profile)
            profile_type = "Buyer"
        else:
            return (False, _("Profile not found"))

        # Check minimum orders
        if self.min_orders_required and self.min_orders_required > 0:
            if profile_type == "Seller":
                order_count = frappe.db.count("Sub Order", {"seller": profile, "docstatus": 1})
            else:
                order_count = frappe.db.count("Marketplace Order", {"buyer": profile, "docstatus": 1})

            if order_count < self.min_orders_required:
                return (False, _("Minimum orders not met ({0}/{1})").format(order_count, self.min_orders_required))

        # Check minimum days active
        if self.min_days_active and self.min_days_active > 0:
            creation_date = getdate(profile_doc.creation)
            days_active = date_diff(nowdate(), creation_date)
            if days_active < self.min_days_active:
                return (False, _("Minimum days active not met ({0}/{1})").format(days_active, self.min_days_active))

        return (True, None)

    def calculate_score(self, kpi_values):
        """
        Calculate overall KPI score from individual values.

        Args:
            kpi_values: dict of {kpi_code: value}

        Returns:
            dict: {
                'total_score': float,
                'passing': bool,
                'item_scores': list of item score details
            }
        """
        item_scores = []
        weighted_sum = 0
        total_weight = 0

        for item in self.get_active_items():
            kpi_code = item.kpi_code or item.kpi_name
            value = kpi_values.get(kpi_code)

            if value is not None:
                score = item.calculate_score(value)
                status = item.get_status(value)
                weighted_score = score * (item.weight or 1)

                item_scores.append({
                    "kpi_code": kpi_code,
                    "kpi_name": item.kpi_name,
                    "value": value,
                    "formatted_value": item.format_value(value),
                    "score": score,
                    "max_score": item.max_score or 100,
                    "weight": item.weight or 1,
                    "weighted_score": weighted_score,
                    "status": status,
                    "target": item.target_value,
                    "threshold_type": item.threshold_type
                })

                weighted_sum += weighted_score
                total_weight += (item.weight or 1)

        # Calculate final score
        if total_weight > 0:
            raw_score = weighted_sum / total_weight
        else:
            raw_score = 0

        # Apply scoring curve if needed
        final_score = self._apply_scoring_curve(raw_score)

        # Normalize if enabled
        if self.normalize_scores:
            final_score = min(100, max(0, final_score))

        passing = final_score >= (self.passing_score or 0)

        return {
            "total_score": round(final_score, 2),
            "passing": passing,
            "passing_score": self.passing_score or 0,
            "item_scores": item_scores,
            "total_weight": total_weight
        }

    def _apply_scoring_curve(self, score):
        """Apply scoring curve transformation."""
        if self.scoring_curve == "Linear":
            return score

        elif self.scoring_curve == "Bell Curve":
            # Favor middle-high scores
            import math
            normalized = score / 100
            return 100 * math.exp(-((normalized - 0.8) ** 2) / 0.2)

        elif self.scoring_curve == "Exponential":
            # Favor high scores more
            return (score / 100) ** 0.5 * 100

        elif self.scoring_curve == "Step":
            # Step function at certain thresholds
            if score >= 90:
                return 100
            elif score >= 75:
                return 85
            elif score >= 60:
                return 70
            elif score >= 40:
                return 50
            return 30

        return score

    def update_statistics(self, score):
        """Update template statistics after evaluation."""
        self.usage_count = (self.usage_count or 0) + 1
        self.last_evaluated_at = now_datetime()

        # Update rolling average
        if self.average_score:
            self.average_score = (self.average_score * (self.usage_count - 1) + score) / self.usage_count
        else:
            self.average_score = score

        self.db_update()

    def duplicate(self, new_name=None):
        """
        Create a copy of this template.

        Args:
            new_name: Optional new name for the duplicate

        Returns:
            KPI Template: The duplicated template
        """
        new_template = frappe.copy_doc(self)
        new_template.template_name = new_name or f"{self.template_name} (Copy)"
        new_template.is_default = 0
        new_template.usage_count = 0
        new_template.average_score = 0
        new_template.last_evaluated_at = None
        new_template.status = "Draft"

        if self.template_code:
            new_template.template_code = f"{self.template_code}_COPY"

        new_template.insert()
        return new_template


@frappe.whitelist()
def get_kpi_template(template_name):
    """Get a specific KPI template."""
    if not template_name:
        return None
    return frappe.get_doc("KPI Template", template_name)


@frappe.whitelist()
def get_default_template(target_type="Seller"):
    """Get the default KPI template for a target type."""
    default_template = frappe.db.get_value(
        "KPI Template",
        {"is_default": 1, "target_type": ["in", [target_type, "Both"]], "status": "Active"},
        "name"
    )
    if default_template:
        return frappe.get_doc("KPI Template", default_template)
    return None


@frappe.whitelist()
def get_all_templates(target_type=None, status="Active"):
    """Get all KPI templates, optionally filtered by target type."""
    filters = {"status": status}
    if target_type:
        filters["target_type"] = ["in", [target_type, "Both"]]

    templates = frappe.get_all(
        "KPI Template",
        filters=filters,
        fields=[
            "name", "template_name", "template_code", "target_type",
            "status", "is_default", "evaluation_period", "passing_score",
            "usage_count", "average_score"
        ],
        order_by="template_name ASC"
    )
    return templates


@frappe.whitelist()
def get_template_for_profile(profile, profile_type="Seller"):
    """
    Get the appropriate KPI template for a profile.

    Args:
        profile: Profile name
        profile_type: 'Seller' or 'Buyer'

    Returns:
        KPI Template or None
    """
    # Check if profile has a specific template assigned
    # (This would require adding a kpi_template field to Seller Profile / Buyer Profile)
    assigned_template = None

    if profile_type == "Seller":
        assigned_template = frappe.db.get_value("Seller Profile", profile, "kpi_template")
        level = frappe.db.get_value("Seller Profile", profile, "seller_level")
    else:
        level = None

    if assigned_template:
        template = frappe.get_doc("KPI Template", assigned_template)
        if template.status == "Active":
            return template

    # Get default template
    return get_default_template(profile_type)


@frappe.whitelist()
def evaluate_profile_kpi(profile, template_name=None, reference_date=None):
    """
    Evaluate KPI for a profile using a template.

    Args:
        profile: Profile name
        template_name: Optional specific template to use
        reference_date: Optional reference date

    Returns:
        dict: Evaluation results
    """
    # Determine profile type
    if frappe.db.exists("Seller Profile", profile):
        profile_type = "Seller"
    elif frappe.db.exists("User", profile):
        profile_type = "Buyer"
    else:
        return {"error": _("Profile not found")}

    # Get template
    if template_name:
        template = get_kpi_template(template_name)
    else:
        template = get_template_for_profile(profile, profile_type)

    if not template:
        return {"error": _("No KPI template found")}

    # Check if profile can be evaluated
    can_evaluate, reason = template.can_evaluate(profile)
    if not can_evaluate:
        return {"error": reason, "can_evaluate": False}

    # Get evaluation period dates
    start_date, end_date = template.get_evaluation_period_dates(
        getdate(reference_date) if reference_date else None
    )

    # Collect KPI values (this would need to be implemented based on specific metrics)
    kpi_values = collect_kpi_values(profile, profile_type, template, start_date, end_date)

    # Calculate score
    result = template.calculate_score(kpi_values)
    result["profile"] = profile
    result["profile_type"] = profile_type
    result["template"] = template.name
    result["start_date"] = str(start_date)
    result["end_date"] = str(end_date)
    result["evaluated_at"] = str(now_datetime())

    # Update template statistics
    template.update_statistics(result["total_score"])

    return result


def collect_kpi_values(profile, profile_type, template, start_date, end_date):
    """
    Collect actual KPI values for a profile.

    This is a placeholder that should be extended based on specific KPI metrics.
    """
    kpi_values = {}

    for item in template.get_active_items():
        value = None

        if profile_type == "Seller":
            value = collect_seller_kpi_value(profile, item, start_date, end_date)
        else:
            value = collect_buyer_kpi_value(profile, item, start_date, end_date)

        if value is not None:
            kpi_values[item.kpi_code or item.kpi_name] = value

    return kpi_values


def collect_seller_kpi_value(seller, kpi_item, start_date, end_date):
    """Collect a specific KPI value for a seller."""
    data_source = kpi_item.data_source
    aggregation = kpi_item.aggregation_method
    filters = kpi_item.get_filter_dict()

    # Add date range filter
    filters["seller"] = seller
    filters["docstatus"] = 1

    if data_source == "Sub Order":
        filters["transaction_date"] = ["between", [start_date, end_date]]

        if kpi_item.metric_type == "Count":
            return frappe.db.count("Sub Order", filters)

        elif kpi_item.metric_type == "Sum":
            total = frappe.db.sql("""
                SELECT COALESCE(SUM(grand_total), 0)
                FROM `tabSub Order`
                WHERE seller = %(seller)s
                AND docstatus = 1
                AND transaction_date BETWEEN %(start)s AND %(end)s
            """, {"seller": seller, "start": start_date, "end": end_date})[0][0]
            return total or 0

        elif kpi_item.metric_type == "Percentage":
            # Example: fulfillment rate
            total = frappe.db.count("Sub Order", {"seller": seller, "docstatus": 1,
                                                   "transaction_date": ["between", [start_date, end_date]]})
            if total > 0:
                completed = frappe.db.count("Sub Order", {"seller": seller, "docstatus": 1,
                                                          "status": "Completed",
                                                          "transaction_date": ["between", [start_date, end_date]]})
                return (completed / total) * 100
            return 100

    elif data_source == "Review":
        filters["creation"] = ["between", [start_date, end_date]]

        if kpi_item.metric_type == "Average":
            result = frappe.db.sql("""
                SELECT AVG(rating)
                FROM `tabReview`
                WHERE seller = %(seller)s
                AND docstatus = 1
                AND creation BETWEEN %(start)s AND %(end)s
            """, {"seller": seller, "start": start_date, "end": end_date})[0][0]
            return result or 0

        elif kpi_item.metric_type == "Count":
            return frappe.db.count("Review", {"seller": seller, "docstatus": 1,
                                              "creation": ["between", [start_date, end_date]]})

    return None


def collect_buyer_kpi_value(buyer, kpi_item, start_date, end_date):
    """Collect a specific KPI value for a buyer."""
    # Placeholder for buyer KPI collection
    return None


@frappe.whitelist()
def duplicate_template(template_name, new_name=None):
    """Duplicate a KPI template."""
    template = frappe.get_doc("KPI Template", template_name)
    new_template = template.duplicate(new_name)
    return new_template.name

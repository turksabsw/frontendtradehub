# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import (
    cint, flt, getdate, nowdate, now_datetime, add_days, add_months,
    date_diff, get_first_day, get_last_day, get_first_day_of_week,
    formatdate
)
from datetime import datetime, timedelta
import json
import math


class SellerKPI(Document):
    """
    Seller KPI DocType for tracking seller performance metrics.

    Tracks Key Performance Indicators for sellers with:
    - Various KPI types (fulfillment, delivery, quality, service)
    - Target values and thresholds
    - Automatic calculation from order/review data
    - Trend analysis and peer comparison
    - Alert settings for threshold breaches
    """

    def before_insert(self):
        """Set default values before inserting a new KPI record."""
        if not self.created_by:
            self.created_by = frappe.session.user
        self.created_at = now_datetime()

        # Get tenant from seller if not set
        if not self.tenant and self.seller:
            self.tenant = frappe.db.get_value("Seller Profile", self.seller, "tenant")

        # Set period label
        self.set_period_label()

        # Get previous value for comparison
        self.set_previous_value()

        # Set default thresholds based on KPI type
        self.set_default_thresholds()

    def validate(self):
        """Validate KPI data before saving."""
        self.validate_seller()
        self.validate_period()
        self.validate_thresholds()
        self.validate_values()
        self.calculate_derived_values()
        self.evaluate_performance()
        self.set_period_label()

    def on_update(self):
        """Actions after KPI is updated."""
        self.modified_at = now_datetime()
        self.modified_by = frappe.session.user

        # Check if alerts should be sent
        if self.alerts_enabled:
            self.check_and_send_alerts()

    def validate_seller(self):
        """Validate seller exists and is valid."""
        if not self.seller:
            frappe.throw(_("Seller is required"))

        if not frappe.db.exists("Seller Profile", self.seller):
            frappe.throw(_("Invalid seller"))

    def validate_period(self):
        """Validate period dates."""
        if not self.period_start or not self.period_end:
            frappe.throw(_("Period start and end dates are required"))

        if getdate(self.period_start) > getdate(self.period_end):
            frappe.throw(_("Period start date must be before end date"))

        # Check period duration
        days = date_diff(self.period_end, self.period_start)
        if days > 366:
            frappe.msgprint(
                _("Warning: KPI period spans more than a year ({0} days)").format(days),
                indicator="orange"
            )

    def validate_thresholds(self):
        """Validate threshold values are consistent."""
        if self.target_type in ["Higher is Better", "Within Range"]:
            # Warning should be below target, critical below warning
            if self.warning_threshold and flt(self.warning_threshold) >= flt(self.target_value):
                frappe.msgprint(
                    _("Warning threshold should be below target value"),
                    indicator="orange"
                )
            if self.critical_threshold and self.warning_threshold:
                if flt(self.critical_threshold) >= flt(self.warning_threshold):
                    frappe.msgprint(
                        _("Critical threshold should be below warning threshold"),
                        indicator="orange"
                    )

        elif self.target_type == "Lower is Better":
            # For metrics like return rate, warning should be above target
            if self.warning_threshold and flt(self.warning_threshold) <= flt(self.target_value):
                frappe.msgprint(
                    _("Warning threshold should be above target value for 'Lower is Better' KPIs"),
                    indicator="orange"
                )

    def validate_values(self):
        """Validate KPI values are within acceptable range."""
        # Check against min/max thresholds
        if self.minimum_threshold and flt(self.actual_value) < flt(self.minimum_threshold):
            if self.kpi_type not in ["Response Time", "Processing Time"]:  # Time metrics can be below min
                frappe.msgprint(
                    _("Actual value is below minimum threshold"),
                    indicator="orange"
                )

        if self.maximum_threshold and flt(self.actual_value) > flt(self.maximum_threshold):
            frappe.throw(_("Actual value cannot exceed maximum threshold"))

    def set_period_label(self):
        """Generate human-readable period label."""
        if not self.period_start:
            return

        start = getdate(self.period_start)

        if self.period_type == "Daily":
            self.period_label = formatdate(start, "dd MMM yyyy")
        elif self.period_type == "Weekly":
            self.period_label = f"Week {start.isocalendar()[1]}, {start.year}"
        elif self.period_type == "Monthly":
            self.period_label = formatdate(start, "MMM yyyy")
        elif self.period_type == "Quarterly":
            quarter = (start.month - 1) // 3 + 1
            self.period_label = f"Q{quarter} {start.year}"
        elif self.period_type == "Annually":
            self.period_label = str(start.year)
        elif self.period_type.startswith("Rolling"):
            days = self.period_type.split()[1]
            self.period_label = f"Rolling {days} Days"
        else:
            self.period_label = f"{formatdate(start, 'dd MMM')} - {formatdate(getdate(self.period_end), 'dd MMM yyyy')}"

        # Set evaluation_period if not set
        if not self.evaluation_period:
            if self.period_type == "Monthly":
                self.evaluation_period = start.strftime("%Y-%m")
            elif self.period_type == "Quarterly":
                quarter = (start.month - 1) // 3 + 1
                self.evaluation_period = f"{start.year}-Q{quarter}"
            elif self.period_type == "Weekly":
                self.evaluation_period = f"{start.year}-W{start.isocalendar()[1]:02d}"
            else:
                self.evaluation_period = start.strftime("%Y-%m-%d")

    def set_default_thresholds(self):
        """Set default thresholds based on KPI type."""
        kpi_defaults = {
            "Order Fulfillment Rate": {
                "target": 95, "warning": 90, "critical": 80, "min": 0, "max": 100, "type": "Higher is Better"
            },
            "On-Time Delivery Rate": {
                "target": 95, "warning": 90, "critical": 80, "min": 0, "max": 100, "type": "Higher is Better"
            },
            "Return Rate": {
                "target": 5, "warning": 10, "critical": 15, "min": 0, "max": 100, "type": "Lower is Better"
            },
            "Cancellation Rate": {
                "target": 3, "warning": 5, "critical": 10, "min": 0, "max": 100, "type": "Lower is Better"
            },
            "Response Time": {
                "target": 24, "warning": 48, "critical": 72, "min": 0, "max": 168, "type": "Lower is Better"
            },
            "Customer Satisfaction": {
                "target": 4.5, "warning": 4.0, "critical": 3.5, "min": 1, "max": 5, "type": "Higher is Better"
            },
            "Complaint Rate": {
                "target": 2, "warning": 5, "critical": 10, "min": 0, "max": 100, "type": "Lower is Better"
            },
            "Dispute Rate": {
                "target": 1, "warning": 3, "critical": 5, "min": 0, "max": 100, "type": "Lower is Better"
            },
            "Refund Rate": {
                "target": 5, "warning": 10, "critical": 20, "min": 0, "max": 100, "type": "Lower is Better"
            },
            "Shipment Tracking Rate": {
                "target": 100, "warning": 95, "critical": 90, "min": 0, "max": 100, "type": "Higher is Better"
            },
            "Review Response Rate": {
                "target": 80, "warning": 60, "critical": 40, "min": 0, "max": 100, "type": "Higher is Better"
            },
            "Listing Quality Score": {
                "target": 80, "warning": 60, "critical": 40, "min": 0, "max": 100, "type": "Higher is Better"
            },
            "Inventory Accuracy": {
                "target": 98, "warning": 95, "critical": 90, "min": 0, "max": 100, "type": "Higher is Better"
            },
            "Order Acceptance Rate": {
                "target": 95, "warning": 90, "critical": 80, "min": 0, "max": 100, "type": "Higher is Better"
            },
            "Processing Time": {
                "target": 24, "warning": 48, "critical": 72, "min": 0, "max": 168, "type": "Lower is Better"
            },
            "Packaging Quality": {
                "target": 95, "warning": 90, "critical": 80, "min": 0, "max": 100, "type": "Higher is Better"
            },
            "Shipping Label Accuracy": {
                "target": 99, "warning": 95, "critical": 90, "min": 0, "max": 100, "type": "Higher is Better"
            },
            "Communication Rating": {
                "target": 4.5, "warning": 4.0, "critical": 3.5, "min": 1, "max": 5, "type": "Higher is Better"
            },
            "Product Accuracy": {
                "target": 98, "warning": 95, "critical": 90, "min": 0, "max": 100, "type": "Higher is Better"
            },
            "Policy Compliance": {
                "target": 100, "warning": 95, "critical": 85, "min": 0, "max": 100, "type": "Higher is Better"
            }
        }

        defaults = kpi_defaults.get(self.kpi_type, {})

        # Only set if not already specified
        if not self.target_value and defaults.get("target"):
            self.target_value = defaults["target"]
        if not self.warning_threshold and defaults.get("warning"):
            self.warning_threshold = defaults["warning"]
        if not self.critical_threshold and defaults.get("critical"):
            self.critical_threshold = defaults["critical"]
        if not self.minimum_threshold and defaults.get("min") is not None:
            self.minimum_threshold = defaults["min"]
        if not self.maximum_threshold and defaults.get("max"):
            self.maximum_threshold = defaults["max"]
        if defaults.get("type"):
            self.target_type = defaults["type"]

    def set_previous_value(self):
        """Get the previous period value for comparison."""
        if not self.seller or not self.kpi_type:
            return

        # Find the most recent KPI record for this seller and type
        prev_kpi = frappe.db.get_value(
            "Seller KPI",
            {
                "seller": self.seller,
                "kpi_type": self.kpi_type,
                "name": ["!=", self.name or ""],
                "period_end": ["<", self.period_start or nowdate()]
            },
            ["actual_value", "status", "consecutive_periods_below"],
            order_by="period_end desc"
        )

        if prev_kpi:
            self.previous_value = flt(prev_kpi[0])
            # Track consecutive periods below target
            if prev_kpi[1] in ["Below Target", "Critical"]:
                self._prev_consecutive_below = cint(prev_kpi[2])
            else:
                self._prev_consecutive_below = 0

    def calculate_derived_values(self):
        """Calculate derived values from actual value."""
        # Value change
        self.value_change = round(flt(self.actual_value) - flt(self.previous_value), 2)

        # Percentage of target
        if flt(self.target_value) > 0:
            self.percentage_of_target = round((flt(self.actual_value) / flt(self.target_value)) * 100, 2)
        else:
            self.percentage_of_target = 100 if flt(self.actual_value) >= 0 else 0

        # Deviation from target
        self.deviation_from_target = round(flt(self.actual_value) - flt(self.target_value), 2)

        # Determine trend
        self.determine_trend()

        # Calculate score contribution (0-100 based on how well target is met)
        self.calculate_score_contribution()

    def determine_trend(self):
        """Determine value trend based on recent history."""
        if not self.seller or not self.kpi_type:
            self.value_trend = "New"
            return

        # Get last 5 KPI values
        recent_kpis = frappe.db.sql("""
            SELECT actual_value
            FROM `tabSeller KPI`
            WHERE seller = %s
            AND kpi_type = %s
            AND name != %s
            ORDER BY period_end DESC
            LIMIT 5
        """, (self.seller, self.kpi_type, self.name or ""), as_dict=True)

        if len(recent_kpis) < 2:
            self.value_trend = "New"
            return

        values = [k.actual_value for k in recent_kpis]

        # Calculate average change
        changes = [values[i] - values[i+1] for i in range(len(values)-1)]
        avg_change = sum(changes) / len(changes) if changes else 0

        # Check for volatility
        if len(changes) >= 3:
            std_dev = math.sqrt(sum((c - avg_change)**2 for c in changes) / len(changes))
            if std_dev > abs(avg_change) * 2:
                self.value_trend = "Volatile"
                return

        # Determine trend based on target type
        if self.target_type == "Higher is Better":
            if avg_change > 1:
                self.value_trend = "Improving"
            elif avg_change < -1:
                self.value_trend = "Declining"
            else:
                self.value_trend = "Stable"
        elif self.target_type == "Lower is Better":
            if avg_change < -1:  # Lower is better, so decreasing is improving
                self.value_trend = "Improving"
            elif avg_change > 1:
                self.value_trend = "Declining"
            else:
                self.value_trend = "Stable"
        else:
            self.value_trend = "Stable"

    def calculate_score_contribution(self):
        """Calculate this KPI's contribution to overall seller score."""
        actual = flt(self.actual_value)
        target = flt(self.target_value)
        warning = flt(self.warning_threshold) if self.warning_threshold else None
        critical = flt(self.critical_threshold) if self.critical_threshold else None

        if self.target_type == "Higher is Better":
            if actual >= target:
                # Exceeding target: 100 points
                self.score_contribution = 100
            elif warning and actual >= warning:
                # Between warning and target: 70-99 points
                if target > warning:
                    ratio = (actual - warning) / (target - warning)
                    self.score_contribution = round(70 + (ratio * 29), 2)
                else:
                    self.score_contribution = 70
            elif critical and actual >= critical:
                # Between critical and warning: 40-69 points
                if warning and warning > critical:
                    ratio = (actual - critical) / (warning - critical)
                    self.score_contribution = round(40 + (ratio * 29), 2)
                else:
                    self.score_contribution = 40
            else:
                # Below critical: 0-39 points
                if critical:
                    ratio = actual / critical if critical > 0 else 0
                    self.score_contribution = round(ratio * 39, 2)
                else:
                    self.score_contribution = 0

        elif self.target_type == "Lower is Better":
            if actual <= target:
                self.score_contribution = 100
            elif warning and actual <= warning:
                if warning > target:
                    ratio = 1 - ((actual - target) / (warning - target))
                    self.score_contribution = round(70 + (ratio * 29), 2)
                else:
                    self.score_contribution = 70
            elif critical and actual <= critical:
                if critical > warning:
                    ratio = 1 - ((actual - warning) / (critical - warning))
                    self.score_contribution = round(40 + (ratio * 29), 2)
                else:
                    self.score_contribution = 40
            else:
                self.score_contribution = 0

        else:
            # Closer to Target or Within Range
            deviation = abs(actual - target)
            if target > 0:
                deviation_percent = (deviation / target) * 100
                self.score_contribution = max(0, round(100 - deviation_percent, 2))
            else:
                self.score_contribution = 100 if deviation == 0 else 50

    def evaluate_performance(self):
        """Evaluate KPI performance and set status."""
        actual = flt(self.actual_value)
        target = flt(self.target_value)
        warning = flt(self.warning_threshold) if self.warning_threshold else None
        critical = flt(self.critical_threshold) if self.critical_threshold else None

        # Evaluate based on target type
        if self.target_type == "Higher is Better":
            if actual >= target * 1.1:  # 10% above target
                self.status = "Exceeding"
                self.evaluation_status = "Exceeding Target"
                self.performance_grade = "A+"
            elif actual >= target:
                self.status = "On Track"
                self.evaluation_status = "Meeting Target"
                self.performance_grade = "A"
            elif warning and actual >= warning:
                self.status = "At Risk"
                self.evaluation_status = "Below Warning Threshold"
                self.performance_grade = "B"
            elif critical and actual >= critical:
                self.status = "Below Target"
                self.evaluation_status = "Below Warning Threshold"
                self.performance_grade = "C"
            else:
                self.status = "Critical"
                self.evaluation_status = "Below Critical Threshold"
                self.performance_grade = "F"

        elif self.target_type == "Lower is Better":
            if actual <= target * 0.9:  # 10% below target (better)
                self.status = "Exceeding"
                self.evaluation_status = "Exceeding Target"
                self.performance_grade = "A+"
            elif actual <= target:
                self.status = "On Track"
                self.evaluation_status = "Meeting Target"
                self.performance_grade = "A"
            elif warning and actual <= warning:
                self.status = "At Risk"
                self.evaluation_status = "Below Warning Threshold"
                self.performance_grade = "B"
            elif critical and actual <= critical:
                self.status = "Below Target"
                self.evaluation_status = "Below Warning Threshold"
                self.performance_grade = "C"
            else:
                self.status = "Critical"
                self.evaluation_status = "Below Critical Threshold"
                self.performance_grade = "F"

        else:
            # Within Range / Closer to Target
            deviation_percent = abs(actual - target) / target * 100 if target > 0 else 0
            if deviation_percent <= 5:
                self.status = "On Track"
                self.evaluation_status = "Meeting Target"
                self.performance_grade = "A"
            elif deviation_percent <= 15:
                self.status = "At Risk"
                self.evaluation_status = "Within Acceptable Range"
                self.performance_grade = "B"
            elif deviation_percent <= 30:
                self.status = "Below Target"
                self.evaluation_status = "Below Warning Threshold"
                self.performance_grade = "C"
            else:
                self.status = "Critical"
                self.evaluation_status = "Below Critical Threshold"
                self.performance_grade = "F"

        # Track consecutive periods below target
        if self.status in ["Below Target", "Critical"]:
            prev_consecutive = getattr(self, '_prev_consecutive_below', 0)
            self.consecutive_periods_below = prev_consecutive + 1
            self.action_required = 1
        else:
            self.consecutive_periods_below = 0
            self.action_required = 0

        # Set recommended action based on status
        self.set_recommended_action()

    def set_recommended_action(self):
        """Set recommended action based on KPI status."""
        if self.status in ["On Track", "Exceeding"]:
            self.recommended_action = None
            return

        actions = {
            "Order Fulfillment Rate": "Review order processing workflow and ensure inventory accuracy",
            "On-Time Delivery Rate": "Evaluate shipping partners and processing times",
            "Return Rate": "Improve product descriptions and quality control",
            "Cancellation Rate": "Better inventory management and realistic shipping estimates",
            "Response Time": "Set up auto-responses and monitor message inbox regularly",
            "Customer Satisfaction": "Address negative feedback and improve service quality",
            "Complaint Rate": "Review customer complaints and address common issues",
            "Dispute Rate": "Improve communication and set clear expectations",
            "Refund Rate": "Enhance product accuracy and quality checks",
            "Shipment Tracking Rate": "Ensure tracking numbers are uploaded for all shipments",
            "Review Response Rate": "Respond to customer reviews promptly",
            "Listing Quality Score": "Improve product titles, descriptions, and images",
            "Inventory Accuracy": "Regular stock counts and real-time inventory updates",
            "Order Acceptance Rate": "Ensure sufficient stock and accept orders promptly",
            "Processing Time": "Optimize picking and packing workflow",
            "Packaging Quality": "Use appropriate packaging materials",
            "Shipping Label Accuracy": "Double-check shipping addresses before printing",
            "Communication Rating": "Respond clearly and professionally to buyer messages",
            "Product Accuracy": "Ensure products match listings exactly",
            "Policy Compliance": "Review and follow marketplace policies"
        }

        self.recommended_action = actions.get(
            self.kpi_type,
            "Review performance metrics and identify areas for improvement"
        )

        # Set action deadline if critical
        if self.status == "Critical" and not self.action_deadline:
            self.action_deadline = add_days(nowdate(), 7)
        elif self.status == "Below Target" and not self.action_deadline:
            self.action_deadline = add_days(nowdate(), 14)

    def check_and_send_alerts(self):
        """Check if alerts should be sent and send them."""
        if not self.alerts_enabled:
            return

        should_alert = False
        alert_type = None

        if self.status == "Critical" and self.alert_on_critical:
            should_alert = True
            alert_type = "Critical"
        elif self.status in ["Below Target", "At Risk"] and self.alert_on_warning:
            should_alert = True
            alert_type = "Warning"

        if should_alert:
            # Check if we've already sent an alert recently
            if self.last_alert_sent:
                hours_since_alert = (now_datetime() - self.last_alert_sent).total_seconds() / 3600
                if hours_since_alert < 24:  # Don't send more than once per day
                    return

            self.send_kpi_alert(alert_type)
            self.last_alert_sent = now_datetime()
            self.alert_count = cint(self.alert_count) + 1

    def send_kpi_alert(self, alert_type):
        """Send KPI alert notification."""
        # Get seller user
        seller_user = frappe.db.get_value("Seller Profile", self.seller, "user")

        # Build recipient list
        recipients = [seller_user] if seller_user else []
        if self.alert_recipients:
            recipients.extend([r.strip() for r in self.alert_recipients.split(",")])

        if not recipients:
            return

        subject = _("{0} Alert: {1} KPI for {2}").format(
            alert_type,
            self.kpi_type,
            self.seller
        )

        message = _("""
        <h3>KPI {alert_type} Alert</h3>
        <p>The following KPI requires your attention:</p>
        <table style="border-collapse: collapse; width: 100%;">
            <tr>
                <td style="padding: 8px; border: 1px solid #ddd;"><strong>KPI Type</strong></td>
                <td style="padding: 8px; border: 1px solid #ddd;">{kpi_type}</td>
            </tr>
            <tr>
                <td style="padding: 8px; border: 1px solid #ddd;"><strong>Current Value</strong></td>
                <td style="padding: 8px; border: 1px solid #ddd;">{actual_value}</td>
            </tr>
            <tr>
                <td style="padding: 8px; border: 1px solid #ddd;"><strong>Target Value</strong></td>
                <td style="padding: 8px; border: 1px solid #ddd;">{target_value}</td>
            </tr>
            <tr>
                <td style="padding: 8px; border: 1px solid #ddd;"><strong>Status</strong></td>
                <td style="padding: 8px; border: 1px solid #ddd;">{status}</td>
            </tr>
            <tr>
                <td style="padding: 8px; border: 1px solid #ddd;"><strong>Period</strong></td>
                <td style="padding: 8px; border: 1px solid #ddd;">{period_label}</td>
            </tr>
        </table>
        <h4>Recommended Action:</h4>
        <p>{recommended_action}</p>
        """).format(
            alert_type=alert_type,
            kpi_type=self.kpi_type,
            actual_value=self.actual_value,
            target_value=self.target_value,
            status=self.status,
            period_label=self.period_label or self.evaluation_period,
            recommended_action=self.recommended_action or "Review performance and take corrective action."
        )

        try:
            frappe.sendmail(
                recipients=recipients,
                subject=subject,
                message=message
            )
        except Exception as e:
            frappe.log_error(f"Failed to send KPI alert: {str(e)}")

    def calculate_from_data(self):
        """
        Calculate KPI value from actual order/review data.
        This is called by scheduled jobs or manually triggered.
        """
        if not self.auto_calculated:
            return

        calculation_methods = {
            "Order Fulfillment Rate": self._calculate_fulfillment_rate,
            "On-Time Delivery Rate": self._calculate_delivery_rate,
            "Return Rate": self._calculate_return_rate,
            "Cancellation Rate": self._calculate_cancellation_rate,
            "Response Time": self._calculate_response_time,
            "Customer Satisfaction": self._calculate_customer_satisfaction,
            "Complaint Rate": self._calculate_complaint_rate,
            "Dispute Rate": self._calculate_dispute_rate,
            "Refund Rate": self._calculate_refund_rate,
            "Shipment Tracking Rate": self._calculate_tracking_rate,
            "Review Response Rate": self._calculate_review_response_rate
        }

        calc_method = calculation_methods.get(self.kpi_type)
        if calc_method:
            result = calc_method()
            if result:
                self.actual_value = result.get("value", 0)
                self.sample_size = result.get("sample_size", 0)
                self.data_points_count = result.get("data_points", 0)
                self.breakdown_data = json.dumps(result.get("breakdown", {}))
                self.last_calculated_at = now_datetime()

                # Recalculate derived values
                self.calculate_derived_values()
                self.evaluate_performance()

    def _calculate_fulfillment_rate(self):
        """Calculate order fulfillment rate."""
        data = frappe.db.sql("""
            SELECT
                COUNT(*) as total_orders,
                SUM(CASE WHEN status IN ('Completed', 'Delivered') THEN 1 ELSE 0 END) as fulfilled
            FROM `tabSub Order`
            WHERE seller = %s
            AND creation BETWEEN %s AND %s
        """, (self.seller, self.period_start, self.period_end), as_dict=True)

        if not data or data[0].total_orders == 0:
            return {"value": 100, "sample_size": 0, "data_points": 0, "breakdown": {}}

        d = data[0]
        rate = (d.fulfilled / d.total_orders) * 100

        return {
            "value": round(rate, 2),
            "sample_size": d.total_orders,
            "data_points": d.total_orders,
            "breakdown": {
                "total_orders": d.total_orders,
                "fulfilled_orders": d.fulfilled,
                "unfulfilled_orders": d.total_orders - d.fulfilled
            }
        }

    def _calculate_delivery_rate(self):
        """Calculate on-time delivery rate."""
        data = frappe.db.sql("""
            SELECT
                COUNT(*) as total_delivered,
                SUM(CASE WHEN delivered_at <= expected_delivery_date THEN 1 ELSE 0 END) as on_time
            FROM `tabSub Order`
            WHERE seller = %s
            AND status = 'Delivered'
            AND delivered_at IS NOT NULL
            AND creation BETWEEN %s AND %s
        """, (self.seller, self.period_start, self.period_end), as_dict=True)

        if not data or data[0].total_delivered == 0:
            return {"value": 100, "sample_size": 0, "data_points": 0, "breakdown": {}}

        d = data[0]
        rate = (d.on_time / d.total_delivered) * 100

        return {
            "value": round(rate, 2),
            "sample_size": d.total_delivered,
            "data_points": d.total_delivered,
            "breakdown": {
                "total_delivered": d.total_delivered,
                "on_time": d.on_time,
                "late": d.total_delivered - d.on_time
            }
        }

    def _calculate_return_rate(self):
        """Calculate return rate."""
        data = frappe.db.sql("""
            SELECT
                COUNT(*) as total_orders,
                SUM(CASE WHEN return_status IN ('Return Requested', 'Returned', 'Refunded') THEN 1 ELSE 0 END) as returned
            FROM `tabSub Order`
            WHERE seller = %s
            AND creation BETWEEN %s AND %s
        """, (self.seller, self.period_start, self.period_end), as_dict=True)

        if not data or data[0].total_orders == 0:
            return {"value": 0, "sample_size": 0, "data_points": 0, "breakdown": {}}

        d = data[0]
        rate = (d.returned / d.total_orders) * 100

        return {
            "value": round(rate, 2),
            "sample_size": d.total_orders,
            "data_points": d.total_orders,
            "breakdown": {
                "total_orders": d.total_orders,
                "returned_orders": d.returned
            }
        }

    def _calculate_cancellation_rate(self):
        """Calculate order cancellation rate."""
        data = frappe.db.sql("""
            SELECT
                COUNT(*) as total_orders,
                SUM(CASE WHEN status = 'Cancelled' AND cancelled_by = 'Seller' THEN 1 ELSE 0 END) as cancelled
            FROM `tabSub Order`
            WHERE seller = %s
            AND creation BETWEEN %s AND %s
        """, (self.seller, self.period_start, self.period_end), as_dict=True)

        if not data or data[0].total_orders == 0:
            return {"value": 0, "sample_size": 0, "data_points": 0, "breakdown": {}}

        d = data[0]
        rate = (d.cancelled / d.total_orders) * 100

        return {
            "value": round(rate, 2),
            "sample_size": d.total_orders,
            "data_points": d.total_orders,
            "breakdown": {
                "total_orders": d.total_orders,
                "seller_cancelled": d.cancelled
            }
        }

    def _calculate_response_time(self):
        """Calculate average response time in hours."""
        # This would typically query a messaging/support system
        # For now, return seller profile's response time
        response_time = frappe.db.get_value(
            "Seller Profile", self.seller, "response_time_hours"
        ) or 24

        return {
            "value": round(flt(response_time), 1),
            "sample_size": 1,
            "data_points": 1,
            "breakdown": {"avg_response_hours": response_time}
        }

    def _calculate_customer_satisfaction(self):
        """Calculate customer satisfaction from reviews."""
        data = frappe.db.sql("""
            SELECT
                COUNT(*) as review_count,
                AVG(rating) as avg_rating
            FROM `tabReview`
            WHERE seller = %s
            AND status = 'Approved'
            AND creation BETWEEN %s AND %s
        """, (self.seller, self.period_start, self.period_end), as_dict=True)

        if not data or data[0].review_count == 0:
            return {"value": 5.0, "sample_size": 0, "data_points": 0, "breakdown": {}}

        d = data[0]
        return {
            "value": round(flt(d.avg_rating), 2),
            "sample_size": d.review_count,
            "data_points": d.review_count,
            "breakdown": {"average_rating": d.avg_rating, "review_count": d.review_count}
        }

    def _calculate_complaint_rate(self):
        """Calculate complaint rate."""
        # Count orders with complaints
        data = frappe.db.sql("""
            SELECT
                (SELECT COUNT(*) FROM `tabSub Order`
                 WHERE seller = %s AND creation BETWEEN %s AND %s) as total_orders,
                (SELECT COUNT(*) FROM `tabModeration Case`
                 WHERE target_seller = %s AND case_type = 'Complaint'
                 AND creation BETWEEN %s AND %s) as complaints
        """, (self.seller, self.period_start, self.period_end,
              self.seller, self.period_start, self.period_end), as_dict=True)

        if not data or data[0].total_orders == 0:
            return {"value": 0, "sample_size": 0, "data_points": 0, "breakdown": {}}

        d = data[0]
        rate = (d.complaints / d.total_orders) * 100

        return {
            "value": round(rate, 2),
            "sample_size": d.total_orders,
            "data_points": d.total_orders,
            "breakdown": {
                "total_orders": d.total_orders,
                "complaints": d.complaints
            }
        }

    def _calculate_dispute_rate(self):
        """Calculate dispute rate."""
        data = frappe.db.sql("""
            SELECT
                COUNT(*) as total_orders,
                SUM(CASE WHEN escrow_status = 'Disputed' THEN 1 ELSE 0 END) as disputed
            FROM `tabSub Order`
            WHERE seller = %s
            AND creation BETWEEN %s AND %s
        """, (self.seller, self.period_start, self.period_end), as_dict=True)

        if not data or data[0].total_orders == 0:
            return {"value": 0, "sample_size": 0, "data_points": 0, "breakdown": {}}

        d = data[0]
        rate = (d.disputed / d.total_orders) * 100

        return {
            "value": round(rate, 2),
            "sample_size": d.total_orders,
            "data_points": d.total_orders,
            "breakdown": {
                "total_orders": d.total_orders,
                "disputed_orders": d.disputed
            }
        }

    def _calculate_refund_rate(self):
        """Calculate refund rate."""
        data = frappe.db.sql("""
            SELECT
                COUNT(*) as total_orders,
                SUM(CASE WHEN refund_status IN ('Refund Requested', 'Refunded', 'Partially Refunded')
                    THEN 1 ELSE 0 END) as refunded
            FROM `tabSub Order`
            WHERE seller = %s
            AND creation BETWEEN %s AND %s
        """, (self.seller, self.period_start, self.period_end), as_dict=True)

        if not data or data[0].total_orders == 0:
            return {"value": 0, "sample_size": 0, "data_points": 0, "breakdown": {}}

        d = data[0]
        rate = (d.refunded / d.total_orders) * 100

        return {
            "value": round(rate, 2),
            "sample_size": d.total_orders,
            "data_points": d.total_orders,
            "breakdown": {
                "total_orders": d.total_orders,
                "refunded_orders": d.refunded
            }
        }

    def _calculate_tracking_rate(self):
        """Calculate shipment tracking rate."""
        data = frappe.db.sql("""
            SELECT
                COUNT(*) as total_shipments,
                SUM(CASE WHEN tracking_number IS NOT NULL AND tracking_number != ''
                    THEN 1 ELSE 0 END) as with_tracking
            FROM `tabMarketplace Shipment`
            WHERE seller = %s
            AND creation BETWEEN %s AND %s
        """, (self.seller, self.period_start, self.period_end), as_dict=True)

        if not data or data[0].total_shipments == 0:
            return {"value": 100, "sample_size": 0, "data_points": 0, "breakdown": {}}

        d = data[0]
        rate = (d.with_tracking / d.total_shipments) * 100

        return {
            "value": round(rate, 2),
            "sample_size": d.total_shipments,
            "data_points": d.total_shipments,
            "breakdown": {
                "total_shipments": d.total_shipments,
                "with_tracking": d.with_tracking
            }
        }

    def _calculate_review_response_rate(self):
        """Calculate review response rate."""
        data = frappe.db.sql("""
            SELECT
                COUNT(*) as total_reviews,
                SUM(CASE WHEN has_seller_response = 1 THEN 1 ELSE 0 END) as responded
            FROM `tabReview`
            WHERE seller = %s
            AND status = 'Approved'
            AND creation BETWEEN %s AND %s
        """, (self.seller, self.period_start, self.period_end), as_dict=True)

        if not data or data[0].total_reviews == 0:
            return {"value": 100, "sample_size": 0, "data_points": 0, "breakdown": {}}

        d = data[0]
        rate = (d.responded / d.total_reviews) * 100

        return {
            "value": round(rate, 2),
            "sample_size": d.total_reviews,
            "data_points": d.total_reviews,
            "breakdown": {
                "total_reviews": d.total_reviews,
                "responded": d.responded
            }
        }

    def update_peer_comparison(self):
        """Update peer comparison metrics."""
        # Get platform average for this KPI type
        platform_avg = frappe.db.sql("""
            SELECT AVG(actual_value) as avg_value
            FROM `tabSeller KPI`
            WHERE kpi_type = %s
            AND evaluation_period = %s
            AND status NOT IN ('Draft', 'Expired')
        """, (self.kpi_type, self.evaluation_period), as_dict=True)

        if platform_avg and platform_avg[0].avg_value:
            self.platform_average = round(flt(platform_avg[0].avg_value), 2)

        # Get rank among all sellers
        if self.target_type == "Higher is Better":
            rank_result = frappe.db.sql("""
                SELECT COUNT(*) as better_count
                FROM `tabSeller KPI`
                WHERE kpi_type = %s
                AND evaluation_period = %s
                AND actual_value > %s
                AND status NOT IN ('Draft', 'Expired')
            """, (self.kpi_type, self.evaluation_period, self.actual_value), as_dict=True)
        else:
            rank_result = frappe.db.sql("""
                SELECT COUNT(*) as better_count
                FROM `tabSeller KPI`
                WHERE kpi_type = %s
                AND evaluation_period = %s
                AND actual_value < %s
                AND status NOT IN ('Draft', 'Expired')
            """, (self.kpi_type, self.evaluation_period, self.actual_value), as_dict=True)

        if rank_result:
            self.peer_rank = rank_result[0].better_count + 1

        # Get total sellers for percentile
        total_sellers = frappe.db.count("Seller KPI", {
            "kpi_type": self.kpi_type,
            "evaluation_period": self.evaluation_period,
            "status": ["not in", ["Draft", "Expired"]]
        })

        if total_sellers > 0:
            sellers_below = total_sellers - self.peer_rank
            self.peer_percentile = round((sellers_below / total_sellers) * 100, 1)

        # Get tier average
        seller_tier = frappe.db.get_value("Seller Profile", self.seller, "seller_tier")
        if seller_tier:
            tier_avg = frappe.db.sql("""
                SELECT AVG(sk.actual_value) as avg_value
                FROM `tabSeller KPI` sk
                JOIN `tabSeller Profile` sp ON sk.seller = sp.name
                WHERE sk.kpi_type = %s
                AND sk.evaluation_period = %s
                AND sp.seller_tier = %s
                AND sk.status NOT IN ('Draft', 'Expired')
            """, (self.kpi_type, self.evaluation_period, seller_tier), as_dict=True)

            if tier_avg and tier_avg[0].avg_value:
                self.tier_average = round(flt(tier_avg[0].avg_value), 2)

    def record_action(self, action_description, user=None):
        """Record an action taken for this KPI."""
        self.action_taken = action_description
        self.action_taken_at = now_datetime()
        self.action_taken_by = user or frappe.session.user
        self.save()

    def get_summary(self):
        """Get a summary for display."""
        return {
            "name": self.name,
            "seller": self.seller,
            "kpi_type": self.kpi_type,
            "kpi_category": self.kpi_category,
            "period_label": self.period_label,
            "evaluation_period": self.evaluation_period,
            "status": self.status,
            "actual_value": self.actual_value,
            "target_value": self.target_value,
            "percentage_of_target": self.percentage_of_target,
            "value_trend": self.value_trend,
            "performance_grade": self.performance_grade,
            "action_required": self.action_required,
            "recommended_action": self.recommended_action
        }

    def get_detailed_report(self):
        """Get a detailed report for this KPI."""
        return {
            "basic": {
                "name": self.name,
                "seller": self.seller,
                "kpi_type": self.kpi_type,
                "kpi_category": self.kpi_category,
                "status": self.status
            },
            "period": {
                "type": self.period_type,
                "start": self.period_start,
                "end": self.period_end,
                "label": self.period_label,
                "evaluation_period": self.evaluation_period
            },
            "targets": {
                "target_value": self.target_value,
                "target_type": self.target_type,
                "minimum_threshold": self.minimum_threshold,
                "maximum_threshold": self.maximum_threshold,
                "warning_threshold": self.warning_threshold,
                "critical_threshold": self.critical_threshold
            },
            "values": {
                "actual_value": self.actual_value,
                "previous_value": self.previous_value,
                "value_change": self.value_change,
                "value_trend": self.value_trend,
                "percentage_of_target": self.percentage_of_target,
                "deviation_from_target": self.deviation_from_target
            },
            "evaluation": {
                "evaluation_status": self.evaluation_status,
                "performance_grade": self.performance_grade,
                "score_contribution": self.score_contribution,
                "days_below_target": self.days_below_target,
                "consecutive_periods_below": self.consecutive_periods_below
            },
            "comparison": {
                "peer_average": self.peer_average,
                "peer_rank": self.peer_rank,
                "peer_percentile": self.peer_percentile,
                "tier_average": self.tier_average,
                "platform_average": self.platform_average
            },
            "statistics": {
                "sample_size": self.sample_size,
                "data_points_count": self.data_points_count,
                "confidence_level": self.confidence_level,
                "standard_deviation": self.standard_deviation,
                "variance": self.variance
            },
            "breakdown": json.loads(self.breakdown_data) if self.breakdown_data else {}
        }


# API Endpoints

@frappe.whitelist()
def create_seller_kpi(seller, kpi_type, period_type="Monthly", target_value=None, period_start=None, period_end=None):
    """
    Create a new KPI record for a seller.

    Args:
        seller: Seller profile name
        kpi_type: Type of KPI
        period_type: Evaluation period type
        target_value: Optional custom target value
        period_start: Start of evaluation period
        period_end: End of evaluation period

    Returns:
        dict: Created KPI summary
    """
    if not frappe.db.exists("Seller Profile", seller):
        frappe.throw(_("Seller not found"))

    # Calculate period dates if not provided
    today = getdate(nowdate())
    if not period_start:
        if period_type == "Daily":
            period_start = today
            period_end = today
        elif period_type == "Weekly":
            period_start = get_first_day_of_week(today)
            period_end = add_days(period_start, 6)
        elif period_type == "Monthly":
            period_start = get_first_day(today)
            period_end = get_last_day(today)
        elif period_type == "Quarterly":
            quarter_start_month = ((today.month - 1) // 3) * 3 + 1
            period_start = today.replace(month=quarter_start_month, day=1)
            period_end = add_months(period_start, 3)
            period_end = add_days(period_end, -1)
        elif period_type == "Annually":
            period_start = today.replace(month=1, day=1)
            period_end = today.replace(month=12, day=31)
        else:
            period_start = get_first_day(today)
            period_end = get_last_day(today)

    if not period_end:
        period_end = period_start

    # Get tenant
    tenant = frappe.db.get_value("Seller Profile", seller, "tenant")

    # Create KPI record
    kpi = frappe.get_doc({
        "doctype": "Seller KPI",
        "seller": seller,
        "kpi_type": kpi_type,
        "period_type": period_type,
        "period_start": period_start,
        "period_end": period_end,
        "tenant": tenant,
        "status": "Active",
        "is_current_period": 1,
        "target_value": flt(target_value) if target_value else None
    })

    kpi.insert()

    # Calculate from data if auto-calculated
    if kpi.auto_calculated:
        kpi.calculate_from_data()
        kpi.save()

    return kpi.get_summary()


@frappe.whitelist()
def calculate_kpi(kpi_name):
    """
    Calculate/recalculate KPI value from data.

    Args:
        kpi_name: Seller KPI name

    Returns:
        dict: Updated KPI summary
    """
    if not frappe.db.exists("Seller KPI", kpi_name):
        frappe.throw(_("KPI not found"))

    kpi = frappe.get_doc("Seller KPI", kpi_name)
    kpi.calculate_from_data()
    kpi.update_peer_comparison()
    kpi.save()

    return kpi.get_summary()


@frappe.whitelist()
def get_seller_kpis(seller, period=None, kpi_type=None, category=None):
    """
    Get all KPIs for a seller.

    Args:
        seller: Seller profile name
        period: Optional period filter
        kpi_type: Optional KPI type filter
        category: Optional category filter

    Returns:
        list: KPI summaries
    """
    if not frappe.db.exists("Seller Profile", seller):
        frappe.throw(_("Seller not found"))

    filters = {
        "seller": seller,
        "status": ["not in", ["Draft", "Expired"]]
    }

    if period:
        filters["evaluation_period"] = period
    if kpi_type:
        filters["kpi_type"] = kpi_type
    if category:
        filters["kpi_category"] = category

    kpis = frappe.get_all("Seller KPI",
        filters=filters,
        fields=[
            "name", "kpi_type", "kpi_category", "status",
            "actual_value", "target_value", "percentage_of_target",
            "value_trend", "performance_grade", "period_label",
            "evaluation_period", "action_required"
        ],
        order_by="kpi_category, kpi_type"
    )

    return kpis


@frappe.whitelist()
def get_kpi_history(seller, kpi_type, limit=12):
    """
    Get KPI history for trend analysis.

    Args:
        seller: Seller profile name
        kpi_type: Type of KPI
        limit: Maximum records to return

    Returns:
        list: Historical KPI values
    """
    if not frappe.db.exists("Seller Profile", seller):
        frappe.throw(_("Seller not found"))

    history = frappe.get_all("Seller KPI",
        filters={
            "seller": seller,
            "kpi_type": kpi_type,
            "status": ["not in", ["Draft", "Expired"]]
        },
        fields=[
            "name", "evaluation_period", "period_label",
            "actual_value", "target_value", "status",
            "value_change", "percentage_of_target",
            "performance_grade", "peer_percentile"
        ],
        order_by="period_end desc",
        limit=cint(limit)
    )

    return history


@frappe.whitelist()
def get_kpi_dashboard(seller):
    """
    Get KPI dashboard data for a seller.

    Args:
        seller: Seller profile name

    Returns:
        dict: Dashboard data with current KPIs, trends, alerts
    """
    if not frappe.db.exists("Seller Profile", seller):
        frappe.throw(_("Seller not found"))

    # Get current period KPIs
    current_kpis = frappe.get_all("Seller KPI",
        filters={
            "seller": seller,
            "is_current_period": 1,
            "status": ["not in", ["Draft", "Expired"]]
        },
        fields=[
            "name", "kpi_type", "kpi_category", "status",
            "actual_value", "target_value", "percentage_of_target",
            "value_trend", "performance_grade", "action_required",
            "recommended_action", "peer_percentile", "score_contribution"
        ]
    )

    # Group by category
    by_category = {}
    for kpi in current_kpis:
        category = kpi.kpi_category
        if category not in by_category:
            by_category[category] = []
        by_category[category].append(kpi)

    # Count statuses
    status_counts = {
        "exceeding": 0,
        "on_track": 0,
        "at_risk": 0,
        "below_target": 0,
        "critical": 0
    }

    for kpi in current_kpis:
        if kpi.status == "Exceeding":
            status_counts["exceeding"] += 1
        elif kpi.status == "On Track":
            status_counts["on_track"] += 1
        elif kpi.status == "At Risk":
            status_counts["at_risk"] += 1
        elif kpi.status == "Below Target":
            status_counts["below_target"] += 1
        elif kpi.status == "Critical":
            status_counts["critical"] += 1

    # Get KPIs requiring action
    action_required = [k for k in current_kpis if k.action_required]

    # Calculate overall KPI health score
    if current_kpis:
        avg_score = sum(flt(k.score_contribution) for k in current_kpis) / len(current_kpis)
    else:
        avg_score = 100

    return {
        "seller": seller,
        "total_kpis": len(current_kpis),
        "health_score": round(avg_score, 2),
        "status_distribution": status_counts,
        "by_category": by_category,
        "action_required": action_required,
        "action_required_count": len(action_required)
    }


@frappe.whitelist()
def bulk_calculate_kpis(seller=None, period_type="Monthly", kpi_types=None):
    """
    Bulk calculate KPIs for sellers.

    Args:
        seller: Optional specific seller (if None, calculates for all active sellers)
        period_type: Period type for calculation
        kpi_types: Optional JSON list of KPI types to calculate

    Returns:
        dict: Calculation results summary
    """
    import json as json_module

    if kpi_types and isinstance(kpi_types, str):
        kpi_types = json_module.loads(kpi_types)

    if not kpi_types:
        kpi_types = [
            "Order Fulfillment Rate",
            "On-Time Delivery Rate",
            "Return Rate",
            "Cancellation Rate",
            "Customer Satisfaction",
            "Response Time"
        ]

    # Get sellers
    if seller:
        sellers = [seller]
    else:
        sellers = frappe.get_all("Seller Profile",
            filters={"status": "Active"},
            pluck="name"
        )

    results = {
        "total_sellers": len(sellers),
        "total_kpis": 0,
        "created": 0,
        "updated": 0,
        "errors": []
    }

    for s in sellers:
        for kpi_type in kpi_types:
            try:
                # Check if KPI exists for current period
                today = getdate(nowdate())
                if period_type == "Monthly":
                    period_start = get_first_day(today)
                    period_end = get_last_day(today)
                    period = today.strftime("%Y-%m")
                elif period_type == "Weekly":
                    period_start = get_first_day_of_week(today)
                    period_end = add_days(period_start, 6)
                    period = f"{today.year}-W{today.isocalendar()[1]:02d}"
                else:
                    period_start = today
                    period_end = today
                    period = today.strftime("%Y-%m-%d")

                existing = frappe.db.exists("Seller KPI", {
                    "seller": s,
                    "kpi_type": kpi_type,
                    "evaluation_period": period
                })

                if existing:
                    # Update existing
                    kpi = frappe.get_doc("Seller KPI", existing)
                    kpi.calculate_from_data()
                    kpi.update_peer_comparison()
                    kpi.save()
                    results["updated"] += 1
                else:
                    # Create new
                    create_seller_kpi(s, kpi_type, period_type)
                    results["created"] += 1

                results["total_kpis"] += 1

            except Exception as e:
                results["errors"].append({
                    "seller": s,
                    "kpi_type": kpi_type,
                    "error": str(e)
                })

    return results


@frappe.whitelist()
def get_kpi_statistics(kpi_type, period=None, tenant=None):
    """
    Get platform-wide statistics for a KPI type.

    Args:
        kpi_type: Type of KPI
        period: Optional period filter
        tenant: Optional tenant filter

    Returns:
        dict: Statistics including distribution, averages, percentiles
    """
    filters = {"kpi_type": kpi_type, "status": ["not in", ["Draft", "Expired"]]}
    if period:
        filters["evaluation_period"] = period
    if tenant:
        filters["tenant"] = tenant

    # Get all KPIs
    kpis = frappe.get_all("Seller KPI",
        filters=filters,
        fields=["actual_value", "status", "performance_grade"]
    )

    if not kpis:
        return {"message": "No KPI data found"}

    values = [flt(k.actual_value) for k in kpis]

    # Calculate statistics
    avg_value = sum(values) / len(values)
    min_value = min(values)
    max_value = max(values)

    # Standard deviation
    variance = sum((v - avg_value) ** 2 for v in values) / len(values)
    std_dev = math.sqrt(variance)

    # Percentiles
    sorted_values = sorted(values)
    n = len(sorted_values)
    p25 = sorted_values[int(n * 0.25)] if n > 3 else min_value
    p50 = sorted_values[int(n * 0.50)] if n > 1 else avg_value
    p75 = sorted_values[int(n * 0.75)] if n > 3 else max_value

    # Status distribution
    status_dist = {}
    for k in kpis:
        status = k.status
        status_dist[status] = status_dist.get(status, 0) + 1

    # Grade distribution
    grade_dist = {}
    for k in kpis:
        grade = k.performance_grade
        grade_dist[grade] = grade_dist.get(grade, 0) + 1

    return {
        "kpi_type": kpi_type,
        "period": period,
        "total_sellers": len(kpis),
        "average": round(avg_value, 2),
        "minimum": round(min_value, 2),
        "maximum": round(max_value, 2),
        "std_deviation": round(std_dev, 2),
        "percentiles": {
            "25th": round(p25, 2),
            "50th": round(p50, 2),
            "75th": round(p75, 2)
        },
        "status_distribution": status_dist,
        "grade_distribution": grade_dist
    }


@frappe.whitelist()
def record_kpi_action(kpi_name, action_description):
    """
    Record an action taken for a KPI.

    Args:
        kpi_name: Seller KPI name
        action_description: Description of action taken

    Returns:
        dict: Result
    """
    if not frappe.db.exists("Seller KPI", kpi_name):
        frappe.throw(_("KPI not found"))

    kpi = frappe.get_doc("Seller KPI", kpi_name)
    kpi.record_action(action_description)

    return {
        "status": "success",
        "message": _("Action recorded successfully"),
        "kpi": kpi_name
    }


@frappe.whitelist()
def get_seller_kpi_summary(seller):
    """
    Get a quick summary of seller's KPI performance.

    Args:
        seller: Seller profile name

    Returns:
        dict: Summary with key metrics
    """
    if not frappe.db.exists("Seller Profile", seller):
        frappe.throw(_("Seller not found"))

    # Get current period KPIs
    kpis = frappe.get_all("Seller KPI",
        filters={
            "seller": seller,
            "is_current_period": 1,
            "status": ["not in", ["Draft", "Expired"]]
        },
        fields=["kpi_type", "actual_value", "target_value", "status", "score_contribution"]
    )

    # Key metrics
    key_metrics = {}
    for kpi in kpis:
        key_metrics[kpi.kpi_type] = {
            "value": kpi.actual_value,
            "target": kpi.target_value,
            "status": kpi.status
        }

    # Overall health
    if kpis:
        health_score = sum(flt(k.score_contribution) for k in kpis) / len(kpis)
        critical_count = sum(1 for k in kpis if k.status == "Critical")
        at_risk_count = sum(1 for k in kpis if k.status in ["At Risk", "Below Target"])
    else:
        health_score = 100
        critical_count = 0
        at_risk_count = 0

    # Get seller's current tier
    seller_tier = frappe.db.get_value("Seller Profile", seller, "seller_tier")

    return {
        "seller": seller,
        "tier": seller_tier,
        "health_score": round(health_score, 2),
        "total_kpis": len(kpis),
        "critical_kpis": critical_count,
        "at_risk_kpis": at_risk_count,
        "key_metrics": key_metrics
    }

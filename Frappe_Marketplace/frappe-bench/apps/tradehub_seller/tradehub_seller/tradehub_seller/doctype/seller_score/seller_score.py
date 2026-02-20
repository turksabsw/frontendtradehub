# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt, getdate, now_datetime, nowdate, add_days, add_months
from datetime import datetime, timedelta


class SellerScore(Document):
    """
    Seller Score DocType for tracking seller performance scores.

    Records individual score calculations with:
    - Component scores (fulfillment, delivery, quality, service, compliance, engagement)
    - Performance metrics (orders, reviews, rates)
    - Penalties and bonuses
    - Historical comparison and trend analysis
    """

    def before_insert(self):
        """Set default values before inserting a new score record."""
        if not self.created_by:
            self.created_by = frappe.session.user
        self.created_at = now_datetime()

        if not self.calculation_date:
            self.calculation_date = nowdate()

        # Get tenant from seller if not set
        if not self.tenant and self.seller:
            self.tenant = frappe.db.get_value("Seller Profile", self.seller, "tenant")

        # Get previous score for comparison
        self.set_previous_score()

        # Get tier at calculation time
        if self.seller:
            self.tier_at_calculation = frappe.db.get_value("Seller Profile", self.seller, "seller_tier")

    def validate(self):
        """Validate score data before saving."""
        self.validate_seller()
        self.validate_scores()
        self.validate_weights()
        self.validate_metrics()
        self.calculate_overall_score()
        self.calculate_score_change()
        self.determine_trend()

    def on_update(self):
        """Actions after score is updated."""
        if self.status == "Finalized":
            self.update_seller_score()

    def on_trash(self):
        """Prevent deletion of finalized scores."""
        if self.status == "Finalized":
            frappe.throw(_("Cannot delete finalized score records"))

    def validate_seller(self):
        """Validate seller exists and is valid."""
        if not self.seller:
            frappe.throw(_("Seller is required"))

        if not frappe.db.exists("Seller Profile", self.seller):
            frappe.throw(_("Invalid seller"))

    def validate_scores(self):
        """Validate all score values are within 0-100 range."""
        score_fields = [
            "overall_score", "fulfillment_score", "delivery_score",
            "quality_score", "service_score", "compliance_score", "engagement_score"
        ]

        for field in score_fields:
            value = flt(getattr(self, field, 0))
            if value < 0 or value > 100:
                frappe.throw(_("{0} must be between 0 and 100").format(
                    field.replace("_", " ").title()
                ))

    def validate_weights(self):
        """Validate score weights sum to 100%."""
        total_weight = (
            flt(self.fulfillment_weight) +
            flt(self.delivery_weight) +
            flt(self.quality_weight) +
            flt(self.service_weight) +
            flt(self.compliance_weight) +
            flt(self.engagement_weight)
        )

        if abs(total_weight - 100) > 0.1:
            frappe.msgprint(
                _("Score weights should sum to 100% (current: {0}%)").format(round(total_weight, 1)),
                indicator="orange"
            )

    def validate_metrics(self):
        """Validate metric values are non-negative."""
        percentage_fields = [
            "fulfillment_rate", "on_time_rate", "return_rate",
            "cancellation_rate", "complaint_rate", "conversion_rate",
            "repeat_customer_rate"
        ]

        for field in percentage_fields:
            value = flt(getattr(self, field, 0))
            if value < 0 or value > 100:
                frappe.throw(_("{0} must be between 0 and 100").format(
                    field.replace("_", " ").title()
                ))

        # Validate rating is 1-5
        if flt(self.average_rating) < 0 or flt(self.average_rating) > 5:
            frappe.throw(_("Average rating must be between 0 and 5"))

        # Validate non-negative integers
        int_fields = [
            "orders_evaluated", "reviews_evaluated", "rating_count",
            "positive_rating_count", "negative_rating_count", "neutral_rating_count",
            "period_sales_count", "policy_violations", "late_shipments",
            "cancelled_orders", "disputed_orders"
        ]

        for field in int_fields:
            if cint(getattr(self, field, 0)) < 0:
                frappe.throw(_("{0} cannot be negative").format(
                    field.replace("_", " ").title()
                ))

    def set_previous_score(self):
        """Get the previous score for comparison."""
        if not self.seller:
            return

        # Find the most recent finalized score for this seller
        prev_score = frappe.db.get_value(
            "Seller Score",
            {
                "seller": self.seller,
                "status": "Finalized",
                "name": ["!=", self.name or ""],
                "calculation_date": ["<", self.calculation_date or nowdate()]
            },
            ["overall_score", "average_rating"],
            order_by="calculation_date desc"
        )

        if prev_score:
            self.previous_score = flt(prev_score[0])
            # Store for rating change calculation
            self._prev_rating = flt(prev_score[1])

    def calculate_overall_score(self):
        """Calculate the weighted overall score from components."""
        # Get component scores and weights
        components = [
            (flt(self.fulfillment_score), flt(self.fulfillment_weight)),
            (flt(self.delivery_score), flt(self.delivery_weight)),
            (flt(self.quality_score), flt(self.quality_weight)),
            (flt(self.service_score), flt(self.service_weight)),
            (flt(self.compliance_score), flt(self.compliance_weight)),
            (flt(self.engagement_score), flt(self.engagement_weight))
        ]

        total_weight = sum(w for s, w in components)
        if total_weight == 0:
            total_weight = 100  # Default to equal weighting

        weighted_sum = sum(s * w for s, w in components)
        base_score = weighted_sum / total_weight

        # Apply bonuses and penalties
        final_score = base_score + flt(self.bonus_points) - flt(self.penalty_deduction)

        # Clamp to 0-100 range
        self.overall_score = max(0, min(100, round(final_score, 2)))

    def calculate_score_change(self):
        """Calculate the change from the previous score."""
        self.score_change = round(flt(self.overall_score) - flt(self.previous_score), 2)

        # Calculate rating change if we have previous rating
        if hasattr(self, '_prev_rating'):
            self.rating_change = round(flt(self.average_rating) - flt(self._prev_rating), 2)

    def determine_trend(self):
        """Determine score trend based on recent history."""
        if not self.seller:
            self.score_trend = "Stable"
            return

        # Get last 5 scores
        recent_scores = frappe.db.sql("""
            SELECT overall_score
            FROM `tabSeller Score`
            WHERE seller = %s
            AND status = 'Finalized'
            AND name != %s
            ORDER BY calculation_date DESC
            LIMIT 5
        """, (self.seller, self.name or ""), as_dict=True)

        if len(recent_scores) < 2:
            self.score_trend = "Stable"
            return

        scores = [s.overall_score for s in recent_scores]
        avg_change = (scores[0] - scores[-1]) / len(scores)

        if avg_change > 1:
            self.score_trend = "Rising"
        elif avg_change < -1:
            self.score_trend = "Declining"
        else:
            self.score_trend = "Stable"

    def calculate_percentile_rank(self):
        """Calculate seller's percentile rank among all sellers."""
        if not self.seller:
            return

        # Count sellers with lower scores
        lower_count = frappe.db.count("Seller Profile",
            {"seller_score": ["<", self.overall_score], "status": "Active"}
        )

        total_count = frappe.db.count("Seller Profile", {"status": "Active"})

        if total_count > 0:
            self.percentile_rank = round((lower_count / total_count) * 100, 1)
        else:
            self.percentile_rank = 50

    def finalize(self, user=None):
        """Finalize the score record."""
        if self.status == "Finalized":
            frappe.throw(_("Score is already finalized"))

        self.status = "Finalized"
        self.finalized_at = now_datetime()
        self.finalized_by = user or frappe.session.user
        self.save()

        # Update seller's current score
        self.update_seller_score()

        frappe.msgprint(_("Score finalized successfully"))

    def update_seller_score(self):
        """Update the seller's current score in Seller Profile."""
        if self.status != "Finalized":
            return

        # Only update if this is the most recent finalized score
        latest_score = frappe.db.get_value(
            "Seller Score",
            {
                "seller": self.seller,
                "status": "Finalized"
            },
            "name",
            order_by="calculation_date desc"
        )

        if latest_score == self.name:
            frappe.db.set_value("Seller Profile", self.seller, {
                "seller_score": self.overall_score,
                "average_rating": self.average_rating,
                "total_reviews": self.rating_count,
                "order_fulfillment_rate": self.fulfillment_rate,
                "on_time_delivery_rate": self.on_time_rate,
                "return_rate": self.return_rate,
                "cancellation_rate": self.cancellation_rate,
                "complaint_rate": self.complaint_rate,
                "response_time_hours": self.response_time_avg,
                "positive_feedback_rate": (flt(self.positive_rating_count) / flt(self.rating_count) * 100) if flt(self.rating_count) > 0 else 100
            })

    def appeal(self, reason):
        """
        Submit an appeal for this score.

        Args:
            reason: Reason for appeal
        """
        if self.status != "Finalized":
            frappe.throw(_("Only finalized scores can be appealed"))

        self.status = "Appealed"
        self.calculation_notes = (self.calculation_notes or "") + f"\n\nAppeal submitted: {reason}"
        self.save()

        frappe.msgprint(_("Appeal submitted successfully"))

    def revise(self, adjustments, reason, user=None):
        """
        Revise the score with manual adjustments.

        Args:
            adjustments: Dict of field adjustments
            reason: Reason for revision
            user: User making the revision
        """
        allowed_adjustments = [
            "fulfillment_score", "delivery_score", "quality_score",
            "service_score", "compliance_score", "engagement_score",
            "bonus_points", "penalty_deduction"
        ]

        for field, value in adjustments.items():
            if field in allowed_adjustments:
                setattr(self, field, flt(value))

        self.manual_adjustments = reason
        self.adjusted_by = user or frappe.session.user
        self.status = "Revised"

        # Recalculate overall score
        self.calculate_overall_score()
        self.calculate_score_change()
        self.save()

        # Update seller if this was finalized
        if self.was_finalized:
            self.update_seller_score()

        frappe.msgprint(_("Score revised successfully"))

    def get_score_breakdown(self):
        """Get a detailed breakdown of the score calculation."""
        return {
            "overall_score": self.overall_score,
            "previous_score": self.previous_score,
            "score_change": self.score_change,
            "score_trend": self.score_trend,
            "percentile_rank": self.percentile_rank,
            "components": {
                "fulfillment": {
                    "score": self.fulfillment_score,
                    "weight": self.fulfillment_weight,
                    "weighted": round(flt(self.fulfillment_score) * flt(self.fulfillment_weight) / 100, 2)
                },
                "delivery": {
                    "score": self.delivery_score,
                    "weight": self.delivery_weight,
                    "weighted": round(flt(self.delivery_score) * flt(self.delivery_weight) / 100, 2)
                },
                "quality": {
                    "score": self.quality_score,
                    "weight": self.quality_weight,
                    "weighted": round(flt(self.quality_score) * flt(self.quality_weight) / 100, 2)
                },
                "service": {
                    "score": self.service_score,
                    "weight": self.service_weight,
                    "weighted": round(flt(self.service_score) * flt(self.service_weight) / 100, 2)
                },
                "compliance": {
                    "score": self.compliance_score,
                    "weight": self.compliance_weight,
                    "weighted": round(flt(self.compliance_score) * flt(self.compliance_weight) / 100, 2)
                },
                "engagement": {
                    "score": self.engagement_score,
                    "weight": self.engagement_weight,
                    "weighted": round(flt(self.engagement_score) * flt(self.engagement_weight) / 100, 2)
                }
            },
            "adjustments": {
                "bonus_points": self.bonus_points,
                "penalty_deduction": self.penalty_deduction,
                "net_adjustment": flt(self.bonus_points) - flt(self.penalty_deduction)
            },
            "metrics": {
                "orders_evaluated": self.orders_evaluated,
                "reviews_evaluated": self.reviews_evaluated,
                "fulfillment_rate": self.fulfillment_rate,
                "on_time_rate": self.on_time_rate,
                "return_rate": self.return_rate,
                "cancellation_rate": self.cancellation_rate,
                "complaint_rate": self.complaint_rate,
                "response_time_avg": self.response_time_avg
            },
            "ratings": {
                "average_rating": self.average_rating,
                "rating_count": self.rating_count,
                "positive": self.positive_rating_count,
                "neutral": self.neutral_rating_count,
                "negative": self.negative_rating_count
            }
        }

    def get_summary(self):
        """Get a summary for display."""
        return {
            "name": self.name,
            "seller": self.seller,
            "score_type": self.score_type,
            "score_period": self.score_period,
            "calculation_date": self.calculation_date,
            "status": self.status,
            "overall_score": self.overall_score,
            "score_change": self.score_change,
            "score_trend": self.score_trend,
            "average_rating": self.average_rating,
            "tier_at_calculation": self.tier_at_calculation
        }


# Score Calculation Functions
def calculate_fulfillment_score(seller, start_date=None, end_date=None):
    """
    Calculate fulfillment score for a seller.

    Args:
        seller: Seller profile name
        start_date: Start of evaluation period
        end_date: End of evaluation period

    Returns:
        dict: Score and metrics
    """
    # Use parameterized queries to prevent SQL injection
    params = {"seller": seller}
    date_filter = ""
    if start_date and end_date:
        date_filter = "AND so.creation BETWEEN %(start_date)s AND %(end_date)s"
        params["start_date"] = start_date
        params["end_date"] = end_date

    # Get order fulfillment metrics
    metrics = frappe.db.sql("""
        SELECT
            COUNT(*) as total_orders,
            SUM(CASE WHEN so.status = 'Completed' THEN 1 ELSE 0 END) as fulfilled_orders,
            SUM(CASE WHEN so.status = 'Cancelled' AND so.cancelled_by = 'Seller' THEN 1 ELSE 0 END) as seller_cancelled
        FROM `tabSub Order` so
        WHERE so.seller = %(seller)s
        {date_filter}
    """.format(date_filter=date_filter), params, as_dict=True)

    if not metrics or metrics[0].total_orders == 0:
        return {"score": 100, "fulfillment_rate": 100, "orders": 0}

    m = metrics[0]
    fulfillment_rate = (m.fulfilled_orders / m.total_orders) * 100
    cancellation_penalty = (m.seller_cancelled / m.total_orders) * 20  # 20 point penalty for cancellation rate

    score = max(0, fulfillment_rate - cancellation_penalty)

    return {
        "score": round(score, 2),
        "fulfillment_rate": round(fulfillment_rate, 2),
        "orders": m.total_orders,
        "fulfilled": m.fulfilled_orders,
        "cancelled": m.seller_cancelled
    }


def calculate_delivery_score(seller, start_date=None, end_date=None):
    """
    Calculate delivery score for a seller.

    Args:
        seller: Seller profile name
        start_date: Start of evaluation period
        end_date: End of evaluation period

    Returns:
        dict: Score and metrics
    """
    # Use parameterized queries to prevent SQL injection (if SQL query is added later)
    date_filter = ""
    if start_date and end_date:
        date_filter = "AND sh.creation BETWEEN %(start_date)s AND %(end_date)s"
        # params would include: {"start_date": start_date, "end_date": end_date}

    # This is a placeholder - actual implementation would check shipment records
    # For now, return seller profile metrics
    seller_doc = frappe.get_doc("Seller Profile", seller)

    return {
        "score": round(flt(seller_doc.on_time_delivery_rate), 2),
        "on_time_rate": seller_doc.on_time_delivery_rate,
        "late_shipments": 0
    }


def calculate_quality_score(seller, start_date=None, end_date=None):
    """
    Calculate quality score based on returns and complaints.

    Args:
        seller: Seller profile name
        start_date: Start of evaluation period
        end_date: End of evaluation period

    Returns:
        dict: Score and metrics
    """
    seller_doc = frappe.get_doc("Seller Profile", seller)

    # Quality is inverse of return rate and complaint rate
    return_penalty = flt(seller_doc.return_rate) * 0.5  # 50% weight to returns
    complaint_penalty = flt(seller_doc.complaint_rate) * 0.5  # 50% weight to complaints

    score = max(0, 100 - return_penalty - complaint_penalty)

    return {
        "score": round(score, 2),
        "return_rate": seller_doc.return_rate,
        "complaint_rate": seller_doc.complaint_rate
    }


def calculate_service_score(seller, start_date=None, end_date=None):
    """
    Calculate service score based on ratings and response time.

    Args:
        seller: Seller profile name
        start_date: Start of evaluation period
        end_date: End of evaluation period

    Returns:
        dict: Score and metrics
    """
    seller_doc = frappe.get_doc("Seller Profile", seller)

    # Rating score (convert 1-5 scale to 0-100)
    rating_score = (flt(seller_doc.average_rating) / 5) * 100

    # Response time score (24hrs = 100, 48hrs = 50, >72hrs = 0)
    response_hours = flt(seller_doc.response_time_hours)
    if response_hours <= 24:
        response_score = 100
    elif response_hours <= 48:
        response_score = 100 - ((response_hours - 24) * 2.08)  # Linear decay
    elif response_hours <= 72:
        response_score = 50 - ((response_hours - 48) * 2.08)
    else:
        response_score = 0

    # Weighted average (60% rating, 40% response)
    score = (rating_score * 0.6) + (response_score * 0.4)

    return {
        "score": round(score, 2),
        "average_rating": seller_doc.average_rating,
        "response_time": response_hours,
        "rating_score": round(rating_score, 2),
        "response_score": round(response_score, 2)
    }


def calculate_compliance_score(seller, start_date=None, end_date=None):
    """
    Calculate compliance score based on policy violations.

    Args:
        seller: Seller profile name
        start_date: Start of evaluation period
        end_date: End of evaluation period

    Returns:
        dict: Score and metrics
    """
    # Count policy violations (Account Actions)
    violations = frappe.db.count("Account Action", {
        "target_doctype": "Seller Profile",
        "target_name": seller,
        "status": ["in", ["Active", "Completed"]]
    })

    # Each violation deducts 10 points
    penalty = min(100, violations * 10)
    score = 100 - penalty

    return {
        "score": round(score, 2),
        "violations": violations,
        "penalty": penalty
    }


def calculate_engagement_score(seller, start_date=None, end_date=None):
    """
    Calculate engagement score based on seller activity.

    Args:
        seller: Seller profile name
        start_date: Start of evaluation period
        end_date: End of evaluation period

    Returns:
        dict: Score and metrics
    """
    seller_doc = frappe.get_doc("Seller Profile", seller)

    # Check last active time
    engagement_score = 100

    if seller_doc.last_active_at:
        days_inactive = (datetime.now() - seller_doc.last_active_at).days
        if days_inactive > 7:
            engagement_score -= min(50, (days_inactive - 7) * 2)

    # Check vacation mode
    if cint(seller_doc.vacation_mode):
        engagement_score -= 20

    return {
        "score": max(0, round(engagement_score, 2)),
        "last_active": seller_doc.last_active_at,
        "vacation_mode": seller_doc.vacation_mode
    }


# API Endpoints
@frappe.whitelist()
def calculate_seller_score(seller, score_type="Periodic", auto_finalize=False):
    """
    Calculate a new score for a seller.

    Args:
        seller: Seller profile name
        score_type: Type of score calculation
        auto_finalize: Automatically finalize the score

    Returns:
        dict: Score calculation result
    """
    if not frappe.db.exists("Seller Profile", seller):
        frappe.throw(_("Seller not found"))

    seller_doc = frappe.get_doc("Seller Profile", seller)

    # Calculate component scores
    fulfillment = calculate_fulfillment_score(seller)
    delivery = calculate_delivery_score(seller)
    quality = calculate_quality_score(seller)
    service = calculate_service_score(seller)
    compliance = calculate_compliance_score(seller)
    engagement = calculate_engagement_score(seller)

    # Create score record
    score = frappe.get_doc({
        "doctype": "Seller Score",
        "seller": seller,
        "score_type": score_type,
        "score_period": datetime.now().strftime("%Y-%m"),
        "calculation_date": nowdate(),
        "tenant": seller_doc.tenant,
        "status": "Draft",
        # Component scores
        "fulfillment_score": fulfillment["score"],
        "delivery_score": delivery["score"],
        "quality_score": quality["score"],
        "service_score": service["score"],
        "compliance_score": compliance["score"],
        "engagement_score": engagement["score"],
        # Metrics
        "orders_evaluated": fulfillment.get("orders", 0),
        "fulfillment_rate": fulfillment.get("fulfillment_rate", 100),
        "on_time_rate": delivery.get("on_time_rate", 100),
        "return_rate": quality.get("return_rate", 0),
        "cancellation_rate": fulfillment.get("cancelled", 0) / max(1, fulfillment.get("orders", 1)) * 100 if fulfillment.get("orders") else 0,
        "complaint_rate": quality.get("complaint_rate", 0),
        "response_time_avg": service.get("response_time", 24),
        # Rating metrics
        "average_rating": seller_doc.average_rating,
        "rating_count": seller_doc.total_reviews,
        # Penalties
        "policy_violations": compliance.get("violations", 0),
        "penalty_deduction": compliance.get("penalty", 0)
    })

    score.insert()

    if cint(auto_finalize):
        score.finalize()

    return score.get_score_breakdown()


@frappe.whitelist()
def get_seller_score_history(seller, limit=10, score_type=None):
    """
    Get score history for a seller.

    Args:
        seller: Seller profile name
        limit: Maximum records to return
        score_type: Filter by score type

    Returns:
        list: Score history records
    """
    if not frappe.db.exists("Seller Profile", seller):
        frappe.throw(_("Seller not found"))

    filters = {
        "seller": seller,
        "status": "Finalized"
    }

    if score_type:
        filters["score_type"] = score_type

    scores = frappe.get_all("Seller Score",
        filters=filters,
        fields=[
            "name", "calculation_date", "score_type", "score_period",
            "overall_score", "score_change", "score_trend",
            "fulfillment_score", "delivery_score", "quality_score",
            "service_score", "compliance_score", "engagement_score",
            "average_rating"
        ],
        order_by="calculation_date desc",
        limit=cint(limit)
    )

    return scores


@frappe.whitelist()
def get_score_details(score_name):
    """
    Get detailed score breakdown.

    Args:
        score_name: Seller Score name

    Returns:
        dict: Detailed score breakdown
    """
    if not frappe.db.exists("Seller Score", score_name):
        frappe.throw(_("Score record not found"))

    score = frappe.get_doc("Seller Score", score_name)
    return score.get_score_breakdown()


@frappe.whitelist()
def finalize_score(score_name):
    """
    Finalize a score record.

    Args:
        score_name: Seller Score name

    Returns:
        dict: Result
    """
    if not frappe.db.exists("Seller Score", score_name):
        frappe.throw(_("Score record not found"))

    score = frappe.get_doc("Seller Score", score_name)
    score.finalize()

    return {
        "status": "success",
        "message": _("Score finalized successfully"),
        "score": score_name
    }


@frappe.whitelist()
def bulk_calculate_scores(score_type="Periodic", tenant=None, auto_finalize=False):
    """
    Calculate scores for all active sellers.

    Args:
        score_type: Type of score calculation
        tenant: Filter by tenant
        auto_finalize: Automatically finalize scores

    Returns:
        dict: Calculation results summary
    """
    filters = {"status": "Active"}
    if tenant:
        filters["tenant"] = tenant

    sellers = frappe.get_all("Seller Profile", filters=filters, pluck="name")

    results = {
        "total": len(sellers),
        "success": 0,
        "failed": 0,
        "errors": []
    }

    for seller in sellers:
        try:
            calculate_seller_score(seller, score_type, auto_finalize)
            results["success"] += 1
        except Exception as e:
            results["failed"] += 1
            results["errors"].append({
                "seller": seller,
                "error": str(e)
            })

    return results


@frappe.whitelist()
def get_score_statistics(tenant=None):
    """
    Get platform-wide score statistics.

    Args:
        tenant: Filter by tenant

    Returns:
        dict: Score statistics
    """
    # Use parameterized queries to prevent SQL injection
    params = {}
    tenant_filter = ""
    if tenant:
        tenant_filter = "AND tenant = %(tenant)s"
        params["tenant"] = tenant

    stats = frappe.db.sql("""
        SELECT
            AVG(seller_score) as avg_score,
            MIN(seller_score) as min_score,
            MAX(seller_score) as max_score,
            COUNT(*) as total_sellers,
            SUM(CASE WHEN seller_score >= 90 THEN 1 ELSE 0 END) as excellent_count,
            SUM(CASE WHEN seller_score >= 70 AND seller_score < 90 THEN 1 ELSE 0 END) as good_count,
            SUM(CASE WHEN seller_score >= 50 AND seller_score < 70 THEN 1 ELSE 0 END) as average_count,
            SUM(CASE WHEN seller_score < 50 THEN 1 ELSE 0 END) as poor_count
        FROM `tabSeller Profile`
        WHERE status = 'Active'
        {tenant_filter}
    """.format(tenant_filter=tenant_filter), params, as_dict=True)

    return {
        "average_score": round(stats[0].avg_score or 0, 2) if stats else 0,
        "min_score": round(stats[0].min_score or 0, 2) if stats else 0,
        "max_score": round(stats[0].max_score or 0, 2) if stats else 0,
        "total_sellers": stats[0].total_sellers or 0 if stats else 0,
        "distribution": {
            "excellent": stats[0].excellent_count or 0 if stats else 0,
            "good": stats[0].good_count or 0 if stats else 0,
            "average": stats[0].average_count or 0 if stats else 0,
            "poor": stats[0].poor_count or 0 if stats else 0
        }
    }


@frappe.whitelist()
def compare_seller_scores(sellers):
    """
    Compare scores between multiple sellers.

    Args:
        sellers: JSON list of seller names

    Returns:
        list: Comparison data
    """
    import json
    if isinstance(sellers, str):
        sellers = json.loads(sellers)

    result = []
    for seller in sellers:
        if frappe.db.exists("Seller Profile", seller):
            seller_doc = frappe.get_doc("Seller Profile", seller)
            result.append({
                "seller": seller,
                "seller_name": seller_doc.seller_name,
                "overall_score": seller_doc.seller_score,
                "average_rating": seller_doc.average_rating,
                "total_sales": seller_doc.total_sales_count,
                "fulfillment_rate": seller_doc.order_fulfillment_rate,
                "on_time_rate": seller_doc.on_time_delivery_rate,
                "tier": seller_doc.seller_tier
            })

    # Sort by overall score descending
    result.sort(key=lambda x: x["overall_score"], reverse=True)

    return result

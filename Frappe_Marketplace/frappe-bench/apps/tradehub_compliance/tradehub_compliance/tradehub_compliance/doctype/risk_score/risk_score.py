# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import nowdate, now_datetime, getdate, add_days, add_months, flt, cint
import json


class RiskScore(Document):
    """
    Risk Score DocType - Risk assessment and credit decisions for sellers and buyers

    Features:
    - Multi-factor risk scoring with weighted averages
    - Automatic risk level determination
    - Credit decision automation with manual override
    - Payment method recommendations based on risk
    - History tracking and trend analysis
    """

    def validate(self):
        """Validate risk score data before save"""
        self.validate_profile()
        self.populate_tenant()
        self.validate_dates()
        self.calculate_factor_scores()
        self.determine_risk_level()
        self.make_credit_decision()
        self.update_timestamps()

    def before_save(self):
        """Before save hook"""
        self.track_score_changes()
        self.set_next_review_date()

    def on_update(self):
        """After update hook - update related documents"""
        self.update_kyc_profile_link()

    def validate_profile(self):
        """Validate profile based on type"""
        if self.profile_type == "Seller":
            if not self.seller_profile:
                frappe.throw(_("Seller Profile is required when Profile Type is Seller"))
            # Clear buyer fields
            self.buyer_profile = None
            self.buyer_name = None
        elif self.profile_type == "Buyer":
            if not self.buyer_profile:
                frappe.throw(_("Buyer Profile is required when Profile Type is Buyer"))
            # Clear seller fields
            self.seller_profile = None
            self.seller_name = None

    def populate_tenant(self):
        """Auto-populate tenant from seller or buyer profile"""
        if self.profile_type == "Seller" and self.seller_profile:
            tenant = frappe.db.get_value("Seller Profile", self.seller_profile, "tenant")
            if tenant:
                self.tenant = tenant
        elif self.profile_type == "Buyer" and self.buyer_profile:
            # Try to get tenant from organization
            org = frappe.db.get_value("User", self.buyer_profile, "organization")
            if org:
                tenant = frappe.db.get_value("Organization", org, "tenant")
                if tenant:
                    self.tenant = tenant

    def validate_dates(self):
        """Validate effective dates"""
        if not self.effective_from:
            self.effective_from = nowdate()

        if self.effective_until:
            if getdate(self.effective_until) < getdate(self.effective_from):
                frappe.throw(_("Effective Until date cannot be before Effective From date"))

        # Check for expiry
        if self.effective_until and getdate(self.effective_until) < getdate(nowdate()):
            if self.status == "Active":
                self.status = "Expired"

    def calculate_factor_scores(self):
        """Calculate summary statistics from scoring factors"""
        if not self.scoring_factors:
            self.total_weight = 0
            self.weighted_average = 0
            self.positive_factors_count = 0
            self.negative_factors_count = 0
            self.critical_factors_count = 0
            self.confidence_level = "Very Low"
            return

        total_weight = 0
        weighted_sum = 0
        positive_count = 0
        negative_count = 0
        critical_count = 0
        active_factors = 0

        for factor in self.scoring_factors:
            if not factor.is_active:
                continue

            active_factors += 1
            weight = flt(factor.weight, 2) or 1
            score = flt(factor.normalized_score, 2) or 0

            # Calculate weighted score for this factor
            factor.weighted_score = score * weight

            total_weight += weight
            weighted_sum += factor.weighted_score

            # Count by impact
            if factor.impact == "Positive":
                positive_count += 1
            elif factor.impact == "Negative":
                negative_count += 1
            elif factor.impact == "Critical":
                critical_count += 1

        self.total_weight = flt(total_weight, 2)
        self.positive_factors_count = positive_count
        self.negative_factors_count = negative_count
        self.critical_factors_count = critical_count

        # Calculate weighted average
        if total_weight > 0:
            self.weighted_average = flt(weighted_sum / total_weight, 2)
        else:
            self.weighted_average = 0

        # Use weighted average as risk score if not set manually
        if self.risk_score == 0 or not self.risk_score:
            self.risk_score = self.weighted_average

        # Determine confidence level based on number of factors
        self.confidence_level = self._determine_confidence(active_factors, total_weight)

        self.last_calculated_at = now_datetime()

    def _determine_confidence(self, factor_count, total_weight):
        """Determine confidence level based on data quality"""
        if factor_count >= 10 and total_weight >= 20:
            return "Very High"
        elif factor_count >= 7 and total_weight >= 15:
            return "High"
        elif factor_count >= 4 and total_weight >= 8:
            return "Medium"
        elif factor_count >= 2 and total_weight >= 3:
            return "Low"
        else:
            return "Very Low"

    def determine_risk_level(self):
        """Determine risk level based on risk score"""
        score = flt(self.risk_score, 2)

        # Risk level thresholds (0-100 scale, higher = more risk)
        if score <= 15:
            self.risk_level = "Very Low"
        elif score <= 30:
            self.risk_level = "Low"
        elif score <= 50:
            self.risk_level = "Medium"
        elif score <= 70:
            self.risk_level = "High"
        elif score <= 85:
            self.risk_level = "Very High"
        else:
            self.risk_level = "Critical"

        # Override to Critical if there are critical factors
        if self.critical_factors_count > 0:
            if self.risk_level not in ["Very High", "Critical"]:
                self.risk_level = "Very High"

    def make_credit_decision(self):
        """Make automatic credit decision based on risk assessment"""
        if self.manual_override:
            # Don't override manual decision
            return

        self.auto_decision = 1

        # Decision based on risk level
        decision_map = {
            "Very Low": "Auto Approve",
            "Low": "Approve",
            "Medium": "Approve with Conditions",
            "High": "Review",
            "Very High": "Review with Caution",
            "Critical": "Reject"
        }

        self.credit_decision = decision_map.get(self.risk_level, "Review")

        # Generate decision reason
        reasons = []
        if self.risk_score:
            reasons.append(f"Risk Score: {self.risk_score}")
        if self.risk_level:
            reasons.append(f"Risk Level: {self.risk_level}")
        if self.critical_factors_count > 0:
            reasons.append(f"{self.critical_factors_count} critical risk factor(s)")
        if self.negative_factors_count > 0:
            reasons.append(f"{self.negative_factors_count} negative risk factor(s)")

        self.credit_decision_reason = "; ".join(reasons) if reasons else "Auto-generated decision"

        # Set payment method recommendations
        self._set_payment_recommendations()

        # Set credit limit based on risk
        self._set_credit_limit()

    def _set_payment_recommendations(self):
        """Set recommended and restricted payment methods based on risk"""
        all_methods = ["Credit Card", "Debit Card", "Bank Transfer", "Cash on Delivery", "Credit Terms", "Letter of Credit", "PayPal", "Escrow"]

        if self.risk_level == "Very Low":
            self.recommended_payment_methods = ", ".join(all_methods)
            self.restricted_payment_methods = ""
        elif self.risk_level == "Low":
            self.recommended_payment_methods = "Credit Card, Debit Card, Bank Transfer, Credit Terms, PayPal"
            self.restricted_payment_methods = ""
        elif self.risk_level == "Medium":
            self.recommended_payment_methods = "Credit Card, Debit Card, Bank Transfer, PayPal, Escrow"
            self.restricted_payment_methods = "Credit Terms"
        elif self.risk_level == "High":
            self.recommended_payment_methods = "Prepaid, Bank Transfer, Escrow"
            self.restricted_payment_methods = "Credit Terms, Cash on Delivery"
        elif self.risk_level == "Very High":
            self.recommended_payment_methods = "Prepaid, Escrow"
            self.restricted_payment_methods = "Credit Terms, Cash on Delivery, Credit Card"
        else:  # Critical
            self.recommended_payment_methods = "Escrow Only"
            self.restricted_payment_methods = "All other methods"

    def _set_credit_limit(self):
        """Set credit limit based on risk level"""
        if not self.credit_limit:
            base_limits = {
                "Very Low": 100000,
                "Low": 50000,
                "Medium": 25000,
                "High": 10000,
                "Very High": 5000,
                "Critical": 0
            }
            self.credit_limit = base_limits.get(self.risk_level, 0)

    def track_score_changes(self):
        """Track changes in risk score for trend analysis"""
        if self.is_new():
            return

        # Get previous value
        old_doc = self.get_doc_before_save()
        if old_doc and old_doc.risk_score:
            self.previous_score = old_doc.risk_score
            self.score_change = flt(self.risk_score - old_doc.risk_score, 2)

            # Determine trend (lower risk = improving)
            if self.score_change < -5:
                self.score_trend = "Improving"
            elif self.score_change > 5:
                self.score_trend = "Worsening"
            else:
                self.score_trend = "Stable"

            # Add to history
            self._add_to_history(old_doc.risk_score, self.risk_score)

    def _add_to_history(self, old_score, new_score):
        """Add score change to calculation history"""
        history = []
        if self.calculation_history:
            try:
                history = json.loads(self.calculation_history)
            except json.JSONDecodeError:
                history = []

        history_entry = {
            "date": str(now_datetime()),
            "old_score": old_score,
            "new_score": new_score,
            "change": flt(new_score - old_score, 2),
            "risk_level": self.risk_level,
            "credit_decision": self.credit_decision,
            "calculated_by": frappe.session.user
        }

        history.append(history_entry)

        # Keep only last 50 entries
        if len(history) > 50:
            history = history[-50:]

        self.calculation_history = json.dumps(history, indent=2)

    def set_next_review_date(self):
        """Set next review date based on frequency"""
        if not self.next_review_date:
            today = getdate(nowdate())

            frequency_days = {
                "Weekly": 7,
                "Bi-Weekly": 14,
                "Monthly": 30,
                "Quarterly": 90,
                "Semi-Annually": 180,
                "Annually": 365,
                "On Event": 0
            }

            days = frequency_days.get(self.review_frequency, 30)
            if days > 0:
                self.next_review_date = add_days(today, days)

    def update_timestamps(self):
        """Update system timestamps"""
        self.modified_at = now_datetime()
        self.modified_by_user = frappe.session.user

        if self.is_new():
            self.created_at = now_datetime()
            self.created_by = frappe.session.user

    def update_kyc_profile_link(self):
        """Update the risk score link in KYC Profile"""
        if not self.kyc_profile_link:
            return

        try:
            kyc_doc = frappe.get_doc("KYC Profile", self.kyc_profile_link)
            if kyc_doc.risk_score_link != self.name:
                kyc_doc.risk_score_link = self.name
                kyc_doc.save(ignore_permissions=True)
        except Exception:
            pass  # Ignore if KYC profile doesn't exist

    def apply_manual_override(self, new_decision, reason, expiry_date=None):
        """Apply a manual override to the credit decision"""
        self.manual_override = 1
        self.credit_decision = new_decision
        self.override_reason = reason
        self.override_by = frappe.session.user
        self.override_at = now_datetime()
        self.override_expiry = expiry_date
        self.auto_decision = 0
        self.save()

    def remove_manual_override(self):
        """Remove manual override and recalculate auto decision"""
        self.manual_override = 0
        self.override_by = None
        self.override_at = None
        self.override_reason = None
        self.override_expiry = None
        self.make_credit_decision()
        self.save()

    def recalculate(self):
        """Recalculate risk score and decision"""
        self.calculate_factor_scores()
        self.determine_risk_level()
        if not self.manual_override:
            self.make_credit_decision()
        self.last_calculated_at = now_datetime()
        self.save()

    def add_risk_factor(self, factor_data):
        """Add a new risk factor to the scoring"""
        self.append("scoring_factors", factor_data)
        self.recalculate()

    def is_high_risk(self):
        """Check if this is a high risk profile"""
        return self.risk_level in ["High", "Very High", "Critical"]

    def is_approved(self):
        """Check if credit decision is approved"""
        return self.credit_decision in ["Auto Approve", "Approve", "Approve with Conditions"]

    def is_review_required(self):
        """Check if manual review is required"""
        return self.credit_decision in ["Review", "Review with Caution"]

    def can_use_payment_method(self, payment_method):
        """Check if a payment method is allowed"""
        if self.restricted_payment_methods:
            restricted = [m.strip() for m in self.restricted_payment_methods.split(",")]
            return payment_method not in restricted
        return True


@frappe.whitelist()
def get_risk_score_for_profile(profile_type, profile_name):
    """
    Get active risk score for a seller or buyer profile

    Args:
        profile_type: 'Seller' or 'Buyer'
        profile_name: Name of the seller/buyer profile

    Returns:
        Risk Score document or None
    """
    filters = {
        "profile_type": profile_type,
        "status": "Active"
    }

    if profile_type == "Seller":
        filters["seller_profile"] = profile_name
    else:
        filters["buyer_profile"] = profile_name

    risk_scores = frappe.get_all(
        "Risk Score",
        filters=filters,
        order_by="effective_from desc",
        limit=1
    )

    if risk_scores:
        return frappe.get_doc("Risk Score", risk_scores[0].name)
    return None


@frappe.whitelist()
def create_risk_score(profile_type, profile_name, factors=None):
    """
    Create a new risk score for a profile

    Args:
        profile_type: 'Seller' or 'Buyer'
        profile_name: Name of the seller/buyer profile
        factors: List of factor dictionaries (optional)

    Returns:
        Created Risk Score document
    """
    doc = frappe.new_doc("Risk Score")
    doc.profile_type = profile_type

    if profile_type == "Seller":
        doc.seller_profile = profile_name
    else:
        doc.buyer_profile = profile_name

    doc.effective_from = nowdate()
    doc.status = "Active"

    # Add factors if provided
    if factors:
        if isinstance(factors, str):
            factors = json.loads(factors)
        for factor in factors:
            doc.append("scoring_factors", factor)

    doc.insert()
    return doc


@frappe.whitelist()
def recalculate_risk_score(risk_score_name):
    """
    Recalculate an existing risk score

    Args:
        risk_score_name: Name of the Risk Score document

    Returns:
        Updated Risk Score document
    """
    doc = frappe.get_doc("Risk Score", risk_score_name)
    doc.recalculate()
    return doc


@frappe.whitelist()
def apply_override(risk_score_name, new_decision, reason, expiry_date=None):
    """
    Apply a manual override to a risk score's credit decision

    Args:
        risk_score_name: Name of the Risk Score document
        new_decision: New credit decision
        reason: Reason for override
        expiry_date: Optional expiry date for override

    Returns:
        Updated Risk Score document
    """
    doc = frappe.get_doc("Risk Score", risk_score_name)
    doc.apply_manual_override(new_decision, reason, expiry_date)
    return doc


@frappe.whitelist()
def check_payment_method(risk_score_name, payment_method):
    """
    Check if a payment method is allowed for a risk score

    Args:
        risk_score_name: Name of the Risk Score document
        payment_method: Payment method to check

    Returns:
        Boolean indicating if method is allowed
    """
    doc = frappe.get_doc("Risk Score", risk_score_name)
    return doc.can_use_payment_method(payment_method)


@frappe.whitelist()
def get_risk_summary(risk_score_name):
    """
    Get a summary of risk assessment

    Args:
        risk_score_name: Name of the Risk Score document

    Returns:
        Dictionary with risk summary
    """
    doc = frappe.get_doc("Risk Score", risk_score_name)

    return {
        "name": doc.name,
        "risk_score": doc.risk_score,
        "risk_level": doc.risk_level,
        "credit_decision": doc.credit_decision,
        "credit_limit": doc.credit_limit,
        "is_high_risk": doc.is_high_risk(),
        "is_approved": doc.is_approved(),
        "needs_review": doc.is_review_required(),
        "recommended_payment_methods": doc.recommended_payment_methods,
        "restricted_payment_methods": doc.restricted_payment_methods,
        "confidence_level": doc.confidence_level,
        "total_factors": len(doc.scoring_factors) if doc.scoring_factors else 0,
        "critical_factors": doc.critical_factors_count,
        "effective_from": str(doc.effective_from) if doc.effective_from else None,
        "effective_until": str(doc.effective_until) if doc.effective_until else None,
        "status": doc.status
    }


def get_risk_score_permission_query(user):
    """Permission query for tenant-based access control"""
    if "System Manager" in frappe.get_roles(user):
        return ""

    # Get user's tenant
    tenant = None

    # Try to get from seller profile
    seller = frappe.db.get_value("Seller Profile", {"user": user}, "tenant")
    if seller:
        tenant = seller

    # Try to get from organization
    if not tenant:
        org = frappe.db.get_value("User", user, "organization")
        if org:
            tenant = frappe.db.get_value("Organization", org, "tenant")

    if tenant:
        return f"`tabRisk Score`.tenant = '{tenant}'"

    return "1=0"  # No access if no tenant

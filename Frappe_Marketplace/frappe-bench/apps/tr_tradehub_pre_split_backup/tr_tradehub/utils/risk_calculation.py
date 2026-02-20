# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

"""
Risk Score Calculation Module

This module provides functions for calculating risk scores from transaction events.
Risk factors are computed based on:
- Transaction history (volume, frequency, disputes)
- Payment behavior (timeliness, defaults)
- Order fulfillment metrics
- Account age and activity
- KYC verification status
"""

import frappe
from frappe import _
from frappe.utils import (
    nowdate,
    now_datetime,
    getdate,
    add_days,
    add_months,
    date_diff,
    flt,
    cint
)


# Risk factor configuration with default weights
RISK_FACTORS_CONFIG = {
    "transaction_volume": {
        "name": "Transaction Volume",
        "description": "Total transaction value in last 90 days",
        "weight": 2.0,
        "category": "Transaction",
        "thresholds": {
            "excellent": 100000,  # > 100k = low risk
            "good": 50000,
            "moderate": 10000,
            "poor": 1000,
            "very_poor": 0
        }
    },
    "transaction_count": {
        "name": "Transaction Count",
        "description": "Number of transactions in last 90 days",
        "weight": 1.5,
        "category": "Transaction",
        "thresholds": {
            "excellent": 50,
            "good": 20,
            "moderate": 10,
            "poor": 3,
            "very_poor": 0
        }
    },
    "dispute_rate": {
        "name": "Dispute Rate",
        "description": "Percentage of transactions with disputes",
        "weight": 3.0,  # Higher weight - disputes are important
        "category": "Dispute",
        "thresholds": {  # Lower is better for disputes
            "excellent": 0,
            "good": 2,
            "moderate": 5,
            "poor": 10,
            "very_poor": 20
        },
        "inverse": True  # Higher values = higher risk
    },
    "payment_timeliness": {
        "name": "Payment Timeliness",
        "description": "Percentage of on-time payments",
        "weight": 2.5,
        "category": "Payment",
        "thresholds": {
            "excellent": 98,
            "good": 90,
            "moderate": 75,
            "poor": 50,
            "very_poor": 0
        }
    },
    "return_rate": {
        "name": "Return Rate",
        "description": "Percentage of orders returned",
        "weight": 1.5,
        "category": "Fulfillment",
        "thresholds": {
            "excellent": 0,
            "good": 5,
            "moderate": 10,
            "poor": 20,
            "very_poor": 30
        },
        "inverse": True
    },
    "account_age": {
        "name": "Account Age",
        "description": "Days since account creation",
        "weight": 1.0,
        "category": "Account",
        "thresholds": {
            "excellent": 365,
            "good": 180,
            "moderate": 90,
            "poor": 30,
            "very_poor": 0
        }
    },
    "kyc_status": {
        "name": "KYC Verification",
        "description": "KYC verification status",
        "weight": 2.0,
        "category": "Verification",
        "status_scores": {
            "Verified": 0,
            "Pending Review": 30,
            "In Progress": 50,
            "Not Started": 80,
            "Rejected": 100
        }
    },
    "cancellation_rate": {
        "name": "Cancellation Rate",
        "description": "Percentage of orders cancelled",
        "weight": 1.5,
        "category": "Fulfillment",
        "thresholds": {
            "excellent": 0,
            "good": 3,
            "moderate": 7,
            "poor": 15,
            "very_poor": 25
        },
        "inverse": True
    },
    "average_order_value": {
        "name": "Average Order Value",
        "description": "Average transaction value",
        "weight": 1.0,
        "category": "Transaction",
        "thresholds": {
            "excellent": 5000,
            "good": 1000,
            "moderate": 500,
            "poor": 100,
            "very_poor": 0
        }
    },
    "late_payment_count": {
        "name": "Late Payments",
        "description": "Number of late payments in last 90 days",
        "weight": 2.0,
        "category": "Payment",
        "thresholds": {
            "excellent": 0,
            "good": 1,
            "moderate": 3,
            "poor": 5,
            "very_poor": 10
        },
        "inverse": True
    }
}


def calculate_risk_score(profile_type, profile_name, update_risk_score=True):
    """
    Calculate risk score from transaction events for a seller or buyer profile.

    This function analyzes transaction history, payment behavior, and other
    metrics to compute a comprehensive risk score.

    Args:
        profile_type: 'Seller' or 'Buyer'
        profile_name: Name of the seller/buyer profile
        update_risk_score: If True, updates or creates the Risk Score document

    Returns:
        dict: Risk calculation result containing:
            - risk_score (float): Calculated risk score (0-100)
            - risk_level (str): Risk level category
            - factors (list): Individual risk factors with scores
            - recommendations (list): Risk mitigation recommendations
            - risk_score_doc (str): Name of Risk Score document (if updated)
    """
    if not profile_type or not profile_name:
        frappe.throw(_("Profile type and profile name are required"))

    if profile_type not in ["Seller", "Buyer"]:
        frappe.throw(_("Profile type must be 'Seller' or 'Buyer'"))

    # Gather transaction data
    transaction_data = _get_transaction_data(profile_type, profile_name)

    # Calculate individual risk factors
    factors = _calculate_risk_factors(transaction_data, profile_type, profile_name)

    # Calculate weighted average risk score
    risk_score = _calculate_weighted_score(factors)

    # Determine risk level
    risk_level = _determine_risk_level(risk_score, factors)

    # Generate recommendations
    recommendations = _generate_recommendations(factors, risk_level)

    result = {
        "risk_score": risk_score,
        "risk_level": risk_level,
        "factors": factors,
        "recommendations": recommendations,
        "calculated_at": str(now_datetime()),
        "profile_type": profile_type,
        "profile_name": profile_name
    }

    # Update Risk Score document if requested
    if update_risk_score:
        risk_score_doc = _update_risk_score_document(
            profile_type,
            profile_name,
            risk_score,
            risk_level,
            factors
        )
        result["risk_score_doc"] = risk_score_doc

    return result


def _get_transaction_data(profile_type, profile_name):
    """
    Gather transaction data for risk calculation.

    Args:
        profile_type: 'Seller' or 'Buyer'
        profile_name: Name of the profile

    Returns:
        dict: Transaction data including orders, payments, disputes
    """
    data = {
        "total_transactions": 0,
        "total_value": 0,
        "dispute_count": 0,
        "return_count": 0,
        "cancellation_count": 0,
        "late_payment_count": 0,
        "on_time_payment_count": 0,
        "account_creation_date": None,
        "kyc_status": "Not Started",
        "recent_orders": [],
        "average_order_value": 0
    }

    # Define the lookback period (90 days)
    lookback_date = add_days(getdate(nowdate()), -90)

    # Get profile creation date
    if profile_type == "Seller":
        profile_data = frappe.db.get_value(
            "Seller Profile",
            profile_name,
            ["creation", "tenant"],
            as_dict=True
        )
        if profile_data:
            data["account_creation_date"] = profile_data.get("creation")
            data["tenant"] = profile_data.get("tenant")

        # Get seller's orders (Sub Orders)
        try:
            orders = frappe.get_all(
                "Sub Order",
                filters={
                    "seller": profile_name,
                    "creation": [">=", lookback_date]
                },
                fields=["name", "grand_total", "status", "creation", "payment_status"]
            )
            data["recent_orders"] = orders
            data["total_transactions"] = len(orders)
            data["total_value"] = sum(flt(o.get("grand_total", 0)) for o in orders)

            # Count by status
            for order in orders:
                status = order.get("status", "").lower()
                if "cancel" in status:
                    data["cancellation_count"] += 1
                if "return" in status:
                    data["return_count"] += 1
                if "dispute" in status:
                    data["dispute_count"] += 1

                payment_status = order.get("payment_status", "").lower()
                if "late" in payment_status or "overdue" in payment_status:
                    data["late_payment_count"] += 1
                elif "paid" in payment_status:
                    data["on_time_payment_count"] += 1

        except Exception:
            pass  # DocType may not exist or have different structure

    else:  # Buyer
        profile_data = frappe.db.get_value(
            "Buyer Profile",
            profile_name,
            ["creation"],
            as_dict=True
        )
        if profile_data:
            data["account_creation_date"] = profile_data.get("creation")

        # Get buyer's orders (Marketplace Orders)
        try:
            orders = frappe.get_all(
                "Marketplace Order",
                filters={
                    "buyer": profile_name,
                    "creation": [">=", lookback_date]
                },
                fields=["name", "grand_total", "status", "creation", "payment_status"]
            )
            data["recent_orders"] = orders
            data["total_transactions"] = len(orders)
            data["total_value"] = sum(flt(o.get("grand_total", 0)) for o in orders)

            # Count by status
            for order in orders:
                status = order.get("status", "").lower()
                if "cancel" in status:
                    data["cancellation_count"] += 1
                if "return" in status:
                    data["return_count"] += 1
                if "dispute" in status:
                    data["dispute_count"] += 1

                payment_status = order.get("payment_status", "").lower()
                if "late" in payment_status or "overdue" in payment_status:
                    data["late_payment_count"] += 1
                elif "paid" in payment_status:
                    data["on_time_payment_count"] += 1

        except Exception:
            pass

    # Calculate average order value
    if data["total_transactions"] > 0:
        data["average_order_value"] = data["total_value"] / data["total_transactions"]

    # Get KYC status
    try:
        kyc_profile = frappe.db.get_value(
            "KYC Profile",
            {
                "profile_type": profile_type,
                profile_type.lower() + "_profile": profile_name
            },
            "verification_status"
        )
        if kyc_profile:
            data["kyc_status"] = kyc_profile
    except Exception:
        pass

    return data


def _calculate_risk_factors(transaction_data, profile_type, profile_name):
    """
    Calculate individual risk factors from transaction data.

    Args:
        transaction_data: Transaction data dictionary
        profile_type: 'Seller' or 'Buyer'
        profile_name: Name of the profile

    Returns:
        list: List of risk factor dictionaries
    """
    factors = []

    # Transaction Volume Factor
    factors.append(_calculate_threshold_factor(
        "transaction_volume",
        transaction_data["total_value"],
        transaction_data
    ))

    # Transaction Count Factor
    factors.append(_calculate_threshold_factor(
        "transaction_count",
        transaction_data["total_transactions"],
        transaction_data
    ))

    # Dispute Rate Factor
    total_txn = transaction_data["total_transactions"]
    dispute_rate = (transaction_data["dispute_count"] / total_txn * 100) if total_txn > 0 else 0
    factors.append(_calculate_threshold_factor(
        "dispute_rate",
        dispute_rate,
        transaction_data
    ))

    # Return Rate Factor
    return_rate = (transaction_data["return_count"] / total_txn * 100) if total_txn > 0 else 0
    factors.append(_calculate_threshold_factor(
        "return_rate",
        return_rate,
        transaction_data
    ))

    # Cancellation Rate Factor
    cancel_rate = (transaction_data["cancellation_count"] / total_txn * 100) if total_txn > 0 else 0
    factors.append(_calculate_threshold_factor(
        "cancellation_rate",
        cancel_rate,
        transaction_data
    ))

    # Payment Timeliness Factor
    total_payments = transaction_data["on_time_payment_count"] + transaction_data["late_payment_count"]
    payment_timeliness = (transaction_data["on_time_payment_count"] / total_payments * 100) if total_payments > 0 else 50
    factors.append(_calculate_threshold_factor(
        "payment_timeliness",
        payment_timeliness,
        transaction_data
    ))

    # Late Payment Count Factor
    factors.append(_calculate_threshold_factor(
        "late_payment_count",
        transaction_data["late_payment_count"],
        transaction_data
    ))

    # Account Age Factor
    if transaction_data["account_creation_date"]:
        account_age = date_diff(nowdate(), transaction_data["account_creation_date"])
    else:
        account_age = 0
    factors.append(_calculate_threshold_factor(
        "account_age",
        account_age,
        transaction_data
    ))

    # Average Order Value Factor
    factors.append(_calculate_threshold_factor(
        "average_order_value",
        transaction_data["average_order_value"],
        transaction_data
    ))

    # KYC Status Factor
    factors.append(_calculate_kyc_factor(transaction_data["kyc_status"]))

    return factors


def _calculate_threshold_factor(factor_key, value, transaction_data):
    """
    Calculate a risk factor based on threshold configuration.

    Args:
        factor_key: Key from RISK_FACTORS_CONFIG
        value: The actual value to evaluate
        transaction_data: Full transaction data for context

    Returns:
        dict: Risk factor with score and metadata
    """
    config = RISK_FACTORS_CONFIG.get(factor_key, {})
    thresholds = config.get("thresholds", {})
    is_inverse = config.get("inverse", False)

    # Determine score based on thresholds
    # For normal factors: higher value = lower risk = lower score
    # For inverse factors: higher value = higher risk = higher score

    if is_inverse:
        if value <= thresholds.get("excellent", 0):
            normalized_score = 0
            impact = "Positive"
        elif value <= thresholds.get("good", 0):
            normalized_score = 15
            impact = "Positive"
        elif value <= thresholds.get("moderate", 0):
            normalized_score = 35
            impact = "Neutral"
        elif value <= thresholds.get("poor", 0):
            normalized_score = 60
            impact = "Negative"
        else:
            normalized_score = 85
            impact = "Critical" if value > thresholds.get("very_poor", 0) * 1.5 else "Negative"
    else:
        if value >= thresholds.get("excellent", 0):
            normalized_score = 0
            impact = "Positive"
        elif value >= thresholds.get("good", 0):
            normalized_score = 15
            impact = "Positive"
        elif value >= thresholds.get("moderate", 0):
            normalized_score = 35
            impact = "Neutral"
        elif value >= thresholds.get("poor", 0):
            normalized_score = 60
            impact = "Negative"
        else:
            normalized_score = 85
            impact = "Negative"

    return {
        "factor_name": config.get("name", factor_key),
        "factor_key": factor_key,
        "description": config.get("description", ""),
        "category": config.get("category", "General"),
        "weight": config.get("weight", 1.0),
        "raw_value": value,
        "normalized_score": normalized_score,
        "weighted_score": normalized_score * config.get("weight", 1.0),
        "impact": impact,
        "is_active": True
    }


def _calculate_kyc_factor(kyc_status):
    """
    Calculate risk factor for KYC verification status.

    Args:
        kyc_status: Current KYC verification status

    Returns:
        dict: Risk factor for KYC
    """
    config = RISK_FACTORS_CONFIG.get("kyc_status", {})
    status_scores = config.get("status_scores", {})

    normalized_score = status_scores.get(kyc_status, 50)

    # Determine impact
    if normalized_score <= 10:
        impact = "Positive"
    elif normalized_score <= 40:
        impact = "Neutral"
    elif normalized_score <= 70:
        impact = "Negative"
    else:
        impact = "Critical"

    return {
        "factor_name": config.get("name", "KYC Verification"),
        "factor_key": "kyc_status",
        "description": config.get("description", ""),
        "category": config.get("category", "Verification"),
        "weight": config.get("weight", 2.0),
        "raw_value": kyc_status,
        "normalized_score": normalized_score,
        "weighted_score": normalized_score * config.get("weight", 2.0),
        "impact": impact,
        "is_active": True
    }


def _calculate_weighted_score(factors):
    """
    Calculate the overall weighted risk score from individual factors.

    Args:
        factors: List of risk factor dictionaries

    Returns:
        float: Weighted average risk score (0-100)
    """
    if not factors:
        return 50  # Default medium risk if no factors

    total_weight = sum(f.get("weight", 1.0) for f in factors if f.get("is_active"))
    if total_weight == 0:
        return 50

    weighted_sum = sum(
        f.get("weighted_score", 0)
        for f in factors
        if f.get("is_active")
    )

    return round(weighted_sum / total_weight, 2)


def _determine_risk_level(risk_score, factors):
    """
    Determine risk level based on score and critical factors.

    Args:
        risk_score: Calculated risk score
        factors: List of risk factors

    Returns:
        str: Risk level category
    """
    # Count critical factors
    critical_count = sum(1 for f in factors if f.get("impact") == "Critical")

    # Base level from score
    if risk_score <= 15:
        level = "Very Low"
    elif risk_score <= 30:
        level = "Low"
    elif risk_score <= 50:
        level = "Medium"
    elif risk_score <= 70:
        level = "High"
    elif risk_score <= 85:
        level = "Very High"
    else:
        level = "Critical"

    # Escalate if there are critical factors
    if critical_count > 0 and level not in ["Very High", "Critical"]:
        level = "Very High"

    return level


def _generate_recommendations(factors, risk_level):
    """
    Generate risk mitigation recommendations based on factors.

    Args:
        factors: List of risk factors
        risk_level: Current risk level

    Returns:
        list: List of recommendation strings
    """
    recommendations = []

    # Find problematic factors
    problem_factors = [
        f for f in factors
        if f.get("impact") in ["Negative", "Critical"]
    ]

    for factor in problem_factors:
        key = factor.get("factor_key")

        if key == "kyc_status":
            recommendations.append(_("Complete KYC verification to improve risk score"))
        elif key == "dispute_rate":
            recommendations.append(_("Review and resolve open disputes to reduce dispute rate"))
        elif key == "late_payment_count":
            recommendations.append(_("Ensure timely payments to improve payment history"))
        elif key == "return_rate":
            recommendations.append(_("Improve product quality or descriptions to reduce returns"))
        elif key == "cancellation_rate":
            recommendations.append(_("Maintain stock levels and honor orders to reduce cancellations"))
        elif key == "transaction_volume":
            recommendations.append(_("Increase transaction activity to build trust"))
        elif key == "account_age":
            recommendations.append(_("Account is relatively new - continue building transaction history"))

    # Add general recommendations based on risk level
    if risk_level in ["High", "Very High", "Critical"]:
        recommendations.append(_("Consider requiring escrow or prepayment for transactions"))

    if risk_level == "Critical":
        recommendations.append(_("Manual review recommended before approving high-value transactions"))

    return recommendations


def _update_risk_score_document(profile_type, profile_name, risk_score, risk_level, factors):
    """
    Update or create Risk Score document with calculated values.

    Args:
        profile_type: 'Seller' or 'Buyer'
        profile_name: Name of the profile
        risk_score: Calculated risk score
        risk_level: Risk level category
        factors: List of risk factors

    Returns:
        str: Name of the Risk Score document
    """
    # Find existing active risk score
    filters = {
        "profile_type": profile_type,
        "status": "Active"
    }

    if profile_type == "Seller":
        filters["seller_profile"] = profile_name
    else:
        filters["buyer_profile"] = profile_name

    existing = frappe.get_all(
        "Risk Score",
        filters=filters,
        order_by="effective_from desc",
        limit=1
    )

    if existing:
        doc = frappe.get_doc("Risk Score", existing[0].name)
    else:
        doc = frappe.new_doc("Risk Score")
        doc.profile_type = profile_type
        if profile_type == "Seller":
            doc.seller_profile = profile_name
        else:
            doc.buyer_profile = profile_name
        doc.effective_from = nowdate()
        doc.status = "Active"

    # Update risk score
    doc.risk_score = risk_score
    doc.risk_level = risk_level

    # Clear existing factors and add new ones
    doc.scoring_factors = []
    for factor in factors:
        doc.append("scoring_factors", {
            "factor_name": factor.get("factor_name"),
            "description": factor.get("description"),
            "category": factor.get("category"),
            "weight": factor.get("weight"),
            "raw_value": str(factor.get("raw_value", "")),
            "normalized_score": factor.get("normalized_score"),
            "weighted_score": factor.get("weighted_score"),
            "impact": factor.get("impact"),
            "is_active": factor.get("is_active", True)
        })

    doc.last_calculated_at = now_datetime()
    doc.save(ignore_permissions=True)

    return doc.name


def calculate_risk_score_for_event(event_type, event_data):
    """
    Calculate/update risk score triggered by a transaction event.

    This function should be called from doc_events hooks when transactions
    occur that might affect risk scores.

    Args:
        event_type: Type of event ('order_created', 'payment_received',
                   'dispute_opened', 'return_requested', etc.)
        event_data: Dictionary containing event details

    Returns:
        dict: Updated risk calculation result
    """
    profile_type = event_data.get("profile_type")
    profile_name = event_data.get("profile_name")

    if not profile_type or not profile_name:
        return None

    # Recalculate risk score
    return calculate_risk_score(profile_type, profile_name, update_risk_score=True)


@frappe.whitelist()
def recalculate_all_risk_scores():
    """
    Batch recalculate risk scores for all active profiles.

    This function can be scheduled as a cron job to keep risk scores current.

    Returns:
        dict: Summary of recalculation results
    """
    results = {
        "sellers_processed": 0,
        "buyers_processed": 0,
        "errors": []
    }

    # Process sellers
    try:
        sellers = frappe.get_all("Seller Profile", filters={"disabled": 0}, pluck="name")
        for seller in sellers:
            try:
                calculate_risk_score("Seller", seller, update_risk_score=True)
                results["sellers_processed"] += 1
            except Exception as e:
                results["errors"].append(f"Seller {seller}: {str(e)}")
    except Exception as e:
        results["errors"].append(f"Error fetching sellers: {str(e)}")

    # Process buyers
    try:
        buyers = frappe.get_all("Buyer Profile", pluck="name")
        for buyer in buyers:
            try:
                calculate_risk_score("Buyer", buyer, update_risk_score=True)
                results["buyers_processed"] += 1
            except Exception as e:
                results["errors"].append(f"Buyer {buyer}: {str(e)}")
    except Exception as e:
        results["errors"].append(f"Error fetching buyers: {str(e)}")

    return results


@frappe.whitelist()
def get_risk_factors_config():
    """
    Get the risk factors configuration.

    Useful for displaying factor definitions in the UI.

    Returns:
        dict: Risk factors configuration
    """
    return RISK_FACTORS_CONFIG

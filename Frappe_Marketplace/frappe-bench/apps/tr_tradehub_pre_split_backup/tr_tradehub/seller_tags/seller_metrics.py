# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

"""
Seller Metrics - Materialized View for Seller KPIs

Calculates and caches seller performance metrics for rule evaluation.
"""

import frappe
from frappe import _
from frappe.utils import now_datetime, getdate, add_days, today
from typing import Dict, Any, Optional, List
from datetime import datetime, date


# Metric field definitions with their SQL types
METRICS_FIELDS = {
    "total_orders": "INT",
    "total_sales_amount": "DECIMAL(18,2)",
    "avg_rating": "FLOAT",
    "avg_response_time_hours": "FLOAT",
    "cancellation_rate": "FLOAT",
    "return_rate": "FLOAT",
    "on_time_delivery_rate": "FLOAT",
    "complaint_rate": "FLOAT",
    "listing_count": "INT",
    "active_listing_count": "INT",
    "active_days": "INT",
    "last_order_date": "DATE",
    "verification_status": "VARCHAR(50)",
    "premium_seller": "INT",  # Boolean as 0/1
    "total_reviews": "INT",
    "positive_review_rate": "FLOAT",
    "repeat_customer_rate": "FLOAT",
}


def get_seller_metrics(seller_id: str) -> Optional[Dict[str, Any]]:
    """
    Get cached metrics for a seller from Seller Metrics DocType.

    Args:
        seller_id: Seller Profile name

    Returns:
        Dict of metric values or None if not found
    """
    metrics = frappe.get_all(
        "Seller Metrics",
        filters={"seller": seller_id},
        fields=["*"],
        order_by="calculation_date desc",
        limit=1
    )

    if metrics:
        return metrics[0]
    return None


def calculate_metrics(seller_id: str) -> Dict[str, Any]:
    """
    Calculate current metrics for a seller from transactional data.

    Args:
        seller_id: Seller Profile name

    Returns:
        Dict of calculated metric values
    """
    metrics = {
        "seller": seller_id,
        "calculation_date": today()
    }

    # Get seller profile for basic info
    try:
        seller = frappe.get_doc("Seller Profile", seller_id)
        metrics["verification_status"] = seller.get("verification_status", "Pending")
        metrics["premium_seller"] = 1 if seller.get("is_premium") else 0
    except Exception:
        metrics["verification_status"] = "Unknown"
        metrics["premium_seller"] = 0

    # Calculate order metrics
    order_metrics = _calculate_order_metrics(seller_id)
    metrics.update(order_metrics)

    # Calculate listing metrics
    listing_metrics = _calculate_listing_metrics(seller_id)
    metrics.update(listing_metrics)

    # Calculate review metrics
    review_metrics = _calculate_review_metrics(seller_id)
    metrics.update(review_metrics)

    # Calculate activity metrics
    activity_metrics = _calculate_activity_metrics(seller_id)
    metrics.update(activity_metrics)

    return metrics


def _calculate_order_metrics(seller_id: str) -> Dict[str, Any]:
    """Calculate order-related metrics."""
    metrics = {
        "total_orders": 0,
        "total_sales_amount": 0.0,
        "cancellation_rate": 0.0,
        "return_rate": 0.0,
        "on_time_delivery_rate": 0.0,
        "last_order_date": None
    }

    # Check if Sub Order doctype exists
    if not frappe.db.table_exists("tabSub Order"):
        return metrics

    try:
        # Total orders and sales
        order_data = frappe.db.sql("""
            SELECT
                COUNT(*) as total_orders,
                COALESCE(SUM(total_amount), 0) as total_sales_amount,
                MAX(creation) as last_order_date
            FROM `tabSub Order`
            WHERE seller = %s
            AND docstatus != 2
        """, seller_id, as_dict=True)

        if order_data:
            metrics["total_orders"] = order_data[0].get("total_orders", 0) or 0
            metrics["total_sales_amount"] = float(order_data[0].get("total_sales_amount", 0) or 0)
            metrics["last_order_date"] = order_data[0].get("last_order_date")

        if metrics["total_orders"] > 0:
            # Cancellation rate
            cancelled = frappe.db.count(
                "Sub Order",
                filters={"seller": seller_id, "status": "Cancelled"}
            )
            metrics["cancellation_rate"] = (cancelled / metrics["total_orders"]) * 100

            # Return rate
            returned = frappe.db.count(
                "Sub Order",
                filters={"seller": seller_id, "status": "Returned"}
            )
            metrics["return_rate"] = (returned / metrics["total_orders"]) * 100

            # On-time delivery rate
            on_time = frappe.db.sql("""
                SELECT COUNT(*) as count
                FROM `tabSub Order`
                WHERE seller = %s
                AND status = 'Delivered'
                AND (delivered_at IS NULL OR delivered_at <= expected_delivery_date)
            """, seller_id, as_dict=True)

            delivered = frappe.db.count(
                "Sub Order",
                filters={"seller": seller_id, "status": "Delivered"}
            )

            if delivered > 0:
                metrics["on_time_delivery_rate"] = (on_time[0].count / delivered) * 100

    except Exception as e:
        frappe.log_error(f"Error calculating order metrics for {seller_id}: {str(e)}")

    return metrics


def _calculate_listing_metrics(seller_id: str) -> Dict[str, Any]:
    """Calculate listing-related metrics."""
    metrics = {
        "listing_count": 0,
        "active_listing_count": 0
    }

    if not frappe.db.table_exists("tabListing"):
        return metrics

    try:
        metrics["listing_count"] = frappe.db.count(
            "Listing",
            filters={"seller": seller_id}
        )

        metrics["active_listing_count"] = frappe.db.count(
            "Listing",
            filters={"seller": seller_id, "status": "Active"}
        )
    except Exception as e:
        frappe.log_error(f"Error calculating listing metrics for {seller_id}: {str(e)}")

    return metrics


def _calculate_review_metrics(seller_id: str) -> Dict[str, Any]:
    """Calculate review-related metrics."""
    metrics = {
        "avg_rating": 0.0,
        "total_reviews": 0,
        "positive_review_rate": 0.0,
        "complaint_rate": 0.0
    }

    # Check if Seller Review doctype exists
    if not frappe.db.table_exists("tabSeller Review"):
        return metrics

    try:
        review_data = frappe.db.sql("""
            SELECT
                COUNT(*) as total_reviews,
                AVG(rating) as avg_rating,
                SUM(CASE WHEN rating >= 4 THEN 1 ELSE 0 END) as positive_reviews
            FROM `tabSeller Review`
            WHERE seller = %s
            AND status = 'Published'
        """, seller_id, as_dict=True)

        if review_data and review_data[0].get("total_reviews"):
            metrics["total_reviews"] = review_data[0]["total_reviews"] or 0
            metrics["avg_rating"] = float(review_data[0]["avg_rating"] or 0)

            if metrics["total_reviews"] > 0:
                metrics["positive_review_rate"] = (
                    (review_data[0]["positive_reviews"] or 0) / metrics["total_reviews"]
                ) * 100

        # Complaint rate from complaints/disputes
        if frappe.db.table_exists("tabSeller Complaint"):
            total_orders = metrics.get("total_orders", 0)
            if total_orders > 0:
                complaints = frappe.db.count(
                    "Seller Complaint",
                    filters={"seller": seller_id}
                )
                metrics["complaint_rate"] = (complaints / total_orders) * 100

    except Exception as e:
        frappe.log_error(f"Error calculating review metrics for {seller_id}: {str(e)}")

    return metrics


def _calculate_activity_metrics(seller_id: str) -> Dict[str, Any]:
    """Calculate activity-related metrics."""
    metrics = {
        "active_days": 0,
        "avg_response_time_hours": 0.0,
        "repeat_customer_rate": 0.0
    }

    try:
        # Active days since registration
        seller = frappe.get_doc("Seller Profile", seller_id)
        if seller.creation:
            creation_date = getdate(seller.creation)
            today_date = getdate(today())
            metrics["active_days"] = (today_date - creation_date).days

        # Average response time (if message/chat system exists)
        if frappe.db.table_exists("tabSeller Message"):
            response_data = frappe.db.sql("""
                SELECT AVG(
                    TIMESTAMPDIFF(HOUR, received_at, responded_at)
                ) as avg_response_hours
                FROM `tabSeller Message`
                WHERE seller = %s
                AND responded_at IS NOT NULL
            """, seller_id, as_dict=True)

            if response_data and response_data[0].get("avg_response_hours"):
                metrics["avg_response_time_hours"] = float(
                    response_data[0]["avg_response_hours"]
                )

        # Repeat customer rate
        if frappe.db.table_exists("tabSub Order"):
            customer_data = frappe.db.sql("""
                SELECT
                    COUNT(DISTINCT customer) as total_customers,
                    COUNT(DISTINCT CASE WHEN order_count > 1 THEN customer END) as repeat_customers
                FROM (
                    SELECT customer, COUNT(*) as order_count
                    FROM `tabSub Order`
                    WHERE seller = %s
                    AND docstatus != 2
                    GROUP BY customer
                ) customer_orders
            """, seller_id, as_dict=True)

            if customer_data and customer_data[0].get("total_customers"):
                total = customer_data[0]["total_customers"]
                repeat = customer_data[0].get("repeat_customers", 0) or 0
                if total > 0:
                    metrics["repeat_customer_rate"] = (repeat / total) * 100

    except Exception as e:
        frappe.log_error(f"Error calculating activity metrics for {seller_id}: {str(e)}")

    return metrics


def refresh_seller_metrics(seller_id: str) -> str:
    """
    Calculate and store fresh metrics for a seller.

    Args:
        seller_id: Seller Profile name

    Returns:
        Name of created Seller Metrics document
    """
    metrics = calculate_metrics(seller_id)

    # Check for existing metrics record for today
    existing = frappe.get_all(
        "Seller Metrics",
        filters={
            "seller": seller_id,
            "calculation_date": today()
        },
        fields=["name"]
    )

    if existing:
        # Update existing record
        doc = frappe.get_doc("Seller Metrics", existing[0].name)
        for key, value in metrics.items():
            if hasattr(doc, key):
                setattr(doc, key, value)
        doc.save(ignore_permissions=True)
        return doc.name
    else:
        # Create new record
        doc = frappe.get_doc({
            "doctype": "Seller Metrics",
            **metrics
        })
        doc.insert(ignore_permissions=True)
        return doc.name


def refresh_all_seller_metrics() -> int:
    """
    Refresh metrics for all active sellers.

    Returns:
        Number of sellers processed
    """
    sellers = frappe.get_all(
        "Seller Profile",
        filters={"status": ["in", ["Active", "Verified"]]},
        fields=["name"]
    )

    count = 0
    for seller in sellers:
        try:
            refresh_seller_metrics(seller.name)
            count += 1
        except Exception as e:
            frappe.log_error(
                f"Error refreshing metrics for {seller.name}: {str(e)}",
                "Seller Metrics Refresh"
            )

    frappe.db.commit()
    return count

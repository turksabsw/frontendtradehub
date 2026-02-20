# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

"""
KPI Tasks Module

Scheduled background tasks for KPI calculations:
- calculate_daily_seller_kpis: Daily calculation of seller KPI metrics
- calculate_monthly_seller_kpis: Monthly full KPI recalculation for all sellers
- calculate_buyer_kpis: Daily calculation of buyer KPI metrics
- recalculate_seller_rankings: Daily ranking update based on KPI scores
- update_kpi_trends: Daily trend analysis comparing to previous periods
"""

import frappe
from frappe import _
from frappe.utils import nowdate, add_days, add_months, getdate, now_datetime, date_diff


def calculate_daily_seller_kpis():
    """
    Calculate daily KPI metrics for all active sellers.
    Creates or updates Seller KPI records for the current day.
    Runs daily to keep metrics up-to-date.
    """
    frappe.logger().info("Running calculate_daily_seller_kpis task")

    today = getdate(nowdate())
    processed_count = 0
    error_count = 0

    # Get all active seller profiles
    sellers = frappe.get_all(
        "Seller Profile",
        filters={"status": ["in", ["Active", "Approved"]]},
        fields=["name", "seller_name", "tenant"]
    )

    for seller in sellers:
        try:
            # Calculate daily KPI for this seller
            kpi = calculate_seller_kpi_metrics(
                seller.name,
                seller.tenant,
                today,
                today,
                "Daily"
            )
            if kpi:
                processed_count += 1

        except Exception as e:
            error_count += 1
            frappe.log_error(
                message=f"Error calculating daily KPI for seller {seller.name}: {str(e)}",
                title="Daily Seller KPI Calculation Error"
            )

    frappe.db.commit()
    frappe.logger().info(
        f"Completed calculate_daily_seller_kpis task: "
        f"{processed_count} sellers processed, {error_count} errors"
    )

    return processed_count


def calculate_monthly_seller_kpis():
    """
    Calculate monthly KPI metrics for all active sellers.
    Creates or updates Seller KPI records for the current month.
    Runs on the 1st of each month for the previous month.
    """
    frappe.logger().info("Running calculate_monthly_seller_kpis task")

    today = getdate(nowdate())
    # Calculate for previous month
    first_of_current_month = today.replace(day=1)
    last_of_previous_month = add_days(first_of_current_month, -1)
    first_of_previous_month = last_of_previous_month.replace(day=1)

    processed_count = 0
    error_count = 0

    # Get all seller profiles (including inactive to maintain history)
    sellers = frappe.get_all(
        "Seller Profile",
        filters={},
        fields=["name", "seller_name", "tenant"]
    )

    for seller in sellers:
        try:
            # Calculate monthly KPI for this seller
            kpi = calculate_seller_kpi_metrics(
                seller.name,
                seller.tenant,
                first_of_previous_month,
                last_of_previous_month,
                "Monthly"
            )
            if kpi:
                processed_count += 1

        except Exception as e:
            error_count += 1
            frappe.log_error(
                message=f"Error calculating monthly KPI for seller {seller.name}: {str(e)}",
                title="Monthly Seller KPI Calculation Error"
            )

    frappe.db.commit()
    frappe.logger().info(
        f"Completed calculate_monthly_seller_kpis task: "
        f"{processed_count} sellers processed, {error_count} errors"
    )

    return processed_count


def calculate_seller_kpi_metrics(seller, tenant, start_date, end_date, kpi_period):
    """
    Calculate KPI metrics for a specific seller within a date range.

    Args:
        seller: Seller Profile name
        tenant: Tenant name
        start_date: Start date for calculation
        end_date: End date for calculation
        kpi_period: Period type (Daily, Weekly, Monthly, Quarterly, Yearly)

    Returns:
        Seller KPI document name or None if no data
    """
    # Check if KPI record already exists for this period
    existing_kpi = frappe.db.get_value(
        "Seller KPI",
        {
            "seller": seller,
            "kpi_period": kpi_period,
            "start_date": start_date,
            "end_date": end_date
        },
        "name"
    )

    if existing_kpi:
        kpi_doc = frappe.get_doc("Seller KPI", existing_kpi)
    else:
        kpi_doc = frappe.new_doc("Seller KPI")
        kpi_doc.seller = seller
        kpi_doc.tenant = tenant
        kpi_doc.kpi_period = kpi_period
        kpi_doc.start_date = start_date
        kpi_doc.end_date = end_date

    kpi_doc.status = "Calculating"
    kpi_doc.save(ignore_permissions=True)

    try:
        # Calculate order metrics
        order_metrics = get_seller_order_metrics(seller, start_date, end_date)
        kpi_doc.total_orders = order_metrics.get("total_orders", 0)
        kpi_doc.total_revenue = order_metrics.get("total_revenue", 0)
        kpi_doc.average_order_value = order_metrics.get("average_order_value", 0)
        kpi_doc.fulfillment_rate = order_metrics.get("fulfillment_rate", 100)
        kpi_doc.on_time_delivery_rate = order_metrics.get("on_time_delivery_rate", 100)
        kpi_doc.return_rate = order_metrics.get("return_rate", 0)
        kpi_doc.cancellation_rate = order_metrics.get("cancellation_rate", 0)
        kpi_doc.refund_rate = order_metrics.get("refund_rate", 0)

        # Calculate customer metrics
        customer_metrics = get_seller_customer_metrics(seller, start_date, end_date)
        kpi_doc.total_customers = customer_metrics.get("total_customers", 0)
        kpi_doc.repeat_customers = customer_metrics.get("repeat_customers", 0)
        kpi_doc.customer_retention_rate = customer_metrics.get("customer_retention_rate", 0)

        # Calculate review metrics
        review_metrics = get_seller_review_metrics(seller, start_date, end_date)
        kpi_doc.average_rating = review_metrics.get("average_rating", 0)
        kpi_doc.total_reviews = review_metrics.get("total_reviews", 0)
        kpi_doc.positive_review_rate = review_metrics.get("positive_review_rate", 100)

        # Calculate issue metrics
        issue_metrics = get_seller_issue_metrics(seller, start_date, end_date)
        kpi_doc.complaint_rate = issue_metrics.get("complaint_rate", 0)
        kpi_doc.dispute_rate = issue_metrics.get("dispute_rate", 0)
        kpi_doc.resolution_rate = issue_metrics.get("resolution_rate", 100)
        kpi_doc.response_time_hours = issue_metrics.get("response_time_hours", 24)

        # Calculate overall KPI score
        kpi_doc.kpi_score = calculate_kpi_score(kpi_doc)

        kpi_doc.status = "Calculated"
        kpi_doc.calculated_at = now_datetime()
        kpi_doc.save(ignore_permissions=True)

        return kpi_doc.name

    except Exception as e:
        kpi_doc.status = "Failed"
        kpi_doc.notes = f"Calculation failed: {str(e)}"
        kpi_doc.save(ignore_permissions=True)
        raise


def get_seller_order_metrics(seller, start_date, end_date):
    """
    Calculate order-related metrics for a seller.

    Returns dict with:
    - total_orders
    - total_revenue
    - average_order_value
    - fulfillment_rate
    - on_time_delivery_rate
    - return_rate
    - cancellation_rate
    - refund_rate
    """
    metrics = {
        "total_orders": 0,
        "total_revenue": 0,
        "average_order_value": 0,
        "fulfillment_rate": 100,
        "on_time_delivery_rate": 100,
        "return_rate": 0,
        "cancellation_rate": 0,
        "refund_rate": 0
    }

    # Get total orders and revenue from Sub Orders (seller-specific orders)
    order_data = frappe.db.sql("""
        SELECT
            COUNT(*) as total_orders,
            COALESCE(SUM(grand_total), 0) as total_revenue,
            COALESCE(AVG(grand_total), 0) as average_order_value,
            SUM(CASE WHEN status = 'Delivered' THEN 1 ELSE 0 END) as delivered_orders,
            SUM(CASE WHEN status = 'Cancelled' THEN 1 ELSE 0 END) as cancelled_orders,
            SUM(CASE WHEN status = 'Returned' THEN 1 ELSE 0 END) as returned_orders,
            SUM(CASE WHEN status = 'Refunded' THEN 1 ELSE 0 END) as refunded_orders
        FROM `tabSub Order`
        WHERE seller = %(seller)s
        AND creation BETWEEN %(start_date)s AND %(end_date)s
    """, {
        "seller": seller,
        "start_date": start_date,
        "end_date": end_date
    }, as_dict=True)

    if order_data and order_data[0]["total_orders"]:
        data = order_data[0]
        total = data["total_orders"]
        metrics["total_orders"] = total
        metrics["total_revenue"] = data["total_revenue"] or 0
        metrics["average_order_value"] = data["average_order_value"] or 0

        if total > 0:
            delivered = data["delivered_orders"] or 0
            cancelled = data["cancelled_orders"] or 0
            returned = data["returned_orders"] or 0
            refunded = data["refunded_orders"] or 0

            # Fulfillment rate = (Delivered + Returned + Refunded) / Total (excludes cancelled)
            fulfilled = total - cancelled
            if total > 0:
                metrics["fulfillment_rate"] = round((fulfilled / total) * 100, 2)
                metrics["cancellation_rate"] = round((cancelled / total) * 100, 2)
                metrics["return_rate"] = round((returned / total) * 100, 2)
                metrics["refund_rate"] = round((refunded / total) * 100, 2)

    # Calculate on-time delivery rate from shipments
    delivery_data = frappe.db.sql("""
        SELECT
            COUNT(*) as total_shipments,
            SUM(CASE WHEN delivered_at <= expected_delivery_date THEN 1 ELSE 0 END) as on_time_deliveries
        FROM `tabMarketplace Shipment`
        WHERE seller = %(seller)s
        AND status = 'Delivered'
        AND creation BETWEEN %(start_date)s AND %(end_date)s
    """, {
        "seller": seller,
        "start_date": start_date,
        "end_date": end_date
    }, as_dict=True)

    if delivery_data and delivery_data[0]["total_shipments"]:
        data = delivery_data[0]
        if data["total_shipments"] > 0:
            on_time = data["on_time_deliveries"] or 0
            metrics["on_time_delivery_rate"] = round(
                (on_time / data["total_shipments"]) * 100, 2
            )

    return metrics


def get_seller_customer_metrics(seller, start_date, end_date):
    """
    Calculate customer-related metrics for a seller.

    Returns dict with:
    - total_customers
    - repeat_customers
    - customer_retention_rate
    """
    metrics = {
        "total_customers": 0,
        "repeat_customers": 0,
        "customer_retention_rate": 0
    }

    # Get unique customers from Sub Orders
    customer_data = frappe.db.sql("""
        SELECT
            COUNT(DISTINCT buyer) as total_customers,
            SUM(CASE WHEN order_count > 1 THEN 1 ELSE 0 END) as repeat_customers
        FROM (
            SELECT
                buyer,
                COUNT(*) as order_count
            FROM `tabSub Order`
            WHERE seller = %(seller)s
            AND creation BETWEEN %(start_date)s AND %(end_date)s
            GROUP BY buyer
        ) as customer_orders
    """, {
        "seller": seller,
        "start_date": start_date,
        "end_date": end_date
    }, as_dict=True)

    if customer_data and customer_data[0]["total_customers"]:
        data = customer_data[0]
        total = data["total_customers"]
        repeat = data["repeat_customers"] or 0
        metrics["total_customers"] = total
        metrics["repeat_customers"] = repeat
        if total > 0:
            metrics["customer_retention_rate"] = round((repeat / total) * 100, 2)

    return metrics


def get_seller_review_metrics(seller, start_date, end_date):
    """
    Calculate review-related metrics for a seller.

    Returns dict with:
    - average_rating
    - total_reviews
    - positive_review_rate (4+ stars)
    """
    metrics = {
        "average_rating": 0,
        "total_reviews": 0,
        "positive_review_rate": 100
    }

    # Get review data
    review_data = frappe.db.sql("""
        SELECT
            COUNT(*) as total_reviews,
            COALESCE(AVG(rating), 0) as average_rating,
            SUM(CASE WHEN rating >= 4 THEN 1 ELSE 0 END) as positive_reviews
        FROM `tabReview`
        WHERE seller = %(seller)s
        AND status = 'Approved'
        AND creation BETWEEN %(start_date)s AND %(end_date)s
    """, {
        "seller": seller,
        "start_date": start_date,
        "end_date": end_date
    }, as_dict=True)

    if review_data and review_data[0]["total_reviews"]:
        data = review_data[0]
        total = data["total_reviews"]
        metrics["total_reviews"] = total
        metrics["average_rating"] = round(data["average_rating"] or 0, 2)
        if total > 0:
            positive = data["positive_reviews"] or 0
            metrics["positive_review_rate"] = round((positive / total) * 100, 2)

    return metrics


def get_seller_issue_metrics(seller, start_date, end_date):
    """
    Calculate issue-related metrics for a seller.

    Returns dict with:
    - complaint_rate
    - dispute_rate
    - resolution_rate
    - response_time_hours
    """
    metrics = {
        "complaint_rate": 0,
        "dispute_rate": 0,
        "resolution_rate": 100,
        "response_time_hours": 24
    }

    # Get total orders for rate calculations
    total_orders = frappe.db.count(
        "Sub Order",
        {
            "seller": seller,
            "creation": ["between", [start_date, end_date]]
        }
    )

    if total_orders == 0:
        return metrics

    # Get dispute/complaint data from Moderation Case if exists
    try:
        dispute_data = frappe.db.sql("""
            SELECT
                COUNT(*) as total_disputes,
                SUM(CASE WHEN status = 'Resolved' THEN 1 ELSE 0 END) as resolved_disputes
            FROM `tabModeration Case`
            WHERE content_owner = %(seller)s
            AND creation BETWEEN %(start_date)s AND %(end_date)s
        """, {
            "seller": seller,
            "start_date": start_date,
            "end_date": end_date
        }, as_dict=True)

        if dispute_data and dispute_data[0]["total_disputes"]:
            data = dispute_data[0]
            total_disputes = data["total_disputes"]
            metrics["dispute_rate"] = round((total_disputes / total_orders) * 100, 2)
            if total_disputes > 0:
                resolved = data["resolved_disputes"] or 0
                metrics["resolution_rate"] = round((resolved / total_disputes) * 100, 2)
    except Exception:
        # Moderation Case table may not exist
        pass

    # Calculate average response time (placeholder - would need message tracking)
    # For now, use default 24 hours
    metrics["response_time_hours"] = 24

    return metrics


def calculate_kpi_score(kpi_doc):
    """
    Calculate overall KPI score (0-100) based on weighted metrics.

    Weights:
    - Fulfillment Rate: 20%
    - On-Time Delivery: 20%
    - Average Rating: 25%
    - Customer Retention: 15%
    - Issue Resolution: 10%
    - Low Return/Cancellation: 10%
    """
    score = 0

    # Fulfillment Rate (20%)
    score += (kpi_doc.fulfillment_rate or 100) * 0.20

    # On-Time Delivery Rate (20%)
    score += (kpi_doc.on_time_delivery_rate or 100) * 0.20

    # Average Rating (25%) - Convert 5-star to 100-point scale
    rating_score = ((kpi_doc.average_rating or 0) / 5) * 100
    score += rating_score * 0.25

    # Customer Retention Rate (15%)
    score += (kpi_doc.customer_retention_rate or 0) * 0.15

    # Resolution Rate (10%)
    score += (kpi_doc.resolution_rate or 100) * 0.10

    # Low Return/Cancellation (10%) - Inverse of return + cancellation rate
    negative_rate = (kpi_doc.return_rate or 0) + (kpi_doc.cancellation_rate or 0)
    score += max(0, 100 - negative_rate) * 0.10

    return round(score, 2)


def recalculate_seller_rankings():
    """
    Recalculate seller rankings based on KPI scores.
    Runs daily to update seller rankings based on their latest KPI scores.
    """
    frappe.logger().info("Running recalculate_seller_rankings task")

    today = getdate(nowdate())
    updated_count = 0

    # Get the latest monthly KPI for each seller
    latest_kpis = frappe.db.sql("""
        SELECT sk.name, sk.seller, sk.kpi_score
        FROM `tabSeller KPI` sk
        INNER JOIN (
            SELECT seller, MAX(end_date) as max_date
            FROM `tabSeller KPI`
            WHERE kpi_period = 'Monthly'
            AND status = 'Calculated'
            GROUP BY seller
        ) latest ON sk.seller = latest.seller AND sk.end_date = latest.max_date
        WHERE sk.kpi_period = 'Monthly'
        AND sk.status = 'Calculated'
        ORDER BY sk.kpi_score DESC
    """, as_dict=True)

    # Update rankings
    for rank, kpi in enumerate(latest_kpis, start=1):
        try:
            frappe.db.set_value(
                "Seller KPI", kpi.name,
                "rank", rank,
                update_modified=False
            )
            updated_count += 1

        except Exception as e:
            frappe.log_error(
                message=f"Error updating rank for KPI {kpi.name}: {str(e)}",
                title="Seller Ranking Update Error"
            )

    frappe.db.commit()
    frappe.logger().info(
        f"Completed recalculate_seller_rankings task: {updated_count} rankings updated"
    )

    return updated_count


def update_kpi_trends():
    """
    Update KPI trends by comparing to previous periods.
    Determines if a seller's KPI score is Improving, Stable, or Declining.
    """
    frappe.logger().info("Running update_kpi_trends task")

    updated_count = 0

    # Get KPIs that need trend analysis
    kpis = frappe.db.sql("""
        SELECT name, seller, kpi_period, kpi_score, start_date, end_date
        FROM `tabSeller KPI`
        WHERE status = 'Calculated'
        AND score_trend = 'Stable'
    """, as_dict=True)

    for kpi in kpis:
        try:
            # Find previous period KPI
            previous_kpi = get_previous_period_kpi(
                kpi.seller,
                kpi.kpi_period,
                kpi.start_date
            )

            if previous_kpi:
                current_score = kpi.kpi_score or 0
                previous_score = previous_kpi.get("kpi_score") or 0

                # Determine trend (5% threshold for change)
                threshold = 5
                if current_score > previous_score + threshold:
                    trend = "Improving"
                elif current_score < previous_score - threshold:
                    trend = "Declining"
                else:
                    trend = "Stable"

                frappe.db.set_value(
                    "Seller KPI", kpi.name,
                    "score_trend", trend,
                    update_modified=False
                )
                updated_count += 1

        except Exception as e:
            frappe.log_error(
                message=f"Error updating trend for KPI {kpi.name}: {str(e)}",
                title="KPI Trend Update Error"
            )

    frappe.db.commit()
    frappe.logger().info(
        f"Completed update_kpi_trends task: {updated_count} trends updated"
    )

    return updated_count


def get_previous_period_kpi(seller, kpi_period, current_start_date):
    """
    Get the previous period's KPI for comparison.

    Args:
        seller: Seller Profile name
        kpi_period: Period type (Daily, Weekly, Monthly, etc.)
        current_start_date: Start date of current period

    Returns:
        Dict with previous KPI data or None
    """
    # Calculate previous period dates
    if kpi_period == "Daily":
        previous_end = add_days(current_start_date, -1)
    elif kpi_period == "Weekly":
        previous_end = add_days(current_start_date, -1)
    elif kpi_period == "Monthly":
        previous_end = add_days(current_start_date, -1)
    elif kpi_period == "Quarterly":
        previous_end = add_days(current_start_date, -1)
    elif kpi_period == "Yearly":
        previous_end = add_days(current_start_date, -1)
    else:
        return None

    return frappe.db.get_value(
        "Seller KPI",
        {
            "seller": seller,
            "kpi_period": kpi_period,
            "end_date": previous_end,
            "status": "Calculated"
        },
        ["name", "kpi_score"],
        as_dict=True
    )


def calculate_buyer_kpis():
    """
    Calculate KPI metrics for buyers (platform-wide and seller-specific).
    Creates or updates Buyer KPI records for active buyers.
    Runs daily to maintain buyer statistics.
    """
    frappe.logger().info("Running calculate_buyer_kpis task")

    today = getdate(nowdate())
    first_of_month = today.replace(day=1)
    processed_count = 0

    # Get all buyers who have made purchases
    buyers = frappe.db.sql("""
        SELECT DISTINCT buyer
        FROM `tabMarketplace Order`
        WHERE buyer IS NOT NULL
        AND creation >= %(start_date)s
    """, {"start_date": add_months(today, -12)}, as_dict=True)

    for buyer in buyers:
        try:
            # Calculate buyer metrics
            buyer_metrics = calculate_buyer_metrics(buyer.buyer, first_of_month, today)

            # Update Buyer Profile if metrics exist
            if buyer_metrics.get("total_orders", 0) > 0:
                update_buyer_profile_stats(buyer.buyer, buyer_metrics)
                processed_count += 1

        except Exception as e:
            frappe.log_error(
                message=f"Error calculating KPI for buyer {buyer.buyer}: {str(e)}",
                title="Buyer KPI Calculation Error"
            )

    frappe.db.commit()
    frappe.logger().info(
        f"Completed calculate_buyer_kpis task: {processed_count} buyers processed"
    )

    return processed_count


def calculate_buyer_metrics(buyer, start_date, end_date):
    """
    Calculate metrics for a specific buyer.

    Returns dict with buyer statistics.
    """
    metrics = {
        "total_orders": 0,
        "total_spent": 0,
        "average_order_value": 0,
        "order_frequency": 0,
        "payment_reliability": 100,
        "dispute_rate": 0
    }

    # Get order statistics
    order_data = frappe.db.sql("""
        SELECT
            COUNT(*) as total_orders,
            COALESCE(SUM(grand_total), 0) as total_spent,
            COALESCE(AVG(grand_total), 0) as average_order_value,
            MIN(creation) as first_order,
            MAX(creation) as last_order
        FROM `tabMarketplace Order`
        WHERE buyer = %(buyer)s
        AND creation BETWEEN %(start_date)s AND %(end_date)s
    """, {
        "buyer": buyer,
        "start_date": start_date,
        "end_date": end_date
    }, as_dict=True)

    if order_data and order_data[0]["total_orders"]:
        data = order_data[0]
        metrics["total_orders"] = data["total_orders"]
        metrics["total_spent"] = data["total_spent"] or 0
        metrics["average_order_value"] = data["average_order_value"] or 0

        # Calculate order frequency (orders per month)
        if data["first_order"] and data["last_order"]:
            days_diff = date_diff(data["last_order"], data["first_order"]) or 1
            months = max(days_diff / 30, 1)
            metrics["order_frequency"] = round(data["total_orders"] / months, 2)

    return metrics


def update_buyer_profile_stats(buyer, metrics):
    """
    Update buyer profile with calculated statistics.
    """
    try:
        # Check if Buyer Profile exists
        buyer_profile = frappe.db.get_value(
            "Buyer Profile",
            {"user": buyer},
            "name"
        )

        if buyer_profile:
            frappe.db.set_value(
                "Buyer Profile", buyer_profile,
                {
                    "total_orders": metrics.get("total_orders", 0),
                    "total_spent": metrics.get("total_spent", 0),
                    "average_order_value": metrics.get("average_order_value", 0)
                },
                update_modified=False
            )
    except Exception:
        # Fields may not exist in Buyer Profile
        pass


# ==================== API Methods ====================

@frappe.whitelist()
def run_kpi_calculations():
    """
    Run all KPI calculation tasks manually.
    This is a whitelisted method that can be called by administrators.
    """
    if not frappe.has_permission("Seller KPI", "write"):
        frappe.throw(_("You don't have permission to run KPI calculations"))

    results = {
        "daily_seller_kpis": calculate_daily_seller_kpis(),
        "rankings_updated": recalculate_seller_rankings(),
        "trends_updated": update_kpi_trends(),
        "buyer_kpis": calculate_buyer_kpis()
    }

    frappe.msgprint(_(
        "KPI calculations completed: "
        "{0} seller KPIs calculated, "
        "{1} rankings updated, "
        "{2} trends updated, "
        "{3} buyer KPIs calculated"
    ).format(
        results["daily_seller_kpis"],
        results["rankings_updated"],
        results["trends_updated"],
        results["buyer_kpis"]
    ))

    return results


@frappe.whitelist()
def calculate_single_seller_kpi(seller, kpi_period="Monthly"):
    """
    Calculate KPI for a single seller on demand.

    Args:
        seller: Seller Profile name
        kpi_period: Period type (Daily, Weekly, Monthly, Quarterly, Yearly)

    Returns:
        Seller KPI document name
    """
    if not frappe.has_permission("Seller KPI", "write"):
        frappe.throw(_("You don't have permission to calculate KPIs"))

    today = getdate(nowdate())

    # Determine date range based on period
    if kpi_period == "Daily":
        start_date = today
        end_date = today
    elif kpi_period == "Weekly":
        start_date = add_days(today, -7)
        end_date = today
    elif kpi_period == "Monthly":
        start_date = today.replace(day=1)
        end_date = today
    elif kpi_period == "Quarterly":
        quarter_start_month = ((today.month - 1) // 3) * 3 + 1
        start_date = today.replace(month=quarter_start_month, day=1)
        end_date = today
    elif kpi_period == "Yearly":
        start_date = today.replace(month=1, day=1)
        end_date = today
    else:
        frappe.throw(_("Invalid KPI period: {0}").format(kpi_period))

    # Get tenant from seller
    tenant = frappe.db.get_value("Seller Profile", seller, "tenant")

    kpi_name = calculate_seller_kpi_metrics(
        seller, tenant, start_date, end_date, kpi_period
    )

    frappe.msgprint(_(
        "KPI calculated successfully for {0} ({1})"
    ).format(seller, kpi_period))

    return kpi_name


@frappe.whitelist()
def get_kpi_statistics():
    """
    Get KPI statistics for dashboard.
    Returns summary of KPI data across all sellers.
    """
    stats = {}

    # Count KPIs by status
    for status in ["Draft", "Calculating", "Calculated", "Failed"]:
        count = frappe.db.count("Seller KPI", filters={"status": status})
        stats[f"status_{status.lower()}"] = count

    # Get average KPI score
    avg_score = frappe.db.sql("""
        SELECT COALESCE(AVG(kpi_score), 0) as avg_score
        FROM `tabSeller KPI`
        WHERE status = 'Calculated'
        AND kpi_period = 'Monthly'
    """, as_dict=True)

    stats["average_kpi_score"] = round(avg_score[0]["avg_score"] if avg_score else 0, 2)

    # Get top performers
    top_sellers = frappe.db.sql("""
        SELECT seller, seller_name, kpi_score, rank
        FROM `tabSeller KPI`
        WHERE status = 'Calculated'
        AND kpi_period = 'Monthly'
        ORDER BY kpi_score DESC
        LIMIT 10
    """, as_dict=True)

    stats["top_sellers"] = top_sellers

    return stats

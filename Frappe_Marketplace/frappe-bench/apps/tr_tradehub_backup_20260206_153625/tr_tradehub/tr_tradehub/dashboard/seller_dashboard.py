# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

"""
Seller Dashboard API Endpoints for TR-TradeHub Marketplace

This module provides comprehensive dashboard APIs for sellers including:
- Sales metrics (GMV, order count, average order value)
- Sales trend charts (daily, weekly, monthly)
- Order status breakdown
- Top-selling products
- Recent orders list
- Performance summary
- Category performance analytics
- Revenue breakdown
- Customer insights
- Payout summary
- Conversion metrics

API URL Pattern:
    POST /api/method/tr_tradehub.dashboard.seller_dashboard.<function_name>

All endpoints require authentication and seller profile.
Data is scoped to the authenticated seller's profile.
"""

from typing import Any, Dict, List, Optional
from datetime import datetime, timedelta

import frappe
from frappe import _
from frappe.utils import (
    cint,
    cstr,
    flt,
    getdate,
    nowdate,
    now_datetime,
    add_days,
    add_months,
    get_datetime,
    get_first_day,
    get_last_day,
    date_diff,
    get_datetime_str,
    formatdate,
    fmt_money,
)


# =============================================================================
# CONSTANTS & CONFIGURATION
# =============================================================================

# Cache TTL for dashboard data (in seconds)
CACHE_TTL = {
    "metrics": 300,  # 5 minutes
    "charts": 600,  # 10 minutes
    "top_products": 900,  # 15 minutes
    "recent_orders": 60,  # 1 minute
}

# Date range options
DATE_RANGES = {
    "today": 0,
    "yesterday": 1,
    "last_7_days": 7,
    "last_30_days": 30,
    "last_90_days": 90,
    "this_month": "this_month",
    "last_month": "last_month",
    "this_quarter": "this_quarter",
    "this_year": "this_year",
    "all_time": None,
}

# Default chart colors for TR-TradeHub theme
CHART_COLORS = {
    "primary": "#7C3AED",  # Purple
    "success": "#10B981",  # Green
    "warning": "#F59E0B",  # Amber
    "danger": "#EF4444",  # Red
    "info": "#3B82F6",  # Blue
    "secondary": "#6B7280",  # Gray
}


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================


def get_current_seller() -> Optional[str]:
    """
    Get current seller profile for authenticated user.

    Returns:
        Seller Profile name or None if not a seller
    """
    if not frappe.session.user or frappe.session.user == "Guest":
        return None

    seller = frappe.db.get_value(
        "Seller Profile",
        {"user": frappe.session.user, "status": ["!=", "Deleted"]},
        "name",
    )
    return seller


def require_seller(func):
    """Decorator to require seller profile for dashboard endpoints."""
    def wrapper(*args, **kwargs):
        seller = kwargs.get("seller") or get_current_seller()
        if not seller:
            frappe.throw(
                _("You must be a seller to access this dashboard"),
                frappe.PermissionError,
            )

        # Check if seller exists and is active
        if not frappe.db.exists("Seller Profile", seller):
            frappe.throw(
                _("Seller profile not found"),
                frappe.DoesNotExistError,
            )

        seller_status = frappe.db.get_value("Seller Profile", seller, "status")
        if seller_status in ["Suspended", "Banned", "Deleted"]:
            frappe.throw(
                _("Your seller account is {0}").format(seller_status),
                frappe.PermissionError,
            )

        kwargs["seller"] = seller
        return func(*args, **kwargs)

    return wrapper


def get_date_range(
    range_type: str = "last_30_days",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> tuple:
    """
    Get start and end dates based on range type.

    Args:
        range_type: Predefined range type or "custom"
        start_date: Custom start date (for range_type="custom")
        end_date: Custom end date (for range_type="custom")

    Returns:
        Tuple of (start_date, end_date) as strings
    """
    today = getdate(nowdate())

    if range_type == "custom" and start_date and end_date:
        return getdate(start_date), getdate(end_date)

    if range_type == "today":
        return today, today
    elif range_type == "yesterday":
        yesterday = add_days(today, -1)
        return yesterday, yesterday
    elif range_type == "last_7_days":
        return add_days(today, -6), today
    elif range_type == "last_30_days":
        return add_days(today, -29), today
    elif range_type == "last_90_days":
        return add_days(today, -89), today
    elif range_type == "this_month":
        return get_first_day(today), today
    elif range_type == "last_month":
        last_month = add_months(today, -1)
        return get_first_day(last_month), get_last_day(last_month)
    elif range_type == "this_quarter":
        quarter_start_month = ((today.month - 1) // 3) * 3 + 1
        quarter_start = today.replace(month=quarter_start_month, day=1)
        return quarter_start, today
    elif range_type == "this_year":
        return today.replace(month=1, day=1), today
    elif range_type == "all_time":
        return None, today
    else:
        # Default to last 30 days
        return add_days(today, -29), today


def get_cache_key(prefix: str, seller: str, **kwargs) -> str:
    """Generate cache key for dashboard data."""
    import hashlib

    key_parts = [prefix, seller]
    for k, v in sorted(kwargs.items()):
        key_parts.append(f"{k}:{v}")
    key_string = ":".join(key_parts)
    return f"seller_dashboard:{hashlib.md5(key_string.encode()).hexdigest()}"


def get_cached_data(cache_key: str) -> Optional[Dict]:
    """Get cached data if available."""
    return frappe.cache().get_value(cache_key)


def set_cached_data(cache_key: str, data: Dict, ttl: int):
    """Set data in cache with TTL."""
    frappe.cache().set_value(cache_key, data, expires_in_sec=ttl)


def format_currency_value(value: float, currency: str = "TRY") -> str:
    """Format value as currency string."""
    return fmt_money(flt(value), currency=currency)


def calculate_percentage_change(current: float, previous: float) -> float:
    """Calculate percentage change between two values."""
    if previous == 0:
        return 100.0 if current > 0 else 0.0
    return round(((current - previous) / previous) * 100, 2)


# =============================================================================
# MAIN DASHBOARD API
# =============================================================================


@frappe.whitelist()
def get_seller_dashboard(
    range_type: str = "last_30_days",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    seller: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Get complete seller dashboard data.

    This is the main endpoint that returns all dashboard components.
    Can be called directly or individual components can be fetched separately.

    Args:
        range_type: Date range type (e.g., "last_30_days", "this_month")
        start_date: Custom start date
        end_date: Custom end date
        seller: Seller profile (auto-detected if not provided)

    Returns:
        Dict containing all dashboard data:
        - metrics: Key performance metrics
        - sales_trend: Sales over time chart data
        - order_status: Order status breakdown
        - top_products: Best-selling products
        - recent_orders: Latest orders
        - performance: Performance summary
        - category_performance: Sales by category
        - payout_summary: Payout information
    """
    seller = seller or get_current_seller()
    if not seller:
        frappe.throw(
            _("Seller profile required"),
            frappe.PermissionError,
        )

    # Check cache
    cache_key = get_cache_key(
        "dashboard", seller, range_type=range_type, start=start_date, end=end_date
    )
    cached = get_cached_data(cache_key)
    if cached:
        return cached

    # Get date range
    start, end = get_date_range(range_type, start_date, end_date)

    # Build dashboard data
    dashboard = {
        "metrics": get_sales_metrics(
            range_type=range_type,
            start_date=start_date,
            end_date=end_date,
            seller=seller,
        ),
        "sales_trend": get_sales_trend_chart(
            range_type=range_type,
            start_date=start_date,
            end_date=end_date,
            seller=seller,
        ),
        "order_status": get_order_status_chart(
            range_type=range_type,
            start_date=start_date,
            end_date=end_date,
            seller=seller,
        ),
        "top_products": get_top_products(
            range_type=range_type,
            start_date=start_date,
            end_date=end_date,
            seller=seller,
            limit=5,
        ),
        "recent_orders": get_recent_orders(
            seller=seller,
            limit=10,
        ),
        "performance": get_performance_summary(seller=seller),
        "category_performance": get_category_performance(
            range_type=range_type,
            start_date=start_date,
            end_date=end_date,
            seller=seller,
        ),
        "payout_summary": get_payout_summary(seller=seller),
        "date_range": {
            "type": range_type,
            "start_date": str(start) if start else None,
            "end_date": str(end) if end else None,
            "display": _get_date_range_display(range_type, start, end),
        },
    }

    # Cache the result
    set_cached_data(cache_key, dashboard, CACHE_TTL["metrics"])

    return dashboard


def _get_date_range_display(
    range_type: str, start: Optional[datetime], end: Optional[datetime]
) -> str:
    """Get human-readable date range display string."""
    if range_type == "today":
        return _("Today")
    elif range_type == "yesterday":
        return _("Yesterday")
    elif range_type == "last_7_days":
        return _("Last 7 days")
    elif range_type == "last_30_days":
        return _("Last 30 days")
    elif range_type == "last_90_days":
        return _("Last 90 days")
    elif range_type == "this_month":
        return _("This Month")
    elif range_type == "last_month":
        return _("Last Month")
    elif range_type == "this_quarter":
        return _("This Quarter")
    elif range_type == "this_year":
        return _("This Year")
    elif range_type == "all_time":
        return _("All Time")
    elif start and end:
        return f"{formatdate(start)} - {formatdate(end)}"
    else:
        return _("Custom Range")


# =============================================================================
# SALES METRICS
# =============================================================================


@frappe.whitelist()
def get_sales_metrics(
    range_type: str = "last_30_days",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    seller: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Get key sales metrics for seller dashboard.

    Returns:
        Dict containing:
        - total_sales: Total sales amount (GMV)
        - order_count: Number of orders
        - average_order_value: Average order value
        - units_sold: Total units sold
        - total_commission: Commission paid
        - net_earnings: Net earnings after commission
        - comparison: Period-over-period comparison
    """
    seller = seller or get_current_seller()
    if not seller:
        return _empty_metrics()

    start, end = get_date_range(range_type, start_date, end_date)

    # Build date filter
    date_filter = ""
    date_params = {"seller": seller}
    if start:
        date_filter = "AND so.order_date >= %(start_date)s"
        date_params["start_date"] = start
    if end:
        date_filter += " AND so.order_date <= %(end_date)s"
        date_params["end_date"] = end

    # Get current period metrics
    metrics = frappe.db.sql(
        f"""
        SELECT
            COUNT(so.name) as order_count,
            COALESCE(SUM(so.grand_total), 0) as total_sales,
            COALESCE(AVG(so.grand_total), 0) as average_order_value,
            COALESCE(SUM(so.commission_amount), 0) as total_commission,
            COALESCE(SUM(so.seller_payout), 0) as net_earnings,
            COALESCE(SUM(
                (SELECT COALESCE(SUM(soi.quantity), 0)
                 FROM `tabSub Order Item` soi
                 WHERE soi.parent = so.name)
            ), 0) as units_sold
        FROM `tabSub Order` so
        WHERE so.seller = %(seller)s
        AND so.status NOT IN ('Cancelled', 'Draft')
        {date_filter}
    """,
        date_params,
        as_dict=True,
    )

    current = metrics[0] if metrics else _empty_metrics_row()

    # Calculate comparison period
    comparison = _get_comparison_metrics(seller, start, end, range_type)

    # Get currency from seller profile
    currency = frappe.db.get_value("Seller Profile", seller, "currency") or "TRY"

    return {
        "total_sales": flt(current.total_sales, 2),
        "total_sales_formatted": format_currency_value(current.total_sales, currency),
        "order_count": cint(current.order_count),
        "average_order_value": flt(current.average_order_value, 2),
        "average_order_value_formatted": format_currency_value(
            current.average_order_value, currency
        ),
        "units_sold": cint(current.units_sold),
        "total_commission": flt(current.total_commission, 2),
        "total_commission_formatted": format_currency_value(
            current.total_commission, currency
        ),
        "net_earnings": flt(current.net_earnings, 2),
        "net_earnings_formatted": format_currency_value(current.net_earnings, currency),
        "currency": currency,
        "comparison": comparison,
    }


def _empty_metrics() -> Dict[str, Any]:
    """Return empty metrics structure."""
    return {
        "total_sales": 0,
        "total_sales_formatted": format_currency_value(0),
        "order_count": 0,
        "average_order_value": 0,
        "average_order_value_formatted": format_currency_value(0),
        "units_sold": 0,
        "total_commission": 0,
        "total_commission_formatted": format_currency_value(0),
        "net_earnings": 0,
        "net_earnings_formatted": format_currency_value(0),
        "currency": "TRY",
        "comparison": {
            "total_sales_change": 0,
            "order_count_change": 0,
            "average_order_value_change": 0,
        },
    }


def _empty_metrics_row():
    """Return empty metrics row with proper structure."""
    class EmptyRow:
        total_sales = 0
        order_count = 0
        average_order_value = 0
        total_commission = 0
        net_earnings = 0
        units_sold = 0
    return EmptyRow()


def _get_comparison_metrics(
    seller: str,
    start: Optional[datetime],
    end: Optional[datetime],
    range_type: str,
) -> Dict[str, float]:
    """Get comparison metrics for previous period."""
    if not start or range_type == "all_time":
        return {
            "total_sales_change": 0,
            "order_count_change": 0,
            "average_order_value_change": 0,
        }

    # Calculate previous period dates
    period_days = date_diff(end, start) + 1
    prev_end = add_days(start, -1)
    prev_start = add_days(prev_end, -(period_days - 1))

    # Get previous period metrics
    prev_metrics = frappe.db.sql(
        """
        SELECT
            COUNT(so.name) as order_count,
            COALESCE(SUM(so.grand_total), 0) as total_sales,
            COALESCE(AVG(so.grand_total), 0) as average_order_value
        FROM `tabSub Order` so
        WHERE so.seller = %(seller)s
        AND so.status NOT IN ('Cancelled', 'Draft')
        AND so.order_date >= %(start_date)s
        AND so.order_date <= %(end_date)s
    """,
        {
            "seller": seller,
            "start_date": prev_start,
            "end_date": prev_end,
        },
        as_dict=True,
    )

    # Get current period metrics for comparison
    curr_metrics = frappe.db.sql(
        """
        SELECT
            COUNT(so.name) as order_count,
            COALESCE(SUM(so.grand_total), 0) as total_sales,
            COALESCE(AVG(so.grand_total), 0) as average_order_value
        FROM `tabSub Order` so
        WHERE so.seller = %(seller)s
        AND so.status NOT IN ('Cancelled', 'Draft')
        AND so.order_date >= %(start_date)s
        AND so.order_date <= %(end_date)s
    """,
        {
            "seller": seller,
            "start_date": start,
            "end_date": end,
        },
        as_dict=True,
    )

    prev = prev_metrics[0] if prev_metrics else _empty_metrics_row()
    curr = curr_metrics[0] if curr_metrics else _empty_metrics_row()

    return {
        "total_sales_change": calculate_percentage_change(
            flt(curr.total_sales), flt(prev.total_sales)
        ),
        "order_count_change": calculate_percentage_change(
            flt(curr.order_count), flt(prev.order_count)
        ),
        "average_order_value_change": calculate_percentage_change(
            flt(curr.average_order_value), flt(prev.average_order_value)
        ),
        "previous_period": {
            "start": str(prev_start),
            "end": str(prev_end),
        },
    }


# =============================================================================
# CHART DATA
# =============================================================================


@frappe.whitelist()
def get_sales_trend_chart(
    range_type: str = "last_30_days",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    seller: Optional[str] = None,
    granularity: str = "daily",
) -> Dict[str, Any]:
    """
    Get sales trend chart data.

    Args:
        range_type: Date range type
        start_date: Custom start date
        end_date: Custom end date
        seller: Seller profile
        granularity: Data granularity ("daily", "weekly", "monthly")

    Returns:
        Chart-ready data structure:
        - labels: Date labels
        - datasets: Array of data series
    """
    seller = seller or get_current_seller()
    if not seller:
        return _empty_chart_data()

    start, end = get_date_range(range_type, start_date, end_date)

    # Determine granularity based on date range
    if not start:
        granularity = "monthly"
    else:
        days = date_diff(end, start)
        if days > 90:
            granularity = "monthly"
        elif days > 14:
            granularity = "weekly" if granularity == "daily" else granularity

    # Build date grouping SQL
    if granularity == "monthly":
        date_group = "DATE_FORMAT(so.order_date, '%Y-%m')"
        date_format = "%Y-%m"
    elif granularity == "weekly":
        date_group = "YEARWEEK(so.order_date, 1)"
        date_format = "%Y-W%V"
    else:
        date_group = "DATE(so.order_date)"
        date_format = "%Y-%m-%d"

    # Build date filter
    date_filter = ""
    date_params = {"seller": seller}
    if start:
        date_filter = "AND so.order_date >= %(start_date)s"
        date_params["start_date"] = start
    if end:
        date_filter += " AND so.order_date <= %(end_date)s"
        date_params["end_date"] = end

    # Get sales data
    data = frappe.db.sql(
        f"""
        SELECT
            {date_group} as period,
            DATE(MIN(so.order_date)) as period_start,
            COUNT(so.name) as order_count,
            COALESCE(SUM(so.grand_total), 0) as total_sales,
            COALESCE(SUM(so.seller_payout), 0) as net_earnings
        FROM `tabSub Order` so
        WHERE so.seller = %(seller)s
        AND so.status NOT IN ('Cancelled', 'Draft')
        {date_filter}
        GROUP BY {date_group}
        ORDER BY period_start
    """,
        date_params,
        as_dict=True,
    )

    # Format for chart
    labels = []
    sales_data = []
    orders_data = []
    earnings_data = []

    for row in data:
        if granularity == "monthly":
            label = row.period_start.strftime("%b %Y") if row.period_start else row.period
        elif granularity == "weekly":
            label = f"Week {str(row.period)[-2:]}"
        else:
            label = row.period_start.strftime("%d %b") if row.period_start else str(row.period)

        labels.append(label)
        sales_data.append(flt(row.total_sales, 2))
        orders_data.append(cint(row.order_count))
        earnings_data.append(flt(row.net_earnings, 2))

    return {
        "labels": labels,
        "datasets": [
            {
                "name": _("Sales"),
                "values": sales_data,
                "chartType": "line",
                "color": CHART_COLORS["primary"],
            },
            {
                "name": _("Net Earnings"),
                "values": earnings_data,
                "chartType": "line",
                "color": CHART_COLORS["success"],
            },
        ],
        "orders_dataset": {
            "name": _("Orders"),
            "values": orders_data,
            "chartType": "bar",
            "color": CHART_COLORS["info"],
        },
        "granularity": granularity,
        "total_points": len(labels),
    }


@frappe.whitelist()
def get_order_status_chart(
    range_type: str = "last_30_days",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    seller: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Get order status breakdown chart data.

    Returns:
        Pie/donut chart data with order status distribution
    """
    seller = seller or get_current_seller()
    if not seller:
        return _empty_chart_data()

    start, end = get_date_range(range_type, start_date, end_date)

    # Build date filter
    date_filter = ""
    date_params = {"seller": seller}
    if start:
        date_filter = "AND so.order_date >= %(start_date)s"
        date_params["start_date"] = start
    if end:
        date_filter += " AND so.order_date <= %(end_date)s"
        date_params["end_date"] = end

    # Get status counts
    status_data = frappe.db.sql(
        f"""
        SELECT
            so.status,
            COUNT(so.name) as count
        FROM `tabSub Order` so
        WHERE so.seller = %(seller)s
        {date_filter}
        GROUP BY so.status
        ORDER BY count DESC
    """,
        date_params,
        as_dict=True,
    )

    # Status colors mapping
    status_colors = {
        "Pending": CHART_COLORS["warning"],
        "Await Payment": CHART_COLORS["warning"],
        "Confirmed": CHART_COLORS["info"],
        "Processing": CHART_COLORS["primary"],
        "Packed": CHART_COLORS["info"],
        "Shipped": CHART_COLORS["primary"],
        "Out for Delivery": CHART_COLORS["primary"],
        "Delivered": CHART_COLORS["success"],
        "Completed": CHART_COLORS["success"],
        "Cancelled": CHART_COLORS["danger"],
        "Returned": CHART_COLORS["danger"],
        "Refunded": CHART_COLORS["secondary"],
        "Draft": CHART_COLORS["secondary"],
    }

    labels = []
    values = []
    colors = []

    for row in status_data:
        labels.append(_(row.status))
        values.append(cint(row.count))
        colors.append(status_colors.get(row.status, CHART_COLORS["secondary"]))

    return {
        "labels": labels,
        "datasets": [
            {
                "name": _("Orders"),
                "values": values,
                "colors": colors,
            }
        ],
        "type": "donut",
        "total": sum(values),
    }


def _empty_chart_data() -> Dict[str, Any]:
    """Return empty chart data structure."""
    return {
        "labels": [],
        "datasets": [],
        "total_points": 0,
    }


# =============================================================================
# TOP PRODUCTS
# =============================================================================


@frappe.whitelist()
def get_top_products(
    range_type: str = "last_30_days",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    seller: Optional[str] = None,
    limit: int = 10,
) -> List[Dict[str, Any]]:
    """
    Get top-selling products for the seller.

    Returns:
        List of top products with sales data
    """
    seller = seller or get_current_seller()
    if not seller:
        return []

    start, end = get_date_range(range_type, start_date, end_date)
    limit = min(cint(limit) or 10, 50)  # Cap at 50

    # Build date filter
    date_filter = ""
    date_params = {"seller": seller, "limit": limit}
    if start:
        date_filter = "AND so.order_date >= %(start_date)s"
        date_params["start_date"] = start
    if end:
        date_filter += " AND so.order_date <= %(end_date)s"
        date_params["end_date"] = end

    # Get top products
    products = frappe.db.sql(
        f"""
        SELECT
            soi.listing,
            soi.listing_title as product_name,
            soi.sku,
            COALESCE(l.primary_image, '') as image,
            SUM(soi.quantity) as units_sold,
            COUNT(DISTINCT so.name) as order_count,
            SUM(soi.amount) as total_revenue,
            AVG(soi.rate) as average_price
        FROM `tabSub Order Item` soi
        JOIN `tabSub Order` so ON soi.parent = so.name
        LEFT JOIN `tabListing` l ON soi.listing = l.name
        WHERE so.seller = %(seller)s
        AND so.status NOT IN ('Cancelled', 'Draft')
        {date_filter}
        GROUP BY soi.listing, soi.listing_title, soi.sku
        ORDER BY total_revenue DESC
        LIMIT %(limit)s
    """,
        date_params,
        as_dict=True,
    )

    currency = frappe.db.get_value("Seller Profile", seller, "currency") or "TRY"

    result = []
    for idx, product in enumerate(products, 1):
        result.append({
            "rank": idx,
            "listing": product.listing,
            "product_name": product.product_name,
            "sku": product.sku,
            "image": product.image,
            "units_sold": cint(product.units_sold),
            "order_count": cint(product.order_count),
            "total_revenue": flt(product.total_revenue, 2),
            "total_revenue_formatted": format_currency_value(
                product.total_revenue, currency
            ),
            "average_price": flt(product.average_price, 2),
            "average_price_formatted": format_currency_value(
                product.average_price, currency
            ),
        })

    return result


# =============================================================================
# RECENT ORDERS
# =============================================================================


@frappe.whitelist()
def get_recent_orders(
    seller: Optional[str] = None,
    limit: int = 10,
    status_filter: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Get recent orders for the seller.

    Args:
        seller: Seller profile
        limit: Number of orders to return
        status_filter: Optional status filter

    Returns:
        List of recent orders
    """
    seller = seller or get_current_seller()
    if not seller:
        return []

    limit = min(cint(limit) or 10, 50)

    filters = {"seller": seller}
    if status_filter:
        filters["status"] = status_filter

    orders = frappe.db.get_all(
        "Sub Order",
        filters=filters,
        fields=[
            "name",
            "sub_order_id",
            "marketplace_order",
            "order_date",
            "status",
            "payment_status",
            "fulfillment_status",
            "buyer_name",
            "grand_total",
            "currency",
            "items_shipped",
            "tracking_number",
            "creation",
        ],
        order_by="creation desc",
        limit_page_length=limit,
    )

    result = []
    for order in orders:
        # Get item count
        item_count = frappe.db.count(
            "Sub Order Item",
            {"parent": order.name},
        )

        result.append({
            "name": order.name,
            "sub_order_id": order.sub_order_id,
            "marketplace_order": order.marketplace_order,
            "order_date": str(order.order_date) if order.order_date else None,
            "status": order.status,
            "status_color": _get_status_color(order.status),
            "payment_status": order.payment_status,
            "fulfillment_status": order.fulfillment_status,
            "buyer_name": order.buyer_name,
            "grand_total": flt(order.grand_total, 2),
            "grand_total_formatted": format_currency_value(
                order.grand_total, order.currency or "TRY"
            ),
            "item_count": item_count,
            "tracking_number": order.tracking_number,
            "created_at": get_datetime_str(order.creation),
            "time_ago": frappe.utils.pretty_date(order.creation),
        })

    return result


def _get_status_color(status: str) -> str:
    """Get color for status badge."""
    color_map = {
        "Pending": "orange",
        "Await Payment": "orange",
        "Confirmed": "blue",
        "Processing": "purple",
        "Packed": "blue",
        "Shipped": "purple",
        "Out for Delivery": "purple",
        "Delivered": "green",
        "Completed": "green",
        "Cancelled": "red",
        "Returned": "red",
        "Refunded": "gray",
        "Draft": "gray",
    }
    return color_map.get(status, "gray")


# =============================================================================
# PERFORMANCE SUMMARY
# =============================================================================


@frappe.whitelist()
def get_performance_summary(seller: Optional[str] = None) -> Dict[str, Any]:
    """
    Get seller performance summary from Seller Profile.

    Returns:
        Performance metrics including:
        - seller_score
        - seller_tier
        - response_rate
        - fulfillment_rate
        - on_time_delivery_rate
        - return_rate
        - average_rating
        - total_reviews
        - badges
    """
    seller = seller or get_current_seller()
    if not seller:
        return _empty_performance()

    profile = frappe.db.get_value(
        "Seller Profile",
        seller,
        [
            "seller_score",
            "seller_tier",
            "response_rate",
            "fulfillment_rate",
            "on_time_delivery_rate",
            "return_rate",
            "cancellation_rate",
            "average_rating",
            "total_reviews",
            "total_sales_count",
            "total_sales_amount",
            "badges",
            "status",
            "verification_status",
        ],
        as_dict=True,
    )

    if not profile:
        return _empty_performance()

    # Parse badges JSON
    badges = []
    if profile.badges:
        try:
            import json
            badges = json.loads(profile.badges)
        except (json.JSONDecodeError, TypeError):
            badges = []

    # Get tier info
    tier_info = None
    if profile.seller_tier:
        tier_info = frappe.db.get_value(
            "Seller Tier",
            profile.seller_tier,
            ["tier_name", "badge_color", "badge_icon"],
            as_dict=True,
        )

    return {
        "seller_score": flt(profile.seller_score, 1),
        "seller_tier": profile.seller_tier,
        "tier_info": tier_info,
        "response_rate": flt(profile.response_rate, 1),
        "fulfillment_rate": flt(profile.fulfillment_rate, 1),
        "on_time_delivery_rate": flt(profile.on_time_delivery_rate, 1),
        "return_rate": flt(profile.return_rate, 1),
        "cancellation_rate": flt(profile.cancellation_rate, 1),
        "average_rating": flt(profile.average_rating, 2),
        "total_reviews": cint(profile.total_reviews),
        "total_sales_count": cint(profile.total_sales_count),
        "total_sales_amount": flt(profile.total_sales_amount, 2),
        "badges": badges,
        "status": profile.status,
        "verification_status": profile.verification_status,
    }


def _empty_performance() -> Dict[str, Any]:
    """Return empty performance structure."""
    return {
        "seller_score": 0,
        "seller_tier": None,
        "tier_info": None,
        "response_rate": 0,
        "fulfillment_rate": 0,
        "on_time_delivery_rate": 0,
        "return_rate": 0,
        "cancellation_rate": 0,
        "average_rating": 0,
        "total_reviews": 0,
        "total_sales_count": 0,
        "total_sales_amount": 0,
        "badges": [],
        "status": None,
        "verification_status": None,
    }


# =============================================================================
# CATEGORY PERFORMANCE
# =============================================================================


@frappe.whitelist()
def get_category_performance(
    range_type: str = "last_30_days",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    seller: Optional[str] = None,
    limit: int = 10,
) -> List[Dict[str, Any]]:
    """
    Get sales performance by category.

    Returns:
        List of categories with sales metrics
    """
    seller = seller or get_current_seller()
    if not seller:
        return []

    start, end = get_date_range(range_type, start_date, end_date)
    limit = min(cint(limit) or 10, 20)

    # Build date filter
    date_filter = ""
    date_params = {"seller": seller, "limit": limit}
    if start:
        date_filter = "AND so.order_date >= %(start_date)s"
        date_params["start_date"] = start
    if end:
        date_filter += " AND so.order_date <= %(end_date)s"
        date_params["end_date"] = end

    # Get category performance
    categories = frappe.db.sql(
        f"""
        SELECT
            l.category,
            c.category_name,
            COUNT(DISTINCT so.name) as order_count,
            SUM(soi.quantity) as units_sold,
            SUM(soi.amount) as total_revenue,
            AVG(soi.rate) as average_price
        FROM `tabSub Order Item` soi
        JOIN `tabSub Order` so ON soi.parent = so.name
        JOIN `tabListing` l ON soi.listing = l.name
        LEFT JOIN `tabCategory` c ON l.category = c.name
        WHERE so.seller = %(seller)s
        AND so.status NOT IN ('Cancelled', 'Draft')
        {date_filter}
        GROUP BY l.category, c.category_name
        ORDER BY total_revenue DESC
        LIMIT %(limit)s
    """,
        date_params,
        as_dict=True,
    )

    currency = frappe.db.get_value("Seller Profile", seller, "currency") or "TRY"
    total_revenue = sum(flt(c.total_revenue) for c in categories)

    result = []
    for cat in categories:
        percentage = (
            round((flt(cat.total_revenue) / total_revenue) * 100, 1)
            if total_revenue > 0
            else 0
        )
        result.append({
            "category": cat.category,
            "category_name": cat.category_name or cat.category,
            "order_count": cint(cat.order_count),
            "units_sold": cint(cat.units_sold),
            "total_revenue": flt(cat.total_revenue, 2),
            "total_revenue_formatted": format_currency_value(
                cat.total_revenue, currency
            ),
            "average_price": flt(cat.average_price, 2),
            "percentage": percentage,
        })

    return result


# =============================================================================
# REVENUE BREAKDOWN
# =============================================================================


@frappe.whitelist()
def get_revenue_breakdown(
    range_type: str = "last_30_days",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    seller: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Get detailed revenue breakdown.

    Returns:
        Revenue breakdown by:
        - gross_sales
        - discounts
        - shipping_collected
        - tax_collected
        - commission
        - net_revenue
    """
    seller = seller or get_current_seller()
    if not seller:
        return _empty_revenue_breakdown()

    start, end = get_date_range(range_type, start_date, end_date)

    # Build date filter
    date_filter = ""
    date_params = {"seller": seller}
    if start:
        date_filter = "AND so.order_date >= %(start_date)s"
        date_params["start_date"] = start
    if end:
        date_filter += " AND so.order_date <= %(end_date)s"
        date_params["end_date"] = end

    breakdown = frappe.db.sql(
        f"""
        SELECT
            COALESCE(SUM(so.subtotal), 0) as gross_sales,
            COALESCE(SUM(so.discount_amount), 0) as discounts,
            COALESCE(SUM(so.shipping_amount), 0) as shipping_collected,
            COALESCE(SUM(so.tax_amount), 0) as tax_collected,
            COALESCE(SUM(so.commission_amount), 0) as commission,
            COALESCE(SUM(so.seller_payout), 0) as net_revenue,
            COALESCE(SUM(so.grand_total), 0) as total_sales
        FROM `tabSub Order` so
        WHERE so.seller = %(seller)s
        AND so.status NOT IN ('Cancelled', 'Draft')
        {date_filter}
    """,
        date_params,
        as_dict=True,
    )

    data = breakdown[0] if breakdown else _empty_revenue_row()
    currency = frappe.db.get_value("Seller Profile", seller, "currency") or "TRY"

    return {
        "gross_sales": flt(data.gross_sales, 2),
        "gross_sales_formatted": format_currency_value(data.gross_sales, currency),
        "discounts": flt(data.discounts, 2),
        "discounts_formatted": format_currency_value(data.discounts, currency),
        "shipping_collected": flt(data.shipping_collected, 2),
        "shipping_collected_formatted": format_currency_value(
            data.shipping_collected, currency
        ),
        "tax_collected": flt(data.tax_collected, 2),
        "tax_collected_formatted": format_currency_value(data.tax_collected, currency),
        "commission": flt(data.commission, 2),
        "commission_formatted": format_currency_value(data.commission, currency),
        "net_revenue": flt(data.net_revenue, 2),
        "net_revenue_formatted": format_currency_value(data.net_revenue, currency),
        "total_sales": flt(data.total_sales, 2),
        "total_sales_formatted": format_currency_value(data.total_sales, currency),
        "currency": currency,
    }


def _empty_revenue_breakdown() -> Dict[str, Any]:
    """Return empty revenue breakdown."""
    return {
        "gross_sales": 0,
        "gross_sales_formatted": format_currency_value(0),
        "discounts": 0,
        "discounts_formatted": format_currency_value(0),
        "shipping_collected": 0,
        "shipping_collected_formatted": format_currency_value(0),
        "tax_collected": 0,
        "tax_collected_formatted": format_currency_value(0),
        "commission": 0,
        "commission_formatted": format_currency_value(0),
        "net_revenue": 0,
        "net_revenue_formatted": format_currency_value(0),
        "total_sales": 0,
        "total_sales_formatted": format_currency_value(0),
        "currency": "TRY",
    }


def _empty_revenue_row():
    """Return empty revenue row."""
    class EmptyRow:
        gross_sales = 0
        discounts = 0
        shipping_collected = 0
        tax_collected = 0
        commission = 0
        net_revenue = 0
        total_sales = 0
    return EmptyRow()


# =============================================================================
# CUSTOMER INSIGHTS
# =============================================================================


@frappe.whitelist()
def get_customer_insights(
    range_type: str = "last_30_days",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    seller: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Get customer insights and statistics.

    Returns:
        Customer metrics:
        - total_customers
        - new_customers
        - returning_customers
        - repeat_rate
        - average_orders_per_customer
        - top_customers
    """
    seller = seller or get_current_seller()
    if not seller:
        return _empty_customer_insights()

    start, end = get_date_range(range_type, start_date, end_date)

    # Build date filter
    date_filter = ""
    date_params = {"seller": seller}
    if start:
        date_filter = "AND so.order_date >= %(start_date)s"
        date_params["start_date"] = start
    if end:
        date_filter += " AND so.order_date <= %(end_date)s"
        date_params["end_date"] = end

    # Get customer stats
    customer_stats = frappe.db.sql(
        f"""
        SELECT
            COUNT(DISTINCT so.buyer) as total_customers,
            SUM(CASE
                WHEN (SELECT MIN(so2.order_date)
                      FROM `tabSub Order` so2
                      WHERE so2.seller = so.seller AND so2.buyer = so.buyer) >= %(start_date)s
                THEN 1 ELSE 0
            END) as new_customers
        FROM `tabSub Order` so
        WHERE so.seller = %(seller)s
        AND so.status NOT IN ('Cancelled', 'Draft')
        {date_filter}
    """,
        date_params,
        as_dict=True,
    )

    stats = customer_stats[0] if customer_stats else {"total_customers": 0, "new_customers": 0}

    # Get returning customers count
    returning_query = frappe.db.sql(
        f"""
        SELECT COUNT(*) as returning_customers
        FROM (
            SELECT so.buyer, COUNT(so.name) as order_count
            FROM `tabSub Order` so
            WHERE so.seller = %(seller)s
            AND so.status NOT IN ('Cancelled', 'Draft')
            {date_filter}
            GROUP BY so.buyer
            HAVING order_count > 1
        ) repeat_buyers
    """,
        date_params,
        as_dict=True,
    )

    returning_customers = (
        returning_query[0].returning_customers if returning_query else 0
    )

    total = cint(stats.total_customers)
    new = cint(stats.new_customers)
    returning = cint(returning_customers)
    repeat_rate = round((returning / total) * 100, 1) if total > 0 else 0

    # Get top customers
    top_customers = frappe.db.sql(
        f"""
        SELECT
            so.buyer,
            so.buyer_name,
            COUNT(so.name) as order_count,
            SUM(so.grand_total) as total_spent
        FROM `tabSub Order` so
        WHERE so.seller = %(seller)s
        AND so.status NOT IN ('Cancelled', 'Draft')
        {date_filter}
        GROUP BY so.buyer, so.buyer_name
        ORDER BY total_spent DESC
        LIMIT 5
    """,
        date_params,
        as_dict=True,
    )

    currency = frappe.db.get_value("Seller Profile", seller, "currency") or "TRY"

    return {
        "total_customers": total,
        "new_customers": new,
        "returning_customers": returning,
        "repeat_rate": repeat_rate,
        "top_customers": [
            {
                "buyer": c.buyer,
                "buyer_name": c.buyer_name,
                "order_count": cint(c.order_count),
                "total_spent": flt(c.total_spent, 2),
                "total_spent_formatted": format_currency_value(c.total_spent, currency),
            }
            for c in top_customers
        ],
    }


def _empty_customer_insights() -> Dict[str, Any]:
    """Return empty customer insights."""
    return {
        "total_customers": 0,
        "new_customers": 0,
        "returning_customers": 0,
        "repeat_rate": 0,
        "top_customers": [],
    }


# =============================================================================
# PAYOUT SUMMARY
# =============================================================================


@frappe.whitelist()
def get_payout_summary(seller: Optional[str] = None) -> Dict[str, Any]:
    """
    Get payout summary for seller.

    Returns:
        Payout information:
        - pending_payout
        - next_payout_date
        - last_payout_amount
        - last_payout_date
        - total_paid_out
        - escrow_balance
    """
    seller = seller or get_current_seller()
    if not seller:
        return _empty_payout_summary()

    # Get pending payout (from unpaid completed orders)
    pending = frappe.db.sql(
        """
        SELECT COALESCE(SUM(so.seller_payout), 0) as pending_payout
        FROM `tabSub Order` so
        WHERE so.seller = %(seller)s
        AND so.status IN ('Delivered', 'Completed')
        AND so.payout_status IN ('Pending', 'Processing')
    """,
        {"seller": seller},
        as_dict=True,
    )

    pending_payout = pending[0].pending_payout if pending else 0

    # Get escrow balance (from shipped but not delivered orders)
    escrow = frappe.db.sql(
        """
        SELECT COALESCE(SUM(so.seller_payout), 0) as escrow_balance
        FROM `tabSub Order` so
        WHERE so.seller = %(seller)s
        AND so.status IN ('Shipped', 'Out for Delivery')
        AND so.escrow_status = 'Held'
    """,
        {"seller": seller},
        as_dict=True,
    )

    escrow_balance = escrow[0].escrow_balance if escrow else 0

    # Get total paid out
    total_paid = frappe.db.sql(
        """
        SELECT COALESCE(SUM(so.seller_payout), 0) as total_paid
        FROM `tabSub Order` so
        WHERE so.seller = %(seller)s
        AND so.payout_status = 'Paid'
    """,
        {"seller": seller},
        as_dict=True,
    )

    total_paid_out = total_paid[0].total_paid if total_paid else 0

    # Get last payout info (most recent paid order)
    last_payout = frappe.db.sql(
        """
        SELECT so.seller_payout, so.escrow_released_at
        FROM `tabSub Order` so
        WHERE so.seller = %(seller)s
        AND so.payout_status = 'Paid'
        ORDER BY so.escrow_released_at DESC
        LIMIT 1
    """,
        {"seller": seller},
        as_dict=True,
    )

    last_payout_amount = last_payout[0].seller_payout if last_payout else 0
    last_payout_date = (
        str(last_payout[0].escrow_released_at) if last_payout else None
    )

    # Calculate next payout date based on commission plan
    commission_plan = frappe.db.get_value("Seller Profile", seller, "commission_plan")
    next_payout_date = None
    payout_frequency = "Weekly"

    if commission_plan:
        plan = frappe.db.get_value(
            "Commission Plan",
            commission_plan,
            ["payout_frequency", "payout_day"],
            as_dict=True,
        )
        if plan:
            payout_frequency = plan.payout_frequency
            next_payout_date = _calculate_next_payout_date(
                plan.payout_frequency, plan.payout_day
            )

    currency = frappe.db.get_value("Seller Profile", seller, "currency") or "TRY"

    return {
        "pending_payout": flt(pending_payout, 2),
        "pending_payout_formatted": format_currency_value(pending_payout, currency),
        "escrow_balance": flt(escrow_balance, 2),
        "escrow_balance_formatted": format_currency_value(escrow_balance, currency),
        "total_paid_out": flt(total_paid_out, 2),
        "total_paid_out_formatted": format_currency_value(total_paid_out, currency),
        "last_payout_amount": flt(last_payout_amount, 2),
        "last_payout_amount_formatted": format_currency_value(
            last_payout_amount, currency
        ),
        "last_payout_date": last_payout_date,
        "next_payout_date": next_payout_date,
        "payout_frequency": payout_frequency,
        "currency": currency,
    }


def _empty_payout_summary() -> Dict[str, Any]:
    """Return empty payout summary."""
    return {
        "pending_payout": 0,
        "pending_payout_formatted": format_currency_value(0),
        "escrow_balance": 0,
        "escrow_balance_formatted": format_currency_value(0),
        "total_paid_out": 0,
        "total_paid_out_formatted": format_currency_value(0),
        "last_payout_amount": 0,
        "last_payout_amount_formatted": format_currency_value(0),
        "last_payout_date": None,
        "next_payout_date": None,
        "payout_frequency": None,
        "currency": "TRY",
    }


def _calculate_next_payout_date(
    frequency: str, payout_day: Optional[int] = None
) -> Optional[str]:
    """Calculate next payout date based on frequency."""
    from datetime import date
    import calendar

    today = date.today()

    if frequency == "Daily":
        return str(add_days(today, 1))
    elif frequency == "Weekly":
        # Next Monday
        days_until_monday = (7 - today.weekday()) % 7
        if days_until_monday == 0:
            days_until_monday = 7
        return str(add_days(today, days_until_monday))
    elif frequency == "Bi-Weekly":
        # Every other Monday
        days_until_monday = (7 - today.weekday()) % 7
        if days_until_monday == 0:
            days_until_monday = 7
        return str(add_days(today, days_until_monday + 7))
    elif frequency == "Monthly":
        # First of next month or specified day
        day = payout_day or 1
        next_month = add_months(today, 1)
        max_day = calendar.monthrange(next_month.year, next_month.month)[1]
        day = min(day, max_day)
        return str(next_month.replace(day=day))
    else:
        return None


# =============================================================================
# CONVERSION METRICS
# =============================================================================


@frappe.whitelist()
def get_conversion_metrics(
    range_type: str = "last_30_days",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    seller: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Get conversion funnel metrics.

    Returns:
        Conversion metrics:
        - listing_views
        - cart_additions
        - orders
        - conversion_rate (views to orders)
        - cart_conversion_rate (cart to orders)
    """
    seller = seller or get_current_seller()
    if not seller:
        return _empty_conversion_metrics()

    start, end = get_date_range(range_type, start_date, end_date)

    # Build date filter
    date_filter = ""
    date_params = {"seller": seller}
    if start:
        date_filter = "AND so.order_date >= %(start_date)s"
        date_params["start_date"] = start
    if end:
        date_filter += " AND so.order_date <= %(end_date)s"
        date_params["end_date"] = end

    # Get order count
    orders = frappe.db.sql(
        f"""
        SELECT COUNT(so.name) as order_count
        FROM `tabSub Order` so
        WHERE so.seller = %(seller)s
        AND so.status NOT IN ('Cancelled', 'Draft')
        {date_filter}
    """,
        date_params,
        as_dict=True,
    )

    order_count = orders[0].order_count if orders else 0

    # Get listing views (aggregate from all seller's listings)
    listing_views_filter = ""
    if start:
        listing_views_filter = "AND l.modified >= %(start_date)s"

    views = frappe.db.sql(
        f"""
        SELECT COALESCE(SUM(l.view_count), 0) as total_views
        FROM `tabListing` l
        WHERE l.seller = %(seller)s
        AND l.status = 'Published'
        {listing_views_filter}
    """,
        {"seller": seller, "start_date": start},
        as_dict=True,
    )

    listing_views = views[0].total_views if views else 0

    # Calculate conversion rate
    conversion_rate = (
        round((order_count / listing_views) * 100, 2) if listing_views > 0 else 0
    )

    # Get active listings count
    active_listings = frappe.db.count(
        "Listing",
        {"seller": seller, "status": "Published"},
    )

    return {
        "listing_views": cint(listing_views),
        "orders": cint(order_count),
        "conversion_rate": conversion_rate,
        "active_listings": cint(active_listings),
        "views_per_listing": (
            round(listing_views / active_listings, 1) if active_listings > 0 else 0
        ),
        "orders_per_listing": (
            round(order_count / active_listings, 2) if active_listings > 0 else 0
        ),
    }


def _empty_conversion_metrics() -> Dict[str, Any]:
    """Return empty conversion metrics."""
    return {
        "listing_views": 0,
        "orders": 0,
        "conversion_rate": 0,
        "active_listings": 0,
        "views_per_listing": 0,
        "orders_per_listing": 0,
    }

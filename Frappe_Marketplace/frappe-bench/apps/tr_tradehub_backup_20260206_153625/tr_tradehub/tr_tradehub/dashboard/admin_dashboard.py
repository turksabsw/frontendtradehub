# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

"""
Admin Dashboard API Endpoints for TR-TradeHub Marketplace

This module provides comprehensive dashboard APIs for platform administrators including:
- Platform-wide metrics (GMV, order count, active users)
- Platform growth trend charts
- Seller performance overview
- Moderation and case management overview
- Revenue and commission analytics
- System health metrics
- Geographic analytics
- Category performance at platform level
- Compliance and governance metrics
- Recent activity feeds

API URL Pattern:
    POST /api/method/tr_tradehub.dashboard.admin_dashboard.<function_name>

All endpoints require authentication with admin/manager roles.
Data represents platform-wide aggregate metrics.
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
    "activity": 60,  # 1 minute
    "system_health": 120,  # 2 minutes
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
    "teal": "#14B8A6",  # Teal
    "pink": "#EC4899",  # Pink
    "orange": "#F97316",  # Orange
    "indigo": "#6366F1",  # Indigo
}

# Admin roles that can access this dashboard
ADMIN_ROLES = [
    "System Manager",
    "Marketplace Admin",
    "Marketplace Manager",
    "Administrator",
]


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================


def check_admin_permission():
    """
    Check if current user has admin permission to access dashboard.

    Raises:
        frappe.PermissionError: If user doesn't have admin role
    """
    if not frappe.session.user or frappe.session.user == "Guest":
        frappe.throw(
            _("Authentication required to access admin dashboard"),
            frappe.PermissionError,
        )

    user_roles = frappe.get_roles(frappe.session.user)
    has_admin_role = any(role in ADMIN_ROLES for role in user_roles)

    if not has_admin_role:
        frappe.throw(
            _("You do not have permission to access the admin dashboard"),
            frappe.PermissionError,
        )


def require_admin(func):
    """Decorator to require admin permission for dashboard endpoints."""
    def wrapper(*args, **kwargs):
        check_admin_permission()
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


def get_cache_key(prefix: str, **kwargs) -> str:
    """Generate cache key for dashboard data."""
    import hashlib

    key_parts = [prefix]
    for k, v in sorted(kwargs.items()):
        key_parts.append(f"{k}:{v}")
    key_string = ":".join(key_parts)
    return f"admin_dashboard:{hashlib.md5(key_string.encode()).hexdigest()}"


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
# MAIN DASHBOARD API
# =============================================================================


@frappe.whitelist()
def get_admin_dashboard(
    range_type: str = "last_30_days",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Get complete admin dashboard data.

    This is the main endpoint that returns all dashboard components.
    Can be called directly or individual components can be fetched separately.

    Args:
        range_type: Date range type (e.g., "last_30_days", "this_month")
        start_date: Custom start date
        end_date: Custom end date

    Returns:
        Dict containing all dashboard data:
        - platform_metrics: Key platform-wide metrics
        - gmv_trend: GMV over time chart data
        - order_status: Platform order status breakdown
        - seller_overview: Seller statistics
        - moderation_overview: Moderation case statistics
        - top_sellers: Best performing sellers
        - top_categories: Best performing categories
        - recent_activity: Latest platform activity
        - system_health: System health metrics
    """
    check_admin_permission()

    # Check cache
    cache_key = get_cache_key(
        "dashboard", range_type=range_type, start=start_date, end=end_date
    )
    cached = get_cached_data(cache_key)
    if cached:
        return cached

    # Get date range
    start, end = get_date_range(range_type, start_date, end_date)

    # Build dashboard data
    dashboard = {
        "platform_metrics": get_platform_metrics(
            range_type=range_type,
            start_date=start_date,
            end_date=end_date,
        ),
        "gmv_trend": get_gmv_trend_chart(
            range_type=range_type,
            start_date=start_date,
            end_date=end_date,
        ),
        "order_status": get_order_status_breakdown(
            range_type=range_type,
            start_date=start_date,
            end_date=end_date,
        ),
        "seller_overview": get_seller_overview(
            range_type=range_type,
            start_date=start_date,
            end_date=end_date,
        ),
        "moderation_overview": get_moderation_overview(),
        "top_sellers": get_top_sellers(
            range_type=range_type,
            start_date=start_date,
            end_date=end_date,
            limit=10,
        ),
        "top_categories": get_top_categories(
            range_type=range_type,
            start_date=start_date,
            end_date=end_date,
            limit=10,
        ),
        "recent_activity": get_recent_activity(limit=20),
        "system_health": get_system_health(),
        "geographic_distribution": get_geographic_distribution(
            range_type=range_type,
            start_date=start_date,
            end_date=end_date,
        ),
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


# =============================================================================
# PLATFORM METRICS
# =============================================================================


@frappe.whitelist()
def get_platform_metrics(
    range_type: str = "last_30_days",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Get key platform-wide metrics.

    Returns:
        Dict containing:
        - total_gmv: Total Gross Merchandise Value
        - order_count: Number of marketplace orders
        - average_order_value: Average order value
        - active_sellers: Count of active sellers
        - active_buyers: Count of active buyers
        - active_listings: Count of published listings
        - total_commission: Total commission earned
        - comparison: Period-over-period comparison
    """
    check_admin_permission()

    start, end = get_date_range(range_type, start_date, end_date)

    # Build date filter
    date_filter = ""
    date_params = {}
    if start:
        date_filter = "AND mo.order_date >= %(start_date)s"
        date_params["start_date"] = start
    if end:
        date_filter += " AND mo.order_date <= %(end_date)s"
        date_params["end_date"] = end

    # Get current period order metrics
    order_metrics = frappe.db.sql(
        f"""
        SELECT
            COUNT(DISTINCT mo.name) as order_count,
            COALESCE(SUM(mo.grand_total), 0) as total_gmv,
            COALESCE(AVG(mo.grand_total), 0) as average_order_value,
            COUNT(DISTINCT mo.buyer) as unique_buyers
        FROM `tabMarketplace Order` mo
        WHERE mo.status NOT IN ('Cancelled', 'Draft')
        {date_filter}
    """,
        date_params,
        as_dict=True,
    )

    current = order_metrics[0] if order_metrics else _empty_metrics_row()

    # Get commission metrics from sub orders
    commission_metrics = frappe.db.sql(
        f"""
        SELECT
            COALESCE(SUM(so.commission_amount), 0) as total_commission,
            COUNT(DISTINCT so.seller) as unique_sellers
        FROM `tabSub Order` so
        WHERE so.status NOT IN ('Cancelled', 'Draft')
        {date_filter.replace('mo.', 'so.')}
    """,
        date_params,
        as_dict=True,
    )

    commission_data = commission_metrics[0] if commission_metrics else {}

    # Get active entities counts
    active_sellers = frappe.db.count(
        "Seller Profile",
        {"status": "Active"},
    )

    active_listings = frappe.db.count(
        "Listing",
        {"status": "Published"},
    )

    total_users = frappe.db.count(
        "User",
        {"enabled": 1, "user_type": "Website User"},
    )

    # Calculate comparison period
    comparison = _get_platform_comparison_metrics(start, end, range_type)

    currency = "TRY"  # Platform default currency

    return {
        "total_gmv": flt(current.total_gmv, 2),
        "total_gmv_formatted": format_currency_value(current.total_gmv, currency),
        "order_count": cint(current.order_count),
        "average_order_value": flt(current.average_order_value, 2),
        "average_order_value_formatted": format_currency_value(
            current.average_order_value, currency
        ),
        "unique_buyers_period": cint(current.unique_buyers),
        "unique_sellers_period": cint(commission_data.get("unique_sellers", 0)),
        "active_sellers": cint(active_sellers),
        "active_listings": cint(active_listings),
        "total_users": cint(total_users),
        "total_commission": flt(commission_data.get("total_commission", 0), 2),
        "total_commission_formatted": format_currency_value(
            commission_data.get("total_commission", 0), currency
        ),
        "currency": currency,
        "comparison": comparison,
    }


def _empty_metrics_row():
    """Return empty metrics row with proper structure."""
    class EmptyRow:
        total_gmv = 0
        order_count = 0
        average_order_value = 0
        unique_buyers = 0
    return EmptyRow()


def _get_platform_comparison_metrics(
    start: Optional[datetime],
    end: Optional[datetime],
    range_type: str,
) -> Dict[str, float]:
    """Get comparison metrics for previous period."""
    if not start or range_type == "all_time":
        return {
            "gmv_change": 0,
            "order_count_change": 0,
            "aov_change": 0,
        }

    # Calculate previous period dates
    period_days = date_diff(end, start) + 1
    prev_end = add_days(start, -1)
    prev_start = add_days(prev_end, -(period_days - 1))

    # Get previous period metrics
    prev_metrics = frappe.db.sql(
        """
        SELECT
            COUNT(mo.name) as order_count,
            COALESCE(SUM(mo.grand_total), 0) as total_gmv,
            COALESCE(AVG(mo.grand_total), 0) as average_order_value
        FROM `tabMarketplace Order` mo
        WHERE mo.status NOT IN ('Cancelled', 'Draft')
        AND mo.order_date >= %(start_date)s
        AND mo.order_date <= %(end_date)s
    """,
        {
            "start_date": prev_start,
            "end_date": prev_end,
        },
        as_dict=True,
    )

    # Get current period metrics for comparison
    curr_metrics = frappe.db.sql(
        """
        SELECT
            COUNT(mo.name) as order_count,
            COALESCE(SUM(mo.grand_total), 0) as total_gmv,
            COALESCE(AVG(mo.grand_total), 0) as average_order_value
        FROM `tabMarketplace Order` mo
        WHERE mo.status NOT IN ('Cancelled', 'Draft')
        AND mo.order_date >= %(start_date)s
        AND mo.order_date <= %(end_date)s
    """,
        {
            "start_date": start,
            "end_date": end,
        },
        as_dict=True,
    )

    prev = prev_metrics[0] if prev_metrics else _empty_metrics_row()
    curr = curr_metrics[0] if curr_metrics else _empty_metrics_row()

    return {
        "gmv_change": calculate_percentage_change(
            flt(curr.total_gmv), flt(prev.total_gmv)
        ),
        "order_count_change": calculate_percentage_change(
            flt(curr.order_count), flt(prev.order_count)
        ),
        "aov_change": calculate_percentage_change(
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
def get_gmv_trend_chart(
    range_type: str = "last_30_days",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    granularity: str = "daily",
) -> Dict[str, Any]:
    """
    Get GMV trend chart data for the platform.

    Args:
        range_type: Date range type
        start_date: Custom start date
        end_date: Custom end date
        granularity: Data granularity ("daily", "weekly", "monthly")

    Returns:
        Chart-ready data structure:
        - labels: Date labels
        - datasets: Array of data series
    """
    check_admin_permission()

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
        date_group = "DATE_FORMAT(mo.order_date, '%Y-%m')"
    elif granularity == "weekly":
        date_group = "YEARWEEK(mo.order_date, 1)"
    else:
        date_group = "DATE(mo.order_date)"

    # Build date filter
    date_filter = ""
    date_params = {}
    if start:
        date_filter = "AND mo.order_date >= %(start_date)s"
        date_params["start_date"] = start
    if end:
        date_filter += " AND mo.order_date <= %(end_date)s"
        date_params["end_date"] = end

    # Get GMV data
    data = frappe.db.sql(
        f"""
        SELECT
            {date_group} as period,
            DATE(MIN(mo.order_date)) as period_start,
            COUNT(mo.name) as order_count,
            COALESCE(SUM(mo.grand_total), 0) as total_gmv,
            COUNT(DISTINCT mo.buyer) as unique_buyers
        FROM `tabMarketplace Order` mo
        WHERE mo.status NOT IN ('Cancelled', 'Draft')
        {date_filter}
        GROUP BY {date_group}
        ORDER BY period_start
    """,
        date_params,
        as_dict=True,
    )

    # Get commission data
    commission_data = frappe.db.sql(
        f"""
        SELECT
            {date_group.replace('mo.', 'so.')} as period,
            COALESCE(SUM(so.commission_amount), 0) as total_commission
        FROM `tabSub Order` so
        WHERE so.status NOT IN ('Cancelled', 'Draft')
        {date_filter.replace('mo.', 'so.')}
        GROUP BY {date_group.replace('mo.', 'so.')}
    """,
        date_params,
        as_dict=True,
    )

    # Create commission lookup
    commission_lookup = {str(c.period): flt(c.total_commission) for c in commission_data}

    # Format for chart
    labels = []
    gmv_data = []
    orders_data = []
    commission_chart_data = []

    for row in data:
        if granularity == "monthly":
            label = row.period_start.strftime("%b %Y") if row.period_start else row.period
        elif granularity == "weekly":
            label = f"Week {str(row.period)[-2:]}"
        else:
            label = row.period_start.strftime("%d %b") if row.period_start else str(row.period)

        labels.append(label)
        gmv_data.append(flt(row.total_gmv, 2))
        orders_data.append(cint(row.order_count))
        commission_chart_data.append(commission_lookup.get(str(row.period), 0))

    return {
        "labels": labels,
        "datasets": [
            {
                "name": _("GMV"),
                "values": gmv_data,
                "chartType": "line",
                "color": CHART_COLORS["primary"],
            },
            {
                "name": _("Commission"),
                "values": commission_chart_data,
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
def get_order_status_breakdown(
    range_type: str = "last_30_days",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Get order status breakdown chart data for the platform.

    Returns:
        Pie/donut chart data with order status distribution
    """
    check_admin_permission()

    start, end = get_date_range(range_type, start_date, end_date)

    # Build date filter
    date_filter = ""
    date_params = {}
    if start:
        date_filter = "AND mo.order_date >= %(start_date)s"
        date_params["start_date"] = start
    if end:
        date_filter += " AND mo.order_date <= %(end_date)s"
        date_params["end_date"] = end

    # Get status counts
    status_data = frappe.db.sql(
        f"""
        SELECT
            mo.status,
            COUNT(mo.name) as count
        FROM `tabMarketplace Order` mo
        WHERE 1=1
        {date_filter}
        GROUP BY mo.status
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
        "Partially Shipped": CHART_COLORS["info"],
        "Shipped": CHART_COLORS["primary"],
        "Delivered": CHART_COLORS["success"],
        "Completed": CHART_COLORS["success"],
        "Cancelled": CHART_COLORS["danger"],
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


# =============================================================================
# SELLER OVERVIEW
# =============================================================================


@frappe.whitelist()
def get_seller_overview(
    range_type: str = "last_30_days",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Get seller statistics overview.

    Returns:
        Dict containing:
        - total_sellers: Total registered sellers
        - active_sellers: Active sellers
        - pending_applications: Pending seller applications
        - by_verification_status: Breakdown by verification status
        - by_tier: Breakdown by seller tier
        - new_sellers_period: New sellers in period
        - average_seller_score: Average platform seller score
    """
    check_admin_permission()

    start, end = get_date_range(range_type, start_date, end_date)

    # Get seller counts by status
    status_counts = frappe.db.sql(
        """
        SELECT status, COUNT(*) as count
        FROM `tabSeller Profile`
        GROUP BY status
    """,
        as_dict=True,
    )

    status_breakdown = {s.status: cint(s.count) for s in status_counts}

    # Get verification status breakdown
    verification_counts = frappe.db.sql(
        """
        SELECT verification_status, COUNT(*) as count
        FROM `tabSeller Profile`
        WHERE status != 'Deleted'
        GROUP BY verification_status
    """,
        as_dict=True,
    )

    verification_breakdown = {v.verification_status: cint(v.count) for v in verification_counts}

    # Get tier breakdown
    tier_counts = frappe.db.sql(
        """
        SELECT
            COALESCE(seller_tier, 'No Tier') as tier,
            COUNT(*) as count
        FROM `tabSeller Profile`
        WHERE status = 'Active'
        GROUP BY seller_tier
        ORDER BY count DESC
    """,
        as_dict=True,
    )

    tier_breakdown = [{"tier": t.tier, "count": cint(t.count)} for t in tier_counts]

    # Get pending applications
    pending_applications = frappe.db.count(
        "Seller Application",
        {"status": ["in", ["Submitted", "Under Review"]]},
    )

    # Get new sellers in period
    new_sellers = 0
    if start:
        new_sellers = frappe.db.count(
            "Seller Profile",
            {
                "creation": [">=", start],
                "status": ["!=", "Deleted"],
            },
        )

    # Get average seller score
    avg_score_result = frappe.db.sql(
        """
        SELECT AVG(seller_score) as avg_score
        FROM `tabSeller Profile`
        WHERE status = 'Active'
        AND seller_score > 0
    """,
        as_dict=True,
    )

    avg_seller_score = flt(avg_score_result[0].avg_score, 1) if avg_score_result else 0

    total_sellers = sum(status_breakdown.values())
    active_sellers = status_breakdown.get("Active", 0)

    return {
        "total_sellers": total_sellers,
        "active_sellers": active_sellers,
        "pending_applications": cint(pending_applications),
        "by_status": status_breakdown,
        "by_verification_status": verification_breakdown,
        "by_tier": tier_breakdown,
        "new_sellers_period": cint(new_sellers),
        "average_seller_score": avg_seller_score,
    }


# =============================================================================
# TOP SELLERS
# =============================================================================


@frappe.whitelist()
def get_top_sellers(
    range_type: str = "last_30_days",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    limit: int = 10,
) -> List[Dict[str, Any]]:
    """
    Get top performing sellers by GMV.

    Returns:
        List of top sellers with sales metrics
    """
    check_admin_permission()

    start, end = get_date_range(range_type, start_date, end_date)
    limit = min(cint(limit) or 10, 50)

    # Build date filter
    date_filter = ""
    date_params = {"limit": limit}
    if start:
        date_filter = "AND so.order_date >= %(start_date)s"
        date_params["start_date"] = start
    if end:
        date_filter += " AND so.order_date <= %(end_date)s"
        date_params["end_date"] = end

    # Get top sellers
    sellers = frappe.db.sql(
        f"""
        SELECT
            so.seller,
            sp.business_name,
            sp.seller_score,
            sp.seller_tier,
            sp.average_rating,
            sp.total_reviews,
            COUNT(so.name) as order_count,
            COALESCE(SUM(so.grand_total), 0) as total_gmv,
            COALESCE(SUM(so.commission_amount), 0) as total_commission,
            COUNT(DISTINCT so.buyer) as unique_customers
        FROM `tabSub Order` so
        JOIN `tabSeller Profile` sp ON so.seller = sp.name
        WHERE so.status NOT IN ('Cancelled', 'Draft')
        {date_filter}
        GROUP BY so.seller, sp.business_name, sp.seller_score, sp.seller_tier,
                 sp.average_rating, sp.total_reviews
        ORDER BY total_gmv DESC
        LIMIT %(limit)s
    """,
        date_params,
        as_dict=True,
    )

    currency = "TRY"

    result = []
    for idx, seller in enumerate(sellers, 1):
        result.append({
            "rank": idx,
            "seller": seller.seller,
            "business_name": seller.business_name,
            "seller_score": flt(seller.seller_score, 1),
            "seller_tier": seller.seller_tier,
            "average_rating": flt(seller.average_rating, 2),
            "total_reviews": cint(seller.total_reviews),
            "order_count": cint(seller.order_count),
            "unique_customers": cint(seller.unique_customers),
            "total_gmv": flt(seller.total_gmv, 2),
            "total_gmv_formatted": format_currency_value(seller.total_gmv, currency),
            "total_commission": flt(seller.total_commission, 2),
            "total_commission_formatted": format_currency_value(
                seller.total_commission, currency
            ),
        })

    return result


# =============================================================================
# TOP CATEGORIES
# =============================================================================


@frappe.whitelist()
def get_top_categories(
    range_type: str = "last_30_days",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    limit: int = 10,
) -> List[Dict[str, Any]]:
    """
    Get top performing categories by sales.

    Returns:
        List of top categories with sales metrics
    """
    check_admin_permission()

    start, end = get_date_range(range_type, start_date, end_date)
    limit = min(cint(limit) or 10, 20)

    # Build date filter
    date_filter = ""
    date_params = {"limit": limit}
    if start:
        date_filter = "AND so.order_date >= %(start_date)s"
        date_params["start_date"] = start
    if end:
        date_filter += " AND so.order_date <= %(end_date)s"
        date_params["end_date"] = end

    # Get top categories
    categories = frappe.db.sql(
        f"""
        SELECT
            l.category,
            c.category_name,
            COUNT(DISTINCT so.name) as order_count,
            SUM(soi.quantity) as units_sold,
            COALESCE(SUM(soi.amount), 0) as total_revenue,
            COUNT(DISTINCT so.seller) as seller_count,
            COUNT(DISTINCT so.buyer) as buyer_count
        FROM `tabSub Order Item` soi
        JOIN `tabSub Order` so ON soi.parent = so.name
        JOIN `tabListing` l ON soi.listing = l.name
        LEFT JOIN `tabCategory` c ON l.category = c.name
        WHERE so.status NOT IN ('Cancelled', 'Draft')
        {date_filter}
        GROUP BY l.category, c.category_name
        ORDER BY total_revenue DESC
        LIMIT %(limit)s
    """,
        date_params,
        as_dict=True,
    )

    currency = "TRY"
    total_revenue = sum(flt(c.total_revenue) for c in categories)

    result = []
    for idx, cat in enumerate(categories, 1):
        percentage = (
            round((flt(cat.total_revenue) / total_revenue) * 100, 1)
            if total_revenue > 0
            else 0
        )
        result.append({
            "rank": idx,
            "category": cat.category,
            "category_name": cat.category_name or cat.category,
            "order_count": cint(cat.order_count),
            "units_sold": cint(cat.units_sold),
            "total_revenue": flt(cat.total_revenue, 2),
            "total_revenue_formatted": format_currency_value(cat.total_revenue, currency),
            "seller_count": cint(cat.seller_count),
            "buyer_count": cint(cat.buyer_count),
            "percentage": percentage,
        })

    return result


# =============================================================================
# MODERATION OVERVIEW
# =============================================================================


@frappe.whitelist()
def get_moderation_overview() -> Dict[str, Any]:
    """
    Get moderation and case management overview.

    Returns:
        Dict containing:
        - pending_listings: Listings awaiting moderation
        - pending_reviews: Reviews awaiting moderation
        - open_disputes: Open dispute cases
        - open_account_actions: Active account actions
        - moderation_queue_age: Average age of pending items
    """
    check_admin_permission()

    # Get pending listing moderation
    pending_listings = frappe.db.count(
        "Listing",
        {"moderation_status": "Pending"},
    )

    # Get pending reviews (if Review DocType has moderation)
    pending_reviews = 0
    if frappe.db.exists("DocType", "Review"):
        pending_reviews = frappe.db.count(
            "Review",
            {"moderation_status": ["in", ["Pending", "Flagged"]]},
        )

    # Get open disputes (if Dispute DocType exists)
    open_disputes = 0
    if frappe.db.exists("DocType", "Dispute"):
        open_disputes = frappe.db.count(
            "Dispute",
            {"status": ["in", ["Open", "Under Review", "Escalated"]]},
        )

    # Get active account actions
    active_actions = frappe.db.count(
        "Account Action",
        {"status": "Active"},
    )

    # Get pending seller applications
    pending_applications = frappe.db.count(
        "Seller Application",
        {"status": ["in", ["Submitted", "Under Review"]]},
    )

    # Get moderation case statistics
    case_by_status = {}
    if frappe.db.exists("DocType", "Moderation Case"):
        case_stats = frappe.db.sql(
            """
            SELECT status, COUNT(*) as count
            FROM `tabModeration Case`
            GROUP BY status
        """,
            as_dict=True,
        )
        case_by_status = {c.status: cint(c.count) for c in case_stats}

    return {
        "pending_listings": cint(pending_listings),
        "pending_reviews": cint(pending_reviews),
        "open_disputes": cint(open_disputes),
        "active_account_actions": cint(active_actions),
        "pending_seller_applications": cint(pending_applications),
        "cases_by_status": case_by_status,
        "total_pending": cint(pending_listings) + cint(pending_reviews) + cint(pending_applications),
    }


# =============================================================================
# RECENT ACTIVITY
# =============================================================================


@frappe.whitelist()
def get_recent_activity(limit: int = 20) -> List[Dict[str, Any]]:
    """
    Get recent platform activity feed.

    Returns:
        List of recent activities across the platform
    """
    check_admin_permission()

    limit = min(cint(limit) or 20, 100)
    activities = []

    # Get recent orders
    recent_orders = frappe.db.get_all(
        "Marketplace Order",
        filters={"status": ["!=", "Draft"]},
        fields=["name", "order_id", "buyer_name", "grand_total", "status", "creation"],
        order_by="creation desc",
        limit_page_length=5,
    )

    for order in recent_orders:
        activities.append({
            "type": "order",
            "icon": "shopping-cart",
            "color": CHART_COLORS["primary"],
            "title": _("New Order #{0}").format(order.order_id or order.name[:8]),
            "description": _("Order placed by {0} for {1}").format(
                order.buyer_name,
                format_currency_value(order.grand_total),
            ),
            "timestamp": get_datetime_str(order.creation),
            "time_ago": frappe.utils.pretty_date(order.creation),
            "reference_doctype": "Marketplace Order",
            "reference_name": order.name,
        })

    # Get recent seller applications
    recent_applications = frappe.db.get_all(
        "Seller Application",
        filters={"status": ["in", ["Submitted", "Approved", "Rejected"]]},
        fields=["name", "applicant_name", "status", "creation"],
        order_by="creation desc",
        limit_page_length=5,
    )

    for app in recent_applications:
        status_colors = {
            "Submitted": CHART_COLORS["info"],
            "Approved": CHART_COLORS["success"],
            "Rejected": CHART_COLORS["danger"],
        }
        activities.append({
            "type": "seller_application",
            "icon": "user-plus",
            "color": status_colors.get(app.status, CHART_COLORS["secondary"]),
            "title": _("Seller Application {0}").format(app.status),
            "description": _("Application from {0}").format(app.applicant_name),
            "timestamp": get_datetime_str(app.creation),
            "time_ago": frappe.utils.pretty_date(app.creation),
            "reference_doctype": "Seller Application",
            "reference_name": app.name,
        })

    # Get recent listings
    recent_listings = frappe.db.get_all(
        "Listing",
        filters={"status": ["in", ["Published", "Pending Moderation"]]},
        fields=["name", "title", "seller", "status", "creation"],
        order_by="creation desc",
        limit_page_length=5,
    )

    for listing in recent_listings:
        seller_name = frappe.db.get_value("Seller Profile", listing.seller, "business_name") or listing.seller
        activities.append({
            "type": "listing",
            "icon": "package",
            "color": CHART_COLORS["teal"],
            "title": _("New Listing Created"),
            "description": _("{0} by {1}").format(listing.title[:50], seller_name),
            "timestamp": get_datetime_str(listing.creation),
            "time_ago": frappe.utils.pretty_date(listing.creation),
            "reference_doctype": "Listing",
            "reference_name": listing.name,
        })

    # Get recent account actions
    recent_actions = frappe.db.get_all(
        "Account Action",
        filters={},
        fields=["name", "action_type", "target_type", "target_name", "status", "creation"],
        order_by="creation desc",
        limit_page_length=5,
    )

    for action in recent_actions:
        activities.append({
            "type": "account_action",
            "icon": "alert-triangle",
            "color": CHART_COLORS["warning"],
            "title": _("{0} - {1}").format(action.action_type, action.target_type),
            "description": _("Action on {0}").format(action.target_name),
            "timestamp": get_datetime_str(action.creation),
            "time_ago": frappe.utils.pretty_date(action.creation),
            "reference_doctype": "Account Action",
            "reference_name": action.name,
        })

    # Sort all activities by timestamp
    activities.sort(key=lambda x: x["timestamp"], reverse=True)

    return activities[:limit]


# =============================================================================
# SYSTEM HEALTH
# =============================================================================


@frappe.whitelist()
def get_system_health() -> Dict[str, Any]:
    """
    Get system health metrics.

    Returns:
        Dict containing:
        - background_jobs: Background job queue status
        - scheduler_status: Scheduler health
        - database_size: Database size info
        - cache_status: Redis cache status
        - error_logs: Recent error count
    """
    check_admin_permission()

    # Get background job queue status
    pending_jobs = frappe.db.count("RQ Job", {"status": "queued"})
    failed_jobs = frappe.db.count("RQ Job", {"status": "failed"})

    # Get scheduler status
    scheduler_enabled = frappe.db.get_single_value("System Settings", "enable_scheduler")

    # Get recent error log count (last 24 hours)
    yesterday = add_days(nowdate(), -1)
    error_count = frappe.db.count(
        "Error Log",
        {"creation": [">=", yesterday]},
    )

    # Get system info
    import os

    disk_usage = None
    try:
        import shutil
        total, used, free = shutil.disk_usage("/")
        disk_usage = {
            "total_gb": round(total / (1024**3), 2),
            "used_gb": round(used / (1024**3), 2),
            "free_gb": round(free / (1024**3), 2),
            "used_percent": round((used / total) * 100, 1),
        }
    except Exception:
        pass

    # Get database table counts
    table_counts = {
        "users": frappe.db.count("User"),
        "sellers": frappe.db.count("Seller Profile"),
        "listings": frappe.db.count("Listing"),
        "orders": frappe.db.count("Marketplace Order"),
        "sub_orders": frappe.db.count("Sub Order"),
    }

    # Get cache info
    cache_info = None
    try:
        cache = frappe.cache()
        if hasattr(cache, "redis"):
            info = cache.redis.info()
            cache_info = {
                "used_memory": info.get("used_memory_human", "N/A"),
                "connected_clients": info.get("connected_clients", 0),
                "uptime_days": info.get("uptime_in_days", 0),
            }
    except Exception:
        pass

    return {
        "background_jobs": {
            "pending": cint(pending_jobs),
            "failed": cint(failed_jobs),
        },
        "scheduler": {
            "enabled": bool(scheduler_enabled),
            "status": "Active" if scheduler_enabled else "Disabled",
        },
        "error_logs": {
            "last_24h": cint(error_count),
            "status": "Normal" if error_count < 100 else "Warning" if error_count < 500 else "Critical",
        },
        "disk_usage": disk_usage,
        "table_counts": table_counts,
        "cache": cache_info,
        "status": "Healthy" if error_count < 100 and failed_jobs < 50 else "Degraded",
    }


# =============================================================================
# GEOGRAPHIC DISTRIBUTION
# =============================================================================


@frappe.whitelist()
def get_geographic_distribution(
    range_type: str = "last_30_days",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Get geographic distribution of orders.

    Returns:
        Dict containing order distribution by region/city
    """
    check_admin_permission()

    start, end = get_date_range(range_type, start_date, end_date)

    # Build date filter
    date_filter = ""
    date_params = {}
    if start:
        date_filter = "AND mo.order_date >= %(start_date)s"
        date_params["start_date"] = start
    if end:
        date_filter += " AND mo.order_date <= %(end_date)s"
        date_params["end_date"] = end

    # Get distribution by city (from shipping address)
    city_distribution = frappe.db.sql(
        f"""
        SELECT
            COALESCE(mo.shipping_city, 'Unknown') as city,
            COUNT(mo.name) as order_count,
            COALESCE(SUM(mo.grand_total), 0) as total_gmv
        FROM `tabMarketplace Order` mo
        WHERE mo.status NOT IN ('Cancelled', 'Draft')
        {date_filter}
        GROUP BY mo.shipping_city
        ORDER BY order_count DESC
        LIMIT 15
    """,
        date_params,
        as_dict=True,
    )

    # Get seller distribution by city
    seller_by_city = frappe.db.sql(
        """
        SELECT
            COALESCE(sp.city, 'Unknown') as city,
            COUNT(sp.name) as seller_count
        FROM `tabSeller Profile` sp
        WHERE sp.status = 'Active'
        GROUP BY sp.city
        ORDER BY seller_count DESC
        LIMIT 10
    """,
        as_dict=True,
    )

    currency = "TRY"

    return {
        "orders_by_city": [
            {
                "city": c.city,
                "order_count": cint(c.order_count),
                "total_gmv": flt(c.total_gmv, 2),
                "total_gmv_formatted": format_currency_value(c.total_gmv, currency),
            }
            for c in city_distribution
        ],
        "sellers_by_city": [
            {
                "city": s.city,
                "seller_count": cint(s.seller_count),
            }
            for s in seller_by_city
        ],
    }


# =============================================================================
# REVENUE & COMMISSION ANALYTICS
# =============================================================================


@frappe.whitelist()
def get_revenue_analytics(
    range_type: str = "last_30_days",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Get detailed revenue and commission analytics.

    Returns:
        Dict containing:
        - total_gmv: Total GMV
        - total_commission: Total commission earned
        - commission_rate: Average commission rate
        - revenue_by_payment_method: Breakdown by payment method
        - escrow_summary: Escrow status summary
    """
    check_admin_permission()

    start, end = get_date_range(range_type, start_date, end_date)

    # Build date filter
    date_filter = ""
    date_params = {}
    if start:
        date_filter = "AND mo.order_date >= %(start_date)s"
        date_params["start_date"] = start
    if end:
        date_filter += " AND mo.order_date <= %(end_date)s"
        date_params["end_date"] = end

    # Get revenue summary
    revenue = frappe.db.sql(
        f"""
        SELECT
            COALESCE(SUM(mo.grand_total), 0) as total_gmv,
            COALESCE(SUM(mo.subtotal), 0) as subtotal,
            COALESCE(SUM(mo.tax_amount), 0) as total_tax,
            COALESCE(SUM(mo.shipping_amount), 0) as total_shipping,
            COALESCE(SUM(mo.discount_amount), 0) as total_discounts
        FROM `tabMarketplace Order` mo
        WHERE mo.status NOT IN ('Cancelled', 'Draft')
        {date_filter}
    """,
        date_params,
        as_dict=True,
    )

    # Get commission summary
    commission = frappe.db.sql(
        f"""
        SELECT
            COALESCE(SUM(so.commission_amount), 0) as total_commission,
            COALESCE(SUM(so.seller_payout), 0) as total_seller_payout,
            COALESCE(AVG(so.commission_rate), 0) as avg_commission_rate
        FROM `tabSub Order` so
        WHERE so.status NOT IN ('Cancelled', 'Draft')
        {date_filter.replace('mo.', 'so.')}
    """,
        date_params,
        as_dict=True,
    )

    # Get payment method breakdown
    payment_breakdown = frappe.db.sql(
        f"""
        SELECT
            COALESCE(mo.payment_method, 'Other') as payment_method,
            COUNT(mo.name) as order_count,
            COALESCE(SUM(mo.grand_total), 0) as total_amount
        FROM `tabMarketplace Order` mo
        WHERE mo.status NOT IN ('Cancelled', 'Draft')
        {date_filter}
        GROUP BY mo.payment_method
        ORDER BY total_amount DESC
    """,
        date_params,
        as_dict=True,
    )

    # Get escrow summary
    escrow_summary = frappe.db.sql(
        """
        SELECT
            escrow_status,
            COUNT(*) as count,
            COALESCE(SUM(seller_payout), 0) as amount
        FROM `tabSub Order`
        WHERE status NOT IN ('Cancelled', 'Draft')
        GROUP BY escrow_status
    """,
        as_dict=True,
    )

    currency = "TRY"
    rev_data = revenue[0] if revenue else {}
    comm_data = commission[0] if commission else {}

    return {
        "total_gmv": flt(rev_data.get("total_gmv", 0), 2),
        "total_gmv_formatted": format_currency_value(rev_data.get("total_gmv", 0), currency),
        "subtotal": flt(rev_data.get("subtotal", 0), 2),
        "total_tax": flt(rev_data.get("total_tax", 0), 2),
        "total_shipping": flt(rev_data.get("total_shipping", 0), 2),
        "total_discounts": flt(rev_data.get("total_discounts", 0), 2),
        "total_commission": flt(comm_data.get("total_commission", 0), 2),
        "total_commission_formatted": format_currency_value(
            comm_data.get("total_commission", 0), currency
        ),
        "total_seller_payout": flt(comm_data.get("total_seller_payout", 0), 2),
        "avg_commission_rate": flt(comm_data.get("avg_commission_rate", 0), 2),
        "payment_methods": [
            {
                "method": p.payment_method,
                "order_count": cint(p.order_count),
                "total_amount": flt(p.total_amount, 2),
                "total_amount_formatted": format_currency_value(p.total_amount, currency),
            }
            for p in payment_breakdown
        ],
        "escrow_summary": [
            {
                "status": e.escrow_status or "Not Set",
                "count": cint(e.count),
                "amount": flt(e.amount, 2),
                "amount_formatted": format_currency_value(e.amount, currency),
            }
            for e in escrow_summary
        ],
        "currency": currency,
    }


# =============================================================================
# USER ANALYTICS
# =============================================================================


@frappe.whitelist()
def get_user_analytics(
    range_type: str = "last_30_days",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Get user analytics for the platform.

    Returns:
        Dict containing user registration, activity metrics
    """
    check_admin_permission()

    start, end = get_date_range(range_type, start_date, end_date)

    # Get total user counts
    total_users = frappe.db.count("User", {"enabled": 1})
    website_users = frappe.db.count("User", {"enabled": 1, "user_type": "Website User"})
    system_users = frappe.db.count("User", {"enabled": 1, "user_type": "System User"})

    # Get new users in period
    new_users = 0
    if start:
        new_users = frappe.db.count(
            "User",
            {
                "creation": [">=", start],
                "enabled": 1,
            },
        )

    # Get active users (logged in during period)
    active_users = 0
    if start:
        active_users = frappe.db.sql(
            """
            SELECT COUNT(DISTINCT user) as count
            FROM `tabActivity Log`
            WHERE creation >= %(start_date)s
            AND user NOT IN ('Guest', 'Administrator')
        """,
            {"start_date": start},
            as_dict=True,
        )
        active_users = active_users[0].count if active_users else 0

    # Get buyer vs seller breakdown
    buyer_count = frappe.db.sql(
        """
        SELECT COUNT(DISTINCT buyer) as count
        FROM `tabMarketplace Order`
        WHERE status NOT IN ('Draft', 'Cancelled')
    """,
        as_dict=True,
    )

    return {
        "total_users": cint(total_users),
        "website_users": cint(website_users),
        "system_users": cint(system_users),
        "new_users_period": cint(new_users),
        "active_users_period": cint(active_users),
        "total_buyers": cint(buyer_count[0].count) if buyer_count else 0,
        "total_sellers": frappe.db.count("Seller Profile", {"status": "Active"}),
    }


# =============================================================================
# LISTING ANALYTICS
# =============================================================================


@frappe.whitelist()
def get_listing_analytics() -> Dict[str, Any]:
    """
    Get listing analytics for the platform.

    Returns:
        Dict containing listing statistics
    """
    check_admin_permission()

    # Get listing counts by status
    status_counts = frappe.db.sql(
        """
        SELECT status, COUNT(*) as count
        FROM `tabListing`
        GROUP BY status
    """,
        as_dict=True,
    )

    status_breakdown = {s.status: cint(s.count) for s in status_counts}

    # Get moderation status breakdown
    moderation_counts = frappe.db.sql(
        """
        SELECT moderation_status, COUNT(*) as count
        FROM `tabListing`
        GROUP BY moderation_status
    """,
        as_dict=True,
    )

    moderation_breakdown = {m.moderation_status: cint(m.count) for m in moderation_counts}

    # Get listing type breakdown
    type_counts = frappe.db.sql(
        """
        SELECT listing_type, COUNT(*) as count
        FROM `tabListing`
        WHERE status = 'Published'
        GROUP BY listing_type
    """,
        as_dict=True,
    )

    type_breakdown = {t.listing_type: cint(t.count) for t in type_counts}

    # Get average listing metrics
    avg_metrics = frappe.db.sql(
        """
        SELECT
            AVG(selling_price) as avg_price,
            AVG(view_count) as avg_views,
            AVG(order_count) as avg_orders,
            AVG(average_rating) as avg_rating
        FROM `tabListing`
        WHERE status = 'Published'
    """,
        as_dict=True,
    )

    metrics = avg_metrics[0] if avg_metrics else {}

    # Get out of stock listings
    out_of_stock = frappe.db.count(
        "Listing",
        {
            "status": "Published",
            "track_inventory": 1,
            "available_qty": ["<=", 0],
        },
    )

    total_listings = sum(status_breakdown.values())
    published_listings = status_breakdown.get("Published", 0)

    return {
        "total_listings": total_listings,
        "published_listings": published_listings,
        "by_status": status_breakdown,
        "by_moderation_status": moderation_breakdown,
        "by_listing_type": type_breakdown,
        "out_of_stock": cint(out_of_stock),
        "avg_price": flt(metrics.get("avg_price", 0), 2),
        "avg_views": flt(metrics.get("avg_views", 0), 1),
        "avg_orders": flt(metrics.get("avg_orders", 0), 1),
        "avg_rating": flt(metrics.get("avg_rating", 0), 2),
    }


# =============================================================================
# COMPLIANCE METRICS
# =============================================================================


@frappe.whitelist()
def get_compliance_metrics() -> Dict[str, Any]:
    """
    Get compliance and governance metrics.

    Returns:
        Dict containing KVKK compliance, KYC status, etc.
    """
    check_admin_permission()

    # Get KYC verification status
    kyc_status = frappe.db.sql(
        """
        SELECT verification_status, COUNT(*) as count
        FROM `tabKYC Profile`
        GROUP BY verification_status
    """,
        as_dict=True,
    )

    kyc_breakdown = {k.verification_status: cint(k.count) for k in kyc_status}

    # Get consent statistics
    consent_stats = {}
    if frappe.db.exists("DocType", "Consent Record"):
        consent_data = frappe.db.sql(
            """
            SELECT
                consent_type,
                status,
                COUNT(*) as count
            FROM `tabConsent Record`
            GROUP BY consent_type, status
        """,
            as_dict=True,
        )

        for c in consent_data:
            if c.consent_type not in consent_stats:
                consent_stats[c.consent_type] = {}
            consent_stats[c.consent_type][c.status] = cint(c.count)

    # Get organization verification status
    org_verification = frappe.db.sql(
        """
        SELECT kyb_status, COUNT(*) as count
        FROM `tabOrganization`
        GROUP BY kyb_status
    """,
        as_dict=True,
    )

    org_breakdown = {o.kyb_status: cint(o.count) for o in org_verification}

    # Get e-invoice enabled sellers
    einvoice_enabled = frappe.db.count(
        "Seller Profile",
        {"e_invoice_enabled": 1, "status": "Active"},
    )

    total_active_sellers = frappe.db.count(
        "Seller Profile",
        {"status": "Active"},
    )

    return {
        "kyc_verification": kyc_breakdown,
        "kyb_verification": org_breakdown,
        "consent_stats": consent_stats,
        "einvoice_adoption": {
            "enabled": cint(einvoice_enabled),
            "total_active_sellers": cint(total_active_sellers),
            "adoption_rate": round(
                (einvoice_enabled / total_active_sellers * 100)
                if total_active_sellers > 0 else 0, 1
            ),
        },
    }


# =============================================================================
# EXPORT DATA
# =============================================================================


@frappe.whitelist()
def export_dashboard_report(
    report_type: str = "summary",
    range_type: str = "last_30_days",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    format: str = "json",
) -> Dict[str, Any]:
    """
    Export dashboard data for reporting.

    Args:
        report_type: Type of report (summary, detailed, sellers, orders)
        range_type: Date range type
        start_date: Custom start date
        end_date: Custom end date
        format: Export format (json, csv)

    Returns:
        Dict containing exported data
    """
    check_admin_permission()

    if report_type == "summary":
        data = {
            "metrics": get_platform_metrics(range_type, start_date, end_date),
            "seller_overview": get_seller_overview(range_type, start_date, end_date),
            "moderation_overview": get_moderation_overview(),
        }
    elif report_type == "sellers":
        data = {
            "top_sellers": get_top_sellers(range_type, start_date, end_date, limit=50),
            "seller_overview": get_seller_overview(range_type, start_date, end_date),
        }
    elif report_type == "orders":
        data = {
            "metrics": get_platform_metrics(range_type, start_date, end_date),
            "order_status": get_order_status_breakdown(range_type, start_date, end_date),
            "top_categories": get_top_categories(range_type, start_date, end_date, limit=20),
        }
    elif report_type == "revenue":
        data = {
            "revenue_analytics": get_revenue_analytics(range_type, start_date, end_date),
            "gmv_trend": get_gmv_trend_chart(range_type, start_date, end_date),
        }
    else:
        data = get_admin_dashboard(range_type, start_date, end_date)

    return {
        "report_type": report_type,
        "date_range": {
            "type": range_type,
            "start_date": start_date,
            "end_date": end_date,
        },
        "generated_at": get_datetime_str(now_datetime()),
        "generated_by": frappe.session.user,
        "data": data,
    }

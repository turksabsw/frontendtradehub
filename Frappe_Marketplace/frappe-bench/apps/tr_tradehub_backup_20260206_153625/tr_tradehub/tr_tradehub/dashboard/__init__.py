# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

"""
Dashboard Module for TR-TradeHub Marketplace

This module provides dashboard APIs and visualization components for:
- Seller Dashboard: Sales metrics, order analytics, performance tracking
- Admin Dashboard: Platform-wide metrics, moderation queue, compliance
- Buyer Dashboard: Purchase history, saved items, recommendations

Dashboard APIs follow Frappe conventions:
- Use @frappe.whitelist() for all endpoints
- Return chart-ready data structures for frontend visualization
- Implement caching for heavy queries
- Support date range filtering

API URL Pattern:
    POST /api/method/tr_tradehub.dashboard.<module>.<function_name>
"""

from tr_tradehub.dashboard.seller_dashboard import (
    get_seller_dashboard,
    get_sales_metrics,
    get_sales_trend_chart,
    get_order_status_chart,
    get_top_products,
    get_recent_orders,
    get_performance_summary,
    get_category_performance,
    get_revenue_breakdown,
    get_customer_insights,
    get_payout_summary,
    get_conversion_metrics,
)

__all__ = [
    # Seller Dashboard
    "get_seller_dashboard",
    "get_sales_metrics",
    "get_sales_trend_chart",
    "get_order_status_chart",
    "get_top_products",
    "get_recent_orders",
    "get_performance_summary",
    "get_category_performance",
    "get_revenue_breakdown",
    "get_customer_insights",
    "get_payout_summary",
    "get_conversion_metrics",
]

# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

"""
TR TradeHub Tasks Module

Contains scheduled background tasks for:
- Subscription management (grace periods, suspensions, renewals)
- KPI calculations (seller and buyer metrics)
- Other periodic maintenance tasks
"""

from tr_tradehub.tasks.subscription_tasks import (
    check_expiring_subscriptions,
    process_grace_periods,
    suspend_overdue_subscriptions,
    send_grace_period_warnings,
    process_auto_renewals,
    reset_daily_api_limits,
    reset_monthly_order_limits,
    check_trial_expirations,
    run_subscription_maintenance,
    get_subscription_statistics,
)

from tr_tradehub.tasks.kpi_tasks import (
    calculate_daily_seller_kpis,
    calculate_monthly_seller_kpis,
    calculate_buyer_kpis,
    recalculate_seller_rankings,
    update_kpi_trends,
    run_kpi_calculations,
    calculate_single_seller_kpi,
    get_kpi_statistics,
)

__all__ = [
    # Subscription Tasks
    "check_expiring_subscriptions",
    "process_grace_periods",
    "suspend_overdue_subscriptions",
    "send_grace_period_warnings",
    "process_auto_renewals",
    "reset_daily_api_limits",
    "reset_monthly_order_limits",
    "check_trial_expirations",
    "run_subscription_maintenance",
    "get_subscription_statistics",

    # KPI Tasks
    "calculate_daily_seller_kpis",
    "calculate_monthly_seller_kpis",
    "calculate_buyer_kpis",
    "recalculate_seller_rankings",
    "update_kpi_trends",
    "run_kpi_calculations",
    "calculate_single_seller_kpi",
    "get_kpi_statistics",
]

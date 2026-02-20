# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

"""
Seller Tags Module - Rule-based automatic seller tagging system.

This module provides:
- Seller Tag: Badge/label definitions
- Seller Tag Rule: AND/OR condition rules for automatic tagging
- Seller Tag Assignment: Seller-tag relationships
- Seller Metrics: Materialized view of seller KPIs
- Rule Engine: Recursive AND/OR condition evaluator
"""

from tr_tradehub.seller_tags.rule_engine import (
    evaluate_conditions,
    evaluate_group,
    evaluate_condition,
    RuleEngine
)

from tr_tradehub.seller_tags.seller_metrics import (
    refresh_seller_metrics,
    calculate_metrics,
    METRICS_FIELDS
)

__all__ = [
    'evaluate_conditions',
    'evaluate_group',
    'evaluate_condition',
    'RuleEngine',
    'refresh_seller_metrics',
    'calculate_metrics',
    'METRICS_FIELDS'
]

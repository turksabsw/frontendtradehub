# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

"""
Group Buy Module - Contribution-based bulk purchasing system.

This module provides:
- Group Buy: Main group purchase campaigns
- Group Buy Tier: Price tier definitions
- Group Buy Commitment: Buyer commitments
- Dynamic pricing based on contribution model
"""

from tradehub_marketing.tradehub_marketing.groupbuy.pricing import (
    calculate_buyer_price,
    calculate_all_prices,
    check_profitability
)

__all__ = [
    'calculate_buyer_price',
    'calculate_all_prices',
    'check_profitability'
]

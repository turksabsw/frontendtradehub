# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

"""
Setup module for TR TradeHub application.

This module contains setup scripts for initializing and configuring
the TR TradeHub marketplace platform, including:

- Turkey geographic data (cities, districts, neighborhoods)
- Master data imports
- Initial configuration

Usage:
    from tr_tradehub.setup.setup_turkey_data import setup_turkey_data
    setup_turkey_data()
"""

from tr_tradehub.setup.setup_turkey_data import (
    setup_turkey_data,
    setup_districts,
    setup_neighborhoods,
    run_setup_turkey_data,
    get_setup_statistics,
)

__all__ = [
    "setup_turkey_data",
    "setup_districts",
    "setup_neighborhoods",
    "run_setup_turkey_data",
    "get_setup_statistics",
]

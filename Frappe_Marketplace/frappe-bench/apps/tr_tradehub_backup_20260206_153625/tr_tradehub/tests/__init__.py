# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

"""
TR TradeHub Test Suite

This module provides comprehensive unit tests for core DocTypes
in the TR TradeHub marketplace application.

Test modules:
- test_listing: Tests for Listing DocType (products, catalog)
- test_order: Tests for Marketplace Order and Sub Order DocTypes
- test_escrow: Tests for Escrow Account DocType (payment holding)

To run all tests:
    bench --site marketplace.local run-tests --app tr_tradehub

To run specific test module:
    bench --site marketplace.local run-tests --app tr_tradehub --module tr_tradehub.tests.test_listing
"""

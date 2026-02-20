# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

"""
TR-TradeHub API v1 Module

This module contains all version 1 API endpoints for TR-TradeHub marketplace.

API Domains:
- identity: User registration, login, authentication, profile management
- seller: Seller onboarding, profile, storefront management
- listing: Product listing CRUD, variants, media management
- order: Cart, checkout, order management
- payment: Payment processing, escrow, refunds
- shipping: Shipping rates, tracking, carrier integration
- review: Product and seller reviews, ratings
- admin: Admin operations, moderation, governance

Usage:
    Import specific modules to access API functions:

    from tr_tradehub.api.v1 import identity
    from tr_tradehub.api.v1 import seller
    from tr_tradehub.api.v1 import listing

API Versioning:
    All v1 APIs are stable and backward-compatible. Breaking changes
    will be introduced in v2+ only.
"""

from tr_tradehub.api.v1 import identity
from tr_tradehub.api.v1 import seller
from tr_tradehub.api.v1 import admin

__all__ = [
    "identity",
    "seller",
    "admin",
]

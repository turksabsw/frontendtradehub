# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

"""
TR-TradeHub API Module

This module provides the REST API layer for TR-TradeHub marketplace platform.
APIs are organized by version (v1, v2, etc.) and by domain (identity, seller, listing, etc.).

API URL Pattern:
    /api/method/tr_tradehub.api.v1.<domain>.<function_name>

Example:
    POST /api/method/tr_tradehub.api.v1.identity.register
    POST /api/method/tr_tradehub.api.v1.identity.login
    GET /api/method/tr_tradehub.api.v1.identity.get_profile

All APIs follow standard patterns:
- Use @frappe.whitelist() decorator for exposure
- Include rate limiting where appropriate
- Return consistent response structures
- Implement proper error handling
- Log security-relevant events
"""

from tr_tradehub.api import v1

__all__ = ["v1"]

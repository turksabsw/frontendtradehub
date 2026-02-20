# Copyright (c) 2024, TradeHub and contributors
# For license information, please see license.txt

"""Integrations for TradeHub Logistics

This module provides external service integrations for the logistics layer:
- Carrier integrations (Aras Kargo, Yurtici Kargo)
- Future: Fulfillment provider integrations
- Future: Address validation services
"""

from tradehub_logistics.integrations import carriers

__all__ = ["carriers"]

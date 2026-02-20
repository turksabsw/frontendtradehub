# Copyright (c) 2024, TradeHub and contributors
# For license information, please see license.txt

"""Carrier Integrations for TradeHub Logistics

This module provides carrier API integrations for Turkish shipping companies:
- Aras Kargo: Major Turkish cargo carrier with API tracking support
- Yurtici Kargo: Leading Turkish logistics company with comprehensive API

Each carrier integration provides methods to:
- Get shipment tracking information
- Create shipping labels (where supported)
- Calculate shipping rates (where supported)
- Handle delivery status updates
"""

from tradehub_logistics.integrations.carriers.aras import ArasIntegration
from tradehub_logistics.integrations.carriers.yurtici import YurticiIntegration

__all__ = ["ArasIntegration", "YurticiIntegration"]

# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

"""
RFQ (Request for Quote) Module - Alibaba-style quotation system.

This module provides:
- RFQ: Main request for quote
- RFQ Item: Requested products
- RFQ Quote: Seller quotes with revision support
- RFQ Message Thread: Ticket-style messaging
- NDA Integration: Contract Instance linking
"""

from tr_tradehub.rfq.nda_integration import (
    create_nda_for_rfq,
    check_nda_signed,
    get_nda_status
)

__all__ = [
    'create_nda_for_rfq',
    'check_nda_signed',
    'get_nda_status'
]

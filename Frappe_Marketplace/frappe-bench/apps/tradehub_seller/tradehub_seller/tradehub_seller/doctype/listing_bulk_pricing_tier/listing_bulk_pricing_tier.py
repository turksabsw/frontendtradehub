# Copyright (c) 2026, TR TradeHub and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class ListingBulkPricingTier(Document):
    # begin: auto-generated types
    # This code is auto-generated. Do not modify anything in this block.

    from typing import TYPE_CHECKING

    if TYPE_CHECKING:
        from frappe.types import DF

        description: DF.SmallText | None
        discount_percentage: DF.Percent
        is_active: DF.Check
        max_qty: DF.Int
        min_qty: DF.Int
        parent: DF.Data
        parentfield: DF.Data
        parenttype: DF.Data
        price: DF.Currency
    # end: auto-generated types

    pass

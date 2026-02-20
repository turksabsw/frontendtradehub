# Copyright (c) 2026, TR TradeHub and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class ListingAttributeValue(Document):
    # begin: auto-generated types
    # This code is auto-generated. Do not modify anything in this block.

    from typing import TYPE_CHECKING

    if TYPE_CHECKING:
        from frappe.types import DF

        attribute: DF.Link
        attribute_name: DF.Data | None
        is_variant_attribute: DF.Check
        parent: DF.Data
        parentfield: DF.Data
        parenttype: DF.Data
        sort_order: DF.Int
        unit: DF.Data | None
        value: DF.Data
        value_label: DF.Data | None
    # end: auto-generated types

    pass

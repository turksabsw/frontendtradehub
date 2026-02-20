# Copyright (c) 2026, TR TradeHub and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class ListingImage(Document):
    # begin: auto-generated types
    # This code is auto-generated. Do not modify anything in this block.

    from typing import TYPE_CHECKING

    if TYPE_CHECKING:
        from frappe.types import DF

        alt_text: DF.Data | None
        channel: DF.Link | None
        image: DF.AttachImage
        image_angle: DF.Literal["", "Front", "Back", "Left", "Right", "Top", "Bottom", "Detail", "Packaging", "Lifestyle", "Dimensions", "Other"]
        is_primary: DF.Check
        parent: DF.Data
        parentfield: DF.Data
        parenttype: DF.Data
        sort_order: DF.Int
    # end: auto-generated types

    pass

# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class AttributeSetItem(Document):
    """
    Attribute Set Item child table for TR-TradeHub marketplace.

    This is a child table that links attributes to attribute sets,
    allowing override of attribute settings per attribute set context.
    """
    pass

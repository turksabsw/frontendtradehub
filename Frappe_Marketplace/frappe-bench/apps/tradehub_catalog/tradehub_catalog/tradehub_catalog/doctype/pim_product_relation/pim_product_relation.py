# Copyright (c) 2026, TR TradeHub and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class PIMProductRelation(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		channel: DF.Link | None
		is_bidirectional: DF.Check
		notes: DF.SmallText | None
		parent: DF.Data
		parentfield: DF.Data
		parenttype: DF.Data
		related_product: DF.Link
		related_product_name: DF.Data | None
		relation_type: DF.Literal["Related", "Cross-Sell", "Up-Sell", "Down-Sell", "Replacement", "Accessory", "Spare Part", "Bundle Item", "Similar", "Frequently Bought Together", "Custom"]
		sort_order: DF.Int
	# end: auto-generated types

	pass

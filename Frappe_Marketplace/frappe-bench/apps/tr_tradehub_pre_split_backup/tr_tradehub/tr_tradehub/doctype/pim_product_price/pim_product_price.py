# Copyright (c) 2026, TR TradeHub and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class PIMProductPrice(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		channel: DF.Link | None
		currency: DF.Link
		customer_group: DF.Link | None
		locale: DF.Data | None
		max_qty: DF.Float
		min_qty: DF.Float
		parent: DF.Data
		parentfield: DF.Data
		parenttype: DF.Data
		price: DF.Currency
		price_tier: DF.Data | None
		price_type: DF.Literal["Standard", "Sale", "MSRP", "MAP", "Wholesale", "Distributor", "Cost", "Promotion", "Bundle", "Custom"]
		valid_from: DF.Datetime | None
		valid_to: DF.Datetime | None
	# end: auto-generated types

	pass

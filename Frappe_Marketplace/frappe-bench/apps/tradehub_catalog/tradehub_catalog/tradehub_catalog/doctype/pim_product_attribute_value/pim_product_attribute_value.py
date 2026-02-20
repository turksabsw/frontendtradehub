# Copyright (c) 2026, TR TradeHub and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class PIMProductAttributeValue(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		attribute_code: DF.Data | None
		attribute_type: DF.Data | None
		channel: DF.Link | None
		locale: DF.Data | None
		parent: DF.Data
		parentfield: DF.Data
		parenttype: DF.Data
		pim_attribute: DF.Link
		value_check: DF.Check
		value_date: DF.Date | None
		value_datetime: DF.Datetime | None
		value_float: DF.Float
		value_html: DF.TextEditor | None
		value_int: DF.Int
		value_json: DF.Code | None
		value_link: DF.Data | None
		value_long_text: DF.SmallText | None
		value_select: DF.Data | None
		value_text: DF.Data | None
	# end: auto-generated types

	pass

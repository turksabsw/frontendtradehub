# Copyright (c) 2026, TR TradeHub and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class PIMProductClassFieldValue(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		field_code: DF.Data
		field_label: DF.Data | None
		field_type: DF.Literal["Data", "Int", "Float", "Currency", "Percent", "Check", "Select", "Link", "Date", "Datetime", "Text", "Text Editor", "Code", "Attach", "Attach Image", "Color", "Rating"]
		parent: DF.Data
		parentfield: DF.Data
		parenttype: DF.Data
		value_check: DF.Check
		value_date: DF.Date | None
		value_datetime: DF.Datetime | None
		value_float: DF.Float
		value_int: DF.Int
		value_json: DF.Code | None
		value_link: DF.Data | None
		value_long_text: DF.Text | None
		value_text: DF.Data | None
	# end: auto-generated types

	pass

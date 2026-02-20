# Copyright (c) 2026, TR TradeHub and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class ProductClassField(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		default_value: DF.SmallText | None
		depends_on: DF.Data | None
		description: DF.SmallText | None
		field_label: DF.Data
		field_name: DF.Data
		fieldtype: DF.Literal["Data", "Text", "Long Text", "Text Editor", "Int", "Float", "Currency", "Check", "Select", "Link", "Date", "Datetime", "Time", "Attach", "Attach Image", "Color", "Code", "JSON", "Password", "Read Only", "Small Text"]
		is_required: DF.Check
		is_unique: DF.Check
		options: DF.SmallText | None
		parent: DF.Data
		parentfield: DF.Data
		parenttype: DF.Data
		read_only: DF.Check
		sort_order: DF.Int
	# end: auto-generated types

	pass

# Copyright (c) 2026, TR TradeHub and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class ProductClassSearchConfig(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		boost_weight: DF.Float
		default_sort_direction: DF.Literal["", "ASC", "DESC"]
		field_label: DF.Data | None
		field_name: DF.Data
		filter_widget: DF.Literal["Text Input", "Dropdown", "Checkbox List", "Range Slider", "Date Picker", "Color Picker", "Auto"]
		is_enabled: DF.Check
		is_faceted: DF.Check
		is_filterable: DF.Check
		is_sortable: DF.Check
		parent: DF.Data
		parentfield: DF.Data
		parenttype: DF.Data
		search_type: DF.Literal["Full Text", "Exact Match", "Prefix", "Fuzzy", "Range", "None"]
		sort_order: DF.Int
	# end: auto-generated types

	pass

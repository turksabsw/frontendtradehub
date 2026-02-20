# Copyright (c) 2026, TR TradeHub and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class VariantAxis(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		axis_order: DF.Int
		is_primary_axis: DF.Check
		parent: DF.Data
		parentfield: DF.Data
		parenttype: DF.Data
		pim_attribute: DF.Link
		show_in_variant_name: DF.Check
	# end: auto-generated types

	pass

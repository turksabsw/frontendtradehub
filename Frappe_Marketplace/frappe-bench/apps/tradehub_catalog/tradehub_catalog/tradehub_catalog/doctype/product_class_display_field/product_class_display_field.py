# Copyright (c) 2026, TR TradeHub and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class ProductClassDisplayField(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		css_class: DF.Data | None
		display_location: DF.Literal["Card Title", "Card Subtitle", "Card Badge", "Card Description", "List View", "Detail Header", "Detail Sidebar", "Quick View"]
		field_label: DF.Data | None
		field_name: DF.Data
		format_template: DF.SmallText | None
		parent: DF.Data
		parentfield: DF.Data
		parenttype: DF.Data
		show_label: DF.Check
		sort_order: DF.Int
	# end: auto-generated types

	pass

# Copyright (c) 2026, TR TradeHub and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class AttributeLabelOverride(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		custom_description: DF.SmallText | None
		custom_label: DF.Data
		custom_placeholder: DF.Data | None
		locale: DF.Data | None
		parent: DF.Data
		parentfield: DF.Data
		parenttype: DF.Data
		pim_attribute: DF.Link
	# end: auto-generated types

	pass

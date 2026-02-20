# Copyright (c) 2026, TR TradeHub and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class FamilyDefaultValue(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		channel: DF.Link | None
		default_value: DF.SmallText
		locale: DF.Data | None
		parent: DF.Data
		parentfield: DF.Data
		parenttype: DF.Data
		pim_attribute: DF.Link
		value_type: DF.Literal["Static", "Jinja Template", "Python Expression"]
	# end: auto-generated types

	pass

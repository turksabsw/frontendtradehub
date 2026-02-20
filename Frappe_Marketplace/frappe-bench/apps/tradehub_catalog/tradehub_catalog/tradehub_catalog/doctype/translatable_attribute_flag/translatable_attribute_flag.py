# Copyright (c) 2026, TR TradeHub and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class TranslatableAttributeFlag(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		is_translatable: DF.Check
		parent: DF.Data
		parentfield: DF.Data
		parenttype: DF.Data
		pim_attribute: DF.Link
		required_locales: DF.SmallText | None
		source_locale: DF.Data
	# end: auto-generated types

	pass

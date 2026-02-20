# Copyright (c) 2026, TR TradeHub and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class ChannelFieldMapping(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		channel: DF.Link
		is_required_for_channel: DF.Check
		parent: DF.Data
		parentfield: DF.Data
		parenttype: DF.Data
		pim_attribute: DF.Link
		sort_order: DF.Int
		target_field_code: DF.Data | None
		target_field_name: DF.Data
		transform_config: DF.Code | None
		transform_type: DF.Literal["None", "Map", "Concat", "Split", "Lookup", "Format", "Custom"]
	# end: auto-generated types

	pass

# Copyright (c) 2026, TR TradeHub and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class RequiredImageAngle(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		angle_code: DF.Data
		angle_name: DF.Data
		channel: DF.Link | None
		description: DF.SmallText | None
		example_image: DF.AttachImage | None
		is_required: DF.Check
		min_height: DF.Int
		min_width: DF.Int
		parent: DF.Data
		parentfield: DF.Data
		parenttype: DF.Data
		sort_order: DF.Int
	# end: auto-generated types

	pass

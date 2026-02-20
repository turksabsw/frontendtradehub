# Copyright (c) 2026, TR TradeHub and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class ProductClassAllowedStatus(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		allowed_transitions: DF.SmallText | None
		allows_deletion: DF.Check
		allows_editing: DF.Check
		auto_transition_after: DF.Int
		auto_transition_to: DF.Data | None
		color: DF.Literal["Blue", "Green", "Orange", "Red", "Yellow", "Gray", "Purple", "Pink", "Cyan"]
		is_active_status: DF.Check
		is_default: DF.Check
		parent: DF.Data
		parentfield: DF.Data
		parenttype: DF.Data
		sort_order: DF.Int
		status_code: DF.Data
		status_name: DF.Data
	# end: auto-generated types

	pass

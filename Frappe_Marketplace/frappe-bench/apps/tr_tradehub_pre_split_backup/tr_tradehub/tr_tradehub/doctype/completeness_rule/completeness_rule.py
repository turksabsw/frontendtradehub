# Copyright (c) 2026, TR TradeHub and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class CompletenessRule(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		channel: DF.Link | None
		is_enabled: DF.Check
		locale: DF.Data | None
		max_length: DF.Int
		max_media_count: DF.Int
		max_value: DF.Float
		min_length: DF.Int
		min_media_count: DF.Int
		min_value: DF.Float
		parent: DF.Data
		parentfield: DF.Data
		parenttype: DF.Data
		rule_type: DF.Literal["Required Attribute", "Required Description", "Min Description Length", "Required Media", "Min Media Count", "Required Image Angle", "Attribute Validation", "Custom"]
		target_attribute: DF.Link | None
		weight: DF.Float
	# end: auto-generated types

	pass

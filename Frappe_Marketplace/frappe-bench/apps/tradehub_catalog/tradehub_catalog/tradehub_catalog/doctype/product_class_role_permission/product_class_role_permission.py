# Copyright (c) 2026, TR TradeHub and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class ProductClassRolePermission(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		allowed_statuses: DF.SmallText | None
		can_change_status: DF.Check
		can_create: DF.Check
		can_delete: DF.Check
		can_export: DF.Check
		can_import: DF.Check
		can_read: DF.Check
		can_write: DF.Check
		parent: DF.Data
		parentfield: DF.Data
		parenttype: DF.Data
		role: DF.Link
	# end: auto-generated types

	pass

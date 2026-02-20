# Copyright (c) 2026, TR TradeHub and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class PIMProductMedia(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		alt_text: DF.Data | None
		caption: DF.SmallText | None
		channel: DF.Link | None
		file: DF.Attach
		file_size: DF.Int
		height: DF.Int
		image_angle: DF.Literal["", "Front", "Back", "Left", "Right", "Top", "Bottom", "Detail", "Packaging", "Lifestyle", "Dimensions", "Label", "Certificate", "Other"]
		is_main: DF.Check
		media_type: DF.Literal["Image", "Video", "Document", "3D Model", "Audio", "External Link"]
		mime_type: DF.Data | None
		parent: DF.Data
		parentfield: DF.Data
		parenttype: DF.Data
		sort_order: DF.Int
		title: DF.Data | None
		width: DF.Int
	# end: auto-generated types

	pass

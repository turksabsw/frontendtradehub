# Copyright (c) 2026, TR TradeHub and contributors
# For license information, please see license.txt

import re
from frappe.model.document import Document


class PIMProductDescription(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		channel: DF.Link | None
		character_count: DF.Int
		description: DF.TextEditor
		description_type: DF.Literal["Short", "Long", "Marketing", "Technical", "Bullet Points", "Meta Description", "SEO Text", "Custom"]
		locale: DF.Data | None
		parent: DF.Data
		parentfield: DF.Data
		parenttype: DF.Data
		plain_text: DF.LongText | None
		word_count: DF.Int
	# end: auto-generated types

	def before_save(self):
		"""Calculate word count and character count from description"""
		if self.description:
			# Strip HTML tags for plain text and counting
			plain = re.sub(r'<[^>]+>', '', self.description)
			plain = re.sub(r'\s+', ' ', plain).strip()

			self.plain_text = plain
			self.word_count = len(plain.split()) if plain else 0
			self.character_count = len(plain) if plain else 0
		else:
			self.plain_text = ""
			self.word_count = 0
			self.character_count = 0

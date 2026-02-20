# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class CommissionPlanRate(Document):
    """
    Commission Plan Rate - Child table for category-specific commission rates.

    Links a Category to a specific commission rate within a Commission Plan,
    allowing different commission percentages for different product categories.
    """
    pass

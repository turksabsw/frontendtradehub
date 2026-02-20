# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class ImportJobError(Document):
    """
    Import Job Error - Child table for tracking individual row errors during import.

    Used by Import Job to track detailed error information for each failed row,
    including error type, message, affected field, and original row data.
    """
    pass

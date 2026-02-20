# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

"""
RFQ Message DocType Controller

Individual messages in RFQ conversations.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime


class RFQMessage(Document):
    """
    Controller for RFQ Message DocType.

    Handles real-time notifications for messages.
    """

    def before_insert(self):
        """Set sent timestamp."""
        if not self.sent_at:
            self.sent_at = now_datetime()

    def after_insert(self):
        """Post-insert processing."""
        self._update_thread()
        self._send_realtime_notification()

    def _update_thread(self):
        """Update thread's last message time."""
        thread = frappe.get_doc("RFQ Message Thread", self.thread)
        thread.last_message_at = self.sent_at
        thread.unread_count = (thread.unread_count or 0) + 1
        thread.save(ignore_permissions=True)

    def _send_realtime_notification(self):
        """Send real-time notification via Socket.IO."""
        thread = frappe.get_doc("RFQ Message Thread", self.thread)

        # Determine recipient user
        if self.sender_type == "Buyer":
            recipient_user = frappe.db.get_value("Seller Profile", thread.seller, "user")
        else:
            recipient_user = frappe.db.get_value("Buyer Profile", thread.buyer, "user")

        if recipient_user:
            frappe.publish_realtime(
                event="rfq_message",
                message={
                    "thread": self.thread,
                    "message": {
                        "name": self.name,
                        "sender_type": self.sender_type,
                        "sender": self.sender,
                        "message": self.message,
                        "sent_at": str(self.sent_at)
                    }
                },
                user=recipient_user
            )

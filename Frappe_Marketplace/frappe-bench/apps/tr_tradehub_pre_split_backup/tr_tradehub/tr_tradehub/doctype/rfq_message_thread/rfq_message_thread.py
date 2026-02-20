# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

"""
RFQ Message Thread DocType Controller

Ticket-style messaging between buyer and seller.
"""

import frappe
from frappe import _
from frappe.model.document import Document


class RFQMessageThread(Document):
    """
    Controller for RFQ Message Thread DocType.

    Manages conversation threads between buyers and sellers.
    """

    def get_messages(self, limit=50):
        """
        Get messages in this thread.

        Args:
            limit: Maximum number of messages to return

        Returns:
            List of messages ordered by creation time
        """
        return frappe.get_all(
            "RFQ Message",
            filters={"thread": self.name},
            fields=["name", "sender_type", "sender", "message", "sent_at", "read_at"],
            order_by="sent_at asc",
            limit=limit
        )

    def get_unread_count(self, user):
        """
        Get unread message count for a user.

        Args:
            user: User to check unread count for

        Returns:
            Number of unread messages
        """
        # Determine if user is buyer or seller
        buyer_user = frappe.db.get_value("Buyer Profile", self.buyer, "user")
        seller_user = frappe.db.get_value("Seller Profile", self.seller, "user")

        if user == buyer_user:
            # Buyer sees unread messages from seller
            sender_type = "Seller"
        elif user == seller_user:
            # Seller sees unread messages from buyer
            sender_type = "Buyer"
        else:
            return 0

        return frappe.db.count(
            "RFQ Message",
            filters={
                "thread": self.name,
                "sender_type": sender_type,
                "read_at": ["is", "not set"]
            }
        )

    def mark_as_read(self, user):
        """
        Mark all messages as read for a user.

        Args:
            user: User who read the messages
        """
        buyer_user = frappe.db.get_value("Buyer Profile", self.buyer, "user")
        seller_user = frappe.db.get_value("Seller Profile", self.seller, "user")

        if user == buyer_user:
            sender_type = "Seller"
        elif user == seller_user:
            sender_type = "Buyer"
        else:
            return

        frappe.db.sql("""
            UPDATE `tabRFQ Message`
            SET read_at = %s
            WHERE thread = %s
            AND sender_type = %s
            AND read_at IS NULL
        """, (frappe.utils.now_datetime(), self.name, sender_type))

        # Update unread count
        self.unread_count = 0
        self.save(ignore_permissions=True)

    @frappe.whitelist()
    def close_thread(self):
        """Close the message thread."""
        self.status = "Closed"
        self.save()
        return {"success": True, "message": _("Thread closed")}

    @frappe.whitelist()
    def reopen_thread(self):
        """Reopen a closed thread."""
        self.status = "Open"
        self.save()
        return {"success": True, "message": _("Thread reopened")}

# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

"""
Buyer Profile DocType Controller

Manages buyer profiles for marketplace and group buy participation.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime


class BuyerProfile(Document):
    """Buyer Profile document controller."""

    def validate(self):
        """Validate buyer profile data."""
        self._validate_user()
        self._set_display_name()
        self._validate_interest_categories()
        self._validate_addresses()

    def before_insert(self):
        """Set defaults before first save."""
        if not self.joined_at:
            self.joined_at = now_datetime()
        if not self.created_by:
            self.created_by = frappe.session.user

    def on_update(self):
        """Update last active timestamp."""
        frappe.db.set_value(
            "Buyer Profile",
            self.name,
            "last_active_at",
            now_datetime(),
            update_modified=False
        )

    def _validate_user(self):
        """Validate user link."""
        if self.user:
            # Check if user already has a buyer profile
            existing = frappe.db.get_value(
                "Buyer Profile",
                {"user": self.user, "name": ["!=", self.name]},
                "name"
            )
            if existing:
                frappe.throw(
                    _("User {0} already has a buyer profile: {1}").format(
                        self.user, existing
                    )
                )

    def _set_display_name(self):
        """Set display name if not provided."""
        if not self.display_name:
            self.display_name = self.buyer_name

    def _validate_interest_categories(self):
        """Validate interest categories to prevent duplicates.

        Ensures that the same category is not selected multiple times
        in the interest_categories child table.
        """
        if not self.interest_categories:
            return

        seen_categories = set()
        for row in self.interest_categories:
            if not row.category:
                continue

            if row.category in seen_categories:
                frappe.throw(
                    _("Duplicate category '{0}' found in interest categories. Each category can only be selected once.").format(
                        row.category_name or row.category
                    )
                )
            seen_categories.add(row.category)

    def _validate_addresses(self):
        """Validate addresses in the addresses child table.

        Ensures:
        1. Only one address can be marked as is_default per address_type
        2. Required fields (street_address) are populated

        When multiple defaults are found for the same address_type, an error is thrown
        requiring the user to correct the configuration.
        """
        if not self.addresses:
            return

        # Track defaults per address_type
        defaults_by_type = {}

        for idx, row in enumerate(self.addresses, start=1):
            # Validate street_address is provided (defensive check - also enforced at DocType level)
            if not row.street_address:
                frappe.throw(
                    _("Row {0}: Street Address is required for all addresses").format(idx)
                )

            # Track is_default by address_type
            if row.is_default:
                address_type = row.address_type or "Billing"

                if address_type in defaults_by_type:
                    # Multiple defaults found for same type
                    existing_row = defaults_by_type[address_type]
                    frappe.throw(
                        _("Multiple default addresses found for type '{0}'. "
                          "Row {1} and Row {2} are both marked as default. "
                          "Only one default address is allowed per address type.").format(
                            address_type, existing_row, idx
                        )
                    )
                defaults_by_type[address_type] = idx

    def update_group_buy_stats(self):
        """Update group buy participation statistics."""
        # Count total commitments
        commitments = frappe.db.get_all(
            "Group Buy Commitment",
            filters={"buyer": self.name, "status": ["in", ["Active", "Paid", "Payment Pending"]]},
            fields=["name", "group_buy", "total_amount"]
        )

        self.total_commitments = len(commitments)
        self.total_commitment_amount = sum(c.total_amount or 0 for c in commitments)

        # Count unique group buys
        group_buys = set(c.group_buy for c in commitments)
        self.total_group_buys = len(group_buys)

        # Count successful group buys
        if group_buys:
            successful = frappe.db.count(
                "Group Buy",
                {"name": ["in", list(group_buys)], "status": ["in", ["Funded", "Completed"]]}
            )
            self.successful_group_buys = successful

        self.save(ignore_permissions=True)

    def update_order_stats(self):
        """Update order statistics."""
        orders = frappe.db.get_all(
            "Marketplace Order",
            filters={"buyer": self.name, "status": ["not in", ["Cancelled", "Draft"]]},
            fields=["name", "grand_total", "creation"]
        )

        self.total_orders = len(orders)
        self.total_spent = sum(o.grand_total or 0 for o in orders)

        if orders:
            self.average_order_value = self.total_spent / len(orders)
            self.last_order_date = max(o.creation for o in orders)

        self.save(ignore_permissions=True)

    def get_active_commitments(self):
        """Get list of active group buy commitments."""
        return frappe.db.get_all(
            "Group Buy Commitment",
            filters={"buyer": self.name, "status": ["in", ["Active", "Payment Pending"]]},
            fields=["name", "group_buy", "quantity", "unit_price", "total_amount", "status"]
        )

    def can_participate_in_group_buy(self, group_buy_name: str) -> tuple:
        """
        Check if buyer can participate in a group buy.

        Returns:
            tuple: (can_participate: bool, message: str)
        """
        if self.status != "Active":
            return False, _("Buyer account is not active")

        group_buy = frappe.get_doc("Group Buy", group_buy_name)

        if group_buy.status != "Active":
            return False, _("Group buy is not active")

        return True, _("Can participate")


@frappe.whitelist()
def get_buyer_interest_categories(buyer):
    """
    Get buyer's interest categories.

    API endpoint to retrieve interest categories for a buyer profile.
    Returns list of categories with their details.

    Args:
        buyer: The buyer profile name/ID

    Returns:
        list: List of dictionaries containing category details

    Example:
        frappe.call({
            method: "tradehub_core.tradehub_core.doctype.buyer_profile.buyer_profile.get_buyer_interest_categories",
            args: { buyer: "BUYER-00001" }
        })
    """
    if not buyer:
        frappe.throw(_("Buyer is required"))

    # Verify buyer exists
    if not frappe.db.exists("Buyer Profile", buyer):
        frappe.throw(_("Buyer Profile {0} not found").format(buyer))

    # Get interest categories from child table
    categories = frappe.get_all(
        "Buyer Interest Category",
        filters={"parent": buyer, "parenttype": "Buyer Profile"},
        fields=[
            "name",
            "category",
            "category_name",
            "interest_level",
            "is_primary",
            "source",
            "notes"
        ],
        order_by="is_primary desc, interest_level desc"
    )

    return categories


@frappe.whitelist()
def get_buyer_addresses(buyer, address_type=None):
    """
    Get buyer's addresses from the addresses child table.

    API endpoint to retrieve addresses for a buyer profile.
    Optionally filtered by address type.

    Args:
        buyer: The buyer profile name/ID
        address_type: Optional filter for address type (e.g., 'Billing', 'Shipping', 'Warehouse')

    Returns:
        list: List of dictionaries containing address details

    Example:
        // Get all addresses
        frappe.call({
            method: "tradehub_core.tradehub_core.doctype.buyer_profile.buyer_profile.get_buyer_addresses",
            args: { buyer: "BUYER-00001" }
        })

        // Get only shipping addresses
        frappe.call({
            method: "tradehub_core.tradehub_core.doctype.buyer_profile.buyer_profile.get_buyer_addresses",
            args: { buyer: "BUYER-00001", address_type: "Shipping" }
        })
    """
    if not buyer:
        frappe.throw(_("Buyer is required"))

    # Verify buyer exists
    if not frappe.db.exists("Buyer Profile", buyer):
        frappe.throw(_("Buyer Profile {0} not found").format(buyer))

    # Build filters
    filters = {"parent": buyer, "parenttype": "Buyer Profile"}
    if address_type:
        filters["address_type"] = address_type

    # Get addresses from child table
    addresses = frappe.get_all(
        "Address Item",
        filters=filters,
        fields=[
            "name",
            "address_type",
            "address_title",
            "is_default",
            "city",
            "city_name",
            "district",
            "district_name",
            "neighborhood",
            "neighborhood_name",
            "street_address",
            "building_info",
            "postal_code",
            "contact_person",
            "phone",
            "email",
            "notes"
        ],
        order_by="is_default desc, address_type asc"
    )

    return addresses

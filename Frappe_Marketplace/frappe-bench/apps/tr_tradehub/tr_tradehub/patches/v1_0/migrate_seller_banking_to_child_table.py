# Copyright (c) 2026, TR TradeHub and contributors
# For license information, please see license.txt

"""
Migration patch to convert Seller Profile individual banking fields to Child Table:
- bank_name, bank_branch, iban, account_holder_name, swift_code -> bank_accounts (Table: Seller Bank Account)
"""

import frappe


def execute():
    """Execute the migration patch."""
    # Reload DocTypes to ensure schema is up to date
    frappe.reload_doc("tr_tradehub", "doctype", "seller_bank_account")
    frappe.reload_doc("tr_tradehub", "doctype", "seller_profile")

    # Get all seller profiles with banking data in the old fields
    sellers = frappe.get_all(
        "Seller Profile",
        filters={},
        fields=["name", "bank_name", "bank_branch", "iban", "account_holder_name", "swift_code"],
        limit_page_length=0
    )

    migrated_count = 0
    error_count = 0

    for seller_data in sellers:
        try:
            # Skip if no banking data to migrate
            if not seller_data.iban and not seller_data.bank_name:
                continue

            seller = frappe.get_doc("Seller Profile", seller_data.name)

            # Skip if already has child table data
            if seller.get("bank_accounts"):
                continue

            # Create bank account entry from individual fields
            seller.append("bank_accounts", {
                "bank_name": seller_data.bank_name or "",
                "bank_branch": seller_data.bank_branch or "",
                "iban": seller_data.iban or "",
                "account_holder_name": seller_data.account_holder_name or "",
                "swift_code": seller_data.swift_code or "",
                "is_default": 1,  # Mark as default since it was the only account
                "is_verified": seller.bank_verified if hasattr(seller, 'bank_verified') else 0,
                "currency": "TRY",
                "bank_country": "Turkey"
            })

            # Use flags to skip validation during migration
            seller.flags.ignore_validate = True
            seller.flags.ignore_permissions = True
            seller.flags.ignore_links = True
            seller.save()
            migrated_count += 1

        except Exception as e:
            error_count += 1
            frappe.log_error(
                message=f"Error migrating Seller Profile {seller_data.name}: {str(e)}",
                title="Seller Banking Migration Error"
            )

    # Log summary
    frappe.logger().info(
        f"Seller Banking Migration Complete: {migrated_count} migrated, {error_count} errors"
    )

    if migrated_count > 0:
        frappe.db.commit()

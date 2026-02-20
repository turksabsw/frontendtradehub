# Copyright (c) 2026, TR TradeHub and contributors
# For license information, please see license.txt

"""
Migration Patch: Migrate Buyer Profile Legacy Address Fields to Child Table

This patch migrates legacy address fields (address_line_1, address_line_2, city, state,
country, postal_code) from Buyer Profile to the new addresses child table using
Address Item DocType.

The legacy fields are preserved but marked as deprecated and hidden.
"""

import frappe
from frappe.utils import cint


def execute():
    """Execute the migration patch."""
    frappe.reload_doc("tr_tradehub", "doctype", "buyer_profile")
    frappe.reload_doc("tr_tradehub", "doctype", "address_item")

    # Get all buyer profiles with legacy address data
    buyers = frappe.db.sql("""
        SELECT name, address_line_1, address_line_2, city, state, country, postal_code,
               contact_phone, contact_email, buyer_name
        FROM `tabBuyer Profile`
        WHERE (address_line_1 IS NOT NULL AND address_line_1 != '')
           OR (city IS NOT NULL AND city != '')
    """, as_dict=True)

    migrated_count = 0
    skipped_count = 0

    for buyer in buyers:
        try:
            buyer_doc = frappe.get_doc("Buyer Profile", buyer.name)

            # Check if addresses table is empty (not already migrated)
            if buyer_doc.addresses and len(buyer_doc.addresses) > 0:
                skipped_count += 1
                continue

            # Build address string
            street_address_parts = []
            if buyer.address_line_1:
                street_address_parts.append(buyer.address_line_1)
            if buyer.address_line_2:
                street_address_parts.append(buyer.address_line_2)

            street_address = "\n".join(street_address_parts) if street_address_parts else None

            if not street_address:
                skipped_count += 1
                continue

            # Try to find matching City record for Turkish location hierarchy
            city_link = None
            if buyer.city:
                city_link = frappe.db.get_value("City", {"city_name": buyer.city}, "name")

            # Create address item for billing (primary use case for buyer)
            buyer_doc.append("addresses", {
                "address_type": "Billing",
                "address_title": "Primary Address",
                "is_default": 1,
                "city": city_link,  # May be None if city doesn't exist in City DocType
                "street_address": street_address,
                "postal_code": buyer.postal_code,
                "contact_person": buyer.buyer_name,
                "phone": buyer.contact_phone,
                "email": buyer.contact_email,
                "notes": f"Migrated from legacy fields. Original city: {buyer.city or 'N/A'}, State: {buyer.state or 'N/A'}, Country: {buyer.country or 'N/A'}"
            })

            # Also add as shipping address (copy)
            buyer_doc.append("addresses", {
                "address_type": "Shipping",
                "address_title": "Shipping Address",
                "is_default": 1,
                "city": city_link,
                "street_address": street_address,
                "postal_code": buyer.postal_code,
                "contact_person": buyer.buyer_name,
                "phone": buyer.contact_phone,
                "email": buyer.contact_email,
                "notes": f"Migrated from legacy fields (copy of billing)"
            })

            buyer_doc.flags.ignore_validate = True
            buyer_doc.flags.ignore_mandatory = True
            buyer_doc.save(ignore_permissions=True)
            migrated_count += 1

        except Exception as e:
            frappe.log_error(
                message=f"Error migrating address for Buyer Profile {buyer.name}: {str(e)}",
                title="Buyer Address Migration Error"
            )

    frappe.db.commit()
    print(f"Buyer address migration complete: {migrated_count} migrated, {skipped_count} skipped")

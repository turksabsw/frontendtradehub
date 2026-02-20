"""ERPNext Webhook Handlers for TradeHub Seller

This module handles reverse synchronization from ERPNext back to TradeHub Seller.
When Supplier documents are created/updated in ERPNext, these handlers
sync the changes back to the corresponding Seller Profile DocType in TradeHub.

Events handled:
- Supplier: Syncs supplier data back to Seller Profile
"""

import frappe
from frappe import _


def on_supplier_update(doc, method):
    """Handle Supplier update events from ERPNext.

    Syncs Supplier changes back to the corresponding Seller Profile
    in TradeHub Seller when the Supplier is updated.

    Args:
        doc: The ERPNext Supplier document
        method: The event method name (on_update)
    """
    # Check if this Supplier is linked to a TradeHub Seller Profile
    seller_profile_id = doc.get("custom_tradehub_seller_profile_id")
    if not seller_profile_id:
        # Try to find by matching company name or tax_id
        seller_profile_id = _find_seller_profile_by_supplier(doc)
        if not seller_profile_id:
            return

    # Check if Seller Profile DocType exists
    if not frappe.db.exists("Seller Profile", seller_profile_id):
        frappe.log_error(
            f"Seller Profile {seller_profile_id} not found for Supplier {doc.name}",
            "ERPNext Sync Error"
        )
        return

    try:
        # Update the Seller Profile with changes from Supplier
        seller_profile = frappe.get_doc("Seller Profile", seller_profile_id)

        # Sync relevant fields from ERPNext Supplier
        if doc.supplier_name:
            seller_profile.company_name = doc.supplier_name

        if doc.get("tax_id"):
            seller_profile.tax_id = doc.tax_id

        # Sync primary contact if available
        if doc.get("supplier_primary_contact"):
            contact = frappe.get_doc("Contact", doc.supplier_primary_contact)
            if contact:
                if contact.email_id:
                    seller_profile.contact_email = contact.email_id
                if contact.phone:
                    seller_profile.contact_phone = contact.phone

        # Track ERPNext sync metadata
        seller_profile.erpnext_supplier = doc.name
        seller_profile.last_erpnext_sync = frappe.utils.now()

        seller_profile.flags.ignore_validate = True
        seller_profile.save()

        frappe.logger().info(
            f"Synced Supplier {doc.name} to Seller Profile {seller_profile_id}"
        )

    except Exception as e:
        frappe.log_error(
            f"Failed to sync Supplier {doc.name}: {str(e)}",
            "ERPNext Sync Error"
        )


def on_supplier_insert(doc, method):
    """Handle Supplier insert events from ERPNext.

    When a new Supplier is created in ERPNext, this optionally creates
    or links to a corresponding Seller Profile in TradeHub Seller.

    Args:
        doc: The ERPNext Supplier document
        method: The event method name (after_insert)
    """
    # Skip if already linked to a Seller Profile
    if doc.get("custom_tradehub_seller_profile_id"):
        return

    # Check if auto-creation is enabled in ERPNext Integration Settings
    settings = _get_erpnext_integration_settings()
    if not settings or not settings.get("auto_create_seller_profiles"):
        return

    try:
        # Check if a Seller Profile already exists with matching criteria
        existing = _find_seller_profile_by_supplier(doc)
        if existing:
            # Link the existing profile
            doc.db_set("custom_tradehub_seller_profile_id", existing)
            frappe.logger().info(
                f"Linked Supplier {doc.name} to existing Seller Profile {existing}"
            )
            return

        # Create a new Seller Profile
        seller_profile = frappe.new_doc("Seller Profile")
        seller_profile.seller_name = doc.supplier_name
        seller_profile.company_name = doc.supplier_name
        seller_profile.status = "Pending Verification"
        seller_profile.erpnext_supplier = doc.name

        if doc.get("tax_id"):
            seller_profile.tax_id = doc.tax_id

        seller_profile.flags.ignore_validate = True
        seller_profile.insert()

        # Link back to Supplier
        doc.db_set("custom_tradehub_seller_profile_id", seller_profile.name)

        frappe.logger().info(
            f"Created Seller Profile {seller_profile.name} for Supplier {doc.name}"
        )

    except Exception as e:
        frappe.log_error(
            f"Failed to create Seller Profile for Supplier {doc.name}: {str(e)}",
            "ERPNext Sync Error"
        )


def on_supplier_delete(doc, method):
    """Handle Supplier delete events from ERPNext.

    When a Supplier is deleted in ERPNext, this updates the linked
    Seller Profile to reflect the deletion.

    Args:
        doc: The ERPNext Supplier document
        method: The event method name (on_trash)
    """
    seller_profile_id = doc.get("custom_tradehub_seller_profile_id")
    if not seller_profile_id:
        return

    if not frappe.db.exists("Seller Profile", seller_profile_id):
        return

    try:
        # Don't delete the Seller Profile, just mark it and clear the link
        seller_profile = frappe.get_doc("Seller Profile", seller_profile_id)
        seller_profile.erpnext_supplier = None
        seller_profile.description = f"{seller_profile.description or ''}\n[ERPNext Supplier {doc.name} was deleted on {frappe.utils.now()}]".strip()
        seller_profile.flags.ignore_validate = True
        seller_profile.save()

        frappe.logger().info(
            f"Unlinked Seller Profile {seller_profile_id} from deleted Supplier {doc.name}"
        )

    except Exception as e:
        frappe.log_error(
            f"Failed to update Seller Profile {seller_profile_id} on Supplier deletion: {str(e)}",
            "ERPNext Sync Error"
        )


def _find_seller_profile_by_supplier(supplier_doc):
    """Find a Seller Profile that matches the given Supplier.

    Matching is done by:
    1. Direct link via erpnext_supplier field
    2. Company name match
    3. Tax ID match

    Args:
        supplier_doc: The ERPNext Supplier document

    Returns:
        str: The Seller Profile name if found, None otherwise
    """
    # Try direct link first
    if frappe.db.exists("Seller Profile", {"erpnext_supplier": supplier_doc.name}):
        return frappe.db.get_value("Seller Profile", {"erpnext_supplier": supplier_doc.name}, "name")

    # Try company name match
    if supplier_doc.supplier_name:
        match = frappe.db.get_value(
            "Seller Profile",
            {"company_name": supplier_doc.supplier_name},
            "name"
        )
        if match:
            return match

    # Try tax_id match if available
    if supplier_doc.get("tax_id"):
        match = frappe.db.get_value(
            "Seller Profile",
            {"tax_id": supplier_doc.tax_id},
            "name"
        )
        if match:
            return match

    return None


def _get_erpnext_integration_settings():
    """Get ERPNext Integration Settings if available.

    Returns:
        dict: Settings document or None if not found
    """
    try:
        if frappe.db.exists("DocType", "ERPNext Integration Settings"):
            return frappe.get_single("ERPNext Integration Settings")
    except Exception:
        pass
    return None

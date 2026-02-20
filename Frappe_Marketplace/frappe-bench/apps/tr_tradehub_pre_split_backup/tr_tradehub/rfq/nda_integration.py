# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

"""
NDA Integration for RFQ Module

Integrates with Contract Center for NDA management.
"""

import frappe
from frappe import _
from typing import Optional, Dict, Any


def check_nda_signed(rfq_name: str, seller: str) -> bool:
    """
    Check if seller has signed the NDA for an RFQ.

    Args:
        rfq_name: RFQ document name
        seller: Seller Profile name

    Returns:
        True if NDA is signed or not required
    """
    rfq = frappe.get_doc("RFQ", rfq_name)

    if not rfq.requires_nda:
        return True

    if not rfq.nda_template:
        return True

    # Check for signed contract instance
    signed = frappe.db.exists(
        "Contract Instance",
        {
            "party_type": "Seller Profile",
            "party": seller,
            "template": rfq.nda_template,
            "status": "Signed"
        }
    )

    return bool(signed)


def get_nda_status(rfq_name: str, seller: str) -> Dict[str, Any]:
    """
    Get detailed NDA status for a seller on an RFQ.

    Args:
        rfq_name: RFQ document name
        seller: Seller Profile name

    Returns:
        Dict with NDA status details
    """
    rfq = frappe.get_doc("RFQ", rfq_name)

    result = {
        "requires_nda": rfq.requires_nda,
        "nda_template": rfq.nda_template,
        "is_signed": False,
        "contract_instance": None,
        "status": None
    }

    if not rfq.requires_nda or not rfq.nda_template:
        result["is_signed"] = True
        return result

    # Find contract instance
    instance = frappe.get_all(
        "Contract Instance",
        filters={
            "party_type": "Seller Profile",
            "party": seller,
            "template": rfq.nda_template
        },
        fields=["name", "status"],
        order_by="creation desc",
        limit=1
    )

    if instance:
        result["contract_instance"] = instance[0].name
        result["status"] = instance[0].status
        result["is_signed"] = instance[0].status == "Signed"

    return result


def create_nda_for_rfq(rfq_name: str, seller: str) -> Optional[str]:
    """
    Create NDA contract instance for a seller participating in an RFQ.

    Args:
        rfq_name: RFQ document name
        seller: Seller Profile name

    Returns:
        Contract Instance name if created, None if not required
    """
    rfq = frappe.get_doc("RFQ", rfq_name)

    if not rfq.requires_nda:
        return None

    if not rfq.nda_template:
        frappe.throw(_("RFQ requires NDA but no template is specified"))

    # Check if already exists
    existing = frappe.get_all(
        "Contract Instance",
        filters={
            "party_type": "Seller Profile",
            "party": seller,
            "template": rfq.nda_template
        },
        limit=1
    )

    if existing:
        return existing[0].name

    # Get seller info for contract
    seller_doc = frappe.get_doc("Seller Profile", seller)

    # Create contract instance
    instance = frappe.get_doc({
        "doctype": "Contract Instance",
        "template": rfq.nda_template,
        "party_type": "Seller Profile",
        "party": seller,
        "party_name": seller_doc.get("company_name") or seller_doc.get("store_name") or seller,
        "status": "Draft"
    })
    instance.insert(ignore_permissions=True)

    # Create RFQ NDA Link
    frappe.get_doc({
        "doctype": "RFQ NDA Link",
        "rfq": rfq_name,
        "seller": seller,
        "contract_instance": instance.name,
        "created_at": frappe.utils.now_datetime()
    }).insert(ignore_permissions=True)

    return instance.name


def get_rfq_nda_links(rfq_name: str) -> list:
    """
    Get all NDA links for an RFQ.

    Args:
        rfq_name: RFQ document name

    Returns:
        List of NDA link details
    """
    links = frappe.get_all(
        "RFQ NDA Link",
        filters={"rfq": rfq_name},
        fields=["name", "seller", "contract_instance", "created_at"]
    )

    result = []
    for link in links:
        instance = frappe.get_doc("Contract Instance", link.contract_instance)
        result.append({
            "link_name": link.name,
            "seller": link.seller,
            "contract_instance": link.contract_instance,
            "status": instance.status,
            "signed_at": instance.get("signed_at"),
            "created_at": link.created_at
        })

    return result


def revoke_nda_access(rfq_name: str, seller: str):
    """
    Revoke NDA access when seller is removed from RFQ.

    Args:
        rfq_name: RFQ document name
        seller: Seller Profile name
    """
    # Find and delete the link
    links = frappe.get_all(
        "RFQ NDA Link",
        filters={"rfq": rfq_name, "seller": seller}
    )

    for link in links:
        frappe.delete_doc("RFQ NDA Link", link.name, ignore_permissions=True)

    # Note: Contract Instance is not deleted as it may have legal value

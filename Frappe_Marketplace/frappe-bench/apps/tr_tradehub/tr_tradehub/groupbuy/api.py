# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

"""
Group Buy API Endpoints

REST API for group buy operations.
"""

import frappe
from frappe import _
from frappe.utils import now_datetime, getdate
from typing import Dict, Any, List, Optional
import json


def _response(success: bool, data: Any = None, message: str = None, errors: List = None) -> Dict:
    """Standard API response format."""
    return {
        "success": success,
        "data": data,
        "message": message,
        "errors": errors or []
    }


@frappe.whitelist()
def create_group_buy(
    title: str,
    listing: str = None,
    description: str = None,
    target_quantity: float = None,
    max_price: float = None,
    best_price: float = None,
    min_quantity: float = 1,
    end_date: str = None,
    reference_share: float = 0.20,
    alpha_factor: float = 1.0,
    profitability_floor: float = None
) -> Dict:
    """
    Create a new group buy campaign.

    Args:
        title: Campaign title
        listing: Optional listing reference
        description: Description
        target_quantity: Target total quantity (T)
        max_price: Maximum price at start (P_T)
        best_price: Best price at full commitment (P_best)
        min_quantity: Minimum commitment quantity
        end_date: Campaign end date
        reference_share: Reference share for pricing (s_ref)
        alpha_factor: Pricing scale factor (alpha)
        profitability_floor: Minimum profitable price

    Returns:
        API response with created group buy
    """
    try:
        seller = _get_current_seller()
        if not seller:
            return _response(False, message=_("No seller profile found for current user"))

        # Validate pricing
        if max_price and best_price and best_price > max_price:
            return _response(False, message=_("Best price cannot be higher than max price"))

        # Create group buy
        gb = frappe.get_doc({
            "doctype": "Group Buy",
            "title": title,
            "seller": seller,
            "listing": listing,
            "description": description,
            "target_quantity": target_quantity,
            "max_price": max_price,
            "best_price": best_price,
            "min_quantity": min_quantity,
            "end_date": end_date,
            "reference_share": reference_share,
            "alpha_factor": alpha_factor,
            "profitability_floor": profitability_floor,
            "status": "Draft",
            "current_quantity": 0,
            "current_price": max_price
        })
        gb.insert()
        frappe.db.commit()

        return _response(True, data={"name": gb.name}, message=_("Group buy created"))

    except Exception as e:
        frappe.log_error(f"Error creating group buy: {str(e)}")
        return _response(False, message=str(e))


@frappe.whitelist()
def activate_group_buy(group_buy_name: str) -> Dict:
    """
    Activate a draft group buy.

    Args:
        group_buy_name: Group Buy document name

    Returns:
        API response
    """
    try:
        gb = frappe.get_doc("Group Buy", group_buy_name)
        seller = _get_current_seller()

        if gb.seller != seller:
            return _response(False, message=_("You don't have permission to activate this group buy"))

        if gb.status != "Draft":
            return _response(False, message=_("Only draft group buys can be activated"))

        # Validate required fields
        if not gb.target_quantity or not gb.max_price or not gb.best_price:
            return _response(False, message=_("Target quantity and prices are required"))

        if not gb.end_date:
            return _response(False, message=_("End date is required"))

        gb.status = "Active"
        gb.start_date = now_datetime()
        gb.save()
        frappe.db.commit()

        return _response(True, message=_("Group buy activated"))

    except Exception as e:
        frappe.log_error(f"Error activating group buy: {str(e)}")
        return _response(False, message=str(e))


@frappe.whitelist()
def join_group_buy(group_buy_name: str, quantity: float) -> Dict:
    """
    Join a group buy with a commitment.

    Args:
        group_buy_name: Group Buy document name
        quantity: Quantity to commit

    Returns:
        API response with commitment details
    """
    try:
        from tr_tradehub.groupbuy.pricing import calculate_buyer_price, calculate_all_prices

        buyer = _get_current_buyer()
        if not buyer:
            return _response(False, message=_("No buyer profile found for current user"))

        gb = frappe.get_doc("Group Buy", group_buy_name)

        # Validate status
        if gb.status != "Active":
            return _response(False, message=_("This group buy is not accepting commitments"))

        # Validate deadline
        if gb.end_date and now_datetime() > gb.end_date:
            return _response(False, message=_("Commitment deadline has passed"))

        # Validate quantity
        if quantity < (gb.min_quantity or 1):
            return _response(
                False,
                message=_("Minimum quantity is {0}").format(gb.min_quantity or 1)
            )

        # Check for existing commitment
        existing = frappe.db.exists(
            "Group Buy Commitment",
            {"group_buy": group_buy_name, "buyer": buyer, "status": "Active"}
        )
        if existing:
            return _response(
                False,
                message=_("You already have an active commitment. Use update_commitment to modify."),
                data={"existing_commitment": existing}
            )

        # Calculate price
        unit_price = calculate_buyer_price(
            quantity,
            gb.target_quantity,
            gb.max_price,
            gb.best_price,
            gb.reference_share or 0.20,
            gb.alpha_factor or 1.0
        )

        # Create commitment
        commitment = frappe.get_doc({
            "doctype": "Group Buy Commitment",
            "group_buy": group_buy_name,
            "buyer": buyer,
            "quantity": quantity,
            "unit_price": unit_price,
            "total_amount": quantity * unit_price,
            "status": "Active",
            "committed_at": now_datetime()
        })
        commitment.insert()

        # Recalculate all prices
        stats = calculate_all_prices(group_buy_name)

        frappe.db.commit()

        return _response(
            True,
            data={
                "commitment": commitment.name,
                "unit_price": unit_price,
                "total_amount": quantity * unit_price,
                "stats": stats
            },
            message=_("Successfully joined group buy")
        )

    except Exception as e:
        frappe.log_error(f"Error joining group buy: {str(e)}")
        return _response(False, message=str(e))


@frappe.whitelist()
def update_commitment(commitment_name: str, new_quantity: float) -> Dict:
    """
    Update an existing commitment quantity.

    Args:
        commitment_name: Group Buy Commitment document name
        new_quantity: New quantity

    Returns:
        API response
    """
    try:
        from tr_tradehub.groupbuy.pricing import calculate_buyer_price, calculate_all_prices

        commitment = frappe.get_doc("Group Buy Commitment", commitment_name)
        buyer = _get_current_buyer()

        if commitment.buyer != buyer:
            return _response(False, message=_("You don't have permission to modify this commitment"))

        if commitment.status != "Active":
            return _response(False, message=_("Only active commitments can be modified"))

        gb = frappe.get_doc("Group Buy", commitment.group_buy)

        # Validate quantity
        if new_quantity < (gb.min_quantity or 1):
            return _response(
                False,
                message=_("Minimum quantity is {0}").format(gb.min_quantity or 1)
            )

        # Update commitment
        commitment.quantity = new_quantity
        commitment.save()

        # Recalculate all prices
        stats = calculate_all_prices(commitment.group_buy)

        frappe.db.commit()

        # Reload to get updated price
        commitment.reload()

        return _response(
            True,
            data={
                "unit_price": commitment.unit_price,
                "total_amount": commitment.total_amount,
                "stats": stats
            },
            message=_("Commitment updated")
        )

    except Exception as e:
        frappe.log_error(f"Error updating commitment: {str(e)}")
        return _response(False, message=str(e))


@frappe.whitelist()
def cancel_commitment(commitment_name: str) -> Dict:
    """
    Cancel a commitment.

    Args:
        commitment_name: Group Buy Commitment document name

    Returns:
        API response
    """
    try:
        from tr_tradehub.groupbuy.pricing import calculate_all_prices

        commitment = frappe.get_doc("Group Buy Commitment", commitment_name)
        buyer = _get_current_buyer()

        if commitment.buyer != buyer:
            return _response(False, message=_("You don't have permission to cancel this commitment"))

        if commitment.status != "Active":
            return _response(False, message=_("Only active commitments can be cancelled"))

        gb = frappe.get_doc("Group Buy", commitment.group_buy)
        if gb.status not in ["Active"]:
            return _response(
                False,
                message=_("Cannot cancel commitment - group buy is no longer active")
            )

        # Cancel commitment
        commitment.status = "Cancelled"
        commitment.cancelled_at = now_datetime()
        commitment.save()

        # Recalculate prices
        calculate_all_prices(commitment.group_buy)

        frappe.db.commit()

        return _response(True, message=_("Commitment cancelled"))

    except Exception as e:
        frappe.log_error(f"Error cancelling commitment: {str(e)}")
        return _response(False, message=str(e))


@frappe.whitelist()
def get_group_buys(
    status: str = None,
    category: str = None,
    limit: int = 20,
    offset: int = 0
) -> Dict:
    """
    Get list of group buys.

    Args:
        status: Filter by status
        category: Filter by category
        limit: Number of results
        offset: Pagination offset

    Returns:
        API response with group buy list
    """
    try:
        filters = {}

        if status:
            filters["status"] = status
        else:
            # Default: show active group buys
            filters["status"] = ["in", ["Active", "Funded"]]

        gbs = frappe.get_all(
            "Group Buy",
            filters=filters,
            fields=[
                "name", "title", "seller", "listing", "status",
                "target_quantity", "current_quantity", "current_price",
                "max_price", "best_price", "end_date", "participant_count"
            ],
            order_by="creation desc",
            limit=limit,
            start=offset
        )

        # Calculate progress for each
        for gb in gbs:
            gb["progress_percent"] = (
                (gb["current_quantity"] / gb["target_quantity"] * 100)
                if gb["target_quantity"] else 0
            )

        total = frappe.db.count("Group Buy", filters)

        return _response(True, data={"group_buys": gbs, "total": total})

    except Exception as e:
        frappe.log_error(f"Error getting group buys: {str(e)}")
        return _response(False, message=str(e))


@frappe.whitelist()
def get_my_commitments() -> Dict:
    """
    Get current user's commitments.

    Returns:
        API response with commitment list
    """
    try:
        buyer = _get_current_buyer()
        if not buyer:
            return _response(False, message=_("No buyer profile found"))

        commitments = frappe.get_all(
            "Group Buy Commitment",
            filters={"buyer": buyer},
            fields=[
                "name", "group_buy", "quantity", "unit_price",
                "total_amount", "status", "committed_at"
            ],
            order_by="creation desc"
        )

        # Enrich with group buy details
        for c in commitments:
            gb = frappe.get_doc("Group Buy", c.group_buy)
            c["group_buy_title"] = gb.title
            c["group_buy_status"] = gb.status
            c["end_date"] = gb.end_date

        return _response(True, data={"commitments": commitments})

    except Exception as e:
        frappe.log_error(f"Error getting commitments: {str(e)}")
        return _response(False, message=str(e))


@frappe.whitelist()
def calculate_price(group_buy_name: str, quantity: float) -> Dict:
    """
    Calculate price for a given quantity (preview).

    Args:
        group_buy_name: Group Buy document name
        quantity: Quantity to calculate for

    Returns:
        API response with pricing details
    """
    try:
        from tr_tradehub.groupbuy.pricing import simulate_price

        result = simulate_price(group_buy_name, float(quantity))
        return _response(True, data=result)

    except Exception as e:
        frappe.log_error(f"Error calculating price: {str(e)}")
        return _response(False, message=str(e))


@frappe.whitelist()
def get_price_tiers(group_buy_name: str) -> Dict:
    """
    Get price tiers for a group buy.

    Args:
        group_buy_name: Group Buy document name

    Returns:
        API response with tier information
    """
    try:
        from tr_tradehub.groupbuy.pricing import get_price_tiers as _get_tiers

        tiers = _get_tiers(group_buy_name)
        return _response(True, data={"tiers": tiers})

    except Exception as e:
        frappe.log_error(f"Error getting price tiers: {str(e)}")
        return _response(False, message=str(e))


# Helper functions
def _get_current_buyer() -> Optional[str]:
    """Get current user's buyer profile."""
    return frappe.db.get_value("Buyer Profile", {"user": frappe.session.user}, "name")


def _get_current_seller() -> Optional[str]:
    """Get current user's seller profile."""
    return frappe.db.get_value("Seller Profile", {"user": frappe.session.user}, "name")

# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

"""
Group Buy Pricing - Contribution-Based Dynamic Pricing Model (Model B)

Implements dynamic pricing where buyers who commit larger quantities
get better prices, incentivizing higher participation.
"""

import frappe
from frappe import _
from typing import List, Dict, Any, Optional
from decimal import Decimal, ROUND_HALF_UP


def calculate_buyer_price(
    q_i: float,
    T: float,
    P_T: float,
    P_best: float,
    s_ref: float = 0.20,
    alpha: float = 1.0
) -> float:
    """
    Calculate buyer's unit price using contribution-based model.

    Formula: P_i = max(P_best, P_T - α * f_i * (P_T - P_best))

    Where:
        - s_i = q_i / T (buyer's share)
        - f_i = min(1, s_i / s_ref) (contribution factor, 0-1 normalized)

    Args:
        q_i: Buyer's committed quantity
        T: Target total quantity
        P_T: Target price (max price at minimum participation)
        P_best: Best price (min price at full contribution)
        s_ref: Reference share ratio (default 20%)
        alpha: Scaling factor (default 1.0)

    Returns:
        P_i: Buyer's unit price
    """
    if T <= 0:
        return P_T

    if q_i <= 0:
        return P_T

    # Buyer's share
    s_i = q_i / T

    # Contribution factor (normalized 0-1)
    f_i = min(1.0, s_i / s_ref)

    # Dynamic price calculation
    price_reduction = alpha * f_i * (P_T - P_best)
    P_i = max(P_best, P_T - price_reduction)

    # Round to 2 decimal places
    return round(P_i, 2)


def calculate_all_prices(group_buy_name: str) -> Dict[str, Any]:
    """
    Recalculate prices for all commitments in a group buy.

    This should be called whenever a new commitment is made
    or an existing commitment is modified.

    Args:
        group_buy_name: Group Buy document name

    Returns:
        Dict with updated statistics
    """
    gb = frappe.get_doc("Group Buy", group_buy_name)

    T = gb.target_quantity
    P_T = gb.max_price
    P_best = gb.best_price
    s_ref = gb.reference_share or 0.20
    alpha = gb.alpha_factor or 1.0

    # Get all active commitments
    commitments = frappe.get_all(
        "Group Buy Commitment",
        filters={"group_buy": group_buy_name, "status": "Active"},
        fields=["name", "buyer", "quantity"]
    )

    total_quantity = 0
    total_revenue = 0

    # Update each commitment's price
    for c in commitments:
        new_price = calculate_buyer_price(c.quantity, T, P_T, P_best, s_ref, alpha)
        total_amount = c.quantity * new_price

        frappe.db.set_value(
            "Group Buy Commitment",
            c.name,
            {
                "unit_price": new_price,
                "total_amount": total_amount
            },
            update_modified=False
        )

        total_quantity += c.quantity
        total_revenue += total_amount

    # Calculate current average price
    if total_quantity > 0 and len(commitments) > 0:
        avg_quantity = total_quantity / len(commitments)
        current_price = calculate_buyer_price(avg_quantity, T, P_T, P_best, s_ref, alpha)
    else:
        current_price = P_T

    # Update group buy stats
    frappe.db.set_value(
        "Group Buy",
        group_buy_name,
        {
            "current_quantity": total_quantity,
            "current_price": current_price,
            "participant_count": len(commitments)
        }
    )

    # Check if target reached
    if total_quantity >= T and gb.status == "Active":
        frappe.db.set_value("Group Buy", group_buy_name, "status", "Funded")
        _notify_target_reached(group_buy_name)

    frappe.db.commit()

    return {
        "total_quantity": total_quantity,
        "total_revenue": total_revenue,
        "current_price": current_price,
        "participant_count": len(commitments),
        "progress_percent": (total_quantity / T * 100) if T > 0 else 0
    }


def check_profitability(group_buy_name: str) -> Dict[str, Any]:
    """
    Check if the group buy meets seller's profitability threshold.

    Args:
        group_buy_name: Group Buy document name

    Returns:
        Dict with profitability analysis
    """
    gb = frappe.get_doc("Group Buy", group_buy_name)

    commitments = frappe.get_all(
        "Group Buy Commitment",
        filters={"group_buy": group_buy_name, "status": "Active"},
        fields=["unit_price", "quantity"]
    )

    total_revenue = sum(c.unit_price * c.quantity for c in commitments)
    total_quantity = sum(c.quantity for c in commitments)

    if total_quantity == 0:
        return {
            "is_profitable": True,
            "avg_price": gb.max_price,
            "min_required_price": gb.profitability_floor or 0,
            "margin": 0,
            "message": _("No commitments yet")
        }

    avg_price = total_revenue / total_quantity
    min_profitable_price = gb.profitability_floor or 0

    is_profitable = avg_price >= min_profitable_price
    margin = avg_price - min_profitable_price

    if not is_profitable:
        frappe.log_error(
            f"Group Buy {group_buy_name}: Average price ({avg_price}) "
            f"is below profitability floor ({min_profitable_price})",
            "Group Buy Profitability"
        )

    return {
        "is_profitable": is_profitable,
        "avg_price": round(avg_price, 2),
        "min_required_price": min_profitable_price,
        "margin": round(margin, 2),
        "total_revenue": round(total_revenue, 2),
        "total_quantity": total_quantity,
        "message": _("Profitable") if is_profitable else _("Below profitability threshold")
    }


def get_price_tiers(group_buy_name: str) -> List[Dict[str, Any]]:
    """
    Get price breakdown by contribution levels.

    Useful for displaying to buyers how prices change with quantity.

    Args:
        group_buy_name: Group Buy document name

    Returns:
        List of tier price information
    """
    gb = frappe.get_doc("Group Buy", group_buy_name)

    T = gb.target_quantity
    P_T = gb.max_price
    P_best = gb.best_price
    s_ref = gb.reference_share or 0.20
    alpha = gb.alpha_factor or 1.0

    # Generate sample quantities to show price progression
    tiers = []
    sample_percentages = [0.01, 0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.50]

    for pct in sample_percentages:
        quantity = T * pct
        if quantity < 1:
            quantity = 1

        price = calculate_buyer_price(quantity, T, P_T, P_best, s_ref, alpha)
        discount = ((P_T - price) / P_T * 100) if P_T > 0 else 0

        tiers.append({
            "min_quantity": round(quantity, 0),
            "share_percent": pct * 100,
            "unit_price": price,
            "discount_percent": round(discount, 1)
        })

    return tiers


def simulate_price(
    group_buy_name: str,
    additional_quantity: float
) -> Dict[str, Any]:
    """
    Simulate what price a buyer would get for a given quantity.

    Args:
        group_buy_name: Group Buy document name
        additional_quantity: Quantity buyer wants to commit

    Returns:
        Dict with simulated pricing
    """
    gb = frappe.get_doc("Group Buy", group_buy_name)

    T = gb.target_quantity
    P_T = gb.max_price
    P_best = gb.best_price
    s_ref = gb.reference_share or 0.20
    alpha = gb.alpha_factor or 1.0

    # Calculate price for this quantity
    unit_price = calculate_buyer_price(additional_quantity, T, P_T, P_best, s_ref, alpha)
    total_amount = additional_quantity * unit_price

    # Calculate savings compared to max price
    max_total = additional_quantity * P_T
    savings = max_total - total_amount
    savings_percent = (savings / max_total * 100) if max_total > 0 else 0

    return {
        "quantity": additional_quantity,
        "unit_price": unit_price,
        "total_amount": round(total_amount, 2),
        "max_price": P_T,
        "savings": round(savings, 2),
        "savings_percent": round(savings_percent, 1),
        "share_percent": round((additional_quantity / T * 100), 2) if T > 0 else 0
    }


def _notify_target_reached(group_buy_name: str):
    """
    Notify all participants that target has been reached.

    Args:
        group_buy_name: Group Buy document name
    """
    gb = frappe.get_doc("Group Buy", group_buy_name)

    commitments = frappe.get_all(
        "Group Buy Commitment",
        filters={"group_buy": group_buy_name, "status": "Active"},
        fields=["buyer"]
    )

    for c in commitments:
        buyer_user = frappe.db.get_value("Buyer Profile", c.buyer, "user")
        if buyer_user:
            frappe.get_doc({
                "doctype": "Notification Log",
                "for_user": buyer_user,
                "type": "Alert",
                "document_type": "Group Buy",
                "document_name": group_buy_name,
                "subject": _("Group Buy Target Reached!"),
                "email_content": _(
                    "Great news! The group buy '{0}' has reached its target. "
                    "Payment processing will begin soon."
                ).format(gb.title)
            }).insert(ignore_permissions=True)

    # Notify seller
    seller_user = frappe.db.get_value("Seller Profile", gb.seller, "user")
    if seller_user:
        frappe.get_doc({
            "doctype": "Notification Log",
            "for_user": seller_user,
            "type": "Alert",
            "document_type": "Group Buy",
            "document_name": group_buy_name,
            "subject": _("Your Group Buy Reached Target!"),
            "email_content": _(
                "Your group buy '{0}' has reached its target quantity. "
                "Total quantity: {1}"
            ).format(gb.title, gb.current_quantity)
        }).insert(ignore_permissions=True)

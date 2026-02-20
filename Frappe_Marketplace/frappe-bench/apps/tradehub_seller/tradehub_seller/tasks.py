# Copyright (c) 2024, TradeHub Team and contributors
# For license information, please see license.txt

"""
Seller scheduled tasks for TradeHub Marketplace.

This module contains scheduled task functions for seller-related operations:
- buybox_rotation: Hourly task to rotate Buy Box winners
- kpi_tasks: Daily task to calculate seller KPI metrics
- tier_tasks: Daily task to update seller tier levels
"""

import frappe
from frappe import _


def buybox_rotation():
    """
    Hourly task to rotate Buy Box winners.

    Buy Box is the prominent product listing position. This task:
    1. Evaluates all active listings for each product
    2. Calculates seller scores based on price, seller rating, fulfillment metrics
    3. Updates Buy Box Entry records with new winners
    4. Notifies sellers of Buy Box status changes
    """
    if not frappe.db.exists("DocType", "Buy Box Entry"):
        return

    # Get all products with multiple active listings
    products_with_listings = frappe.db.sql("""
        SELECT DISTINCT product
        FROM `tabListing`
        WHERE status = 'Active'
        GROUP BY product
        HAVING COUNT(*) > 1
    """, as_dict=True)

    for product in products_with_listings:
        try:
            rotate_buybox_for_product(product.product)
        except Exception as e:
            frappe.log_error(
                message=f"Buy Box rotation failed for product {product.product}: {str(e)}",
                title="Buy Box Rotation Error"
            )

    frappe.db.commit()


def rotate_buybox_for_product(product_name):
    """
    Rotate Buy Box winner for a specific product.

    Args:
        product_name: Name of the Product doctype
    """
    # Get all active listings for this product
    listings = frappe.get_all(
        "Listing",
        filters={"product": product_name, "status": "Active"},
        fields=["name", "seller_profile", "price", "stock_quantity"]
    )

    if not listings:
        return

    # Calculate scores for each listing
    scored_listings = []
    for listing in listings:
        score = calculate_listing_score(listing)
        scored_listings.append({"listing": listing.name, "score": score})

    # Sort by score (highest first)
    scored_listings.sort(key=lambda x: x["score"], reverse=True)

    # Get or create Buy Box Entry
    winner = scored_listings[0]
    existing_entry = frappe.db.exists("Buy Box Entry", {"product": product_name})

    if existing_entry:
        entry = frappe.get_doc("Buy Box Entry", existing_entry)
        old_winner = entry.listing
        entry.listing = winner["listing"]
        entry.score = winner["score"]
        entry.save(ignore_permissions=True)

        # Notify if winner changed
        if old_winner != winner["listing"]:
            notify_buybox_change(product_name, old_winner, winner["listing"])
    else:
        entry = frappe.get_doc({
            "doctype": "Buy Box Entry",
            "product": product_name,
            "listing": winner["listing"],
            "score": winner["score"]
        })
        entry.insert(ignore_permissions=True)


def calculate_listing_score(listing):
    """
    Calculate Buy Box score for a listing.

    Score is based on:
    - Price (lower is better)
    - Seller rating
    - Stock availability
    - Fulfillment metrics

    Args:
        listing: Listing dict with name, seller_profile, price, stock_quantity

    Returns:
        float: Composite score (0-100)
    """
    score = 50.0  # Base score

    # Price factor (max 30 points, lower price = higher score)
    if listing.price:
        # Normalize price (this is simplified; real implementation would compare to competitors)
        price_score = max(0, 30 - (float(listing.price) / 100))
        score += price_score

    # Stock factor (max 10 points)
    if listing.stock_quantity and listing.stock_quantity > 0:
        stock_score = min(10, listing.stock_quantity / 10)
        score += stock_score

    # Seller rating factor (max 10 points)
    if listing.seller_profile:
        seller_score = frappe.db.get_value("Seller Score",
            {"seller_profile": listing.seller_profile}, "composite_score") or 0
        score += min(10, float(seller_score) / 10)

    return round(score, 2)


def notify_buybox_change(product_name, old_listing, new_listing):
    """
    Notify sellers of Buy Box status change.

    Args:
        product_name: Product name
        old_listing: Previous winner listing name
        new_listing: New winner listing name
    """
    # Notification logic would go here
    # Could use Frappe's notification system or ECA rules
    pass


def kpi_tasks():
    """
    Daily task to calculate and update seller KPI metrics.

    KPIs calculated:
    - Order fulfillment rate
    - On-time delivery rate
    - Customer satisfaction score
    - Return/refund rate
    - Response time
    """
    if not frappe.db.exists("DocType", "Seller Profile"):
        return

    # Get all active seller profiles
    sellers = frappe.get_all(
        "Seller Profile",
        filters={"status": "Active"},
        fields=["name"]
    )

    for seller in sellers:
        try:
            calculate_seller_kpis(seller.name)
        except Exception as e:
            frappe.log_error(
                message=f"KPI calculation failed for seller {seller.name}: {str(e)}",
                title="Seller KPI Error"
            )

    frappe.db.commit()


def calculate_seller_kpis(seller_profile):
    """
    Calculate KPIs for a specific seller.

    Args:
        seller_profile: Seller Profile name
    """
    from datetime import datetime, timedelta

    # Calculate metrics for the last 30 days
    thirty_days_ago = datetime.now() - timedelta(days=30)

    # Get KPI template
    kpi_templates = frappe.get_all("KPI Template", filters={"is_active": 1}, fields=["name", "kpi_name", "weight"])

    for template in kpi_templates:
        # Calculate metric value based on KPI type
        value = calculate_kpi_value(seller_profile, template.kpi_name, thirty_days_ago)

        # Update or create Seller KPI record
        existing_kpi = frappe.db.exists("Seller KPI", {
            "seller_profile": seller_profile,
            "kpi_template": template.name
        })

        if existing_kpi:
            kpi = frappe.get_doc("Seller KPI", existing_kpi)
            kpi.value = value
            kpi.calculated_at = datetime.now()
            kpi.save(ignore_permissions=True)
        else:
            kpi = frappe.get_doc({
                "doctype": "Seller KPI",
                "seller_profile": seller_profile,
                "kpi_template": template.name,
                "value": value,
                "calculated_at": datetime.now()
            })
            kpi.insert(ignore_permissions=True)

    # Update seller metrics summary
    update_seller_metrics(seller_profile)


def calculate_kpi_value(seller_profile, kpi_name, since_date):
    """
    Calculate a specific KPI value for a seller.

    Args:
        seller_profile: Seller Profile name
        kpi_name: Name of the KPI to calculate
        since_date: Calculate metrics since this date

    Returns:
        float: KPI value
    """
    # This is a simplified implementation
    # Real implementation would query orders, shipments, reviews, etc.

    kpi_name_lower = kpi_name.lower()

    if "fulfillment" in kpi_name_lower:
        return 95.0  # Placeholder
    elif "delivery" in kpi_name_lower:
        return 92.0  # Placeholder
    elif "satisfaction" in kpi_name_lower:
        return 4.5  # Placeholder (out of 5)
    elif "return" in kpi_name_lower or "refund" in kpi_name_lower:
        return 2.5  # Placeholder (percentage)
    elif "response" in kpi_name_lower:
        return 2.0  # Placeholder (hours)
    else:
        return 0.0


def update_seller_metrics(seller_profile):
    """
    Update Seller Metrics summary record.

    Args:
        seller_profile: Seller Profile name
    """
    # Get all KPIs for this seller
    kpis = frappe.get_all(
        "Seller KPI",
        filters={"seller_profile": seller_profile},
        fields=["kpi_template", "value"]
    )

    if not kpis:
        return

    # Calculate weighted average score
    total_weight = 0
    weighted_sum = 0

    for kpi in kpis:
        template = frappe.get_doc("KPI Template", kpi.kpi_template)
        weight = template.weight or 1
        total_weight += weight
        weighted_sum += kpi.value * weight

    composite_score = weighted_sum / total_weight if total_weight > 0 else 0

    # Update or create Seller Metrics
    existing_metrics = frappe.db.exists("Seller Metrics", {"seller_profile": seller_profile})

    if existing_metrics:
        frappe.db.set_value("Seller Metrics", existing_metrics, "composite_score", composite_score)
    else:
        metrics = frappe.get_doc({
            "doctype": "Seller Metrics",
            "seller_profile": seller_profile,
            "composite_score": composite_score
        })
        metrics.insert(ignore_permissions=True)


def tier_tasks():
    """
    Daily task to evaluate and update seller tier levels.

    Tiers are based on:
    - Sales volume
    - KPI scores
    - Tenure
    - Compliance status
    """
    if not frappe.db.exists("DocType", "Seller Profile"):
        return

    # Get all active seller profiles
    sellers = frappe.get_all(
        "Seller Profile",
        filters={"status": "Active"},
        fields=["name", "seller_tier", "creation"]
    )

    # Get tier definitions
    tiers = frappe.get_all(
        "Seller Tier",
        filters={"is_active": 1},
        fields=["name", "min_score", "min_sales_volume", "min_tenure_days"],
        order_by="min_score desc"
    )

    for seller in sellers:
        try:
            evaluate_seller_tier(seller, tiers)
        except Exception as e:
            frappe.log_error(
                message=f"Tier evaluation failed for seller {seller.name}: {str(e)}",
                title="Seller Tier Error"
            )

    frappe.db.commit()


def evaluate_seller_tier(seller, tiers):
    """
    Evaluate and update tier for a specific seller.

    Args:
        seller: Seller dict with name, seller_tier, creation
        tiers: List of tier definitions
    """
    from datetime import datetime

    # Get seller metrics
    metrics = frappe.db.get_value(
        "Seller Metrics",
        {"seller_profile": seller.name},
        ["composite_score", "total_sales_volume"],
        as_dict=True
    )

    if not metrics:
        return

    # Calculate tenure in days
    creation_date = seller.creation
    if isinstance(creation_date, str):
        creation_date = datetime.fromisoformat(creation_date.replace('Z', '+00:00'))
    tenure_days = (datetime.now() - creation_date.replace(tzinfo=None)).days

    # Find appropriate tier
    new_tier = None
    for tier in tiers:
        if (metrics.composite_score >= (tier.min_score or 0) and
            (metrics.total_sales_volume or 0) >= (tier.min_sales_volume or 0) and
            tenure_days >= (tier.min_tenure_days or 0)):
            new_tier = tier.name
            break

    # Update tier if changed
    if new_tier and new_tier != seller.seller_tier:
        frappe.db.set_value("Seller Profile", seller.name, "seller_tier", new_tier)

        # Log tier change
        frappe.get_doc({
            "doctype": "Comment",
            "comment_type": "Info",
            "reference_doctype": "Seller Profile",
            "reference_name": seller.name,
            "content": f"Tier upgraded to {new_tier}"
        }).insert(ignore_permissions=True)

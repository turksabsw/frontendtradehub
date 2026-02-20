# Copyright (c) 2026, TR TradeHub and contributors
# For license information, please see license.txt

"""
Migration patch to convert Seller Profile badges JSON field to Child Table:
- badges (JSON) -> seller_badges (Table: Seller Badge)
"""

import json
import frappe
from frappe.utils import cint, getdate, today


def execute():
    """Execute the migration patch."""
    # Reload DocTypes to ensure schema is up to date
    frappe.reload_doc("tr_tradehub", "doctype", "seller_badge")
    frappe.reload_doc("tr_tradehub", "doctype", "seller_profile")

    # Get all seller profiles with JSON data in the badges field
    sellers = frappe.get_all(
        "Seller Profile",
        filters={},
        fields=["name", "badges"],
        limit_page_length=0
    )

    migrated_count = 0
    error_count = 0

    for seller_data in sellers:
        try:
            # Skip if no JSON data to migrate
            if not seller_data.badges:
                continue

            seller = frappe.get_doc("Seller Profile", seller_data.name)

            # Skip if already has child table data
            if seller.get("seller_badges"):
                continue

            modified = migrate_badges(seller, seller_data.badges)

            if modified:
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
                title="Seller Badge Migration Error"
            )

    # Log summary
    frappe.logger().info(
        f"Seller Badge Migration Complete: {migrated_count} migrated, {error_count} errors"
    )

    if migrated_count > 0:
        frappe.db.commit()


def migrate_badges(seller, badges_json):
    """Migrate badges JSON to Seller Badge child table."""
    try:
        badges = parse_json(badges_json)
        if not badges:
            return False

        # Handle different JSON structures
        # Structure 1: ["badge1", "badge2", ...]
        # Structure 2: [{"name": "badge1", "earned_date": "2024-01-01"}, ...]
        # Structure 3: [{"badge_name": "badge1", "badge_code": "TOP_SELLER"}, ...]

        if isinstance(badges, list):
            for badge in badges:
                if isinstance(badge, str):
                    # Structure 1: simple string array
                    seller.append("seller_badges", {
                        "badge_name": badge,
                        "badge_code": badge.upper().replace(" ", "_"),
                        "earned_date": today(),
                        "is_active": 1
                    })
                elif isinstance(badge, dict):
                    # Structure 2 or 3: object array
                    badge_name = (
                        badge.get("badge_name") or
                        badge.get("name") or
                        badge.get("title") or
                        "Unknown Badge"
                    )
                    badge_code = (
                        badge.get("badge_code") or
                        badge.get("code") or
                        badge_name.upper().replace(" ", "_")
                    )
                    earned_date = badge.get("earned_date") or badge.get("date") or today()

                    # Parse date if string
                    if isinstance(earned_date, str):
                        try:
                            earned_date = getdate(earned_date)
                        except Exception:
                            earned_date = today()

                    expires_on = badge.get("expires_on") or badge.get("expiry_date")
                    if expires_on and isinstance(expires_on, str):
                        try:
                            expires_on = getdate(expires_on)
                        except Exception:
                            expires_on = None

                    seller.append("seller_badges", {
                        "badge_name": badge_name,
                        "badge_code": badge_code,
                        "badge_icon": badge.get("icon") or badge.get("badge_icon") or "",
                        "badge_color": badge.get("color") or badge.get("badge_color") or "#4CAF50",
                        "description": badge.get("description") or badge.get("reason") or "",
                        "earned_date": earned_date,
                        "expires_on": expires_on,
                        "is_active": cint(badge.get("is_active", 1)),
                        "awarded_by": badge.get("awarded_by") or badge.get("granted_by"),
                        "criteria": badge.get("criteria") or badge.get("requirements") or ""
                    })

        return True
    except Exception as e:
        frappe.log_error(
            message=f"Error migrating badges for Seller Profile {seller.name}: {str(e)}",
            title="Badge Migration Error"
        )
        return False


def parse_json(json_str):
    """Safely parse JSON string."""
    if not json_str:
        return None

    if isinstance(json_str, (dict, list)):
        return json_str

    try:
        return json.loads(json_str)
    except (json.JSONDecodeError, TypeError):
        return None

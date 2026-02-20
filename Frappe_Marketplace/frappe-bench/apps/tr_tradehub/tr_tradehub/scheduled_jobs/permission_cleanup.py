# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

"""
Permission Cleanup Scheduled Tasks

Scheduled jobs for cleaning up orphan User Permissions and auditing permission records.
These tasks help maintain data integrity in the RBAC/ABAC permission system.
"""

import frappe
from frappe import _
from frappe.utils import now_datetime, add_days, today, getdate


def cleanup_orphan_user_permissions():
    """
    Daily job: Clean up orphan User Permissions.

    Removes User Permissions that reference:
    - Deleted Tenant records
    - Deleted Seller Profile records
    - Deleted Organization records
    - Users that no longer exist

    This ensures the permission system stays clean and doesn't accumulate
    stale references that could cause issues or confusion.
    """
    frappe.logger().info("Starting orphan User Permission cleanup...")

    deleted_count = 0
    errors = 0

    try:
        # 1. Find User Permissions referencing deleted Tenants
        orphan_tenant_permissions = frappe.db.sql("""
            SELECT up.name, up.user, up.allow, up.for_value
            FROM `tabUser Permission` up
            WHERE up.allow = 'Tenant'
            AND NOT EXISTS (
                SELECT 1 FROM `tabTenant` t WHERE t.name = up.for_value
            )
        """, as_dict=True)

        for perm in orphan_tenant_permissions:
            try:
                frappe.delete_doc("User Permission", perm.name, ignore_permissions=True, force=True)
                deleted_count += 1
                frappe.logger().debug(f"Deleted orphan Tenant permission: {perm.name}")
            except Exception as e:
                errors += 1
                frappe.log_error(
                    f"Error deleting orphan Tenant permission {perm.name}: {str(e)}",
                    "Permission Cleanup Task"
                )

        # 2. Find User Permissions referencing deleted Seller Profiles
        orphan_seller_permissions = frappe.db.sql("""
            SELECT up.name, up.user, up.allow, up.for_value
            FROM `tabUser Permission` up
            WHERE up.allow = 'Seller Profile'
            AND NOT EXISTS (
                SELECT 1 FROM `tabSeller Profile` sp WHERE sp.name = up.for_value
            )
        """, as_dict=True)

        for perm in orphan_seller_permissions:
            try:
                frappe.delete_doc("User Permission", perm.name, ignore_permissions=True, force=True)
                deleted_count += 1
                frappe.logger().debug(f"Deleted orphan Seller Profile permission: {perm.name}")
            except Exception as e:
                errors += 1
                frappe.log_error(
                    f"Error deleting orphan Seller Profile permission {perm.name}: {str(e)}",
                    "Permission Cleanup Task"
                )

        # 3. Find User Permissions referencing deleted Organizations
        orphan_org_permissions = frappe.db.sql("""
            SELECT up.name, up.user, up.allow, up.for_value
            FROM `tabUser Permission` up
            WHERE up.allow = 'Organization'
            AND NOT EXISTS (
                SELECT 1 FROM `tabOrganization` o WHERE o.name = up.for_value
            )
        """, as_dict=True)

        for perm in orphan_org_permissions:
            try:
                frappe.delete_doc("User Permission", perm.name, ignore_permissions=True, force=True)
                deleted_count += 1
                frappe.logger().debug(f"Deleted orphan Organization permission: {perm.name}")
            except Exception as e:
                errors += 1
                frappe.log_error(
                    f"Error deleting orphan Organization permission {perm.name}: {str(e)}",
                    "Permission Cleanup Task"
                )

        # 4. Find User Permissions for users that no longer exist
        orphan_user_permissions = frappe.db.sql("""
            SELECT up.name, up.user, up.allow, up.for_value
            FROM `tabUser Permission` up
            WHERE up.allow IN ('Tenant', 'Seller Profile', 'Organization')
            AND NOT EXISTS (
                SELECT 1 FROM `tabUser` u WHERE u.name = up.user AND u.enabled = 1
            )
        """, as_dict=True)

        for perm in orphan_user_permissions:
            try:
                frappe.delete_doc("User Permission", perm.name, ignore_permissions=True, force=True)
                deleted_count += 1
                frappe.logger().debug(f"Deleted permission for disabled/deleted user: {perm.name}")
            except Exception as e:
                errors += 1
                frappe.log_error(
                    f"Error deleting permission for missing user {perm.name}: {str(e)}",
                    "Permission Cleanup Task"
                )

        frappe.db.commit()

        frappe.logger().info(
            f"Permission cleanup complete. Deleted: {deleted_count}, Errors: {errors}"
        )

        # Log summary for audit trail
        if deleted_count > 0:
            frappe.get_doc({
                "doctype": "Comment",
                "comment_type": "Info",
                "reference_doctype": "User Permission",
                "reference_name": "User Permission",
                "content": _(
                    "Permission Cleanup Job: Deleted {0} orphan User Permissions. Errors: {1}"
                ).format(deleted_count, errors)
            }).insert(ignore_permissions=True)

    except Exception as e:
        frappe.log_error(
            f"Critical error in permission cleanup: {str(e)}",
            "Permission Cleanup Task"
        )


def audit_permission_records():
    """
    Weekly job: Audit permission records and log statistics.

    Generates an audit log containing:
    - Total User Permissions by allow type (Tenant, Seller Profile, Organization)
    - Permissions per user distribution
    - Potential anomalies (users with excessive permissions)
    - Permissions without proper role linkage

    This helps administrators monitor the health of the permission system.
    """
    frappe.logger().info("Starting permission audit...")

    try:
        audit_data = {
            "timestamp": now_datetime(),
            "summary": {},
            "anomalies": [],
            "recommendations": []
        }

        # 1. Count permissions by allow type
        permission_counts = frappe.db.sql("""
            SELECT
                up.allow,
                COUNT(*) as count
            FROM `tabUser Permission` up
            WHERE up.allow IN ('Tenant', 'Seller Profile', 'Organization')
            GROUP BY up.allow
        """, as_dict=True)

        audit_data["summary"]["permissions_by_type"] = {
            row["allow"]: row["count"] for row in permission_counts
        }

        # 2. Count users with permissions
        users_with_permissions = frappe.db.sql("""
            SELECT
                up.user,
                COUNT(*) as permission_count
            FROM `tabUser Permission` up
            WHERE up.allow IN ('Tenant', 'Seller Profile', 'Organization')
            GROUP BY up.user
            ORDER BY permission_count DESC
        """, as_dict=True)

        audit_data["summary"]["total_users_with_permissions"] = len(users_with_permissions)

        # 3. Check for anomalies - users with excessive permissions (more than 10)
        excessive_permission_threshold = 10
        for user_perm in users_with_permissions:
            if user_perm["permission_count"] > excessive_permission_threshold:
                audit_data["anomalies"].append({
                    "type": "excessive_permissions",
                    "user": user_perm["user"],
                    "count": user_perm["permission_count"],
                    "message": _(
                        "User {0} has {1} permissions, which exceeds threshold of {2}"
                    ).format(
                        user_perm["user"],
                        user_perm["permission_count"],
                        excessive_permission_threshold
                    )
                })

        # 4. Check for users with Tenant permission but no Seller/Buyer profile
        users_without_profile = frappe.db.sql("""
            SELECT DISTINCT up.user
            FROM `tabUser Permission` up
            WHERE up.allow = 'Tenant'
            AND up.user != 'Administrator'
            AND NOT EXISTS (
                SELECT 1 FROM `tabSeller Profile` sp WHERE sp.user = up.user
            )
            AND NOT EXISTS (
                SELECT 1 FROM `tabBuyer Profile` bp WHERE bp.user = up.user
            )
        """, as_dict=True)

        for user in users_without_profile:
            audit_data["anomalies"].append({
                "type": "permission_without_profile",
                "user": user["user"],
                "message": _(
                    "User {0} has Tenant permission but no Seller or Buyer profile"
                ).format(user["user"])
            })

        # 5. Check for multi-tenant users (should be rare)
        multi_tenant_users = frappe.db.sql("""
            SELECT
                up.user,
                COUNT(DISTINCT up.for_value) as tenant_count
            FROM `tabUser Permission` up
            WHERE up.allow = 'Tenant'
            GROUP BY up.user
            HAVING tenant_count > 1
        """, as_dict=True)

        for user in multi_tenant_users:
            audit_data["anomalies"].append({
                "type": "multi_tenant_user",
                "user": user["user"],
                "tenant_count": user["tenant_count"],
                "message": _(
                    "User {0} has access to {1} tenants - verify this is intentional"
                ).format(user["user"], user["tenant_count"])
            })

        # 6. Generate recommendations based on anomalies
        if len(users_without_profile) > 0:
            audit_data["recommendations"].append(
                _("Review {0} users with Tenant permissions but no profile").format(
                    len(users_without_profile)
                )
            )

        if len(multi_tenant_users) > 0:
            audit_data["recommendations"].append(
                _("Review {0} users with multi-tenant access").format(
                    len(multi_tenant_users)
                )
            )

        # Log the audit results
        audit_log_content = _build_audit_log_content(audit_data)

        frappe.logger().info(f"Permission audit complete:\n{audit_log_content}")

        # Create audit log entry
        frappe.get_doc({
            "doctype": "Comment",
            "comment_type": "Info",
            "reference_doctype": "User Permission",
            "reference_name": "User Permission",
            "content": audit_log_content
        }).insert(ignore_permissions=True)

        frappe.db.commit()

    except Exception as e:
        frappe.log_error(
            f"Error in permission audit: {str(e)}",
            "Permission Audit Task"
        )


def _build_audit_log_content(audit_data: dict) -> str:
    """
    Build formatted audit log content.

    Args:
        audit_data: Dictionary containing audit results

    Returns:
        Formatted string for logging
    """
    lines = [
        _("=== Permission Audit Report ==="),
        _("Timestamp: {0}").format(audit_data["timestamp"]),
        "",
        _("--- Summary ---")
    ]

    # Permission counts by type
    for perm_type, count in audit_data["summary"].get("permissions_by_type", {}).items():
        lines.append(_("{0}: {1} permissions").format(perm_type, count))

    lines.append(_("Total users with permissions: {0}").format(
        audit_data["summary"].get("total_users_with_permissions", 0)
    ))

    # Anomalies
    if audit_data["anomalies"]:
        lines.extend(["", _("--- Anomalies ({0}) ---").format(len(audit_data["anomalies"]))])
        for anomaly in audit_data["anomalies"][:10]:  # Limit to first 10
            lines.append(f"  - {anomaly['message']}")
        if len(audit_data["anomalies"]) > 10:
            lines.append(_("  ... and {0} more").format(len(audit_data["anomalies"]) - 10))

    # Recommendations
    if audit_data["recommendations"]:
        lines.extend(["", _("--- Recommendations ---")])
        for rec in audit_data["recommendations"]:
            lines.append(f"  - {rec}")

    lines.append("")
    lines.append(_("=== End of Audit Report ==="))

    return "\n".join(lines)


def cleanup_duplicate_permissions():
    """
    Daily job: Remove duplicate User Permissions.

    Identifies and removes duplicate User Permission entries where
    the same user has multiple permissions for the same allow/for_value combination.
    Keeps only the oldest entry.
    """
    frappe.logger().info("Starting duplicate permission cleanup...")

    deleted_count = 0

    try:
        # Find duplicates
        duplicates = frappe.db.sql("""
            SELECT
                up.user,
                up.allow,
                up.for_value,
                COUNT(*) as count,
                MIN(up.creation) as oldest_creation
            FROM `tabUser Permission` up
            WHERE up.allow IN ('Tenant', 'Seller Profile', 'Organization')
            GROUP BY up.user, up.allow, up.for_value
            HAVING count > 1
        """, as_dict=True)

        for dup in duplicates:
            # Get all duplicates except the oldest
            to_delete = frappe.db.sql("""
                SELECT name
                FROM `tabUser Permission`
                WHERE user = %s
                AND allow = %s
                AND for_value = %s
                AND creation > %s
            """, (dup["user"], dup["allow"], dup["for_value"], dup["oldest_creation"]), as_dict=True)

            for perm in to_delete:
                try:
                    frappe.delete_doc("User Permission", perm.name, ignore_permissions=True, force=True)
                    deleted_count += 1
                except Exception as e:
                    frappe.log_error(
                        f"Error deleting duplicate permission {perm.name}: {str(e)}",
                        "Permission Cleanup Task"
                    )

        frappe.db.commit()

        if deleted_count > 0:
            frappe.logger().info(f"Deleted {deleted_count} duplicate permissions")

    except Exception as e:
        frappe.log_error(
            f"Error in duplicate permission cleanup: {str(e)}",
            "Permission Cleanup Task"
        )

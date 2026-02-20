# Copyright (c) 2026, Trade Hub and contributors
# For license information, please see license.txt

"""
Trade Hub Permission Functions for Multi-Tenant Data Isolation.

This module provides permission functions that integrate with Frappe's
permission system to enforce tenant isolation across all DocTypes.

These functions are referenced in hooks.py:
- permission_query_conditions: Adds WHERE clause to filter by tenant
- has_permission: Checks document-level permission based on tenant

The actual tenant logic is delegated to trade_hub.utils.tenant to maintain
a single source of truth for tenant management.
"""

from typing import Optional

import frappe
from frappe import _


def get_tenant_permission_query_conditions(user: str = None) -> str:
    """
    Get SQL WHERE conditions for tenant-based filtering.

    This function is used by Frappe's permission_query_conditions hook to
    automatically filter list views and queries by the user's tenant.

    Args:
        user: The user to check permissions for (defaults to current user)

    Returns:
        str: SQL condition string. Returns empty string for admins (no filter),
             '1=0' for users without tenant (no access), or tenant filter
             for normal users.

    Example in hooks.py:
        permission_query_conditions = {
            "SKU Product": "tr_tradehub.permissions.get_tenant_permission_query_conditions"
        }

    How it works:
    1. Administrators and System Managers see all data (empty condition)
    2. Users without a tenant see no data (1=0 condition)
    3. Normal users see only data matching their tenant

    IMPORTANT: This function expects the DocType table to have a 'tenant' field.
    For DocTypes without tenant field, the function returns empty string (no filter).
    """
    from tr_tradehub.utils.tenant import get_user_tenant, is_platform_admin

    if not user:
        user = frappe.session.user

    # Platform admins (Administrator, System Manager, Trade Hub Admin)
    # can see all data across tenants
    if is_platform_admin():
        return ""

    # Get the user's tenant
    tenant = get_user_tenant(user)

    if not tenant:
        # Users without a tenant cannot see any tenant-isolated data
        # This prevents data leakage for users not properly assigned to a tenant
        return "1=0"

    # Return condition to filter by tenant
    # The table alias is added by Frappe based on the DocType
    # We use backticks for MySQL/MariaDB compatibility
    return f"`tenant` = {frappe.db.escape(tenant)}"


def has_tenant_permission(
    doc: "frappe.model.document.Document",
    ptype: str = None,
    user: str = None
) -> bool:
    """
    Check if a user has permission to access a specific document based on tenant.

    This function is used by Frappe's has_permission hook for document-level
    permission checks. It supplements role-based permissions with tenant isolation.

    Args:
        doc: The document to check permission for
        ptype: Permission type ('read', 'write', 'create', 'delete', 'submit', etc.)
               Note: ptype is provided by Frappe but not used here since tenant
               isolation applies to all permission types equally.
        user: The user to check (defaults to current user)

    Returns:
        bool: True if the user has permission to access the document,
              False otherwise.

    Example in hooks.py:
        has_permission = {
            "SKU Product": "tr_tradehub.permissions.has_tenant_permission"
        }

    How it works:
    1. Administrators and System Managers have permission to all documents
    2. Documents without a tenant field are accessible (no tenant isolation)
    3. Documents with a tenant field are only accessible if user's tenant matches
    """
    from tr_tradehub.utils.tenant import get_user_tenant, is_platform_admin

    if not user:
        user = frappe.session.user

    # Platform admins can access all documents
    if is_platform_admin():
        return True

    # If document doesn't have a tenant field, allow access
    # (tenant isolation doesn't apply to this DocType)
    if not hasattr(doc, "tenant") or not doc.get("tenant"):
        return True

    # Get user's tenant
    user_tenant = get_user_tenant(user)

    # If user has no tenant, they can't access tenant-isolated documents
    if not user_tenant:
        return False

    # Check if user's tenant matches document's tenant
    return user_tenant == doc.tenant


def get_tenant_from_doc(doc: "frappe.model.document.Document") -> Optional[str]:
    """
    Extract tenant value from a document.

    This is a utility function that can be used by other permission functions
    to get the tenant value from different sources.

    Args:
        doc: The document to extract tenant from

    Returns:
        str or None: The tenant name if found, None otherwise.

    The function checks:
    1. Direct tenant field on the document
    2. Tenant field on linked parent document (for child tables)
    """
    # Direct tenant field
    if hasattr(doc, "tenant") and doc.get("tenant"):
        return doc.tenant

    # For child table documents, try to get tenant from parent
    if hasattr(doc, "parenttype") and doc.parenttype:
        parent_meta = frappe.get_meta(doc.parenttype)
        if parent_meta.has_field("tenant"):
            parent_doc = frappe.get_cached_doc(doc.parenttype, doc.parent)
            return parent_doc.get("tenant")

    return None


def validate_tenant_access(
    tenant: str,
    user: str = None,
    ptype: str = "read"
) -> None:
    """
    Validate that a user has access to a specific tenant.

    This function raises a PermissionError if the user doesn't have access.
    Use this for explicit permission checks in API endpoints or business logic.

    Args:
        tenant: The tenant to check access for
        user: The user to check (defaults to current user)
        ptype: Permission type for the error message

    Raises:
        frappe.PermissionError: If user doesn't have access to the tenant

    Example:
        @frappe.whitelist()
        def get_tenant_products(tenant):
            validate_tenant_access(tenant)
            return frappe.get_all("SKU Product", filters={"tenant": tenant})
    """
    from tr_tradehub.utils.tenant import check_tenant_permission

    if not user:
        user = frappe.session.user

    if not check_tenant_permission(tenant, user, ptype):
        frappe.throw(
            _("You do not have {0} access to tenant {1}").format(ptype, tenant),
            frappe.PermissionError
        )


def get_permitted_tenants(user: str = None) -> list:
    """
    Get list of tenants a user has access to.

    Most users have access to only one tenant, but platform admins
    have access to all tenants.

    Args:
        user: The user to check (defaults to current user)

    Returns:
        list: List of tenant names the user can access.
              Empty list if user has no tenant access.
              All active tenants if user is a platform admin.

    Example:
        tenants = get_permitted_tenants()
        if len(tenants) > 1:
            # User can switch between tenants
            show_tenant_selector()
    """
    from tr_tradehub.utils.tenant import get_user_tenant, is_platform_admin

    if not user:
        user = frappe.session.user

    # Platform admins can access all tenants
    if is_platform_admin():
        return frappe.get_all(
            "Tenant",
            filters={"status": ["in", ["Active", "Trial"]]},
            pluck="name"
        )

    # Normal users can only access their assigned tenant
    user_tenant = get_user_tenant(user)
    if user_tenant:
        return [user_tenant]

    return []


def add_tenant_restriction(
    doctype: str,
    filters: dict = None,
    user: str = None
) -> dict:
    """
    Add tenant restriction to a filters dictionary.

    This is a utility function for use in API endpoints and business logic
    when building queries that need tenant isolation.

    Args:
        doctype: The DocType being queried
        filters: Existing filters dictionary (will be copied and modified)
        user: The user context for tenant lookup

    Returns:
        dict: New filters dictionary with tenant restriction added

    Raises:
        frappe.PermissionError: If user has no tenant access

    Example:
        @frappe.whitelist()
        def get_products(category=None):
            filters = {"status": "Active"}
            if category:
                filters["category"] = category
            filters = add_tenant_restriction("SKU Product", filters)
            return frappe.get_all("SKU Product", filters=filters)
    """
    from tr_tradehub.utils.tenant import get_user_tenant, is_platform_admin

    if not user:
        user = frappe.session.user

    # Start with a copy of the filters
    filters = dict(filters) if filters else {}

    # Platform admins don't need tenant restriction
    if is_platform_admin():
        return filters

    # Check if DocType has tenant field
    meta = frappe.get_meta(doctype)
    if not meta.has_field("tenant"):
        return filters

    # Get user's tenant
    tenant = get_user_tenant(user)
    if not tenant:
        frappe.throw(
            _("You must be assigned to a tenant to access {0}").format(doctype),
            frappe.PermissionError
        )

    filters["tenant"] = tenant
    return filters


# =============================================================================
# ROLE-BASED PERMISSION HELPERS
# =============================================================================


def is_tenant_admin(user: str = None) -> bool:
    """
    Check if a user is an admin for their tenant.

    Tenant admins can manage users and settings within their tenant.

    Args:
        user: The user to check (defaults to current user)

    Returns:
        bool: True if user is a tenant admin, False otherwise.
    """
    if not user:
        user = frappe.session.user

    return "Tenant Admin" in frappe.get_roles(user)


def is_seller(user: str = None) -> bool:
    """
    Check if a user has the Seller role.

    Args:
        user: The user to check (defaults to current user)

    Returns:
        bool: True if user is a seller, False otherwise.
    """
    if not user:
        user = frappe.session.user

    return "Seller" in frappe.get_roles(user)


def is_buyer(user: str = None) -> bool:
    """
    Check if a user has the Buyer role.

    Args:
        user: The user to check (defaults to current user)

    Returns:
        bool: True if user is a buyer, False otherwise.
    """
    if not user:
        user = frappe.session.user

    return "Buyer" in frappe.get_roles(user)


def is_seller_manager(user: str = None) -> bool:
    """
    Check if a user has the Seller Manager role.

    Seller Managers can manage products and orders for their seller account.

    Args:
        user: The user to check (defaults to current user)

    Returns:
        bool: True if user is a seller manager, False otherwise.
    """
    if not user:
        user = frappe.session.user

    return "Seller Manager" in frappe.get_roles(user)

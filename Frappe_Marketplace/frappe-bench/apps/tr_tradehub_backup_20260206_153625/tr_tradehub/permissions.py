# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

"""
Permission Query Conditions Module for Multi-Tenant Data Isolation

This module provides permission query condition functions that are used by Frappe's
permission system to filter data based on tenant associations. These functions are
registered in hooks.py under `permission_query_conditions` and are called automatically
when querying tenant-scoped DocTypes.

The module implements:
- Tenant-based data isolation for Seller Profile, Organization, and other DocTypes
- System Manager bypass for administrative access
- User Permission integration for tenant assignments
- Proper SQL escaping to prevent injection attacks

Usage in hooks.py:
    permission_query_conditions = {
        "Seller Profile": "tr_tradehub.permissions.get_seller_permission_query",
        "Organization": "tr_tradehub.permissions.get_organization_permission_query",
        "Listing": "tr_tradehub.permissions.get_listing_permission_query",
    }

How it works:
1. When a user queries a DocType, Frappe calls the registered function
2. The function returns a SQL WHERE clause fragment
3. Frappe appends this condition to filter results
4. Users only see records matching their tenant assignment
"""

from typing import Optional

import frappe
from frappe import _


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================


def get_user_tenant(user: Optional[str] = None) -> Optional[str]:
    """
    Get the tenant assigned to a user via User Permission.

    This function checks User Permission records to find which tenant
    the user has been assigned to. Users can only see data from their
    assigned tenant.

    Args:
        user: The user to check (default: current session user)

    Returns:
        str: Tenant ID/name if found, None otherwise

    Example:
        tenant = get_user_tenant("seller@example.com")
        if tenant:
            # User has a tenant assignment
            pass
    """
    if user is None:
        user = frappe.session.user

    if not user or user == "Guest":
        return None

    # Get tenant from User Permission
    tenant = frappe.db.get_value(
        "User Permission",
        {"user": user, "allow": "Tenant"},
        "for_value"
    )

    if tenant:
        return tenant

    # Fallback: Check seller profile for tenant
    seller_tenant = frappe.db.get_value(
        "Seller Profile",
        {"user": user},
        "tenant"
    )

    return seller_tenant


def is_system_manager(user: Optional[str] = None) -> bool:
    """
    Check if the user has System Manager role.

    System Managers bypass all tenant restrictions and can see all data.

    Args:
        user: The user to check (default: current session user)

    Returns:
        bool: True if user has System Manager role
    """
    if user is None:
        user = frappe.session.user

    if not user or user == "Guest":
        return False

    return "System Manager" in frappe.get_roles(user)


def build_tenant_condition(
    doctype: str,
    tenant: str,
    field_name: str = "tenant"
) -> str:
    """
    Build a SQL WHERE condition for tenant filtering.

    This function creates a properly escaped SQL condition string
    to filter records by tenant.

    Args:
        doctype: The DocType being queried
        tenant: The tenant ID to filter by
        field_name: The name of the tenant field (default: "tenant")

    Returns:
        str: SQL condition string like "(`tabDocType`.`tenant` = 'TEN-00001')"
    """
    escaped_tenant = frappe.db.escape(tenant)
    return f"(`tab{doctype}`.`{field_name}` = {escaped_tenant})"


# =============================================================================
# PERMISSION QUERY CONDITIONS FOR SELLER PROFILE
# =============================================================================


def get_seller_permission_query(user: Optional[str] = None) -> str:
    """
    Permission query condition for Seller Profile DocType.

    This function filters Seller Profile records based on the user's
    tenant assignment. It is registered in hooks.py and called
    automatically when querying Seller Profile.

    Args:
        user: The user making the query

    Returns:
        str: SQL WHERE clause fragment for filtering

    Behavior:
        - System Manager: Returns "" (no filter, sees all records)
        - User with tenant: Returns condition filtering by tenant
        - User without tenant: Returns "1=0" (no results)

    Example:
        # In hooks.py:
        permission_query_conditions = {
            "Seller Profile": "tr_tradehub.permissions.get_seller_permission_query"
        }

        # When user queries Seller Profile:
        # Frappe calls get_seller_permission_query(user)
        # Returns: "(`tabSeller Profile`.`tenant` = 'TEN-00001')"
        # This is appended to the WHERE clause
    """
    if user is None:
        user = frappe.session.user

    # System Manager bypasses all restrictions
    if is_system_manager(user):
        return ""

    # Get user's tenant
    tenant = get_user_tenant(user)

    if tenant:
        return build_tenant_condition("Seller Profile", tenant)

    # No tenant assigned - no access to any records
    return "1=0"


# =============================================================================
# PERMISSION QUERY CONDITIONS FOR ORGANIZATION
# =============================================================================


def get_organization_permission_query(user: Optional[str] = None) -> str:
    """
    Permission query condition for Organization DocType.

    This function filters Organization records based on the user's
    tenant assignment. Organizations belong to tenants, and users
    should only see organizations within their tenant.

    Args:
        user: The user making the query

    Returns:
        str: SQL WHERE clause fragment for filtering

    Behavior:
        - System Manager: Returns "" (no filter, sees all records)
        - User with tenant: Returns condition filtering by tenant
        - User without tenant: Returns "1=0" (no results)
    """
    if user is None:
        user = frappe.session.user

    # System Manager bypasses all restrictions
    if is_system_manager(user):
        return ""

    # Get user's tenant
    tenant = get_user_tenant(user)

    if tenant:
        return build_tenant_condition("Organization", tenant)

    # No tenant assigned - no access to any records
    return "1=0"


# =============================================================================
# PERMISSION QUERY CONDITIONS FOR LISTING
# =============================================================================


def get_listing_permission_query(user: Optional[str] = None) -> str:
    """
    Permission query condition for Listing DocType.

    This function filters Listing records based on the user's
    tenant assignment. Listings belong to sellers within tenants.

    Args:
        user: The user making the query

    Returns:
        str: SQL WHERE clause fragment for filtering

    Behavior:
        - System Manager: Returns "" (no filter, sees all records)
        - User with tenant: Returns condition filtering by tenant
        - User without tenant: Returns "1=0" (no results)
    """
    if user is None:
        user = frappe.session.user

    # System Manager bypasses all restrictions
    if is_system_manager(user):
        return ""

    # Get user's tenant
    tenant = get_user_tenant(user)

    if tenant:
        return build_tenant_condition("Listing", tenant)

    # No tenant assigned - no access to any records
    return "1=0"


# =============================================================================
# PERMISSION QUERY CONDITIONS FOR ORDER-RELATED DOCTYPES
# =============================================================================


def get_marketplace_order_permission_query(user: Optional[str] = None) -> str:
    """
    Permission query condition for Marketplace Order DocType.

    Marketplace Orders have both buyer and seller associations. This filter ensures
    users only see orders related to their tenant.

    Args:
        user: The user making the query

    Returns:
        str: SQL WHERE clause fragment for filtering
    """
    if user is None:
        user = frappe.session.user

    # System Manager bypasses all restrictions
    if is_system_manager(user):
        return ""

    # Get user's tenant
    tenant = get_user_tenant(user)

    if tenant:
        return build_tenant_condition("Marketplace Order", tenant)

    # No tenant assigned - no access to any records
    return "1=0"


def get_sub_order_permission_query(user: Optional[str] = None) -> str:
    """
    Permission query condition for Sub Order DocType.

    Sub Orders are created per seller from parent Orders. This filter
    ensures sellers only see their own sub orders.

    Args:
        user: The user making the query

    Returns:
        str: SQL WHERE clause fragment for filtering
    """
    if user is None:
        user = frappe.session.user

    # System Manager bypasses all restrictions
    if is_system_manager(user):
        return ""

    # Get user's tenant
    tenant = get_user_tenant(user)

    if tenant:
        return build_tenant_condition("Sub Order", tenant)

    # No tenant assigned - no access to any records
    return "1=0"


def get_marketplace_order_permission_query(user: Optional[str] = None) -> str:
    """
    Permission query condition for Marketplace Order DocType.

    Marketplace Orders represent the overall order placed by a buyer that may
    span multiple sellers. This filter ensures users only see orders
    related to their tenant (either as buyer or through seller relationships).

    Args:
        user: The user making the query

    Returns:
        str: SQL WHERE clause fragment for filtering

    Behavior:
        - System Manager: Returns "" (no filter, sees all records)
        - User with tenant: Returns condition filtering by tenant
        - User without tenant: Returns "1=0" (no results)
    """
    if user is None:
        user = frappe.session.user

    # System Manager bypasses all restrictions
    if is_system_manager(user):
        return ""

    # Get user's tenant
    tenant = get_user_tenant(user)

    if tenant:
        return build_tenant_condition("Marketplace Order", tenant)

    # No tenant assigned - no access to any records
    return "1=0"


# =============================================================================
# PERMISSION QUERY CONDITIONS FOR CART
# =============================================================================


def get_cart_permission_query(user: Optional[str] = None) -> str:
    """
    Permission query condition for Cart DocType.

    Carts contain shopping cart data for buyers. This filter ensures
    users only see carts belonging to their tenant. Buyers should only
    see their own cart, while sellers may need to see carts for
    analytics within their tenant.

    Args:
        user: The user making the query

    Returns:
        str: SQL WHERE clause fragment for filtering

    Behavior:
        - System Manager: Returns "" (no filter, sees all records)
        - User with tenant: Returns condition filtering by tenant
        - User without tenant: Returns "1=0" (no results)
    """
    if user is None:
        user = frappe.session.user

    # System Manager bypasses all restrictions
    if is_system_manager(user):
        return ""

    # Get user's tenant
    tenant = get_user_tenant(user)

    if tenant:
        return build_tenant_condition("Cart", tenant)

    # No tenant assigned - no access to any records
    return "1=0"


# =============================================================================
# PERMISSION QUERY CONDITIONS FOR RFQ (REQUEST FOR QUOTE)
# =============================================================================


def get_rfq_permission_query(user: Optional[str] = None) -> str:
    """
    Permission query condition for RFQ (Request for Quote) DocType.

    RFQs are B2B requests where buyers request quotes from sellers.
    This filter ensures users only see RFQs related to their tenant.
    Buyers see RFQs they created, sellers see RFQs targeting them.

    Args:
        user: The user making the query

    Returns:
        str: SQL WHERE clause fragment for filtering

    Behavior:
        - System Manager: Returns "" (no filter, sees all records)
        - User with tenant: Returns condition filtering by tenant
        - User without tenant: Returns "1=0" (no results)

    Note:
        For more granular access control (e.g., sellers only seeing
        RFQs where they are targeted), additional has_permission
        hooks may be needed.
    """
    if user is None:
        user = frappe.session.user

    # System Manager bypasses all restrictions
    if is_system_manager(user):
        return ""

    # Get user's tenant
    tenant = get_user_tenant(user)

    if tenant:
        return build_tenant_condition("RFQ", tenant)

    # No tenant assigned - no access to any records
    return "1=0"


# =============================================================================
# GENERIC TENANT PERMISSION QUERY
# =============================================================================


def get_tenant_permission_query(doctype: str, user: Optional[str] = None) -> str:
    """
    Generic permission query condition for any tenant-scoped DocType.

    This is a factory function that can be used to create permission
    query conditions for any DocType that has a 'tenant' field.

    Args:
        doctype: The DocType being queried
        user: The user making the query

    Returns:
        str: SQL WHERE clause fragment for filtering

    Example:
        # For a custom DocType "My Doctype" with tenant field:
        def get_my_doctype_permission_query(user):
            return get_tenant_permission_query("My Doctype", user)
    """
    if user is None:
        user = frappe.session.user

    # System Manager bypasses all restrictions
    if is_system_manager(user):
        return ""

    # Get user's tenant
    tenant = get_user_tenant(user)

    if tenant:
        return build_tenant_condition(doctype, tenant)

    # No tenant assigned - no access to any records
    return "1=0"


# =============================================================================
# HAS_PERMISSION FUNCTIONS
# =============================================================================


def has_seller_permission(doc, ptype=None, user=None) -> bool:
    """
    Check if user has permission to access a specific Seller Profile document.

    This is used for document-level permission checks (has_permission hook).
    It verifies that the user belongs to the same tenant as the document.

    Args:
        doc: The Seller Profile document or document name
        ptype: Permission type (read, write, etc.) - not used in tenant check
        user: The user to check (default: current session user)

    Returns:
        bool: True if user has permission, False otherwise
    """
    if user is None:
        user = frappe.session.user

    # System Manager has access to all
    if is_system_manager(user):
        return True

    # Get user's tenant
    user_tenant = get_user_tenant(user)
    if not user_tenant:
        return False

    # Get document's tenant
    if isinstance(doc, str):
        doc_tenant = frappe.db.get_value("Seller Profile", doc, "tenant")
    else:
        doc_tenant = doc.get("tenant") if hasattr(doc, "get") else getattr(doc, "tenant", None)

    return user_tenant == doc_tenant


def has_organization_permission(doc, ptype=None, user=None) -> bool:
    """
    Check if user has permission to access a specific Organization document.

    Args:
        doc: The Organization document or document name
        ptype: Permission type (read, write, etc.) - not used in tenant check
        user: The user to check (default: current session user)

    Returns:
        bool: True if user has permission, False otherwise
    """
    if user is None:
        user = frappe.session.user

    # System Manager has access to all
    if is_system_manager(user):
        return True

    # Get user's tenant
    user_tenant = get_user_tenant(user)
    if not user_tenant:
        return False

    # Get document's tenant
    if isinstance(doc, str):
        doc_tenant = frappe.db.get_value("Organization", doc, "tenant")
    else:
        doc_tenant = doc.get("tenant") if hasattr(doc, "get") else getattr(doc, "tenant", None)

    return user_tenant == doc_tenant


def has_marketplace_order_permission(doc, ptype=None, user=None) -> bool:
    """
    Check if user has permission to access a specific Marketplace Order document.

    Marketplace Orders represent the overall order placed by a buyer that may
    span multiple sellers. Access is granted if:
    - User is System Manager (full access)
    - User is the buyer of the order
    - User is a seller with sub-orders in this marketplace order
    - User's tenant matches the order's tenant (for admin roles)

    Args:
        doc: The Marketplace Order document or document name
        ptype: Permission type (read, write, etc.)
        user: The user to check (default: current session user)

    Returns:
        bool: True if user has permission, False otherwise
    """
    if user is None:
        user = frappe.session.user

    # System Manager has access to all
    if is_system_manager(user):
        return True

    # Get document data
    if isinstance(doc, str):
        doc_data = frappe.db.get_value(
            "Marketplace Order",
            doc,
            ["buyer", "tenant"],
            as_dict=True
        )
        if not doc_data:
            return False
        doc_buyer = doc_data.get("buyer")
        doc_tenant = doc_data.get("tenant")
        doc_name = doc
    else:
        doc_buyer = doc.get("buyer") if hasattr(doc, "get") else getattr(doc, "buyer", None)
        doc_tenant = doc.get("tenant") if hasattr(doc, "get") else getattr(doc, "tenant", None)
        doc_name = doc.get("name") if hasattr(doc, "get") else getattr(doc, "name", None)

    # Check 1: User is the buyer of this order
    if user == doc_buyer:
        return True

    # Check 2: User is a seller with sub-orders in this marketplace order
    # Get the user's Seller Profile
    seller_profile = frappe.db.get_value(
        "Seller Profile",
        {"user": user},
        "name"
    )

    if seller_profile and doc_name:
        # Check if there are any sub-orders for this seller in this marketplace order
        has_sub_orders = frappe.db.exists(
            "Sub Order",
            {
                "marketplace_order": doc_name,
                "seller": seller_profile
            }
        )
        if has_sub_orders:
            return True

    # Check 3: Tenant-based access for admin roles (Alici Admin, Satici Admin, etc.)
    user_tenant = get_user_tenant(user)
    if user_tenant and doc_tenant and user_tenant == doc_tenant:
        # User belongs to the same tenant - grant access for tenant admins
        user_roles = frappe.get_roles(user)
        admin_roles = ["Marka Sahibi", "Alici Admin", "Satici Admin"]
        if any(role in user_roles for role in admin_roles):
            return True

    return False


def has_sub_order_permission(doc, ptype=None, user=None) -> bool:
    """
    Check if user has permission to access a specific Sub Order document.

    Sub Orders are created per seller from parent Marketplace Orders. Access
    is granted if:
    - User is System Manager (full access)
    - User is the seller responsible for this sub-order
    - User is the buyer of this sub-order
    - User's tenant matches the sub-order's tenant (for admin roles)

    Args:
        doc: The Sub Order document or document name
        ptype: Permission type (read, write, etc.)
        user: The user to check (default: current session user)

    Returns:
        bool: True if user has permission, False otherwise
    """
    if user is None:
        user = frappe.session.user

    # System Manager has access to all
    if is_system_manager(user):
        return True

    # Get document data
    if isinstance(doc, str):
        doc_data = frappe.db.get_value(
            "Sub Order",
            doc,
            ["seller", "buyer", "tenant"],
            as_dict=True
        )
        if not doc_data:
            return False
        doc_seller = doc_data.get("seller")
        doc_buyer = doc_data.get("buyer")
        doc_tenant = doc_data.get("tenant")
    else:
        doc_seller = doc.get("seller") if hasattr(doc, "get") else getattr(doc, "seller", None)
        doc_buyer = doc.get("buyer") if hasattr(doc, "get") else getattr(doc, "buyer", None)
        doc_tenant = doc.get("tenant") if hasattr(doc, "get") else getattr(doc, "tenant", None)

    # Check 1: User is the buyer of this sub-order
    if user == doc_buyer:
        return True

    # Check 2: User is the seller responsible for this sub-order
    # Get the user's Seller Profile
    seller_profile = frappe.db.get_value(
        "Seller Profile",
        {"user": user},
        "name"
    )

    if seller_profile and doc_seller and seller_profile == doc_seller:
        return True

    # Check 3: Tenant-based access for admin roles (Alici Admin, Satici Admin, etc.)
    user_tenant = get_user_tenant(user)
    if user_tenant and doc_tenant and user_tenant == doc_tenant:
        # User belongs to the same tenant - grant access for tenant admins
        user_roles = frappe.get_roles(user)
        admin_roles = ["Marka Sahibi", "Alici Admin", "Satici Admin"]
        if any(role in user_roles for role in admin_roles):
            return True

    return False


# =============================================================================
# UTILITY FUNCTIONS FOR PERMISSION MANAGEMENT
# =============================================================================


def create_tenant_user_permission(
    user: str,
    tenant: str,
    apply_to_all_doctypes: int = 1,
    is_default: int = 1
) -> Optional[str]:
    """
    Create a User Permission for tenant-based data isolation.

    This function creates a User Permission record that associates
    a user with a tenant, enabling automatic data filtering.

    Args:
        user: The user to grant permission to
        tenant: The tenant ID/name
        apply_to_all_doctypes: Apply permission to all DocTypes (default: 1)
        is_default: Set as default tenant for user (default: 1)

    Returns:
        str: Name of created User Permission, None if already exists

    Raises:
        frappe.ValidationError: If user or tenant doesn't exist
    """
    # Check if permission already exists
    existing = frappe.db.exists(
        "User Permission",
        {"user": user, "allow": "Tenant", "for_value": tenant}
    )
    if existing:
        return None

    # Validate user exists
    if not frappe.db.exists("User", user):
        frappe.throw(_("User {0} does not exist").format(user))

    # Validate tenant exists
    if not frappe.db.exists("Tenant", tenant):
        frappe.throw(_("Tenant {0} does not exist").format(tenant))

    # Create User Permission
    user_permission = frappe.new_doc("User Permission")
    user_permission.user = user
    user_permission.allow = "Tenant"
    user_permission.for_value = tenant
    user_permission.apply_to_all_doctypes = apply_to_all_doctypes
    user_permission.is_default = is_default
    user_permission.insert(ignore_permissions=True)

    return user_permission.name


def remove_tenant_user_permission(user: str, tenant: str) -> bool:
    """
    Remove a User Permission for tenant association.

    Args:
        user: The user to remove permission from
        tenant: The tenant ID/name

    Returns:
        bool: True if permission was removed, False if it didn't exist
    """
    permission_name = frappe.db.get_value(
        "User Permission",
        {"user": user, "allow": "Tenant", "for_value": tenant}
    )

    if permission_name:
        frappe.delete_doc("User Permission", permission_name, ignore_permissions=True)
        return True

    return False


def get_users_in_tenant(tenant: str) -> list:
    """
    Get all users assigned to a specific tenant.

    Args:
        tenant: The tenant ID/name

    Returns:
        list: List of user names assigned to the tenant
    """
    user_permissions = frappe.get_all(
        "User Permission",
        filters={"allow": "Tenant", "for_value": tenant},
        pluck="user"
    )
    return user_permissions


def get_user_tenants(user: str) -> list:
    """
    Get all tenants a user has access to.

    Args:
        user: The user to check

    Returns:
        list: List of tenant IDs the user can access
    """
    tenants = frappe.get_all(
        "User Permission",
        filters={"user": user, "allow": "Tenant"},
        pluck="for_value"
    )
    return tenants

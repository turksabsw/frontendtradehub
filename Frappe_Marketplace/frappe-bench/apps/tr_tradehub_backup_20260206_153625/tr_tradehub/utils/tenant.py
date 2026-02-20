# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

"""
Tenant Utility Module for Multi-Tenant Isolation

This module provides functions and decorators for implementing multi-tenant
isolation in TR-TradeHub marketplace. It handles:
- Getting tenant context from session or request
- Applying tenant filters to database queries
- Validating tenant access permissions
- Managing tenant context for background jobs

Usage:
    from tr_tradehub.utils import get_current_tenant, apply_tenant_filter

    # Get current tenant
    tenant_id = get_current_tenant()

    # Apply tenant filter to conditions
    conditions = {"status": "Active"}
    conditions = apply_tenant_filter("Listing", conditions)

    # Use decorator for tenant-scoped functions
    @with_tenant_context
    def my_function():
        pass
"""

import functools
from contextlib import contextmanager
from typing import Any, Callable, Dict, List, Optional, Union

import frappe
from frappe import _
from frappe.utils import cstr


# =============================================================================
# EXCEPTIONS
# =============================================================================


class TenantContextError(Exception):
    """Base exception for tenant context errors."""

    pass


class TenantNotFoundError(TenantContextError):
    """Raised when tenant cannot be found or determined."""

    pass


class TenantAccessDeniedError(TenantContextError):
    """Raised when user does not have access to a tenant."""

    pass


# =============================================================================
# TENANT CONTEXT FUNCTIONS
# =============================================================================


def get_current_tenant() -> Optional[str]:
    """
    Get tenant context from session or request.

    This is the primary method for determining the current tenant context.
    It checks multiple sources in order of priority:
    1. frappe.local.tenant_id (explicitly set context)
    2. frappe.local.session.tenant_id (session-based)
    3. frappe.form_dict.get("tenant_id") (request parameter)
    4. User's default tenant from user settings

    Returns:
        str: Tenant ID/name if found, None otherwise

    Example:
        tenant_id = get_current_tenant()
        if tenant_id:
            # User is operating within a tenant context
            pass
    """
    # Check explicitly set context first (highest priority)
    if hasattr(frappe.local, "tenant_id") and frappe.local.tenant_id:
        return frappe.local.tenant_id

    # Check session
    tenant_id = get_tenant_from_session()
    if tenant_id:
        return tenant_id

    # Check request parameters
    tenant_id = get_tenant_from_request()
    if tenant_id:
        return tenant_id

    # Check user's default tenant
    tenant_id = get_user_default_tenant()
    if tenant_id:
        return tenant_id

    return None


def get_tenant_from_session() -> Optional[str]:
    """
    Get tenant ID from current session.

    Returns:
        str: Tenant ID from session, None if not set
    """
    if hasattr(frappe.local, "session") and frappe.local.session:
        return getattr(frappe.local.session, "tenant_id", None)
    return None


def get_tenant_from_request() -> Optional[str]:
    """
    Get tenant ID from request parameters.

    Checks both form_dict (POST/form data) and request args (GET parameters).

    Returns:
        str: Tenant ID from request, None if not set
    """
    # Check form_dict first
    if frappe.form_dict and frappe.form_dict.get("tenant_id"):
        return cstr(frappe.form_dict.get("tenant_id"))

    # Check request args
    if hasattr(frappe.local, "request") and frappe.local.request:
        tenant_id = frappe.local.request.args.get("tenant_id")
        if tenant_id:
            return cstr(tenant_id)

    return None


def get_user_default_tenant() -> Optional[str]:
    """
    Get the default tenant for the current user.

    This checks user settings or seller profile to determine the user's
    default tenant association.

    Returns:
        str: Default tenant ID for user, None if not set
    """
    if frappe.session.user == "Guest":
        return None

    # Check user's default tenant setting
    default_tenant = frappe.db.get_value(
        "User", frappe.session.user, "default_tenant"
    )
    if default_tenant:
        return default_tenant

    # Check if user has a seller profile with tenant
    seller_profile = frappe.db.get_value(
        "Seller Profile",
        {"user": frappe.session.user},
        "tenant",
    )
    if seller_profile:
        return seller_profile

    return None


def set_tenant_context(tenant_id: str) -> None:
    """
    Explicitly set the tenant context for current request/operation.

    This sets the tenant_id on frappe.local which takes highest priority
    when determining current tenant.

    Args:
        tenant_id: The tenant ID to set as current context

    Raises:
        TenantNotFoundError: If tenant does not exist
        TenantAccessDeniedError: If user doesn't have access to tenant

    Example:
        set_tenant_context("TENANT-001")
        # Now all tenant-scoped operations use TENANT-001
    """
    if not tenant_id:
        raise TenantNotFoundError(_("Tenant ID cannot be empty"))

    # Verify tenant exists
    if not frappe.db.exists("Tenant", tenant_id):
        raise TenantNotFoundError(_("Tenant {0} not found").format(tenant_id))

    # Check if user has access to this tenant
    if not check_tenant_permission(tenant_id, frappe.session.user):
        raise TenantAccessDeniedError(
            _("You do not have access to tenant {0}").format(tenant_id)
        )

    frappe.local.tenant_id = tenant_id


def clear_tenant_context() -> None:
    """
    Clear the current tenant context.

    This removes the explicitly set tenant_id from frappe.local.
    """
    if hasattr(frappe.local, "tenant_id"):
        frappe.local.tenant_id = None


@contextmanager
def tenant_context(tenant_id: str):
    """
    Context manager for temporarily setting tenant context.

    This is useful for operations that need to run in a specific tenant
    context temporarily, such as background jobs or cross-tenant operations.

    Args:
        tenant_id: The tenant ID to use within the context

    Yields:
        None

    Example:
        with tenant_context("TENANT-001"):
            listings = frappe.get_list("Listing", filters={"status": "Active"})
    """
    previous_tenant = getattr(frappe.local, "tenant_id", None)
    try:
        set_tenant_context(tenant_id)
        yield
    finally:
        if previous_tenant:
            frappe.local.tenant_id = previous_tenant
        else:
            clear_tenant_context()


# =============================================================================
# FILTER FUNCTIONS
# =============================================================================


def apply_tenant_filter(
    doctype: str,
    conditions: Dict[str, Any],
    tenant_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Apply tenant filter to query conditions.

    This function adds a tenant_id filter to the provided conditions dict
    if the DocType is tenant-scoped and a tenant context exists.

    Args:
        doctype: The DocType being queried
        conditions: Dict of filter conditions to modify
        tenant_id: Optional explicit tenant ID (uses current context if not provided)

    Returns:
        dict: Modified conditions with tenant filter applied

    Example:
        conditions = {"status": "Active", "category": "Electronics"}
        conditions = apply_tenant_filter("Listing", conditions)
        # conditions now includes tenant_id filter
    """
    # Get tenant ID
    if tenant_id is None:
        tenant_id = get_current_tenant()

    if not tenant_id:
        return conditions

    # Check if DocType has tenant_id field
    if not is_tenant_scoped_doctype(doctype):
        return conditions

    # Add tenant filter
    conditions = conditions.copy()  # Don't modify original
    conditions["tenant_id"] = tenant_id

    return conditions


def build_tenant_query_condition(
    doctype: str,
    tenant_id: Optional[str] = None,
    field_name: str = "tenant_id",
) -> str:
    """
    Build SQL WHERE clause for tenant filtering.

    This is useful for custom SQL queries that need tenant isolation.

    Args:
        doctype: The DocType being queried
        tenant_id: Optional explicit tenant ID
        field_name: Name of the tenant field (default: tenant_id)

    Returns:
        str: SQL condition string, empty string if no tenant context

    Example:
        condition = build_tenant_query_condition("Listing")
        # Returns: "`tabListing`.`tenant_id` = 'TENANT-001'"
    """
    if tenant_id is None:
        tenant_id = get_current_tenant()

    if not tenant_id:
        return ""

    # Escape tenant_id to prevent SQL injection
    escaped_tenant_id = frappe.db.escape(tenant_id)
    return f"`tab{doctype}`.`{field_name}` = {escaped_tenant_id}"


def get_tenant_list_query(
    doctype: str,
    user: Optional[str] = None,
) -> str:
    """
    Generate the list query filter for tenant isolation.

    This function is designed to be used in DocType get_list_query hooks
    for automatic tenant filtering.

    Args:
        doctype: The DocType being queried
        user: The user making the query (default: current user)

    Returns:
        str: SQL WHERE condition for tenant filtering

    Example:
        # In doctype controller:
        @staticmethod
        def get_list_query(user):
            return get_tenant_list_query("Listing", user)
    """
    tenant_id = get_current_tenant()

    if not tenant_id:
        # No tenant context - check if user is admin
        if user and ("System Manager" in frappe.get_roles(user)):
            return ""  # Admins can see all
        return "1=0"  # No tenant context, return no results

    return build_tenant_query_condition(doctype, tenant_id)


# =============================================================================
# VALIDATION FUNCTIONS
# =============================================================================


def validate_tenant_access(
    tenant_id: str,
    user: Optional[str] = None,
    throw: bool = True,
) -> bool:
    """
    Validate that a user has access to a specific tenant.

    Args:
        tenant_id: The tenant ID to validate access for
        user: The user to check (default: current session user)
        throw: If True, raises exception on failure (default: True)

    Returns:
        bool: True if access is allowed, False otherwise

    Raises:
        TenantAccessDeniedError: If throw=True and access is denied
    """
    if user is None:
        user = frappe.session.user

    # System Manager can access all tenants
    if "System Manager" in frappe.get_roles(user):
        return True

    # Check if user belongs to this tenant
    has_access = check_tenant_permission(tenant_id, user)

    if not has_access and throw:
        raise TenantAccessDeniedError(
            _("You do not have access to tenant {0}").format(tenant_id)
        )

    return has_access


def check_tenant_permission(
    tenant_id: str,
    user: Optional[str] = None,
) -> bool:
    """
    Check if a user has permission to access a tenant.

    This checks various associations:
    - Is user a tenant admin?
    - Does user have a seller profile in this tenant?
    - Is user's default tenant this tenant?

    Args:
        tenant_id: The tenant ID to check
        user: The user to check (default: current session user)

    Returns:
        bool: True if user has permission
    """
    if user is None:
        user = frappe.session.user

    # Guest has no tenant access
    if user == "Guest":
        return False

    # System Manager can access all
    if "System Manager" in frappe.get_roles(user):
        return True

    # Check if user is tenant admin
    tenant_admin = frappe.db.get_value("Tenant", tenant_id, "admin_user")
    if tenant_admin == user:
        return True

    # Check if user has seller profile in this tenant
    has_seller_profile = frappe.db.exists(
        "Seller Profile", {"user": user, "tenant": tenant_id}
    )
    if has_seller_profile:
        return True

    # Check user's default tenant
    user_default_tenant = frappe.db.get_value("User", user, "default_tenant")
    if user_default_tenant == tenant_id:
        return True

    return False


def validate_document_tenant(
    doc,
    throw: bool = True,
) -> bool:
    """
    Validate that a document's tenant matches the current context.

    This should be called in document controllers to ensure documents
    are only modified within their tenant context.

    Args:
        doc: The document to validate
        throw: If True, raises exception on mismatch (default: True)

    Returns:
        bool: True if tenant matches or document is not tenant-scoped

    Raises:
        TenantAccessDeniedError: If throw=True and tenant doesn't match
    """
    if not hasattr(doc, "tenant_id") or not doc.tenant_id:
        return True  # Not tenant-scoped

    current_tenant = get_current_tenant()

    # No tenant context - check if user is admin
    if not current_tenant:
        if "System Manager" in frappe.get_roles():
            return True
        if throw:
            raise TenantAccessDeniedError(
                _("Cannot access document outside tenant context")
            )
        return False

    if doc.tenant_id != current_tenant:
        if throw:
            raise TenantAccessDeniedError(
                _("Document belongs to a different tenant")
            )
        return False

    return True


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================


def get_tenant_doc(
    tenant_id: Optional[str] = None,
    cached: bool = True,
) -> "frappe.Document":
    """
    Get the Tenant document for the current or specified tenant.

    Args:
        tenant_id: Optional tenant ID (uses current context if not provided)
        cached: If True, uses cached document (default: True)

    Returns:
        Document: The Tenant document

    Raises:
        TenantNotFoundError: If tenant cannot be determined or doesn't exist
    """
    if tenant_id is None:
        tenant_id = get_current_tenant()

    if not tenant_id:
        raise TenantNotFoundError(_("No tenant context available"))

    if cached:
        return frappe.get_cached_doc("Tenant", tenant_id)
    return frappe.get_doc("Tenant", tenant_id)


def is_tenant_active(tenant_id: Optional[str] = None) -> bool:
    """
    Check if the current or specified tenant is active.

    Args:
        tenant_id: Optional tenant ID (uses current context if not provided)

    Returns:
        bool: True if tenant is active, False otherwise
    """
    try:
        tenant = get_tenant_doc(tenant_id)
        return tenant.is_active()
    except TenantNotFoundError:
        return False


def is_tenant_scoped_doctype(doctype: str) -> bool:
    """
    Check if a DocType is tenant-scoped (has tenant_id field).

    Args:
        doctype: The DocType name to check

    Returns:
        bool: True if DocType has tenant_id field
    """
    # Cache the result for performance
    cache_key = f"tenant_scoped_doctype:{doctype}"
    cached = frappe.cache().get_value(cache_key)

    if cached is not None:
        return cached

    meta = frappe.get_meta(doctype)
    has_tenant_field = meta.has_field("tenant_id")

    frappe.cache().set_value(cache_key, has_tenant_field, expires_in_sec=3600)
    return has_tenant_field


def get_tenant_settings(
    tenant_id: Optional[str] = None,
    setting_key: Optional[str] = None,
) -> Union[Dict[str, Any], Any]:
    """
    Get settings for a tenant.

    Args:
        tenant_id: Optional tenant ID (uses current context if not provided)
        setting_key: Optional specific setting key to retrieve

    Returns:
        dict or value: All settings or specific setting value
    """
    tenant = get_tenant_doc(tenant_id)

    settings = {
        "max_sellers": tenant.max_sellers,
        "max_listings_per_seller": tenant.max_listings_per_seller,
        "commission_rate": tenant.commission_rate,
        "subscription_tier": tenant.subscription_tier,
        "e_invoice_enabled": tenant.e_invoice_enabled,
        "e_archive_enabled": tenant.e_archive_enabled,
    }

    if setting_key:
        return settings.get(setting_key)

    return settings


# =============================================================================
# DECORATORS
# =============================================================================


def with_tenant_context(func: Callable) -> Callable:
    """
    Decorator to ensure function runs within a tenant context.

    If no tenant context exists, the decorated function will not execute
    and will return None (or raise if configured).

    Args:
        func: The function to decorate

    Returns:
        Callable: Decorated function

    Example:
        @with_tenant_context
        def create_listing(title, price):
            # This will only run if tenant context exists
            doc = frappe.new_doc("Listing")
            doc.title = title
            doc.price = price
            doc.insert()
            return doc
    """

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        tenant_id = get_current_tenant()
        if not tenant_id:
            frappe.throw(_("This operation requires a tenant context"))
        return func(*args, **kwargs)

    return wrapper


def require_tenant(tenant_id: Optional[str] = None) -> Callable:
    """
    Decorator factory to require a specific tenant context.

    Args:
        tenant_id: Optional specific tenant ID to require

    Returns:
        Callable: Decorator function

    Example:
        @require_tenant("TENANT-001")
        def process_tenant_data():
            # Only runs if current tenant is TENANT-001
            pass

        @require_tenant()  # Requires any tenant context
        def generic_tenant_operation():
            pass
    """

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            current_tenant = get_current_tenant()

            if not current_tenant:
                frappe.throw(_("This operation requires a tenant context"))

            if tenant_id and current_tenant != tenant_id:
                frappe.throw(
                    _("This operation requires tenant {0}").format(tenant_id)
                )

            return func(*args, **kwargs)

        return wrapper

    return decorator


# =============================================================================
# DOCTYPE CONTROLLER HELPERS
# =============================================================================


def set_tenant_before_insert(doc) -> None:
    """
    Helper to set tenant_id on document before insert.

    Call this in your DocType's before_insert method.

    Args:
        doc: The document being inserted

    Example:
        class Listing(Document):
            def before_insert(self):
                set_tenant_before_insert(self)
    """
    if hasattr(doc, "tenant_id") and not doc.tenant_id:
        tenant_id = get_current_tenant()
        if tenant_id:
            doc.tenant_id = tenant_id
        else:
            frappe.throw(
                _("Cannot create {0} without tenant context").format(
                    doc.doctype
                )
            )


def validate_tenant_on_save(doc) -> None:
    """
    Helper to validate tenant on document save.

    Call this in your DocType's validate method.

    Args:
        doc: The document being saved

    Raises:
        TenantAccessDeniedError: If tenant validation fails
    """
    validate_document_tenant(doc, throw=True)


# =============================================================================
# API ENDPOINTS
# =============================================================================


@frappe.whitelist()
def switch_tenant(tenant_id: str) -> Dict[str, Any]:
    """
    API endpoint to switch the current user's tenant context.

    Args:
        tenant_id: The tenant ID to switch to

    Returns:
        dict: Result with status and tenant info
    """
    try:
        set_tenant_context(tenant_id)
        tenant = get_tenant_doc(tenant_id)

        # Update session
        if hasattr(frappe.local, "session"):
            frappe.local.session.tenant_id = tenant_id

        return {
            "success": True,
            "tenant_id": tenant_id,
            "tenant_name": tenant.tenant_name,
            "company_name": tenant.company_name,
        }
    except (TenantNotFoundError, TenantAccessDeniedError) as e:
        return {"success": False, "message": str(e)}


@frappe.whitelist()
def get_user_tenants() -> List[Dict[str, Any]]:
    """
    API endpoint to get all tenants accessible by the current user.

    Returns:
        list: List of tenant info dicts the user can access
    """
    user = frappe.session.user

    if user == "Guest":
        return []

    # System Manager can see all tenants
    if "System Manager" in frappe.get_roles(user):
        tenants = frappe.get_all(
            "Tenant",
            filters={"status": "Active"},
            fields=["name", "tenant_name", "company_name", "subscription_tier"],
        )
        return tenants

    # Get tenants from seller profiles
    seller_tenants = frappe.get_all(
        "Seller Profile",
        filters={"user": user},
        pluck="tenant",
    )

    # Get user's default tenant
    default_tenant = frappe.db.get_value("User", user, "default_tenant")

    # Combine and deduplicate
    tenant_ids = list(set(seller_tenants + ([default_tenant] if default_tenant else [])))

    if not tenant_ids:
        return []

    tenants = frappe.get_all(
        "Tenant",
        filters={"name": ["in", tenant_ids], "status": "Active"},
        fields=["name", "tenant_name", "company_name", "subscription_tier"],
    )

    return tenants


@frappe.whitelist()
def get_current_tenant_info() -> Optional[Dict[str, Any]]:
    """
    API endpoint to get information about the current tenant context.

    Returns:
        dict: Current tenant info or None if no context
    """
    tenant_id = get_current_tenant()

    if not tenant_id:
        return None

    try:
        tenant = get_tenant_doc(tenant_id)
        return {
            "tenant_id": tenant_id,
            "tenant_name": tenant.tenant_name,
            "company_name": tenant.company_name,
            "subscription_tier": tenant.subscription_tier,
            "is_active": tenant.is_active(),
            "settings": get_tenant_settings(tenant_id),
        }
    except TenantNotFoundError:
        return None

# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

"""
TR TradeHub Utilities Module

This module provides utility functions for the TR-TradeHub marketplace platform.
"""

from tr_tradehub.utils.tenant import (
    get_current_tenant,
    get_tenant_from_session,
    get_tenant_from_request,
    set_tenant_context,
    clear_tenant_context,
    apply_tenant_filter,
    validate_tenant_access,
    with_tenant_context,
    get_tenant_doc,
    is_tenant_active,
    check_tenant_permission,
    TenantContextError,
    TenantNotFoundError,
    TenantAccessDeniedError,
)

from tr_tradehub.utils.erpnext_sync import (
    # ERPNext availability check
    is_erpnext_installed,
    require_erpnext,
    # Listing -> Item sync
    create_item_from_listing,
    sync_item_from_listing,
    update_item_stock_from_listing,
    # Listing Variant -> Item Variant sync
    create_item_variant_from_listing_variant,
    # Seller Profile -> Supplier sync
    create_supplier_from_seller,
    sync_supplier_from_seller,
    # Organization -> Customer sync
    create_customer_from_organization,
    sync_customer_from_organization,
    # Marketplace Order -> Sales Order sync
    create_sales_order_from_marketplace_order,
    # Bulk sync functions
    bulk_sync_listings_to_items,
    bulk_sync_sellers_to_suppliers,
    # API endpoints
    sync_listing_to_erpnext,
    get_erpnext_sync_status,
    run_bulk_sync,
    # Exceptions
    ERPNextNotInstalled,
    ERPNextSyncError,
)

__all__ = [
    # Tenant context functions
    "get_current_tenant",
    "get_tenant_from_session",
    "get_tenant_from_request",
    "set_tenant_context",
    "clear_tenant_context",
    # Filter functions
    "apply_tenant_filter",
    # Validation functions
    "validate_tenant_access",
    "check_tenant_permission",
    # Decorator
    "with_tenant_context",
    # Helper functions
    "get_tenant_doc",
    "is_tenant_active",
    # Exceptions
    "TenantContextError",
    "TenantNotFoundError",
    "TenantAccessDeniedError",
    # ERPNext Sync
    "is_erpnext_installed",
    "require_erpnext",
    "create_item_from_listing",
    "sync_item_from_listing",
    "update_item_stock_from_listing",
    "create_item_variant_from_listing_variant",
    "create_supplier_from_seller",
    "sync_supplier_from_seller",
    "create_customer_from_organization",
    "sync_customer_from_organization",
    "create_sales_order_from_marketplace_order",
    "bulk_sync_listings_to_items",
    "bulk_sync_sellers_to_suppliers",
    "sync_listing_to_erpnext",
    "get_erpnext_sync_status",
    "run_bulk_sync",
    "ERPNextNotInstalled",
    "ERPNextSyncError",
]

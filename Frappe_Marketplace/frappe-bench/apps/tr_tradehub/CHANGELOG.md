# Changelog

All notable changes to the TR TradeHub B2B Marketplace Platform will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Core Architecture - RBAC/ABAC Implementation

This release implements comprehensive Role-Based Access Control (RBAC) and Attribute-Based Access Control (ABAC) for the TR TradeHub B2B marketplace platform, establishing the Tenant-Seller-Organization hierarchical relationship model.

---

## [1.0.0] - 2026-02-02

### Added

#### Role Permission System

- **ROLE_PERMISSIONS.md** - Comprehensive documentation for all 6 marketplace roles:
  - `System Manager` - Full platform administration access
  - `Marka Sahibi` - Brand owner with oversight permissions
  - `Alici Admin` - Buyer organization administrator
  - `Alici Editor` - Buyer organization content editor
  - `Satici Admin` - Seller organization administrator
  - `Satici` - Individual seller with own-profile access

- **Role hierarchy documentation** with clear permission boundaries
- **DocType permission matrix** for all core DocTypes

#### Row-Level Security (ABAC)

- **Permission Query Functions** (`permissions.py`):
  - `get_marketplace_order_permission_query()` - Filters orders by tenant
  - `get_cart_permission_query()` - Filters carts by tenant
  - `get_rfq_permission_query()` - Filters RFQ records by tenant

- **Has Permission Hooks**:
  - `has_marketplace_order_permission()` - Buyer/seller order access validation
  - `has_sub_order_permission()` - Sub-order access by seller/buyer relationship

- **User Permission Auto-Creation**:
  - Seller Profile creation automatically creates User Permission for tenant
  - Organization creation automatically creates User Permission for creator's tenant
  - Follows existing pattern from Tenant DocType

#### Field-Level Permissions (permlevel)

- **Tenant DocType** - Admin-only fields protected:
  - `subscription_tier` (permlevel: 1)
  - `max_sellers` (permlevel: 1)
  - `max_listings_per_seller` (permlevel: 1)
  - `commission_rate` (permlevel: 1)

- **Seller Profile DocType** - Admin-only fields protected:
  - `verification_status` (permlevel: 1)
  - `is_restricted` (permlevel: 1)
  - `seller_score` (permlevel: 1)
  - `is_top_seller` (permlevel: 1)
  - `is_premium_seller` (permlevel: 1)

- **Organization DocType** - Admin-only fields protected:
  - `verification_status` (permlevel: 1)
  - `credit_limit` (permlevel: 1)
  - `is_approved_buyer` (permlevel: 1)
  - `is_approved_seller` (permlevel: 1)

#### Client-Side Filters (set_query)

- **listing.js** - Set query filters for tenant isolation:
  - Seller field filters by tenant
  - Category field filters active categories only
  - Subcategory cascading filter by parent category
  - Attribute Set filter by selected category
  - Variant Of filter by same seller and tenant
  - Auto-populate tenant from seller
  - Cascading field clearing with user feedback

- **cart.js** - Set query filters for multi-tenant carts:
  - Organization field filter by tenant
  - Buyer field filter via custom query (get_buyers_for_tenant)
  - Cart Line child table filters for Listing and Listing Variant
  - Marketplace Order field filter by tenant
  - Cart summary display with item/seller count
  - Status-based editing restrictions

#### Validation Hooks

- **listing.py** - Tenant validation:
  - `validate_tenant_seller_consistency()` - Ensures seller's tenant matches listing's tenant
  - Auto-sets tenant from seller if not specified
  - Clear ValidationError messages for mismatches

- **cart.py** - Cart tenant validation:
  - `validate_tenant_consistency()` - Validates organization and cart items
  - Auto-sets tenant from organization
  - `get_buyers_for_tenant()` - Server-side query for buyer field

#### Scheduled Jobs

- **permission_cleanup.py** - New scheduled jobs module:
  - `cleanup_orphan_user_permissions()` - Daily job removing orphaned permissions
  - `cleanup_duplicate_permissions()` - Daily job removing duplicate entries
  - `audit_permission_records()` - Weekly permission audit report with anomaly detection

- **hooks.py** - Scheduler events configured:
  - Hourly: Seller metrics refresh, RFQ deadline checks
  - Daily: Tag rule evaluation, orphan/duplicate permission cleanup
  - Weekly: Old metrics cleanup, permission audit

#### Test Coverage

- **test_tenant_organization_hierarchy.py** - Hierarchy tests:
  - `TestTenantCreation` - Tenant naming and creation
  - `TestOrganizationTenantLink` - Organization-tenant relationship
  - `TestSellerProfileTenantLink` - Seller-organization-tenant chain
  - `TestTenantOrganizationConsistency` - Mismatch rejection
  - `TestTenantChangePrevention` - Tenant change restrictions

- **test_rbac_permissions.py** - RBAC permission tests:
  - `TestSystemManagerFullAccess` - Full CRUD verification
  - `TestSaticiOwnProfileAccess` - if_owner verification
  - `TestAliciAdminOrganizationManagement` - Buyer admin permissions
  - `TestCrossTenantAccessPrevention` - Tenant isolation
  - `TestFieldLevelPermissions` - permlevel 1 restrictions
  - `TestRoleHierarchy` - Role hierarchy verification

- **test_e2e_permission_flow.py** - End-to-end tests:
  - Full permission flow from tenant creation to seller access
  - 8 sequential test methods covering complete workflow
  - Standalone verification functions for manual testing

### Changed

#### DocType Permission Updates

- **Tenant DocType** (`tenant.json`):
  - Added System Manager permlevel 1 permission entry
  - All roles retain read-only access (no changes to base permissions)

- **Seller Profile DocType** (`seller_profile.json`):
  - Removed overly permissive "All" role
  - Added `if_owner: 1` for Satici role (row-level security)
  - Enhanced `tenant` field with `read_only_depends_on: eval:doc.organization`
  - Added comprehensive permission matrix for all 6 roles
  - Added System Manager permlevel 1 permission entry

- **Organization DocType** (`organization.json`):
  - Added Buyer Profile to links section
  - Added Organization Member to links section
  - Added `if_owner: 1` for Alici Admin and Alici Editor roles
  - Enhanced permission matrix for all 6 roles
  - Added System Manager permlevel 1 permission entry

#### Hooks Configuration

- **hooks.py**:
  - Added Cart, Marketplace Order, RFQ to `permission_query_conditions`
  - Added Marketplace Order, Sub Order to `has_permission` hooks
  - Configured `scheduler_events` with permission cleanup jobs

#### Fixtures

- **01_role.json**:
  - Added `home_page` configuration for each custom role
  - Role definitions enhanced with proper desk access settings

### Security

#### Breaking Changes

- **Satici role now uses `if_owner: 1`** - Sellers can only access their own Seller Profile records
- **Alici Admin and Alici Editor use `if_owner: 1`** - Buyer admins/editors can only access their own Organization
- **Admin-only fields protected with permlevel 1** - Non-System Manager users cannot edit verification status, credit limits, subscription tiers, etc.
- **Cross-tenant access blocked** - All tenant-scoped DocTypes now enforce tenant isolation via permission queries

#### Data Access Restrictions

| Role | Tenant | Organization | Seller Profile | Listing | Cart | Order |
|------|--------|--------------|----------------|---------|------|-------|
| System Manager | Full CRUD | Full CRUD | Full CRUD | Full CRUD | Full CRUD | Full CRUD |
| Marka Sahibi | Read | Read | Read | Read (tenant) | Read (tenant) | Read (tenant) |
| Alici Admin | Read | Own only | Read | Read (tenant) | Own only | Own only |
| Alici Editor | Read | Own only | Read | Read (tenant) | - | - |
| Satici Admin | Read | Read | Create/Edit (org) | Create/Edit (org) | Read | Read (org) |
| Satici | Read | Read | Own only | Own only | - | Own only |

### Migration Notes

#### Required Actions After Update

1. **Run Frappe migrate** to apply DocType field changes:
   ```bash
   bench --site [sitename] migrate
   ```

2. **Clear cache** to reload permissions:
   ```bash
   bench --site [sitename] clear-cache
   ```

3. **Verify role assignments** - Ensure users have correct roles assigned

4. **Review existing User Permissions** - Run cleanup to remove orphans:
   ```bash
   bench --site [sitename] console
   >>> from tr_tradehub.scheduled_jobs.permission_cleanup import cleanup_orphan_user_permissions
   >>> cleanup_orphan_user_permissions()
   ```

#### Backward Compatibility

- Existing Tenant, Organization, and Seller Profile records remain accessible
- Users without specific roles may lose access to previously visible records
- System Manager retains full access to all records
- Admin-only fields (verification_status, etc.) will be read-only for non-System Manager users

### Files Modified

| File | Changes |
|------|---------|
| `hooks.py` | Added permission_query_conditions, has_permission, scheduler_events |
| `permissions.py` | Added 3 permission query functions, 2 has_permission functions |
| `tenant.json` | Added permlevel 1 for admin fields |
| `seller_profile.json` | Added if_owner, read_only_depends_on, permlevel 1 fields |
| `seller_profile.py` | Added User Permission creation on after_insert |
| `organization.json` | Added links, if_owner permissions, permlevel 1 fields |
| `organization.py` | Added User Permission creation on after_insert |
| `listing.py` | Added validate_tenant_seller_consistency() |
| `cart.py` | Added validate_tenant_consistency(), get_buyers_for_tenant() |
| `01_role.json` | Added home_page configuration for roles |

### Files Created

| File | Purpose |
|------|---------|
| `docs/ROLE_PERMISSIONS.md` | Role permission documentation |
| `scheduled_jobs/__init__.py` | Scheduled jobs package init |
| `scheduled_jobs/permission_cleanup.py` | Permission cleanup scheduled jobs |
| `doctype/listing/listing.js` | Client-side set_query filters |
| `doctype/cart/cart.js` | Client-side set_query filters |
| `tests/test_tenant_organization_hierarchy.py` | Hierarchy relationship tests |
| `tests/test_rbac_permissions.py` | RBAC permission tests |
| `tests/test_e2e_permission_flow.py` | End-to-end permission flow tests |

### Specification Reference

This implementation follows **002-core-architecture.md** specification covering:
- Tenant-Seller-Organization hierarchical relationships
- RBAC (Role-Based Access Control) via DocType permissions
- ABAC (Attribute-Based Access Control) via permission queries and if_owner
- Field-level permissions via permlevel
- Row-level security via User Permission

---

## Previous Releases

For changes prior to the Core Architecture implementation, see the git history.

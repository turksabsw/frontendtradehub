# TR TradeHub Role Permissions Matrix

This document provides comprehensive documentation of all roles in the TR TradeHub B2B marketplace platform, their purposes, permission boundaries, and the complete DocType permission matrix.

## Table of Contents

- [Role Overview](#role-overview)
- [Role Hierarchy](#role-hierarchy)
- [Role Descriptions](#role-descriptions)
- [Permission Matrix by DocType](#permission-matrix-by-doctype)
- [User Permission (Row-Level Security)](#user-permission-row-level-security)
- [Field-Level Permissions](#field-level-permissions)
- [Role Profiles](#role-profiles)

---

## Role Overview

TR TradeHub implements a comprehensive Role-Based Access Control (RBAC) system combined with Attribute-Based Access Control (ABAC) for row-level security. The platform uses 6 primary roles:

| Role | Turkish Name | Type | Primary Use Case |
|------|--------------|------|------------------|
| System Manager | Sistem Yoneticisi | Built-in | Full platform administration |
| Marka Sahibi | Brand Owner | Custom | Brand oversight and catalog management |
| Alici Admin | Buyer Admin | Custom | Buyer organization management |
| Alici Editor | Buyer Editor | Custom | Buyer operations (orders, RFQ) |
| Satici Admin | Seller Admin | Custom | Seller organization management |
| Satici | Seller | Custom | Daily seller operations |

---

## Role Hierarchy

```
                    System Manager
                          |
                    Marka Sahibi
                    (Brand Owner)
                          |
            +-------------+-------------+
            |                           |
      Alici Admin                 Satici Admin
     (Buyer Admin)               (Seller Admin)
            |                           |
      Alici Editor                   Satici
     (Buyer Editor)                 (Seller)
```

### Hierarchy Rules

1. **System Manager** has unrestricted access to all DocTypes and data
2. **Marka Sahibi** can view all tenant data but cannot modify core settings
3. **Alici Admin** inherits Alici Editor permissions plus organization management
4. **Satici Admin** inherits Satici permissions plus seller organization management
5. Higher roles inherit lower role permissions within their branch

---

## Role Descriptions

### 1. System Manager (Sistem Yoneticisi)

**Purpose:** Full platform administration and configuration

**Responsibilities:**
- Create and manage Tenants
- Configure platform-wide settings
- Manage user accounts and role assignments
- Access all DocTypes with full CRUD permissions
- Configure commission plans and pricing
- Manage system integrations

**Permission Level:** Full Access (permlevel 0 and 1)

### 2. Marka Sahibi (Brand Owner)

**Purpose:** Brand catalog oversight and multi-tenant brand management

**Responsibilities:**
- View brand-related data across authorized tenants
- Manage brand authorization requests
- Review brand compliance and usage
- Monitor brand performance metrics
- Approve/reject brand applications

**Permission Level:** Read-only on most DocTypes, limited write access to brand-specific DocTypes

**Use Cases:**
- Brand manufacturers managing authorized sellers
- Franchise owners overseeing franchisee compliance
- Brand representatives monitoring marketplace presence

### 3. Alici Admin (Buyer Admin)

**Purpose:** Buyer organization administration

**Responsibilities:**
- Create and manage organization profile
- Manage organization members and their roles
- Set purchasing policies and limits
- Approve high-value purchases
- Manage buyer addresses and contacts
- Review organization-wide order history
- Create and manage RFQ requests

**Permission Level:** Full access to buyer-specific DocTypes within own organization

**Typical User:** Purchasing Manager, Procurement Director

### 4. Alici Editor (Buyer Editor)

**Purpose:** Daily buyer operations

**Responsibilities:**
- Browse catalog and add items to cart
- Create standard purchase orders
- Submit RFQ requests
- Track order status
- Manage personal addresses
- View organization data (read-only)

**Permission Level:** Limited write access, primarily for order-related operations

**Typical User:** Purchasing Specialist, Procurement Officer

### 5. Satici Admin (Seller Admin)

**Purpose:** Seller organization administration

**Responsibilities:**
- Manage seller profile settings
- Add and manage team members
- Configure shipping rules and policies
- Set pricing and commission preferences
- View financial reports and analytics
- Manage seller documents and compliance
- Handle withdrawal requests

**Permission Level:** Full access to seller-specific DocTypes within own organization

**Typical User:** Store Owner, Sales Manager

### 6. Satici (Seller)

**Purpose:** Daily seller operations

**Responsibilities:**
- Create and manage product listings
- Process incoming orders
- Update inventory/stock levels
- Respond to buyer inquiries
- Handle returns and refunds (within limits)
- View own performance metrics

**Permission Level:** Write access to operational DocTypes, read-only for organization settings

**Typical User:** Sales Representative, Warehouse Staff

---

## Permission Matrix by DocType

### Core DocTypes

| DocType | System Manager | Marka Sahibi | Alici Admin | Alici Editor | Satici Admin | Satici |
|---------|----------------|--------------|-------------|--------------|--------------|--------|
| **Tenant** | CRUD | R | R | R | R | R |
| **Organization** | CRUD | R | CRW | RW | R | R |
| **Seller Profile** | CRUD | R | R | R | RW* | RW* |
| **Buyer Profile** | CRUD | R | CRW | RW | R | R |

*Legend: C=Create, R=Read, W=Write, U=Update, D=Delete*
*Note: RW* indicates row-level restriction (only own records)*

### Catalog DocTypes

| DocType | System Manager | Marka Sahibi | Alici Admin | Alici Editor | Satici Admin | Satici |
|---------|----------------|--------------|-------------|--------------|--------------|--------|
| **Category** | CRUD | R | R | R | R | R |
| **Listing** | CRUD | RW | R | R | CRUD* | CRUD* |
| **SKU** | CRUD | R | R | R | CRUD* | CRUD* |
| **Attribute** | CRUD | R | R | R | R | R |
| **Attribute Set** | CRUD | R | R | R | R | R |
| **Media Asset** | CRUD | R | R | R | CRUD* | CRUD* |

### Order DocTypes

| DocType | System Manager | Marka Sahibi | Alici Admin | Alici Editor | Satici Admin | Satici |
|---------|----------------|--------------|-------------|--------------|--------------|--------|
| **Cart** | CRUD | R | CRUD* | CRUD* | R* | R* |
| **Cart Line** | CRUD | R | CRUD* | CRUD* | R* | R* |
| **Marketplace Order** | CRUD | R | R* | R* | R* | R* |
| **Sub Order** | CRUD | R | R* | R* | RW* | RW* |
| **Order Event** | CRUD | R | R* | R* | R* | R* |

### Seller Management DocTypes

| DocType | System Manager | Marka Sahibi | Alici Admin | Alici Editor | Satici Admin | Satici |
|---------|----------------|--------------|-------------|--------------|--------------|--------|
| **Seller Application** | CRUD | R | - | - | R* | - |
| **Seller Tier** | CRUD | R | R | R | R | R |
| **Seller Metrics** | CRUD | R | R | R | R* | R* |
| **Seller Tag** | CRUD | R | R | R | R | R |
| **Seller Balance** | CRUD | R | - | - | R* | R* |
| **Storefront** | CRUD | R | R | R | RW* | R* |

### RFQ DocTypes

| DocType | System Manager | Marka Sahibi | Alici Admin | Alici Editor | Satici Admin | Satici |
|---------|----------------|--------------|-------------|--------------|--------------|--------|
| **RFQ** | CRUD | R | CRUD* | CRW* | R* | R* |
| **RFQ Quote** | CRUD | R | R* | R* | CRUD* | CRUD* |
| **RFQ Message** | CRUD | R | CRUD* | CRUD* | CRUD* | CRUD* |
| **RFQ Item** | CRUD | R | CRUD* | CRW* | R* | R* |

### Payment & Finance DocTypes

| DocType | System Manager | Marka Sahibi | Alici Admin | Alici Editor | Satici Admin | Satici |
|---------|----------------|--------------|-------------|--------------|--------------|--------|
| **Commission Plan** | CRUD | R | R | R | R | R |
| **Commission Rule** | CRUD | R | R | R | R | R |
| **Escrow Account** | CRUD | R | R* | R* | R* | R* |
| **Payment Intent** | CRUD | R | R* | R* | R* | R* |

### Shipping DocTypes

| DocType | System Manager | Marka Sahibi | Alici Admin | Alici Editor | Satici Admin | Satici |
|---------|----------------|--------------|-------------|--------------|--------------|--------|
| **Shipping Rule** | CRUD | R | R | R | CRW* | R* |
| **Shipping Zone** | CRUD | R | R | R | R | R |
| **Marketplace Shipment** | CRUD | R | R* | R* | RW* | RW* |
| **Tracking Event** | CRUD | R | R* | R* | R* | R* |

---

## User Permission (Row-Level Security)

TR TradeHub uses Frappe's User Permission system for row-level data isolation:

### Tenant Isolation

All tenant-scoped DocTypes filter data based on the user's assigned Tenant:

```
User → User Permission (Tenant) → Filters all DocTypes with tenant field
```

**Implementation:**
- When a user is created, they are assigned a User Permission linking them to their Tenant
- All queries automatically filter by the user's permitted Tenant(s)
- This prevents cross-tenant data access

### Seller/Buyer Isolation

Within a tenant, further isolation is applied:

```
Seller User → User Permission (Seller Profile) → Filters seller-specific DocTypes
Buyer User → User Permission (Organization) → Filters buyer-specific DocTypes
```

### DocTypes with Permission Query Conditions

The following DocTypes have permission_query_conditions defined in `hooks.py`:

- Tenant
- Organization
- Seller Profile
- Buyer Profile
- Listing
- Cart
- Marketplace Order
- RFQ

---

## Field-Level Permissions

Certain fields are restricted based on permlevel settings:

### Permlevel 0 (Standard Access)

All users with DocType access can view/edit these fields.

### Permlevel 1 (Admin Only)

Only System Manager can modify these fields:

**Tenant DocType:**
- `subscription_tier`
- `max_sellers`
- `max_listings_per_seller`
- `commission_rate`

**Seller Profile DocType:**
- `verification_status`
- `is_restricted`
- `seller_score`
- `is_top_seller`
- `is_premium_seller`

**Organization DocType:**
- `verification_status`
- `credit_limit`
- `is_approved_buyer`
- `is_approved_seller`

---

## Role Profiles

Role Profiles provide pre-configured role bundles for easy user assignment:

### Marka Sahibi Profili
- Marka Sahibi

### Alici Admin Profili
- Alici Admin
- Alici Editor (inherited)

### Alici Editor Profili
- Alici Editor

### Satici Admin Profili
- Satici Admin
- Satici (inherited)

### Satici Profili
- Satici

---

## Best Practices

### Assigning Roles

1. Always use Role Profiles instead of individual role assignments
2. One user should belong to either Buyer or Seller roles, not both
3. System Manager role should only be assigned to platform administrators

### Creating New DocTypes

When creating new DocTypes in TR TradeHub:

1. Always include the `tenant` field for tenant isolation
2. Add permissions for all 6 roles
3. Set appropriate `permlevel` for admin-only fields
4. Add DocType to `permission_query_conditions` in hooks.py if tenant filtering is needed
5. Document permission rationale in code comments

### Security Considerations

1. Never bypass permission checks with `frappe.flags.ignore_permissions`
2. Always validate tenant consistency in server-side hooks
3. Use `has_permission` hooks for complex permission logic
4. Audit sensitive operations in the activity log

---

## Changelog

| Date | Version | Changes |
|------|---------|---------|
| 2024-01-01 | 1.0.0 | Initial role permission structure |
| 2026-02-02 | 1.1.0 | Added comprehensive documentation, field-level permissions |

---

*Document maintained by: TR TradeHub Development Team*
*Last Updated: 2026-02-02*

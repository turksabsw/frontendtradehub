# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt, getdate, nowdate, now_datetime


class Organization(Document):
    """
    Organization DocType for company accounts in TR-TradeHub marketplace.

    Organizations represent business entities (companies, sole proprietorships, etc.)
    that can act as buyers or sellers on the marketplace. Each organization:
    - Has Turkish tax compliance fields (VKN, Tax Office, MERSIS)
    - Supports E-Invoice (E-Fatura) and E-Archive integration
    - Can have multiple members with different roles
    - Links to ERPNext Customer for ERP integration
    - Supports KYB (Know Your Business) verification workflow
    - Must belong to a Tenant for multi-tenant data isolation
    """

    def before_insert(self):
        """Set default values before inserting a new organization."""
        if not self.created_by:
            self.created_by = frappe.session.user

        # Set tenant from user context if not specified
        if not self.tenant:
            self.set_tenant_from_context()

        # Store original tenant for change detection
        self._original_tenant = None

    def before_validate(self):
        """
        Auto-fill fields before validation runs.

        IMPORTANT: Use before_validate for auto-fill, NOT before_save.
        before_save runs AFTER validate(), so mandatory field check would fail first.
        Hook execution order: before_validate → validate → before_save → save
        """
        # Auto-fill tenant from user context if not set
        self.auto_fill_tenant_from_context()

        # Store original tenant for change detection in validate
        if not self.is_new():
            self._original_tenant = frappe.db.get_value("Organization", self.name, "tenant")

    def validate(self):
        """Validate organization data before saving."""
        self.validate_tenant()
        self.validate_tenant_change()
        self.validate_tax_id()
        self.validate_mersis_number()
        self.validate_trade_registry()
        self.validate_e_invoice_alias()
        self.validate_founded_year()
        self.validate_members()
        self.modified_by = frappe.session.user

    def on_update(self):
        """Actions to perform after organization is updated."""
        self.sync_to_erpnext_customer()
        self.clear_organization_cache()

    def after_insert(self):
        """Actions to perform after organization is inserted."""
        # Create ERPNext Customer if not exists
        if not self.erpnext_customer:
            self.create_erpnext_customer()

        # Create User Permission for creator to enable tenant data isolation
        self.create_user_permission_for_tenant()

    def on_trash(self):
        """Prevent deletion of organization with active orders."""
        self.check_linked_documents()

    def set_tenant_from_context(self):
        """Set tenant from user's session context."""
        try:
            from tradehub_core.tradehub_core.utils.tenant import get_current_tenant
            tenant = get_current_tenant()
            if tenant:
                self.tenant = tenant
        except ImportError:
            pass

    def auto_fill_tenant_from_context(self):
        """
        Auto-fill tenant from user's session context if not set.

        This method is called during before_validate to ensure the tenant
        field is populated before mandatory field validation runs.
        """
        if not self.tenant:
            self.set_tenant_from_context()

    def validate_tenant(self):
        """
        Validate tenant field for organization.

        This validation ensures:
        1. Tenant is set (required for multi-tenant isolation)
        2. Tenant exists in the database
        3. Tenant is active (not suspended or inactive)

        Raises:
            frappe.ValidationError: If tenant validation fails
        """
        if not self.tenant:
            frappe.throw(
                _("Tenant is required. Please select a tenant for this organization.")
            )

        # Check if tenant exists
        if not frappe.db.exists("Tenant", self.tenant):
            frappe.throw(
                _("Selected Tenant '{0}' does not exist.").format(self.tenant)
            )

        # Check if tenant is active
        tenant_status = frappe.db.get_value("Tenant", self.tenant, "status")
        if tenant_status not in ["Active", "Pending Verification"]:
            frappe.throw(
                _("Cannot create organization under Tenant '{0}' with status '{1}'. "
                  "Tenant must be Active.").format(self.tenant, tenant_status)
            )

    def validate_tenant_change(self):
        """
        Prevent changing tenant if organization has linked seller profiles.

        This validation ensures data integrity by preventing tenant changes
        that would break the tenant isolation hierarchy. Organizations with
        linked seller profiles cannot change tenants as it would create
        cross-tenant data inconsistency.

        Raises:
            frappe.ValidationError: If attempting to change tenant with linked sellers
        """
        if self.is_new():
            return

        # Check if tenant has changed
        original_tenant = getattr(self, "_original_tenant", None)
        if not original_tenant or original_tenant == self.tenant:
            return

        # Check for linked seller profiles
        linked_sellers = frappe.db.count("Seller Profile", {"organization": self.name})
        if linked_sellers > 0:
            frappe.throw(
                _("Cannot change Tenant for Organization with {0} linked Seller Profile(s). "
                  "Please reassign or delete the linked Seller Profiles first.").format(linked_sellers)
            )

        # Check for linked marketplace orders
        linked_orders = frappe.db.count("Marketplace Order", {"buyer_organization": self.name})
        if linked_orders > 0:
            frappe.throw(
                _("Cannot change Tenant for Organization with {0} linked Order(s). "
                  "Please complete or cancel the orders first.").format(linked_orders)
            )

    def validate_tax_id(self):
        """
        Validate Turkish Tax ID (VKN) format.
        VKN is 10 digits for companies.
        """
        if self.tax_id:
            tax_id = self.tax_id.strip()
            if not tax_id.isdigit():
                frappe.throw(_("Tax ID (VKN) must contain only digits"))
            if len(tax_id) != 10:
                frappe.throw(_("Tax ID (VKN) must be exactly 10 digits for companies"))

            # Validate VKN checksum (Turkish algorithm)
            if not self.validate_vkn_checksum(tax_id):
                frappe.throw(_("Invalid Tax ID (VKN). Checksum validation failed."))

    def validate_vkn_checksum(self, vkn):
        """
        Validate Turkish VKN (Vergi Kimlik Numarasi) checksum.
        Algorithm: Each digit is processed with specific rules.
        """
        if len(vkn) != 10:
            return False

        try:
            digits = [int(d) for d in vkn]
            total = 0

            for i in range(9):
                tmp = (digits[i] + (9 - i)) % 10
                tmp = (tmp * (2 ** (9 - i))) % 9
                if tmp == 0 and digits[i] != 0:
                    tmp = 9
                total += tmp

            check_digit = (10 - (total % 10)) % 10
            return check_digit == digits[9]
        except (ValueError, IndexError):
            return False

    def validate_mersis_number(self):
        """Validate MERSIS number format (16 digits)."""
        if self.mersis_number:
            mersis = self.mersis_number.strip()
            if not mersis.isdigit():
                frappe.throw(_("MERSIS Number must contain only digits"))
            if len(mersis) != 16:
                frappe.throw(_("MERSIS Number must be exactly 16 digits"))

    def validate_trade_registry(self):
        """Basic validation for trade registry number."""
        if self.trade_registry_number:
            # Trade registry numbers can vary by city, basic format check
            registry = self.trade_registry_number.strip()
            if len(registry) < 4:
                frappe.throw(_("Trade Registry Number seems too short"))

    def validate_e_invoice_alias(self):
        """Validate E-Invoice alias format."""
        if self.e_invoice_registered and self.e_invoice_alias:
            alias = self.e_invoice_alias.strip().upper()
            # E-Invoice aliases start with PK (Portal Kullanicisi) or GB (GIB)
            if not (alias.startswith("PK:") or alias.startswith("GB:")):
                frappe.throw(_("E-Invoice Alias must start with 'PK:' or 'GB:'"))
            self.e_invoice_alias = alias

    def validate_founded_year(self):
        """Validate founded year is reasonable."""
        if self.founded_year:
            current_year = getdate(nowdate()).year
            if self.founded_year < 1800 or self.founded_year > current_year:
                frappe.throw(_("Founded year must be between 1800 and {0}").format(current_year))

    def validate_members(self):
        """Validate organization members."""
        if self.organization_members:
            users = []
            primary_contacts = 0
            admins = 0

            for member in self.organization_members:
                # Check for duplicate users
                if member.user in users:
                    frappe.throw(_("User {0} is added multiple times").format(member.user))
                users.append(member.user)

                # Count primary contacts
                if member.is_primary_contact:
                    primary_contacts += 1

                # Count admins
                if member.is_admin:
                    admins += 1

            # Warn if no primary contact
            if len(self.organization_members) > 0 and primary_contacts == 0:
                frappe.msgprint(_("No primary contact designated for this organization"))

            # Ensure at least one admin for non-empty member list
            if len(self.organization_members) > 0 and admins == 0:
                frappe.msgprint(_("Consider designating at least one admin for this organization"))

    def create_erpnext_customer(self):
        """Create linked ERPNext Customer record."""
        if frappe.db.exists("Customer", {"tax_id": self.tax_id}):
            # Link to existing customer with same tax ID
            existing = frappe.db.get_value("Customer", {"tax_id": self.tax_id}, "name")
            self.db_set("erpnext_customer", existing)
            return

        customer_data = {
            "doctype": "Customer",
            "customer_name": self.organization_name,
            "customer_type": "Company",
            "customer_group": "Commercial",
            "territory": "Turkey",
            "tax_id": self.tax_id,
            "default_currency": "TRY"
        }

        try:
            customer = frappe.get_doc(customer_data)
            customer.flags.ignore_permissions = True
            customer.insert()
            self.db_set("erpnext_customer", customer.name)
            frappe.msgprint(_("ERPNext Customer {0} created").format(customer.name))
        except Exception as e:
            frappe.log_error(f"Failed to create ERPNext Customer for Organization {self.name}: {str(e)}")

    def sync_to_erpnext_customer(self):
        """Sync organization data to linked ERPNext Customer."""
        if not self.erpnext_customer:
            return

        try:
            customer = frappe.get_doc("Customer", self.erpnext_customer)

            # Update customer fields
            customer.customer_name = self.organization_name
            customer.tax_id = self.tax_id

            # Sync credit limit if set
            if flt(self.credit_limit) > 0:
                customer.credit_limit = self.credit_limit

            customer.flags.ignore_permissions = True
            customer.save()
        except frappe.DoesNotExistError:
            # Customer was deleted, clear the link
            self.db_set("erpnext_customer", None)
        except Exception as e:
            frappe.log_error(f"Failed to sync ERPNext Customer for Organization {self.name}: {str(e)}")

    def check_linked_documents(self):
        """Check for linked documents before allowing deletion."""
        # Check for linked seller profiles
        if frappe.db.exists("Seller Profile", {"organization": self.name}):
            frappe.throw(
                _("Cannot delete Organization with active Seller Profiles. "
                  "Please delete linked Seller Profiles first.")
            )

        # Check for linked marketplace orders
        if frappe.db.exists("Marketplace Order", {"buyer_organization": self.name}):
            frappe.throw(
                _("Cannot delete Organization with existing orders. "
                  "Please cancel or complete all orders first.")
            )

    def clear_organization_cache(self):
        """Clear cached organization data."""
        cache_key = f"organization:{self.name}"
        frappe.cache().delete_value(cache_key)

    def create_user_permission_for_tenant(self):
        """
        Create User Permission for organization creator to enable tenant data isolation.

        This ensures that the user who created the organization can only access data
        belonging to this tenant by creating a User Permission linking the user
        to the tenant. This is essential for multi-tenant data isolation.
        """
        if not self.created_by or not self.tenant:
            return

        if self.created_by == "Administrator":
            return

        # Check if User Permission already exists
        if frappe.db.exists("User Permission", {
            "user": self.created_by,
            "allow": "Tenant",
            "for_value": self.tenant
        }):
            return

        try:
            user_permission = frappe.get_doc({
                "doctype": "User Permission",
                "user": self.created_by,
                "allow": "Tenant",
                "for_value": self.tenant,
                "apply_to_all_doctypes": 1,
                "is_default": 1
            })
            user_permission.insert(ignore_permissions=True)
        except Exception as e:
            frappe.log_error(
                message=str(e),
                title=_("Failed to create User Permission for Organization {0}").format(self.name)
            )

    # Verification Methods
    def mark_verified(self, verified_by=None):
        """Mark organization as verified after KYB review."""
        self.verification_status = "Verified"
        self.verified_at = now_datetime()
        self.verified_by = verified_by or frappe.session.user
        self.status = "Active"
        self.is_approved_buyer = 1
        self.save()

    def mark_rejected(self, reason=None):
        """Mark organization verification as rejected."""
        self.verification_status = "Rejected"
        if reason:
            self.kyb_notes = f"Rejected: {reason}\n\n{self.kyb_notes or ''}"
        self.save()

    def request_documents(self, note=None):
        """Request additional documents for verification."""
        self.verification_status = "Documents Requested"
        if note:
            self.kyb_notes = f"Documents requested: {note}\n\n{self.kyb_notes or ''}"
        self.save()

    # Member Management Methods
    def add_member(self, user, role="Member", is_admin=False, is_primary=False):
        """Add a member to the organization."""
        # Check if user already exists
        for member in self.organization_members:
            if member.user == user:
                frappe.throw(_("User {0} is already a member of this organization").format(user))

        self.append("organization_members", {
            "user": user,
            "role": role,
            "is_admin": is_admin,
            "is_primary_contact": is_primary,
            "added_on": nowdate()
        })
        self.save()

    def remove_member(self, user):
        """Remove a member from the organization."""
        members_to_keep = []
        found = False

        for member in self.organization_members:
            if member.user != user:
                members_to_keep.append(member)
            else:
                found = True

        if not found:
            frappe.throw(_("User {0} is not a member of this organization").format(user))

        self.organization_members = members_to_keep
        self.save()

    def get_members(self, role=None):
        """Get organization members, optionally filtered by role."""
        members = []
        for member in self.organization_members:
            if role is None or member.role == role:
                members.append({
                    "user": member.user,
                    "full_name": member.full_name,
                    "role": member.role,
                    "is_admin": member.is_admin,
                    "is_primary_contact": member.is_primary_contact,
                    "email": member.email
                })
        return members

    def get_admins(self):
        """Get all admin members of the organization."""
        return [m for m in self.organization_members if m.is_admin]

    def is_member(self, user):
        """Check if user is a member of this organization."""
        for member in self.organization_members:
            if member.user == user:
                return True
        return False

    def get_member_role(self, user):
        """Get the role of a specific member."""
        for member in self.organization_members:
            if member.user == user:
                return member.role
        return None

    # Status and Permission Checks
    def is_active(self):
        """Check if organization is active."""
        return self.status == "Active"

    def is_verified(self):
        """Check if organization is verified."""
        return self.verification_status == "Verified"

    def can_buy(self):
        """Check if organization can make purchases."""
        return self.is_active() and self.is_approved_buyer

    def can_sell(self):
        """Check if organization can sell on the marketplace."""
        return self.is_active() and self.is_approved_seller and self.is_verified()

    def can_use_credit(self):
        """Check if organization can use credit for purchases."""
        return (self.is_active() and
                self.is_verified() and
                flt(self.credit_limit) > 0 and
                cint(self.can_use_credit))

    def get_available_credit(self):
        """Get available credit for the organization."""
        if not self.can_use_credit():
            return 0

        # Calculate used credit from pending orders
        used_credit = frappe.db.sql("""
            SELECT COALESCE(SUM(grand_total), 0)
            FROM `tabMarketplace Order`
            WHERE buyer_organization = %s
            AND payment_status = 'Credit'
            AND status NOT IN ('Cancelled', 'Completed', 'Refunded')
        """, self.name)[0][0] or 0

        return max(0, flt(self.credit_limit) - flt(used_credit))

    # Tenant-Related Methods
    def get_tenant(self):
        """
        Get the tenant document for this organization.

        Returns:
            Document: The Tenant document or None if not set
        """
        if not self.tenant:
            return None
        return frappe.get_doc("Tenant", self.tenant)

    def get_seller_count(self):
        """
        Get count of seller profiles linked to this organization.

        Returns:
            int: Number of linked seller profiles
        """
        return frappe.db.count("Seller Profile", {"organization": self.name})

    def is_tenant_active(self):
        """
        Check if the organization's tenant is active.

        Returns:
            bool: True if tenant exists and is active
        """
        if not self.tenant:
            return False

        tenant = self.get_tenant()
        if not tenant:
            return False

        return tenant.is_active() if hasattr(tenant, "is_active") else tenant.status == "Active"

    def get_tenant_name(self):
        """
        Get the display name of the organization's tenant.

        Returns:
            str: Tenant name or None
        """
        if not self.tenant:
            return None
        return frappe.db.get_value("Tenant", self.tenant, "tenant_name")


# API Endpoints
@frappe.whitelist()
def get_organization_details(organization_name):
    """
    Get detailed information about an organization.

    Args:
        organization_name: Name of the organization

    Returns:
        dict: Organization details
    """
    if not frappe.has_permission("Organization", "read"):
        frappe.throw(_("Not permitted to view organization details"))

    org = frappe.get_doc("Organization", organization_name)

    return {
        "name": org.name,
        "organization_name": org.organization_name,
        "organization_type": org.organization_type,
        "status": org.status,
        "verification_status": org.verification_status,
        "tax_id": org.tax_id,
        "city": org.city,
        "country": org.country,
        "is_active": org.is_active(),
        "is_verified": org.is_verified(),
        "can_buy": org.can_buy(),
        "can_sell": org.can_sell(),
        "member_count": len(org.organization_members or []),
        "e_invoice_registered": org.e_invoice_registered
    }


@frappe.whitelist()
def verify_organization(organization_name):
    """
    Verify an organization after KYB review.

    Args:
        organization_name: Name of the organization

    Returns:
        dict: Updated organization status
    """
    if not frappe.has_permission("Organization", "write"):
        frappe.throw(_("Not permitted to verify organizations"))

    org = frappe.get_doc("Organization", organization_name)
    org.mark_verified()

    return {
        "status": "success",
        "message": _("Organization verified successfully"),
        "verification_status": org.verification_status
    }


@frappe.whitelist()
def reject_organization(organization_name, reason=None):
    """
    Reject an organization verification.

    Args:
        organization_name: Name of the organization
        reason: Reason for rejection

    Returns:
        dict: Updated organization status
    """
    if not frappe.has_permission("Organization", "write"):
        frappe.throw(_("Not permitted to reject organizations"))

    org = frappe.get_doc("Organization", organization_name)
    org.mark_rejected(reason)

    return {
        "status": "success",
        "message": _("Organization verification rejected"),
        "verification_status": org.verification_status
    }


@frappe.whitelist()
def add_organization_member(organization_name, user, role="Member", is_admin=0):
    """
    Add a member to an organization.

    Args:
        organization_name: Name of the organization
        user: User to add
        role: Role for the member
        is_admin: Whether the member is an admin

    Returns:
        dict: Result of operation
    """
    if not frappe.has_permission("Organization", "write"):
        frappe.throw(_("Not permitted to manage organization members"))

    org = frappe.get_doc("Organization", organization_name)
    org.add_member(user, role, cint(is_admin))

    return {
        "status": "success",
        "message": _("Member added successfully"),
        "member_count": len(org.organization_members)
    }


@frappe.whitelist()
def remove_organization_member(organization_name, user):
    """
    Remove a member from an organization.

    Args:
        organization_name: Name of the organization
        user: User to remove

    Returns:
        dict: Result of operation
    """
    if not frappe.has_permission("Organization", "write"):
        frappe.throw(_("Not permitted to manage organization members"))

    org = frappe.get_doc("Organization", organization_name)
    org.remove_member(user)

    return {
        "status": "success",
        "message": _("Member removed successfully"),
        "member_count": len(org.organization_members)
    }


@frappe.whitelist()
def get_user_organizations(user=None):
    """
    Get all organizations a user belongs to.

    Args:
        user: User to check (defaults to current user)

    Returns:
        list: Organizations the user belongs to
    """
    user = user or frappe.session.user

    organizations = frappe.db.sql("""
        SELECT
            o.name,
            o.organization_name,
            o.organization_type,
            o.status,
            om.role,
            om.is_admin
        FROM `tabOrganization` o
        INNER JOIN `tabOrganization Member` om ON om.parent = o.name
        WHERE om.user = %s
        ORDER BY o.organization_name
    """, user, as_dict=True)

    return organizations


@frappe.whitelist()
def check_e_invoice_status(tax_id):
    """
    Check E-Invoice registration status for a given tax ID.
    This is a placeholder for actual GIB integration.

    Args:
        tax_id: Tax ID (VKN) to check

    Returns:
        dict: E-Invoice registration status
    """
    # TODO: Integrate with GIB (Turkish Revenue Administration) API
    # For now, return a placeholder response
    return {
        "tax_id": tax_id,
        "e_invoice_registered": False,
        "e_archive_enabled": False,
        "alias": None,
        "message": _("E-Invoice status check requires GIB integration")
    }

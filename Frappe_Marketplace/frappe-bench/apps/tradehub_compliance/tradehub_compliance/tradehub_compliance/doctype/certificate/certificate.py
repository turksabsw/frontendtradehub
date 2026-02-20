# Copyright (c) 2026, Trade Hub and contributors
# For license information, please see license.txt

"""
Certificate DocType for Trade Hub B2B Marketplace.

This module implements the Certificate DocType that manages product and seller
certificates with expiry tracking and verification workflow. Certificates can
be linked to SKU Products (product certificates) or Seller Profiles (seller
certificates) based on the certificate type's applicability.

Key Features:
- Expiry tracking with automatic status updates
- Verification workflow (Pending -> Under Review -> Verified/Rejected -> Active)
- Multi-tenant isolation via product or seller
- Renewal tracking and history
- Certificate document management
- Automatic renewal reminder support
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import (
    cint,
    flt,
    getdate,
    nowdate,
    date_diff,
    add_months,
    get_datetime,
)


class Certificate(Document):
    """
    Certificate DocType managing product and seller certifications.

    Certificates represent compliance documents such as CE, ISO, GOTS, OEKO-TEX
    that can be attached to products or sellers. They include expiry tracking,
    verification workflow, and renewal management.
    """

    def before_insert(self):
        """Set default values before inserting a new certificate."""
        self.set_tenant_from_ownership()
        self.set_default_expiry_date()
        self.extract_document_filename()

    def validate(self):
        """Validate certificate data before saving."""
        self.validate_ownership()
        self.validate_tenant_isolation()
        self.validate_dates()
        self.validate_status_transition()
        self.calculate_expiry_info()
        self.extract_document_filename()

    def on_update(self):
        """Actions after certificate is updated."""
        self.update_certificate_type_count()
        self.clear_certificate_cache()

    def on_trash(self):
        """Actions before certificate is deleted."""
        self.validate_deletion()
        self.update_certificate_type_count()

    # =========================================================================
    # INITIALIZATION METHODS
    # =========================================================================

    def set_tenant_from_ownership(self):
        """Set tenant from the linked product or seller."""
        if self.tenant:
            return

        if self.sku_product:
            tenant = frappe.db.get_value("SKU Product", self.sku_product, "tenant")
            if tenant:
                self.tenant = tenant
                self.tenant_name = frappe.db.get_value(
                    "Tenant", tenant, "tenant_name"
                )
        elif self.seller:
            tenant = frappe.db.get_value("Seller Profile", self.seller, "tenant")
            if tenant:
                self.tenant = tenant
                self.tenant_name = frappe.db.get_value(
                    "Tenant", tenant, "tenant_name"
                )

    def set_default_expiry_date(self):
        """Set default expiry date based on certificate type validity."""
        if self.expiry_date or not self.issue_date:
            return

        # Get validity from certificate type
        validity_months = self.default_validity_months or 0
        if not validity_months and self.certificate_type:
            validity_months = frappe.db.get_value(
                "Certificate Type",
                self.certificate_type,
                "default_validity_months"
            ) or 0

        if validity_months > 0:
            self.expiry_date = add_months(getdate(self.issue_date), validity_months)

    def extract_document_filename(self):
        """Extract filename from the uploaded certificate document."""
        if self.certificate_document and not self.document_filename:
            # Extract filename from the file path/URL
            filename = self.certificate_document.split("/")[-1]
            self.document_filename = filename

    # =========================================================================
    # VALIDATION METHODS
    # =========================================================================

    def validate_ownership(self):
        """Validate that certificate has valid ownership (product or seller)."""
        applicable_to = self.applicable_to

        if not applicable_to and self.certificate_type:
            applicable_to = frappe.db.get_value(
                "Certificate Type",
                self.certificate_type,
                "applicable_to"
            )

        if applicable_to == "Product":
            if not self.sku_product:
                frappe.throw(
                    _("Product is required for product certificates")
                )
            if self.seller:
                frappe.msgprint(
                    _("Seller field will be ignored for product certificates"),
                    indicator="orange"
                )
        elif applicable_to == "Seller":
            if not self.seller:
                frappe.throw(
                    _("Seller is required for seller certificates")
                )
            if self.sku_product:
                frappe.msgprint(
                    _("Product field will be ignored for seller certificates"),
                    indicator="orange"
                )
        elif applicable_to == "Both":
            if not self.sku_product and not self.seller:
                frappe.throw(
                    _("Either Product or Seller is required for this certificate type")
                )

    def validate_tenant_isolation(self):
        """Validate multi-tenant isolation."""
        if not self.tenant:
            # Try to set tenant from ownership
            self.set_tenant_from_ownership()

        if not self.tenant:
            # Allow if user is admin
            if not frappe.has_permission("Tenant", "write"):
                frappe.throw(
                    _("Certificate must be associated with a tenant")
                )
            return

        # Verify user has access to this tenant
        from tradehub_core.tradehub_core.utils.tenant import get_current_tenant

        user_tenant = get_current_tenant()
        if user_tenant and self.tenant != user_tenant:
            if not frappe.has_permission("Tenant", "write"):
                frappe.throw(
                    _("Access denied: You cannot access certificates from another tenant")
                )

    def validate_dates(self):
        """Validate issue and expiry dates."""
        if not self.issue_date:
            frappe.throw(_("Issue Date is required"))

        issue_date = getdate(self.issue_date)

        # Issue date cannot be in the future
        if issue_date > getdate(nowdate()):
            frappe.throw(_("Issue Date cannot be in the future"))

        # Expiry date must be after issue date (if set)
        if self.expiry_date:
            expiry_date = getdate(self.expiry_date)
            if expiry_date <= issue_date:
                frappe.throw(_("Expiry Date must be after Issue Date"))

    def validate_status_transition(self):
        """Validate status transitions in the workflow."""
        if self.is_new():
            return

        old_doc = self.get_doc_before_save()
        if not old_doc:
            return

        old_status = old_doc.status
        new_status = self.status

        if old_status == new_status:
            return

        # Define valid transitions
        valid_transitions = {
            "Pending Verification": ["Under Review", "Rejected", "Suspended"],
            "Under Review": ["Verified", "Rejected", "Pending Verification"],
            "Verified": ["Active", "Suspended", "Revoked"],
            "Rejected": ["Pending Verification", "Under Review"],
            "Active": ["Expired", "Suspended", "Revoked"],
            "Expired": ["Active", "Suspended"],  # Can reactivate if renewed
            "Suspended": ["Active", "Pending Verification", "Revoked"],
            "Revoked": [],  # Terminal state
        }

        allowed = valid_transitions.get(old_status, [])
        if new_status not in allowed and not frappe.has_permission("Tenant", "write"):
            frappe.throw(
                _("Invalid status transition from {0} to {1}. Allowed: {2}").format(
                    old_status, new_status, ", ".join(allowed) if allowed else "None"
                )
            )

    # =========================================================================
    # EXPIRY CALCULATION METHODS
    # =========================================================================

    def calculate_expiry_info(self):
        """Calculate days until expiry and expiry status."""
        if not self.expiry_date:
            self.days_until_expiry = None
            self.expiry_status = "No Expiry"
            return

        expiry_date = getdate(self.expiry_date)
        today = getdate(nowdate())
        days_remaining = date_diff(expiry_date, today)

        self.days_until_expiry = days_remaining

        # Determine expiry status
        reminder_days = self.renewal_reminder_days or 30

        if days_remaining < 0:
            self.expiry_status = "Expired"
            # Auto-update status if currently Active
            if self.status == "Active":
                self.status = "Expired"
        elif days_remaining <= reminder_days:
            self.expiry_status = "Expiring Soon"
        else:
            self.expiry_status = "Valid"

    def is_expired(self):
        """
        Check if the certificate is expired.

        Returns:
            bool: True if certificate is expired
        """
        if not self.expiry_date:
            return False

        return getdate(self.expiry_date) < getdate(nowdate())

    def is_expiring_soon(self, days=None):
        """
        Check if the certificate is expiring soon.

        Args:
            days: Number of days to consider as "soon" (default: renewal_reminder_days)

        Returns:
            bool: True if certificate is expiring soon
        """
        if not self.expiry_date:
            return False

        days = days or self.renewal_reminder_days or 30
        days_until = date_diff(getdate(self.expiry_date), getdate(nowdate()))
        return 0 <= days_until <= days

    # =========================================================================
    # VERIFICATION WORKFLOW METHODS
    # =========================================================================

    def start_verification(self):
        """Start the verification process for this certificate."""
        if self.status != "Pending Verification":
            frappe.throw(
                _("Certificate must be in 'Pending Verification' status to start verification")
            )

        self.status = "Under Review"
        self.verification_status = "In Progress"
        self.save()

        return {"status": "Under Review", "message": _("Verification started")}

    def complete_verification(self, verified=True, notes=None):
        """
        Complete the verification process.

        Args:
            verified: Whether the certificate is verified as authentic
            notes: Verification notes

        Returns:
            dict: Result of the verification
        """
        if self.status != "Under Review":
            frappe.throw(
                _("Certificate must be in 'Under Review' status to complete verification")
            )

        self.verification_date = nowdate()
        self.verified_by = frappe.session.user
        self.verification_notes = notes

        if verified:
            self.status = "Verified"
            self.verification_status = "Verified"
            message = _("Certificate verified successfully")
        else:
            self.status = "Rejected"
            self.verification_status = "Failed"
            message = _("Certificate verification failed")

        self.save()

        return {"status": self.status, "message": message}

    def activate(self):
        """Activate a verified certificate."""
        if self.status != "Verified":
            frappe.throw(
                _("Certificate must be in 'Verified' status to activate")
            )

        # Check if expired
        if self.is_expired():
            frappe.throw(
                _("Cannot activate an expired certificate. Please renew first.")
            )

        self.status = "Active"
        self.save()

        return {"status": "Active", "message": _("Certificate activated")}

    def suspend(self, reason=None):
        """
        Suspend the certificate.

        Args:
            reason: Reason for suspension

        Returns:
            dict: Result of the suspension
        """
        if self.status not in ["Active", "Verified", "Pending Verification"]:
            frappe.throw(
                _("Certificate cannot be suspended from current status")
            )

        self.status = "Suspended"
        if reason:
            self.internal_notes = (self.internal_notes or "") + f"\nSuspended: {reason}"
        self.save()

        return {"status": "Suspended", "message": _("Certificate suspended")}

    def revoke(self, reason=None):
        """
        Revoke the certificate permanently.

        Args:
            reason: Reason for revocation

        Returns:
            dict: Result of the revocation
        """
        if self.status == "Revoked":
            frappe.throw(_("Certificate is already revoked"))

        self.status = "Revoked"
        if reason:
            self.internal_notes = (self.internal_notes or "") + f"\nRevoked: {reason}"
        self.save()

        return {"status": "Revoked", "message": _("Certificate revoked")}

    # =========================================================================
    # RENEWAL METHODS
    # =========================================================================

    def create_renewal(self, new_issue_date=None, new_expiry_date=None):
        """
        Create a renewal certificate based on this one.

        Args:
            new_issue_date: Issue date for the new certificate (default: today)
            new_expiry_date: Expiry date for the new certificate

        Returns:
            Document: The new certificate document
        """
        if not self.requires_renewal:
            frappe.throw(_("This certificate type does not require renewal"))

        new_cert = frappe.new_doc("Certificate")

        # Copy relevant fields
        fields_to_copy = [
            "certificate_type",
            "sku_product",
            "seller",
            "tenant",
            "certificate_number",
            "issuing_authority",
            "issuing_body",
            "certificate_scope",
            "verification_url",
        ]

        for field in fields_to_copy:
            setattr(new_cert, field, getattr(self, field, None))

        # Set dates
        new_cert.issue_date = new_issue_date or nowdate()

        if new_expiry_date:
            new_cert.expiry_date = new_expiry_date
        elif self.default_validity_months:
            new_cert.expiry_date = add_months(
                getdate(new_cert.issue_date),
                self.default_validity_months
            )

        # Set renewal links
        new_cert.previous_certificate = self.name
        new_cert.renewed_from = self.name

        # Set initial status
        new_cert.status = "Pending Verification"
        new_cert.verification_status = "Pending"

        new_cert.insert()

        # Update this certificate to point to renewal
        self.renewed_to = new_cert.name
        self.db_set("renewed_to", new_cert.name, update_modified=False)

        return new_cert

    def mark_renewal_reminder_sent(self):
        """Mark that a renewal reminder has been sent for this certificate."""
        self.db_set("renewal_reminder_sent", 1, update_modified=False)

    # =========================================================================
    # DELETION VALIDATION
    # =========================================================================

    def validate_deletion(self):
        """Validate that certificate can be deleted."""
        # Active certificates should not be deleted
        if self.status in ["Active", "Verified"]:
            frappe.throw(
                _("Cannot delete an active or verified certificate. Please revoke or suspend first.")
            )

        # Check if this certificate has been renewed
        if self.renewed_to:
            frappe.throw(
                _("Cannot delete a certificate that has been renewed. The renewal chain must be preserved.")
            )

    # =========================================================================
    # CACHE AND COUNT MANAGEMENT
    # =========================================================================

    def update_certificate_type_count(self):
        """Update the certificate count for the certificate type."""
        if self.certificate_type:
            try:
                cert_type = frappe.get_doc("Certificate Type", self.certificate_type)
                cert_type.update_certificate_count()
            except Exception:
                pass  # Ignore errors in count update

    def clear_certificate_cache(self):
        """Clear cached certificate data."""
        cache_keys = [
            f"certificate:{self.name}",
        ]

        if self.sku_product:
            cache_keys.append(f"product_certificates:{self.sku_product}")

        if self.seller:
            cache_keys.append(f"seller_certificates:{self.seller}")

        if self.tenant:
            cache_keys.append(f"tenant_certificates:{self.tenant}")

        for key in cache_keys:
            frappe.cache().delete_value(key)


# =============================================================================
# WHITELISTED API FUNCTIONS
# =============================================================================


@frappe.whitelist()
def get_certificates(
    tenant=None,
    sku_product=None,
    seller=None,
    certificate_type=None,
    status=None,
    include_expired=False,
    limit=20,
    offset=0,
):
    """
    Get list of certificates with filters.

    Args:
        tenant: Filter by tenant
        sku_product: Filter by SKU Product
        seller: Filter by Seller Profile
        certificate_type: Filter by Certificate Type
        status: Filter by status
        include_expired: Include expired certificates
        limit: Maximum number of results
        offset: Offset for pagination

    Returns:
        list: List of certificate documents
    """
    filters = {}

    if tenant:
        filters["tenant"] = tenant

    if sku_product:
        filters["sku_product"] = sku_product

    if seller:
        filters["seller"] = seller

    if certificate_type:
        filters["certificate_type"] = certificate_type

    if status:
        filters["status"] = status
    elif not include_expired:
        filters["status"] = ["not in", ["Expired", "Revoked"]]

    certificates = frappe.get_all(
        "Certificate",
        filters=filters,
        fields=[
            "name",
            "certificate_type",
            "type_name",
            "certificate_category",
            "status",
            "sku_product",
            "product_name",
            "seller",
            "seller_name",
            "certificate_number",
            "issue_date",
            "expiry_date",
            "days_until_expiry",
            "expiry_status",
            "verification_status",
        ],
        order_by="expiry_date asc",
        limit_page_length=cint(limit),
        limit_start=cint(offset),
    )

    return certificates


@frappe.whitelist()
def get_certificate(certificate_name):
    """
    Get a single certificate by name.

    Args:
        certificate_name: The certificate document name

    Returns:
        dict: Certificate data
    """
    if not frappe.db.exists("Certificate", certificate_name):
        frappe.throw(_("Certificate {0} not found").format(certificate_name))

    cert = frappe.get_doc("Certificate", certificate_name)

    return {
        "name": cert.name,
        "certificate_type": cert.certificate_type,
        "type_name": cert.type_name,
        "certificate_category": cert.certificate_category,
        "applicable_to": cert.applicable_to,
        "status": cert.status,
        "sku_product": cert.sku_product,
        "product_name": cert.product_name,
        "product_sku_code": cert.product_sku_code,
        "seller": cert.seller,
        "seller_name": cert.seller_name,
        "tenant": cert.tenant,
        "tenant_name": cert.tenant_name,
        "certificate_number": cert.certificate_number,
        "issuing_authority": cert.issuing_authority,
        "issuing_body": cert.issuing_body,
        "certificate_scope": cert.certificate_scope,
        "issue_date": cert.issue_date,
        "expiry_date": cert.expiry_date,
        "days_until_expiry": cert.days_until_expiry,
        "expiry_status": cert.expiry_status,
        "requires_renewal": cert.requires_renewal,
        "renewal_reminder_days": cert.renewal_reminder_days,
        "renewal_reminder_sent": cert.renewal_reminder_sent,
        "verification_status": cert.verification_status,
        "verification_date": cert.verification_date,
        "verified_by_name": cert.verified_by_name,
        "verification_notes": cert.verification_notes,
        "certificate_document": cert.certificate_document,
        "verification_url": cert.verification_url,
        "previous_certificate": cert.previous_certificate,
        "renewed_to": cert.renewed_to,
        "description": cert.description,
    }


@frappe.whitelist()
def get_product_certificates(sku_product, include_expired=False):
    """
    Get all certificates for a product.

    Args:
        sku_product: SKU Product name
        include_expired: Include expired certificates

    Returns:
        list: List of certificates
    """
    return get_certificates(
        sku_product=sku_product,
        include_expired=include_expired
    )


@frappe.whitelist()
def get_seller_certificates(seller, include_expired=False):
    """
    Get all certificates for a seller.

    Args:
        seller: Seller Profile name
        include_expired: Include expired certificates

    Returns:
        list: List of certificates
    """
    return get_certificates(
        seller=seller,
        include_expired=include_expired
    )


@frappe.whitelist()
def start_certificate_verification(certificate_name):
    """
    Start verification process for a certificate.

    Args:
        certificate_name: Certificate document name

    Returns:
        dict: Result of the operation
    """
    cert = frappe.get_doc("Certificate", certificate_name)
    return cert.start_verification()


@frappe.whitelist()
def complete_certificate_verification(certificate_name, verified, notes=None):
    """
    Complete verification process for a certificate.

    Args:
        certificate_name: Certificate document name
        verified: Whether verification passed (1/0 or True/False)
        notes: Verification notes

    Returns:
        dict: Result of the operation
    """
    cert = frappe.get_doc("Certificate", certificate_name)
    return cert.complete_verification(
        verified=cint(verified),
        notes=notes
    )


@frappe.whitelist()
def activate_certificate(certificate_name):
    """
    Activate a verified certificate.

    Args:
        certificate_name: Certificate document name

    Returns:
        dict: Result of the operation
    """
    cert = frappe.get_doc("Certificate", certificate_name)
    return cert.activate()


@frappe.whitelist()
def suspend_certificate(certificate_name, reason=None):
    """
    Suspend a certificate.

    Args:
        certificate_name: Certificate document name
        reason: Reason for suspension

    Returns:
        dict: Result of the operation
    """
    cert = frappe.get_doc("Certificate", certificate_name)
    return cert.suspend(reason=reason)


@frappe.whitelist()
def revoke_certificate(certificate_name, reason=None):
    """
    Revoke a certificate permanently.

    Args:
        certificate_name: Certificate document name
        reason: Reason for revocation

    Returns:
        dict: Result of the operation
    """
    cert = frappe.get_doc("Certificate", certificate_name)
    return cert.revoke(reason=reason)


@frappe.whitelist()
def renew_certificate(certificate_name, new_issue_date=None, new_expiry_date=None):
    """
    Create a renewal for a certificate.

    Args:
        certificate_name: Certificate document name
        new_issue_date: Issue date for the new certificate
        new_expiry_date: Expiry date for the new certificate

    Returns:
        dict: New certificate data
    """
    cert = frappe.get_doc("Certificate", certificate_name)
    new_cert = cert.create_renewal(
        new_issue_date=new_issue_date,
        new_expiry_date=new_expiry_date
    )

    return {
        "name": new_cert.name,
        "message": _("Renewal certificate created: {0}").format(new_cert.name),
    }


@frappe.whitelist()
def get_expiring_certificates(days=30, tenant=None):
    """
    Get certificates expiring within specified days.

    Args:
        days: Number of days to look ahead
        tenant: Filter by tenant

    Returns:
        list: List of expiring certificates
    """
    from frappe.utils import add_days

    filters = {
        "status": "Active",
        "expiry_date": ["between", [nowdate(), add_days(nowdate(), cint(days))]],
    }

    if tenant:
        filters["tenant"] = tenant

    certificates = frappe.get_all(
        "Certificate",
        filters=filters,
        fields=[
            "name",
            "certificate_type",
            "type_name",
            "sku_product",
            "product_name",
            "seller",
            "seller_name",
            "certificate_number",
            "expiry_date",
            "days_until_expiry",
            "renewal_reminder_sent",
        ],
        order_by="expiry_date asc",
    )

    return certificates


@frappe.whitelist()
def get_expired_certificates(tenant=None, limit=50):
    """
    Get expired certificates.

    Args:
        tenant: Filter by tenant
        limit: Maximum number of results

    Returns:
        list: List of expired certificates
    """
    filters = {
        "status": "Active",
        "expiry_date": ["<", nowdate()],
    }

    if tenant:
        filters["tenant"] = tenant

    certificates = frappe.get_all(
        "Certificate",
        filters=filters,
        fields=[
            "name",
            "certificate_type",
            "type_name",
            "sku_product",
            "product_name",
            "seller",
            "seller_name",
            "certificate_number",
            "expiry_date",
            "days_until_expiry",
        ],
        order_by="expiry_date desc",
        limit_page_length=cint(limit),
    )

    return certificates


@frappe.whitelist()
def check_certificate_compliance(sku_product=None, seller=None):
    """
    Check certificate compliance for a product or seller.

    Args:
        sku_product: SKU Product name
        seller: Seller Profile name

    Returns:
        dict: Compliance status with missing mandatory certificates
    """
    if not sku_product and not seller:
        frappe.throw(_("Either sku_product or seller is required"))

    # Get tenant from product or seller
    tenant = None
    if sku_product:
        tenant = frappe.db.get_value("SKU Product", sku_product, "tenant")
        applicable_to = "Product"
    else:
        tenant = frappe.db.get_value("Seller Profile", seller, "tenant")
        applicable_to = "Seller"

    # Get mandatory certificate types
    from tradehub_compliance.tradehub_compliance.doctype.certificate_type.certificate_type import (
        get_mandatory_certificate_types,
    )

    mandatory_types = get_mandatory_certificate_types(
        applicable_to=applicable_to,
        tenant=tenant
    )

    # Get existing active certificates
    filters = {"status": "Active"}
    if sku_product:
        filters["sku_product"] = sku_product
    else:
        filters["seller"] = seller

    existing_certs = frappe.get_all(
        "Certificate",
        filters=filters,
        fields=["certificate_type"],
    )

    existing_types = [c.certificate_type for c in existing_certs]

    # Find missing mandatory certificates
    missing = []
    for cert_type in mandatory_types:
        if cert_type.name not in existing_types:
            missing.append({
                "type_code": cert_type.name,
                "type_name": cert_type.type_name,
                "category": cert_type.certificate_category,
            })

    is_compliant = len(missing) == 0

    return {
        "is_compliant": is_compliant,
        "total_mandatory": len(mandatory_types),
        "total_existing": len(existing_certs),
        "missing_certificates": missing,
    }


@frappe.whitelist()
def get_certificate_statistics(tenant=None):
    """
    Get certificate statistics for dashboard.

    Args:
        tenant: Filter by tenant

    Returns:
        dict: Certificate statistics
    """
    base_filters = {}
    if tenant:
        base_filters["tenant"] = tenant

    # Total certificates by status
    status_counts = {}
    for status in [
        "Pending Verification",
        "Under Review",
        "Verified",
        "Rejected",
        "Active",
        "Expired",
        "Suspended",
        "Revoked",
    ]:
        filters = {**base_filters, "status": status}
        status_counts[status] = frappe.db.count("Certificate", filters)

    # Expiring soon (within 30 days)
    from frappe.utils import add_days

    expiring_soon = frappe.db.count(
        "Certificate",
        {
            **base_filters,
            "status": "Active",
            "expiry_date": ["between", [nowdate(), add_days(nowdate(), 30)]],
        },
    )

    # Already expired but still marked Active
    expired_active = frappe.db.count(
        "Certificate",
        {
            **base_filters,
            "status": "Active",
            "expiry_date": ["<", nowdate()],
        },
    )

    # By category
    category_data = frappe.db.sql(
        """
        SELECT certificate_category, COUNT(*) as count
        FROM `tabCertificate`
        WHERE status = 'Active'
        {tenant_filter}
        GROUP BY certificate_category
        ORDER BY count DESC
        """.format(
            tenant_filter=f"AND tenant = '{tenant}'" if tenant else ""
        ),
        as_dict=True,
    )

    return {
        "total_active": status_counts.get("Active", 0),
        "total_pending": status_counts.get("Pending Verification", 0),
        "expiring_soon": expiring_soon,
        "expired_active": expired_active,
        "status_breakdown": status_counts,
        "by_category": category_data,
    }

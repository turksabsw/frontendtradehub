# Copyright (c) 2026, Trade Hub and contributors
# For license information, please see license.txt

"""
Certificate Type DocType for Trade Hub B2B Marketplace.

This module implements the Certificate Type DocType that defines different
certificate standards such as CE, ISO 9001, GOTS, OEKO-TEX, etc. Certificate
types can be global or tenant-specific and define the characteristics and
requirements for each certification.

Key Features:
- Support for various certificate categories (Compliance, Quality, Environmental, etc.)
- Applicability to Products, Sellers, or Both
- Validity and renewal settings
- Multi-tenant support (certificate types can be global or tenant-specific)
- Standard certificate types creation (CE, ISO 9001, GOTS, OEKO-TEX, etc.)
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint


class CertificateType(Document):
    """
    Certificate Type DocType defining certification standards.

    Certificate Types represent different certifications that can be obtained
    by sellers or assigned to products. They define the category, validity
    period, renewal requirements, and other characteristics of each certificate.
    """

    def before_insert(self):
        """Set default values before inserting a new certificate type."""
        self.set_tenant_from_user()
        self.generate_type_code()

    def validate(self):
        """Validate certificate type data before saving."""
        self.validate_type_name()
        self.validate_type_code()
        self.validate_tenant_consistency()
        self.validate_validity_settings()

    def on_update(self):
        """Actions after certificate type is updated."""
        self.clear_certificate_type_cache()

    def on_trash(self):
        """Prevent deletion of certificate type with linked certificates."""
        self.check_linked_certificates()

    # =========================================================================
    # INITIALIZATION METHODS
    # =========================================================================

    def set_tenant_from_user(self):
        """Set tenant from current user if not already set."""
        if not self.tenant and not self.is_global:
            user_tenant = frappe.db.get_value("User", frappe.session.user, "tenant")
            if user_tenant:
                self.tenant = user_tenant

    def generate_type_code(self):
        """Generate type code from type name if not provided."""
        if not self.type_code and self.type_name:
            # Convert to uppercase and replace special characters
            code = self.type_name.upper()
            code = code.replace(" ", "-")
            # Remove special characters except hyphens
            code = "".join(c for c in code if c.isalnum() or c == "-")
            # Remove consecutive hyphens
            while "--" in code:
                code = code.replace("--", "-")
            code = code.strip("-")

            # Ensure uniqueness
            base_code = code
            counter = 1
            while frappe.db.exists("Certificate Type", {"type_code": code}):
                code = f"{base_code}-{counter}"
                counter += 1

            self.type_code = code

    # =========================================================================
    # VALIDATION METHODS
    # =========================================================================

    def validate_type_name(self):
        """Validate certificate type name."""
        if not self.type_name:
            frappe.throw(_("Certificate Type Name is required"))

        # Check for invalid characters
        if any(char in self.type_name for char in ["<", ">", '"', "\\"]):
            frappe.throw(_("Certificate Type Name contains invalid characters"))

        # Check length
        if len(self.type_name) > 140:
            frappe.throw(_("Certificate Type Name cannot exceed 140 characters"))

        # Trim whitespace
        self.type_name = self.type_name.strip()

    def validate_type_code(self):
        """Validate certificate type code."""
        if not self.type_code:
            frappe.throw(_("Type Code is required"))

        # Ensure uppercase
        self.type_code = self.type_code.upper()

        # Check for valid characters (alphanumeric and hyphens only)
        if not all(c.isalnum() or c == "-" for c in self.type_code):
            frappe.throw(
                _("Type Code can only contain letters, numbers, and hyphens")
            )

    def validate_tenant_consistency(self):
        """Ensure tenant consistency for certificate types."""
        # Global certificate types should not have tenant
        if self.is_global and self.tenant:
            self.tenant = None
            self.tenant_name = None

        # Non-global certificate types need tenant
        if not self.is_global and not self.tenant:
            # Only admin can create global certificate types
            if not frappe.has_permission("Tenant", "write"):
                frappe.throw(
                    _("Please select a tenant or mark the certificate type as global")
                )

    def validate_validity_settings(self):
        """Validate validity and renewal settings."""
        if self.default_validity_months and self.default_validity_months < 0:
            frappe.throw(_("Default Validity cannot be negative"))

        if self.renewal_reminder_days and self.renewal_reminder_days < 0:
            frappe.throw(_("Renewal Reminder Days cannot be negative"))

        # If requires renewal, should have validity period
        if self.requires_renewal and not self.default_validity_months:
            frappe.msgprint(
                _("Certificate type requires renewal but no default validity is set"),
                indicator="orange",
            )

    # =========================================================================
    # LINKED DOCUMENT CHECKS
    # =========================================================================

    def check_linked_certificates(self):
        """Check for linked certificates before allowing deletion."""
        # Check Product Certificates
        product_cert_count = frappe.db.count(
            "Product Certificate", {"certificate_type": self.name}
        )

        # Check Seller Certificates
        seller_cert_count = frappe.db.count(
            "Seller Certificate", {"certificate_type": self.name}
        )

        total_count = product_cert_count + seller_cert_count

        if total_count > 0:
            frappe.throw(
                _(
                    "Cannot delete certificate type with {0} linked certificate(s). "
                    "Please remove or reassign certificates first."
                ).format(total_count)
            )

    # =========================================================================
    # CERTIFICATE COUNT METHODS
    # =========================================================================

    def update_certificate_count(self):
        """Update the certificate count for this type."""
        product_count = frappe.db.count(
            "Product Certificate",
            filters={"certificate_type": self.name, "status": "Active"},
        )

        seller_count = frappe.db.count(
            "Seller Certificate",
            filters={"certificate_type": self.name, "status": "Active"},
        )

        total_count = product_count + seller_count
        self.db_set("certificate_count", total_count, update_modified=False)

    def get_active_certificate_count(self):
        """
        Get count of active certificates for this type.

        Returns:
            int: Number of active certificates
        """
        product_count = frappe.db.count(
            "Product Certificate",
            filters={"certificate_type": self.name, "status": "Active"},
        )

        seller_count = frappe.db.count(
            "Seller Certificate",
            filters={"certificate_type": self.name, "status": "Active"},
        )

        return product_count + seller_count

    # =========================================================================
    # CACHE MANAGEMENT
    # =========================================================================

    def clear_certificate_type_cache(self):
        """Clear cached certificate type data."""
        cache_keys = [
            "certificate_type_list",
            f"certificate_type:{self.name}",
        ]
        if self.tenant:
            cache_keys.append(f"certificate_type_list:{self.tenant}")

        for key in cache_keys:
            frappe.cache().delete_value(key)


# =============================================================================
# WHITELISTED API FUNCTIONS
# =============================================================================


@frappe.whitelist()
def get_certificate_type_list(
    tenant=None,
    include_disabled=False,
    applicable_to=None,
    category=None,
):
    """
    Get list of certificate types.

    Args:
        tenant: Optional tenant filter (None = global certificate types only)
        include_disabled: Include disabled certificate types
        applicable_to: Filter by applicability (Product, Seller, Both)
        category: Filter by certificate category

    Returns:
        list: List of certificate type documents
    """
    filters = {}

    if not include_disabled:
        filters["enabled"] = 1

    if applicable_to:
        if applicable_to == "Product":
            filters["applicable_to"] = ["in", ["Product", "Both"]]
        elif applicable_to == "Seller":
            filters["applicable_to"] = ["in", ["Seller", "Both"]]
        else:
            filters["applicable_to"] = applicable_to

    if category:
        filters["certificate_category"] = category

    if tenant:
        # Include tenant-specific and global certificate types
        certificate_types = frappe.get_all(
            "Certificate Type",
            or_filters=[["tenant", "=", tenant], ["is_global", "=", 1]],
            filters=filters,
            fields=[
                "name",
                "type_name",
                "type_code",
                "certificate_category",
                "applicable_to",
                "icon",
                "default_validity_months",
                "is_mandatory",
                "display_order",
                "certificate_count",
            ],
            order_by="display_order asc, type_name asc",
        )
    else:
        # Only global certificate types
        filters["is_global"] = 1
        certificate_types = frappe.get_all(
            "Certificate Type",
            filters=filters,
            fields=[
                "name",
                "type_name",
                "type_code",
                "certificate_category",
                "applicable_to",
                "icon",
                "default_validity_months",
                "is_mandatory",
                "display_order",
                "certificate_count",
            ],
            order_by="display_order asc, type_name asc",
        )

    return certificate_types


@frappe.whitelist()
def get_certificate_type(type_code):
    """
    Get certificate type by code.

    Args:
        type_code: The unique code of the certificate type

    Returns:
        dict: Certificate type data
    """
    if not frappe.db.exists("Certificate Type", type_code):
        frappe.throw(_("Certificate Type {0} not found").format(type_code))

    cert_type = frappe.get_doc("Certificate Type", type_code)

    return {
        "name": cert_type.name,
        "type_name": cert_type.type_name,
        "type_code": cert_type.type_code,
        "certificate_category": cert_type.certificate_category,
        "applicable_to": cert_type.applicable_to,
        "standards_body": cert_type.standards_body,
        "issuing_authority": cert_type.issuing_authority,
        "description": cert_type.description,
        "requirements": cert_type.requirements,
        "default_validity_months": cert_type.default_validity_months,
        "renewal_reminder_days": cert_type.renewal_reminder_days,
        "requires_physical_audit": cert_type.requires_physical_audit,
        "requires_renewal": cert_type.requires_renewal,
        "is_mandatory": cert_type.is_mandatory,
        "icon": cert_type.icon,
        "website": cert_type.website,
        "reference_standard": cert_type.reference_standard,
        "verification_url": cert_type.verification_url,
    }


@frappe.whitelist()
def get_mandatory_certificate_types(applicable_to="Product", tenant=None):
    """
    Get mandatory certificate types for a given applicability.

    Args:
        applicable_to: Product or Seller
        tenant: Optional tenant filter

    Returns:
        list: List of mandatory certificate types
    """
    filters = {
        "enabled": 1,
        "is_mandatory": 1,
    }

    if applicable_to == "Product":
        filters["applicable_to"] = ["in", ["Product", "Both"]]
    elif applicable_to == "Seller":
        filters["applicable_to"] = ["in", ["Seller", "Both"]]

    if tenant:
        cert_types = frappe.get_all(
            "Certificate Type",
            or_filters=[["tenant", "=", tenant], ["is_global", "=", 1]],
            filters=filters,
            fields=["name", "type_name", "type_code", "certificate_category"],
            order_by="display_order asc",
        )
    else:
        filters["is_global"] = 1
        cert_types = frappe.get_all(
            "Certificate Type",
            filters=filters,
            fields=["name", "type_name", "type_code", "certificate_category"],
            order_by="display_order asc",
        )

    return cert_types


@frappe.whitelist()
def create_standard_certificate_types():
    """
    Create standard certificate types commonly used in B2B trade.

    This creates predefined certificate types for:
    - CE (Conformite Europeenne)
    - ISO 9001 (Quality Management)
    - ISO 14001 (Environmental Management)
    - GOTS (Global Organic Textile Standard)
    - OEKO-TEX Standard 100
    - FSC (Forest Stewardship Council)
    - BSCI (Business Social Compliance Initiative)
    - GRS (Global Recycled Standard)

    Returns:
        dict: Summary of created certificate types
    """
    # Check permission
    if not frappe.has_permission("Certificate Type", "create"):
        frappe.throw(_("Insufficient permissions to create certificate types"))

    standard_types = [
        {
            "type_name": "CE Marking",
            "type_code": "CE",
            "certificate_category": "Compliance",
            "applicable_to": "Product",
            "standards_body": "European Commission",
            "issuing_authority": "Notified Bodies (EU)",
            "description": "The CE marking indicates that a product has been assessed by the manufacturer and deemed to meet EU safety, health, and environmental protection requirements.",
            "requirements": "Products must meet applicable EU directives and harmonized standards. Technical documentation and Declaration of Conformity required.",
            "default_validity_months": 0,
            "requires_renewal": 0,
            "requires_physical_audit": 0,
            "is_mandatory": 1,
            "is_global": 1,
            "website": "https://ec.europa.eu/growth/single-market/ce-marking_en",
            "reference_standard": "EU Directives",
            "display_order": 1,
        },
        {
            "type_name": "ISO 9001 Quality Management",
            "type_code": "ISO-9001",
            "certificate_category": "Quality",
            "applicable_to": "Seller",
            "standards_body": "International Organization for Standardization (ISO)",
            "issuing_authority": "Accredited Certification Bodies",
            "description": "ISO 9001 is the international standard for quality management systems (QMS). It helps organizations ensure they meet customer and regulatory requirements.",
            "requirements": "Implementation of a quality management system meeting ISO 9001:2015 requirements. Requires third-party certification audit.",
            "default_validity_months": 36,
            "requires_renewal": 1,
            "requires_physical_audit": 1,
            "renewal_reminder_days": 90,
            "is_mandatory": 0,
            "is_global": 1,
            "website": "https://www.iso.org/iso-9001-quality-management.html",
            "reference_standard": "ISO 9001:2015",
            "display_order": 2,
        },
        {
            "type_name": "ISO 14001 Environmental Management",
            "type_code": "ISO-14001",
            "certificate_category": "Environmental",
            "applicable_to": "Seller",
            "standards_body": "International Organization for Standardization (ISO)",
            "issuing_authority": "Accredited Certification Bodies",
            "description": "ISO 14001 is the international standard for environmental management systems (EMS). It helps organizations minimize their environmental impact.",
            "requirements": "Implementation of an environmental management system meeting ISO 14001:2015 requirements. Requires third-party certification audit.",
            "default_validity_months": 36,
            "requires_renewal": 1,
            "requires_physical_audit": 1,
            "renewal_reminder_days": 90,
            "is_mandatory": 0,
            "is_global": 1,
            "website": "https://www.iso.org/iso-14001-environmental-management.html",
            "reference_standard": "ISO 14001:2015",
            "display_order": 3,
        },
        {
            "type_name": "GOTS - Global Organic Textile Standard",
            "type_code": "GOTS",
            "certificate_category": "Organic",
            "applicable_to": "Both",
            "standards_body": "Global Standard gGmbH",
            "issuing_authority": "GOTS Approved Certification Bodies",
            "description": "GOTS is the worldwide leading textile processing standard for organic fibres, including ecological and social criteria, backed up by independent certification.",
            "requirements": "Products must contain minimum 70% certified organic natural fibres. Full supply chain certification required. Social criteria compliance mandatory.",
            "default_validity_months": 12,
            "requires_renewal": 1,
            "requires_physical_audit": 1,
            "renewal_reminder_days": 60,
            "is_mandatory": 0,
            "is_global": 1,
            "website": "https://global-standard.org/",
            "reference_standard": "GOTS 6.0",
            "display_order": 4,
        },
        {
            "type_name": "OEKO-TEX Standard 100",
            "type_code": "OEKO-TEX-100",
            "certificate_category": "Safety",
            "applicable_to": "Product",
            "standards_body": "OEKO-TEX Association",
            "issuing_authority": "OEKO-TEX Member Institutes",
            "description": "OEKO-TEX Standard 100 is an independent testing and certification system for textile products at all stages of production, testing for harmful substances.",
            "requirements": "Products must be tested and certified free from harmful substances according to the OEKO-TEX criteria catalog. Laboratory testing required.",
            "default_validity_months": 12,
            "requires_renewal": 1,
            "requires_physical_audit": 0,
            "renewal_reminder_days": 60,
            "is_mandatory": 0,
            "is_global": 1,
            "website": "https://www.oeko-tex.com/en/our-standards/standard-100-by-oeko-tex",
            "reference_standard": "OEKO-TEX Standard 100",
            "display_order": 5,
        },
        {
            "type_name": "FSC - Forest Stewardship Council",
            "type_code": "FSC",
            "certificate_category": "Sustainability",
            "applicable_to": "Both",
            "standards_body": "Forest Stewardship Council",
            "issuing_authority": "FSC Accredited Certification Bodies",
            "description": "FSC certification ensures that products come from responsibly managed forests that provide environmental, social, and economic benefits.",
            "requirements": "Chain of custody certification required. Forest management or recycled content verification. Annual surveillance audits.",
            "default_validity_months": 60,
            "requires_renewal": 1,
            "requires_physical_audit": 1,
            "renewal_reminder_days": 90,
            "is_mandatory": 0,
            "is_global": 1,
            "website": "https://fsc.org/",
            "reference_standard": "FSC-STD-40-004",
            "display_order": 6,
        },
        {
            "type_name": "BSCI - Business Social Compliance Initiative",
            "type_code": "BSCI",
            "certificate_category": "Social",
            "applicable_to": "Seller",
            "standards_body": "amfori",
            "issuing_authority": "amfori BSCI Approved Auditing Companies",
            "description": "BSCI is a leading supply chain management system that supports companies to drive social compliance in their global supply chains.",
            "requirements": "Compliance with BSCI Code of Conduct covering workers rights, health and safety, environment, and business ethics. Third-party audit required.",
            "default_validity_months": 24,
            "requires_renewal": 1,
            "requires_physical_audit": 1,
            "renewal_reminder_days": 60,
            "is_mandatory": 0,
            "is_global": 1,
            "website": "https://www.amfori.org/content/amfori-bsci",
            "reference_standard": "amfori BSCI Code of Conduct",
            "display_order": 7,
        },
        {
            "type_name": "GRS - Global Recycled Standard",
            "type_code": "GRS",
            "certificate_category": "Sustainability",
            "applicable_to": "Both",
            "standards_body": "Textile Exchange",
            "issuing_authority": "Textile Exchange Approved Certification Bodies",
            "description": "GRS is an international, voluntary, full product standard that sets requirements for third-party certification of recycled content, chain of custody, social and environmental practices.",
            "requirements": "Products must contain minimum 20% recycled material. Full chain of custody certification. Social and environmental criteria compliance.",
            "default_validity_months": 12,
            "requires_renewal": 1,
            "requires_physical_audit": 1,
            "renewal_reminder_days": 60,
            "is_mandatory": 0,
            "is_global": 1,
            "website": "https://textileexchange.org/standards/recycled-claim-standard-global-recycled-standard/",
            "reference_standard": "GRS 4.0",
            "display_order": 8,
        },
    ]

    created = []
    skipped = []

    for cert_type_data in standard_types:
        if frappe.db.exists("Certificate Type", cert_type_data["type_code"]):
            skipped.append(cert_type_data["type_code"])
            continue

        cert_type = frappe.new_doc("Certificate Type")
        for field, value in cert_type_data.items():
            setattr(cert_type, field, value)

        cert_type.insert(ignore_permissions=True)
        created.append(cert_type.type_code)

    frappe.db.commit()

    return {
        "created": created,
        "skipped": skipped,
        "message": _("Created {0} certificate types, {1} already existed").format(
            len(created), len(skipped)
        ),
    }


@frappe.whitelist()
def update_certificate_counts():
    """
    Update certificate counts for all certificate types.
    Intended to be called via scheduler or manually.

    Returns:
        dict: Number of certificate types updated
    """
    cert_types = frappe.get_all("Certificate Type", fields=["name"])
    updated = 0

    for cert_type_data in cert_types:
        cert_type = frappe.get_doc("Certificate Type", cert_type_data.name)
        old_count = cert_type.certificate_count or 0
        cert_type.update_certificate_count()
        if cert_type.certificate_count != old_count:
            updated += 1

    frappe.db.commit()

    return {"updated_count": updated, "total_certificate_types": len(cert_types)}


@frappe.whitelist()
def get_certificate_categories():
    """
    Get list of available certificate categories.

    Returns:
        list: List of certificate category options
    """
    return [
        {"value": "Compliance", "label": _("Compliance")},
        {"value": "Quality", "label": _("Quality")},
        {"value": "Environmental", "label": _("Environmental")},
        {"value": "Social", "label": _("Social")},
        {"value": "Safety", "label": _("Safety")},
        {"value": "Organic", "label": _("Organic")},
        {"value": "Sustainability", "label": _("Sustainability")},
        {"value": "Industry Specific", "label": _("Industry Specific")},
        {"value": "Other", "label": _("Other")},
    ]

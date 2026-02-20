# Copyright (c) 2026, Trade Hub and contributors
# For license information, please see license.txt

"""
SEO Meta DocType for Trade Hub B2B Marketplace.

This module implements centralized SEO metadata management for products,
categories, brands, and other content types. It provides a single source
of truth for all SEO-related metadata including meta tags, Open Graph,
Twitter Cards, robots directives, and Schema.org structured data.

Key Features:
- Centralized SEO metadata management
- Support for multiple content types (products, categories, brands)
- Open Graph and Twitter Card support
- Schema.org structured data
- Robots directives and sitemap configuration
- Multi-tenant support
"""

import json
import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt


# Supported reference DocTypes for SEO metadata
SUPPORTED_DOCTYPES = frozenset([
    "SKU Product",
    "Product Category",
    "Brand",
    "Seller Profile",
])


class SEOMeta(Document):
    """
    SEO Meta DocType for managing SEO metadata across different content types.

    Provides centralized SEO management for products, categories, and other
    content with support for meta tags, social sharing, and structured data.
    """

    def before_insert(self):
        """Set default values before inserting a new SEO Meta document."""
        self.set_reference_title()
        self.set_tenant_from_reference()

    def validate(self):
        """Validate SEO metadata before saving."""
        self.validate_reference_doctype()
        self.validate_unique_reference()
        self.validate_meta_title_length()
        self.validate_meta_description_length()
        self.validate_sitemap_priority()
        self.validate_schema_data()

        # Update computed fields
        self.set_reference_title()
        self.set_tenant_from_reference()

    def on_update(self):
        """Actions after SEO metadata is updated."""
        # Clear SEO cache for this reference
        self.clear_seo_cache()

    def on_trash(self):
        """Actions before SEO metadata is deleted."""
        self.clear_seo_cache()

    # =========================================================================
    # VALIDATION METHODS
    # =========================================================================

    def validate_reference_doctype(self):
        """Validate that reference DocType is supported."""
        if self.reference_doctype and self.reference_doctype not in SUPPORTED_DOCTYPES:
            frappe.msgprint(
                _("DocType {0} is not in the standard supported list. "
                  "Ensure it has the necessary fields for SEO integration.").format(
                    self.reference_doctype
                ),
                indicator="orange"
            )

    def validate_unique_reference(self):
        """Ensure only one SEO Meta exists per reference document."""
        if self.reference_doctype and self.reference_name:
            existing = frappe.db.exists(
                "SEO Meta",
                {
                    "reference_doctype": self.reference_doctype,
                    "reference_name": self.reference_name,
                    "name": ("!=", self.name or "")
                }
            )
            if existing:
                frappe.throw(
                    _("SEO metadata already exists for {0}: {1}").format(
                        self.reference_doctype, self.reference_name
                    )
                )

    def validate_meta_title_length(self):
        """Validate meta title length for SEO best practices."""
        if self.meta_title:
            title_length = len(self.meta_title)
            if title_length > 60:
                frappe.msgprint(
                    _("Meta title is {0} characters. Recommended: 50-60 characters. "
                      "Longer titles may be truncated in search results.").format(
                        title_length
                    ),
                    indicator="orange"
                )
            elif title_length < 30:
                frappe.msgprint(
                    _("Meta title is only {0} characters. Consider using 50-60 characters "
                      "for better search visibility.").format(title_length),
                    indicator="blue"
                )

    def validate_meta_description_length(self):
        """Validate meta description length for SEO best practices."""
        if self.meta_description:
            desc_length = len(self.meta_description)
            if desc_length > 160:
                frappe.msgprint(
                    _("Meta description is {0} characters. Recommended: 150-160 characters. "
                      "Longer descriptions may be truncated in search results.").format(
                        desc_length
                    ),
                    indicator="orange"
                )
            elif desc_length < 70:
                frappe.msgprint(
                    _("Meta description is only {0} characters. Consider using 150-160 "
                      "characters for better search visibility.").format(desc_length),
                    indicator="blue"
                )

    def validate_sitemap_priority(self):
        """Validate sitemap priority is within valid range."""
        if self.sitemap_priority is not None:
            priority = flt(self.sitemap_priority)
            if priority < 0 or priority > 1:
                frappe.throw(
                    _("Sitemap priority must be between 0.0 and 1.0")
                )
            self.sitemap_priority = priority

    def validate_schema_data(self):
        """Validate schema data is valid JSON if provided."""
        if self.schema_data:
            try:
                parsed = json.loads(self.schema_data)
                # Ensure it's a dictionary or list
                if not isinstance(parsed, (dict, list)):
                    frappe.throw(
                        _("Schema data must be a valid JSON object or array")
                    )
            except json.JSONDecodeError as e:
                frappe.throw(
                    _("Invalid JSON in schema data: {0}").format(str(e))
                )

    # =========================================================================
    # COMPUTED FIELD METHODS
    # =========================================================================

    def set_reference_title(self):
        """Set reference title from the linked document."""
        if not self.reference_doctype or not self.reference_name:
            return

        if not frappe.db.exists(self.reference_doctype, self.reference_name):
            return

        # Get title field based on DocType
        title_field_map = {
            "SKU Product": "product_name",
            "Product Category": "category_name",
            "Brand": "brand_name",
            "Seller Profile": "company_name",
        }

        title_field = title_field_map.get(self.reference_doctype, "name")

        try:
            self.reference_title = frappe.db.get_value(
                self.reference_doctype,
                self.reference_name,
                title_field
            ) or self.reference_name
        except Exception:
            self.reference_title = self.reference_name

    def set_tenant_from_reference(self):
        """Inherit tenant from reference document for multi-tenant isolation."""
        if not self.reference_doctype or not self.reference_name:
            return

        if not frappe.db.exists(self.reference_doctype, self.reference_name):
            return

        # Check if reference DocType has tenant field
        meta = frappe.get_meta(self.reference_doctype)
        if meta.has_field("tenant"):
            tenant = frappe.db.get_value(
                self.reference_doctype,
                self.reference_name,
                "tenant"
            )
            if tenant:
                self.tenant = tenant

    # =========================================================================
    # CACHE MANAGEMENT
    # =========================================================================

    def clear_seo_cache(self):
        """Clear cached SEO data for this reference."""
        if self.reference_doctype and self.reference_name:
            cache_key = f"seo_meta:{self.reference_doctype}:{self.reference_name}"
            frappe.cache().delete_value(cache_key)

    # =========================================================================
    # OUTPUT METHODS
    # =========================================================================

    def get_meta_tags(self):
        """
        Get formatted meta tags for HTML head.

        Returns:
            dict: Meta tag data for template rendering
        """
        return {
            "title": self.meta_title or self.reference_title,
            "description": self.meta_description,
            "keywords": self.meta_keywords,
            "canonical": self.canonical_url,
            "robots": self.get_robots_directive()
        }

    def get_open_graph(self):
        """
        Get Open Graph metadata for social sharing.

        Returns:
            dict: Open Graph data for template rendering
        """
        return {
            "og:title": self.og_title or self.meta_title or self.reference_title,
            "og:description": self.og_description or self.meta_description,
            "og:image": self.og_image,
            "og:type": self.og_type or "website"
        }

    def get_twitter_card(self):
        """
        Get Twitter Card metadata.

        Returns:
            dict: Twitter Card data for template rendering
        """
        return {
            "twitter:card": self.twitter_card or "summary_large_image",
            "twitter:title": self.twitter_title or self.og_title or self.meta_title,
            "twitter:description": self.twitter_description or self.og_description or self.meta_description,
            "twitter:image": self.twitter_image or self.og_image
        }

    def get_robots_directive(self):
        """
        Get formatted robots directive.

        Returns:
            str: Robots meta tag content
        """
        directives = []

        if not cint(self.robots_index):
            directives.append("noindex")
        else:
            directives.append("index")

        if not cint(self.robots_follow):
            directives.append("nofollow")
        else:
            directives.append("follow")

        if self.robots_additional:
            directives.extend([d.strip() for d in self.robots_additional.split(",") if d.strip()])

        return ", ".join(directives)

    def get_schema_json_ld(self):
        """
        Get Schema.org JSON-LD for structured data.

        Returns:
            str: JSON-LD script content or None
        """
        if not self.schema_data:
            return None

        try:
            data = json.loads(self.schema_data)
            if "@context" not in data:
                data["@context"] = "https://schema.org"
            if "@type" not in data and self.schema_type != "Custom":
                data["@type"] = self.schema_type
            return json.dumps(data, indent=2)
        except (json.JSONDecodeError, TypeError):
            return None

    def get_sitemap_entry(self):
        """
        Get sitemap entry data for XML sitemap generation.

        Returns:
            dict: Sitemap entry data or None if not included
        """
        if not cint(self.include_in_sitemap):
            return None

        return {
            "loc": self.canonical_url,
            "priority": flt(self.sitemap_priority) or 0.5,
            "changefreq": self.sitemap_changefreq or "weekly"
        }


# =============================================================================
# WHITELISTED API FUNCTIONS
# =============================================================================


@frappe.whitelist()
def get_seo_meta(reference_doctype, reference_name):
    """
    Get SEO metadata for a reference document.

    Args:
        reference_doctype: The DocType of the reference
        reference_name: The name of the reference document

    Returns:
        dict: SEO metadata or default values
    """
    # Check cache first
    cache_key = f"seo_meta:{reference_doctype}:{reference_name}"
    cached = frappe.cache().get_value(cache_key)
    if cached:
        return cached

    # Look up SEO Meta
    seo_meta_name = frappe.db.get_value(
        "SEO Meta",
        {
            "reference_doctype": reference_doctype,
            "reference_name": reference_name,
            "enabled": 1
        },
        "name"
    )

    if seo_meta_name:
        seo_meta = frappe.get_doc("SEO Meta", seo_meta_name)
        result = {
            "meta_tags": seo_meta.get_meta_tags(),
            "open_graph": seo_meta.get_open_graph(),
            "twitter_card": seo_meta.get_twitter_card(),
            "schema_json_ld": seo_meta.get_schema_json_ld(),
            "sitemap": seo_meta.get_sitemap_entry()
        }
    else:
        # Return default/fallback values from reference document
        result = get_default_seo_meta(reference_doctype, reference_name)

    # Cache the result
    frappe.cache().set_value(cache_key, result, expires_in_sec=3600)

    return result


def get_default_seo_meta(reference_doctype, reference_name):
    """
    Get default SEO metadata from reference document fields.

    Args:
        reference_doctype: The DocType of the reference
        reference_name: The name of the reference document

    Returns:
        dict: Default SEO metadata from reference document
    """
    if not frappe.db.exists(reference_doctype, reference_name):
        return None

    # Field mapping for different DocTypes
    field_maps = {
        "SKU Product": {
            "title": "product_name",
            "description": "seo_description",
            "keywords": "seo_keywords",
            "image": "thumbnail"
        },
        "Product Category": {
            "title": "category_name",
            "description": "seo_description",
            "keywords": "seo_keywords",
            "image": "image"
        },
        "Brand": {
            "title": "brand_name",
            "description": "seo_description",
            "keywords": "seo_keywords",
            "image": "logo"
        }
    }

    field_map = field_maps.get(reference_doctype, {"title": "name"})

    doc_data = frappe.db.get_value(
        reference_doctype,
        reference_name,
        list(field_map.values()),
        as_dict=True
    )

    if not doc_data:
        return None

    title = doc_data.get(field_map.get("title", "name"), reference_name)
    description = doc_data.get(field_map.get("description"), "")
    keywords = doc_data.get(field_map.get("keywords"), "")
    image = doc_data.get(field_map.get("image"), "")

    return {
        "meta_tags": {
            "title": title,
            "description": description,
            "keywords": keywords,
            "canonical": None,
            "robots": "index, follow"
        },
        "open_graph": {
            "og:title": title,
            "og:description": description,
            "og:image": image,
            "og:type": "product" if reference_doctype == "SKU Product" else "website"
        },
        "twitter_card": {
            "twitter:card": "summary_large_image",
            "twitter:title": title,
            "twitter:description": description,
            "twitter:image": image
        },
        "schema_json_ld": None,
        "sitemap": {
            "priority": 0.5,
            "changefreq": "weekly"
        }
    }


@frappe.whitelist()
def create_seo_meta_from_document(reference_doctype, reference_name, auto_fill=True):
    """
    Create SEO Meta document from a reference document.

    Args:
        reference_doctype: The DocType of the reference
        reference_name: The name of the reference document
        auto_fill: Whether to auto-fill fields from reference

    Returns:
        dict: Created SEO Meta document data
    """
    # Check if already exists
    existing = frappe.db.exists(
        "SEO Meta",
        {
            "reference_doctype": reference_doctype,
            "reference_name": reference_name
        }
    )
    if existing:
        return frappe.get_doc("SEO Meta", existing).as_dict()

    seo_meta = frappe.new_doc("SEO Meta")
    seo_meta.reference_doctype = reference_doctype
    seo_meta.reference_name = reference_name

    if auto_fill:
        defaults = get_default_seo_meta(reference_doctype, reference_name)
        if defaults:
            meta_tags = defaults.get("meta_tags", {})
            og = defaults.get("open_graph", {})

            seo_meta.meta_title = meta_tags.get("title", "")
            seo_meta.meta_description = meta_tags.get("description", "")
            seo_meta.meta_keywords = meta_tags.get("keywords", "")
            seo_meta.og_image = og.get("og:image", "")

    seo_meta.insert(ignore_permissions=True)

    return seo_meta.as_dict()


@frappe.whitelist()
def bulk_create_seo_meta(reference_doctype, reference_names=None, limit=100):
    """
    Bulk create SEO Meta documents for multiple references.

    Args:
        reference_doctype: The DocType of the references
        reference_names: List of reference names (optional, gets all if not provided)
        limit: Maximum number of records to process

    Returns:
        dict: Summary of created records
    """
    created = 0
    skipped = 0
    errors = []

    if reference_names:
        names = json.loads(reference_names) if isinstance(reference_names, str) else reference_names
    else:
        # Get documents that don't have SEO Meta yet
        existing = frappe.get_all(
            "SEO Meta",
            filters={"reference_doctype": reference_doctype},
            fields=["reference_name"]
        )
        existing_names = set(e.reference_name for e in existing)

        all_names = frappe.get_all(
            reference_doctype,
            limit_page_length=cint(limit),
            pluck="name"
        )
        names = [n for n in all_names if n not in existing_names]

    for name in names[:cint(limit)]:
        try:
            create_seo_meta_from_document(reference_doctype, name, auto_fill=True)
            created += 1
        except frappe.DuplicateEntryError:
            skipped += 1
        except Exception as e:
            errors.append({"name": name, "error": str(e)})

    return {
        "created": created,
        "skipped": skipped,
        "errors": errors
    }


@frappe.whitelist()
def get_seo_report(reference_doctype=None, tenant=None):
    """
    Get SEO coverage report for a DocType or tenant.

    Args:
        reference_doctype: Filter by DocType (optional)
        tenant: Filter by tenant (optional)

    Returns:
        dict: SEO coverage statistics
    """
    filters = {"enabled": 1}
    if reference_doctype:
        filters["reference_doctype"] = reference_doctype
    if tenant:
        filters["tenant"] = tenant

    seo_metas = frappe.get_all(
        "SEO Meta",
        filters=filters,
        fields=["name", "reference_doctype", "reference_name",
                "meta_title", "meta_description", "og_image", "schema_data"]
    )

    # Calculate statistics
    total = len(seo_metas)
    with_title = sum(1 for s in seo_metas if s.meta_title)
    with_description = sum(1 for s in seo_metas if s.meta_description)
    with_og_image = sum(1 for s in seo_metas if s.og_image)
    with_schema = sum(1 for s in seo_metas if s.schema_data)

    return {
        "total": total,
        "with_meta_title": with_title,
        "with_meta_description": with_description,
        "with_og_image": with_og_image,
        "with_schema": with_schema,
        "coverage_percent": {
            "meta_title": round(with_title / total * 100, 1) if total else 0,
            "meta_description": round(with_description / total * 100, 1) if total else 0,
            "og_image": round(with_og_image / total * 100, 1) if total else 0,
            "schema": round(with_schema / total * 100, 1) if total else 0
        }
    }

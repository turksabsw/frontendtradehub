# Copyright (c) 2026, Trade Hub and contributors
# For license information, please see license.txt

"""
Sitemap Generation Utility for Trade Hub B2B Marketplace.

This module provides comprehensive XML sitemap generation for SEO optimization.
It supports generating sitemaps for products, categories, brands, and seller pages
with multi-tenant support and proper caching.

Key Features:
- Standard XML sitemap generation following sitemaps.org protocol
- Sitemap index support for large sites (>50,000 URLs per sitemap)
- Multi-tenant support with tenant-specific sitemaps
- Integration with SEO Meta DocType for sitemap configuration
- Background job support for scheduled regeneration
- Caching for performance optimization

Usage:
    from tr_tradehub.utils.sitemap_generator import generate_sitemap, get_sitemap_xml

    # Generate sitemap for products
    sitemap_xml = generate_sitemap("products")

    # Generate complete sitemap index
    sitemap_index = generate_sitemap_index()
"""

from datetime import datetime
from typing import Any, Dict, List, Optional
from xml.etree import ElementTree as ET
from xml.dom import minidom

import frappe
from frappe import _
from frappe.utils import cint, flt, get_url, now_datetime, cstr


# XML Sitemap namespace
SITEMAP_NS = "http://www.sitemaps.org/schemas/sitemap/0.9"

# Maximum URLs per sitemap (per sitemaps.org specification)
MAX_URLS_PER_SITEMAP = 50000

# Default sitemap values
DEFAULT_PRIORITY = 0.5
DEFAULT_CHANGEFREQ = "weekly"

# Content type configurations for sitemap generation
CONTENT_TYPE_CONFIG = {
    "products": {
        "doctype": "SKU Product",
        "url_field": "url_slug",
        "url_prefix": "/products/",
        "priority": 0.8,
        "changefreq": "daily",
        "filters": {"status": "Active", "is_published": 1},
        "lastmod_field": "modified",
    },
    "categories": {
        "doctype": "Product Category",
        "url_field": "url_slug",
        "url_prefix": "/categories/",
        "priority": 0.7,
        "changefreq": "weekly",
        "filters": {"enabled": 1},
        "lastmod_field": "modified",
    },
    "sellers": {
        "doctype": "Seller Profile",
        "url_field": "url_slug",
        "url_prefix": "/sellers/",
        "priority": 0.6,
        "changefreq": "weekly",
        "filters": {"status": "Active", "verification_status": "Verified"},
        "lastmod_field": "modified",
    },
    "brands": {
        "doctype": "Brand",
        "url_field": "url_slug",
        "url_prefix": "/brands/",
        "priority": 0.6,
        "changefreq": "weekly",
        "filters": {"is_active": 1},
        "lastmod_field": "modified",
    },
}

# Cache key prefix for sitemaps
SITEMAP_CACHE_PREFIX = "trade_hub:sitemap"

# Cache duration in seconds (1 hour)
SITEMAP_CACHE_DURATION = 3600


# =============================================================================
# CORE SITEMAP GENERATION FUNCTIONS
# =============================================================================


def generate_sitemap(
    content_type: str,
    tenant: str = None,
    page: int = 1,
    base_url: str = None,
    use_cache: bool = True
) -> str:
    """
    Generate XML sitemap for a specific content type.

    Args:
        content_type: Type of content to include (products, categories, sellers, brands)
        tenant: Optional tenant filter for multi-tenant sites
        page: Page number for paginated sitemaps (1-indexed)
        base_url: Base URL for generating absolute URLs (defaults to site URL)
        use_cache: Whether to use cached sitemap if available

    Returns:
        str: XML sitemap content

    Raises:
        frappe.ValidationError: If content_type is not supported

    Example:
        sitemap_xml = generate_sitemap("products")
        sitemap_xml = generate_sitemap("products", tenant="TEN-00001", page=2)
    """
    if content_type not in CONTENT_TYPE_CONFIG:
        frappe.throw(
            _("Unsupported content type: {0}. Supported types: {1}").format(
                content_type, ", ".join(CONTENT_TYPE_CONFIG.keys())
            ),
            frappe.ValidationError
        )

    # Check cache first
    cache_key = get_sitemap_cache_key(content_type, tenant, page)
    if use_cache:
        cached_sitemap = frappe.cache().get_value(cache_key)
        if cached_sitemap:
            return cached_sitemap

    # Get base URL
    if not base_url:
        base_url = get_site_base_url(tenant)

    # Get configuration for content type
    config = CONTENT_TYPE_CONFIG[content_type]

    # Get URLs for this content type
    urls = get_content_urls(
        content_type=content_type,
        config=config,
        tenant=tenant,
        page=page,
        base_url=base_url
    )

    # Generate XML
    sitemap_xml = build_sitemap_xml(urls)

    # Cache the result
    frappe.cache().set_value(cache_key, sitemap_xml, expires_in_sec=SITEMAP_CACHE_DURATION)

    return sitemap_xml


def generate_sitemap_index(
    tenant: str = None,
    base_url: str = None,
    content_types: List[str] = None,
    use_cache: bool = True
) -> str:
    """
    Generate sitemap index file containing references to all individual sitemaps.

    Args:
        tenant: Optional tenant filter for multi-tenant sites
        base_url: Base URL for generating absolute URLs
        content_types: List of content types to include (defaults to all)
        use_cache: Whether to use cached sitemap index if available

    Returns:
        str: XML sitemap index content

    Example:
        sitemap_index = generate_sitemap_index()
        sitemap_index = generate_sitemap_index(tenant="TEN-00001")
    """
    # Check cache first
    cache_key = get_sitemap_cache_key("index", tenant)
    if use_cache:
        cached_sitemap = frappe.cache().get_value(cache_key)
        if cached_sitemap:
            return cached_sitemap

    # Get base URL
    if not base_url:
        base_url = get_site_base_url(tenant)

    # Use all content types if not specified
    if not content_types:
        content_types = list(CONTENT_TYPE_CONFIG.keys())

    # Collect all sitemap references
    sitemaps = []
    for content_type in content_types:
        sitemap_entries = get_sitemap_entries_for_type(
            content_type=content_type,
            tenant=tenant,
            base_url=base_url
        )
        sitemaps.extend(sitemap_entries)

    # Build sitemap index XML
    sitemap_index_xml = build_sitemap_index_xml(sitemaps)

    # Cache the result
    frappe.cache().set_value(cache_key, sitemap_index_xml, expires_in_sec=SITEMAP_CACHE_DURATION)

    return sitemap_index_xml


def get_content_urls(
    content_type: str,
    config: Dict[str, Any],
    tenant: str = None,
    page: int = 1,
    base_url: str = None
) -> List[Dict[str, Any]]:
    """
    Get URLs for a specific content type with SEO metadata.

    Args:
        content_type: Type of content
        config: Configuration dict for this content type
        tenant: Optional tenant filter
        page: Page number (1-indexed)
        base_url: Base URL for absolute URLs

    Returns:
        list: List of URL entries with loc, lastmod, changefreq, priority
    """
    doctype = config["doctype"]
    url_field = config["url_field"]
    url_prefix = config["url_prefix"]
    default_priority = config.get("priority", DEFAULT_PRIORITY)
    default_changefreq = config.get("changefreq", DEFAULT_CHANGEFREQ)
    filters = dict(config.get("filters", {}))
    lastmod_field = config.get("lastmod_field", "modified")

    # Add tenant filter if specified
    if tenant:
        meta = frappe.get_meta(doctype)
        if meta.has_field("tenant"):
            filters["tenant"] = tenant

    # Calculate pagination
    offset = (page - 1) * MAX_URLS_PER_SITEMAP
    limit = MAX_URLS_PER_SITEMAP

    # Get documents
    fields = ["name", url_field, lastmod_field]
    documents = frappe.get_all(
        doctype,
        filters=filters,
        fields=fields,
        limit_page_length=limit,
        limit_start=offset,
        order_by="modified desc"
    )

    # Build URL entries
    urls = []
    for doc in documents:
        url_slug = doc.get(url_field)
        if not url_slug:
            continue

        # Get SEO meta if available
        seo_data = get_seo_meta_for_sitemap(doctype, doc.name)

        # Check if should be included in sitemap
        if seo_data and not seo_data.get("include_in_sitemap", True):
            continue

        # Build URL entry
        url_entry = {
            "loc": f"{base_url}{url_prefix}{url_slug}",
            "lastmod": format_datetime_for_sitemap(doc.get(lastmod_field)),
            "changefreq": seo_data.get("changefreq", default_changefreq) if seo_data else default_changefreq,
            "priority": seo_data.get("priority", default_priority) if seo_data else default_priority,
        }

        # Use canonical URL if available from SEO meta
        if seo_data and seo_data.get("canonical_url"):
            url_entry["loc"] = seo_data["canonical_url"]

        urls.append(url_entry)

    return urls


def get_sitemap_entries_for_type(
    content_type: str,
    tenant: str = None,
    base_url: str = None
) -> List[Dict[str, str]]:
    """
    Get sitemap index entries for a content type (may be paginated).

    Args:
        content_type: Type of content
        tenant: Optional tenant filter
        base_url: Base URL for sitemap URLs

    Returns:
        list: List of sitemap entries with loc and lastmod
    """
    config = CONTENT_TYPE_CONFIG.get(content_type)
    if not config:
        return []

    doctype = config["doctype"]
    filters = dict(config.get("filters", {}))

    # Add tenant filter if specified
    if tenant:
        meta = frappe.get_meta(doctype)
        if meta.has_field("tenant"):
            filters["tenant"] = tenant

    # Get total count
    total_count = frappe.db.count(doctype, filters=filters)

    if total_count == 0:
        return []

    # Calculate number of sitemap pages needed
    num_pages = (total_count + MAX_URLS_PER_SITEMAP - 1) // MAX_URLS_PER_SITEMAP

    # Get the latest modification date for this content type
    latest_modified = frappe.db.sql("""
        SELECT MAX(modified) FROM `tab{0}` WHERE {1}
    """.format(
        doctype,
        " AND ".join([f"{k} = %s" for k in filters.keys()]) if filters else "1=1"
    ), tuple(filters.values()))[0][0] if filters else None

    if not latest_modified:
        latest_modified = now_datetime()

    # Build sitemap entries
    sitemaps = []
    for page in range(1, num_pages + 1):
        sitemap_url = build_sitemap_url(
            content_type=content_type,
            tenant=tenant,
            page=page if num_pages > 1 else None,
            base_url=base_url
        )
        sitemaps.append({
            "loc": sitemap_url,
            "lastmod": format_datetime_for_sitemap(latest_modified)
        })

    return sitemaps


# =============================================================================
# XML BUILDING FUNCTIONS
# =============================================================================


def build_sitemap_xml(urls: List[Dict[str, Any]]) -> str:
    """
    Build XML sitemap from URL list.

    Args:
        urls: List of URL entries with loc, lastmod, changefreq, priority

    Returns:
        str: Formatted XML sitemap string
    """
    # Create root element with namespace
    urlset = ET.Element("urlset")
    urlset.set("xmlns", SITEMAP_NS)

    # Add URL entries
    for url_data in urls:
        url_elem = ET.SubElement(urlset, "url")

        # loc (required)
        loc = ET.SubElement(url_elem, "loc")
        loc.text = url_data["loc"]

        # lastmod (optional)
        if url_data.get("lastmod"):
            lastmod = ET.SubElement(url_elem, "lastmod")
            lastmod.text = url_data["lastmod"]

        # changefreq (optional)
        if url_data.get("changefreq"):
            changefreq = ET.SubElement(url_elem, "changefreq")
            changefreq.text = url_data["changefreq"]

        # priority (optional)
        if url_data.get("priority") is not None:
            priority = ET.SubElement(url_elem, "priority")
            priority.text = str(flt(url_data["priority"], 1))

    # Generate XML string with proper formatting
    return prettify_xml(urlset)


def build_sitemap_index_xml(sitemaps: List[Dict[str, str]]) -> str:
    """
    Build XML sitemap index from sitemap list.

    Args:
        sitemaps: List of sitemap entries with loc and lastmod

    Returns:
        str: Formatted XML sitemap index string
    """
    # Create root element with namespace
    sitemapindex = ET.Element("sitemapindex")
    sitemapindex.set("xmlns", SITEMAP_NS)

    # Add sitemap entries
    for sitemap_data in sitemaps:
        sitemap_elem = ET.SubElement(sitemapindex, "sitemap")

        # loc (required)
        loc = ET.SubElement(sitemap_elem, "loc")
        loc.text = sitemap_data["loc"]

        # lastmod (optional)
        if sitemap_data.get("lastmod"):
            lastmod = ET.SubElement(sitemap_elem, "lastmod")
            lastmod.text = sitemap_data["lastmod"]

    # Generate XML string with proper formatting
    return prettify_xml(sitemapindex)


def prettify_xml(elem: ET.Element) -> str:
    """
    Convert ElementTree element to pretty-printed XML string.

    Args:
        elem: ElementTree element

    Returns:
        str: Formatted XML string with declaration
    """
    rough_string = ET.tostring(elem, encoding="unicode")
    reparsed = minidom.parseString(rough_string)
    return reparsed.toprettyxml(indent="  ", encoding=None)


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================


def get_site_base_url(tenant: str = None) -> str:
    """
    Get the base URL for the site.

    Args:
        tenant: Optional tenant for custom domain lookup

    Returns:
        str: Base URL without trailing slash
    """
    if tenant:
        # Check for custom domain
        custom_domain = frappe.db.get_value("Tenant", tenant, "custom_domain")
        if custom_domain:
            return f"https://{custom_domain}"

    # Use Frappe's get_url
    base_url = get_url()
    return base_url.rstrip("/")


def build_sitemap_url(
    content_type: str,
    tenant: str = None,
    page: int = None,
    base_url: str = None
) -> str:
    """
    Build URL for a sitemap file.

    Args:
        content_type: Type of content
        tenant: Optional tenant filter
        page: Page number for paginated sitemaps
        base_url: Base URL

    Returns:
        str: Sitemap URL
    """
    if not base_url:
        base_url = get_site_base_url(tenant)

    # Build sitemap filename
    parts = ["sitemap", content_type]
    if tenant:
        parts.append(tenant.lower().replace("-", "_"))
    if page and page > 1:
        parts.append(str(page))

    filename = "_".join(parts) + ".xml"

    return f"{base_url}/{filename}"


def get_sitemap_cache_key(content_type: str, tenant: str = None, page: int = 1) -> str:
    """
    Get cache key for a sitemap.

    Args:
        content_type: Type of content
        tenant: Optional tenant
        page: Page number

    Returns:
        str: Cache key
    """
    parts = [SITEMAP_CACHE_PREFIX, content_type]
    if tenant:
        parts.append(tenant)
    parts.append(str(page))
    return ":".join(parts)


def format_datetime_for_sitemap(dt: Any) -> str:
    """
    Format datetime for sitemap XML (W3C datetime format).

    Args:
        dt: Datetime value (string or datetime object)

    Returns:
        str: ISO 8601 formatted date string
    """
    if not dt:
        return ""

    if isinstance(dt, str):
        try:
            dt = datetime.fromisoformat(dt.replace("Z", "+00:00"))
        except ValueError:
            return ""

    if isinstance(dt, datetime):
        return dt.strftime("%Y-%m-%dT%H:%M:%S+00:00")

    return ""


def get_seo_meta_for_sitemap(doctype: str, docname: str) -> Optional[Dict[str, Any]]:
    """
    Get SEO metadata for sitemap from SEO Meta DocType.

    Args:
        doctype: Reference DocType
        docname: Reference document name

    Returns:
        dict: SEO sitemap data or None
    """
    if not frappe.db.exists("DocType", "SEO Meta"):
        return None

    seo_meta = frappe.db.get_value(
        "SEO Meta",
        {
            "reference_doctype": doctype,
            "reference_name": docname,
            "enabled": 1
        },
        ["include_in_sitemap", "sitemap_priority", "sitemap_changefreq", "canonical_url"],
        as_dict=True
    )

    if not seo_meta:
        return None

    return {
        "include_in_sitemap": cint(seo_meta.include_in_sitemap) if seo_meta.include_in_sitemap is not None else True,
        "priority": flt(seo_meta.sitemap_priority) if seo_meta.sitemap_priority else None,
        "changefreq": seo_meta.sitemap_changefreq,
        "canonical_url": seo_meta.canonical_url,
    }


def get_url_count(content_type: str, tenant: str = None) -> int:
    """
    Get total URL count for a content type.

    Args:
        content_type: Type of content
        tenant: Optional tenant filter

    Returns:
        int: Total URL count
    """
    config = CONTENT_TYPE_CONFIG.get(content_type)
    if not config:
        return 0

    doctype = config["doctype"]
    filters = dict(config.get("filters", {}))

    # Add tenant filter if specified
    if tenant:
        meta = frappe.get_meta(doctype)
        if meta.has_field("tenant"):
            filters["tenant"] = tenant

    return frappe.db.count(doctype, filters=filters)


# =============================================================================
# CACHE MANAGEMENT
# =============================================================================


def clear_sitemap_cache(content_type: str = None, tenant: str = None) -> None:
    """
    Clear cached sitemap data.

    Args:
        content_type: Optional content type to clear (None = clear all)
        tenant: Optional tenant to clear (None = clear all)
    """
    if content_type:
        # Clear specific content type
        content_types = [content_type]
    else:
        # Clear all content types
        content_types = list(CONTENT_TYPE_CONFIG.keys())
        content_types.append("index")

    for ct in content_types:
        # Clear all pages for this content type
        for page in range(1, 100):  # Reasonable maximum
            cache_key = get_sitemap_cache_key(ct, tenant, page)
            frappe.cache().delete_value(cache_key)

            # Also clear without tenant
            if tenant:
                cache_key_no_tenant = get_sitemap_cache_key(ct, None, page)
                frappe.cache().delete_value(cache_key_no_tenant)


def invalidate_sitemap_for_doc(doctype: str, docname: str) -> None:
    """
    Invalidate sitemap cache when a document is updated.

    This function should be called from doc_events hooks.

    Args:
        doctype: DocType of the updated document
        docname: Name of the updated document
    """
    # Find which content type this doctype belongs to
    for content_type, config in CONTENT_TYPE_CONFIG.items():
        if config["doctype"] == doctype:
            # Get tenant from document if available
            tenant = None
            meta = frappe.get_meta(doctype)
            if meta.has_field("tenant"):
                tenant = frappe.db.get_value(doctype, docname, "tenant")

            # Clear cache for this content type
            clear_sitemap_cache(content_type, tenant)

            # Also clear sitemap index
            clear_sitemap_cache("index", tenant)

            break


# =============================================================================
# BACKGROUND JOB FUNCTIONS
# =============================================================================


def regenerate_all_sitemaps(tenant: str = None) -> Dict[str, Any]:
    """
    Regenerate all sitemaps (for background job).

    Args:
        tenant: Optional tenant filter

    Returns:
        dict: Summary of regeneration results
    """
    results = {
        "success": True,
        "content_types": {},
        "total_urls": 0,
        "errors": []
    }

    # Clear existing cache
    clear_sitemap_cache(tenant=tenant)

    # Regenerate each content type
    for content_type in CONTENT_TYPE_CONFIG.keys():
        try:
            url_count = get_url_count(content_type, tenant)
            num_pages = (url_count + MAX_URLS_PER_SITEMAP - 1) // MAX_URLS_PER_SITEMAP or 1

            for page in range(1, num_pages + 1):
                generate_sitemap(
                    content_type=content_type,
                    tenant=tenant,
                    page=page,
                    use_cache=False
                )

            results["content_types"][content_type] = {
                "url_count": url_count,
                "pages": num_pages
            }
            results["total_urls"] += url_count

        except Exception as e:
            results["errors"].append({
                "content_type": content_type,
                "error": str(e)
            })
            results["success"] = False

    # Regenerate sitemap index
    try:
        generate_sitemap_index(tenant=tenant, use_cache=False)
    except Exception as e:
        results["errors"].append({
            "content_type": "index",
            "error": str(e)
        })
        results["success"] = False

    return results


def enqueue_sitemap_regeneration(tenant: str = None) -> str:
    """
    Enqueue background job for sitemap regeneration.

    Args:
        tenant: Optional tenant filter

    Returns:
        str: Job ID
    """
    job = frappe.enqueue(
        "tr_tradehub.utils.sitemap_generator.regenerate_all_sitemaps",
        tenant=tenant,
        queue="long",
        timeout=1800,  # 30 minutes
        is_async=True
    )
    return job.id if hasattr(job, 'id') else cstr(job)


# =============================================================================
# SITEMAP STATISTICS
# =============================================================================


def get_sitemap_stats(tenant: str = None) -> Dict[str, Any]:
    """
    Get sitemap statistics and coverage.

    Args:
        tenant: Optional tenant filter

    Returns:
        dict: Sitemap statistics
    """
    stats = {
        "total_urls": 0,
        "content_types": {},
        "estimated_sitemap_files": 0
    }

    for content_type, config in CONTENT_TYPE_CONFIG.items():
        url_count = get_url_count(content_type, tenant)
        num_pages = (url_count + MAX_URLS_PER_SITEMAP - 1) // MAX_URLS_PER_SITEMAP or 1

        stats["content_types"][content_type] = {
            "doctype": config["doctype"],
            "url_count": url_count,
            "sitemap_files": num_pages,
            "priority": config.get("priority", DEFAULT_PRIORITY),
            "changefreq": config.get("changefreq", DEFAULT_CHANGEFREQ)
        }
        stats["total_urls"] += url_count
        stats["estimated_sitemap_files"] += num_pages

    # Add 1 for sitemap index
    stats["estimated_sitemap_files"] += 1

    return stats


# =============================================================================
# WHITELISTED API FUNCTIONS
# =============================================================================


@frappe.whitelist(allow_guest=True)
def get_sitemap_xml(
    content_type: str,
    tenant: str = None,
    page: int = 1
) -> str:
    """
    Get XML sitemap for a specific content type.

    This endpoint is designed to be called by search engine crawlers.

    Args:
        content_type: Type of content (products, categories, sellers, brands)
        tenant: Optional tenant filter
        page: Page number for paginated sitemaps

    Returns:
        str: XML sitemap content

    Example API call:
        frappe.call('tr_tradehub.utils.sitemap_generator.get_sitemap_xml',
                    content_type='products')
    """
    # Set appropriate content type for response
    frappe.response["content_type"] = "application/xml"

    return generate_sitemap(
        content_type=content_type,
        tenant=tenant,
        page=cint(page) or 1
    )


@frappe.whitelist(allow_guest=True)
def get_sitemap_index_xml(tenant: str = None) -> str:
    """
    Get XML sitemap index.

    This endpoint is designed to be called by search engine crawlers.

    Args:
        tenant: Optional tenant filter

    Returns:
        str: XML sitemap index content

    Example API call:
        frappe.call('tr_tradehub.utils.sitemap_generator.get_sitemap_index_xml')
    """
    # Set appropriate content type for response
    frappe.response["content_type"] = "application/xml"

    return generate_sitemap_index(tenant=tenant)


@frappe.whitelist()
def refresh_sitemap(content_type: str = None, tenant: str = None) -> Dict[str, Any]:
    """
    Manually refresh sitemap cache.

    Args:
        content_type: Optional content type to refresh (None = all)
        tenant: Optional tenant filter

    Returns:
        dict: Refresh result summary

    Example API call:
        frappe.call('tr_tradehub.utils.sitemap_generator.refresh_sitemap')
    """
    # Clear cache
    clear_sitemap_cache(content_type, tenant)

    # Regenerate
    if content_type:
        url_count = get_url_count(content_type, tenant)
        generate_sitemap(content_type=content_type, tenant=tenant, use_cache=False)
        return {
            "success": True,
            "message": _("Sitemap refreshed for {0}").format(content_type),
            "url_count": url_count
        }
    else:
        results = regenerate_all_sitemaps(tenant=tenant)
        return {
            "success": results["success"],
            "message": _("All sitemaps refreshed"),
            "total_urls": results["total_urls"],
            "content_types": results["content_types"],
            "errors": results["errors"]
        }


@frappe.whitelist()
def get_sitemap_statistics(tenant: str = None) -> Dict[str, Any]:
    """
    Get sitemap statistics and coverage information.

    Args:
        tenant: Optional tenant filter

    Returns:
        dict: Sitemap statistics

    Example API call:
        frappe.call('tr_tradehub.utils.sitemap_generator.get_sitemap_statistics')
    """
    return get_sitemap_stats(tenant)


@frappe.whitelist()
def schedule_sitemap_regeneration(tenant: str = None) -> Dict[str, str]:
    """
    Schedule background job for sitemap regeneration.

    Args:
        tenant: Optional tenant filter

    Returns:
        dict: Job information

    Example API call:
        frappe.call('tr_tradehub.utils.sitemap_generator.schedule_sitemap_regeneration')
    """
    job_id = enqueue_sitemap_regeneration(tenant)
    return {
        "success": True,
        "message": _("Sitemap regeneration scheduled"),
        "job_id": job_id
    }


@frappe.whitelist(allow_guest=True)
def ping_search_engines(sitemap_url: str = None, tenant: str = None) -> Dict[str, Any]:
    """
    Ping search engines to notify them of sitemap updates.

    This function notifies Google and Bing about sitemap changes.

    Args:
        sitemap_url: URL of the sitemap (defaults to sitemap index)
        tenant: Optional tenant for custom domain

    Returns:
        dict: Ping results for each search engine
    """
    import requests

    if not sitemap_url:
        base_url = get_site_base_url(tenant)
        sitemap_url = f"{base_url}/sitemap.xml"

    # Search engine ping URLs
    ping_urls = {
        "google": f"https://www.google.com/ping?sitemap={sitemap_url}",
        "bing": f"https://www.bing.com/ping?sitemap={sitemap_url}",
    }

    results = {
        "sitemap_url": sitemap_url,
        "engines": {}
    }

    for engine, ping_url in ping_urls.items():
        try:
            response = requests.get(ping_url, timeout=30)
            results["engines"][engine] = {
                "success": response.status_code == 200,
                "status_code": response.status_code
            }
        except Exception as e:
            results["engines"][engine] = {
                "success": False,
                "error": str(e)
            }

    return results


# =============================================================================
# STATIC PAGE SITEMAP SUPPORT
# =============================================================================


def add_static_pages(base_url: str = None) -> List[Dict[str, Any]]:
    """
    Get static pages for sitemap (home, about, contact, etc.).

    Args:
        base_url: Base URL for absolute URLs

    Returns:
        list: List of static page URL entries
    """
    if not base_url:
        base_url = get_site_base_url()

    static_pages = [
        {"path": "/", "priority": 1.0, "changefreq": "daily"},
        {"path": "/about", "priority": 0.7, "changefreq": "monthly"},
        {"path": "/contact", "priority": 0.6, "changefreq": "monthly"},
        {"path": "/terms", "priority": 0.4, "changefreq": "yearly"},
        {"path": "/privacy", "priority": 0.4, "changefreq": "yearly"},
        {"path": "/sellers", "priority": 0.8, "changefreq": "weekly"},
        {"path": "/categories", "priority": 0.8, "changefreq": "weekly"},
        {"path": "/brands", "priority": 0.7, "changefreq": "weekly"},
    ]

    urls = []
    for page in static_pages:
        urls.append({
            "loc": f"{base_url}{page['path']}",
            "lastmod": format_datetime_for_sitemap(now_datetime()),
            "changefreq": page["changefreq"],
            "priority": page["priority"]
        })

    return urls


def generate_complete_sitemap(tenant: str = None, base_url: str = None) -> str:
    """
    Generate a complete sitemap including static pages and dynamic content.

    This is useful for smaller sites that don't need sitemap index.

    Args:
        tenant: Optional tenant filter
        base_url: Base URL for absolute URLs

    Returns:
        str: Complete XML sitemap
    """
    if not base_url:
        base_url = get_site_base_url(tenant)

    all_urls = []

    # Add static pages
    all_urls.extend(add_static_pages(base_url))

    # Add dynamic content from all types
    for content_type, config in CONTENT_TYPE_CONFIG.items():
        urls = get_content_urls(
            content_type=content_type,
            config=config,
            tenant=tenant,
            page=1,
            base_url=base_url
        )
        all_urls.extend(urls)

    # Check if we exceed max URLs
    if len(all_urls) > MAX_URLS_PER_SITEMAP:
        frappe.msgprint(
            _("Total URLs ({0}) exceed maximum per sitemap ({1}). "
              "Use sitemap index for large sites.").format(
                len(all_urls), MAX_URLS_PER_SITEMAP
            ),
            indicator="orange"
        )
        # Truncate to max
        all_urls = all_urls[:MAX_URLS_PER_SITEMAP]

    return build_sitemap_xml(all_urls)

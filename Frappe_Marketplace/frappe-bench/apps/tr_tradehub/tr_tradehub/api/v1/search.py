# Copyright (c) 2026, Trade Hub and contributors
# For license information, please see license.txt

"""
Trade Hub Search API v1.

This module provides a comprehensive search API with faceted filtering
for the Trade Hub B2B marketplace. It enables buyers and sellers to
search products with advanced filtering, sorting, and faceted navigation.

Key Features:
- Full-text product search with relevance scoring
- Faceted filtering (category, brand, seller, price, attributes, etc.)
- Dynamic facet counts based on current filters
- Search suggestions and autocomplete
- Popular search tracking
- Multi-tenant data isolation
- SEO-friendly URL parameter support

Usage Flow:
1. search_products() - Main search with filters and pagination
2. get_search_facets() - Get available facets for filter UI
3. get_search_suggestions() - Autocomplete as user types
4. get_popular_searches() - Show trending searches
"""

import json
import re
from typing import Optional, Dict, Any, List

import frappe
from frappe import _
from frappe.utils import (
    cint, flt, nowdate, now_datetime, cstr
)


# =============================================================================
# CONSTANTS
# =============================================================================

# Default pagination limits
DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100

# Search configuration
MIN_SEARCH_LENGTH = 2
MAX_SUGGESTIONS = 10
POPULAR_SEARCH_LIMIT = 20

# Sort options
SORT_OPTIONS = {
    "relevance": {"field": "_score", "order": "desc", "label": "Relevance"},
    "price_asc": {"field": "base_price", "order": "asc", "label": "Price: Low to High"},
    "price_desc": {"field": "base_price", "order": "desc", "label": "Price: High to Low"},
    "newest": {"field": "creation", "order": "desc", "label": "Newest First"},
    "name_asc": {"field": "product_name", "order": "asc", "label": "Name: A to Z"},
    "name_desc": {"field": "product_name", "order": "desc", "label": "Name: Z to A"},
    "rating": {"field": "average_rating", "order": "desc", "label": "Highest Rated"},
    "best_seller": {"field": "total_orders", "order": "desc", "label": "Best Selling"}
}

# Searchable fields with weights for relevance scoring
SEARCHABLE_FIELDS = {
    "product_name": 10,
    "sku_code": 8,
    "product_description": 5,
    "seo_keywords": 7,
    "brand_name": 6,
    "seller_name": 4,
    "category_name": 6
}


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def get_current_tenant() -> Optional[str]:
    """Get current user's tenant."""
    try:
        from tr_tradehub.utils.tenant import get_current_tenant as _get_tenant
        return _get_tenant()
    except ImportError:
        return frappe.db.get_value("User", frappe.session.user, "tenant")


def validate_page_params(limit: int, offset: int) -> tuple:
    """Validate and sanitize pagination parameters."""
    limit = min(max(cint(limit), 1), MAX_PAGE_SIZE) if limit else DEFAULT_PAGE_SIZE
    offset = max(cint(offset), 0)
    return limit, offset


def parse_json_param(param: Any, param_name: str) -> Any:
    """Parse a JSON parameter if it's a string."""
    if param is None:
        return None
    if isinstance(param, str):
        try:
            return json.loads(param)
        except json.JSONDecodeError:
            frappe.throw(_("{0} must be valid JSON").format(param_name))
    return param


def sanitize_search_query(query: str) -> str:
    """
    Sanitize search query for safe SQL operations.

    Args:
        query: Raw search query

    Returns:
        str: Sanitized query
    """
    if not query:
        return ""

    # Remove special SQL characters
    query = cstr(query).strip()
    query = re.sub(r'[;\'\"\\%_]', ' ', query)

    # Remove extra whitespace
    query = re.sub(r'\s+', ' ', query)

    # Limit length
    return query[:100]


def build_like_conditions(query: str, fields: List[str]) -> tuple:
    """
    Build LIKE conditions for search query.

    Args:
        query: Search query
        fields: Fields to search in

    Returns:
        tuple: (conditions list, values dict)
    """
    if not query:
        return [], {}

    words = query.split()
    conditions = []
    values = {}

    for i, word in enumerate(words):
        word_conditions = []
        param_name = f"word_{i}"
        values[param_name] = f"%{word}%"

        for field in fields:
            word_conditions.append(f"`tab{field}`.`{field.split('.')[-1]}` LIKE %({param_name})s")

        if word_conditions:
            conditions.append(f"({' OR '.join(word_conditions)})")

    return conditions, values


def calculate_relevance_score(product: Dict, query: str) -> float:
    """
    Calculate relevance score for a product based on search query.

    Args:
        product: Product data
        query: Search query

    Returns:
        float: Relevance score (0-100)
    """
    if not query:
        return 0

    query_lower = query.lower()
    words = query_lower.split()
    score = 0

    for field, weight in SEARCHABLE_FIELDS.items():
        value = cstr(product.get(field, "")).lower()
        if not value:
            continue

        # Exact match bonus
        if query_lower in value:
            score += weight * 2

        # Word match
        for word in words:
            if word in value:
                score += weight

            # Starting match bonus
            if value.startswith(word):
                score += weight * 0.5

    # Normalize to 0-100
    max_possible = sum(SEARCHABLE_FIELDS.values()) * 3
    return min(100, (score / max_possible) * 100)


# =============================================================================
# MAIN SEARCH API
# =============================================================================

@frappe.whitelist(allow_guest=True)
def search_products(
    q: str = None,
    category: str = None,
    brand: str = None,
    seller: str = None,
    price_min: float = None,
    price_max: float = None,
    rating_min: float = None,
    in_stock: int = None,
    certificate: str = None,
    attributes: str = None,
    tenant: str = None,
    sort_by: str = "relevance",
    limit: int = None,
    offset: int = None
) -> Dict[str, Any]:
    """
    Search products with faceted filtering.

    This is the primary search endpoint for the marketplace. It supports
    full-text search, multiple filter types, sorting, and pagination.

    Args:
        q: Search query (searches in name, SKU, description, keywords)
        category: Filter by Product Category name (supports hierarchy)
        brand: Filter by Brand name (comma-separated for multiple)
        seller: Filter by Seller Profile name (comma-separated for multiple)
        price_min: Minimum price filter
        price_max: Maximum price filter
        rating_min: Minimum rating filter (1-5)
        in_stock: Filter by stock availability (1=in stock only)
        certificate: Filter by Certificate Type (comma-separated)
        attributes: JSON object of attribute filters {attr_code: [values]}
        tenant: Filter by tenant (auto-detected if not provided)
        sort_by: Sort option (relevance, price_asc, price_desc, newest, etc.)
        limit: Number of results per page (default 20, max 100)
        offset: Starting position for pagination

    Returns:
        dict: {
            "success": True,
            "products": [...],
            "total": int,
            "count": int,
            "limit": int,
            "offset": int,
            "has_more": bool,
            "query": str,
            "filters_applied": {...},
            "sort": str
        }
    """
    limit, offset = validate_page_params(limit, offset)

    # Sanitize and validate query
    search_query = sanitize_search_query(q) if q else ""

    # Build base filters
    filters = {
        "status": "Active",
        "is_published": 1
    }

    # Apply tenant filter
    if tenant:
        filters["tenant"] = tenant
    elif not frappe.session.user == "Guest":
        current_tenant = get_current_tenant()
        if current_tenant:
            filters["tenant"] = current_tenant

    # Build filter tracking
    filters_applied = {}

    # Category filter (including subcategories)
    category_list = None
    if category:
        category_list = get_category_with_descendants(category)
        filters_applied["category"] = category

    # Brand filter
    brand_list = None
    if brand:
        brand_list = [b.strip() for b in brand.split(",") if b.strip()]
        filters_applied["brand"] = brand_list

    # Seller filter
    seller_list = None
    if seller:
        seller_list = [s.strip() for s in seller.split(",") if s.strip()]
        filters_applied["seller"] = seller_list

    # Price filter
    if price_min is not None:
        filters_applied["price_min"] = flt(price_min)
    if price_max is not None:
        filters_applied["price_max"] = flt(price_max)

    # Rating filter
    if rating_min is not None:
        filters_applied["rating_min"] = flt(rating_min)

    # Stock filter
    if cint(in_stock):
        filters_applied["in_stock"] = True

    # Certificate filter
    cert_list = None
    if certificate:
        cert_list = [c.strip() for c in certificate.split(",") if c.strip()]
        filters_applied["certificate"] = cert_list

    # Attribute filters
    attr_filters = parse_json_param(attributes, "attributes") if attributes else None
    if attr_filters:
        filters_applied["attributes"] = attr_filters

    # Validate sort option
    if sort_by not in SORT_OPTIONS:
        sort_by = "relevance"

    # Build and execute search query
    products, total = execute_product_search(
        search_query=search_query,
        filters=filters,
        category_list=category_list,
        brand_list=brand_list,
        seller_list=seller_list,
        price_min=flt(price_min) if price_min is not None else None,
        price_max=flt(price_max) if price_max is not None else None,
        rating_min=flt(rating_min) if rating_min is not None else None,
        in_stock=cint(in_stock),
        cert_list=cert_list,
        attr_filters=attr_filters,
        sort_by=sort_by,
        limit=limit,
        offset=offset
    )

    # Calculate relevance scores if sorting by relevance
    if sort_by == "relevance" and search_query:
        for product in products:
            product["_relevance_score"] = calculate_relevance_score(product, search_query)
        products.sort(key=lambda x: x.get("_relevance_score", 0), reverse=True)

    has_more = total > offset + limit

    # Track search query
    if search_query and len(search_query) >= MIN_SEARCH_LENGTH:
        track_search_query(search_query, total)

    return {
        "success": True,
        "products": products,
        "total": total,
        "count": len(products),
        "limit": limit,
        "offset": offset,
        "has_more": has_more,
        "query": search_query,
        "filters_applied": filters_applied,
        "sort": sort_by
    }


def execute_product_search(
    search_query: str,
    filters: Dict,
    category_list: List[str] = None,
    brand_list: List[str] = None,
    seller_list: List[str] = None,
    price_min: float = None,
    price_max: float = None,
    rating_min: float = None,
    in_stock: int = 0,
    cert_list: List[str] = None,
    attr_filters: Dict = None,
    sort_by: str = "relevance",
    limit: int = DEFAULT_PAGE_SIZE,
    offset: int = 0
) -> tuple:
    """
    Execute the product search query.

    Args:
        search_query: Text search query
        filters: Base filters dict
        category_list: List of category names
        brand_list: List of brand names
        seller_list: List of seller names
        price_min: Minimum price
        price_max: Maximum price
        rating_min: Minimum rating
        in_stock: Stock filter
        cert_list: Certificate filter list
        attr_filters: Attribute filters
        sort_by: Sort option
        limit: Page size
        offset: Starting position

    Returns:
        tuple: (products list, total count)
    """
    # Build SQL query
    conditions = []
    values = {}

    # Base filters
    conditions.append("`tabSKU Product`.`status` = 'Active'")
    conditions.append("`tabSKU Product`.`is_published` = 1")

    # Tenant filter
    if filters.get("tenant"):
        conditions.append("`tabSKU Product`.`tenant` = %(tenant)s")
        values["tenant"] = filters["tenant"]

    # Text search
    if search_query:
        search_conditions = []
        values["search_query"] = f"%{search_query}%"

        search_fields = [
            "product_name", "sku_code", "product_description",
            "seo_keywords", "brand_name", "seller_name", "category_name"
        ]
        for field in search_fields:
            search_conditions.append(f"`tabSKU Product`.`{field}` LIKE %(search_query)s")

        conditions.append(f"({' OR '.join(search_conditions)})")

    # Category filter
    if category_list:
        placeholders = ", ".join([f"%(cat_{i})s" for i in range(len(category_list))])
        conditions.append(f"`tabSKU Product`.`category` IN ({placeholders})")
        for i, cat in enumerate(category_list):
            values[f"cat_{i}"] = cat

    # Brand filter
    if brand_list:
        placeholders = ", ".join([f"%(brand_{i})s" for i in range(len(brand_list))])
        conditions.append(f"`tabSKU Product`.`brand` IN ({placeholders})")
        for i, brand in enumerate(brand_list):
            values[f"brand_{i}"] = brand

    # Seller filter
    if seller_list:
        placeholders = ", ".join([f"%(seller_{i})s" for i in range(len(seller_list))])
        conditions.append(f"`tabSKU Product`.`seller` IN ({placeholders})")
        for i, seller in enumerate(seller_list):
            values[f"seller_{i}"] = seller

    # Price filter
    if price_min is not None:
        conditions.append("`tabSKU Product`.`base_price` >= %(price_min)s")
        values["price_min"] = price_min
    if price_max is not None:
        conditions.append("`tabSKU Product`.`base_price` <= %(price_max)s")
        values["price_max"] = price_max

    # Rating filter
    if rating_min is not None:
        conditions.append("COALESCE(`tabSKU Product`.`average_rating`, 0) >= %(rating_min)s")
        values["rating_min"] = rating_min

    # Stock filter
    if in_stock:
        conditions.append("""
            (`tabSKU Product`.`is_stock_item` = 0
             OR `tabSKU Product`.`stock_quantity` > 0
             OR `tabSKU Product`.`allow_negative_stock` = 1)
        """)

    # Certificate filter (products that have at least one of the certificates)
    if cert_list:
        cert_placeholders = ", ".join([f"%(cert_{i})s" for i in range(len(cert_list))])
        conditions.append(f"""
            EXISTS (
                SELECT 1 FROM `tabProduct Certificate` pc
                WHERE pc.parent = `tabSKU Product`.`name`
                AND pc.certificate_type IN ({cert_placeholders})
            )
        """)
        for i, cert in enumerate(cert_list):
            values[f"cert_{i}"] = cert

    # Attribute filters
    if attr_filters:
        for attr_code, attr_values in attr_filters.items():
            if not isinstance(attr_values, list):
                attr_values = [attr_values]

            # Get attribute name from code
            attr_name = frappe.db.get_value(
                "Product Attribute",
                {"attribute_code": attr_code},
                "name"
            )

            if attr_name and attr_values:
                attr_param = attr_code.replace("-", "_")
                val_placeholders = ", ".join([
                    f"%({attr_param}_{i})s" for i in range(len(attr_values))
                ])

                conditions.append(f"""
                    EXISTS (
                        SELECT 1 FROM `tabProduct Variant` pv
                        WHERE pv.sku_product = `tabSKU Product`.`name`
                        AND pv.status = 'Active'
                        AND (
                            pv.color IN ({val_placeholders})
                            OR pv.size IN ({val_placeholders})
                            OR pv.material IN ({val_placeholders})
                        )
                    )
                """)
                for i, val in enumerate(attr_values):
                    values[f"{attr_param}_{i}"] = val

    # Build WHERE clause
    where_clause = " AND ".join(conditions) if conditions else "1=1"

    # Get total count
    count_query = f"""
        SELECT COUNT(DISTINCT `tabSKU Product`.`name`) as total
        FROM `tabSKU Product`
        WHERE {where_clause}
    """
    total_result = frappe.db.sql(count_query, values, as_dict=True)
    total = total_result[0].total if total_result else 0

    # Build ORDER BY clause
    sort_config = SORT_OPTIONS.get(sort_by, SORT_OPTIONS["relevance"])
    if sort_by == "relevance" and search_query:
        # For relevance, we'll sort in Python after calculating scores
        order_clause = "`tabSKU Product`.`creation` DESC"
    else:
        order_clause = f"`tabSKU Product`.`{sort_config['field']}` {sort_config['order'].upper()}"

    # Get products
    select_fields = """
        `tabSKU Product`.`name`,
        `tabSKU Product`.`product_name`,
        `tabSKU Product`.`sku_code`,
        `tabSKU Product`.`url_slug`,
        `tabSKU Product`.`product_description`,
        `tabSKU Product`.`short_description`,
        `tabSKU Product`.`category`,
        `tabSKU Product`.`category_name`,
        `tabSKU Product`.`brand`,
        `tabSKU Product`.`brand_name`,
        `tabSKU Product`.`seller`,
        `tabSKU Product`.`seller_name`,
        `tabSKU Product`.`base_price`,
        `tabSKU Product`.`currency`,
        `tabSKU Product`.`min_order_quantity`,
        `tabSKU Product`.`stock_quantity`,
        `tabSKU Product`.`is_stock_item`,
        `tabSKU Product`.`allow_negative_stock`,
        `tabSKU Product`.`average_rating`,
        `tabSKU Product`.`total_reviews`,
        `tabSKU Product`.`total_orders`,
        `tabSKU Product`.`primary_image`,
        `tabSKU Product`.`seo_title`,
        `tabSKU Product`.`tenant`,
        `tabSKU Product`.`creation`
    """

    product_query = f"""
        SELECT {select_fields}
        FROM `tabSKU Product`
        WHERE {where_clause}
        ORDER BY {order_clause}
        LIMIT %(limit)s OFFSET %(offset)s
    """
    values["limit"] = limit
    values["offset"] = offset

    products = frappe.db.sql(product_query, values, as_dict=True)

    # Enhance product data
    for product in products:
        # Add stock availability flag
        product["in_stock"] = (
            not product.get("is_stock_item") or
            flt(product.get("stock_quantity", 0)) > 0 or
            product.get("allow_negative_stock")
        )

        # Format price
        if product.get("base_price"):
            product["formatted_price"] = frappe.format_value(
                product["base_price"],
                {"fieldtype": "Currency", "options": product.get("currency", "USD")}
            )

    return products, total


def get_category_with_descendants(category: str) -> List[str]:
    """
    Get category and all its descendant categories.

    Args:
        category: Parent category name

    Returns:
        list: Category names including descendants
    """
    categories = [category]

    # Get child categories recursively
    children = frappe.get_all(
        "Product Category",
        filters={"parent_product_category": category, "enabled": 1},
        pluck="name"
    )

    for child in children:
        categories.extend(get_category_with_descendants(child))

    return categories


# =============================================================================
# FACETED FILTERING APIs
# =============================================================================

@frappe.whitelist(allow_guest=True)
def get_search_facets(
    q: str = None,
    category: str = None,
    brand: str = None,
    seller: str = None,
    price_min: float = None,
    price_max: float = None,
    tenant: str = None
) -> Dict[str, Any]:
    """
    Get available facets and their counts for the current search.

    This endpoint returns the filter options with product counts,
    allowing the frontend to display dynamic faceted navigation.

    Args:
        q: Search query
        category: Current category filter
        brand: Current brand filter
        seller: Current seller filter
        price_min: Current price minimum
        price_max: Current price maximum
        tenant: Tenant filter

    Returns:
        dict: {
            "success": True,
            "facets": {
                "categories": [...],
                "brands": [...],
                "sellers": [...],
                "price_range": {...},
                "ratings": [...],
                "certificates": [...]
            }
        }
    """
    # Build base filters
    base_conditions = [
        "`tabSKU Product`.`status` = 'Active'",
        "`tabSKU Product`.`is_published` = 1"
    ]
    values = {}

    # Apply tenant filter
    if tenant:
        base_conditions.append("`tabSKU Product`.`tenant` = %(tenant)s")
        values["tenant"] = tenant
    elif not frappe.session.user == "Guest":
        current_tenant = get_current_tenant()
        if current_tenant:
            base_conditions.append("`tabSKU Product`.`tenant` = %(tenant)s")
            values["tenant"] = current_tenant

    # Apply search query
    if q:
        search_query = sanitize_search_query(q)
        if search_query:
            values["search_query"] = f"%{search_query}%"
            search_fields = [
                "product_name", "sku_code", "product_description",
                "seo_keywords", "brand_name", "seller_name"
            ]
            search_conditions = [f"`tabSKU Product`.`{f}` LIKE %(search_query)s" for f in search_fields]
            base_conditions.append(f"({' OR '.join(search_conditions)})")

    where_clause = " AND ".join(base_conditions)

    # Get facets
    facets = {
        "categories": get_category_facets(where_clause, values, category),
        "brands": get_brand_facets(where_clause, values, brand),
        "sellers": get_seller_facets(where_clause, values, seller),
        "price_range": get_price_range_facet(where_clause, values),
        "ratings": get_rating_facets(where_clause, values),
        "certificates": get_certificate_facets(where_clause, values),
        "stock_status": get_stock_status_facets(where_clause, values)
    }

    # Get filter configs if category is specified
    if category:
        facets["filter_configs"] = get_category_filter_configs(category, tenant)

    return {
        "success": True,
        "facets": facets
    }


def get_category_facets(where_clause: str, values: Dict, current_category: str = None) -> List[Dict]:
    """Get category facets with counts."""
    query = f"""
        SELECT
            `tabSKU Product`.`category` as value,
            `tabSKU Product`.`category_name` as label,
            COUNT(*) as count
        FROM `tabSKU Product`
        WHERE {where_clause}
        AND `tabSKU Product`.`category` IS NOT NULL
        GROUP BY `tabSKU Product`.`category`, `tabSKU Product`.`category_name`
        ORDER BY count DESC
        LIMIT 50
    """
    results = frappe.db.sql(query, values, as_dict=True)

    # Mark selected
    for r in results:
        r["selected"] = r["value"] == current_category if current_category else False

    return results


def get_brand_facets(where_clause: str, values: Dict, current_brands: str = None) -> List[Dict]:
    """Get brand facets with counts."""
    current_brand_list = [b.strip() for b in current_brands.split(",")] if current_brands else []

    query = f"""
        SELECT
            `tabSKU Product`.`brand` as value,
            `tabSKU Product`.`brand_name` as label,
            COUNT(*) as count
        FROM `tabSKU Product`
        WHERE {where_clause}
        AND `tabSKU Product`.`brand` IS NOT NULL
        GROUP BY `tabSKU Product`.`brand`, `tabSKU Product`.`brand_name`
        ORDER BY count DESC
        LIMIT 50
    """
    results = frappe.db.sql(query, values, as_dict=True)

    # Mark selected
    for r in results:
        r["selected"] = r["value"] in current_brand_list

    return results


def get_seller_facets(where_clause: str, values: Dict, current_sellers: str = None) -> List[Dict]:
    """Get seller facets with counts."""
    current_seller_list = [s.strip() for s in current_sellers.split(",")] if current_sellers else []

    query = f"""
        SELECT
            `tabSKU Product`.`seller` as value,
            `tabSKU Product`.`seller_name` as label,
            COUNT(*) as count
        FROM `tabSKU Product`
        WHERE {where_clause}
        AND `tabSKU Product`.`seller` IS NOT NULL
        GROUP BY `tabSKU Product`.`seller`, `tabSKU Product`.`seller_name`
        ORDER BY count DESC
        LIMIT 50
    """
    results = frappe.db.sql(query, values, as_dict=True)

    # Mark selected
    for r in results:
        r["selected"] = r["value"] in current_seller_list

    return results


def get_price_range_facet(where_clause: str, values: Dict) -> Dict:
    """Get price range statistics."""
    query = f"""
        SELECT
            MIN(`tabSKU Product`.`base_price`) as min_price,
            MAX(`tabSKU Product`.`base_price`) as max_price,
            AVG(`tabSKU Product`.`base_price`) as avg_price
        FROM `tabSKU Product`
        WHERE {where_clause}
        AND `tabSKU Product`.`base_price` > 0
    """
    result = frappe.db.sql(query, values, as_dict=True)

    if result and result[0].get("min_price") is not None:
        return {
            "min": flt(result[0]["min_price"]),
            "max": flt(result[0]["max_price"]),
            "avg": flt(result[0]["avg_price"]),
            "step": 1
        }

    return {"min": 0, "max": 10000, "avg": 0, "step": 1}


def get_rating_facets(where_clause: str, values: Dict) -> List[Dict]:
    """Get rating distribution."""
    rating_ranges = [
        {"min": 4, "label": "4 Stars & Up"},
        {"min": 3, "label": "3 Stars & Up"},
        {"min": 2, "label": "2 Stars & Up"},
        {"min": 1, "label": "1 Star & Up"}
    ]

    results = []
    for rating in rating_ranges:
        query = f"""
            SELECT COUNT(*) as count
            FROM `tabSKU Product`
            WHERE {where_clause}
            AND COALESCE(`tabSKU Product`.`average_rating`, 0) >= %(min_rating)s
        """
        count_values = {**values, "min_rating": rating["min"]}
        count_result = frappe.db.sql(query, count_values, as_dict=True)

        results.append({
            "value": rating["min"],
            "label": rating["label"],
            "count": count_result[0]["count"] if count_result else 0
        })

    return results


def get_certificate_facets(where_clause: str, values: Dict) -> List[Dict]:
    """Get certificate type facets."""
    query = f"""
        SELECT
            pc.certificate_type as value,
            ct.certificate_name as label,
            COUNT(DISTINCT `tabSKU Product`.`name`) as count
        FROM `tabSKU Product`
        INNER JOIN `tabProduct Certificate` pc ON pc.parent = `tabSKU Product`.`name`
        INNER JOIN `tabCertificate Type` ct ON ct.name = pc.certificate_type
        WHERE {where_clause}
        GROUP BY pc.certificate_type, ct.certificate_name
        ORDER BY count DESC
        LIMIT 20
    """
    try:
        results = frappe.db.sql(query, values, as_dict=True)
        return results
    except Exception:
        # Table might not exist yet
        return []


def get_stock_status_facets(where_clause: str, values: Dict) -> List[Dict]:
    """Get stock status facets."""
    in_stock_query = f"""
        SELECT COUNT(*) as count
        FROM `tabSKU Product`
        WHERE {where_clause}
        AND (
            `tabSKU Product`.`is_stock_item` = 0
            OR `tabSKU Product`.`stock_quantity` > 0
            OR `tabSKU Product`.`allow_negative_stock` = 1
        )
    """
    in_stock_result = frappe.db.sql(in_stock_query, values, as_dict=True)

    out_of_stock_query = f"""
        SELECT COUNT(*) as count
        FROM `tabSKU Product`
        WHERE {where_clause}
        AND `tabSKU Product`.`is_stock_item` = 1
        AND `tabSKU Product`.`stock_quantity` <= 0
        AND `tabSKU Product`.`allow_negative_stock` = 0
    """
    out_of_stock_result = frappe.db.sql(out_of_stock_query, values, as_dict=True)

    return [
        {
            "value": "in_stock",
            "label": "In Stock",
            "count": in_stock_result[0]["count"] if in_stock_result else 0
        },
        {
            "value": "out_of_stock",
            "label": "Out of Stock",
            "count": out_of_stock_result[0]["count"] if out_of_stock_result else 0
        }
    ]


def get_category_filter_configs(category: str, tenant: str = None) -> List[Dict]:
    """Get filter configurations for a category."""
    try:
        from tr_tradehub.trade_hub.doctype.filter_config.filter_config import get_filters_for_category
        return get_filters_for_category(category, tenant)
    except Exception:
        return []


# =============================================================================
# SEARCH SUGGESTIONS AND AUTOCOMPLETE
# =============================================================================

@frappe.whitelist(allow_guest=True)
def get_search_suggestions(
    q: str,
    limit: int = None,
    tenant: str = None
) -> Dict[str, Any]:
    """
    Get search suggestions for autocomplete.

    Returns product name suggestions, category matches, and brand matches
    based on the partial search query.

    Args:
        q: Partial search query (min 2 characters)
        limit: Maximum number of suggestions (default 10)
        tenant: Tenant filter

    Returns:
        dict: {
            "success": True,
            "suggestions": {
                "products": [...],
                "categories": [...],
                "brands": [...]
            }
        }
    """
    if not q or len(q) < MIN_SEARCH_LENGTH:
        return {
            "success": True,
            "suggestions": {
                "products": [],
                "categories": [],
                "brands": []
            }
        }

    limit = min(cint(limit) or MAX_SUGGESTIONS, MAX_SUGGESTIONS)
    search_query = sanitize_search_query(q)

    # Build tenant filter
    tenant_condition = ""
    values = {"query": f"%{search_query}%", "limit": limit}

    if tenant:
        tenant_condition = "AND `tabSKU Product`.`tenant` = %(tenant)s"
        values["tenant"] = tenant
    elif not frappe.session.user == "Guest":
        current_tenant = get_current_tenant()
        if current_tenant:
            tenant_condition = "AND `tabSKU Product`.`tenant` = %(tenant)s"
            values["tenant"] = current_tenant

    # Get product suggestions
    product_query = f"""
        SELECT DISTINCT
            `tabSKU Product`.`name`,
            `tabSKU Product`.`product_name`,
            `tabSKU Product`.`sku_code`,
            `tabSKU Product`.`url_slug`,
            `tabSKU Product`.`primary_image`,
            `tabSKU Product`.`base_price`,
            `tabSKU Product`.`currency`
        FROM `tabSKU Product`
        WHERE `tabSKU Product`.`status` = 'Active'
        AND `tabSKU Product`.`is_published` = 1
        AND (
            `tabSKU Product`.`product_name` LIKE %(query)s
            OR `tabSKU Product`.`sku_code` LIKE %(query)s
        )
        {tenant_condition}
        ORDER BY
            CASE
                WHEN `tabSKU Product`.`product_name` LIKE %(query_start)s THEN 1
                WHEN `tabSKU Product`.`sku_code` LIKE %(query_start)s THEN 2
                ELSE 3
            END,
            `tabSKU Product`.`product_name`
        LIMIT %(limit)s
    """
    values["query_start"] = f"{search_query}%"
    products = frappe.db.sql(product_query, values, as_dict=True)

    # Get category suggestions
    category_query = """
        SELECT DISTINCT
            `tabProduct Category`.`name`,
            `tabProduct Category`.`category_name`
        FROM `tabProduct Category`
        WHERE `tabProduct Category`.`enabled` = 1
        AND `tabProduct Category`.`category_name` LIKE %(query)s
        ORDER BY `tabProduct Category`.`category_name`
        LIMIT %(limit)s
    """
    categories = frappe.db.sql(category_query, values, as_dict=True)

    # Get brand suggestions
    brand_query = """
        SELECT DISTINCT
            `tabBrand`.`name`,
            `tabBrand`.`brand_name`,
            `tabBrand`.`logo`
        FROM `tabBrand`
        WHERE `tabBrand`.`enabled` = 1
        AND `tabBrand`.`brand_name` LIKE %(query)s
        ORDER BY `tabBrand`.`brand_name`
        LIMIT %(limit)s
    """
    brands = frappe.db.sql(brand_query, values, as_dict=True)

    return {
        "success": True,
        "suggestions": {
            "products": products,
            "categories": categories,
            "brands": brands
        }
    }


@frappe.whitelist(allow_guest=True)
def get_popular_searches(
    limit: int = None,
    tenant: str = None
) -> Dict[str, Any]:
    """
    Get popular search terms.

    Returns the most frequently searched terms, useful for
    displaying trending searches on the homepage.

    Args:
        limit: Maximum number of results (default 10)
        tenant: Tenant filter

    Returns:
        dict: {
            "success": True,
            "searches": [
                {"query": "...", "count": int},
                ...
            ]
        }
    """
    limit = min(cint(limit) or 10, POPULAR_SEARCH_LIMIT)

    filters = {}
    if tenant:
        filters["tenant"] = tenant
    elif not frappe.session.user == "Guest":
        current_tenant = get_current_tenant()
        if current_tenant:
            filters["tenant"] = current_tenant

    # Check if Search Log DocType exists
    if not frappe.db.exists("DocType", "Search Log"):
        # Return empty list if tracking not enabled
        return {
            "success": True,
            "searches": []
        }

    try:
        searches = frappe.get_all(
            "Search Log",
            filters=filters,
            fields=["search_query as query", "SUM(search_count) as count"],
            group_by="search_query",
            order_by="count desc",
            limit=limit
        )

        return {
            "success": True,
            "searches": searches
        }
    except Exception:
        return {
            "success": True,
            "searches": []
        }


def track_search_query(query: str, result_count: int):
    """
    Track a search query for analytics.

    Args:
        query: Search query
        result_count: Number of results found
    """
    # Check if Search Log DocType exists
    if not frappe.db.exists("DocType", "Search Log"):
        return

    try:
        # Get current tenant
        tenant = None
        if not frappe.session.user == "Guest":
            tenant = get_current_tenant()

        # Check for existing log today
        existing = frappe.db.get_value(
            "Search Log",
            {
                "search_query": query.lower(),
                "search_date": nowdate(),
                "tenant": tenant
            },
            "name"
        )

        if existing:
            # Increment count
            frappe.db.set_value(
                "Search Log", existing,
                "search_count", frappe.db.get_value("Search Log", existing, "search_count") + 1,
                update_modified=False
            )
        else:
            # Create new log
            doc = frappe.get_doc({
                "doctype": "Search Log",
                "search_query": query.lower(),
                "search_date": nowdate(),
                "result_count": result_count,
                "search_count": 1,
                "tenant": tenant
            })
            doc.insert(ignore_permissions=True)

        frappe.db.commit()
    except Exception:
        # Don't fail search if tracking fails
        pass


# =============================================================================
# UTILITY APIs
# =============================================================================

@frappe.whitelist(allow_guest=True)
def get_search_config() -> Dict[str, Any]:
    """
    Get search configuration options.

    Returns available sort options and configuration for the search UI.

    Returns:
        dict: Configuration options
    """
    return {
        "success": True,
        "config": {
            "sort_options": [
                {"value": key, "label": val["label"]}
                for key, val in SORT_OPTIONS.items()
            ],
            "default_sort": "relevance",
            "page_size": DEFAULT_PAGE_SIZE,
            "max_page_size": MAX_PAGE_SIZE,
            "min_search_length": MIN_SEARCH_LENGTH,
            "max_suggestions": MAX_SUGGESTIONS
        }
    }


@frappe.whitelist(allow_guest=True)
def get_product_by_slug(slug: str) -> Dict[str, Any]:
    """
    Get a product by its URL slug.

    Args:
        slug: Product URL slug

    Returns:
        dict: Product details
    """
    if not slug:
        frappe.throw(_("Product slug is required"))

    # Get tenant filter
    tenant_filter = {}
    if not frappe.session.user == "Guest":
        current_tenant = get_current_tenant()
        if current_tenant:
            tenant_filter["tenant"] = current_tenant

    product_name = frappe.db.get_value(
        "SKU Product",
        {"url_slug": slug, "status": "Active", "is_published": 1, **tenant_filter},
        "name"
    )

    if not product_name:
        return {
            "success": False,
            "message": _("Product not found")
        }

    product = frappe.get_doc("SKU Product", product_name)

    return {
        "success": True,
        "product": product.as_dict()
    }


@frappe.whitelist(allow_guest=True)
def get_related_products(
    product: str,
    limit: int = None
) -> Dict[str, Any]:
    """
    Get related products based on category and attributes.

    Args:
        product: Product name or SKU
        limit: Maximum number of results (default 10)

    Returns:
        dict: Related products list
    """
    limit = min(cint(limit) or 10, 20)

    # Get product details
    product_data = frappe.db.get_value(
        "SKU Product",
        product,
        ["category", "brand", "seller", "tenant", "base_price"],
        as_dict=True
    )

    if not product_data:
        return {
            "success": False,
            "message": _("Product not found")
        }

    # Build filters
    filters = {
        "status": "Active",
        "is_published": 1,
        "name": ["!=", product]
    }

    if product_data.get("tenant"):
        filters["tenant"] = product_data["tenant"]

    # First try same category
    if product_data.get("category"):
        filters["category"] = product_data["category"]

    related = frappe.get_all(
        "SKU Product",
        filters=filters,
        fields=[
            "name", "product_name", "sku_code", "url_slug",
            "primary_image", "base_price", "currency",
            "average_rating", "total_reviews"
        ],
        order_by="total_orders desc",
        limit=limit
    )

    # If not enough, try same brand
    if len(related) < limit and product_data.get("brand"):
        del filters["category"]
        filters["brand"] = product_data["brand"]
        filters["name"] = ["not in", [product] + [r["name"] for r in related]]

        more = frappe.get_all(
            "SKU Product",
            filters=filters,
            fields=[
                "name", "product_name", "sku_code", "url_slug",
                "primary_image", "base_price", "currency",
                "average_rating", "total_reviews"
            ],
            order_by="total_orders desc",
            limit=limit - len(related)
        )
        related.extend(more)

    return {
        "success": True,
        "products": related,
        "count": len(related)
    }

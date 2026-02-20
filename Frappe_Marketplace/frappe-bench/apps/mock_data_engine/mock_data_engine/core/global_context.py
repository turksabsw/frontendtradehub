# Copyright (c) 2024, Mock Data Engine and contributors
# For license information, please see license.txt

"""
Global Context Manager for Cross-DocType Consistency.

This module provides a GlobalContextManager class that maintains shared
context across all DocTypes during mock data generation. This ensures
consistency across related records in the tr_tradehub app.

Key Features:
- Shared entity tracking (Organizations, Sellers, Buyers, Products)
- Cross-DocType relationship consistency
- Master data context sharing
- Industry-specific context propagation
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, List, Optional, Set, TYPE_CHECKING

if TYPE_CHECKING:
    from mock_data_engine.core.record_cache import RecordCache


class GlobalContextManager:
    """
    Manages global context for cross-DocType consistency.
    
    This class tracks shared entities (Organizations, Sellers, Buyers, Products)
    and provides context to AI generation to ensure consistency across all
    DocTypes in the tr_tradehub app.
    
    Example:
        >>> context = GlobalContextManager(seed=42)
        >>> context.add_organization("ORG-001", {"name": "ABC Ltd", "city": "Istanbul"})
        >>> context.get_organization_context()
        "Organizations: ABC Ltd (Istanbul), ..."
    """
    
    # Master DocTypes that should be generated first
    MASTER_DOCTYPES = {
        "Organization",
        "Tenant",
        "Seller Profile",
        "Buyer Profile",
        "Category",
        "Brand",
        "Listing",
        "Product Class",
    }
    
    # DocType groups for consistency
    DOCTYPE_GROUPS = {
        "organizations": ["Organization", "Tenant"],
        "profiles": ["Seller Profile", "Buyer Profile", "Organization Member"],
        "products": ["Listing", "PIM Product", "SKU", "Product Variant"],
        "orders": ["Order", "Sub Order", "Order Item", "Marketplace Order"],
        "rfq": ["RFQ", "RFQ Quote", "RFQ Item", "Quotation"],
        "communications": ["Message Thread", "Message", "RFQ Message"],
    }
    
    def __init__(self, seed: Optional[int] = None):
        """
        Initialize the GlobalContextManager.
        
        Args:
            seed: Optional random seed for reproducibility
        """
        self._seed = seed
        
        # Track organizations
        self._organizations: Dict[str, Dict[str, Any]] = {}
        
        # Track seller profiles
        self._seller_profiles: Dict[str, Dict[str, Any]] = {}
        
        # Track buyer profiles
        self._buyer_profiles: Dict[str, Dict[str, Any]] = {}
        
        # Track listings/products
        self._listings: Dict[str, Dict[str, Any]] = {}
        
        # Track categories
        self._categories: Dict[str, Dict[str, Any]] = {}
        
        # Track brands
        self._brands: Dict[str, Dict[str, Any]] = {}
        
        # Track tenants
        self._tenants: Dict[str, Dict[str, Any]] = {}
        
        # Cross-DocType relationships
        self._relationships: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        
        # Industry context
        self._industry_context: Optional[Dict[str, Any]] = None
        
        # Shared entity names (for consistency)
        self._shared_entity_names: Dict[str, List[str]] = defaultdict(list)
    
    def add_organization(self, name: str, data: Dict[str, Any]) -> None:
        """Add an organization to the global context."""
        self._organizations[name] = data
        self._shared_entity_names["organizations"].append(data.get("organization_name") or name)
    
    def add_seller_profile(self, name: str, data: Dict[str, Any]) -> None:
        """Add a seller profile to the global context."""
        self._seller_profiles[name] = data
        self._shared_entity_names["sellers"].append(data.get("seller_name") or name)
        # Link to organization if exists
        if "organization" in data and data["organization"]:
            self._relationships["seller_organization"].append({
                "seller": name,
                "organization": data["organization"]
            })
    
    def add_buyer_profile(self, name: str, data: Dict[str, Any]) -> None:
        """Add a buyer profile to the global context."""
        self._buyer_profiles[name] = data
        self._shared_entity_names["buyers"].append(data.get("buyer_name") or name)
        # Link to organization if exists
        if "organization" in data and data["organization"]:
            self._relationships["buyer_organization"].append({
                "buyer": name,
                "organization": data["organization"]
            })
    
    def add_listing(self, name: str, data: Dict[str, Any]) -> None:
        """Add a listing/product to the global context."""
        self._listings[name] = data
        self._shared_entity_names["products"].append(data.get("title") or data.get("product_name") or name)
        # Link to seller if exists
        if "seller" in data and data["seller"]:
            self._relationships["listing_seller"].append({
                "listing": name,
                "seller": data["seller"]
            })
        # Link to category if exists
        if "category" in data and data["category"]:
            self._relationships["listing_category"].append({
                "listing": name,
                "category": data["category"]
            })
    
    def add_category(self, name: str, data: Dict[str, Any]) -> None:
        """Add a category to the global context."""
        self._categories[name] = data
        self._shared_entity_names["categories"].append(data.get("category_name") or name)
    
    def add_brand(self, name: str, data: Dict[str, Any]) -> None:
        """Add a brand to the global context."""
        self._brands[name] = data
        self._shared_entity_names["brands"].append(data.get("brand_name") or name)
    
    def add_tenant(self, name: str, data: Dict[str, Any]) -> None:
        """Add a tenant to the global context."""
        self._tenants[name] = data
        self._shared_entity_names["tenants"].append(data.get("tenant_name") or name)
    
    def set_industry_context(self, context: Dict[str, Any]) -> None:
        """Set industry-specific context."""
        self._industry_context = context
    
    def get_global_context_string(self, target_doctype: str) -> str:
        """
        Get a comprehensive global context string for AI generation.
        
        This provides all relevant context from other DocTypes to ensure
        consistency when generating data for the target DocType.
        
        Args:
            target_doctype: The DocType being generated
            
        Returns:
            A formatted string with global context
        """
        context_parts = []
        
        # Add industry context
        if self._industry_context:
            industry_name = self._industry_context.get("industry_name", "")
            if industry_name:
                context_parts.append(f"Industry Context: {industry_name}")
                if self._industry_context.get("description"):
                    context_parts.append(f"Industry Description: {self._industry_context['description'][:200]}")
        
        # Add organizations context (relevant for most DocTypes)
        if target_doctype not in ["Organization", "Tenant"]:
            if self._organizations:
                org_names = [data.get("organization_name") or name for name, data in list(self._organizations.items())[:10]]
                if org_names:
                    context_parts.append(f"Available Organizations ({len(self._organizations)}): {', '.join(org_names)}")
        
        # Add seller profiles context (for Order, Listing, RFQ, etc.)
        if target_doctype in ["Order", "Listing", "RFQ", "Quotation", "Sample Request", "Message Thread"]:
            if self._seller_profiles:
                seller_names = [data.get("seller_name") or name for name, data in list(self._seller_profiles.items())[:10]]
                if seller_names:
                    context_parts.append(f"Available Sellers ({len(self._seller_profiles)}): {', '.join(seller_names)}")
                    # Add seller-organization relationships
                    seller_orgs = []
                    for rel in self._relationships.get("seller_organization", [])[:5]:
                        seller_orgs.append(f"{rel['seller']} -> {rel['organization']}")
                    if seller_orgs:
                        context_parts.append(f"Seller-Organization Relationships: {', '.join(seller_orgs)}")
        
        # Add buyer profiles context (for Order, RFQ, Cart, etc.)
        if target_doctype in ["Order", "RFQ", "Cart", "Message Thread", "Review"]:
            if self._buyer_profiles:
                buyer_names = [data.get("buyer_name") or name for name, data in list(self._buyer_profiles.items())[:10]]
                if buyer_names:
                    context_parts.append(f"Available Buyers ({len(self._buyer_profiles)}): {', '.join(buyer_names)}")
        
        # Add listings/products context (for Order Item, Cart Item, Review, etc.)
        if target_doctype in ["Order Item", "Cart Item", "Review", "RFQ Item", "Quotation Item"]:
            if self._listings:
                listing_titles = [data.get("title") or data.get("product_name") or name for name, data in list(self._listings.items())[:10]]
                if listing_titles:
                    context_parts.append(f"Available Products/Listings ({len(self._listings)}): {', '.join(listing_titles)}")
                    # Add listing-seller relationships
                    listing_sellers = []
                    for rel in self._relationships.get("listing_seller", [])[:5]:
                        listing_sellers.append(f"{rel['listing']} -> {rel['seller']}")
                    if listing_sellers:
                        context_parts.append(f"Product-Seller Relationships: {', '.join(listing_sellers)}")
        
        # Add categories context (for Listing, Product, etc.)
        if target_doctype in ["Listing", "PIM Product", "Product Class"]:
            if self._categories:
                category_names = [data.get("category_name") or name for name, data in list(self._categories.items())[:10]]
                if category_names:
                    context_parts.append(f"Available Categories ({len(self._categories)}): {', '.join(category_names)}")
        
        # Add brands context (for Listing, Product, etc.)
        if target_doctype in ["Listing", "PIM Product"]:
            if self._brands:
                brand_names = [data.get("brand_name") or name for name, data in list(self._brands.items())[:10]]
                if brand_names:
                    context_parts.append(f"Available Brands ({len(self._brands)}): {', '.join(brand_names)}")
        
        # Add tenants context (for most DocTypes)
        if target_doctype not in ["Tenant"]:
            if self._tenants:
                tenant_names = [data.get("tenant_name") or name for name, data in list(self._tenants.items())[:5]]
                if tenant_names:
                    context_parts.append(f"Available Tenants ({len(self._tenants)}): {', '.join(tenant_names)}")
        
        if not context_parts:
            return ""
        
        return "\n".join(context_parts)
    
    def sync_from_record_cache(self, record_cache: "RecordCache") -> None:
        """
        Sync global context from RecordCache.
        
        This method extracts relevant entities from the record cache
        and populates the global context for consistency.
        
        Args:
            record_cache: The RecordCache instance to sync from
        """
        # Sync organizations
        org_records = record_cache.get_records("Organization")
        for entry in org_records:
            self.add_organization(entry.name, entry.data)
        
        # Sync tenants
        tenant_records = record_cache.get_records("Tenant")
        for entry in tenant_records:
            self.add_tenant(entry.name, entry.data)
        
        # Sync seller profiles
        seller_records = record_cache.get_records("Seller Profile")
        for entry in seller_records:
            self.add_seller_profile(entry.name, entry.data)
        
        # Sync buyer profiles
        buyer_records = record_cache.get_records("Buyer Profile")
        for entry in buyer_records:
            self.add_buyer_profile(entry.name, entry.data)
        
        # Sync listings
        listing_records = record_cache.get_records("Listing")
        for entry in listing_records:
            self.add_listing(entry.name, entry.data)
        
        # Sync categories
        category_records = record_cache.get_records("Category")
        for entry in category_records:
            self.add_category(entry.name, entry.data)
        
        # Sync brands
        brand_records = record_cache.get_records("Brand")
        for entry in brand_records:
            self.add_brand(entry.name, entry.data)
    
    def get_shared_entity_names(self, entity_type: str) -> List[str]:
        """Get shared entity names for a specific type."""
        return self._shared_entity_names.get(entity_type, []).copy()
    
    def clear(self) -> None:
        """Clear all context."""
        self._organizations.clear()
        self._seller_profiles.clear()
        self._buyer_profiles.clear()
        self._listings.clear()
        self._categories.clear()
        self._brands.clear()
        self._tenants.clear()
        self._relationships.clear()
        self._shared_entity_names.clear()
        self._industry_context = None








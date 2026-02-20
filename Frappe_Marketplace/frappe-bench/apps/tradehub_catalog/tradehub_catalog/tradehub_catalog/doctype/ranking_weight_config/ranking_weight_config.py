# Copyright (c) 2026, TR TradeHub and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from typing import Dict, Optional


class RankingWeightConfig(Document):
    def validate(self):
        """Validate ranking weight configuration"""
        self.validate_weights()
        self.validate_single_default()

    def validate_weights(self):
        """Ensure all weights are valid percentages"""
        weight_fields = [
            'sales_weight', 'view_weight', 'conversion_weight', 'ctr_weight',
            'wishlist_weight', 'review_weight', 'rating_weight',
            'quality_score_weight', 'seller_score_weight', 'recency_weight', 'stock_weight'
        ]

        for field in weight_fields:
            value = getattr(self, field, 0) or 0
            if value < 0 or value > 100:
                frappe.throw(
                    _("{0} must be between 0 and 100").format(
                        self.meta.get_label(field)
                    )
                )

        # Calculate total weight (should ideally sum to 100 for proper normalization)
        total_weight = sum(getattr(self, f, 0) or 0 for f in weight_fields)
        if total_weight > 0 and abs(total_weight - 100) > 0.01:
            frappe.msgprint(
                _("Total weights sum to {0}%. For best results, weights should sum to 100%.").format(
                    round(total_weight, 2)
                ),
                indicator="orange"
            )

    def validate_single_default(self):
        """Ensure only one default config exists per scope"""
        if self.is_default:
            filters = {
                "is_default": 1,
                "name": ["!=", self.name]
            }

            # Check for existing defaults in the same scope
            if self.tenant:
                filters["tenant"] = self.tenant
            elif self.category:
                filters["category"] = self.category
            else:
                filters["tenant"] = ["is", "not set"]
                filters["category"] = ["is", "not set"]

            existing = frappe.get_all("Ranking Weight Config", filters=filters)
            if existing:
                frappe.throw(
                    _("A default configuration already exists for this scope. "
                      "Please deactivate the existing default first.")
                )

    def get_weights_dict(self) -> Dict[str, float]:
        """Return weights as a dictionary for easy access"""
        return {
            "sales": self.sales_weight or 0,
            "views": self.view_weight or 0,
            "conversion": self.conversion_weight or 0,
            "ctr": self.ctr_weight or 0,
            "wishlist": self.wishlist_weight or 0,
            "reviews": self.review_weight or 0,
            "rating": self.rating_weight or 0,
            "quality": self.quality_score_weight or 0,
            "seller": self.seller_score_weight or 0,
            "recency": self.recency_weight or 0,
            "stock": self.stock_weight or 0
        }

    def get_boosts_dict(self) -> Dict[str, float]:
        """Return boost settings as a dictionary"""
        return {
            "featured": self.featured_boost or 0,
            "bestseller": self.bestseller_boost or 0,
            "new_arrival": self.new_arrival_boost or 0,
            "sale": self.sale_boost or 0,
            "new_listing_days": self.new_listing_boost_days or 0,
            "new_listing_amount": self.new_listing_boost_amount or 0
        }

    def get_penalties_dict(self) -> Dict[str, float]:
        """Return penalty settings as a dictionary"""
        return {
            "out_of_stock": self.out_of_stock_penalty or 0,
            "low_rating": self.low_rating_penalty or 0
        }


@frappe.whitelist()
def get_ranking_config(category: str = None, tenant: str = None) -> Optional[Dict]:
    """
    Get the appropriate ranking configuration for the given context.

    Priority:
    1. Category + Tenant specific config
    2. Category specific config
    3. Tenant specific config
    4. Global default config

    Args:
        category: Optional category name
        tenant: Optional tenant name

    Returns:
        dict: Ranking configuration or None
    """
    # Try category + tenant specific
    if category and tenant:
        config = frappe.get_all(
            "Ranking Weight Config",
            filters={
                "category": category,
                "tenant": tenant,
                "is_active": 1
            },
            limit=1
        )
        if config:
            return frappe.get_doc("Ranking Weight Config", config[0].name).as_dict()

    # Try category specific
    if category:
        config = frappe.get_all(
            "Ranking Weight Config",
            filters={
                "category": category,
                "tenant": ["is", "not set"],
                "is_active": 1
            },
            limit=1
        )
        if config:
            return frappe.get_doc("Ranking Weight Config", config[0].name).as_dict()

    # Try tenant specific
    if tenant:
        config = frappe.get_all(
            "Ranking Weight Config",
            filters={
                "tenant": tenant,
                "category": ["is", "not set"],
                "is_active": 1
            },
            limit=1
        )
        if config:
            return frappe.get_doc("Ranking Weight Config", config[0].name).as_dict()

    # Fall back to global default
    config = frappe.get_all(
        "Ranking Weight Config",
        filters={
            "is_default": 1,
            "is_active": 1,
            "tenant": ["is", "not set"],
            "category": ["is", "not set"]
        },
        limit=1
    )
    if config:
        return frappe.get_doc("Ranking Weight Config", config[0].name).as_dict()

    return None


@frappe.whitelist()
def create_default_ranking_config() -> Dict:
    """
    Create a default ranking configuration if none exists.

    Returns:
        dict: The created or existing default configuration
    """
    # Check if default already exists
    existing = frappe.get_all(
        "Ranking Weight Config",
        filters={"is_default": 1, "is_active": 1},
        limit=1
    )

    if existing:
        return {"message": "Default configuration already exists", "name": existing[0].name}

    # Create default config
    config = frappe.get_doc({
        "doctype": "Ranking Weight Config",
        "config_name": "Default Marketplace Ranking",
        "is_active": 1,
        "is_default": 1,
        # Performance weights (55% total)
        "sales_weight": 25,
        "view_weight": 10,
        "conversion_weight": 15,
        "ctr_weight": 5,
        # Engagement weights (20% total)
        "wishlist_weight": 3,
        "review_weight": 5,
        "rating_weight": 12,
        # Quality weights (25% total)
        "quality_score_weight": 10,
        "seller_score_weight": 10,
        "recency_weight": 3,
        "stock_weight": 2,
        # Boosts
        "featured_boost": 15,
        "bestseller_boost": 8,
        "new_arrival_boost": 5,
        "sale_boost": 3,
        "new_listing_boost_days": 14,
        "new_listing_boost_amount": 10,
        # Penalties
        "out_of_stock_penalty": -25,
        "low_rating_penalty": -15,
        # Algorithm settings
        "use_time_decay": 1,
        "decay_half_life_days": 30,
        "normalize_scores": 1,
        "min_orders_for_conversion": 5
    })
    config.insert(ignore_permissions=True)

    return {"message": "Default configuration created", "name": config.name}

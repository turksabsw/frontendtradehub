# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

"""
Reviews & Moderation Module

This module provides:
- Review submission and management
- Seller response handling
- Helpfulness voting
- Content moderation workflow
- Auto-detection of policy violations
- Appeal processing
"""

from tradehub_compliance.tradehub_compliance.reviews.review_manager import (
    submit_review,
    update_review,
    publish_review,
    hide_review,
    delete_review,
    get_reviews_for_listing,
    get_reviews_for_seller
)

from tradehub_compliance.tradehub_compliance.reviews.moderation import (
    create_moderation_case,
    assign_case,
    resolve_case,
    escalate_case,
    submit_appeal
)

__all__ = [
    # Review operations
    'submit_review',
    'update_review',
    'publish_review',
    'hide_review',
    'delete_review',
    'get_reviews_for_listing',
    'get_reviews_for_seller',
    # Moderation operations
    'create_moderation_case',
    'assign_case',
    'resolve_case',
    'escalate_case',
    'submit_appeal'
]

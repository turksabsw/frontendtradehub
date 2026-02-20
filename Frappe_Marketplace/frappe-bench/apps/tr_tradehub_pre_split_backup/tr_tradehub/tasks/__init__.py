# Copyright (c) 2026, Trade Hub and contributors
# For license information, please see license.txt

"""
Trade Hub Background Tasks Package.

This package contains background job modules for the Trade Hub B2B Trading Platform,
including media processing, certificate alerts, and scheduled maintenance tasks.
"""

from tr_tradehub.tasks.media_processor import (
    process_media_asset,
    process_pending_media,
    resize_image,
    convert_to_webp,
    generate_thumbnail,
    optimize_image,
)

from tr_tradehub.tasks.certificate_alerts import (
    check_expiring_certificates,
    process_tenant_certificates,
    get_certificate_expiry_stats,
    get_expiring_certificates_report,
    send_certificate_notification,
    update_expired_certificate_statuses,
)

from tr_tradehub.tasks.buybox_rotation import (
    rotate_buybox,
    rotate_product_buybox,
    get_rotation_statistics,
    get_seller_rotation_history,
    manual_rotate_buybox,
    get_buybox_rotation_stats,
    get_seller_buybox_history,
)

__all__ = [
    # Media processor functions
    "process_media_asset",
    "process_pending_media",
    "resize_image",
    "convert_to_webp",
    "generate_thumbnail",
    "optimize_image",
    # Certificate alerts functions
    "check_expiring_certificates",
    "process_tenant_certificates",
    "get_certificate_expiry_stats",
    "get_expiring_certificates_report",
    "send_certificate_notification",
    "update_expired_certificate_statuses",
    # Buy Box rotation functions
    "rotate_buybox",
    "rotate_product_buybox",
    "get_rotation_statistics",
    "get_seller_rotation_history",
    "manual_rotate_buybox",
    "get_buybox_rotation_stats",
    "get_seller_buybox_history",
]

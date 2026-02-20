# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

"""
Turkish Carrier Integrations for TR-TradeHub Marketplace

This module provides integration utilities for Turkish shipping carriers:

- Yurtici Kargo: Turkey's leading logistics company
- Aras Kargo: Major Turkish cargo carrier
- MNG Kargo: Popular Turkish carrier (future implementation)
- PTT Kargo: Turkish postal service (future implementation)

Each carrier module provides:
- Shipment creation with label generation
- Tracking queries and status updates
- Pickup scheduling
- Webhook/callback handling
- Error handling and logging

Configuration:
    Carrier credentials are stored in site_config.json or
    TR TradeHub Settings DocType:

    site_config.json:
    {
        "yurtici_username": "your-username",
        "yurtici_password": "your-password",
        "yurtici_user_language": "TR",
        "yurtici_customer_code": "your-customer-code",
        "yurtici_base_url": "https://webservices.yurticikargo.com",

        "aras_api_key": "your-api-key",
        "aras_api_secret": "your-api-secret",
        "aras_customer_code": "your-customer-code",
        "aras_base_url": "https://customerservices.araskargo.com.tr"
    }

Usage:
    from tr_tradehub.integrations.carriers import yurtici, aras

    # Create shipment with Yurtici
    result = yurtici.create_shipment(
        shipment="SHP-XXXXXXXXXX",
        sender_info={...},
        receiver_info={...},
        package_info={...}
    )

    # Track shipment with Aras
    result = aras.track_shipment(tracking_number="1234567890")
"""

from tr_tradehub.integrations.carriers.yurtici import (
    YurticiClient,
    YurticiError,
    YurticiAuthenticationError,
    YurticiValidationError,
    YurticiShipmentError,
    create_shipment as yurtici_create_shipment,
    track_shipment as yurtici_track_shipment,
    cancel_shipment as yurtici_cancel_shipment,
    schedule_pickup as yurtici_schedule_pickup,
    get_shipment_info as yurtici_get_shipment_info,
    verify_webhook as yurtici_verify_webhook,
    get_delivery_points as yurtici_get_delivery_points,
)

from tr_tradehub.integrations.carriers.aras import (
    ArasClient,
    ArasError,
    ArasAuthenticationError,
    ArasValidationError,
    ArasShipmentError,
    create_shipment as aras_create_shipment,
    track_shipment as aras_track_shipment,
    cancel_shipment as aras_cancel_shipment,
    schedule_pickup as aras_schedule_pickup,
    get_shipment_info as aras_get_shipment_info,
    verify_callback as aras_verify_callback,
    get_branch_list as aras_get_branch_list,
)


# Carrier type constants
CARRIER_YURTICI = "Yurtici Kargo"
CARRIER_ARAS = "Aras Kargo"
CARRIER_MNG = "MNG Kargo"
CARRIER_PTT = "PTT Kargo"
CARRIER_SURAT = "SuratKargo"
CARRIER_TRENDYOL = "Trendyol Express"
CARRIER_HEPSIJET = "HepsiJet"

# International carriers
CARRIER_UPS = "UPS"
CARRIER_DHL = "DHL"
CARRIER_FEDEX = "FedEx"

# Supported carriers list
SUPPORTED_TURKISH_CARRIERS = [
    CARRIER_YURTICI,
    CARRIER_ARAS,
]

SUPPORTED_INTERNATIONAL_CARRIERS = [
    CARRIER_UPS,
    CARRIER_DHL,
    CARRIER_FEDEX,
]

SUPPORTED_CARRIERS = SUPPORTED_TURKISH_CARRIERS + SUPPORTED_INTERNATIONAL_CARRIERS


def get_carrier_client(carrier_type: str):
    """
    Get carrier client instance.

    Args:
        carrier_type: Carrier identifier (Yurtici Kargo, Aras Kargo, etc.)

    Returns:
        Carrier client instance

    Raises:
        ValueError: If carrier type is not supported
    """
    if carrier_type == CARRIER_YURTICI:
        return YurticiClient()
    elif carrier_type == CARRIER_ARAS:
        return ArasClient()
    else:
        raise ValueError(f"Unsupported carrier: {carrier_type}")


def create_shipment(
    carrier_type: str,
    shipment: str,
    sender_info: dict,
    receiver_info: dict,
    package_info: dict,
    **kwargs,
) -> dict:
    """
    Create shipment through specified carrier.

    Args:
        carrier_type: Carrier to use
        shipment: Marketplace Shipment document name
        sender_info: Sender address and contact details
        receiver_info: Receiver address and contact details
        package_info: Package weight, dimensions, count
        **kwargs: Additional carrier-specific parameters

    Returns:
        dict: Carrier response with tracking number and label URL
    """
    if carrier_type == CARRIER_YURTICI:
        return yurtici_create_shipment(
            shipment=shipment,
            sender_info=sender_info,
            receiver_info=receiver_info,
            package_info=package_info,
            **kwargs
        )
    elif carrier_type == CARRIER_ARAS:
        return aras_create_shipment(
            shipment=shipment,
            sender_info=sender_info,
            receiver_info=receiver_info,
            package_info=package_info,
            **kwargs
        )
    else:
        raise ValueError(f"Unsupported carrier: {carrier_type}")


def track_shipment(
    carrier_type: str,
    tracking_number: str,
) -> dict:
    """
    Track shipment through specified carrier.

    Args:
        carrier_type: Carrier to use
        tracking_number: Carrier tracking number

    Returns:
        dict: Tracking information with events
    """
    if carrier_type == CARRIER_YURTICI:
        return yurtici_track_shipment(tracking_number=tracking_number)
    elif carrier_type == CARRIER_ARAS:
        return aras_track_shipment(tracking_number=tracking_number)
    else:
        raise ValueError(f"Unsupported carrier: {carrier_type}")


def cancel_shipment(
    carrier_type: str,
    tracking_number: str,
    reason: str = None,
) -> dict:
    """
    Cancel shipment through specified carrier.

    Args:
        carrier_type: Carrier to use
        tracking_number: Carrier tracking number
        reason: Cancellation reason

    Returns:
        dict: Cancellation result
    """
    if carrier_type == CARRIER_YURTICI:
        return yurtici_cancel_shipment(
            tracking_number=tracking_number,
            reason=reason
        )
    elif carrier_type == CARRIER_ARAS:
        return aras_cancel_shipment(
            tracking_number=tracking_number,
            reason=reason
        )
    else:
        raise ValueError(f"Unsupported carrier: {carrier_type}")


def get_tracking_url(carrier_type: str, tracking_number: str) -> str:
    """
    Get public tracking URL for a carrier.

    Args:
        carrier_type: Carrier name
        tracking_number: Tracking number

    Returns:
        str: Public tracking URL
    """
    tracking_urls = {
        CARRIER_YURTICI: f"https://www.yurticikargo.com/tr/online-servisler/gonderi-sorgula?code={tracking_number}",
        CARRIER_ARAS: f"https://www.araskargo.com.tr/trmall/kargotakip.aspx?q={tracking_number}",
        CARRIER_MNG: f"https://www.mngkargo.com.tr/gonderi-takip/?no={tracking_number}",
        CARRIER_PTT: f"https://gonderitakip.ptt.gov.tr/?barkod={tracking_number}",
        CARRIER_SURAT: f"https://www.suratkargo.com.tr/gonderi-takip?takipNo={tracking_number}",
        CARRIER_TRENDYOL: f"https://www.trendyol.com/kargo-takip/{tracking_number}",
        CARRIER_HEPSIJET: f"https://www.hepsijet.com/takip/{tracking_number}",
        CARRIER_UPS: f"https://www.ups.com/track?tracknum={tracking_number}",
        CARRIER_DHL: f"https://www.dhl.com/tr-en/home/tracking.html?tracking-id={tracking_number}",
        CARRIER_FEDEX: f"https://www.fedex.com/fedextrack/?tracknumbers={tracking_number}",
    }

    return tracking_urls.get(carrier_type)


def normalize_carrier_name(carrier_name: str) -> str:
    """
    Normalize carrier name to standard format.

    Args:
        carrier_name: Carrier name in various formats

    Returns:
        str: Normalized carrier name
    """
    name_lower = carrier_name.lower().strip()

    normalization_map = {
        "yurtici": CARRIER_YURTICI,
        "yurtici kargo": CARRIER_YURTICI,
        "yurticikargo": CARRIER_YURTICI,
        "yk": CARRIER_YURTICI,
        "aras": CARRIER_ARAS,
        "aras kargo": CARRIER_ARAS,
        "araskargo": CARRIER_ARAS,
        "ak": CARRIER_ARAS,
        "mng": CARRIER_MNG,
        "mng kargo": CARRIER_MNG,
        "ptt": CARRIER_PTT,
        "ptt kargo": CARRIER_PTT,
        "surat": CARRIER_SURAT,
        "suratkargo": CARRIER_SURAT,
        "surat kargo": CARRIER_SURAT,
        "trendyol": CARRIER_TRENDYOL,
        "trendyol express": CARRIER_TRENDYOL,
        "hepsijet": CARRIER_HEPSIJET,
        "ups": CARRIER_UPS,
        "dhl": CARRIER_DHL,
        "fedex": CARRIER_FEDEX,
    }

    return normalization_map.get(name_lower, carrier_name)


def is_carrier_supported(carrier_type: str) -> bool:
    """
    Check if carrier is supported for API integration.

    Args:
        carrier_type: Carrier name

    Returns:
        bool: True if carrier has API integration
    """
    normalized = normalize_carrier_name(carrier_type)
    return normalized in SUPPORTED_TURKISH_CARRIERS


__all__ = [
    # Constants
    "CARRIER_YURTICI",
    "CARRIER_ARAS",
    "CARRIER_MNG",
    "CARRIER_PTT",
    "CARRIER_SURAT",
    "CARRIER_TRENDYOL",
    "CARRIER_HEPSIJET",
    "CARRIER_UPS",
    "CARRIER_DHL",
    "CARRIER_FEDEX",
    "SUPPORTED_TURKISH_CARRIERS",
    "SUPPORTED_INTERNATIONAL_CARRIERS",
    "SUPPORTED_CARRIERS",

    # Factory functions
    "get_carrier_client",
    "create_shipment",
    "track_shipment",
    "cancel_shipment",
    "get_tracking_url",
    "normalize_carrier_name",
    "is_carrier_supported",

    # Yurtici exports
    "YurticiClient",
    "YurticiError",
    "YurticiAuthenticationError",
    "YurticiValidationError",
    "YurticiShipmentError",
    "yurtici_create_shipment",
    "yurtici_track_shipment",
    "yurtici_cancel_shipment",
    "yurtici_schedule_pickup",
    "yurtici_get_shipment_info",
    "yurtici_verify_webhook",
    "yurtici_get_delivery_points",

    # Aras exports
    "ArasClient",
    "ArasError",
    "ArasAuthenticationError",
    "ArasValidationError",
    "ArasShipmentError",
    "aras_create_shipment",
    "aras_track_shipment",
    "aras_cancel_shipment",
    "aras_schedule_pickup",
    "aras_get_shipment_info",
    "aras_verify_callback",
    "aras_get_branch_list",
]

# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

"""
Payment Gateway Integrations for TR-TradeHub Marketplace

This module provides integration utilities for Turkish and international
payment gateways:

- iyzico: Turkish payment gateway with official Python SDK
- PayTR: Turkish payment gateway with Direct API integration
- Stripe: International payment gateway (future implementation)

Each gateway module provides:
- Payment creation and processing
- 3D Secure authentication handling
- Installment payment support (taksit)
- Refund processing
- Webhook signature verification
- Error handling and logging

Configuration:
    Payment gateway credentials are stored in site_config.json or
    TR TradeHub Settings DocType:

    site_config.json:
    {
        "iyzico_api_key": "your-api-key",
        "iyzico_secret_key": "your-secret-key",
        "iyzico_base_url": "https://api.iyzipay.com",  # or sandbox URL

        "paytr_merchant_id": "your-merchant-id",
        "paytr_merchant_key": "your-merchant-key",
        "paytr_merchant_salt": "your-merchant-salt",
        "paytr_base_url": "https://www.paytr.com"
    }

Usage:
    from tr_tradehub.integrations import iyzico, paytr

    # Create payment with iyzico
    result = iyzico.create_payment(
        payment_intent="pi_xxx",
        card_token="card_xxx",
        buyer_info={...}
    )

    # Create payment with PayTR
    result = paytr.create_payment(
        payment_intent="pi_xxx",
        card_info={...},
        buyer_info={...}
    )
"""

from tr_tradehub.integrations.iyzico import (
    IyzicoClient,
    IyzicoError,
    create_payment,
    create_3d_payment,
    complete_3d_payment,
    refund_payment,
    cancel_payment,
    get_installment_info,
    verify_webhook,
    get_payment_details,
)

from tr_tradehub.integrations.paytr import (
    PayTRClient,
    PayTRError,
    create_payment as paytr_create_payment,
    create_iframe_token,
    refund_payment as paytr_refund_payment,
    verify_callback,
    get_payment_status,
)


# Gateway type constants
GATEWAY_IYZICO = "iyzico"
GATEWAY_PAYTR = "paytr"
GATEWAY_STRIPE = "stripe"

# Supported gateways list
SUPPORTED_GATEWAYS = [GATEWAY_IYZICO, GATEWAY_PAYTR]


def get_gateway_client(gateway_type: str):
    """
    Get payment gateway client instance.

    Args:
        gateway_type: Gateway identifier (iyzico, paytr, stripe)

    Returns:
        Gateway client instance

    Raises:
        ValueError: If gateway type is not supported
    """
    if gateway_type == GATEWAY_IYZICO:
        return IyzicoClient()
    elif gateway_type == GATEWAY_PAYTR:
        return PayTRClient()
    else:
        raise ValueError(f"Unsupported payment gateway: {gateway_type}")


def process_payment(
    gateway_type: str,
    payment_intent: str,
    payment_data: dict,
) -> dict:
    """
    Process payment through specified gateway.

    Args:
        gateway_type: Gateway to use (iyzico, paytr)
        payment_intent: Payment Intent document name
        payment_data: Payment details including card/buyer info

    Returns:
        dict: Gateway response with payment result
    """
    if gateway_type == GATEWAY_IYZICO:
        return create_payment(
            payment_intent=payment_intent,
            **payment_data
        )
    elif gateway_type == GATEWAY_PAYTR:
        return paytr_create_payment(
            payment_intent=payment_intent,
            **payment_data
        )
    else:
        raise ValueError(f"Unsupported payment gateway: {gateway_type}")


def process_refund(
    gateway_type: str,
    payment_id: str,
    amount: float,
    reason: str = None,
) -> dict:
    """
    Process refund through specified gateway.

    Args:
        gateway_type: Gateway to use
        payment_id: Gateway payment/transaction ID
        amount: Refund amount
        reason: Refund reason

    Returns:
        dict: Gateway response with refund result
    """
    if gateway_type == GATEWAY_IYZICO:
        return refund_payment(
            payment_id=payment_id,
            amount=amount,
            reason=reason
        )
    elif gateway_type == GATEWAY_PAYTR:
        return paytr_refund_payment(
            merchant_oid=payment_id,
            amount=amount,
            reason=reason
        )
    else:
        raise ValueError(f"Unsupported payment gateway: {gateway_type}")


__all__ = [
    # Constants
    "GATEWAY_IYZICO",
    "GATEWAY_PAYTR",
    "GATEWAY_STRIPE",
    "SUPPORTED_GATEWAYS",

    # Factory functions
    "get_gateway_client",
    "process_payment",
    "process_refund",

    # iyzico exports
    "IyzicoClient",
    "IyzicoError",
    "create_payment",
    "create_3d_payment",
    "complete_3d_payment",
    "refund_payment",
    "cancel_payment",
    "get_installment_info",
    "verify_webhook",
    "get_payment_details",

    # PayTR exports
    "PayTRClient",
    "PayTRError",
    "paytr_create_payment",
    "create_iframe_token",
    "paytr_refund_payment",
    "verify_callback",
    "get_payment_status",
]

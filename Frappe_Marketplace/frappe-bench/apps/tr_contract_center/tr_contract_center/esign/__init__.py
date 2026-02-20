# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

"""
E-Sign Provider Abstraction Layer

Supports multiple e-signature providers:
- Turkcell E-Sign
- E-Imza.gov.tr
- Custom/Generic providers
"""

from tr_contract_center.esign.base import ESignProviderBase
from tr_contract_center.esign.turkcell_adapter import TurkcellESignAdapter
from tr_contract_center.esign.generic_adapter import GenericESignAdapter

import frappe

# Provider registry
PROVIDERS = {
    "turkcell_esign": TurkcellESignAdapter,
    "e_imza_gov": GenericESignAdapter,  # Placeholder
    "generic": GenericESignAdapter
}


def get_provider_adapter(provider_name):
    """
    Get the appropriate e-sign adapter for a provider.

    Args:
        provider_name: Name of the ESign Provider document

    Returns:
        ESignProviderBase: Configured adapter instance
    """
    if not frappe.db.exists("ESign Provider", provider_name):
        return None

    provider_doc = frappe.get_doc("ESign Provider", provider_name)

    adapter_class = PROVIDERS.get(provider_doc.provider_type)
    if not adapter_class:
        adapter_class = GenericESignAdapter

    return adapter_class(provider_doc)


def get_default_provider():
    """
    Get the default enabled e-sign provider.

    Returns:
        str: Name of the default provider or None
    """
    return frappe.db.get_value(
        "ESign Provider",
        {"enabled": 1, "is_default": 1},
        "name"
    )

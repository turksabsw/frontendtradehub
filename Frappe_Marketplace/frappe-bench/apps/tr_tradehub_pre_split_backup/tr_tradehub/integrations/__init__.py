# Copyright (c) 2026, Trade Hub and contributors
# For license information, please see license.txt

"""
Trade Hub Integrations Package.

This package contains integration modules for external services including:
- Keycloak SSO (OAuth2/OpenID Connect authentication)
- Payment gateways (future)
- Shipping carriers (future)
- Analytics providers (future)
"""

from tr_tradehub.integrations.keycloak import (
    KeycloakClient,
    get_keycloak_client,
    get_keycloak_settings,
    is_keycloak_enabled,
    validate_keycloak_token,
    get_user_from_token,
    create_or_update_frappe_user,
    sync_user_roles,
    get_authorization_url,
    exchange_code_for_token,
    refresh_access_token,
    logout_user,
    get_keycloak_user_info,
)

__all__ = [
    # Keycloak client and helpers
    "KeycloakClient",
    "get_keycloak_client",
    "get_keycloak_settings",
    "is_keycloak_enabled",
    "validate_keycloak_token",
    "get_user_from_token",
    "create_or_update_frappe_user",
    "sync_user_roles",
    "get_authorization_url",
    "exchange_code_for_token",
    "refresh_access_token",
    "logout_user",
    "get_keycloak_user_info",
]

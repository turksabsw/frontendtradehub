# Copyright (c) 2026, Trade Hub and contributors
# For license information, please see license.txt

"""
Keycloak SSO Integration Utilities for Trade Hub B2B Marketplace.

This module provides comprehensive Keycloak OAuth2/OpenID Connect integration
for single sign-on authentication across the Trade Hub platform.

Key Features:
- OAuth2/OIDC authentication flow support
- Token validation and introspection
- User management (create, update, sync with Frappe)
- Role management and mapping to Frappe roles
- Tenant-aware user provisioning
- Automatic Frappe user creation on SSO login

Requirements:
- python-keycloak>=7.0.0

CRITICAL VERSION NOTES:
- For Keycloak versions < 18: Add '/auth/' to server URL (e.g., 'http://localhost:8080/auth/')
- For Keycloak versions >= 18: No '/auth/' prefix needed (e.g., 'http://localhost:8080/')
- JWT 'aud' claim must include client name - requires audience mapper configuration in Keycloak
- Redirect URIs must match exactly (trailing slash matters)

Configuration:
    Set these values in site_config.json or as environment variables:
    - keycloak_server_url: Keycloak server URL
    - keycloak_realm: Realm name
    - keycloak_client_id: OAuth2 client ID
    - keycloak_client_secret: OAuth2 client secret
    - keycloak_admin_username: Admin username (optional, for user management)
    - keycloak_admin_password: Admin password (optional, for user management)

Usage:
    from tr_tradehub.integrations.keycloak import KeycloakClient, get_keycloak_client

    # Get singleton client instance
    client = get_keycloak_client()

    # Validate a token
    is_valid, user_info = client.validate_token(access_token)

    # Get authorization URL for OAuth2 flow
    auth_url = client.get_authorization_url(redirect_uri, state)

    # Exchange authorization code for tokens
    tokens = client.exchange_code(code, redirect_uri)
"""

from typing import Any, Dict, List, Optional, Tuple, Union
import os
import json
import hashlib
import time

import frappe
from frappe import _
from frappe.utils import cint, now_datetime, get_datetime, add_to_date


# =============================================================================
# CONSTANTS
# =============================================================================

# Cache key prefix
KEYCLOAK_CACHE_PREFIX = "trade_hub:keycloak"

# Token types
TOKEN_TYPE_ACCESS = "access_token"
TOKEN_TYPE_REFRESH = "refresh_token"
TOKEN_TYPE_ID = "id_token"

# Default role mappings from Keycloak roles to Frappe roles
DEFAULT_ROLE_MAPPINGS = {
    "trade_hub_admin": "System Manager",
    "trade_hub_seller": "Seller",
    "trade_hub_buyer": "Buyer",
    "trade_hub_seller_manager": "Seller Manager",
    "trade_hub_support": "Support Agent",
    "trade_hub_analyst": "Analyst",
}

# Required scopes for Trade Hub
REQUIRED_SCOPES = ["openid", "profile", "email"]


# =============================================================================
# KEYCLOAK CLIENT CLASS
# =============================================================================


class KeycloakClient:
    """
    Keycloak OAuth2/OpenID Connect client for Trade Hub.

    This class wraps the python-keycloak library and provides Trade Hub-specific
    functionality including Frappe user management and tenant awareness.

    Attributes:
        server_url: Keycloak server URL
        realm: Realm name
        client_id: OAuth2 client ID
        client_secret: OAuth2 client secret
        openid_client: KeycloakOpenID instance
        admin_client: KeycloakAdmin instance (optional)
    """

    _instance = None
    _initialized = False

    def __new__(cls, *args, **kwargs):
        """Singleton pattern for KeycloakClient."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(
        self,
        server_url: str = None,
        realm: str = None,
        client_id: str = None,
        client_secret: str = None,
        admin_username: str = None,
        admin_password: str = None,
        verify_ssl: bool = True,
    ):
        """
        Initialize Keycloak client.

        Args:
            server_url: Keycloak server URL (e.g., 'http://localhost:8080/')
            realm: Keycloak realm name
            client_id: OAuth2 client ID
            client_secret: OAuth2 client secret
            admin_username: Admin username for user management (optional)
            admin_password: Admin password for user management (optional)
            verify_ssl: Whether to verify SSL certificates
        """
        if self._initialized:
            return

        # Get settings from config if not provided
        settings = get_keycloak_settings()

        self.server_url = server_url or settings.get("server_url")
        self.realm = realm or settings.get("realm")
        self.client_id = client_id or settings.get("client_id")
        self.client_secret = client_secret or settings.get("client_secret")
        self.admin_username = admin_username or settings.get("admin_username")
        self.admin_password = admin_password or settings.get("admin_password")
        self.verify_ssl = verify_ssl

        self._openid_client = None
        self._admin_client = None
        self._public_key = None
        self._public_key_fetched_at = None

        self._initialized = True

    @property
    def openid_client(self):
        """
        Get or create KeycloakOpenID client.

        Returns:
            KeycloakOpenID: Initialized OpenID client

        Raises:
            frappe.ValidationError: If Keycloak is not configured
        """
        if self._openid_client is None:
            if not self._is_configured():
                frappe.throw(
                    _("Keycloak is not configured. Please set keycloak_server_url, "
                      "keycloak_realm, keycloak_client_id, and keycloak_client_secret "
                      "in site_config.json"),
                    title=_("Keycloak Configuration Error")
                )

            try:
                from keycloak import KeycloakOpenID

                self._openid_client = KeycloakOpenID(
                    server_url=self.server_url,
                    client_id=self.client_id,
                    realm_name=self.realm,
                    client_secret_key=self.client_secret,
                    verify=self.verify_ssl,
                )
            except ImportError:
                frappe.throw(
                    _("python-keycloak library is not installed. "
                      "Please run: pip install python-keycloak>=7.0.0"),
                    title=_("Missing Dependency")
                )

        return self._openid_client

    @property
    def admin_client(self):
        """
        Get or create KeycloakAdmin client.

        Returns:
            KeycloakAdmin: Initialized admin client, or None if not configured

        Note:
            Admin client is optional and only needed for user management
            operations like creating users or managing roles.
        """
        if self._admin_client is None:
            if not self.admin_username or not self.admin_password:
                return None

            try:
                from keycloak import KeycloakAdmin

                self._admin_client = KeycloakAdmin(
                    server_url=self.server_url,
                    username=self.admin_username,
                    password=self.admin_password,
                    realm_name=self.realm,
                    verify=self.verify_ssl,
                )
            except ImportError:
                frappe.log_error(
                    message="python-keycloak library not installed",
                    title="Keycloak Admin Client Error"
                )
                return None
            except Exception as e:
                frappe.log_error(
                    message=f"Failed to initialize Keycloak admin client: {str(e)}",
                    title="Keycloak Admin Client Error"
                )
                return None

        return self._admin_client

    def _is_configured(self) -> bool:
        """Check if Keycloak is properly configured."""
        return all([
            self.server_url,
            self.realm,
            self.client_id,
            self.client_secret,
        ])

    # =========================================================================
    # TOKEN OPERATIONS
    # =========================================================================

    def validate_token(
        self,
        access_token: str,
        verify_audience: bool = True,
    ) -> Tuple[bool, Optional[Dict[str, Any]]]:
        """
        Validate an access token and extract user information.

        Args:
            access_token: The access token to validate
            verify_audience: Whether to verify the audience claim

        Returns:
            Tuple of (is_valid, user_info_dict or None)

        Example:
            is_valid, user_info = client.validate_token(token)
            if is_valid:
                email = user_info.get('email')
        """
        try:
            # Try token introspection first (more reliable)
            token_info = self.openid_client.introspect(access_token)

            if not token_info.get("active", False):
                return False, None

            # Verify audience if required
            if verify_audience:
                aud = token_info.get("aud", [])
                if isinstance(aud, str):
                    aud = [aud]
                if self.client_id not in aud:
                    frappe.log_error(
                        message=f"Token audience mismatch. Expected: {self.client_id}, Got: {aud}",
                        title="Keycloak Token Validation"
                    )
                    return False, None

            return True, token_info

        except Exception as e:
            frappe.log_error(
                message=f"Token validation failed: {str(e)}",
                title="Keycloak Token Validation Error"
            )
            return False, None

    def decode_token(
        self,
        token: str,
        token_type: str = TOKEN_TYPE_ACCESS,
    ) -> Optional[Dict[str, Any]]:
        """
        Decode a JWT token without full validation.

        Args:
            token: The JWT token to decode
            token_type: Type of token (access_token, id_token, refresh_token)

        Returns:
            Decoded token claims as dict, or None on error

        Note:
            This only decodes the token, it does not validate it.
            Use validate_token() for full validation.
        """
        try:
            # Get public key with caching
            if self._public_key is None or self._is_public_key_expired():
                self._fetch_public_key()

            options = {
                "verify_signature": True,
                "verify_aud": token_type == TOKEN_TYPE_ACCESS,
                "verify_exp": True,
            }

            return self.openid_client.decode_token(
                token,
                key=self._public_key,
                options=options,
            )
        except Exception as e:
            frappe.log_error(
                message=f"Token decode failed: {str(e)}",
                title="Keycloak Token Decode Error"
            )
            return None

    def _fetch_public_key(self):
        """Fetch and cache Keycloak public key."""
        try:
            self._public_key = (
                "-----BEGIN PUBLIC KEY-----\n"
                + self.openid_client.public_key()
                + "\n-----END PUBLIC KEY-----"
            )
            self._public_key_fetched_at = time.time()
        except Exception as e:
            frappe.log_error(
                message=f"Failed to fetch public key: {str(e)}",
                title="Keycloak Public Key Error"
            )
            raise

    def _is_public_key_expired(self) -> bool:
        """Check if cached public key has expired (1 hour TTL)."""
        if self._public_key_fetched_at is None:
            return True
        return (time.time() - self._public_key_fetched_at) > 3600

    def get_user_info(self, access_token: str) -> Optional[Dict[str, Any]]:
        """
        Get user information from Keycloak userinfo endpoint.

        Args:
            access_token: Valid access token

        Returns:
            User info dict containing email, name, etc., or None on error
        """
        try:
            return self.openid_client.userinfo(access_token)
        except Exception as e:
            frappe.log_error(
                message=f"Failed to get user info: {str(e)}",
                title="Keycloak User Info Error"
            )
            return None

    # =========================================================================
    # OAUTH2 FLOW
    # =========================================================================

    def get_authorization_url(
        self,
        redirect_uri: str,
        state: str = None,
        scope: List[str] = None,
        nonce: str = None,
    ) -> str:
        """
        Generate OAuth2 authorization URL for login redirect.

        Args:
            redirect_uri: URL to redirect after authentication
            state: CSRF protection state parameter
            scope: List of scopes to request (defaults to openid, profile, email)
            nonce: Nonce for replay protection

        Returns:
            Authorization URL string

        Example:
            auth_url = client.get_authorization_url(
                redirect_uri='http://localhost:8000/api/method/trade_hub.api.v1.auth.sso_callback',
                state=frappe.generate_hash(length=32)
            )
        """
        if scope is None:
            scope = REQUIRED_SCOPES

        return self.openid_client.auth_url(
            redirect_uri=redirect_uri,
            scope=" ".join(scope),
            state=state,
            nonce=nonce,
        )

    def exchange_code(
        self,
        code: str,
        redirect_uri: str,
    ) -> Optional[Dict[str, Any]]:
        """
        Exchange authorization code for tokens.

        Args:
            code: Authorization code from callback
            redirect_uri: Same redirect URI used in authorization request

        Returns:
            Token dict containing access_token, refresh_token, id_token, etc.
            or None on error

        Example:
            tokens = client.exchange_code(code, redirect_uri)
            access_token = tokens['access_token']
            refresh_token = tokens['refresh_token']
        """
        try:
            return self.openid_client.token(
                grant_type="authorization_code",
                code=code,
                redirect_uri=redirect_uri,
            )
        except Exception as e:
            frappe.log_error(
                message=f"Code exchange failed: {str(e)}",
                title="Keycloak Code Exchange Error"
            )
            return None

    def refresh_token(self, refresh_token: str) -> Optional[Dict[str, Any]]:
        """
        Refresh an access token using refresh token.

        Args:
            refresh_token: Valid refresh token

        Returns:
            New token dict or None on error

        Example:
            new_tokens = client.refresh_token(refresh_token)
            if new_tokens:
                new_access_token = new_tokens['access_token']
        """
        try:
            return self.openid_client.refresh_token(refresh_token)
        except Exception as e:
            frappe.log_error(
                message=f"Token refresh failed: {str(e)}",
                title="Keycloak Token Refresh Error"
            )
            return None

    def logout(self, refresh_token: str) -> bool:
        """
        Logout user from Keycloak (invalidate tokens).

        Args:
            refresh_token: User's refresh token

        Returns:
            True if logout successful, False otherwise
        """
        try:
            self.openid_client.logout(refresh_token)
            return True
        except Exception as e:
            frappe.log_error(
                message=f"Logout failed: {str(e)}",
                title="Keycloak Logout Error"
            )
            return False

    # =========================================================================
    # USER MANAGEMENT
    # =========================================================================

    def get_keycloak_user(self, user_id: str) -> Optional[Dict[str, Any]]:
        """
        Get user details from Keycloak by user ID.

        Args:
            user_id: Keycloak user ID (UUID)

        Returns:
            User dict or None if not found
        """
        if not self.admin_client:
            frappe.log_error(
                message="Admin client not configured for user management",
                title="Keycloak Admin Error"
            )
            return None

        try:
            return self.admin_client.get_user(user_id)
        except Exception as e:
            frappe.log_error(
                message=f"Failed to get user {user_id}: {str(e)}",
                title="Keycloak Get User Error"
            )
            return None

    def get_keycloak_user_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        """
        Get user details from Keycloak by email.

        Args:
            email: User email address

        Returns:
            User dict or None if not found
        """
        if not self.admin_client:
            return None

        try:
            users = self.admin_client.get_users({"email": email, "exact": True})
            return users[0] if users else None
        except Exception as e:
            frappe.log_error(
                message=f"Failed to get user by email {email}: {str(e)}",
                title="Keycloak Get User Error"
            )
            return None

    def create_keycloak_user(
        self,
        email: str,
        username: str = None,
        first_name: str = None,
        last_name: str = None,
        password: str = None,
        email_verified: bool = False,
        enabled: bool = True,
        attributes: Dict[str, List[str]] = None,
    ) -> Optional[str]:
        """
        Create a new user in Keycloak.

        Args:
            email: User email address
            username: Username (defaults to email)
            first_name: First name
            last_name: Last name
            password: Initial password (user will be required to change)
            email_verified: Whether email is verified
            enabled: Whether user is enabled
            attributes: Custom user attributes

        Returns:
            Keycloak user ID or None on error
        """
        if not self.admin_client:
            frappe.log_error(
                message="Admin client not configured for user creation",
                title="Keycloak Admin Error"
            )
            return None

        try:
            user_data = {
                "email": email,
                "username": username or email,
                "firstName": first_name or "",
                "lastName": last_name or "",
                "enabled": enabled,
                "emailVerified": email_verified,
            }

            if attributes:
                user_data["attributes"] = attributes

            user_id = self.admin_client.create_user(user_data)

            # Set initial password if provided
            if password and user_id:
                self.admin_client.set_user_password(
                    user_id=user_id,
                    password=password,
                    temporary=True,  # Require password change on first login
                )

            return user_id

        except Exception as e:
            frappe.log_error(
                message=f"Failed to create user {email}: {str(e)}",
                title="Keycloak Create User Error"
            )
            return None

    def update_keycloak_user(
        self,
        user_id: str,
        **kwargs,
    ) -> bool:
        """
        Update user in Keycloak.

        Args:
            user_id: Keycloak user ID
            **kwargs: User attributes to update (email, firstName, lastName, enabled, etc.)

        Returns:
            True if update successful, False otherwise
        """
        if not self.admin_client:
            return False

        try:
            self.admin_client.update_user(user_id=user_id, payload=kwargs)
            return True
        except Exception as e:
            frappe.log_error(
                message=f"Failed to update user {user_id}: {str(e)}",
                title="Keycloak Update User Error"
            )
            return False

    def get_user_roles(self, user_id: str) -> List[str]:
        """
        Get user's realm roles from Keycloak.

        Args:
            user_id: Keycloak user ID

        Returns:
            List of role names
        """
        if not self.admin_client:
            return []

        try:
            roles = self.admin_client.get_realm_roles_of_user(user_id)
            return [role.get("name") for role in roles if role.get("name")]
        except Exception as e:
            frappe.log_error(
                message=f"Failed to get roles for user {user_id}: {str(e)}",
                title="Keycloak Get Roles Error"
            )
            return []

    def assign_user_role(self, user_id: str, role_name: str) -> bool:
        """
        Assign a realm role to a user.

        Args:
            user_id: Keycloak user ID
            role_name: Role name to assign

        Returns:
            True if successful, False otherwise
        """
        if not self.admin_client:
            return False

        try:
            # Get role ID
            role = self.admin_client.get_realm_role(role_name)
            if not role:
                frappe.log_error(
                    message=f"Role {role_name} not found",
                    title="Keycloak Assign Role Error"
                )
                return False

            self.admin_client.assign_realm_roles(
                user_id=user_id,
                roles=[role],
            )
            return True

        except Exception as e:
            frappe.log_error(
                message=f"Failed to assign role {role_name} to user {user_id}: {str(e)}",
                title="Keycloak Assign Role Error"
            )
            return False

    def remove_user_role(self, user_id: str, role_name: str) -> bool:
        """
        Remove a realm role from a user.

        Args:
            user_id: Keycloak user ID
            role_name: Role name to remove

        Returns:
            True if successful, False otherwise
        """
        if not self.admin_client:
            return False

        try:
            role = self.admin_client.get_realm_role(role_name)
            if not role:
                return True  # Role doesn't exist, nothing to remove

            self.admin_client.delete_realm_roles_of_user(
                user_id=user_id,
                roles=[role],
            )
            return True

        except Exception as e:
            frappe.log_error(
                message=f"Failed to remove role {role_name} from user {user_id}: {str(e)}",
                title="Keycloak Remove Role Error"
            )
            return False


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================


def get_keycloak_settings() -> Dict[str, Any]:
    """
    Get Keycloak configuration from site config or environment variables.

    Priority: site_config.json > environment variables > defaults

    Returns:
        Dict with Keycloak settings

    Example:
        settings = get_keycloak_settings()
        server_url = settings.get('server_url')
    """
    # Check cache first
    cache_key = f"{KEYCLOAK_CACHE_PREFIX}:settings"
    cached_settings = frappe.cache().get_value(cache_key)
    if cached_settings:
        return json.loads(cached_settings)

    settings = {}

    # Try site config first
    site_config = frappe.get_site_config() if hasattr(frappe, "get_site_config") else {}

    settings["server_url"] = (
        site_config.get("keycloak_server_url")
        or os.environ.get("KEYCLOAK_SERVER_URL")
    )

    settings["realm"] = (
        site_config.get("keycloak_realm")
        or os.environ.get("KEYCLOAK_REALM")
        or "trade-hub"
    )

    settings["client_id"] = (
        site_config.get("keycloak_client_id")
        or os.environ.get("KEYCLOAK_CLIENT_ID")
        or "trade-hub"
    )

    settings["client_secret"] = (
        site_config.get("keycloak_client_secret")
        or os.environ.get("KEYCLOAK_CLIENT_SECRET")
    )

    settings["admin_username"] = (
        site_config.get("keycloak_admin_username")
        or os.environ.get("KEYCLOAK_ADMIN_USERNAME")
    )

    settings["admin_password"] = (
        site_config.get("keycloak_admin_password")
        or os.environ.get("KEYCLOAK_ADMIN_PASSWORD")
    )

    settings["enabled"] = cint(
        site_config.get("keycloak_enabled", 0)
        or os.environ.get("KEYCLOAK_ENABLED", "0")
    )

    # Role mappings
    settings["role_mappings"] = (
        site_config.get("keycloak_role_mappings")
        or DEFAULT_ROLE_MAPPINGS
    )

    # Auto-create users on SSO login
    settings["auto_create_users"] = cint(
        site_config.get("keycloak_auto_create_users", 1)
    )

    # Default tenant for new users
    settings["default_tenant"] = site_config.get("keycloak_default_tenant")

    # Cache for 5 minutes
    frappe.cache().set_value(cache_key, json.dumps(settings), expires_in_sec=300)

    return settings


def is_keycloak_enabled() -> bool:
    """
    Check if Keycloak SSO is enabled.

    Returns:
        bool: True if Keycloak is enabled and configured
    """
    settings = get_keycloak_settings()
    return bool(
        settings.get("enabled")
        and settings.get("server_url")
        and settings.get("client_id")
        and settings.get("client_secret")
    )


def get_keycloak_client() -> KeycloakClient:
    """
    Get or create the singleton KeycloakClient instance.

    Returns:
        KeycloakClient: Initialized client instance

    Example:
        client = get_keycloak_client()
        auth_url = client.get_authorization_url(redirect_uri, state)
    """
    return KeycloakClient()


def validate_keycloak_token(access_token: str) -> Tuple[bool, Optional[Dict[str, Any]]]:
    """
    Validate a Keycloak access token.

    Args:
        access_token: The access token to validate

    Returns:
        Tuple of (is_valid, user_info or None)

    Example:
        is_valid, user_info = validate_keycloak_token(token)
        if is_valid:
            email = user_info.get('email')
    """
    client = get_keycloak_client()
    return client.validate_token(access_token)


def get_user_from_token(access_token: str) -> Optional[Dict[str, Any]]:
    """
    Get user information from a validated access token.

    Args:
        access_token: Valid access token

    Returns:
        User info dict or None
    """
    client = get_keycloak_client()
    return client.get_user_info(access_token)


def get_keycloak_user_info(access_token: str) -> Optional[Dict[str, Any]]:
    """
    Alias for get_user_from_token.
    Get user information from Keycloak userinfo endpoint.

    Args:
        access_token: Valid access token

    Returns:
        User info dict or None
    """
    return get_user_from_token(access_token)


def create_or_update_frappe_user(
    keycloak_user_info: Dict[str, Any],
    tenant: str = None,
    roles: List[str] = None,
) -> Optional[str]:
    """
    Create or update a Frappe user from Keycloak user info.

    This function is called after successful SSO authentication to ensure
    the user exists in Frappe with proper roles and tenant assignment.

    Args:
        keycloak_user_info: User info dict from Keycloak (from token or userinfo)
        tenant: Tenant to assign (defaults to settings.default_tenant)
        roles: List of Frappe roles to assign (if None, maps from Keycloak roles)

    Returns:
        Frappe user name (email) or None on error

    Example:
        user = create_or_update_frappe_user(user_info, tenant='TENANT-001')
    """
    email = keycloak_user_info.get("email")
    if not email:
        frappe.log_error(
            message=f"No email in Keycloak user info: {keycloak_user_info}",
            title="Keycloak User Sync Error"
        )
        return None

    settings = get_keycloak_settings()

    # Check if auto-create is disabled
    if not settings.get("auto_create_users", True):
        if not frappe.db.exists("User", email):
            frappe.log_error(
                message=f"User {email} not found and auto-create is disabled",
                title="Keycloak User Sync Error"
            )
            return None

    try:
        # Get or create user
        if frappe.db.exists("User", email):
            user_doc = frappe.get_doc("User", email)
            is_new = False
        else:
            user_doc = frappe.new_doc("User")
            user_doc.email = email
            user_doc.send_welcome_email = 0
            is_new = True

        # Update user fields
        user_doc.first_name = keycloak_user_info.get("given_name") or keycloak_user_info.get("firstName") or ""
        user_doc.last_name = keycloak_user_info.get("family_name") or keycloak_user_info.get("lastName") or ""
        user_doc.full_name = keycloak_user_info.get("name") or f"{user_doc.first_name} {user_doc.last_name}".strip()
        user_doc.username = keycloak_user_info.get("preferred_username") or email.split("@")[0]
        user_doc.enabled = 1

        # Set Keycloak ID as custom field if it exists
        keycloak_sub = keycloak_user_info.get("sub")
        if keycloak_sub and hasattr(user_doc, "keycloak_user_id"):
            user_doc.keycloak_user_id = keycloak_sub

        # Set tenant if provided or default
        if tenant:
            if hasattr(user_doc, "tenant"):
                user_doc.tenant = tenant
        elif settings.get("default_tenant"):
            if hasattr(user_doc, "tenant") and not user_doc.get("tenant"):
                user_doc.tenant = settings["default_tenant"]

        # Save user
        user_doc.flags.ignore_permissions = True
        user_doc.flags.no_welcome_mail = True
        user_doc.save()

        # Sync roles
        if roles:
            _sync_user_roles(user_doc, roles)
        elif is_new:
            # Map Keycloak roles to Frappe roles for new users
            keycloak_roles = keycloak_user_info.get("realm_access", {}).get("roles", [])
            frappe_roles = _map_keycloak_roles_to_frappe(keycloak_roles, settings)
            if frappe_roles:
                _sync_user_roles(user_doc, frappe_roles)

        frappe.db.commit()
        return email

    except Exception as e:
        frappe.log_error(
            message=f"Failed to create/update user {email}: {str(e)}",
            title="Keycloak User Sync Error"
        )
        return None


def sync_user_roles(user: str, keycloak_roles: List[str]) -> bool:
    """
    Sync Frappe user roles from Keycloak roles.

    Args:
        user: Frappe user name (email)
        keycloak_roles: List of Keycloak role names

    Returns:
        True if sync successful, False otherwise
    """
    try:
        user_doc = frappe.get_doc("User", user)
        settings = get_keycloak_settings()
        frappe_roles = _map_keycloak_roles_to_frappe(keycloak_roles, settings)
        _sync_user_roles(user_doc, frappe_roles)
        return True
    except Exception as e:
        frappe.log_error(
            message=f"Failed to sync roles for user {user}: {str(e)}",
            title="Keycloak Role Sync Error"
        )
        return False


def _map_keycloak_roles_to_frappe(
    keycloak_roles: List[str],
    settings: Dict[str, Any],
) -> List[str]:
    """
    Map Keycloak role names to Frappe role names.

    Args:
        keycloak_roles: List of Keycloak role names
        settings: Keycloak settings containing role_mappings

    Returns:
        List of Frappe role names
    """
    role_mappings = settings.get("role_mappings", DEFAULT_ROLE_MAPPINGS)
    frappe_roles = []

    for kc_role in keycloak_roles:
        if kc_role in role_mappings:
            frappe_roles.append(role_mappings[kc_role])

    return list(set(frappe_roles))  # Remove duplicates


def _sync_user_roles(user_doc, roles: List[str]):
    """
    Internal function to sync roles to a user document.

    Args:
        user_doc: Frappe User document
        roles: List of Frappe role names to assign
    """
    # Get current roles
    current_roles = {r.role for r in user_doc.roles}

    # Add missing roles
    for role in roles:
        if role not in current_roles and frappe.db.exists("Role", role):
            user_doc.append("roles", {"role": role})

    user_doc.flags.ignore_permissions = True
    user_doc.save()


def get_authorization_url(
    redirect_uri: str,
    state: str = None,
    scope: List[str] = None,
) -> str:
    """
    Get OAuth2 authorization URL for SSO login.

    Args:
        redirect_uri: Callback URL after authentication
        state: CSRF protection state
        scope: List of OAuth2 scopes

    Returns:
        Authorization URL string

    Example:
        auth_url = get_authorization_url(
            redirect_uri='/api/method/trade_hub.api.v1.auth.sso_callback',
            state=frappe.generate_hash()
        )
    """
    client = get_keycloak_client()
    return client.get_authorization_url(redirect_uri, state, scope)


def exchange_code_for_token(
    code: str,
    redirect_uri: str,
) -> Optional[Dict[str, Any]]:
    """
    Exchange authorization code for tokens.

    Args:
        code: Authorization code from callback
        redirect_uri: Same redirect URI used in authorization

    Returns:
        Token dict or None on error
    """
    client = get_keycloak_client()
    return client.exchange_code(code, redirect_uri)


def refresh_access_token(refresh_token: str) -> Optional[Dict[str, Any]]:
    """
    Refresh an access token.

    Args:
        refresh_token: Valid refresh token

    Returns:
        New token dict or None on error
    """
    client = get_keycloak_client()
    return client.refresh_token(refresh_token)


def logout_user(refresh_token: str) -> bool:
    """
    Logout user from Keycloak.

    Args:
        refresh_token: User's refresh token

    Returns:
        True if successful, False otherwise
    """
    client = get_keycloak_client()
    return client.logout(refresh_token)


def create_user_from_keycloak(
    access_token: str = None,
    keycloak_user_info: Dict[str, Any] = None,
    tenant: str = None,
    default_roles: List[str] = None,
    auto_login: bool = True,
) -> Tuple[Optional[str], bool]:
    """
    Create a Frappe user automatically on first SSO login from Keycloak.

    This function is the primary entry point for automatic user provisioning
    during SSO authentication. It handles:
    - Validating the access token (if provided)
    - Fetching user info from Keycloak (if not provided)
    - Checking if user already exists in Frappe
    - Creating new user with proper tenant assignment
    - Mapping Keycloak roles to Frappe roles
    - Optionally logging the user into Frappe session

    Args:
        access_token: Valid Keycloak access token (required if keycloak_user_info not provided)
        keycloak_user_info: Pre-fetched Keycloak user info dict (optional, will fetch if not provided)
        tenant: Tenant to assign to new user (defaults to keycloak_default_tenant from settings)
        default_roles: List of Frappe roles to assign (if None, maps from Keycloak roles)
        auto_login: Whether to automatically log the user into Frappe session

    Returns:
        Tuple of (user_email or None, is_new_user)
        - user_email: The Frappe user email/name, or None if creation failed
        - is_new_user: True if user was created, False if user already existed

    Example:
        # After receiving authorization code callback
        tokens = exchange_code_for_token(code, redirect_uri)
        user_email, is_new = create_user_from_keycloak(
            access_token=tokens['access_token'],
            tenant='TENANT-001'
        )
        if user_email:
            # User is now created and logged in
            pass

    Raises:
        frappe.ValidationError: If Keycloak is not enabled or user info cannot be retrieved
    """
    # Check if Keycloak is enabled
    if not is_keycloak_enabled():
        frappe.throw(
            _("Keycloak SSO is not enabled"),
            title=_("SSO Not Available")
        )

    settings = get_keycloak_settings()

    # Check if auto-create users is enabled
    if not settings.get("auto_create_users", True):
        frappe.throw(
            _("Automatic user creation is disabled. Please contact administrator."),
            title=_("User Creation Disabled")
        )

    # Get user info from Keycloak if not provided
    if not keycloak_user_info:
        if not access_token:
            frappe.throw(
                _("Either access_token or keycloak_user_info must be provided"),
                title=_("Invalid Parameters")
            )

        # Validate token first
        is_valid, token_info = validate_keycloak_token(access_token)
        if not is_valid:
            frappe.throw(
                _("Invalid or expired access token"),
                title=_("Token Validation Failed")
            )

        # Get full user info from userinfo endpoint
        keycloak_user_info = get_keycloak_user_info(access_token)
        if not keycloak_user_info:
            # Fall back to token info
            keycloak_user_info = token_info

    if not keycloak_user_info:
        frappe.throw(
            _("Could not retrieve user information from Keycloak"),
            title=_("User Info Error")
        )

    # Extract email - required field
    email = keycloak_user_info.get("email")
    if not email:
        frappe.throw(
            _("User email not provided by Keycloak. Email is required for user creation."),
            title=_("Missing Email")
        )

    # Check if email is verified (optional but recommended)
    email_verified = keycloak_user_info.get("email_verified", False)
    if not email_verified:
        frappe.log_error(
            message=f"User {email} has unverified email in Keycloak",
            title="Keycloak Unverified Email Warning"
        )

    # Check if user already exists
    is_new_user = not frappe.db.exists("User", email)

    # Determine tenant
    user_tenant = tenant or settings.get("default_tenant")

    # Create or update user
    try:
        user_email = _create_or_update_user_from_keycloak_info(
            keycloak_user_info=keycloak_user_info,
            tenant=user_tenant,
            roles=default_roles,
            settings=settings,
            is_new_user=is_new_user,
        )

        if not user_email:
            return None, False

        # Auto-login user to Frappe session if requested
        if auto_login and user_email:
            _login_user_to_frappe(user_email)

        # Log the event
        if is_new_user:
            frappe.logger().info(
                f"Created new Frappe user from Keycloak SSO: {user_email}"
            )
        else:
            frappe.logger().info(
                f"Updated existing Frappe user from Keycloak SSO: {user_email}"
            )

        return user_email, is_new_user

    except Exception as e:
        frappe.log_error(
            message=f"Failed to create user from Keycloak: {str(e)}",
            title="Keycloak User Creation Error"
        )
        return None, False


def _create_or_update_user_from_keycloak_info(
    keycloak_user_info: Dict[str, Any],
    tenant: str,
    roles: List[str],
    settings: Dict[str, Any],
    is_new_user: bool,
) -> Optional[str]:
    """
    Internal function to create or update a Frappe user from Keycloak info.

    Args:
        keycloak_user_info: User info dict from Keycloak
        tenant: Tenant to assign
        roles: List of Frappe roles to assign
        settings: Keycloak settings dict
        is_new_user: Whether this is a new user

    Returns:
        User email or None on error
    """
    email = keycloak_user_info.get("email")

    try:
        # Get or create user document
        if is_new_user:
            user_doc = frappe.new_doc("User")
            user_doc.email = email
            user_doc.send_welcome_email = 0
            user_doc.user_type = "Website User"  # Default for SSO users
        else:
            user_doc = frappe.get_doc("User", email)

        # Update user fields from Keycloak info
        user_doc.first_name = (
            keycloak_user_info.get("given_name")
            or keycloak_user_info.get("firstName")
            or ""
        )
        user_doc.last_name = (
            keycloak_user_info.get("family_name")
            or keycloak_user_info.get("lastName")
            or ""
        )
        user_doc.full_name = (
            keycloak_user_info.get("name")
            or f"{user_doc.first_name} {user_doc.last_name}".strip()
            or email.split("@")[0]
        )
        user_doc.username = (
            keycloak_user_info.get("preferred_username")
            or email.split("@")[0]
        )
        user_doc.enabled = 1

        # Set Keycloak-specific fields
        keycloak_sub = keycloak_user_info.get("sub")
        if keycloak_sub and hasattr(user_doc, "keycloak_user_id"):
            user_doc.keycloak_user_id = keycloak_sub

        # Set tenant if provided and field exists
        if tenant and hasattr(user_doc, "tenant"):
            if is_new_user or not user_doc.get("tenant"):
                user_doc.tenant = tenant

        # Set phone if available
        phone = keycloak_user_info.get("phone_number")
        if phone and not user_doc.get("phone"):
            user_doc.phone = phone

        # Set locale/language if available
        locale = keycloak_user_info.get("locale")
        if locale:
            # Map common locales to Frappe languages
            locale_mapping = {
                "en": "en",
                "tr": "tr",
                "de": "de",
                "fr": "fr",
                "es": "es",
            }
            language = locale_mapping.get(locale[:2].lower())
            if language and frappe.db.exists("Language", language):
                user_doc.language = language

        # Save user with bypass permissions
        user_doc.flags.ignore_permissions = True
        user_doc.flags.no_welcome_mail = True
        user_doc.save()

        # Sync roles
        if roles:
            _sync_user_roles(user_doc, roles)
        elif is_new_user:
            # Map Keycloak roles to Frappe roles for new users
            keycloak_roles = (
                keycloak_user_info.get("realm_access", {}).get("roles", [])
            )
            # Also check for client roles
            resource_access = keycloak_user_info.get("resource_access", {})
            client_id = settings.get("client_id")
            if client_id and client_id in resource_access:
                keycloak_roles.extend(
                    resource_access[client_id].get("roles", [])
                )

            frappe_roles = _map_keycloak_roles_to_frappe(keycloak_roles, settings)
            if frappe_roles:
                _sync_user_roles(user_doc, frappe_roles)
            else:
                # Assign default guest role if no roles mapped
                _sync_user_roles(user_doc, ["Guest"])

        frappe.db.commit()
        return email

    except Exception as e:
        frappe.db.rollback()
        frappe.log_error(
            message=f"Failed to create/update user {email}: {str(e)}\n"
                    f"User info: {keycloak_user_info}",
            title="Keycloak User Sync Error"
        )
        raise


def _login_user_to_frappe(user_email: str) -> bool:
    """
    Log a user into the Frappe session.

    Args:
        user_email: The user's email/name in Frappe

    Returns:
        True if login successful, False otherwise
    """
    try:
        frappe.local.login_manager.login_as(user_email)
        frappe.local.session_obj.update_session()
        return True
    except Exception as e:
        frappe.log_error(
            message=f"Failed to login user {user_email}: {str(e)}",
            title="Keycloak Auto-Login Error"
        )
        return False


def handle_sso_callback(
    code: str,
    redirect_uri: str,
    state: str = None,
    tenant: str = None,
) -> Tuple[Optional[str], Dict[str, Any]]:
    """
    Handle the complete SSO callback flow including user creation.

    This is a convenience function that combines:
    - State verification (CSRF protection)
    - Code exchange for tokens
    - User creation/update in Frappe
    - Auto-login to Frappe session

    Args:
        code: Authorization code from Keycloak callback
        redirect_uri: The redirect URI used in the authorization request
        state: State parameter for CSRF verification (optional but recommended)
        tenant: Tenant to assign to new users

    Returns:
        Tuple of (user_email or None, result_dict)
        result_dict contains:
        - success: bool
        - is_new_user: bool
        - tokens: dict with access_token, refresh_token, etc.
        - error: error message if failed

    Example:
        @frappe.whitelist(allow_guest=True)
        def sso_callback():
            code = frappe.form_dict.get('code')
            state = frappe.form_dict.get('state')
            redirect_uri = frappe.utils.get_url('/api/method/...')

            user, result = handle_sso_callback(code, redirect_uri, state)
            if result['success']:
                frappe.local.response['type'] = 'redirect'
                frappe.local.response['location'] = '/app'
            else:
                frappe.throw(result['error'])
    """
    result = {
        "success": False,
        "is_new_user": False,
        "tokens": None,
        "error": None,
    }

    try:
        # Verify state if provided
        if state:
            cache_key = f"{KEYCLOAK_CACHE_PREFIX}:state:{state}"
            is_valid_state = frappe.cache().get_value(cache_key) == "1"
            if not is_valid_state:
                result["error"] = "Invalid or expired state parameter"
                return None, result
            # Delete state after verification (one-time use)
            frappe.cache().delete_value(cache_key)

        # Exchange code for tokens
        tokens = exchange_code_for_token(code, redirect_uri)
        if not tokens:
            result["error"] = "Failed to exchange authorization code for tokens"
            return None, result

        result["tokens"] = {
            "access_token": tokens.get("access_token"),
            "refresh_token": tokens.get("refresh_token"),
            "id_token": tokens.get("id_token"),
            "expires_in": tokens.get("expires_in"),
            "token_type": tokens.get("token_type"),
        }

        # Create/update user and auto-login
        user_email, is_new_user = create_user_from_keycloak(
            access_token=tokens.get("access_token"),
            tenant=tenant,
            auto_login=True,
        )

        if user_email:
            result["success"] = True
            result["is_new_user"] = is_new_user
            return user_email, result
        else:
            result["error"] = "Failed to create or update user"
            return None, result

    except Exception as e:
        result["error"] = str(e)
        frappe.log_error(
            message=f"SSO callback handling failed: {str(e)}",
            title="Keycloak SSO Callback Error"
        )
        return None, result


# =============================================================================
# WHITELISTED API FUNCTIONS
# =============================================================================


@frappe.whitelist(allow_guest=True)
def check_keycloak_status() -> Dict[str, Any]:
    """
    Check if Keycloak SSO is enabled and configured.

    Returns:
        Dict with status information

    API: GET /api/method/trade_hub.integrations.keycloak.check_keycloak_status
    """
    return {
        "enabled": is_keycloak_enabled(),
        "realm": get_keycloak_settings().get("realm"),
    }


@frappe.whitelist(allow_guest=True)
def get_sso_login_url(redirect_uri: str = None) -> Dict[str, Any]:
    """
    Get SSO login URL for Keycloak authentication.

    Args:
        redirect_uri: Optional custom redirect URI after login

    Returns:
        Dict with authorization_url and state

    API: GET /api/method/trade_hub.integrations.keycloak.get_sso_login_url
    """
    if not is_keycloak_enabled():
        frappe.throw(_("Keycloak SSO is not enabled"), title=_("SSO Not Available"))

    # Generate CSRF state
    state = frappe.generate_hash(length=32)

    # Store state in cache for verification
    cache_key = f"{KEYCLOAK_CACHE_PREFIX}:state:{state}"
    frappe.cache().set_value(cache_key, "1", expires_in_sec=600)  # 10 min expiry

    # Use default redirect if not provided
    if not redirect_uri:
        redirect_uri = frappe.utils.get_url(
            "/api/method/trade_hub.api.v1.auth.sso_callback"
        )

    auth_url = get_authorization_url(redirect_uri, state)

    return {
        "authorization_url": auth_url,
        "state": state,
    }


@frappe.whitelist()
def verify_sso_state(state: str) -> bool:
    """
    Verify CSRF state from SSO callback.

    Args:
        state: State parameter from callback

    Returns:
        True if state is valid, False otherwise

    API: POST /api/method/trade_hub.integrations.keycloak.verify_sso_state
    """
    cache_key = f"{KEYCLOAK_CACHE_PREFIX}:state:{state}"
    is_valid = frappe.cache().get_value(cache_key) == "1"

    if is_valid:
        # Delete state after verification (one-time use)
        frappe.cache().delete_value(cache_key)

    return is_valid


@frappe.whitelist()
def get_current_user_keycloak_info() -> Optional[Dict[str, Any]]:
    """
    Get Keycloak information for the current logged-in user.

    Returns:
        Dict with Keycloak user info or None if not an SSO user

    API: GET /api/method/trade_hub.integrations.keycloak.get_current_user_keycloak_info
    """
    user = frappe.session.user
    if user == "Guest":
        return None

    user_doc = frappe.get_doc("User", user)

    # Check if user has Keycloak ID
    if not hasattr(user_doc, "keycloak_user_id") or not user_doc.keycloak_user_id:
        return None

    return {
        "keycloak_user_id": user_doc.keycloak_user_id,
        "email": user_doc.email,
        "full_name": user_doc.full_name,
        "is_sso_user": True,
    }


@frappe.whitelist()
def refresh_user_token(refresh_token: str) -> Optional[Dict[str, Any]]:
    """
    Refresh access token for current user.

    Args:
        refresh_token: Valid refresh token

    Returns:
        New token dict or None on error

    API: POST /api/method/trade_hub.integrations.keycloak.refresh_user_token
    """
    if frappe.session.user == "Guest":
        frappe.throw(_("Not authenticated"), title=_("Authentication Required"))

    tokens = refresh_access_token(refresh_token)
    if tokens:
        return {
            "access_token": tokens.get("access_token"),
            "refresh_token": tokens.get("refresh_token"),
            "expires_in": tokens.get("expires_in"),
            "token_type": tokens.get("token_type"),
        }

    return None


@frappe.whitelist()
def sso_logout(refresh_token: str = None) -> Dict[str, bool]:
    """
    Logout from both Frappe and Keycloak.

    Args:
        refresh_token: Optional refresh token to invalidate in Keycloak

    Returns:
        Dict with logout status

    API: POST /api/method/trade_hub.integrations.keycloak.sso_logout
    """
    keycloak_logged_out = False

    if refresh_token:
        keycloak_logged_out = logout_user(refresh_token)

    # Logout from Frappe
    frappe.local.login_manager.logout()

    return {
        "frappe_logged_out": True,
        "keycloak_logged_out": keycloak_logged_out,
    }

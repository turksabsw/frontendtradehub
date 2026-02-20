# Copyright (c) 2026, Trade Hub and contributors
# For license information, please see license.txt

"""
Keycloak Settings DocType for tenant-specific SSO configuration.

This module implements tenant-specific Keycloak OAuth2/OIDC configuration including:
- Keycloak server and realm settings
- OAuth2 client configuration (public and confidential clients)
- Token management and refresh settings
- Automatic user creation and role synchronization
- User attribute mapping from Keycloak to Frappe
- Social login provider configuration
- Admin API access for user management

Each tenant can have its own Keycloak realm and client configuration,
enabling multi-tenant SSO isolation while maintaining platform-wide
visibility for administrators.

CRITICAL: Keycloak Version Handling:
- For Keycloak versions >= 18: server URL without /auth/ prefix
- For Keycloak versions < 18: server URL with /auth/ prefix
- JWT `aud` claim must include client name - requires audience mapper in Keycloak
"""

import re
import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime, cint, get_url


class KeycloakSettings(Document):
    """
    Keycloak Settings DocType for tenant-specific SSO configuration.

    Provides configuration for:
    - Keycloak server connection
    - OAuth2 client settings
    - Token management
    - Automatic user provisioning
    - Role synchronization
    - Social login providers
    - Admin API access
    """

    def before_insert(self):
        """Set default values before inserting a new Keycloak configuration."""
        self.validate_unique_tenant()
        self.set_default_redirect_uris()

    def validate(self):
        """Validate Keycloak settings before saving."""
        self.validate_server_url()
        self.validate_realm_name()
        self.validate_client_id()
        self.validate_client_secret()
        self.validate_token_settings()
        self.validate_redirect_uris()
        self.validate_admin_credentials()
        self.update_well_known_url()

    def on_update(self):
        """Actions to perform after Keycloak settings are updated."""
        self.clear_keycloak_cache()

    def on_trash(self):
        """Actions to perform before deletion."""
        self.clear_keycloak_cache()

    # =========================================================================
    # VALIDATION METHODS
    # =========================================================================

    def validate_unique_tenant(self):
        """Ensure only one Keycloak settings exists per tenant."""
        if self.tenant:
            existing = frappe.db.get_value(
                "Keycloak Settings",
                {"tenant": self.tenant, "name": ("!=", self.name or "")},
                "name"
            )
            if existing:
                frappe.throw(
                    _("Keycloak Settings already exists for tenant {0}").format(
                        self.tenant
                    )
                )

    def validate_server_url(self):
        """
        Validate Keycloak server URL format.

        Server URL should be a valid URL without trailing slash.
        The /auth/ suffix is handled based on Keycloak version.
        """
        if self.server_url:
            url = self.server_url.strip()

            # Remove trailing slash
            url = url.rstrip("/")

            # Remove /auth suffix if present (we'll add it back based on version)
            if url.endswith("/auth"):
                url = url[:-5]

            # Basic URL validation
            url_pattern = r'^https?://[a-zA-Z0-9][-a-zA-Z0-9.]*[a-zA-Z0-9](:[0-9]+)?$'
            if not re.match(url_pattern, url):
                frappe.throw(
                    _("Invalid server URL format. "
                      "Expected format: https://keycloak.example.com or http://localhost:8080")
                )

            self.server_url = url

    def validate_realm_name(self):
        """
        Validate Keycloak realm name format.

        Realm names can contain alphanumeric characters, underscores, and hyphens.
        """
        if self.realm_name:
            realm = self.realm_name.strip()

            # Realm name pattern: alphanumeric, underscore, hyphen
            pattern = r'^[a-zA-Z0-9_-]+$'
            if not re.match(pattern, realm):
                frappe.throw(
                    _("Invalid realm name. "
                      "Realm names can only contain letters, numbers, underscores, and hyphens")
                )

            self.realm_name = realm

    def validate_client_id(self):
        """Validate OAuth2 client ID."""
        if self.client_id:
            client_id = self.client_id.strip()

            if len(client_id) < 3:
                frappe.throw(_("Client ID must be at least 3 characters"))

            if len(client_id) > 255:
                frappe.throw(_("Client ID cannot exceed 255 characters"))

            self.client_id = client_id

    def validate_client_secret(self):
        """Validate client secret is provided for confidential clients."""
        if not self.public_client and self.enabled:
            if not self.client_secret:
                frappe.throw(
                    _("Client secret is required for confidential clients. "
                      "Enable 'Public Client' if using a browser-based application without a secret.")
                )

    def validate_token_settings(self):
        """Validate token lifespan settings are within reasonable bounds."""
        if self.access_token_lifespan:
            lifespan = cint(self.access_token_lifespan)
            if lifespan < 60:
                frappe.throw(_("Access token lifespan must be at least 60 seconds"))
            if lifespan > 86400:
                frappe.throw(_("Access token lifespan cannot exceed 86400 seconds (24 hours)"))

        if self.refresh_token_lifespan:
            lifespan = cint(self.refresh_token_lifespan)
            if lifespan < 300:
                frappe.throw(_("Refresh token lifespan must be at least 300 seconds (5 minutes)"))
            if lifespan > 604800:
                frappe.throw(_("Refresh token lifespan cannot exceed 604800 seconds (7 days)"))

        if self.connection_timeout:
            timeout = cint(self.connection_timeout)
            if timeout < 5:
                frappe.throw(_("Connection timeout must be at least 5 seconds"))
            if timeout > 120:
                frappe.throw(_("Connection timeout cannot exceed 120 seconds"))

    def validate_redirect_uris(self):
        """Validate redirect URI format."""
        if self.redirect_uri:
            uri = self.redirect_uri.strip()
            if not uri.startswith(("http://", "https://")):
                frappe.throw(_("Redirect URI must start with http:// or https://"))
            self.redirect_uri = uri

        if self.post_logout_redirect_uri:
            uri = self.post_logout_redirect_uri.strip()
            if not uri.startswith(("http://", "https://")):
                frappe.throw(_("Post logout redirect URI must start with http:// or https://"))
            self.post_logout_redirect_uri = uri

        if self.allowed_redirect_uris:
            uris = self.allowed_redirect_uris.strip().split("\n")
            valid_uris = []
            for uri in uris:
                uri = uri.strip()
                if uri:
                    if not uri.startswith(("http://", "https://")):
                        frappe.throw(_("All redirect URIs must start with http:// or https://"))
                    valid_uris.append(uri)
            self.allowed_redirect_uris = "\n".join(valid_uris)

    def validate_admin_credentials(self):
        """Validate admin API credentials if user management is enabled."""
        if self.sync_user_roles and self.enabled:
            if not self.admin_username and not self.admin_client_secret:
                frappe.msgprint(
                    _("Warning: Admin credentials or client secret required for role synchronization. "
                      "Either provide admin username/password or admin client secret."),
                    indicator="orange"
                )

    def set_default_redirect_uris(self):
        """Set default redirect URIs based on site URL."""
        if not self.redirect_uri:
            base_url = get_url()
            self.redirect_uri = f"{base_url}/api/method/trade_hub.integrations.keycloak.callback"
        if not self.post_logout_redirect_uri:
            self.post_logout_redirect_uri = get_url()

    def update_well_known_url(self):
        """Update the OpenID Connect discovery URL based on server and realm."""
        if self.server_url and self.realm_name:
            base_url = self.get_keycloak_base_url()
            self.well_known_url = (
                f"{base_url}/realms/{self.realm_name}/.well-known/openid-configuration"
            )

    # =========================================================================
    # CACHE MANAGEMENT
    # =========================================================================

    def clear_keycloak_cache(self):
        """Clear cached Keycloak configuration."""
        cache_keys = [
            f"keycloak_settings:{self.tenant}",
            f"keycloak_openid:{self.tenant}",
            f"keycloak_admin:{self.tenant}",
            f"keycloak_jwks:{self.tenant}",
        ]
        for key in cache_keys:
            frappe.cache().delete_value(key)

    # =========================================================================
    # KEYCLOAK URL HELPERS
    # =========================================================================

    def get_keycloak_base_url(self):
        """
        Get the Keycloak base URL with appropriate /auth/ suffix.

        Returns:
            str: Base URL for Keycloak API calls
        """
        base_url = self.server_url.rstrip("/")

        # For Keycloak versions < 18, add /auth/ prefix
        if self.keycloak_version == "Pre-18 (Legacy)":
            base_url = f"{base_url}/auth"

        return base_url

    def get_authorization_url(self):
        """
        Get the OAuth2 authorization endpoint URL.

        Returns:
            str: Authorization endpoint URL
        """
        base_url = self.get_keycloak_base_url()
        return f"{base_url}/realms/{self.realm_name}/protocol/openid-connect/auth"

    def get_token_url(self):
        """
        Get the OAuth2 token endpoint URL.

        Returns:
            str: Token endpoint URL
        """
        base_url = self.get_keycloak_base_url()
        return f"{base_url}/realms/{self.realm_name}/protocol/openid-connect/token"

    def get_userinfo_url(self):
        """
        Get the OAuth2 userinfo endpoint URL.

        Returns:
            str: Userinfo endpoint URL
        """
        base_url = self.get_keycloak_base_url()
        return f"{base_url}/realms/{self.realm_name}/protocol/openid-connect/userinfo"

    def get_logout_url(self):
        """
        Get the OAuth2 logout endpoint URL.

        Returns:
            str: Logout endpoint URL
        """
        base_url = self.get_keycloak_base_url()
        return f"{base_url}/realms/{self.realm_name}/protocol/openid-connect/logout"

    def get_jwks_url(self):
        """
        Get the JWKS endpoint URL for token verification.

        Returns:
            str: JWKS endpoint URL
        """
        base_url = self.get_keycloak_base_url()
        return f"{base_url}/realms/{self.realm_name}/protocol/openid-connect/certs"

    # =========================================================================
    # CONFIGURATION GETTERS
    # =========================================================================

    def get_openid_config(self):
        """
        Get the complete OpenID Connect configuration for frontend use.

        Returns:
            dict: OpenID Connect configuration
        """
        return {
            "enabled": self.enabled,
            "client_id": self.client_id,
            "public_client": self.public_client,
            "pkce_enabled": self.pkce_enabled,
            "realm_name": self.realm_name,
            "authorization_url": self.get_authorization_url(),
            "token_url": self.get_token_url(),
            "userinfo_url": self.get_userinfo_url(),
            "logout_url": self.get_logout_url(),
            "jwks_url": self.get_jwks_url(),
            "redirect_uri": self.redirect_uri,
            "post_logout_redirect_uri": self.post_logout_redirect_uri,
            "social_providers": {
                "google": self.enable_google_login,
                "facebook": self.enable_facebook_login,
                "apple": self.enable_apple_login,
                "linkedin": self.enable_linkedin_login,
            },
        }

    def get_attribute_mapping(self):
        """
        Get the user attribute mapping configuration.

        Returns:
            dict: Attribute mapping from Keycloak to Frappe fields
        """
        return {
            "email": self.email_attribute,
            "first_name": self.first_name_attribute,
            "last_name": self.last_name_attribute,
            "phone": self.phone_attribute,
            "tenant": self.tenant_attribute,
            "user_type": self.user_type_attribute,
        }

    def get_role_mapping(self):
        """
        Get the role mapping configuration.

        Returns:
            dict: Role mapping from Keycloak to Trade Hub
        """
        return {
            "default_roles": [r.strip() for r in (self.default_roles or "").split(",") if r.strip()],
            "seller_role": self.seller_role_name,
            "buyer_role": self.buyer_role_name,
        }

    # =========================================================================
    # CONNECTION TEST
    # =========================================================================

    def test_connection(self):
        """
        Test the connection to Keycloak server.

        Returns:
            dict: Connection test result with status and message
        """
        import requests

        if not self.server_url or not self.realm_name:
            self.db_set("connection_status", "Failed")
            return {
                "success": False,
                "message": "Server URL and realm name are required"
            }

        try:
            # Try to fetch the OpenID configuration
            response = requests.get(
                self.well_known_url,
                timeout=cint(self.connection_timeout) or 30,
                verify=self.verify_ssl
            )

            if response.status_code == 200:
                config = response.json()

                # Verify expected endpoints are present
                required_endpoints = [
                    "authorization_endpoint",
                    "token_endpoint",
                    "userinfo_endpoint"
                ]

                missing = [ep for ep in required_endpoints if ep not in config]
                if missing:
                    self.db_set("connection_status", "Failed")
                    return {
                        "success": False,
                        "message": f"Missing endpoints in OpenID config: {', '.join(missing)}"
                    }

                self.db_set("connection_status", "Connected")
                self.db_set("last_connection_test", now_datetime())
                return {
                    "success": True,
                    "message": "Successfully connected to Keycloak server",
                    "issuer": config.get("issuer"),
                    "endpoints": {
                        "authorization": config.get("authorization_endpoint"),
                        "token": config.get("token_endpoint"),
                        "userinfo": config.get("userinfo_endpoint"),
                    }
                }
            else:
                self.db_set("connection_status", "Failed")
                return {
                    "success": False,
                    "message": f"Keycloak returned status {response.status_code}"
                }

        except requests.exceptions.SSLError as e:
            self.db_set("connection_status", "Failed")
            return {
                "success": False,
                "message": f"SSL verification failed. Consider disabling 'Verify SSL' for development. Error: {str(e)}"
            }

        except requests.exceptions.ConnectionError as e:
            self.db_set("connection_status", "Failed")
            return {
                "success": False,
                "message": f"Could not connect to Keycloak server: {str(e)}"
            }

        except requests.exceptions.Timeout:
            self.db_set("connection_status", "Failed")
            return {
                "success": False,
                "message": f"Connection timed out after {self.connection_timeout} seconds"
            }

        except Exception as e:
            self.db_set("connection_status", "Failed")
            frappe.log_error(
                message=str(e),
                title=f"Keycloak Connection Test Error for {self.tenant}"
            )
            return {
                "success": False,
                "message": str(e)
            }


# =============================================================================
# WHITELISTED API FUNCTIONS
# =============================================================================


@frappe.whitelist()
def get_keycloak_settings(tenant):
    """
    Get Keycloak settings for a tenant.

    Args:
        tenant: Tenant name

    Returns:
        dict: Keycloak settings document or None if not found
    """
    if not frappe.has_permission("Keycloak Settings", "read"):
        frappe.throw(_("Not permitted to view Keycloak settings"))

    settings = frappe.db.get_value(
        "Keycloak Settings",
        {"tenant": tenant},
        "*",
        as_dict=True
    )

    # Remove sensitive fields
    if settings:
        settings.pop("client_secret", None)
        settings.pop("admin_password", None)
        settings.pop("admin_client_secret", None)

    return settings


@frappe.whitelist()
def get_openid_config(tenant):
    """
    Get the OpenID Connect configuration for frontend integration.

    Args:
        tenant: Tenant name

    Returns:
        dict: OpenID Connect configuration for the tenant
    """
    # Check cache first
    cache_key = f"keycloak_openid:{tenant}"
    cached = frappe.cache().get_value(cache_key)
    if cached:
        return cached

    # Get from database
    settings_name = frappe.db.get_value(
        "Keycloak Settings",
        {"tenant": tenant, "enabled": 1},
        "name"
    )

    if not settings_name:
        return {"enabled": False}

    settings = frappe.get_doc("Keycloak Settings", settings_name)
    config = settings.get_openid_config()

    # Cache for 5 minutes
    frappe.cache().set_value(cache_key, config, expires_in_sec=300)

    return config


@frappe.whitelist()
def test_keycloak_connection(tenant):
    """
    Test the Keycloak connection for a tenant.

    Args:
        tenant: Tenant name

    Returns:
        dict: Connection test result
    """
    if not frappe.has_permission("Keycloak Settings", "write"):
        frappe.throw(_("Not permitted to test Keycloak connection"))

    settings_name = frappe.db.get_value(
        "Keycloak Settings",
        {"tenant": tenant},
        "name"
    )

    if not settings_name:
        return {"success": False, "message": "Keycloak settings not found"}

    settings = frappe.get_doc("Keycloak Settings", settings_name)
    return settings.test_connection()


@frappe.whitelist()
def create_keycloak_settings(
    tenant,
    server_url,
    realm_name,
    client_id,
    client_secret=None,
    public_client=False
):
    """
    Create Keycloak settings for a tenant.

    Args:
        tenant: Tenant name
        server_url: Keycloak server URL
        realm_name: Keycloak realm name
        client_id: OAuth2 client ID
        client_secret: OAuth2 client secret (optional for public clients)
        public_client: Whether this is a public client

    Returns:
        dict: Created Keycloak settings
    """
    if not frappe.has_permission("Keycloak Settings", "create"):
        frappe.throw(_("Not permitted to create Keycloak settings"))

    # Check if settings already exist
    existing = frappe.db.get_value("Keycloak Settings", {"tenant": tenant}, "name")
    if existing:
        frappe.throw(_("Keycloak settings already exist for tenant {0}").format(tenant))

    doc = frappe.get_doc({
        "doctype": "Keycloak Settings",
        "tenant": tenant,
        "enabled": 0,
        "server_url": server_url,
        "realm_name": realm_name,
        "client_id": client_id,
        "client_secret": client_secret,
        "public_client": 1 if public_client else 0,
        "auto_create_users": 1,
        "auto_update_user_info": 1,
        "sync_user_roles": 1,
    })

    doc.insert()

    # Return without sensitive data
    result = doc.as_dict()
    result.pop("client_secret", None)
    result.pop("admin_password", None)
    result.pop("admin_client_secret", None)

    return result


@frappe.whitelist()
def get_authorization_url(tenant, state=None, redirect_uri=None):
    """
    Get the OAuth2 authorization URL for initiating login.

    Args:
        tenant: Tenant name
        state: Optional state parameter for CSRF protection
        redirect_uri: Optional custom redirect URI

    Returns:
        dict: Authorization URL with parameters
    """
    settings_name = frappe.db.get_value(
        "Keycloak Settings",
        {"tenant": tenant, "enabled": 1},
        "name"
    )

    if not settings_name:
        frappe.throw(_("Keycloak SSO is not enabled for this tenant"))

    settings = frappe.get_doc("Keycloak Settings", settings_name)

    import urllib.parse
    import secrets

    # Generate state if not provided
    if not state:
        state = secrets.token_urlsafe(32)

    params = {
        "client_id": settings.client_id,
        "response_type": "code",
        "scope": "openid profile email",
        "redirect_uri": redirect_uri or settings.redirect_uri,
        "state": state,
    }

    # Add PKCE challenge if enabled
    if settings.pkce_enabled:
        code_verifier = secrets.token_urlsafe(64)[:128]
        import hashlib
        import base64
        code_challenge = base64.urlsafe_b64encode(
            hashlib.sha256(code_verifier.encode()).digest()
        ).decode().rstrip("=")

        params["code_challenge"] = code_challenge
        params["code_challenge_method"] = "S256"

        # Store verifier in session/cache for later use
        frappe.cache().set_value(
            f"keycloak_pkce:{state}",
            code_verifier,
            expires_in_sec=600
        )

    auth_url = f"{settings.get_authorization_url()}?{urllib.parse.urlencode(params)}"

    return {
        "authorization_url": auth_url,
        "state": state,
    }


@frappe.whitelist()
def get_logout_url(tenant, id_token_hint=None, redirect_uri=None):
    """
    Get the logout URL for ending the Keycloak session.

    Args:
        tenant: Tenant name
        id_token_hint: Optional ID token for session identification
        redirect_uri: Optional post-logout redirect URI

    Returns:
        dict: Logout URL
    """
    settings_name = frappe.db.get_value(
        "Keycloak Settings",
        {"tenant": tenant, "enabled": 1},
        "name"
    )

    if not settings_name:
        frappe.throw(_("Keycloak SSO is not enabled for this tenant"))

    settings = frappe.get_doc("Keycloak Settings", settings_name)

    import urllib.parse

    params = {}
    if id_token_hint:
        params["id_token_hint"] = id_token_hint
    if redirect_uri or settings.post_logout_redirect_uri:
        params["post_logout_redirect_uri"] = redirect_uri or settings.post_logout_redirect_uri

    logout_url = settings.get_logout_url()
    if params:
        logout_url = f"{logout_url}?{urllib.parse.urlencode(params)}"

    return {"logout_url": logout_url}


@frappe.whitelist()
def get_social_providers(tenant):
    """
    Get enabled social login providers for a tenant.

    Args:
        tenant: Tenant name

    Returns:
        dict: Social login provider configuration
    """
    settings = frappe.db.get_value(
        "Keycloak Settings",
        {"tenant": tenant, "enabled": 1},
        [
            "enable_google_login",
            "enable_facebook_login",
            "enable_apple_login",
            "enable_linkedin_login"
        ],
        as_dict=True
    )

    if not settings:
        return {"enabled": False, "providers": []}

    providers = []
    if settings.enable_google_login:
        providers.append({"id": "google", "name": "Google"})
    if settings.enable_facebook_login:
        providers.append({"id": "facebook", "name": "Facebook"})
    if settings.enable_apple_login:
        providers.append({"id": "apple", "name": "Apple"})
    if settings.enable_linkedin_login:
        providers.append({"id": "linkedin", "name": "LinkedIn"})

    return {
        "enabled": True,
        "providers": providers
    }

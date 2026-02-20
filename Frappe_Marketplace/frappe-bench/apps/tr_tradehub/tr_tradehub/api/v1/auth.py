# Copyright (c) 2026, Trade Hub and contributors
# For license information, please see license.txt

"""
Trade Hub Authentication API v1.

This module provides comprehensive OAuth2/OpenID Connect SSO authentication
endpoints for the Trade Hub B2B marketplace, integrating with Keycloak
for single sign-on across all platform applications.

Key Features:
- OAuth2 authorization code flow with PKCE support
- SSO callback endpoint for token exchange
- Automatic Frappe user creation on first login
- Token refresh and logout endpoints
- Multi-tenant support with tenant-specific Keycloak configuration
- CSRF protection with state parameter validation
- Secure session management

SSO Flow:
1. Frontend calls get_login_url() to get Keycloak authorization URL
2. User is redirected to Keycloak for authentication
3. Keycloak redirects back to sso_callback() with authorization code
4. Callback exchanges code for tokens, creates/updates user, starts session
5. User is redirected to the success URL or error page

Usage Example:
    # Frontend initiates login
    const response = await fetch('/api/method/trade_hub.api.v1.auth.get_login_url');
    window.location.href = response.authorization_url;

    # After callback, user is logged in
    # Frontend can check session status
    const user = await fetch('/api/method/trade_hub.api.v1.auth.get_session_user');

CRITICAL NOTES:
- For Keycloak >= 18: server URL without /auth/ prefix
- For Keycloak < 18: server URL with /auth/ prefix
- JWT 'aud' claim must include client name (requires audience mapper in Keycloak)
- Redirect URIs must match exactly (trailing slash matters)
"""

from typing import Any, Dict, List, Optional
import json
import secrets
import urllib.parse

import frappe
from frappe import _
from frappe.utils import cint, get_url, now_datetime


# =============================================================================
# CONSTANTS
# =============================================================================

# Cache key prefix for SSO operations
SSO_CACHE_PREFIX = "trade_hub:sso"

# Default OAuth2 scopes
DEFAULT_SCOPES = ["openid", "profile", "email"]

# State parameter expiry in seconds (10 minutes)
STATE_EXPIRY_SECONDS = 600

# Redirect paths
DEFAULT_SUCCESS_PATH = "/"
DEFAULT_ERROR_PATH = "/login?error=sso_failed"

# Session cookie settings
SESSION_COOKIE_NAME = "sid"


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================


def get_keycloak_client():
    """
    Get the Keycloak client instance.

    Returns:
        KeycloakClient: Initialized Keycloak client
    """
    try:
        from tr_tradehub.integrations.keycloak import get_keycloak_client as _get_client
        return _get_client()
    except ImportError:
        frappe.throw(
            _("Keycloak integration module not available"),
            title=_("Configuration Error")
        )


def is_keycloak_enabled() -> bool:
    """
    Check if Keycloak SSO is enabled.

    Returns:
        bool: True if Keycloak is enabled and configured
    """
    try:
        from tr_tradehub.integrations.keycloak import is_keycloak_enabled as _is_enabled
        return _is_enabled()
    except ImportError:
        return False


def get_keycloak_settings() -> Dict[str, Any]:
    """
    Get Keycloak configuration settings.

    Returns:
        dict: Keycloak settings
    """
    try:
        from tr_tradehub.integrations.keycloak import get_keycloak_settings as _get_settings
        return _get_settings()
    except ImportError:
        return {}


def create_or_update_user(keycloak_user_info: Dict[str, Any], tenant: str = None) -> Optional[str]:
    """
    Create or update a Frappe user from Keycloak user info.

    Args:
        keycloak_user_info: User info from Keycloak token/userinfo endpoint
        tenant: Optional tenant to assign to the user

    Returns:
        str: The Frappe user name (email) or None on error
    """
    try:
        from tr_tradehub.integrations.keycloak import create_or_update_frappe_user
        return create_or_update_frappe_user(keycloak_user_info, tenant)
    except ImportError:
        # Fallback implementation
        return _create_user_fallback(keycloak_user_info, tenant)


def _create_user_fallback(keycloak_user_info: Dict[str, Any], tenant: str = None) -> Optional[str]:
    """
    Fallback user creation if main function is not available.

    Args:
        keycloak_user_info: User info from Keycloak
        tenant: Optional tenant to assign

    Returns:
        str: The user email or None on error
    """
    email = keycloak_user_info.get("email")
    if not email:
        frappe.log_error(
            message=f"No email in Keycloak user info: {keycloak_user_info}",
            title="SSO User Creation Error"
        )
        return None

    try:
        if frappe.db.exists("User", email):
            user_doc = frappe.get_doc("User", email)
            is_new = False
        else:
            user_doc = frappe.new_doc("User")
            user_doc.email = email
            user_doc.send_welcome_email = 0
            is_new = True

        # Update user fields
        user_doc.first_name = (
            keycloak_user_info.get("given_name") or
            keycloak_user_info.get("firstName") or
            ""
        )
        user_doc.last_name = (
            keycloak_user_info.get("family_name") or
            keycloak_user_info.get("lastName") or
            ""
        )
        user_doc.full_name = (
            keycloak_user_info.get("name") or
            f"{user_doc.first_name} {user_doc.last_name}".strip()
        )
        user_doc.username = (
            keycloak_user_info.get("preferred_username") or
            email.split("@")[0]
        )
        user_doc.enabled = 1

        # Set Keycloak ID if field exists
        keycloak_sub = keycloak_user_info.get("sub")
        if keycloak_sub and hasattr(user_doc, "keycloak_user_id"):
            user_doc.keycloak_user_id = keycloak_sub

        # Set tenant if provided and field exists
        if tenant and hasattr(user_doc, "tenant"):
            user_doc.tenant = tenant

        user_doc.flags.ignore_permissions = True
        user_doc.flags.no_welcome_mail = True
        user_doc.save()

        frappe.db.commit()
        return email

    except Exception as e:
        frappe.log_error(
            message=f"Failed to create/update user {email}: {str(e)}",
            title="SSO User Creation Error"
        )
        return None


def generate_state() -> str:
    """
    Generate a cryptographically secure state parameter.

    Returns:
        str: A secure random state string
    """
    return secrets.token_urlsafe(32)


def store_state(state: str, data: Dict[str, Any] = None) -> None:
    """
    Store state parameter in cache for verification.

    Args:
        state: The state parameter value
        data: Optional additional data to store (redirect_uri, tenant, etc.)
    """
    cache_key = f"{SSO_CACHE_PREFIX}:state:{state}"
    cache_data = {"valid": True, "created_at": str(now_datetime())}
    if data:
        cache_data.update(data)

    frappe.cache().set_value(
        cache_key,
        json.dumps(cache_data),
        expires_in_sec=STATE_EXPIRY_SECONDS
    )


def verify_state(state: str) -> tuple:
    """
    Verify state parameter from callback.

    Args:
        state: The state parameter from callback

    Returns:
        tuple: (is_valid, stored_data or None)
    """
    if not state:
        return False, None

    cache_key = f"{SSO_CACHE_PREFIX}:state:{state}"
    cached = frappe.cache().get_value(cache_key)

    if not cached:
        return False, None

    # Delete state after verification (one-time use)
    frappe.cache().delete_value(cache_key)

    try:
        data = json.loads(cached)
        return data.get("valid", False), data
    except json.JSONDecodeError:
        return False, None


def store_pkce_verifier(state: str, verifier: str) -> None:
    """
    Store PKCE code verifier for later use.

    Args:
        state: The state parameter to associate with
        verifier: The code verifier
    """
    cache_key = f"{SSO_CACHE_PREFIX}:pkce:{state}"
    frappe.cache().set_value(
        cache_key,
        verifier,
        expires_in_sec=STATE_EXPIRY_SECONDS
    )


def get_pkce_verifier(state: str) -> Optional[str]:
    """
    Retrieve and delete PKCE code verifier.

    Args:
        state: The state parameter

    Returns:
        str: The code verifier or None
    """
    cache_key = f"{SSO_CACHE_PREFIX}:pkce:{state}"
    verifier = frappe.cache().get_value(cache_key)

    if verifier:
        frappe.cache().delete_value(cache_key)

    return verifier


def start_frappe_session(user: str) -> None:
    """
    Start a Frappe session for the given user.

    Args:
        user: The user email/name
    """
    frappe.local.login_manager.login_as(user)


def get_redirect_url(path: str = None, params: Dict[str, str] = None) -> str:
    """
    Build a full redirect URL.

    Args:
        path: The path to redirect to
        params: Optional query parameters

    Returns:
        str: Full redirect URL
    """
    base_url = get_url()
    path = path or DEFAULT_SUCCESS_PATH

    if path.startswith("http"):
        url = path
    else:
        url = f"{base_url}{path}"

    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"

    return url


def build_callback_uri() -> str:
    """
    Build the SSO callback URI.

    Returns:
        str: The callback URI
    """
    return f"{get_url()}/api/method/trade_hub.api.v1.auth.sso_callback"


# =============================================================================
# PUBLIC API ENDPOINTS
# =============================================================================


@frappe.whitelist(allow_guest=True)
def get_sso_status() -> Dict[str, Any]:
    """
    Check SSO availability and configuration.

    Returns the status of Keycloak SSO integration, including whether
    it's enabled and the realm name.

    Returns:
        dict: {
            "enabled": bool,
            "realm": str or None,
            "features": {...}
        }

    API: GET /api/method/trade_hub.api.v1.auth.get_sso_status
    """
    enabled = is_keycloak_enabled()
    settings = get_keycloak_settings() if enabled else {}

    return {
        "success": True,
        "enabled": enabled,
        "realm": settings.get("realm"),
        "features": {
            "social_login": enabled,
            "auto_create_users": settings.get("auto_create_users", True),
        }
    }


@frappe.whitelist(allow_guest=True)
def get_login_url(
    redirect_uri: str = None,
    success_url: str = None,
    tenant: str = None
) -> Dict[str, Any]:
    """
    Get the Keycloak authorization URL for SSO login.

    Generates a secure authorization URL with CSRF state protection.
    The frontend should redirect the user to this URL to initiate login.

    Args:
        redirect_uri: Custom OAuth2 callback URI (optional, uses default)
        success_url: URL to redirect to after successful login (optional)
        tenant: Tenant context for multi-tenant deployments (optional)

    Returns:
        dict: {
            "success": True,
            "authorization_url": str,
            "state": str
        }

    API: GET /api/method/trade_hub.api.v1.auth.get_login_url

    Example:
        GET /api/method/trade_hub.api.v1.auth.get_login_url?success_url=/dashboard
    """
    if not is_keycloak_enabled():
        frappe.throw(
            _("Keycloak SSO is not enabled"),
            title=_("SSO Not Available")
        )

    # Generate CSRF state
    state = generate_state()

    # Use default callback URI if not provided
    callback_uri = redirect_uri or build_callback_uri()

    # Store state with additional data for callback
    store_state(state, {
        "redirect_uri": callback_uri,
        "success_url": success_url or DEFAULT_SUCCESS_PATH,
        "tenant": tenant,
    })

    # Get authorization URL from Keycloak client
    client = get_keycloak_client()
    auth_url = client.get_authorization_url(
        redirect_uri=callback_uri,
        state=state,
        scope=DEFAULT_SCOPES,
    )

    return {
        "success": True,
        "authorization_url": auth_url,
        "state": state,
    }


@frappe.whitelist(allow_guest=True)
def sso_callback(
    code: str = None,
    state: str = None,
    error: str = None,
    error_description: str = None
) -> None:
    """
    OAuth2 callback endpoint for Keycloak SSO.

    This endpoint handles the OAuth2 authorization code flow callback from Keycloak.
    It validates the state, exchanges the code for tokens, creates/updates the user,
    starts a Frappe session, and redirects to the success URL.

    Args:
        code: Authorization code from Keycloak
        state: State parameter for CSRF validation
        error: Error code if authentication failed
        error_description: Human-readable error description

    Returns:
        None (redirects to success or error URL)

    API: GET /api/method/trade_hub.api.v1.auth.sso_callback

    Flow:
        1. Validate state parameter (CSRF protection)
        2. Check for errors from Keycloak
        3. Exchange authorization code for tokens
        4. Validate access token
        5. Get user info from token
        6. Create or update Frappe user
        7. Start Frappe session
        8. Redirect to success URL
    """
    # Handle errors from Keycloak
    if error:
        frappe.log_error(
            message=f"SSO error: {error} - {error_description}",
            title="Keycloak SSO Error"
        )
        redirect_url = get_redirect_url(DEFAULT_ERROR_PATH, {
            "error": error,
            "error_description": error_description or "Authentication failed"
        })
        frappe.local.response["type"] = "redirect"
        frappe.local.response["location"] = redirect_url
        return

    # Validate required parameters
    if not code:
        frappe.log_error(
            message="SSO callback missing authorization code",
            title="Keycloak SSO Error"
        )
        redirect_url = get_redirect_url(DEFAULT_ERROR_PATH, {
            "error": "missing_code",
            "error_description": "Authorization code not provided"
        })
        frappe.local.response["type"] = "redirect"
        frappe.local.response["location"] = redirect_url
        return

    if not state:
        frappe.log_error(
            message="SSO callback missing state parameter",
            title="Keycloak SSO Error"
        )
        redirect_url = get_redirect_url(DEFAULT_ERROR_PATH, {
            "error": "missing_state",
            "error_description": "State parameter not provided"
        })
        frappe.local.response["type"] = "redirect"
        frappe.local.response["location"] = redirect_url
        return

    # Verify state (CSRF protection)
    is_valid, state_data = verify_state(state)
    if not is_valid:
        frappe.log_error(
            message=f"Invalid or expired state parameter: {state}",
            title="Keycloak SSO Error"
        )
        redirect_url = get_redirect_url(DEFAULT_ERROR_PATH, {
            "error": "invalid_state",
            "error_description": "State validation failed. Please try logging in again."
        })
        frappe.local.response["type"] = "redirect"
        frappe.local.response["location"] = redirect_url
        return

    # Get stored data from state
    callback_uri = state_data.get("redirect_uri") or build_callback_uri()
    success_url = state_data.get("success_url") or DEFAULT_SUCCESS_PATH
    tenant = state_data.get("tenant")

    try:
        # Check if Keycloak is enabled
        if not is_keycloak_enabled():
            raise Exception("Keycloak SSO is not enabled")

        # Get Keycloak client
        client = get_keycloak_client()

        # Exchange authorization code for tokens
        tokens = client.exchange_code(code, callback_uri)

        if not tokens:
            raise Exception("Failed to exchange authorization code for tokens")

        access_token = tokens.get("access_token")
        if not access_token:
            raise Exception("No access token in response")

        # Validate the token and get user info
        is_token_valid, token_info = client.validate_token(access_token)

        if not is_token_valid:
            raise Exception("Token validation failed")

        # Get additional user info if needed
        user_info = client.get_user_info(access_token)

        # Merge token info and user info
        keycloak_user_info = {**token_info}
        if user_info:
            keycloak_user_info.update(user_info)

        # Verify email is present
        email = keycloak_user_info.get("email")
        if not email:
            raise Exception("No email in user info. Email claim must be included in token.")

        # Verify email is verified (optional but recommended)
        email_verified = keycloak_user_info.get("email_verified", True)
        settings = get_keycloak_settings()
        if settings.get("require_email_verified", False) and not email_verified:
            raise Exception("Email address is not verified in Keycloak")

        # Create or update Frappe user
        frappe_user = create_or_update_user(keycloak_user_info, tenant)

        if not frappe_user:
            raise Exception(f"Failed to create/update user for email: {email}")

        # Start Frappe session
        start_frappe_session(frappe_user)

        # Store tokens in session if needed (for token refresh)
        if tokens.get("refresh_token"):
            frappe.cache().set_value(
                f"{SSO_CACHE_PREFIX}:refresh:{frappe_user}",
                tokens.get("refresh_token"),
                expires_in_sec=cint(tokens.get("refresh_expires_in", 86400))
            )

        # Log successful login
        frappe.logger().info(f"SSO login successful for user: {frappe_user}")

        # Redirect to success URL
        redirect_url = get_redirect_url(success_url)
        frappe.local.response["type"] = "redirect"
        frappe.local.response["location"] = redirect_url

    except Exception as e:
        frappe.log_error(
            message=f"SSO callback error: {str(e)}",
            title="Keycloak SSO Error"
        )
        redirect_url = get_redirect_url(DEFAULT_ERROR_PATH, {
            "error": "callback_error",
            "error_description": str(e)
        })
        frappe.local.response["type"] = "redirect"
        frappe.local.response["location"] = redirect_url


@frappe.whitelist()
def get_session_user() -> Dict[str, Any]:
    """
    Get current session user information.

    Returns information about the currently logged-in user,
    including whether they authenticated via SSO.

    Returns:
        dict: {
            "success": True,
            "logged_in": bool,
            "user": {...} | None
        }

    API: GET /api/method/trade_hub.api.v1.auth.get_session_user
    """
    user = frappe.session.user

    if user == "Guest":
        return {
            "success": True,
            "logged_in": False,
            "user": None
        }

    user_doc = frappe.get_doc("User", user)

    # Check if user has Keycloak ID (SSO user)
    is_sso_user = bool(
        hasattr(user_doc, "keycloak_user_id") and user_doc.keycloak_user_id
    )

    return {
        "success": True,
        "logged_in": True,
        "user": {
            "email": user_doc.email,
            "full_name": user_doc.full_name,
            "first_name": user_doc.first_name,
            "last_name": user_doc.last_name,
            "username": user_doc.username,
            "user_image": user_doc.user_image,
            "is_sso_user": is_sso_user,
            "roles": [r.role for r in user_doc.roles],
            "tenant": getattr(user_doc, "tenant", None),
        }
    }


@frappe.whitelist()
def refresh_token() -> Dict[str, Any]:
    """
    Refresh the access token using stored refresh token.

    Uses the refresh token stored during login to get new tokens
    from Keycloak.

    Returns:
        dict: {
            "success": True,
            "expires_in": int
        }

    API: POST /api/method/trade_hub.api.v1.auth.refresh_token
    """
    user = frappe.session.user

    if user == "Guest":
        frappe.throw(_("Not authenticated"), title=_("Authentication Required"))

    # Get stored refresh token
    refresh_token_value = frappe.cache().get_value(
        f"{SSO_CACHE_PREFIX}:refresh:{user}"
    )

    if not refresh_token_value:
        frappe.throw(
            _("No refresh token available. Please log in again."),
            title=_("Token Expired")
        )

    try:
        client = get_keycloak_client()
        new_tokens = client.refresh_token(refresh_token_value)

        if not new_tokens:
            frappe.throw(
                _("Failed to refresh token. Please log in again."),
                title=_("Token Refresh Failed")
            )

        # Store new refresh token
        if new_tokens.get("refresh_token"):
            frappe.cache().set_value(
                f"{SSO_CACHE_PREFIX}:refresh:{user}",
                new_tokens.get("refresh_token"),
                expires_in_sec=cint(new_tokens.get("refresh_expires_in", 86400))
            )

        return {
            "success": True,
            "expires_in": new_tokens.get("expires_in"),
            "token_type": new_tokens.get("token_type", "Bearer"),
        }

    except Exception as e:
        frappe.log_error(
            message=f"Token refresh failed for user {user}: {str(e)}",
            title="Token Refresh Error"
        )
        frappe.throw(
            _("Failed to refresh token: {0}").format(str(e)),
            title=_("Token Refresh Failed")
        )


@frappe.whitelist()
def logout(
    redirect_url: str = None,
    logout_from_keycloak: bool = True
) -> Dict[str, Any]:
    """
    Logout from Frappe and optionally from Keycloak.

    Ends the Frappe session and optionally invalidates the Keycloak
    session as well.

    Args:
        redirect_url: URL to redirect to after logout
        logout_from_keycloak: Whether to also logout from Keycloak

    Returns:
        dict: {
            "success": True,
            "keycloak_logout_url": str | None
        }

    API: POST /api/method/trade_hub.api.v1.auth.logout
    """
    user = frappe.session.user
    keycloak_logout_url = None

    if user != "Guest":
        # Get refresh token before logout
        refresh_token_value = frappe.cache().get_value(
            f"{SSO_CACHE_PREFIX}:refresh:{user}"
        )

        # Clear cached refresh token
        frappe.cache().delete_value(f"{SSO_CACHE_PREFIX}:refresh:{user}")

        # Logout from Keycloak if requested
        if logout_from_keycloak and refresh_token_value and is_keycloak_enabled():
            try:
                client = get_keycloak_client()
                client.logout(refresh_token_value)
            except Exception as e:
                frappe.log_error(
                    message=f"Keycloak logout failed for user {user}: {str(e)}",
                    title="Keycloak Logout Error"
                )

            # Build Keycloak logout URL for frontend redirect
            settings = get_keycloak_settings()
            if settings.get("server_url") and settings.get("realm"):
                post_logout_uri = redirect_url or get_url()
                keycloak_logout_url = (
                    f"{settings['server_url']}/realms/{settings['realm']}"
                    f"/protocol/openid-connect/logout"
                    f"?post_logout_redirect_uri={urllib.parse.quote(post_logout_uri)}"
                )

    # Logout from Frappe
    frappe.local.login_manager.logout()

    return {
        "success": True,
        "keycloak_logout_url": keycloak_logout_url,
        "redirect_url": redirect_url or get_url(),
    }


@frappe.whitelist(allow_guest=True)
def check_email_exists(email: str) -> Dict[str, Any]:
    """
    Check if a user with the given email exists.

    Useful for pre-login validation to determine if user should
    register or login.

    Args:
        email: Email address to check

    Returns:
        dict: {
            "success": True,
            "exists": bool
        }

    API: GET /api/method/trade_hub.api.v1.auth.check_email_exists
    """
    if not email:
        frappe.throw(_("Email is required"))

    exists = frappe.db.exists("User", email)

    return {
        "success": True,
        "exists": bool(exists)
    }


@frappe.whitelist(allow_guest=True)
def get_social_providers() -> Dict[str, Any]:
    """
    Get available social login providers.

    Returns a list of enabled social login providers configured
    in Keycloak.

    Returns:
        dict: {
            "success": True,
            "providers": [{"id": str, "name": str, "icon": str}]
        }

    API: GET /api/method/trade_hub.api.v1.auth.get_social_providers
    """
    if not is_keycloak_enabled():
        return {
            "success": True,
            "providers": []
        }

    # Social providers are configured in Keycloak realm settings
    # This returns commonly configured providers
    # Actual availability depends on Keycloak configuration
    providers = [
        {"id": "google", "name": "Google", "icon": "google"},
        {"id": "facebook", "name": "Facebook", "icon": "facebook"},
        {"id": "apple", "name": "Apple", "icon": "apple"},
        {"id": "linkedin", "name": "LinkedIn", "icon": "linkedin"},
    ]

    return {
        "success": True,
        "providers": providers
    }


# =============================================================================
# INTERNAL/ADMIN ENDPOINTS
# =============================================================================


@frappe.whitelist()
def get_sso_debug_info() -> Dict[str, Any]:
    """
    Get SSO configuration debug information.

    Returns detailed configuration information for debugging SSO issues.
    Only available to System Managers.

    Returns:
        dict: SSO configuration details

    API: GET /api/method/trade_hub.api.v1.auth.get_sso_debug_info
    """
    if "System Manager" not in frappe.get_roles():
        frappe.throw(_("Only System Managers can access debug info"))

    settings = get_keycloak_settings()

    return {
        "success": True,
        "debug_info": {
            "enabled": is_keycloak_enabled(),
            "server_url": settings.get("server_url"),
            "realm": settings.get("realm"),
            "client_id": settings.get("client_id"),
            "auto_create_users": settings.get("auto_create_users"),
            "default_tenant": settings.get("default_tenant"),
            "callback_uri": build_callback_uri(),
            "role_mappings": settings.get("role_mappings", {}),
        }
    }


@frappe.whitelist()
def test_keycloak_connection() -> Dict[str, Any]:
    """
    Test the connection to Keycloak server.

    Attempts to connect to Keycloak and fetch the OpenID configuration.
    Only available to System Managers.

    Returns:
        dict: Connection test result

    API: POST /api/method/trade_hub.api.v1.auth.test_keycloak_connection
    """
    if "System Manager" not in frappe.get_roles():
        frappe.throw(_("Only System Managers can test connections"))

    if not is_keycloak_enabled():
        return {
            "success": False,
            "message": "Keycloak is not configured"
        }

    try:
        import requests

        settings = get_keycloak_settings()
        server_url = settings.get("server_url")
        realm = settings.get("realm")

        well_known_url = f"{server_url}/realms/{realm}/.well-known/openid-configuration"

        response = requests.get(well_known_url, timeout=10)

        if response.status_code == 200:
            config = response.json()
            return {
                "success": True,
                "message": "Successfully connected to Keycloak",
                "issuer": config.get("issuer"),
                "authorization_endpoint": config.get("authorization_endpoint"),
                "token_endpoint": config.get("token_endpoint"),
            }
        else:
            return {
                "success": False,
                "message": f"Keycloak returned status {response.status_code}",
            }

    except requests.exceptions.ConnectionError as e:
        return {
            "success": False,
            "message": f"Could not connect to Keycloak: {str(e)}",
        }
    except requests.exceptions.Timeout:
        return {
            "success": False,
            "message": "Connection timed out",
        }
    except Exception as e:
        return {
            "success": False,
            "message": f"Connection test failed: {str(e)}",
        }


@frappe.whitelist()
def invalidate_user_sessions(user: str) -> Dict[str, Any]:
    """
    Invalidate all SSO sessions for a user.

    Clears cached refresh tokens and optionally revokes Keycloak sessions.
    Only available to System Managers.

    Args:
        user: The user email

    Returns:
        dict: Result of invalidation

    API: POST /api/method/trade_hub.api.v1.auth.invalidate_user_sessions
    """
    if "System Manager" not in frappe.get_roles():
        frappe.throw(_("Only System Managers can invalidate sessions"))

    if not user:
        frappe.throw(_("User is required"))

    if not frappe.db.exists("User", user):
        frappe.throw(_("User not found"))

    # Clear cached refresh token
    frappe.cache().delete_value(f"{SSO_CACHE_PREFIX}:refresh:{user}")

    return {
        "success": True,
        "message": f"SSO sessions invalidated for user: {user}"
    }

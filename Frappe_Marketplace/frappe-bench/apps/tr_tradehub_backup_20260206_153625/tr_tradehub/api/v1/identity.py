# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

"""
Identity & Access API Endpoints for TR-TradeHub Marketplace

This module provides API endpoints for:
- User registration (individual and organization)
- Login with enhancements (2FA, KVKK consent)
- Password management (change, reset, forgot)
- Profile management
- Session management
- Email/Phone verification
- Two-factor authentication (2FA) management
- Account security settings

API URL Pattern:
    POST /api/method/tr_tradehub.api.v1.identity.<function_name>

All endpoints follow Frappe conventions and patterns from frappe/auth.py
"""

import hashlib
import secrets
import re
from typing import Any, Dict, List, Optional

import frappe
from frappe import _
from frappe.utils import (
    cint,
    cstr,
    flt,
    getdate,
    nowdate,
    now_datetime,
    add_days,
    get_datetime,
    random_string,
    get_url,
)
from frappe.utils.password import (
    update_password as _update_password,
    check_password,
)


# =============================================================================
# CONSTANTS & CONFIGURATION
# =============================================================================

# Rate limiting settings (per user/IP)
RATE_LIMITS = {
    "register": {"limit": 5, "window": 3600},  # 5 registrations per hour per IP
    "login": {"limit": 10, "window": 300},  # 10 login attempts per 5 min
    "password_reset": {"limit": 3, "window": 3600},  # 3 reset requests per hour
    "verification": {"limit": 5, "window": 300},  # 5 verification attempts per 5 min
    "2fa_verify": {"limit": 5, "window": 300},  # 5 2FA attempts per 5 min
}

# Password requirements
PASSWORD_MIN_LENGTH = 8
PASSWORD_REQUIREMENTS = {
    "min_length": 8,
    "require_uppercase": True,
    "require_lowercase": True,
    "require_digit": True,
    "require_special": False,  # Optional but recommended
}

# Verification code settings
VERIFICATION_CODE_LENGTH = 6
VERIFICATION_CODE_EXPIRY_MINUTES = 15


# =============================================================================
# RATE LIMITING
# =============================================================================


def check_rate_limit(
    action: str,
    identifier: Optional[str] = None,
    throw: bool = True,
) -> bool:
    """
    Check if an action is rate limited.

    Args:
        action: The action to check (e.g., "register", "login")
        identifier: User/IP identifier (defaults to request IP)
        throw: If True, raises exception when rate limited

    Returns:
        bool: True if allowed, False if rate limited

    Raises:
        frappe.TooManyRequestsError: If throw=True and rate limited
    """
    if action not in RATE_LIMITS:
        return True

    config = RATE_LIMITS[action]

    # Get identifier (use IP address by default)
    if not identifier:
        try:
            identifier = frappe.request.remote_addr if frappe.request else "unknown"
        except Exception:
            identifier = "unknown"

    cache_key = f"rate_limit:{action}:{identifier}"

    # Get current count
    current = frappe.cache().get_value(cache_key)
    if current is None:
        # First request
        frappe.cache().set_value(cache_key, 1, expires_in_sec=config["window"])
        return True

    current = cint(current)
    if current >= config["limit"]:
        if throw:
            frappe.throw(
                _("Too many requests. Please try again later."),
                exc=frappe.TooManyRequestsError,
            )
        return False

    # Increment counter
    frappe.cache().set_value(cache_key, current + 1, expires_in_sec=config["window"])
    return True


# =============================================================================
# VALIDATION HELPERS
# =============================================================================


def validate_email_format(email: str) -> bool:
    """Validate email format using regex."""
    if not email:
        return False
    pattern = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
    return bool(re.match(pattern, email.strip()))


def validate_phone_format(phone: str, country: str = "TR") -> bool:
    """
    Validate phone number format.

    Args:
        phone: Phone number to validate
        country: Country code for format validation

    Returns:
        bool: True if valid
    """
    if not phone:
        return False

    # Remove spaces and dashes
    phone = re.sub(r"[\s\-\(\)]", "", phone)

    if country == "TR":
        # Turkish phone: starts with +90 or 0, followed by 10 digits
        pattern = r"^(\+90|0)?[5][0-9]{9}$"
        return bool(re.match(pattern, phone))

    # Generic international format
    pattern = r"^\+?[1-9]\d{6,14}$"
    return bool(re.match(pattern, phone))


def validate_password_strength(password: str) -> Dict[str, Any]:
    """
    Validate password meets security requirements.

    Args:
        password: Password to validate

    Returns:
        dict: Validation result with is_valid and errors list
    """
    errors = []

    if len(password) < PASSWORD_REQUIREMENTS["min_length"]:
        errors.append(
            _("Password must be at least {0} characters").format(
                PASSWORD_REQUIREMENTS["min_length"]
            )
        )

    if PASSWORD_REQUIREMENTS["require_uppercase"] and not re.search(r"[A-Z]", password):
        errors.append(_("Password must contain at least one uppercase letter"))

    if PASSWORD_REQUIREMENTS["require_lowercase"] and not re.search(r"[a-z]", password):
        errors.append(_("Password must contain at least one lowercase letter"))

    if PASSWORD_REQUIREMENTS["require_digit"] and not re.search(r"\d", password):
        errors.append(_("Password must contain at least one number"))

    if PASSWORD_REQUIREMENTS["require_special"] and not re.search(
        r"[!@#$%^&*(),.?\":{}|<>]", password
    ):
        errors.append(_("Password must contain at least one special character"))

    return {"is_valid": len(errors) == 0, "errors": errors}


def validate_tckn(tckn: str) -> bool:
    """
    Validate Turkish Citizenship Number (TCKN).

    Args:
        tckn: TCKN to validate

    Returns:
        bool: True if valid
    """
    if not tckn or len(tckn) != 11:
        return False

    if not tckn.isdigit() or tckn[0] == "0":
        return False

    try:
        digits = [int(d) for d in tckn]

        # 10th digit check
        odd_sum = sum(digits[i] for i in range(0, 9, 2))
        even_sum = sum(digits[i] for i in range(1, 8, 2))
        check_10 = (odd_sum * 7 - even_sum) % 10

        if check_10 != digits[9]:
            return False

        # 11th digit check
        check_11 = sum(digits[:10]) % 10
        return check_11 == digits[10]
    except (ValueError, IndexError):
        return False


def normalize_phone(phone: str, country: str = "TR") -> str:
    """Normalize phone number to standard format."""
    phone = re.sub(r"[\s\-\(\)]", "", phone)

    if country == "TR":
        # Convert to +90 format
        if phone.startswith("0"):
            phone = "+90" + phone[1:]
        elif not phone.startswith("+"):
            phone = "+90" + phone

    return phone


# =============================================================================
# REGISTRATION ENDPOINTS
# =============================================================================


@frappe.whitelist(allow_guest=True)
def register(
    email: str,
    password: str,
    first_name: str,
    last_name: str,
    phone: Optional[str] = None,
    account_type: str = "Individual",
    accept_terms: bool = False,
    accept_kvkk: bool = False,
    marketing_consent: bool = False,
    tenant_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Register a new user account on TR-TradeHub marketplace.

    This endpoint handles individual user registration. For organization
    registration, use register_organization endpoint.

    Args:
        email: User's email address (will be used as username)
        password: User's password (must meet security requirements)
        first_name: User's first name
        last_name: User's last name
        phone: Optional phone number
        account_type: "Individual" or "Business" (default: Individual)
        accept_terms: Must be True to register
        accept_kvkk: KVKK consent (required for Turkish users)
        marketing_consent: Optional marketing communications consent
        tenant_id: Optional tenant for multi-tenant registration

    Returns:
        dict: Registration result with user info or error

    Example:
        POST /api/method/tr_tradehub.api.v1.identity.register
        {
            "email": "user@example.com",
            "password": "SecurePass123",
            "first_name": "John",
            "last_name": "Doe",
            "accept_terms": true,
            "accept_kvkk": true
        }
    """
    # Rate limiting
    check_rate_limit("register")

    # Validate required fields
    if not email or not password or not first_name or not last_name:
        frappe.throw(_("Email, password, first name, and last name are required"))

    email = email.strip().lower()
    first_name = first_name.strip()
    last_name = last_name.strip()

    # Validate email format
    if not validate_email_format(email):
        frappe.throw(_("Please enter a valid email address"))

    # Check if email already exists
    if frappe.db.exists("User", email):
        frappe.throw(_("An account with this email already exists"))

    # Validate password strength
    password_check = validate_password_strength(password)
    if not password_check["is_valid"]:
        frappe.throw("\n".join(password_check["errors"]))

    # Validate phone if provided
    if phone:
        phone = normalize_phone(phone)
        if not validate_phone_format(phone):
            frappe.throw(_("Please enter a valid phone number"))

    # Validate terms acceptance
    if not accept_terms:
        frappe.throw(_("You must accept the terms and conditions to register"))

    # Validate KVKK consent
    if not accept_kvkk:
        frappe.throw(_("KVKK consent is required to register"))

    # Create user
    try:
        user = frappe.get_doc(
            {
                "doctype": "User",
                "email": email,
                "first_name": first_name,
                "last_name": last_name,
                "full_name": f"{first_name} {last_name}",
                "enabled": 1,
                "new_password": password,
                "user_type": "Website User",
                "send_welcome_email": 0,  # We'll handle verification ourselves
                "mobile_no": phone,
            }
        )
        user.flags.ignore_permissions = True
        user.flags.no_welcome_mail = True
        user.insert()

        # Assign marketplace buyer role
        user.add_roles("Marketplace Buyer")

        # Set default tenant if provided
        if tenant_id and frappe.db.exists("Tenant", tenant_id):
            frappe.db.set_value("User", email, "default_tenant", tenant_id)

        # Record consents
        _record_registration_consents(
            user=email,
            accept_terms=accept_terms,
            accept_kvkk=accept_kvkk,
            marketing_consent=marketing_consent,
            tenant_id=tenant_id,
        )

        # Send verification email
        verification_key = _create_email_verification(email)

        # Log registration event
        _log_identity_event(
            "registration",
            email,
            {"account_type": account_type, "tenant_id": tenant_id},
        )

        return {
            "success": True,
            "message": _(
                "Account created successfully. Please check your email to verify your account."
            ),
            "user": email,
            "requires_verification": True,
            "verification_sent": True,
        }

    except frappe.DuplicateEntryError:
        frappe.throw(_("An account with this email already exists"))
    except Exception as e:
        frappe.log_error(f"Registration error: {str(e)}", "Identity API Error")
        frappe.throw(_("An error occurred during registration. Please try again."))


@frappe.whitelist(allow_guest=True)
def register_organization(
    email: str,
    password: str,
    first_name: str,
    last_name: str,
    organization_name: str,
    tax_id: str,
    phone: Optional[str] = None,
    organization_type: str = "Company",
    accept_terms: bool = False,
    accept_kvkk: bool = False,
    marketing_consent: bool = False,
    tenant_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Register a new organization account on TR-TradeHub marketplace.

    This endpoint creates both a user account (as organization admin)
    and an Organization record for B2B/B4B functionality.

    Args:
        email: Admin user's email address
        password: Admin user's password
        first_name: Admin's first name
        last_name: Admin's last name
        organization_name: Company/organization name
        tax_id: Tax ID (VKN for Turkish companies)
        phone: Optional phone number
        organization_type: "Company", "Sole Proprietor", "Partnership", etc.
        accept_terms: Must be True to register
        accept_kvkk: KVKK consent (required)
        marketing_consent: Optional marketing consent
        tenant_id: Optional tenant for multi-tenant registration

    Returns:
        dict: Registration result with user and organization info

    Example:
        POST /api/method/tr_tradehub.api.v1.identity.register_organization
        {
            "email": "admin@company.com",
            "password": "SecurePass123",
            "first_name": "John",
            "last_name": "Doe",
            "organization_name": "Acme Corp",
            "tax_id": "1234567890",
            "accept_terms": true,
            "accept_kvkk": true
        }
    """
    # Rate limiting
    check_rate_limit("register")

    # Validate required fields
    required_fields = {
        "email": email,
        "password": password,
        "first_name": first_name,
        "last_name": last_name,
        "organization_name": organization_name,
        "tax_id": tax_id,
    }

    for field, value in required_fields.items():
        if not value:
            frappe.throw(_("{0} is required").format(field.replace("_", " ").title()))

    email = email.strip().lower()
    organization_name = organization_name.strip()
    tax_id = tax_id.strip()

    # Validate email format
    if not validate_email_format(email):
        frappe.throw(_("Please enter a valid email address"))

    # Check if email already exists
    if frappe.db.exists("User", email):
        frappe.throw(_("An account with this email already exists"))

    # Validate password
    password_check = validate_password_strength(password)
    if not password_check["is_valid"]:
        frappe.throw("\n".join(password_check["errors"]))

    # Validate Turkish VKN format (10 digits)
    if len(tax_id) == 10 and tax_id.isdigit():
        # Turkish VKN validation would go here
        pass
    elif len(tax_id) == 11 and tax_id.isdigit():
        # Could be TCKN for sole proprietors
        if not validate_tckn(tax_id):
            frappe.throw(_("Invalid tax ID format"))
    else:
        frappe.throw(_("Tax ID must be 10 digits (VKN) or 11 digits (TCKN)"))

    # Check if organization with this tax ID already exists
    if frappe.db.exists("Organization", {"tax_id": tax_id}):
        frappe.throw(
            _("An organization with this tax ID is already registered. "
              "Please contact support if you need to be added as a member.")
        )

    # Validate terms
    if not accept_terms:
        frappe.throw(_("You must accept the terms and conditions"))
    if not accept_kvkk:
        frappe.throw(_("KVKK consent is required"))

    # Create user first
    try:
        user = frappe.get_doc(
            {
                "doctype": "User",
                "email": email,
                "first_name": first_name,
                "last_name": last_name,
                "full_name": f"{first_name} {last_name}",
                "enabled": 1,
                "new_password": password,
                "user_type": "Website User",
                "send_welcome_email": 0,
                "mobile_no": normalize_phone(phone) if phone else None,
            }
        )
        user.flags.ignore_permissions = True
        user.flags.no_welcome_mail = True
        user.insert()

        # Assign roles
        user.add_roles("Marketplace Buyer", "Organization Admin")

        # Create organization
        org = frappe.get_doc(
            {
                "doctype": "Organization",
                "organization_name": organization_name,
                "organization_type": organization_type,
                "tax_id": tax_id,
                "admin_user": email,
                "primary_contact_email": email,
                "primary_contact_phone": normalize_phone(phone) if phone else None,
                "status": "Pending Verification",
                "tenant": tenant_id,
            }
        )
        org.flags.ignore_permissions = True
        org.insert()

        # Add user as organization member (admin)
        if frappe.db.exists("DocType", "Organization Member"):
            member = frappe.get_doc(
                {
                    "doctype": "Organization Member",
                    "parent": org.name,
                    "parenttype": "Organization",
                    "parentfield": "members",
                    "user": email,
                    "role": "Admin",
                    "is_primary_contact": 1,
                    "can_manage_members": 1,
                    "can_manage_orders": 1,
                    "can_manage_payments": 1,
                }
            )
            member.flags.ignore_permissions = True
            member.insert()

        # Set default tenant
        if tenant_id:
            frappe.db.set_value("User", email, "default_tenant", tenant_id)

        # Record consents
        _record_registration_consents(
            user=email,
            accept_terms=accept_terms,
            accept_kvkk=accept_kvkk,
            marketing_consent=marketing_consent,
            tenant_id=tenant_id,
        )

        # Send verification email
        verification_key = _create_email_verification(email)

        # Log event
        _log_identity_event(
            "organization_registration",
            email,
            {"organization": org.name, "tax_id": tax_id},
        )

        return {
            "success": True,
            "message": _(
                "Organization account created. Please verify your email to continue."
            ),
            "user": email,
            "organization": org.name,
            "organization_status": org.status,
            "requires_verification": True,
        }

    except Exception as e:
        # Cleanup on failure
        if frappe.db.exists("User", email):
            frappe.delete_doc("User", email, force=True)
        frappe.log_error(f"Organization registration error: {str(e)}", "Identity API Error")
        frappe.throw(_("An error occurred during registration. Please try again."))


# =============================================================================
# LOGIN ENDPOINTS
# =============================================================================


@frappe.whitelist(allow_guest=True)
def login(
    usr: str,
    pwd: str,
    device_id: Optional[str] = None,
    remember_me: bool = False,
) -> Dict[str, Any]:
    """
    Enhanced login endpoint with 2FA and KVKK consent checking.

    Args:
        usr: Email or username
        pwd: Password
        device_id: Optional device identifier for trusted devices
        remember_me: If True, extends session duration

    Returns:
        dict: Login result with session info or 2FA requirement

    Example:
        POST /api/method/tr_tradehub.api.v1.identity.login
        {
            "usr": "user@example.com",
            "pwd": "password123"
        }
    """
    # Rate limiting
    check_rate_limit("login", usr)

    if not usr or not pwd:
        frappe.throw(_("Email and password are required"))

    usr = usr.strip().lower()

    # Check if user exists
    if not frappe.db.exists("User", usr):
        # Don't reveal that user doesn't exist
        frappe.throw(_("Invalid email or password"))

    # Check if user is enabled
    user_doc = frappe.get_doc("User", usr)
    if not user_doc.enabled:
        frappe.throw(
            _("Your account has been disabled. Please contact support.")
        )

    # Verify password
    try:
        check_password(usr, pwd)
    except frappe.AuthenticationError:
        _log_identity_event("failed_login", usr, {"reason": "invalid_password"})
        frappe.throw(_("Invalid email or password"))

    # Check for account actions/restrictions
    has_restriction = _check_account_restrictions(usr)
    if has_restriction:
        frappe.throw(
            _("Your account has restrictions. Please contact support."),
            title=_("Account Restricted"),
        )

    # Check if 2FA is enabled
    if _is_2fa_enabled(usr):
        # Generate and send 2FA code
        otp_secret = _generate_2fa_code(usr)

        return {
            "success": True,
            "requires_2fa": True,
            "message": _("Please enter the verification code sent to your device"),
            "otp_id": otp_secret,
            "user": usr,
        }

    # Check KVKK consent status
    kvkk_status = _check_kvkk_consent(usr)
    if not kvkk_status["has_valid_consent"]:
        return {
            "success": True,
            "requires_consent_renewal": True,
            "message": _("Please review and accept the updated privacy policy"),
            "consent_types": kvkk_status.get("required_consents", []),
            "user": usr,
        }

    # Perform login
    login_result = _perform_login(usr, remember_me, device_id)

    # Log successful login
    _log_identity_event("login", usr, {"device_id": device_id})

    return {
        "success": True,
        "message": _("Login successful"),
        "user": usr,
        "full_name": user_doc.full_name,
        "session_id": login_result.get("session_id"),
        "tenant_id": frappe.db.get_value("User", usr, "default_tenant"),
    }


@frappe.whitelist(allow_guest=True)
def verify_2fa(
    usr: str,
    otp_code: str,
    otp_id: Optional[str] = None,
    device_id: Optional[str] = None,
    trust_device: bool = False,
) -> Dict[str, Any]:
    """
    Verify 2FA code and complete login.

    Args:
        usr: User email
        otp_code: OTP code entered by user
        otp_id: OTP identifier from login response
        device_id: Device identifier
        trust_device: If True, add device to trusted list

    Returns:
        dict: Login result after 2FA verification
    """
    # Rate limiting
    check_rate_limit("2fa_verify", usr)

    if not usr or not otp_code:
        frappe.throw(_("User and OTP code are required"))

    usr = usr.strip().lower()

    # Verify OTP
    if not _verify_2fa_code(usr, otp_code, otp_id):
        _log_identity_event("failed_2fa", usr, {"otp_id": otp_id})
        frappe.throw(_("Invalid or expired verification code"))

    # Trust device if requested
    if trust_device and device_id:
        _trust_device(usr, device_id)

    # Check KVKK consent
    kvkk_status = _check_kvkk_consent(usr)
    if not kvkk_status["has_valid_consent"]:
        return {
            "success": True,
            "requires_consent_renewal": True,
            "message": _("Please review and accept the updated privacy policy"),
            "user": usr,
        }

    # Complete login
    login_result = _perform_login(usr, remember_me=False, device_id=device_id)

    _log_identity_event("2fa_verified", usr, {"device_id": device_id, "trusted": trust_device})

    user_doc = frappe.get_doc("User", usr)

    return {
        "success": True,
        "message": _("Login successful"),
        "user": usr,
        "full_name": user_doc.full_name,
        "session_id": login_result.get("session_id"),
    }


@frappe.whitelist()
def logout() -> Dict[str, Any]:
    """
    Logout current user and invalidate session.

    Returns:
        dict: Logout result
    """
    user = frappe.session.user

    if user == "Guest":
        return {"success": True, "message": _("Already logged out")}

    # Log logout event
    _log_identity_event("logout", user, {})

    # Clear session
    frappe.local.login_manager.logout()

    return {
        "success": True,
        "message": _("Logged out successfully"),
    }


@frappe.whitelist()
def logout_all_sessions() -> Dict[str, Any]:
    """
    Logout from all active sessions.

    Returns:
        dict: Result with count of sessions terminated
    """
    user = frappe.session.user

    if user == "Guest":
        frappe.throw(_("Not logged in"))

    # Get all sessions for user
    sessions = frappe.db.get_all(
        "Sessions",
        filters={"user": user},
        pluck="sid",
    )

    # Delete all sessions
    for sid in sessions:
        frappe.cache().hdel("session", sid)
        frappe.db.delete("Sessions", {"sid": sid})

    frappe.db.commit()

    _log_identity_event("logout_all", user, {"sessions_terminated": len(sessions)})

    return {
        "success": True,
        "message": _("Logged out from all sessions"),
        "sessions_terminated": len(sessions),
    }


# =============================================================================
# PASSWORD MANAGEMENT
# =============================================================================


@frappe.whitelist(allow_guest=True)
def forgot_password(email: str) -> Dict[str, Any]:
    """
    Initiate password reset process.

    Args:
        email: User's email address

    Returns:
        dict: Result (always success to prevent email enumeration)
    """
    # Rate limiting
    check_rate_limit("password_reset", email)

    email = email.strip().lower()

    # Always return success to prevent email enumeration
    if not frappe.db.exists("User", email):
        return {
            "success": True,
            "message": _("If an account exists, a password reset email has been sent."),
        }

    user = frappe.get_doc("User", email)
    if not user.enabled:
        return {
            "success": True,
            "message": _("If an account exists, a password reset email has been sent."),
        }

    # Generate reset key
    reset_key = frappe.generate_hash(length=32)
    reset_key_expiry = add_days(nowdate(), 1)

    # Store reset key
    frappe.db.set_value(
        "User",
        email,
        {
            "reset_password_key": reset_key,
            "last_reset_password_key_generated_on": now_datetime(),
        },
    )

    # Send reset email
    reset_url = get_url(f"/update-password?key={reset_key}")
    try:
        frappe.sendmail(
            recipients=email,
            subject=_("Password Reset Request - TR-TradeHub"),
            template="password_reset",
            args={
                "first_name": user.first_name,
                "reset_link": reset_url,
                "valid_hours": 24,
            },
            now=True,
        )
    except Exception as e:
        frappe.log_error(f"Password reset email error: {str(e)}", "Identity API Error")

    _log_identity_event("password_reset_requested", email, {})

    return {
        "success": True,
        "message": _("If an account exists, a password reset email has been sent."),
    }


@frappe.whitelist(allow_guest=True)
def reset_password(key: str, new_password: str) -> Dict[str, Any]:
    """
    Reset password using reset key from email.

    Args:
        key: Password reset key from email
        new_password: New password

    Returns:
        dict: Result of password reset
    """
    if not key or not new_password:
        frappe.throw(_("Reset key and new password are required"))

    # Find user with this reset key
    user = frappe.db.get_value(
        "User",
        {"reset_password_key": key},
        ["name", "last_reset_password_key_generated_on"],
        as_dict=True,
    )

    if not user:
        frappe.throw(_("Invalid or expired password reset link"))

    # Check if key has expired (24 hours)
    if user.last_reset_password_key_generated_on:
        key_age = get_datetime() - get_datetime(user.last_reset_password_key_generated_on)
        if key_age.total_seconds() > 86400:  # 24 hours
            frappe.throw(_("Password reset link has expired. Please request a new one."))

    # Validate new password
    password_check = validate_password_strength(new_password)
    if not password_check["is_valid"]:
        frappe.throw("\n".join(password_check["errors"]))

    # Update password
    _update_password(user.name, new_password)

    # Clear reset key
    frappe.db.set_value(
        "User",
        user.name,
        {
            "reset_password_key": None,
            "last_reset_password_key_generated_on": None,
        },
    )

    _log_identity_event("password_reset_completed", user.name, {})

    return {
        "success": True,
        "message": _("Password has been reset successfully. You can now login."),
    }


@frappe.whitelist()
def change_password(
    current_password: str,
    new_password: str,
) -> Dict[str, Any]:
    """
    Change password for logged-in user.

    Args:
        current_password: Current password
        new_password: New password

    Returns:
        dict: Result of password change
    """
    user = frappe.session.user

    if user == "Guest":
        frappe.throw(_("Not logged in"))

    if not current_password or not new_password:
        frappe.throw(_("Current password and new password are required"))

    # Verify current password
    try:
        check_password(user, current_password)
    except frappe.AuthenticationError:
        frappe.throw(_("Current password is incorrect"))

    # Validate new password
    password_check = validate_password_strength(new_password)
    if not password_check["is_valid"]:
        frappe.throw("\n".join(password_check["errors"]))

    # Check that new password is different
    try:
        check_password(user, new_password)
        frappe.throw(_("New password must be different from current password"))
    except frappe.AuthenticationError:
        pass  # Good - passwords are different

    # Update password
    _update_password(user, new_password)

    _log_identity_event("password_changed", user, {})

    return {
        "success": True,
        "message": _("Password changed successfully"),
    }


# =============================================================================
# EMAIL/PHONE VERIFICATION
# =============================================================================


@frappe.whitelist(allow_guest=True)
def verify_email(key: str) -> Dict[str, Any]:
    """
    Verify email address using verification key.

    Args:
        key: Verification key from email

    Returns:
        dict: Verification result
    """
    if not key:
        frappe.throw(_("Verification key is required"))

    # Find user with this verification key
    cache_key = f"email_verification:{key}"
    user_email = frappe.cache().get_value(cache_key)

    if not user_email:
        frappe.throw(_("Invalid or expired verification link"))

    # Mark email as verified
    frappe.db.set_value("User", user_email, "email_verified", 1)

    # Clear verification key
    frappe.cache().delete_value(cache_key)

    _log_identity_event("email_verified", user_email, {})

    return {
        "success": True,
        "message": _("Email verified successfully. You can now login."),
        "user": user_email,
    }


@frappe.whitelist()
def resend_verification_email() -> Dict[str, Any]:
    """
    Resend email verification link.

    Returns:
        dict: Result
    """
    # Rate limiting
    check_rate_limit("verification", frappe.session.user)

    user = frappe.session.user

    if user == "Guest":
        frappe.throw(_("Not logged in"))

    # Check if already verified
    if frappe.db.get_value("User", user, "email_verified"):
        return {
            "success": True,
            "message": _("Email is already verified"),
        }

    # Create new verification
    _create_email_verification(user)

    return {
        "success": True,
        "message": _("Verification email sent"),
    }


@frappe.whitelist()
def send_phone_verification(phone: Optional[str] = None) -> Dict[str, Any]:
    """
    Send phone verification code via SMS.

    Args:
        phone: Phone number (uses profile phone if not provided)

    Returns:
        dict: Result with verification ID
    """
    # Rate limiting
    check_rate_limit("verification", frappe.session.user)

    user = frappe.session.user

    if user == "Guest":
        frappe.throw(_("Not logged in"))

    if phone:
        phone = normalize_phone(phone)
        if not validate_phone_format(phone):
            frappe.throw(_("Invalid phone number format"))
    else:
        phone = frappe.db.get_value("User", user, "mobile_no")
        if not phone:
            frappe.throw(_("No phone number on file"))

    # Generate verification code
    code = "".join([str(secrets.randbelow(10)) for _ in range(VERIFICATION_CODE_LENGTH)])
    verification_id = frappe.generate_hash(length=16)

    # Store code
    cache_key = f"phone_verification:{verification_id}"
    frappe.cache().set_value(
        cache_key,
        {"user": user, "phone": phone, "code": code},
        expires_in_sec=VERIFICATION_CODE_EXPIRY_MINUTES * 60,
    )

    # Send SMS (placeholder - integrate with actual SMS provider)
    # _send_sms(phone, f"Your TR-TradeHub verification code is: {code}")

    _log_identity_event("phone_verification_sent", user, {"phone": phone[-4:]})

    return {
        "success": True,
        "message": _("Verification code sent to {0}").format(phone[-4:].rjust(len(phone), "*")),
        "verification_id": verification_id,
        "expires_in_minutes": VERIFICATION_CODE_EXPIRY_MINUTES,
    }


@frappe.whitelist()
def verify_phone(verification_id: str, code: str) -> Dict[str, Any]:
    """
    Verify phone number with code.

    Args:
        verification_id: Verification ID from send_phone_verification
        code: Verification code

    Returns:
        dict: Verification result
    """
    # Rate limiting
    check_rate_limit("verification", frappe.session.user)

    user = frappe.session.user

    if user == "Guest":
        frappe.throw(_("Not logged in"))

    if not verification_id or not code:
        frappe.throw(_("Verification ID and code are required"))

    cache_key = f"phone_verification:{verification_id}"
    verification_data = frappe.cache().get_value(cache_key)

    if not verification_data:
        frappe.throw(_("Invalid or expired verification code"))

    if verification_data["user"] != user:
        frappe.throw(_("Verification code does not match"))

    if verification_data["code"] != code:
        frappe.throw(_("Invalid verification code"))

    # Mark phone as verified
    phone = verification_data["phone"]
    frappe.db.set_value(
        "User",
        user,
        {
            "mobile_no": phone,
            "phone_verified": 1,
        },
    )

    # Clear verification
    frappe.cache().delete_value(cache_key)

    _log_identity_event("phone_verified", user, {"phone": phone[-4:]})

    return {
        "success": True,
        "message": _("Phone number verified successfully"),
    }


# =============================================================================
# PROFILE MANAGEMENT
# =============================================================================


@frappe.whitelist()
def get_profile() -> Dict[str, Any]:
    """
    Get current user's profile information.

    Returns:
        dict: User profile data
    """
    user = frappe.session.user

    if user == "Guest":
        frappe.throw(_("Not logged in"))

    user_doc = frappe.get_doc("User", user)

    # Get associated organization if any
    organization = None
    org_name = frappe.db.get_value(
        "Organization Member",
        {"user": user},
        "parent",
    )
    if org_name:
        organization = frappe.db.get_value(
            "Organization",
            org_name,
            ["name", "organization_name", "status"],
            as_dict=True,
        )

    # Get KYC status
    kyc_status = None
    if frappe.db.exists("DocType", "KYC Profile"):
        kyc = frappe.db.get_value(
            "KYC Profile",
            {"user": user, "status": ("not in", ["Rejected", "Expired"])},
            ["name", "status", "verification_status", "risk_level"],
            as_dict=True,
        )
        if kyc:
            kyc_status = kyc

    # Get tenant info
    tenant_id = frappe.db.get_value("User", user, "default_tenant")
    tenant_info = None
    if tenant_id:
        tenant_info = frappe.db.get_value(
            "Tenant",
            tenant_id,
            ["name", "tenant_name", "company_name"],
            as_dict=True,
        )

    return {
        "success": True,
        "profile": {
            "email": user_doc.email,
            "first_name": user_doc.first_name,
            "last_name": user_doc.last_name,
            "full_name": user_doc.full_name,
            "phone": user_doc.mobile_no,
            "email_verified": cint(user_doc.get("email_verified", 0)),
            "phone_verified": cint(user_doc.get("phone_verified", 0)),
            "user_image": user_doc.user_image,
            "language": user_doc.language,
            "time_zone": user_doc.time_zone,
            "roles": [r.role for r in user_doc.roles],
        },
        "organization": organization,
        "kyc_status": kyc_status,
        "tenant": tenant_info,
        "security": {
            "2fa_enabled": _is_2fa_enabled(user),
            "last_login": user_doc.last_login,
            "last_password_reset": user_doc.get("last_reset_password_key_generated_on"),
        },
    }


@frappe.whitelist()
def update_profile(
    first_name: Optional[str] = None,
    last_name: Optional[str] = None,
    phone: Optional[str] = None,
    language: Optional[str] = None,
    time_zone: Optional[str] = None,
    user_image: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Update current user's profile information.

    Args:
        first_name: New first name
        last_name: New last name
        phone: New phone number
        language: Preferred language
        time_zone: Preferred timezone
        user_image: Profile image URL

    Returns:
        dict: Updated profile data
    """
    user = frappe.session.user

    if user == "Guest":
        frappe.throw(_("Not logged in"))

    user_doc = frappe.get_doc("User", user)

    # Update fields if provided
    if first_name:
        user_doc.first_name = first_name.strip()
    if last_name:
        user_doc.last_name = last_name.strip()
    if first_name or last_name:
        user_doc.full_name = f"{user_doc.first_name} {user_doc.last_name}"

    if phone:
        phone = normalize_phone(phone)
        if not validate_phone_format(phone):
            frappe.throw(_("Invalid phone number format"))
        if phone != user_doc.mobile_no:
            user_doc.mobile_no = phone
            # Reset phone verification
            user_doc.phone_verified = 0

    if language:
        user_doc.language = language
    if time_zone:
        user_doc.time_zone = time_zone
    if user_image:
        user_doc.user_image = user_image

    user_doc.save(ignore_permissions=True)

    _log_identity_event("profile_updated", user, {})

    return {
        "success": True,
        "message": _("Profile updated successfully"),
        "profile": {
            "first_name": user_doc.first_name,
            "last_name": user_doc.last_name,
            "full_name": user_doc.full_name,
            "phone": user_doc.mobile_no,
            "phone_verified": cint(user_doc.get("phone_verified", 0)),
            "language": user_doc.language,
            "time_zone": user_doc.time_zone,
            "user_image": user_doc.user_image,
        },
    }


# =============================================================================
# 2FA MANAGEMENT
# =============================================================================


@frappe.whitelist()
def enable_2fa(method: str = "totp") -> Dict[str, Any]:
    """
    Enable two-factor authentication.

    Args:
        method: 2FA method - "totp" (authenticator app) or "sms"

    Returns:
        dict: Setup information (e.g., QR code for TOTP)
    """
    user = frappe.session.user

    if user == "Guest":
        frappe.throw(_("Not logged in"))

    if method not in ["totp", "sms"]:
        frappe.throw(_("Invalid 2FA method. Use 'totp' or 'sms'"))

    if method == "sms":
        # Check phone is verified
        phone_verified = frappe.db.get_value("User", user, "phone_verified")
        if not phone_verified:
            frappe.throw(_("Please verify your phone number before enabling SMS 2FA"))

    # Generate TOTP secret
    import pyotp

    secret = pyotp.random_base32()
    totp = pyotp.TOTP(secret)

    # Store temporarily until confirmed
    cache_key = f"2fa_setup:{user}"
    frappe.cache().set_value(
        cache_key,
        {"secret": secret, "method": method},
        expires_in_sec=600,  # 10 minutes to complete setup
    )

    if method == "totp":
        # Generate provisioning URI for QR code
        provisioning_uri = totp.provisioning_uri(
            name=user,
            issuer_name="TR-TradeHub",
        )
        return {
            "success": True,
            "method": "totp",
            "secret": secret,
            "provisioning_uri": provisioning_uri,
            "message": _("Scan the QR code with your authenticator app, then verify with a code"),
        }
    else:
        # SMS method - will send code during verification
        return {
            "success": True,
            "method": "sms",
            "message": _("SMS 2FA will be enabled. Complete setup by verifying a code."),
        }


@frappe.whitelist()
def confirm_2fa_setup(code: str) -> Dict[str, Any]:
    """
    Confirm 2FA setup with verification code.

    Args:
        code: Verification code from authenticator app or SMS

    Returns:
        dict: Setup confirmation and backup codes
    """
    user = frappe.session.user

    if user == "Guest":
        frappe.throw(_("Not logged in"))

    cache_key = f"2fa_setup:{user}"
    setup_data = frappe.cache().get_value(cache_key)

    if not setup_data:
        frappe.throw(_("2FA setup has expired. Please start again."))

    secret = setup_data["secret"]
    method = setup_data["method"]

    # Verify code
    import pyotp

    totp = pyotp.TOTP(secret)
    if not totp.verify(code, valid_window=1):
        frappe.throw(_("Invalid verification code"))

    # Generate backup codes
    backup_codes = [secrets.token_hex(4).upper() for _ in range(8)]
    hashed_backup_codes = [
        hashlib.sha256(code.encode()).hexdigest() for code in backup_codes
    ]

    # Save 2FA settings
    frappe.db.set_value(
        "User",
        user,
        {
            "two_factor_method": method,
            "totp_secret": secret,
            "backup_codes": ",".join(hashed_backup_codes),
            "two_factor_enabled": 1,
        },
    )

    # Clear setup cache
    frappe.cache().delete_value(cache_key)

    _log_identity_event("2fa_enabled", user, {"method": method})

    return {
        "success": True,
        "message": _("Two-factor authentication enabled successfully"),
        "backup_codes": backup_codes,
        "warning": _(
            "Save these backup codes in a secure place. "
            "They will not be shown again."
        ),
    }


@frappe.whitelist()
def disable_2fa(password: str) -> Dict[str, Any]:
    """
    Disable two-factor authentication.

    Args:
        password: Current password for verification

    Returns:
        dict: Result
    """
    user = frappe.session.user

    if user == "Guest":
        frappe.throw(_("Not logged in"))

    # Verify password
    try:
        check_password(user, password)
    except frappe.AuthenticationError:
        frappe.throw(_("Invalid password"))

    # Disable 2FA
    frappe.db.set_value(
        "User",
        user,
        {
            "two_factor_enabled": 0,
            "two_factor_method": None,
            "totp_secret": None,
            "backup_codes": None,
        },
    )

    _log_identity_event("2fa_disabled", user, {})

    return {
        "success": True,
        "message": _("Two-factor authentication disabled"),
    }


@frappe.whitelist()
def regenerate_backup_codes(password: str) -> Dict[str, Any]:
    """
    Regenerate 2FA backup codes.

    Args:
        password: Current password for verification

    Returns:
        dict: New backup codes
    """
    user = frappe.session.user

    if user == "Guest":
        frappe.throw(_("Not logged in"))

    if not _is_2fa_enabled(user):
        frappe.throw(_("2FA is not enabled"))

    # Verify password
    try:
        check_password(user, password)
    except frappe.AuthenticationError:
        frappe.throw(_("Invalid password"))

    # Generate new backup codes
    backup_codes = [secrets.token_hex(4).upper() for _ in range(8)]
    hashed_backup_codes = [
        hashlib.sha256(code.encode()).hexdigest() for code in backup_codes
    ]

    # Save new codes
    frappe.db.set_value("User", user, "backup_codes", ",".join(hashed_backup_codes))

    _log_identity_event("backup_codes_regenerated", user, {})

    return {
        "success": True,
        "backup_codes": backup_codes,
        "message": _("New backup codes generated"),
        "warning": _(
            "Save these backup codes in a secure place. "
            "They will not be shown again."
        ),
    }


# =============================================================================
# SESSION MANAGEMENT
# =============================================================================


@frappe.whitelist()
def get_active_sessions() -> Dict[str, Any]:
    """
    Get all active sessions for current user.

    Returns:
        dict: List of active sessions
    """
    user = frappe.session.user

    if user == "Guest":
        frappe.throw(_("Not logged in"))

    sessions = frappe.db.get_all(
        "Sessions",
        filters={"user": user},
        fields=["sid", "device", "status", "lastused"],
        order_by="lastused desc",
    )

    current_session = frappe.session.sid

    session_list = []
    for session in sessions:
        session_list.append(
            {
                "session_id": session.sid[:8] + "...",  # Partial ID for security
                "is_current": session.sid == current_session,
                "device": session.device or "Unknown",
                "last_active": session.lastused,
                "status": session.status,
            }
        )

    return {
        "success": True,
        "sessions": session_list,
        "total": len(session_list),
    }


@frappe.whitelist()
def terminate_session(session_id: str) -> Dict[str, Any]:
    """
    Terminate a specific session.

    Args:
        session_id: Partial session ID to terminate

    Returns:
        dict: Result
    """
    user = frappe.session.user

    if user == "Guest":
        frappe.throw(_("Not logged in"))

    # Find session matching partial ID
    sessions = frappe.db.get_all(
        "Sessions",
        filters={"user": user, "sid": ("like", f"{session_id}%")},
        pluck="sid",
    )

    if not sessions:
        frappe.throw(_("Session not found"))

    sid = sessions[0]

    # Don't allow terminating current session
    if sid == frappe.session.sid:
        frappe.throw(_("Cannot terminate current session. Use logout instead."))

    # Delete session
    frappe.cache().hdel("session", sid)
    frappe.db.delete("Sessions", {"sid": sid})
    frappe.db.commit()

    _log_identity_event("session_terminated", user, {"session": session_id})

    return {
        "success": True,
        "message": _("Session terminated"),
    }


# =============================================================================
# HELPER FUNCTIONS (PRIVATE)
# =============================================================================


def _record_registration_consents(
    user: str,
    accept_terms: bool,
    accept_kvkk: bool,
    marketing_consent: bool,
    tenant_id: Optional[str] = None,
) -> None:
    """Record consent records for new registration."""
    try:
        if not frappe.db.exists("DocType", "Consent Record"):
            return

        ip_address = None
        user_agent = None
        try:
            if frappe.request:
                ip_address = frappe.request.remote_addr
                user_agent = str(frappe.request.user_agent)[:500]
        except Exception:
            pass

        # Terms and Conditions consent
        if accept_terms:
            frappe.get_doc(
                {
                    "doctype": "Consent Record",
                    "user": user,
                    "consent_type": "Terms and Conditions",
                    "purpose": "Platform terms acceptance",
                    "legal_basis": "Contract",
                    "is_given": 1,
                    "given_at": now_datetime(),
                    "given_via": "Registration Form",
                    "given_ip_address": ip_address,
                    "given_user_agent": user_agent,
                    "tenant": tenant_id,
                }
            ).insert(ignore_permissions=True)

        # KVKK consent
        if accept_kvkk:
            frappe.get_doc(
                {
                    "doctype": "Consent Record",
                    "user": user,
                    "consent_type": "Data Processing",
                    "purpose": "KVKK personal data processing consent",
                    "legal_basis": "Consent",
                    "is_given": 1,
                    "given_at": now_datetime(),
                    "given_via": "Registration Form",
                    "given_ip_address": ip_address,
                    "given_user_agent": user_agent,
                    "tenant": tenant_id,
                }
            ).insert(ignore_permissions=True)

        # Marketing consent (optional)
        if marketing_consent:
            frappe.get_doc(
                {
                    "doctype": "Consent Record",
                    "user": user,
                    "consent_type": "Marketing Communications",
                    "purpose": "Marketing and promotional communications",
                    "legal_basis": "Consent",
                    "is_given": 1,
                    "given_at": now_datetime(),
                    "given_via": "Registration Form",
                    "given_ip_address": ip_address,
                    "given_user_agent": user_agent,
                    "tenant": tenant_id,
                }
            ).insert(ignore_permissions=True)

    except Exception as e:
        frappe.log_error(f"Error recording consents: {str(e)}", "Identity API Error")


def _create_email_verification(email: str) -> str:
    """Create email verification key and send email."""
    verification_key = frappe.generate_hash(length=32)

    # Store verification key
    cache_key = f"email_verification:{verification_key}"
    frappe.cache().set_value(
        cache_key,
        email,
        expires_in_sec=86400,  # 24 hours
    )

    # Send verification email
    verification_url = get_url(
        f"/api/method/tr_tradehub.api.v1.identity.verify_email?key={verification_key}"
    )

    try:
        user = frappe.get_doc("User", email)
        frappe.sendmail(
            recipients=email,
            subject=_("Verify Your Email - TR-TradeHub"),
            template="email_verification",
            args={
                "first_name": user.first_name,
                "verification_link": verification_url,
            },
            now=True,
        )
    except Exception as e:
        frappe.log_error(f"Verification email error: {str(e)}", "Identity API Error")

    return verification_key


def _is_2fa_enabled(user: str) -> bool:
    """Check if 2FA is enabled for user."""
    return cint(frappe.db.get_value("User", user, "two_factor_enabled")) == 1


def _generate_2fa_code(user: str) -> str:
    """Generate and send 2FA verification code."""
    method = frappe.db.get_value("User", user, "two_factor_method")

    if method == "totp":
        # For TOTP, user uses their authenticator app
        otp_id = frappe.generate_hash(length=16)
        return otp_id

    elif method == "sms":
        # Generate code for SMS
        code = "".join([str(secrets.randbelow(10)) for _ in range(6)])
        otp_id = frappe.generate_hash(length=16)

        # Store code
        cache_key = f"2fa_code:{otp_id}"
        frappe.cache().set_value(
            cache_key,
            {"user": user, "code": code},
            expires_in_sec=300,  # 5 minutes
        )

        # Send SMS
        phone = frappe.db.get_value("User", user, "mobile_no")
        # _send_sms(phone, f"Your TR-TradeHub verification code is: {code}")

        return otp_id

    return ""


def _verify_2fa_code(user: str, code: str, otp_id: Optional[str] = None) -> bool:
    """Verify 2FA code."""
    method = frappe.db.get_value("User", user, "two_factor_method")

    if method == "totp":
        # Verify TOTP code
        import pyotp

        secret = frappe.db.get_value("User", user, "totp_secret")
        if not secret:
            return False

        totp = pyotp.TOTP(secret)
        if totp.verify(code, valid_window=1):
            return True

        # Check backup codes
        backup_codes = frappe.db.get_value("User", user, "backup_codes")
        if backup_codes:
            hashed_code = hashlib.sha256(code.upper().encode()).hexdigest()
            codes_list = backup_codes.split(",")
            if hashed_code in codes_list:
                # Remove used backup code
                codes_list.remove(hashed_code)
                frappe.db.set_value("User", user, "backup_codes", ",".join(codes_list))
                return True

        return False

    elif method == "sms":
        # Verify SMS code
        cache_key = f"2fa_code:{otp_id}"
        stored = frappe.cache().get_value(cache_key)

        if not stored:
            return False

        if stored["user"] == user and stored["code"] == code:
            frappe.cache().delete_value(cache_key)
            return True

        return False

    return False


def _check_account_restrictions(user: str) -> bool:
    """Check if user has any active account restrictions."""
    if not frappe.db.exists("DocType", "Account Action"):
        return False

    active_restrictions = frappe.db.count(
        "Account Action",
        filters={
            "target_user": user,
            "status": "Active",
            "action_type": ("in", ["Restriction", "Suspension", "Temporary Ban", "Permanent Ban"]),
        },
    )

    return active_restrictions > 0


def _check_kvkk_consent(user: str) -> Dict[str, Any]:
    """Check if user has valid KVKK consent."""
    if not frappe.db.exists("DocType", "Consent Record"):
        return {"has_valid_consent": True}

    consent = frappe.db.get_value(
        "Consent Record",
        {
            "user": user,
            "consent_type": "Data Processing",
            "status": "Active",
        },
        ["name", "consent_version"],
        as_dict=True,
    )

    if not consent:
        return {
            "has_valid_consent": False,
            "required_consents": ["Data Processing"],
        }

    # Check if consent version is current (placeholder logic)
    # In production, compare with current privacy policy version
    return {"has_valid_consent": True, "consent": consent}


def _perform_login(
    user: str,
    remember_me: bool = False,
    device_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Perform actual login and create session."""
    from frappe.auth import LoginManager

    login_manager = LoginManager()
    login_manager.authenticate(user=user, pwd=None)
    login_manager.post_login()

    # Update last login
    frappe.db.set_value("User", user, "last_login", now_datetime())

    return {
        "session_id": frappe.session.sid,
        "user": user,
    }


def _trust_device(user: str, device_id: str) -> None:
    """Add device to user's trusted devices list."""
    cache_key = f"trusted_devices:{user}"
    devices = frappe.cache().get_value(cache_key) or []
    if device_id not in devices:
        devices.append(device_id)
        # Keep only last 10 trusted devices
        devices = devices[-10:]
        frappe.cache().set_value(cache_key, devices)


def _log_identity_event(
    event_type: str,
    user: str,
    details: Dict[str, Any],
) -> None:
    """Log identity-related security event."""
    try:
        ip_address = None
        user_agent = None
        try:
            if frappe.request:
                ip_address = frappe.request.remote_addr
                user_agent = str(frappe.request.user_agent)[:200]
        except Exception:
            pass

        frappe.get_doc(
            {
                "doctype": "Activity Log",
                "user": user,
                "operation": event_type,
                "status": "Success",
                "content": frappe.as_json(details),
                "ip_address": ip_address,
            }
        ).insert(ignore_permissions=True)
    except Exception as e:
        # Don't let logging errors affect main flow
        frappe.log_error(f"Identity event logging error: {str(e)}", "Identity API")


# =============================================================================
# PUBLIC API SUMMARY
# =============================================================================

"""
Public API Endpoints:

Registration:
- register: Register individual user account
- register_organization: Register organization account

Authentication:
- login: Enhanced login with 2FA support
- verify_2fa: Complete 2FA verification
- logout: Logout current session
- logout_all_sessions: Logout from all sessions

Password Management:
- forgot_password: Initiate password reset
- reset_password: Reset password with key
- change_password: Change password (authenticated)

Verification:
- verify_email: Verify email address
- resend_verification_email: Resend verification
- send_phone_verification: Send phone verification SMS
- verify_phone: Verify phone number

Profile:
- get_profile: Get user profile
- update_profile: Update profile information

2FA Management:
- enable_2fa: Enable two-factor authentication
- confirm_2fa_setup: Confirm 2FA setup
- disable_2fa: Disable 2FA
- regenerate_backup_codes: Get new backup codes

Session Management:
- get_active_sessions: List active sessions
- terminate_session: End specific session
"""

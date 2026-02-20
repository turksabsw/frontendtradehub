# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

"""
Seller Onboarding API Endpoints for TR-TradeHub Marketplace

This module provides API endpoints for:
- Seller application submission and management
- Seller profile management
- Storefront creation and customization
- Commission plan assignment and queries
- Performance metrics and scoring
- Tier management and progression

API URL Pattern:
    POST /api/method/tr_tradehub.api.v1.seller.<function_name>

All endpoints follow Frappe conventions and patterns.
"""

import json
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
)


# =============================================================================
# CONSTANTS & CONFIGURATION
# =============================================================================

# Rate limiting settings (per user/IP)
RATE_LIMITS = {
    "application_submit": {"limit": 3, "window": 3600},  # 3 per hour
    "storefront_create": {"limit": 5, "window": 3600},  # 5 per hour
    "storefront_update": {"limit": 30, "window": 300},  # 30 per 5 min
    "metrics_update": {"limit": 10, "window": 300},  # 10 per 5 min
}


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
        action: The action to check
        identifier: User/IP identifier (defaults to session user)
        throw: If True, raises exception when rate limited

    Returns:
        bool: True if allowed, False if rate limited

    Raises:
        frappe.TooManyRequestsError: If throw=True and rate limited
    """
    if action not in RATE_LIMITS:
        return True

    config = RATE_LIMITS[action]

    # Get identifier (use session user by default)
    if not identifier:
        identifier = frappe.session.user or "unknown"

    cache_key = f"rate_limit:seller:{action}:{identifier}"

    # Get current count
    current = frappe.cache().get_value(cache_key)
    if current is None:
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

    frappe.cache().set_value(cache_key, current + 1, expires_in_sec=config["window"])
    return True


# =============================================================================
# VALIDATION HELPERS
# =============================================================================


def validate_tax_id(tax_id: str, tax_id_type: str = "TCKN") -> Dict[str, Any]:
    """
    Validate Turkish tax ID (VKN or TCKN).

    Args:
        tax_id: Tax ID to validate
        tax_id_type: Type of tax ID (VKN or TCKN)

    Returns:
        dict: Validation result with is_valid and any errors
    """
    if not tax_id:
        return {"is_valid": False, "error": _("Tax ID is required")}

    tax_id = tax_id.strip()
    if not tax_id.isdigit():
        return {"is_valid": False, "error": _("Tax ID must contain only digits")}

    if tax_id_type == "VKN":
        if len(tax_id) != 10:
            return {"is_valid": False, "error": _("VKN must be exactly 10 digits")}
        is_valid = _validate_vkn_checksum(tax_id)
    else:
        if len(tax_id) != 11:
            return {"is_valid": False, "error": _("TCKN must be exactly 11 digits")}
        is_valid = _validate_tckn_checksum(tax_id)

    return {
        "is_valid": is_valid,
        "error": _("Checksum validation failed") if not is_valid else None,
    }


def _validate_vkn_checksum(vkn: str) -> bool:
    """Validate Turkish VKN checksum."""
    if len(vkn) != 10:
        return False
    try:
        digits = [int(d) for d in vkn]
        total = 0
        for i in range(9):
            tmp = (digits[i] + (9 - i)) % 10
            tmp = (tmp * (2 ** (9 - i))) % 9
            if tmp == 0 and digits[i] != 0:
                tmp = 9
            total += tmp
        check_digit = (10 - (total % 10)) % 10
        return check_digit == digits[9]
    except (ValueError, IndexError):
        return False


def _validate_tckn_checksum(tckn: str) -> bool:
    """Validate Turkish TCKN checksum."""
    if len(tckn) != 11:
        return False
    try:
        digits = [int(d) for d in tckn]
        if digits[0] == 0:
            return False
        odd_sum = digits[0] + digits[2] + digits[4] + digits[6] + digits[8]
        even_sum = digits[1] + digits[3] + digits[5] + digits[7]
        digit_10 = ((odd_sum * 7) - even_sum) % 10
        if digit_10 < 0:
            digit_10 += 10
        if digits[9] != digit_10:
            return False
        total = sum(digits[:10])
        digit_11 = total % 10
        return digits[10] == digit_11
    except (ValueError, IndexError):
        return False


def validate_iban(iban: str) -> Dict[str, Any]:
    """
    Validate Turkish IBAN.

    Args:
        iban: IBAN to validate

    Returns:
        dict: Validation result
    """
    if not iban:
        return {"is_valid": False, "error": _("IBAN is required")}

    iban = iban.strip().upper().replace(" ", "")

    if len(iban) != 26:
        return {"is_valid": False, "error": _("Turkish IBAN must be 26 characters")}

    if not iban.startswith("TR"):
        return {"is_valid": False, "error": _("Turkish IBAN must start with 'TR'")}

    if not iban[2:].isalnum():
        return {"is_valid": False, "error": _("IBAN contains invalid characters")}

    # MOD-97 checksum validation
    rearranged = iban[4:] + iban[:4]
    numeric = ""
    for char in rearranged:
        if char.isalpha():
            numeric += str(ord(char) - ord("A") + 10)
        else:
            numeric += char

    is_valid = int(numeric) % 97 == 1

    return {
        "is_valid": is_valid,
        "iban_formatted": f"{iban[:4]} {iban[4:8]} {iban[8:12]} {iban[12:16]} {iban[16:20]} {iban[20:24]} {iban[24:]}",
        "error": _("Invalid IBAN checksum") if not is_valid else None,
    }


def get_current_seller() -> Optional[str]:
    """
    Get the seller profile for the current user.

    Returns:
        str or None: Seller profile name or None if not a seller
    """
    user = frappe.session.user
    if user == "Guest":
        return None

    return frappe.db.get_value("Seller Profile", {"user": user}, "name")


def require_seller(func):
    """Decorator to require seller profile for API endpoints."""
    def wrapper(*args, **kwargs):
        seller = get_current_seller()
        if not seller:
            frappe.throw(_("You must be a seller to access this resource"))
        kwargs["_seller"] = seller
        return func(*args, **kwargs)
    return wrapper


# =============================================================================
# SELLER APPLICATION ENDPOINTS
# =============================================================================


@frappe.whitelist()
def create_application(
    business_name: str,
    seller_type: str,
    tax_id: str,
    tax_id_type: str = "TCKN",
    contact_email: Optional[str] = None,
    contact_phone: Optional[str] = None,
    address_line_1: Optional[str] = None,
    city: Optional[str] = None,
    country: str = "Turkey",
    iban: Optional[str] = None,
    accept_terms: bool = False,
    accept_kvkk: bool = False,
    **kwargs,
) -> Dict[str, Any]:
    """
    Create a new seller application.

    This is the first step in seller onboarding. The application will be
    reviewed by administrators before the seller profile is created.

    Args:
        business_name: Name of the business or individual seller
        seller_type: Type of seller (Individual, Business, Enterprise)
        tax_id: Tax identification number (VKN or TCKN)
        tax_id_type: Type of tax ID (VKN or TCKN)
        contact_email: Contact email address
        contact_phone: Contact phone number
        address_line_1: Primary address line
        city: City
        country: Country (defaults to Turkey)
        iban: Bank IBAN for payouts
        accept_terms: Must accept terms and conditions
        accept_kvkk: Must accept KVKK consent

    Returns:
        dict: Application creation result with application ID

    Example:
        POST /api/method/tr_tradehub.api.v1.seller.create_application
        {
            "business_name": "My Shop",
            "seller_type": "Individual",
            "tax_id": "12345678901",
            "tax_id_type": "TCKN",
            "accept_terms": true,
            "accept_kvkk": true
        }
    """
    # Rate limiting
    check_rate_limit("application_submit")

    user = frappe.session.user
    if user == "Guest":
        frappe.throw(_("You must be logged in to apply as a seller"))

    # Validate required fields
    if not business_name:
        frappe.throw(_("Business name is required"))

    if not seller_type:
        frappe.throw(_("Seller type is required"))

    if seller_type not in ["Individual", "Business", "Enterprise"]:
        frappe.throw(_("Invalid seller type"))

    # Validate tax ID
    tax_validation = validate_tax_id(tax_id, tax_id_type)
    if not tax_validation["is_valid"]:
        frappe.throw(tax_validation["error"])

    # Validate IBAN if provided
    if iban:
        iban_validation = validate_iban(iban)
        if not iban_validation["is_valid"]:
            frappe.throw(iban_validation["error"])
        iban = iban_validation["iban_formatted"].replace(" ", "")

    # Validate agreements
    if not accept_terms:
        frappe.throw(_("You must accept the terms and conditions"))

    if not accept_kvkk:
        frappe.throw(_("You must accept the KVKK consent"))

    # Check if user already has a seller profile
    if frappe.db.exists("Seller Profile", {"user": user}):
        frappe.throw(_("You already have a seller profile"))

    # Check if user already has an active application
    existing_app = frappe.db.exists(
        "Seller Application",
        {
            "applicant_user": user,
            "status": ["in", ["Draft", "Submitted", "Under Review", "Documents Requested", "Revision Required"]],
        },
    )
    if existing_app:
        frappe.throw(
            _("You already have an active application ({0})").format(existing_app)
        )

    # Create application
    try:
        application_data = {
            "doctype": "Seller Application",
            "applicant_user": user,
            "business_name": business_name.strip(),
            "seller_type": seller_type,
            "tax_id": tax_id,
            "tax_id_type": tax_id_type,
            "contact_email": contact_email or frappe.db.get_value("User", user, "email"),
            "contact_phone": contact_phone,
            "address_line_1": address_line_1,
            "city": city,
            "country": country,
            "iban": iban,
            "terms_accepted": 1,
            "kvkk_accepted": 1,
        }

        # Add optional fields from kwargs
        optional_fields = [
            "address_line_2", "state", "postal_code", "mobile", "whatsapp",
            "website", "tax_office", "trade_registry_number", "mersis_number",
            "e_invoice_registered", "e_invoice_alias", "bank_name", "bank_branch",
            "account_holder_name", "swift_code", "identity_document_number",
            "identity_document_type", "identity_document_expiry",
            "business_description", "main_categories", "estimated_monthly_sales",
            "priority"
        ]
        for field in optional_fields:
            if field in kwargs and kwargs[field] is not None:
                application_data[field] = kwargs[field]

        application = frappe.get_doc(application_data)
        application.flags.ignore_permissions = True
        application.insert()

        _log_seller_event("application_created", user, {"application": application.name})

        return {
            "success": True,
            "message": _("Seller application created successfully"),
            "application": application.name,
            "status": application.status,
            "next_step": _("Submit your application for review"),
        }

    except frappe.DuplicateEntryError:
        frappe.throw(_("An application with this information already exists"))
    except Exception as e:
        frappe.log_error(f"Seller application error: {str(e)}", "Seller API Error")
        frappe.throw(_("An error occurred while creating the application"))


@frappe.whitelist()
def submit_application(application_name: str) -> Dict[str, Any]:
    """
    Submit a seller application for review.

    Args:
        application_name: Name of the seller application

    Returns:
        dict: Submission result
    """
    check_rate_limit("application_submit")

    user = frappe.session.user
    if user == "Guest":
        frappe.throw(_("Not logged in"))

    application = frappe.get_doc("Seller Application", application_name)

    # Verify ownership
    if application.applicant_user != user and not frappe.has_permission("Seller Application", "write"):
        frappe.throw(_("Not permitted to submit this application"))

    # Submit the application
    application.submit_application()

    _log_seller_event("application_submitted", user, {"application": application_name})

    return {
        "success": True,
        "message": _("Application submitted for review"),
        "application": application_name,
        "status": application.status,
        "submitted_at": application.submitted_at,
    }


@frappe.whitelist()
def get_application_status(application_name: Optional[str] = None) -> Dict[str, Any]:
    """
    Get the status of a seller application.

    Args:
        application_name: Name of the application (optional, defaults to current user's application)

    Returns:
        dict: Application status details
    """
    user = frappe.session.user
    if user == "Guest":
        frappe.throw(_("Not logged in"))

    if not application_name:
        # Find user's application
        application_name = frappe.db.get_value(
            "Seller Application",
            {"applicant_user": user, "status": ["not in", ["Cancelled", "Rejected"]]},
            "name",
        )

    if not application_name:
        return {
            "has_application": False,
            "message": _("No active application found"),
        }

    application = frappe.get_doc("Seller Application", application_name)

    # Verify ownership or permission
    if application.applicant_user != user and not frappe.has_permission("Seller Application", "read"):
        frappe.throw(_("Not permitted to view this application"))

    return {
        "has_application": True,
        "application": application_name,
        "business_name": application.business_name,
        "seller_type": application.seller_type,
        "status": application.status,
        "workflow_state": application.workflow_state,
        "submitted_at": application.submitted_at,
        "assigned_to": application.assigned_to,
        "review_deadline": application.review_deadline,
        "revision_requested": cint(application.revision_requested),
        "revision_notes": application.revision_notes,
        "rejection_reason": application.rejection_reason,
        "seller_profile": application.seller_profile,
    }


@frappe.whitelist()
def update_application(application_name: str, **kwargs) -> Dict[str, Any]:
    """
    Update a seller application (only allowed in Draft or Revision Required status).

    Args:
        application_name: Name of the seller application
        **kwargs: Fields to update

    Returns:
        dict: Update result
    """
    user = frappe.session.user
    if user == "Guest":
        frappe.throw(_("Not logged in"))

    application = frappe.get_doc("Seller Application", application_name)

    # Verify ownership
    if application.applicant_user != user:
        frappe.throw(_("Not permitted to update this application"))

    # Can only update in certain statuses
    if application.status not in ["Draft", "Revision Required", "Documents Requested"]:
        frappe.throw(_("Application cannot be updated in '{0}' status").format(application.status))

    # Allowed fields to update
    allowed_fields = [
        "business_name", "seller_type", "tax_id", "tax_id_type", "contact_email",
        "contact_phone", "mobile", "whatsapp", "website", "address_line_1",
        "address_line_2", "city", "state", "country", "postal_code", "tax_office",
        "trade_registry_number", "mersis_number", "e_invoice_registered",
        "e_invoice_alias", "bank_name", "bank_branch", "iban", "account_holder_name",
        "swift_code", "identity_document_number", "identity_document_type",
        "identity_document_expiry", "business_description", "main_categories",
        "estimated_monthly_sales"
    ]

    # Validate tax_id if being updated
    if "tax_id" in kwargs:
        tax_id_type = kwargs.get("tax_id_type", application.tax_id_type)
        tax_validation = validate_tax_id(kwargs["tax_id"], tax_id_type)
        if not tax_validation["is_valid"]:
            frappe.throw(tax_validation["error"])

    # Validate IBAN if being updated
    if "iban" in kwargs:
        iban_validation = validate_iban(kwargs["iban"])
        if not iban_validation["is_valid"]:
            frappe.throw(iban_validation["error"])
        kwargs["iban"] = iban_validation["iban_formatted"].replace(" ", "")

    # Update allowed fields
    for field in allowed_fields:
        if field in kwargs:
            setattr(application, field, kwargs[field])

    application.save()

    return {
        "success": True,
        "message": _("Application updated successfully"),
        "application": application_name,
        "status": application.status,
    }


@frappe.whitelist()
def cancel_application(application_name: str, reason: Optional[str] = None) -> Dict[str, Any]:
    """
    Cancel a seller application.

    Args:
        application_name: Name of the seller application
        reason: Reason for cancellation (optional)

    Returns:
        dict: Cancellation result
    """
    user = frappe.session.user
    if user == "Guest":
        frappe.throw(_("Not logged in"))

    application = frappe.get_doc("Seller Application", application_name)

    # Verify ownership or permission
    if application.applicant_user != user and not frappe.has_permission("Seller Application", "write"):
        frappe.throw(_("Not permitted to cancel this application"))

    # Cancel the application
    application.cancel(reason)

    _log_seller_event("application_cancelled", user, {"application": application_name, "reason": reason})

    return {
        "success": True,
        "message": _("Application cancelled"),
        "application": application_name,
        "status": application.status,
    }


# =============================================================================
# SELLER PROFILE ENDPOINTS
# =============================================================================


@frappe.whitelist()
def get_seller_profile(seller_name: Optional[str] = None) -> Dict[str, Any]:
    """
    Get seller profile information.

    Args:
        seller_name: Name of the seller profile (optional, defaults to current user's profile)

    Returns:
        dict: Seller profile details
    """
    user = frappe.session.user

    if not seller_name:
        seller_name = get_current_seller()

    if not seller_name:
        return {"has_profile": False, "message": _("No seller profile found")}

    # Check permission for viewing
    seller = frappe.get_doc("Seller Profile", seller_name)
    is_owner = seller.user == user

    if not is_owner and not frappe.has_permission("Seller Profile", "read"):
        frappe.throw(_("Not permitted to view this seller profile"))

    # Build response based on ownership
    profile_data = {
        "has_profile": True,
        "name": seller.name,
        "seller_name": seller.seller_name,
        "display_name": seller.display_name,
        "seller_type": seller.seller_type,
        "status": seller.status,
        "verification_status": seller.verification_status,
        "seller_tier": seller.seller_tier,
        "seller_score": seller.seller_score,
        "average_rating": seller.average_rating,
        "total_reviews": seller.total_reviews,
        "total_sales_count": seller.total_sales_count,
        "is_active": seller.is_active(),
        "is_verified": seller.is_verified(),
        "can_accept_orders": seller.can_accept_orders(),
        "is_top_seller": cint(seller.is_top_seller),
        "is_premium_seller": cint(seller.is_premium_seller),
        "badges": json.loads(seller.badges or "[]"),
        "city": seller.city,
        "country": seller.country,
        "vacation_mode": cint(seller.vacation_mode),
    }

    # Add sensitive details only for owner or admin
    if is_owner or frappe.has_permission("Seller Profile", "write"):
        profile_data.update({
            "contact_email": seller.contact_email,
            "contact_phone": seller.contact_phone,
            "iban": seller.iban,
            "bank_name": seller.bank_name,
            "commission_plan": seller.commission_plan,
            "max_listings": seller.max_listings,
            "available_listing_slots": seller.get_available_listing_slots(),
            "can_sell": cint(seller.can_sell),
            "can_withdraw": cint(seller.can_withdraw),
            "can_create_listings": cint(seller.can_create_listings),
            "is_restricted": cint(seller.is_restricted),
            "restriction_reason": seller.restriction_reason,
            "erpnext_supplier": seller.erpnext_supplier,
        })

    return profile_data


@frappe.whitelist()
def update_seller_profile(
    seller_name: Optional[str] = None,
    **kwargs,
) -> Dict[str, Any]:
    """
    Update seller profile information.

    Args:
        seller_name: Name of the seller profile (optional, defaults to current user's profile)
        **kwargs: Fields to update

    Returns:
        dict: Update result
    """
    user = frappe.session.user
    if user == "Guest":
        frappe.throw(_("Not logged in"))

    if not seller_name:
        seller_name = get_current_seller()

    if not seller_name:
        frappe.throw(_("No seller profile found"))

    seller = frappe.get_doc("Seller Profile", seller_name)

    # Verify ownership
    if seller.user != user and not frappe.has_permission("Seller Profile", "write"):
        frappe.throw(_("Not permitted to update this seller profile"))

    # Allowed fields for self-update
    allowed_fields = [
        "display_name", "short_description", "contact_phone", "mobile",
        "whatsapp", "website", "address_line_1", "address_line_2",
        "city", "state", "postal_code", "logo", "banner",
    ]

    # Admin can update additional fields
    if frappe.has_permission("Seller Profile", "write") and seller.user != user:
        allowed_fields.extend([
            "seller_name", "seller_type", "status", "verification_status",
            "commission_plan", "seller_tier", "max_listings", "can_sell",
            "can_withdraw", "can_create_listings", "is_top_seller",
            "is_premium_seller", "is_restricted", "restriction_reason",
        ])

    # Validate IBAN if being updated (admin only)
    if "iban" in kwargs and frappe.has_permission("Seller Profile", "write"):
        iban_validation = validate_iban(kwargs["iban"])
        if not iban_validation["is_valid"]:
            frappe.throw(iban_validation["error"])
        kwargs["iban"] = iban_validation["iban_formatted"].replace(" ", "")
        allowed_fields.append("iban")

    # Update allowed fields
    for field in allowed_fields:
        if field in kwargs:
            setattr(seller, field, kwargs[field])

    seller.save()

    _log_seller_event("profile_updated", user, {"seller": seller_name})

    return {
        "success": True,
        "message": _("Seller profile updated successfully"),
        "seller": seller_name,
    }


@frappe.whitelist()
def toggle_vacation_mode(enable: bool = True) -> Dict[str, Any]:
    """
    Toggle vacation mode for the current seller.

    When vacation mode is enabled, the seller's store is temporarily hidden
    and cannot accept new orders.

    Args:
        enable: True to enable vacation mode, False to disable

    Returns:
        dict: Result of operation
    """
    seller_name = get_current_seller()
    if not seller_name:
        frappe.throw(_("No seller profile found"))

    seller = frappe.get_doc("Seller Profile", seller_name)
    seller.vacation_mode = cint(enable)
    seller.save()

    _log_seller_event(
        "vacation_mode_changed",
        frappe.session.user,
        {"seller": seller_name, "vacation_mode": enable},
    )

    return {
        "success": True,
        "message": _("Vacation mode {0}").format("enabled" if enable else "disabled"),
        "vacation_mode": cint(seller.vacation_mode),
        "status": seller.status,
    }


@frappe.whitelist()
def get_seller_statistics(seller_name: Optional[str] = None) -> Dict[str, Any]:
    """
    Get detailed statistics for a seller.

    Args:
        seller_name: Name of the seller profile (optional)

    Returns:
        dict: Seller statistics
    """
    user = frappe.session.user

    if not seller_name:
        seller_name = get_current_seller()

    if not seller_name:
        frappe.throw(_("No seller profile found"))

    seller = frappe.get_doc("Seller Profile", seller_name)

    # Check permission
    is_owner = seller.user == user
    if not is_owner and not frappe.has_permission("Seller Profile", "read"):
        frappe.throw(_("Not permitted to view seller statistics"))

    # Get listing statistics
    listing_stats = frappe.db.sql(
        """
        SELECT status, COUNT(*) as count
        FROM `tabListing`
        WHERE seller = %s
        GROUP BY status
        """,
        seller_name,
        as_dict=True,
    )

    # Get monthly order statistics
    order_stats = frappe.db.sql(
        """
        SELECT
            DATE_FORMAT(creation, '%%Y-%%m') as month,
            COUNT(*) as order_count,
            COALESCE(SUM(total), 0) as total_amount
        FROM `tabSub Order`
        WHERE seller = %s
        AND status = 'Completed'
        AND creation >= DATE_SUB(NOW(), INTERVAL 12 MONTH)
        GROUP BY DATE_FORMAT(creation, '%%Y-%%m')
        ORDER BY month DESC
        """,
        seller_name,
        as_dict=True,
    )

    return {
        "seller_name": seller_name,
        "seller_score": seller.seller_score,
        "average_rating": seller.average_rating,
        "total_reviews": seller.total_reviews,
        "total_sales_count": seller.total_sales_count,
        "total_sales_amount": seller.total_sales_amount,
        "listing_stats": {s["status"]: s["count"] for s in listing_stats},
        "monthly_sales": order_stats,
        "metrics": {
            "order_fulfillment_rate": seller.order_fulfillment_rate,
            "on_time_delivery_rate": seller.on_time_delivery_rate,
            "return_rate": seller.return_rate,
            "cancellation_rate": seller.cancellation_rate,
            "response_time_hours": seller.response_time_hours,
            "complaint_rate": seller.complaint_rate,
            "positive_feedback_rate": seller.positive_feedback_rate,
        },
        "badges": json.loads(seller.badges or "[]"),
        "available_listing_slots": seller.get_available_listing_slots(),
    }


@frappe.whitelist()
def recalculate_metrics(seller_name: Optional[str] = None) -> Dict[str, Any]:
    """
    Trigger recalculation of seller performance metrics.

    Args:
        seller_name: Name of the seller profile (optional)

    Returns:
        dict: Updated metrics
    """
    check_rate_limit("metrics_update")

    user = frappe.session.user

    if not seller_name:
        seller_name = get_current_seller()

    if not seller_name:
        frappe.throw(_("No seller profile found"))

    seller = frappe.get_doc("Seller Profile", seller_name)

    # Check permission
    if seller.user != user and not frappe.has_permission("Seller Profile", "write"):
        frappe.throw(_("Not permitted to update metrics"))

    seller.update_metrics()

    return {
        "success": True,
        "message": _("Metrics recalculated successfully"),
        "seller_score": seller.seller_score,
        "average_rating": seller.average_rating,
        "metrics": {
            "order_fulfillment_rate": seller.order_fulfillment_rate,
            "on_time_delivery_rate": seller.on_time_delivery_rate,
            "return_rate": seller.return_rate,
            "cancellation_rate": seller.cancellation_rate,
        },
    }


# =============================================================================
# STOREFRONT ENDPOINTS
# =============================================================================


@frappe.whitelist()
def create_storefront(
    store_name: str,
    seller_name: Optional[str] = None,
    **kwargs,
) -> Dict[str, Any]:
    """
    Create a new storefront for a seller.

    Args:
        store_name: Name for the store
        seller_name: Seller profile name (optional, defaults to current user's profile)
        **kwargs: Additional storefront fields

    Returns:
        dict: Created storefront information
    """
    check_rate_limit("storefront_create")

    user = frappe.session.user
    if user == "Guest":
        frappe.throw(_("Not logged in"))

    if not seller_name:
        seller_name = get_current_seller()

    if not seller_name:
        frappe.throw(_("No seller profile found"))

    seller = frappe.get_doc("Seller Profile", seller_name)

    # Verify ownership
    if seller.user != user and not frappe.has_permission("Storefront", "create"):
        frappe.throw(_("Not permitted to create storefront for this seller"))

    # Check if seller already has a storefront
    if frappe.db.exists("Storefront", {"seller": seller_name}):
        frappe.throw(_("Seller already has a storefront"))

    # Create storefront
    storefront_data = {
        "doctype": "Storefront",
        "seller": seller_name,
        "store_name": store_name.strip(),
    }

    # Add optional fields
    optional_fields = [
        "tagline", "short_description", "about_html", "logo", "banner",
        "favicon", "theme", "primary_color", "secondary_color", "accent_color",
        "background_color", "text_color", "layout_type", "meta_title",
        "meta_description", "meta_keywords", "public_email", "public_phone",
        "whatsapp_number", "show_address", "public_address", "facebook_url",
        "instagram_url", "twitter_url", "linkedin_url", "youtube_url",
        "tiktok_url", "shipping_policy", "return_policy", "privacy_policy",
        "terms_of_service",
    ]

    for field in optional_fields:
        if field in kwargs and kwargs[field] is not None:
            storefront_data[field] = kwargs[field]

    storefront = frappe.get_doc(storefront_data)
    storefront.insert()

    _log_seller_event("storefront_created", user, {"storefront": storefront.name, "seller": seller_name})

    return {
        "success": True,
        "message": _("Storefront created successfully"),
        "storefront": storefront.name,
        "slug": storefront.slug,
        "route": storefront.route,
    }


@frappe.whitelist()
def get_storefront(
    storefront_name: Optional[str] = None,
    slug: Optional[str] = None,
    seller_name: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Get storefront information.

    Args:
        storefront_name: Name of the storefront
        slug: URL slug of the storefront
        seller_name: Seller profile name

    Returns:
        dict: Storefront information
    """
    if not storefront_name and not slug and not seller_name:
        # Get current user's storefront
        seller_name = get_current_seller()
        if not seller_name:
            return {"has_storefront": False, "message": _("No storefront found")}

    # Find storefront
    filters = {}
    if storefront_name:
        filters["name"] = storefront_name
    elif slug:
        filters["slug"] = slug
    elif seller_name:
        filters["seller"] = seller_name

    storefront_name = frappe.db.get_value("Storefront", filters, "name")

    if not storefront_name:
        return {"has_storefront": False, "message": _("Storefront not found")}

    storefront = frappe.get_doc("Storefront", storefront_name)

    # Check if published or user has permission
    if not storefront.is_active():
        seller_user = frappe.db.get_value("Seller Profile", storefront.seller, "user")
        if seller_user != frappe.session.user and not frappe.has_permission("Storefront", "read"):
            frappe.throw(_("This storefront is not available"))

    return {
        "has_storefront": True,
        **storefront.get_public_info(),
    }


@frappe.whitelist()
def update_storefront(storefront_name: Optional[str] = None, **kwargs) -> Dict[str, Any]:
    """
    Update storefront information.

    Args:
        storefront_name: Name of the storefront (optional)
        **kwargs: Fields to update

    Returns:
        dict: Update result
    """
    check_rate_limit("storefront_update")

    user = frappe.session.user
    if user == "Guest":
        frappe.throw(_("Not logged in"))

    if not storefront_name:
        seller_name = get_current_seller()
        if seller_name:
            storefront_name = frappe.db.get_value("Storefront", {"seller": seller_name}, "name")

    if not storefront_name:
        frappe.throw(_("No storefront found"))

    storefront = frappe.get_doc("Storefront", storefront_name)

    # Check ownership
    seller_user = frappe.db.get_value("Seller Profile", storefront.seller, "user")
    if seller_user != user and not frappe.has_permission("Storefront", "write"):
        frappe.throw(_("Not permitted to update this storefront"))

    # Allowed fields for update
    allowed_fields = [
        "store_name", "tagline", "short_description", "about_html",
        "logo", "banner", "favicon", "theme", "primary_color", "secondary_color",
        "accent_color", "background_color", "text_color", "layout_type",
        "show_banner", "show_featured_products", "featured_products_count",
        "show_categories", "show_reviews", "show_contact_info", "products_per_page",
        "meta_title", "meta_description", "meta_keywords", "og_image",
        "public_email", "public_phone", "whatsapp_number", "show_address", "public_address",
        "facebook_url", "instagram_url", "twitter_url", "linkedin_url", "youtube_url", "tiktok_url",
        "shipping_policy", "return_policy", "privacy_policy", "terms_of_service",
        "custom_css", "custom_header_html", "custom_footer_html",
    ]

    for field in allowed_fields:
        if field in kwargs:
            setattr(storefront, field, kwargs[field])

    storefront.save()

    _log_seller_event("storefront_updated", user, {"storefront": storefront_name})

    return {
        "success": True,
        "message": _("Storefront updated successfully"),
        "storefront": storefront_name,
    }


@frappe.whitelist()
def publish_storefront(storefront_name: Optional[str] = None) -> Dict[str, Any]:
    """
    Publish a storefront to make it publicly visible.

    Args:
        storefront_name: Name of the storefront (optional)

    Returns:
        dict: Publication result
    """
    user = frappe.session.user
    if user == "Guest":
        frappe.throw(_("Not logged in"))

    if not storefront_name:
        seller_name = get_current_seller()
        if seller_name:
            storefront_name = frappe.db.get_value("Storefront", {"seller": seller_name}, "name")

    if not storefront_name:
        frappe.throw(_("No storefront found"))

    storefront = frappe.get_doc("Storefront", storefront_name)

    # Check ownership
    seller_user = frappe.db.get_value("Seller Profile", storefront.seller, "user")
    if seller_user != user and not frappe.has_permission("Storefront", "write"):
        frappe.throw(_("Not permitted to publish this storefront"))

    storefront.publish()

    _log_seller_event("storefront_published", user, {"storefront": storefront_name})

    return {
        "success": True,
        "message": _("Storefront published successfully"),
        "is_published": storefront.is_published,
        "status": storefront.status,
    }


@frappe.whitelist()
def unpublish_storefront(storefront_name: Optional[str] = None) -> Dict[str, Any]:
    """
    Unpublish a storefront to hide it from public.

    Args:
        storefront_name: Name of the storefront (optional)

    Returns:
        dict: Result
    """
    user = frappe.session.user
    if user == "Guest":
        frappe.throw(_("Not logged in"))

    if not storefront_name:
        seller_name = get_current_seller()
        if seller_name:
            storefront_name = frappe.db.get_value("Storefront", {"seller": seller_name}, "name")

    if not storefront_name:
        frappe.throw(_("No storefront found"))

    storefront = frappe.get_doc("Storefront", storefront_name)

    # Check ownership
    seller_user = frappe.db.get_value("Seller Profile", storefront.seller, "user")
    if seller_user != user and not frappe.has_permission("Storefront", "write"):
        frappe.throw(_("Not permitted to unpublish this storefront"))

    storefront.unpublish()

    return {
        "success": True,
        "message": _("Storefront unpublished"),
        "is_published": storefront.is_published,
        "status": storefront.status,
    }


@frappe.whitelist(allow_guest=True)
def get_featured_storefronts(limit: int = 10) -> List[Dict[str, Any]]:
    """
    Get featured storefronts for homepage/discovery.

    Args:
        limit: Maximum number of storefronts to return

    Returns:
        list: Featured storefronts
    """
    storefronts = frappe.db.sql(
        """
        SELECT
            name, store_name, slug, tagline, logo, banner,
            average_rating, total_reviews, total_products, total_sales
        FROM `tabStorefront`
        WHERE status = 'Active'
        AND is_published = 1
        AND is_featured = 1
        AND (featured_until IS NULL OR featured_until >= NOW())
        ORDER BY featured_priority DESC, average_rating DESC
        LIMIT %s
        """,
        cint(limit),
        as_dict=True,
    )

    return storefronts


@frappe.whitelist(allow_guest=True)
def search_storefronts(query: str, limit: int = 20) -> List[Dict[str, Any]]:
    """
    Search storefronts by name or description.

    Args:
        query: Search query
        limit: Maximum number of results

    Returns:
        list: Matching storefronts
    """
    if not query or len(query) < 2:
        return []

    storefronts = frappe.db.sql(
        """
        SELECT
            name, store_name, slug, tagline, logo,
            average_rating, total_reviews, total_products
        FROM `tabStorefront`
        WHERE status = 'Active'
        AND is_published = 1
        AND (
            store_name LIKE %s
            OR tagline LIKE %s
            OR short_description LIKE %s
        )
        ORDER BY average_rating DESC
        LIMIT %s
        """,
        (f"%{query}%", f"%{query}%", f"%{query}%", cint(limit)),
        as_dict=True,
    )

    return storefronts


# =============================================================================
# COMMISSION PLAN ENDPOINTS
# =============================================================================


@frappe.whitelist()
def get_commission_plans(seller_name: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Get available commission plans for a seller.

    Args:
        seller_name: Seller profile name (optional)

    Returns:
        list: Available commission plans
    """
    if not seller_name:
        seller_name = get_current_seller()

    # Get tenant filter
    tenant = None
    if seller_name:
        tenant = frappe.db.get_value("Seller Profile", seller_name, "tenant")

    # Get available plans
    filters = {"status": "Active"}
    if tenant:
        filters["tenant"] = ["in", [tenant, None, ""]]

    plans = frappe.get_all(
        "Commission Plan",
        filters=filters,
        fields=[
            "name", "plan_name", "plan_code", "plan_type",
            "base_commission_rate", "is_default", "short_description",
            "max_sellers", "current_seller_count", "is_invite_only",
        ],
        order_by="is_default desc, base_commission_rate asc",
    )

    result = []
    for p in plans:
        # Check availability
        if cint(p["max_sellers"]) > 0 and cint(p["current_seller_count"]) >= cint(p["max_sellers"]):
            p["available"] = False
            p["unavailable_reason"] = _("Plan is full")
        elif cint(p["is_invite_only"]):
            p["available"] = False
            p["unavailable_reason"] = _("Invite only")
        else:
            p["available"] = True

        # Check seller eligibility if seller provided
        if seller_name and p["available"]:
            plan = frappe.get_doc("Commission Plan", p["name"])
            can_join, reason = plan.can_seller_join(seller_name)
            if not can_join:
                p["available"] = False
                p["unavailable_reason"] = reason

        result.append(p)

    return result


@frappe.whitelist()
def get_my_commission_plan() -> Dict[str, Any]:
    """
    Get the commission plan for the current seller.

    Returns:
        dict: Commission plan details
    """
    seller_name = get_current_seller()
    if not seller_name:
        frappe.throw(_("No seller profile found"))

    commission_plan = frappe.db.get_value("Seller Profile", seller_name, "commission_plan")

    if not commission_plan:
        # Get default plan
        default = frappe.db.get_value(
            "Commission Plan",
            {"is_default": 1, "status": "Active"},
            "name",
        )
        if default:
            return {
                "has_plan": False,
                "message": _("No plan assigned, using default"),
                "default_plan": frappe.get_doc("Commission Plan", default).get_plan_summary(),
            }
        return {"has_plan": False, "message": _("No commission plan assigned")}

    plan = frappe.get_doc("Commission Plan", commission_plan)
    return {
        "has_plan": True,
        **plan.get_plan_summary(),
    }


@frappe.whitelist()
def calculate_commission(
    order_value: float,
    category: Optional[str] = None,
    seller_name: Optional[str] = None,
    shipping_cost: float = 0,
) -> Dict[str, Any]:
    """
    Calculate commission for an order value.

    Args:
        order_value: Total order value
        category: Product category (optional)
        seller_name: Seller profile name (optional)
        shipping_cost: Shipping cost to potentially exclude

    Returns:
        dict: Commission calculation result
    """
    if not seller_name:
        seller_name = get_current_seller()

    if not seller_name:
        frappe.throw(_("Seller is required"))

    commission_plan = frappe.db.get_value("Seller Profile", seller_name, "commission_plan")

    if not commission_plan:
        # Use default plan
        commission_plan = frappe.db.get_value(
            "Commission Plan",
            {"is_default": 1, "status": "Active"},
            "name",
        )

    if not commission_plan:
        frappe.throw(_("No commission plan found"))

    plan = frappe.get_doc("Commission Plan", commission_plan)

    if not plan.is_active():
        frappe.throw(_("Commission plan is not active"))

    return plan.calculate_commission(
        order_value=flt(order_value),
        category=category,
        seller=seller_name,
        shipping_cost=flt(shipping_cost),
    )


# =============================================================================
# SELLER TIER ENDPOINTS
# =============================================================================


@frappe.whitelist()
def get_seller_tier(seller_name: Optional[str] = None) -> Dict[str, Any]:
    """
    Get the tier information for a seller.

    Args:
        seller_name: Seller profile name (optional)

    Returns:
        dict: Tier information
    """
    if not seller_name:
        seller_name = get_current_seller()

    if not seller_name:
        frappe.throw(_("No seller profile found"))

    seller = frappe.get_doc("Seller Profile", seller_name)

    if not seller.seller_tier:
        return {"has_tier": False, "message": _("No tier assigned")}

    tier = frappe.get_doc("Seller Tier", seller.seller_tier)

    return {
        "has_tier": True,
        "tier_name": tier.tier_name,
        "tier_level": tier.tier_level,
        "badge_icon": tier.badge_icon,
        "badge_color": tier.badge_color,
        "badge_image": tier.badge_image,
        "description": tier.description,
        "benefits_summary": tier.get_benefits_summary() if hasattr(tier, "get_benefits_summary") else None,
        "requirements_summary": tier.get_requirements_summary() if hasattr(tier, "get_requirements_summary") else None,
    }


@frappe.whitelist()
def get_tier_progression(seller_name: Optional[str] = None) -> Dict[str, Any]:
    """
    Get tier progression information for a seller.

    Shows current tier, next tier requirements, and progress.

    Args:
        seller_name: Seller profile name (optional)

    Returns:
        dict: Tier progression information
    """
    if not seller_name:
        seller_name = get_current_seller()

    if not seller_name:
        frappe.throw(_("No seller profile found"))

    seller = frappe.get_doc("Seller Profile", seller_name)

    current_tier = None
    next_tier = None

    if seller.seller_tier:
        current_tier = frappe.get_doc("Seller Tier", seller.seller_tier)
        if current_tier.next_tier:
            next_tier = frappe.get_doc("Seller Tier", current_tier.next_tier)

    result = {
        "seller_score": seller.seller_score,
        "total_sales_count": seller.total_sales_count,
        "total_sales_amount": seller.total_sales_amount,
        "average_rating": seller.average_rating,
    }

    if current_tier:
        result["current_tier"] = {
            "name": current_tier.tier_name,
            "level": current_tier.tier_level,
            "badge_color": current_tier.badge_color,
        }

    if next_tier:
        result["next_tier"] = {
            "name": next_tier.tier_name,
            "level": next_tier.tier_level,
            "badge_color": next_tier.badge_color,
            "requirements": {
                "min_seller_score": next_tier.min_seller_score,
                "min_total_sales_count": next_tier.min_total_sales_count,
                "min_average_rating": next_tier.min_average_rating,
            },
        }

        # Calculate progress
        if next_tier.min_seller_score:
            result["score_progress"] = min(100, (seller.seller_score / next_tier.min_seller_score) * 100)
        if next_tier.min_total_sales_count:
            result["sales_progress"] = min(100, (seller.total_sales_count / next_tier.min_total_sales_count) * 100)
        if next_tier.min_average_rating:
            result["rating_progress"] = min(100, (seller.average_rating / next_tier.min_average_rating) * 100)

    return result


@frappe.whitelist()
def get_all_tiers() -> List[Dict[str, Any]]:
    """
    Get all available seller tiers.

    Returns:
        list: All seller tiers
    """
    tiers = frappe.get_all(
        "Seller Tier",
        filters={"is_active": 1},
        fields=[
            "name", "tier_name", "tier_level", "badge_icon", "badge_color",
            "badge_image", "description", "min_seller_score", "min_total_sales_count",
            "min_average_rating",
        ],
        order_by="tier_level asc",
    )

    return tiers


# =============================================================================
# VALIDATION ENDPOINTS
# =============================================================================


@frappe.whitelist(allow_guest=True)
def validate_tax_id_api(tax_id: str, tax_id_type: str = "TCKN") -> Dict[str, Any]:
    """
    Validate a Turkish tax ID (public API).

    Args:
        tax_id: Tax ID to validate
        tax_id_type: Type of tax ID (VKN or TCKN)

    Returns:
        dict: Validation result
    """
    result = validate_tax_id(tax_id, tax_id_type)
    return {
        "is_valid": result["is_valid"],
        "tax_id_type": tax_id_type,
        "expected_length": 10 if tax_id_type == "VKN" else 11,
        "actual_length": len(tax_id) if tax_id else 0,
    }


@frappe.whitelist(allow_guest=True)
def validate_iban_api(iban: str) -> Dict[str, Any]:
    """
    Validate a Turkish IBAN (public API).

    Args:
        iban: IBAN to validate

    Returns:
        dict: Validation result
    """
    return validate_iban(iban)


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================


def _log_seller_event(
    event_type: str,
    user: str,
    details: Dict[str, Any],
) -> None:
    """Log seller-related events for audit trail."""
    try:
        ip_address = None
        try:
            if frappe.request:
                ip_address = frappe.request.remote_addr
        except Exception:
            pass

        frappe.get_doc(
            {
                "doctype": "Activity Log",
                "user": user,
                "operation": f"seller_{event_type}",
                "status": "Success",
                "content": frappe.as_json(details),
                "ip_address": ip_address,
            }
        ).insert(ignore_permissions=True)
    except Exception as e:
        frappe.log_error(f"Seller event logging error: {str(e)}", "Seller API")


# =============================================================================
# PUBLIC API SUMMARY
# =============================================================================

"""
Public API Endpoints:

Seller Application:
- create_application: Create new seller application
- submit_application: Submit application for review
- get_application_status: Get application status
- update_application: Update draft/revision application
- cancel_application: Cancel application

Seller Profile:
- get_seller_profile: Get seller profile details
- update_seller_profile: Update seller profile
- toggle_vacation_mode: Enable/disable vacation mode
- get_seller_statistics: Get detailed statistics
- recalculate_metrics: Trigger metrics recalculation

Storefront:
- create_storefront: Create new storefront
- get_storefront: Get storefront details
- update_storefront: Update storefront
- publish_storefront: Publish storefront
- unpublish_storefront: Unpublish storefront
- get_featured_storefronts: Get featured storefronts
- search_storefronts: Search storefronts

Commission Plans:
- get_commission_plans: Get available plans
- get_my_commission_plan: Get current seller's plan
- calculate_commission: Calculate commission for order

Seller Tiers:
- get_seller_tier: Get seller tier info
- get_tier_progression: Get tier progression
- get_all_tiers: Get all tiers

Validation:
- validate_tax_id_api: Validate Turkish tax ID
- validate_iban_api: Validate Turkish IBAN
"""

# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt, getdate, nowdate, now_datetime, add_days, date_diff


class KYCProfile(Document):
    """
    KYC Profile DocType for individual identity verification in TR-TradeHub marketplace.

    KYC (Know Your Customer) profiles are used to verify individual users who want to:
    - Sell as individuals on the marketplace (C2C)
    - Act as sole proprietors or freelancers
    - Become verified buyers with higher transaction limits

    Features:
    - Turkish ID (TCKN) validation with checksum
    - Document upload and verification workflow
    - AML/Sanctions screening integration
    - Risk scoring and assessment
    - KVKK (Turkish GDPR) consent tracking
    """

    def before_insert(self):
        """Set default values before inserting a new KYC profile."""
        if not self.created_by:
            self.created_by = frappe.session.user

        # Set tenant from user context if not specified
        if not self.tenant:
            self.set_tenant_from_context()

        # Set email from user if not provided
        if not self.email and self.user:
            self.email = frappe.db.get_value("User", self.user, "email")

    def validate(self):
        """Validate KYC profile data before saving."""
        self.validate_user_unique()
        self.validate_age()
        self.validate_tckn()
        self.validate_passport_number()
        self.validate_id_expiry()
        self.validate_kvkk_consent()
        self.validate_status_transition()
        self.update_full_name()
        self.modified_by = frappe.session.user

    def on_update(self):
        """Actions to perform after KYC profile is updated."""
        self.update_user_kyc_status()
        self.clear_kyc_cache()

    def after_insert(self):
        """Actions to perform after KYC profile is inserted."""
        self.notify_submission()

    def on_trash(self):
        """Prevent deletion of verified KYC profiles."""
        if self.status == "Verified":
            frappe.throw(
                _("Cannot delete verified KYC profiles. "
                  "Please archive or suspend instead.")
            )

    def set_tenant_from_context(self):
        """Set tenant from user's session context."""
        try:
            from tradehub_core.tradehub_core.utils.tenant import get_current_tenant
            tenant = get_current_tenant()
            if tenant:
                self.tenant = tenant
        except ImportError:
            pass

    def validate_user_unique(self):
        """Ensure only one active KYC profile per user."""
        if self.user:
            existing = frappe.db.get_value(
                "KYC Profile",
                {
                    "user": self.user,
                    "name": ("!=", self.name),
                    "status": ("not in", ["Rejected", "Expired"])
                },
                "name"
            )
            if existing:
                frappe.throw(
                    _("User {0} already has an active KYC profile: {1}").format(
                        self.user, existing
                    )
                )

    def validate_age(self):
        """Validate that user is at least 18 years old."""
        if self.date_of_birth:
            today = getdate(nowdate())
            dob = getdate(self.date_of_birth)
            age = date_diff(today, dob) // 365

            if age < 18:
                frappe.throw(_("User must be at least 18 years old to complete KYC"))

            if age > 120:
                frappe.throw(_("Please verify the date of birth"))

    def validate_tckn(self):
        """
        Validate Turkish Citizenship Number (TCKN) format and checksum.
        TCKN is 11 digits with specific validation rules.
        """
        if self.tckn:
            tckn = self.tckn.strip()

            if not tckn.isdigit():
                frappe.throw(_("TCKN must contain only digits"))

            if len(tckn) != 11:
                frappe.throw(_("TCKN must be exactly 11 digits"))

            if tckn[0] == '0':
                frappe.throw(_("TCKN cannot start with 0"))

            # Validate TCKN checksum
            if not self.validate_tckn_checksum(tckn):
                frappe.throw(_("Invalid TCKN. Checksum validation failed."))

            self.tckn = tckn

    def validate_tckn_checksum(self, tckn):
        """
        Validate Turkish Citizenship Number (TCKN) checksum.

        Algorithm:
        - 10th digit = ((sum of 1st,3rd,5th,7th,9th digits) * 7 -
                        (sum of 2nd,4th,6th,8th digits)) % 10
        - 11th digit = (sum of first 10 digits) % 10
        """
        if len(tckn) != 11:
            return False

        try:
            digits = [int(d) for d in tckn]

            # First check: 10th digit
            odd_sum = sum(digits[i] for i in range(0, 9, 2))  # 1st,3rd,5th,7th,9th
            even_sum = sum(digits[i] for i in range(1, 8, 2))  # 2nd,4th,6th,8th
            check_10 = (odd_sum * 7 - even_sum) % 10

            if check_10 != digits[9]:
                return False

            # Second check: 11th digit
            check_11 = sum(digits[:10]) % 10

            if check_11 != digits[10]:
                return False

            return True
        except (ValueError, IndexError):
            return False

    def validate_passport_number(self):
        """Validate passport number format if provided."""
        if self.passport_number:
            passport = self.passport_number.strip().upper()
            # Turkish passports start with U followed by 8 digits
            # But international passports vary, so basic validation
            if len(passport) < 6 or len(passport) > 15:
                frappe.throw(_("Invalid passport number format"))
            self.passport_number = passport

    def validate_id_expiry(self):
        """Validate that ID document is not expired."""
        if self.id_expiry_date:
            if getdate(self.id_expiry_date) < getdate(nowdate()):
                frappe.throw(_("ID document has expired. Please provide a valid document."))

    def validate_kvkk_consent(self):
        """Validate KVKK consent for submission."""
        if self.status == "Pending Review" and not self.kvkk_consent_given:
            frappe.throw(
                _("KVKK consent is required to submit KYC application. "
                  "Please accept the privacy policy.")
            )

    def validate_status_transition(self):
        """Validate status transitions are valid."""
        if self.is_new():
            return

        old_status = frappe.db.get_value("KYC Profile", self.name, "status")

        valid_transitions = {
            "Draft": ["Pending Review"],
            "Pending Review": ["In Review", "Documents Required", "Rejected"],
            "In Review": ["Verified", "Rejected", "Documents Required"],
            "Documents Required": ["Pending Review", "Rejected"],
            "Verified": ["Expired", "Suspended"],
            "Rejected": ["Draft"],  # Allow reapplication
            "Expired": ["Draft"],
            "Suspended": ["Verified", "Rejected"]
        }

        if old_status and old_status != self.status:
            allowed = valid_transitions.get(old_status, [])
            if self.status not in allowed:
                frappe.throw(
                    _("Invalid status transition from {0} to {1}").format(
                        old_status, self.status
                    )
                )

    def update_full_name(self):
        """Update full name from name components."""
        name_parts = [self.first_name]
        if self.middle_name:
            name_parts.append(self.middle_name)
        name_parts.append(self.last_name)
        self.full_name = " ".join(filter(None, name_parts))

    def update_user_kyc_status(self):
        """Update user's KYC verification status."""
        if not self.user:
            return

        # Update custom field on User if it exists
        try:
            if self.status == "Verified":
                frappe.db.set_value(
                    "User", self.user, "kyc_verified", 1,
                    update_modified=False
                )
            elif self.status in ["Rejected", "Expired", "Suspended"]:
                frappe.db.set_value(
                    "User", self.user, "kyc_verified", 0,
                    update_modified=False
                )
        except Exception:
            # Custom field might not exist
            pass

    def clear_kyc_cache(self):
        """Clear cached KYC data."""
        if self.user:
            cache_key = f"kyc_profile:{self.user}"
            frappe.cache().delete_value(cache_key)

    def notify_submission(self):
        """Send notification when KYC is submitted for review."""
        if self.status == "Pending Review":
            # TODO: Send email notification to compliance team
            pass

    # Verification Methods
    def submit_for_review(self):
        """Submit KYC profile for review."""
        if self.status != "Draft":
            frappe.throw(_("Only draft profiles can be submitted for review"))

        # Validate required documents
        if not self.id_front_image:
            frappe.throw(_("ID front image is required"))

        if not self.kvkk_consent_given:
            frappe.throw(_("KVKK consent is required"))

        self.status = "Pending Review"
        self.save()

    def start_review(self, reviewer=None):
        """Mark profile as being reviewed."""
        if self.status != "Pending Review":
            frappe.throw(_("Only pending profiles can be reviewed"))

        self.status = "In Review"
        self.verification_status = "In Progress"
        self.save()

    def request_documents(self, documents_needed=None, notes=None):
        """Request additional documents from user."""
        self.status = "Documents Required"
        if notes:
            self.internal_notes = f"Documents requested: {notes}\n\n{self.internal_notes or ''}"
        self.save()

        # TODO: Send notification to user

    def mark_verified(self, verified_by=None):
        """Mark KYC profile as verified."""
        self.status = "Verified"
        self.verification_status = "Completed"
        self.verified_at = now_datetime()
        self.verified_by = verified_by or frappe.session.user
        self.id_verified = 1

        # Set review date based on risk level
        review_days = {
            "Low": 365,
            "Medium": 180,
            "High": 90,
            "Very High": 30
        }
        days = review_days.get(self.risk_level, 365)
        self.next_review_date = add_days(nowdate(), days)

        self.save()

        # TODO: Send notification to user

    def mark_rejected(self, reason=None, notes=None, can_reapply=True, reapply_days=30):
        """Mark KYC profile as rejected."""
        self.status = "Rejected"
        self.verification_status = "Failed"
        self.rejection_reason = reason
        self.rejection_date = now_datetime()
        self.can_reapply = cint(can_reapply)

        if notes:
            self.rejection_notes = notes

        if can_reapply:
            self.reapply_after = add_days(nowdate(), reapply_days)

        self.save()

        # TODO: Send notification to user

    def suspend(self, reason=None):
        """Suspend a verified KYC profile."""
        if self.status != "Verified":
            frappe.throw(_("Only verified profiles can be suspended"))

        self.status = "Suspended"
        if reason:
            self.internal_notes = f"Suspended: {reason}\n\n{self.internal_notes or ''}"
        self.save()

    def expire(self):
        """Mark KYC profile as expired."""
        if self.status != "Verified":
            frappe.throw(_("Only verified profiles can expire"))

        self.status = "Expired"
        self.save()

    # AML/Risk Methods
    def run_aml_check(self, provider="manual"):
        """
        Run AML/Sanctions screening.
        This is a placeholder for integration with actual AML providers.
        """
        self.aml_check_status = "Pending"
        self.aml_check_date = now_datetime()
        self.aml_provider = provider
        self.save()

        # TODO: Integrate with actual AML provider (e.g., ComplyAdvantage, Refinitiv)
        # For now, return placeholder response
        return {
            "status": "Pending",
            "message": _("AML check requires provider integration")
        }

    def calculate_risk_score(self):
        """
        Calculate risk score based on various factors.
        Score: 0-100, higher = more risk
        """
        score = 0
        factors = []

        # Country risk
        high_risk_countries = ["AF", "IR", "KP", "SY", "YE"]  # ISO codes
        country = frappe.db.get_value("Country", self.nationality, "code") if self.nationality else None
        if country and country.upper() in high_risk_countries:
            score += 30
            factors.append("High-risk nationality")

        # PEP status
        if self.pep_status == "PEP":
            score += 25
            factors.append("Politically Exposed Person")
        elif self.pep_status == "PEP Relative/Associate":
            score += 15
            factors.append("PEP relative/associate")

        # Sanctions match
        if self.sanctions_status == "Match Found":
            score += 40
            factors.append("Sanctions list match")

        # Adverse media
        if self.adverse_media_status == "Match Found":
            score += 20
            factors.append("Adverse media found")

        # Document issues
        if not self.id_verified:
            score += 10
            factors.append("ID not verified")

        if not self.address_verified:
            score += 5
            factors.append("Address not verified")

        # Age factor (very young or very old)
        if self.date_of_birth:
            age = date_diff(getdate(nowdate()), getdate(self.date_of_birth)) // 365
            if age < 21:
                score += 5
                factors.append("Young age")
            elif age > 70:
                score += 5
                factors.append("Elderly")

        # Cap at 100
        self.risk_score = min(100, score)
        self.risk_factors = "\n".join(factors) if factors else "No risk factors identified"
        self.last_risk_assessment = now_datetime()

        # Set risk level based on score
        if score >= 70:
            self.risk_level = "Very High"
        elif score >= 50:
            self.risk_level = "High"
        elif score >= 25:
            self.risk_level = "Medium"
        else:
            self.risk_level = "Low"

        self.save()

        return {
            "score": self.risk_score,
            "level": self.risk_level,
            "factors": factors
        }

    # Utility Methods
    def is_verified(self):
        """Check if KYC is verified."""
        return self.status == "Verified"

    def is_active(self):
        """Check if KYC is in an active state."""
        return self.status in ["Verified", "Pending Review", "In Review"]

    def can_user_transact(self):
        """Check if user can perform marketplace transactions."""
        return self.status == "Verified" and not self.is_high_risk()

    def is_high_risk(self):
        """Check if user is classified as high risk."""
        return self.risk_level in ["High", "Very High"]

    def get_verification_summary(self):
        """Get a summary of verification status."""
        return {
            "status": self.status,
            "verification_status": self.verification_status,
            "id_verified": self.id_verified,
            "address_verified": self.address_verified,
            "liveness_verified": self.liveness_verified,
            "aml_status": self.aml_check_status,
            "risk_level": self.risk_level,
            "risk_score": self.risk_score
        }


# API Endpoints
@frappe.whitelist()
def get_kyc_profile(user=None):
    """
    Get KYC profile for a user.

    Args:
        user: User to get profile for (defaults to current user)

    Returns:
        dict: KYC profile details
    """
    user = user or frappe.session.user

    # Check if user can access this profile
    if user != frappe.session.user and "System Manager" not in frappe.get_roles():
        frappe.throw(_("Not permitted to access KYC profile"))

    kyc = frappe.db.get_value(
        "KYC Profile",
        {"user": user, "status": ("not in", ["Rejected", "Expired"])},
        ["name", "full_name", "status", "verification_status", "risk_level"],
        as_dict=True
    )

    if not kyc:
        return {"exists": False}

    return {
        "exists": True,
        **kyc
    }


@frappe.whitelist()
def submit_kyc_for_review(kyc_profile_name):
    """
    Submit a KYC profile for review.

    Args:
        kyc_profile_name: Name of the KYC profile

    Returns:
        dict: Result of operation
    """
    kyc = frappe.get_doc("KYC Profile", kyc_profile_name)

    # Permission check
    if kyc.user != frappe.session.user:
        frappe.throw(_("Not permitted to submit this KYC profile"))

    kyc.submit_for_review()

    return {
        "status": "success",
        "message": _("KYC profile submitted for review"),
        "profile_status": kyc.status
    }


@frappe.whitelist()
def verify_kyc(kyc_profile_name):
    """
    Verify a KYC profile (admin only).

    Args:
        kyc_profile_name: Name of the KYC profile

    Returns:
        dict: Result of operation
    """
    if "System Manager" not in frappe.get_roles():
        frappe.throw(_("Not permitted to verify KYC profiles"))

    kyc = frappe.get_doc("KYC Profile", kyc_profile_name)
    kyc.mark_verified()

    return {
        "status": "success",
        "message": _("KYC profile verified successfully"),
        "verification_status": kyc.verification_status
    }


@frappe.whitelist()
def reject_kyc(kyc_profile_name, reason=None, notes=None, can_reapply=1):
    """
    Reject a KYC profile (admin only).

    Args:
        kyc_profile_name: Name of the KYC profile
        reason: Rejection reason
        notes: Additional notes
        can_reapply: Whether user can reapply

    Returns:
        dict: Result of operation
    """
    if "System Manager" not in frappe.get_roles():
        frappe.throw(_("Not permitted to reject KYC profiles"))

    kyc = frappe.get_doc("KYC Profile", kyc_profile_name)
    kyc.mark_rejected(reason, notes, cint(can_reapply))

    return {
        "status": "success",
        "message": _("KYC profile rejected"),
        "can_reapply": kyc.can_reapply,
        "reapply_after": kyc.reapply_after
    }


@frappe.whitelist()
def run_risk_assessment(kyc_profile_name):
    """
    Run risk assessment on a KYC profile.

    Args:
        kyc_profile_name: Name of the KYC profile

    Returns:
        dict: Risk assessment results
    """
    if "System Manager" not in frappe.get_roles():
        frappe.throw(_("Not permitted to run risk assessment"))

    kyc = frappe.get_doc("KYC Profile", kyc_profile_name)
    result = kyc.calculate_risk_score()

    return {
        "status": "success",
        **result
    }


@frappe.whitelist()
def validate_tckn(tckn):
    """
    Validate a Turkish Citizenship Number.

    Args:
        tckn: TCKN to validate

    Returns:
        dict: Validation result
    """
    if not tckn:
        return {"valid": False, "message": _("TCKN is required")}

    tckn = tckn.strip()

    if not tckn.isdigit():
        return {"valid": False, "message": _("TCKN must contain only digits")}

    if len(tckn) != 11:
        return {"valid": False, "message": _("TCKN must be exactly 11 digits")}

    if tckn[0] == '0':
        return {"valid": False, "message": _("TCKN cannot start with 0")}

    # Create temporary instance to use validation method
    kyc = KYCProfile.__new__(KYCProfile)
    if not kyc.validate_tckn_checksum(tckn):
        return {"valid": False, "message": _("Invalid TCKN checksum")}

    return {"valid": True, "message": _("TCKN is valid")}


@frappe.whitelist()
def get_pending_kyc_reviews():
    """
    Get list of KYC profiles pending review (admin only).

    Returns:
        list: Pending KYC profiles
    """
    if "System Manager" not in frappe.get_roles():
        frappe.throw(_("Not permitted to view pending reviews"))

    profiles = frappe.get_all(
        "KYC Profile",
        filters={"status": ["in", ["Pending Review", "In Review"]]},
        fields=[
            "name", "full_name", "user", "status", "profile_type",
            "nationality", "creation", "risk_level"
        ],
        order_by="creation asc"
    )

    return profiles


@frappe.whitelist()
def get_kyc_statistics():
    """
    Get KYC statistics for dashboard (admin only).

    Returns:
        dict: KYC statistics
    """
    if "System Manager" not in frappe.get_roles():
        frappe.throw(_("Not permitted to view KYC statistics"))

    stats = {
        "total": frappe.db.count("KYC Profile"),
        "verified": frappe.db.count("KYC Profile", {"status": "Verified"}),
        "pending": frappe.db.count("KYC Profile", {"status": "Pending Review"}),
        "in_review": frappe.db.count("KYC Profile", {"status": "In Review"}),
        "rejected": frappe.db.count("KYC Profile", {"status": "Rejected"}),
        "expired": frappe.db.count("KYC Profile", {"status": "Expired"}),
        "suspended": frappe.db.count("KYC Profile", {"status": "Suspended"})
    }

    # Risk distribution
    stats["risk_distribution"] = {
        "low": frappe.db.count("KYC Profile", {"risk_level": "Low", "status": "Verified"}),
        "medium": frappe.db.count("KYC Profile", {"risk_level": "Medium", "status": "Verified"}),
        "high": frappe.db.count("KYC Profile", {"risk_level": "High", "status": "Verified"}),
        "very_high": frappe.db.count("KYC Profile", {"risk_level": "Very High", "status": "Verified"})
    }

    return stats

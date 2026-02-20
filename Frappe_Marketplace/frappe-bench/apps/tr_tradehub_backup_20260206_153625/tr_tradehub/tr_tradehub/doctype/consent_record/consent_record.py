# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, getdate, nowdate, now_datetime, add_days, get_datetime


class ConsentRecord(Document):
    """
    Consent Record DocType for KVKK (Turkish Personal Data Protection Law) compliance.

    This DocType records and manages user consents for various data processing activities
    as required by KVKK (Kisisel Verilerin Korunmasi Kanunu) and GDPR-compatible regulations.

    Features:
    - Multiple consent types (data processing, marketing, third-party sharing, etc.)
    - Consent collection tracking with IP address and timestamp
    - Consent withdrawal management
    - Double opt-in verification
    - Third-party sharing tracking for international transfers
    - Consent version tracking for audit trail
    - Expiry and renewal management
    """

    def before_insert(self):
        """Set default values before inserting a new consent record."""
        if not self.created_by:
            self.created_by = frappe.session.user

        # Set tenant from user context if not specified
        if not self.tenant:
            self.set_tenant_from_context()

        # Set given_at timestamp if consent is given
        if self.is_given and not self.given_at:
            self.given_at = now_datetime()

        # Capture request information
        if self.is_given and not self.given_ip_address:
            self.capture_request_info()

    def validate(self):
        """Validate consent record data before saving."""
        self.validate_user()
        self.validate_consent_given()
        self.validate_expiry()
        self.validate_third_party()
        self.validate_status_transitions()
        self.validate_withdrawal()
        self.modified_by = frappe.session.user

    def on_update(self):
        """Actions to perform after consent record is updated."""
        self.update_related_profiles()
        self.clear_consent_cache()

    def after_insert(self):
        """Actions to perform after consent record is created."""
        self.send_consent_confirmation()
        self.log_consent_event("created")

    def on_trash(self):
        """Prevent deletion of consent records - they must be preserved for audit."""
        frappe.throw(
            _("Consent records cannot be deleted for audit purposes. "
              "Mark as withdrawn or expired instead.")
        )

    def set_tenant_from_context(self):
        """Set tenant from user's session context."""
        try:
            from tr_tradehub.utils.tenant import get_current_tenant
            tenant = get_current_tenant()
            if tenant:
                self.tenant = tenant
        except ImportError:
            pass

    def capture_request_info(self):
        """Capture IP address and user agent from request."""
        try:
            if frappe.request:
                self.given_ip_address = frappe.request.remote_addr
                self.given_user_agent = str(frappe.request.user_agent)[:500]  # Limit length
        except Exception:
            pass

    def validate_user(self):
        """Validate that user exists and is active."""
        if self.user:
            if not frappe.db.exists("User", self.user):
                frappe.throw(_("User {0} does not exist").format(self.user))

            # Check if user is enabled
            enabled = frappe.db.get_value("User", self.user, "enabled")
            if not enabled:
                frappe.msgprint(
                    _("Warning: User {0} is disabled").format(self.user),
                    indicator="orange"
                )

    def validate_consent_given(self):
        """Validate consent given fields."""
        if self.is_given:
            if not self.given_at:
                self.given_at = now_datetime()

            if not self.given_via:
                frappe.throw(_("Please specify how consent was given"))

        # If consent is being given now, set status to Active or Pending Verification
        if self.is_given and self.status == "Pending Verification":
            # Keep as pending if verification is needed
            if self.requires_double_opt_in():
                self.status = "Pending Verification"
            else:
                self.status = "Active"

    def validate_expiry(self):
        """Validate expiry settings."""
        if self.has_expiry:
            if not self.expiry_date:
                frappe.throw(_("Expiry date is required when 'Has Expiry' is checked"))

            # Check if already expired
            if getdate(self.expiry_date) < getdate(nowdate()):
                if self.status == "Active":
                    self.status = "Expired"
                    self.is_given = 0
                    frappe.msgprint(_("Consent has expired"), indicator="orange")

    def validate_third_party(self):
        """Validate third-party sharing fields."""
        if self.involves_third_party or self.consent_type in ["Third Party Sharing", "International Transfer"]:
            if not self.third_party_name:
                frappe.throw(_("Third party name is required for third-party sharing consent"))

            # For international transfers, country is required
            if self.consent_type == "International Transfer" and not self.third_party_country:
                frappe.throw(_("Third party country is required for international transfer consent"))

    def validate_status_transitions(self):
        """Validate that status transitions are valid."""
        if self.is_new():
            return

        old_status = frappe.db.get_value("Consent Record", self.name, "status")

        valid_transitions = {
            "Pending Verification": ["Active", "Expired", "Invalid"],
            "Active": ["Withdrawn", "Expired", "Superseded"],
            "Withdrawn": [],  # Cannot change from withdrawn
            "Expired": ["Active"],  # Can renew
            "Superseded": [],  # Cannot change from superseded
            "Invalid": []  # Cannot change from invalid
        }

        if old_status and old_status != self.status:
            allowed = valid_transitions.get(old_status, [])
            if self.status not in allowed:
                frappe.throw(
                    _("Invalid status transition from {0} to {1}").format(
                        old_status, self.status
                    )
                )

    def validate_withdrawal(self):
        """Validate withdrawal fields."""
        if self.is_withdrawn:
            if not self.withdrawn_at:
                self.withdrawn_at = now_datetime()

            self.status = "Withdrawn"
            self.is_given = 0

            # Capture IP for withdrawal
            if not self.withdrawn_ip_address:
                try:
                    if frappe.request:
                        self.withdrawn_ip_address = frappe.request.remote_addr
                except Exception:
                    pass

    def requires_double_opt_in(self):
        """Check if this consent type requires double opt-in."""
        # Marketing and newsletter typically require double opt-in
        double_opt_in_types = [
            "Marketing Communications",
            "Newsletter",
            "Email Notifications",
            "SMS Notifications"
        ]
        return self.consent_type in double_opt_in_types

    def update_related_profiles(self):
        """Update related profiles when consent changes."""
        if self.kyc_profile:
            self.update_kyc_consent_status()

    def update_kyc_consent_status(self):
        """Update KYC profile consent status."""
        if not self.kyc_profile:
            return

        try:
            kyc = frappe.get_doc("KYC Profile", self.kyc_profile)

            if self.consent_type == "Data Processing":
                kyc.data_processing_consent = cint(self.is_given and self.status == "Active")
            elif self.consent_type == "Marketing Communications":
                kyc.marketing_consent = cint(self.is_given and self.status == "Active")
            elif self.consent_type == "Third Party Sharing":
                kyc.third_party_sharing_consent = cint(self.is_given and self.status == "Active")

            # Update KVKK consent flag
            if self.consent_type == "Data Processing":
                kyc.kvkk_consent_given = cint(self.is_given and self.status == "Active")
                if self.is_given and self.status == "Active":
                    kyc.kvkk_consent_date = self.given_at
                    kyc.kvkk_consent_version = self.consent_version

            kyc.flags.ignore_permissions = True
            kyc.save(ignore_permissions=True)
        except Exception as e:
            frappe.log_error(
                f"Error updating KYC consent status: {str(e)}",
                "Consent Record Update Error"
            )

    def clear_consent_cache(self):
        """Clear cached consent data for user."""
        if self.user:
            cache_key = f"consent_records:{self.user}"
            frappe.cache().delete_value(cache_key)

    def send_consent_confirmation(self):
        """Send confirmation email for consent."""
        if not self.is_given:
            return

        # Check if double opt-in is required
        if self.requires_double_opt_in() and not self.is_verified:
            self.send_double_opt_in_email()

    def send_double_opt_in_email(self):
        """Send double opt-in verification email."""
        # Generate verification token
        verification_token = frappe.generate_hash(length=32)
        self.verification_reference = verification_token

        # TODO: Implement actual email sending
        # This would typically use frappe.sendmail with a verification link

    def log_consent_event(self, event_type):
        """Log consent event for audit trail."""
        frappe.get_doc({
            "doctype": "Comment",
            "comment_type": "Info",
            "reference_doctype": "Consent Record",
            "reference_name": self.name,
            "content": f"Consent {event_type} - Type: {self.consent_type}, Status: {self.status}"
        }).insert(ignore_permissions=True)

    # Public Methods
    def give_consent(self, ip_address=None, user_agent=None, source=None, via="Web Form"):
        """Record that consent has been given."""
        self.is_given = 1
        self.given_at = now_datetime()
        self.given_via = via
        self.given_ip_address = ip_address
        self.given_user_agent = user_agent
        self.given_source = source

        if self.requires_double_opt_in():
            self.status = "Pending Verification"
        else:
            self.status = "Active"

        self.save()
        self.log_consent_event("given")

        return {
            "status": "success",
            "requires_verification": self.requires_double_opt_in(),
            "consent_status": self.status
        }

    def withdraw_consent(self, reason=None, via="Preferences Page", request_deletion=False):
        """Withdraw consent."""
        if self.status == "Withdrawn":
            frappe.throw(_("Consent has already been withdrawn"))

        self.is_withdrawn = 1
        self.withdrawn_at = now_datetime()
        self.withdrawn_via = via
        self.withdrawal_reason = reason
        self.data_deletion_requested = cint(request_deletion)
        self.status = "Withdrawn"
        self.is_given = 0

        # Capture IP
        try:
            if frappe.request:
                self.withdrawn_ip_address = frappe.request.remote_addr
        except Exception:
            pass

        self.save()
        self.log_consent_event("withdrawn")

        # Handle data deletion request
        if request_deletion:
            self.process_deletion_request()

        return {
            "status": "success",
            "message": _("Consent has been withdrawn"),
            "deletion_requested": request_deletion
        }

    def verify_consent(self, verification_token=None, verified_by=None):
        """Verify consent (complete double opt-in)."""
        if self.status != "Pending Verification":
            frappe.throw(_("Consent is not pending verification"))

        if self.verification_reference and verification_token:
            if self.verification_reference != verification_token:
                frappe.throw(_("Invalid verification token"))

        self.is_verified = 1
        self.verified_at = now_datetime()
        self.verified_by = verified_by or frappe.session.user
        self.double_opt_in_completed = 1
        self.status = "Active"

        self.save()
        self.log_consent_event("verified")

        return {
            "status": "success",
            "message": _("Consent verified successfully")
        }

    def renew_consent(self, new_expiry_date=None):
        """Renew an expired consent."""
        if self.status not in ["Expired", "Active"]:
            frappe.throw(_("Only expired or active consents can be renewed"))

        # Create amendment record
        old_name = self.name

        self.is_given = 1
        self.given_at = now_datetime()
        self.status = "Active"
        self.is_withdrawn = 0
        self.withdrawn_at = None

        if new_expiry_date:
            self.expiry_date = new_expiry_date
        elif self.has_expiry:
            # Extend by default period (1 year)
            self.expiry_date = add_days(nowdate(), 365)

        self.renewal_reminder_sent = 0

        self.save()
        self.log_consent_event("renewed")

        return {
            "status": "success",
            "message": _("Consent renewed successfully"),
            "new_expiry": self.expiry_date
        }

    def supersede(self, new_consent):
        """Mark this consent as superseded by a new consent."""
        self.status = "Superseded"
        self.save()

        # Link new consent to this one
        frappe.db.set_value(
            "Consent Record", new_consent,
            "amended_from", self.name
        )

        self.log_consent_event("superseded")

    def process_deletion_request(self):
        """Process a data deletion request associated with consent withdrawal."""
        # TODO: Implement data deletion workflow
        # This would typically:
        # 1. Create a data subject request record
        # 2. Notify data protection officer
        # 3. Queue deletion jobs for associated data
        pass

    def is_active(self):
        """Check if consent is currently active."""
        if self.status != "Active":
            return False

        if self.has_expiry and self.expiry_date:
            if getdate(self.expiry_date) < getdate(nowdate()):
                return False

        return self.is_given and not self.is_withdrawn

    def get_consent_summary(self):
        """Get a summary of the consent record."""
        return {
            "consent_type": self.consent_type,
            "status": self.status,
            "is_active": self.is_active(),
            "given_at": self.given_at,
            "given_via": self.given_via,
            "is_verified": self.is_verified,
            "has_expiry": self.has_expiry,
            "expiry_date": self.expiry_date,
            "is_withdrawn": self.is_withdrawn,
            "withdrawn_at": self.withdrawn_at
        }


# API Endpoints
@frappe.whitelist()
def get_user_consents(user=None, consent_type=None, active_only=True):
    """
    Get consent records for a user.

    Args:
        user: User to get consents for (defaults to current user)
        consent_type: Filter by consent type
        active_only: Only return active consents

    Returns:
        list: Consent records
    """
    user = user or frappe.session.user

    # Permission check
    if user != frappe.session.user and "System Manager" not in frappe.get_roles():
        frappe.throw(_("Not permitted to access consent records"))

    filters = {"user": user}

    if consent_type:
        filters["consent_type"] = consent_type

    if active_only:
        filters["status"] = "Active"

    consents = frappe.get_all(
        "Consent Record",
        filters=filters,
        fields=[
            "name", "consent_type", "purpose", "status", "is_given",
            "given_at", "given_via", "is_verified", "has_expiry",
            "expiry_date", "is_withdrawn", "withdrawn_at"
        ],
        order_by="consent_type asc"
    )

    return consents


@frappe.whitelist()
def record_consent(
    consent_type,
    purpose,
    purpose_description=None,
    legal_basis="Consent",
    data_categories=None,
    consent_version=None,
    consent_text=None,
    privacy_policy_version=None,
    third_party_name=None,
    third_party_country=None
):
    """
    Record a new consent from the current user.

    Args:
        consent_type: Type of consent
        purpose: Brief purpose description
        purpose_description: Detailed purpose
        legal_basis: Legal basis for processing
        data_categories: Categories of data
        consent_version: Version of consent form
        consent_text: Actual consent text shown
        privacy_policy_version: Privacy policy version
        third_party_name: Third party name if applicable
        third_party_country: Third party country if applicable

    Returns:
        dict: Result with consent record name
    """
    # Check if active consent already exists
    existing = frappe.db.get_value(
        "Consent Record",
        {
            "user": frappe.session.user,
            "consent_type": consent_type,
            "status": "Active"
        },
        "name"
    )

    if existing:
        frappe.throw(
            _("Active consent already exists for {0}. "
              "Please withdraw existing consent first.").format(consent_type)
        )

    # Capture request info
    ip_address = None
    user_agent = None
    try:
        if frappe.request:
            ip_address = frappe.request.remote_addr
            user_agent = str(frappe.request.user_agent)[:500]
    except Exception:
        pass

    # Determine if third party is involved
    involves_third_party = bool(third_party_name) or consent_type in [
        "Third Party Sharing", "International Transfer"
    ]

    consent = frappe.get_doc({
        "doctype": "Consent Record",
        "user": frappe.session.user,
        "consent_type": consent_type,
        "purpose": purpose,
        "purpose_description": purpose_description,
        "legal_basis": legal_basis,
        "data_categories": data_categories,
        "consent_version": consent_version,
        "consent_text": consent_text,
        "privacy_policy_version": privacy_policy_version,
        "is_given": 1,
        "given_at": now_datetime(),
        "given_via": "Web Form",
        "given_ip_address": ip_address,
        "given_user_agent": user_agent,
        "involves_third_party": cint(involves_third_party),
        "third_party_name": third_party_name,
        "third_party_country": third_party_country
    })

    consent.insert()

    return {
        "status": "success",
        "consent_name": consent.name,
        "consent_status": consent.status,
        "requires_verification": consent.status == "Pending Verification"
    }


@frappe.whitelist()
def withdraw_consent(consent_name, reason=None, request_deletion=False):
    """
    Withdraw a consent record.

    Args:
        consent_name: Name of the consent record
        reason: Reason for withdrawal
        request_deletion: Whether to request data deletion

    Returns:
        dict: Result of withdrawal
    """
    consent = frappe.get_doc("Consent Record", consent_name)

    # Permission check
    if consent.user != frappe.session.user and "System Manager" not in frappe.get_roles():
        frappe.throw(_("Not permitted to withdraw this consent"))

    result = consent.withdraw_consent(
        reason=reason,
        request_deletion=cint(request_deletion)
    )

    return result


@frappe.whitelist()
def verify_consent(consent_name, token=None):
    """
    Verify a consent record (complete double opt-in).

    Args:
        consent_name: Name of the consent record
        token: Verification token

    Returns:
        dict: Result of verification
    """
    consent = frappe.get_doc("Consent Record", consent_name)

    # Permission check - allow anyone with valid token to verify
    if consent.user != frappe.session.user:
        if not token or token != consent.verification_reference:
            frappe.throw(_("Invalid verification token"))

    result = consent.verify_consent(verification_token=token)

    return result


@frappe.whitelist()
def check_consent(consent_type, user=None):
    """
    Check if a user has active consent for a specific type.

    Args:
        consent_type: Type of consent to check
        user: User to check (defaults to current user)

    Returns:
        dict: Consent status
    """
    user = user or frappe.session.user

    consent = frappe.db.get_value(
        "Consent Record",
        {
            "user": user,
            "consent_type": consent_type,
            "status": "Active"
        },
        ["name", "given_at", "expiry_date", "is_verified"],
        as_dict=True
    )

    if not consent:
        return {
            "has_consent": False,
            "message": _("No active consent found for {0}").format(consent_type)
        }

    # Check expiry
    if consent.expiry_date and getdate(consent.expiry_date) < getdate(nowdate()):
        return {
            "has_consent": False,
            "message": _("Consent has expired"),
            "expired": True,
            "expired_on": consent.expiry_date
        }

    return {
        "has_consent": True,
        "consent_name": consent.name,
        "given_at": consent.given_at,
        "is_verified": consent.is_verified,
        "expiry_date": consent.expiry_date
    }


@frappe.whitelist()
def get_consent_statistics():
    """
    Get consent statistics for admin dashboard.

    Returns:
        dict: Consent statistics
    """
    if "System Manager" not in frappe.get_roles():
        frappe.throw(_("Not permitted to view consent statistics"))

    stats = {
        "total": frappe.db.count("Consent Record"),
        "active": frappe.db.count("Consent Record", {"status": "Active"}),
        "pending_verification": frappe.db.count("Consent Record", {"status": "Pending Verification"}),
        "withdrawn": frappe.db.count("Consent Record", {"status": "Withdrawn"}),
        "expired": frappe.db.count("Consent Record", {"status": "Expired"})
    }

    # Consent by type
    consent_types = frappe.db.sql("""
        SELECT consent_type, COUNT(*) as count
        FROM `tabConsent Record`
        WHERE status = 'Active'
        GROUP BY consent_type
        ORDER BY count DESC
    """, as_dict=True)

    stats["by_type"] = {ct["consent_type"]: ct["count"] for ct in consent_types}

    # Recent consent activity (last 30 days)
    from frappe.utils import add_days
    thirty_days_ago = add_days(nowdate(), -30)

    stats["recent_given"] = frappe.db.count(
        "Consent Record",
        {"given_at": (">=", thirty_days_ago)}
    )

    stats["recent_withdrawn"] = frappe.db.count(
        "Consent Record",
        {"withdrawn_at": (">=", thirty_days_ago)}
    )

    return stats


@frappe.whitelist()
def get_expiring_consents(days=30):
    """
    Get consents expiring within specified days.

    Args:
        days: Number of days to look ahead

    Returns:
        list: Expiring consent records
    """
    if "System Manager" not in frappe.get_roles():
        frappe.throw(_("Not permitted to view expiring consents"))

    expiry_threshold = add_days(nowdate(), cint(days))

    consents = frappe.get_all(
        "Consent Record",
        filters={
            "status": "Active",
            "has_expiry": 1,
            "expiry_date": ["<=", expiry_threshold]
        },
        fields=[
            "name", "user", "user_full_name", "consent_type", "purpose",
            "expiry_date", "auto_renew", "renewal_reminder_sent"
        ],
        order_by="expiry_date asc"
    )

    return consents


@frappe.whitelist()
def export_user_consents(user=None, format="json"):
    """
    Export all consent records for a user (KVKK data subject request).

    Args:
        user: User to export consents for
        format: Export format (json or csv)

    Returns:
        dict: Exported consent data
    """
    user = user or frappe.session.user

    # Permission check
    if user != frappe.session.user and "System Manager" not in frappe.get_roles():
        frappe.throw(_("Not permitted to export consent records"))

    consents = frappe.get_all(
        "Consent Record",
        filters={"user": user},
        fields=[
            "name", "consent_type", "purpose", "purpose_description",
            "legal_basis", "data_categories", "status", "is_given",
            "given_at", "given_via", "consent_version",
            "is_withdrawn", "withdrawn_at", "withdrawal_reason",
            "involves_third_party", "third_party_name", "third_party_country",
            "has_expiry", "expiry_date", "creation", "modified"
        ],
        order_by="creation desc"
    )

    export_data = {
        "user": user,
        "export_date": nowdate(),
        "total_records": len(consents),
        "consents": consents
    }

    if format == "csv":
        # Return as CSV string
        import csv
        import io

        output = io.StringIO()
        if consents:
            writer = csv.DictWriter(output, fieldnames=consents[0].keys())
            writer.writeheader()
            writer.writerows(consents)

        return {
            "format": "csv",
            "data": output.getvalue()
        }

    return {
        "format": "json",
        "data": export_data
    }

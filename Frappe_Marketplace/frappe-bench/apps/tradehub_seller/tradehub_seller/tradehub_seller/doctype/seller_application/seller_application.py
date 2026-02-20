# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt, getdate, nowdate, now_datetime, add_days


class SellerApplication(Document):
    """
    Seller Application DocType for handling seller onboarding workflow.

    Seller Applications represent requests from users to become sellers on the
    TR-TradeHub marketplace. Each application goes through a workflow:
    - Draft: Initial state, applicant fills out information
    - Submitted: Application submitted for review
    - Under Review: Application is being reviewed by staff
    - Documents Requested: Additional documents needed
    - Revision Required: Changes needed before approval
    - Approved: Application approved, Seller Profile created
    - Rejected: Application rejected with reason
    - Cancelled: Application cancelled by applicant or admin
    """

    def before_insert(self):
        """Set default values before inserting a new application."""
        # Set tenant from user context if not specified
        if not self.tenant:
            self.set_tenant_from_context()

        # Set contact email from user if not specified
        if not self.contact_email and self.applicant_user:
            self.contact_email = frappe.db.get_value("User", self.applicant_user, "email")

        # Initialize workflow state
        self.workflow_state = "Draft"
        self.status = "Draft"

        # Add creation history entry
        self.add_history_entry("Created", None, "Draft", "Application created")

    def validate(self):
        """Validate application data before saving."""
        self.validate_applicant_user()
        self.validate_tax_id()
        self.validate_iban()
        self.validate_mersis_number()
        self.validate_e_invoice_alias()
        self.validate_identity_document()
        self.validate_agreements()
        self.validate_status_transition()

    def on_update(self):
        """Actions to perform after application is updated."""
        pass

    def after_insert(self):
        """Actions to perform after application is inserted."""
        pass

    def on_trash(self):
        """Prevent deletion of application in certain states."""
        if self.status in ["Submitted", "Under Review", "Approved"]:
            frappe.throw(
                _("Cannot delete application in '{0}' status. "
                  "Please cancel the application first.").format(self.status)
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

    def validate_applicant_user(self):
        """Validate applicant user link."""
        if not self.applicant_user:
            frappe.throw(_("Applicant User is required"))

        if not frappe.db.exists("User", self.applicant_user):
            frappe.throw(_("User {0} does not exist").format(self.applicant_user))

        # Check if user already has a seller profile
        existing_profile = frappe.db.exists("Seller Profile", {"user": self.applicant_user})
        if existing_profile:
            frappe.throw(_("User {0} already has a Seller Profile").format(self.applicant_user))

        # Check if user already has a pending/approved application (only for new records)
        if self.is_new():
            existing_app = frappe.db.exists("Seller Application", {
                "applicant_user": self.applicant_user,
                "status": ["in", ["Draft", "Submitted", "Under Review", "Documents Requested", "Revision Required", "Approved"]]
            })
            if existing_app:
                frappe.throw(
                    _("User {0} already has an active application ({1}). "
                      "Please wait for the existing application to be processed.").format(
                        self.applicant_user, existing_app
                    )
                )

    def validate_tax_id(self):
        """
        Validate Turkish Tax ID (VKN or TCKN) format and checksum.
        - VKN: 10 digits for companies
        - TCKN: 11 digits for individuals
        """
        if not self.tax_id:
            return

        tax_id = self.tax_id.strip()
        if not tax_id.isdigit():
            frappe.throw(_("Tax ID must contain only digits"))

        if self.tax_id_type == "VKN":
            if len(tax_id) != 10:
                frappe.throw(_("VKN (Company Tax ID) must be exactly 10 digits"))
            if not self.validate_vkn_checksum(tax_id):
                frappe.throw(_("Invalid VKN. Checksum validation failed."))
        elif self.tax_id_type == "TCKN":
            if len(tax_id) != 11:
                frappe.throw(_("TCKN (Individual Tax ID) must be exactly 11 digits"))
            if not self.validate_tckn_checksum(tax_id):
                frappe.throw(_("Invalid TCKN. Checksum validation failed."))

    def validate_vkn_checksum(self, vkn):
        """
        Validate Turkish VKN (Vergi Kimlik Numarasi) checksum.
        Algorithm: Each digit is processed with specific rules.
        """
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

    def validate_tckn_checksum(self, tckn):
        """
        Validate Turkish TCKN (T.C. Kimlik Numarasi) checksum.
        Algorithm: Uses specific formula for 10th and 11th digits.
        """
        if len(tckn) != 11:
            return False

        try:
            digits = [int(d) for d in tckn]

            # First digit cannot be 0
            if digits[0] == 0:
                return False

            # Calculate 10th digit
            odd_sum = digits[0] + digits[2] + digits[4] + digits[6] + digits[8]
            even_sum = digits[1] + digits[3] + digits[5] + digits[7]
            digit_10 = ((odd_sum * 7) - even_sum) % 10
            if digit_10 < 0:
                digit_10 += 10

            if digits[9] != digit_10:
                return False

            # Calculate 11th digit
            total = sum(digits[:10])
            digit_11 = total % 10

            return digits[10] == digit_11
        except (ValueError, IndexError):
            return False

    def validate_iban(self):
        """
        Validate Turkish IBAN format.
        Turkish IBAN: TR + 2 check digits + 5 digit bank code + 16 digit account number = 26 chars
        """
        if not self.iban:
            return

        iban = self.iban.strip().upper().replace(" ", "")

        # Basic format check
        if len(iban) != 26:
            frappe.throw(_("Turkish IBAN must be exactly 26 characters"))

        if not iban.startswith("TR"):
            frappe.throw(_("Turkish IBAN must start with 'TR'"))

        # Check that rest is alphanumeric
        if not iban[2:].isalnum():
            frappe.throw(_("IBAN contains invalid characters"))

        # IBAN checksum validation
        if not self.validate_iban_checksum(iban):
            frappe.throw(_("Invalid IBAN. Checksum validation failed."))

        self.iban = iban

    def validate_iban_checksum(self, iban):
        """
        Validate IBAN using MOD-97 algorithm.
        """
        # Move first 4 characters to end
        rearranged = iban[4:] + iban[:4]

        # Convert letters to numbers (A=10, B=11, ..., Z=35)
        numeric = ""
        for char in rearranged:
            if char.isalpha():
                numeric += str(ord(char) - ord("A") + 10)
            else:
                numeric += char

        # Check if remainder is 1
        return int(numeric) % 97 == 1

    def validate_mersis_number(self):
        """Validate MERSIS number format (16 digits)."""
        if not self.mersis_number:
            return

        mersis = self.mersis_number.strip()
        if not mersis.isdigit():
            frappe.throw(_("MERSIS Number must contain only digits"))
        if len(mersis) != 16:
            frappe.throw(_("MERSIS Number must be exactly 16 digits"))

    def validate_e_invoice_alias(self):
        """Validate E-Invoice alias format."""
        if self.e_invoice_registered and self.e_invoice_alias:
            alias = self.e_invoice_alias.strip().upper()
            if not (alias.startswith("PK:") or alias.startswith("GB:")):
                frappe.throw(_("E-Invoice Alias must start with 'PK:' or 'GB:'"))
            self.e_invoice_alias = alias

    def validate_identity_document(self):
        """Validate identity document fields."""
        if self.identity_document_expiry:
            if getdate(self.identity_document_expiry) < getdate(nowdate()):
                frappe.throw(_("Identity document has expired. Please provide a valid document."))

    def validate_agreements(self):
        """Validate that all required agreements are accepted for submission."""
        if self.status in ["Submitted", "Under Review"]:
            required_agreements = [
                ("terms_accepted", "Terms & Conditions"),
                ("privacy_accepted", "Privacy Policy"),
                ("kvkk_accepted", "KVKK Consent"),
                ("commission_accepted", "Commission Terms"),
                ("return_policy_accepted", "Return Policy")
            ]

            for field, label in required_agreements:
                if not cint(getattr(self, field, 0)):
                    frappe.throw(_("You must accept the {0} to submit the application").format(label))

    def validate_status_transition(self):
        """Validate that status transitions are valid."""
        if self.is_new():
            return

        old_status = self.get_doc_before_save()
        if not old_status:
            return

        old_status = old_status.status

        valid_transitions = {
            "Draft": ["Submitted", "Cancelled"],
            "Submitted": ["Under Review", "Cancelled"],
            "Under Review": ["Documents Requested", "Revision Required", "Approved", "Rejected"],
            "Documents Requested": ["Under Review", "Cancelled"],
            "Revision Required": ["Submitted", "Cancelled"],
            "Approved": [],
            "Rejected": [],
            "Cancelled": []
        }

        if old_status != self.status:
            if self.status not in valid_transitions.get(old_status, []):
                frappe.throw(
                    _("Invalid status transition from '{0}' to '{1}'").format(
                        old_status, self.status
                    )
                )

    def add_history_entry(self, action, from_status=None, to_status=None, notes=None):
        """Add a history entry to track status changes."""
        self.append("application_history", {
            "action": action,
            "from_status": from_status,
            "to_status": to_status or self.status,
            "action_by": frappe.session.user,
            "action_at": now_datetime(),
            "notes": notes
        })

    # Workflow Methods
    def submit_application(self):
        """Submit the application for review."""
        if self.status != "Draft" and self.status != "Revision Required":
            frappe.throw(_("Application can only be submitted from Draft or Revision Required status"))

        # Validate all required fields
        self.validate()

        old_status = self.status
        self.status = "Submitted"
        self.workflow_state = "Pending Review"
        self.submitted_at = now_datetime()
        self.submitted_by = frappe.session.user
        self.acceptance_date = now_datetime()

        self.add_history_entry(
            "Resubmitted" if old_status == "Revision Required" else "Submitted",
            old_status,
            "Submitted",
            "Application submitted for review"
        )
        self.save()

        # Send notification to admins
        self.notify_reviewers()

        return True

    def assign_reviewer(self, reviewer_user):
        """Assign a reviewer to the application."""
        if self.status not in ["Submitted", "Under Review"]:
            frappe.throw(_("Can only assign reviewer when application is Submitted or Under Review"))

        old_assigned = self.assigned_to
        self.assigned_to = reviewer_user

        self.add_history_entry(
            "Assigned",
            None,
            None,
            f"Assigned to {reviewer_user}" + (f" (was {old_assigned})" if old_assigned else "")
        )
        self.save()

        # Notify the assigned reviewer
        self.notify_reviewer_assigned(reviewer_user)

    def start_review(self):
        """Start the review process."""
        if self.status != "Submitted":
            frappe.throw(_("Can only start review when application is Submitted"))

        self.status = "Under Review"
        self.workflow_state = "In Review"
        self.review_status = "In Progress"
        self.review_started_at = now_datetime()

        if not self.assigned_to:
            self.assigned_to = frappe.session.user

        # Set review deadline (default 3 business days)
        self.review_deadline = add_days(nowdate(), 3)

        self.add_history_entry(
            "Review Started",
            "Submitted",
            "Under Review",
            f"Review started by {frappe.session.user}"
        )
        self.save()

    def request_documents(self, notes=None):
        """Request additional documents from the applicant."""
        if self.status != "Under Review":
            frappe.throw(_("Can only request documents when application is Under Review"))

        self.status = "Documents Requested"
        self.workflow_state = "Documents Requested"
        self.review_status = "Pending Documents"
        self.revision_notes = notes

        self.add_history_entry(
            "Documents Requested",
            "Under Review",
            "Documents Requested",
            notes
        )
        self.save()

        # Notify the applicant
        self.notify_applicant("documents_requested", notes)

    def request_revision(self, notes):
        """Request revision/changes from the applicant."""
        if self.status != "Under Review":
            frappe.throw(_("Can only request revision when application is Under Review"))

        if not notes:
            frappe.throw(_("Revision notes are required"))

        self.status = "Revision Required"
        self.workflow_state = "Revision Required"
        self.review_status = "Pending Verification"
        self.revision_requested = 1
        self.revision_notes = notes

        self.add_history_entry(
            "Revision Requested",
            "Under Review",
            "Revision Required",
            notes
        )
        self.save()

        # Notify the applicant
        self.notify_applicant("revision_required", notes)

    def approve(self, commission_plan=None, initial_tier=None):
        """Approve the application and create Seller Profile."""
        if self.status != "Under Review":
            frappe.throw(_("Can only approve application that is Under Review"))

        self.status = "Approved"
        self.workflow_state = "Approved"
        self.review_status = "Completed"
        self.approved_at = now_datetime()
        self.approved_by = frappe.session.user
        self.reviewed_at = now_datetime()
        self.reviewed_by = frappe.session.user

        if commission_plan:
            self.commission_plan = commission_plan
        if initial_tier:
            self.initial_tier = initial_tier

        self.add_history_entry(
            "Approved",
            "Under Review",
            "Approved",
            f"Application approved by {frappe.session.user}"
        )

        # Create Seller Profile
        seller_profile = self.create_seller_profile()
        self.seller_profile = seller_profile.name

        self.save()

        # Send welcome email
        self.send_welcome_email()

        return seller_profile

    def reject(self, reason, notes=None):
        """Reject the application."""
        if self.status != "Under Review":
            frappe.throw(_("Can only reject application that is Under Review"))

        if not reason:
            frappe.throw(_("Rejection reason is required"))

        self.status = "Rejected"
        self.workflow_state = "Rejected"
        self.review_status = "Completed"
        self.rejection_reason = reason
        self.reviewed_at = now_datetime()
        self.reviewed_by = frappe.session.user

        if notes:
            self.review_notes = notes

        self.add_history_entry(
            "Rejected",
            "Under Review",
            "Rejected",
            f"Reason: {reason}" + (f"\nNotes: {notes}" if notes else "")
        )
        self.save()

        # Notify the applicant
        self.notify_applicant("rejected", reason)

    def cancel(self, reason=None):
        """Cancel the application."""
        if self.status in ["Approved", "Rejected", "Cancelled"]:
            frappe.throw(_("Application in '{0}' status cannot be cancelled").format(self.status))

        old_status = self.status
        self.status = "Cancelled"
        self.workflow_state = "Cancelled"

        self.add_history_entry(
            "Cancelled",
            old_status,
            "Cancelled",
            reason
        )
        self.save()

    def create_seller_profile(self):
        """Create Seller Profile from approved application."""
        seller_profile = frappe.get_doc({
            "doctype": "Seller Profile",
            "seller_name": self.business_name,
            "user": self.applicant_user,
            "seller_type": self.seller_type,
            "tenant": self.tenant,
            "status": "Active",
            "verification_status": "Verified",
            "verified_at": now_datetime(),
            "verified_by": frappe.session.user,
            "identity_verified": 1,
            "contact_email": self.contact_email,
            "contact_phone": self.contact_phone,
            "mobile": self.mobile,
            "whatsapp": self.whatsapp,
            "website": self.website,
            "address_line_1": self.address_line_1,
            "address_line_2": self.address_line_2,
            "city": self.city,
            "state": self.state,
            "country": self.country,
            "postal_code": self.postal_code,
            "tax_id": self.tax_id,
            "tax_id_type": self.tax_id_type,
            "tax_office": self.tax_office,
            "trade_registry_number": self.trade_registry_number,
            "mersis_number": self.mersis_number,
            "e_invoice_registered": self.e_invoice_registered,
            "e_invoice_alias": self.e_invoice_alias,
            "bank_name": self.bank_name,
            "bank_branch": self.bank_branch,
            "iban": self.iban,
            "account_holder_name": self.account_holder_name,
            "swift_code": self.swift_code,
            "commission_plan": self.commission_plan,
            "seller_tier": self.initial_tier,
            "can_sell": 1,
            "can_withdraw": 1,
            "can_create_listings": 1
        })

        seller_profile.flags.ignore_permissions = True
        seller_profile.insert()

        frappe.msgprint(_("Seller Profile {0} created successfully").format(seller_profile.name))

        return seller_profile

    # Notification Methods
    def notify_reviewers(self):
        """Notify reviewers about new application."""
        # Placeholder for notification system integration
        pass

    def notify_reviewer_assigned(self, reviewer_user):
        """Notify reviewer about assignment."""
        # Placeholder for notification system integration
        pass

    def notify_applicant(self, notification_type, message=None):
        """Send notification to applicant."""
        # Placeholder for notification system integration
        pass

    def send_welcome_email(self):
        """Send welcome email to approved seller."""
        try:
            # Placeholder for email sending
            self.db_set("welcome_email_sent", 1)
        except Exception as e:
            frappe.log_error(f"Failed to send welcome email for {self.name}: {str(e)}")


# API Endpoints
@frappe.whitelist()
def submit_application(application_name):
    """
    Submit a seller application for review.

    Args:
        application_name: Name of the seller application

    Returns:
        dict: Result of submission
    """
    application = frappe.get_doc("Seller Application", application_name)

    # Check permissions
    if application.applicant_user != frappe.session.user and not frappe.has_permission("Seller Application", "write"):
        frappe.throw(_("Not permitted to submit this application"))

    application.submit_application()

    return {
        "status": "success",
        "message": _("Application submitted successfully"),
        "application_status": application.status
    }


@frappe.whitelist()
def assign_reviewer(application_name, reviewer_user):
    """
    Assign a reviewer to a seller application.

    Args:
        application_name: Name of the seller application
        reviewer_user: User to assign as reviewer

    Returns:
        dict: Result of assignment
    """
    if not frappe.has_permission("Seller Application", "write"):
        frappe.throw(_("Not permitted to assign reviewers"))

    application = frappe.get_doc("Seller Application", application_name)
    application.assign_reviewer(reviewer_user)

    return {
        "status": "success",
        "message": _("Reviewer assigned successfully"),
        "assigned_to": application.assigned_to
    }


@frappe.whitelist()
def start_review(application_name):
    """
    Start the review process for a seller application.

    Args:
        application_name: Name of the seller application

    Returns:
        dict: Result of starting review
    """
    if not frappe.has_permission("Seller Application", "write"):
        frappe.throw(_("Not permitted to review applications"))

    application = frappe.get_doc("Seller Application", application_name)
    application.start_review()

    return {
        "status": "success",
        "message": _("Review started"),
        "application_status": application.status
    }


@frappe.whitelist()
def request_documents(application_name, notes=None):
    """
    Request additional documents from applicant.

    Args:
        application_name: Name of the seller application
        notes: Notes about what documents are needed

    Returns:
        dict: Result of request
    """
    if not frappe.has_permission("Seller Application", "write"):
        frappe.throw(_("Not permitted to request documents"))

    application = frappe.get_doc("Seller Application", application_name)
    application.request_documents(notes)

    return {
        "status": "success",
        "message": _("Document request sent"),
        "application_status": application.status
    }


@frappe.whitelist()
def request_revision(application_name, notes):
    """
    Request revision from applicant.

    Args:
        application_name: Name of the seller application
        notes: Notes about what needs to be revised

    Returns:
        dict: Result of request
    """
    if not frappe.has_permission("Seller Application", "write"):
        frappe.throw(_("Not permitted to request revision"))

    application = frappe.get_doc("Seller Application", application_name)
    application.request_revision(notes)

    return {
        "status": "success",
        "message": _("Revision request sent"),
        "application_status": application.status
    }


@frappe.whitelist()
def approve_application(application_name, commission_plan=None, initial_tier=None):
    """
    Approve a seller application.

    Args:
        application_name: Name of the seller application
        commission_plan: Commission plan to assign
        initial_tier: Initial seller tier

    Returns:
        dict: Result of approval with created seller profile
    """
    if not frappe.has_permission("Seller Application", "write"):
        frappe.throw(_("Not permitted to approve applications"))

    application = frappe.get_doc("Seller Application", application_name)
    seller_profile = application.approve(commission_plan, initial_tier)

    return {
        "status": "success",
        "message": _("Application approved successfully"),
        "seller_profile": seller_profile.name,
        "seller_profile_url": frappe.utils.get_url_to_form("Seller Profile", seller_profile.name)
    }


@frappe.whitelist()
def reject_application(application_name, reason, notes=None):
    """
    Reject a seller application.

    Args:
        application_name: Name of the seller application
        reason: Rejection reason
        notes: Additional notes

    Returns:
        dict: Result of rejection
    """
    if not frappe.has_permission("Seller Application", "write"):
        frappe.throw(_("Not permitted to reject applications"))

    application = frappe.get_doc("Seller Application", application_name)
    application.reject(reason, notes)

    return {
        "status": "success",
        "message": _("Application rejected"),
        "application_status": application.status
    }


@frappe.whitelist()
def cancel_application(application_name, reason=None):
    """
    Cancel a seller application.

    Args:
        application_name: Name of the seller application
        reason: Cancellation reason

    Returns:
        dict: Result of cancellation
    """
    application = frappe.get_doc("Seller Application", application_name)

    # Check permissions
    if application.applicant_user != frappe.session.user and not frappe.has_permission("Seller Application", "write"):
        frappe.throw(_("Not permitted to cancel this application"))

    application.cancel(reason)

    return {
        "status": "success",
        "message": _("Application cancelled"),
        "application_status": application.status
    }


@frappe.whitelist()
def get_application_status(application_name=None, user=None):
    """
    Get the status of a seller application.

    Args:
        application_name: Name of the seller application
        user: User to check (defaults to current user)

    Returns:
        dict: Application status details
    """
    if not application_name and not user:
        user = frappe.session.user

    if user and not application_name:
        application_name = frappe.db.get_value(
            "Seller Application",
            {"applicant_user": user, "status": ["not in", ["Cancelled", "Rejected"]]},
            "name"
        )

    if not application_name:
        return {"has_application": False}

    application = frappe.get_doc("Seller Application", application_name)

    # Check permissions
    if application.applicant_user != frappe.session.user and not frappe.has_permission("Seller Application", "read"):
        frappe.throw(_("Not permitted to view this application"))

    return {
        "has_application": True,
        "name": application.name,
        "business_name": application.business_name,
        "status": application.status,
        "workflow_state": application.workflow_state,
        "submitted_at": application.submitted_at,
        "assigned_to": application.assigned_to,
        "review_deadline": application.review_deadline,
        "revision_requested": application.revision_requested,
        "revision_notes": application.revision_notes,
        "rejection_reason": application.rejection_reason,
        "seller_profile": application.seller_profile
    }


@frappe.whitelist()
def get_pending_applications(status=None, assigned_to=None, priority=None):
    """
    Get list of pending seller applications for reviewers.

    Args:
        status: Filter by status
        assigned_to: Filter by assigned reviewer
        priority: Filter by priority

    Returns:
        list: List of pending applications
    """
    if not frappe.has_permission("Seller Application", "read"):
        frappe.throw(_("Not permitted to view applications"))

    filters = {}

    if status:
        filters["status"] = status
    else:
        filters["status"] = ["in", ["Submitted", "Under Review", "Documents Requested"]]

    if assigned_to:
        filters["assigned_to"] = assigned_to

    if priority:
        filters["priority"] = priority

    applications = frappe.get_all(
        "Seller Application",
        filters=filters,
        fields=[
            "name", "business_name", "applicant_user", "seller_type",
            "status", "priority", "submitted_at", "assigned_to",
            "review_deadline", "city", "country"
        ],
        order_by="priority desc, submitted_at asc"
    )

    return applications


@frappe.whitelist()
def get_application_statistics():
    """
    Get statistics about seller applications.

    Returns:
        dict: Application statistics
    """
    if not frappe.has_permission("Seller Application", "read"):
        frappe.throw(_("Not permitted to view application statistics"))

    # Get counts by status
    status_counts = frappe.db.sql("""
        SELECT status, COUNT(*) as count
        FROM `tabSeller Application`
        GROUP BY status
    """, as_dict=True)

    # Get counts by priority for pending applications
    priority_counts = frappe.db.sql("""
        SELECT priority, COUNT(*) as count
        FROM `tabSeller Application`
        WHERE status IN ('Submitted', 'Under Review', 'Documents Requested')
        GROUP BY priority
    """, as_dict=True)

    # Get average review time for approved applications
    avg_review_time = frappe.db.sql("""
        SELECT AVG(TIMESTAMPDIFF(HOUR, submitted_at, approved_at)) as avg_hours
        FROM `tabSeller Application`
        WHERE status = 'Approved'
        AND submitted_at IS NOT NULL
        AND approved_at IS NOT NULL
    """, as_dict=True)

    # Get overdue reviews
    overdue_count = frappe.db.count("Seller Application", {
        "status": "Under Review",
        "review_deadline": ["<", nowdate()]
    })

    return {
        "by_status": {s.status: s.count for s in status_counts},
        "by_priority": {p.priority: p.count for p in priority_counts},
        "average_review_hours": avg_review_time[0].avg_hours if avg_review_time else None,
        "overdue_reviews": overdue_count,
        "total_pending": sum(
            s.count for s in status_counts
            if s.status in ["Submitted", "Under Review", "Documents Requested"]
        )
    }


@frappe.whitelist()
def validate_tax_id(tax_id, tax_id_type="TCKN"):
    """
    Validate a Turkish tax ID (VKN or TCKN).

    Args:
        tax_id: Tax ID to validate
        tax_id_type: Type of tax ID (VKN or TCKN)

    Returns:
        dict: Validation result
    """
    application = SellerApplication({"tax_id": tax_id, "tax_id_type": tax_id_type})

    if tax_id_type == "VKN":
        is_valid = application.validate_vkn_checksum(tax_id)
        expected_length = 10
    else:
        is_valid = application.validate_tckn_checksum(tax_id)
        expected_length = 11

    return {
        "is_valid": is_valid,
        "tax_id_type": tax_id_type,
        "expected_length": expected_length,
        "actual_length": len(tax_id) if tax_id else 0
    }


@frappe.whitelist()
def validate_iban(iban):
    """
    Validate a Turkish IBAN.

    Args:
        iban: IBAN to validate

    Returns:
        dict: Validation result
    """
    application = SellerApplication({})

    iban_cleaned = iban.strip().upper().replace(" ", "") if iban else ""

    # Basic checks
    if len(iban_cleaned) != 26:
        return {"is_valid": False, "error": "Turkish IBAN must be 26 characters"}

    if not iban_cleaned.startswith("TR"):
        return {"is_valid": False, "error": "Turkish IBAN must start with 'TR'"}

    is_valid = application.validate_iban_checksum(iban_cleaned)

    return {
        "is_valid": is_valid,
        "iban_formatted": f"{iban_cleaned[:4]} {iban_cleaned[4:8]} {iban_cleaned[8:12]} {iban_cleaned[12:16]} {iban_cleaned[16:20]} {iban_cleaned[20:24]} {iban_cleaned[24:]}"
    }

# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, getdate, nowdate, now_datetime, get_datetime, add_days


class AccountAction(Document):
    """
    Account Action DocType for managing warnings, restrictions, and bans.

    This DocType tracks and enforces account-level actions taken against users,
    sellers, or organizations for policy violations, fraud, or other issues.

    Features:
    - Multiple action types (warning, restriction, suspension, ban, etc.)
    - Target different account types (User, Seller Profile, Organization)
    - Duration management with auto-lift capability
    - Specific restriction controls (selling, buying, messaging, etc.)
    - Escalation tracking for repeat offenders
    - Appeal workflow
    - Evidence and audit trail
    - Notification management
    """

    def before_insert(self):
        """Set default values before inserting a new action."""
        if not self.created_by_user:
            self.created_by_user = frappe.session.user

        if not self.creation_date:
            self.creation_date = now_datetime()

        if not self.start_date:
            self.start_date = now_datetime()

        # Set tenant from context if not specified
        if not self.tenant:
            self.set_tenant_from_context()

        # Calculate escalation level
        self.calculate_escalation_level()

        # Set violation count
        self.calculate_violation_count()

    def validate(self):
        """Validate action data before saving."""
        self.validate_target()
        self.validate_dates()
        self.validate_action_type()
        self.validate_restrictions()
        self.validate_status_transitions()
        self.validate_appeal()

    def on_submit(self):
        """Actions to perform when action is submitted/activated."""
        self.apply_action_to_target()
        self.send_notification()
        self.log_action_event("activated")

    def on_update(self):
        """Actions to perform after action is updated."""
        self.check_expiry()
        self.clear_action_cache()

    def after_insert(self):
        """Actions to perform after action is created."""
        self.log_action_event("created")

    def on_trash(self):
        """Prevent deletion of account actions - they must be preserved for audit."""
        frappe.throw(
            _("Account actions cannot be deleted for audit purposes. "
              "Mark as cancelled or lifted instead.")
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

    def calculate_escalation_level(self):
        """Calculate escalation level based on previous actions."""
        if self.previous_action:
            prev_level = frappe.db.get_value(
                "Account Action",
                self.previous_action,
                "escalation_level"
            )
            self.escalation_level = (prev_level or 1) + 1
        elif not self.escalation_level:
            self.escalation_level = 1

    def calculate_violation_count(self):
        """Calculate total violation count for this target."""
        if not self.violation_count or self.violation_count == 1:
            filters = {"status": ["not in", ["Cancelled", "Overturned"]]}

            if self.target_type == "User" and self.user:
                filters["user"] = self.user
            elif self.target_type == "Seller Profile" and self.seller_profile:
                filters["seller_profile"] = self.seller_profile
            elif self.target_type == "Organization" and self.organization:
                filters["organization"] = self.organization
            else:
                return

            if self.reason_code:
                filters["reason_code"] = self.reason_code

            count = frappe.db.count("Account Action", filters)
            self.violation_count = count + 1

    def validate_target(self):
        """Validate target account exists and is consistent."""
        if self.target_type == "User":
            if not self.user:
                frappe.throw(_("User is required when target type is User"))
            if not frappe.db.exists("User", self.user):
                frappe.throw(_("User {0} does not exist").format(self.user))
            # Clear other targets
            self.seller_profile = None
            self.organization = None

        elif self.target_type == "Seller Profile":
            if not self.seller_profile:
                frappe.throw(_("Seller Profile is required when target type is Seller Profile"))
            # Clear other targets
            self.user = None
            self.organization = None

        elif self.target_type == "Organization":
            if not self.organization:
                frappe.throw(_("Organization is required when target type is Organization"))
            # Clear other targets
            self.user = None
            self.seller_profile = None

    def validate_dates(self):
        """Validate start and end dates."""
        if self.is_permanent:
            self.end_date = None
        elif self.action_type not in ["Warning"]:
            if not self.end_date:
                frappe.throw(
                    _("End date is required for non-permanent {0}").format(self.action_type)
                )

        if self.end_date and self.start_date:
            if get_datetime(self.end_date) <= get_datetime(self.start_date):
                frappe.throw(_("End date must be after start date"))

    def validate_action_type(self):
        """Validate action type and set appropriate defaults."""
        # Permanent ban must be permanent
        if self.action_type == "Permanent Ban":
            self.is_permanent = 1
            self.auto_lift = 0
            self.end_date = None

        # Account termination is always permanent
        if self.action_type == "Account Termination":
            self.is_permanent = 1
            self.auto_lift = 0
            self.end_date = None
            self.is_appealable = 0

        # Warnings typically don't need end date
        if self.action_type == "Warning":
            if not self.end_date:
                # Default warning to 90 days
                self.end_date = add_days(nowdate(), 90)

        # Set restrictions based on action type
        if self.action_type in ["Temporary Ban", "Permanent Ban", "Account Termination"]:
            self.restrict_all_activity = 1

    def validate_restrictions(self):
        """Validate restriction settings."""
        # If all activity is restricted, set individual restrictions
        if self.restrict_all_activity:
            self.restrict_selling = 1
            self.restrict_buying = 1
            self.restrict_messaging = 1
            self.restrict_reviews = 1
            self.restrict_listing_create = 1
            self.restrict_withdrawal = 1

    def validate_status_transitions(self):
        """Validate that status transitions are valid."""
        if self.is_new():
            return

        old_status = frappe.db.get_value("Account Action", self.name, "status")

        valid_transitions = {
            "Draft": ["Pending Approval", "Active", "Cancelled"],
            "Pending Approval": ["Active", "Cancelled"],
            "Active": ["Expired", "Lifted", "Appealed", "Escalated"],
            "Appealed": ["Active", "Lifted", "Overturned"],
            "Expired": ["Lifted"],  # Can be lifted for cleanup
            "Lifted": [],  # Final state
            "Overturned": [],  # Final state
            "Escalated": ["Active", "Lifted"],
            "Cancelled": []  # Final state
        }

        if old_status and old_status != self.status:
            allowed = valid_transitions.get(old_status, [])
            if self.status not in allowed:
                frappe.throw(
                    _("Invalid status transition from {0} to {1}").format(
                        old_status, self.status
                    )
                )

    def validate_appeal(self):
        """Validate appeal-related fields."""
        if not self.is_appealable:
            # Clear appeal fields if not appealable
            self.appeal_status = ""
            self.appeal_reason = None
            self.appeal_evidence = None
            return

        if self.appeal_status in ["Approved", "Partially Approved"]:
            if not self.appeal_decision:
                frappe.throw(_("Appeal decision is required when appeal is approved"))

        # Auto-set appeal decided timestamp
        if self.appeal_status in ["Approved", "Rejected", "Partially Approved"]:
            if not self.appeal_decided_at:
                self.appeal_decided_at = now_datetime()
            if not self.appeal_decided_by:
                self.appeal_decided_by = frappe.session.user

    def check_expiry(self):
        """Check if action has expired and update status."""
        if self.status == "Active" and not self.is_permanent:
            if self.end_date and get_datetime(self.end_date) < get_datetime(now_datetime()):
                if self.auto_lift:
                    self.lift_action(reason="Automatic expiry", auto=True)
                else:
                    self.status = "Expired"
                    self.save(ignore_permissions=True)

    def apply_action_to_target(self):
        """Apply the action to the target account."""
        if self.status != "Active":
            return

        try:
            if self.target_type == "User" and self.user:
                self.apply_action_to_user()
            elif self.target_type == "Seller Profile" and self.seller_profile:
                self.apply_action_to_seller()
            elif self.target_type == "Organization" and self.organization:
                self.apply_action_to_organization()
        except Exception as e:
            frappe.log_error(
                f"Error applying account action {self.name}: {str(e)}",
                "Account Action Apply Error"
            )

    def apply_action_to_user(self):
        """Apply restrictions to a user account."""
        if self.action_type in ["Temporary Ban", "Permanent Ban", "Account Termination"]:
            # Disable user account
            frappe.db.set_value("User", self.user, "enabled", 0)

    def apply_action_to_seller(self):
        """Apply restrictions to a seller profile."""
        if not frappe.db.exists("Seller Profile", self.seller_profile):
            return

        updates = {}

        if self.action_type in ["Temporary Ban", "Permanent Ban", "Account Termination"]:
            updates["status"] = "Banned"
        elif self.action_type == "Suspension":
            updates["status"] = "Suspended"
        elif self.action_type == "Restriction":
            updates["status"] = "Restricted"

        if self.restrict_selling:
            updates["can_sell"] = 0
        if self.restrict_listing_create:
            updates["can_create_listings"] = 0
        if self.restrict_withdrawal:
            updates["can_withdraw"] = 0

        if updates:
            for field, value in updates.items():
                if frappe.db.has_column("Seller Profile", field):
                    frappe.db.set_value("Seller Profile", self.seller_profile, field, value)

    def apply_action_to_organization(self):
        """Apply restrictions to an organization."""
        if not frappe.db.exists("Organization", self.organization):
            return

        if self.action_type in ["Temporary Ban", "Permanent Ban", "Account Termination"]:
            frappe.db.set_value("Organization", self.organization, "status", "Banned")
        elif self.action_type == "Suspension":
            frappe.db.set_value("Organization", self.organization, "status", "Suspended")

    def remove_action_from_target(self):
        """Remove restrictions from target when action is lifted."""
        try:
            if self.target_type == "User" and self.user:
                self.remove_action_from_user()
            elif self.target_type == "Seller Profile" and self.seller_profile:
                self.remove_action_from_seller()
            elif self.target_type == "Organization" and self.organization:
                self.remove_action_from_organization()
        except Exception as e:
            frappe.log_error(
                f"Error removing account action {self.name}: {str(e)}",
                "Account Action Remove Error"
            )

    def remove_action_from_user(self):
        """Remove restrictions from user account."""
        # Check if there are other active actions
        other_active = frappe.db.count(
            "Account Action",
            {
                "user": self.user,
                "status": "Active",
                "name": ["!=", self.name]
            }
        )

        if other_active == 0:
            # Re-enable user if no other active actions
            frappe.db.set_value("User", self.user, "enabled", 1)

    def remove_action_from_seller(self):
        """Remove restrictions from seller profile."""
        if not frappe.db.exists("Seller Profile", self.seller_profile):
            return

        # Check if there are other active actions
        other_active = frappe.db.count(
            "Account Action",
            {
                "seller_profile": self.seller_profile,
                "status": "Active",
                "name": ["!=", self.name]
            }
        )

        if other_active == 0:
            updates = {"status": "Active"}
            if frappe.db.has_column("Seller Profile", "can_sell"):
                updates["can_sell"] = 1
            if frappe.db.has_column("Seller Profile", "can_create_listings"):
                updates["can_create_listings"] = 1
            if frappe.db.has_column("Seller Profile", "can_withdraw"):
                updates["can_withdraw"] = 1

            for field, value in updates.items():
                frappe.db.set_value("Seller Profile", self.seller_profile, field, value)

    def remove_action_from_organization(self):
        """Remove restrictions from organization."""
        if not frappe.db.exists("Organization", self.organization):
            return

        # Check if there are other active actions
        other_active = frappe.db.count(
            "Account Action",
            {
                "organization": self.organization,
                "status": "Active",
                "name": ["!=", self.name]
            }
        )

        if other_active == 0:
            frappe.db.set_value("Organization", self.organization, "status", "Active")

    def send_notification(self):
        """Send notification to the affected account."""
        if self.notification_sent:
            return

        # Get target email
        email = self.get_target_email()
        if not email:
            return

        try:
            subject = _("Account Action Notice: {0}").format(self.action_type)

            message = self.get_notification_message()

            frappe.sendmail(
                recipients=[email],
                subject=subject,
                message=message,
                reference_doctype="Account Action",
                reference_name=self.name
            )

            self.notification_sent = 1
            self.notification_sent_at = now_datetime()
            self.notification_method = "Email"
            self.db_update()

        except Exception as e:
            frappe.log_error(
                f"Error sending notification for {self.name}: {str(e)}",
                "Account Action Notification Error"
            )

    def get_target_email(self):
        """Get email address for the target account."""
        if self.target_type == "User" and self.user:
            return self.user  # User name is usually email
        elif self.target_type == "Seller Profile" and self.seller_profile:
            return frappe.db.get_value("Seller Profile", self.seller_profile, "email")
        elif self.target_type == "Organization" and self.organization:
            return frappe.db.get_value("Organization", self.organization, "email")
        return None

    def get_notification_message(self):
        """Generate notification message for the action."""
        message_parts = [
            _("Your account has been subject to the following action:"),
            "",
            _("**Action Type:** {0}").format(self.action_type),
            _("**Reason:** {0}").format(self.reason),
        ]

        if self.detailed_reason:
            message_parts.append(_("**Details:** {0}").format(self.detailed_reason))

        if not self.is_permanent and self.end_date:
            message_parts.append(_("**Effective Until:** {0}").format(self.end_date))
        elif self.is_permanent:
            message_parts.append(_("**Duration:** Permanent"))

        if self.is_appealable:
            message_parts.extend([
                "",
                _("If you believe this action was taken in error, you may submit an appeal.")
            ])

        return "\n".join(message_parts)

    def clear_action_cache(self):
        """Clear cached action data."""
        cache_keys = []
        if self.user:
            cache_keys.append(f"account_actions:{self.user}")
        if self.seller_profile:
            cache_keys.append(f"account_actions:seller:{self.seller_profile}")
        if self.organization:
            cache_keys.append(f"account_actions:org:{self.organization}")

        for key in cache_keys:
            frappe.cache().delete_value(key)

    def log_action_event(self, event_type):
        """Log action event for audit trail."""
        frappe.get_doc({
            "doctype": "Comment",
            "comment_type": "Info",
            "reference_doctype": "Account Action",
            "reference_name": self.name,
            "content": f"Action {event_type} - Type: {self.action_type}, "
                       f"Target: {self.target_type}, Status: {self.status}"
        }).insert(ignore_permissions=True)

    # Public Methods
    def lift_action(self, reason=None, lifted_by=None, auto=False):
        """Lift the action early."""
        if self.status in ["Lifted", "Overturned", "Cancelled"]:
            frappe.throw(_("Action has already been lifted or cancelled"))

        self.status = "Lifted"
        self.lifted_at = now_datetime()
        self.lifted_by = lifted_by or frappe.session.user
        self.lifted_reason = reason or (_("Auto-lift on expiry") if auto else _("Manual lift"))

        self.remove_action_from_target()
        self.save()
        self.log_action_event("lifted")

        return {
            "status": "success",
            "message": _("Action has been lifted")
        }

    def submit_appeal(self, reason, evidence=None):
        """Submit an appeal for this action."""
        if not self.is_appealable:
            frappe.throw(_("This action is not appealable"))

        if self.appeal_status not in ["", "Not Appealed"]:
            frappe.throw(_("An appeal has already been submitted"))

        self.appeal_status = "Appeal Submitted"
        self.appeal_submitted_at = now_datetime()
        self.appeal_reason = reason
        if evidence:
            self.appeal_evidence = evidence
        self.status = "Appealed"

        self.save()
        self.log_action_event("appeal_submitted")

        return {
            "status": "success",
            "message": _("Appeal has been submitted")
        }

    def review_appeal(self, decision, response=None, status="Under Review"):
        """Review an appeal (admin function)."""
        if self.appeal_status not in ["Appeal Submitted", "Under Review"]:
            frappe.throw(_("No appeal pending review"))

        self.appeal_status = status

        if status in ["Approved", "Rejected", "Partially Approved"]:
            self.appeal_decision = decision
            self.appeal_response = response
            self.appeal_decided_at = now_datetime()
            self.appeal_decided_by = frappe.session.user

            if status == "Approved":
                self.status = "Overturned"
                self.remove_action_from_target()
            elif status == "Partially Approved":
                # Reduce duration or restrictions
                pass
            else:
                # Rejected - restore to Active
                self.status = "Active"

        self.save()
        self.log_action_event(f"appeal_{status.lower()}")

        # Send notification about appeal decision
        self.send_appeal_decision_notification()

        return {
            "status": "success",
            "message": _("Appeal has been {0}").format(status.lower())
        }

    def send_appeal_decision_notification(self):
        """Send notification about appeal decision."""
        email = self.get_target_email()
        if not email:
            return

        try:
            subject = _("Appeal Decision: {0}").format(self.appeal_status)

            message_parts = [
                _("Your appeal for the account action has been reviewed."),
                "",
                _("**Decision:** {0}").format(self.appeal_status),
            ]

            if self.appeal_response:
                message_parts.append(_("**Response:** {0}").format(self.appeal_response))

            frappe.sendmail(
                recipients=[email],
                subject=subject,
                message="\n".join(message_parts),
                reference_doctype="Account Action",
                reference_name=self.name
            )

        except Exception as e:
            frappe.log_error(
                f"Error sending appeal notification: {str(e)}",
                "Account Action Appeal Notification Error"
            )

    def escalate(self, new_action_type=None, reason=None):
        """Escalate to a more severe action."""
        if not new_action_type:
            new_action_type = self.next_escalation_action or self.get_next_escalation_level()

        # Create new escalated action
        new_action = frappe.get_doc({
            "doctype": "Account Action",
            "action_type": new_action_type,
            "severity": self.get_escalated_severity(),
            "target_type": self.target_type,
            "user": self.user,
            "seller_profile": self.seller_profile,
            "organization": self.organization,
            "tenant": self.tenant,
            "reason_code": self.reason_code,
            "reason": reason or _("Escalated from {0}").format(self.name),
            "detailed_reason": _("Escalated due to: {0}").format(self.reason),
            "violation_type": "Escalated Offense",
            "previous_action": self.name,
            "escalation_level": self.escalation_level + 1
        })

        new_action.insert()

        # Mark this action as escalated
        self.status = "Escalated"
        self.save()
        self.log_action_event("escalated")

        return {
            "status": "success",
            "new_action": new_action.name,
            "message": _("Action escalated to {0}").format(new_action_type)
        }

    def get_next_escalation_level(self):
        """Get the next escalation action type."""
        escalation_order = [
            "Warning",
            "Restriction",
            "Suspension",
            "Temporary Ban",
            "Permanent Ban",
            "Account Termination"
        ]

        try:
            current_index = escalation_order.index(self.action_type)
            if current_index < len(escalation_order) - 1:
                return escalation_order[current_index + 1]
        except ValueError:
            pass

        return "Suspension"

    def get_escalated_severity(self):
        """Get escalated severity level."""
        severity_order = ["Low", "Medium", "High", "Critical"]
        try:
            current_index = severity_order.index(self.severity)
            if current_index < len(severity_order) - 1:
                return severity_order[current_index + 1]
        except ValueError:
            pass
        return "High"

    def is_active(self):
        """Check if this action is currently active."""
        if self.status != "Active":
            return False

        if not self.is_permanent and self.end_date:
            if get_datetime(self.end_date) < get_datetime(now_datetime()):
                return False

        return True

    def get_action_summary(self):
        """Get a summary of this action."""
        return {
            "name": self.name,
            "action_type": self.action_type,
            "severity": self.severity,
            "status": self.status,
            "reason": self.reason,
            "reason_code": self.reason_code,
            "target_type": self.target_type,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "is_permanent": self.is_permanent,
            "is_active": self.is_active(),
            "is_appealable": self.is_appealable,
            "appeal_status": self.appeal_status,
            "restrictions": {
                "selling": self.restrict_selling,
                "buying": self.restrict_buying,
                "messaging": self.restrict_messaging,
                "reviews": self.restrict_reviews,
                "listing_create": self.restrict_listing_create,
                "withdrawal": self.restrict_withdrawal,
                "all_activity": self.restrict_all_activity
            }
        }


# API Endpoints
@frappe.whitelist()
def get_account_actions(target_type, target_id, active_only=True):
    """
    Get account actions for a target.

    Args:
        target_type: Type of target (User, Seller Profile, Organization)
        target_id: ID of the target
        active_only: Only return active actions

    Returns:
        list: Account actions
    """
    # Permission check
    if "System Manager" not in frappe.get_roles() and "Marketplace Admin" not in frappe.get_roles():
        # Users can only see their own actions
        if target_type == "User" and target_id != frappe.session.user:
            frappe.throw(_("Not permitted to view these account actions"))

    filters = {"target_type": target_type}

    if target_type == "User":
        filters["user"] = target_id
    elif target_type == "Seller Profile":
        filters["seller_profile"] = target_id
    elif target_type == "Organization":
        filters["organization"] = target_id

    if active_only:
        filters["status"] = "Active"

    actions = frappe.get_all(
        "Account Action",
        filters=filters,
        fields=[
            "name", "action_type", "severity", "status", "reason", "reason_code",
            "start_date", "end_date", "is_permanent", "is_appealable", "appeal_status",
            "restrict_selling", "restrict_buying", "restrict_messaging",
            "restrict_reviews", "restrict_listing_create", "restrict_withdrawal"
        ],
        order_by="creation desc"
    )

    return actions


@frappe.whitelist()
def check_account_status(target_type, target_id):
    """
    Check if an account has any active restrictions.

    Args:
        target_type: Type of target
        target_id: ID of the target

    Returns:
        dict: Account status and restrictions
    """
    filters = {
        "target_type": target_type,
        "status": "Active"
    }

    if target_type == "User":
        filters["user"] = target_id
    elif target_type == "Seller Profile":
        filters["seller_profile"] = target_id
    elif target_type == "Organization":
        filters["organization"] = target_id

    actions = frappe.get_all(
        "Account Action",
        filters=filters,
        fields=[
            "name", "action_type", "severity", "reason",
            "restrict_selling", "restrict_buying", "restrict_messaging",
            "restrict_reviews", "restrict_listing_create", "restrict_withdrawal",
            "restrict_all_activity", "end_date", "is_permanent"
        ]
    )

    if not actions:
        return {
            "has_restrictions": False,
            "can_sell": True,
            "can_buy": True,
            "can_message": True,
            "can_review": True,
            "can_create_listing": True,
            "can_withdraw": True,
            "actions": []
        }

    # Aggregate restrictions
    restrictions = {
        "can_sell": True,
        "can_buy": True,
        "can_message": True,
        "can_review": True,
        "can_create_listing": True,
        "can_withdraw": True
    }

    for action in actions:
        if action.restrict_selling or action.restrict_all_activity:
            restrictions["can_sell"] = False
        if action.restrict_buying or action.restrict_all_activity:
            restrictions["can_buy"] = False
        if action.restrict_messaging or action.restrict_all_activity:
            restrictions["can_message"] = False
        if action.restrict_reviews or action.restrict_all_activity:
            restrictions["can_review"] = False
        if action.restrict_listing_create or action.restrict_all_activity:
            restrictions["can_create_listing"] = False
        if action.restrict_withdrawal or action.restrict_all_activity:
            restrictions["can_withdraw"] = False

    return {
        "has_restrictions": True,
        **restrictions,
        "actions": actions
    }


@frappe.whitelist()
def create_account_action(
    action_type,
    target_type,
    target_id,
    reason,
    severity="Medium",
    reason_code=None,
    detailed_reason=None,
    duration_days=None,
    is_permanent=False,
    restrictions=None
):
    """
    Create a new account action.

    Args:
        action_type: Type of action
        target_type: Type of target
        target_id: ID of target
        reason: Brief reason
        severity: Severity level
        reason_code: Standardized reason code
        detailed_reason: Full explanation
        duration_days: Duration in days (None for permanent)
        is_permanent: Whether action is permanent
        restrictions: Dict of specific restrictions

    Returns:
        dict: Result with action name
    """
    if "System Manager" not in frappe.get_roles() and "Marketplace Admin" not in frappe.get_roles():
        frappe.throw(_("Not permitted to create account actions"))

    doc_data = {
        "doctype": "Account Action",
        "action_type": action_type,
        "target_type": target_type,
        "severity": severity,
        "reason": reason,
        "reason_code": reason_code,
        "detailed_reason": detailed_reason,
        "is_permanent": cint(is_permanent),
        "start_date": now_datetime()
    }

    # Set target
    if target_type == "User":
        doc_data["user"] = target_id
    elif target_type == "Seller Profile":
        doc_data["seller_profile"] = target_id
    elif target_type == "Organization":
        doc_data["organization"] = target_id

    # Set duration
    if not is_permanent and duration_days:
        doc_data["end_date"] = add_days(nowdate(), cint(duration_days))

    # Set restrictions
    if restrictions and isinstance(restrictions, dict):
        for key, value in restrictions.items():
            if key.startswith("restrict_"):
                doc_data[key] = cint(value)

    action = frappe.get_doc(doc_data)
    action.insert()

    return {
        "status": "success",
        "action_name": action.name,
        "message": _("Account action created successfully")
    }


@frappe.whitelist()
def lift_account_action(action_name, reason=None):
    """
    Lift an account action.

    Args:
        action_name: Name of the action
        reason: Reason for lifting

    Returns:
        dict: Result
    """
    if "System Manager" not in frappe.get_roles() and "Marketplace Admin" not in frappe.get_roles():
        frappe.throw(_("Not permitted to lift account actions"))

    action = frappe.get_doc("Account Action", action_name)
    return action.lift_action(reason=reason)


@frappe.whitelist()
def submit_action_appeal(action_name, reason, evidence=None):
    """
    Submit an appeal for an account action.

    Args:
        action_name: Name of the action
        reason: Appeal reason
        evidence: Supporting evidence

    Returns:
        dict: Result
    """
    action = frappe.get_doc("Account Action", action_name)

    # Verify user is the target
    is_target = False
    if action.target_type == "User" and action.user == frappe.session.user:
        is_target = True
    # TODO: Add checks for seller profile and organization members

    if not is_target and "System Manager" not in frappe.get_roles():
        frappe.throw(_("Not permitted to submit this appeal"))

    return action.submit_appeal(reason=reason, evidence=evidence)


@frappe.whitelist()
def review_action_appeal(action_name, decision, status, response=None):
    """
    Review an appeal (admin function).

    Args:
        action_name: Name of the action
        decision: Appeal decision
        status: New appeal status
        response: Response to send to user

    Returns:
        dict: Result
    """
    if "System Manager" not in frappe.get_roles() and "Marketplace Admin" not in frappe.get_roles():
        frappe.throw(_("Not permitted to review appeals"))

    action = frappe.get_doc("Account Action", action_name)
    return action.review_appeal(decision=decision, response=response, status=status)


@frappe.whitelist()
def get_action_statistics():
    """
    Get account action statistics for admin dashboard.

    Returns:
        dict: Action statistics
    """
    if "System Manager" not in frappe.get_roles() and "Marketplace Admin" not in frappe.get_roles():
        frappe.throw(_("Not permitted to view action statistics"))

    stats = {
        "total": frappe.db.count("Account Action"),
        "active": frappe.db.count("Account Action", {"status": "Active"}),
        "pending_approval": frappe.db.count("Account Action", {"status": "Pending Approval"}),
        "appealed": frappe.db.count("Account Action", {"status": "Appealed"}),
        "lifted": frappe.db.count("Account Action", {"status": "Lifted"}),
        "overturned": frappe.db.count("Account Action", {"status": "Overturned"})
    }

    # Actions by type
    action_types = frappe.db.sql("""
        SELECT action_type, COUNT(*) as count
        FROM `tabAccount Action`
        WHERE status = 'Active'
        GROUP BY action_type
        ORDER BY count DESC
    """, as_dict=True)

    stats["by_type"] = {at["action_type"]: at["count"] for at in action_types}

    # Actions by severity
    severities = frappe.db.sql("""
        SELECT severity, COUNT(*) as count
        FROM `tabAccount Action`
        WHERE status = 'Active'
        GROUP BY severity
    """, as_dict=True)

    stats["by_severity"] = {s["severity"]: s["count"] for s in severities}

    # Recent activity (last 30 days)
    thirty_days_ago = add_days(nowdate(), -30)

    stats["recent_created"] = frappe.db.count(
        "Account Action",
        {"creation": (">=", thirty_days_ago)}
    )

    stats["recent_lifted"] = frappe.db.count(
        "Account Action",
        {"lifted_at": (">=", thirty_days_ago)}
    )

    stats["pending_appeals"] = frappe.db.count(
        "Account Action",
        {"appeal_status": ["in", ["Appeal Submitted", "Under Review"]]}
    )

    return stats


@frappe.whitelist()
def get_pending_appeals():
    """
    Get account actions with pending appeals.

    Returns:
        list: Actions with pending appeals
    """
    if "System Manager" not in frappe.get_roles() and "Marketplace Admin" not in frappe.get_roles():
        frappe.throw(_("Not permitted to view pending appeals"))

    appeals = frappe.get_all(
        "Account Action",
        filters={
            "appeal_status": ["in", ["Appeal Submitted", "Under Review"]]
        },
        fields=[
            "name", "action_type", "severity", "target_type", "user",
            "seller_profile", "organization", "reason", "appeal_reason",
            "appeal_submitted_at", "appeal_status"
        ],
        order_by="appeal_submitted_at asc"
    )

    return appeals

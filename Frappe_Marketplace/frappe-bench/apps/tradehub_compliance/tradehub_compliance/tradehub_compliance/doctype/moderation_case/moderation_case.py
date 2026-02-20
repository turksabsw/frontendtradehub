# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt, getdate, nowdate, now_datetime, get_datetime, add_days, time_diff_in_hours
import json


class ModerationCase(Document):
    """
    Moderation Case DocType for content review.

    This DocType manages the review workflow for marketplace content including
    listings, reviews, storefronts, and other user-generated content.

    Features:
    - Support for multiple content types (Dynamic Link)
    - Report-based and automated case creation
    - Assignment and review workflow
    - Decision and action tracking
    - Appeal workflow
    - Escalation management
    - SLA tracking
    - Notification management
    - Full audit trail
    """

    def before_insert(self):
        """Set default values before inserting a new case."""
        if not self.created_by_user:
            self.created_by_user = frappe.session.user

        if not self.creation_date:
            self.creation_date = now_datetime()

        # Generate unique case ID
        if not self.case_id:
            self.case_id = self.generate_case_id()

        # Set tenant from context if not specified
        if not self.tenant:
            self.set_tenant_from_context()

        # Capture content snapshot
        self.capture_content_snapshot()

        # Calculate queue position
        self.calculate_queue_position()

        # Set SLA target based on priority
        self.set_sla_target()

        # Check for repeat offenses
        self.check_repeat_offense()

    def validate(self):
        """Validate case data before saving."""
        self.validate_content()
        self.validate_status_transitions()
        self.validate_decision()
        self.validate_appeal()
        self.validate_escalation()
        self.update_metrics()

    def on_update(self):
        """Actions to perform after case is updated."""
        self.check_sla_status()
        self.log_history_event("updated")

    def after_insert(self):
        """Actions to perform after case is created."""
        self.log_history_event("created")

    def on_trash(self):
        """Prevent deletion of moderation cases - they must be preserved for audit."""
        frappe.throw(
            _("Moderation cases cannot be deleted for audit purposes. "
              "Mark as closed instead.")
        )

    def generate_case_id(self):
        """Generate a unique case ID."""
        import time
        timestamp = int(time.time() * 1000) % 100000000
        return f"MC-{timestamp}"

    def set_tenant_from_context(self):
        """Set tenant from user's session context."""
        try:
            from tradehub_core.tradehub_core.utils.tenant import get_current_tenant
            tenant = get_current_tenant()
            if tenant:
                self.tenant = tenant
        except ImportError:
            pass

    def capture_content_snapshot(self):
        """Capture a snapshot of the content at time of case creation."""
        if self.content_type and self.content_id and not self.content_snapshot:
            try:
                content_doc = frappe.get_doc(self.content_type, self.content_id)

                # Get basic fields based on content type
                snapshot = {
                    "name": content_doc.name,
                    "doctype": self.content_type,
                    "captured_at": str(now_datetime()),
                }

                # Add title/name field
                title_fields = ["title", "name", "listing_name", "store_name", "seller_name"]
                for field in title_fields:
                    if hasattr(content_doc, field) and getattr(content_doc, field):
                        snapshot["title"] = getattr(content_doc, field)
                        self.content_title = getattr(content_doc, field)
                        break

                # Add creation date
                if hasattr(content_doc, "creation"):
                    self.content_created_at = content_doc.creation
                    snapshot["creation"] = str(content_doc.creation)

                # Add status if available
                if hasattr(content_doc, "status"):
                    snapshot["status"] = content_doc.status

                # Add key fields based on content type
                if self.content_type == "Listing":
                    for field in ["description", "base_price", "selling_price", "seller", "category"]:
                        if hasattr(content_doc, field):
                            snapshot[field] = getattr(content_doc, field)
                elif self.content_type == "Review":
                    for field in ["rating", "review_text", "reviewer", "listing"]:
                        if hasattr(content_doc, field):
                            snapshot[field] = getattr(content_doc, field)
                elif self.content_type == "Storefront":
                    for field in ["store_name", "tagline", "seller"]:
                        if hasattr(content_doc, field):
                            snapshot[field] = getattr(content_doc, field)

                # Determine content owner
                owner_fields = ["seller", "owner", "user", "reviewer", "created_by"]
                for field in owner_fields:
                    if hasattr(content_doc, field) and getattr(content_doc, field):
                        self.content_owner = getattr(content_doc, field)
                        # Determine owner type
                        if field == "seller":
                            self.content_owner_type = "Seller Profile"
                        elif field in ["owner", "user", "reviewer", "created_by"]:
                            self.content_owner_type = "User"
                        break

                self.content_snapshot = json.dumps(snapshot)

            except Exception as e:
                frappe.log_error(
                    f"Error capturing content snapshot for {self.content_type}/{self.content_id}: {str(e)}",
                    "Moderation Case Snapshot Error"
                )

    def calculate_queue_position(self):
        """Calculate the queue position based on open cases."""
        open_cases_count = frappe.db.count(
            "Moderation Case",
            {"status": ["in", ["Open", "Assigned"]]}
        )
        self.queue_position = open_cases_count + 1

    def set_sla_target(self):
        """Set SLA target hours based on priority."""
        sla_targets = {
            "Critical": 4,
            "High": 12,
            "Medium": 24,
            "Low": 48
        }
        if not self.sla_target_hours:
            self.sla_target_hours = sla_targets.get(self.priority, 24)

    def check_repeat_offense(self):
        """Check if this is a repeat offense by the content owner."""
        if not self.content_owner:
            return

        previous_cases = frappe.db.count(
            "Moderation Case",
            {
                "content_owner": self.content_owner,
                "status": ["in", ["Resolved", "Closed"]],
                "violation_type": ["!=", "No Violation"],
                "name": ["!=", self.name or ""]
            }
        )

        if previous_cases > 0:
            self.is_repeat_offense = 1
            self.previous_violations_count = previous_cases

    def validate_content(self):
        """Validate that the content exists and is valid."""
        if not self.content_type:
            frappe.throw(_("Content Type is required"))

        if not self.content_id:
            frappe.throw(_("Content ID is required"))

        # Verify content exists
        if not frappe.db.exists(self.content_type, self.content_id):
            frappe.throw(
                _("Content {0} of type {1} does not exist").format(
                    self.content_id, self.content_type
                )
            )

    def validate_status_transitions(self):
        """Validate that status transitions are valid."""
        if self.is_new():
            return

        old_status = frappe.db.get_value("Moderation Case", self.name, "status")

        valid_transitions = {
            "Open": ["Assigned", "In Review", "Escalated", "Closed"],
            "Assigned": ["In Review", "Open", "Escalated", "Closed"],
            "In Review": ["Resolved", "Pending Info", "Escalated", "Closed"],
            "Pending Info": ["In Review", "Resolved", "Escalated", "Closed"],
            "Escalated": ["In Review", "Resolved", "Closed"],
            "Resolved": ["Closed", "Appealed", "Reopened"],
            "Closed": ["Reopened"],
            "Appealed": ["Resolved", "In Review"],
            "Reopened": ["Assigned", "In Review", "Resolved", "Closed"]
        }

        if old_status and old_status != self.status:
            allowed = valid_transitions.get(old_status, [])
            if self.status not in allowed:
                frappe.throw(
                    _("Invalid status transition from {0} to {1}").format(
                        old_status, self.status
                    )
                )

    def validate_decision(self):
        """Validate decision-related fields."""
        if self.status == "Resolved" and not self.decision:
            frappe.throw(_("Decision is required when resolving a case"))

        # Set review completion timestamp
        if self.status == "Resolved" and not self.review_completed_at:
            self.review_completed_at = now_datetime()
            self.reviewed_by = frappe.session.user

            # Calculate review time
            if self.review_started_at:
                diff = get_datetime(self.review_completed_at) - get_datetime(self.review_started_at)
                self.review_time_seconds = int(diff.total_seconds())

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

    def validate_escalation(self):
        """Validate escalation-related fields."""
        if self.is_escalated and not self.escalation_level:
            frappe.throw(_("Escalation level is required when case is escalated"))

    def update_metrics(self):
        """Update performance metrics."""
        if self.creation_date:
            # Calculate wait time (time until assignment)
            if self.assigned_at:
                self.wait_time_hours = flt(
                    time_diff_in_hours(self.assigned_at, self.creation_date), 2
                )

            # Calculate resolution time
            if self.status in ["Resolved", "Closed"] and self.review_completed_at:
                self.resolution_time_hours = flt(
                    time_diff_in_hours(self.review_completed_at, self.creation_date), 2
                )

    def check_sla_status(self):
        """Check and update SLA status."""
        if not self.sla_target_hours or self.status in ["Resolved", "Closed"]:
            return

        hours_elapsed = flt(time_diff_in_hours(now_datetime(), self.creation_date), 2)

        if hours_elapsed > self.sla_target_hours:
            self.sla_status = "Breached"
        elif hours_elapsed > self.sla_target_hours * 0.8:
            self.sla_status = "At Risk"
        else:
            self.sla_status = "On Track"

    def log_history_event(self, event_type, details=None):
        """Log an event to the moderation history."""
        history = []
        if self.moderation_history:
            try:
                history = json.loads(self.moderation_history)
            except (json.JSONDecodeError, TypeError):
                history = []

        event = {
            "timestamp": str(now_datetime()),
            "event": event_type,
            "user": frappe.session.user,
            "status": self.status,
        }

        if details:
            event["details"] = details

        history.append(event)
        self.moderation_history = json.dumps(history)

    # -------------------- Public Methods --------------------

    def assign_case(self, moderator):
        """Assign this case to a moderator."""
        if self.status not in ["Open", "Reopened"]:
            frappe.throw(_("Only open cases can be assigned"))

        if not frappe.db.exists("User", moderator):
            frappe.throw(_("User {0} does not exist").format(moderator))

        self.assigned_to = moderator
        self.assigned_at = now_datetime()
        self.status = "Assigned"

        self.log_history_event("assigned", {"assigned_to": moderator})
        self.save()

        return {
            "status": "success",
            "message": _("Case assigned to {0}").format(moderator)
        }

    def start_review(self):
        """Start the review process."""
        if self.status not in ["Assigned", "Open"]:
            frappe.throw(_("Case must be assigned before starting review"))

        self.status = "In Review"
        self.review_started_at = now_datetime()

        if not self.assigned_to:
            self.assigned_to = frappe.session.user
            self.assigned_at = now_datetime()

        self.log_history_event("review_started")
        self.save()

        return {
            "status": "success",
            "message": _("Review started")
        }

    def resolve_case(self, decision, decision_reason=None, action_taken=None,
                     content_action=None, decision_notes=None):
        """Resolve the case with a decision."""
        if self.status not in ["In Review", "Pending Info", "Escalated", "Appealed"]:
            frappe.throw(_("Case must be in review to be resolved"))

        if not decision:
            frappe.throw(_("Decision is required"))

        self.status = "Resolved"
        self.decision = decision
        self.decision_reason = decision_reason
        self.decision_notes = decision_notes
        self.action_taken = action_taken
        self.content_action = content_action
        self.review_completed_at = now_datetime()
        self.reviewed_by = frappe.session.user

        # Calculate review time
        if self.review_started_at:
            diff = get_datetime(self.review_completed_at) - get_datetime(self.review_started_at)
            self.review_time_seconds = int(diff.total_seconds())

        self.log_history_event("resolved", {
            "decision": decision,
            "action_taken": action_taken
        })

        # Apply content action if specified
        if content_action and content_action != "No Change":
            self.apply_content_action(content_action)

        self.save()

        # Send notifications
        self.send_decision_notification()

        return {
            "status": "success",
            "message": _("Case resolved with decision: {0}").format(decision)
        }

    def apply_content_action(self, action):
        """Apply the specified action to the content."""
        if not self.content_type or not self.content_id:
            return

        try:
            content_doc = frappe.get_doc(self.content_type, self.content_id)

            if action == "Remove":
                if hasattr(content_doc, "status"):
                    content_doc.status = "Removed"
                elif hasattr(content_doc, "is_active"):
                    content_doc.is_active = 0
            elif action == "Hide":
                if hasattr(content_doc, "status"):
                    content_doc.status = "Hidden"
                elif hasattr(content_doc, "is_visible"):
                    content_doc.is_visible = 0
            elif action == "Restrict Visibility":
                if hasattr(content_doc, "visibility"):
                    content_doc.visibility = "Restricted"
            elif action == "Delist":
                if hasattr(content_doc, "status"):
                    content_doc.status = "Delisted"
            elif action == "Restore":
                if hasattr(content_doc, "status"):
                    content_doc.status = "Active"
                if hasattr(content_doc, "is_active"):
                    content_doc.is_active = 1

            # Add moderation flag if available
            if hasattr(content_doc, "moderation_status"):
                if action in ["Remove", "Hide", "Delist"]:
                    content_doc.moderation_status = "Rejected"
                elif action == "Restore":
                    content_doc.moderation_status = "Approved"

            content_doc.save(ignore_permissions=True)

        except Exception as e:
            frappe.log_error(
                f"Error applying content action {action} to {self.content_type}/{self.content_id}: {str(e)}",
                "Moderation Case Action Error"
            )

    def escalate_case(self, escalation_level, escalated_to, reason):
        """Escalate the case to a higher level."""
        if self.status in ["Resolved", "Closed"]:
            frappe.throw(_("Resolved or closed cases cannot be escalated"))

        self.is_escalated = 1
        self.escalation_level = escalation_level
        self.escalated_to = escalated_to
        self.escalation_reason = reason
        self.escalated_at = now_datetime()
        self.escalated_by = frappe.session.user
        self.status = "Escalated"

        # Update priority for escalated cases
        if self.priority not in ["Critical", "High"]:
            self.priority = "High"

        self.log_history_event("escalated", {
            "level": escalation_level,
            "to": escalated_to,
            "reason": reason
        })

        self.save()

        return {
            "status": "success",
            "message": _("Case escalated to {0}").format(escalation_level)
        }

    def request_info(self, request_details):
        """Request additional information for the case."""
        if self.status not in ["In Review", "Assigned"]:
            frappe.throw(_("Case must be in review to request info"))

        self.status = "Pending Info"

        self.log_history_event("info_requested", {
            "request_details": request_details
        })

        self.save()

        return {
            "status": "success",
            "message": _("Information requested")
        }

    def close_case(self, close_reason=None):
        """Close the case."""
        self.status = "Closed"

        self.log_history_event("closed", {
            "reason": close_reason
        })

        self.save()

        return {
            "status": "success",
            "message": _("Case closed")
        }

    def reopen_case(self, reason):
        """Reopen a closed or resolved case."""
        if self.status not in ["Resolved", "Closed"]:
            frappe.throw(_("Only resolved or closed cases can be reopened"))

        self.status = "Reopened"

        self.log_history_event("reopened", {
            "reason": reason
        })

        self.save()

        return {
            "status": "success",
            "message": _("Case reopened")
        }

    def submit_appeal(self, appeal_reason, appeal_evidence=None):
        """Submit an appeal for this case."""
        if not self.is_appealable:
            frappe.throw(_("This case is not appealable"))

        if self.status != "Resolved":
            frappe.throw(_("Only resolved cases can be appealed"))

        if self.appeal_status not in ["", "Not Appealed"]:
            frappe.throw(_("An appeal has already been submitted"))

        self.appeal_status = "Appeal Submitted"
        self.appeal_submitted_at = now_datetime()
        self.appeal_reason = appeal_reason
        if appeal_evidence:
            self.appeal_evidence = appeal_evidence
        self.status = "Appealed"

        self.log_history_event("appeal_submitted")

        self.save()

        return {
            "status": "success",
            "message": _("Appeal submitted successfully")
        }

    def review_appeal(self, status, decision, response=None):
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
                # Reverse the original action
                if self.content_action in ["Remove", "Hide", "Delist"]:
                    self.apply_content_action("Restore")
                self.decision = "No Action Needed"
            elif status == "Rejected":
                # Keep the original decision
                pass

            self.status = "Resolved"

        self.log_history_event(f"appeal_{status.lower()}", {
            "decision": decision
        })

        self.save()

        # Send appeal decision notification
        self.send_appeal_notification()

        return {
            "status": "success",
            "message": _("Appeal {0}").format(status.lower())
        }

    def send_decision_notification(self):
        """Send notification about the case decision."""
        if self.decision_notification_sent:
            return

        # Notify content owner
        owner_email = self.get_content_owner_email()
        if owner_email:
            try:
                subject = _("Content Moderation Decision - {0}").format(self.case_id)
                message = self.get_owner_notification_message()

                frappe.sendmail(
                    recipients=[owner_email],
                    subject=subject,
                    message=message,
                    reference_doctype="Moderation Case",
                    reference_name=self.name
                )

                self.owner_notified = 1
                self.owner_notified_at = now_datetime()

            except Exception as e:
                frappe.log_error(
                    f"Error sending owner notification: {str(e)}",
                    "Moderation Notification Error"
                )

        # Notify reporter
        if self.reporter:
            try:
                subject = _("Content Report Update - {0}").format(self.case_id)
                message = self.get_reporter_notification_message()

                frappe.sendmail(
                    recipients=[self.reporter],
                    subject=subject,
                    message=message,
                    reference_doctype="Moderation Case",
                    reference_name=self.name
                )

                self.reporter_notified = 1
                self.reporter_notified_at = now_datetime()

            except Exception as e:
                frappe.log_error(
                    f"Error sending reporter notification: {str(e)}",
                    "Moderation Notification Error"
                )

        self.decision_notification_sent = 1
        self.db_update()

    def send_appeal_notification(self):
        """Send notification about appeal decision."""
        owner_email = self.get_content_owner_email()
        if not owner_email:
            return

        try:
            subject = _("Appeal Decision - {0}").format(self.case_id)

            message_parts = [
                _("Your appeal for moderation case {0} has been reviewed.").format(self.case_id),
                "",
                _("**Decision:** {0}").format(self.appeal_status),
            ]

            if self.appeal_response:
                message_parts.append(_("**Response:** {0}").format(self.appeal_response))

            frappe.sendmail(
                recipients=[owner_email],
                subject=subject,
                message="\n".join(message_parts),
                reference_doctype="Moderation Case",
                reference_name=self.name
            )

        except Exception as e:
            frappe.log_error(
                f"Error sending appeal notification: {str(e)}",
                "Moderation Appeal Notification Error"
            )

    def get_content_owner_email(self):
        """Get email address for the content owner."""
        if not self.content_owner:
            return None

        if self.content_owner_type == "User":
            return self.content_owner
        elif self.content_owner_type == "Seller Profile":
            return frappe.db.get_value("Seller Profile", self.content_owner, "email")
        elif self.content_owner_type == "Organization":
            return frappe.db.get_value("Organization", self.content_owner, "email")

        return None

    def get_owner_notification_message(self):
        """Generate notification message for content owner."""
        message_parts = [
            _("Your content has been reviewed by our moderation team."),
            "",
            _("**Case ID:** {0}").format(self.case_id),
            _("**Content Type:** {0}").format(self.content_type),
            _("**Decision:** {0}").format(self.decision),
        ]

        if self.decision_reason:
            message_parts.append(_("**Reason:** {0}").format(self.decision_reason))

        if self.action_taken and self.action_taken != "None":
            message_parts.append(_("**Action Taken:** {0}").format(self.action_taken))

        if self.is_appealable:
            message_parts.extend([
                "",
                _("If you believe this decision was made in error, you may submit an appeal.")
            ])

        return "\n".join(message_parts)

    def get_reporter_notification_message(self):
        """Generate notification message for reporter."""
        message_parts = [
            _("Thank you for your report. We have reviewed the content you reported."),
            "",
            _("**Case ID:** {0}").format(self.case_id),
            _("**Status:** {0}").format(self.status),
        ]

        if self.action_taken and self.action_taken != "None":
            message_parts.append(_("**Action Taken:** {0}").format(self.action_taken))
        else:
            message_parts.append(_("After review, no violation was found."))

        message_parts.extend([
            "",
            _("Thank you for helping us maintain a safe marketplace.")
        ])

        return "\n".join(message_parts)

    def get_case_summary(self):
        """Get a summary of this case."""
        return {
            "name": self.name,
            "case_id": self.case_id,
            "case_type": self.case_type,
            "priority": self.priority,
            "status": self.status,
            "content_type": self.content_type,
            "content_id": self.content_id,
            "content_title": self.content_title,
            "content_owner": self.content_owner,
            "report_reason": self.report_reason,
            "violation_type": self.violation_type,
            "decision": self.decision,
            "action_taken": self.action_taken,
            "assigned_to": self.assigned_to,
            "is_escalated": self.is_escalated,
            "is_appealable": self.is_appealable,
            "appeal_status": self.appeal_status,
            "sla_status": self.sla_status,
            "creation_date": self.creation_date,
            "review_completed_at": self.review_completed_at
        }


# -------------------- API Endpoints --------------------

@frappe.whitelist()
def get_moderation_case(case_name):
    """
    Get moderation case details.

    Args:
        case_name: Name or case_id of the moderation case

    Returns:
        dict: Case details
    """
    # Try to find by name or case_id
    if not frappe.db.exists("Moderation Case", case_name):
        case_name = frappe.db.get_value(
            "Moderation Case",
            {"case_id": case_name},
            "name"
        )
        if not case_name:
            frappe.throw(_("Moderation case not found"))

    case_doc = frappe.get_doc("Moderation Case", case_name)
    return case_doc.get_case_summary()


@frappe.whitelist()
def create_moderation_case(content_type, content_id, case_type="Content Report",
                           report_reason=None, report_description=None,
                           priority="Medium", report_source="User Report"):
    """
    Create a new moderation case.

    Args:
        content_type: DocType of the content
        content_id: ID of the content
        case_type: Type of moderation case
        report_reason: Reason for the report
        report_description: Detailed description
        priority: Priority level
        report_source: Source of the report

    Returns:
        dict: Result with case name
    """
    doc = frappe.get_doc({
        "doctype": "Moderation Case",
        "content_type": content_type,
        "content_id": content_id,
        "case_type": case_type,
        "report_reason": report_reason,
        "report_description": report_description,
        "priority": priority,
        "report_source": report_source,
        "reporter": frappe.session.user if report_source in ["User Report", "Seller Report"] else None
    })

    doc.insert()

    return {
        "status": "success",
        "case_name": doc.name,
        "case_id": doc.case_id,
        "message": _("Moderation case created successfully")
    }


@frappe.whitelist()
def assign_case(case_name, moderator):
    """
    Assign a case to a moderator.

    Args:
        case_name: Name of the case
        moderator: User to assign to

    Returns:
        dict: Result
    """
    if "System Manager" not in frappe.get_roles() and "Marketplace Admin" not in frappe.get_roles():
        frappe.throw(_("Not permitted to assign cases"))

    case_doc = frappe.get_doc("Moderation Case", case_name)
    return case_doc.assign_case(moderator)


@frappe.whitelist()
def start_review(case_name):
    """
    Start review of a case.

    Args:
        case_name: Name of the case

    Returns:
        dict: Result
    """
    if "System Manager" not in frappe.get_roles() and "Marketplace Admin" not in frappe.get_roles() and "Marketplace Moderator" not in frappe.get_roles():
        frappe.throw(_("Not permitted to review cases"))

    case_doc = frappe.get_doc("Moderation Case", case_name)
    return case_doc.start_review()


@frappe.whitelist()
def resolve_case(case_name, decision, decision_reason=None, action_taken=None,
                 content_action=None, decision_notes=None):
    """
    Resolve a moderation case.

    Args:
        case_name: Name of the case
        decision: Decision made
        decision_reason: Reason for decision
        action_taken: Action taken
        content_action: Action applied to content
        decision_notes: Additional notes

    Returns:
        dict: Result
    """
    if "System Manager" not in frappe.get_roles() and "Marketplace Admin" not in frappe.get_roles() and "Marketplace Moderator" not in frappe.get_roles():
        frappe.throw(_("Not permitted to resolve cases"))

    case_doc = frappe.get_doc("Moderation Case", case_name)
    return case_doc.resolve_case(
        decision=decision,
        decision_reason=decision_reason,
        action_taken=action_taken,
        content_action=content_action,
        decision_notes=decision_notes
    )


@frappe.whitelist()
def escalate_case(case_name, escalation_level, escalated_to, reason):
    """
    Escalate a case.

    Args:
        case_name: Name of the case
        escalation_level: Level to escalate to
        escalated_to: User to escalate to
        reason: Reason for escalation

    Returns:
        dict: Result
    """
    if "System Manager" not in frappe.get_roles() and "Marketplace Admin" not in frappe.get_roles() and "Marketplace Moderator" not in frappe.get_roles():
        frappe.throw(_("Not permitted to escalate cases"))

    case_doc = frappe.get_doc("Moderation Case", case_name)
    return case_doc.escalate_case(escalation_level, escalated_to, reason)


@frappe.whitelist()
def submit_appeal(case_name, appeal_reason, appeal_evidence=None):
    """
    Submit an appeal for a moderation decision.

    Args:
        case_name: Name of the case
        appeal_reason: Reason for appeal
        appeal_evidence: Supporting evidence

    Returns:
        dict: Result
    """
    case_doc = frappe.get_doc("Moderation Case", case_name)

    # Verify user is the content owner
    is_owner = False
    if case_doc.content_owner_type == "User" and case_doc.content_owner == frappe.session.user:
        is_owner = True
    # TODO: Add checks for seller profile and organization owners

    if not is_owner and "System Manager" not in frappe.get_roles():
        frappe.throw(_("Not permitted to submit this appeal"))

    return case_doc.submit_appeal(appeal_reason, appeal_evidence)


@frappe.whitelist()
def review_appeal(case_name, status, decision, response=None):
    """
    Review an appeal.

    Args:
        case_name: Name of the case
        status: Appeal status (Approved/Rejected/Partially Approved)
        decision: Decision text
        response: Response to content owner

    Returns:
        dict: Result
    """
    if "System Manager" not in frappe.get_roles() and "Marketplace Admin" not in frappe.get_roles():
        frappe.throw(_("Not permitted to review appeals"))

    case_doc = frappe.get_doc("Moderation Case", case_name)
    return case_doc.review_appeal(status, decision, response)


@frappe.whitelist()
def get_moderation_queue(status=None, priority=None, assigned_to=None, limit=50):
    """
    Get moderation queue.

    Args:
        status: Filter by status
        priority: Filter by priority
        assigned_to: Filter by assignee
        limit: Maximum number of cases to return

    Returns:
        list: Moderation cases
    """
    if "System Manager" not in frappe.get_roles() and "Marketplace Admin" not in frappe.get_roles() and "Marketplace Moderator" not in frappe.get_roles():
        frappe.throw(_("Not permitted to view moderation queue"))

    filters = {}

    if status:
        filters["status"] = status
    else:
        filters["status"] = ["in", ["Open", "Assigned", "In Review", "Pending Info", "Escalated"]]

    if priority:
        filters["priority"] = priority

    if assigned_to:
        filters["assigned_to"] = assigned_to

    cases = frappe.get_all(
        "Moderation Case",
        filters=filters,
        fields=[
            "name", "case_id", "case_type", "priority", "status",
            "content_type", "content_id", "content_title",
            "report_reason", "assigned_to", "is_escalated",
            "sla_status", "creation_date", "sla_target_hours"
        ],
        order_by="FIELD(priority, 'Critical', 'High', 'Medium', 'Low'), creation asc",
        limit_page_length=cint(limit)
    )

    return cases


@frappe.whitelist()
def get_moderation_statistics():
    """
    Get moderation statistics for dashboard.

    Returns:
        dict: Statistics
    """
    if "System Manager" not in frappe.get_roles() and "Marketplace Admin" not in frappe.get_roles():
        frappe.throw(_("Not permitted to view moderation statistics"))

    stats = {
        "total": frappe.db.count("Moderation Case"),
        "open": frappe.db.count("Moderation Case", {"status": "Open"}),
        "assigned": frappe.db.count("Moderation Case", {"status": "Assigned"}),
        "in_review": frappe.db.count("Moderation Case", {"status": "In Review"}),
        "pending_info": frappe.db.count("Moderation Case", {"status": "Pending Info"}),
        "escalated": frappe.db.count("Moderation Case", {"status": "Escalated"}),
        "resolved": frappe.db.count("Moderation Case", {"status": "Resolved"}),
        "appealed": frappe.db.count("Moderation Case", {"status": "Appealed"})
    }

    # By priority
    priorities = frappe.db.sql("""
        SELECT priority, COUNT(*) as count
        FROM `tabModeration Case`
        WHERE status NOT IN ('Resolved', 'Closed')
        GROUP BY priority
    """, as_dict=True)

    stats["by_priority"] = {p["priority"]: p["count"] for p in priorities}

    # By case type
    case_types = frappe.db.sql("""
        SELECT case_type, COUNT(*) as count
        FROM `tabModeration Case`
        WHERE status NOT IN ('Resolved', 'Closed')
        GROUP BY case_type
    """, as_dict=True)

    stats["by_case_type"] = {ct["case_type"]: ct["count"] for ct in case_types}

    # SLA breached
    stats["sla_breached"] = frappe.db.count(
        "Moderation Case",
        {
            "status": ["not in", ["Resolved", "Closed"]],
            "sla_status": "Breached"
        }
    )

    # Recent activity (last 7 days)
    seven_days_ago = add_days(nowdate(), -7)

    stats["created_7d"] = frappe.db.count(
        "Moderation Case",
        {"creation": (">=", seven_days_ago)}
    )

    stats["resolved_7d"] = frappe.db.count(
        "Moderation Case",
        {"review_completed_at": (">=", seven_days_ago)}
    )

    # Pending appeals
    stats["pending_appeals"] = frappe.db.count(
        "Moderation Case",
        {"appeal_status": ["in", ["Appeal Submitted", "Under Review"]]}
    )

    return stats


@frappe.whitelist()
def get_pending_appeals():
    """
    Get cases with pending appeals.

    Returns:
        list: Cases with pending appeals
    """
    if "System Manager" not in frappe.get_roles() and "Marketplace Admin" not in frappe.get_roles():
        frappe.throw(_("Not permitted to view pending appeals"))

    appeals = frappe.get_all(
        "Moderation Case",
        filters={
            "appeal_status": ["in", ["Appeal Submitted", "Under Review"]]
        },
        fields=[
            "name", "case_id", "content_type", "content_id", "content_title",
            "decision", "action_taken", "appeal_reason", "appeal_submitted_at"
        ],
        order_by="appeal_submitted_at asc"
    )

    return appeals


@frappe.whitelist()
def bulk_assign_cases(case_names, moderator):
    """
    Bulk assign cases to a moderator.

    Args:
        case_names: List of case names (JSON string)
        moderator: User to assign to

    Returns:
        dict: Result
    """
    if "System Manager" not in frappe.get_roles() and "Marketplace Admin" not in frappe.get_roles():
        frappe.throw(_("Not permitted to assign cases"))

    if isinstance(case_names, str):
        case_names = json.loads(case_names)

    assigned_count = 0
    for case_name in case_names:
        try:
            case_doc = frappe.get_doc("Moderation Case", case_name)
            if case_doc.status in ["Open", "Reopened"]:
                case_doc.assign_case(moderator)
                assigned_count += 1
        except Exception:
            pass

    return {
        "status": "success",
        "assigned_count": assigned_count,
        "message": _("{0} cases assigned to {1}").format(assigned_count, moderator)
    }


@frappe.whitelist()
def report_content(content_type, content_id, report_reason, description=None):
    """
    Public API to report content for moderation.

    Args:
        content_type: Type of content (Listing, Review, etc.)
        content_id: ID of the content
        report_reason: Reason for report
        description: Optional description

    Returns:
        dict: Result with case info
    """
    # Verify content exists
    if not frappe.db.exists(content_type, content_id):
        frappe.throw(_("Content not found"))

    # Check for duplicate recent reports from same user
    recent_report = frappe.db.exists(
        "Moderation Case",
        {
            "content_type": content_type,
            "content_id": content_id,
            "reporter": frappe.session.user,
            "status": ["not in", ["Resolved", "Closed"]],
            "creation": (">=", add_days(nowdate(), -7))
        }
    )

    if recent_report:
        frappe.throw(_("You have already reported this content recently"))

    # Create the case
    case_doc = frappe.get_doc({
        "doctype": "Moderation Case",
        "content_type": content_type,
        "content_id": content_id,
        "case_type": "Content Report",
        "report_source": "User Report",
        "reporter": frappe.session.user,
        "report_reason": report_reason,
        "report_description": description,
        "priority": "Medium"
    })

    case_doc.insert()

    return {
        "status": "success",
        "case_id": case_doc.case_id,
        "message": _("Thank you for your report. We will review it shortly.")
    }

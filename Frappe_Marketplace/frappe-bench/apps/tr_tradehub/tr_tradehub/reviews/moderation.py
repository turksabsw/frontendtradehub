# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

"""
Content Moderation Module

Handles content moderation workflow including:
- Case creation and assignment
- Auto-detection of policy violations
- Decision and action processing
- Appeal handling
- Escalation workflow
"""

import frappe
from frappe import _
from frappe.utils import now_datetime, add_to_date
from typing import Dict, Any, List, Optional
import json
import re


# Profanity and spam patterns (basic implementation)
PROFANITY_PATTERNS = [
    # Add actual patterns in production
    r'\b(spam|scam|fake)\b',
]

SPAM_INDICATORS = [
    r'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]){3,}',  # URLs
    r'\b\d{10,}\b',  # Long numbers (phone numbers)
    r'(.)\1{5,}',  # Repeated characters
]


def create_moderation_case(
    content_type: str,
    content_id: str,
    report_source: str = "User Report",
    reporter: str = None,
    report_reason: str = None,
    report_description: str = None,
    report_evidence: str = None,
    is_auto_detected: bool = False,
    detection_method: str = None,
    detection_confidence: float = None,
    detection_flags: List[str] = None,
    priority: str = "Medium"
) -> Dict[str, Any]:
    """
    Create a new moderation case.

    Args:
        content_type: DocType of content being reported
        content_id: Document name of content
        report_source: How the case was initiated
        reporter: User who reported (if applicable)
        report_reason: Main reason for report
        report_description: Detailed description
        report_evidence: Attached evidence file
        is_auto_detected: Whether auto-detected
        detection_method: Method used for auto-detection
        detection_confidence: Confidence level (0-100)
        detection_flags: List of flags raised
        priority: Case priority

    Returns:
        Created case details
    """
    try:
        # Get content details
        content_doc = frappe.get_doc(content_type, content_id)
        content_title = _get_content_title(content_doc)
        content_owner, content_owner_type = _get_content_owner(content_doc)

        # Check for existing open case
        existing = frappe.db.exists(
            "Moderation Case",
            {
                "content_type": content_type,
                "content_id": content_id,
                "status": ["not in", ["Resolved", "Closed"]]
            }
        )

        if existing:
            # Add to existing case notes instead of creating duplicate
            frappe.db.sql("""
                UPDATE `tabModeration Case`
                SET internal_notes = CONCAT(IFNULL(internal_notes, ''),
                    '\n\n[', NOW(), '] Additional report from ', %s, ': ', %s)
                WHERE name = %s
            """, (reporter or "System", report_description or report_reason, existing))
            frappe.db.commit()

            return {
                "success": True,
                "message": _("Report added to existing case"),
                "data": {"case": existing, "is_existing": True}
            }

        # Snapshot content for audit
        content_snapshot = _create_content_snapshot(content_doc)

        # Calculate priority based on factors
        calculated_priority = _calculate_priority(
            report_reason,
            is_auto_detected,
            detection_confidence,
            content_owner
        )

        # Create case
        case = frappe.get_doc({
            "doctype": "Moderation Case",
            "case_type": "Content Report" if reporter else "Proactive Review",
            "priority": calculated_priority or priority,
            "status": "Open",
            "content_type": content_type,
            "content_id": content_id,
            "content_title": content_title,
            "content_owner": content_owner,
            "content_owner_type": content_owner_type,
            "content_created_at": content_doc.creation,
            "content_snapshot": json.dumps(content_snapshot),
            "report_source": report_source,
            "reporter": reporter,
            "report_reason": report_reason,
            "report_description": report_description,
            "report_evidence": report_evidence,
            "is_auto_detected": is_auto_detected,
            "detection_method": detection_method,
            "detection_confidence": detection_confidence,
            "detection_flags": json.dumps(detection_flags) if detection_flags else None,
            "created_by_user": frappe.session.user,
            "creation_date": now_datetime(),
            "sla_target_hours": _get_sla_target(calculated_priority or priority)
        })

        # Check for repeat offender
        previous_violations = _get_previous_violations(content_owner, content_owner_type)
        if previous_violations > 0:
            case.is_repeat_offense = 1
            case.previous_violations_count = previous_violations

        case.insert(ignore_permissions=True)
        frappe.db.commit()

        # Auto-assign if queue is short
        _try_auto_assign(case.name)

        return {
            "success": True,
            "message": _("Moderation case created"),
            "data": {
                "case": case.name,
                "case_id": case.case_id,
                "priority": case.priority
            }
        }

    except Exception as e:
        frappe.log_error(f"Error creating moderation case: {str(e)}", "Moderation Case Creation")
        return {"success": False, "message": str(e)}


def assign_case(
    case_name: str,
    moderator: str,
    assigner: str = None
) -> Dict[str, Any]:
    """
    Assign a moderation case to a moderator.

    Args:
        case_name: Moderation Case document name
        moderator: User to assign to
        assigner: User making the assignment

    Returns:
        Success status
    """
    try:
        case = frappe.get_doc("Moderation Case", case_name)

        if case.status in ["Resolved", "Closed"]:
            return {"success": False, "message": _("Cannot assign closed cases")}

        case.assigned_to = moderator
        case.assigned_at = now_datetime()
        case.status = "Assigned"

        # Log assignment in history
        _add_to_history(case, "Assigned", f"Assigned to {moderator}", assigner)

        case.save(ignore_permissions=True)
        frappe.db.commit()

        # Notify moderator
        _notify_moderator(moderator, case.name, "New case assigned")

        return {"success": True, "message": _("Case assigned successfully")}

    except Exception as e:
        frappe.log_error(f"Error assigning case: {str(e)}", "Case Assignment")
        return {"success": False, "message": str(e)}


def resolve_case(
    case_name: str,
    decision: str,
    decision_reason: str = None,
    decision_notes: str = None,
    action_taken: str = "None",
    content_action: str = "No Change",
    warning_issued: bool = False
) -> Dict[str, Any]:
    """
    Resolve a moderation case.

    Args:
        case_name: Moderation Case document name
        decision: Final decision
        decision_reason: Brief reason
        decision_notes: Detailed notes
        action_taken: Action applied
        content_action: Action on content
        warning_issued: Whether warning was sent

    Returns:
        Success status
    """
    try:
        case = frappe.get_doc("Moderation Case", case_name)

        if case.status in ["Resolved", "Closed"]:
            return {"success": False, "message": _("Case is already resolved")}

        # Set decision fields
        case.decision = decision
        case.decision_reason = decision_reason
        case.decision_notes = decision_notes
        case.action_taken = action_taken
        case.content_action = content_action
        case.warning_issued = warning_issued
        case.status = "Resolved"
        case.reviewed_by = frappe.session.user
        case.review_completed_at = now_datetime()

        # Calculate review time
        if case.review_started_at:
            review_time = (case.review_completed_at - case.review_started_at).total_seconds()
            case.review_time_seconds = int(review_time)

        # Calculate resolution time
        if case.creation_date:
            resolution_hours = (case.review_completed_at - case.creation_date).total_seconds() / 3600
            case.resolution_time_hours = round(resolution_hours, 2)

        # Check SLA status
        if case.sla_target_hours and case.resolution_time_hours:
            if case.resolution_time_hours <= case.sla_target_hours:
                case.sla_status = "On Track"
            else:
                case.sla_status = "Breached"

        # Log decision
        _add_to_history(case, "Resolved", f"Decision: {decision}, Action: {action_taken}")

        case.save(ignore_permissions=True)

        # Execute content action
        if content_action != "No Change":
            _execute_content_action(case.content_type, case.content_id, content_action)

        # Send notifications
        _send_resolution_notifications(case)

        frappe.db.commit()

        return {
            "success": True,
            "message": _("Case resolved successfully"),
            "data": {
                "decision": decision,
                "action_taken": action_taken
            }
        }

    except Exception as e:
        frappe.log_error(f"Error resolving case: {str(e)}", "Case Resolution")
        return {"success": False, "message": str(e)}


def escalate_case(
    case_name: str,
    escalation_level: str,
    escalate_to: str = None,
    reason: str = None
) -> Dict[str, Any]:
    """
    Escalate a moderation case.

    Args:
        case_name: Moderation Case document name
        escalation_level: Level to escalate to
        escalate_to: Specific user to escalate to
        reason: Reason for escalation

    Returns:
        Success status
    """
    try:
        case = frappe.get_doc("Moderation Case", case_name)

        if case.status in ["Resolved", "Closed"]:
            return {"success": False, "message": _("Cannot escalate resolved cases")}

        case.is_escalated = 1
        case.escalation_level = escalation_level
        case.escalated_to = escalate_to
        case.escalation_reason = reason
        case.escalated_at = now_datetime()
        case.escalated_by = frappe.session.user
        case.status = "Escalated"

        # Update priority based on escalation
        if escalation_level in ["Level 4 - Legal", "Level 5 - Executive"]:
            case.priority = "Critical"
        elif escalation_level in ["Level 3 - Manager"]:
            case.priority = "High"

        _add_to_history(case, "Escalated", f"Escalated to {escalation_level}: {reason}")

        case.save(ignore_permissions=True)

        # Notify escalation target
        if escalate_to:
            _notify_moderator(escalate_to, case.name, f"Escalated case: {reason}")

        frappe.db.commit()

        return {"success": True, "message": _("Case escalated successfully")}

    except Exception as e:
        frappe.log_error(f"Error escalating case: {str(e)}", "Case Escalation")
        return {"success": False, "message": str(e)}


def submit_appeal(
    case_name: str,
    appellant: str,
    appeal_reason: str,
    appeal_evidence: str = None
) -> Dict[str, Any]:
    """
    Submit an appeal for a moderation decision.

    Args:
        case_name: Moderation Case document name
        appellant: User submitting the appeal
        appeal_reason: Reason for appeal
        appeal_evidence: Supporting evidence

    Returns:
        Success status
    """
    try:
        case = frappe.get_doc("Moderation Case", case_name)

        if not case.is_appealable:
            return {"success": False, "message": _("This decision cannot be appealed")}

        if case.appeal_status and case.appeal_status != "Not Appealed":
            return {"success": False, "message": _("An appeal has already been submitted")}

        # Verify appellant is content owner
        content_owner_user = _get_content_owner_user(case.content_owner, case.content_owner_type)
        if content_owner_user != appellant:
            return {"success": False, "message": _("Only the content owner can appeal")}

        case.appeal_status = "Appeal Submitted"
        case.appeal_submitted_at = now_datetime()
        case.appeal_reason = appeal_reason
        case.appeal_evidence = appeal_evidence
        case.status = "Appealed"

        _add_to_history(case, "Appeal Submitted", f"Appeal reason: {appeal_reason}")

        case.save(ignore_permissions=True)
        frappe.db.commit()

        return {
            "success": True,
            "message": _("Appeal submitted successfully")
        }

    except Exception as e:
        frappe.log_error(f"Error submitting appeal: {str(e)}", "Appeal Submission")
        return {"success": False, "message": str(e)}


def auto_check_content(
    content: str,
    title: str = None,
    content_type: str = None
) -> Dict[str, Any]:
    """
    Automatically check content for policy violations.

    Args:
        content: Main content text
        title: Title text
        content_type: Type of content

    Returns:
        Check result with flags
    """
    flags = []
    flagged = False
    confidence = 0
    detection_method = "Text Analysis"

    text_to_check = f"{title or ''} {content}"

    # Check for profanity patterns
    for pattern in PROFANITY_PATTERNS:
        if re.search(pattern, text_to_check, re.IGNORECASE):
            flags.append("profanity")
            flagged = True
            confidence = max(confidence, 80)

    # Check for spam indicators
    spam_count = 0
    for pattern in SPAM_INDICATORS:
        matches = re.findall(pattern, text_to_check)
        spam_count += len(matches)

    if spam_count >= 3:
        flags.append("spam_indicators")
        flagged = True
        confidence = max(confidence, 70)

    # Check for excessive caps (shouting)
    if len(text_to_check) > 20:
        caps_ratio = sum(1 for c in text_to_check if c.isupper()) / len(text_to_check)
        if caps_ratio > 0.5:
            flags.append("excessive_caps")
            flagged = True
            confidence = max(confidence, 60)

    # Check for short/low-effort content
    if content_type == "Review" and len(content.strip()) < 20:
        flags.append("low_effort")
        flagged = True
        confidence = max(confidence, 50)

    return {
        "flagged": flagged,
        "flags": flags,
        "confidence": confidence,
        "detection_method": detection_method,
        "reason": ", ".join(flags) if flags else None
    }


# Helper functions

def _get_content_title(doc) -> str:
    """Get title field from content document."""
    title_fields = ["title", "name", "subject", "case_id", "review_id"]
    for field in title_fields:
        if hasattr(doc, field) and getattr(doc, field):
            return str(getattr(doc, field))[:200]
    return doc.name


def _get_content_owner(doc) -> tuple:
    """Get content owner and owner type from document."""
    owner_fields = [
        ("seller", "Seller Profile"),
        ("reviewer", "User"),
        ("owner", "User"),
        ("user", "User")
    ]

    for field, owner_type in owner_fields:
        if hasattr(doc, field) and getattr(doc, field):
            return getattr(doc, field), owner_type

    return doc.owner, "User"


def _get_content_owner_user(content_owner: str, owner_type: str) -> str:
    """Get user account for content owner."""
    if owner_type == "User":
        return content_owner
    elif owner_type == "Seller Profile":
        return frappe.db.get_value("Seller Profile", content_owner, "user")
    return None


def _create_content_snapshot(doc) -> Dict[str, Any]:
    """Create a snapshot of content for audit purposes."""
    snapshot = {
        "doctype": doc.doctype,
        "name": doc.name,
        "creation": str(doc.creation),
        "modified": str(doc.modified),
        "snapshot_at": str(now_datetime())
    }

    # Add relevant fields based on doctype
    if doc.doctype == "Review":
        snapshot["rating"] = doc.rating
        snapshot["title"] = doc.title
        snapshot["review_text"] = doc.review_text
        snapshot["reviewer"] = doc.reviewer
    elif doc.doctype == "Listing":
        snapshot["title"] = doc.title
        snapshot["description"] = doc.description[:1000] if doc.description else None
        snapshot["seller"] = doc.seller

    return snapshot


def _calculate_priority(
    reason: str,
    is_auto: bool,
    confidence: float,
    owner: str
) -> str:
    """Calculate case priority based on factors."""
    critical_reasons = [
        "Counterfeit Product", "Safety Concern", "Legal Issue",
        "Fraud/Scam", "Violent Content"
    ]
    high_reasons = [
        "Intellectual Property Violation", "Harassment", "Hate Speech",
        "Privacy Violation"
    ]

    if reason in critical_reasons:
        return "Critical"
    elif reason in high_reasons:
        return "High"
    elif is_auto and confidence and confidence >= 90:
        return "High"

    return "Medium"


def _get_sla_target(priority: str) -> float:
    """Get SLA target hours based on priority."""
    sla_targets = {
        "Critical": 4,
        "High": 12,
        "Medium": 24,
        "Low": 48
    }
    return sla_targets.get(priority, 24)


def _get_previous_violations(owner: str, owner_type: str) -> int:
    """Count previous violations by content owner."""
    if not owner:
        return 0

    return frappe.db.count(
        "Moderation Case",
        {
            "content_owner": owner,
            "content_owner_type": owner_type,
            "decision": ["in", ["Rejected", "Removed", "Account Action"]],
            "status": ["in", ["Resolved", "Closed"]]
        }
    )


def _try_auto_assign(case_name: str):
    """Try to auto-assign case to available moderator."""
    # Get moderators with least cases
    moderators = frappe.get_all(
        "User",
        filters={
            "enabled": 1,
            "name": ["in", frappe.get_all(
                "Has Role",
                filters={"role": "Marketplace Moderator"},
                pluck="parent"
            )]
        },
        pluck="name"
    )

    if not moderators:
        return

    # Find moderator with least open cases
    min_cases = float('inf')
    best_moderator = None

    for mod in moderators:
        case_count = frappe.db.count(
            "Moderation Case",
            {"assigned_to": mod, "status": ["in", ["Assigned", "In Review"]]}
        )
        if case_count < min_cases:
            min_cases = case_count
            best_moderator = mod

    # Auto-assign if moderator has few cases
    if best_moderator and min_cases < 10:
        assign_case(case_name, best_moderator)


def _add_to_history(case, action: str, details: str, user: str = None):
    """Add entry to moderation history."""
    history = json.loads(case.moderation_history or "[]")
    history.append({
        "timestamp": str(now_datetime()),
        "action": action,
        "details": details,
        "user": user or frappe.session.user
    })
    case.moderation_history = json.dumps(history)


def _execute_content_action(content_type: str, content_id: str, action: str):
    """Execute action on the content."""
    try:
        doc = frappe.get_doc(content_type, content_id)

        if action == "Remove":
            doc.status = "Removed"
        elif action == "Hide":
            doc.status = "Hidden"
            if hasattr(doc, "is_visible"):
                doc.is_visible = 0
        elif action == "Restrict Visibility":
            if hasattr(doc, "is_visible"):
                doc.is_visible = 0
        elif action == "Add Warning Label":
            if hasattr(doc, "moderation_notes"):
                doc.moderation_notes = "Warning: This content may violate community guidelines"
        elif action == "Restore":
            doc.status = "Published" if hasattr(doc, "status") else "Active"
            if hasattr(doc, "is_visible"):
                doc.is_visible = 1

        doc.save(ignore_permissions=True)

    except Exception as e:
        frappe.log_error(f"Error executing content action: {str(e)}", "Content Action")


def _send_resolution_notifications(case):
    """Send notifications about case resolution."""
    # Notify content owner
    owner_user = _get_content_owner_user(case.content_owner, case.content_owner_type)
    if owner_user:
        frappe.get_doc({
            "doctype": "Notification Log",
            "for_user": owner_user,
            "type": "Alert",
            "document_type": "Moderation Case",
            "document_name": case.name,
            "subject": _("Moderation Decision"),
            "email_content": _(
                "A moderation decision has been made regarding your content. "
                "Decision: {0}. {1}"
            ).format(case.decision, case.decision_reason or "")
        }).insert(ignore_permissions=True)
        case.owner_notified = 1
        case.owner_notified_at = now_datetime()

    # Notify reporter if applicable
    if case.reporter:
        frappe.get_doc({
            "doctype": "Notification Log",
            "for_user": case.reporter,
            "type": "Alert",
            "document_type": "Moderation Case",
            "document_name": case.name,
            "subject": _("Report Reviewed"),
            "email_content": _(
                "Your report has been reviewed. Thank you for helping keep our platform safe."
            )
        }).insert(ignore_permissions=True)
        case.reporter_notified = 1
        case.reporter_notified_at = now_datetime()

    case.decision_notification_sent = 1


def _notify_moderator(moderator: str, case_name: str, message: str):
    """Send notification to moderator."""
    frappe.get_doc({
        "doctype": "Notification Log",
        "for_user": moderator,
        "type": "Alert",
        "document_type": "Moderation Case",
        "document_name": case_name,
        "subject": _("Moderation Case"),
        "email_content": message
    }).insert(ignore_permissions=True)

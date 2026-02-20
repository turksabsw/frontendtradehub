# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

"""
Admin & Governance API Endpoints for TR-TradeHub Marketplace

This module provides API endpoints for platform administration including:
- Account Action management (warnings, restrictions, bans)
- Content Moderation workflow
- Platform statistics and dashboards
- Seller management operations
- Listing moderation
- Commission and rule management
- System health and audit logs

API URL Pattern:
    POST /api/method/tr_tradehub.api.v1.admin.<function_name>

All endpoints require admin-level permissions (System Manager or Marketplace Admin).
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
    get_datetime,
)


# =============================================================================
# CONSTANTS & CONFIGURATION
# =============================================================================

# Rate limiting settings (per admin user)
RATE_LIMITS = {
    "account_action_create": {"limit": 50, "window": 3600},  # 50 per hour
    "bulk_operation": {"limit": 20, "window": 3600},  # 20 per hour
    "export": {"limit": 10, "window": 3600},  # 10 per hour
    "moderation_resolve": {"limit": 100, "window": 3600},  # 100 per hour
}

# Admin roles
ADMIN_ROLES = ["System Manager", "Marketplace Admin"]
MODERATOR_ROLES = ["System Manager", "Marketplace Admin", "Marketplace Moderator"]


# =============================================================================
# PERMISSION HELPERS
# =============================================================================


def check_admin_permission(throw: bool = True) -> bool:
    """
    Check if current user has admin permission.

    Args:
        throw: If True, raises exception when not permitted

    Returns:
        bool: True if permitted

    Raises:
        frappe.PermissionError: If throw=True and not permitted
    """
    user_roles = frappe.get_roles()
    has_permission = any(role in user_roles for role in ADMIN_ROLES)

    if not has_permission and throw:
        frappe.throw(
            _("You do not have permission to access admin functions"),
            exc=frappe.PermissionError,
        )

    return has_permission


def check_moderator_permission(throw: bool = True) -> bool:
    """
    Check if current user has moderator permission.

    Args:
        throw: If True, raises exception when not permitted

    Returns:
        bool: True if permitted
    """
    user_roles = frappe.get_roles()
    has_permission = any(role in user_roles for role in MODERATOR_ROLES)

    if not has_permission and throw:
        frappe.throw(
            _("You do not have permission to access moderation functions"),
            exc=frappe.PermissionError,
        )

    return has_permission


def check_rate_limit(
    action: str,
    identifier: Optional[str] = None,
    throw: bool = True,
) -> bool:
    """
    Check if an action is rate limited.

    Args:
        action: The action to check
        identifier: User identifier (defaults to session user)
        throw: If True, raises exception when rate limited

    Returns:
        bool: True if allowed, False if rate limited
    """
    if action not in RATE_LIMITS:
        return True

    config = RATE_LIMITS[action]

    if not identifier:
        identifier = frappe.session.user or "unknown"

    cache_key = f"rate_limit:admin:{action}:{identifier}"

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
# ACCOUNT ACTION ENDPOINTS
# =============================================================================


@frappe.whitelist()
def create_account_action(
    action_type: str,
    target_type: str,
    target_id: str,
    reason: str,
    severity: str = "Medium",
    reason_code: Optional[str] = None,
    detailed_reason: Optional[str] = None,
    duration_days: Optional[int] = None,
    is_permanent: bool = False,
    restrictions: Optional[str] = None,
    is_appealable: bool = True,
) -> Dict[str, Any]:
    """
    Create a new account action (warning, restriction, ban, etc.).

    Args:
        action_type: Type of action (Warning, Restriction, Suspension, Temporary Ban, Permanent Ban, Account Termination)
        target_type: Type of target (User, Seller Profile, Organization)
        target_id: ID of the target account
        reason: Brief reason for the action
        severity: Severity level (Low, Medium, High, Critical)
        reason_code: Standardized reason code for categorization
        detailed_reason: Full explanation of the action
        duration_days: Duration in days for temporary actions
        is_permanent: Whether the action is permanent
        restrictions: JSON string of specific restrictions to apply
        is_appealable: Whether the action can be appealed

    Returns:
        dict: Result with action name and details

    Example:
        POST /api/method/tr_tradehub.api.v1.admin.create_account_action
        {
            "action_type": "Warning",
            "target_type": "Seller Profile",
            "target_id": "SP-001",
            "reason": "Policy violation",
            "severity": "Medium"
        }
    """
    check_admin_permission()
    check_rate_limit("account_action_create")

    # Validate required fields
    if not action_type:
        frappe.throw(_("Action type is required"))
    if not target_type:
        frappe.throw(_("Target type is required"))
    if not target_id:
        frappe.throw(_("Target ID is required"))
    if not reason:
        frappe.throw(_("Reason is required"))

    # Validate action type
    valid_action_types = [
        "Warning", "Restriction", "Suspension",
        "Temporary Ban", "Permanent Ban", "Account Termination"
    ]
    if action_type not in valid_action_types:
        frappe.throw(_("Invalid action type: {0}").format(action_type))

    # Validate target type
    valid_target_types = ["User", "Seller Profile", "Organization"]
    if target_type not in valid_target_types:
        frappe.throw(_("Invalid target type: {0}").format(target_type))

    # Validate target exists
    if target_type == "User":
        if not frappe.db.exists("User", target_id):
            frappe.throw(_("User {0} does not exist").format(target_id))
    elif target_type == "Seller Profile":
        if not frappe.db.exists("Seller Profile", target_id):
            frappe.throw(_("Seller Profile {0} does not exist").format(target_id))
    elif target_type == "Organization":
        if not frappe.db.exists("Organization", target_id):
            frappe.throw(_("Organization {0} does not exist").format(target_id))

    # Build document data
    doc_data = {
        "doctype": "Account Action",
        "action_type": action_type,
        "target_type": target_type,
        "severity": severity,
        "reason": reason,
        "reason_code": reason_code,
        "detailed_reason": detailed_reason,
        "is_permanent": cint(is_permanent),
        "is_appealable": cint(is_appealable),
        "start_date": now_datetime(),
        "status": "Active",
    }

    # Set target field
    if target_type == "User":
        doc_data["user"] = target_id
    elif target_type == "Seller Profile":
        doc_data["seller_profile"] = target_id
    elif target_type == "Organization":
        doc_data["organization"] = target_id

    # Set duration
    if not is_permanent and duration_days:
        doc_data["end_date"] = add_days(nowdate(), cint(duration_days))
        doc_data["auto_lift"] = 1

    # Parse and set restrictions
    if restrictions:
        try:
            if isinstance(restrictions, str):
                restrictions = json.loads(restrictions)
            for key, value in restrictions.items():
                if key.startswith("restrict_"):
                    doc_data[key] = cint(value)
        except (json.JSONDecodeError, TypeError):
            frappe.throw(_("Invalid restrictions format"))

    action = frappe.get_doc(doc_data)
    action.insert()

    _log_admin_event("account_action_created", {
        "action": action.name,
        "action_type": action_type,
        "target_type": target_type,
        "target_id": target_id,
    })

    return {
        "success": True,
        "action_name": action.name,
        "action_type": action.action_type,
        "status": action.status,
        "message": _("Account action created successfully"),
    }


@frappe.whitelist()
def get_account_action(action_name: str) -> Dict[str, Any]:
    """
    Get details of an account action.

    Args:
        action_name: Name of the account action

    Returns:
        dict: Account action details
    """
    check_admin_permission()

    if not frappe.db.exists("Account Action", action_name):
        frappe.throw(_("Account action not found"))

    action = frappe.get_doc("Account Action", action_name)
    return action.get_action_summary()


@frappe.whitelist()
def list_account_actions(
    target_type: Optional[str] = None,
    target_id: Optional[str] = None,
    status: Optional[str] = None,
    action_type: Optional[str] = None,
    severity: Optional[str] = None,
    active_only: bool = False,
    limit: int = 50,
    offset: int = 0,
) -> Dict[str, Any]:
    """
    List account actions with filtering options.

    Args:
        target_type: Filter by target type
        target_id: Filter by target ID
        status: Filter by status
        action_type: Filter by action type
        severity: Filter by severity
        active_only: Only return active actions
        limit: Maximum number of results
        offset: Starting offset

    Returns:
        dict: List of account actions and pagination info
    """
    check_admin_permission()

    filters = {}

    if target_type:
        filters["target_type"] = target_type
        if target_id:
            if target_type == "User":
                filters["user"] = target_id
            elif target_type == "Seller Profile":
                filters["seller_profile"] = target_id
            elif target_type == "Organization":
                filters["organization"] = target_id

    if status:
        filters["status"] = status
    elif active_only:
        filters["status"] = "Active"

    if action_type:
        filters["action_type"] = action_type

    if severity:
        filters["severity"] = severity

    total_count = frappe.db.count("Account Action", filters)

    actions = frappe.get_all(
        "Account Action",
        filters=filters,
        fields=[
            "name", "action_type", "severity", "status", "reason", "reason_code",
            "target_type", "user", "seller_profile", "organization",
            "start_date", "end_date", "is_permanent", "is_appealable",
            "appeal_status", "created_by_user", "creation",
        ],
        order_by="creation desc",
        limit_page_length=cint(limit),
        limit_start=cint(offset),
    )

    return {
        "success": True,
        "actions": actions,
        "total": total_count,
        "limit": limit,
        "offset": offset,
    }


@frappe.whitelist()
def lift_account_action(
    action_name: str,
    reason: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Lift (end early) an account action.

    Args:
        action_name: Name of the account action
        reason: Reason for lifting the action

    Returns:
        dict: Result of the operation
    """
    check_admin_permission()

    if not frappe.db.exists("Account Action", action_name):
        frappe.throw(_("Account action not found"))

    action = frappe.get_doc("Account Action", action_name)
    result = action.lift_action(reason=reason)

    _log_admin_event("account_action_lifted", {
        "action": action_name,
        "reason": reason,
    })

    return result


@frappe.whitelist()
def review_account_action_appeal(
    action_name: str,
    decision: str,
    status: str,
    response: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Review an appeal for an account action.

    Args:
        action_name: Name of the account action
        decision: Decision text
        status: Appeal status (Approved, Rejected, Partially Approved)
        response: Response to send to the user

    Returns:
        dict: Result of the operation
    """
    check_admin_permission()

    if not frappe.db.exists("Account Action", action_name):
        frappe.throw(_("Account action not found"))

    action = frappe.get_doc("Account Action", action_name)
    result = action.review_appeal(decision=decision, response=response, status=status)

    _log_admin_event("account_action_appeal_reviewed", {
        "action": action_name,
        "status": status,
        "decision": decision,
    })

    return result


@frappe.whitelist()
def get_account_action_statistics() -> Dict[str, Any]:
    """
    Get comprehensive account action statistics for admin dashboard.

    Returns:
        dict: Statistics including counts, breakdowns, and trends
    """
    check_admin_permission()

    stats = {
        "total": frappe.db.count("Account Action"),
        "active": frappe.db.count("Account Action", {"status": "Active"}),
        "pending_approval": frappe.db.count("Account Action", {"status": "Pending Approval"}),
        "appealed": frappe.db.count("Account Action", {"status": "Appealed"}),
        "lifted": frappe.db.count("Account Action", {"status": "Lifted"}),
        "overturned": frappe.db.count("Account Action", {"status": "Overturned"}),
    }

    # Actions by type (active only)
    action_types = frappe.db.sql("""
        SELECT action_type, COUNT(*) as count
        FROM `tabAccount Action`
        WHERE status = 'Active'
        GROUP BY action_type
        ORDER BY count DESC
    """, as_dict=True)

    stats["by_type"] = {at["action_type"]: at["count"] for at in action_types}

    # Actions by severity (active only)
    severities = frappe.db.sql("""
        SELECT severity, COUNT(*) as count
        FROM `tabAccount Action`
        WHERE status = 'Active'
        GROUP BY severity
    """, as_dict=True)

    stats["by_severity"] = {s["severity"]: s["count"] for s in severities}

    # Actions by target type (active only)
    target_types = frappe.db.sql("""
        SELECT target_type, COUNT(*) as count
        FROM `tabAccount Action`
        WHERE status = 'Active'
        GROUP BY target_type
    """, as_dict=True)

    stats["by_target_type"] = {tt["target_type"]: tt["count"] for tt in target_types}

    # Recent activity (last 30 days)
    thirty_days_ago = add_days(nowdate(), -30)

    stats["created_30d"] = frappe.db.count(
        "Account Action",
        {"creation": (">=", thirty_days_ago)}
    )

    stats["lifted_30d"] = frappe.db.count(
        "Account Action",
        {"lifted_at": (">=", thirty_days_ago)}
    )

    stats["pending_appeals"] = frappe.db.count(
        "Account Action",
        {"appeal_status": ["in", ["Appeal Submitted", "Under Review"]]}
    )

    # Trend data (daily for last 14 days)
    trend_data = frappe.db.sql("""
        SELECT DATE(creation) as date, COUNT(*) as count
        FROM `tabAccount Action`
        WHERE creation >= DATE_SUB(NOW(), INTERVAL 14 DAY)
        GROUP BY DATE(creation)
        ORDER BY date ASC
    """, as_dict=True)

    stats["trend"] = [{"date": str(t["date"]), "count": t["count"]} for t in trend_data]

    return stats


@frappe.whitelist()
def get_pending_account_action_appeals() -> List[Dict[str, Any]]:
    """
    Get all account actions with pending appeals.

    Returns:
        list: Account actions with pending appeals
    """
    check_admin_permission()

    appeals = frappe.get_all(
        "Account Action",
        filters={
            "appeal_status": ["in", ["Appeal Submitted", "Under Review"]]
        },
        fields=[
            "name", "action_type", "severity", "target_type", "user",
            "seller_profile", "organization", "reason", "appeal_reason",
            "appeal_submitted_at", "appeal_status", "appeal_evidence",
        ],
        order_by="appeal_submitted_at asc"
    )

    return appeals


# =============================================================================
# MODERATION CASE ENDPOINTS
# =============================================================================


@frappe.whitelist()
def get_moderation_queue(
    status: Optional[str] = None,
    priority: Optional[str] = None,
    case_type: Optional[str] = None,
    assigned_to: Optional[str] = None,
    content_type: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> Dict[str, Any]:
    """
    Get moderation case queue with filtering.

    Args:
        status: Filter by status
        priority: Filter by priority
        case_type: Filter by case type
        assigned_to: Filter by assignee
        content_type: Filter by content type
        limit: Maximum results
        offset: Starting offset

    Returns:
        dict: List of moderation cases and pagination info
    """
    check_moderator_permission()

    filters = {}

    if status:
        filters["status"] = status
    else:
        filters["status"] = ["in", ["Open", "Assigned", "In Review", "Pending Info", "Escalated"]]

    if priority:
        filters["priority"] = priority

    if case_type:
        filters["case_type"] = case_type

    if assigned_to:
        filters["assigned_to"] = assigned_to

    if content_type:
        filters["content_type"] = content_type

    total_count = frappe.db.count("Moderation Case", filters)

    cases = frappe.get_all(
        "Moderation Case",
        filters=filters,
        fields=[
            "name", "case_id", "case_type", "priority", "status",
            "content_type", "content_id", "content_title", "content_owner",
            "report_reason", "assigned_to", "is_escalated", "is_repeat_offense",
            "sla_status", "sla_target_hours", "creation_date", "queue_position",
        ],
        order_by="FIELD(priority, 'Critical', 'High', 'Medium', 'Low'), creation asc",
        limit_page_length=cint(limit),
        limit_start=cint(offset),
    )

    return {
        "success": True,
        "cases": cases,
        "total": total_count,
        "limit": limit,
        "offset": offset,
    }


@frappe.whitelist()
def get_moderation_case(case_name: str) -> Dict[str, Any]:
    """
    Get detailed moderation case information.

    Args:
        case_name: Name or case_id of the moderation case

    Returns:
        dict: Case details including history
    """
    check_moderator_permission()

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

    # Get full case data
    case_data = case_doc.get_case_summary()

    # Add additional details for admin view
    case_data.update({
        "content_snapshot": json.loads(case_doc.content_snapshot or "{}"),
        "report_description": case_doc.report_description,
        "report_source": case_doc.report_source,
        "reporter": case_doc.reporter,
        "decision_reason": case_doc.decision_reason,
        "decision_notes": case_doc.decision_notes,
        "content_action": case_doc.content_action,
        "escalation_level": case_doc.escalation_level,
        "escalation_reason": case_doc.escalation_reason,
        "escalated_to": case_doc.escalated_to,
        "wait_time_hours": case_doc.wait_time_hours,
        "resolution_time_hours": case_doc.resolution_time_hours,
        "review_time_seconds": case_doc.review_time_seconds,
        "history": json.loads(case_doc.moderation_history or "[]"),
    })

    return case_data


@frappe.whitelist()
def assign_moderation_case(
    case_name: str,
    moderator: str,
) -> Dict[str, Any]:
    """
    Assign a moderation case to a moderator.

    Args:
        case_name: Name of the case
        moderator: User to assign to

    Returns:
        dict: Result
    """
    check_admin_permission()

    if not frappe.db.exists("Moderation Case", case_name):
        frappe.throw(_("Moderation case not found"))

    if not frappe.db.exists("User", moderator):
        frappe.throw(_("User {0} does not exist").format(moderator))

    case_doc = frappe.get_doc("Moderation Case", case_name)
    result = case_doc.assign_case(moderator)

    _log_admin_event("moderation_case_assigned", {
        "case": case_name,
        "assigned_to": moderator,
    })

    return result


@frappe.whitelist()
def start_moderation_review(case_name: str) -> Dict[str, Any]:
    """
    Start review of a moderation case.

    Args:
        case_name: Name of the case

    Returns:
        dict: Result
    """
    check_moderator_permission()

    if not frappe.db.exists("Moderation Case", case_name):
        frappe.throw(_("Moderation case not found"))

    case_doc = frappe.get_doc("Moderation Case", case_name)
    return case_doc.start_review()


@frappe.whitelist()
def resolve_moderation_case(
    case_name: str,
    decision: str,
    decision_reason: Optional[str] = None,
    action_taken: Optional[str] = None,
    content_action: Optional[str] = None,
    decision_notes: Optional[str] = None,
    violation_type: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Resolve a moderation case with a decision.

    Args:
        case_name: Name of the case
        decision: Decision (Violation Confirmed, No Violation, Inconclusive)
        decision_reason: Reason for the decision
        action_taken: Action taken (Warning Issued, Content Removed, Account Action, etc.)
        content_action: Action applied to content (Remove, Hide, Delist, No Change, Restore)
        decision_notes: Additional notes
        violation_type: Type of violation if confirmed

    Returns:
        dict: Result
    """
    check_moderator_permission()
    check_rate_limit("moderation_resolve")

    if not frappe.db.exists("Moderation Case", case_name):
        frappe.throw(_("Moderation case not found"))

    case_doc = frappe.get_doc("Moderation Case", case_name)

    # Update violation type if provided
    if violation_type:
        case_doc.violation_type = violation_type

    result = case_doc.resolve_case(
        decision=decision,
        decision_reason=decision_reason,
        action_taken=action_taken,
        content_action=content_action,
        decision_notes=decision_notes,
    )

    _log_admin_event("moderation_case_resolved", {
        "case": case_name,
        "decision": decision,
        "action_taken": action_taken,
    })

    return result


@frappe.whitelist()
def escalate_moderation_case(
    case_name: str,
    escalation_level: str,
    escalated_to: str,
    reason: str,
) -> Dict[str, Any]:
    """
    Escalate a moderation case to a higher level.

    Args:
        case_name: Name of the case
        escalation_level: Level to escalate to (L1, L2, L3, Legal, Executive)
        escalated_to: User to escalate to
        reason: Reason for escalation

    Returns:
        dict: Result
    """
    check_moderator_permission()

    if not frappe.db.exists("Moderation Case", case_name):
        frappe.throw(_("Moderation case not found"))

    case_doc = frappe.get_doc("Moderation Case", case_name)
    result = case_doc.escalate_case(escalation_level, escalated_to, reason)

    _log_admin_event("moderation_case_escalated", {
        "case": case_name,
        "level": escalation_level,
        "escalated_to": escalated_to,
    })

    return result


@frappe.whitelist()
def review_moderation_appeal(
    case_name: str,
    status: str,
    decision: str,
    response: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Review an appeal for a moderation case.

    Args:
        case_name: Name of the case
        status: Appeal status (Approved, Rejected, Partially Approved)
        decision: Decision text
        response: Response to content owner

    Returns:
        dict: Result
    """
    check_admin_permission()

    if not frappe.db.exists("Moderation Case", case_name):
        frappe.throw(_("Moderation case not found"))

    case_doc = frappe.get_doc("Moderation Case", case_name)
    result = case_doc.review_appeal(status, decision, response)

    _log_admin_event("moderation_appeal_reviewed", {
        "case": case_name,
        "status": status,
    })

    return result


@frappe.whitelist()
def bulk_assign_moderation_cases(
    case_names: str,
    moderator: str,
) -> Dict[str, Any]:
    """
    Bulk assign moderation cases to a moderator.

    Args:
        case_names: JSON array of case names
        moderator: User to assign to

    Returns:
        dict: Result with count of assigned cases
    """
    check_admin_permission()
    check_rate_limit("bulk_operation")

    if isinstance(case_names, str):
        case_names = json.loads(case_names)

    if not frappe.db.exists("User", moderator):
        frappe.throw(_("User {0} does not exist").format(moderator))

    assigned_count = 0
    failed = []

    for case_name in case_names:
        try:
            if frappe.db.exists("Moderation Case", case_name):
                case_doc = frappe.get_doc("Moderation Case", case_name)
                if case_doc.status in ["Open", "Reopened"]:
                    case_doc.assign_case(moderator)
                    assigned_count += 1
                else:
                    failed.append({"case": case_name, "reason": f"Invalid status: {case_doc.status}"})
            else:
                failed.append({"case": case_name, "reason": "Not found"})
        except Exception as e:
            failed.append({"case": case_name, "reason": str(e)})

    _log_admin_event("moderation_cases_bulk_assigned", {
        "moderator": moderator,
        "assigned_count": assigned_count,
        "total_requested": len(case_names),
    })

    return {
        "success": True,
        "assigned_count": assigned_count,
        "failed": failed,
        "message": _("{0} cases assigned to {1}").format(assigned_count, moderator),
    }


@frappe.whitelist()
def get_moderation_statistics() -> Dict[str, Any]:
    """
    Get comprehensive moderation statistics for admin dashboard.

    Returns:
        dict: Statistics including counts, breakdowns, and performance metrics
    """
    check_admin_permission()

    stats = {
        "total": frappe.db.count("Moderation Case"),
        "open": frappe.db.count("Moderation Case", {"status": "Open"}),
        "assigned": frappe.db.count("Moderation Case", {"status": "Assigned"}),
        "in_review": frappe.db.count("Moderation Case", {"status": "In Review"}),
        "pending_info": frappe.db.count("Moderation Case", {"status": "Pending Info"}),
        "escalated": frappe.db.count("Moderation Case", {"status": "Escalated"}),
        "resolved": frappe.db.count("Moderation Case", {"status": "Resolved"}),
        "closed": frappe.db.count("Moderation Case", {"status": "Closed"}),
        "appealed": frappe.db.count("Moderation Case", {"status": "Appealed"}),
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

    # By content type
    content_types = frappe.db.sql("""
        SELECT content_type, COUNT(*) as count
        FROM `tabModeration Case`
        WHERE status NOT IN ('Resolved', 'Closed')
        GROUP BY content_type
    """, as_dict=True)

    stats["by_content_type"] = {ct["content_type"]: ct["count"] for ct in content_types}

    # SLA metrics
    stats["sla_on_track"] = frappe.db.count(
        "Moderation Case",
        {"status": ["not in", ["Resolved", "Closed"]], "sla_status": "On Track"}
    )
    stats["sla_at_risk"] = frappe.db.count(
        "Moderation Case",
        {"status": ["not in", ["Resolved", "Closed"]], "sla_status": "At Risk"}
    )
    stats["sla_breached"] = frappe.db.count(
        "Moderation Case",
        {"status": ["not in", ["Resolved", "Closed"]], "sla_status": "Breached"}
    )

    # Pending appeals
    stats["pending_appeals"] = frappe.db.count(
        "Moderation Case",
        {"appeal_status": ["in", ["Appeal Submitted", "Under Review"]]}
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

    # Average resolution time (last 30 days, in hours)
    avg_resolution = frappe.db.sql("""
        SELECT AVG(resolution_time_hours) as avg_hours
        FROM `tabModeration Case`
        WHERE status IN ('Resolved', 'Closed')
        AND review_completed_at >= DATE_SUB(NOW(), INTERVAL 30 DAY)
    """, as_dict=True)

    stats["avg_resolution_hours"] = flt(avg_resolution[0]["avg_hours"], 2) if avg_resolution else 0

    # Moderator performance (last 7 days)
    moderator_stats = frappe.db.sql("""
        SELECT reviewed_by, COUNT(*) as count
        FROM `tabModeration Case`
        WHERE status IN ('Resolved', 'Closed')
        AND review_completed_at >= DATE_SUB(NOW(), INTERVAL 7 DAY)
        AND reviewed_by IS NOT NULL
        GROUP BY reviewed_by
        ORDER BY count DESC
        LIMIT 10
    """, as_dict=True)

    stats["moderator_performance"] = moderator_stats

    return stats


@frappe.whitelist()
def get_pending_moderation_appeals() -> List[Dict[str, Any]]:
    """
    Get all moderation cases with pending appeals.

    Returns:
        list: Cases with pending appeals
    """
    check_admin_permission()

    appeals = frappe.get_all(
        "Moderation Case",
        filters={
            "appeal_status": ["in", ["Appeal Submitted", "Under Review"]]
        },
        fields=[
            "name", "case_id", "content_type", "content_id", "content_title",
            "content_owner", "decision", "action_taken", "content_action",
            "appeal_reason", "appeal_evidence", "appeal_submitted_at",
        ],
        order_by="appeal_submitted_at asc"
    )

    return appeals


# =============================================================================
# PLATFORM DASHBOARD ENDPOINTS
# =============================================================================


@frappe.whitelist()
def get_platform_statistics() -> Dict[str, Any]:
    """
    Get comprehensive platform statistics for admin dashboard.

    Returns:
        dict: Platform-wide statistics
    """
    check_admin_permission()

    stats = {}

    # User statistics
    stats["users"] = {
        "total": frappe.db.count("User", {"user_type": "Website User"}),
        "active_30d": frappe.db.count(
            "User",
            {"last_login": (">=", add_days(nowdate(), -30))}
        ),
    }

    # Seller statistics
    if frappe.db.exists("DocType", "Seller Profile"):
        stats["sellers"] = {
            "total": frappe.db.count("Seller Profile"),
            "active": frappe.db.count("Seller Profile", {"status": "Active"}),
            "pending_verification": frappe.db.count("Seller Profile", {"verification_status": "Pending"}),
            "suspended": frappe.db.count("Seller Profile", {"status": "Suspended"}),
        }

    # Seller applications
    if frappe.db.exists("DocType", "Seller Application"):
        stats["seller_applications"] = {
            "total": frappe.db.count("Seller Application"),
            "pending": frappe.db.count("Seller Application", {"status": "Submitted"}),
            "under_review": frappe.db.count("Seller Application", {"status": "Under Review"}),
            "approved_30d": frappe.db.count(
                "Seller Application",
                {
                    "status": "Approved",
                    "modified": (">=", add_days(nowdate(), -30))
                }
            ),
        }

    # Listing statistics
    if frappe.db.exists("DocType", "Listing"):
        stats["listings"] = {
            "total": frappe.db.count("Listing"),
            "active": frappe.db.count("Listing", {"status": "Active"}),
            "pending_moderation": frappe.db.count("Listing", {"moderation_status": "Pending Review"}),
            "created_30d": frappe.db.count(
                "Listing",
                {"creation": (">=", add_days(nowdate(), -30))}
            ),
        }

    # Order statistics
    if frappe.db.exists("DocType", "Marketplace Order"):
        stats["orders"] = {
            "total": frappe.db.count("Marketplace Order"),
            "pending": frappe.db.count("Marketplace Order", {"status": "Pending"}),
            "processing": frappe.db.count("Marketplace Order", {"status": "Processing"}),
            "completed_30d": frappe.db.count(
                "Marketplace Order",
                {
                    "status": "Completed",
                    "modified": (">=", add_days(nowdate(), -30))
                }
            ),
        }

        # GMV (Gross Merchandise Value) - last 30 days
        gmv_result = frappe.db.sql("""
            SELECT COALESCE(SUM(grand_total), 0) as gmv
            FROM `tabMarketplace Order`
            WHERE status NOT IN ('Cancelled', 'Refunded')
            AND creation >= DATE_SUB(NOW(), INTERVAL 30 DAY)
        """, as_dict=True)

        stats["orders"]["gmv_30d"] = flt(gmv_result[0]["gmv"], 2) if gmv_result else 0

    # Review statistics
    if frappe.db.exists("DocType", "Review"):
        stats["reviews"] = {
            "total": frappe.db.count("Review"),
            "pending_moderation": frappe.db.count("Review", {"moderation_status": "Pending Review"}),
            "created_30d": frappe.db.count(
                "Review",
                {"creation": (">=", add_days(nowdate(), -30))}
            ),
        }

        # Average rating
        avg_rating = frappe.db.sql("""
            SELECT AVG(rating) as avg_rating
            FROM `tabReview`
            WHERE status = 'Published'
        """, as_dict=True)

        stats["reviews"]["avg_rating"] = flt(avg_rating[0]["avg_rating"], 2) if avg_rating else 0

    # Moderation statistics
    if frappe.db.exists("DocType", "Moderation Case"):
        stats["moderation"] = {
            "open_cases": frappe.db.count("Moderation Case", {"status": ["in", ["Open", "Assigned", "In Review"]]}),
            "sla_breached": frappe.db.count("Moderation Case", {"sla_status": "Breached", "status": ["not in", ["Resolved", "Closed"]]}),
        }

    # Account actions
    if frappe.db.exists("DocType", "Account Action"):
        stats["account_actions"] = {
            "active": frappe.db.count("Account Action", {"status": "Active"}),
            "pending_appeals": frappe.db.count("Account Action", {"appeal_status": ["in", ["Appeal Submitted", "Under Review"]]}),
        }

    return {
        "success": True,
        "statistics": stats,
        "generated_at": str(now_datetime()),
    }


@frappe.whitelist()
def get_activity_feed(limit: int = 50) -> List[Dict[str, Any]]:
    """
    Get recent platform activity feed for admin dashboard.

    Args:
        limit: Maximum number of activities

    Returns:
        list: Recent activities
    """
    check_admin_permission()

    activities = []

    # Recent moderation cases
    if frappe.db.exists("DocType", "Moderation Case"):
        mod_cases = frappe.get_all(
            "Moderation Case",
            fields=["name", "case_id", "case_type", "status", "content_type", "creation"],
            order_by="creation desc",
            limit_page_length=10,
        )
        for case in mod_cases:
            activities.append({
                "type": "moderation_case",
                "title": f"Moderation Case {case.case_id}",
                "description": f"{case.case_type} - {case.content_type}",
                "status": case.status,
                "timestamp": case.creation,
                "link": f"/app/moderation-case/{case.name}",
            })

    # Recent account actions
    if frappe.db.exists("DocType", "Account Action"):
        actions = frappe.get_all(
            "Account Action",
            fields=["name", "action_type", "target_type", "status", "severity", "creation"],
            order_by="creation desc",
            limit_page_length=10,
        )
        for action in actions:
            activities.append({
                "type": "account_action",
                "title": f"{action.action_type} Action",
                "description": f"Target: {action.target_type} - {action.severity}",
                "status": action.status,
                "timestamp": action.creation,
                "link": f"/app/account-action/{action.name}",
            })

    # Recent seller applications
    if frappe.db.exists("DocType", "Seller Application"):
        applications = frappe.get_all(
            "Seller Application",
            fields=["name", "business_name", "status", "creation"],
            order_by="creation desc",
            limit_page_length=10,
        )
        for app in applications:
            activities.append({
                "type": "seller_application",
                "title": f"Seller Application: {app.business_name}",
                "description": f"Status: {app.status}",
                "status": app.status,
                "timestamp": app.creation,
                "link": f"/app/seller-application/{app.name}",
            })

    # Sort all activities by timestamp
    activities.sort(key=lambda x: x["timestamp"], reverse=True)

    return activities[:cint(limit)]


# =============================================================================
# SELLER MANAGEMENT ENDPOINTS
# =============================================================================


@frappe.whitelist()
def list_sellers(
    status: Optional[str] = None,
    verification_status: Optional[str] = None,
    seller_type: Optional[str] = None,
    search: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> Dict[str, Any]:
    """
    List sellers with filtering options.

    Args:
        status: Filter by status
        verification_status: Filter by verification status
        seller_type: Filter by seller type
        search: Search term for seller name
        limit: Maximum results
        offset: Starting offset

    Returns:
        dict: List of sellers and pagination info
    """
    check_admin_permission()

    if not frappe.db.exists("DocType", "Seller Profile"):
        return {"success": True, "sellers": [], "total": 0}

    filters = {}

    if status:
        filters["status"] = status

    if verification_status:
        filters["verification_status"] = verification_status

    if seller_type:
        filters["seller_type"] = seller_type

    if search:
        filters["seller_name"] = ["like", f"%{search}%"]

    total_count = frappe.db.count("Seller Profile", filters)

    sellers = frappe.get_all(
        "Seller Profile",
        filters=filters,
        fields=[
            "name", "seller_name", "display_name", "seller_type", "status",
            "verification_status", "seller_tier", "seller_score", "average_rating",
            "total_reviews", "total_sales_count", "city", "country",
            "can_sell", "can_withdraw", "is_restricted", "creation",
        ],
        order_by="creation desc",
        limit_page_length=cint(limit),
        limit_start=cint(offset),
    )

    return {
        "success": True,
        "sellers": sellers,
        "total": total_count,
        "limit": limit,
        "offset": offset,
    }


@frappe.whitelist()
def update_seller_status(
    seller_name: str,
    status: str,
    reason: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Update seller profile status.

    Args:
        seller_name: Name of the seller profile
        status: New status
        reason: Reason for status change

    Returns:
        dict: Result
    """
    check_admin_permission()

    if not frappe.db.exists("Seller Profile", seller_name):
        frappe.throw(_("Seller profile not found"))

    valid_statuses = ["Active", "Suspended", "Restricted", "Banned", "Pending Verification"]
    if status not in valid_statuses:
        frappe.throw(_("Invalid status: {0}").format(status))

    seller = frappe.get_doc("Seller Profile", seller_name)
    old_status = seller.status
    seller.status = status

    if status == "Suspended":
        seller.can_sell = 0
        seller.can_create_listings = 0
    elif status == "Restricted":
        seller.is_restricted = 1
        seller.restriction_reason = reason
    elif status == "Active":
        seller.can_sell = 1
        seller.can_create_listings = 1
        seller.is_restricted = 0
        seller.restriction_reason = None

    seller.save(ignore_permissions=True)

    _log_admin_event("seller_status_changed", {
        "seller": seller_name,
        "old_status": old_status,
        "new_status": status,
        "reason": reason,
    })

    return {
        "success": True,
        "message": _("Seller status updated to {0}").format(status),
        "seller": seller_name,
        "status": status,
    }


@frappe.whitelist()
def verify_seller(
    seller_name: str,
    verification_status: str,
    notes: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Update seller verification status.

    Args:
        seller_name: Name of the seller profile
        verification_status: New verification status
        notes: Verification notes

    Returns:
        dict: Result
    """
    check_admin_permission()

    if not frappe.db.exists("Seller Profile", seller_name):
        frappe.throw(_("Seller profile not found"))

    valid_statuses = ["Not Verified", "Pending", "Verified", "Rejected"]
    if verification_status not in valid_statuses:
        frappe.throw(_("Invalid verification status: {0}").format(verification_status))

    seller = frappe.get_doc("Seller Profile", seller_name)
    seller.verification_status = verification_status

    if verification_status == "Verified":
        seller.verified_at = now_datetime()
        seller.verified_by = frappe.session.user

    seller.save(ignore_permissions=True)

    _log_admin_event("seller_verified", {
        "seller": seller_name,
        "verification_status": verification_status,
        "notes": notes,
    })

    return {
        "success": True,
        "message": _("Seller verification status updated to {0}").format(verification_status),
        "seller": seller_name,
        "verification_status": verification_status,
    }


# =============================================================================
# LISTING MODERATION ENDPOINTS
# =============================================================================


@frappe.whitelist()
def list_pending_listings(
    limit: int = 50,
    offset: int = 0,
) -> Dict[str, Any]:
    """
    List listings pending moderation.

    Args:
        limit: Maximum results
        offset: Starting offset

    Returns:
        dict: List of pending listings
    """
    check_moderator_permission()

    if not frappe.db.exists("DocType", "Listing"):
        return {"success": True, "listings": [], "total": 0}

    filters = {"moderation_status": "Pending Review"}

    total_count = frappe.db.count("Listing", filters)

    listings = frappe.get_all(
        "Listing",
        filters=filters,
        fields=[
            "name", "listing_code", "title", "seller", "category",
            "base_price", "selling_price", "status", "moderation_status",
            "creation", "quality_score",
        ],
        order_by="creation asc",
        limit_page_length=cint(limit),
        limit_start=cint(offset),
    )

    return {
        "success": True,
        "listings": listings,
        "total": total_count,
        "limit": limit,
        "offset": offset,
    }


@frappe.whitelist()
def moderate_listing(
    listing_name: str,
    action: str,
    reason: Optional[str] = None,
    notes: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Moderate a listing (approve, reject, flag).

    Args:
        listing_name: Name of the listing
        action: Action to take (approve, reject, flag, request_changes)
        reason: Reason for the action
        notes: Additional notes

    Returns:
        dict: Result
    """
    check_moderator_permission()

    if not frappe.db.exists("Listing", listing_name):
        frappe.throw(_("Listing not found"))

    valid_actions = ["approve", "reject", "flag", "request_changes"]
    if action not in valid_actions:
        frappe.throw(_("Invalid action: {0}").format(action))

    listing = frappe.get_doc("Listing", listing_name)

    if action == "approve":
        if hasattr(listing, "approve"):
            listing.approve()
        else:
            listing.moderation_status = "Approved"
            listing.status = "Active"
    elif action == "reject":
        if hasattr(listing, "reject"):
            listing.reject(reason)
        else:
            listing.moderation_status = "Rejected"
            listing.moderation_notes = reason
    elif action == "flag":
        if hasattr(listing, "flag"):
            listing.flag(reason)
        else:
            listing.moderation_status = "Flagged"
            listing.moderation_notes = reason
    elif action == "request_changes":
        listing.moderation_status = "Changes Requested"
        listing.moderation_notes = notes

    listing.save(ignore_permissions=True)

    _log_admin_event("listing_moderated", {
        "listing": listing_name,
        "action": action,
        "reason": reason,
    })

    return {
        "success": True,
        "message": _("Listing {0}").format(action),
        "listing": listing_name,
        "moderation_status": listing.moderation_status,
    }


@frappe.whitelist()
def bulk_moderate_listings(
    listing_names: str,
    action: str,
    reason: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Bulk moderate listings.

    Args:
        listing_names: JSON array of listing names
        action: Action to take
        reason: Reason for the action

    Returns:
        dict: Result with counts
    """
    check_moderator_permission()
    check_rate_limit("bulk_operation")

    if isinstance(listing_names, str):
        listing_names = json.loads(listing_names)

    success_count = 0
    failed = []

    for listing_name in listing_names:
        try:
            result = moderate_listing(listing_name, action, reason)
            if result.get("success"):
                success_count += 1
            else:
                failed.append({"listing": listing_name, "reason": "Unknown error"})
        except Exception as e:
            failed.append({"listing": listing_name, "reason": str(e)})

    return {
        "success": True,
        "moderated_count": success_count,
        "failed": failed,
        "message": _("{0} listings {1}").format(success_count, action),
    }


# =============================================================================
# AUDIT LOG ENDPOINTS
# =============================================================================


@frappe.whitelist()
def get_audit_logs(
    user: Optional[str] = None,
    operation: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
) -> Dict[str, Any]:
    """
    Get admin audit logs.

    Args:
        user: Filter by user
        operation: Filter by operation type
        start_date: Start date filter
        end_date: End date filter
        limit: Maximum results
        offset: Starting offset

    Returns:
        dict: Audit log entries
    """
    check_admin_permission()

    filters = {"operation": ["like", "admin_%"]}

    if user:
        filters["user"] = user

    if operation:
        filters["operation"] = operation

    if start_date:
        filters["creation"] = (">=", start_date)

    if end_date:
        if "creation" in filters:
            filters["creation"] = ["between", [start_date, end_date]]
        else:
            filters["creation"] = ("<=", end_date)

    total_count = frappe.db.count("Activity Log", filters)

    logs = frappe.get_all(
        "Activity Log",
        filters=filters,
        fields=[
            "name", "user", "operation", "status", "content",
            "ip_address", "creation",
        ],
        order_by="creation desc",
        limit_page_length=cint(limit),
        limit_start=cint(offset),
    )

    # Parse content JSON
    for log in logs:
        if log.get("content"):
            try:
                log["content"] = json.loads(log["content"])
            except (json.JSONDecodeError, TypeError):
                pass

    return {
        "success": True,
        "logs": logs,
        "total": total_count,
        "limit": limit,
        "offset": offset,
    }


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================


def _log_admin_event(
    event_type: str,
    details: Dict[str, Any],
) -> None:
    """Log admin-related events for audit trail."""
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
                "user": frappe.session.user,
                "operation": f"admin_{event_type}",
                "status": "Success",
                "content": frappe.as_json(details),
                "ip_address": ip_address,
            }
        ).insert(ignore_permissions=True)
    except Exception as e:
        frappe.log_error(f"Admin event logging error: {str(e)}", "Admin API")


# =============================================================================
# PUBLIC API SUMMARY
# =============================================================================

"""
Public API Endpoints:

Account Actions:
- create_account_action: Create warning, restriction, ban, etc.
- get_account_action: Get action details
- list_account_actions: List actions with filters
- lift_account_action: End action early
- review_account_action_appeal: Review appeal
- get_account_action_statistics: Dashboard stats
- get_pending_account_action_appeals: List pending appeals

Moderation Cases:
- get_moderation_queue: Get moderation queue
- get_moderation_case: Get case details
- assign_moderation_case: Assign to moderator
- start_moderation_review: Start review
- resolve_moderation_case: Resolve with decision
- escalate_moderation_case: Escalate case
- review_moderation_appeal: Review appeal
- bulk_assign_moderation_cases: Bulk assign
- get_moderation_statistics: Dashboard stats
- get_pending_moderation_appeals: List pending appeals

Platform Dashboard:
- get_platform_statistics: Comprehensive stats
- get_activity_feed: Recent activity feed

Seller Management:
- list_sellers: List sellers with filters
- update_seller_status: Update seller status
- verify_seller: Update verification status

Listing Moderation:
- list_pending_listings: List pending moderation
- moderate_listing: Approve/reject/flag listing
- bulk_moderate_listings: Bulk moderation

Audit:
- get_audit_logs: Get admin audit logs
"""

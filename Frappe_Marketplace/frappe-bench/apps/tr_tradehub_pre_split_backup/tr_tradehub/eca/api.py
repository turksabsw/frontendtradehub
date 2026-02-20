# Copyright (c) 2026, TR TradeHub and contributors
# For license information, please see license.txt

"""
ECA API Endpoints

Provides whitelisted API endpoints for Event-Condition-Action operations.
All endpoints use @frappe.whitelist() decorator for external access.

Endpoints:
    - get_rules_for_doctype: GET active rules for a DocType
    - test_rule: POST test rule against document without executing actions
    - get_rule_execution_log: GET rule execution history
"""

import json
from typing import Any, Dict, List, Optional, Union

import frappe
from frappe import _
from frappe.utils import cint, now_datetime, get_datetime, add_days

# Import ECA dispatcher functions
from tr_tradehub.eca.dispatcher import (
    ECADispatcher,
    get_rules_for_doctype as _get_rules_for_doctype,
    test_rule as _test_rule
)


@frappe.whitelist()
def get_rules_for_doctype(
    doctype: str,
    event_type: Optional[str] = None,
    include_conditions: bool = False,
    include_actions: bool = False
) -> List[Dict]:
    """
    Get all active ECA rules for a specific DocType.

    Args:
        doctype: DocType name to get rules for
        event_type: Optional event type filter (after_save, on_submit, etc.)
        include_conditions: If True, include rule conditions in response
        include_actions: If True, include rule actions in response

    Returns:
        list: List of rule dictionaries with:
            - name: Rule document name
            - rule_name: Human-readable rule name
            - rule_code: Unique rule code
            - event_type: Event that triggers the rule
            - condition_logic: AND/OR/Custom
            - priority: Execution priority
            - is_active: Active status
            - description: Rule description
            - conditions: List of conditions (if include_conditions=True)
            - actions: List of actions (if include_actions=True)
    """
    # Get base rule data
    rules = _get_rules_for_doctype(doctype, event_type)

    if not cint(include_conditions) and not cint(include_actions):
        return rules

    # Enhance with conditions and/or actions
    enhanced_rules = []

    for rule_data in rules:
        rule_name = rule_data.get("name")
        try:
            rule_doc = frappe.get_doc("ECA Rule", rule_name)

            enhanced = dict(rule_data)
            enhanced["description"] = rule_doc.description

            if cint(include_conditions):
                conditions = []
                for cond in rule_doc.conditions:
                    conditions.append({
                        "field_name": cond.field_name,
                        "operator": cond.operator,
                        "value": cond.value,
                        "value_type": cond.value_type,
                        "logic_operator": cond.logic_operator
                    })
                enhanced["conditions"] = conditions
                enhanced["jinja_condition"] = rule_doc.jinja_condition
                enhanced["python_condition"] = rule_doc.python_condition

            if cint(include_actions):
                actions = []
                for action in rule_doc.actions:
                    actions.append({
                        "action_type": action.action_type,
                        "is_active": action.is_active,
                        "execution_order": action.execution_order,
                        "action_template": action.action_template,
                        "description": action.description,
                        "stop_on_error": action.stop_on_error,
                        "async_execution": action.async_execution
                    })
                enhanced["actions"] = actions

            enhanced_rules.append(enhanced)

        except frappe.DoesNotExistError:
            # Rule was deleted, skip it
            continue

    return enhanced_rules


@frappe.whitelist()
def test_rule(
    rule: str,
    document: str,
    evaluate_only: bool = True
) -> Dict:
    """
    Test an ECA rule against a specific document without executing actions.

    This is useful for testing rule conditions before activating the rule,
    or for debugging why a rule is/isn't triggering.

    Args:
        rule: ECA Rule name or rule_code
        document: Document name to test against
        evaluate_only: If True (default), only evaluate conditions, don't execute actions
            If False, actually execute actions (use with caution)

    Returns:
        dict: Test results including:
            - rule: Rule name
            - document: Document name
            - doctype: Document type
            - condition_result: Boolean result of all conditions
            - condition_details: Detailed results per condition
            - would_execute: Whether actions would execute (if rule were active)
            - actions_preview: List of actions that would execute
            - execution_result: Actual execution result (if evaluate_only=False)
    """
    # Resolve rule by name or code
    try:
        rule_doc = frappe.get_doc("ECA Rule", rule)
    except frappe.DoesNotExistError:
        # Try by rule_code
        rule_name = frappe.db.get_value("ECA Rule", {"rule_code": rule}, "name")
        if not rule_name:
            frappe.throw(_("ECA Rule '{0}' not found").format(rule), frappe.DoesNotExistError)
        rule_doc = frappe.get_doc("ECA Rule", rule_name)

    # Get the document
    try:
        doc = frappe.get_doc(rule_doc.event_doctype, document)
    except frappe.DoesNotExistError:
        frappe.throw(_("Document '{0}' of type '{1}' not found").format(
            document, rule_doc.event_doctype
        ), frappe.DoesNotExistError)

    # Create dispatcher for testing
    dispatcher = ECADispatcher(doc, rule_doc.event_type)

    # Evaluate conditions
    condition_result, condition_details = dispatcher._evaluate_conditions(rule_doc)

    result = {
        "rule": rule_doc.name,
        "rule_name": rule_doc.rule_name,
        "document": doc.name,
        "doctype": doc.doctype,
        "event_type": rule_doc.event_type,
        "condition_result": condition_result,
        "condition_details": condition_details,
        "would_execute": condition_result and rule_doc.is_active,
        "rule_is_active": rule_doc.is_active
    }

    # Add actions preview
    actions_preview = []
    for action in rule_doc.actions:
        if action.is_active:
            actions_preview.append({
                "action_type": action.action_type,
                "execution_order": action.execution_order,
                "description": action.description or action.action_type,
                "stop_on_error": action.stop_on_error,
                "async_execution": action.async_execution
            })
    result["actions_preview"] = actions_preview

    # Execute actions if requested (and conditions pass)
    if not cint(evaluate_only) and condition_result:
        # Set flag to prevent circular triggers
        original_flag = getattr(frappe.flags, 'in_eca_execution', False)
        try:
            frappe.flags.in_eca_execution = True
            action_results = dispatcher._execute_actions(rule_doc)
            result["execution_result"] = {
                "executed": True,
                "actions_executed": len(action_results),
                "actions_succeeded": sum(1 for a in action_results if a.get('success')),
                "actions_failed": sum(1 for a in action_results if not a.get('success')),
                "action_results": action_results
            }
        finally:
            frappe.flags.in_eca_execution = original_flag
    else:
        result["execution_result"] = {
            "executed": False,
            "reason": "evaluate_only mode" if cint(evaluate_only) else "conditions not met"
        }

    return result


@frappe.whitelist()
def get_rule_execution_log(
    rule: Optional[str] = None,
    doctype: Optional[str] = None,
    document: Optional[str] = None,
    status: Optional[str] = None,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
    order_by: str = "trigger_time desc"
) -> Dict:
    """
    Get ECA rule execution logs with filtering.

    Args:
        rule: Optional ECA Rule name to filter by
        doctype: Optional DocType to filter by
        document: Optional document name to filter by
        status: Optional status filter (Success, Failed, Partial, Error, Skipped)
        from_date: Optional start date filter (YYYY-MM-DD)
        to_date: Optional end date filter (YYYY-MM-DD)
        limit: Maximum number of records to return (default 100, max 500)
        offset: Number of records to skip for pagination
        order_by: Order by clause (default: trigger_time desc)

    Returns:
        dict: Execution log data including:
            - total: Total matching records
            - limit: Applied limit
            - offset: Applied offset
            - logs: List of log entries
            - summary: Aggregate statistics
    """
    # Validate and sanitize limit
    limit = min(cint(limit) or 100, 500)
    offset = cint(offset) or 0

    # Build filters
    filters = {}

    if rule:
        filters["eca_rule"] = rule

    if doctype:
        filters["trigger_doctype"] = doctype

    if document:
        filters["trigger_document"] = document

    if status:
        filters["status"] = status

    if from_date:
        try:
            from_dt = get_datetime(from_date)
            filters["trigger_time"] = [">=", from_dt]
        except Exception:
            pass

    if to_date:
        try:
            to_dt = get_datetime(to_date)
            # Handle date range properly
            if from_date and "trigger_time" in filters:
                filters["trigger_time"] = ["between", [get_datetime(from_date), to_dt]]
            else:
                filters["trigger_time"] = ["<=", to_dt]
        except Exception:
            pass

    # Validate order_by to prevent SQL injection
    allowed_order_fields = [
        "trigger_time", "execution_time_ms", "status",
        "eca_rule", "trigger_doctype", "trigger_document"
    ]
    order_parts = order_by.lower().split()
    if len(order_parts) >= 1 and order_parts[0] in allowed_order_fields:
        safe_order = order_by
    else:
        safe_order = "trigger_time desc"

    # Get total count
    total = frappe.db.count("ECA Rule Log", filters=filters)

    # Get logs
    logs = frappe.get_all(
        "ECA Rule Log",
        filters=filters,
        fields=[
            "name",
            "eca_rule",
            "status",
            "trigger_doctype",
            "trigger_document",
            "trigger_event",
            "trigger_user",
            "trigger_time",
            "execution_time_ms",
            "condition_result",
            "actions_executed",
            "actions_succeeded",
            "actions_failed",
            "error_message"
        ],
        order_by=safe_order,
        limit_start=offset,
        limit_page_length=limit
    )

    # Enhance logs with rule names
    for log in logs:
        if log.get("eca_rule"):
            rule_name = frappe.db.get_value("ECA Rule", log["eca_rule"], "rule_name")
            log["rule_name"] = rule_name

        # Format trigger_time as string for JSON serialization
        if log.get("trigger_time"):
            log["trigger_time"] = str(log["trigger_time"])

    # Calculate summary statistics
    summary = _get_execution_summary(filters)

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "logs": logs,
        "summary": summary
    }


def _get_execution_summary(filters: Dict) -> Dict:
    """
    Calculate aggregate statistics for execution logs.

    Args:
        filters: Filters to apply to the summary query

    Returns:
        dict: Summary statistics
    """
    summary = {
        "total_executions": 0,
        "by_status": {},
        "avg_execution_time_ms": 0,
        "total_actions_executed": 0,
        "total_actions_succeeded": 0,
        "total_actions_failed": 0
    }

    try:
        # Get status counts
        status_counts = frappe.get_all(
            "ECA Rule Log",
            filters=filters,
            fields=["status", "count(*) as count"],
            group_by="status"
        )

        for sc in status_counts:
            summary["by_status"][sc.status] = sc.count
            summary["total_executions"] += sc.count

        # Get average execution time and action counts
        if summary["total_executions"] > 0:
            agg_data = frappe.db.sql("""
                SELECT
                    AVG(execution_time_ms) as avg_time,
                    SUM(actions_executed) as total_executed,
                    SUM(actions_succeeded) as total_succeeded,
                    SUM(actions_failed) as total_failed
                FROM `tabECA Rule Log`
                WHERE 1=1
            """, as_dict=True)

            if agg_data and agg_data[0]:
                summary["avg_execution_time_ms"] = round(agg_data[0].get("avg_time") or 0, 2)
                summary["total_actions_executed"] = cint(agg_data[0].get("total_executed"))
                summary["total_actions_succeeded"] = cint(agg_data[0].get("total_succeeded"))
                summary["total_actions_failed"] = cint(agg_data[0].get("total_failed"))

    except Exception:
        # Return empty summary on error
        pass

    return summary


@frappe.whitelist()
def get_rule_log_detail(log_name: str) -> Dict:
    """
    Get detailed information for a specific execution log entry.

    Args:
        log_name: ECA Rule Log document name

    Returns:
        dict: Complete log entry with condition and action details
    """
    try:
        log_doc = frappe.get_doc("ECA Rule Log", log_name)
    except frappe.DoesNotExistError:
        frappe.throw(_("Log entry '{0}' not found").format(log_name), frappe.DoesNotExistError)

    result = {
        "name": log_doc.name,
        "eca_rule": log_doc.eca_rule,
        "status": log_doc.status,
        "trigger_doctype": log_doc.trigger_doctype,
        "trigger_document": log_doc.trigger_document,
        "trigger_event": log_doc.trigger_event,
        "trigger_user": log_doc.trigger_user,
        "trigger_time": str(log_doc.trigger_time) if log_doc.trigger_time else None,
        "execution_time_ms": log_doc.execution_time_ms,
        "condition_result": log_doc.condition_result,
        "actions_executed": log_doc.actions_executed,
        "actions_succeeded": log_doc.actions_succeeded,
        "actions_failed": log_doc.actions_failed,
        "error_message": log_doc.error_message
    }

    # Parse condition details
    if log_doc.condition_details:
        try:
            result["condition_details"] = json.loads(log_doc.condition_details)
        except json.JSONDecodeError:
            result["condition_details"] = log_doc.condition_details

    # Parse action results
    if log_doc.action_results:
        try:
            result["action_results"] = json.loads(log_doc.action_results)
        except json.JSONDecodeError:
            result["action_results"] = log_doc.action_results

    # Add rule name
    if log_doc.eca_rule:
        rule_name = frappe.db.get_value("ECA Rule", log_doc.eca_rule, "rule_name")
        result["rule_name"] = rule_name

    # Add user full name
    if log_doc.trigger_user:
        user_name = frappe.db.get_value("User", log_doc.trigger_user, "full_name")
        result["trigger_user_name"] = user_name

    return result


@frappe.whitelist()
def get_rule_statistics(rule: str, days: int = 30) -> Dict:
    """
    Get execution statistics for a specific ECA rule.

    Args:
        rule: ECA Rule name
        days: Number of days to include in statistics (default 30)

    Returns:
        dict: Rule statistics including:
            - total_executions: Total execution count
            - success_rate: Percentage of successful executions
            - avg_execution_time_ms: Average execution time
            - executions_by_day: Daily execution counts
            - status_breakdown: Count per status
            - top_trigger_documents: Most frequently triggered documents
    """
    # Verify rule exists
    if not frappe.db.exists("ECA Rule", rule):
        frappe.throw(_("ECA Rule '{0}' not found").format(rule), frappe.DoesNotExistError)

    from_date = add_days(now_datetime(), -cint(days))

    # Get basic counts
    total = frappe.db.count(
        "ECA Rule Log",
        filters={
            "eca_rule": rule,
            "trigger_time": [">=", from_date]
        }
    )

    success_count = frappe.db.count(
        "ECA Rule Log",
        filters={
            "eca_rule": rule,
            "trigger_time": [">=", from_date],
            "status": "Success"
        }
    )

    result = {
        "rule": rule,
        "period_days": cint(days),
        "total_executions": total,
        "success_count": success_count,
        "success_rate": round((success_count / total * 100) if total > 0 else 0, 2)
    }

    # Get average execution time
    avg_time = frappe.db.sql("""
        SELECT AVG(execution_time_ms) as avg_time
        FROM `tabECA Rule Log`
        WHERE eca_rule = %s AND trigger_time >= %s
    """, (rule, from_date), as_dict=True)

    result["avg_execution_time_ms"] = round(avg_time[0].avg_time or 0, 2) if avg_time else 0

    # Get status breakdown
    status_counts = frappe.get_all(
        "ECA Rule Log",
        filters={
            "eca_rule": rule,
            "trigger_time": [">=", from_date]
        },
        fields=["status", "count(*) as count"],
        group_by="status"
    )
    result["status_breakdown"] = {sc.status: sc.count for sc in status_counts}

    # Get daily execution counts
    daily_counts = frappe.db.sql("""
        SELECT DATE(trigger_time) as date, COUNT(*) as count
        FROM `tabECA Rule Log`
        WHERE eca_rule = %s AND trigger_time >= %s
        GROUP BY DATE(trigger_time)
        ORDER BY date ASC
    """, (rule, from_date), as_dict=True)

    result["executions_by_day"] = [
        {"date": str(dc.date), "count": dc.count}
        for dc in daily_counts
    ]

    # Get top triggered documents
    top_docs = frappe.get_all(
        "ECA Rule Log",
        filters={
            "eca_rule": rule,
            "trigger_time": [">=", from_date]
        },
        fields=["trigger_document", "trigger_doctype", "count(*) as count"],
        group_by="trigger_document, trigger_doctype",
        order_by="count desc",
        limit=10
    )
    result["top_trigger_documents"] = top_docs

    return result


@frappe.whitelist()
def clear_execution_logs(
    rule: Optional[str] = None,
    older_than_days: int = 30,
    dry_run: bool = True
) -> Dict:
    """
    Clear old execution logs for a specific rule or all rules.

    Args:
        rule: Optional ECA Rule name to clear logs for (all rules if not specified)
        older_than_days: Delete logs older than this many days (default 30)
        dry_run: If True (default), only return count without deleting

    Returns:
        dict: Result with count of logs deleted/would be deleted
    """
    if cint(older_than_days) < 1:
        frappe.throw(_("older_than_days must be at least 1"))

    cutoff_date = add_days(now_datetime(), -cint(older_than_days))

    filters = {
        "trigger_time": ["<", cutoff_date]
    }

    if rule:
        filters["eca_rule"] = rule

    count = frappe.db.count("ECA Rule Log", filters=filters)

    result = {
        "logs_found": count,
        "older_than_days": cint(older_than_days),
        "cutoff_date": str(cutoff_date),
        "dry_run": cint(dry_run)
    }

    if not cint(dry_run):
        # Actually delete the logs
        frappe.db.delete("ECA Rule Log", filters=filters)
        frappe.db.commit()
        result["logs_deleted"] = count
        result["message"] = f"Deleted {count} log entries older than {older_than_days} days"
    else:
        result["logs_deleted"] = 0
        result["message"] = f"Would delete {count} log entries older than {older_than_days} days (dry run)"

    return result


@frappe.whitelist()
def get_available_event_types() -> List[Dict]:
    """
    Get list of available event types for ECA rules.

    Returns:
        list: Available event types with descriptions
    """
    return [
        {"value": "before_insert", "label": "Before Insert", "description": "Triggered before a new document is inserted"},
        {"value": "after_insert", "label": "After Insert", "description": "Triggered after a new document is inserted"},
        {"value": "validate", "label": "Validate", "description": "Triggered during document validation"},
        {"value": "before_save", "label": "Before Save", "description": "Triggered before a document is saved"},
        {"value": "after_save", "label": "After Save", "description": "Triggered after a document is saved"},
        {"value": "on_update", "label": "On Update", "description": "Triggered when a document is updated"},
        {"value": "on_submit", "label": "On Submit", "description": "Triggered when a document is submitted"},
        {"value": "on_cancel", "label": "On Cancel", "description": "Triggered when a document is cancelled"},
        {"value": "on_trash", "label": "On Trash", "description": "Triggered when a document is deleted"},
        {"value": "on_update_after_submit", "label": "On Update After Submit", "description": "Triggered when a submitted document is modified"},
        {"value": "before_rename", "label": "Before Rename", "description": "Triggered before a document is renamed"},
        {"value": "after_rename", "label": "After Rename", "description": "Triggered after a document is renamed"},
        {"value": "on_change", "label": "On Change", "description": "Triggered on any document change"}
    ]


@frappe.whitelist()
def get_available_action_types() -> List[Dict]:
    """
    Get list of available action types for ECA rules.

    Returns:
        list: Available action types with descriptions
    """
    return [
        {"value": "Send Email", "label": "Send Email", "description": "Send an email using a template"},
        {"value": "System Notification", "label": "System Notification", "description": "Send a system notification to users"},
        {"value": "Webhook", "label": "Webhook", "description": "Make an HTTP request to an external URL"},
        {"value": "Set Field", "label": "Set Field", "description": "Update a field value on the document"},
        {"value": "Create Document", "label": "Create Document", "description": "Create a new document"},
        {"value": "Update Document", "label": "Update Document", "description": "Update an existing document"},
        {"value": "Delete Document", "label": "Delete Document", "description": "Delete a document"},
        {"value": "Custom Method", "label": "Custom Method", "description": "Call a custom Python method"},
        {"value": "Log Message", "label": "Log Message", "description": "Log a message to the error log"}
    ]


@frappe.whitelist()
def get_available_operators() -> List[Dict]:
    """
    Get list of available condition operators for ECA rules.

    Returns:
        list: Available operators with descriptions
    """
    return [
        {"value": "equals", "label": "Equals", "description": "Field equals value"},
        {"value": "not_equals", "label": "Not Equals", "description": "Field does not equal value"},
        {"value": "greater_than", "label": "Greater Than", "description": "Field is greater than value (numeric)"},
        {"value": "less_than", "label": "Less Than", "description": "Field is less than value (numeric)"},
        {"value": "greater_than_or_equals", "label": "Greater Than or Equals", "description": "Field is >= value"},
        {"value": "less_than_or_equals", "label": "Less Than or Equals", "description": "Field is <= value"},
        {"value": "contains", "label": "Contains", "description": "Field contains value as substring"},
        {"value": "not_contains", "label": "Not Contains", "description": "Field does not contain value"},
        {"value": "starts_with", "label": "Starts With", "description": "Field starts with value"},
        {"value": "ends_with", "label": "Ends With", "description": "Field ends with value"},
        {"value": "is_set", "label": "Is Set", "description": "Field has a value (not empty/null)"},
        {"value": "is_not_set", "label": "Is Not Set", "description": "Field is empty or null"},
        {"value": "changed", "label": "Changed", "description": "Field value changed from previous save"},
        {"value": "changed_from", "label": "Changed From", "description": "Field changed from specific value"},
        {"value": "changed_to", "label": "Changed To", "description": "Field changed to specific value"},
        {"value": "in_list", "label": "In List", "description": "Field value is in a comma-separated list"},
        {"value": "not_in_list", "label": "Not In List", "description": "Field value is not in list"},
        {"value": "regex_match", "label": "Regex Match", "description": "Field matches regex pattern"}
    ]

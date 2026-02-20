# Copyright (c) 2026, TradeHub and contributors
# For license information, please see license.txt

"""
ECA Scheduled Tasks

This module provides scheduled tasks for the ECA module including:
- Log cleanup: Remove old ECA Rule Logs to prevent database bloat
- Rule status monitoring: Check and potentially reset rules with Error status
- Cache maintenance: Periodically refresh rule caches for optimal performance
- Statistics aggregation: Compile execution statistics for reporting

These tasks are registered in hooks.py scheduler_events and run via
Frappe's background scheduler.

Pattern Reference: tr_tradehub/rfq/tasks.py (status transition with audit trail)
"""

import frappe
from frappe import _
from frappe.utils import add_days, now_datetime, get_datetime, cint
from typing import Dict, List, Optional


# =============================================================================
# LOG CLEANUP TASKS
# =============================================================================

def cleanup_old_eca_logs():
    """
    Daily task to clean up old ECA Rule Logs.

    Removes logs older than the configured retention period (default: 30 days)
    to prevent database bloat while maintaining audit trail for recent executions.

    This task should be scheduled daily via hooks.py:
        scheduler_events = {
            "daily": ["tr_tradehub.eca.tasks.cleanup_old_eca_logs"]
        }
    """
    # Get retention days from ECA Settings or use default
    retention_days = _get_log_retention_days()

    try:
        # Import the ECALog class
        from tr_tradehub.tr_tradehub.doctype.eca_rule_log.eca_rule_log import ECALog

        # Use the cleanup_old_logs method
        deleted_count = ECALog.cleanup_old_logs(days=retention_days)

        if deleted_count > 0:
            frappe.log_error(
                f"ECA Log Cleanup: Deleted {deleted_count} logs older than {retention_days} days",
                "ECA Log Cleanup Info"
            )

        frappe.db.commit()

        return {
            "success": True,
            "deleted_count": deleted_count,
            "retention_days": retention_days
        }

    except Exception as e:
        frappe.log_error(
            f"ECA Log Cleanup failed: {str(e)}",
            "ECA Log Cleanup Error"
        )
        return {
            "success": False,
            "error": str(e)
        }


def cleanup_eca_logs_batch(batch_size: int = 500):
    """
    Batch cleanup for large log volumes.

    Processes logs in batches to avoid long-running transactions
    and memory issues with very large log tables.

    Args:
        batch_size: Number of logs to delete per batch (default: 500)

    Returns:
        Dictionary with cleanup results
    """
    retention_days = _get_log_retention_days()
    cutoff_date = add_days(now_datetime(), -retention_days)

    total_deleted = 0
    batches_processed = 0
    max_batches = 100  # Safety limit to prevent infinite loops

    try:
        while batches_processed < max_batches:
            # Get batch of old logs
            old_logs = frappe.get_all(
                "ECA Rule Log",
                filters={"execution_time": ["<", cutoff_date]},
                fields=["name"],
                limit=batch_size
            )

            if not old_logs:
                break

            # Delete the batch
            for log in old_logs:
                frappe.delete_doc(
                    "ECA Rule Log",
                    log.name,
                    ignore_permissions=True,
                    delete_permanently=True
                )

            total_deleted += len(old_logs)
            batches_processed += 1
            frappe.db.commit()

        return {
            "success": True,
            "total_deleted": total_deleted,
            "batches_processed": batches_processed
        }

    except Exception as e:
        frappe.log_error(
            f"ECA Log Batch Cleanup failed after deleting {total_deleted}: {str(e)}",
            "ECA Log Cleanup Error"
        )
        return {
            "success": False,
            "total_deleted": total_deleted,
            "error": str(e)
        }


def _get_log_retention_days() -> int:
    """
    Get the log retention period in days.

    Checks for ECA Settings DocType for custom retention,
    falls back to default of 30 days.

    Returns:
        Number of days to retain logs
    """
    default_retention = 30

    try:
        # Check if there's a custom setting
        # This allows configuration without code changes
        if frappe.db.exists("ECA Settings", "ECA Settings"):
            settings = frappe.get_single("ECA Settings")
            if hasattr(settings, "log_retention_days") and settings.log_retention_days:
                return cint(settings.log_retention_days)
    except Exception:
        pass

    return default_retention


# =============================================================================
# RULE STATUS MONITORING
# =============================================================================

def check_error_rules():
    """
    Hourly task to check rules with Error status.

    Identifies rules that have been in Error status and checks if they
    should be automatically reset or if they need manual intervention.

    This task should be scheduled hourly via hooks.py:
        scheduler_events = {
            "hourly": ["tr_tradehub.eca.tasks.check_error_rules"]
        }
    """
    try:
        # Get rules with Error status
        error_rules = frappe.get_all(
            "ECA Rule",
            filters={"status": "Error", "enabled": 1},
            fields=["name", "rule_name", "event_doctype", "event_type", "modified"]
        )

        if not error_rules:
            return {"success": True, "error_rules_count": 0}

        # Log the error rules for monitoring
        rule_names = [r.rule_name for r in error_rules]
        frappe.log_error(
            f"ECA Rules in Error Status:\n" + "\n".join(rule_names),
            "ECA Error Rules Monitoring"
        )

        return {
            "success": True,
            "error_rules_count": len(error_rules),
            "error_rules": [r.name for r in error_rules]
        }

    except Exception as e:
        frappe.log_error(
            f"Error checking ECA rules status: {str(e)}",
            "ECA Rule Monitoring Error"
        )
        return {
            "success": False,
            "error": str(e)
        }


def reset_error_rules(hours_since_error: int = 24):
    """
    Reset rules that have been in Error status for a specified time.

    Automatically resets rules to Active status if they've been in Error
    for longer than the specified period, allowing them to be retried.

    Args:
        hours_since_error: Hours since the rule was modified (entered Error)

    Returns:
        Dictionary with reset results
    """
    cutoff_time = add_days(now_datetime(), -(hours_since_error / 24))

    try:
        # Get error rules that haven't been modified recently
        error_rules = frappe.get_all(
            "ECA Rule",
            filters={
                "status": "Error",
                "enabled": 1,
                "modified": ["<", cutoff_time]
            },
            fields=["name", "rule_name"]
        )

        reset_count = 0
        for rule in error_rules:
            try:
                frappe.db.set_value(
                    "ECA Rule",
                    rule.name,
                    "status",
                    "Active",
                    update_modified=True
                )

                # Add comment for audit trail
                doc = frappe.get_doc("ECA Rule", rule.name)
                doc.add_comment(
                    "Info",
                    _("Rule automatically reset from Error to Active after {0} hours").format(
                        hours_since_error
                    )
                )

                reset_count += 1
            except Exception as e:
                frappe.log_error(
                    f"Failed to reset rule {rule.name}: {str(e)}",
                    "ECA Rule Reset Error"
                )

        frappe.db.commit()

        return {
            "success": True,
            "reset_count": reset_count,
            "total_error_rules": len(error_rules)
        }

    except Exception as e:
        frappe.log_error(
            f"Error resetting ECA rules: {str(e)}",
            "ECA Rule Reset Error"
        )
        return {
            "success": False,
            "error": str(e)
        }


# =============================================================================
# CACHE MAINTENANCE
# =============================================================================

def refresh_rule_cache():
    """
    Periodic task to refresh the ECA rule cache.

    Clears and rebuilds the rule cache to ensure consistency
    after any database-level changes or cache corruption.

    This task can be scheduled every few hours via hooks.py:
        scheduler_events = {
            "cron": {
                "0 */4 * * *": ["tr_tradehub.eca.tasks.refresh_rule_cache"]
            }
        }
    """
    try:
        from tr_tradehub.eca.handlers import invalidate_rule_cache

        # Invalidate all cached rules
        invalidate_rule_cache()

        # Pre-warm cache for active DocTypes
        active_rules = frappe.get_all(
            "ECA Rule",
            filters={"enabled": 1, "status": "Active"},
            fields=["event_doctype", "event_type"],
            group_by="event_doctype, event_type"
        )

        # Trigger cache population for each active combination
        for rule in active_rules:
            try:
                frappe.cache().delete_value(
                    f"eca_rules:{rule.event_doctype}:{rule.event_type}"
                )
            except Exception:
                pass

        return {
            "success": True,
            "active_combinations": len(active_rules)
        }

    except Exception as e:
        frappe.log_error(
            f"Error refreshing ECA rule cache: {str(e)}",
            "ECA Cache Refresh Error"
        )
        return {
            "success": False,
            "error": str(e)
        }


def clear_rate_limit_counters():
    """
    Periodic task to clean up expired rate limit counters from Redis.

    While Redis TTL handles expiration automatically, this task
    can force cleanup of any orphaned keys.

    This is usually not needed due to TTL, but can be run manually
    or weekly for maintenance.
    """
    try:
        redis = frappe.cache().get_redis()
        if not redis:
            return {"success": True, "message": "Redis not available"}

        # Scan for old rate limit keys
        cursor = 0
        deleted_count = 0

        while True:
            cursor, keys = redis.scan(cursor, match="eca_rate:*")
            if keys:
                # Check TTL and delete if expired
                for key in keys:
                    ttl = redis.ttl(key)
                    if ttl == -1:  # No expiration set (shouldn't happen)
                        redis.delete(key)
                        deleted_count += 1

            if cursor == 0:
                break

        return {
            "success": True,
            "deleted_count": deleted_count
        }

    except Exception as e:
        frappe.log_error(
            f"Error clearing rate limit counters: {str(e)}",
            "ECA Rate Limit Cleanup Error"
        )
        return {
            "success": False,
            "error": str(e)
        }


# =============================================================================
# STATISTICS AGGREGATION
# =============================================================================

def aggregate_execution_statistics():
    """
    Daily task to aggregate execution statistics for reporting.

    Compiles daily statistics including:
    - Total executions per rule
    - Success/failure rates
    - Average execution chains
    - Most active DocTypes

    This task should be scheduled daily after log cleanup:
        scheduler_events = {
            "daily": [
                "tr_tradehub.eca.tasks.cleanup_old_eca_logs",
                "tr_tradehub.eca.tasks.aggregate_execution_statistics"
            ]
        }
    """
    try:
        yesterday = add_days(now_datetime(), -1)
        today_start = yesterday.replace(hour=0, minute=0, second=0, microsecond=0)
        today_end = yesterday.replace(hour=23, minute=59, second=59, microsecond=999999)

        # Get execution counts by status
        stats = frappe.db.sql("""
            SELECT
                execution_status,
                COUNT(*) as count,
                COUNT(DISTINCT eca_rule) as unique_rules,
                COUNT(DISTINCT trigger_doctype) as unique_doctypes
            FROM `tabECA Rule Log`
            WHERE execution_time BETWEEN %s AND %s
            GROUP BY execution_status
        """, (today_start, today_end), as_dict=True)

        # Get most active rules
        top_rules = frappe.db.sql("""
            SELECT
                eca_rule,
                COUNT(*) as execution_count,
                SUM(CASE WHEN execution_status = 'Success' THEN 1 ELSE 0 END) as success_count,
                SUM(CASE WHEN execution_status = 'Failed' THEN 1 ELSE 0 END) as failed_count
            FROM `tabECA Rule Log`
            WHERE execution_time BETWEEN %s AND %s
            GROUP BY eca_rule
            ORDER BY execution_count DESC
            LIMIT 10
        """, (today_start, today_end), as_dict=True)

        # Calculate totals
        total_executions = sum(s.get("count", 0) for s in stats)
        success_count = next(
            (s.get("count", 0) for s in stats if s.get("execution_status") == "Success"),
            0
        )

        result = {
            "success": True,
            "date": str(yesterday.date()),
            "total_executions": total_executions,
            "success_rate": (success_count / total_executions * 100) if total_executions > 0 else 0,
            "status_breakdown": stats,
            "top_rules": top_rules
        }

        return result

    except Exception as e:
        frappe.log_error(
            f"Error aggregating ECA statistics: {str(e)}",
            "ECA Statistics Error"
        )
        return {
            "success": False,
            "error": str(e)
        }


def update_rule_execution_stats():
    """
    Update execution statistics on ECA Rule documents.

    Syncs the total_executions and last_executed fields on ECA Rules
    based on the actual log entries. This handles any discrepancies
    that might occur due to failed commits or concurrent updates.

    This task can be run weekly for data integrity:
        scheduler_events = {
            "weekly": ["tr_tradehub.eca.tasks.update_rule_execution_stats"]
        }
    """
    try:
        # Get all active rules
        rules = frappe.get_all(
            "ECA Rule",
            filters={"enabled": 1},
            fields=["name", "total_executions", "last_executed"]
        )

        updated_count = 0

        for rule in rules:
            # Get actual stats from logs
            actual_stats = frappe.db.sql("""
                SELECT
                    COUNT(*) as total,
                    MAX(execution_time) as last_exec
                FROM `tabECA Rule Log`
                WHERE eca_rule = %s
                AND execution_status IN ('Success', 'Partial')
            """, (rule.name,), as_dict=True)

            if actual_stats:
                stats = actual_stats[0]
                actual_total = stats.get("total", 0) or 0
                actual_last = stats.get("last_exec")

                # Check if update is needed
                needs_update = False
                update_fields = {}

                if actual_total != (rule.total_executions or 0):
                    update_fields["total_executions"] = actual_total
                    needs_update = True

                if actual_last and (not rule.last_executed or get_datetime(actual_last) > get_datetime(rule.last_executed)):
                    update_fields["last_executed"] = actual_last
                    needs_update = True

                if needs_update:
                    frappe.db.set_value(
                        "ECA Rule",
                        rule.name,
                        update_fields,
                        update_modified=False
                    )
                    updated_count += 1

        frappe.db.commit()

        return {
            "success": True,
            "rules_checked": len(rules),
            "rules_updated": updated_count
        }

    except Exception as e:
        frappe.log_error(
            f"Error updating rule execution stats: {str(e)}",
            "ECA Stats Update Error"
        )
        return {
            "success": False,
            "error": str(e)
        }


# =============================================================================
# SCHEDULED RULE EVALUATION
# =============================================================================

def evaluate_scheduled_rules():
    """
    Evaluate rules that are configured for scheduled execution.

    This task is for rules that need to run periodically against
    matching documents (e.g., check all orders with status X daily).

    Note: This is an advanced feature for rules that scan existing
    documents rather than triggering on events.

    This task should be scheduled based on configuration:
        scheduler_events = {
            "hourly": ["tr_tradehub.eca.tasks.evaluate_scheduled_rules"]
        }
    """
    # This is a placeholder for scheduled rule evaluation
    # which would require a "Scheduled" event_type in the ECA Rule DocType
    # For now, we log that scheduled rules are not yet implemented

    try:
        # Check if there are any rules with scheduled-like configuration
        # (This would be expanded when scheduled rules are added)

        return {
            "success": True,
            "message": "Scheduled rule evaluation not yet configured"
        }

    except Exception as e:
        frappe.log_error(
            f"Error in scheduled rule evaluation: {str(e)}",
            "ECA Scheduled Evaluation Error"
        )
        return {
            "success": False,
            "error": str(e)
        }


# =============================================================================
# API ENDPOINTS
# =============================================================================

@frappe.whitelist()
def run_log_cleanup(days: int = None):
    """
    API endpoint to manually trigger log cleanup.

    Args:
        days: Override the default retention days (optional)

    Returns:
        Cleanup results
    """
    # Check permissions
    if not frappe.has_permission("ECA Rule Log", "delete"):
        frappe.throw(_("Insufficient permissions to delete logs"))

    if days:
        # Override retention days for this run
        from tr_tradehub.tr_tradehub.doctype.eca_rule_log.eca_rule_log import ECALog
        deleted_count = ECALog.cleanup_old_logs(days=cint(days))
        frappe.db.commit()
        return {
            "success": True,
            "deleted_count": deleted_count,
            "retention_days": days
        }

    return cleanup_old_eca_logs()


@frappe.whitelist()
def run_statistics():
    """
    API endpoint to get execution statistics.

    Returns:
        Current execution statistics
    """
    # Check permissions
    if not frappe.has_permission("ECA Rule Log", "read"):
        frappe.throw(_("Insufficient permissions"))

    return aggregate_execution_statistics()


@frappe.whitelist()
def get_task_status():
    """
    API endpoint to get the status of scheduled tasks.

    Returns:
        Dictionary with task information
    """
    if not frappe.has_permission("ECA Rule", "read"):
        frappe.throw(_("Insufficient permissions"))

    # Get counts for monitoring
    total_rules = frappe.db.count("ECA Rule", {"enabled": 1})
    error_rules = frappe.db.count("ECA Rule", {"enabled": 1, "status": "Error"})
    total_logs = frappe.db.count("ECA Rule Log")

    retention_days = _get_log_retention_days()
    cutoff = add_days(now_datetime(), -retention_days)
    old_logs = frappe.db.count("ECA Rule Log", {"execution_time": ["<", cutoff]})

    return {
        "total_active_rules": total_rules,
        "rules_in_error": error_rules,
        "total_logs": total_logs,
        "logs_pending_cleanup": old_logs,
        "retention_days": retention_days
    }

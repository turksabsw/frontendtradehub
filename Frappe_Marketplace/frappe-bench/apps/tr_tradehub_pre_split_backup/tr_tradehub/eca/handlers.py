# Copyright (c) 2026, TradeHub and contributors
# For license information, please see license.txt

"""
ECA Document Event Handlers

This module provides the doc_event handlers that integrate ECA rules with
Frappe's document lifecycle events. It serves as the bridge between
Frappe's doc_events hooks and the ECA engine, actions, and logging systems.

Supported Events:
- before_insert: Before document is inserted
- after_insert: After document is inserted
- before_save: Before document is saved
- after_save: After document is saved
- before_validate: Before document validation
- after_validate: After document validation (before save)
- on_update: After document update
- on_submit: After document submission
- before_submit: Before document submission
- on_cancel: After document cancellation
- before_cancel: Before document cancellation
- on_trash: After document is trashed
- after_delete: After document is deleted

Pattern Reference: tr_tradehub/rfq/tasks.py (status transition with audit trail)
"""

import frappe
from frappe import _
from frappe.utils import now_datetime
from typing import Any, Dict, List, Optional


# =============================================================================
# EVENT TYPE MAPPING
# =============================================================================

# Map Frappe's internal event names to ECA Rule event_type values
EVENT_TYPE_MAP = {
    "before_insert": "Before Insert",
    "after_insert": "After Insert",
    "validate": "Before Validate",
    "before_validate": "Before Validate",
    "after_validate": "After Validate",
    "before_save": "Before Save",
    "after_save": "After Save",
    "on_update": "On Update",
    "on_submit": "On Submit",
    "before_submit": "Before Submit",
    "on_cancel": "On Cancel",
    "before_cancel": "Before Cancel",
    "on_trash": "On Trash",
    "after_delete": "After Delete",
    "on_change": "On Change",
}

# Events that have access to old_doc (for change detection)
EVENTS_WITH_OLD_DOC = {
    "before_save",
    "after_save",
    "on_update",
    "validate",
    "before_validate",
    "after_validate",
    "on_submit",
    "before_submit",
    "on_cancel",
    "before_cancel",
}


# =============================================================================
# MAIN EVENT HANDLER
# =============================================================================

def handle_doc_event(doc, event: str):
    """
    Main handler for document events.

    This function is called by Frappe's doc_events hook system for all
    document lifecycle events. It:
    1. Checks if there are matching ECA rules for this event
    2. Evaluates conditions for each rule
    3. Executes actions for rules where conditions pass
    4. Logs all executions

    Args:
        doc: The Frappe document that triggered the event
        event: The event type (e.g., "after_save", "on_submit")
    """
    # Skip if not a valid event type
    eca_event_type = EVENT_TYPE_MAP.get(event)
    if not eca_event_type:
        return

    # Skip processing if ECA module is disabled
    if getattr(frappe.flags, "disable_eca", False):
        return

    # Skip if this is an ECA-related DocType to prevent loops
    if _is_eca_doctype(doc.doctype):
        return

    try:
        # Get applicable rules for this doctype and event
        rules = _get_applicable_rules(doc.doctype, eca_event_type)

        if not rules:
            return

        # Get old_doc for change detection if applicable
        old_doc = _get_old_doc(doc, event)

        # Process each rule
        for rule in rules:
            _process_rule(doc, old_doc, rule, eca_event_type)

    except Exception as e:
        # Log error but don't raise - ECA errors shouldn't break document saves
        frappe.log_error(
            f"ECA handler error for {doc.doctype}/{doc.name} on {event}:\n{str(e)}",
            "ECA Handler Error"
        )


def _is_eca_doctype(doctype: str) -> bool:
    """
    Check if a DocType is an ECA-related type.

    We skip processing for ECA DocTypes to prevent infinite loops.

    Args:
        doctype: The DocType name

    Returns:
        True if this is an ECA DocType
    """
    eca_doctypes = {
        "ECA Rule",
        "ECA Rule Condition",
        "ECA Rule Action",
        "ECA Rule Log",
        "ECA Action Template",
    }
    return doctype in eca_doctypes


def _get_old_doc(doc, event: str) -> Optional[Any]:
    """
    Get the previous version of the document for change detection.

    Args:
        doc: The current document
        event: The event type

    Returns:
        The old document or None if not available
    """
    if event not in EVENTS_WITH_OLD_DOC:
        return None

    # Frappe stores _doc_before_save for change detection
    if hasattr(doc, "_doc_before_save") and doc._doc_before_save:
        return doc._doc_before_save

    return None


# =============================================================================
# RULE RETRIEVAL
# =============================================================================

def _get_applicable_rules(doctype: str, event_type: str) -> List[Any]:
    """
    Get all active ECA rules that apply to this doctype and event.

    Rules are retrieved in priority order (lower number = higher priority).
    Only enabled rules with 'Active' status are returned.

    Args:
        doctype: The DocType that triggered the event
        event_type: The ECA event type (e.g., "After Save")

    Returns:
        List of ECA Rule documents, ordered by priority
    """
    # Use a cache key to avoid repeated queries
    cache_key = f"eca_rules:{doctype}:{event_type}"

    # Check cache first (short TTL for rule changes)
    cached_rule_names = frappe.cache().get_value(cache_key)

    if cached_rule_names is None:
        # Query for matching rules
        rule_names = frappe.get_all(
            "ECA Rule",
            filters={
                "event_doctype": doctype,
                "event_type": event_type,
                "enabled": 1,
                "status": "Active",
            },
            fields=["name"],
            order_by="priority asc",
            pluck="name"
        )

        # Cache for 60 seconds
        frappe.cache().set_value(cache_key, rule_names, expires_in_sec=60)
        cached_rule_names = rule_names

    # Load full rule documents
    rules = []
    for rule_name in cached_rule_names:
        try:
            rule = frappe.get_doc("ECA Rule", rule_name)
            rules.append(rule)
        except frappe.DoesNotExistError:
            # Rule was deleted, invalidate cache
            frappe.cache().delete_key(cache_key)
            continue

    return rules


def invalidate_rule_cache(doctype: str = None, event_type: str = None):
    """
    Invalidate the rule cache for a specific doctype/event or all rules.

    Should be called when ECA Rules are modified.

    Args:
        doctype: Optional specific doctype to invalidate
        event_type: Optional specific event type to invalidate
    """
    if doctype and event_type:
        cache_key = f"eca_rules:{doctype}:{event_type}"
        frappe.cache().delete_key(cache_key)
    else:
        # Delete all ECA rule cache keys
        try:
            redis = frappe.cache().get_redis()
            if redis:
                pattern = "eca_rules:*"
                cursor = 0
                while True:
                    cursor, keys = redis.scan(cursor, match=pattern)
                    if keys:
                        redis.delete(*keys)
                    if cursor == 0:
                        break
        except Exception:
            pass  # Ignore cache invalidation errors


# =============================================================================
# RULE PROCESSING
# =============================================================================

def _process_rule(doc, old_doc, rule, event_type: str):
    """
    Process a single ECA rule for a document event.

    This function:
    1. Checks rate limits
    2. Checks chain tracking (circular prevention)
    3. Evaluates conditions
    4. Executes actions if conditions pass
    5. Creates execution log

    Args:
        doc: The trigger document
        old_doc: The previous document state (may be None)
        rule: The ECA Rule document
        event_type: The event type string
    """
    # Import ECA components here to avoid circular imports
    from tr_tradehub.eca.engine import ECAEngine, ExecutionResult
    from tr_tradehub.eca.actions import ActionRunner, ActionContext, execute_actions
    from tr_tradehub.eca.rate_limiter import check_rate_limit
    from tr_tradehub.eca.chain_tracker import chain_context, get_current_chain_id, get_current_chain_depth
    from tr_tradehub.tr_tradehub.doctype.eca_rule_log.eca_rule_log import ECALog

    execution_status = "Skipped"
    condition_result = False
    action_results = []
    error_message = None
    chain_id = get_current_chain_id() or frappe.generate_hash(length=12)
    chain_depth = get_current_chain_depth()

    try:
        # Step 1: Check rate limiting
        rate_limit_result = check_rate_limit(rule, doc)
        if not rate_limit_result.allowed:
            execution_status = "Skipped"
            error_message = rate_limit_result.reason

            # Log the skipped execution
            ECALog.create_log(
                eca_rule=rule.name,
                execution_status=execution_status,
                trigger_doctype=doc.doctype,
                trigger_document=doc.name,
                condition_result=False,
                action_results=None,
                error_message=error_message,
                chain_id=chain_id,
                chain_depth=chain_depth
            )
            return

        # Step 2: Use chain context for circular prevention
        with chain_context(rule, chain_id=chain_id) as ctx:
            chain_id = ctx.chain_id
            chain_depth = ctx.chain_depth

            if not ctx.allowed:
                execution_status = "Skipped"
                error_message = ctx.reason

                # Log the skipped execution
                ECALog.create_log(
                    eca_rule=rule.name,
                    execution_status=execution_status,
                    trigger_doctype=doc.doctype,
                    trigger_document=doc.name,
                    condition_result=False,
                    action_results=None,
                    error_message=error_message,
                    chain_id=chain_id,
                    chain_depth=chain_depth
                )
                return

            # Step 3: Evaluate conditions
            engine = ECAEngine(doc, old_doc)
            condition_result = engine.evaluate_rule(rule)

            if not condition_result:
                execution_status = "Skipped"
                error_message = "Conditions not met"

                # Log the skipped execution
                ECALog.create_log(
                    eca_rule=rule.name,
                    execution_status=execution_status,
                    trigger_doctype=doc.doctype,
                    trigger_document=doc.name,
                    condition_result=False,
                    action_results=None,
                    error_message=error_message,
                    chain_id=chain_id,
                    chain_depth=chain_depth
                )
                return

            # Step 4: Execute actions
            context = ActionContext(
                doc=doc,
                old_doc=old_doc,
                rule=rule,
                action=None,
                chain_id=chain_id,
                chain_depth=chain_depth
            )

            runner = ActionRunner(context)
            results = runner.execute_all()

            # Convert results to serializable format
            action_results = [r.to_dict() for r in results]

            # Determine overall status
            execution_status = runner.get_overall_status()

            # Check for errors in action results
            failed_actions = [r for r in results if not r.success]
            if failed_actions:
                error_messages = [r.message for r in failed_actions if r.message]
                error_message = "; ".join(error_messages) if error_messages else None

            # Update rule statistics
            _update_rule_statistics(rule)

    except Exception as e:
        execution_status = "Failed"
        error_message = str(e)
        frappe.log_error(
            f"ECA rule execution failed: {rule.name}\n"
            f"DocType: {doc.doctype}, Document: {doc.name}\n"
            f"Error: {str(e)}",
            "ECA Rule Execution Error"
        )

    finally:
        # Always create execution log
        try:
            ECALog.create_log(
                eca_rule=rule.name,
                execution_status=execution_status,
                trigger_doctype=doc.doctype,
                trigger_document=doc.name,
                condition_result=condition_result,
                action_results=action_results if action_results else None,
                error_message=error_message,
                chain_id=chain_id,
                chain_depth=chain_depth
            )
        except Exception as log_error:
            frappe.log_error(
                f"Failed to create ECA log: {str(log_error)}",
                "ECA Log Creation Error"
            )


def _update_rule_statistics(rule):
    """
    Update the execution statistics on the ECA Rule.

    Args:
        rule: The ECA Rule document
    """
    try:
        frappe.db.set_value(
            "ECA Rule",
            rule.name,
            {
                "last_executed": now_datetime(),
                "total_executions": (rule.total_executions or 0) + 1
            },
            update_modified=False
        )
    except Exception:
        pass  # Don't fail on stats update


# =============================================================================
# INDIVIDUAL EVENT HANDLERS
# =============================================================================
# These functions are called directly from hooks.py doc_events

def before_insert(doc, method=None):
    """Handler for before_insert event."""
    handle_doc_event(doc, "before_insert")


def after_insert(doc, method=None):
    """Handler for after_insert event."""
    handle_doc_event(doc, "after_insert")


def validate(doc, method=None):
    """Handler for validate (before_validate) event."""
    handle_doc_event(doc, "validate")


def before_validate(doc, method=None):
    """Handler for before_validate event."""
    handle_doc_event(doc, "before_validate")


def before_save(doc, method=None):
    """Handler for before_save event."""
    handle_doc_event(doc, "before_save")


def after_save(doc, method=None):
    """Handler for after_save event."""
    handle_doc_event(doc, "after_save")


def on_update(doc, method=None):
    """Handler for on_update event."""
    handle_doc_event(doc, "on_update")


def before_submit(doc, method=None):
    """Handler for before_submit event."""
    handle_doc_event(doc, "before_submit")


def on_submit(doc, method=None):
    """Handler for on_submit event."""
    handle_doc_event(doc, "on_submit")


def before_cancel(doc, method=None):
    """Handler for before_cancel event."""
    handle_doc_event(doc, "before_cancel")


def on_cancel(doc, method=None):
    """Handler for on_cancel event."""
    handle_doc_event(doc, "on_cancel")


def on_trash(doc, method=None):
    """Handler for on_trash event."""
    handle_doc_event(doc, "on_trash")


def after_delete(doc, method=None):
    """Handler for after_delete event."""
    handle_doc_event(doc, "after_delete")


def on_change(doc, method=None):
    """Handler for on_change event."""
    handle_doc_event(doc, "on_change")


# =============================================================================
# UTILITY FUNCTIONS
# =============================================================================

def disable_eca_processing():
    """
    Disable ECA processing for the current request.

    Use this when performing bulk operations to avoid triggering rules.

    Usage:
        from tr_tradehub.eca.handlers import disable_eca_processing, enable_eca_processing

        disable_eca_processing()
        try:
            # Bulk operations here
            pass
        finally:
            enable_eca_processing()
    """
    frappe.flags.disable_eca = True


def enable_eca_processing():
    """
    Re-enable ECA processing for the current request.
    """
    frappe.flags.disable_eca = False


def is_eca_processing_enabled() -> bool:
    """
    Check if ECA processing is enabled.

    Returns:
        True if ECA processing is enabled
    """
    return not getattr(frappe.flags, "disable_eca", False)


@frappe.whitelist()
def manually_trigger_rules(doctype: str, docname: str, event_type: str = "After Save"):
    """
    Manually trigger ECA rules for a document.

    This can be used for testing or for manual rule execution.

    Args:
        doctype: The document type
        docname: The document name
        event_type: The event type to simulate (default: "After Save")

    Returns:
        Dictionary with execution results
    """
    # Check permissions
    if not frappe.has_permission(doctype, "read", docname):
        frappe.throw(_("Insufficient permissions"))

    # Get the document
    doc = frappe.get_doc(doctype, docname)

    # Get applicable rules
    rules = _get_applicable_rules(doctype, event_type)

    results = []
    for rule in rules:
        _process_rule(doc, None, rule, event_type)
        results.append({
            "rule": rule.name,
            "status": "triggered"
        })

    return {
        "success": True,
        "rules_triggered": len(results),
        "results": results
    }


@frappe.whitelist()
def get_rules_for_doctype(doctype: str) -> List[Dict]:
    """
    Get all active ECA rules for a specific DocType.

    API endpoint for rule discovery.

    Args:
        doctype: The DocType to get rules for

    Returns:
        List of rule summaries
    """
    rules = frappe.get_all(
        "ECA Rule",
        filters={
            "event_doctype": doctype,
            "enabled": 1,
        },
        fields=["name", "rule_name", "event_type", "priority", "status", "last_executed", "total_executions"],
        order_by="priority asc"
    )

    return rules


@frappe.whitelist()
def test_rule_conditions(rule_name: str, doctype: str, docname: str) -> Dict:
    """
    Test a rule's conditions against a specific document without executing actions.

    Useful for debugging and rule development.

    Args:
        rule_name: The ECA Rule name
        doctype: The document type
        docname: The document name

    Returns:
        Dictionary with condition evaluation results
    """
    # Check permissions
    if not frappe.has_permission("ECA Rule", "read"):
        frappe.throw(_("Insufficient permissions"))

    from tr_tradehub.eca.engine import ECAEngine

    # Get the rule and document
    rule = frappe.get_doc("ECA Rule", rule_name)
    doc = frappe.get_doc(doctype, docname)

    # Evaluate conditions
    engine = ECAEngine(doc, None)
    result = engine.evaluate_rule(rule)

    # Get detailed condition results
    condition_details = []
    for condition in rule.conditions:
        try:
            cond_result = engine.evaluate_condition(condition)
            actual_value = engine.get_field_value(condition.field_path)
            condition_details.append({
                "field_path": condition.field_path,
                "operator": condition.operator,
                "expected_value": condition.value,
                "actual_value": str(actual_value) if actual_value is not None else None,
                "result": cond_result,
                "group": condition.condition_group,
            })
        except Exception as e:
            condition_details.append({
                "field_path": condition.field_path,
                "operator": condition.operator,
                "error": str(e),
                "result": False,
            })

    return {
        "rule_name": rule_name,
        "overall_result": result,
        "condition_logic": rule.condition_logic,
        "conditions": condition_details,
    }

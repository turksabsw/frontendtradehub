# Copyright (c) 2026, TR TradeHub and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class ECARuleLog(Document):
    """
    ECA Rule Log DocType

    Audit trail for ECA rule executions. Records:
    - Which rule was triggered
    - What document/event triggered it
    - Condition evaluation results
    - Action execution results
    - Timing and error information
    """

    def validate(self):
        """Validate log entry"""
        self.calculate_status()

    def calculate_status(self):
        """Auto-calculate status based on results"""
        if self.error_message or self.error_traceback:
            self.status = "Error"
        elif not self.condition_result:
            self.status = "Skipped"
        elif self.actions_failed and self.actions_failed > 0:
            if self.actions_succeeded and self.actions_succeeded > 0:
                self.status = "Partial"
            else:
                self.status = "Failed"
        else:
            self.status = "Success"


def create_log_entry(rule, doc, event_type, **kwargs):
    """
    Create an ECA Rule Log entry

    Args:
        rule: ECA Rule document
        doc: Trigger document
        event_type: Event that triggered the rule
        **kwargs: Additional log data (condition_result, action_results, etc.)

    Returns:
        ECARuleLog: Created log document
    """
    log = frappe.new_doc("ECA Rule Log")
    log.eca_rule = rule.name
    log.trigger_doctype = doc.doctype
    log.trigger_document = doc.name
    log.trigger_event = event_type
    log.trigger_user = frappe.session.user
    log.trigger_time = frappe.utils.now_datetime()

    # Set optional fields from kwargs
    for field in ["condition_result", "condition_details", "actions_executed",
                  "actions_succeeded", "actions_failed", "action_results",
                  "execution_time_ms", "error_message", "error_traceback"]:
        if field in kwargs:
            setattr(log, field, kwargs[field])

    log.insert(ignore_permissions=True)
    return log

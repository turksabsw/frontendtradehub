# Copyright (c) 2024, Custom and contributors
# For license information, please see license.txt

"""
Mock Generation Request - DocType Controller

This module provides the controller for Mock Generation Request, which tracks
the execution of mock data generation tasks including status workflow,
progress tracking, and statistics.

Status Workflow:
    Draft -> Queued -> Processing -> Completed/Failed
    Failed -> Draft (retry)
    Queued -> Cancelled
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime, time_diff_in_seconds


class MockGenerationRequest(Document):
    """
    Controller for Mock Generation Request DocType.

    Manages the lifecycle of mock data generation requests including
    status transitions, progress tracking, and execution control.
    """

    # Valid status transitions
    VALID_TRANSITIONS = {
        "Draft": ["Queued"],
        "Queued": ["Processing", "Cancelled"],
        "Processing": ["Completed", "Failed"],
        "Completed": [],  # Terminal state
        "Failed": ["Draft"],  # Allow retry
        "Cancelled": []  # Terminal state
    }

    def validate(self):
        """Validate the request before save."""
        self.validate_configuration()
        self.validate_record_count()

    def before_save(self):
        """Handle pre-save operations including status transition validation."""
        if self.has_value_changed("status"):
            self.validate_status_transition()

    def validate_configuration(self):
        """
        Validate that the request has proper target configuration.

        Raises:
            frappe.ValidationError: If configuration is invalid.
        """
        if self.generation_mode == "Single DocType":
            if not self.target_doctype:
                frappe.throw(
                    _("Target DocType is required when generation mode is 'Single DocType'."),
                    title=_("Missing Target DocType")
                )

            # Validate that the target DocType exists
            if self.target_doctype and not frappe.db.exists("DocType", self.target_doctype):
                frappe.throw(
                    _("DocType '{0}' does not exist.").format(self.target_doctype),
                    title=_("Invalid DocType")
                )

        elif self.generation_mode == "Multiple DocTypes":
            if not self.selected_doctypes or len(self.selected_doctypes) == 0:
                frappe.throw(
                    _("At least one DocType must be selected when generation mode is 'Multiple DocTypes'."),
                    title=_("Missing DocTypes")
                )

        elif self.generation_mode == "From Profile":
            if not self.profile:
                frappe.throw(
                    _("Generation Profile is required when generation mode is 'From Profile'."),
                    title=_("Missing Profile")
                )

    def validate_record_count(self):
        """
        Validate that record count is reasonable.

        Raises:
            frappe.ValidationError: If record count is invalid.
        """
        if self.generation_mode == "Single DocType":
            if self.record_count is not None and self.record_count < 1:
                frappe.throw(
                    _("Record count must be at least 1."),
                    title=_("Invalid Record Count")
                )

            if self.record_count is not None and self.record_count > 100000:
                frappe.msgprint(
                    _("Generating more than 100,000 records may take a long time and "
                      "consume significant resources."),
                    indicator="orange",
                    alert=True
                )

    def validate_status_transition(self):
        """
        Validate that the status transition is allowed.

        Raises:
            frappe.ValidationError: If the transition is not allowed.
        """
        old_doc = self.get_doc_before_save()
        old_status = old_doc.status if old_doc else "Draft"

        if old_status == self.status:
            return  # No transition

        valid_next_statuses = self.VALID_TRANSITIONS.get(old_status, [])

        if self.status not in valid_next_statuses:
            frappe.throw(
                _("Invalid status transition from '{0}' to '{1}'. "
                  "Allowed transitions: {2}").format(
                    old_status,
                    self.status,
                    ", ".join(valid_next_statuses) if valid_next_statuses else "None (terminal state)"
                ),
                title=_("Invalid Status Transition")
            )

    def check_production_protection(self):
        """
        Check if generation should be blocked due to production protection.

        Raises:
            frappe.ValidationError: If running in a protected production environment.
        """
        settings = frappe.get_single("Mock Engine Settings")

        if settings.is_production_protected():
            frappe.throw(
                _("Mock data generation is blocked in production environments. "
                  "Disable 'Production Protection' in Mock Engine Settings to proceed "
                  "(not recommended for production systems)."),
                title=_("Production Protection Active")
            )

    @frappe.whitelist()
    def start_generation(self):
        """
        Start the generation request.

        This method transitions the request from Draft to Queued status
        and schedules it for background processing.

        This is the primary API for starting mock data generation,
        following the Status Workflow Pattern from the spec.

        Returns:
            dict: Result containing success status and message.
        """
        return self.queue_generation()

    @frappe.whitelist()
    def queue_generation(self):
        """
        Queue the generation request for processing.

        This method transitions the request from Draft to Queued status
        and schedules it for background processing.

        Returns:
            dict: Result containing success status and message.
        """
        if self.status != "Draft":
            frappe.throw(
                _("Only requests in 'Draft' status can be queued. Current status: {0}").format(
                    self.status
                ),
                title=_("Invalid Status")
            )

        # Check production protection
        self.check_production_protection()

        # Update status and queue timestamp
        self.status = "Queued"
        self.queued_at = now_datetime()

        # Reset progress fields
        self.progress_percent = 0
        self.records_created = 0
        self.records_failed = 0
        self.current_batch = 0
        self.total_batches = 0
        self.started_at = None
        self.completed_at = None
        self.duration_seconds = None
        self.error_message = None

        self.save()

        # Enqueue the generation job
        frappe.enqueue(
            "mock_data_engine.mock_data_engine.mock_data_engine.doctype."
            "mock_generation_request.mock_generation_request.execute_generation",
            request_name=self.name,
            queue="long",
            timeout=3600,  # 1 hour timeout
            job_id=f"mock_gen_{self.name}"
        )

        frappe.msgprint(
            _("Generation request has been queued and will start processing shortly."),
            indicator="green",
            alert=True
        )

        return {
            "success": True,
            "message": _("Generation queued successfully."),
            "request_name": self.name
        }

    @frappe.whitelist()
    def cancel_generation(self):
        """
        Cancel a queued generation request.

        Returns:
            dict: Result containing success status and message.
        """
        if self.status != "Queued":
            frappe.throw(
                _("Only requests in 'Queued' status can be cancelled. Current status: {0}").format(
                    self.status
                ),
                title=_("Invalid Status")
            )

        self.status = "Cancelled"
        self.completed_at = now_datetime()
        self.save()

        frappe.msgprint(
            _("Generation request has been cancelled."),
            indicator="orange",
            alert=True
        )

        return {
            "success": True,
            "message": _("Generation cancelled successfully.")
        }

    @frappe.whitelist()
    def retry_generation(self):
        """
        Retry a failed generation request.

        This resets the request to Draft status so it can be queued again.

        Returns:
            dict: Result containing success status and message.
        """
        if self.status != "Failed":
            frappe.throw(
                _("Only requests in 'Failed' status can be retried. Current status: {0}").format(
                    self.status
                ),
                title=_("Invalid Status")
            )

        self.status = "Draft"
        self.error_message = None
        self.save()

        frappe.msgprint(
            _("Generation request has been reset to Draft. You can now queue it again."),
            indicator="green",
            alert=True
        )

        return {
            "success": True,
            "message": _("Generation reset to Draft successfully.")
        }

    def start_processing(self):
        """
        Mark the request as processing and record start time.

        This is called internally when the background job starts.
        """
        self.status = "Processing"
        self.started_at = now_datetime()
        self.db_update()
        frappe.db.commit()

    def update_progress(self, records_created=None, records_failed=None,
                       current_batch=None, total_batches=None):
        """
        Update progress statistics.

        This method updates progress fields and calculates the progress percentage.
        It uses db_update() for efficiency during bulk operations.

        Args:
            records_created: Number of successfully created records.
            records_failed: Number of failed records.
            current_batch: Current batch number.
            total_batches: Total number of batches.
        """
        if records_created is not None:
            self.records_created = records_created
        if records_failed is not None:
            self.records_failed = records_failed
        if current_batch is not None:
            self.current_batch = current_batch
        if total_batches is not None:
            self.total_batches = total_batches

        # Calculate progress percentage
        total_records = self.get_total_target_records()
        if total_records > 0:
            processed = (self.records_created or 0) + (self.records_failed or 0)
            self.progress_percent = min(100, (processed / total_records) * 100)

        self.db_update()
        frappe.db.commit()

        # Publish real-time progress update
        frappe.publish_progress(
            percent=self.progress_percent,
            title=_("Mock Data Generation"),
            description=_("Generated {0} of {1} records").format(
                self.records_created or 0,
                total_records
            ),
            doctype=self.doctype,
            docname=self.name
        )

    def get_total_target_records(self):
        """
        Get the total number of records to be generated.

        Returns:
            int: Total target record count.
        """
        if self.generation_mode == "Single DocType":
            return self.record_count or 0

        elif self.generation_mode == "Multiple DocTypes":
            return sum(
                (row.record_count or 0) for row in (self.selected_doctypes or [])
            )

        elif self.generation_mode == "From Profile" and self.profile:
            try:
                profile_doc = frappe.get_doc("Mock Generation Profile", self.profile)
                return sum(
                    (row.record_count or 0)
                    for row in (profile_doc.doctype_quantities or [])
                )
            except Exception:
                return 0

        return 0

    def mark_completed(self):
        """
        Mark the request as completed and record completion time.
        """
        self.status = "Completed"
        self.completed_at = now_datetime()
        self.progress_percent = 100

        if self.started_at:
            self.duration_seconds = time_diff_in_seconds(
                self.completed_at,
                self.started_at
            )

        self.db_update()
        frappe.db.commit()

    def mark_failed(self, error_message=None):
        """
        Mark the request as failed and record the error.

        Args:
            error_message: The error message to record.
        """
        self.status = "Failed"
        self.completed_at = now_datetime()

        if error_message:
            self.error_message = str(error_message)[:65535]  # Limit to Long Text max

        if self.started_at:
            self.duration_seconds = time_diff_in_seconds(
                self.completed_at,
                self.started_at
            )

        self.db_update()
        frappe.db.commit()

    def get_effective_locale(self):
        """
        Get the effective locale for this request.

        Returns the request's locale override if set, otherwise falls back
        to the global default from Mock Engine Settings.

        Returns:
            str: The locale to use for generation.
        """
        if self.locale:
            return self.locale

        settings = frappe.get_single("Mock Engine Settings")
        return settings.default_locale or "en_US"

    def get_effective_seed(self):
        """
        Get the effective seed value for this request.

        Returns the request's seed override if set, otherwise falls back
        to the global default from Mock Engine Settings.

        Returns:
            int or None: The seed value to use for generation.
        """
        if self.seed_value:
            return self.seed_value

        settings = frappe.get_single("Mock Engine Settings")
        return settings.seed_value


def execute_generation(request_name):
    """
    Execute the mock data generation for a request.

    This function is called by the background job queue.

    Args:
        request_name: The name of the Mock Generation Request to process.
    """
    try:
        request = frappe.get_doc("Mock Generation Request", request_name)

        # Verify status is Queued
        if request.status != "Queued":
            frappe.log_error(
                message=f"Request {request_name} is not in Queued status: {request.status}",
                title="Mock Generation - Invalid Status"
            )
            return

        # Start processing
        request.start_processing()

        # TODO: Implement actual generation logic in phase 11 (Execution Engine)
        # For now, this is a placeholder that will be completed when the
        # generator.py is implemented in subtask-11-1

        # Simulate completion for now (will be replaced)
        request.mark_completed()

    except Exception as e:
        frappe.log_error(
            message=frappe.get_traceback(),
            title=f"Mock Generation Failed: {request_name}"
        )

        try:
            request = frappe.get_doc("Mock Generation Request", request_name)
            request.mark_failed(str(e))
        except Exception:
            pass


@frappe.whitelist()
def get_generation_progress(request_name):
    """
    Get the current progress of a generation request.

    This API endpoint can be called to poll for progress updates.

    Args:
        request_name: The name of the Mock Generation Request.

    Returns:
        dict: Progress information including status, percentage, and counts.
    """
    request = frappe.get_doc("Mock Generation Request", request_name)

    return {
        "status": request.status,
        "progress_percent": request.progress_percent,
        "records_created": request.records_created,
        "records_failed": request.records_failed,
        "current_batch": request.current_batch,
        "total_batches": request.total_batches,
        "started_at": request.started_at,
        "completed_at": request.completed_at,
        "duration_seconds": request.duration_seconds,
        "error_message": request.error_message
    }

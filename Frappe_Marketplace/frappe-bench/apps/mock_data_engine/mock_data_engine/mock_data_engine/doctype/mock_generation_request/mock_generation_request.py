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
        "Draft": ["Queued", "Cancelled"],
        "Queued": ["Processing", "Cancelled"],
        "Processing": ["Completed", "Failed", "Cancelled"],  # Allow cancel from Processing
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
        # Skip validation if ignore_validate flag is set (e.g., for cancel operation)
        if getattr(self.flags, 'ignore_validate', False):
            return
        
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
        if self.status == "Cancelled":
            frappe.throw(
                _("Cannot queue a cancelled request. Please create a new request."),
                title=_("Invalid Status")
            )
        
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
        # Use correct module path
        frappe.enqueue(
            "mock_data_engine.mock_data_engine.doctype."
            "mock_generation_request.mock_generation_request.execute_generation",
            request_name=self.name,
            queue="long",
            timeout=7200,  # 2 hours timeout (increased for large batches)
            job_id=f"mock_gen_{self.name}",
            now=False,  # Don't execute immediately, use queue
            is_async=True  # Ensure it runs in background
        )
        
        # Log for debugging
        frappe.log_error(
            message=f"Mock Generation Request {self.name} queued for background processing",
            title="Mock Generation Queued"
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
        Cancel a queued or processing generation request.

        Returns:
            dict: Result containing success status and message.
        """
        if self.status not in ("Queued", "Processing"):
            frappe.throw(
                _("Only requests in 'Queued' or 'Processing' status can be cancelled. Current status: {0}").format(
                    self.status
                ),
                title=_("Invalid Status")
            )
        
        # Skip validation for cancel operation
        self.flags.ignore_validate = True

        # Set cancellation flag in cache FIRST (before status change)
        frappe.cache().set_value(f"mock_data_engine:cancel_request:{self.name}", "1", expires_in_sec=3600)
        frappe.cache().set_value(f"mock_gen_cancelled_{self.name}", True, expires_in_sec=3600)
        
        # Try to cancel the background job using RQ
        job_id = f"mock_gen_{self.name}"
        try:
            from rq import cancel_job
            from frappe.utils.background_jobs import get_redis_conn
            import redis
            
            # Get Redis connection
            redis_conn = get_redis_conn()
            if redis_conn:
                # Try to cancel the job
                try:
                    cancel_job(job_id, connection=redis_conn)
                except Exception:
                    # Job might not exist or already finished
                    pass
        except ImportError:
            pass
        except Exception as e:
            frappe.log_error(
                message=f"Failed to cancel background job {job_id}: {str(e)}",
                title="Cancel Job Error"
            )

        # Mark as cancelled
        self.status = "Cancelled"
        self.completed_at = now_datetime()
        self.error_message = _("Cancelled by user")
        self.save()  # flags.ignore_validate already set above

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
            self.progress_percent = min(100.0, max(0.0, (processed / total_records) * 100.0))
        else:
            # If no target records, set to 100% if completed, 0% otherwise
            if self.status in ["Completed", "Failed", "Cancelled"]:
                self.progress_percent = 100.0
            else:
                self.progress_percent = 0.0

        self.db_update()
        frappe.db.commit()

        # Publish real-time progress update via socket
        frappe.publish_realtime(
            "mock_generation_progress",
            {
                "request_name": self.name,
                "progress_percent": self.progress_percent,
                "records_created": self.records_created or 0,
                "records_failed": self.records_failed or 0,
                "current_batch": self.current_batch or 0,
                "total_batches": self.total_batches or 0,
                "total_records": total_records
            },
            doctype=self.doctype,
            docname=self.name
        )
        
        # Also use standard progress for Frappe's progress bar
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
                total = 0
                for row in (profile_doc.doctype_quantities or []):
                    # Check if enabled (default to True if not set)
                    if getattr(row, 'enabled', True):
                        # Use doctype_name field (correct field name in child table)
                        doctype_name = getattr(row, 'doctype_name', None) or getattr(row, 'doctype', None)
                        if doctype_name:  # Only count if doctype is set
                            total += (row.record_count or 0)
                return total
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
    import frappe
    import traceback
    
    try:
        # Check if cancelled before starting
        if frappe.cache().get_value(f"mock_gen_cancelled_{request_name}"):
            frappe.log_error(
                message=f"Generation cancelled before start for request: {request_name}",
                title="Mock Generation Cancelled"
            )
            return
        
        # Log start
        frappe.log_error(
            message=f"Starting mock generation for request: {request_name}",
            title="Mock Generation Started"
        )
        
        request = frappe.get_doc("Mock Generation Request", request_name)
        
        # Check if request was cancelled
        if request.status == "Cancelled":
            frappe.log_error(
                message=f"Request {request_name} was cancelled before processing",
                title="Mock Generation Cancelled"
            )
            return

        # Verify status is Queued
        if request.status != "Queued":
            frappe.log_error(
                message=f"Request {request_name} is not in Queued status: {request.status}",
                title="Mock Generation - Invalid Status"
            )
            return

        # Start processing
        request.start_processing()
        
        # Log processing start
        frappe.log_error(
            message=f"Mock generation processing started for: {request_name}",
            title="Mock Generation Processing"
        )

        # Get settings
        settings = frappe.get_single("Mock Engine Settings")

        # Determine effective parameters
        locale = request.get_effective_locale()
        seed = request.get_effective_seed()
        
        # Determine AI setting: Priority: Request > Profile > Settings
        use_ai = False
        if hasattr(request, 'use_ai_generation') and request.use_ai_generation is not None:
            # Request-level setting takes priority
            use_ai = bool(request.use_ai_generation)
        elif request.generation_mode == "From Profile" and request.profile:
            # Check profile-level setting
            try:
                profile = frappe.get_doc("Mock Generation Profile", request.profile)
                if hasattr(profile, 'use_ai_generation') and profile.use_ai_generation is not None:
                    use_ai = bool(profile.use_ai_generation)
                else:
                    use_ai = settings.enable_ai_generation if settings else False
            except Exception:
                use_ai = settings.enable_ai_generation if settings else False
        else:
            # Fall back to settings
            use_ai = settings.enable_ai_generation if settings else False
        
        # Ensure AI is only enabled if API key is configured
        if use_ai and settings:
            # Check if any API key is configured
            has_api_key = False
            try:
                if hasattr(settings, 'gemini_api_key') and settings.gemini_api_key:
                    api_key = settings.get_password("gemini_api_key")
                    if api_key:
                        has_api_key = True
            except Exception:
                pass
            try:
                if hasattr(settings, 'openai_api_key') and settings.openai_api_key:
                    api_key = settings.get_password("openai_api_key")
                    if api_key:
                        has_api_key = True
            except Exception:
                pass
            try:
                if hasattr(settings, 'anthropic_api_key') and settings.anthropic_api_key:
                    api_key = settings.get_password("anthropic_api_key")
                    if api_key:
                        has_api_key = True
            except Exception:
                pass
            
            if not has_api_key:
                frappe.log_error(
                    message="AI generation requested but no API key configured. Falling back to standard generation.",
                    title="Mock Generation - AI Disabled"
                )
                use_ai = False
        
        auto_resolve = request.auto_resolve_dependencies if hasattr(request, 'auto_resolve_dependencies') else True
        fail_on_error = request.fail_on_error if hasattr(request, 'fail_on_error') else False
        log_generation_details = request.log_generation_details if hasattr(request, 'log_generation_details') else True

        if request.generation_mode == "Single DocType":
            # Single DocType generation
            from mock_data_engine.core.generator import MockDataGenerator

            generator = MockDataGenerator(
                request_name=request_name,
                locale=locale,
                seed=seed,
                fail_on_error=fail_on_error,
                auto_resolve_dependencies=auto_resolve,
                enable_ai_generation=use_ai,
                publish_progress=False,
            )
            generator._request_doc = request

            # Use exact record_count, no fallback - user specified value should be respected
            record_count = request.record_count if request.record_count is not None else 10
            generator.add_doctype(
                doctype=request.target_doctype,
                count=record_count,
                use_ai=use_ai,
            )

            result = generator.execute()

            # Update request with results
            request.records_created = result.total_created
            request.records_failed = result.total_failed
            request.progress_percent = 100

        elif request.generation_mode == "Multiple DocTypes":
            # Multiple DocTypes from selected_doctypes child table
            from mock_data_engine.core.generator import MockDataGenerator

            total_created = 0
            total_failed = 0
            total_records = sum((row.record_count or 0) for row in (request.selected_doctypes or []))

            for row in (request.selected_doctypes or []):
                if not row.doctype_name:
                    continue

                try:
                    generator = MockDataGenerator(
                        request_name=request_name,
                        locale=locale,
                        seed=seed,
                        fail_on_error=fail_on_error,
                        auto_resolve_dependencies=auto_resolve,
                        enable_ai_generation=use_ai,
                        publish_progress=False,
                    )
                    generator._request_doc = request

                    # Use exact record_count from row, no fallback
                    record_count = row.record_count if row.record_count is not None else 10
                    generator.add_doctype(
                        doctype=row.doctype_name,
                        count=record_count,
                        use_ai=use_ai,
                    )

                    result = generator.execute()

                    total_created += result.total_created
                    total_failed += result.total_failed
                    frappe.db.commit()
                except Exception as row_error:
                    # Count failed records based on actual requested count
                    failed_count = row.record_count if row.record_count is not None else 10
                    total_failed += failed_count
                    frappe.log_error(
                        message=f"{row.doctype_name}: {str(row_error)}\n{frappe.get_traceback()}",
                        title=f"Mock Generation Failed for {row.doctype_name}"
                    )
                    frappe.db.commit()
                    if fail_on_error:
                        raise

                # Update progress
                processed = total_created + total_failed
                if total_records > 0:
                    request.update_progress(
                        records_created=total_created,
                        records_failed=total_failed
                    )

            request.records_created = total_created
            request.records_failed = total_failed
            request.progress_percent = 100

        elif request.generation_mode == "From Profile" and request.profile:
            from mock_data_engine.core.generator import MockDataGenerator

            profile = frappe.get_doc("Mock Generation Profile", request.profile)
            total_created = 0
            total_failed = 0
            doctypes_to_generate = []

            # Get default record count from settings if not specified
            settings_default_count = settings.default_record_count if settings and hasattr(settings, 'default_record_count') and settings.default_record_count else 10
            
            # Priority: Request record_count > Profile doctype_quantities record_count > Settings default
            # But for "From Profile" mode, we prioritize profile's doctype_quantities over request.record_count
            
            if getattr(profile, 'target_mode', '') == 'All DocTypes in App' and getattr(profile, 'target_app', ''):
                # Try multiple module name formats (e.g. "Tr Tradehub", "tr_tradehub")
                app_module = profile.target_app.replace('_', ' ').title()
                app_doctypes = frappe.get_all('DocType', filters={'module': app_module}, pluck='name', order_by='name')
                if not app_doctypes:
                    app_doctypes = frappe.get_all('DocType', filters={'module': profile.target_app}, pluck='name', order_by='name')
                if not app_doctypes:
                    # Try with just capitalized first letter
                    cap_module = profile.target_app.replace('_', ' ').capitalize()
                    app_doctypes = frappe.get_all('DocType', filters={'module': cap_module}, pluck='name', order_by='name')
                
                # For "All DocTypes in App", determine record count priority:
                # 1. Request record_count (if explicitly set and > 0)
                # 2. Profile doctype_quantities'deki ilk record_count (if exists)
                # 3. Settings default
                profile_record_count = None
                if profile.doctype_quantities and len(profile.doctype_quantities) > 0:
                    # Get first non-null record_count from profile
                    for row in profile.doctype_quantities:
                        if hasattr(row, 'record_count') and row.record_count is not None:
                            profile_record_count = int(row.record_count)
                            break
                
                # Determine final count
                if request.record_count is not None and request.record_count > 0:
                    count = int(request.record_count)  # Request takes priority if set
                elif profile_record_count is not None:
                    count = profile_record_count  # Use profile's record_count
                else:
                    count = settings_default_count  # Fallback to settings
                
                for dt_name in app_doctypes:
                    try:
                        m = frappe.get_meta(dt_name)
                        if not m.istable and not m.issingle:
                            doctypes_to_generate.append({'doctype': dt_name, 'count': count})
                    except Exception:
                        pass  # Skip invalid DocTypes
            elif getattr(profile, 'target_mode', '') == 'Specific DocTypes':
                for row in (profile.doctype_quantities or []):
                    # Use correct field name: doctype_name (not doctype)
                    doctype_name = getattr(row, 'doctype_name', None) or getattr(row, 'doctype', None)
                    if getattr(row, 'enabled', True) and doctype_name:
                        # CRITICAL: Use EXACT record_count from profile row, even if 0
                        # Only fallback to settings if record_count is None (not set)
                        if hasattr(row, 'record_count') and row.record_count is not None:
                            count = int(row.record_count)  # Use exact value from profile
                        else:
                            count = settings_default_count  # Only use default if not set in profile
                        doctypes_to_generate.append({'doctype': doctype_name, 'count': count})
            else:
                # Default to Specific DocTypes behavior
                for row in (profile.doctype_quantities or []):
                    # Use correct field name: doctype_name (not doctype)
                    doctype_name = getattr(row, 'doctype_name', None) or getattr(row, 'doctype', None)
                    if doctype_name:
                        # CRITICAL: Use EXACT record_count from profile row, even if 0
                        if hasattr(row, 'record_count') and row.record_count is not None:
                            count = int(row.record_count)  # Use exact value from profile
                        else:
                            count = settings_default_count  # Only use default if not set in profile
                        doctypes_to_generate.append({'doctype': doctype_name, 'count': count})

            # Get locale from profile if not set in request
            if locale:
                effective_locale = locale
            elif hasattr(profile, 'get_effective_locale'):
                effective_locale = profile.get_effective_locale()
            else:
                effective_locale = getattr(profile, 'locale', None) or settings.default_locale or 'tr_TR'

            # Create SHARED global context for cross-DocType consistency
            # This ensures all DocTypes in tr_tradehub app share the same context
            shared_global_context = None
            try:
                from mock_data_engine.core.global_context import GlobalContextManager
                shared_global_context = GlobalContextManager(seed=seed)
                # Set industry context if available
                if hasattr(profile, 'industry') and profile.industry:
                    try:
                        ind_doc = frappe.get_doc("Mock Industry", profile.industry)
                        if hasattr(ind_doc, "get_ai_context"):
                            industry_ai_context = ind_doc.get_ai_context()
                            shared_global_context.set_industry_context({
                                "industry_name": ind_doc.industry_name or ind_doc.name,
                                "description": getattr(ind_doc, "description", ""),
                                **industry_ai_context
                            })
                    except Exception:
                        pass
            except Exception:
                pass
            
            for idx, dt_info in enumerate(doctypes_to_generate):
                # Check if request was cancelled (check both status and cache)
                request.reload()
                if request.status == "Cancelled" or frappe.cache().get_value(f"mock_data_engine:cancel_request:{request_name}"):
                    frappe.log_error(
                        message=f"Generation cancelled for request {request_name}",
                        title="Mock Generation Cancelled"
                    )
                    request.flags.ignore_validate = True
                    request.status = "Cancelled"
                    request.completed_at = frappe.utils.now_datetime()
                    request.error_message = _("Cancelled by user")
                    request.save()
                    frappe.db.commit()
                    return
                
                try:
                    # Create a generator PER DocType so each gets fresh state
                    # and proper AI context from the request/profile
                    generator = MockDataGenerator(
                        request_name=request_name,
                        profile_name=request.profile,
                        locale=effective_locale,
                        seed=seed,
                        fail_on_error=fail_on_error,
                        auto_resolve_dependencies=auto_resolve,
                        enable_ai_generation=use_ai,
                        publish_progress=False,
                    )
                    # Store request doc so _generate_with_ai can read profile/industry
                    generator._request_doc = request
                    
                    # SHARE global context across all generators for consistency
                    if shared_global_context:
                        generator._global_context = shared_global_context
                        # Sync from previous generators' record caches
                        shared_global_context.sync_from_record_cache(generator.record_cache)

                    generator.add_doctype(
                        doctype=dt_info['doctype'],
                        count=dt_info['count'],
                        use_ai=use_ai,
                    )

                    result = generator.execute()
                    
                    # Sync global context AFTER generation to capture all created records
                    if shared_global_context:
                        shared_global_context.sync_from_record_cache(generator.record_cache)
                    
                    total_created += result.total_created
                    total_failed += result.total_failed

                    # Create generation log entry - Save directly to DB to avoid reload issues
                    if log_generation_details:
                        try:
                            # Map generation_method to valid values: "Faker", "LLM", "Hybrid"
                            method_map = {
                                True: "LLM",  # AI generation = LLM
                                False: "Faker"  # Standard generation = Faker
                            }
                            generation_method = method_map.get(use_ai, "Faker")
                            
                            # Determine status
                            if result.total_failed == 0:
                                log_status = 'Completed'
                            elif result.total_created > 0:
                                log_status = 'Partially Completed'
                            else:
                                log_status = 'Failed'
                            
                            # Save log directly to database to avoid reload() issues
                            log_doc = frappe.get_doc({
                                'doctype': 'Mock Generation Log',
                                'parent': request_name,
                                'parenttype': 'Mock Generation Request',
                                'parentfield': 'generation_logs',
                                'doctype_name': dt_info['doctype'],
                                'status': log_status,
                                'records_created': result.total_created,
                                'records_failed': result.total_failed,
                                'generation_method': generation_method,
                                'created_at': frappe.utils.now_datetime()
                            })
                            if result.total_failed > 0:
                                # Get actual error messages from result
                                error_msgs = []
                                if hasattr(result, 'failed_records') and result.failed_records:
                                    for doctype_name, failures in result.failed_records.items():
                                        if doctype_name == dt_info['doctype']:
                                            for failure in failures[:3]:  # Limit to first 3 errors
                                                if isinstance(failure, dict) and 'error' in failure:
                                                    error_msgs.append(failure['error'][:200])
                                if error_msgs:
                                    log_doc.error_message = "; ".join(error_msgs)[:500]
                                else:
                                    log_doc.error_message = f"Some records failed during generation (Check Error Log for details)"
                            
                            # Set flags to skip any after_insert hooks that might cause issues
                            log_doc.flags.ignore_validate = True
                            log_doc.flags.ignore_permissions = True
                            log_doc.insert(ignore_permissions=True)
                            frappe.db.commit()
                            
                        except Exception as log_error:
                            frappe.log_error(
                                message=f"Failed to create generation log: {str(log_error)}\nTraceback: {frappe.get_traceback()}",
                                title="Generation Log Error"
                            )
                            frappe.db.commit()

                    # Update progress after each DocType
                    request.update_progress(
                        records_created=total_created,
                        records_failed=total_failed,
                    )
                    
                    # Check cancellation AFTER updating progress and logs
                    request.reload()
                    if request.status == "Cancelled" or frappe.cache().get_value(f"mock_data_engine:cancel_request:{request_name}"):
                        request.flags.ignore_validate = True
                        request.status = "Cancelled"
                        request.completed_at = frappe.utils.now_datetime()
                        request.error_message = _("Cancelled by user")
                        request.save()
                        frappe.db.commit()
                        return
                    
                    # Save progress update
                    frappe.db.commit()

                except Exception as row_error:
                    total_failed += dt_info['count']
                    error_msg = f"{dt_info['doctype']}: {str(row_error)}\n{frappe.get_traceback()}"
                    
                    # Log to Error Log with full traceback
                    frappe.log_error(
                        message=f"Mock Generation Failed for {dt_info['doctype']}\n\nError: {str(row_error)}\n\nFull Traceback:\n{frappe.get_traceback()}",
                        title=f"Mock Generation Failed: {dt_info['doctype']}"
                    )
                    
                    # Create generation log entry for failed DocType - Save directly to DB
                    if log_generation_details:
                        try:
                            # Map generation_method to valid values: "Faker", "LLM", "Hybrid"
                            method_map = {
                                True: "LLM",  # AI generation = LLM
                                False: "Faker"  # Standard generation = Faker
                            }
                            generation_method = method_map.get(use_ai, "Faker")
                            
                            # Save log directly to database to avoid reload() issues
                            log_doc = frappe.get_doc({
                                'doctype': 'Mock Generation Log',
                                'parent': request_name,
                                'parenttype': 'Mock Generation Request',
                                'parentfield': 'generation_logs',
                                'doctype_name': dt_info['doctype'],
                                'status': 'Failed',
                                'records_created': 0,
                                'records_failed': dt_info['count'],
                                'error_message': f"{str(row_error)[:400]}\n(Check Error Log for full details)",  # Limit error message length but add hint
                                'generation_method': generation_method,
                                'created_at': frappe.utils.now_datetime()
                            })
                            log_doc.insert(ignore_permissions=True)
                            frappe.db.commit()
                            
                        except Exception as log_error:
                            frappe.log_error(
                                message=f"Failed to create generation log: {str(log_error)}\nTraceback: {frappe.get_traceback()}",
                                title="Generation Log Error"
                            )
                            frappe.db.commit()
                    
                    # Commit error state
                    frappe.db.commit()
                    if fail_on_error:
                        raise

            request.records_created = total_created
            request.records_failed = total_failed
            request.progress_percent = 100

        # Mark as completed
        request.mark_completed()

        frappe.publish_realtime(
            "mock_generation_complete",
            {"request_name": request_name, "status": "Completed"},
            doctype="Mock Generation Request",
            docname=request_name
        )

    except Exception as e:
        frappe.log_error(
            message=frappe.get_traceback(),
            title=f"Mock Generation Failed: {request_name}"
        )

        try:
            request = frappe.get_doc("Mock Generation Request", request_name)
            request.mark_failed(str(e))

            frappe.publish_realtime(
                "mock_generation_complete",
                {"request_name": request_name, "status": "Failed"},
                doctype="Mock Generation Request",
                docname=request_name
            )
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

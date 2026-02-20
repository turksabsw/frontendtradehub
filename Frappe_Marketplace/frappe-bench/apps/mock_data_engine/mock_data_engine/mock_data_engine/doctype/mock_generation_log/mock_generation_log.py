# Copyright (c) 2024, Custom and contributors
# For license information, please see license.txt

"""
Mock Generation Log - Child Table DocType Controller

This module provides the controller for Mock Generation Log, which is a child table
of Mock Generation Request that tracks per-DocType generation status and statistics.

Log Status Values:
    - Pending: Not yet started
    - Processing: Currently generating
    - Completed: All records generated successfully
    - Partially Completed: Some records generated, some failed
    - Failed: All records failed to generate
    - Skipped: DocType was skipped (e.g., excluded, no required data)
"""

from frappe.model.document import Document


class MockGenerationLog(Document):
    """
    Controller for Mock Generation Log child table.

    Tracks generation statistics and status for individual DocTypes
    within a Mock Generation Request.
    """

    def validate(self):
        """Validate the log entry."""
        self.validate_counts()
        self.update_status_from_counts()

    def validate_counts(self):
        """Ensure record counts are non-negative."""
        if self.records_created is not None and self.records_created < 0:
            self.records_created = 0
        if self.records_failed is not None and self.records_failed < 0:
            self.records_failed = 0
        if self.duration_ms is not None and self.duration_ms < 0:
            self.duration_ms = 0

    def update_status_from_counts(self):
        """
        Automatically update status based on record counts.

        This helps maintain consistency between counts and status.
        """
        if self.status in ("Pending", "Processing", "Skipped"):
            # Don't auto-update these statuses
            return

        created = self.records_created or 0
        failed = self.records_failed or 0

        if created == 0 and failed == 0:
            # No records processed yet
            return

        if failed == 0 and created > 0:
            self.status = "Completed"
        elif created == 0 and failed > 0:
            self.status = "Failed"
        elif created > 0 and failed > 0:
            self.status = "Partially Completed"

    def mark_processing(self):
        """Mark this log entry as currently processing."""
        self.status = "Processing"
        from frappe.utils import now_datetime
        self.created_at = now_datetime()

    def mark_completed(self, records_created, duration_ms=None, method=None):
        """
        Mark this log entry as completed.

        Args:
            records_created: Number of records successfully created.
            duration_ms: Time taken in milliseconds.
            method: Generation method used (Faker/LLM/Hybrid).
        """
        self.status = "Completed"
        self.records_created = records_created
        self.records_failed = 0
        if duration_ms is not None:
            self.duration_ms = duration_ms
        if method:
            self.generation_method = method

    def mark_failed(self, error_message, records_created=0, records_failed=0,
                   duration_ms=None):
        """
        Mark this log entry as failed.

        Args:
            error_message: The error message.
            records_created: Number of records created before failure.
            records_failed: Number of records that failed.
            duration_ms: Time taken in milliseconds.
        """
        self.records_created = records_created
        self.records_failed = records_failed
        self.error_message = str(error_message)[:500] if error_message else None

        if records_created > 0:
            self.status = "Partially Completed"
        else:
            self.status = "Failed"

        if duration_ms is not None:
            self.duration_ms = duration_ms

    def mark_skipped(self, reason=None):
        """
        Mark this log entry as skipped.

        Args:
            reason: Reason for skipping (stored in error_message).
        """
        self.status = "Skipped"
        self.records_created = 0
        self.records_failed = 0
        if reason:
            self.error_message = str(reason)[:500]

    def get_success_rate(self):
        """
        Calculate the success rate for this DocType generation.

        Returns:
            float: Success rate as a percentage (0-100), or None if no records.
        """
        created = self.records_created or 0
        failed = self.records_failed or 0
        total = created + failed

        if total == 0:
            return None

        return (created / total) * 100

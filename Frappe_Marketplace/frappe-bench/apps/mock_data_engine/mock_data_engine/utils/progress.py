# Copyright (c) 2024, Mock Data Engine and contributors
# For license information, please see license.txt

"""
Progress Tracking Module for Mock Data Engine.

This module provides the ProgressTracker class for tracking and reporting
progress during mock data generation operations. It integrates with Frappe's
real-time event system to provide live progress updates to the UI.

Key Features:
- Real-time progress updates via frappe.publish_progress()
- Per-DocType progress tracking
- Batch progress calculation
- Time estimation for remaining work
- Error tracking and reporting

Usage:
    from mock_data_engine.utils.progress import ProgressTracker

    # Create tracker for a generation request
    tracker = ProgressTracker(
        request_name="MGR-2024-00001",
        total_records=1000
    )

    # Update progress as records are created
    for i in range(1000):
        create_record()
        tracker.increment()

    # Or track by DocType
    tracker.set_doctype("Customer", 100)
    for i in range(100):
        create_customer()
        tracker.increment_doctype("Customer")

    # Check progress
    print(f"Progress: {tracker.percent}%")
    print(f"ETA: {tracker.estimated_time_remaining}s")
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    pass


@dataclass
class DocTypeProgress:
    """
    Progress tracking for a single DocType.

    Attributes:
        doctype: The DocType name
        total: Total records to generate
        created: Records successfully created
        failed: Records that failed to create
        skipped: Records that were skipped
        started_at: Timestamp when generation started
        completed_at: Timestamp when generation completed
    """
    doctype: str
    total: int = 0
    created: int = 0
    failed: int = 0
    skipped: int = 0
    started_at: Optional[float] = None
    completed_at: Optional[float] = None

    @property
    def percent(self) -> float:
        """Calculate completion percentage for this DocType."""
        if self.total <= 0:
            return 100.0
        return ((self.created + self.failed + self.skipped) / self.total) * 100

    @property
    def is_complete(self) -> bool:
        """Check if DocType generation is complete."""
        return (self.created + self.failed + self.skipped) >= self.total

    @property
    def duration_seconds(self) -> Optional[float]:
        """Calculate duration in seconds."""
        if self.started_at is None:
            return None
        end_time = self.completed_at or time.time()
        return end_time - self.started_at

    @property
    def records_per_second(self) -> Optional[float]:
        """Calculate generation rate."""
        duration = self.duration_seconds
        if duration is None or duration <= 0:
            return None
        total_processed = self.created + self.failed + self.skipped
        return total_processed / duration

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "doctype": self.doctype,
            "total": self.total,
            "created": self.created,
            "failed": self.failed,
            "skipped": self.skipped,
            "percent": round(self.percent, 2),
            "is_complete": self.is_complete,
            "duration_seconds": self.duration_seconds,
            "records_per_second": self.records_per_second,
        }


class ProgressTracker:
    """
    Tracks progress of mock data generation operations.

    This class provides comprehensive progress tracking for generation
    operations, including per-DocType tracking, time estimates, and
    real-time UI updates via Frappe's event system.

    Attributes:
        request_name: The Mock Generation Request document name
        total_records: Total number of records to generate
        publish_realtime: Whether to publish progress via frappe.publish_realtime

    Example:
        >>> tracker = ProgressTracker("MGR-001", total_records=500)
        >>> tracker.set_doctype("Customer", 100)
        >>> tracker.set_doctype("Item", 400)
        >>> for i in range(100):
        ...     create_customer()
        ...     tracker.increment_doctype("Customer")
        >>> print(f"Progress: {tracker.percent}%")
    """

    def __init__(
        self,
        request_name: Optional[str] = None,
        total_records: int = 0,
        publish_realtime: bool = True,
        update_interval: float = 1.0,
        on_progress: Optional[Callable[[float], None]] = None
    ):
        """
        Initialize ProgressTracker.

        Args:
            request_name: The Mock Generation Request document name.
                         Used for publishing progress to the specific request.
            total_records: Total number of records to generate.
            publish_realtime: Whether to publish progress via frappe.publish_realtime.
            update_interval: Minimum interval (seconds) between UI updates.
            on_progress: Optional callback function called on progress updates.
        """
        self._request_name = request_name
        self._total_records = total_records
        self._publish_realtime = publish_realtime
        self._update_interval = update_interval
        self._on_progress = on_progress

        # Overall counters
        self._created = 0
        self._failed = 0
        self._skipped = 0

        # Per-DocType tracking
        self._doctypes: Dict[str, DocTypeProgress] = {}

        # Timing
        self._started_at: Optional[float] = None
        self._completed_at: Optional[float] = None
        self._last_update: float = 0

        # Batch tracking
        self._current_batch: int = 0
        self._total_batches: int = 0
        self._batch_size: int = 0

        # Phase tracking
        self._current_phase: int = 0
        self._phase_name: str = ""
        self._phase_current: int = 0
        self._phase_total: int = 0
        self._phase_doctype: str = ""

        # Error tracking
        self._errors: List[Dict[str, Any]] = []

    @property
    def request_name(self) -> Optional[str]:
        """Get the request name."""
        return self._request_name

    @property
    def total_records(self) -> int:
        """Get total records to generate."""
        return self._total_records

    @total_records.setter
    def total_records(self, value: int) -> None:
        """Set total records to generate."""
        self._total_records = max(0, value)

    @property
    def created(self) -> int:
        """Get total records created."""
        return self._created

    @property
    def failed(self) -> int:
        """Get total records failed."""
        return self._failed

    @property
    def skipped(self) -> int:
        """Get total records skipped."""
        return self._skipped

    @property
    def processed(self) -> int:
        """Get total records processed (created + failed + skipped)."""
        return self._created + self._failed + self._skipped

    @property
    def percent(self) -> float:
        """
        Calculate overall completion percentage.

        Returns:
            Percentage from 0 to 100.
        """
        if self._total_records <= 0:
            return 100.0 if self.processed > 0 else 0.0
        return min(100.0, (self.processed / self._total_records) * 100)

    @property
    def is_complete(self) -> bool:
        """Check if generation is complete."""
        return self.processed >= self._total_records

    @property
    def started_at(self) -> Optional[float]:
        """Get generation start timestamp."""
        return self._started_at

    @property
    def completed_at(self) -> Optional[float]:
        """Get generation completion timestamp."""
        return self._completed_at

    @property
    def duration_seconds(self) -> Optional[float]:
        """
        Calculate total duration in seconds.

        Returns:
            Duration in seconds, or None if not started.
        """
        if self._started_at is None:
            return None
        end_time = self._completed_at or time.time()
        return end_time - self._started_at

    @property
    def records_per_second(self) -> Optional[float]:
        """
        Calculate average generation rate.

        Returns:
            Records per second, or None if not enough data.
        """
        duration = self.duration_seconds
        if duration is None or duration <= 0:
            return None
        return self.processed / duration

    @property
    def estimated_time_remaining(self) -> Optional[float]:
        """
        Estimate remaining time in seconds.

        Returns:
            Estimated seconds remaining, or None if cannot estimate.
        """
        rate = self.records_per_second
        if rate is None or rate <= 0:
            return None

        remaining = self._total_records - self.processed
        if remaining <= 0:
            return 0

        return remaining / rate

    @property
    def current_batch(self) -> int:
        """Get current batch number."""
        return self._current_batch

    @property
    def total_batches(self) -> int:
        """Get total number of batches."""
        return self._total_batches

    def start(self) -> None:
        """Mark generation as started."""
        self._started_at = time.time()
        self._publish_progress()

    def complete(self) -> None:
        """Mark generation as complete."""
        self._completed_at = time.time()
        self._publish_progress(force=True)

    def set_doctype(self, doctype: str, total: int) -> DocTypeProgress:
        """
        Set up tracking for a DocType.

        Args:
            doctype: The DocType name.
            total: Total records to generate for this DocType.

        Returns:
            DocTypeProgress instance for the DocType.
        """
        progress = DocTypeProgress(doctype=doctype, total=total)
        self._doctypes[doctype] = progress
        return progress

    def start_doctype(self, doctype: str) -> None:
        """
        Mark a DocType as started.

        Args:
            doctype: The DocType name.
        """
        if doctype in self._doctypes:
            self._doctypes[doctype].started_at = time.time()

    def complete_doctype(self, doctype: str) -> None:
        """
        Mark a DocType as complete.

        Args:
            doctype: The DocType name.
        """
        if doctype in self._doctypes:
            self._doctypes[doctype].completed_at = time.time()

    def increment(self, count: int = 1) -> None:
        """
        Increment overall created count.

        Args:
            count: Number of records created (default 1).
        """
        self._created += count
        self._publish_progress()

    def increment_failed(self, count: int = 1) -> None:
        """
        Increment overall failed count.

        Args:
            count: Number of records failed (default 1).
        """
        self._failed += count
        self._publish_progress()

    def increment_skipped(self, count: int = 1) -> None:
        """
        Increment overall skipped count.

        Args:
            count: Number of records skipped (default 1).
        """
        self._skipped += count
        self._publish_progress()

    def increment_doctype(
        self,
        doctype: str,
        created: int = 0,
        failed: int = 0,
        skipped: int = 0
    ) -> None:
        """
        Increment counts for a specific DocType.

        Args:
            doctype: The DocType name.
            created: Number of records created.
            failed: Number of records failed.
            skipped: Number of records skipped.
        """
        if doctype not in self._doctypes:
            self._doctypes[doctype] = DocTypeProgress(doctype=doctype)

        progress = self._doctypes[doctype]
        progress.created += created
        progress.failed += failed
        progress.skipped += skipped

        # Also update overall counters
        self._created += created
        self._failed += failed
        self._skipped += skipped

        self._publish_progress()

    def set_batch_info(
        self,
        current_batch: int,
        total_batches: int,
        batch_size: int = 0
    ) -> None:
        """
        Set batch processing information.

        Args:
            current_batch: Current batch number (1-indexed).
            total_batches: Total number of batches.
            batch_size: Size of each batch.
        """
        self._current_batch = current_batch
        self._total_batches = total_batches
        self._batch_size = batch_size

    def set_phase(self, phase_number: int, phase_name: str) -> None:
        """
        Set the current generation phase.

        The generator uses a three-phase approach:
        - Phase 1: Independent DocTypes (no dependencies)
        - Phase 2: Dependent DocTypes (dependencies satisfied)
        - Phase 3: Circular DocTypes (two-pass with backfill)

        Args:
            phase_number: The phase number (1, 2, or 3).
            phase_name: Human-readable name for the phase.

        Example:
            >>> tracker.set_phase(1, "Independent DocTypes")
            >>> tracker.set_phase(2, "Dependent DocTypes")
            >>> tracker.set_phase(3, "Circular DocTypes (First Pass)")
        """
        self._current_phase = phase_number
        self._phase_name = phase_name
        self._phase_current = 0
        self._phase_total = 0
        self._phase_doctype = ""
        self._publish_progress()

    def set_phase_progress(
        self,
        current: int,
        total: int,
        doctype: str = ""
    ) -> None:
        """
        Set progress within the current phase.

        Args:
            current: Current DocType index within the phase (1-indexed).
            total: Total number of DocTypes in the phase.
            doctype: Name of the DocType currently being processed.

        Example:
            >>> tracker.set_phase(1, "Independent DocTypes")
            >>> tracker.set_phase_progress(1, 3, "Customer")
            >>> # Processing Customer (1 of 3 independent DocTypes)
        """
        self._phase_current = current
        self._phase_total = total
        self._phase_doctype = doctype
        self._publish_progress()

    @property
    def current_phase(self) -> int:
        """Get the current generation phase number."""
        return self._current_phase

    @property
    def phase_name(self) -> str:
        """Get the current phase name."""
        return self._phase_name

    @property
    def phase_percent(self) -> float:
        """Calculate progress percentage within current phase."""
        if self._phase_total <= 0:
            return 100.0
        return (self._phase_current / self._phase_total) * 100

    def add_error(
        self,
        message: str,
        doctype: Optional[str] = None,
        record_data: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        Record an error that occurred during generation.

        Args:
            message: Error message.
            doctype: Optional DocType that failed.
            record_data: Optional data that was being generated.
        """
        self._errors.append({
            "timestamp": time.time(),
            "message": message,
            "doctype": doctype,
            "record_data": record_data,
        })

    def get_doctype_progress(self, doctype: str) -> Optional[DocTypeProgress]:
        """
        Get progress for a specific DocType.

        Args:
            doctype: The DocType name.

        Returns:
            DocTypeProgress instance or None if not tracked.
        """
        return self._doctypes.get(doctype)

    def get_all_doctype_progress(self) -> Dict[str, DocTypeProgress]:
        """
        Get progress for all tracked DocTypes.

        Returns:
            Dictionary mapping DocType name to DocTypeProgress.
        """
        return self._doctypes.copy()

    def _should_publish(self) -> bool:
        """Check if we should publish progress update."""
        now = time.time()
        if now - self._last_update >= self._update_interval:
            return True
        return False

    def _publish_progress(self, force: bool = False) -> None:
        """
        Publish progress update.

        Args:
            force: If True, publish regardless of interval.
        """
        if not force and not self._should_publish():
            return

        self._last_update = time.time()

        # Call callback if provided
        if self._on_progress:
            try:
                self._on_progress(self.percent)
            except Exception:
                pass  # Don't let callback errors break generation

        # Publish to Frappe realtime if enabled
        if self._publish_realtime and self._request_name:
            self._publish_to_frappe()

    def _publish_to_frappe(self) -> None:
        """Publish progress to Frappe realtime event system."""
        try:
            import frappe

            # Publish progress using frappe.publish_progress
            frappe.publish_progress(
                percent=round(self.percent, 1),
                title="Mock Data Generation",
                description=self._get_progress_description(),
                doctype="Mock Generation Request",
                docname=self._request_name,
            )

            # Also publish detailed progress via realtime
            frappe.publish_realtime(
                event="mock_generation_progress",
                message=self.to_dict(),
                doctype="Mock Generation Request",
                docname=self._request_name,
            )

        except ImportError:
            pass  # Frappe not available
        except Exception:
            pass  # Don't let publish errors break generation

    def _get_progress_description(self) -> str:
        """Get human-readable progress description."""
        parts = []

        # Phase info
        if self._current_phase > 0 and self._phase_name:
            if self._phase_total > 0:
                parts.append(
                    f"Phase {self._current_phase}: {self._phase_name} "
                    f"({self._phase_current}/{self._phase_total})"
                )
            else:
                parts.append(f"Phase {self._current_phase}: {self._phase_name}")

        # Current DocType
        if self._phase_doctype:
            parts.append(f"DocType: {self._phase_doctype}")

        # Records progress
        parts.append(f"{self._created} created")
        if self._failed > 0:
            parts.append(f"{self._failed} failed")
        if self._skipped > 0:
            parts.append(f"{self._skipped} skipped")

        # Batch info
        if self._total_batches > 0:
            parts.append(f"Batch {self._current_batch}/{self._total_batches}")

        # ETA
        eta = self.estimated_time_remaining
        if eta is not None and eta > 0:
            if eta < 60:
                parts.append(f"ETA: {int(eta)}s")
            else:
                minutes = int(eta / 60)
                parts.append(f"ETA: {minutes}m")

        return " | ".join(parts)

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert progress to dictionary for serialization.

        Returns:
            Dictionary with all progress information.
        """
        return {
            "request_name": self._request_name,
            "total_records": self._total_records,
            "created": self._created,
            "failed": self._failed,
            "skipped": self._skipped,
            "processed": self.processed,
            "percent": round(self.percent, 2),
            "is_complete": self.is_complete,
            "started_at": self._started_at,
            "completed_at": self._completed_at,
            "duration_seconds": self.duration_seconds,
            "records_per_second": self.records_per_second,
            "estimated_time_remaining": self.estimated_time_remaining,
            "current_batch": self._current_batch,
            "total_batches": self._total_batches,
            "batch_size": self._batch_size,
            "current_phase": self._current_phase,
            "phase_name": self._phase_name,
            "phase_current": self._phase_current,
            "phase_total": self._phase_total,
            "phase_doctype": self._phase_doctype,
            "phase_percent": round(self.phase_percent, 2),
            "doctypes": {
                dt: progress.to_dict()
                for dt, progress in self._doctypes.items()
            },
            "error_count": len(self._errors),
        }

    def get_summary(self) -> Dict[str, Any]:
        """
        Get a summary of the generation progress.

        Returns:
            Dictionary with summary information suitable for logging.
        """
        return {
            "total_records": self._total_records,
            "created": self._created,
            "failed": self._failed,
            "skipped": self._skipped,
            "success_rate": (
                (self._created / self._total_records * 100)
                if self._total_records > 0 else 100.0
            ),
            "duration_seconds": self.duration_seconds,
            "records_per_second": self.records_per_second,
            "doctypes_processed": len(self._doctypes),
            "errors": len(self._errors),
        }

    def __repr__(self) -> str:
        """String representation of ProgressTracker."""
        return (
            f"ProgressTracker("
            f"request='{self._request_name}', "
            f"progress={self.processed}/{self._total_records} ({self.percent:.1f}%), "
            f"created={self._created}, failed={self._failed}, skipped={self._skipped}"
            f")"
        )


def create_progress_tracker(
    request_name: Optional[str] = None,
    total_records: int = 0,
    **kwargs
) -> ProgressTracker:
    """
    Factory function to create a ProgressTracker.

    Args:
        request_name: The Mock Generation Request document name.
        total_records: Total number of records to generate.
        **kwargs: Additional arguments passed to ProgressTracker.

    Returns:
        A new ProgressTracker instance.

    Example:
        >>> tracker = create_progress_tracker("MGR-001", 1000)
        >>> tracker.start()
    """
    return ProgressTracker(
        request_name=request_name,
        total_records=total_records,
        **kwargs
    )

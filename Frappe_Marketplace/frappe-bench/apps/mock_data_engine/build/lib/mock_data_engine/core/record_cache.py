# Copyright (c) 2024, Mock Data Engine and contributors
# For license information, please see license.txt

"""
Record Cache Module for Mock Data Engine.

This module provides the RecordCache class for tracking records created
during mock data generation. It serves several critical purposes:

1. **Record Tracking**: Keep track of all records created during generation
   to avoid duplicates and enable cleanup/rollback.

2. **Circular Dependency Resolution**: Support the two-pass approach for
   handling circular dependencies by tracking records that need backfilling.

3. **Link Field Resolution**: Provide random selection from previously
   created records for Link field population.

4. **Statistics**: Track generation statistics (created, failed, skipped).

5. **Cleanup**: Enable rollback of generated records if generation fails.

Usage:
    cache = RecordCache()

    # Add records as they're created
    cache.add_record("Customer", "CUST-001")
    cache.add_record("Customer", "CUST-002", {"customer_name": "Test"})

    # Get random record for Link field
    customer_name = cache.get_random_record("Customer")

    # Get all records for a DocType
    all_customers = cache.get_records("Customer")

    # Track records needing backfill (two-pass approach)
    cache.add_pending_backfill("Sales Invoice", "INV-001", "customer", "Customer")

    # Get statistics
    stats = cache.get_statistics()
"""

from __future__ import annotations

import random
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    pass


@dataclass
class RecordEntry:
    """
    Represents a single record in the cache.

    Attributes:
        name: The document name (primary key)
        doctype: The DocType of the record
        data: Optional dictionary of field values
        created_at: Timestamp when the record was added to cache
        needs_backfill: Whether this record has NULL Link fields needing update
        backfill_fields: List of fields that need to be backfilled
        generation_method: How this record was generated (Faker, LLM, Hybrid)
    """
    name: str
    doctype: str
    data: Dict[str, Any] = field(default_factory=dict)
    created_at: Optional[float] = None
    needs_backfill: bool = False
    backfill_fields: List[str] = field(default_factory=list)
    generation_method: str = "Faker"

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "name": self.name,
            "doctype": self.doctype,
            "data": self.data,
            "created_at": self.created_at,
            "needs_backfill": self.needs_backfill,
            "backfill_fields": self.backfill_fields,
            "generation_method": self.generation_method,
        }


@dataclass
class BackfillEntry:
    """
    Represents a pending backfill operation for circular dependencies.

    When circular dependencies are detected, records are created with
    NULL Link fields. These entries track which fields need to be
    updated in the second pass.

    Attributes:
        doctype: The DocType of the record to update
        name: The document name to update
        fieldname: The field that needs to be backfilled
        target_doctype: The DocType of the Link field target
        resolved: Whether this backfill has been completed
        target_name: The resolved target document name (set after backfill)
    """
    doctype: str
    name: str
    fieldname: str
    target_doctype: str
    resolved: bool = False
    target_name: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "doctype": self.doctype,
            "name": self.name,
            "fieldname": self.fieldname,
            "target_doctype": self.target_doctype,
            "resolved": self.resolved,
            "target_name": self.target_name,
        }


@dataclass
class GenerationStatistics:
    """
    Statistics for mock data generation.

    Attributes:
        total_requested: Total number of records requested
        total_created: Total number of records successfully created
        total_failed: Total number of records that failed to create
        total_skipped: Total number of records skipped
        by_doctype: Per-DocType breakdown of statistics
        by_method: Per-generation-method breakdown
        backfills_pending: Number of pending backfill operations
        backfills_completed: Number of completed backfill operations
    """
    total_requested: int = 0
    total_created: int = 0
    total_failed: int = 0
    total_skipped: int = 0
    by_doctype: Dict[str, Dict[str, int]] = field(default_factory=dict)
    by_method: Dict[str, int] = field(default_factory=dict)
    backfills_pending: int = 0
    backfills_completed: int = 0

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "total_requested": self.total_requested,
            "total_created": self.total_created,
            "total_failed": self.total_failed,
            "total_skipped": self.total_skipped,
            "success_rate": self.success_rate,
            "by_doctype": self.by_doctype,
            "by_method": self.by_method,
            "backfills_pending": self.backfills_pending,
            "backfills_completed": self.backfills_completed,
        }

    @property
    def success_rate(self) -> float:
        """Calculate the success rate as a percentage."""
        if self.total_requested == 0:
            return 100.0
        return (self.total_created / self.total_requested) * 100


class RecordCache:
    """
    Cache for tracking records created during mock data generation.

    This class maintains an in-memory cache of all records created during
    a generation session. It supports:

    - Adding and retrieving records by DocType
    - Random selection for Link field resolution
    - Tracking pending backfills for circular dependencies
    - Generation statistics
    - Cleanup/rollback support

    The cache uses a dictionary structure keyed by DocType for efficient
    lookups and supports reproducible random selection via seeding.

    Attributes:
        seed: Optional random seed for reproducibility

    Example:
        >>> cache = RecordCache(seed=42)
        >>> cache.add_record("Customer", "CUST-001")
        >>> cache.add_record("Customer", "CUST-002")
        >>> cache.get_random_record("Customer")
        'CUST-001'  # Reproducible with seed
    """

    def __init__(self, seed: Optional[int] = None):
        """
        Initialize the RecordCache.

        Args:
            seed: Optional random seed for reproducible record selection
        """
        self._seed = seed
        self._random = random.Random(seed)

        # Main record storage: DocType -> {name -> RecordEntry}
        self._records: Dict[str, Dict[str, RecordEntry]] = defaultdict(dict)

        # Quick lookup: DocType -> list of names (for random selection)
        self._record_names: Dict[str, List[str]] = defaultdict(list)

        # Pending backfills for circular dependency resolution
        self._pending_backfills: List[BackfillEntry] = []

        # Track failed records: DocType -> list of error messages
        self._failed_records: Dict[str, List[Dict[str, Any]]] = defaultdict(list)

        # Track skipped records: DocType -> count
        self._skipped_records: Dict[str, int] = defaultdict(int)

        # Track requested counts: DocType -> count
        self._requested_counts: Dict[str, int] = defaultdict(int)

        # Generation method tracking
        self._method_counts: Dict[str, int] = defaultdict(int)

    @property
    def seed(self) -> Optional[int]:
        """Get the random seed."""
        return self._seed

    def set_seed(self, seed: int) -> None:
        """
        Set or reset the random seed.

        Args:
            seed: The random seed value
        """
        self._seed = seed
        self._random = random.Random(seed)

    def add_record(
        self,
        doctype: str,
        name: str,
        data: Optional[Dict[str, Any]] = None,
        needs_backfill: bool = False,
        backfill_fields: Optional[List[str]] = None,
        generation_method: str = "Faker"
    ) -> RecordEntry:
        """
        Add a created record to the cache.

        Args:
            doctype: The DocType of the record
            name: The document name (primary key)
            data: Optional dictionary of field values
            needs_backfill: Whether this record has fields needing backfill
            backfill_fields: List of fields that need backfilling
            generation_method: How the record was generated (Faker/LLM/Hybrid)

        Returns:
            The RecordEntry that was created

        Example:
            >>> cache = RecordCache()
            >>> entry = cache.add_record("Customer", "CUST-001", {"customer_name": "Test"})
            >>> entry.name
            'CUST-001'
        """
        import time

        entry = RecordEntry(
            name=name,
            doctype=doctype,
            data=data or {},
            created_at=time.time(),
            needs_backfill=needs_backfill,
            backfill_fields=backfill_fields or [],
            generation_method=generation_method,
        )

        # Only add if not already exists (avoid duplicates)
        if name not in self._records[doctype]:
            self._records[doctype][name] = entry
            self._record_names[doctype].append(name)
            self._method_counts[generation_method] += 1
        else:
            # Update existing entry
            self._records[doctype][name] = entry

        return entry

    def add_pending_backfill(
        self,
        doctype: str,
        name: str,
        fieldname: str,
        target_doctype: str
    ) -> BackfillEntry:
        """
        Add a pending backfill entry for circular dependency resolution.

        When a record is created with a NULL Link field due to circular
        dependencies, this method records the field that needs to be
        updated in the second pass.

        Args:
            doctype: The DocType of the record to update
            name: The document name to update
            fieldname: The field that needs to be backfilled
            target_doctype: The DocType of the Link field target

        Returns:
            The BackfillEntry that was created

        Example:
            >>> cache = RecordCache()
            >>> cache.add_record("Sales Invoice", "INV-001", needs_backfill=True)
            >>> cache.add_pending_backfill("Sales Invoice", "INV-001", "customer", "Customer")
        """
        entry = BackfillEntry(
            doctype=doctype,
            name=name,
            fieldname=fieldname,
            target_doctype=target_doctype,
        )
        self._pending_backfills.append(entry)

        # Also update the record entry
        if name in self._records[doctype]:
            record = self._records[doctype][name]
            record.needs_backfill = True
            if fieldname not in record.backfill_fields:
                record.backfill_fields.append(fieldname)

        return entry

    def mark_backfill_resolved(
        self,
        doctype: str,
        name: str,
        fieldname: str,
        target_name: str
    ) -> bool:
        """
        Mark a backfill entry as resolved.

        Args:
            doctype: The DocType of the record
            name: The document name
            fieldname: The field that was backfilled
            target_name: The resolved target document name

        Returns:
            True if the backfill was found and marked, False otherwise
        """
        for entry in self._pending_backfills:
            if (entry.doctype == doctype and
                entry.name == name and
                entry.fieldname == fieldname):
                entry.resolved = True
                entry.target_name = target_name
                return True
        return False

    def add_failed_record(
        self,
        doctype: str,
        error: str,
        data: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        Record a failed record creation attempt.

        Args:
            doctype: The DocType that failed
            error: The error message
            data: Optional data that was being inserted
        """
        self._failed_records[doctype].append({
            "error": error,
            "data": data or {},
        })

    def add_skipped_record(self, doctype: str, count: int = 1) -> None:
        """
        Record skipped records.

        Args:
            doctype: The DocType that was skipped
            count: Number of records skipped
        """
        self._skipped_records[doctype] += count

    def set_requested_count(self, doctype: str, count: int) -> None:
        """
        Set the requested count for a DocType.

        Args:
            doctype: The DocType
            count: The number of records requested
        """
        self._requested_counts[doctype] = count

    def get_record(self, doctype: str, name: str) -> Optional[RecordEntry]:
        """
        Get a specific record from the cache.

        Args:
            doctype: The DocType of the record
            name: The document name

        Returns:
            The RecordEntry if found, None otherwise
        """
        return self._records.get(doctype, {}).get(name)

    def get_records(self, doctype: str) -> List[RecordEntry]:
        """
        Get all records for a DocType.

        Args:
            doctype: The DocType to get records for

        Returns:
            List of RecordEntry objects
        """
        return list(self._records.get(doctype, {}).values())

    def get_record_names(self, doctype: str) -> List[str]:
        """
        Get all record names for a DocType.

        Args:
            doctype: The DocType to get names for

        Returns:
            List of document names
        """
        return self._record_names.get(doctype, []).copy()

    def get_random_record(self, doctype: str) -> Optional[str]:
        """
        Get a random record name for a DocType.

        Uses the configured seed for reproducibility.

        Args:
            doctype: The DocType to get a random record from

        Returns:
            A random document name, or None if no records exist

        Example:
            >>> cache = RecordCache(seed=42)
            >>> cache.add_record("Customer", "CUST-001")
            >>> cache.add_record("Customer", "CUST-002")
            >>> cache.get_random_record("Customer")
            'CUST-001'
        """
        names = self._record_names.get(doctype, [])
        if not names:
            return None
        return self._random.choice(names)

    def get_random_records(self, doctype: str, count: int) -> List[str]:
        """
        Get multiple random record names for a DocType.

        Args:
            doctype: The DocType to get records from
            count: Number of random records to return

        Returns:
            List of random document names (may be shorter than count if not enough records)
        """
        names = self._record_names.get(doctype, [])
        if not names:
            return []

        # If we need more than available, sample with replacement
        if count >= len(names):
            return names.copy()

        return self._random.sample(names, count)

    def has_records(self, doctype: str) -> bool:
        """
        Check if any records exist for a DocType.

        Args:
            doctype: The DocType to check

        Returns:
            True if records exist, False otherwise
        """
        return bool(self._record_names.get(doctype))

    def get_record_count(self, doctype: str) -> int:
        """
        Get the number of records for a DocType.

        Args:
            doctype: The DocType to count

        Returns:
            The number of cached records
        """
        return len(self._record_names.get(doctype, []))

    def get_all_doctypes(self) -> Set[str]:
        """
        Get all DocTypes that have cached records.

        Returns:
            Set of DocType names
        """
        return set(self._records.keys())

    def get_pending_backfills(self, doctype: Optional[str] = None) -> List[BackfillEntry]:
        """
        Get pending backfill entries.

        Args:
            doctype: Optional DocType to filter by

        Returns:
            List of unresolved BackfillEntry objects
        """
        entries = [e for e in self._pending_backfills if not e.resolved]
        if doctype:
            entries = [e for e in entries if e.doctype == doctype]
        return entries

    def get_pending_backfills_for_target(self, target_doctype: str) -> List[BackfillEntry]:
        """
        Get pending backfills that need records from a target DocType.

        Args:
            target_doctype: The DocType that backfills are waiting for

        Returns:
            List of BackfillEntry objects targeting the specified DocType
        """
        return [
            e for e in self._pending_backfills
            if not e.resolved and e.target_doctype == target_doctype
        ]

    def get_records_needing_backfill(self, doctype: Optional[str] = None) -> List[RecordEntry]:
        """
        Get records that have fields needing backfill.

        Args:
            doctype: Optional DocType to filter by

        Returns:
            List of RecordEntry objects with needs_backfill=True
        """
        records = []
        for dt, entries in self._records.items():
            if doctype and dt != doctype:
                continue
            for entry in entries.values():
                if entry.needs_backfill:
                    records.append(entry)
        return records

    def get_statistics(self) -> GenerationStatistics:
        """
        Get generation statistics.

        Returns:
            GenerationStatistics object with all counts
        """
        stats = GenerationStatistics()

        # Calculate totals from tracked data
        stats.total_requested = sum(self._requested_counts.values())
        stats.total_created = sum(len(names) for names in self._record_names.values())
        stats.total_failed = sum(len(errors) for errors in self._failed_records.values())
        stats.total_skipped = sum(self._skipped_records.values())

        # Per-DocType breakdown
        all_doctypes = (
            set(self._requested_counts.keys()) |
            set(self._record_names.keys()) |
            set(self._failed_records.keys()) |
            set(self._skipped_records.keys())
        )

        for doctype in all_doctypes:
            stats.by_doctype[doctype] = {
                "requested": self._requested_counts.get(doctype, 0),
                "created": len(self._record_names.get(doctype, [])),
                "failed": len(self._failed_records.get(doctype, [])),
                "skipped": self._skipped_records.get(doctype, 0),
            }

        # Method breakdown
        stats.by_method = dict(self._method_counts)

        # Backfill stats
        stats.backfills_pending = len([e for e in self._pending_backfills if not e.resolved])
        stats.backfills_completed = len([e for e in self._pending_backfills if e.resolved])

        return stats

    def get_all_record_names(self) -> Dict[str, List[str]]:
        """
        Get all record names organized by DocType.

        Useful for cleanup/rollback operations.

        Returns:
            Dictionary mapping DocType -> list of document names
        """
        return {
            doctype: names.copy()
            for doctype, names in self._record_names.items()
        }

    def get_failed_records(self, doctype: Optional[str] = None) -> Dict[str, List[Dict[str, Any]]]:
        """
        Get failed record information.

        Args:
            doctype: Optional DocType to filter by

        Returns:
            Dictionary mapping DocType -> list of failure info
        """
        if doctype:
            return {doctype: self._failed_records.get(doctype, [])}
        return dict(self._failed_records)

    def clear_doctype(self, doctype: str) -> int:
        """
        Clear all cached records for a DocType.

        Args:
            doctype: The DocType to clear

        Returns:
            The number of records that were cleared
        """
        count = len(self._record_names.get(doctype, []))

        if doctype in self._records:
            del self._records[doctype]
        if doctype in self._record_names:
            del self._record_names[doctype]
        if doctype in self._failed_records:
            del self._failed_records[doctype]
        if doctype in self._skipped_records:
            del self._skipped_records[doctype]
        if doctype in self._requested_counts:
            del self._requested_counts[doctype]

        # Clear backfills for this doctype
        self._pending_backfills = [
            e for e in self._pending_backfills
            if e.doctype != doctype
        ]

        return count

    def clear_all(self) -> int:
        """
        Clear all cached records.

        Returns:
            The total number of records that were cleared
        """
        total = sum(len(names) for names in self._record_names.values())

        self._records.clear()
        self._record_names.clear()
        self._pending_backfills.clear()
        self._failed_records.clear()
        self._skipped_records.clear()
        self._requested_counts.clear()
        self._method_counts.clear()

        # Reset random state if seeded
        if self._seed is not None:
            self._random = random.Random(self._seed)

        return total

    def merge(self, other: "RecordCache") -> None:
        """
        Merge another RecordCache into this one.

        Useful when combining results from parallel generation.

        Args:
            other: Another RecordCache to merge in
        """
        # Merge records
        for doctype, entries in other._records.items():
            for name, entry in entries.items():
                if name not in self._records[doctype]:
                    self._records[doctype][name] = entry
                    self._record_names[doctype].append(name)

        # Merge backfills
        self._pending_backfills.extend(other._pending_backfills)

        # Merge failures
        for doctype, failures in other._failed_records.items():
            self._failed_records[doctype].extend(failures)

        # Merge skipped counts
        for doctype, count in other._skipped_records.items():
            self._skipped_records[doctype] += count

        # Merge requested counts (take max)
        for doctype, count in other._requested_counts.items():
            self._requested_counts[doctype] = max(
                self._requested_counts.get(doctype, 0),
                count
            )

        # Merge method counts
        for method, count in other._method_counts.items():
            self._method_counts[method] += count

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert the entire cache to a dictionary.

        Useful for serialization/debugging.

        Returns:
            Dictionary representation of the cache
        """
        return {
            "seed": self._seed,
            "records": {
                doctype: {name: entry.to_dict() for name, entry in entries.items()}
                for doctype, entries in self._records.items()
            },
            "pending_backfills": [e.to_dict() for e in self._pending_backfills],
            "failed_records": dict(self._failed_records),
            "skipped_records": dict(self._skipped_records),
            "requested_counts": dict(self._requested_counts),
            "method_counts": dict(self._method_counts),
            "statistics": self.get_statistics().to_dict(),
        }

    def __repr__(self) -> str:
        """String representation of RecordCache."""
        total_records = sum(len(names) for names in self._record_names.values())
        doctype_count = len(self._records)
        pending_backfills = len([e for e in self._pending_backfills if not e.resolved])

        return (
            f"RecordCache("
            f"records={total_records}, "
            f"doctypes={doctype_count}, "
            f"pending_backfills={pending_backfills}, "
            f"seed={self._seed}"
            f")"
        )

    def __len__(self) -> int:
        """Return the total number of cached records."""
        return sum(len(names) for names in self._record_names.values())

    def __contains__(self, item: Tuple[str, str]) -> bool:
        """
        Check if a record exists in the cache.

        Args:
            item: Tuple of (doctype, name)

        Returns:
            True if the record exists

        Example:
            >>> cache = RecordCache()
            >>> cache.add_record("Customer", "CUST-001")
            >>> ("Customer", "CUST-001") in cache
            True
        """
        doctype, name = item
        return name in self._records.get(doctype, {})


def create_record_cache(seed: Optional[int] = None) -> RecordCache:
    """
    Factory function to create a RecordCache.

    Args:
        seed: Optional random seed for reproducibility

    Returns:
        A new RecordCache instance

    Example:
        >>> cache = create_record_cache(seed=42)
        >>> cache.seed
        42
    """
    return RecordCache(seed=seed)

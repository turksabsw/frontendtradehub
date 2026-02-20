# Copyright (c) 2024, Mock Data Engine and contributors
# For license information, please see license.txt

"""
Mock Data Generator Module.

This module provides the MockDataGenerator class, the main execution engine
for mock data generation in the Frappe framework. It orchestrates the entire
generation process including:

1. Configuration resolution (Request > Profile > Settings)
2. Dependency analysis and ordering (topological sort)
3. Phased generation (independent, dependent, circular)
4. Field value generation using handlers
5. Progress tracking and reporting
6. Error handling and recovery

The generator follows a three-phase approach:
- Phase 1: Independent DocTypes (no dependencies in the set)
- Phase 2: Dependent DocTypes (dependencies already generated)
- Phase 3: Circular DocTypes (two-pass approach with backfill)

Usage:
    from mock_data_engine.mock_data_engine.core.generator import MockDataGenerator

    # Create generator with configuration
    generator = MockDataGenerator(
        request_name="MGR-2024-00001",
        locale="tr_TR",
        seed=42
    )

    # Execute generation
    result = generator.execute()

    # Check results
    print(f"Created: {result.total_created}")
    print(f"Failed: {result.total_failed}")
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, TYPE_CHECKING

if TYPE_CHECKING:
    from mock_data_engine.mock_data_engine.core.meta_reader import DocTypeMeta, FieldInfo
    from mock_data_engine.mock_data_engine.core.config_resolver import ResolvedConfig
    from mock_data_engine.mock_data_engine.core.record_cache import RecordCache
    from mock_data_engine.mock_data_engine.core.dependency_resolver import (
        DependencyResolver,
        GenerationPlan,
    )
    from mock_data_engine.mock_data_engine.handlers.factory import FieldHandlerFactory
    from mock_data_engine.mock_data_engine.utils.progress import ProgressTracker


@dataclass
class BatchResult:
    """
    Result of a single batch generation operation.

    Attributes:
        batch_id: Unique identifier for this batch (typically sequential)
        batch_number: The batch number (1-indexed)
        success: Whether the batch completed successfully
        records_created: Number of records successfully created in this batch
        records_failed: Number of records that failed in this batch
        created_names: List of document names created
        errors: List of error messages for failed records
        duration_seconds: Time taken to process this batch
        rolled_back: Whether this batch was rolled back
        savepoint_name: Name of the savepoint used for this batch
    """
    batch_id: str = ""
    batch_number: int = 0
    success: bool = True
    records_created: int = 0
    records_failed: int = 0
    created_names: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    duration_seconds: float = 0.0
    rolled_back: bool = False
    savepoint_name: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "batch_id": self.batch_id,
            "batch_number": self.batch_number,
            "success": self.success,
            "records_created": self.records_created,
            "records_failed": self.records_failed,
            "created_names": self.created_names,
            "errors": self.errors,
            "duration_seconds": round(self.duration_seconds, 4),
            "rolled_back": self.rolled_back,
            "savepoint_name": self.savepoint_name,
        }


@dataclass
class GenerationResult:
    """
    Result of a mock data generation operation.

    Attributes:
        success: Whether generation completed successfully
        total_requested: Total records requested
        total_created: Total records successfully created
        total_failed: Total records that failed to create
        total_skipped: Total records skipped (e.g., excluded DocTypes)
        doctypes_processed: List of DocTypes that were processed
        created_records: Dict mapping DocType -> list of created document names
        failed_records: Dict mapping DocType -> list of error info
        duration_seconds: Total execution time in seconds
        errors: List of error messages encountered
        backfills_completed: Number of circular dependency backfills completed
    """
    success: bool = True
    total_requested: int = 0
    total_created: int = 0
    total_failed: int = 0
    total_skipped: int = 0
    doctypes_processed: List[str] = field(default_factory=list)
    created_records: Dict[str, List[str]] = field(default_factory=dict)
    failed_records: Dict[str, List[Dict[str, Any]]] = field(default_factory=dict)
    duration_seconds: float = 0.0
    errors: List[str] = field(default_factory=list)
    backfills_completed: int = 0

    @property
    def success_rate(self) -> float:
        """Calculate success rate as percentage."""
        if self.total_requested == 0:
            return 100.0
        return (self.total_created / self.total_requested) * 100

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "success": self.success,
            "total_requested": self.total_requested,
            "total_created": self.total_created,
            "total_failed": self.total_failed,
            "total_skipped": self.total_skipped,
            "success_rate": round(self.success_rate, 2),
            "doctypes_processed": self.doctypes_processed,
            "created_records": self.created_records,
            "failed_records": self.failed_records,
            "duration_seconds": round(self.duration_seconds, 2),
            "errors": self.errors,
            "backfills_completed": self.backfills_completed,
        }


@dataclass
class DocTypeGenerationConfig:
    """
    Configuration for generating records of a specific DocType.

    Attributes:
        doctype: The DocType name
        count: Number of records to generate
        field_overrides: Field-specific override configurations
        skip_fields: Fields to skip during generation
        use_ai: Whether to use AI generation for this DocType
    """
    doctype: str
    count: int = 10
    field_overrides: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    skip_fields: Set[str] = field(default_factory=set)
    use_ai: bool = False


class MockDataGeneratorError(Exception):
    """Base exception for MockDataGenerator errors."""
    pass


class GenerationAbortedError(MockDataGeneratorError):
    """Raised when generation is aborted due to critical error."""
    pass


class ProductionEnvironmentError(MockDataGeneratorError):
    """Raised when attempting to generate data in production environment."""
    pass


class MockDataGenerator:
    """
    Main execution engine for mock data generation.

    This class orchestrates the entire mock data generation process,
    coordinating between configuration resolution, dependency analysis,
    field handlers, and database operations.

    The generator follows a three-phase approach:
    - Phase 1: Generate independent DocTypes (no dependencies)
    - Phase 2: Generate dependent DocTypes (dependencies satisfied)
    - Phase 3: Handle circular dependencies (two-pass with backfill)

    Attributes:
        request_name: Optional Mock Generation Request document name
        locale: Locale for data generation (e.g., 'tr_TR')
        seed: Random seed for reproducibility
        fail_on_error: Whether to abort on first error

    Example:
        >>> generator = MockDataGenerator(
        ...     request_name="MGR-001",
        ...     locale="tr_TR",
        ...     seed=42
        ... )
        >>> result = generator.execute()
        >>> print(f"Created {result.total_created} records")
    """

    def __init__(
        self,
        request_name: Optional[str] = None,
        profile_name: Optional[str] = None,
        locale: str = "en_US",
        seed: Optional[int] = None,
        fail_on_error: bool = False,
        batch_size: int = 100,
        auto_resolve_dependencies: bool = True,
        log_generation_details: bool = True,
        enable_ai_generation: bool = False,
        publish_progress: bool = True,
    ):
        """
        Initialize the MockDataGenerator.

        Args:
            request_name: Optional Mock Generation Request document name.
                         If provided, configuration is loaded from the request.
            profile_name: Optional Mock Generation Profile name.
                         Used if request doesn't specify a profile.
            locale: Locale for data generation (e.g., 'tr_TR', 'en_US').
            seed: Random seed for reproducibility.
            fail_on_error: Whether to abort immediately on first error.
            batch_size: Number of records per batch for bulk operations.
            auto_resolve_dependencies: Whether to auto-create linked documents.
            log_generation_details: Whether to log detailed generation info.
            enable_ai_generation: Whether to enable AI-powered generation.
            publish_progress: Whether to publish progress via Frappe realtime.
        """
        self._request_name = request_name
        self._profile_name = profile_name
        self._locale = locale
        self._seed = seed
        self._fail_on_error = fail_on_error
        self._batch_size = batch_size
        self._auto_resolve_dependencies = auto_resolve_dependencies
        self._log_generation_details = log_generation_details
        self._enable_ai_generation = enable_ai_generation
        self._publish_progress = publish_progress

        # Lazy-loaded components
        self._config: Optional["ResolvedConfig"] = None
        self._record_cache: Optional["RecordCache"] = None
        self._dependency_resolver: Optional["DependencyResolver"] = None
        self._handler_factory: Optional["FieldHandlerFactory"] = None
        self._progress_tracker: Optional["ProgressTracker"] = None

        # Generation plan
        self._generation_plan: Optional["GenerationPlan"] = None

        # DocType configurations
        self._doctype_configs: Dict[str, DocTypeGenerationConfig] = {}

        # Execution state
        self._started_at: Optional[float] = None
        self._completed_at: Optional[float] = None
        self._aborted: bool = False
        self._abort_reason: Optional[str] = None

    # =========================================================================
    # Properties
    # =========================================================================

    @property
    def request_name(self) -> Optional[str]:
        """Get the request name."""
        return self._request_name

    @property
    def locale(self) -> str:
        """Get the locale for generation."""
        return self._locale

    @property
    def seed(self) -> Optional[int]:
        """Get the random seed."""
        return self._seed

    @property
    def config(self) -> "ResolvedConfig":
        """
        Get the resolved configuration (lazy loaded).

        Returns:
            ResolvedConfig with all resolved values.
        """
        if self._config is None:
            self._config = self._resolve_configuration()
        return self._config

    @property
    def record_cache(self) -> "RecordCache":
        """
        Get the record cache (lazy loaded).

        Returns:
            RecordCache for tracking created records.
        """
        if self._record_cache is None:
            from mock_data_engine.mock_data_engine.core.record_cache import RecordCache
            self._record_cache = RecordCache(seed=self._seed)
        return self._record_cache

    @property
    def dependency_resolver(self) -> "DependencyResolver":
        """
        Get the dependency resolver (lazy loaded).

        Returns:
            DependencyResolver for analyzing dependencies.
        """
        if self._dependency_resolver is None:
            from mock_data_engine.mock_data_engine.core.dependency_resolver import (
                DependencyResolver,
            )
            excluded = self.config.excluded_doctypes
            self._dependency_resolver = DependencyResolver(
                excluded_doctypes=excluded
            )
        return self._dependency_resolver

    @property
    def handler_factory(self) -> "FieldHandlerFactory":
        """
        Get the field handler factory (lazy loaded).

        Returns:
            FieldHandlerFactory for creating field handlers.
        """
        if self._handler_factory is None:
            from mock_data_engine.mock_data_engine.handlers.factory import (
                FieldHandlerFactory,
            )
            self._handler_factory = FieldHandlerFactory(
                locale=self._locale,
                seed=self._seed,
                config=self.config,
            )
        return self._handler_factory

    @property
    def progress_tracker(self) -> "ProgressTracker":
        """
        Get the progress tracker (lazy loaded).

        Returns:
            ProgressTracker for tracking generation progress.
        """
        if self._progress_tracker is None:
            from mock_data_engine.mock_data_engine.utils.progress import ProgressTracker
            self._progress_tracker = ProgressTracker(
                request_name=self._request_name,
                publish_realtime=self._publish_progress,
            )
        return self._progress_tracker

    @property
    def is_aborted(self) -> bool:
        """Check if generation was aborted."""
        return self._aborted

    @property
    def abort_reason(self) -> Optional[str]:
        """Get the abort reason if generation was aborted."""
        return self._abort_reason

    # =========================================================================
    # Configuration Methods
    # =========================================================================

    def _resolve_configuration(self) -> "ResolvedConfig":
        """
        Resolve configuration from request, profile, and settings.

        Returns:
            ResolvedConfig with all resolved values.
        """
        from mock_data_engine.mock_data_engine.core.config_resolver import (
            ConfigResolver,
            ResolvedConfig,
        )

        request = None
        profile = None

        # Load request if name provided
        if self._request_name:
            try:
                import frappe
                request = frappe.get_doc("Mock Generation Request", self._request_name)
            except Exception:
                pass

        # Load profile if name provided
        if self._profile_name:
            try:
                import frappe
                profile = frappe.get_doc("Mock Generation Profile", self._profile_name)
            except Exception:
                pass

        # If no frappe or documents, use default config
        if request is None and profile is None:
            return ResolvedConfig(
                locale=self._locale,
                seed_value=self._seed,
                batch_size=self._batch_size,
                auto_resolve_dependencies=self._auto_resolve_dependencies,
                fail_on_error=self._fail_on_error,
                log_generation_details=self._log_generation_details,
                enable_ai_generation=self._enable_ai_generation,
            )

        resolver = ConfigResolver(request=request, profile=profile)
        return resolver.resolve_all()

    def add_doctype(
        self,
        doctype: str,
        count: int = 10,
        field_overrides: Optional[Dict[str, Dict[str, Any]]] = None,
        skip_fields: Optional[Set[str]] = None,
        use_ai: bool = False,
    ) -> "MockDataGenerator":
        """
        Add a DocType to generate with specified configuration.

        Args:
            doctype: The DocType name to generate.
            count: Number of records to generate.
            field_overrides: Field-specific override configurations.
            skip_fields: Fields to skip during generation.
            use_ai: Whether to use AI generation for this DocType.

        Returns:
            Self for method chaining.

        Example:
            >>> generator.add_doctype("Customer", count=100)
            >>> generator.add_doctype("Item", count=50, use_ai=True)
        """
        self._doctype_configs[doctype] = DocTypeGenerationConfig(
            doctype=doctype,
            count=count,
            field_overrides=field_overrides or {},
            skip_fields=skip_fields or set(),
            use_ai=use_ai,
        )
        return self

    def add_doctypes(
        self,
        doctypes: Dict[str, int],
    ) -> "MockDataGenerator":
        """
        Add multiple DocTypes with their counts.

        Args:
            doctypes: Dict mapping DocType name to count.

        Returns:
            Self for method chaining.

        Example:
            >>> generator.add_doctypes({
            ...     "Customer": 100,
            ...     "Item": 50,
            ...     "Supplier": 25
            ... })
        """
        for doctype, count in doctypes.items():
            self.add_doctype(doctype, count=count)
        return self

    def clear_doctypes(self) -> "MockDataGenerator":
        """
        Clear all configured DocTypes.

        Returns:
            Self for method chaining.
        """
        self._doctype_configs.clear()
        return self

    def get_doctype_config(self, doctype: str) -> Optional[DocTypeGenerationConfig]:
        """
        Get configuration for a specific DocType.

        Args:
            doctype: The DocType name.

        Returns:
            DocTypeGenerationConfig or None if not configured.
        """
        return self._doctype_configs.get(doctype)

    # =========================================================================
    # Validation Methods
    # =========================================================================

    def _validate_environment(self) -> None:
        """
        Validate the execution environment.

        Raises:
            ProductionEnvironmentError: If running in production with protection enabled.
        """
        if not self.config.production_protection:
            return

        try:
            from mock_data_engine.mock_data_engine.utils.environment import (
                validate_environment,
            )
            validate_environment()
        except ImportError:
            # Environment module not available, skip validation
            pass

    def _validate_doctypes(self) -> List[str]:
        """
        Validate that configured DocTypes exist and are accessible.

        Returns:
            List of valid DocType names.

        Raises:
            MockDataGeneratorError: If no valid DocTypes are configured.
        """
        valid_doctypes = []

        for doctype in self._doctype_configs:
            # Check if DocType is excluded
            if self.config.is_excluded_doctype(doctype):
                continue

            # Try to get DocType meta to validate it exists
            try:
                from mock_data_engine.mock_data_engine.core.meta_reader import DocTypeMeta
                meta = DocTypeMeta(doctype)
                # Basic validation - check if we can get fields
                if meta.get_data_fields():
                    valid_doctypes.append(doctype)
            except Exception:
                # DocType doesn't exist or can't be accessed
                pass

        if not valid_doctypes:
            raise MockDataGeneratorError(
                "No valid DocTypes configured for generation. "
                "Check that DocTypes exist and are not excluded."
            )

        return valid_doctypes

    # =========================================================================
    # Main Execution Flow
    # =========================================================================

    def execute(self) -> GenerationResult:
        """
        Execute the mock data generation process.

        This is the main entry point for generation. It:
        1. Validates the environment and configuration
        2. Analyzes dependencies and creates generation plan
        3. Generates records in three phases (independent, dependent, circular)
        4. Performs backfill for circular dependencies
        5. Returns the generation result

        Returns:
            GenerationResult with all generation statistics.

        Raises:
            ProductionEnvironmentError: If running in production.
            MockDataGeneratorError: If configuration is invalid.
            GenerationAbortedError: If generation was aborted due to error.

        Example:
            >>> generator = MockDataGenerator(locale="tr_TR")
            >>> generator.add_doctypes({"Customer": 100, "Item": 50})
            >>> result = generator.execute()
            >>> print(f"Success rate: {result.success_rate}%")
        """
        self._started_at = time.time()
        result = GenerationResult()

        try:
            # Step 1: Validate environment
            self._validate_environment()

            # Step 2: Validate DocTypes and get valid list
            valid_doctypes = self._validate_doctypes()

            # Step 3: Build dependency graph and get generation plan
            self._generation_plan = self._build_generation_plan(valid_doctypes)

            # Step 4: Calculate total records and set up progress tracking
            total_records = self._calculate_total_records()
            result.total_requested = total_records
            self.progress_tracker.total_records = total_records
            self.progress_tracker.start()

            # Step 5: Execute phased generation
            # Phase 1: Independent DocTypes
            self._generate_phase_1(result)

            # Phase 2: Dependent DocTypes
            self._generate_phase_2(result)

            # Phase 3: Circular DocTypes (two-pass)
            self._generate_phase_3(result)

            # Step 6: Perform backfill for circular dependencies
            self._perform_backfill(result)

            # Step 7: Finalize
            result.success = not self._aborted
            result.doctypes_processed = list(self._generation_plan.generation_order)

        except ProductionEnvironmentError as e:
            result.success = False
            result.errors.append(f"Production environment detected: {str(e)}")
            raise

        except MockDataGeneratorError as e:
            result.success = False
            result.errors.append(str(e))

        except Exception as e:
            result.success = False
            result.errors.append(f"Unexpected error: {str(e)}")
            if self._fail_on_error:
                raise GenerationAbortedError(str(e)) from e

        finally:
            self._completed_at = time.time()
            result.duration_seconds = self._completed_at - self._started_at

            # Finalize progress tracking
            self.progress_tracker.complete()

            # Populate result from cache
            self._populate_result_from_cache(result)

        return result

    def _build_generation_plan(self, doctypes: List[str]) -> "GenerationPlan":
        """
        Build the generation plan from dependency analysis.

        Args:
            doctypes: List of DocTypes to analyze.

        Returns:
            GenerationPlan with ordered phases.
        """
        # Add DocTypes to resolver
        self.dependency_resolver.add_doctypes(doctypes)

        # Build dependency graph
        self.dependency_resolver.build_dependency_graph()

        # Get generation plan
        return self.dependency_resolver.get_generation_plan()

    def _calculate_total_records(self) -> int:
        """
        Calculate total number of records to generate.

        Returns:
            Total record count across all DocTypes.
        """
        total = 0
        for doctype in self._generation_plan.generation_order:
            config = self._doctype_configs.get(doctype)
            if config:
                total += config.count
                # Set up record cache tracking
                self.record_cache.set_requested_count(doctype, config.count)
        return total

    # =========================================================================
    # Phased Generation Methods
    # =========================================================================

    def generate_phase_1(
        self,
        result: Optional[GenerationResult] = None,
    ) -> GenerationResult:
        """
        Generate Phase 1: Independent DocTypes.

        Independent DocTypes have no dependencies within the generation set
        and can be generated first without any Link field resolution.

        This is the first phase of the three-phase generation approach:
        - Phase 1: Independent DocTypes (no dependencies)
        - Phase 2: Dependent DocTypes (dependencies satisfied)
        - Phase 3: Circular DocTypes (two-pass with backfill)

        Args:
            result: Optional GenerationResult to update. If None, creates new one.

        Returns:
            GenerationResult with Phase 1 generation statistics.

        Example:
            >>> generator = MockDataGenerator(locale="tr_TR")
            >>> generator.add_doctypes({"Customer": 10, "Item": 5})
            >>> # Build plan first
            >>> generator._generation_plan = generator._build_generation_plan(
            ...     list(generator._doctype_configs.keys())
            ... )
            >>> result = generator.generate_phase_1()
            >>> print(f"Phase 1 created: {result.total_created}")
        """
        if result is None:
            result = GenerationResult()

        if not self._generation_plan:
            return result

        # Update progress tracker for phase 1
        self.progress_tracker.set_phase(1, "Independent DocTypes")

        independent_doctypes = self._generation_plan.independent
        total_phase_1 = len(independent_doctypes)

        for idx, doctype in enumerate(independent_doctypes):
            if self._aborted:
                break

            # Update phase progress
            self.progress_tracker.set_phase_progress(
                current=idx + 1,
                total=total_phase_1,
                doctype=doctype,
            )

            self._generate_doctype_records(doctype, result)

        return result

    def generate_phase_2(
        self,
        result: Optional[GenerationResult] = None,
    ) -> GenerationResult:
        """
        Generate Phase 2: Dependent DocTypes.

        Dependent DocTypes have dependencies that were satisfied in Phase 1.
        Link fields can be resolved using the record cache populated during
        Phase 1 generation.

        This is the second phase of the three-phase generation approach:
        - Phase 1: Independent DocTypes (no dependencies)
        - Phase 2: Dependent DocTypes (dependencies satisfied)
        - Phase 3: Circular DocTypes (two-pass with backfill)

        Args:
            result: Optional GenerationResult to update. If None, creates new one.

        Returns:
            GenerationResult with Phase 2 generation statistics.

        Example:
            >>> generator = MockDataGenerator(locale="tr_TR")
            >>> generator.add_doctypes({"Customer": 10, "Sales Invoice": 5})
            >>> # After Phase 1 completes...
            >>> result = generator.generate_phase_2()
            >>> print(f"Phase 2 created: {result.total_created}")
        """
        if result is None:
            result = GenerationResult()

        if not self._generation_plan:
            return result

        # Update progress tracker for phase 2
        self.progress_tracker.set_phase(2, "Dependent DocTypes")

        dependent_doctypes = self._generation_plan.dependent
        total_phase_2 = len(dependent_doctypes)

        for idx, doctype in enumerate(dependent_doctypes):
            if self._aborted:
                break

            # Update phase progress
            self.progress_tracker.set_phase_progress(
                current=idx + 1,
                total=total_phase_2,
                doctype=doctype,
            )

            self._generate_doctype_records(doctype, result)

        return result

    def generate_phase_3(
        self,
        result: Optional[GenerationResult] = None,
    ) -> GenerationResult:
        """
        Generate Phase 3: Circular DocTypes (First Pass).

        Circular DocTypes are part of dependency cycles. They are created
        with NULL Link fields initially during this phase. The actual
        link values will be backfilled in a second pass after all records
        in the cycle have been created.

        This is the third phase of the three-phase generation approach:
        - Phase 1: Independent DocTypes (no dependencies)
        - Phase 2: Dependent DocTypes (dependencies satisfied)
        - Phase 3: Circular DocTypes (two-pass with backfill)

        Args:
            result: Optional GenerationResult to update. If None, creates new one.

        Returns:
            GenerationResult with Phase 3 generation statistics.

        Example:
            >>> generator = MockDataGenerator(locale="tr_TR")
            >>> # For DocTypes with circular dependencies
            >>> result = generator.generate_phase_3()
            >>> # Then call perform_backfill() to resolve circular links
        """
        if result is None:
            result = GenerationResult()

        if not self._generation_plan:
            return result

        # Update progress tracker for phase 3
        self.progress_tracker.set_phase(3, "Circular DocTypes (First Pass)")

        circular_doctypes = self._generation_plan.circular
        total_phase_3 = len(circular_doctypes)

        for idx, doctype in enumerate(circular_doctypes):
            if self._aborted:
                break

            # Update phase progress
            self.progress_tracker.set_phase_progress(
                current=idx + 1,
                total=total_phase_3,
                doctype=doctype,
            )

            # Generate with is_circular=True to skip circular link fields
            self._generate_doctype_records(doctype, result, is_circular=True)

        return result

    def _generate_phase_1(self, result: GenerationResult) -> None:
        """
        Internal method to generate Phase 1: Independent DocTypes.

        This method is called by execute() and delegates to generate_phase_1().

        Args:
            result: GenerationResult to update with progress.
        """
        self.generate_phase_1(result)

    def _generate_phase_2(self, result: GenerationResult) -> None:
        """
        Internal method to generate Phase 2: Dependent DocTypes.

        This method is called by execute() and delegates to generate_phase_2().

        Args:
            result: GenerationResult to update with progress.
        """
        self.generate_phase_2(result)

    def _generate_phase_3(self, result: GenerationResult) -> None:
        """
        Internal method to generate Phase 3: Circular DocTypes.

        This method is called by execute() and delegates to generate_phase_3().

        Args:
            result: GenerationResult to update with progress.
        """
        self.generate_phase_3(result)

    def perform_backfill(
        self,
        result: Optional[GenerationResult] = None,
    ) -> GenerationResult:
        """
        Perform backfill for circular dependencies (Second Pass).

        Updates NULL Link fields with actual references now that all
        records in the circular dependency have been created.

        This is called after Phase 3 to resolve circular Link fields:
        - Phase 3 creates records with NULL circular Link fields
        - Backfill updates those fields with valid references

        Args:
            result: Optional GenerationResult to update. If None, creates new one.

        Returns:
            GenerationResult with backfill statistics.

        Example:
            >>> generator = MockDataGenerator(locale="tr_TR")
            >>> # After Phase 3 creates records with circular dependencies
            >>> result = generator.perform_backfill()
            >>> print(f"Backfills completed: {result.backfills_completed}")
        """
        if result is None:
            result = GenerationResult()

        # Update progress tracker for backfill phase
        self.progress_tracker.set_phase(4, "Backfill (Second Pass)")

        backfills = self.record_cache.get_pending_backfills()
        total_backfills = len(backfills)

        for idx, backfill in enumerate(backfills):
            if self._aborted:
                break

            # Update progress
            self.progress_tracker.set_phase_progress(
                current=idx + 1,
                total=total_backfills,
                doctype=backfill.doctype,
            )

            try:
                # Get a random record from the target DocType
                target_name = self.record_cache.get_random_record(
                    backfill.target_doctype
                )

                if target_name:
                    # Update the record with the resolved link
                    self._update_record_field(
                        backfill.doctype,
                        backfill.name,
                        backfill.fieldname,
                        target_name,
                    )

                    # Mark backfill as resolved
                    self.record_cache.mark_backfill_resolved(
                        backfill.doctype,
                        backfill.name,
                        backfill.fieldname,
                        target_name,
                    )
                    result.backfills_completed += 1

            except Exception as e:
                if self._fail_on_error:
                    self._aborted = True
                    self._abort_reason = f"Backfill failed: {str(e)}"
                    break

        return result

    def _perform_backfill(self, result: GenerationResult) -> None:
        """
        Internal method to perform backfill for circular dependencies.

        This method is called by execute() and delegates to perform_backfill().

        Args:
            result: GenerationResult to update with backfill count.
        """
        self.perform_backfill(result)

    def _update_record_field(
        self,
        doctype: str,
        name: str,
        fieldname: str,
        value: Any,
    ) -> None:
        """
        Update a single field on an existing record.

        Args:
            doctype: The DocType of the record.
            name: The document name.
            fieldname: The field to update.
            value: The new field value.
        """
        try:
            import frappe
            frappe.db.set_value(doctype, name, fieldname, value, update_modified=False)
        except ImportError:
            # Frappe not available, skip
            pass

    # =========================================================================
    # Record Generation Methods
    # =========================================================================

    def _generate_doctype_records(
        self,
        doctype: str,
        result: GenerationResult,
        is_circular: bool = False,
    ) -> None:
        """
        Generate records for a single DocType.

        Args:
            doctype: The DocType to generate records for.
            result: GenerationResult to update with progress.
            is_circular: Whether this DocType is in a circular dependency.
        """
        config = self._doctype_configs.get(doctype)
        if not config:
            return

        # Update progress tracker
        self.progress_tracker.set_doctype(doctype, config.count)
        self.progress_tracker.start_doctype(doctype)

        # Generate records in batches
        batch_count = (config.count + self._batch_size - 1) // self._batch_size

        for batch_num in range(batch_count):
            if self._aborted:
                break

            # Calculate batch size for this iteration
            start_idx = batch_num * self._batch_size
            end_idx = min(start_idx + self._batch_size, config.count)
            current_batch_size = end_idx - start_idx

            # Update batch info
            self.progress_tracker.set_batch_info(
                current_batch=batch_num + 1,
                total_batches=batch_count,
                batch_size=current_batch_size,
            )

            # Generate batch
            self._generate_batch(
                doctype=doctype,
                count=current_batch_size,
                start_idx=start_idx,
                result=result,
                is_circular=is_circular,
            )

        # Mark DocType as complete
        self.progress_tracker.complete_doctype(doctype)

    def _generate_batch(
        self,
        doctype: str,
        count: int,
        start_idx: int,
        result: GenerationResult,
        is_circular: bool = False,
    ) -> None:
        """
        Generate a batch of records for a DocType.

        Args:
            doctype: The DocType to generate records for.
            count: Number of records in this batch.
            start_idx: Starting index for this batch.
            result: GenerationResult to update with progress.
            is_circular: Whether this DocType is in a circular dependency.
        """
        config = self._doctype_configs.get(doctype)
        if not config:
            return

        for i in range(count):
            if self._aborted:
                break

            record_idx = start_idx + i

            try:
                # Generate record data
                record_data = self._generate_record_data(
                    doctype=doctype,
                    config=config,
                    record_idx=record_idx,
                    is_circular=is_circular,
                )

                # Insert record
                doc_name = self._insert_record(doctype, record_data)

                if doc_name:
                    # Track in cache
                    needs_backfill = is_circular and self._generation_plan.has_cycles
                    backfill_fields = []

                    if is_circular:
                        # Get circular edges for this DocType
                        for edge in self._generation_plan.circular_edges:
                            if edge.source == doctype:
                                backfill_fields.append(edge.fieldname)

                    self.record_cache.add_record(
                        doctype=doctype,
                        name=doc_name,
                        data=record_data,
                        needs_backfill=needs_backfill,
                        backfill_fields=backfill_fields,
                    )

                    # Register pending backfills
                    for fieldname in backfill_fields:
                        # Find target DocType from edges
                        for edge in self._generation_plan.circular_edges:
                            if edge.source == doctype and edge.fieldname == fieldname:
                                self.record_cache.add_pending_backfill(
                                    doctype=doctype,
                                    name=doc_name,
                                    fieldname=fieldname,
                                    target_doctype=edge.target,
                                )
                                break

                    # Update progress
                    self.progress_tracker.increment_doctype(doctype, created=1)

                    # Track in result
                    if doctype not in result.created_records:
                        result.created_records[doctype] = []
                    result.created_records[doctype].append(doc_name)
                    result.total_created += 1

            except Exception as e:
                # Record failure
                error_msg = str(e)
                self.record_cache.add_failed_record(doctype, error_msg)
                self.progress_tracker.increment_doctype(doctype, failed=1)
                self.progress_tracker.add_error(error_msg, doctype)

                if doctype not in result.failed_records:
                    result.failed_records[doctype] = []
                result.failed_records[doctype].append({
                    "error": error_msg,
                    "index": record_idx,
                })
                result.total_failed += 1

                if self._fail_on_error:
                    self._aborted = True
                    self._abort_reason = f"Failed to create {doctype}: {error_msg}"
                    break

    # =========================================================================
    # Batch Generation with Transaction Management
    # =========================================================================

    def batch_generate(
        self,
        doctype: str,
        count: int,
        *,
        use_transactions: bool = True,
        rollback_on_failure: bool = True,
        commit_per_batch: bool = True,
        batch_size: Optional[int] = None,
        is_circular: bool = False,
    ) -> List[BatchResult]:
        """
        Generate records for a DocType with transaction management and savepoints.

        This method provides fine-grained control over batch processing with
        database transactions and savepoints. It allows:
        - Per-batch savepoints for partial rollback on failure
        - Configurable commit behavior
        - Detailed batch-level result tracking

        Args:
            doctype: The DocType to generate records for.
            count: Total number of records to generate.
            use_transactions: Whether to use database transactions.
            rollback_on_failure: Whether to rollback batch on failure.
            commit_per_batch: Whether to commit after each successful batch.
            batch_size: Override the default batch size.
            is_circular: Whether this DocType is in a circular dependency.

        Returns:
            List of BatchResult objects, one per batch processed.

        Raises:
            GenerationAbortedError: If fail_on_error is True and a batch fails.

        Example:
            >>> generator = MockDataGenerator(locale="tr_TR")
            >>> generator.add_doctype("Customer", count=1000)
            >>> batch_results = generator.batch_generate(
            ...     doctype="Customer",
            ...     count=1000,
            ...     use_transactions=True,
            ...     commit_per_batch=True,
            ...     batch_size=100
            ... )
            >>> for batch in batch_results:
            ...     print(f"Batch {batch.batch_number}: {batch.records_created} created")
        """
        batch_results: List[BatchResult] = []
        effective_batch_size = batch_size or self._batch_size

        # Get or create config for this DocType
        config = self._doctype_configs.get(doctype)
        if not config:
            config = DocTypeGenerationConfig(doctype=doctype, count=count)
            self._doctype_configs[doctype] = config

        # Calculate batch count
        batch_count = (count + effective_batch_size - 1) // effective_batch_size

        # Start overall transaction if enabled
        if use_transactions:
            self._begin_transaction()

        try:
            for batch_num in range(batch_count):
                if self._aborted:
                    break

                # Calculate batch boundaries
                start_idx = batch_num * effective_batch_size
                end_idx = min(start_idx + effective_batch_size, count)
                current_batch_size = end_idx - start_idx

                # Generate unique batch ID and savepoint name
                batch_id = f"{doctype}_{batch_num + 1}_{int(time.time() * 1000)}"
                savepoint_name = f"sp_batch_{doctype}_{batch_num + 1}"

                # Create savepoint for this batch
                if use_transactions:
                    self._create_savepoint(savepoint_name)

                batch_start_time = time.time()
                batch_result = BatchResult(
                    batch_id=batch_id,
                    batch_number=batch_num + 1,
                    savepoint_name=savepoint_name,
                )

                try:
                    # Generate records for this batch
                    for i in range(current_batch_size):
                        record_idx = start_idx + i

                        try:
                            # Generate record data
                            record_data = self._generate_record_data(
                                doctype=doctype,
                                config=config,
                                record_idx=record_idx,
                                is_circular=is_circular,
                            )

                            # Insert record
                            doc_name = self._insert_record(doctype, record_data)

                            if doc_name:
                                batch_result.created_names.append(doc_name)
                                batch_result.records_created += 1

                                # Track in cache if available
                                self.record_cache.add_record(
                                    doctype=doctype,
                                    name=doc_name,
                                    data=record_data,
                                    needs_backfill=is_circular,
                                )
                            else:
                                batch_result.records_failed += 1
                                batch_result.errors.append(
                                    f"Record {record_idx}: Insert returned None"
                                )

                        except Exception as e:
                            batch_result.records_failed += 1
                            batch_result.errors.append(
                                f"Record {record_idx}: {str(e)}"
                            )

                            if self._fail_on_error:
                                raise

                    # Batch completed successfully
                    batch_result.success = batch_result.records_failed == 0

                    # Release savepoint and optionally commit
                    if use_transactions:
                        self._release_savepoint(savepoint_name)
                        if commit_per_batch and batch_result.success:
                            self._commit_transaction()
                            # Start new transaction for next batch
                            if batch_num < batch_count - 1:
                                self._begin_transaction()

                except Exception as e:
                    # Batch failed
                    batch_result.success = False

                    if use_transactions and rollback_on_failure:
                        # Rollback to savepoint
                        self._rollback_to_savepoint(savepoint_name)
                        batch_result.rolled_back = True
                        # Clear names since they were rolled back
                        batch_result.created_names = []
                        batch_result.records_created = 0

                    if self._fail_on_error:
                        self._aborted = True
                        self._abort_reason = f"Batch {batch_num + 1} failed: {str(e)}"
                        raise GenerationAbortedError(
                            f"Batch generation aborted: {str(e)}"
                        ) from e

                finally:
                    batch_result.duration_seconds = time.time() - batch_start_time
                    batch_results.append(batch_result)

            # Final commit if using transactions and not committing per batch
            if use_transactions and not commit_per_batch:
                self._commit_transaction()

        except GenerationAbortedError:
            # Re-raise abort errors
            if use_transactions:
                self._rollback_transaction()
            raise

        except Exception as e:
            # Rollback entire transaction on unexpected error
            if use_transactions:
                self._rollback_transaction()
            raise MockDataGeneratorError(
                f"Batch generation failed: {str(e)}"
            ) from e

        return batch_results

    def _begin_transaction(self) -> None:
        """
        Begin a database transaction.

        This is a no-op if Frappe is not available or if autocommit is disabled.
        """
        try:
            import frappe
            # Frappe manages transactions automatically, but we can ensure
            # we're in a transaction context
            if hasattr(frappe.db, 'begin'):
                frappe.db.begin()
        except ImportError:
            pass
        except Exception:
            # Silently ignore transaction errors in non-Frappe environments
            pass

    def _commit_transaction(self) -> None:
        """
        Commit the current database transaction.

        This commits all changes made since the last begin or commit.
        """
        try:
            import frappe
            frappe.db.commit()
        except ImportError:
            pass
        except Exception:
            # Silently ignore commit errors in non-Frappe environments
            pass

    def _rollback_transaction(self) -> None:
        """
        Rollback the current database transaction.

        This reverts all changes made since the last begin or commit.
        """
        try:
            import frappe
            frappe.db.rollback()
        except ImportError:
            pass
        except Exception:
            # Silently ignore rollback errors in non-Frappe environments
            pass

    def _create_savepoint(self, name: str) -> None:
        """
        Create a database savepoint.

        Savepoints allow partial rollbacks within a transaction.
        If the savepoint fails, it continues silently.

        Args:
            name: Unique name for the savepoint.
        """
        try:
            import frappe
            if hasattr(frappe.db, 'savepoint'):
                frappe.db.savepoint(name)
            else:
                # Fallback: execute raw SQL
                frappe.db.sql(f"SAVEPOINT {name}")
        except ImportError:
            pass
        except Exception:
            # Silently ignore savepoint errors
            pass

    def _release_savepoint(self, name: str) -> None:
        """
        Release a database savepoint.

        This releases the savepoint after successful operations.
        The savepoint can no longer be rolled back to after release.

        Args:
            name: Name of the savepoint to release.
        """
        try:
            import frappe
            if hasattr(frappe.db, 'release_savepoint'):
                frappe.db.release_savepoint(name)
            else:
                # Fallback: execute raw SQL
                frappe.db.sql(f"RELEASE SAVEPOINT {name}")
        except ImportError:
            pass
        except Exception:
            # Silently ignore release errors
            pass

    def _rollback_to_savepoint(self, name: str) -> None:
        """
        Rollback to a database savepoint.

        This reverts all changes made since the savepoint was created.
        The savepoint remains valid and can be rolled back to again.

        Args:
            name: Name of the savepoint to rollback to.
        """
        try:
            import frappe
            if hasattr(frappe.db, 'rollback_to_savepoint'):
                frappe.db.rollback_to_savepoint(name)
            else:
                # Fallback: execute raw SQL
                frappe.db.sql(f"ROLLBACK TO SAVEPOINT {name}")
        except ImportError:
            pass
        except Exception:
            # Silently ignore rollback errors
            pass

    def _generate_record_data(
        self,
        doctype: str,
        config: DocTypeGenerationConfig,
        record_idx: int,
        is_circular: bool = False,
    ) -> Dict[str, Any]:
        """
        Generate field values for a single record.

        Args:
            doctype: The DocType to generate data for.
            config: The generation configuration for this DocType.
            record_idx: Index of this record in the batch.
            is_circular: Whether this DocType is in a circular dependency.

        Returns:
            Dictionary of field names to generated values.
        """
        from mock_data_engine.mock_data_engine.core.meta_reader import DocTypeMeta

        meta = DocTypeMeta(doctype)
        record_data: Dict[str, Any] = {}

        # Get data fields (exclude layout fields)
        fields = meta.get_data_fields()

        for field_info in fields:
            fieldname = field_info.fieldname

            # Skip configured skip fields
            if fieldname in config.skip_fields:
                continue

            # Skip name field (handled by naming)
            if fieldname == "name":
                continue

            # For circular dependencies, skip circular Link fields (will be backfilled)
            if is_circular and self._is_circular_link_field(doctype, fieldname):
                record_data[fieldname] = None
                continue

            try:
                # Get field override if any
                override = config.field_overrides.get(fieldname)
                if not override:
                    override = self.config.get_field_override(doctype, fieldname)

                # Create generation context
                context = self.handler_factory.create_context(
                    field_info=field_info,
                    doctype=doctype,
                    record_data=record_data,
                    record_cache=self.record_cache,
                    batch_index=record_idx,
                    total_count=config.count,
                    field_override=override,
                )

                # Get handler and generate value
                handler = self.handler_factory.get_handler(field_info, override)
                value = handler.generate(context)

                if value is not None:
                    record_data[fieldname] = value

            except Exception:
                # On field generation error, use None or skip
                pass

        return record_data

    def _is_circular_link_field(self, doctype: str, fieldname: str) -> bool:
        """
        Check if a field is a circular Link field that needs backfill.

        Args:
            doctype: The DocType name.
            fieldname: The field name.

        Returns:
            True if the field is a circular Link field.
        """
        if not self._generation_plan:
            return False

        for edge in self._generation_plan.circular_edges:
            if edge.source == doctype and edge.fieldname == fieldname:
                return True

        return False

    def _insert_record(
        self,
        doctype: str,
        data: Dict[str, Any],
    ) -> Optional[str]:
        """
        Insert a record into the database.

        Args:
            doctype: The DocType to insert.
            data: The field values.

        Returns:
            The document name if successful, None otherwise.
        """
        try:
            import frappe

            # Create document
            doc = frappe.new_doc(doctype)
            doc.update(data)

            # Use ignore flags for bulk insertion
            doc.flags.ignore_validate = True
            doc.flags.ignore_permissions = True
            doc.flags.ignore_mandatory = True

            # Insert
            doc.insert()

            return doc.name

        except ImportError:
            # Frappe not available
            return None

    # =========================================================================
    # Result Population
    # =========================================================================

    def _populate_result_from_cache(self, result: GenerationResult) -> None:
        """
        Populate the result with data from the record cache.

        Args:
            result: GenerationResult to populate.
        """
        stats = self.record_cache.get_statistics()

        # Update totals from cache
        result.total_created = stats.total_created
        result.total_failed = stats.total_failed
        result.total_skipped = stats.total_skipped

        # Get all created record names
        result.created_records = self.record_cache.get_all_record_names()

        # Get failed record info
        result.failed_records = self.record_cache.get_failed_records()

    # =========================================================================
    # Abort Methods
    # =========================================================================

    def abort(self, reason: str = "User requested abort") -> None:
        """
        Abort the current generation.

        Args:
            reason: Reason for aborting.
        """
        self._aborted = True
        self._abort_reason = reason

    def reset(self) -> None:
        """Reset the generator state for a new execution."""
        self._aborted = False
        self._abort_reason = None
        self._started_at = None
        self._completed_at = None
        self._generation_plan = None

        # Reset lazy-loaded components
        if self._record_cache:
            self._record_cache.clear_all()
        if self._dependency_resolver:
            self._dependency_resolver.clear()
        if self._progress_tracker:
            self._progress_tracker = None

    # =========================================================================
    # String Representation
    # =========================================================================

    def __repr__(self) -> str:
        """String representation of MockDataGenerator."""
        doctype_count = len(self._doctype_configs)
        total_records = sum(c.count for c in self._doctype_configs.values())

        return (
            f"MockDataGenerator("
            f"request='{self._request_name}', "
            f"locale='{self._locale}', "
            f"seed={self._seed}, "
            f"doctypes={doctype_count}, "
            f"records={total_records}"
            f")"
        )


# =========================================================================
# Factory Functions
# =========================================================================


def create_mock_generator(
    request_name: Optional[str] = None,
    locale: str = "en_US",
    seed: Optional[int] = None,
    **kwargs
) -> MockDataGenerator:
    """
    Factory function to create a MockDataGenerator.

    Args:
        request_name: Optional Mock Generation Request document name.
        locale: Locale for data generation.
        seed: Random seed for reproducibility.
        **kwargs: Additional arguments passed to MockDataGenerator.

    Returns:
        A new MockDataGenerator instance.

    Example:
        >>> generator = create_mock_generator(locale="tr_TR", seed=42)
        >>> generator.add_doctype("Customer", count=100)
        >>> result = generator.execute()
    """
    return MockDataGenerator(
        request_name=request_name,
        locale=locale,
        seed=seed,
        **kwargs
    )


def execute_generation(
    doctypes: Dict[str, int],
    locale: str = "en_US",
    seed: Optional[int] = None,
    **kwargs
) -> GenerationResult:
    """
    Convenience function to execute mock data generation.

    This is a simple entry point for generating mock data without
    manually creating and configuring a generator.

    Args:
        doctypes: Dict mapping DocType name to record count.
        locale: Locale for data generation.
        seed: Random seed for reproducibility.
        **kwargs: Additional arguments passed to MockDataGenerator.

    Returns:
        GenerationResult with all statistics.

    Example:
        >>> result = execute_generation(
        ...     {"Customer": 100, "Item": 50},
        ...     locale="tr_TR",
        ...     seed=42
        ... )
        >>> print(f"Created: {result.total_created}")
    """
    generator = MockDataGenerator(locale=locale, seed=seed, **kwargs)
    generator.add_doctypes(doctypes)
    return generator.execute()

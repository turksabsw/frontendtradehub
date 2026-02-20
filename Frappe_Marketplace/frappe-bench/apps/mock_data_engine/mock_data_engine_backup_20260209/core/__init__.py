# Copyright (c) 2024, Mock Data Engine and contributors
# For license information, please see license.txt

"""
Core module for Mock Data Engine.

This module provides the core infrastructure for mock data generation:
- DocTypeMeta: Schema introspection for DocTypes
- ConfigResolver: 3-tier configuration resolution (Request > Profile > Settings)
- RecordCache: Tracking created records during generation
- DependencyResolver: Dependency graph building and topological sort
- MockDataGenerator: Main execution engine
"""

from mock_data_engine.mock_data_engine.core.meta_reader import DocTypeMeta
from mock_data_engine.mock_data_engine.core.config_resolver import (
    ConfigResolver,
    ResolvedConfig,
    create_resolver_for_request,
    create_resolver_for_profile,
)
from mock_data_engine.mock_data_engine.core.record_cache import (
    RecordCache,
    RecordEntry,
    BackfillEntry,
    GenerationStatistics,
    create_record_cache,
)
from mock_data_engine.mock_data_engine.core.dependency_resolver import (
    DependencyResolver,
    DependencyNode,
    DependencyEdge,
    GenerationPlan,
    build_dependency_graph,
    get_generation_order,
    create_dependency_resolver,
)
from mock_data_engine.mock_data_engine.core.generator import (
    MockDataGenerator,
    GenerationResult,
    DocTypeGenerationConfig,
    MockDataGeneratorError,
    GenerationAbortedError,
    ProductionEnvironmentError,
    create_mock_generator,
    execute_generation,
)

__all__ = [
    # Meta reader
    "DocTypeMeta",
    # Config resolver
    "ConfigResolver",
    "ResolvedConfig",
    "create_resolver_for_request",
    "create_resolver_for_profile",
    # Record cache
    "RecordCache",
    "RecordEntry",
    "BackfillEntry",
    "GenerationStatistics",
    "create_record_cache",
    # Dependency resolver
    "DependencyResolver",
    "DependencyNode",
    "DependencyEdge",
    "GenerationPlan",
    "build_dependency_graph",
    "get_generation_order",
    "create_dependency_resolver",
    # Generator
    "MockDataGenerator",
    "GenerationResult",
    "DocTypeGenerationConfig",
    "MockDataGeneratorError",
    "GenerationAbortedError",
    "ProductionEnvironmentError",
    "create_mock_generator",
    "execute_generation",
]

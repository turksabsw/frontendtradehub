# Copyright (c) 2024, Mock Data Engine and contributors
# For license information, please see license.txt

"""
Utility modules for Mock Data Engine.

This module provides utility functions for:
- Environment validation and production protection
- Progress tracking for generation operations
- Naming conventions and patterns
"""

from mock_data_engine.utils.environment import (
    validate_environment,
    is_production_environment,
    ProductionEnvironmentError,
    get_environment_info,
)
from mock_data_engine.utils.progress import (
    ProgressTracker,
    create_progress_tracker,
)
from mock_data_engine.utils.naming_handler import (
    NamingHandler,
    NamingContext,
    NamingError,
    generate_document_name,
)

__all__ = [
    # Environment utilities
    "validate_environment",
    "is_production_environment",
    "ProductionEnvironmentError",
    "get_environment_info",
    # Progress tracking
    "ProgressTracker",
    "create_progress_tracker",
    # Naming utilities
    "NamingHandler",
    "NamingContext",
    "NamingError",
    "generate_document_name",
]

# Note: doc_events module is accessed directly via hooks.py path resolution
# and does not need to be exported here

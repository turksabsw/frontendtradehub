# Copyright (c) 2024, Mock Data Engine and contributors
# For license information, please see license.txt

"""
API Module for Mock Data Engine.

This module provides the public API endpoints for mock data generation,
progress tracking, and LLM provider testing.

Key Endpoints:
- generate(): Generate mock data for specified DocTypes
- get_progress(): Get generation progress for a request
- test_llm_connection(): Test connection to an LLM provider

All endpoints are whitelisted for use via Frappe's API system.

Usage:
    # Via Frappe API
    frappe.call('mock_data_engine.api.generation.generate',
                doctype='Customer', count=100)

    # Via REST API
    POST /api/method/mock_data_engine.mock_data_engine.api.generation.generate
    {"doctype": "Customer", "count": 100}
"""

from mock_data_engine.api.generation import (
    generate,
    generate_async,
    get_progress,
    test_llm_connection,
    get_supported_doctypes,
    get_excluded_doctypes,
)

__all__ = [
    # Generation endpoints
    "generate",
    "generate_async",
    "get_progress",
    # LLM endpoints
    "test_llm_connection",
    # Utility endpoints
    "get_supported_doctypes",
    "get_excluded_doctypes",
]

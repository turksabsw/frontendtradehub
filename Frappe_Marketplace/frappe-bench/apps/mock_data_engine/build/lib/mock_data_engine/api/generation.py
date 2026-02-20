# Copyright (c) 2024, Mock Data Engine and contributors
# For license information, please see license.txt

"""
Generation API Module for Mock Data Engine.

This module provides the public API endpoints for mock data generation,
including synchronous generation, async generation with background jobs,
progress tracking, and LLM provider testing.

API Endpoints:
    - generate(): Synchronous mock data generation
    - generate_async(): Asynchronous generation via background job
    - get_progress(): Get generation progress for a request
    - test_llm_connection(): Test connection to an LLM provider
    - get_supported_doctypes(): Get list of DocTypes available for generation
    - get_excluded_doctypes(): Get list of excluded DocTypes

All endpoints are decorated with @frappe.whitelist() for API access.

Usage:
    # Synchronous generation (small batches)
    result = frappe.call(
        'mock_data_engine.mock_data_engine.api.generation.generate',
        doctype='Customer',
        count=10,
        locale='tr_TR'
    )

    # Asynchronous generation (large batches)
    result = frappe.call(
        'mock_data_engine.mock_data_engine.api.generation.generate_async',
        doctype='Customer',
        count=1000,
        locale='tr_TR'
    )

    # Check progress
    progress = frappe.call(
        'mock_data_engine.mock_data_engine.api.generation.get_progress',
        request_name='MGR-2024-00001'
    )

    # Test LLM connection
    result = frappe.call(
        'mock_data_engine.mock_data_engine.api.generation.test_llm_connection',
        provider='gemini'
    )
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Union

# Import frappe at module level for type hints
# Actual import happens at runtime in functions
try:
    import frappe
    from frappe import _
except ImportError:
    # Allow import for testing without frappe
    frappe = None
    _ = lambda x: x


# ============================================================================
# Main Generation Endpoints
# ============================================================================


def generate(
    doctype: str,
    count: int = 10,
    locale: Optional[str] = None,
    seed: Optional[int] = None,
    field_overrides: Optional[Union[str, Dict[str, Dict[str, Any]]]] = None,
    auto_resolve_dependencies: bool = True,
    fail_on_error: bool = False,
    use_ai: bool = False,
) -> Dict[str, Any]:
    """
    Generate mock data for a specified DocType.

    This is the main API endpoint for synchronous mock data generation.
    For large batches (>100 records), consider using generate_async() instead.

    Args:
        doctype: The DocType to generate records for (e.g., 'Customer', 'Item').
        count: Number of records to generate (default: 10).
        locale: Locale for data generation (e.g., 'tr_TR', 'en_US').
                Falls back to Mock Engine Settings default if not specified.
        seed: Random seed for reproducible generation.
        field_overrides: Field-specific override configurations.
                        Can be a dict or JSON string.
        auto_resolve_dependencies: Whether to auto-create linked documents.
        fail_on_error: Whether to abort on first error.
        use_ai: Whether to enable AI-powered generation.

    Returns:
        dict: Result containing:
            - success (bool): Whether generation completed successfully
            - message (str): Status message
            - total_created (int): Number of records created
            - total_failed (int): Number of records that failed
            - created_names (list): List of created document names
            - errors (list): List of error messages if any

    Raises:
        frappe.ValidationError: If DocType is invalid or excluded.
        frappe.PermissionError: If user lacks permission.

    Example:
        >>> result = generate(doctype='Customer', count=5, locale='tr_TR')
        >>> print(f"Created: {result['total_created']} records")

    API Usage:
        POST /api/method/mock_data_engine.mock_data_engine.api.generation.generate
        {
            "doctype": "Customer",
            "count": 10,
            "locale": "tr_TR"
        }
    """
    import frappe
    from frappe import _

    # Validate DocType
    if not doctype:
        frappe.throw(_("DocType is required"), frappe.ValidationError)

    if not frappe.db.exists("DocType", doctype):
        frappe.throw(
            _("DocType '{0}' does not exist").format(doctype),
            frappe.ValidationError
        )

    # Check if DocType is excluded
    settings = frappe.get_single("Mock Engine Settings")
    excluded_doctypes = [row.doctype for row in (settings.excluded_doctypes or [])]

    if doctype in excluded_doctypes:
        frappe.throw(
            _("DocType '{0}' is excluded from generation").format(doctype),
            frappe.ValidationError
        )

    # Validate count
    if count < 1:
        frappe.throw(_("Count must be at least 1"), frappe.ValidationError)

    if count > 10000:
        frappe.throw(
            _("For more than 10,000 records, please use generate_async()"),
            frappe.ValidationError
        )

    # Parse field_overrides if JSON string
    if isinstance(field_overrides, str):
        try:
            field_overrides = json.loads(field_overrides)
        except json.JSONDecodeError:
            frappe.throw(
                _("Invalid JSON in field_overrides"),
                frappe.ValidationError
            )

    # Get effective locale
    effective_locale = locale or settings.default_locale or "en_US"

    # Get effective seed
    effective_seed = seed if seed is not None else settings.seed_value

    try:
        # Import and create generator
        from mock_data_engine.mock_data_engine.core.generator import MockDataGenerator

        generator = MockDataGenerator(
            locale=effective_locale,
            seed=effective_seed,
            fail_on_error=fail_on_error,
            auto_resolve_dependencies=auto_resolve_dependencies,
            enable_ai_generation=use_ai,
            publish_progress=False,  # No realtime for sync generation
        )

        # Add DocType configuration
        generator.add_doctype(
            doctype=doctype,
            count=count,
            field_overrides=field_overrides or {},
            use_ai=use_ai,
        )

        # Execute generation
        result = generator.execute()

        # Format response
        created_names = result.created_records.get(doctype, [])

        return {
            "success": result.success,
            "message": _("Successfully generated {0} records").format(result.total_created),
            "total_requested": result.total_requested,
            "total_created": result.total_created,
            "total_failed": result.total_failed,
            "total_skipped": result.total_skipped,
            "created_names": created_names,
            "duration_seconds": round(result.duration_seconds, 2),
            "errors": result.errors[:10],  # Limit errors returned
        }

    except Exception as e:
        frappe.log_error(
            message=frappe.get_traceback(),
            title=f"Mock Data Generation Failed: {doctype}"
        )
        return {
            "success": False,
            "message": str(e),
            "total_requested": count,
            "total_created": 0,
            "total_failed": count,
            "total_skipped": 0,
            "created_names": [],
            "duration_seconds": 0,
            "errors": [str(e)],
        }


# Add whitelist decorator
if frappe:
    generate = frappe.whitelist()(generate)


def generate_async(
    doctype: Optional[str] = None,
    count: int = 100,
    doctypes: Optional[Union[str, Dict[str, int]]] = None,
    locale: Optional[str] = None,
    seed: Optional[int] = None,
    auto_resolve_dependencies: bool = True,
    fail_on_error: bool = False,
    use_ai: bool = False,
    profile_name: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Generate mock data asynchronously via background job.

    This endpoint creates a Mock Generation Request and queues it for
    background processing. Use get_progress() to track the status.

    Args:
        doctype: Single DocType to generate records for.
        count: Number of records for single DocType mode (default: 100).
        doctypes: Dict mapping DocType names to counts for multi-DocType mode.
                 Can be a dict or JSON string.
        locale: Locale for data generation (e.g., 'tr_TR', 'en_US').
        seed: Random seed for reproducible generation.
        auto_resolve_dependencies: Whether to auto-create linked documents.
        fail_on_error: Whether to abort on first error.
        use_ai: Whether to enable AI-powered generation.
        profile_name: Name of a Mock Generation Profile to use.

    Returns:
        dict: Result containing:
            - success (bool): Whether request was created successfully
            - message (str): Status message
            - request_name (str): The Mock Generation Request document name

    Example:
        >>> result = generate_async(doctype='Customer', count=1000)
        >>> request_name = result['request_name']
        >>> # Later, check progress
        >>> progress = get_progress(request_name)

    API Usage:
        POST /api/method/mock_data_engine.mock_data_engine.api.generation.generate_async
        {
            "doctype": "Customer",
            "count": 1000,
            "locale": "tr_TR"
        }
    """
    import frappe
    from frappe import _

    # Parse doctypes if JSON string
    if isinstance(doctypes, str):
        try:
            doctypes = json.loads(doctypes)
        except json.JSONDecodeError:
            frappe.throw(
                _("Invalid JSON in doctypes parameter"),
                frappe.ValidationError
            )

    # Determine generation mode
    if profile_name:
        generation_mode = "From Profile"
    elif doctypes:
        generation_mode = "Multiple DocTypes"
    elif doctype:
        generation_mode = "Single DocType"
    else:
        frappe.throw(
            _("Either doctype, doctypes, or profile_name is required"),
            frappe.ValidationError
        )

    # Validate single DocType
    if generation_mode == "Single DocType":
        if not frappe.db.exists("DocType", doctype):
            frappe.throw(
                _("DocType '{0}' does not exist").format(doctype),
                frappe.ValidationError
            )

    # Get settings for defaults
    settings = frappe.get_single("Mock Engine Settings")
    effective_locale = locale or settings.default_locale or "en_US"
    effective_seed = seed if seed is not None else settings.seed_value

    try:
        # Create Mock Generation Request
        request = frappe.new_doc("Mock Generation Request")
        request.generation_mode = generation_mode

        if generation_mode == "Single DocType":
            request.target_doctype = doctype
            request.record_count = count

        elif generation_mode == "Multiple DocTypes":
            for dt_name, dt_count in (doctypes or {}).items():
                request.append("selected_doctypes", {
                    "doctype": dt_name,
                    "record_count": dt_count
                })

        elif generation_mode == "From Profile":
            request.profile = profile_name

        # Set options
        request.locale = effective_locale
        request.seed_value = effective_seed
        request.auto_resolve_dependencies = auto_resolve_dependencies
        request.fail_on_error = fail_on_error
        request.log_generation_details = True

        request.insert()

        # Queue the generation
        request.queue_generation()

        return {
            "success": True,
            "message": _("Generation request created and queued"),
            "request_name": request.name
        }

    except Exception as e:
        frappe.log_error(
            message=frappe.get_traceback(),
            title="Failed to create generation request"
        )
        return {
            "success": False,
            "message": str(e),
            "request_name": None
        }


# Add whitelist decorator
if frappe:
    generate_async = frappe.whitelist()(generate_async)


# ============================================================================
# Progress Tracking Endpoint
# ============================================================================


def get_progress(request_name: str) -> Dict[str, Any]:
    """
    Get the current progress of a generation request.

    This endpoint returns detailed progress information for a
    Mock Generation Request, including status, counts, and timing.

    Args:
        request_name: The name of the Mock Generation Request document.

    Returns:
        dict: Progress information including:
            - status (str): Current status (Draft, Queued, Processing, etc.)
            - progress_percent (float): Completion percentage (0-100)
            - records_created (int): Number of records created so far
            - records_failed (int): Number of records that failed
            - current_batch (int): Current batch number
            - total_batches (int): Total number of batches
            - started_at (str): When processing started
            - completed_at (str): When processing completed (if done)
            - duration_seconds (float): Duration in seconds
            - error_message (str): Error message if failed

    Raises:
        frappe.DoesNotExistError: If request_name doesn't exist.

    Example:
        >>> progress = get_progress('MGR-2024-00001')
        >>> print(f"Progress: {progress['progress_percent']}%")

    API Usage:
        GET /api/method/mock_data_engine.mock_data_engine.api.generation.get_progress
        ?request_name=MGR-2024-00001
    """
    import frappe
    from frappe import _

    if not request_name:
        frappe.throw(_("request_name is required"), frappe.ValidationError)

    if not frappe.db.exists("Mock Generation Request", request_name):
        frappe.throw(
            _("Mock Generation Request '{0}' not found").format(request_name),
            frappe.DoesNotExistError
        )

    request = frappe.get_doc("Mock Generation Request", request_name)

    return {
        "request_name": request.name,
        "status": request.status,
        "progress_percent": request.progress_percent or 0,
        "records_created": request.records_created or 0,
        "records_failed": request.records_failed or 0,
        "current_batch": request.current_batch or 0,
        "total_batches": request.total_batches or 0,
        "started_at": str(request.started_at) if request.started_at else None,
        "completed_at": str(request.completed_at) if request.completed_at else None,
        "duration_seconds": request.duration_seconds,
        "error_message": request.error_message,
        "generation_mode": request.generation_mode,
        "target_doctype": request.target_doctype,
    }


# Add whitelist decorator
if frappe:
    get_progress = frappe.whitelist()(get_progress)


# ============================================================================
# LLM Connection Testing Endpoint
# ============================================================================


def test_llm_connection(
    provider: str,
    api_key: Optional[str] = None,
    model: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Test connection to an LLM provider.

    This endpoint validates the API key and connection to a specified
    LLM provider by sending a simple test request.

    Args:
        provider: The provider to test ('gemini', 'openai', 'anthropic', 'ollama').
        api_key: Optional API key to test. If not provided, uses the key
                from Mock Engine Settings.
        model: Optional model to use for testing.

    Returns:
        dict: Result containing:
            - success (bool): Whether connection was successful
            - message (str): Status message
            - provider (str): The tested provider name
            - model (str): The model used for testing
            - response_time_ms (float): Response time in milliseconds

    Raises:
        frappe.ValidationError: If provider is invalid.

    Example:
        >>> result = test_llm_connection(provider='gemini')
        >>> if result['success']:
        ...     print("Connection successful!")

    API Usage:
        POST /api/method/mock_data_engine.mock_data_engine.api.generation.test_llm_connection
        {"provider": "gemini"}
    """
    import frappe
    from frappe import _
    import time

    # Validate provider
    valid_providers = ["gemini", "openai", "anthropic", "ollama"]
    provider_lower = provider.lower().strip()

    if provider_lower not in valid_providers:
        frappe.throw(
            _("Invalid provider '{0}'. Valid providers: {1}").format(
                provider, ", ".join(valid_providers)
            ),
            frappe.ValidationError
        )

    # Get API key from settings if not provided
    effective_api_key = api_key
    settings = frappe.get_single("Mock Engine Settings")

    if not effective_api_key:
        if provider_lower == "gemini":
            effective_api_key = settings.get_password("gemini_api_key")
        elif provider_lower == "openai":
            effective_api_key = settings.get_password("openai_api_key")
        elif provider_lower == "anthropic":
            effective_api_key = settings.get_password("anthropic_api_key")
        elif provider_lower == "ollama":
            # Ollama doesn't require API key
            effective_api_key = None

    # Check if API key is available (except for Ollama)
    if provider_lower != "ollama" and not effective_api_key:
        return {
            "success": False,
            "message": _("No API key configured for {0}").format(provider),
            "provider": provider_lower,
            "model": None,
            "response_time_ms": 0,
        }

    try:
        start_time = time.time()

        # Import and create provider
        if provider_lower == "gemini":
            from mock_data_engine.mock_data_engine.providers.gemini_provider import (
                create_gemini_provider,
                DEFAULT_GEMINI_MODEL,
            )
            test_model = model or DEFAULT_GEMINI_MODEL
            llm_provider = create_gemini_provider(
                api_key=effective_api_key,
                model=test_model,
            )

        elif provider_lower == "openai":
            from mock_data_engine.mock_data_engine.providers.openai_provider import (
                create_openai_provider,
                DEFAULT_OPENAI_MODEL,
            )
            test_model = model or DEFAULT_OPENAI_MODEL
            llm_provider = create_openai_provider(
                api_key=effective_api_key,
                model=test_model,
            )

        elif provider_lower == "anthropic":
            from mock_data_engine.mock_data_engine.providers.anthropic_provider import (
                create_anthropic_provider,
                DEFAULT_ANTHROPIC_MODEL,
            )
            test_model = model or DEFAULT_ANTHROPIC_MODEL
            llm_provider = create_anthropic_provider(
                api_key=effective_api_key,
                model=test_model,
            )

        elif provider_lower == "ollama":
            from mock_data_engine.mock_data_engine.providers.ollama_provider import (
                create_ollama_provider,
                DEFAULT_OLLAMA_MODEL,
            )
            test_model = model or settings.ollama_model or DEFAULT_OLLAMA_MODEL
            base_url = settings.ollama_base_url or "http://localhost:11434"
            llm_provider = create_ollama_provider(
                model=test_model,
                base_url=base_url,
            )

        # Test connection
        connection_result = llm_provider.test_connection()
        end_time = time.time()
        response_time_ms = (end_time - start_time) * 1000

        if connection_result:
            return {
                "success": True,
                "message": _("Connection successful"),
                "provider": provider_lower,
                "model": test_model,
                "response_time_ms": round(response_time_ms, 2),
            }
        else:
            return {
                "success": False,
                "message": _("Connection test failed"),
                "provider": provider_lower,
                "model": test_model,
                "response_time_ms": round(response_time_ms, 2),
            }

    except Exception as e:
        frappe.log_error(
            message=frappe.get_traceback(),
            title=f"LLM Connection Test Failed: {provider}"
        )
        return {
            "success": False,
            "message": str(e),
            "provider": provider_lower,
            "model": model,
            "response_time_ms": 0,
        }


# Add whitelist decorator
if frappe:
    test_llm_connection = frappe.whitelist()(test_llm_connection)


# ============================================================================
# Utility Endpoints
# ============================================================================


def get_supported_doctypes(
    app: Optional[str] = None,
    search: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Get list of DocTypes available for generation.

    This endpoint returns DocTypes that can be used for mock data
    generation, optionally filtered by app or search term.

    Args:
        app: Optional app name to filter by (e.g., 'erpnext').
        search: Optional search term to filter DocType names.

    Returns:
        dict: Result containing:
            - success (bool): Whether query was successful
            - doctypes (list): List of DocType info dicts with name and module

    Example:
        >>> result = get_supported_doctypes(app='erpnext')
        >>> for dt in result['doctypes']:
        ...     print(dt['name'])

    API Usage:
        GET /api/method/mock_data_engine.mock_data_engine.api.generation.get_supported_doctypes
        ?app=erpnext&search=customer
    """
    import frappe
    from frappe import _

    # Get settings for exclusions
    settings = frappe.get_single("Mock Engine Settings")
    excluded_apps = [row.app for row in (settings.excluded_apps or [])]
    excluded_doctypes = [row.doctype for row in (settings.excluded_doctypes or [])]

    # Build filters
    filters = {
        "istable": 0,
        "issingle": 0,
        "is_virtual": 0,
        "custom": 0,
    }

    if app:
        # Get the module for the app
        filters["module"] = ["like", f"%{app}%"]

    # Get DocTypes
    doctypes = frappe.get_all(
        "DocType",
        filters=filters,
        fields=["name", "module"],
        order_by="name",
    )

    # Filter out excluded
    result = []
    for dt in doctypes:
        # Skip excluded doctypes
        if dt["name"] in excluded_doctypes:
            continue

        # Skip if app is in excluded apps
        # (app name is derived from module in Frappe)
        module_parts = dt["module"].split(".")
        dt_app = module_parts[0] if module_parts else ""
        if dt_app in excluded_apps:
            continue

        # Apply search filter
        if search and search.lower() not in dt["name"].lower():
            continue

        result.append({
            "name": dt["name"],
            "module": dt["module"],
        })

    return {
        "success": True,
        "count": len(result),
        "doctypes": result[:100],  # Limit to 100
    }


# Add whitelist decorator
if frappe:
    get_supported_doctypes = frappe.whitelist()(get_supported_doctypes)


def get_excluded_doctypes() -> Dict[str, Any]:
    """
    Get list of DocTypes excluded from generation.

    This endpoint returns the list of DocTypes that have been
    excluded from mock data generation in Mock Engine Settings.

    Returns:
        dict: Result containing:
            - success (bool): Whether query was successful
            - excluded_apps (list): List of excluded app names
            - excluded_doctypes (list): List of excluded DocType names

    Example:
        >>> result = get_excluded_doctypes()
        >>> for dt in result['excluded_doctypes']:
        ...     print(f"Excluded: {dt}")

    API Usage:
        GET /api/method/mock_data_engine.mock_data_engine.api.generation.get_excluded_doctypes
    """
    import frappe

    settings = frappe.get_single("Mock Engine Settings")

    excluded_apps = [row.app for row in (settings.excluded_apps or [])]
    excluded_doctypes = [row.doctype for row in (settings.excluded_doctypes or [])]

    return {
        "success": True,
        "excluded_apps": excluded_apps,
        "excluded_doctypes": excluded_doctypes,
    }


# Add whitelist decorator
if frappe:
    get_excluded_doctypes = frappe.whitelist()(get_excluded_doctypes)

# Copyright (c) 2024, Mock Data Engine and contributors
# For license information, please see license.txt

"""
Jinja2 Prompt Templates for AI-powered Data Generation.

This package contains Jinja2 templates used for generating prompts that are
sent to LLM providers for AI-powered mock data generation.

Templates:
- doctype_prompt.jinja2: Template for generating multiple records for a DocType
- field_content_prompt.jinja2: Template for generating content for specific fields

Usage:
    from jinja2 import Environment, PackageLoader

    env = Environment(
        loader=PackageLoader('mock_data_engine.mock_data_engine', 'templates'),
        autoescape=False,  # Disable escaping for prompts
    )

    template = env.get_template('doctype_prompt.jinja2')
    prompt = template.render(
        doctype="Customer",
        count=10,
        fields=[...],
        locale="tr_TR",
    )
"""

from pathlib import Path
from typing import Any, Dict, List, Optional

# Template directory path
TEMPLATES_DIR = Path(__file__).parent


def get_template_path(template_name: str) -> Path:
    """
    Get the full path to a template file.

    Args:
        template_name: The template filename (e.g., "doctype_prompt.jinja2")

    Returns:
        Path to the template file

    Raises:
        FileNotFoundError: If template does not exist
    """
    template_path = TEMPLATES_DIR / template_name
    if not template_path.exists():
        raise FileNotFoundError(f"Template not found: {template_name}")
    return template_path


def load_template(template_name: str) -> str:
    """
    Load a template file contents.

    Args:
        template_name: The template filename

    Returns:
        Template content as string
    """
    template_path = get_template_path(template_name)
    return template_path.read_text(encoding="utf-8")


def render_doctype_prompt(
    doctype: str,
    count: int,
    fields: List[Dict[str, Any]],
    locale: str = "en_US",
    industry: Optional[str] = None,
    existing_links: Optional[Dict[str, List[str]]] = None,
    constraints: Optional[Dict[str, str]] = None,
    seed: Optional[int] = None,
) -> str:
    """
    Render the doctype generation prompt template.

    This is a convenience function that renders the doctype_prompt.jinja2
    template with the provided parameters.

    Args:
        doctype: The DocType name
        count: Number of records to generate
        fields: List of field definitions (from DocTypeMeta)
        locale: Locale for data generation
        industry: Optional industry context
        existing_links: Pre-resolved link field values
        constraints: Field-specific constraints
        seed: Random seed for reproducibility hint

    Returns:
        Rendered prompt string ready to send to LLM

    Example:
        >>> prompt = render_doctype_prompt(
        ...     doctype="Customer",
        ...     count=10,
        ...     fields=[{"fieldname": "customer_name", "fieldtype": "Data", "reqd": True}],
        ...     locale="tr_TR",
        ...     industry="Retail"
        ... )
    """
    try:
        from jinja2 import Environment, FileSystemLoader
    except ImportError:
        raise ImportError(
            "jinja2 is required for template rendering. "
            "Install with: pip install jinja2"
        )

    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=False,  # No HTML escaping for prompts
        trim_blocks=True,
        lstrip_blocks=True,
    )

    template = env.get_template("doctype_prompt.jinja2")

    return template.render(
        doctype=doctype,
        count=count,
        fields=fields,
        locale=locale,
        industry=industry,
        existing_links=existing_links or {},
        constraints=constraints or {},
        seed=seed,
    )


def render_field_content_prompt(
    doctype: str,
    fieldname: str,
    fieldtype: str,
    label: Optional[str] = None,
    context: Optional[Dict[str, Any]] = None,
    locale: str = "en_US",
    max_length: Optional[int] = None,
) -> str:
    """
    Render the field content generation prompt template.

    This function renders prompts for generating content for a specific field.

    Args:
        doctype: The DocType name
        fieldname: The field name
        fieldtype: The Frappe field type
        label: Human-readable field label
        context: Additional context (record values, industry, etc.)
        locale: Locale for data generation
        max_length: Maximum length constraint

    Returns:
        Rendered prompt string ready to send to LLM
    """
    try:
        from jinja2 import Environment, FileSystemLoader
    except ImportError:
        raise ImportError(
            "jinja2 is required for template rendering. "
            "Install with: pip install jinja2"
        )

    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=False,
        trim_blocks=True,
        lstrip_blocks=True,
    )

    template = env.get_template("field_content_prompt.jinja2")

    return template.render(
        doctype=doctype,
        fieldname=fieldname,
        fieldtype=fieldtype,
        label=label or fieldname,
        context=context or {},
        locale=locale,
        max_length=max_length,
    )


# Template names for reference
DOCTYPE_PROMPT_TEMPLATE = "doctype_prompt.jinja2"
FIELD_CONTENT_PROMPT_TEMPLATE = "field_content_prompt.jinja2"


__all__ = [
    "TEMPLATES_DIR",
    "DOCTYPE_PROMPT_TEMPLATE",
    "FIELD_CONTENT_PROMPT_TEMPLATE",
    "get_template_path",
    "load_template",
    "render_doctype_prompt",
    "render_field_content_prompt",
]

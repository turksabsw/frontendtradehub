# Copyright (c) 2024, Custom and contributors
# For license information, please see license.txt

"""
Mock Engine Settings - Single DocType Controller

This module provides the controller for Mock Engine Settings, a Single DocType
that stores global configuration for the Mock Data Engine including API keys,
generation defaults, and exclusion lists.

API keys are stored using Frappe's Password fieldtype which provides automatic
encryption at rest.
"""

import frappe
from frappe import _
from frappe.model.document import Document


class MockEngineSettings(Document):
    """
    Controller for Mock Engine Settings Single DocType.

    Provides validation for API keys, batch settings, and generation options.
    API keys are automatically encrypted by Frappe's Password fieldtype.
    """

    def validate(self):
        """Validate settings before save."""
        self.validate_ai_configuration()
        self.validate_batch_settings()
        self.validate_ollama_settings()

    def validate_ai_configuration(self):
        """
        Validate that at least one LLM provider is configured when AI generation is enabled.

        Raises:
            frappe.ValidationError: If AI generation is enabled but no provider is configured.
        """
        if not self.enable_ai_generation:
            return

        # Check if at least one provider is configured
        has_provider = any([
            self.gemini_api_key,
            self.openai_api_key,
            self.anthropic_api_key,
            self.ollama_enabled
        ])

        if not has_provider:
            frappe.throw(
                _("Please configure at least one LLM provider (Gemini, OpenAI, Anthropic, or Ollama) "
                  "when AI generation is enabled, or disable AI generation."),
                title=_("Missing LLM Provider")
            )

        # Validate that selected primary provider is configured
        if self.primary_llm_provider:
            self._validate_primary_provider()

    def _validate_primary_provider(self):
        """Validate that the selected primary provider has credentials configured."""
        provider_field_map = {
            "Gemini": "gemini_api_key",
            "OpenAI": "openai_api_key",
            "Anthropic": "anthropic_api_key",
            "Ollama": "ollama_enabled"
        }

        if self.primary_llm_provider in provider_field_map:
            field = provider_field_map[self.primary_llm_provider]
            value = getattr(self, field, None)

            if not value:
                frappe.throw(
                    _("Please configure {0} before selecting it as the primary provider.").format(
                        self.primary_llm_provider
                    ),
                    title=_("Provider Not Configured")
                )

    def validate_batch_settings(self):
        """
        Validate batch size and record count settings.

        Raises:
            frappe.ValidationError: If batch size or record count is invalid.
        """
        if self.default_batch_size and self.default_batch_size < 1:
            frappe.throw(
                _("Default batch size must be at least 1."),
                title=_("Invalid Batch Size")
            )

        if self.default_batch_size and self.default_batch_size > 10000:
            frappe.msgprint(
                _("Large batch sizes (>{0}) may cause memory issues. "
                  "Consider using a smaller batch size.").format(10000),
                indicator="orange",
                alert=True
            )

        if self.default_record_count and self.default_record_count < 1:
            frappe.throw(
                _("Default record count must be at least 1."),
                title=_("Invalid Record Count")
            )

    def validate_ollama_settings(self):
        """
        Validate Ollama configuration when enabled.

        Raises:
            frappe.ValidationError: If Ollama is enabled but host is not configured.
        """
        if self.ollama_enabled:
            if not self.ollama_host:
                self.ollama_host = "http://localhost:11434"

            if not self.ollama_model:
                self.ollama_model = "gemma3"

    @frappe.whitelist()
    def test_gemini_connection(self):
        """
        Test connection to Google Gemini API.

        Returns:
            dict: Result containing success status and message.
        """
        if not self.gemini_api_key:
            return {
                "success": False,
                "message": _("Gemini API key is not configured.")
            }

        try:
            from google import genai

            api_key = self.get_password("gemini_api_key")
            client = genai.Client(api_key=api_key)

            # Simple test call
            response = client.models.generate_content(
                model=self.gemini_model or "gemini-2.0-flash",
                contents="Say 'OK' if you can hear me."
            )

            if response and response.text:
                return {
                    "success": True,
                    "message": _("Gemini connection successful.")
                }
            else:
                return {
                    "success": False,
                    "message": _("Gemini returned an empty response.")
                }

        except ImportError:
            return {
                "success": False,
                "message": _("google-genai package is not installed. "
                           "Run: pip install google-genai")
            }
        except Exception as e:
            return {
                "success": False,
                "message": _("Gemini connection failed: {0}").format(str(e))
            }

    @frappe.whitelist()
    def test_openai_connection(self):
        """
        Test connection to OpenAI API.

        Returns:
            dict: Result containing success status and message.
        """
        if not self.openai_api_key:
            return {
                "success": False,
                "message": _("OpenAI API key is not configured.")
            }

        try:
            from openai import OpenAI

            api_key = self.get_password("openai_api_key")
            client = OpenAI(api_key=api_key)

            response = client.chat.completions.create(
                model=self.openai_model or "gpt-4o-mini",
                messages=[{"role": "user", "content": "Say 'OK' if you can hear me."}],
                max_completion_tokens=10,
                temperature=0
            )

            if response and response.choices:
                return {
                    "success": True,
                    "message": _("OpenAI connection successful.")
                }
            else:
                return {
                    "success": False,
                    "message": _("OpenAI returned an empty response.")
                }

        except ImportError:
            return {
                "success": False,
                "message": _("openai package is not installed. "
                           "Run: pip install openai")
            }
        except Exception as e:
            return {
                "success": False,
                "message": _("OpenAI connection failed: {0}").format(str(e))
            }

    @frappe.whitelist()
    def test_anthropic_connection(self):
        """
        Test connection to Anthropic API.

        Returns:
            dict: Result containing success status and message.
        """
        if not self.anthropic_api_key:
            return {
                "success": False,
                "message": _("Anthropic API key is not configured.")
            }

        try:
            from anthropic import Anthropic

            api_key = self.get_password("anthropic_api_key")
            client = Anthropic(api_key=api_key)

            message = client.messages.create(
                model=self.anthropic_model or "claude-sonnet-4-5",
                max_tokens=10,
                messages=[{"role": "user", "content": "Say 'OK' if you can hear me."}]
            )

            if message and message.content:
                return {
                    "success": True,
                    "message": _("Anthropic connection successful.")
                }
            else:
                return {
                    "success": False,
                    "message": _("Anthropic returned an empty response.")
                }

        except ImportError:
            return {
                "success": False,
                "message": _("anthropic package is not installed. "
                           "Run: pip install anthropic")
            }
        except Exception as e:
            return {
                "success": False,
                "message": _("Anthropic connection failed: {0}").format(str(e))
            }

    @frappe.whitelist()
    def test_ollama_connection(self):
        """
        Test connection to local Ollama server.

        Returns:
            dict: Result containing success status and message.
        """
        if not self.ollama_enabled:
            return {
                "success": False,
                "message": _("Ollama is not enabled.")
            }

        try:
            from ollama import chat

            response = chat(
                model=self.ollama_model or "gemma3",
                messages=[{"role": "user", "content": "Say 'OK' if you can hear me."}]
            )

            if response and response.message and response.message.content:
                return {
                    "success": True,
                    "message": _("Ollama connection successful. Model: {0}").format(
                        self.ollama_model or "gemma3"
                    )
                }
            else:
                return {
                    "success": False,
                    "message": _("Ollama returned an empty response.")
                }

        except ImportError:
            return {
                "success": False,
                "message": _("ollama package is not installed. "
                           "Run: pip install ollama")
            }
        except Exception as e:
            error_msg = str(e)
            if "Connection refused" in error_msg or "connect" in error_msg.lower():
                return {
                    "success": False,
                    "message": _("Cannot connect to Ollama server at {0}. "
                               "Make sure Ollama is running (ollama serve).").format(
                        self.ollama_host or "http://localhost:11434"
                    )
                }
            return {
                "success": False,
                "message": _("Ollama connection failed: {0}").format(error_msg)
            }

    @frappe.whitelist()
    def test_unsplash_connection(self):
        """
        Test connection to Unsplash API.

        Returns:
            dict: Result containing success status and message.
        """
        if not self.unsplash_access_key:
            return {
                "success": False,
                "message": _("Unsplash access key is not configured.")
            }

        try:
            import requests

            access_key = self.get_password("unsplash_access_key")
            response = requests.get(
                "https://api.unsplash.com/photos/random",
                params={"client_id": access_key, "query": "test"},
                timeout=10
            )

            if response.status_code == 200:
                return {
                    "success": True,
                    "message": _("Unsplash connection successful.")
                }
            elif response.status_code == 401:
                return {
                    "success": False,
                    "message": _("Invalid Unsplash access key.")
                }
            else:
                return {
                    "success": False,
                    "message": _("Unsplash API returned status {0}.").format(
                        response.status_code
                    )
                }

        except ImportError:
            return {
                "success": False,
                "message": _("requests package is not installed.")
            }
        except Exception as e:
            return {
                "success": False,
                "message": _("Unsplash connection failed: {0}").format(str(e))
            }

    def get_configured_provider(self):
        """
        Get the currently configured and available LLM provider.

        Returns:
            str or None: Name of the configured provider, or None if none configured.
        """
        if not self.enable_ai_generation:
            return None

        # Return primary provider if configured
        if self.primary_llm_provider:
            provider_check = {
                "Gemini": self.gemini_api_key,
                "OpenAI": self.openai_api_key,
                "Anthropic": self.anthropic_api_key,
                "Ollama": self.ollama_enabled
            }
            if provider_check.get(self.primary_llm_provider):
                return self.primary_llm_provider

        # Fallback: return first available provider
        if self.gemini_api_key:
            return "Gemini"
        if self.openai_api_key:
            return "OpenAI"
        if self.anthropic_api_key:
            return "Anthropic"
        if self.ollama_enabled:
            return "Ollama"

        return None

    def is_production_protected(self):
        """
        Check if production protection is enabled and we're in a production environment.

        Returns:
            bool: True if generation should be blocked.
        """
        if not self.production_protection:
            return False

        # Check for production environment indicators
        site_config = frappe.get_site_config()

        # Check developer_mode (production = False or absent)
        if not site_config.get("developer_mode"):
            # Additional check: FRAPPE_ENV environment variable
            import os
            env = os.environ.get("FRAPPE_ENV", "").lower()
            if env in ("production", "prod"):
                return True

            # Check if site name suggests production
            site_name = frappe.local.site or ""
            prod_indicators = ["prod", "live", "www"]
            if any(indicator in site_name.lower() for indicator in prod_indicators):
                return True

        return False


def get_settings():
    """
    Get Mock Engine Settings singleton instance.

    This is the recommended way to access settings from other modules.

    Returns:
        MockEngineSettings: The settings document.

    Example:
        >>> from mock_data_engine.mock_data_engine.mock_data_engine.doctype.mock_engine_settings.mock_engine_settings import get_settings
        >>> settings = get_settings()
        >>> print(settings.default_locale)
        'tr_TR'
    """
    return frappe.get_single("Mock Engine Settings")

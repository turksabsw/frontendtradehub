# Copyright (c) 2024, Mock Data Engine and contributors
# For license information, please see license.txt

"""
Gemini LLM Provider for Mock Data Engine.

This module provides the Google Gemini provider implementation for AI-powered
mock data generation. It uses the google-genai SDK (NOT google-generativeai
which is deprecated and EOL Nov 2025).

Key Features:
- Uses google-genai SDK for Gemini API access
- Supports Gemini 2.0 Flash (default), 1.5 Flash, and 1.5 Pro models
- Temperature control for deterministic generation (default: 0)
- Automatic retry on transient failures
- Connection testing for API key validation

Usage:
    from mock_data_engine.providers.gemini_provider import (
        GeminiProvider,
        create_gemini_provider,
    )

    # Create provider with API key
    config = AIServiceConfig(
        provider_type=AIProviderType.GEMINI,
        api_key="your-api-key",
        model="gemini-2.0-flash",
        temperature=0.0,
    )
    provider = GeminiProvider(config)

    # Generate content
    result = provider.generate(
        prompt="Generate a Turkish company name",
        context={"locale": "tr_TR", "industry": "Technology"}
    )
    print(result.content)

Note:
    Requires the google-genai package to be installed:
    pip install google-genai

    Do NOT use google-generativeai (deprecated, EOL November 30, 2025)
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, TYPE_CHECKING

from mock_data_engine.providers.ai_service import (
    AIProviderType,
    AIServiceConfig,
    AIProviderError,
    AIProviderConnectionError,
    AIProviderRateLimitError,
    AIGenerationError,
    GenerationResult,
    LLMProvider,
    AIService,
)

if TYPE_CHECKING:
    from google.genai import Client
    from google.genai.types import GenerateContentResponse


# =============================================================================
# Constants
# =============================================================================

# Default model for Gemini provider
DEFAULT_GEMINI_MODEL = "gemini-2.0-flash"

# Available Gemini models
AVAILABLE_GEMINI_MODELS = [
    "gemini-2.0-flash",
    "gemini-2.0-flash-lite",
    "gemini-1.5-flash",
    "gemini-1.5-flash-8b",
    "gemini-1.5-pro",
]

# Test prompt for connection testing
TEST_PROMPT = "Say 'OK' if you can read this."


# =============================================================================
# GeminiProvider Implementation
# =============================================================================


class GeminiProvider(LLMProvider):
    """
    Google Gemini LLM provider implementation.

    This provider uses the google-genai SDK for accessing Google's Gemini
    models. It supports text generation for mock data creation.

    IMPORTANT: This uses the google-genai package, NOT google-generativeai
    which is deprecated (EOL Nov 30, 2025).

    Attributes:
        config: The provider configuration (AIServiceConfig).
        name: Provider name ("gemini").

    Supported Models:
        - gemini-2.0-flash (default): Fast and capable
        - gemini-2.0-flash-lite: Ultra-fast, cost-effective
        - gemini-1.5-flash: Fast and efficient
        - gemini-1.5-flash-8b: Smaller, faster variant
        - gemini-1.5-pro: Most capable, slower

    Example:
        >>> config = AIServiceConfig(
        ...     provider_type=AIProviderType.GEMINI,
        ...     api_key="your-api-key",
        ...     temperature=0.0,
        ... )
        >>> provider = GeminiProvider(config)
        >>> result = provider.generate("Generate a Turkish name")
        >>> print(result.content)
        "Ahmet Yilmaz"
    """

    def __init__(self, config: AIServiceConfig):
        """
        Initialize the Gemini provider.

        Args:
            config: The AIServiceConfig with provider settings.
                    Must have provider_type=AIProviderType.GEMINI.

        Raises:
            ValueError: If provider_type is not GEMINI.
        """
        if config.provider_type != AIProviderType.GEMINI:
            raise ValueError(
                f"Invalid provider type: {config.provider_type}. "
                f"Expected: {AIProviderType.GEMINI}"
            )
        super().__init__(config)
        self._genai_client: Optional["Client"] = None

    def _initialize_client(self) -> None:
        """
        Initialize the Google GenAI client.

        This method imports the google-genai SDK and creates a Client
        instance with the configured API key.

        Raises:
            ImportError: If google-genai package is not installed.
            AIProviderError: If client initialization fails.
        """
        try:
            from google import genai
        except ImportError as e:
            raise ImportError(
                "The google-genai package is required for Gemini provider. "
                "Install it with: pip install google-genai\n"
                "NOTE: Do NOT use google-generativeai (deprecated, EOL Nov 2025)"
            ) from e

        try:
            # Create the client with API key
            self._genai_client = genai.Client(api_key=self._config.api_key)
        except Exception as e:
            raise AIProviderError(
                f"Failed to initialize Gemini client: {e}",
                provider=self.name,
                original_error=e,
            )

    @property
    def client(self) -> "Client":
        """
        Get the GenAI client, initializing if needed.

        Returns:
            The initialized Google GenAI Client.

        Raises:
            AIProviderError: If client is not initialized and cannot be created.
        """
        if not self._initialized:
            self.initialize()
        return self._genai_client

    def generate(
        self,
        prompt: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> GenerationResult:
        """
        Generate content using Google Gemini.

        This method sends a prompt to the Gemini API and returns
        the generated content wrapped in a GenerationResult.

        Args:
            prompt: The prompt for content generation.
            context: Optional context dictionary with additional information.
                     Supported context keys:
                     - locale: The locale for generation (e.g., "tr_TR")
                     - doctype: The DocType being generated
                     - fieldname: The field being generated
                     - industry: Industry context for more relevant content

        Returns:
            GenerationResult containing the generated content and metadata.

        Raises:
            AIGenerationError: If content generation fails.
            AIProviderConnectionError: If connection to API fails.
            AIProviderRateLimitError: If rate limit is exceeded.

        Example:
            >>> result = provider.generate(
            ...     prompt="Generate a Turkish business name",
            ...     context={"locale": "tr_TR", "industry": "Retail"}
            ... )
            >>> print(result.content)
            "Yildiz Ticaret A.S."
        """
        if not self._initialized:
            self.initialize()

        # Build the enhanced prompt with context if provided
        enhanced_prompt = self._build_prompt_with_context(prompt, context)

        # Get the model to use
        model = self._config.default_model or DEFAULT_GEMINI_MODEL

        try:
            # Make the API call using google-genai SDK
            # The SDK uses: client.models.generate_content()
            response = self._genai_client.models.generate_content(
                model=model,
                contents=enhanced_prompt,
                config=self._build_generation_config(),
            )

            # Extract the text content from response
            content = self._extract_content(response)

            # Determine tokens used if available
            tokens_used = self._extract_token_usage(response)

            # Determine finish reason
            finish_reason = self._extract_finish_reason(response)

            return GenerationResult(
                content=content,
                provider=self.name,
                model=model,
                tokens_used=tokens_used,
                finish_reason=finish_reason,
                raw_response=response,
            )

        except Exception as e:
            # Handle specific error types
            error_str = str(e).lower()

            if "rate limit" in error_str or "429" in error_str or "quota" in error_str:
                raise AIProviderRateLimitError(
                    f"Gemini rate limit exceeded: {e}",
                    provider=self.name,
                    original_error=e,
                )
            elif "connection" in error_str or "timeout" in error_str or "network" in error_str:
                raise AIProviderConnectionError(
                    f"Failed to connect to Gemini API: {e}",
                    provider=self.name,
                    original_error=e,
                )
            elif "invalid" in error_str and "api" in error_str and "key" in error_str:
                raise AIProviderConnectionError(
                    f"Invalid Gemini API key: {e}",
                    provider=self.name,
                    original_error=e,
                )
            else:
                raise AIGenerationError(
                    f"Gemini generation failed: {e}",
                    provider=self.name,
                    original_error=e,
                )

    def _build_prompt_with_context(
        self,
        prompt: str,
        context: Optional[Dict[str, Any]],
    ) -> str:
        """
        Build an enhanced prompt with context information.

        Args:
            prompt: The base prompt.
            context: Optional context dictionary.

        Returns:
            Enhanced prompt string.
        """
        if not context:
            return prompt

        # Build context prefix
        context_parts = []

        if context.get("locale"):
            locale = context["locale"]
            locale_map = {
                "tr_TR": "Turkish",
                "en_US": "American English",
                "en_GB": "British English",
                "de_DE": "German",
                "fr_FR": "French",
            }
            language = locale_map.get(locale, locale)
            context_parts.append(f"Language/Locale: {language}")

        if context.get("industry"):
            context_parts.append(f"Industry: {context['industry']}")

        if context.get("doctype"):
            context_parts.append(f"DocType: {context['doctype']}")

        if context.get("fieldname"):
            context_parts.append(f"Field: {context['fieldname']}")

        if context.get("fieldtype"):
            context_parts.append(f"Field Type: {context['fieldtype']}")

        if context_parts:
            context_str = "\n".join(context_parts)
            return f"Context:\n{context_str}\n\nTask:\n{prompt}"

        return prompt

    def _build_generation_config(self) -> Dict[str, Any]:
        """
        Build the generation configuration for the API call.

        Returns:
            Dictionary with generation configuration.
        """
        # Using google-genai SDK format
        # Note: The config parameter accepts a GenerateContentConfig or dict
        return {
            "temperature": self._config.temperature,
            "max_output_tokens": self._config.max_tokens,
            # Stop sequences for cleaner output
            "stop_sequences": ["\n\n\n"],
        }

    def _extract_content(self, response: Any) -> str:
        """
        Extract text content from Gemini response.

        Args:
            response: The GenerateContentResponse from the API.

        Returns:
            The extracted text content.

        Raises:
            AIGenerationError: If content cannot be extracted.
        """
        try:
            # The google-genai SDK response has a .text property
            if hasattr(response, "text"):
                return response.text.strip()

            # Fallback: access candidates directly
            if hasattr(response, "candidates") and response.candidates:
                candidate = response.candidates[0]
                if hasattr(candidate, "content") and candidate.content:
                    if hasattr(candidate.content, "parts") and candidate.content.parts:
                        return candidate.content.parts[0].text.strip()

            # If we can't extract content, raise an error
            raise AIGenerationError(
                "No content in Gemini response",
                provider=self.name,
            )

        except AIGenerationError:
            raise
        except Exception as e:
            raise AIGenerationError(
                f"Failed to extract content from response: {e}",
                provider=self.name,
                original_error=e,
            )

    def _extract_token_usage(self, response: Any) -> Optional[int]:
        """
        Extract token usage from Gemini response.

        Args:
            response: The GenerateContentResponse from the API.

        Returns:
            Total tokens used, or None if not available.
        """
        try:
            # Try to get usage metadata
            if hasattr(response, "usage_metadata"):
                usage = response.usage_metadata
                if hasattr(usage, "total_token_count"):
                    return usage.total_token_count
                # Sum input and output tokens
                total = 0
                if hasattr(usage, "prompt_token_count"):
                    total += usage.prompt_token_count or 0
                if hasattr(usage, "candidates_token_count"):
                    total += usage.candidates_token_count or 0
                return total if total > 0 else None
            return None
        except Exception:
            return None

    def _extract_finish_reason(self, response: Any) -> Optional[str]:
        """
        Extract finish reason from Gemini response.

        Args:
            response: The GenerateContentResponse from the API.

        Returns:
            Finish reason string, or None if not available.
        """
        try:
            if hasattr(response, "candidates") and response.candidates:
                candidate = response.candidates[0]
                if hasattr(candidate, "finish_reason"):
                    return str(candidate.finish_reason)
            return None
        except Exception:
            return None

    def test_connection(self) -> bool:
        """
        Test the connection to the Gemini API.

        This method sends a simple prompt to verify the API key is valid
        and the service is accessible.

        Returns:
            True if connection is successful.

        Raises:
            AIProviderConnectionError: If connection test fails.
        """
        if not self._initialized:
            self.initialize()

        try:
            # Use a simple test prompt
            model = self._config.default_model or DEFAULT_GEMINI_MODEL

            response = self._genai_client.models.generate_content(
                model=model,
                contents=TEST_PROMPT,
                config={
                    "temperature": 0,
                    "max_output_tokens": 10,
                },
            )

            # Check if we got a response
            content = self._extract_content(response)
            return bool(content)

        except Exception as e:
            raise AIProviderConnectionError(
                f"Gemini connection test failed: {e}",
                provider=self.name,
                original_error=e,
            )

    def get_available_models(self) -> List[str]:
        """
        Get list of available Gemini models.

        Returns:
            List of model identifiers.
        """
        return AVAILABLE_GEMINI_MODELS.copy()

    def __repr__(self) -> str:
        """String representation of the provider."""
        model = self._config.default_model or DEFAULT_GEMINI_MODEL
        return (
            f"GeminiProvider("
            f"model={model}, "
            f"temperature={self._config.temperature}, "
            f"initialized={self._initialized})"
        )


# =============================================================================
# Factory Functions
# =============================================================================


def create_gemini_provider(
    api_key: str,
    model: Optional[str] = None,
    temperature: float = 0.0,
    max_tokens: int = 1024,
) -> GeminiProvider:
    """
    Factory function to create a GeminiProvider instance.

    This is a convenience function for quickly creating a Gemini provider
    without manually building the AIServiceConfig.

    Args:
        api_key: The Google API key for Gemini.
        model: Optional model to use (default: gemini-2.0-flash).
        temperature: Temperature for generation (default: 0.0 for determinism).
        max_tokens: Maximum tokens in response (default: 1024).

    Returns:
        Configured GeminiProvider instance.

    Example:
        >>> provider = create_gemini_provider(
        ...     api_key="your-api-key",
        ...     temperature=0.7,
        ... )
        >>> result = provider.generate("Hello!")
    """
    config = AIServiceConfig(
        provider_type=AIProviderType.GEMINI,
        api_key=api_key,
        model=model or DEFAULT_GEMINI_MODEL,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    return GeminiProvider(config)


# =============================================================================
# Provider Registration
# =============================================================================

# Register GeminiProvider with the AIService registry
# This allows get_llm_provider() to automatically create GeminiProvider
# instances when configured
AIService.register_provider(AIProviderType.GEMINI, GeminiProvider)


# =============================================================================
# Module Exports
# =============================================================================

__all__ = [
    "GeminiProvider",
    "create_gemini_provider",
    "DEFAULT_GEMINI_MODEL",
    "AVAILABLE_GEMINI_MODELS",
]

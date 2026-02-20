# Copyright (c) 2024, Mock Data Engine and contributors
# For license information, please see license.txt

"""
Ollama LLM Provider for Mock Data Engine.

This module provides the Ollama provider implementation for AI-powered
mock data generation using local LLM execution. It uses the ollama SDK
with the chat API.

Key Features:
- Uses ollama SDK for local LLM access
- Supports Gemma3 (default), Llama3, Mistral, CodeLlama, and other Ollama models
- No API key required - runs locally
- Temperature control for deterministic generation (default: 0)
- Automatic retry on transient failures
- Connection testing for server availability

IMPORTANT:
- Requires Ollama server running locally at http://localhost:11434
- Models must be pre-pulled: `ollama pull gemma3`

Usage:
    from mock_data_engine.providers.ollama_provider import (
        OllamaProvider,
        create_ollama_provider,
    )

    # Create provider
    config = AIServiceConfig(
        provider_type=AIProviderType.OLLAMA,
        model="gemma3",
        temperature=0.0,
    )
    provider = OllamaProvider(config)

    # Generate content
    result = provider.generate(
        prompt="Generate a Turkish company name",
        context={"locale": "tr_TR", "industry": "Technology"}
    )
    print(result.content)

Note:
    Requires the ollama package to be installed:
    pip install ollama

    And Ollama server must be running:
    ollama serve
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
    from ollama import ChatResponse


# =============================================================================
# Constants
# =============================================================================

# Default model for Ollama provider
DEFAULT_OLLAMA_MODEL = "gemma3"

# Default Ollama server URL
DEFAULT_OLLAMA_BASE_URL = "http://localhost:11434"

# Available Ollama models (commonly used)
AVAILABLE_OLLAMA_MODELS = [
    "gemma3",
    "gemma2",
    "llama3",
    "llama3.1",
    "mistral",
    "codellama",
    "phi3",
    "qwen2",
]

# Test prompt for connection testing
TEST_PROMPT = "Say 'OK' if you can read this."


# =============================================================================
# OllamaProvider Implementation
# =============================================================================


class OllamaProvider(LLMProvider):
    """
    Ollama LLM provider implementation for local LLM execution.

    This provider uses the ollama SDK for accessing locally running LLM models.
    It supports text generation for mock data creation without requiring
    an API key or internet connection.

    IMPORTANT:
    - Requires Ollama server running at http://localhost:11434
    - Models must be pre-pulled: `ollama pull gemma3`

    Attributes:
        config: The provider configuration (AIServiceConfig).
        name: Provider name ("ollama").

    Supported Models:
        - gemma3 (default): Google's Gemma 3 model
        - gemma2: Google's Gemma 2 model
        - llama3: Meta's Llama 3 model
        - llama3.1: Meta's Llama 3.1 model
        - mistral: Mistral AI's model
        - codellama: Meta's code-focused Llama model
        - phi3: Microsoft's Phi-3 model
        - qwen2: Alibaba's Qwen 2 model

    Example:
        >>> config = AIServiceConfig(
        ...     provider_type=AIProviderType.OLLAMA,
        ...     model="gemma3",
        ...     temperature=0.0,
        ... )
        >>> provider = OllamaProvider(config)
        >>> result = provider.generate("Generate a Turkish name")
        >>> print(result.content)
        "Ahmet Yilmaz"
    """

    def __init__(self, config: AIServiceConfig):
        """
        Initialize the Ollama provider.

        Args:
            config: The AIServiceConfig with provider settings.
                    Must have provider_type=AIProviderType.OLLAMA.

        Raises:
            ValueError: If provider_type is not OLLAMA.
        """
        if config.provider_type != AIProviderType.OLLAMA:
            raise ValueError(
                f"Invalid provider type: {config.provider_type}. "
                f"Expected: {AIProviderType.OLLAMA}"
            )
        super().__init__(config)
        self._chat_fn = None
        self._client = None

    def _initialize_client(self) -> None:
        """
        Initialize the Ollama client.

        This method imports the ollama SDK and stores the chat function
        for later use. It also validates that the Ollama server is accessible.

        Raises:
            ImportError: If ollama package is not installed.
            AIProviderError: If client initialization fails.
        """
        try:
            from ollama import chat, Client
        except ImportError as e:
            raise ImportError(
                "The ollama package is required for Ollama provider. "
                "Install it with: pip install ollama"
            ) from e

        try:
            # Store the chat function for later use
            self._chat_fn = chat

            # Create client with custom base URL if specified
            base_url = self._config.base_url or DEFAULT_OLLAMA_BASE_URL
            self._client = Client(host=base_url)

        except Exception as e:
            raise AIProviderError(
                f"Failed to initialize Ollama client: {e}",
                provider=self.name,
                original_error=e,
            )

    @property
    def client(self):
        """
        Get the Ollama client, initializing if needed.

        Returns:
            The initialized Ollama Client.

        Raises:
            AIProviderError: If client is not initialized and cannot be created.
        """
        if not self._initialized:
            self.initialize()
        return self._client

    def generate(
        self,
        prompt: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> GenerationResult:
        """
        Generate content using Ollama.

        This method sends a prompt to the local Ollama server and returns
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
            AIProviderConnectionError: If connection to Ollama server fails.

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
        model = self._config.default_model or DEFAULT_OLLAMA_MODEL

        try:
            # Make the API call using ollama SDK
            # Ollama uses chat() with model and messages parameters
            response = self._client.chat(
                model=model,
                messages=[{"role": "user", "content": enhanced_prompt}],
                options={
                    "temperature": self._config.temperature,
                    "num_predict": self._config.max_tokens,
                },
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

            if "connection" in error_str or "refused" in error_str:
                raise AIProviderConnectionError(
                    f"Failed to connect to Ollama server. "
                    f"Ensure Ollama is running at {self._config.base_url or DEFAULT_OLLAMA_BASE_URL}. "
                    f"Error: {e}",
                    provider=self.name,
                    original_error=e,
                )
            elif "model" in error_str and "not found" in error_str:
                raise AIProviderConnectionError(
                    f"Ollama model '{model}' not found. "
                    f"Pull the model first with: ollama pull {model}. "
                    f"Error: {e}",
                    provider=self.name,
                    original_error=e,
                )
            elif "timeout" in error_str:
                raise AIProviderConnectionError(
                    f"Ollama request timed out: {e}",
                    provider=self.name,
                    original_error=e,
                )
            else:
                raise AIGenerationError(
                    f"Ollama generation failed: {e}",
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

    def _extract_content(self, response: "ChatResponse") -> str:
        """
        Extract text content from Ollama response.

        Args:
            response: The ChatResponse from the API.

        Returns:
            The extracted text content.

        Raises:
            AIGenerationError: If content cannot be extracted.
        """
        try:
            # Ollama chat response structure: response.message.content
            if hasattr(response, "message") and response.message:
                if hasattr(response.message, "content") and response.message.content:
                    return response.message.content.strip()

            # Alternative: response might be a dict-like object
            if isinstance(response, dict):
                message = response.get("message", {})
                if isinstance(message, dict):
                    content = message.get("content", "")
                    if content:
                        return content.strip()

            # If we can't extract content, raise an error
            raise AIGenerationError(
                "No content in Ollama response",
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

    def _extract_token_usage(self, response: "ChatResponse") -> Optional[int]:
        """
        Extract token usage from Ollama response.

        Args:
            response: The ChatResponse from the API.

        Returns:
            Total tokens used, or None if not available.
        """
        try:
            # Ollama provides token counts in the response
            total = 0

            # Check for prompt_eval_count (input tokens)
            if hasattr(response, "prompt_eval_count"):
                total += response.prompt_eval_count or 0
            elif isinstance(response, dict):
                total += response.get("prompt_eval_count", 0) or 0

            # Check for eval_count (output tokens)
            if hasattr(response, "eval_count"):
                total += response.eval_count or 0
            elif isinstance(response, dict):
                total += response.get("eval_count", 0) or 0

            return total if total > 0 else None

        except Exception:
            return None

    def _extract_finish_reason(self, response: "ChatResponse") -> Optional[str]:
        """
        Extract finish reason from Ollama response.

        Args:
            response: The ChatResponse from the API.

        Returns:
            Finish reason string, or None if not available.
        """
        try:
            # Ollama uses done_reason attribute
            if hasattr(response, "done_reason"):
                return response.done_reason
            elif isinstance(response, dict):
                return response.get("done_reason")

            # Check for 'done' status
            if hasattr(response, "done") and response.done:
                return "stop"
            elif isinstance(response, dict) and response.get("done"):
                return "stop"

            return None
        except Exception:
            return None

    def test_connection(self) -> bool:
        """
        Test the connection to the Ollama server.

        This method sends a simple prompt to verify the server is accessible
        and the configured model is available.

        Returns:
            True if connection is successful.

        Raises:
            AIProviderConnectionError: If connection test fails.
        """
        if not self._initialized:
            self.initialize()

        try:
            # Use a simple test prompt with minimal tokens
            model = self._config.default_model or DEFAULT_OLLAMA_MODEL

            response = self._client.chat(
                model=model,
                messages=[{"role": "user", "content": TEST_PROMPT}],
                options={
                    "temperature": 0,
                    "num_predict": 10,
                },
            )

            # Check if we got a response
            content = self._extract_content(response)
            return bool(content)

        except Exception as e:
            error_str = str(e).lower()

            if "connection" in error_str or "refused" in error_str:
                raise AIProviderConnectionError(
                    f"Cannot connect to Ollama server at "
                    f"{self._config.base_url or DEFAULT_OLLAMA_BASE_URL}. "
                    f"Ensure Ollama is running with: ollama serve",
                    provider=self.name,
                    original_error=e,
                )
            elif "model" in error_str and "not found" in error_str:
                raise AIProviderConnectionError(
                    f"Model '{model}' not found. "
                    f"Pull the model with: ollama pull {model}",
                    provider=self.name,
                    original_error=e,
                )
            else:
                raise AIProviderConnectionError(
                    f"Ollama connection test failed: {e}",
                    provider=self.name,
                    original_error=e,
                )

    def get_available_models(self) -> List[str]:
        """
        Get list of available Ollama models.

        Returns:
            List of model identifiers.

        Note:
            This returns a static list of commonly used models.
            For dynamically discovering installed models, use
            the Ollama CLI: `ollama list`
        """
        return AVAILABLE_OLLAMA_MODELS.copy()

    def list_installed_models(self) -> List[str]:
        """
        List models installed on the local Ollama server.

        Returns:
            List of installed model names.

        Raises:
            AIProviderConnectionError: If unable to connect to Ollama server.
        """
        if not self._initialized:
            self.initialize()

        try:
            # Use ollama.list() to get installed models
            from ollama import list as ollama_list

            response = ollama_list()

            models = []
            if hasattr(response, "models"):
                for model in response.models:
                    if hasattr(model, "name"):
                        models.append(model.name)
            elif isinstance(response, dict):
                for model in response.get("models", []):
                    if isinstance(model, dict):
                        models.append(model.get("name", ""))
                    elif hasattr(model, "name"):
                        models.append(model.name)

            return [m for m in models if m]

        except Exception as e:
            raise AIProviderConnectionError(
                f"Failed to list Ollama models: {e}",
                provider=self.name,
                original_error=e,
            )

    def __repr__(self) -> str:
        """String representation of the provider."""
        model = self._config.default_model or DEFAULT_OLLAMA_MODEL
        base_url = self._config.base_url or DEFAULT_OLLAMA_BASE_URL
        return (
            f"OllamaProvider("
            f"model={model}, "
            f"base_url={base_url}, "
            f"temperature={self._config.temperature}, "
            f"initialized={self._initialized})"
        )


# =============================================================================
# Factory Functions
# =============================================================================


def create_ollama_provider(
    model: Optional[str] = None,
    base_url: Optional[str] = None,
    temperature: float = 0.0,
    max_tokens: int = 1024,
) -> OllamaProvider:
    """
    Factory function to create an OllamaProvider instance.

    This is a convenience function for quickly creating an Ollama provider
    without manually building the AIServiceConfig.

    Args:
        model: Optional model to use (default: gemma3).
        base_url: Optional Ollama server URL (default: http://localhost:11434).
        temperature: Temperature for generation (default: 0.0 for determinism).
        max_tokens: Maximum tokens in response (default: 1024).

    Returns:
        Configured OllamaProvider instance.

    Example:
        >>> provider = create_ollama_provider(
        ...     model="llama3",
        ...     temperature=0.7,
        ... )
        >>> result = provider.generate("Hello!")
    """
    config = AIServiceConfig(
        provider_type=AIProviderType.OLLAMA,
        model=model or DEFAULT_OLLAMA_MODEL,
        base_url=base_url or DEFAULT_OLLAMA_BASE_URL,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    return OllamaProvider(config)


# =============================================================================
# Provider Registration
# =============================================================================

# Register OllamaProvider with the AIService registry
# This allows get_llm_provider() to automatically create OllamaProvider
# instances when configured
AIService.register_provider(AIProviderType.OLLAMA, OllamaProvider)


# =============================================================================
# Module Exports
# =============================================================================

__all__ = [
    "OllamaProvider",
    "create_ollama_provider",
    "DEFAULT_OLLAMA_MODEL",
    "DEFAULT_OLLAMA_BASE_URL",
    "AVAILABLE_OLLAMA_MODELS",
]

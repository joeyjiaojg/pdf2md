"""LLM integration — auto-detect providers and post-process markdown output."""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from typing import Any

from pdf2md.config import Config

logger = logging.getLogger(__name__)

_PROBE_TIMEOUT = 5  # seconds
_CHAT_TIMEOUT = 30  # seconds

_PROVIDER_CONFIGS: dict[str, dict[str, str]] = {
    "opencode": {
        "base_url": "https://api.opencode.ai/v1",
        "model": "deepseek-v4-flash-free",
        "key_env": "OPENCODE_API_KEY",
    },
    "ollama": {
        "base_url": "http://localhost:11434",
        "model": "qwen3:0.8b",
        "key_env": "",
    },
    "llamacpp": {
        "base_url": "http://localhost:8081/v1",
        "model": "",
        "key_env": "",
    },
}

_STAGE_PROMPTS: dict[str, str] = {
    "table": (
        "Normalize the HTML tables in this markdown. "
        "Fix broken row/colspan, alignment issues, and ensure valid HTML table syntax. "
        "Only change table content; preserve all other text exactly as-is."
    ),
    "formula": (
        "Clean up LaTeX formulas in this markdown. "
        "Fix mismatched delimiters: use $$ for display math and $ for inline formulas. "
        "Only change formula content; preserve all other text exactly as-is."
    ),
    "heading": (
        "Improve heading hierarchy in this markdown. "
        "Ensure H1 comes first, H2 follows H1, H3 follows H2 — no skipping levels. "
        "Only change heading levels; preserve all content and formatting."
    ),
    "full_md": (
        "Polish this markdown for consistency: fix spacing around headings, "
        "normalize list indentation, ensure code blocks have language tags where obvious. "
        "Do NOT rewrite sentences or change content meaning."
    ),
    "translate": (
        "Translate this markdown document from {source_lang} to Simplified Chinese (中文). "
        "Requirements:\n"
        "1. Translate ALL text content including headings, paragraphs, tables, lists\n"
        "2. Keep the original markdown structure (##, ###, tables, code blocks)\n"
        "3. Translate table headers and content to Chinese\n"
        "4. Preserve technical terms, numbers, codes, and proper nouns\n"
        "5. Output ONLY the translated markdown, no explanations\n\n"
        "---\n"
        "{content}"
    ),
}


class LLMClient:
    """Client for OpenAI-compatible LLM APIs (opencode, ollama, llamacpp)."""

    def __init__(
        self,
        provider: str,
        base_url: str,
        api_key: str,
        model: str,
        config: Config,
    ) -> None:
        self.provider = provider
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.config = config

    def post_process(self, markdown: str, stage: str) -> str:
        """Post-process markdown content using the LLM for a specific stage.

        Args:
            markdown: The markdown content to process.
            stage: One of "table", "formula", "heading", "full_md", "translate".

        Returns:
            Processed markdown, or original markdown unchanged on failure.
        """
        prompt = _STAGE_PROMPTS.get(stage)
        if prompt is None:
            logger.warning("Unknown LLM post-processing stage: %s", stage)
            return markdown

        if not markdown.strip():
            return markdown

        if stage == "translate":
            result = self._translate_to_chinese(markdown)
            if result is None:
                return markdown
            return result

        messages = [
            {
                "role": "system",
                "content": "You are a markdown formatting assistant. Follow instructions precisely and return only the processed markdown.",
            },
            {"role": "user", "content": f"{prompt}\n\n---\n{markdown}"},
        ]

        result = self._call(messages)
        if result is None:
            return markdown

        return result

    def _translate_to_chinese(self, markdown: str) -> str | None:
        source_lang = getattr(self.config, "translate_from_lang", "auto")
        
        if source_lang == "auto":
            try:
                from pdf2md.language import detect_language
                source_lang = detect_language(markdown)
                logger.info("Auto-detected source language: %s", source_lang)
            except Exception as e:
                logger.warning("Failed to auto-detect language: %s, using English", e)
                source_lang = "en"

        prompt = _STAGE_PROMPTS["translate"].format(source_lang=source_lang, content=markdown)

        messages = [
            {
                "role": "system",
                "content": "You are a professional Chinese translator. Translate the following markdown to Simplified Chinese while preserving structure.",
            },
            {"role": "user", "content": prompt},
        ]

        result = self._call(messages)
        return result

    def _call(self, messages: list[dict[str, str]]) -> str | None:
        """Call the LLM chat completion API.

        Returns:
            Response content string, or None on failure.
        """
        url = f"{self.base_url}/chat/completions"
        headers = {
            "Content-Type": "application/json",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        body: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.0,
        }

        data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")

        try:
            with urllib.request.urlopen(req, timeout=_CHAT_TIMEOUT) as resp:
                response_data = json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, json.JSONDecodeError, OSError) as exc:
            logger.warning("LLM API call failed: %s", exc)
            return None

        try:
            content = response_data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            logger.warning("Unexpected LLM response format: %s", exc)
            return None

        return content.strip()


def _probe_endpoint(url: str, timeout: int = _PROBE_TIMEOUT) -> bool:
    """Check if an HTTP endpoint is reachable.

    Returns True if the endpoint responds with HTTP 200 (or similar).
    """
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return resp.status < 500
    except (urllib.error.URLError, OSError):
        return False


def create_llm_client(config: Config) -> LLMClient | None:
    """Factory: probe available LLM providers and return a client for the first responsive one.

    Resolution order (based on config.llm_provider):
      1. Explicitly configured provider.
      2. If "opencode" is configured but unreachable, fall through to ollama → llamacpp.
      3. If an explicit non-default provider is configured but unreachable, return None.

    Returns:
        An LLMClient instance, or None if no provider is available.
    """
    if not config.llm_enabled:
        return None

    provider = config.llm_provider
    prov_config = _PROVIDER_CONFIGS.get(provider)

    if prov_config is None:
        logger.warning("Unknown LLM provider: %s", provider)
        return None

    # Resolve base URL
    base_url = (
        config.llm_base_url
        or prov_config["base_url"]
    )

    # Resolve model
    model = config.llm_model or prov_config["model"]

    # Resolve API key
    api_key = config.llm_api_key
    if not api_key and prov_config["key_env"]:
        api_key = os.environ.get(prov_config["key_env"], "")

    # Determine probe URL
    probe_url = f"{base_url.rstrip('/')}/models"

    if _probe_endpoint(probe_url):
        logger.info("LLM provider '%s' is available at %s", provider, base_url)
        return LLMClient(provider, base_url, api_key, model, config)

    # If the configured provider is the default "opencode", try fallbacks
    if provider == "opencode":
        logger.info("OpenCode unreachable, trying fallback providers...")
        for fallback_name in ("ollama", "llamacpp"):
            fb_config = _PROVIDER_CONFIGS[fallback_name]
            fb_url = config.llm_base_url or fb_config["base_url"]
            fb_model = config.llm_model or fb_config["model"]
            fb_key = config.llm_api_key
            if not fb_key and fb_config["key_env"]:
                fb_key = os.environ.get(fb_config["key_env"], "")

            if _probe_endpoint(f"{fb_url.rstrip('/')}/models"):
                logger.info("Fallback LLM provider '%s' is available", fallback_name)
                return LLMClient(fallback_name, fb_url, fb_key, fb_model, config)

        logger.warning("No LLM provider available (opencode, ollama, llamacpp all unreachable)")
        return None

    # Explicit non-default provider configured but unreachable
    logger.warning(
        "Configured LLM provider '%s' is not available at %s", provider, base_url
    )
    return None

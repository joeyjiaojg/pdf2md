"""Configuration loading for pdf2md CLI tool."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError:
    tomllib = None  # type: ignore[assignment]


@dataclass
class Config:
    """Single source of truth for pdf2md configuration."""

    # MinerU backend selection
    backend: str = "hybrid-auto-engine"  # hybrid-auto-engine, pipeline, vlm-auto-engine

    # Output directory for markdown files
    output_dir: str = "./output"

    # Batch processing
    batch_size: int = 1

    # LLM provider settings
    llm_enabled: bool = False
    llm_provider: str = "opencode"  # opencode, ollama, llamacpp
    llm_model: str = ""  # empty = use provider default
    llm_base_url: str = ""  # empty = use provider default
    llm_api_key: str = ""  # empty = try without key or use env var

    # Per-stage LLM post-processing toggles
    stages_post_table: bool = False
    stages_post_formula: bool = False
    stages_post_md: bool = False

    # Translation settings
    translate_enabled: bool = False
    translate_from_lang: str = "auto"

    # General
    verbose: bool = False
    timeout: int = 3600  # max seconds per PDF (CPU needs longer)

    # MinerU model source (for downloading models)
    model_source: str = ""  # modelscope, huggingface, local; empty = auto


def _merge_into_config(config: Config, data: dict[str, Any]) -> Config:
    """Merge a flat or nested dict into a Config dataclass.

    Supports both:
      - flat keys: backend="pipeline"
      - nested keys: llm.provider="ollama"
    """
    valid_field_names = {f.name for f in fields(config)}

    for key, value in data.items():
        if key in valid_field_names:
            setattr(config, key, value)
        elif "." in key:
            # dotted key like "llm.api_key" → skip, not supported
            logger.debug("Ignoring dotted config key: %s", key)
        else:
            logger.debug("Ignoring unknown config key: %s", key)
    return config


def _load_toml(path: Path) -> dict[str, Any] | None:
    """Load a TOML file. Returns None on failure."""
    if tomllib is None:
        logger.warning("tomllib not available (Python 3.11+ required for TOML support)")
        return None
    try:
        with path.open("rb") as f:
            return tomllib.load(f)
    except Exception as exc:
        logger.error("Failed to parse TOML config %s: %s", path, exc)
        return None


def _load_json(path: Path) -> dict[str, Any] | None:
    """Load a JSON file. Returns None on failure."""
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as exc:
        logger.error("Failed to parse JSON config %s: %s", path, exc)
        return None


def load_config(config_path: str | None = None) -> Config:
    """Load configuration from a TOML or JSON file, or return defaults.

    Resolution order:
      1. If config_path is given, load from that file.
      2. If config_path ends with .toml, use TOML parser.
      3. If config_path ends with .json, use JSON parser.
      4. If no path or file not found, return Config() defaults.
    """
    config = Config()

    if config_path is None:
        return config

    path = Path(config_path)

    if not path.exists():
        logger.warning("Config file not found: %s. Using defaults.", config_path)
        return config

    if path.suffix == ".toml":
        data = _load_toml(path)
    elif path.suffix == ".json":
        data = _load_json(path)
    else:
        logger.warning("Unsupported config format: %s. Use .toml or .json.", path.suffix)
        return config

    if data is None:
        return config

    _merge_into_config(config, data)

    # Override api_key from env if not set in config
    if not config.llm_api_key:
        config.llm_api_key = os.environ.get("OPENCODE_API_KEY", "")

    return config

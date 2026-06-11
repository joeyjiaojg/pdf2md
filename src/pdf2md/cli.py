"""CLI entrypoint for pdf2md — convert PDF to Markdown using MinerU."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from pdf2md.config import load_config
from pdf2md.converter import detect_mineru_cli, parse_pdfs
from pdf2md.llm import create_llm_client


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pdf2md",
        description="Convert PDF to Markdown using MinerU, with optional LLM post-processing.",
    )

    parser.add_argument(
        "input",
        nargs="+",
        help="PDF file path(s) or directory containing PDFs (supports glob patterns)",
    )
    parser.add_argument(
        "-o", "--output-dir",
        default="./output",
        help="Output directory for markdown files (default: ./output)",
    )
    parser.add_argument(
        "-b", "--backend",
        choices=["hybrid-auto-engine", "pipeline", "vlm-auto-engine"],
        default=None,
        help="MinerU parsing backend (default: hybrid-auto-engine)",
    )
    parser.add_argument(
        "--llm",
        action="store_true",
        help="Enable LLM post-processing of markdown output",
    )
    parser.add_argument(
        "--llm-provider",
        choices=["opencode", "ollama", "llamacpp"],
        default=None,
        help="LLM provider (default: opencode, falls back to ollama/llamacpp)",
    )
    parser.add_argument(
        "--llm-model",
        default=None,
        help="LLM model name (default: provider-specific default)",
    )
    parser.add_argument(
        "--stages",
        nargs="+",
        choices=["table", "formula", "heading", "full_md"],
        default=None,
        help="LLM post-processing stages to run (default: none, implies --llm)",
    )
    parser.add_argument(
        "--config",
        default=None,
        help="Path to TOML or JSON config file",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=None,
        help="Number of PDFs to process in parallel (default: 1)",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=None,
        help="Timeout in seconds per PDF (default: 3600)",
    )
    parser.add_argument(
        "--translate",
        action="store_true",
        help="Enable auto-translation to Simplified Chinese if source is not Chinese",
    )
    parser.add_argument(
        "--translate-from",
        choices=["auto", "en", "ja", "ko"],
        default=None,
        help="Source language for translation (default: auto-detect)",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose logging",
    )

    return parser


def _expand_inputs(raw_inputs: list[str]) -> list[str]:
    """Expand input arguments into a flat list of PDF file paths.

    Supports:
      - Individual file paths
      - Directory paths (scanned for .pdf files)
      - Glob patterns (e.g. "*.pdf", "docs/**/*.pdf")
    """
    paths: list[str] = []
    for raw in raw_inputs:
        p = Path(raw)
        if p.is_dir():
            paths.extend(str(f) for f in sorted(p.glob("*.pdf")))
        elif p.exists():
            paths.append(str(p.resolve()))
        else:
            # Try glob expansion
            import glob as glob_module
            matches = sorted(glob_module.glob(raw, recursive=True))
            if matches:
                paths.extend(matches)
            else:
                logging.warning("No files matched: %s", raw)
    return paths


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(levelname)s | %(message)s",
        stream=sys.stderr,
    )


def _gpu_available() -> bool:
    """Detect whether a CUDA-compatible GPU is available.

    Returns True if torch is installed and cuda is available,
    otherwise False.  On CPU-only systems this avoids crashing
    on MinerU's hybrid-auto-engine backend.
    """
    try:
        import torch
        return torch.cuda.is_available()
    except Exception:
        return False


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()

    # Load config (CLI args override config file values)
    config = load_config(args.config)
    _setup_logging(args.verbose or config.verbose)

    # Auto-detect GPU — fall back to pipeline on CPU-only systems
    user_explicit_backend = args.backend is not None
    if not user_explicit_backend and not _gpu_available():
        logger = logging.getLogger(__name__)
        logger.info("No GPU detected — falling back to 'pipeline' backend")
        config.backend = "pipeline"

    # CLI overrides
    if args.output_dir:
        config.output_dir = args.output_dir
    if args.backend:
        config.backend = args.backend
    if args.batch_size:
        config.batch_size = args.batch_size
    if args.timeout is not None:
        config.timeout = args.timeout
    if args.translate:
        config.translate_enabled = True
    if args.translate_from:
        config.translate_from_lang = args.translate_from
    if args.verbose:
        config.verbose = True

    # LLM overrides
    if args.llm or args.stages:
        config.llm_enabled = True
    if args.llm_provider:
        config.llm_provider = args.llm_provider
    if args.llm_model:
        config.llm_model = args.llm_model
    if args.stages:
        config.stages_post_table = "table" in args.stages
        config.stages_post_formula = "formula" in args.stages
        config.stages_post_md = "full_md" in args.stages
        # 'heading' in stages → not a separate Config field; treated as part of full_md

    # Check MinerU availability
    cli = detect_mineru_cli()
    if cli is None:
        logging.error(
            "MinerU CLI not found. Install with: uv pip install 'mineru[core]'"
        )
        return 1

    logging.info("Using MinerU CLI: %s", cli)
    logging.info("Backend: %s", config.backend)

    # Expand input paths
    pdf_paths = _expand_inputs(args.input)
    if not pdf_paths:
        logging.error("No PDF files found from input: %s", " ".join(args.input))
        return 1

    logging.info("Found %d PDF(s) to process", len(pdf_paths))

    # Initialize LLM client if enabled
    llm_client = None
    if config.llm_enabled:
        llm_client = create_llm_client(config)
        if llm_client is None:
            logging.warning("LLM post-processing requested but no provider available. Continuing without LLM.")
        else:
            logging.info("LLM post-processing enabled using provider: %s", llm_client.provider)

    # Parse PDFs
    try:
        output_paths = parse_pdfs(
            input_paths=pdf_paths,
            output_dir=config.output_dir,
            backend=config.backend,
            config=config,
        )
    except RuntimeError as exc:
        logging.error(str(exc))
        return 1

    # Post-process with LLM if enabled
    if llm_client and output_paths:
        stages_to_run = []
        if config.stages_post_table:
            stages_to_run.append("table")
        if config.stages_post_formula:
            stages_to_run.append("formula")
        if config.stages_post_md:
            stages_to_run.append("full_md")

        # Add translation if enabled and content is not Chinese
        if config.translate_enabled:
            stages_to_run.append("translate")

        if stages_to_run:
            for md_path_str in output_paths:
                md_path = Path(md_path_str)
                if not md_path.is_file():
                    continue
                try:
                    content = md_path.read_text(encoding="utf-8")
                except Exception as exc:
                    logging.warning("Cannot read %s: %s", md_path, exc)
                    continue

                if "translate" in stages_to_run:
                    try:
                        from pdf2md.language import is_chinese
                        if not is_chinese(content):
                            logging.info("Translating %s from non-Chinese to Chinese", md_path.name)
                            content = llm_client.post_process(content, "translate")
                        else:
                            logging.info("%s is already in Chinese, skipping translation", md_path.name)
                    except Exception as e:
                        logging.warning("Translation failed for %s: %s", md_path.name, e)
                        logging.info("Continuing without translation...")

                for stage in stages_to_run:
                    if stage != "translate":
                        logging.info("LLM post-processing stage '%s' on %s", stage, md_path.name)
                        content = llm_client.post_process(content, stage)

                try:
                    md_path.write_text(content, encoding="utf-8")
                except Exception as exc:
                    logging.warning("Cannot write %s: %s", md_path, exc)

    # Summary
    success_count = len(output_paths)
    logging.info(
        "Done. %d/%d PDF(s) converted. Output: %s",
        success_count,
        len(pdf_paths),
        config.output_dir,
    )
    for p in output_paths:
        print(p)

    return 0


if __name__ == "__main__":
    sys.exit(main())

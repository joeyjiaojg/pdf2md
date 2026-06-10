"""MinerU wrapper — invoke the mineru CLI to convert PDFs to Markdown."""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Callable

from pdf2md.config import Config
from pdf2md.splitter import split_pdf_by_range, get_page_range_from_pdf

logger = logging.getLogger(__name__)

def detect_mineru_cli() -> str | None:
    """Check which MinerU CLI is available on the system.

    Returns:
        "mineru" for v3.x CLI, "magic-pdf" for v1.x CLI, or None if neither found.
    """
    for cli in ("mineru", "magic-pdf"):
        if shutil.which(cli) is not None:
            return cli
    return None


def _find_output_md(output_dir: Path, input_stem: str) -> str | None:
    """Locate the markdown output file produced by MinerU.

    MinerU v3.x: {output_dir}/{input_stem}/ **/*.md
    magic-pdf:   {output_dir}/{input_stem}_md/ *.md
    Also checks flat {output_dir}/*.md as last resort.
    """
    candidates = [
        output_dir / input_stem,
        output_dir / f"{input_stem}_md",
    ]
    for candidate_dir in candidates:
        if candidate_dir.is_dir():
            # Recursive glob — MinerU v3.x nests output under method subdir (auto/)
            md_files = sorted(candidate_dir.rglob("*.md"))
            if md_files:
                return str(md_files[0])

    # Flat directory fallback
    flat_md = list(output_dir.glob("*.md"))
    if flat_md:
        return str(flat_md[0])

    return None


def _build_env(config: Config) -> dict[str, str]:
    """Build enriched environment for subprocess."""
    env = os.environ.copy()
    if config.model_source:
        env["MINERU_MODEL_SOURCE"] = config.model_source
    return env


def parse_pdf(
    input_path: str,
    output_dir: str,
    backend: str | None = None,
    config: Config | None = None,
    progress_callback: Callable[[str], None] | None = None,
) -> str:
    """Convert a single PDF to Markdown using the mineru CLI.

    Args:
        input_path: Path to the PDF file.
        output_dir: Directory to write output.
        backend: MinerU backend override (defaults to config.backend or "hybrid-auto-engine").
        config: Optional Config object for settings.
        progress_callback: Called with status messages during conversion.

    Returns:
        Absolute path to the generated markdown file.

    Raises:
        RuntimeError: If mineru CLI is not found, conversion fails, or output not produced.
    """
    if config is None:
        config = Config()

    backend = backend or config.backend
    out = Path(output_dir).resolve()
    inp = Path(input_path).resolve()

    if not inp.is_file():
        raise RuntimeError(f"Input file not found: {input_path}")

    out.mkdir(parents=True, exist_ok=True)

    total_pages = 0
    try:
        total_pages = get_page_range_from_pdf(str(inp))
    except RuntimeError as e:
        if "pypdf" in str(e).lower():
            raise
        logger.warning("Cannot detect page count: %s, skipping auto-split", e)

    if config.timeout < 7200 and total_pages > 100:
        logger.info(
            "Large PDF detected (%d pages), auto-splitting for timeout safety",
            total_pages
        )
        split_output = output_dir
        split_paths = list(split_pdf_by_range(str(inp), split_output, max_pages_per_file=50))
        _emit(progress_callback, f"Split {inp.name} into {len(split_paths)} parts")
        
        parsed_outputs = []
        for split_path in split_paths:
            orig_output_dir = config.output_dir
            config.output_dir = split_output
            try:
                parsed_outputs.append(parse_pdf(
                    split_path, split_output, backend, config, progress_callback
                ))
            finally:
                config.output_dir = orig_output_dir
        
        return merge_markdown_splits(parsed_outputs, str(inp.stem))

    _emit(progress_callback, f"Parsing {inp.name} using backend '{backend}'...")

    cli = detect_mineru_cli()
    if cli is None:
        raise RuntimeError(
            "No MinerU CLI found. Install with: uv pip install 'mineru[core]'"
        )

    args = _build_command(cli, str(inp), str(out), backend, config)
    env = _build_env(config)

    if config.verbose:
        logger.info("Running: %s", " ".join(args))

    try:
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=config.timeout,
            env=env,
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError(
            f"mineru timed out after {config.timeout}s on {inp.name}"
        )

    if result.returncode != 0:
        error_msg = result.stderr.strip() or result.stdout.strip() or "unknown error"
        raise RuntimeError(
            f"mineru failed on {inp.name} (exit {result.returncode}): {error_msg[:500]}"
        )

    if config.verbose:
        _log_cli_output(result)

    md_path = _find_output_md(out, inp.stem)
    if md_path is None:
        # Wait briefly for filesystem flush
        time.sleep(1)
        md_path = _find_output_md(out, inp.stem)

    if md_path is None:
        raise RuntimeError(
            f"mineru completed but no markdown output found in {out}"
        )

    _emit(progress_callback, f"✓ {inp.name} → {md_path}")
    return md_path


def _build_command(cli: str, input_path: str, output_dir: str, backend: str, config: Config) -> list[str]:
    """Build the subprocess argument list for the detected CLI."""
    if cli == "mineru":
        args = [
            "mineru",
            "-p", input_path,
            "-o", output_dir,
            "-b", backend,
        ]
    else:  # magic-pdf
        # magic-pdf uses -m (method) rather than -b (backend)
        method = "auto"
        if backend == "pipeline":
            method = "auto"
        args = [
            "magic-pdf",
            "-p", input_path,
            "-o", output_dir,
            "-m", method,
        ]

    return args


def _log_cli_output(result: subprocess.CompletedProcess) -> None:
    """Log stdout/stderr from mineru subprocess when verbose."""
    if result.stdout.strip():
        for line in result.stdout.strip().splitlines():
            logger.debug("mineru stdout: %s", line)
    if result.stderr.strip():
        for line in result.stderr.strip().splitlines():
            logger.debug("mineru stderr: %s", line)


def _emit(callback: Callable[[str], None] | None, msg: str) -> None:
    """Call the progress callback if provided."""
    if callback is not None:
        callback(msg)


def merge_markdown_splits(md_paths: list[str], original_stem: str) -> str:
    """Merge multiple markdown files from split PDFs back into a single file.

    Concatenates all markdown files in order and writes to a single output file.

    Args:
        md_paths: List of markdown file paths from split PDFs.
        original_stem: Original PDF stem for output filename.

    Returns:
        Path to the merged markdown file.
    """
    if not md_paths:
        raise RuntimeError("No markdown files to merge")

    merged_content = ""
    for md_path in md_paths:
        if Path(md_path).is_file():
            merged_content += Path(md_path).read_text(encoding="utf-8")
            merged_content += "\n"

    output_path = Path(output_dir) / f"{original_stem}.md"
    output_path.write_text(merged_content, encoding="utf-8")

    logger.info("Merged %d split markdown files into %s", len(md_paths), output_path)
    return str(output_path.resolve())


def _process_single(args: tuple) -> str:
    """Wrapper for parallel execution — unpacks a tuple for ThreadPoolExecutor.

    Args tuple: (input_path, output_dir, backend, config)
    """
    input_path, output_dir, backend, config = args
    return parse_pdf(
        input_path=input_path,
        output_dir=output_dir,
        backend=backend,
        config=config,
    )


def parse_pdfs(
    input_paths: list[str],
    output_dir: str,
    backend: str | None = None,
    config: Config | None = None,
) -> list[str]:
    """Convert multiple PDFs to Markdown, optionally in parallel.

    Args:
        input_paths: List of PDF file paths.
        output_dir: Directory to write outputs.
        backend: MinerU backend override.
        config: Configuration object.

    Returns:
        List of output markdown file paths in the same order as inputs.

    Raises:
        RuntimeError: If any conversion fails.
    """
    if config is None:
        config = Config()

    backend = backend or config.backend
    batch_size = max(1, config.batch_size)

    if batch_size == 1:
        results = []
        for path in input_paths:
            results.append(parse_pdf(path, output_dir, backend, config))
        return results

    # Parallel execution
    results: list[str | None] = [None] * len(input_paths)
    work_items = [
        (path, output_dir, backend, config) for path in input_paths
    ]

    with ThreadPoolExecutor(max_workers=batch_size) as executor:
        future_map = {
            executor.submit(_process_single, item): idx
            for idx, item in enumerate(work_items)
        }
        for future in as_completed(future_map):
            idx = future_map[future]
            try:
                results[idx] = future.result()
            except Exception as exc:
                raise RuntimeError(
                    f"Failed to parse {input_paths[idx]}: {exc}"
                ) from exc

    return [r for r in results if r is not None]

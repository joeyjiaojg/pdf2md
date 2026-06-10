"""PDF splitter utilities for splitting PDFs by page range."""

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Generator

try:
    from pypdf import PdfReader, PdfWriter
except ImportError:
    PdfReader = None  # type: ignore
    PdfWriter = None  # type: ignore

logger = logging.getLogger(__name__)


def split_pdf_by_pages(
    input_path: str,
    output_dir: str,
    pages: list[list[int]],
    prefix: str | None = None,
) -> list[str]:
    """Split a PDF file into multiple PDFs based on page ranges.

    Args:
        input_path: Path to the input PDF.
        output_dir: Directory to write split PDFs.
        pages: List of page ranges, where each range is a list of 1-based page numbers.
               Example: [[1, 50], [51, 100], [101, 194]]
        prefix: Optional prefix for output filenames. Uses input stem if not provided.

    Returns:
        List of paths to the split PDF files.
    """
    input_path = Path(input_path).resolve()
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    if not input_path.is_file():
        raise RuntimeError(f"Input PDF not found: {input_path}")

    stem = prefix or input_path.stem
    split_paths: list[str] = []

    try:
        # Use pdfplumber or pypdf for splitting
        try:
            from pypdf import PdfReader
            use_pypdf = True
        except ImportError:
            logger.warning("pypdf not available, trying pdf2image + poppler...")
            use_pypdf = False

        if use_pypdf:
            reader = PdfReader(str(input_path))
            total_pages = len(reader.pages)
            logger.info("Input PDF has %d pages", total_pages)

            for page_range in pages:
                if not page_range:
                    continue

                start_page = min(page_range) - 1
                end_page = max(page_range)

                if start_page < 0 or end_page >= total_pages or start_page > end_page:
                    logger.warning("Invalid page range %s for %d-page PDF", page_range, total_pages)
                    continue

                output_path = output_dir / f"{stem}_p{start_page+1}-{end_page}.pdf"

                writer = PdfWriter()
                for i in range(start_page, end_page):
                    writer.add_page(reader.pages[i])

                with open(output_path, "wb") as f:
                    writer.write(f)

                split_paths.append(str(output_path.resolve()))
                logger.info("Split: %s → %s (pages %s-%s)", input_path.name, output_path.name, start_page+1, end_page)

        else:
            raise RuntimeError("PDF splitting requires pypdf. Install with: pip install pypdf")

    except Exception as exc:
        logger.error("Failed to split PDF: %s", exc)
        raise

    return split_paths


def get_page_range_from_pdf(input_path: str) -> int:
    """Get the total number of pages in a PDF.

    Args:
        input_path: Path to the PDF file.

    Returns:
        Total page count.

    Raises:
        RuntimeError: If pypdf is not available or PDF cannot be read.
    """
    try:
        from pypdf import PdfReader
        reader = PdfReader(input_path)
        return len(reader.pages)
    except ImportError:
        raise RuntimeError(
            "pypdf is required to detect PDF page count. Install with: pip install pypdf"
        )
    except Exception as exc:
        raise RuntimeError(f"Cannot read PDF {input_path}: {exc}")


def split_pdf_by_range(
    input_path: str,
    output_dir: str,
    max_pages_per_file: int = 50,
) -> Generator[str, None, None]:
    """Split a PDF into multiple files, each with at most max_pages_per_file pages.

    Args:
        input_path: Path to the input PDF.
        output_dir: Directory to write split PDFs.
        max_pages_per_file: Maximum pages per split PDF.

    Yields:
        Paths to the split PDF files.
    """
    total_pages = get_page_range_from_pdf(input_path)
    logger.info("Splitting %s (%d pages) into chunks of %d pages each", input_path, total_pages, max_pages_per_file)

    stem = Path(input_path).stem
    start = 1

    while start <= total_pages:
        end = min(start + max_pages_per_file - 1, total_pages)
        page_range = list(range(start, end + 1))

        # Split this chunk
        split_paths = split_pdf_by_pages(input_path, output_dir, [page_range], f"{stem}_part")
        for p in split_paths:
            yield p

        start = end + 1


if __name__ == "__main__":
    import sys
    from pypdf import PdfWriter, PdfReader

    if len(sys.argv) < 3:
        print(f"Usage: {sys.argv[0]} <input.pdf> <output_dir> [max_pages]")
        sys.exit(1)

    input_pdf = sys.argv[1]
    output_dir = sys.argv[2]
    max_pages = int(sys.argv[3]) if len(sys.argv) > 3 else 50

    split_pdf_by_range(input_pdf, output_dir, max_pages)
    print("Split complete")

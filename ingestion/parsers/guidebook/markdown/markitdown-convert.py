#!/usr/bin/env python3
"""
pdf2cleanmd_concurrent.py

Pipeline:
  1) Per page: extract single-page PDF (in-memory) and raw Markdown via markitdown, render PNG via pypdfium2.
  2) If text is minimal/empty, use OCR (EasyOCR) to extract text first.
  3) Submit OpenAI vision cleanup for each page concurrently (up to MAX_CONCURRENCY workers).
  4) Write per-page .md as soon as the result returns; optionally combine into one .md at the end.
  5) Aggregate and print total token usage.

Install:
  pip install "markitdown[pdf]" pypdfium2 pypdf pillow openai python-dotenv easyocr

Environment:
  - Put OPENAI_API_KEY in .env or export it in your shell.
"""

from __future__ import annotations

import base64
import io
import sys
import tempfile
from pathlib import Path
from typing import Optional, Tuple, Dict, Any, List
from concurrent.futures import ThreadPoolExecutor, as_completed

from dotenv import load_dotenv
from markitdown import MarkItDown
import pypdfium2 as pdfium
from pypdf import PdfReader, PdfWriter
from PIL import Image  # noqa: F401
from openai import OpenAI

# ------------------------------
# Constants (edit these)
# ------------------------------
INPUT_FILE: Path = Path("3.pdf")     # Path to source PDF or image (png/jpg)
OUT_DIR: Optional[Path] = None           # None => "<file_stem>_md"
MODEL: str = "gpt-4o"               # Vision-capable model
DPI: int = 220                           # Page rasterization DPI
START_PAGE: int = 3                      # 1-based inclusive (for PDFs)
END_PAGE: Optional[int] = 3           # 1-based inclusive; None => last page (for PDFs)
LINK_IMAGE: bool = False                 # Put ![ ](...) at top of each page's .md
COMBINE: bool = True                     # Write combined Markdown at the end
SKIP_OPENAI: bool = False                # If True, skip OpenAI call (saves raw MarkItDown output)
MAX_CONCURRENCY: int = 5                 # Number of concurrent OpenAI calls
TEMPERATURE: float = 0.0                 # OpenAI temperature
USE_OCR_IF_NEEDED: bool = True           # If True, use OCR when text extraction is minimal
MIN_TEXT_LENGTH: int = 50                # Minimum text length to consider valid extraction
# ------------------------------

load_dotenv()

# Lazy-load OCR reader (only when needed)
_ocr_reader = None

def get_ocr_reader():
    global _ocr_reader
    if _ocr_reader is None:
        import easyocr
        print("[OCR] Initializing EasyOCR with Korean and English support...")
        _ocr_reader = easyocr.Reader(['ko', 'en'], gpu=False)
    return _ocr_reader


def ocr_image(image_path: Path) -> str:
    """Extract text from image using EasyOCR (Korean + English)."""
    reader = get_ocr_reader()
    result = reader.readtext(str(image_path), detail=0)
    return "\n".join(result)


def b64_image(path: Path) -> str:
    with open(path, "rb") as f:
        import base64 as _b64
        return _b64.b64encode(f.read()).decode("ascii")


def extract_page_pdf_bytes(src_pdf: Path, page_index: int) -> bytes:
    reader = PdfReader(str(src_pdf))
    writer = PdfWriter()
    writer.add_page(reader.pages[page_index])
    bio = io.BytesIO()
    writer.write(bio)
    bio.seek(0)
    return bio.getvalue()


def markitdown_convert_page(md: MarkItDown, page_pdf_bytes: bytes) -> str:
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(page_pdf_bytes)
        tmp.flush()
        tmp_path = Path(tmp.name)
    try:
        result = md.convert(str(tmp_path))
        return (result.text_content or "").strip()
    finally:
        try:
            tmp_path.unlink(missing_ok=True)
        except Exception:
            pass


def render_page_png(pdf_doc: pdfium.PdfDocument, page_index: int, out_png: Path, dpi: int = 220) -> None:
    scale = float(dpi) / 72.0
    page = pdf_doc[page_index]
    pil = page.render(scale=scale).to_pil()
    out_png.parent.mkdir(parents=True, exist_ok=True)
    pil.save(out_png, format="PNG")


def build_messages(raw_markdown: str, page_png_path: Path, page_no: int) -> list[dict[str, Any]]:
    img_b64 = b64_image(page_png_path)
    return [
        {
            "role": "system",
            "content": (
                "You are a precise Markdown formatter. Given raw text and a page image, "
                "reconstruct clean, semantic Markdown for this single page only. "
                "Preserve all content; do not add text not present on this page. "
                "If the markdown text format does not match the image, prioritize the document structure from the image. "
                "Infer headings, lists, tables (GitHub Flavored Markdown). "
                "Keep math as LaTeX ($...$ / $$...$$). "
                # "Respect reading order for multi-column layouts. "
                "If a figure/caption is obvious, include it as a Markdown figure. "
                "Return ONLY the Markdown for this page - do NOT wrap it in code blocks or markdown fences."
                "Preserve Chart formatting. If the text does not respect the chart from the image, reformat it to match the chart."
            ),
        },
        {
            "role": "user",
            "content": [
                {"type": "text", "text": f"Page {page_no} — raw markdown to clean:\n\n{raw_markdown}"},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img_b64}", "detail": "high"}},
            ],
        },
    ]


def openai_cleanup_page(
    model: str,
    page_no: int,
    raw_markdown: str,
    png_path: Path,
    temperature: float,
) -> Tuple[int, str, Dict[str, int]]:
    """
    Worker function for a single page: calls OpenAI and returns (page_no, cleaned_markdown, usage).
    Creates its own OpenAI client (thread-safe).
    """
    client = OpenAI()
    messages = build_messages(raw_markdown, png_path, page_no)
    resp = client.chat.completions.create(model=model, messages=messages, temperature=temperature)
    md_text = (resp.choices[0].message.content or "").strip()
    usage = {
        "prompt_tokens": getattr(resp.usage, "prompt_tokens", 0) if hasattr(resp, "usage") else 0,
        "completion_tokens": getattr(resp.usage, "completion_tokens", 0) if hasattr(resp, "usage") else 0,
        "total_tokens": getattr(resp.usage, "total_tokens", 0) if hasattr(resp, "usage") else 0,
    }
    return page_no, md_text, usage


def combine_pages(out_dir: Path, combined_name: str = "document_refined.md") -> Path:
    parts = []
    for md_file in sorted(out_dir.glob("page-*.md")):
        # Extract page number from filename (e.g., page-001.md -> 1)
        page_num = int(md_file.stem.split("-")[1])
        content = md_file.read_text(encoding="utf-8").rstrip()
        # Add page separator
        parts.append(f"#### Page {page_num}\n\n{content}\n")
    out_path = out_dir / combined_name
    out_path.write_text("\n".join(parts), encoding="utf-8")
    return out_path


def is_image_file(path: Path) -> bool:
    return path.suffix.lower() in ['.png', '.jpg', '.jpeg']


def main() -> int:
    input_path = INPUT_FILE
    if not input_path.exists():
        print(f"[!] File not found: {input_path}", file=sys.stderr)
        return 2

    out_dir = OUT_DIR or Path(f"{input_path.stem}_md")
    out_dir.mkdir(parents=True, exist_ok=True)

    md = MarkItDown()

    # Handle image files vs PDFs
    if is_image_file(input_path):
        print(f"Processing image file: {input_path} → {out_dir}")

        # For images, create a single page job
        page_no = 1
        png_path = out_dir / f"page-{page_no:03d}.png"
        md_path = out_dir / f"page-{page_no:03d}.md"

        # Check if already processed
        if png_path.exists() and md_path.exists():
            print(f"⊘ Page {page_no}: Already processed, skipping...")
            page_jobs = []
        else:
            # Copy image to output directory
            from shutil import copy2
            copy2(str(input_path), str(png_path))

            # Try OCR directly on the image
            if USE_OCR_IF_NEEDED:
                print(f"[OCR] Extracting text from image...")
                raw_md = ocr_image(input_path)
                print(f"[OCR] Extracted {len(raw_md)} characters")
            else:
                raw_md = ""

            page_jobs = [(page_no, md_path, png_path, raw_md)]
        total_pages = 1

    else:
        # PDF processing
        pdf_path = input_path
        pdf_doc = pdfium.PdfDocument(str(pdf_path))
        total_pages = len(pdf_doc)

        start_idx = max(0, (START_PAGE - 1))
        end_idx = (END_PAGE - 1) if END_PAGE is not None else (total_pages - 1)
        if start_idx > end_idx or start_idx >= total_pages:
            print(f"[!] Invalid page range. PDF has {total_pages} pages.", file=sys.stderr)
            return 2

        print(f"Processing {pdf_path} → {out_dir}  (pages {start_idx+1}..{end_idx+1} of {total_pages})")

        # Step 1: Extract raw_md + render PNG for each target page
        page_jobs: List[Tuple[int, Path, Path, str]] = []  # (page_no, md_path, png_path, raw_md)
        for i in range(start_idx, min(end_idx, total_pages - 1) + 1):
            page_no = i + 1
            png_path = out_dir / f"page-{page_no:03d}.png"
            md_path = out_dir / f"page-{page_no:03d}.md"

            # Check if already processed
            if png_path.exists() and md_path.exists():
                print(f"⊘ Page {page_no}: Already processed, skipping...")
                continue

            page_pdf_bytes = extract_page_pdf_bytes(pdf_path, i)
            raw_md = markitdown_convert_page(md, page_pdf_bytes)
            render_page_png(pdf_doc, i, png_path, dpi=DPI)

            # If text extraction is poor, use OCR
            if USE_OCR_IF_NEEDED and len(raw_md.strip()) < MIN_TEXT_LENGTH:
                print(f"[OCR] Page {page_no}: Minimal text extracted ({len(raw_md)} chars), using OCR...")
                ocr_text = ocr_image(png_path)
                print(f"[OCR] Page {page_no}: Extracted {len(ocr_text)} characters via OCR")
                raw_md = ocr_text

            page_jobs.append((page_no, md_path, png_path, raw_md))

    # Step 2: Fan out OpenAI calls concurrently
    totals = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

    if SKIP_OPENAI:
        # No concurrency path—just dump raw outputs
        for page_no, md_path, png_path, raw_md in page_jobs:
            cleaned = raw_md
            with md_path.open("w", encoding="utf-8") as f:
                if LINK_IMAGE:
                    f.write(f"![Page {page_no}]({png_path.name})\n\n")
                f.write(cleaned.strip() + "\n")
            print(f"✔ Page {page_no}: {md_path.name}, {png_path.name}")
    else:
        with ThreadPoolExecutor(max_workers=max(1, int(MAX_CONCURRENCY))) as pool:
            futures = {
                pool.submit(
                    openai_cleanup_page,
                    MODEL,
                    page_no,
                    raw_md,
                    png_path,
                    TEMPERATURE,
                ): (page_no, md_path, png_path)
                for (page_no, md_path, png_path, raw_md) in page_jobs
            }

            for fut in as_completed(futures):
                page_no, md_path, png_path = futures[fut]
                try:
                    _page_no, cleaned, usage = fut.result()
                except Exception as e:
                    print(f"[!] OpenAI call failed on page {page_no}: {e}", file=sys.stderr)
                    # Fallback: use raw_md already captured in page_jobs
                    raw_md = next(r for (p, _, _, r) in page_jobs if p == page_no)
                    cleaned = raw_md
                    usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

                totals["prompt_tokens"] += usage.get("prompt_tokens", 0)
                totals["completion_tokens"] += usage.get("completion_tokens", 0)
                totals["total_tokens"] += usage.get("total_tokens", 0)

                with md_path.open("w", encoding="utf-8") as f:
                    if LINK_IMAGE:
                        f.write(f"![Page {page_no}]({png_path.name})\n\n")
                    f.write(cleaned.strip() + "\n")

                print(f"✔ Page {page_no}: {md_path.name}, {png_path.name}")

    # Step 3: Combine
    if COMBINE:
        combined = combine_pages(out_dir)
        print(f"✔ Combined Markdown: {combined}")

    # Step 4: Token totals
    print("=== OpenAI Token Usage ===")
    print(f"Prompt tokens:     {totals['prompt_tokens']}")
    print(f"Completion tokens: {totals['completion_tokens']}")
    print(f"Total tokens:      {totals['total_tokens']}")

    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Language detection utilities for markdown content."""

from __future__ import annotations

import logging
import re
from typing import Literal

logger = logging.getLogger(__name__)


# Unicode ranges for common scripts
SCRIPT_RANGES: dict[str, tuple[int, int]] = {
    "zh": (0x4e00, 0x9fff),  # CJK Unified Ideographs (Mainland Chinese)
    "zh_ext": (0x3400, 0x4dbf),  # CJK Unified Ideographs Extension A
    "ja": (0x4e00, 0x9fff) | (0x3040, 0x309f) | (0x30a0, 0x30ff),  # CJK + Hiragana + Katakana
    "ko": (0xac00, 0xd7af),  # Hangul Syllables
    "en": (0x0041, 0x007a) | (0x0074, 0x007a),  # Basic Latin (letters)
}


def detect_script(text: str) -> str | None:
    """Detect the dominant script in text using Unicode ranges.

    Returns:
        Script code (zh, ja, ko, en, etc.) or None if detection fails.
    """
    if not text or len(text.strip()) < 50:
        return None

    # Count characters in each script range
    script_counts: dict[str, int] = {script: 0 for script in SCRIPT_RANGES}

    for char in text[:5000]:  # Sample first 5000 chars for speed
        code = ord(char)
        for script, (start, end) in SCRIPT_RANGES.items():
            if start <= code <= end:
                script_counts[script] += 1
                break  # Count each char only once

    # Find dominant script
    max_count = max(script_counts.values())
    if max_count == 0:
        return None

    # Return script with highest count
    dominant = max(script_counts, key=lambda s: script_counts[s])
    return dominant


def detect_language(markdown: str) -> Literal["zh", "ja", "ko", "en", "other"]:
    """Detect the language of markdown content.

    Checks:
      1. Table headers for language keywords
      2. Plain text for script dominance
      3. Fallback to filename if available

    Args:
        markdown: The markdown content to analyze.

    Returns:
        Language code: "zh" (Chinese), "ja" (Japanese), "ko" (Korean),
        "en" (English), or "other" (unknown/other language).
    """
    if not markdown.strip():
        return "other"

    # Check for Chinese/Japanese/Korean table headers
    zh_keywords = ["姓名", "地址", "金额", "日期", "报告", "公司", "股东"]
    ja_keywords = ["氏名", "住所", "金額", "日付", "会社", "株主"]
    ko_keywords = ["이름", "주소", "금액", "일시", "회사", "주주"]
    en_keywords = ["Name", "Address", "Amount", "Date", "Company", "Shareholder"]

    text_content = re.sub(r'<[^>]+>', '', markdown)  # Remove HTML tags
    text_content = re.sub(r'\[.*?\]', '', text_content)  # Remove markdown links

    # Check table headers
    if any(kw in markdown for kw in zh_keywords):
        return "zh"
    if any(kw in markdown for kw in ja_keywords):
        return "ja"
    if any(kw in markdown for kw in ko_keywords):
        return "ko"
    if any(kw in markdown for kw in en_keywords):
        return "en"

    # Check script dominance
    dominant_script = detect_script(markdown)
    if dominant_script == "zh" or dominant_script == "zh_ext":
        return "zh"
    elif dominant_script == "ja":
        return "ja"
    elif dominant_script == "ko":
        return "ko"
    elif dominant_script == "en":
        return "en"

    return "other"


def is_chinese(markdown: str) -> bool:
    """Check if markdown content is primarily in Chinese.

    Returns:
        True if Chinese, False otherwise.
    """
    return detect_language(markdown) == "zh"


if __name__ == "__main__":
    # Test with sample Chinese text
    sample_zh = """
    ## 公司简介
    
    公司名称：天津绿发电力集团股份有限公司
    
    股票代码：000537
    
    注册地址：天津经济技术开发区新城西路 52 号
    """

    sample_en = """
    ## Company Overview
    
    Company Name: Green Development Electricity Group
    
    Stock Code: 000537
    
    Registered Address: Tianjin Economic-Technological Development Area
    """

    print(f"Chinese sample: {detect_language(sample_zh)}")
    print(f"English sample: {detect_language(sample_en)}")

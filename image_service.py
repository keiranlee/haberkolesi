"""Devosuit branded social card generator for news items."""

import os
from pathlib import Path
import re
from typing import Optional, Tuple
from datetime import datetime

from PIL import Image, ImageDraw, ImageFont

from domain import Category, RawNews

# Brand color constants
BG_COLOR = (32, 31, 75)        # #201F4B (Deep Devosuit Indigo)
BG_ACCENT = (20, 19, 52)       # Darker indigo gradient
ORANGE_PRIMARY = (244, 132, 1) # #F48401
ORANGE_DARK = (242, 64, 1)     # #F24001
WHITE = (255, 255, 255)
MUTED_TEXT = (165, 172, 205)   # Slate/purple-gray
BORDER_COLOR = (55, 52, 115)   # Border stroke

CATEGORY_COLORS = {
    Category.GIRISIM: (244, 132, 1),    # Devosuit Orange
    Category.AI: (147, 51, 234),         # Purple
    Category.TEKNOLOJI: (59, 130, 246),  # Blue
    Category.YAZILIM: (16, 185, 129),    # Emerald
}

CATEGORY_TITLES = {
    Category.GIRISIM: "GİRİŞİM",
    Category.AI: "YAPAY ZEKA",
    Category.TEKNOLOJI: "TEKNOLOJİ",
    Category.YAZILIM: "YAZILIM",
}


def _get_font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    """Find and load a modern system font or fallback to default."""
    font_candidates = [
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf" if bold else "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/System/Library/Fonts/SFNS.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for candidate in font_candidates:
        if os.path.exists(candidate):
            try:
                return ImageFont.truetype(candidate, size)
            except Exception:
                continue
    return ImageFont.load_default()


def _wrap_text(text: str, font: ImageFont.ImageFont, max_width: int, draw: ImageDraw.ImageDraw) -> list[str]:
    """Wrap text to fit within max_width pixels."""
    words = text.split()
    if not words:
        return []
    lines = []
    current_line = words[0]
    for word in words[1:]:
        test_line = f"{current_line} {word}"
        bbox = draw.textbbox((0, 0), test_line, font=font)
        w = bbox[2] - bbox[0]
        if w <= max_width:
            current_line = test_line
        else:
            lines.append(current_line)
            current_line = word
    lines.append(current_line)
    return lines


def _truncate_lines(lines: list[str], max_lines: int) -> list[str]:
    if len(lines) <= max_lines:
        return lines
    retained = list(lines[:max_lines])
    retained[-1] = retained[-1].rstrip(".… ") + "…"
    return retained


def _is_english(text: str) -> bool:
    """Detect if text is predominantly English to prevent English text on Turkish social cards."""
    if not text:
        return False
    # If it contains Turkish-specific characters, it's Turkish
    if re.search(r"[çğıöşüÇĞİÖŞÜ]", text):
        return False
    english_words = {
        "the", "be", "to", "of", "and", "a", "in", "that", "have", "i",
        "it", "for", "not", "on", "with", "he", "as", "you", "do", "at",
        "this", "but", "his", "by", "from", "they", "we", "say", "her",
        "she", "or", "an", "will", "my", "one", "all", "would", "there",
        "their", "what", "so", "up", "out", "if", "about", "who", "get",
        "which", "go", "me", "when", "make", "can", "like", "time", "no",
        "just", "him", "know", "take", "people", "into", "year", "your",
        "good", "some", "could", "them", "see", "other", "than", "then",
        "now", "look", "only", "come", "its", "over", "think", "also",
        "back", "after", "use", "two", "how", "our", "work", "first",
        "well", "way", "even", "new", "want", "because", "any", "these",
        "give", "day", "most", "us", "is", "are", "was", "were", "has",
        "had", "been", "buyers", "percent", "prefer", "online", "before",
        "sales", "representative", "market", "business", "company",
        "data", "indicate", "search", "engine", "making", "page"
    }
    words = re.findall(r"[a-z]+", text.lower())
    if not words:
        return False
    matching_en = [w for w in words if w in english_words]
    return len(matching_en) >= 2 or (len(words) >= 3 and len(matching_en) / len(words) >= 0.25)


class ImageService:
    def __init__(self, output_dir: Path, assets_dir: Optional[Path] = None):
        self.output_dir = output_dir / "images"
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.assets_dir = assets_dir or (Path(__file__).resolve().parent / "assets")

    def generate_card(
        self,
        news_id: int,
        title: str,
        category: Category,
        source: str,
        published_at: Optional[datetime] = None,
        key_fact: Optional[str] = None,
        width: int = 1200,
        height: int = 675,
    ) -> Path:
        """Create a 1200x675 Devosuit branded news card."""
        # 1. Canvas with deep background
        image = Image.new("RGB", (width, height), BG_COLOR)
        draw = ImageDraw.Draw(image, "RGBA")

        # 2. Modern background glow / gradient accents
        # Top-left ambient dark gradient
        for r in range(400, 0, -20):
            alpha = int(35 * (1 - r / 400))
            draw.ellipse(
                [-100 - r, -100 - r, -100 + r, -100 + r],
                fill=(*BG_ACCENT, alpha),
            )

        # Bottom-right warm orange glow
        for r in range(500, 0, -25):
            alpha = int(45 * (1 - r / 500))
            draw.ellipse(
                [width - 150 - r, height - 100 - r, width - 150 + r, height - 100 + r],
                fill=(*ORANGE_PRIMARY, alpha),
            )

        # Subtle card boundary inner border
        draw.rounded_rectangle(
            [24, 24, width - 24, height - 24],
            radius=20,
            outline=(*BORDER_COLOR, 180),
            width=2,
        )

        # 3. Top bar: Category Badge & Devosuit Brand
        cat_color = CATEGORY_COLORS.get(category, ORANGE_PRIMARY)
        cat_text = CATEGORY_TITLES.get(category, category.value.upper())

        badge_font = _get_font(20, bold=True)
        badge_bbox = draw.textbbox((0, 0), cat_text, font=badge_font)
        badge_w = (badge_bbox[2] - badge_bbox[0]) + 32
        badge_h = 38
        badge_x = 72
        badge_y = 68

        # Category pill
        draw.rounded_rectangle(
            [badge_x, badge_y, badge_x + badge_w, badge_y + badge_h],
            radius=19,
            fill=(*cat_color, 45),
            outline=(*cat_color, 220),
            width=2,
        )
        draw.text(
            (badge_x + 16, badge_y + 8),
            cat_text,
            font=badge_font,
            fill=WHITE,
        )

        # Devosuit Brand Mark (Top Right)
        brand_font = _get_font(22, bold=True)
        brand_text = "DEVOSUIT"
        brand_bbox = draw.textbbox((0, 0), brand_text, font=brand_font)
        brand_w = brand_bbox[2] - brand_bbox[0]
        draw.text(
            (width - 72 - brand_w, 74),
            brand_text,
            font=brand_font,
            fill=(*ORANGE_PRIMARY, 240),
        )

        # 4. News Headline (Center)
        # Font size adapts based on title length
        title_font_size = 52 if len(title) <= 70 else (46 if len(title) <= 110 else 40)
        title_font = _get_font(title_font_size, bold=True)
        title_lines = _wrap_text(title, title_font, max_width=1040, draw=draw)
        title_lines = _truncate_lines(title_lines, 4)

        line_height = int(title_font_size * 1.35)
        # Vertically balance the title
        has_fact = bool(key_fact and not _is_english(key_fact) and len(title_lines) <= 3)
        title_start_y = 195 if (not has_fact and len(title_lines) <= 2) else 165

        for i, line in enumerate(title_lines):
            draw.text(
                (72, title_start_y + (i * line_height)),
                line,
                font=title_font,
                fill=WHITE,
            )

        current_y = title_start_y + (len(title_lines) * line_height) + 24

        # 5. Key Fact / Highlight Box (ONLY if Turkish and space permits)
        if has_fact:
            fact_font = _get_font(21, bold=False)
            fact_lines = _wrap_text(f"•  {key_fact}", fact_font, max_width=980, draw=draw)
            fact_lines = _truncate_lines(fact_lines, 2)
            if fact_lines:
                fact_h = len(fact_lines) * 32 + 24
                draw.rounded_rectangle(
                    [72, current_y, width - 140, current_y + fact_h],
                    radius=12,
                    fill=(45, 43, 98, 160),
                    outline=(70, 66, 140, 200),
                    width=1,
                )
                for fi, fl in enumerate(fact_lines):
                    draw.text(
                        (94, current_y + 12 + (fi * 32)),
                        fl,
                        font=fact_font,
                        fill=MUTED_TEXT,
                    )

        # 6. Bottom Bar: Source, Date, and Orange Accent Line
        # Orange decorative accent bar
        draw.rounded_rectangle(
            [72, height - 105, 180, height - 101],
            radius=2,
            fill=ORANGE_PRIMARY,
        )

        clean_source = re.sub(r"\s*[\-—–]\s*(?:Latest|RSS|Feed|Son\s*Haberler|En\s*Son).*", "", source, flags=re.I).strip() or source
        footer_font = _get_font(19, bold=False)
        date_str = published_at.strftime("%d.%m.%Y") if published_at else ""
        source_meta = f"Kaynak: {clean_source}" + (f" · {date_str}" if date_str else "")

        draw.text(
            (72, height - 85),
            source_meta,
            font=footer_font,
            fill=MUTED_TEXT,
        )

        draw.text(
            (width - 195, height - 85),
            "devosuit.com",
            font=footer_font,
            fill=MUTED_TEXT,
        )

        # Save to file
        file_path = self.output_dir / f"{news_id}.png"
        image.save(file_path, "PNG", optimize=True)
        return file_path

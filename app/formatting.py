from __future__ import annotations

import html
import re


_CODE_SPAN = re.compile(r"`([^`]+)`")
_LINK = re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+)\)")
_BOLD = re.compile(r"\*\*(.+?)\*\*|__(.+?)__")
_ITALIC = re.compile(r"(?<!\w)\*([^*\n]+?)\*(?!\w)|(?<!\w)_([^_\n]+?)_(?!\w)")
_HEADING = re.compile(r"^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$")
_BULLET = re.compile(r"^\s*[-*+]\s+(.+)$")


def markdown_to_telegram_html(markdown: str) -> str:
    """Render the Markdown emitted by the engine using Telegram HTML tags."""
    rendered_lines: list[str] = []
    in_code_block = False
    for line in markdown.splitlines():
        stripped = line.strip()
        if stripped.startswith("```"):
            if in_code_block:
                rendered_lines.append("</code>")
                in_code_block = False
            else:
                rendered_lines.append("<pre><code>")
                in_code_block = True
            continue
        if in_code_block:
            rendered_lines.append(html.escape(line, quote=False))
            continue
        if stripped == "---":
            rendered_lines.append("<b>──────────</b>")
            continue
        heading = _HEADING.match(line)
        if heading:
            heading_text = heading.group(1)
            if not (
                (heading_text.startswith("**") and heading_text.endswith("**"))
                or (heading_text.startswith("__") and heading_text.endswith("__"))
            ):
                heading_text = f"**{heading_text}**"
            line = heading_text
        else:
            bullet = _BULLET.match(line)
            if bullet:
                line = f"• {bullet.group(1)}"
        rendered_lines.append(_render_inline(line))
    if in_code_block:
        rendered_lines.append("</code>")
    return "\n".join(rendered_lines)


def _render_inline(text: str) -> str:
    escaped = html.escape(text, quote=False)
    placeholders: list[str] = []

    def protect(value: str) -> str:
        placeholders.append(value)
        return f"\x00{len(placeholders) - 1}\x00"

    escaped = _CODE_SPAN.sub(
        lambda match: protect(f"<code>{match.group(1)}</code>"),
        escaped,
    )
    escaped = _LINK.sub(
        lambda match: protect(
            f'<a href="{html.escape(match.group(2), quote=True)}">{match.group(1)}</a>'
        ),
        escaped,
    )
    escaped = _BOLD.sub(
        lambda match: f"<b>{match.group(1) or match.group(2)}</b>",
        escaped,
    )
    escaped = _ITALIC.sub(
        lambda match: f"<i>{match.group(1) or match.group(2)}</i>",
        escaped,
    )
    for index, value in enumerate(placeholders):
        escaped = escaped.replace(f"\x00{index}\x00", value)
    return escaped


def split_message(text: str, max_length: int = 4096) -> list[str]:
    """Split text into Telegram-sized chunks without needlessly breaking words."""
    if max_length <= 0:
        raise ValueError("max_length must be positive")
    if not text:
        return [text]

    chunks: list[str] = []
    remaining = text
    while len(remaining) > max_length:
        split_at = remaining.rfind("\n", 0, max_length + 1)
        if split_at <= 0:
            split_at = max_length

        chunk = remaining[:split_at].rstrip()
        if not chunk:
            split_at = max_length
            chunk = remaining[:split_at]
        chunks.append(chunk)
        remaining = remaining[split_at:].lstrip()

    chunks.append(remaining)
    return chunks
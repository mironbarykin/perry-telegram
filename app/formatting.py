from __future__ import annotations

import html
import re


_CODE_SPAN = re.compile(r"`([^`]+)`")
_LINK = re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+)\)")
_BOLD = re.compile(r"\*\*(.+?)\*\*|__(.+?)__")
_ITALIC = re.compile(r"(?<!\w)\*([^*\n]+?)\*(?!\w)|(?<!\w)_([^_\n]+?)_(?!\w)")


def markdown_to_telegram_html(markdown: str) -> str:
    """Render the Markdown emitted by the engine using Telegram HTML tags."""
    rendered_lines: list[str] = []
    for line in markdown.splitlines():
        stripped = line.strip()
        if stripped == "---":
            rendered_lines.append("<b>──────────</b>")
            continue
        if stripped.startswith("### "):
            line = stripped[4:].strip()
            if not (line.startswith("**") and line.endswith("**")):
                line = f"**{line}**"
        elif line.startswith("* "):
            line = f"• {line[2:]}"
        rendered_lines.append(_render_inline(line))
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

"""
services.acp_content_writing.export — AA-569: tenant-facing content_piece download (My Content).

Text export is always available (every channel — just `content_text` as-is, already citation-tag
-stripped by run_write_background()/quality_gates.py before persist, nothing further to do here).
HTML export is Blog-only: T9's blog prompt (AA-452, services/acp_content_writing/prompts.py) is
the only channel instructed to write real markdown (`## ` H2 sections, `## FAQ` with `**Q: .../
A:**` pairs) — every other channel's content_text is plain prose, so running it through a
markdown renderer would be a no-op at best and could mis-render a literal "#"/"*" the tenant
actually typed at worst. The router enforces this (400 for html on a non-blog piece), not this
module — this module only renders, it doesn't decide when rendering is appropriate.
"""
from __future__ import annotations

import html as html_escape

import markdown

_HTML_DOC_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{title}</title>
<style>
  body {{ font-family: Georgia, 'Times New Roman', serif; max-width: 680px; margin: 40px auto;
          padding: 0 20px; line-height: 1.65; color: #1F2933; }}
  h1, h2, h3 {{ font-family: -apple-system, 'Segoe UI', sans-serif; color: #1F2933; }}
  a {{ color: #B5791F; }}
</style>
</head>
<body>
{body}
</body>
</html>
"""


def render_content_text_to_html(content_text: str, *, title: str = "Content") -> str:
    """Converts a blog piece's markdown-flavored `content_text` into a standalone HTML document
    (not a bare fragment) — the export is a real, openable .html file, not a snippet meant to be
    inlined somewhere else."""
    body = markdown.markdown(content_text, extensions=["extra", "nl2br"])
    return _HTML_DOC_TEMPLATE.format(title=html_escape.escape(title), body=body)


__all__ = ["render_content_text_to_html"]

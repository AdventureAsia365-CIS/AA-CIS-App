"""AA-569 — services/acp_content_writing/export.py, the Blog-only markdown->HTML renderer used
by GET /v1/content-writing/pieces/{piece_id}/export?format=html."""
from services.acp_content_writing.export import render_content_text_to_html


class TestRenderContentTextToHtml:
    def test_h2_heading_rendered(self):
        html = render_content_text_to_html("## A Title\n\nSome body text.")
        assert "<h2>A Title</h2>" in html
        assert "<p>Some body text.</p>" in html

    def test_bold_rendered(self):
        html = render_content_text_to_html("**Q: How old?**\nA: Very old.")
        assert "<strong>Q: How old?</strong>" in html

    def test_plain_paragraphs_no_markdown_syntax(self):
        """Non-blog-shaped text (no ##/**) still renders as valid, readable HTML — the router
        gates format=html to the blog channel, but this function itself doesn't assume markdown
        syntax is present."""
        html = render_content_text_to_html("Just a plain sentence with no markdown at all.")
        assert "<p>Just a plain sentence with no markdown at all.</p>" in html

    def test_is_a_standalone_html_document(self):
        html = render_content_text_to_html("Body text.", title="My Post")
        assert html.strip().startswith("<!DOCTYPE html>")
        assert "<title>My Post</title>" in html
        assert "<meta charset=\"utf-8\">" in html

    def test_title_is_html_escaped(self):
        html = render_content_text_to_html("x", title="<script>alert(1)</script>")
        assert "<script>alert(1)</script>" not in html
        assert "&lt;script&gt;" in html

from app.tools.markup import extract_main_html_fragment, html_to_markdown


def test_extract_main_html_fragment_prefers_main_content_and_drops_chrome() -> None:
    html = """
    <html>
      <body>
        <header>
          <nav>Home Pricing Docs</nav>
        </header>
        <main>
          <h1>Enterprise Ticketing</h1>
          <p>Structured ticket IDs improve traceability and auditability.</p>
        </main>
        <footer>Subscribe to our newsletter</footer>
      </body>
    </html>
    """

    fragment = extract_main_html_fragment(html)

    assert "Enterprise Ticketing" in fragment
    assert "Structured ticket IDs improve traceability" in fragment
    assert "Home Pricing Docs" not in fragment
    assert "newsletter" not in fragment.lower()


def test_html_to_markdown_reduces_cookie_and_sidebar_boilerplate() -> None:
    html = """
    <html>
      <body>
        <div class="cookie-banner">Accept cookies</div>
        <aside class="sidebar">Related posts and ads</aside>
        <article>
          <h1>Risk Review</h1>
          <p>Operators need precise incident context.</p>
          <ul><li>Traceability</li><li>Auditability</li></ul>
        </article>
      </body>
    </html>
    """

    markdown = html_to_markdown(html)

    assert "Risk Review" in markdown
    assert "Operators need precise incident context." in markdown
    assert "Traceability" in markdown
    assert "Accept cookies" not in markdown
    assert "Related posts and ads" not in markdown


def test_extract_main_html_fragment_uses_content_id_container_when_main_tag_is_absent() -> None:
    html = """
    <html>
      <body>
        <div class="top-nav">Docs Pricing Blog</div>
        <div id="blog-content" class="blog-content-container">
          <div class="blog-description w-richtext">
            <p>Teams need better ticket integration workflows.</p>
            <p>Connected enterprise applications reduce response times.</p>
          </div>
        </div>
        <footer>Footer links</footer>
      </body>
    </html>
    """

    fragment = extract_main_html_fragment(html)

    assert "Teams need better ticket integration workflows." in fragment
    assert "Connected enterprise applications reduce response times." in fragment
    assert "Docs Pricing Blog" not in fragment
    assert "Footer links" not in fragment

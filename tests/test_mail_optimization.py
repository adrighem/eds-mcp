from eds_mcp.mail import extract_text_from_message, clean_html


def test_clean_html():
    html = """
    <html>
        <head><style>body { color: red; }</style></head>
        <body>
            <h1>Hello World</h1>
            <p>This is a <b>test</b>.</p>
            <br>
            <script>alert('bad');</script>
            <div>Another line</div>
            &nbsp;&nbsp;Spaces and &lt;entities&gt;
        </body>
    </html>
    """
    cleaned = clean_html(html)
    assert "Hello World" in cleaned
    assert "This is a test" in cleaned
    assert "Another line" in cleaned
    assert "Spaces and <entities>" in cleaned
    assert "color: red" not in cleaned
    assert "alert('bad')" not in cleaned
    assert "<script>" not in cleaned


def test_extract_text_from_multipart():
    raw = """From: sender@example.com
To: recipient@example.com
Subject: Test Multipart
Content-Type: multipart/alternative; boundary="boundary"

--boundary
Content-Type: text/plain; charset=utf-8

This is the plain text.
--boundary
Content-Type: text/html; charset=utf-8

<html><body><h1>This is HTML</h1></body></html>
--boundary--
"""
    extracted = extract_text_from_message(raw)
    assert "From: sender@example.com" in extracted
    assert "Subject: Test Multipart" in extracted
    assert "This is the plain text." in extracted
    assert "This is HTML" not in extracted


def test_extract_text_from_html_only():
    raw = """From: sender@example.com
Subject: Test HTML Only
Content-Type: text/html; charset=utf-8

<html><body><p>Just some <b>HTML</b> content.</p></body></html>
"""
    extracted = extract_text_from_message(raw)
    assert "Just some HTML content." in extracted


def test_extract_text_length_limit():
    long_text = "Word " * 5000
    raw = f"""From: sender@example.com
Subject: Long Email
Content-Type: text/plain; charset=utf-8

{long_text}
"""
    extracted = extract_text_from_message(raw)
    assert "[... content truncated due to length ...]" in extracted
    assert len(extracted) < 11000

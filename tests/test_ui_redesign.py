

def test_home_exposes_csrf_token_for_sysadmin_chat():
    from pathlib import Path

    html = Path("src/ai_hq/templates/home.html").read_text()

    assert (
        'name="csrf-token"' in html
        and 'content="{{ csrf_token }}"' in html
    ), (
        "SysAdmin Chat needs the authenticated session CSRF token "
        "exposed to JavaScript"
    )





def test_sysadmin_chat_is_fixed_drawer_with_close_control():
    """
    Regression: selecting SysAdmin must expose chat in a fixed drawer
    that is independent of the Operations Floor grid/scroll position.
    """
    from pathlib import Path
    import re

    html = Path("src/ai_hq/templates/home.html").read_text()
    css = Path("src/ai_hq/static/hq.css").read_text()
    js = Path("src/ai_hq/static/hq.js").read_text()

    assert 'id="sysadmin-chat-close"' in html, (
        "SysAdmin Chat drawer needs an explicit close control"
    )

    match = re.search(
        r"\.sysadmin-chat\s*\{(?P<body>.*?)\}",
        css,
        re.DOTALL,
    )
    assert match is not None, "Missing .sysadmin-chat CSS rule"

    body = match.group("body")

    assert re.search(r"position\s*:\s*fixed\s*;", body), (
        "SysAdmin Chat must be fixed to the viewport"
    )
    assert re.search(r"right\s*:\s*[^;]+;", body), (
        "SysAdmin Chat drawer must be anchored to the right"
    )
    assert re.search(r"z-index\s*:\s*\d+\s*;", body), (
        "SysAdmin Chat drawer must render above the Operations Floor"
    )

    assert 'getElementById("sysadmin-chat-close")' in js, (
        "SysAdmin Chat JavaScript must wire the close control"
    )
    assert "closeSysAdminChat" in js, (
        "SysAdmin Chat needs explicit close behaviour"
    )


def test_sysadmin_chat_renders_markdown_without_innerhtml():
    from pathlib import Path
    js = Path("src/ai_hq/static/hq.js").read_text()
    assert "renderMarkdown(body, content)" in js
    assert "body.innerHTML" not in js


def test_sysadmin_chat_normalizes_escaped_markdown():
    from pathlib import Path
    js = Path("src/ai_hq/static/hq.js").read_text()
    assert "content = content.replace" in js
    assert "renderMarkdown(body, content)" in js
    assert "body.innerHTML" not in js



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


def test_sysadmin_chat_spans_operations_floor_grid():
    """
    Regression: SysAdmin Chat is a direct child of the three-column
    .hq-shell grid. When opened it must span the shell instead of being
    auto-placed into an implicit row/column.
    """
    from pathlib import Path
    import re

    css = Path("src/ai_hq/static/hq.css").read_text()

    match = re.search(
        r"\.sysadmin-chat\s*\{(?P<body>.*?)\}",
        css,
        re.DOTALL,
    )

    assert match is not None, "Missing .sysadmin-chat CSS rule"

    body = match.group("body")

    assert re.search(
        r"grid-column\s*:\s*1\s*/\s*-1\s*;",
        body,
    ), (
        "SysAdmin Chat must explicitly span the full .hq-shell grid "
        "instead of relying on CSS grid auto-placement"
    )


def test_sysadmin_chat_spans_operations_floor_grid():
    """
    Regression: SysAdmin Chat is a direct child of the three-column
    .hq-shell grid. When opened it must span the shell instead of being
    auto-placed into an implicit row/column.
    """
    from pathlib import Path
    import re

    css = Path("src/ai_hq/static/hq.css").read_text()

    match = re.search(
        r"\.sysadmin-chat\s*\{(?P<body>.*?)\}",
        css,
        re.DOTALL,
    )

    assert match is not None, "Missing .sysadmin-chat CSS rule"

    body = match.group("body")

    assert re.search(
        r"grid-column\s*:\s*1\s*/\s*-1\s*;",
        body,
    ), (
        "SysAdmin Chat must explicitly span the full .hq-shell grid "
        "instead of relying on CSS grid auto-placement"
    )

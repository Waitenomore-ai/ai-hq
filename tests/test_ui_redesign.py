

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

from pathlib import Path

from ai_hq.code_changes.context import RepositoryContextProvider


def test_dripvid_phone_menu_request_surfaces_mobile_member_css(tmp_path: Path):
    css_dir = tmp_path / "public" / "css"
    css_dir.mkdir(parents=True)

    target = css_dir / "mobile-member.css"
    target.write_text(
        "@media(max-width:850px){.member-watch-page .sidebar{padding:1rem}.member-watch-page .sidebar nav{gap:1rem}.member-watch-page .sidebar nav a{padding:.82rem .9rem}}\n",
        encoding="utf-8",
    )

    for index in range(12):
        (css_dir / f"layout-{index}.css").write_text(
            ".menu { padding: 1rem; } .phone { gap: 1rem; }\n",
            encoding="utf-8",
        )

    provider = RepositoryContextProvider(
        repository="dripvid",
        source_path=tmp_path,
        max_files=12,
        max_chars_per_file=2000,
        max_total_chars=48000,
    )

    context = provider.build(
        instruction=(
            "DripVid: make the mobile menu slightly smaller on phones by "
            "reducing the spacing and padding only. Do not change desktop "
            "layout."
        )
    )

    paths = [item["path"] for item in context["files"]]
    assert "public/css/mobile-member.css" in paths

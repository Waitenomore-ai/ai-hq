from pathlib import Path


def test_ai_hq_nginx_route_strips_prefix_and_targets_localhost():
    text = Path("deploy/nginx-ai-hq-location.conf").read_text()
    assert "location = /ai-hq" in text
    assert "return 301 /ai-hq/;" in text
    assert "location /ai-hq/" in text
    assert "proxy_pass http://127.0.0.1:8090/;" in text
    assert "X-Forwarded-Prefix /ai-hq" in text
    for header in (
        "Host $host",
        "X-Real-IP $remote_addr",
        "X-Forwarded-For $proxy_add_x_forwarded_for",
        "X-Forwarded-Proto $scheme",
        "X-Forwarded-Host $host",
    ):
        assert header in text


def test_ai_hq_nginx_asset_does_not_change_dripvid_backend():
    text = Path("deploy/nginx-ai-hq-location.conf").read_text()
    assert "127.0.0.1:3000" not in text


def test_renderer_inserts_ai_hq_route_before_catch_all():
    text = Path("deploy/render-nginx.sh").read_text()
    assert "nginx-ai-hq-location.conf" in text
    assert "location / {" in text
    assert "candidate" in text.lower()
    assert "nginx -s reload" not in text
    assert "systemctl reload nginx" not in text

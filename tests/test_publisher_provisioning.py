from pathlib import Path


def test_publisher_token_installer_uses_private_root_owned_file_and_env_pointer():
    installer = Path("deploy/install-github-publisher-token.sh")

    assert installer.is_file()
    text = installer.read_text()
    assert "umask 077" in text
    assert "/etc/ai-hq/github-publisher.token" in text
    assert "read -r -s" in text
    assert "chmod 600" in text or "install -m 600" in text
    assert "AI_HQ_GITHUB_PUBLISH_TOKEN_SOURCE=/etc/ai-hq/github-publisher.token" in text
    assert "printf '%s\\n' \"$TOKEN\"" in text


def test_deployer_requires_secure_publisher_token_source_before_starting_release():
    text = Path("deploy/ai-hq-deploy").read_text()

    assert "AI_HQ_GITHUB_PUBLISH_TOKEN_SOURCE=/etc/ai-hq/github-publisher.token" in text
    assert "GitHub publisher token source is missing" in text
    assert "GitHub publisher token file must be a regular non-symlink file" in text
    assert "GitHub publisher token file permissions are too broad" in text
    assert "GitHub publisher token file is empty" in text

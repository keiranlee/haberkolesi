from pathlib import Path


def test_docker_context_excludes_secrets_and_local_state():
    ignored = {
        line.strip()
        for line in Path(".dockerignore").read_text().splitlines()
        if line.strip() and not line.startswith("#")
    }

    assert ".env" in ignored
    assert ".git" in ignored
    assert ".venv" in ignored
    assert "data" in ignored

from types import SimpleNamespace

import pytest

from check_mod_updates.config import LocalPatchError
from check_mod_updates import server


def configured_server(tmp_path, monkeypatch):
    patcher = tmp_path / "apply-local-fixes.py"
    patcher.write_text("#!/usr/bin/env python3\n", encoding="utf-8")
    monkeypatch.setattr(server, "BASE", tmp_path)
    monkeypatch.setattr(server, "LOCAL_FIXES", patcher)
    return patcher


def test_local_fixes_run_in_the_rootless_podman_user_namespace(tmp_path, monkeypatch, capsys):
    patcher = configured_server(tmp_path, monkeypatch)
    calls = []

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        return SimpleNamespace(returncode=10, stdout="changed\n", stderr="warning\n")

    monkeypatch.setattr(server.subprocess, "run", run)

    assert server.apply_local_fixes()
    assert calls == [(
        ["podman", "unshare", "python3", str(patcher)],
        {"cwd": tmp_path, "capture_output": True, "text": True},
    )]
    captured = capsys.readouterr()
    assert "changed" in captured.out
    assert "warning" in captured.err


def test_local_fixes_surface_podman_unshare_failures_with_exit_status(tmp_path, monkeypatch):
    configured_server(tmp_path, monkeypatch)
    monkeypatch.setattr(
        server.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=125, stdout="", stderr="unshare failed"),
    )

    with pytest.raises(LocalPatchError, match=r"podman unshare.*exit code 125"):
        server.apply_local_fixes()

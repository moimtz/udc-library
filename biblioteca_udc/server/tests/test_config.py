"""Listening address: a fixed IP, or the Tailscale address detected at start-up."""
import subprocess

import pytest

import config


def _fake_run(stdout, returncode=0):
    def run(*a, **k):
        return subprocess.CompletedProcess(a, returncode, stdout=stdout, stderr="")
    return run


def test_fixed_host(monkeypatch):
    monkeypatch.setattr(config, "HOST", "127.0.0.1")
    assert config.listen_host() == "127.0.0.1"


def test_tailscale_host(monkeypatch):
    monkeypatch.setattr(config, "HOST", "tailscale")
    monkeypatch.setattr(subprocess, "run", _fake_run("100.101.102.103\nfd7a:115c::1\n"))
    assert config.listen_host() == "100.101.102.103"


def test_tailscale_not_connected(monkeypatch):
    monkeypatch.setattr(config, "HOST", "tailscale")
    monkeypatch.setattr(subprocess, "run", _fake_run("", returncode=1))
    with pytest.raises(RuntimeError, match="not connected"):
        config.listen_host()

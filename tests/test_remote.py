"""원격(SSH) 백엔드 — 명령 구성/설정/파싱 테스트 (실제 SSH 미사용)."""
from __future__ import annotations

import subprocess

import pytest

from pcmon import services
from pcmon.config import Config


def test_remote_config_default_empty():
    assert Config.from_dict({}).remote.host == ""


def test_remote_config_parsed():
    cfg = Config.from_dict({"remote": {"host": "keymedi1"}})
    assert cfg.remote.host == "keymedi1"


def test_run_local_passes_cmd_verbatim(monkeypatch):
    seen = {}

    def fake_run(cmd, **kw):
        seen["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, 0, stdout="ok", stderr="")

    monkeypatch.setattr(services.subprocess, "run", fake_run)
    assert services._run(["docker", "ps"]) == "ok"
    assert seen["cmd"] == ["docker", "ps"]


def test_run_remote_wraps_with_ssh_and_quotes(monkeypatch):
    seen = {}

    def fake_run(cmd, **kw):
        seen["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, 0, stdout="ok", stderr="")

    monkeypatch.setattr(services.subprocess, "run", fake_run)
    services._run(["docker", "stats", "--format", "{{.Name}}\t{{.CPUPerc}}"], host="keymedi1")
    cmd = seen["cmd"]
    assert cmd[0] == "ssh"
    assert "keymedi1" in cmd
    # 원격 명령은 마지막 단일 문자열, 탭/중괄호가 shlex 로 안전하게 인용됨
    remote = cmd[-1]
    assert remote.startswith("docker stats --format ")
    assert "{{.Name}}" in remote  # 포맷 보존


def test_run_remote_failure_returns_none(monkeypatch):
    def fake_run(cmd, **kw):
        return subprocess.CompletedProcess(cmd, 255, stdout="", stderr="conn refused")

    monkeypatch.setattr(services.subprocess, "run", fake_run)
    assert services._run(["docker", "ps"], host="x") is None


def test_remote_system_usage_parses_proc(monkeypatch):
    # /proc/stat + /proc/meminfo 모의 → 두 번째 호출에서 CPU% 산출
    sample = (
        "cpu  100 0 50 800 50 0 0 0 0 0\n"
        "MemTotal:       16000000 kB\n"
        "MemAvailable:    4000000 kB\n"
    )
    monkeypatch.setattr(services, "_run", lambda cmd, host="": sample)
    services._remote_cpu_cache.pop("h", None)
    u1 = services._remote_system_usage("h")           # prime
    assert u1.ram_percent == 75.0                     # (1 - 4M/16M)*100
    # 두 번째 샘플: idle 만 100 증가 → cpu 사용 0 근처
    sample2 = (
        "cpu  100 0 50 900 50 0 0 0 0 0\n"
        "MemTotal:       16000000 kB\n"
        "MemAvailable:    4000000 kB\n"
    )
    monkeypatch.setattr(services, "_run", lambda cmd, host="": sample2)
    u2 = services._remote_system_usage("h")
    assert 0.0 <= u2.cpu_percent <= 100.0


def test_remote_top_processes_parses_ps(monkeypatch):
    out = "open-design 0.5 17.8\nclaude 1.2 2.8\nsshd 0.0 0.1\n"
    monkeypatch.setattr(services, "_run", lambda cmd, host="": out)
    procs = services.remote_top_processes("h", count=5, exclude=["sshd"])
    names = [p.name for p in procs]
    assert "open-design" in names and "sshd" not in names
    assert procs[0].ram_percent == 17.8

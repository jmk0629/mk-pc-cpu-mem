"""MCP 도구 본체 — 순수 함수(딕셔너리 반환).

mcp 패키지 없이도 import/테스트 가능하도록 server.py 와 분리한다.
pcmon 코어(config/metrics/services/telegram_bot)를 그대로 재사용한다.
"""
from __future__ import annotations

from typing import Any

# pcmon 패키지를 재사용 (src 가 sys.path 에 있다는 전제 — pyproject 설정)
from pcmon import metrics, services
from pcmon.config import Config
from pcmon.telegram_bot import _command_allowed, _exec_command


def _cfg() -> Config:
    return Config.load()


def get_metrics() -> dict[str, Any]:
    cfg = _cfg()
    m = metrics.system_metrics()
    procs = metrics.top_processes(cfg.system_alert.top_process_count, cfg.exclude_services)
    return {
        "cpu_percent": m.cpu_percent,
        "ram_percent": m.ram_percent,
        "top_processes": [
            {"name": p.name, "cpu_percent": p.cpu_percent, "ram_percent": p.ram_percent} for p in procs
        ],
    }


def list_services() -> dict[str, Any]:
    cfg = _cfg()
    out = []
    for t in cfg.targets:
        u = services.target_usage(t)
        out.append({
            "name": t.name,
            "type": t.type,
            "cpu_percent": u.cpu_percent,
            "ram_percent": u.ram_percent,
            "available": u.available,
        })
    return {"services": out}


def restart_service(name: str) -> dict[str, Any]:
    cfg = _cfg()
    target = next((t for t in cfg.targets if t.name == name), None)
    if target is None:
        return {"ok": False, "detail": f"알 수 없는 서비스: {name}"}
    r = services.restart_target(target, cfg)
    return {"ok": r.ok, "detail": r.detail}


def run_command(command: str) -> dict[str, Any]:
    cfg = _cfg()
    if not cfg.control.allow_run_command:
        return {"ok": False, "detail": "control.allow_run_command=false 로 차단됨"}
    if not _command_allowed(command, cfg.control.command_allowlist):
        return {"ok": False, "detail": "command_allowlist 에 없는 명령"}
    return {"ok": True, "output": _exec_command(command)}

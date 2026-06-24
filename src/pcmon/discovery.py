"""감시 대상 자동 발견 (이미지의 'exclude 빼고 전부 감시' 동작).

docker 컨테이너 + systemd 서비스를 실행 중 목록에서 자동 수집하고,
config.exclude_services 에 걸리는 항목(OS 기본 서비스 등)을 제외해 Target 목록을 만든다.
명시적 config.targets 와 합쳐 사용한다(명시적 우선).

순수 파싱 함수(_filter)는 단위 테스트 가능하도록 부작용과 분리한다.
"""
from __future__ import annotations

import shutil
import subprocess

from .config import Config, Target

_CMD_TIMEOUT = 15


def discover(cfg: Config) -> list[Target]:
    """설정에 따라 docker/systemd 대상을 발견해 필터링한 Target 목록 반환."""
    targets: list[Target] = []
    if not cfg.discovery.enabled:
        return targets
    if cfg.discovery.docker:
        for name in _filter(_docker_names(), cfg.exclude_services):
            targets.append(Target(name=name, type="docker", match=name))
    if cfg.discovery.systemd:
        for unit in _filter(_systemd_units(), cfg.exclude_services):
            display = unit[:-len(".service")] if unit.endswith(".service") else unit
            targets.append(Target(name=display, type="systemd", match=unit))
    return targets


def _filter(names: list[str], exclude: list[str]) -> list[str]:
    """exclude 의 어떤 항목이 이름에 부분 일치하면 제외(대소문자 무시).

    예: exclude=['systemd'] 면 systemd-journald, systemd-logind … 전부 제외.
    .service 접미사는 매칭 시 무시.
    """
    ex = [e.lower() for e in exclude if e]
    out: list[str] = []
    for n in names:
        base = n[:-len(".service")] if n.endswith(".service") else n
        low = base.lower()
        if any(e in low for e in ex):
            continue
        out.append(n)
    return out


def _docker_names() -> list[str]:
    if not shutil.which("docker"):
        return []
    out = _run(["docker", "ps", "--format", "{{.Names}}"])
    return [l.strip() for l in out.splitlines() if l.strip()] if out else []


def _systemd_units() -> list[str]:
    if not shutil.which("systemctl"):
        return []
    out = _run([
        "systemctl", "list-units", "--type=service", "--state=running",
        "--no-legend", "--no-pager", "--plain",
    ])
    units: list[str] = []
    if out:
        for line in out.splitlines():
            parts = line.split()
            if parts and parts[0].endswith(".service"):
                units.append(parts[0])
    return units


def _run(cmd: list[str]) -> str | None:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=_CMD_TIMEOUT)
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return None
    return r.stdout.strip() if r.returncode == 0 else None

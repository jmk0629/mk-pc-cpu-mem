"""크로스플랫폼 서비스/타겟 제어 계층.

타겟 종류(type)별로 사용률 측정과 재시작 방법이 다르다:
  - docker  : `docker stats` / `docker restart`              (OS 무관, Docker 필요)
  - systemd : cgroup 메모리 + `systemctl restart`            (Linux 전용)
  - launchd : psutil 집계 + `launchctl kickstart -k`         (macOS 전용)
  - process : 이름 매칭 프로세스 psutil 집계 + SIGTERM 재기동  (OS 무관, 베스트에포트)

모든 외부 명령은 timeout 과 예외 가드를 둔다. 실패는 (None) 사용률 또는
RestartResult(ok=False) 로 표면화하고 절대 데몬을 죽이지 않는다.
"""
from __future__ import annotations

import platform
import shutil
import subprocess
import time
from dataclasses import dataclass

import psutil

from .config import Config, Target

_CMD_TIMEOUT = 20

# systemd CPU% 산출용 직전 샘플 캐시: unit -> (monotonic_ts, cpu_usage_nsec)
# CPUUsageNSec 는 누적값이라 두 시점 차분이 필요(psutil prime 과 동일 원리).
_systemd_cpu_cache: dict[str, tuple[float, int]] = {}


def current_platform() -> str:
    return platform.system()  # 'Linux' | 'Darwin' | 'Windows'


@dataclass
class Usage:
    cpu_percent: float
    ram_percent: float
    available: bool = True  # 대상을 찾지 못하면 False


@dataclass
class RestartResult:
    ok: bool
    detail: str


# ----------------------------------------------------------------------------
# 사용률 측정
# ----------------------------------------------------------------------------
def target_usage(target: Target) -> Usage:
    try:
        if target.type == "system":
            return _system_usage()
        if target.type == "docker":
            return _docker_usage(target.match)
        if target.type == "systemd":
            return _systemd_usage(target.match)
        return _process_usage(target.match)  # launchd/process 폴백
    except Exception:  # noqa: BLE001 — 측정 실패가 데몬을 죽이면 안 됨
        return Usage(0.0, 0.0, available=False)


def _systemd_usage(unit: str) -> Usage:
    """systemd 유닛의 cgroup 회계 기반 정확 측정(Linux 전용).

    RAM% = MemoryCurrent / 전체메모리.  CPU% = ΔCPUUsageNSec / (Δt · ncpu).
    첫 호출은 CPU 기준점만 잡고 0.0 반환(prime). 다음 주기부터 구간 평균.
    """
    if not shutil.which("systemctl"):
        return Usage(0.0, 0.0, available=False)
    out = _run(["systemctl", "show", unit, "-p", "MemoryCurrent", "-p", "CPUUsageNSec", "-p", "ActiveState"])
    if out is None:
        return Usage(0.0, 0.0, available=False)
    fields = dict(
        line.split("=", 1) for line in out.splitlines() if "=" in line
    )
    if fields.get("ActiveState") not in ("active", "activating", "reloading"):
        return Usage(0.0, 0.0, available=False)

    mem_bytes = _to_int(fields.get("MemoryCurrent"))
    total = psutil.virtual_memory().total or 1
    ram_pct = round(min(mem_bytes / total * 100.0, 100.0), 1) if mem_bytes >= 0 else 0.0

    cpu_nsec = _to_int(fields.get("CPUUsageNSec"))
    now = time.monotonic()
    ncpu = psutil.cpu_count() or 1
    cpu_pct = 0.0
    prev = _systemd_cpu_cache.get(unit)
    if prev and cpu_nsec >= 0:
        prev_t, prev_nsec = prev
        dt = now - prev_t
        if dt > 0 and cpu_nsec >= prev_nsec:
            cpu_pct = round(min((cpu_nsec - prev_nsec) / (dt * 1e9 * ncpu) * 100.0, 100.0), 1)
    if cpu_nsec >= 0:
        _systemd_cpu_cache[unit] = (now, cpu_nsec)
    return Usage(cpu_pct, ram_pct)


def _system_usage() -> Usage:
    """전체 PC 한 대를 하나의 감시 대상으로. macOS/리눅스 공통(psutil)."""
    cpu = psutil.cpu_percent(interval=0.5)
    ram = psutil.virtual_memory().percent
    return Usage(round(cpu, 1), round(ram, 1))


def _docker_usage(name: str) -> Usage:
    if not shutil.which("docker"):
        return Usage(0.0, 0.0, available=False)
    out = _run(
        ["docker", "stats", "--no-stream", "--format", "{{.Name}}\t{{.CPUPerc}}\t{{.MemPerc}}", name]
    )
    if out is None:
        return Usage(0.0, 0.0, available=False)
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) == 3 and parts[0] == name:
            return Usage(_pct(parts[1]), _pct(parts[2]))
    return Usage(0.0, 0.0, available=False)


def _process_usage(match: str) -> Usage:
    """이름/커맨드라인에 match 가 포함된 프로세스들을 합산.

    여러 프로세스(워커 등)면 합계 사용률을 낸다. 코어 수로 정규화해 0~100 유지.
    """
    needle = match.lower()
    total_cpu = 0.0
    total_ram = 0.0
    found = False
    for p in psutil.process_iter(["name", "cmdline"]):
        try:
            name = (p.info.get("name") or "")
            cmd = " ".join(p.info.get("cmdline") or [])
            if needle in name.lower() or needle in cmd.lower():
                found = True
                p.cpu_percent(None)
                total_ram += p.memory_percent()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    if not found:
        return Usage(0.0, 0.0, available=False)
    # CPU 는 prime 후 짧게 재측정해야 의미 있는 값이 나온다.
    cpu_count = psutil.cpu_count() or 1
    for p in psutil.process_iter(["name", "cmdline"]):
        try:
            name = (p.info.get("name") or "")
            cmd = " ".join(p.info.get("cmdline") or [])
            if needle in name.lower() or needle in cmd.lower():
                total_cpu += p.cpu_percent(None)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return Usage(round(min(total_cpu / cpu_count, 100.0), 1), round(min(total_ram, 100.0), 1))


# ----------------------------------------------------------------------------
# 재시작 / 재부팅
# ----------------------------------------------------------------------------
def restart_target(target: Target, cfg: Config) -> RestartResult:
    if not cfg.control.allow_service_restart:
        return RestartResult(False, "서비스 재시작이 설정에서 비활성화됨(control.allow_service_restart=false)")
    try:
        if target.type == "system":
            # 전체 PC 는 서비스 재시작 대상이 아님 — 재부팅은 /reboot 로만(게이트).
            return RestartResult(False, "전체 시스템은 재시작 대상이 아닙니다. 재부팅은 /reboot 를 사용하세요.")
        if target.type == "docker":
            return _restart_docker(target.match)
        if target.type == "systemd":
            return _restart_systemd(target.match)
        if target.type == "launchd":
            return _restart_launchd(target.match)
        return _restart_process(target.match)
    except Exception as e:  # noqa: BLE001
        return RestartResult(False, f"예외: {e}")


def _restart_docker(name: str) -> RestartResult:
    out = _run(["docker", "restart", name])
    return RestartResult(out is not None, out or "docker restart 실패")


def _restart_systemd(unit: str) -> RestartResult:
    out = _run(["systemctl", "restart", unit])
    return RestartResult(out is not None, "systemctl restart 완료" if out is not None else "실패")


def _restart_launchd(label: str) -> RestartResult:
    # 사용자 도메인 가정. 시스템 데몬이면 system/ 도메인으로 바꿔야 함.
    domain = f"gui/{_uid()}/{label}"
    out = _run(["launchctl", "kickstart", "-k", domain])
    return RestartResult(out is not None, "launchctl kickstart 완료" if out is not None else "실패")


def _restart_process(match: str) -> RestartResult:
    """매칭 프로세스에 SIGTERM. 감독자(systemd/launchd/docker)가 재기동한다는 전제."""
    needle = match.lower()
    killed = 0
    for p in psutil.process_iter(["name", "cmdline"]):
        try:
            name = (p.info.get("name") or "")
            cmd = " ".join(p.info.get("cmdline") or [])
            if needle in name.lower() or needle in cmd.lower():
                p.terminate()
                killed += 1
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return RestartResult(killed > 0, f"{killed}개 프로세스에 SIGTERM 전송" if killed else "대상 프로세스 없음")


def reboot_system(cfg: Config) -> RestartResult:
    if not cfg.control.allow_reboot:
        return RestartResult(False, "재부팅이 설정에서 비활성화됨(control.allow_reboot=false)")
    system = current_platform()
    if system == "Linux":
        cmd = ["systemctl", "reboot"] if shutil.which("systemctl") else ["reboot"]
    elif system == "Darwin":
        cmd = ["shutdown", "-r", "now"]
    else:
        return RestartResult(False, f"지원하지 않는 OS: {system}")
    out = _run(cmd)
    return RestartResult(out is not None, "재부팅 명령 실행" if out is not None else "재부팅 실패(권한?)")


# ----------------------------------------------------------------------------
# 내부 유틸
# ----------------------------------------------------------------------------
def _run(cmd: list[str]) -> str | None:
    """명령 실행 → stdout 문자열. 실패/타임아웃이면 None(가드)."""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=_CMD_TIMEOUT)
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return None
    if r.returncode != 0:
        return None
    return r.stdout.strip()


def _pct(s: str) -> float:
    try:
        return round(float(s.replace("%", "").strip()), 1)
    except ValueError:
        return 0.0


def _to_int(s: str | None) -> int:
    """systemctl 수치 파싱. 미설정은 '[not set]'/빈값 → -1(미가용 표시)."""
    if not s or not s.strip().isdigit():
        return -1
    return int(s.strip())


def _uid() -> int:
    import os

    return os.getuid() if hasattr(os, "getuid") else 0

"""크로스플랫폼 + 원격(SSH) 서비스/타겟 제어 계층.

타겟 종류(type)별로 사용률 측정과 재시작 방법이 다르다:
  - system  : 머신 전체 CPU/RAM (로컬 psutil / 원격 /proc)
  - docker  : `docker stats` / `docker restart`              (OS 무관, Docker 필요)
  - systemd : cgroup 회계 + `systemctl restart`              (Linux 전용)
  - launchd : psutil 집계 + `launchctl kickstart -k`         (macOS 전용, 로컬만)
  - process : 이름 매칭 프로세스 psutil 집계 + SIGTERM        (로컬만)

원격 감시: cfg.remote.host(SSH 별칭)가 설정되면 docker/systemd/system 명령을
`ssh <host>` 로 실행한다 → 현재 PC(예: Mac)에서 미니 PC를 감시. host="" 면 로컬.

모든 외부 명령은 timeout 과 예외 가드를 둔다. 실패는 Usage(available=False) 또는
RestartResult(ok=False) 로 표면화하고 절대 데몬을 죽이지 않는다.
"""
from __future__ import annotations

import platform
import shlex
import shutil
import subprocess
import time
from dataclasses import dataclass

import psutil

from .config import Config, Target
from .metrics import ProcessMetrics

_CMD_TIMEOUT = 20

# SSH 옵션: 비대화·짧은 타임아웃 + 연결 재사용(ControlPersist)으로 매 주기 재접속 비용 절감.
_SSH_OPTS = [
    "-o", "BatchMode=yes",
    "-o", "ConnectTimeout=8",
    "-o", "ControlMaster=auto",
    "-o", "ControlPersist=60s",
    "-o", "ControlPath=~/.ssh/cm-pcmon-%r@%h:%p",
]

# systemd CPU% 산출용 직전 샘플 캐시: "host:unit" -> (monotonic_ts, cpu_usage_nsec)
_systemd_cpu_cache: dict[str, tuple[float, int]] = {}
# 원격 system CPU% 산출용 /proc/stat jiffies 캐시: host -> (idle_all, total)
_remote_cpu_cache: dict[str, tuple[float, float]] = {}
# 원격 호스트 정적 정보 캐시: host -> (total_mem_bytes, ncpu)
_remote_sysinfo_cache: dict[str, tuple[int, int]] = {}


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
def target_usage(target: Target, host: str | None = None) -> Usage:
    # host 인자는 하위호환용. 기본은 target.host 사용(멀티호스트).
    host = target.host if host is None else host
    try:
        if target.type == "system":
            return _remote_system_usage(host) if host else _system_usage()
        if target.type == "docker":
            return _docker_usage(target.match, host)
        if target.type == "systemd":
            return _systemd_usage(target.match, host)
        if host:
            return Usage(0.0, 0.0, available=False)  # process/launchd 는 원격 미지원
        return _process_usage(target.match)
    except Exception:  # noqa: BLE001 — 측정 실패가 데몬을 죽이면 안 됨
        return Usage(0.0, 0.0, available=False)


def _systemd_usage(unit: str, host: str = "") -> Usage:
    """systemd 유닛의 cgroup 회계 기반 정확 측정(Linux 전용, 로컬/원격).

    RAM% = MemoryCurrent / 전체메모리.  CPU% = ΔCPUUsageNSec / (Δt · ncpu).
    첫 호출은 CPU 기준점만 잡고 0.0 반환(prime). 다음 주기부터 구간 평균.
    """
    if not _tool_ok("systemctl", host):
        return Usage(0.0, 0.0, available=False)
    out = _run(["systemctl", "show", unit, "-p", "MemoryCurrent", "-p", "CPUUsageNSec", "-p", "ActiveState"], host)
    if out is None:
        return Usage(0.0, 0.0, available=False)
    fields = dict(line.split("=", 1) for line in out.splitlines() if "=" in line)
    if fields.get("ActiveState") not in ("active", "activating", "reloading"):
        return Usage(0.0, 0.0, available=False)

    total, ncpu = _sysinfo(host)
    mem_bytes = _to_int(fields.get("MemoryCurrent"))
    ram_pct = round(min(mem_bytes / total * 100.0, 100.0), 1) if mem_bytes >= 0 else 0.0

    cpu_nsec = _to_int(fields.get("CPUUsageNSec"))
    now = time.monotonic()
    cpu_pct = 0.0
    key = f"{host}:{unit}"
    prev = _systemd_cpu_cache.get(key)
    if prev and cpu_nsec >= 0:
        prev_t, prev_nsec = prev
        dt = now - prev_t
        if dt > 0 and cpu_nsec >= prev_nsec:
            cpu_pct = round(min((cpu_nsec - prev_nsec) / (dt * 1e9 * ncpu) * 100.0, 100.0), 1)
    if cpu_nsec >= 0:
        _systemd_cpu_cache[key] = (now, cpu_nsec)
    return Usage(cpu_pct, ram_pct)


def _system_usage() -> Usage:
    """전체 PC 한 대를 하나의 감시 대상으로(로컬, psutil)."""
    cpu = psutil.cpu_percent(interval=0.5)
    ram = psutil.virtual_memory().percent
    return Usage(round(cpu, 1), round(ram, 1))


def _docker_usage(name: str, host: str = "") -> Usage:
    if not _tool_ok("docker", host):
        return Usage(0.0, 0.0, available=False)
    out = _run(
        ["docker", "stats", "--no-stream", "--format", "{{.Name}}\t{{.CPUPerc}}\t{{.MemPerc}}", name],
        host,
    )
    if out is None:
        return Usage(0.0, 0.0, available=False)
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) == 3 and parts[0] == name:
            return Usage(_pct(parts[1]), _pct(parts[2]))
    return Usage(0.0, 0.0, available=False)


def _process_usage(match: str) -> Usage:
    """이름/커맨드라인에 match 가 포함된 프로세스들을 합산(로컬 전용)."""
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
# 원격 시스템 메트릭 (현재 PC에서 미니 PC 감시용)
# ----------------------------------------------------------------------------
def remote_system_metrics(host: str) -> Usage:
    return _remote_system_usage(host)


def _remote_system_usage(host: str) -> Usage:
    """원격 호스트 전체 CPU/RAM. /proc/stat(두 시점 차분) + /proc/meminfo."""
    out = _run(["sh", "-c", "head -1 /proc/stat; cat /proc/meminfo"], host)
    if out is None:
        return Usage(0.0, 0.0, available=False)
    cpu_pct, ram_pct = 0.0, 0.0
    mem_total = mem_avail = 0
    for line in out.splitlines():
        if line.startswith("cpu "):
            vals = [float(x) for x in line.split()[1:]]
            idle_all = (vals[3] + vals[4]) if len(vals) > 4 else (vals[3] if len(vals) > 3 else 0.0)
            total = sum(vals)
            prev = _remote_cpu_cache.get(host)
            if prev:
                d_idle = idle_all - prev[0]
                d_total = total - prev[1]
                if d_total > 0:
                    cpu_pct = round(max(0.0, min((1 - d_idle / d_total) * 100.0, 100.0)), 1)
            _remote_cpu_cache[host] = (idle_all, total)
        elif line.startswith("MemTotal:"):
            mem_total = _to_int(line.split()[1])
        elif line.startswith("MemAvailable:"):
            mem_avail = _to_int(line.split()[1])
    if mem_total > 0 and mem_avail >= 0:
        ram_pct = round((1 - mem_avail / mem_total) * 100.0, 1)
    return Usage(cpu_pct, ram_pct)


def remote_top_processes(host: str, count: int, exclude: list[str] | None = None) -> list[ProcessMetrics]:
    """원격 호스트 자원 상위 프로세스. `ps` 로 수집."""
    ex = [e.lower() for e in (exclude or [])]
    out = _run(["sh", "-c", f"ps -eo comm,pcpu,pmem --sort=-pmem --no-headers | head -n {max(count * 3, count)}"], host)
    if out is None:
        return []
    results: list[ProcessMetrics] = []
    for line in out.splitlines():
        parts = line.split(None, 2)
        if len(parts) != 3:
            continue
        name, pcpu, pmem = parts
        if any(e and e in name.lower() for e in ex):
            continue
        results.append(ProcessMetrics(pid=0, name=name, cpu_percent=_pct(pcpu), ram_percent=_pct(pmem)))
        if len(results) >= count:
            break
    return results


# ----------------------------------------------------------------------------
# 재시작 / 재부팅
# ----------------------------------------------------------------------------
def restart_target(target: Target, cfg: Config) -> RestartResult:
    if not cfg.control.allow_service_restart:
        return RestartResult(False, "서비스 재시작이 설정에서 비활성화됨(control.allow_service_restart=false)")
    host = target.host or cfg.remote.host
    try:
        if target.type == "system":
            return RestartResult(False, "전체 시스템은 재시작 대상이 아닙니다. 재부팅은 /reboot 를 사용하세요.")
        if target.type == "docker":
            return _restart_docker(target.match, host)
        if target.type == "systemd":
            return _restart_systemd(target.match, host)
        if host:
            return RestartResult(False, "원격에서는 docker/systemd 만 재시작할 수 있습니다.")
        if target.type == "launchd":
            return _restart_launchd(target.match)
        return _restart_process(target.match)
    except Exception as e:  # noqa: BLE001
        return RestartResult(False, f"예외: {e}")


def _restart_docker(name: str, host: str = "") -> RestartResult:
    out = _run(["docker", "restart", name], host)
    return RestartResult(out is not None, out or "docker restart 실패")


def _restart_systemd(unit: str, host: str = "") -> RestartResult:
    out = _run(["systemctl", "restart", unit], host)
    if out is not None:
        return RestartResult(True, "systemctl restart 완료")
    hint = " (원격 시스템 서비스는 sudo 권한이 필요할 수 있음)" if host else ""
    return RestartResult(False, "systemctl restart 실패" + hint)


def _restart_launchd(label: str) -> RestartResult:
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
    host = cfg.remote.host
    if host:
        out = _run(["systemctl", "reboot"], host)
        return RestartResult(out is not None, "원격 재부팅 명령 실행" if out is not None else "원격 재부팅 실패(sudo 권한?)")
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
def _run(cmd: list[str], host: str = "") -> str | None:
    """명령 실행 → stdout. host 가 있으면 ssh 로 원격 실행. 실패/타임아웃이면 None.

    원격은 각 인자를 shlex.quote 로 안전하게 묶어 단일 문자열로 전달(원격 셸 word-split·
    메타문자 오해석 방지). docker 의 `{{.Name}}\\t...` 포맷 보존을 위해 필수.
    """
    if host:
        remote_cmd = " ".join(shlex.quote(a) for a in cmd)
        full = ["ssh", *_SSH_OPTS, host, remote_cmd]
    else:
        full = cmd
    try:
        r = subprocess.run(full, capture_output=True, text=True, timeout=_CMD_TIMEOUT)
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return None
    if r.returncode != 0:
        return None
    return r.stdout.strip()


def _tool_ok(tool: str, host: str) -> bool:
    """로컬은 which 로 확인. 원격은 실행으로 판단(없으면 _run 이 None)."""
    if host:
        return True
    return shutil.which(tool) is not None


def _sysinfo(host: str) -> tuple[int, int]:
    """(전체 메모리 bytes, 논리 CPU 수). 로컬은 psutil, 원격은 /proc(호스트별 캐시)."""
    if not host:
        return (psutil.virtual_memory().total or 1, psutil.cpu_count() or 1)
    cached = _remote_sysinfo_cache.get(host)
    if cached:
        return cached
    out = _run(["sh", "-c", "nproc; grep MemTotal /proc/meminfo"], host)
    total_bytes, ncpu = 1, 1
    if out:
        lines = out.splitlines()
        if lines and lines[0].strip().isdigit():
            ncpu = int(lines[0].strip())
        for line in lines:
            if line.startswith("MemTotal:"):
                total_bytes = _to_int(line.split()[1]) * 1024  # kB → bytes
    info = (max(total_bytes, 1), max(ncpu, 1))
    _remote_sysinfo_cache[host] = info
    return info


def _pct(s: str) -> float:
    try:
        return round(float(s.replace("%", "").strip()), 1)
    except ValueError:
        return 0.0


def _to_int(s: str | None) -> int:
    """수치 파싱. 미설정/비수치는 -1(미가용 표시)."""
    if not s or not s.strip().isdigit():
        return -1
    return int(s.strip())


def _uid() -> int:
    import os

    return os.getuid() if hasattr(os, "getuid") else 0

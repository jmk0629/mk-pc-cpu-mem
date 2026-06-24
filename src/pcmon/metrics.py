"""시스템/프로세스 자원 수집 (psutil 기반, 크로스플랫폼).

서비스(타겟)별 사용률은 services.py 가 담당. 여기서는 전체 시스템과
원인 프로세스 집계('시스템 경보' 용)만 다룬다.
"""
from __future__ import annotations

from dataclasses import dataclass

import psutil


@dataclass
class SystemMetrics:
    cpu_percent: float
    ram_percent: float


@dataclass
class ProcessMetrics:
    pid: int
    name: str
    cpu_percent: float
    ram_percent: float


# psutil.cpu_percent 는 첫 호출이 0.0 을 반환하므로 interval 로 한 번 측정한다.
def system_metrics(interval: float = 0.5) -> SystemMetrics:
    cpu = psutil.cpu_percent(interval=interval)
    ram = psutil.virtual_memory().percent
    return SystemMetrics(cpu_percent=round(cpu, 1), ram_percent=round(ram, 1))


def top_processes(count: int = 5, exclude: list[str] | None = None) -> list[ProcessMetrics]:
    """RAM 사용률 상위 프로세스. exclude 에 포함된 이름은 집계에서 제외.

    CPU% 는 두 시점 차분이 필요하므로 1패스 prime 후 짧게 측정한다.
    """
    exclude = [e.lower() for e in (exclude or [])]
    procs: list[psutil.Process] = []
    for p in psutil.process_iter(["name"]):
        try:
            p.cpu_percent(None)  # prime: 다음 호출이 구간 평균을 반환
            procs.append(p)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    results: list[ProcessMetrics] = []
    for p in procs:
        try:
            name = (p.info.get("name") or "").strip()
            if not name or _excluded(name, exclude):
                continue
            results.append(
                ProcessMetrics(
                    pid=p.pid,
                    name=name,
                    cpu_percent=round(p.cpu_percent(None), 1),
                    ram_percent=round(p.memory_percent(), 1),
                )
            )
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    results.sort(key=lambda m: (m.ram_percent, m.cpu_percent), reverse=True)
    return results[:count]


def _excluded(name: str, exclude_lower: list[str]) -> bool:
    n = name.lower()
    return any(ex and ex in n for ex in exclude_lower)

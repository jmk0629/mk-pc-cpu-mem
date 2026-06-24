"""monitor.py — 핵심 감시 데몬.

부팅 시 자동 시작 → 매 주기(기본 30s) CPU/RAM 수집 → 상태 머신으로
주의/위험/복구 알림 발송 → 전체 고부하 시 '시스템 경보' → heartbeat 갱신.
텔레그램 제어 봇(버튼/명령)을 별도 스레드로 함께 띄운다.
"""
from __future__ import annotations

import logging
import signal
import time
from pathlib import Path

from . import discovery, metrics, notifier as nf, services
from .config import Config, HostConfig, Target
from .notifier import Notifier, restart_buttons
from .state import Event, StateMachine
from .telegram_bot import TelegramBot

log = logging.getLogger("pcmon.monitor")


def _tid(t: Target) -> str:
    """타겟 고유 키(멀티호스트 충돌 방지). 콜백 데이터로도 사용."""
    return f"{t.host}|{t.name}"


def _label(t: Target) -> str:
    return f"{t.name} @{t.host}" if t.host else t.name


class Monitor:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.notifier = Notifier(cfg)
        self.state = StateMachine(cfg)
        self.targets: dict[str, Target] = {}
        self._last_discovery = 0.0
        self._next_gap = 0.0           # 다음 재발견까지 최소 간격(초)
        self._running = True
        self._sys_alerted: dict[str, bool] = {}   # host alias -> 경보중 여부
        self._refresh_targets(force=True)

    # ---- 타겟 구성(멀티호스트) ----
    def _refresh_targets(self, force: bool = False) -> None:
        """hosts 별로 system + 명시적 + (활성 시)자동발견 타겟을 병합. 주기적 재발견.

        원격 발견이 비면(예: 부팅 직후 네트워크 미준비) 다음 틱에 빨리 재시도하고,
        정상 발견되면 refresh_minutes 주기로 되돌린다.
        """
        now = time.monotonic()
        if not force and (now - self._last_discovery) < self._next_gap:
            return
        self._last_discovery = now
        merged: dict[str, Target] = {}
        any_disc_host = False
        disc_ok = True
        for h in self.cfg.hosts:
            if h.system:
                t = Target(name=h.name, type="system", match="", host=h.host)
                merged[_tid(t)] = t
            for t in h.targets:
                merged[_tid(t)] = t
            if h.discovery:
                any_disc_host = True
                try:
                    found = discovery.discover_for(self.cfg, h.host)
                except Exception as e:  # noqa: BLE001 — 발견 실패가 데몬을 죽이면 안 됨
                    log.warning("자동 발견 실패(%s): %s", h.host or "local", e)
                    found = []
                if not found:
                    disc_ok = False
                for t in found:
                    merged.setdefault(_tid(t), t)
        # 발견 실패(콜드스타트 등)면 다음 틱에 빨리 재시도, 정상이면 5분 주기로.
        retry_soon = any_disc_host and not disc_ok
        self._next_gap = (max(self.cfg.timing.check_interval_seconds, 15)
                          if retry_soon else self.cfg.discovery.refresh_minutes * 60)
        if set(merged) != set(self.targets):
            log.info("감시 대상 %d개: %s", len(merged), ", ".join(_label(t) for t in merged.values()))
        self.targets = merged

    # ---- Actions 프로토콜 구현 (텔레그램 봇이 호출) ----
    def restart(self, key: str) -> str:
        target = self.targets.get(key) or self._find_by_name(key)
        if target is None:
            return f"❌ 알 수 없는 서비스: {key}"
        result = services.restart_target(target, self.cfg)
        label = _label(target)
        if result.ok:
            self.state.acknowledge_restart(_tid(target))
            return nf.restart_done_message(label)
        return f"❌ {label} 재시작 실패: {result.detail}"

    def ignore(self, key: str) -> None:
        if key in self.targets:
            self.state.snooze(key)

    def reboot(self) -> str:
        result = services.reboot_system(self.cfg)
        return "✅ 재부팅 명령 실행" if result.ok else f"❌ 재부팅 실패: {result.detail}"

    def _find_by_name(self, name: str) -> Target | None:
        return next((t for t in self.targets.values() if t.name == name), None)

    # ---- 호스트별 시스템 메트릭 ----
    def _hosts(self) -> list[HostConfig]:
        return self.cfg.hosts

    def _sys_metrics_for(self, host: str):
        return services.remote_system_metrics(host) if host else metrics.system_metrics()

    def _top_for(self, host: str):
        n = self.cfg.system_alert.top_process_count
        if host:
            return services.remote_top_processes(host, n, self.cfg.exclude_services)
        return metrics.top_processes(n, self.cfg.exclude_services)

    def status_text(self) -> str:
        lines = ["🖥 <b>현재 상태</b>"]
        for h in self._hosts():
            m = self._sys_metrics_for(h.host)
            lines.append(f"  • {h.name}: CPU {m.cpu_percent}% / RAM {m.ram_percent}%")
        return "\n".join(lines)

    def top_text(self) -> str:
        lines = ["<b>자원 상위 프로세스</b>"]
        for h in self._hosts():
            lines.append(f"<b>{h.name}</b>")
            for p in self._top_for(h.host):
                lines.append(f"  • {p.name}: CPU {p.cpu_percent}% / RAM {p.ram_percent}%")
        return "\n".join(lines)

    def services_text(self) -> str:
        if not self.targets:
            return "감시 대상 서비스가 없습니다(config.hosts / discovery)."
        lines = ["<b>감시 대상 서비스</b>"]
        for t in self.targets.values():
            u = services.target_usage(t)
            tag = "" if u.available else " (대상 없음)"
            lines.append(f"  • {_label(t)} [{t.type}]: CPU {u.cpu_percent}% / RAM {u.ram_percent}%{tag}")
        return "\n".join(lines)

    # ---- 메인 루프 ----
    def run(self) -> None:
        logging.info("monitor 시작 (platform=%s)", services.current_platform())
        bot = TelegramBot(self.cfg, self.notifier, self)
        bot.start()
        self.notifier.send(nf.startup_message())

        signal.signal(signal.SIGTERM, self._on_signal)
        signal.signal(signal.SIGINT, self._on_signal)

        interval = self.cfg.timing.check_interval_seconds
        while self._running:
            try:
                self._tick()
            except Exception as e:  # noqa: BLE001 — 한 주기 실패가 데몬을 죽이면 안 됨
                log.exception("tick 실패: %s", e)
            self._write_heartbeat()
            time.sleep(interval)
        bot.stop()
        log.info("monitor 종료")

    def _tick(self) -> None:
        # 0) 주기적 재발견(새 컨테이너/서비스 반영)
        self._refresh_targets()
        # 1) 타겟별 감시 (각 타겟의 host 로 로컬/원격 측정)
        for tid, target in list(self.targets.items()):
            u = services.target_usage(target)
            if not u.available:
                continue
            event = self.state.update(tid, u.cpu_percent, u.ram_percent)
            self._emit(target, tid, event, u.cpu_percent, u.ram_percent)

        # 2) 호스트별 전체 고부하 '시스템 경보'
        if self.cfg.system_alert.enabled:
            self._check_system_alert()

    def _emit(self, target: Target, tid: str, event: Event, cpu: float, ram: float) -> None:
        tm = self.cfg.timing
        label = _label(target)
        if event == Event.WARN_ALERT:
            self.notifier.send(nf.warn_message(label, cpu, ram, tm.alert_minutes))
        elif event == Event.DANGER_PROMPT:
            self.notifier.send(nf.danger_message(label, cpu, ram, tm.restart_minutes), restart_buttons(tid))
        elif event == Event.RECOVERY:
            self.notifier.send(nf.recovery_message(label, cpu, ram))

    def _check_system_alert(self) -> None:
        th = self.cfg.thresholds
        for h in self._hosts():
            m = self._sys_metrics_for(h.host)
            over = m.cpu_percent >= th.cpu_percent or m.ram_percent >= th.ram_percent
            if over and not self._sys_alerted.get(h.host):
                procs = self._top_for(h.host)
                suffix = f" @{h.host}" if h.host else ""
                self.notifier.send(nf.system_alert_message(m.cpu_percent, m.ram_percent, procs) +
                                   (f"\n(host: {h.name}{suffix})"))
                self._sys_alerted[h.host] = True
            elif not over:
                self._sys_alerted[h.host] = False

    def _write_heartbeat(self) -> None:
        try:
            Path(self.cfg.watchdog.heartbeat_path).write_text(str(time.time()), encoding="utf-8")
        except OSError as e:
            log.warning("heartbeat 기록 실패: %s", e)

    def _on_signal(self, *_a) -> None:
        self._running = False


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    cfg = Config.load()
    Monitor(cfg).run()


if __name__ == "__main__":
    main()

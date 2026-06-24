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

import time

from . import discovery, metrics, notifier as nf, services
from .config import Config, Target
from .notifier import Notifier, restart_buttons
from .state import Event, StateMachine
from .telegram_bot import TelegramBot

log = logging.getLogger("pcmon.monitor")


class Monitor:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.notifier = Notifier(cfg)
        self.state = StateMachine(cfg)
        self._explicit: dict[str, Target] = {t.name: t for t in cfg.targets}
        self.targets: dict[str, Target] = dict(self._explicit)
        self._last_discovery = 0.0
        self._running = True
        self._sys_alerted = False
        self._refresh_targets(force=True)

    def _refresh_targets(self, force: bool = False) -> None:
        """명시적 타겟 + (활성화 시) 자동 발견 타겟 병합. 주기적으로 재발견."""
        if not self.cfg.discovery.enabled:
            return
        now = time.monotonic()
        if not force and (now - self._last_discovery) < self.cfg.discovery.refresh_minutes * 60:
            return
        self._last_discovery = now
        merged = dict(self._explicit)  # 명시적 타겟 우선
        try:
            for t in discovery.discover(self.cfg):
                merged.setdefault(t.name, t)
        except Exception as e:  # noqa: BLE001 — 발견 실패가 데몬을 죽이면 안 됨
            log.warning("자동 발견 실패: %s", e)
        if set(merged) != set(self.targets):
            log.info("감시 대상 %d개: %s", len(merged), ", ".join(sorted(merged)))
        self.targets = merged

    # ---- Actions 프로토콜 구현 (텔레그램 봇이 호출) ----
    def restart(self, name: str) -> str:
        target = self.targets.get(name)
        if target is None:
            return f"❌ 알 수 없는 서비스: {name}"
        result = services.restart_target(target, self.cfg)
        if result.ok:
            self.state.acknowledge_restart(name)
            return nf.restart_done_message(name)
        return f"❌ {name} 재시작 실패: {result.detail}"

    def ignore(self, name: str) -> None:
        if name in self.targets:
            self.state.snooze(name)

    def reboot(self) -> str:
        result = services.reboot_system(self.cfg)
        return "✅ 재부팅 명령 실행" if result.ok else f"❌ 재부팅 실패: {result.detail}"

    def status_text(self) -> str:
        m = metrics.system_metrics()
        return f"🖥 <b>현재 상태</b>\n전체 CPU: {m.cpu_percent}% / RAM: {m.ram_percent}%"

    def top_text(self) -> str:
        procs = metrics.top_processes(self.cfg.system_alert.top_process_count, self.cfg.exclude_services)
        lines = ["<b>자원 상위 프로세스</b>"]
        for p in procs:
            lines.append(f"  • {p.name}: CPU {p.cpu_percent}% / RAM {p.ram_percent}%")
        return "\n".join(lines)

    def services_text(self) -> str:
        if not self.targets:
            return "감시 대상 서비스가 없습니다(config.targets)."
        lines = ["<b>감시 대상 서비스</b>"]
        for name, t in self.targets.items():
            u = services.target_usage(t)
            tag = "" if u.available else " (대상 없음)"
            lines.append(f"  • {name} [{t.type}]: CPU {u.cpu_percent}% / RAM {u.ram_percent}%{tag}")
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
        # 1) 타겟별 감시
        for name, target in list(self.targets.items()):
            u = services.target_usage(target)
            if not u.available:
                continue
            event = self.state.update(name, u.cpu_percent, u.ram_percent)
            self._emit(name, event, u.cpu_percent, u.ram_percent)

        # 2) 전체 고부하 '시스템 경보'
        if self.cfg.system_alert.enabled:
            self._check_system_alert()

    def _emit(self, name: str, event: Event, cpu: float, ram: float) -> None:
        tm = self.cfg.timing
        if event == Event.WARN_ALERT:
            self.notifier.send(nf.warn_message(name, cpu, ram, tm.alert_minutes))
        elif event == Event.DANGER_PROMPT:
            self.notifier.send(nf.danger_message(name, cpu, ram, tm.restart_minutes), restart_buttons(name))
        elif event == Event.RECOVERY:
            self.notifier.send(nf.recovery_message(name, cpu, ram))

    def _check_system_alert(self) -> None:
        m = metrics.system_metrics()
        over = m.cpu_percent >= self.cfg.thresholds.cpu_percent or m.ram_percent >= self.cfg.thresholds.ram_percent
        if over and not self._sys_alerted:
            procs = metrics.top_processes(self.cfg.system_alert.top_process_count, self.cfg.exclude_services)
            self.notifier.send(nf.system_alert_message(m.cpu_percent, m.ram_percent, procs))
            self._sys_alerted = True
        elif not over:
            self._sys_alerted = False

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

"""watchdog.py — 감시 데몬(monitor) 먹통 감지 안전장치.

systemd .timer / launchd StartInterval 로 주기 실행된다(데몬 아님, 1회 실행 후 종료).
heartbeat 파일이 max_age_minutes 이상 미갱신이면 '긴급' 알림을 발송하고,
watchdog.allow_reboot=true 면 재부팅 버튼을 함께 보낸다.
"""
from __future__ import annotations

import logging
import sys
import time
from pathlib import Path

from .config import Config
from .notifier import Notifier, reboot_buttons, watchdog_emergency_message

log = logging.getLogger("pcmon.watchdog")


def heartbeat_age_minutes(path: str, now: float | None = None) -> float | None:
    """heartbeat 파일 경과(분). 없으면 None."""
    p = Path(path)
    if not p.exists():
        return None
    now = time.time() if now is None else now
    try:
        ts = float(p.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        ts = p.stat().st_mtime
    return max(0.0, (now - ts) / 60.0)


def check(cfg: Config) -> bool:
    """1회 점검. 이상(먹통)이면 True 반환."""
    age = heartbeat_age_minutes(cfg.watchdog.heartbeat_path)
    notifier = Notifier(cfg)
    if age is None:
        log.warning("heartbeat 파일 없음: %s", cfg.watchdog.heartbeat_path)
        notifier.send(
            "🚨 <b>[긴급] heartbeat 파일 없음</b>\nmonitor 가 시작되지 않았을 수 있습니다.",
            reboot_buttons() if cfg.watchdog.allow_reboot else None,
        )
        return True
    if age >= cfg.watchdog.max_age_minutes:
        log.warning("heartbeat 만료: %.1f분", age)
        notifier.send(
            watchdog_emergency_message(age),
            reboot_buttons() if cfg.watchdog.allow_reboot else None,
        )
        return True
    log.info("heartbeat 정상: %.1f분 전 갱신", age)
    return False


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    cfg = Config.load()
    stale = check(cfg)
    sys.exit(1 if stale else 0)


if __name__ == "__main__":
    main()

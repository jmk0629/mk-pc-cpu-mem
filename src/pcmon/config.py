"""config.yaml 로드 + 환경변수 오버라이드 + 구조화된 dataclass.

코드 수정 없이 config.yaml 만 편집하면 동작이 바뀐다(이미지의 설계 의도).
민감값(토큰)은 환경변수 PCMON_TELEGRAM_TOKEN 으로 주입 가능하며, 파일값보다 우선한다.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class TelegramConfig:
    token: str = ""
    chat_ids: list[int] = field(default_factory=list)
    allowed_user_ids: list[int] = field(default_factory=list)

    def is_allowed(self, user_id: int) -> bool:
        """버튼/명령 실행 권한 게이트. allowed_user_ids 가 비면 chat_ids 로 폴백."""
        allow = self.allowed_user_ids or self.chat_ids
        return user_id in allow


@dataclass
class Thresholds:
    cpu_percent: float = 80.0
    ram_percent: float = 80.0


@dataclass
class Timing:
    check_interval_seconds: int = 30
    alert_minutes: int = 5
    restart_minutes: int = 20
    response_timeout_minutes: int = 10
    snooze_minutes: int = 10
    recovery_minutes: int = 1


@dataclass
class WatchdogConfig:
    heartbeat_path: str = "/tmp/pcmon-heartbeat"
    max_age_minutes: int = 5
    allow_reboot: bool = False


@dataclass
class ControlConfig:
    allow_service_restart: bool = True
    allow_reboot: bool = False
    allow_run_command: bool = False
    command_allowlist: list[str] = field(default_factory=list)


@dataclass
class Target:
    name: str
    type: str  # docker | systemd | launchd | process
    match: str


@dataclass
class SystemAlertConfig:
    enabled: bool = True
    top_process_count: int = 5


@dataclass
class Config:
    telegram: TelegramConfig = field(default_factory=TelegramConfig)
    thresholds: Thresholds = field(default_factory=Thresholds)
    timing: Timing = field(default_factory=Timing)
    watchdog: WatchdogConfig = field(default_factory=WatchdogConfig)
    control: ControlConfig = field(default_factory=ControlConfig)
    targets: list[Target] = field(default_factory=list)
    exclude_services: list[str] = field(default_factory=list)
    system_alert: SystemAlertConfig = field(default_factory=SystemAlertConfig)

    # ---- 로드 ----
    @classmethod
    def load(cls, path: str | os.PathLike[str] | None = None) -> "Config":
        data: dict[str, Any] = {}
        resolved = _resolve_path(path)
        if resolved and resolved.exists():
            with resolved.open("r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
        return cls.from_dict(data)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Config":
        tg = data.get("telegram", {}) or {}
        telegram = TelegramConfig(
            token=os.environ.get("PCMON_TELEGRAM_TOKEN", tg.get("token", "")),
            chat_ids=[int(x) for x in (tg.get("chat_ids") or []) if int(x) != 0],
            allowed_user_ids=[int(x) for x in (tg.get("allowed_user_ids") or [])],
        )
        thresholds = Thresholds(**_subset(data.get("thresholds"), Thresholds))
        timing = Timing(**_subset(data.get("timing"), Timing))
        watchdog = WatchdogConfig(**_subset(data.get("watchdog"), WatchdogConfig))
        control = ControlConfig(**_subset(data.get("control"), ControlConfig))
        system_alert = SystemAlertConfig(**_subset(data.get("system_alert"), SystemAlertConfig))
        targets = [
            Target(name=str(t["name"]), type=str(t.get("type", "process")), match=str(t["match"]))
            for t in (data.get("targets") or [])
        ]
        return cls(
            telegram=telegram,
            thresholds=thresholds,
            timing=timing,
            watchdog=watchdog,
            control=control,
            targets=targets,
            exclude_services=[str(s) for s in (data.get("exclude_services") or [])],
            system_alert=system_alert,
        )


def _subset(raw: dict[str, Any] | None, dc_type: type) -> dict[str, Any]:
    """dataclass 필드에 존재하는 키만 추려 미지의 키로 인한 TypeError 방지."""
    if not raw:
        return {}
    valid = {f for f in dc_type.__dataclass_fields__}  # type: ignore[attr-defined]
    return {k: v for k, v in raw.items() if k in valid}


def _resolve_path(path: str | os.PathLike[str] | None) -> Path | None:
    if path:
        return Path(path)
    env = os.environ.get("PCMON_CONFIG")
    if env:
        return Path(env)
    # 우선순위: 현재 디렉터리 → /opt/pc-monitor → 패키지 루트
    candidates = [
        Path.cwd() / "config.yaml",
        Path("/opt/pc-monitor/config.yaml"),
        Path(__file__).resolve().parents[2] / "config.yaml",
    ]
    for c in candidates:
        if c.exists():
            return c
    return None

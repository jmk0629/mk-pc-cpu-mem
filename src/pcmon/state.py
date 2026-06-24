"""타겟별 알림 상태 머신 (이미지 '시스템 동작 흐름' 구현).

흐름:
  정상 → (임계값 초과 alert_minutes 지속) → 주의(WARN) 알림 1회
       → (초과가 restart_minutes 지속)    → 위험(DANGER) 재시작 질문
       → 사용자가 '무시' → snooze_minutes 스누즈 후 재질문
       → 임계값 이하 recovery_minutes 유지 → 복구(RECOVERY) 알림, 정상 복귀

시간은 now() 를 주입받아 테스트 가능하게 한다(실시간 sleep 불필요).
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum

from .config import Config


class Level(str, Enum):
    NORMAL = "normal"
    WARN = "warn"
    DANGER = "danger"


class Event(str, Enum):
    NONE = "none"
    WARN_ALERT = "warn_alert"        # ⚠️ 주의 알림
    DANGER_PROMPT = "danger_prompt"  # 🔴 재시작 질문(버튼)
    RECOVERY = "recovery"            # ✅ 복구 알림


@dataclass
class TargetState:
    breach_since: float | None = None   # 임계값 초과 시작 시각
    recover_since: float | None = None  # 임계값 이하 복귀 시작 시각
    level: Level = Level.NORMAL
    warn_sent: bool = False
    danger_prompt_at: float | None = None  # 마지막 위험 질문 시각(스누즈 기준)
    snooze_until: float | None = None      # '무시' 시 이 시각까지 재질문 보류
    last_cpu: float = 0.0
    last_ram: float = 0.0


@dataclass
class StateMachine:
    cfg: Config
    now: callable = field(default=time.monotonic)
    states: dict[str, TargetState] = field(default_factory=dict)

    def _state(self, name: str) -> TargetState:
        return self.states.setdefault(name, TargetState())

    def _over_threshold(self, cpu: float, ram: float) -> bool:
        return cpu >= self.cfg.thresholds.cpu_percent or ram >= self.cfg.thresholds.ram_percent

    def update(self, name: str, cpu: float, ram: float) -> Event:
        """한 주기의 측정값을 반영하고 발생한 이벤트(최대 1개)를 반환."""
        st = self._state(name)
        st.last_cpu, st.last_ram = cpu, ram
        t = self.now()
        tm = self.cfg.timing

        if self._over_threshold(cpu, ram):
            st.recover_since = None
            if st.breach_since is None:
                st.breach_since = t
            elapsed_min = (t - st.breach_since) / 60.0

            # 위험 단계: restart_minutes 이상 지속 → 재시작 질문(스누즈 만료 시 재질문)
            if elapsed_min >= tm.restart_minutes:
                if st.snooze_until is not None and t < st.snooze_until:
                    return Event.NONE
                # 이미 위험 질문을 보냈고 응답 타임아웃 안 지났으면 보류
                if st.danger_prompt_at is not None:
                    waited = (t - st.danger_prompt_at) / 60.0
                    if waited < tm.response_timeout_minutes:
                        return Event.NONE
                st.level = Level.DANGER
                st.danger_prompt_at = t
                st.snooze_until = None
                return Event.DANGER_PROMPT

            # 주의 단계: alert_minutes 이상 지속 → 1회 알림
            if elapsed_min >= tm.alert_minutes and not st.warn_sent:
                st.level = Level.WARN
                st.warn_sent = True
                return Event.WARN_ALERT
            return Event.NONE

        # 임계값 이하 — 복구 판정
        st.breach_since = None
        if st.level == Level.NORMAL:
            return Event.NONE
        if st.recover_since is None:
            st.recover_since = t
        if (t - st.recover_since) / 60.0 >= tm.recovery_minutes:
            self.states[name] = TargetState(last_cpu=cpu, last_ram=ram)  # 리셋
            return Event.RECOVERY
        return Event.NONE

    def snooze(self, name: str) -> None:
        """'무시' 버튼 처리 — snooze_minutes 후 재질문."""
        st = self._state(name)
        st.snooze_until = self.now() + self.cfg.timing.snooze_minutes * 60.0
        st.danger_prompt_at = None

    def acknowledge_restart(self, name: str) -> None:
        """'재시작' 실행 후 상태 초기화(복구 대기)."""
        st = self._state(name)
        st.breach_since = None
        st.warn_sent = False
        st.danger_prompt_at = None
        st.snooze_until = None
        st.level = Level.NORMAL

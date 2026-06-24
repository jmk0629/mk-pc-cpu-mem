"""상태 머신(정상→주의→위험→복구, 스누즈) 단위 테스트.

시간을 주입(fake clock)해 실시간 sleep 없이 분 단위 전이를 검증한다.
"""
from __future__ import annotations

from pcmon.config import Config
from pcmon.state import Event, Level, StateMachine


class Clock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t

    def advance_min(self, m: float) -> None:
        self.t += m * 60.0


def _cfg() -> Config:
    return Config.from_dict({
        "thresholds": {"cpu_percent": 80, "ram_percent": 80},
        "timing": {
            "alert_minutes": 5,
            "restart_minutes": 20,
            "response_timeout_minutes": 10,
            "snooze_minutes": 10,
            "recovery_minutes": 1,
        },
    })


def test_warn_after_alert_minutes():
    clk = Clock()
    sm = StateMachine(_cfg(), now=clk)
    assert sm.update("svc", 95, 30) == Event.NONE  # 막 초과 시작
    clk.advance_min(4)
    assert sm.update("svc", 95, 30) == Event.NONE  # 아직 5분 미만
    clk.advance_min(1.1)
    assert sm.update("svc", 95, 30) == Event.WARN_ALERT  # 5분 경과
    # 주의는 1회만
    assert sm.update("svc", 95, 30) == Event.NONE


def test_danger_prompt_after_restart_minutes():
    clk = Clock()
    sm = StateMachine(_cfg(), now=clk)
    sm.update("svc", 95, 30)
    clk.advance_min(6)
    assert sm.update("svc", 95, 30) == Event.WARN_ALERT
    clk.advance_min(15)  # 총 21분
    assert sm.update("svc", 95, 30) == Event.DANGER_PROMPT
    assert sm.states["svc"].level == Level.DANGER


def test_ignore_snoozes_then_reprompts():
    clk = Clock()
    sm = StateMachine(_cfg(), now=clk)
    sm.update("svc", 95, 30)
    clk.advance_min(21)
    assert sm.update("svc", 95, 30) == Event.DANGER_PROMPT
    sm.snooze("svc")  # 사용자가 '무시'
    clk.advance_min(5)
    assert sm.update("svc", 95, 30) == Event.NONE  # 스누즈 중
    clk.advance_min(6)  # 스누즈 10분 경과
    assert sm.update("svc", 95, 30) == Event.DANGER_PROMPT  # 재질문


def test_recovery():
    clk = Clock()
    sm = StateMachine(_cfg(), now=clk)
    sm.update("svc", 95, 30)
    clk.advance_min(6)
    sm.update("svc", 95, 30)  # WARN
    # 임계값 이하로 복귀
    assert sm.update("svc", 10, 10) == Event.NONE  # recover_since 시작
    clk.advance_min(1.1)
    assert sm.update("svc", 10, 10) == Event.RECOVERY
    assert sm.states["svc"].level == Level.NORMAL


def test_threshold_uses_either_cpu_or_ram():
    sm = StateMachine(_cfg())
    # CPU 정상, RAM 초과 → 초과로 간주
    assert sm._over_threshold(10, 90) is True
    assert sm._over_threshold(90, 10) is True
    assert sm._over_threshold(10, 10) is False

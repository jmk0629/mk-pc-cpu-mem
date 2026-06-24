"""Telegram Bot API 송신 + 알림 메시지 빌더.

이미지의 알림 종류/문구를 그대로 구현:
  🟢 시작 · ⚠️ 주의/시스템경보 · 🔴 위험(버튼) · ✅ 복구 · 🚨 긴급(watchdog)
토큰이 없으면 send_* 는 조용히 no-op(테스트/오프라인 안전).
"""
from __future__ import annotations

import logging
from typing import Any

import requests

from .config import Config
from .metrics import ProcessMetrics

log = logging.getLogger("pcmon.notifier")
_API = "https://api.telegram.org/bot{token}/{method}"
_TIMEOUT = 15


class Notifier:
    def __init__(self, cfg: Config):
        self.cfg = cfg

    @property
    def enabled(self) -> bool:
        return bool(self.cfg.telegram.token) and bool(self.cfg.telegram.chat_ids)

    # ---- 저수준 ----
    def _call(self, method: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        if not self.cfg.telegram.token:
            log.debug("telegram token 없음 — %s no-op", method)
            return None
        url = _API.format(token=self.cfg.telegram.token, method=method)
        try:
            r = requests.post(url, json=payload, timeout=_TIMEOUT)
            data = r.json()
            if not data.get("ok"):
                log.warning("telegram %s 실패: %s", method, data.get("description"))
                return None
            return data.get("result")
        except (requests.RequestException, ValueError) as e:
            log.warning("telegram %s 예외: %s", method, e)
            return None

    def send(self, text: str, buttons: list[list[dict[str, str]]] | None = None) -> None:
        """설정된 모든 chat_id 에 발송."""
        for chat_id in self.cfg.telegram.chat_ids:
            payload: dict[str, Any] = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
            if buttons:
                payload["reply_markup"] = {"inline_keyboard": buttons}
            self._call("sendMessage", payload)

    def send_to(self, chat_id: int, text: str, buttons: list[list[dict[str, str]]] | None = None) -> None:
        payload: dict[str, Any] = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
        if buttons:
            payload["reply_markup"] = {"inline_keyboard": buttons}
        self._call("sendMessage", payload)

    def answer_callback(self, callback_id: str, text: str = "") -> None:
        self._call("answerCallbackQuery", {"callback_query_id": callback_id, "text": text})


# ----------------------------------------------------------------------------
# 메시지 빌더 (순수 함수 — 테스트 용이)
# ----------------------------------------------------------------------------
def startup_message() -> str:
    return "🟢 <b>Mini PC 모니터링 시작</b>"

def restart_done_message(name: str) -> str:
    return f"✅ <b>{name}</b> 재시작 완료"

def warn_message(name: str, cpu: float, ram: float, minutes: int) -> str:
    return (
        f"⚠️ <b>[경고] {name}</b>\n"
        f"CPU: {cpu}% / RAM: {ram}%\n"
        f"{minutes}분 이상 지속 중"
    )

def danger_message(name: str, cpu: float, ram: float, minutes: int) -> str:
    return (
        f"🔴 <b>[위험] {name}</b>\n"
        f"CPU: {cpu}% / RAM: {ram}%\n"
        f"{minutes}분 이상 지속 중\n\n"
        f"서비스를 재시작하시겠습니까?"
    )

def recovery_message(name: str, cpu: float, ram: float) -> str:
    return f"✅ <b>[복구] {name}</b>\nCPU: {cpu}% / RAM: {ram}% — 정상 복귀"

def system_alert_message(cpu: float, ram: float, procs: list[ProcessMetrics]) -> str:
    lines = [
        "⚠️ <b>[시스템 경보] 고부하 감지</b>",
        f"전체 CPU: {cpu}% / RAM: {ram}%",
        "",
        "주요 원인 프로세스:",
    ]
    for p in procs:
        lines.append(f"  • {p.name}: CPU {p.cpu_percent}% / RAM {p.ram_percent}%")
    return "\n".join(lines)

def watchdog_emergency_message(age_minutes: float) -> str:
    return (
        "🚨 <b>[긴급] 감시 데몬 응답 없음</b>\n"
        f"heartbeat 가 {age_minutes:.0f}분 이상 갱신되지 않았습니다.\n"
        "monitor 가 먹통일 수 있습니다."
    )


# 인라인 버튼 빌더 — callback_data 규약: "<action>:<target>"
def restart_buttons(name: str) -> list[list[dict[str, str]]]:
    return [[
        {"text": "✅ 재시작", "callback_data": f"restart:{name}"},
        {"text": "❌ 무시", "callback_data": f"ignore:{name}"},
    ]]

def reboot_buttons() -> list[list[dict[str, str]]]:
    return [[
        {"text": "✅ 재부팅", "callback_data": "reboot:system"},
        {"text": "❌ 무시", "callback_data": "ignore:system"},
    ]]

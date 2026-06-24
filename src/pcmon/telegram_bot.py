"""텔레그램 제어 인터페이스 — getUpdates 롱폴링.

두 가지를 처리한다:
  1) 인라인 버튼 콜백  ("restart:<name>", "ignore:<name>", "reboot:system")
  2) 슬래시 명령        (/status /top /services /restart <name> /reboot /help)

monitor.py 가 Actions(권한·상태머신 연동된 콜백 묶음)를 주입한다.
권한 게이트: allowed_user_ids(없으면 chat_ids) 외 사용자는 무시한다.
"""
from __future__ import annotations

import logging
import shlex
import subprocess
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Protocol

import requests

from .config import Config
from .notifier import Notifier

log = logging.getLogger("pcmon.telegram")
_API = "https://api.telegram.org/bot{token}/{method}"


class Actions(Protocol):
    """monitor.py 가 구현해 주입하는 제어 동작."""
    def restart(self, name: str) -> str: ...
    def ignore(self, name: str) -> None: ...
    def reboot(self) -> str: ...
    def status_text(self) -> str: ...
    def top_text(self) -> str: ...
    def services_text(self) -> str: ...


@dataclass
class TelegramBot:
    cfg: Config
    notifier: Notifier
    actions: Actions
    _stop: threading.Event = None  # type: ignore[assignment]
    _offset: int = 0

    def __post_init__(self) -> None:
        self._stop = threading.Event()

    # ---- 수명주기 ----
    def start(self) -> threading.Thread:
        t = threading.Thread(target=self._poll_loop, name="telegram-poll", daemon=True)
        t.start()
        return t

    def stop(self) -> None:
        self._stop.set()

    # ---- 롱폴링 ----
    def _poll_loop(self) -> None:
        if not self.cfg.telegram.token:
            log.info("telegram token 없음 — 제어 봇 비활성")
            return
        log.info("telegram 제어 봇 시작")
        while not self._stop.is_set():
            try:
                updates = self._get_updates()
            except Exception as e:  # noqa: BLE001
                log.warning("getUpdates 예외: %s", e)
                time.sleep(3)
                continue
            for u in updates:
                self._offset = max(self._offset, u["update_id"] + 1)
                try:
                    self._dispatch(u)
                except Exception as e:  # noqa: BLE001
                    log.exception("update 처리 실패: %s", e)

    def _get_updates(self) -> list[dict[str, Any]]:
        url = _API.format(token=self.cfg.telegram.token, method="getUpdates")
        r = requests.get(url, params={"timeout": 25, "offset": self._offset}, timeout=30)
        data = r.json()
        return data.get("result", []) if data.get("ok") else []

    # ---- 디스패치 ----
    def _dispatch(self, update: dict[str, Any]) -> None:
        if "callback_query" in update:
            self._handle_callback(update["callback_query"])
        elif "message" in update and "text" in update["message"]:
            self._handle_message(update["message"])

    def _authorized(self, user_id: int) -> bool:
        return self.cfg.telegram.is_allowed(user_id)

    def _handle_callback(self, cq: dict[str, Any]) -> None:
        user_id = cq.get("from", {}).get("id", 0)
        cid = cq.get("id", "")
        data = cq.get("data", "")
        if not self._authorized(user_id):
            self.notifier.answer_callback(cid, "권한이 없습니다")
            return
        action, _, arg = data.partition(":")
        if action == "restart":
            self.notifier.answer_callback(cid, "재시작 중…")
            self.notifier.send(self.actions.restart(arg))
        elif action == "ignore":
            self.actions.ignore(arg)
            self.notifier.answer_callback(cid, "무시 — 스누즈")
        elif action == "reboot":
            self.notifier.answer_callback(cid, "재부팅 중…")
            self.notifier.send(self.actions.reboot())
        else:
            self.notifier.answer_callback(cid, "알 수 없는 동작")

    def _handle_message(self, msg: dict[str, Any]) -> None:
        user_id = msg.get("from", {}).get("id", 0)
        chat_id = msg.get("chat", {}).get("id", 0)
        text = msg["text"].strip()
        if not self._authorized(user_id):
            self.notifier.send_to(chat_id, "권한이 없습니다.")
            return
        cmd, _, rest = text.partition(" ")
        cmd = cmd.lstrip("/").split("@")[0].lower()
        rest = rest.strip()
        handler = _COMMANDS.get(cmd)
        if handler is None:
            self.notifier.send_to(chat_id, _help_text())
            return
        reply = handler(self, rest, chat_id)
        if reply:
            self.notifier.send_to(chat_id, reply)

    # ---- 명령 핸들러 ----
    def _cmd_status(self, _arg: str, _chat: int) -> str:
        return self.actions.status_text()

    def _cmd_top(self, _arg: str, _chat: int) -> str:
        return self.actions.top_text()

    def _cmd_services(self, _arg: str, _chat: int) -> str:
        return self.actions.services_text()

    def _cmd_restart(self, arg: str, _chat: int) -> str:
        if not arg:
            return "사용법: /restart &lt;서비스명&gt;"
        return self.actions.restart(arg)

    def _cmd_reboot(self, _arg: str, chat: int) -> str:
        from .notifier import reboot_buttons
        self.notifier.send_to(chat, "⚠️ 시스템을 재부팅하시겠습니까?", reboot_buttons())
        return ""

    def _cmd_run(self, arg: str, _chat: int) -> str:
        """allowlist 기반 원격 명령 실행(확장/브리지). 기본 비활성."""
        if not self.cfg.control.allow_run_command:
            return "원격 명령 실행이 비활성화되어 있습니다(control.allow_run_command=false)."
        if not arg:
            return "사용법: /run &lt;명령&gt;"
        if not _command_allowed(arg, self.cfg.control.command_allowlist):
            return "허용되지 않은 명령입니다(command_allowlist 확인)."
        return _exec_command(arg)

    def _cmd_help(self, _arg: str, _chat: int) -> str:
        return _help_text()


# 명령 레지스트리 — 새 명령 추가 시 여기에 한 줄 + 메서드 추가(/add-telegram-command 스킬 참고)
_COMMANDS: dict[str, Callable[["TelegramBot", str, int], str]] = {
    "status": TelegramBot._cmd_status,
    "top": TelegramBot._cmd_top,
    "services": TelegramBot._cmd_services,
    "restart": TelegramBot._cmd_restart,
    "reboot": TelegramBot._cmd_reboot,
    "run": TelegramBot._cmd_run,
    "help": TelegramBot._cmd_help,
    "start": TelegramBot._cmd_help,
}


def _help_text() -> str:
    return (
        "<b>사용 가능한 명령</b>\n"
        "/status — 전체 CPU/RAM 현황\n"
        "/top — 자원 상위 프로세스\n"
        "/services — 감시 대상 서비스 사용률\n"
        "/restart &lt;name&gt; — 서비스 재시작\n"
        "/reboot — 시스템 재부팅(확인 버튼)\n"
        "/run &lt;cmd&gt; — allowlist 명령 실행(기본 비활성)\n"
        "/help — 이 도움말"
    )


def _command_allowed(cmd: str, allowlist: list[str]) -> bool:
    return any(cmd.strip().startswith(prefix) for prefix in allowlist) if allowlist else False


def _exec_command(cmd: str) -> str:
    try:
        r = subprocess.run(shlex.split(cmd), capture_output=True, text=True, timeout=30)
    except (subprocess.TimeoutExpired, FileNotFoundError, ValueError, OSError) as e:
        return f"실행 실패: {e}"
    out = (r.stdout or "").strip()
    err = (r.stderr or "").strip()
    body = out or err or "(출력 없음)"
    return f"<pre>{body[:3500]}</pre>"

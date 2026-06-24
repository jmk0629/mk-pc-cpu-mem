"""MCP 서버 스켈레톤 — pcmon 의 감시/제어를 MCP 도구로 노출.

확장 의도: 텔레그램/Discord/원격 에이전트가 MCP 클라이언트로 이 PC에 붙어
  - get_metrics      : 현재 CPU/RAM/상위 프로세스 조회
  - list_services    : 감시 대상 서비스 사용률
  - restart_service  : 서비스 재시작(control.allow_service_restart 게이트)
  - run_command      : allowlist 명령 실행(control.allow_run_command 게이트, 기본 차단)
하도록 한다. 원격 개발(파일 편집 등)은 추후 도구를 여기에 추가해 확장.

`mcp` 패키지가 설치돼 있어야 실제 서버가 뜬다. 없으면 안내만 출력(코어는 무관).
도구 본체는 tools.py 의 순수 함수라 mcp 없이도 단위 테스트 가능하다.
"""
from __future__ import annotations

import json
import sys

from .tools import (
    get_metrics,
    list_services,
    restart_service,
    run_command,
)

SERVER_NAME = "mk-pc-cpu-mem"


def build_server():
    """FastMCP 서버 인스턴스 구성. mcp 미설치 시 ImportError 를 호출자에 위임."""
    from mcp.server.fastmcp import FastMCP  # 지연 import — 선택적 의존

    mcp = FastMCP(SERVER_NAME)

    @mcp.tool()
    def metrics() -> str:
        """현재 시스템 CPU/RAM 사용률과 자원 상위 프로세스를 반환한다."""
        return json.dumps(get_metrics(), ensure_ascii=False)

    @mcp.tool()
    def services() -> str:
        """config.targets 에 정의된 감시 대상 서비스들의 사용률을 반환한다."""
        return json.dumps(list_services(), ensure_ascii=False)

    @mcp.tool()
    def restart(name: str) -> str:
        """지정한 서비스(name)를 재시작한다. 설정에서 허용된 경우에만 동작한다."""
        return json.dumps(restart_service(name), ensure_ascii=False)

    @mcp.tool()
    def run(command: str) -> str:
        """allowlist 에 부합하는 명령을 실행한다(기본 차단). 원격 운영/개발 확장 통로."""
        return json.dumps(run_command(command), ensure_ascii=False)

    return mcp


def main() -> None:
    try:
        server = build_server()
    except ImportError:
        sys.stderr.write(
            "[mk-pc-cpu-mem] MCP 서버를 띄우려면 `pip install mcp` 가 필요합니다.\n"
            "코어 감시(monitor/watchdog)는 mcp 없이도 동작합니다.\n"
        )
        sys.exit(2)
    server.run()  # stdio 트랜스포트 (기본)


if __name__ == "__main__":
    main()

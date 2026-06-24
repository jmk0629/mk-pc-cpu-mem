---
name: add-mcp-tool
description: mk-pc-cpu-mem MCP 서버에 새 도구(get_x/do_y)를 추가할 때 tools.py 순수 함수와 server.py FastMCP 래퍼를 함께 만들고 위험 동작 게이트를 검증한다. 원격 운영·개발 확장의 표준 경로.
---

# add-mcp-tool

MCP 도구를 **순수 함수(tools.py) + 래퍼(server.py)** 두 층으로 추가한다(테스트 가능성 유지).

## 입력 (yaml 또는 대화)

```yaml
name: disk_usage             # 도구명
description: 디스크 사용률 반환  # 도구 docstring
returns: dict                # 순수 함수 반환(dict). server 는 json.dumps
gated: false                 # 위험 동작(명령/쓰기)이면 true → control.allow_* 게이트 필수
```

## 동작 — 두 층 동시 추가

1. **순수 함수** `src/mcp_server/tools.py` 에 `def <name>(...) -> dict[str, Any]` 추가.
   - `pcmon` 코어(`metrics`/`services`/`config`)를 재사용. 새 로직은 가능하면 pcmon 에 두고 호출만.
   - 위험 동작이면 `Config.load().control.allow_*` 와 allowlist 를 **반드시** 확인하고 차단 메시지 반환.
2. **래퍼** `src/mcp_server/server.py` 의 `build_server()` 안에 `@mcp.tool()` 함수 추가 →
   `return json.dumps(<name>(...), ensure_ascii=False)`. import 도 상단에 추가.
3. **테스트** `tests/` 에 순수 함수 단위 테스트(mcp 미설치 환경에서 import 가능해야 함).
4. **문서** `README.md` MCP 섹션 + `docs/ARCHITECTURE.md` 도구 목록 갱신.

## 절대 규칙

- mcp 패키지는 **선택적 의존**. server.py 의 `from mcp...` 는 지연 import 유지(tools.py 는 mcp 비의존).
- 파일 쓰기/명령 실행 등 위험 도구는 기본 차단(`control.allow_run_command` 등) — 게이트 우회 금지.
- 원격 개발(파일 read/write/patch, git) 확장도 동일 패턴: 순수 함수 + 게이트 + 래퍼.

## 검증

`pytest -q` 통과. `python -c "import mcp_server.tools"` (mcp 없이) 성공. → `/new-feature-doc` → `/commit-push`.

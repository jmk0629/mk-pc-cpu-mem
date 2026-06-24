# mk-pc-cpu-mem — Claude Code 하네스 사용법

루트 `CLAUDE.md` 는 코드 컨벤션. 이 파일은 `.claude/` 하네스(skills/agents/memory) 사용법.

## Skills (5)

`/<skill-name>` 으로 호출. 각 SKILL.md 가 실제 지시문.

| Skill | 언제 사용 | 무엇을 만들/검사 |
|---|---|---|
| `/add-telegram-command` | 새 텔레그램 명령 추가 시 | `telegram_bot.py` 핸들러 + `_COMMANDS` 레지스트리 + `_help_text` + README + 테스트 — 한 번에 동기 |
| `/add-mcp-tool` | MCP 도구 추가 시 | `mcp_server/tools.py` 순수 함수 + `server.py` `@mcp.tool()` 래퍼 + 게이트 확인 |
| `/new-feature-doc` | 기능 추가 완료 시 | `docs/features/YYYY-MM-DD-<slug>.md` 생성(내용+날짜) |
| `/commit-push` | 커밋/푸시할 때 | 시크릿 가드 → conventional commit(한국어 제목) → `git push origin main` |
| `/log-mistake` | 실수/교정 발생 시 | `.claude/memory/MISTAKES.md` 최신순 기록 + 재발방지 규칙 반영 제안 |

## Agents (2)

| Agent | 호출 시점 |
|---|---|
| `daemon-safety-reviewer` | monitor/watchdog/services 변경 시. 무한루프 데몬의 예외 가드·timeout·게이트 우회·리소스 누수 점검 |
| `telegram-security-reviewer` | telegram_bot/mcp_server 변경 시 또는 PR 직전. 권한 게이트·명령 인젝션·토큰 노출·allowlist 우회 점검 |

## 워크플로 예시

새 명령 `/disk` (디스크 사용률) 추가 시:

```
/add-telegram-command
  - command: disk
  - description: 디스크 사용률 조회
  - handler: psutil.disk_usage 집계 → 텍스트
```

→ `_cmd_disk` 메서드 + `_COMMANDS["disk"]` + `_help_text` 한 줄 + README 표 + 테스트 →
`telegram-security-reviewer` 로 권한 게이트 확인 → `/new-feature-doc` → `/commit-push`.

## 권한 (`.claude/settings.local.json`)

- Allow: python/pytest/pip/venv, git status/diff/log/add/commit/push, gh, 읽기계열(ls/cat/grep/rg/find), docker/systemctl/launchctl 조회.
- Deny: `git push --force`, `git reset --hard`, `rm -rf`, `sudo reboot`, `curl|sh|bash`, config.yaml/.env 커밋.

## 절대 규칙 재확인

- 코어 import 부작용 금지 · 한 주기 실패가 데몬을 죽이지 않음 · 외부 명령 timeout+가드.
- 위험 동작(재부팅/원격 명령)은 config 게이트로 기본 차단 — 우회 코드 금지.
- 새 명령/도구는 반드시 스킬 경유(레지스트리·도움말 드리프트 방지).
- 시크릿은 `config.yaml`(gitignore)/env 로만. 예제는 placeholder.
- 작업 전 `memory/MISTAKES.md` 읽기, 기능마다 `docs/features/` 기록.

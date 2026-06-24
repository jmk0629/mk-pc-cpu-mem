# mk-pc-cpu-mem — 프로젝트 컨벤션

이 파일은 Claude Code 가 mk-pc-cpu-mem 작업을 할 때 따라야 할 **코드 컨벤션**.
`.claude/CLAUDE.md` 는 하네스(skills/agents/memory) 사용법.

## 절대 규칙

1. **코어는 import 부작용 금지**: `pcmon` 모듈은 토큰/네트워크 없이도 import 되어야 한다. 네트워크·시스템 호출은 함수 호출 시점에만.
2. **한 주기 실패가 데몬을 죽이지 않는다**: monitor 루프의 `_tick()` 류는 try/except 로 감싸고 다음 주기로 진행.
3. **외부 명령은 timeout + 예외 가드**: `subprocess`/`docker`/`systemctl` 등은 반드시 timeout, 실패는 `RestartResult(ok=False)` / `Usage(available=False)` 로 표면화(예외 전파 금지).
4. **위험 동작은 config 게이트로 기본 차단**: 재부팅(`control.allow_reboot`)·원격 명령(`control.allow_run_command`+allowlist)·watchdog 재부팅(`watchdog.allow_reboot`). 게이트 우회 코드 추가 금지.
5. **시크릿은 코드/깃에 금지**: 토큰은 `config.yaml`(gitignore) 또는 `PCMON_TELEGRAM_TOKEN` env. 예제는 `config.yaml.example` 에 placeholder 만.
6. **알림 정책은 state.py 에**: 임계/지속시간/스누즈 로직을 monitor 루프에 흩지 말고 상태 머신에 둔다(테스트 가능하게 `now()` 주입).
7. **크로스플랫폼 분기는 services.py 한 곳**: OS별 if 를 다른 모듈로 퍼뜨리지 않는다.
8. **새 텔레그램 명령/ MCP 도구는 스킬 경유**: `/add-telegram-command`, `/add-mcp-tool` 로 레지스트리·핸들러·도움말을 함께 갱신(드리프트 방지).
9. **작업 시작 전** `.claude/memory/MISTAKES.md` 를 먼저 읽고 같은 실수를 반복하지 않는다.
10. **기능 추가마다 문서**: `docs/features/YYYY-MM-DD-<slug>.md` 로 내용+날짜 기록(`/new-feature-doc`).

## 구조

```
src/pcmon/        코어 (config·metrics·services·state·notifier·telegram_bot·monitor·watchdog)
src/mcp_server/   MCP 확장 (tools 순수함수 + server FastMCP 래퍼)
deploy/           systemd · launchd · install.sh
tests/            pytest 단위 테스트
docs/             ARCHITECTURE · PLAN · features/
config.yaml(.example)  모든 설정
```

## 코드 스타일 (Python)

- Python ≥3.10, `from __future__ import annotations`, 타입 힌트 명시.
- dataclass 우선. 순수 함수(메시지 빌더/도구 본체)와 부작용(송신/실행) 분리.
- 로깅은 `logging.getLogger("pcmon.<mod>")`. print 지양(데몬).
- 의존은 최소(psutil/PyYAML/requests). 새 런타임 의존 추가는 신중히, requirements/pyproject 동시 갱신.

## 테스트

- `pytest -q`. 상태 머신은 fake clock(`now` 주입)으로 분 단위 전이 검증, 실시간 sleep 금지.
- 시스템/네트워크에 의존하는 부분은 단위 테스트에서 호출하지 않거나 가드 경로를 검증.

## 커밋 / 푸시

- 자동 커밋/푸시는 `/commit-push` 스킬로. 리모트: `https://github.com/jmk0629/mk-pc-cpu-mem`.
- 커밋 제목은 한국어로 이해 가능하게(타입 프리픽스 `feat:`/`fix:`/`docs:` 등 + 식별자는 영어).
- 시크릿(config.yaml/.env) 절대 staging 금지. `git add .`/`-A` 지양, 파일 명시. force push 금지.
- 작은 커밋 선호(기능/Phase 단위).

## 검증 체크리스트 (작업 종료 시)

- [ ] `pytest -q` 통과
- [ ] 새 의존 추가 시 requirements.txt + pyproject.toml 동기
- [ ] 새 명령/도구 추가 시 도움말(`_help_text`)·README 갱신
- [ ] `docs/features/` 항목 작성
- [ ] 시크릿이 diff 에 없는지 확인

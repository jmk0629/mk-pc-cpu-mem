# 아키텍처

## 모듈 경계 (단방향 의존)

```
config.py    설정 로드(yaml + env). 모든 모듈이 의존하는 잎(leaf).
metrics.py   psutil 시스템/프로세스 수집. config 비의존.
services.py  타겟별 사용률 + 재시작/재부팅. OS 분기(docker/systemd/launchd/process).
state.py     알림 상태 머신(정상→주의→위험→복구). 순수 로직, now() 주입.
notifier.py  Telegram 송신 + 메시지 빌더(순수 함수).
telegram_bot.py  getUpdates 롱폴링 + 명령/버튼 디스패치. Actions 프로토콜 주입.
monitor.py   ↑ 전부를 조립하는 데몬. Actions 구현. 메인 루프 + heartbeat.
watchdog.py  heartbeat 점검 1회 실행 유닛.
mcp_server/  tools.py(순수) ↔ server.py(FastMCP). pcmon 코어 재사용.
```

원칙:
- **코어는 import 부작용 없음** — 네트워크/시스템 호출은 호출 시점에만. 토큰 없어도 import/테스트 가능.
- **한 주기 실패가 데몬을 죽이지 않음** — `_tick()` 전체를 try/except 로 감싸고 다음 주기 진행.
- **외부 명령은 timeout + 예외 가드** — 실패는 `RestartResult(ok=False)` / `Usage(available=False)` 로 표면화.
- **시간 주입** — 상태 머신은 `now()` 콜러블을 받아 분 단위 전이를 sleep 없이 테스트.

## 상태 머신 (state.py)

타겟별 `TargetState` 를 유지하며 매 주기 `update(name, cpu, ram)` → `Event` 반환.

| 조건 | 전이 | Event |
|---|---|---|
| 임계값 초과 시작 | breach_since 기록 | NONE |
| 초과 `alert_minutes`(5) 지속 | WARN, warn_sent | WARN_ALERT |
| 초과 `restart_minutes`(20) 지속 | DANGER | DANGER_PROMPT |
| '무시' 버튼 | snooze_until = now + 10분 | (다음 질문 보류) |
| 스누즈 만료 후에도 초과 | DANGER 재질문 | DANGER_PROMPT |
| 위험 질문 후 `response_timeout`(10) 무응답 | 재질문 | DANGER_PROMPT |
| 임계값 이하 `recovery_minutes`(1) 유지 | NORMAL 리셋 | RECOVERY |

## 제어 흐름 (텔레그램 ↔ monitor)

```
TelegramBot(poll thread)  --callback/command-->  Actions(=Monitor)
   restart:<name>  → Monitor.restart(name) → services.restart_target → 결과 알림
   ignore:<name>   → Monitor.ignore(name)  → state.snooze
   reboot:system   → Monitor.reboot()      → services.reboot_system
   /status /top /services → Monitor.*_text()
```

권한 게이트: `telegram.allowed_user_ids`(없으면 chat_ids) 외 사용자는 모든 콜백/명령 무시.

## 크로스플랫폼 서비스 제어 (services.py)

| type | 사용률 | 재시작 |
|---|---|---|
| `docker` | `docker stats --no-stream` | `docker restart` |
| `systemd` | 프로세스 매칭 집계(베스트에포트) | `systemctl restart` (Linux) |
| `launchd` | 프로세스 매칭 집계 | `launchctl kickstart -k gui/<uid>/<label>` (macOS) |
| `process` | 이름/cmdline 매칭 psutil 합산 | SIGTERM(감독자 재기동 전제) |

재부팅: Linux `systemctl reboot`, macOS `shutdown -r now`. `control.allow_reboot` 게이트.

## 위험 동작 게이트 (기본 차단)

- `control.allow_reboot` — 재부팅
- `control.allow_run_command` + `command_allowlist` — 원격 임의 명령(/run, MCP run_command)
- watchdog 의 재부팅 버튼은 `watchdog.allow_reboot` 별도 게이트

## MCP 확장 (mcp_server/)

`tools.py` 의 순수 함수(get_metrics/list_services/restart_service/run_command)를
`server.py` 가 FastMCP 도구로 감싼다. `mcp` 미설치 시 코어는 영향 없음.
원격 개발(파일 read/write/patch, 빌드, git)로의 확장은 tools.py 에 도구를 추가하는 방향.

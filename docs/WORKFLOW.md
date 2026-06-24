# 워크플로우 — 처리 흐름 상세

이 문서는 mk-pc-cpu-mem 가 **런타임에 어떤 순서로 흘러가는지**(감시→상태판정→알림→제어→안전장치)와
**개발/배포 워크플로우**를 한 곳에 정리한다. 코드 위치는 `file:함수` 로 표기한다.

---

## 1. 큰 그림

```
┌────────────────────────────────────────────────────────────────────┐
│  대상 PC (Mini PC=Ubuntu/systemd 또는 Mac/launchd)                   │
│                                                                      │
│   pc-monitor (상시 데몬)            pc-watchdog (2분 주기 1회 실행)   │
│   ┌───────────────────────┐        ┌──────────────────────────┐     │
│   │ monitor.py            │        │ watchdog.py              │     │
│   │  └ 메인 루프(30s)      │        │  └ heartbeat 만료 점검    │     │
│   │  └ 텔레그램 폴러(thread)│       └──────────┬───────────────┘     │
│   └─────────┬─────────────┘                   │                     │
│             │ heartbeat 파일 ◄─────────────────┘ (읽기)              │
└─────────────┼────────────────────────────────────────────────────┘
              │ Telegram Bot API (HTTPS)
              ▼
       ┌─────────────┐   알림(🟢⚠️🔴✅🚨) + 버튼/명령
       │  텔레그램     │ ◄──────────────────────────►  사용자
       └─────────────┘   재시작/무시/재부팅, /status·/top·/services
```

- **monitor.py** = 상시 데몬. 30초마다 자원 수집 → 상태 머신 → 알림 발송. 동시에 텔레그램 제어 봇 스레드 가동.
- **watchdog.py** = 안전장치. monitor 가 매 주기 갱신하는 heartbeat 파일을 2분마다 점검, 5분 이상 미갱신이면 🚨 긴급 알림.
- 둘 다 부팅 시 자동 시작(systemd `.service`/`.timer` 또는 launchd `.plist`).

---

## 2. monitor 데몬 — 생애주기

`pcmon/monitor.py:Monitor.run`

```
[부팅] systemd/launchd 가 `python -m pcmon.monitor` 실행
  │
  ├─ Config.load()                     config.yaml + env(PCMON_TELEGRAM_TOKEN) 로드
  ├─ Monitor(cfg)                      상태 머신·notifier·targets 초기화
  ├─ TelegramBot(...).start()          getUpdates 롱폴링 스레드 가동(데몬 스레드)
  ├─ notifier.send(🟢 시작)             "Mini PC 모니터링 시작"
  ├─ SIGTERM/SIGINT 핸들러 등록          → _running=False 로 우아한 종료
  │
  └─ while _running:                   ── 메인 루프 ──
        try: _tick()                   한 주기(아래 3절). 실패해도 except 로 흡수
        except: log.exception(...)     ★ 한 주기 실패가 데몬을 죽이지 않음
        _write_heartbeat()             state/heartbeat 에 현재 epoch 기록
        sleep(check_interval_seconds)  기본 30초
```

핵심 불변식:
- **루프는 절대 예외로 죽지 않는다** — `_tick()` 전체가 try/except 로 감싸짐.
- **heartbeat 는 매 주기 기록** — watchdog 가 이걸로 생존을 판단.

---

## 3. 한 주기(_tick) — 처리 파이프라인

`pcmon/monitor.py:Monitor._tick`

```
_tick()
  │
  ├─ (A) 타겟별 감시  for target in targets:
  │       usage = services.target_usage(target)      ── 4절: 사용률 측정(OS/타입별)
  │       if not usage.available: continue            대상이 없으면 스킵
  │       event = state.update(name, cpu, ram)        ── 5절: 상태 머신 → 이벤트
  │       _emit(name, event, cpu, ram)                ── 6절: 이벤트 → 알림 발송
  │
  └─ (B) 전체 고부하 '시스템 경보'  if system_alert.enabled:
          m = metrics.system_metrics()                전체 CPU/RAM
          over = m.cpu>=th or m.ram>=th
          if over and not _sys_alerted:               엣지 트리거(중복 억제)
              procs = metrics.top_processes(exclude)   원인 프로세스 상위 N
              notifier.send(⚠️ 시스템 경보 + procs)
              _sys_alerted = True
          elif not over: _sys_alerted = False          정상 복귀 시 리암
```

(A)는 **특정 서비스/대상**의 단계별 알림, (B)는 **머신 전체**의 즉시 고부하 경보 — 책임이 다르다.

---

## 4. 사용률 측정 — 타입별 분기

`pcmon/services.py:target_usage` / `metrics.py`

| target.type | 측정 방법 | 함수 |
|---|---|---|
| `system` | 머신 전체 CPU/RAM (psutil) | `_system_usage` |
| `docker` | `docker stats --no-stream` 파싱 | `_docker_usage` |
| `systemd` | 프로세스 매칭 집계(베스트에포트) | `_process_usage` |
| `launchd` | 프로세스 매칭 집계 | `_process_usage` |
| `process` | 이름/cmdline 매칭 psutil 합산 | `_process_usage` |

- psutil CPU% 는 **prime 후 재측정**(첫 호출은 항상 0.0). `metrics.top_processes`, `services._process_usage` 모두 이 패턴.
- 모든 외부 명령은 **timeout + 예외 가드** → 실패는 `Usage(available=False)` 로 표면화(예외 전파 금지).

---

## 5. 상태 머신 — 정상→주의→위험→복구

`pcmon/state.py:StateMachine.update` (타겟별 `TargetState` 유지, 시간은 `now()` 주입)

```
                 임계값 초과 시작
   [정상] ───────────────────────► breach_since 기록 (이벤트 없음)
      ▲                                  │
      │ 임계값 이하 recovery_minutes 유지  │ 초과 alert_minutes(5분) 지속
      │  → 상태 리셋                       ▼
   RECOVERY ◄────────────────────  [주의]  WARN_ALERT (1회)
                                        │ 초과 restart_minutes(20분) 지속
                                        ▼
                                   [위험]  DANGER_PROMPT  (재시작 버튼)
                                        │
            ┌───────────────────────────┼───────────────────────────┐
       '무시' 버튼                   응답 없음                    '재시작' 버튼
       snooze(10분)              response_timeout(10분)         acknowledge_restart()
       후 재질문                   경과 시 재질문                 → 상태 리셋(복구 대기)
```

- 임계 판정은 **CPU 또는 RAM 중 하나라도 초과**면 초과(`_over_threshold`).
- `breach_since`(초과 시작) / `recover_since`(복귀 시작) 타임스탬프로 지속시간을 계산.
- 모든 분 단위 전이는 fake clock 주입으로 단위 테스트됨(`tests/test_state.py`).

---

## 6. 이벤트 → 알림 발송

`pcmon/monitor.py:Monitor._emit` → `pcmon/notifier.py`

| Event | 메시지 빌더 | 텔레그램 표시 |
|---|---|---|
| `WARN_ALERT` | `warn_message` | ⚠️ [경고] name / CPU·RAM / N분 지속 |
| `DANGER_PROMPT` | `danger_message` + `restart_buttons` | 🔴 [위험] … 재시작하시겠습니까? [✅재시작][❌무시] |
| `RECOVERY` | `recovery_message` | ✅ [복구] name / 정상 복귀 |
| (시스템 경보) | `system_alert_message` | ⚠️ [시스템 경보] 전체 부하 + 원인 프로세스 |
| (watchdog) | `watchdog_emergency_message` | 🚨 [긴급] heartbeat 없음 |

- 메시지 빌더는 **순수 함수**(부작용 없음) → 포맷을 테스트/재사용 가능.
- 발송은 `Notifier.send` 가 `telegram.chat_ids` 전부에 HTTP POST. 토큰 없으면 조용히 no-op.

---

## 7. 제어 흐름 — 텔레그램 → 동작

`pcmon/telegram_bot.py:TelegramBot._poll_loop`

```
getUpdates(롱폴링 25s) ── 별도 데몬 스레드
   │
   ├─ callback_query (버튼)              _handle_callback
   │     권한 게이트: is_allowed(user_id) ── 실패 시 "권한 없음"
   │     "restart:<name>" → Monitor.restart(name) → services.restart_target → 결과 알림
   │     "ignore:<name>"  → Monitor.ignore(name)  → state.snooze
   │     "reboot:system"  → Monitor.reboot()      → services.reboot_system(게이트)
   │
   └─ message (슬래시 명령)               _handle_message → _COMMANDS[cmd]
         /status   → Monitor.status_text()      전체 CPU/RAM
         /top      → Monitor.top_text()         상위 프로세스
         /services → Monitor.services_text()    감시 대상별 사용률
         /restart <name> → Monitor.restart(name)
         /reboot   → reboot_buttons (확인 후 실행)
         /run <cmd>→ allowlist 검사 후 실행 (control.allow_run_command, 기본 차단)
         /help     → 도움말
```

- `Monitor` 가 `Actions` 프로토콜을 구현 → 봇과 데몬이 **느슨하게 결합**(테스트 시 가짜 Actions 주입 가능).
- 위험 동작(재부팅/원격 명령)은 `control.allow_*` 게이트로 **기본 차단**.

---

## 8. watchdog — 안전장치

`pcmon/watchdog.py:check` (systemd `.timer`/launchd `StartInterval` 가 2분마다 1회 실행)

```
check(cfg)
  │ age = heartbeat_age_minutes(path)        파일 mtime/내용 → 경과(분)
  ├─ age is None(파일 없음) → 🚨 긴급("heartbeat 없음") + (옵션) 재부팅 버튼 → exit 1
  ├─ age >= max_age_minutes(5분) → 🚨 긴급(응답 없음) + (옵션) 재부팅 버튼 → exit 1
  └─ 정상 → 로그만 → exit 0
```

- watchdog 는 **상시 데몬이 아니라 주기 실행**(스케줄러가 띄움). monitor 와 독립 프로세스라
  monitor 가 먹통이어도 alert 가 나간다.
- 재부팅 버튼은 `watchdog.allow_reboot` 별도 게이트.

---

## 9. 설정 적용 워크플로우 (코드 수정 없이)

```
config.yaml 편집(임계값/알림시간/대상/토큰)
   │
   ├─ Linux : sudo systemctl restart pc-monitor
   └─ macOS : launchctl kickstart -k gui/$(id -u)/com.mkpc.monitor
   → Config.load() 재실행되어 즉시 반영
```

토큰은 `config.yaml`(gitignore) 또는 `PCMON_TELEGRAM_TOKEN` 환경변수(우선).

---

## 10. 개발 → 배포 워크플로우 (.claude 하네스)

```
변경 작업
  │
  ├─ 새 텔레그램 명령    → /add-telegram-command  (핸들러+레지스트리+도움말+README+테스트 동기)
  ├─ 새 MCP 도구        → /add-mcp-tool          (tools.py 순수함수 + server.py 래퍼)
  ├─ 코어/데몬 변경      → daemon-safety-reviewer 에이전트 (예외가드/timeout/게이트)
  ├─ 봇/ MCP 변경       → telegram-security-reviewer 에이전트 (권한/인젝션/토큰)
  ├─ 실수/교정          → /log-mistake           (.claude/memory/MISTAKES.md)
  │
  ├─ pytest -q          (상태머신/config/watchdog 단위 테스트)
  ├─ /new-feature-doc   → docs/features/YYYY-MM-DD-*.md
  └─ /commit-push       → 시크릿 가드 → 한국어 커밋 → git push origin main
```

전체 모듈 의존 방향과 설계 원칙은 `docs/ARCHITECTURE.md`, 로드맵은 `docs/PLAN.md` 참고.

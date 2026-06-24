# mk-pc-cpu-mem

Mini PC 의 **CPU·메모리 사용률을 24시간 자동 감시**하여, 이상이 탐지되면 **텔레그램으로 즉시 알림**을 보내고,
필요하면 **버튼 한 번으로 서비스 재시작 또는 시스템 재부팅**까지 대응하는 자동 관리 시스템.
나아가 **MCP 로 외부(텔레그램/Discord/에이전트)에서 PC에 붙어 원격 운영·개발**까지 확장할 수 있도록 설계되었다.

> 크로스플랫폼: 코어 감시는 OS 무관(psutil), 서비스 등록만 Linux=systemd / macOS=launchd 양쪽 제공.

## 📌 이 시스템이 하는 일

CPU/메모리를 30초마다 확인 → 임계값(기본 80%) 초과가 일정 시간 지속되면 단계별 알림 →
위험 단계에서 재시작/재부팅 버튼 제공 → 부하가 임계값 이하로 복귀하면 복구 알림.

## 📦 구성 파일

| 파일 | 역할 |
|---|---|
| `src/pcmon/monitor.py` | 핵심 감시 데몬. CPU/RAM 을 30초마다 확인하고 단계별 알림 발송 + 텔레그램 제어 봇 |
| `src/pcmon/watchdog.py` | 감시 데몬 먹통 여부 확인 안전장치. heartbeat 미갱신 시 긴급 알림 |
| `src/pcmon/state.py` | 정상→주의→위험→복구 상태 머신 (스누즈 포함) |
| `src/pcmon/services.py` | 크로스플랫폼 서비스 사용률 측정 + 재시작/재부팅 (docker/systemd/launchd/process) |
| `src/pcmon/telegram_bot.py` | 텔레그램 명령/버튼 처리 (제어 인터페이스) |
| `src/mcp_server/` | **MCP 확장 포인트** — get_metrics / restart_service / run_command 도구 |
| `config.yaml` | 임계값·알림 시간·텔레그램 토큰 등 모든 설정. **코드 수정 없이 이 파일만 편집** |
| `deploy/systemd/*`, `deploy/launchd/*` | 부팅 시 자동 시작 + watchdog 주기 실행 등록 |

## 🔄 동작 흐름

```
① 부팅 시 자동 시작         → 🟢 모니터링 시작 알림
② 30초마다 CPU·RAM 수집
③ CPU or RAM > 80% ?        → 아니면 정상 루프
④ 5분 이상 지속             → ⚠️ 주의 알림 1회
⑤ 20분 이상 지속            → 🔴 재시작 질문 [✅재시작 / ❌무시]
      ❌무시 → 10분 스누즈 후 재질문
      ✅재시작 → 서비스 즉시 재시작 → 결과 알림
⑥ 부하가 임계값 이하로 복귀  → ✅ 복구 알림
```

watchdog: 2분마다 실행 → heartbeat 5분 이상 미갱신이면 🚨 긴급(응답 없음) 알림.

## 📱 텔레그램 알림 종류

| 아이콘 | 유형 | 발송 조건 |
|---|---|---|
| 🟢 | 시작 | 부팅 또는 서비스 재시작 후 |
| ⚠️ | 주의 | CPU/RAM 80% 초과 → 5분 지속 |
| 🔴 | 위험 | 80% 초과 → 20분 이상 지속 (재시작 버튼) |
| ✅ | 복구 | 부하가 임계값 이하로 복귀 시 |
| ⚠️ | 시스템 경보 | 특정 서비스 외 전체 고부하 + 원인 프로세스 |
| 🚨 | 긴급 | watchdog — heartbeat 5분 이상 없음 |

## 📲 텔레그램 명령

```
/status            전체 CPU/RAM 현황
/top               자원 상위 프로세스
/services          감시 대상 서비스 사용률
/restart <name>    서비스 재시작
/reboot            시스템 재부팅(확인 버튼)
/run <cmd>         allowlist 명령 실행 (기본 비활성)
/help              도움말
```

## ⚙️ 설정 (config.yaml)

`config.yaml.example` 를 복사해 사용. 주요 값:

- `thresholds.cpu_percent` / `ram_percent` — 임계값(기본 80)
- `timing.alert_minutes`(5) / `restart_minutes`(20) / `response_timeout_minutes`(10) / `snooze_minutes`(10)
- `timing.check_interval_seconds`(30) — 점검 주기
- `watchdog.max_age_minutes`(5) — heartbeat 만료 기준
- `telegram.token` / `chat_ids` / `allowed_user_ids` — 수신·권한
- `targets[]` — 감시 대상 (docker/systemd/launchd/process)
- `exclude_services[]` — 시스템 경보 집계 제외 (cron, ssh, dbus, systemd, docker …)
- `control.allow_reboot` / `allow_run_command` — 위험 동작 게이트 (기본 차단)

토큰은 `PCMON_TELEGRAM_TOKEN` 환경변수로도 주입 가능(파일값보다 우선).

## 🚀 설치

```bash
# 1) 텔레그램 봇 준비: @BotFather → 토큰, @userinfobot → chat_id
cp config.yaml.example config.yaml   # token/chat_ids/targets 채우기

# 2) 설치 (Linux: systemd / macOS: launchd 자동 분기)
sudo ./deploy/install.sh             # Linux
./deploy/install.sh                  # macOS

# 적용(설정 변경 후): sudo systemctl restart pc-monitor
```

## 🧪 개발

```bash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt pytest
pip install -e .
pytest -q                            # 단위 테스트
python -m pcmon.monitor              # 로컬 실행 (config.yaml 필요)
```

## 🔌 MCP 확장 (원격 운영/개발)

```bash
pip install '.[mcp]'
python -m mcp_server.server          # stdio MCP 서버 — get_metrics/services/restart/run 도구
```

MCP 클라이언트(텔레그램 브리지, Discord 봇, 코딩 에이전트)를 연결해 외부에서 이 PC의
상태 조회·서비스 재시작을 수행할 수 있다. 원격 개발(파일 편집 등) 도구는 `src/mcp_server/tools.py`
에 추가해 확장한다(`/add-mcp-tool` 스킬 참고).

## 📁 히스토리

기능을 추가할 때마다 `docs/features/YYYY-MM-DD-<slug>.md` 로 내용과 날짜를 기록한다.
런타임 처리 흐름은 `docs/WORKFLOW.md`, 미니 PC 원격 감시/배포 설계는 `docs/REMOTE_MINIPC.md`,
설계 배경/계획은 `docs/ARCHITECTURE.md`, `docs/PLAN.md` 참고.

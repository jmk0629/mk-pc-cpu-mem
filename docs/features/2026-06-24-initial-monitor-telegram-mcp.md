# 초기 구축 — CPU/RAM 감시 + 텔레그램 제어 + MCP 스켈레톤

- **기간**: 2026-06-24
- **유형**: 신규 기능 (P0 전체)
- **레이어**: pcmon 코어 + mcp_server + deploy + docs + .claude 하네스

## 무엇을 / 배경

mk-hospital·mk-health-app·mk-cli-compare 의 하네스/문서 컨벤션을 그대로 따라
Mini PC 자원 감시 시스템을 신규 구축했다. 이미지로 받은 설계(monitor/watchdog/config +
단계별 텔레그램 알림 + 재시작/재부팅 버튼)를 Python 으로 구현하고, 향후 MCP 원격
운영·개발로 확장할 수 있는 구조를 마련했다.

## 구현

### 코어 (`src/pcmon/`)
- `config.py` — config.yaml 로드 + `PCMON_TELEGRAM_TOKEN` env override + 권한 게이트(`is_allowed`).
- `metrics.py` — psutil 기반 시스템/상위 프로세스 수집. CPU% 는 prime 후 측정.
- `services.py` — 타겟 type(docker/systemd/launchd/process)별 사용률 + 재시작, OS별 재부팅.
  모든 외부 명령은 timeout + 예외 가드 → 실패를 `Usage.available=False` / `RestartResult.ok=False` 로 표면화.
- `state.py` — 정상→주의(5분)→위험(20분, 재시작 질문)→복구 상태 머신. '무시' 스누즈(10분),
  무응답 재질문(10분). `now()` 주입으로 sleep 없이 테스트.
- `notifier.py` — Telegram 송신 + 이미지 문구 그대로의 메시지 빌더(🟢⚠️🔴✅🚨) + 인라인 버튼.
- `telegram_bot.py` — getUpdates 롱폴링(별도 스레드) + 명령 레지스트리(/status·/top·/services·
  /restart·/reboot·/run·/help) + 버튼 콜백(restart/ignore/reboot). 권한 게이트 통과 사용자만.
- `monitor.py` — 메인 루프(기본 30s): 타겟 감시 → 상태 이벤트 → 알림, 전체 고부하 '시스템 경보',
  heartbeat 기록. Actions 프로토콜 구현해 봇과 연결.
- `watchdog.py` — heartbeat 만료(5분) 감지 1회 실행 유닛, 긴급 알림(+옵션 재부팅 버튼).

### MCP 확장 (`src/mcp_server/`)
- `tools.py` — 순수 함수(get_metrics/list_services/restart_service/run_command), pcmon 코어 재사용.
- `server.py` — FastMCP 로 도구 노출. `mcp` 미설치 시 코어 무관(지연 import).

### 배포 (`deploy/`)
- systemd: `pc-monitor.service`, `pc-watchdog.service` + `.timer`(2분).
- launchd: `com.mkpc.monitor.plist`(KeepAlive), `com.mkpc.watchdog.plist`(StartInterval 120s).
- `install.sh` — OS 자동 분기 설치(/opt/pc-monitor + venv + 서비스 등록).

### 위험 동작 게이트(기본 차단)
- `control.allow_reboot`(재부팅), `control.allow_run_command`+`command_allowlist`(원격 명령),
  `watchdog.allow_reboot`(watchdog 재부팅 버튼).

## 검증

- `pytest -q` → **14 passed** (state 5, config 6, watchdog 3).
- 스모크: 실제 시스템 메트릭 수집·전 모듈 import·MCP tools 호출 정상(macOS/Darwin 확인).

## 변경 파일 (신규)

| 영역 | 파일 |
|---|---|
| 코어 | `src/pcmon/{__init__,config,metrics,services,state,notifier,telegram_bot,monitor,watchdog}.py` |
| MCP | `src/mcp_server/{__init__,server,tools}.py` |
| 배포 | `deploy/systemd/pc-*.{service,timer}`, `deploy/launchd/com.mkpc.*.plist`, `deploy/install.sh` |
| 설정 | `config.yaml.example`, `requirements.txt`, `pyproject.toml` |
| 테스트 | `tests/test_{state,config,watchdog}.py` |
| 문서 | `README.md`, `docs/{ARCHITECTURE,PLAN}.md`, 본 파일 |
| 하네스 | `.claude/{CLAUDE.md, settings.local.json, memory/MISTAKES.md, skills/*, agents/*}` |

## 다음 (PLAN.md P1/P2)

서비스별 CPU 정확도(cgroup), 알림 중복 억제·히스토리, MCP 원격 개발 도구(파일/git), Discord 브리지.

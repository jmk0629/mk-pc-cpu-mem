# Mac launchd 자동 실행 + 발견 콜드스타트 견고화

- **기간**: 2026-06-24
- **유형**: 배포(운영) + 견고성
- **레이어**: deploy(launchd) + pcmon(monitor) + docs

## 무엇을 / 배경

Mac에서 멀티호스트 감시(Mac + 미니PC)를 **로그인 시 자동 실행**되도록 LaunchAgent 로 등록하고,
부팅 직후 네트워크 미준비로 원격 자동 발견이 비는 콜드스타트를 빠르게 회복하도록 보완했다.

## 구현

### launchd LaunchAgent (Mac 로컬)
- `~/Library/LaunchAgents/com.mkpc.monitor.plist` — `<repo>/venv/bin/python -m pcmon.monitor`,
  `PYTHONPATH=<repo>/src`, `PCMON_CONFIG=<repo>/config.yaml`, RunAtLoad + KeepAlive, 로그 `/tmp/pcmon-monitor.err`.
- `~/Library/LaunchAgents/com.mkpc.watchdog.plist` — 120초 StartInterval, heartbeat 점검.
- repo 안에 안정적 `venv/`(gitignore) 구성 후 등록(`launchctl bootstrap gui/$(id -u) ...`).
- 수동 켜고/끄기/재시작/로그 확인 방법을 README "Mac 자동 실행 / 수동 켜고 끄기" 절에 정리.

### 콜드스타트 견고화 (`monitor._refresh_targets`)
- 원격 발견이 **비면**(부팅 직후 SSH/네트워크 미준비 등) 다음 재발견을 5분이 아니라 **다음 틱(≥15s)**에 재시도.
- 정상 발견되면 `refresh_minutes`(5분) 주기로 복귀. `_next_gap` 으로 제어.

## 검증

- 등록 직후 startup 1회는 콜드스타트로 2개(Mac/미니PC system)만 잡힘 → 다음 틱/재시작에서 7개 전부 발견 확인.
- 재시작 후: `감시 대상 7개`(Mac, 미니PC@keymedi1, open-design, html-pdf-service, caddy, meditv-report, monthly-reminder).
- heartbeat 정상 갱신, watchdog `heartbeat 정상` 로그. `pytest -q` → 32 passed.

## 변경 파일

| 파일 | 변경 |
|---|---|
| `~/Library/LaunchAgents/com.mkpc.{monitor,watchdog}.plist` | (머신 로컬, 미커밋) Mac 자동 실행 |
| `src/pcmon/monitor.py` | `_refresh_targets` 콜드스타트 빠른 재시도(`_next_gap`) |
| `README.md` | Mac launchd 자동 실행 + 수동 켜고 끄기 절 |

## 운영 메모

- Mac 꺼짐/로그아웃 동안은 감시 안 됨 — 미니 PC 24h 는 직접 설치(모드 A)가 정답.
- launchd 데몬과 수동 `python -m pcmon.monitor` 를 동시에 띄우지 말 것(같은 봇 알림 중복).

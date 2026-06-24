# 멀티호스트 — 한 모니터로 여러 대(Mac + 미니 PC) 동시 감시

- **기간**: 2026-06-24
- **유형**: 신규 기능
- **레이어**: pcmon(config·discovery·services·monitor) + mcp_server

## 무엇을 / 배경

"내 PC랑 미니 PC 둘 다 한 번에 감시되게" 요청에 따라, 기존의 단일 전역 `remote.host`
모델을 **호스트별 타겟**으로 일반화했다. 한 모니터(한 봇)가 로컬 Mac + 원격 미니 PC를 동시에 감시한다.

## 구현

### `config.py`
- `Target.host` 필드 추가("" = 로컬, 아니면 SSH 별칭).
- `HostConfig{name, host, discovery, system, targets}` + `Config.hosts: list[HostConfig]`.
- `_parse_hosts`: `hosts` 파싱. 없으면 레거시(`remote`/`discovery`/`targets`)에서 단일 호스트 합성(하위호환).

### `monitor.py`
- `_tid(t)="host|name"`(고유 키, 콜백 데이터), `_label(t)="name @host"`(표시).
- `_refresh_targets`: 호스트별 system + 명시 + (discovery)발견 타겟을 tid 키로 병합.
- `_tick`: `target_usage(target)`(target.host 로 자동 분기) → `state.update(tid, ...)` → `_emit(target, tid, ...)`.
- 버튼 콜백 `restart:{tid}` / `ignore:{tid}` 로 정확한 호스트의 타겟 제어. `/restart <name>` 은 이름으로도 매칭.
- `/status`·`/top`·시스템 경보가 **호스트별**로 계산(`@host` 표기). `_check_system_alert` 는 host 별 `_sys_alerted`.

### `discovery.py` / `mcp_server`
- `discover_for(cfg, host)`: 주어진 호스트에서 발견(타겟에 host 부여). `discover(cfg)` 는 레거시 유지.
- MCP `list_services`/`restart_service` 가 `_all_targets(cfg)`(호스트 평탄화)를 사용, 응답에 `host` 포함.

## 검증 (라이브, Mac + keymedi1)

- 한 모니터가 6개 동시 감시: `Mac [system]`(로컬 CPU 23%/RAM 84%) + `미니PC @keymedi1 [system]`,
  open-design·html-pdf-service·caddy·meditv-report(원격 SSH). `/status` 가 두 호스트를 함께 표기.
- 실제 데몬(`-m pcmon.monitor`) 루프 무에러 + heartbeat 갱신 확인.
- `pytest -q` → 32 passed (multi-host 5 추가).

## 변경 파일

| 파일 | 변경 |
|---|---|
| `src/pcmon/config.py` | `Target.host`, `HostConfig`, `Config.hosts`, `_parse_hosts`(레거시 폴백) |
| `src/pcmon/monitor.py` | tid/label, 호스트별 타겟 병합·메트릭·시스템경보, 콜백 라우팅 |
| `src/pcmon/discovery.py` | `discover_for(cfg, host)` |
| `src/pcmon/services.py` | `target_usage`/`restart_target` 가 `target.host` 사용 |
| `src/mcp_server/tools.py` | `_all_targets` 평탄화, 응답에 host |
| `tests/test_hosts.py` | **신규** — 멀티호스트 파싱/구성 5 |
| `config.yaml.example`, `docs/REMOTE_MINIPC.md` | 멀티호스트(모드 C) 문서화 |

## 운영 메모

- Mac 이 꺼진 동안은 감시 안 됨 — 진짜 24h 는 미니 PC에 직접 설치(모드 A)가 정답.
- Mac RAM 이 상시 80%↑ → Mac system 타겟이 자연히 주의 알림을 낼 수 있음(임계값은 config 로 조정).

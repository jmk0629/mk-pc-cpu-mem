# 원격(SSH) 백엔드 — 현재 PC에서 미니 PC 감시

- **기간**: 2026-06-24
- **유형**: 신규 기능
- **레이어**: pcmon(services·discovery·config·monitor) + mcp_server

## 무엇을 / 배경

"미니 PC에 설치하지 말고 현재 PC(Mac)에서 실행할 수 없나?"는 요청에 따라,
`config.remote.host` 만 주면 모든 측정/제어를 `ssh <host>` 로 수행하는 원격 백엔드를 추가했다.
미니 PC 에 아무것도 설치하지 않고 현재 PC에서 docker/systemd 를 감시·제어한다.

## 구현

### `services.py`
- `_run(cmd, host="")`: host 가 있으면 `["ssh", *opts, host, shlex 인용된 단일 명령]` 로 래핑.
  `shlex.quote` 로 `{{.Name}}\t...` 등 포맷/메타문자 보존. SSH `ControlMaster/ControlPersist` 로 연결 재사용.
- `target_usage(target, host="")`, `_docker_usage/_systemd_usage(.., host)`: 원격 분기.
  systemd cgroup 캐시 키를 `"host:unit"` 로(호스트 간 충돌 방지).
- `_remote_system_usage(host)`: `/proc/stat`(idle/total 차분) + `/proc/meminfo` 로 전체 CPU/RAM.
- `remote_top_processes(host, n, exclude)`: `ps -eo comm,pcpu,pmem --sort=-pmem`.
- `_sysinfo(host)`: 원격 전체 메모리/CPU 수 호스트별 캐시(서비스마다 재조회 방지).
- 재시작/재부팅도 host 인지: docker 원격 재시작 OK(무sudo), systemd 시스템서비스/재부팅은 원격 sudo 필요(실패 시 안내).

### `discovery.py`
- `_docker_names/_systemd_units(host)` + `_run(cmd, host)` 로 원격 자동 발견.

### `config.py` / `monitor.py` / `mcp_server`
- `RemoteConfig{host}` 추가(`cfg.remote.host`).
- `Monitor._sys_metrics/_top`: remote.host 면 원격 메트릭 사용. 메시지에 `@host` 표기.
- `_tick`/`services_text` 가 host 를 전달. MCP `list_services` 도 host 전달.

## 검증 (현재 PC=Mac → 미니 PC=keymedi1, 라이브)

- 원격 자동 발견 5개: open-design, html-pdf-service, caddy, meditv-report, monthly-reminder.
- 원격 측정: open-design 17.8%(docker), meditv-report 2.3%(cgroup), 전체 CPU 5.8%/RAM 16.6%(/proc), 상위 프로세스(ps).
- 텔레그램에 `@keymedi1` 표기로 발송 확인. `pytest -q` → 27 passed(remote 7 추가).

## 보안

- 토큰을 SSH 명령줄/원격에 싣지 않음(텔레그램 호출은 현재 PC에서만). 원격 명령 인자는 `shlex.quote`.
- 원격 sudo 미보유 → 시스템 서비스 재시작/재부팅은 차단/안내(docker 재시작은 가능).

## 변경 파일

| 파일 | 변경 |
|---|---|
| `src/pcmon/services.py` | SSH `_run`, 원격 usage/metrics/restart, 캐시 |
| `src/pcmon/discovery.py` | 원격 발견 |
| `src/pcmon/config.py` | `RemoteConfig` |
| `src/pcmon/monitor.py` | 원격 메트릭/표기, host 전달 |
| `src/mcp_server/tools.py` | host 전달 |
| `tests/test_remote.py` | **신규** — SSH 명령구성/파싱/설정 7 |
| `config.yaml.example`, `docs/REMOTE_MINIPC.md` | 원격 모드 문서화 |

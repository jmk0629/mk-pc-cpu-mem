# 자동 발견 + systemd cgroup 측정 + 미니 PC 라이브 검증

- **기간**: 2026-06-24
- **유형**: 신규 기능 + 원격 검증
- **레이어**: pcmon(discovery·services·config·monitor) + docs

## 무엇을 / 배경

이미지의 "OS 기본 서비스만 빼고 docker 컨테이너 + systemd 서비스를 전부 감시" 동작을
구현하고, 실제 미니 PC(keymedi1, Ubuntu 24.04)에서 읽기 전용으로 검증했다.
감시 코드는 미니 PC 위에서 도는 것이 원칙(SSH 는 배포/검증 수단).

## 구현

### `discovery.py` (신규)
- `discover(cfg)`: `docker ps` + `systemctl list-units --state=running` 수집 → `_filter` 로
  `exclude_services` 부분일치 제외 → `Target(docker|systemd)` 생성.
- `_filter`(순수 함수): `.service` 접미사 무시, 대소문자 무시, 부분 일치 제외(`systemd` → systemd-* 전부).

### `services.py:_systemd_usage` (신규)
- `systemctl show -p MemoryCurrent -p CPUUsageNSec -p ActiveState` 파싱.
- RAM% = MemoryCurrent / `virtual_memory().total`. CPU% = ΔCPUUsageNSec / (Δt·ncpu).
- 누적 CPU 값 차분용 모듈 캐시 `_systemd_cpu_cache`. 첫 호출 prime(0.0), `dt>0`·카운터리셋 가드.

### `config.py` / `monitor.py`
- `DiscoveryConfig`(enabled/docker/systemd/refresh_minutes) 추가.
- `Monitor._refresh_targets`: 명시적 targets + 발견 targets 병합, `refresh_minutes` 주기 가드,
  try/except 로 데몬 보호. `_tick` 첫머리에서 호출.

## 검증 (미니 PC, 읽기 전용 — 기존 /opt/pc-monitor 무관)

- 소스를 `/tmp/pcmon-val` 로 SSH 전송 + venv 구성.
- 자동 발견 12개 → exclude 보강 후 의미있는 대상: open-design, html-pdf-service, caddy, meditv-report.
- cgroup 측정 정확도: open-design 17.8%(docker stats 17.75% 일치), meditv-report 386MB→2.3%.
- **텔레그램 라이브**(MkPcCpuMem_bot): 🟢 시작 + 감시 대상 목록(실측) + 전체 상태 발송 성공.
- `pytest -q` → 20 passed (discovery 6 추가).

## 보안 메모

- 토큰을 SSH 명령줄에 두지 않음(프로세스 테이블 노출 차단). `stdin → umask 077 env 파일` 로 주입 후 검증 끝나고 삭제.
- 노출된 토큰은 운영 전 BotFather `/revoke` 재발급 권장.

## 변경 파일

| 파일 | 변경 |
|---|---|
| `src/pcmon/discovery.py` | **신규** — docker/systemd 자동 발견 + 필터 |
| `src/pcmon/services.py` | `_systemd_usage`(cgroup) + `_to_int`, systemd 라우팅 |
| `src/pcmon/config.py` | `DiscoveryConfig` |
| `src/pcmon/monitor.py` | `_refresh_targets` 주기 재발견 |
| `tests/test_discovery.py` | **신규** — 필터/설정 6 테스트 |
| `config.yaml.example` | discovery 섹션 문서화 |
| `docs/REMOTE_MINIPC.md` | **신규** — 원격/미니PC 설계 설명 |

## 다음 (배포 결정 대기)

미니 PC 정식 24h 배포는 기존 root `/opt/pc-monitor` 교체 여부 + sudo 권한 결정이 필요(운영자 판단).
docker 워크로드(open-design 등) 재시작은 sudo 없이 가능, systemd 시스템 서비스 재시작/재부팅은 sudo 필요.

# system 타겟 타입 추가 + macOS 라이브 검증

- **기간**: 2026-06-24
- **유형**: 신규 기능 + 통합 검증
- **레이어**: pcmon(services) + config + docs

## 무엇을 / 배경

"내 macOS PC 전체를 그냥 감시하자"는 요구에 맞춰, 개별 서비스(docker/process)가 아니라
**PC 한 대 전체(CPU/RAM)를 하나의 감시 대상**으로 보는 `system` 타겟 타입을 추가했다.

## 구현

### `services.py`
- `target_usage`: `type == "system"` → `_system_usage()`(psutil 전체 CPU/RAM, OS 무관) 분기 추가.
- `restart_target`: `type == "system"` → 재시작 대상이 아님을 안내(`"전체 시스템은 재시작 대상이 아닙니다.
  재부팅은 /reboot 를 사용하세요."`). 전체 PC 의 위험 단계에서 '재시작' 버튼을 눌러도 안전하게
  유도 메시지만 반환(우발적 동작 방지). 재부팅은 `control.allow_reboot` 게이트 유지.

### `config.yaml.example`
- targets 주석에 `system` 타입 설명 + 기본 예시(`{name: 내 Mac, type: system, match: local}`)로 교체.
- macOS 기준 `exclude_services`(WindowServer, launchd, bluetoothd, cups …) 반영.

## 검증 (macOS / Darwin, 실제 봇 `@MkPcCpuMem_bot`)

- `system` 타겟 사용률 측정: CPU/RAM 실측 정상, `restart_target` 유도 메시지 정상.
- `pytest -q` → 14 passed (회귀 없음).
- **라이브 텔레그램**: chat_id 자동 수집(getUpdates) → config 주입 → 6개 알림 타입
  (🟢시작·⚠️주의·⚠️시스템경보·🔴위험+버튼·✅복구·🚨긴급) 실제 발송 성공.
- **양방향 제어**: 봇 폴러로 인라인 버튼(재시작/무시) + 슬래시 명령(/status·/top·/services) 응답 확인.
- 빠른 타이밍 데모 설정(alert 0.15분/restart 0.6분)으로 staged 흐름(시작→주의→위험) 동작 확인.

## 운영 메모

- 실 `config.yaml` 은 gitignore(토큰·chat_id 포함, 커밋 금지). 기본 타이밍 5분/20분 유지.
- 토큰이 대화/스크린샷에 노출되었으므로 운영 전 BotFather `/revoke` 재발급 권장.
- macOS 자동 시작은 `deploy/launchd/*.plist` + `deploy/install.sh`.

## 변경 파일

| 파일 | 변경 |
|---|---|
| `src/pcmon/services.py` | `system` 타입 사용률 측정(`_system_usage`) + 재시작 유도 분기 |
| `config.yaml.example` | system 타입 문서화 + macOS exclude_services |
| `docs/features/2026-06-24-system-target-and-macos-live.md` | 본 문서 |

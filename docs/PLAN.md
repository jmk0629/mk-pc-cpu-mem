# 계획 / 로드맵

## P0 — 감시 + 텔레그램 제어 (완료)

- [x] config.yaml 스키마 + 로드(env override) + 권한 게이트
- [x] metrics: 시스템/프로세스 수집 (psutil)
- [x] services: 크로스플랫폼 사용률 + 재시작/재부팅 (docker/systemd/launchd/process)
- [x] state: 정상→주의→위험→복구 상태 머신 + 스누즈
- [x] notifier: 텔레그램 송신 + 알림 메시지 빌더 (이미지 문구 반영)
- [x] telegram_bot: 롱폴링 + 명령(/status·/top·/services·/restart·/reboot·/run) + 버튼 콜백
- [x] monitor: 메인 루프 + heartbeat + 시스템 경보
- [x] watchdog: heartbeat 만료 감지 + 긴급 알림
- [x] deploy: systemd(.service/.timer) + launchd(.plist) + install.sh
- [x] tests: state/config/watchdog 단위 테스트
- [x] MCP 서버 스켈레톤 (get_metrics/services/restart/run)

## P1 — 관측/안정화 (예정)

- [ ] 서비스별 CPU 정확도 향상: systemd cgroup(MemoryCurrent/CPUUsageNSec) 직접 파싱
- [ ] 알림 중복 억제(rate limit) + 알림 히스토리 영속화
- [ ] /status 에 디스크/네트워크/온도 추가
- [ ] config 변경 자동 감지(reload) — SIGHUP

## P2 — MCP 원격 운영/개발 확장 (예정)

- [ ] MCP run_command 를 PTY 세션으로 — 장기 실행/스트리밍 출력
- [ ] 파일 도구(read/write/patch) + git 도구 → 원격 개발
- [ ] Discord 브리지(텔레그램과 동일 Actions 재사용)
- [ ] 인증/감사 로그 — 누가 어떤 제어를 했는지 기록

## 설계 결정 메모

- **psutil 단일 의존으로 크로스플랫폼**: OS별 분기를 services.py 한 곳에 격리.
- **상태 머신 분리**: 알림 정책을 monitor 루프에서 떼어내 테스트 가능하게.
- **위험 동작은 opt-in**: 재부팅/원격 명령은 config 게이트로 기본 차단 (사고 방지).
- **MCP 는 코어 재사용**: 텔레그램과 MCP 가 같은 services/metrics 를 호출 — 로직 중복 없음.

# 미니 PC 원격 감시 — 설계와 소스 설명

이미지의 시스템은 **Ubuntu 미니 PC에서 자체적으로 24시간** 돌며, 그 PC의
docker 컨테이너 + systemd 서비스를 *OS 기본 서비스만 빼고 전부* 감시한다.
이 문서는 그 동작을 mk-pc-cpu-mem 에서 **어떻게 구현했고 어떻게 미니 PC(keymedi1)에서
검증/배포하는지** 소스 기준으로 설명한다.

대상 미니 PC: `chatreey-mini` — Ubuntu 24.04.4, Python 3.12, 4 core / 15 GiB,
docker 컨테이너(`open-design`, `html-pdf-service`, `portainer`) + systemd 서비스 다수.

---

## 1. 핵심 아이디어 — "어디서 실행되는가"

감시 코드는 **감시 대상 PC 위에서** 실행되는 것이 원칙이다(이미지 설계 그대로).
미니 PC는 항상 켜져 있으므로 monitor 데몬을 미니 PC에 올리면 진짜 24시간 감시가 된다.
Mac 같은 개발 PC는 **배포·개발 도구**로만 쓴다(SSH 로 소스 전송/검증).

```
[Mac, 개발/배포]  ──SSH(keymedi1)──►  [Mini PC, 24h 감시 대상 + 실행 위치]
  소스 작성/테스트/git push           pc-monitor (systemd) ── docker/systemd 자체 감시
                                       └ Telegram 알림/제어
```

> SSH 는 **배포 수단**이지 감시 수단이 아니다. 감시 자체는 미니 PC 로컬에서 docker/systemctl 을
> 직접 호출하므로 빠르고 권한 문제(원격 sudo)도 줄어든다.

### 두 가지 실행 모드

| 모드 | 실행 위치 | 설정 | 24h | 용도 |
|---|---|---|---|---|
| (A) 대상 PC에서 실행 | 미니 PC (systemd) | `remote.host: ""` | ✅ 미니 PC가 항상 켜짐 | 정식 운영 |
| (B) 현재 PC에서 원격 감시 | Mac 등 (SSH) | `remote.host: keymedi1` | ⚠️ 현재 PC 켜진 동안만 | 설치 없이 점검/개발 |

모드 (B)는 미니 PC에 **아무것도 설치하지 않고** 현재 PC에서 `ssh keymedi1` 로 docker/systemd 를
들여다본다. 아래 §4.5 참고. 진짜 24시간 감시는 (A)가 정답이다.

---

## 2. 자동 발견 — `src/pcmon/discovery.py`

이미지의 "exclude 빼고 전부 감시"를 구현한 모듈. 명시적 `targets` 를 일일이 적지 않아도 된다.

```
discover(cfg)
  ├─ docker:  `docker ps --format {{.Names}}`           → 컨테이너명 목록
  ├─ systemd: `systemctl list-units --type=service        → 실행 중 유닛 목록
  │            --state=running --no-legend --plain`
  └─ _filter(names, exclude_services)                     → exclude 부분일치 제외
        → Target(type=docker|systemd) 리스트
```

- **필터 규칙**(`_filter`, 순수 함수 → 단위 테스트): exclude 의 한 항목이라도 이름에 부분 일치하면 제외.
  `exclude=['systemd']` 면 `systemd-journald`, `systemd-logind` … 일괄 제외. `.service` 접미사는 매칭 시 무시.
- monitor 는 `discovery.refresh_minutes`(기본 5분)마다 재발견 → **새로 뜬 컨테이너/서비스 자동 편입**
  (`Monitor._refresh_targets`, 주기 가드 + try/except 로 데몬 보호).
- 명시적 `targets` 가 우선(같은 이름이면 명시적 유지).

### 실측 검증 (미니 PC, 읽기 전용)
```
자동 발견 12개: open-design, html-pdf-service, caddy, meditv-report,
  monthly-reminder, thermald, udisks2, unattended-upgrades, upower,
  user@1000, user@1001, wpa_supplicant
→ exclude 보강 후 의미있는 4~5개: open-design, html-pdf-service, caddy, meditv-report(, monthly-reminder)
```

---

## 3. systemd cgroup 정확 측정 — `src/pcmon/services.py:_systemd_usage`

docker 는 `docker stats` 로 바로 %가 나오지만, systemd 서비스는 cgroup 회계를 직접 읽어 환산한다.

```
systemctl show <unit> -p MemoryCurrent -p CPUUsageNSec -p ActiveState
   MemoryCurrent=386273280     (bytes)   → RAM% = MemoryCurrent / 전체메모리 × 100
   CPUUsageNSec=637855042000   (누적 ns)  → CPU% = ΔCPUUsageNSec / (Δt · ncpu) × 100
```

- `CPUUsageNSec` 는 **누적값**이라 두 시점 차분이 필요(psutil prime 과 동일 원리).
  모듈 캐시 `_systemd_cpu_cache[unit] = (monotonic_t, cpu_nsec)` 에 직전 샘플을 저장,
  다음 주기에 구간 평균을 낸다. 첫 호출은 0.0(prime).
- 엣지 가드: `dt > 0`, `cpu_nsec >= prev`(카운터 리셋 방어), 0~100 클램프, 미설정값(`_to_int → -1`)은 미가용.
- 검증: `meditv-report` MemoryCurrent 386 MB → RAM 2.3%(386M/16G), `open-design` docker 17.75% ≈ 측정 17.8% 일치.

---

## 4. 권한 모델 — 미니 PC 에서 무엇을 할 수 있나

| 동작 | 필요 권한 | 미니 PC 현황 |
|---|---|---|
| CPU/RAM/프로세스 수집 | 없음 | ✅ |
| docker 컨테이너 사용률/재시작 | docker 그룹 | ✅ (사용자가 docker 그룹) |
| systemd 서비스 사용률(읽기) | 없음 | ✅ |
| **systemd 시스템 서비스 재시작** | sudo | ⚠️ sudo 비번 필요 |
| **시스템 재부팅** | sudo | ⚠️ + `control.allow_reboot` 게이트 |

> 미니 PC 는 passwordless sudo 가 아니므로, **시스템 서비스 재시작/재부팅**은 sudo 권한 부여가 필요하다.
> docker 컨테이너 재시작은 sudo 없이 동작한다(주요 워크로드 open-design/html-pdf-service 가 docker).

systemd 시스템 서비스 재시작을 무인 자동화하려면 다음 중 하나:
- monitor 를 **root systemd 서비스**로 설치(`deploy/systemd/pc-monitor.service`, `User=root`) — 권장.
- 또는 특정 유닛에 한해 `sudoers` 에 `NOPASSWD: /usr/bin/systemctl restart <unit>` 허용.

---

## 4.5 모드 (B) — 현재 PC에서 원격 감시 (SSH 백엔드)

`config.yaml` 에 `remote.host: keymedi1` 만 주면, 모든 측정/제어가 `ssh keymedi1` 로 실행된다.
미니 PC 에는 설치가 필요 없다.

```yaml
remote:    { host: keymedi1 }
discovery: { enabled: true }        # 원격 docker/systemd 자동 발견
telegram:  { token: "...", chat_ids: [...] }
```
```bash
# 현재 PC(Mac)에서:
python -m pcmon.monitor               # ssh keymedi1 로 미니 PC 감시 → 텔레그램 알림
```

구현(`services.py` / `discovery.py`):
- **`_run(cmd, host)`**: host 가 있으면 `ssh <host> "<cmd>"` 로 실행. 각 인자를 `shlex.quote` 로
  안전하게 인용(원격 셸 word-split·`{{.Name}}` 같은 메타문자 오해석 방지).
- **연결 재사용**: SSH `ControlMaster=auto` + `ControlPersist=60s` 로 매 주기 재접속 비용 절감.
- **원격 시스템 메트릭**: `/proc/stat`(두 시점 차분) + `/proc/meminfo` 파싱(`_remote_system_usage`),
  상위 프로세스는 `ps -eo comm,pcpu,pmem`(`remote_top_processes`). 원격엔 psutil 불필요.
- **원격 정적정보 캐시**: 전체 메모리/CPU 수는 호스트별 1회만 조회(`_sysinfo`).
- 알림/명령에 대상이 `@keymedi1` 로 표기되어 로컬과 구분된다.
- **제약**: docker 재시작은 원격에서도 sudo 불필요. systemd **시스템 서비스** 재시작/재부팅은
  원격 sudo 가 필요(없으면 실패 메시지). process/launchd 타입은 원격 미지원.

> 토큰은 SSH 명령줄에 절대 싣지 않는다(원격 프로세스 테이블 노출). 토큰은 현재 PC의 `config.yaml`
> 또는 `PCMON_TELEGRAM_TOKEN` env 에만 둔다 — 텔레그램 호출은 현재 PC에서 일어나므로 원격에 토큰이 가지 않는다.

## 5. 배포 방법 (미니 PC)

### 5-1. SSH 로 소스 전송 + 검증(읽기 전용, 무해)
```bash
# Mac 에서:
tar czf - -C src pcmon | ssh keymedi1 'mkdir -p /tmp/pcmon-val && tar xzf - -C /tmp/pcmon-val'
ssh keymedi1 'cd /tmp/pcmon-val && python3 -m venv .venv && .venv/bin/pip install -q psutil PyYAML requests'
# config-mini.yaml(discovery.enabled=true) + 토큰은 stdin→600 env 파일로 주입(명령줄 노출 금지)
```

### 5-2. 정식 설치 (24시간, systemd)
`deploy/install.sh` 가 OS 분기(Linux=systemd). 미니 PC 에선:
```bash
sudo ./deploy/install.sh          # /opt/pc-monitor + venv + pc-monitor.service + pc-watchdog.timer
# config.yaml 에 token/chat_ids 채우고:
sudo systemctl restart pc-monitor
```

### 토큰 취급 원칙
- 토큰을 **SSH 명령줄/원격 프로세스 인자에 두지 않는다**(프로세스 테이블 노출). `stdin → umask 077 파일`
  또는 `config.yaml`(루트 소유, 권한 제한)로만 전달.
- 노출된 토큰은 BotFather `/revoke` 로 재발급.

---

## 6. 기존 배포물 주의

미니 PC `/opt/pc-monitor`(root 소유)에 **이미 단일 파일형 monitor.py/watchdog.py 가
`pc-monitor.service` + `pc-watchdog.timer` 로 가동 중**이다(이미지의 원본 시스템). mk-pc-cpu-mem 로
교체하려면 sudo 가 필요하며, 같은 텔레그램 채팅을 쓰면 알림이 중복되므로 **둘 중 하나만** 운영한다.
교체 여부는 운영자가 결정한다([[PLAN]] 의 배포 항목 참고).

---

## 7. 관련 소스/문서

- 자동 발견: `src/pcmon/discovery.py`, 설정 `discovery.*`
- cgroup 측정: `src/pcmon/services.py:_systemd_usage`
- 주기 재발견: `src/pcmon/monitor.py:_refresh_targets`
- 런타임 흐름 전반: `docs/WORKFLOW.md`
- 모듈 경계/원칙: `docs/ARCHITECTURE.md`

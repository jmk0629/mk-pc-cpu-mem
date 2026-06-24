# mk-pc-cpu-mem — 실수 메모리 (MISTAKES ledger)

작업을 시작하기 전에 이 파일을 먼저 읽는다. 과거 실수를 반복하지 않기 위함.
새 실수를 발견하면 `/log-mistake` 로 **맨 위에 최신순** 기록한다.

포맷:
```
## [YYYY-MM-DD] <한 줄 제목>
- **증상**: ...
- **원인**: ...
- **수정**: ...
- **재발방지**: ...
- **관련 파일**: path:line
```

---

## [2026-06-24] (시드) psutil cpu_percent 첫 호출은 항상 0.0

- **증상**: 프로세스/시스템 CPU% 가 첫 측정에서 0.0 으로 나와 임계 판정이 안 됨.
- **원인**: `psutil.cpu_percent()`/`Process.cpu_percent()` 는 직전 호출 이후의 구간 평균을 반환한다. 첫 호출은 기준점만 잡고 0.0.
- **수정**: 시스템은 `cpu_percent(interval=...)` 로 블로킹 측정. 프로세스는 prime(`cpu_percent(None)`) 후 두 번째 호출로 측정(`metrics.top_processes`, `services._process_usage`).
- **재발방지**: 새로 프로세스 CPU 를 재는 코드는 반드시 prime 패턴을 따른다.
- **관련 파일**: `src/pcmon/metrics.py`, `src/pcmon/services.py`

---
name: commit-push
description: mk-pc-cpu-mem 변경을 의미 단위로 stage → conventional commit(한국어 제목) → git push origin main. 시크릿(config.yaml/.env)·force push 를 차단하고 안전하게 자동 커밋/푸시한다.
---

# commit-push

mk-pc-cpu-mem 변경사항을 안전하게 커밋하고 `https://github.com/jmk0629/mk-pc-cpu-mem` 로 푸시한다.

## 입력 (선택)

- `message` — 커밋 메시지(생략 시 변경 내용으로 자동 작성)
- `scope` — 범위 힌트 (예: `pcmon`, `mcp`, `deploy`, `docs`)

## 동작

1. **현황 파악**: `git status`, `git diff`, `git log --oneline -5` 를 병렬 실행.
2. **시크릿 가드** (차단 = 커밋 중단):
   - `config.yaml`, `*.env`, `pcmon.env`, `*secret*`, `*credential*` 가 staging 대상이면 **제외**하고 경고.
   - diff 에 텔레그램 봇 토큰 패턴(`\d{8,10}:[A-Za-z0-9_-]{35}`), `Bearer ` 하드코딩이 보이면 중단 후 보고.
3. **stage**: 관련 파일만 명시적으로 `git add <files>`. `git add -A`/`.` 지양(시크릿 혼입 방지).
4. **commit**: Conventional Commits + **한국어 제목**(타입 프리픽스/식별자는 영어).
   - `feat:` `fix:` `refactor:` `docs:` `test:` `chore:` `style:`
   - 제목 한 줄(72자 이내) + 본문(왜). 끝에 `Co-Authored-By: Claude` 추가.
5. **push**: `git push origin main` (최초엔 `git push -u origin main`).
   - **force push 절대 금지.** 거부되면(원격 선행) `git pull --rebase` 후 재시도, 충돌은 사용자에게 보고.

## 금지

- `git push --force` / `-f`, `git reset --hard`
- `config.yaml`/`.env` 등 시크릿 파일 커밋
- 사용자 미확인 대규모 삭제

## 출력

커밋 해시 + 푸시 결과 + (있다면) 제외한 시크릿 파일 목록.

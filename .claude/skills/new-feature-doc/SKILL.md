---
name: new-feature-doc
description: 기능 추가/수정을 완료했을 때 docs/features/YYYY-MM-DD-<slug>.md 로 내용과 날짜를 기록한다. mk-hospital/mk-health-app 과 동일한 히스토리 컨벤션.
---

# new-feature-doc

기능 단위 작업이 끝나면 `docs/features/` 에 날짜별 기록을 남긴다.

## 입력

- `slug` — 파일명 슬러그(영문 kebab-case, 예: `disk-metric`)
- `title` — 한국어 제목

## 동작

1. 오늘 날짜로 `docs/features/<YYYY-MM-DD>-<slug>.md` 생성(이미 있으면 이어쓰기 확인).
2. 아래 템플릿으로 작성:

```markdown
# <제목>

- **기간**: YYYY-MM-DD
- **유형**: 신규 기능 | 버그 수정 | 리팩터 | 문서
- **레이어**: pcmon | mcp_server | deploy | docs | 하네스

## 무엇을 / 배경
...

## 구현
... (모듈별로 무엇을 어떻게)

## 검증
- pytest 결과, 스모크 테스트

## 변경 파일
| 파일 | 변경 |
|---|---|

## 다음
... (있으면 PLAN.md 와 연결)
```

3. 큰 변화면 `docs/PLAN.md` 체크박스/로드맵도 함께 갱신.

## 주의

- 시크릿(토큰/chat_id) 기재 금지.
- "왜" 중심으로. 코드에서 자명한 것은 생략, 판단/트레이드오프를 남긴다.

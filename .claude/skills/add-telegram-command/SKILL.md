---
name: add-telegram-command
description: mk-pc-cpu-mem 에 새 텔레그램 명령(/foo)을 추가할 때 핸들러·레지스트리·도움말·README·테스트를 한 번에 동기화한다. 한 곳만 고쳐 명령이 도움말/문서와 어긋나는 드리프트를 방지.
---

# add-telegram-command

새 슬래시 명령을 **네 군데 동시에** 갱신해 드리프트를 막는다.

## 입력 (yaml 또는 대화)

```yaml
command: disk                 # 슬래시 없이
description: 디스크 사용률 조회   # 도움말/README 표기
needs_auth: true              # 권한 게이트(거의 항상 true). 위험 동작이면 버튼 확인 추가
body: |                       # 핸들러가 만들 텍스트 로직 설명
  psutil.disk_usage('/') 집계 → "디스크: x% 사용" 텍스트 반환
```

## 동작 — 다음 4곳을 모두 수정

1. **핸들러 메서드** `src/pcmon/telegram_bot.py` 의 `TelegramBot` 에 `_cmd_<command>(self, arg, chat) -> str` 추가.
   - 단순 조회면 `self.actions.<...>` 를 호출하거나 직접 텍스트 생성.
   - 위험 동작(재시작/재부팅류)이면 `control.allow_*` 게이트 확인 + 인라인 버튼으로 확인받기.
2. **레지스트리** 같은 파일의 `_COMMANDS` dict 에 `"<command>": TelegramBot._cmd_<command>` 추가.
3. **도움말** 같은 파일의 `_help_text()` 에 한 줄 추가.
4. **문서** `README.md` 의 "텔레그램 명령" 표 + (필요시) Actions 프로토콜에 메서드 시그니처 추가.
5. **테스트** `tests/` 에 핸들러 로직 단위 테스트(가능한 부분). 외부 호출은 가드 경로 검증.

## 검증

- `pytest -q` 통과.
- 권한 게이트: `_authorized` 통과 사용자만 실행되는지 확인(공개 명령 금지).
- 위험 명령이면 `control.allow_*` 게이트 + 버튼 확인이 있는지 재확인.

## 마무리

`telegram-security-reviewer` 에이전트로 인젝션/게이트 점검 → `/new-feature-doc` → `/commit-push`.

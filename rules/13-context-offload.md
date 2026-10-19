---
always_load: true
reason: "대용량 출력 오프로드는 작업 종류·경로와 무관하게 매 세션 발동한다 — paths glob 으로 좁히면 정작 필요한 순간(긴 tool 출력 직전)에 로드되지 않는다"
---

# 13. Context Offload (대용량 산출물 무손실 오프로드)

**긴 tool 출력을 컨텍스트에 쏟기 직전 → `offload`로 우회. 원본은 파일에, 컨텍스트엔 stub+id만.**

TencentDB-Agent-Memory의 단기 컨텍스트 오프로드(node_id 역추적)를 Claude Code에 이식한 규약.
handoff(세션 종료)·planning-with-files(계획 추적)와 층위가 다름 — **작업 중 대용량 산출물 전용**.

## 발동 (명시적 wrapper만 — 자동 hook 없음)

수백 줄 이상이 예상되는 출력을 컨텍스트에 그대로 들이기 직전:

- 명령 출력: `~/.claude/bin/offload --head 20 -- <command>`
- 대용량 파일: `~/.claude/bin/offload --file <path>`
- 생성/붙여넣은 텍스트: `… | ~/.claude/bin/offload --stdin`

컨텍스트엔 `[ref:<id>] <src> · N lines · …` stub + head만 남는다. 원본은 `~/.claude/refs/<id>.md`(무손실).

## 회수 (역추적 = grep, 별도 DB 없음)

- 전체 원본: `~/.claude/bin/offload --get <id>` (= node_id 역추적)
- 보관 목록: `~/.claude/bin/offload --list`
- id는 content-addressed(sha) — 같은 출력 재오프로드 시 동일 id, 멱등.

## 쓰지 말아야 할 때

- 짧은 출력(수십 줄): 그냥 직접 출력. 오프로드는 오버헤드.
- 사용자가 즉시 봐야 하는 결과: 컨텍스트에 직접.
- 영구 보존 사실/선호: 그건 장기 메모리 영역. refs는 세션 작업용 휘발.

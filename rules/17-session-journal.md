# 17. Session Journal (실시간 세션 저널 → /handoff 대체 보조)

**의미 있는 턴마다 세션 저널에 기여하라.** 목적: /handoff 없이 세션 이어하기.
저널: `$HARNESS_JOURNAL_DIR/<날짜>-<세션>.md`(기본 `~/notes/Sessions`, Obsidian 볼트 폴더 권장) — Stop 훅(`session-journal-capture.sh`)이
객관 타임라인(요청·변경파일)을 매 턴 자동 append.
현재 저널 경로는 **`~/.claude/sessions/journal-ptr/<내 session_id>`**, 없으면 `~/.claude/sessions/current-journal`.
**신규 저널은 `~/.claude/sessions/journal-staging/`에서 시작**하고, 타임라인 2건+ 또는 의미노트 1건+이
생겨야 볼트로 승격된다(1턴 껍데기 오염 차단). 미승격분은 7일 후 자동 삭제 —
**네가 의미 노트를 안 남기면 그 세션 기록은 볼트에 남지 않는다.** 경로는 위 순서로 읽어라(승격 시 바뀜).

> **왜 sid별인가**: `.pending-note`·`current-journal` 이 **전역 단일 파일**이면
> 병렬 세션이 같은 파일을 두고 다툰다 — 남의 노트를 내 저널에 접합하고 원본을 지울 수 있다.
> 파일명에 sid 를 넣으면 두 세션이 같은 파일을 쓸 수 없어 경합이 **구조적으로 0** 이 된다.

## 매 "의미 있는" 턴 끝에 (실제 작업 진전이 있을 때만)

1. **의미 노트** — **`~/.claude/sessions/pending-notes/<내 session_id>.md`** 에 1~2줄 Write:
   `한 일(무엇·왜) · 막힌 점 · 다음 스텝`. Stop 훅이 이걸 이번 타임라인 항목에 접합하고 파일을 지운다(소비형).
   - session_id 는 **`$CLAUDE_CODE_SESSION_ID` 환경변수에서만** 얻는다 (`echo "$CLAUDE_CODE_SESSION_ID"`).
     **`journal-ptr/` 를 뒤져 sid 를 고르지 마라** — 그 디렉토리엔 *다른 세션들의* sid 가 함께 들어있어
     남의 sid 를 골라 남의 노트에 덮어쓰게 된다(고치려던 경합의 재도입). 게다가 내 journal-ptr 파일은
     첫 Stop 전엔 없어서 1턴차엔 실패한다. env 는 1턴차에도 유효하고 모호성이 0 이다.
   - **전역 단일 파일에 쓰지 마라** — 다른 세션이 가져간다.
2. **요약·다음·링크 갱신** — 경로는 위 `journal-ptr/<sid>` 를 읽어 얻고, 저널의 세 곳을 Edit:
   - `> [!summary] 요약` — 세션 전체 러닝 요약(1~3줄)
   - `**▶ 다음 스텝:**` — 지금 기준 다음 액션
   - `**🔗 관련 보드:**` — 진행 보드를 쓴다면 관련 카드를 `[[카드제목]]`으로 링크(선택)

## 쓰지 말아야 할 때

- 단순 대화·조회 턴 — 저널 오염 금지. 진전이 있을 때만(§11).
- 타임라인 항목을 손으로 쓰지 마라 — append는 훅이 자동(중복 방지). 나는 `pending-notes/<sid>.md`와 요약/다음/링크만 만진다.
- 저널이 곧 연속성 자산 → 세션 끝 `/handoff`는 이제 선택. 단 다일(多日)·복잡 작업의 깊은 학습 보존이 필요하면 여전히 /handoff 권장.

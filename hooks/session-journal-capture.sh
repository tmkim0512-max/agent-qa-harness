#!/usr/bin/env bash
# Stop 훅: 매 턴 끝에 세션별 마크다운 저널(Obsidian 등 노트 볼트)에 타임라인 APPEND(롤링X → 히스토리 유지).
# 객관(요청·변경파일) + LLM이 pending-notes/<sid>.md 에 남긴 의미노트를 한 항목으로 접합. 목적: /handoff 없이 세션 이어하기.
# 절대 차단 안 함(항상 exit 0). 저널 위치는 HARNESS_JOURNAL_DIR (기본 ~/notes/Sessions).
IN=$(cat)
# 세션 밖 자동화 워커(claude -p 루프 등)는 스킵 — 안 거르면 **워커의 Stop 훅이 사람 세션의
# 의미노트를 소비(삭제)** 한다. 정상 대화형 세션엔 이 마커가 없다.
[ -n "${CLAUDE_HEADLESS_WORKER:-}" ] && exit 0
[ -n "${RALPH_SESSION:-}" ] && exit 0
pick(){ printf '%s' "$IN" | python3 -c "import sys,json;print(json.load(sys.stdin).get('$1',''))" 2>/dev/null; }
CWD=$(pick cwd); [ -z "$CWD" ] && CWD="$PWD"
SID=$(pick session_id); TRANSCRIPT=$(pick transcript_path)
[ -z "$SID" ] && [ -n "$TRANSCRIPT" ] && SID=$(basename "$TRANSCRIPT" .jsonl)
[ -z "$SID" ] && exit 0
SHORT=${SID:0:12}

DIR="${HARNESS_JOURNAL_DIR:-$HOME/notes/Sessions}"; STAGE="$HOME/.claude/sessions/journal-staging"
mkdir -p "$DIR" "$STAGE" "$HOME/.claude/sessions/pending-notes" 2>/dev/null
# 신규 저널은 staging에서 시작 → 실질 내용(타임라인 2건+ 또는 의미노트 1건+)이 생겨야 볼트로 승격.
# 1턴짜리 껍데기가 볼트를 오염시키는 걸 구조적으로 차단.
JOURNAL=$(ls "$DIR"/*-"$SHORT".md 2>/dev/null | head -1)          # 승격된 저널 우선 재사용
[ -z "$JOURNAL" ] && JOURNAL=$(ls "$STAGE"/*-"$SHORT".md 2>/dev/null | head -1)
[ -z "$JOURNAL" ] && JOURNAL="$STAGE/$(date +%Y%m%d)-$SHORT.md"

if [ ! -f "$JOURNAL" ]; then                                      # 최초 생성 = 헤더 + 요약/다음/링크 골격
  {
    printf -- '---\ntype: session-journal\nsession: %s\nstarted: %s\nstatus: active\ntags: [session, journal]\n---\n\n' \
      "$SID" "$(date '+%Y-%m-%d %H:%M:%S')"
    printf '# 세션 저널 · %s\n\n> [!summary] 요약\n> _(진행되며 갱신)_\n\n**▶ 다음 스텝:** _(갱신 예정)_\n\n**🔗 관련 보드:** \n\n## 타임라인\n' "$SHORT"
  } > "$JOURNAL" 2>/dev/null
fi

LASTMSG=""                                                        # 마지막 user 프롬프트(시스템/툴 블록 제외)
if [ -n "$TRANSCRIPT" ] && [ -f "$TRANSCRIPT" ]; then
  LASTMSG=$(python3 - "$TRANSCRIPT" <<'PY' 2>/dev/null
import sys, json
# 사용자 요청이 아닌 툴/터미널 블록. 종전 필터가 <task-notification>·<bash-stdout> 을 안 걸러
# 요청항목의 상당 부분이 이 노이즈였다.
SKIP = ("<system-reminder", "<command", "<local-command", "<task-notification",
        "<bash-input", "<bash-stdout", "<bash-stderr")
last = ""
skipped = 0
for ln in open(sys.argv[1], encoding="utf-8"):
    try: e = json.loads(ln)
    except Exception: continue
    if e.get("type") != "user": continue
    c = e.get("message", {}).get("content")
    if isinstance(c, str):
        t = c.strip()
        if t.startswith(SKIP): skipped += 1; t = ""
    elif isinstance(c, list):
        parts = []
        for b in c:
            if not (isinstance(b, dict) and b.get("type") == "text"): continue
            bt = b.get("text","").strip()
            if not bt: continue
            if bt.startswith(SKIP): skipped += 1; continue
            parts.append(bt)
        t = " ".join(parts).strip()
    else: t = ""
    if t: last = t
# 빈 칸은 "정보 없음"과 구별이 안 된다 — 걸러서 남은 게 없다는 사실을 표시한다(§12)
if not last and skipped: last = "(툴 알림만 있음 — 사용자 요청 텍스트 없음)"
print(last[:200].replace("\n", " "))
PY
)
fi

GIT=""                                                            # git 변경 파일(repo일 때만)
if git -C "$CWD" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  GIT=$(git -C "$CWD" status --short 2>/dev/null | head -6 | tr '\n' ';' | sed 's/;$//')
fi

# LLM 의미노트 — **sid별 파일이 정본**(파일명이 sid 라 세션 간 경합 구조적으로 0).
# 단일 .pending-note 면 병렬 세션이 남의 노트를 자기 저널에 접합하고 원본을 지울 수 있다.
PDIR="$HOME/.claude/sessions/pending-notes"
NOTE=""
MINE="$PDIR/$SID.md"
[ -f "$MINE" ] && { NOTE=$(cat "$MINE" 2>/dev/null); rm -f "$MINE" 2>/dev/null; }

{                                                                 # 타임라인 항목 APPEND
  echo "- **$(date '+%H:%M')** · 요청: ${LASTMSG:-—}"
  # 다중 줄 노트: 2번째 줄부터 들여쓰기만 줘야 마크다운 중첩이 안 깨지고 :72 승격 카운터도 1건으로 센다
  [ -n "$NOTE" ] && printf '%s\n' "$NOTE" | awk 'NR==1{print "  - " $0; next}{print "    " $0}'
  [ -n "$GIT" ] && echo "  - 변경: \`$GIT\`"
} >> "$JOURNAL" 2>/dev/null

case "$JOURNAL" in                                                # staging → 볼트 승격 판정
  "$STAGE"/*)
    ITEMS=$(grep -c '^- \*\*' "$JOURNAL" 2>/dev/null || echo 0)
    NOTES=$(grep '^  - ' "$JOURNAL" 2>/dev/null | grep -vc '^  - 변경: ')
    if [ "${ITEMS:-0}" -ge 2 ] || [ "${NOTES:-0}" -ge 1 ]; then
      mv "$JOURNAL" "$DIR/" 2>/dev/null && JOURNAL="$DIR/$(basename "$JOURNAL")"
    fi
    ;;
esac
# sid별 포인터가 정본. current-journal 은 단일 세션용 fallback 포인터(룰 17 참조).
mkdir -p "$HOME/.claude/sessions/journal-ptr" 2>/dev/null
printf '%s' "$JOURNAL" > "$HOME/.claude/sessions/journal-ptr/$SID" 2>/dev/null
printf '%s' "$JOURNAL" > "$HOME/.claude/sessions/current-journal" 2>/dev/null

STAMP="$HOME/.claude/sessions/.journal-gc-stamp"                  # staging GC: 미승격 껍데기 7일 TTL (하루 1회)
if [ -z "$(find "$STAMP" -mtime -1 2>/dev/null)" ]; then
  find "$STAGE" -name '*.md' -mtime +7 -delete 2>/dev/null
  touch "$STAMP" 2>/dev/null
fi

exit 0

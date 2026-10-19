#!/usr/bin/env python3
"""destructive_git_guard — 비가역 git 명령 차단 (PreToolUse:Bash).

공개판 주: 원본은 "다른 세션이 이 트리를 점유 중" 맥락을 차단 사유에 붙이는 교차세션 조회를
함께 했으나, 그 부분은 개인 세션 레지스트리에 의존해 이 저장소에서는 뺐다.

차단(비가역 2종만):
  · git push -f / --force        원격 히스토리는 되돌릴 수 없다
  · git reset --hard             미커밋 변경은 reflog 로도 복구되지 않는다
조언(차단 아님):
  · git checkout . / git restore . / git clean -f(d)   — 사고 이력 0건이라 차단 근거 없음

설계 원칙 — **확신이 안 서면 차단하지 말고 경고한다.**
  · 따옴표 문자열·heredoc 본문·읽기전용 명령(grep/echo/cat…)은 판정 대상에서 뺀다.
    가드 훅은 정상 명령(mktemp 정리, 레이블 문자열, 읽기전용 grep 등)을 오차단하기 쉽다.
    이 훅이 그걸 반복하면 안 된다.
  · 자기 오류로는 절대 차단하지 않는다 — 파싱/정규식/조회 예외는 전부 exit 0.

kill-switch:
  GIT_GUARD=0                    이 훅 전체 (env 또는 **명령 문자열 안**에 포함 → 1회 우회)
  GIT_GUARD_MODE=warn            차단 → 경고로 강등

py3.9 (/usr/bin/python3) 호환 — PEP604 유니온 금지.
"""
from __future__ import annotations

import json
import os
import re
import sys
from typing import Any, Dict, List, Optional, Tuple

MAX_LEN = 20000  # ReDoS 상한
ADVISE_ENV = "GIT_GUARD_MODE"
OVERRIDE_TOKEN = "GIT_GUARD=0"

# git 글로벌 옵션( -C <path> / --git-dir=… )을 건너뛴다.
# 이게 없으면 `git -C <worktree> push -f` 가 통과한다 — 옵션을 끼워 단순 패턴 검사를
# 빠져나가는 대표적인 형태다.
_G = r"\bgit(?:\s+-[Cc]\s+\S+|\s+--?[\w=./:@-]+)*"

BLOCK_RULES = [
    (
        re.compile(_G + r"\s+push\b[^;&|\n]*?(?:\s-f\b|\s--force\b(?!-))"),
        "git push --force",
        "원격 히스토리를 되돌릴 수 없게 덮어씁니다. 남이 그 브랜치를 보고 있으면 그 사람 작업이 사라집니다.",
        "대안: git push --force-with-lease  (남의 푸시를 덮게 되면 실패해서 알려준다)",
    ),
    (
        re.compile(_G + r"\s+reset\b[^;&|\n]*?\s--hard\b"),
        "git reset --hard",
        "워킹트리의 미커밋 변경이 사라집니다. reflog 는 커밋만 되살립니다 — 미커밋은 복구 불가입니다.",
        "대안: git worktree add --detach <tmp> origin/main  ",
    ),
]

# dry-run(-n / --dry-run)은 **아무것도 지우지 않는다.** 여기에 삭제 조언을 붙이면
# 거짓 사실이 모델 컨텍스트로 주입된다 — 차단이 아니라 조언이어도 고쳐야 한다.
_DRYRUN_RE = re.compile(r"(?:\s--dry-run\b|\s-[a-zA-Z]*n[a-zA-Z]*\b)")

# (정규식, 라벨, 사유, 이 정규식이 걸리면 조언 생략)
ADVISE_RULES = [
    (re.compile(_G + r"\s+checkout\s+\.(?=\s|$)"), "git checkout .",
     "추적 중인 파일의 미커밋 수정이 전부 되돌아갑니다.", None),
    (re.compile(_G + r"\s+restore\s+\.(?=\s|$)"), "git restore .",
     "추적 중인 파일의 미커밋 수정이 전부 되돌아갑니다.", None),
    (re.compile(_G + r"\s+clean\b[^;&|\n]*?(?:\s-[a-zA-Z]*f[a-zA-Z]*\b|\s--force\b)"), "git clean -f",
     "untracked 파일이 삭제됩니다 (다른 세션의 미저장 산출물 포함 가능).", _DRYRUN_RE),
]

# 첫 실행 토큰이 이 안에 있으면 그 세그먼트는 판정하지 않는다(읽기 전용).
RO_HEADS = {
    "grep", "rg", "ag", "ack", "echo", "printf", "cat", "bat", "less", "head",
    "tail", "wc", "jq", "fd", "find", "ls", "sort", "uniq", "diff", "comm", "man",
}
_ASSIGN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
_WRAPPERS = {"sudo", "command", "env", "nohup", "time", "exec", "builtin"}
_HEREDOC_RE = re.compile(r"<<-?\s*['\"]?([A-Za-z_][A-Za-z0-9_]*)['\"]?[\s\S]*?^\1", re.M)
_QUOTED_RE = re.compile(r"'[^']*'|\"[^\"]*\"")
# 줄머리 또는 공백 뒤의 `#` 부터 줄 끝까지 = 셸 주석. 실행되지 않으므로 판정 대상이 아니다.
# `main#frag` / `--grep=#123` 처럼 앞에 공백이 없는 `#` 은 주석이 아니라 인자다 — 건드리지 않는다.
# 개행은 먹지 않는다(`[^\n]*`) — segments() 의 줄 단위 분리를 보존해야 한다.
_COMMENT_RE = re.compile(r"(?m)(?:^|(?<=\s))#[^\n]*")
_SPLIT_RE = re.compile(r"&&|\|\||[;\n|]")


def sanitize(cmd: str) -> Optional[str]:
    """판정용 텍스트. None = 판독 불가 → 통과(fail-open).

    순서가 load-bearing:
      1. heredoc — 델리미터가 따옴표를 쓰므로(`<<'EOF'`) 따옴표보다 먼저 지운다.
      2. 따옴표 문자열.
      3. 주석 — 따옴표를 먼저 지운 뒤라야 문자열 안 `#`(URL 프래그먼트 등)을 오제거하지 않는다.

    주석 제거로 차단력이 줄지 않는다 — 실제 실행되는 명령은 언제나 `#` **앞**에 있고
    그 부분은 그대로 남는다(`git reset --hard HEAD  # 메모` → 앞부분이 걸려 차단).
    """
    if len(cmd) > MAX_LEN:
        return None
    try:
        cmd = _HEREDOC_RE.sub(" ", cmd)
        cmd = _QUOTED_RE.sub(" ", cmd)
        cmd = _COMMENT_RE.sub(" ", cmd)
    except Exception:
        return None
    return cmd


def segments(text: str) -> List[str]:
    """읽기전용 세그먼트를 걸러낸 판정 대상만 반환."""
    out = []
    for seg in _SPLIT_RE.split(text):
        toks = seg.split()
        i = 0
        while i < len(toks) and (_ASSIGN_RE.match(toks[i]) or toks[i] in _WRAPPERS):
            i += 1
        if i < len(toks):
            head = os.path.basename(toks[i])
            if head in RO_HEADS:
                continue
        out.append(seg)
    return out


def evaluate(command: str) -> Tuple[List[Tuple[str, str, str]], List[Tuple[str, str]]]:
    """(blocks, advisories). 각 blocks 항목 = (label, why, alternative)."""
    text = sanitize(command)
    if text is None:
        return [], []
    segs = segments(text)
    blocks: List[Tuple[str, str, str]] = []
    advis: List[Tuple[str, str]] = []
    for seg in segs:
        for rx, label, why, alt in BLOCK_RULES:
            if rx.search(seg) and all(b[0] != label for b in blocks):
                blocks.append((label, why, alt))
        for rx, label, why, skip_rx in ADVISE_RULES:
            if skip_rx is not None and skip_rx.search(seg):
                continue  # dry-run — 실제로 아무것도 지우지 않는다
            if rx.search(seg) and all(a[0] != label for a in advis):
                advis.append((label, why))
    return blocks, advis


def _deny(label_lines: List[str]) -> int:
    msg = "\n".join(label_lines)
    sys.stderr.write(msg + "\n")
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": msg,
    }}, ensure_ascii=False))
    return 2


def _advise(text: str) -> int:
    sys.stderr.write(text + "\n")
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "additionalContext": text,
    }}, ensure_ascii=False))
    return 0


def main() -> int:
    if os.environ.get("GIT_GUARD") == "0":
        sys.stderr.write("[destructive_git_guard] DISABLED via GIT_GUARD=0\n")
        return 0

    raw = sys.stdin.read()
    payload: Dict[str, Any] = json.loads(raw) if raw.strip() else {}
    if payload.get("tool_name") != "Bash":
        return 0
    command = (payload.get("tool_input") or {}).get("command") or ""
    if not command.strip() or "git" not in command:
        return 0

    if OVERRIDE_TOKEN in command:
        sys.stderr.write("[destructive_git_guard] in-band override (%s) — 통과\n" % OVERRIDE_TOKEN)
        return 0

    blocks, advis = evaluate(command)
    if not blocks and not advis:
        return 0

    warn_mode = os.environ.get(ADVISE_ENV, "block").lower() == "warn"

    lines: List[str] = []
    if blocks:
        head = "🛑 파괴적 git 명령 차단" if not warn_mode else "⚠ 파괴적 git 명령 (warn 모드 — 통과시킴)"
        lines.append(head)
        for label, why, alt in blocks:
            lines.append("  · %s — %s" % (label, why))
            lines.append("    %s" % alt)
    if advis:
        lines.append("⚠ 되돌릴 수 없는 워킹트리 변경 주의")
        for label, why in advis:
            lines.append("  · %s — %s" % (label, why))
    if blocks and not warn_mode:
        lines.append("정말 필요하면 명령 앞에 %s 를 붙여 1회 우회: `%s git ...`"
                     % (OVERRIDE_TOKEN, OVERRIDE_TOKEN))
        lines.append("(훅 전체 비활성: export GIT_GUARD=0 / 경고 강등: %s=warn)" % ADVISE_ENV)
        return _deny(lines)
    return _advise("\n".join(lines))


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # 자기 오류로는 절대 차단하지 않는다 (§12 No Silent Failure — 사유는 남긴다)
        sys.stderr.write("[destructive_git_guard] fail-open: %s: %s\n" % (type(e).__name__, e))
        sys.exit(0)

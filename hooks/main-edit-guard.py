#!/usr/bin/env python3
# PreToolUse 훅: §15 전면 위임을 강제한다. 메인 스레드의 파일 수정 경로를 막는다.
#   (1) 파일툴  Write|Edit|MultiEdit|NotebookEdit
#   (2) Bash    인플레이스 편집·파일생성 명령 + `>`/`>>` 리다이렉트
#   (3) MCP     serena/obsidian 의 쓰기 계열 툴 (읽기 계열은 건드리지 않는다)
# 서브에이전트 호출은 무조건 통과시킨다.
#
# 판별 근거(headless 실측 — claude -p + --settings 로 페이로드 덤프):
#   서브에이전트 payload 에만 agent_id/agent_type 이 붙는다. 메인엔 두 키가 아예 없다.
#   session_id·transcript_path 는 메인/서브가 완전히 동일 → 그걸론 구분 불가.
#
# fail-open 설계: 파싱 실패·경로 필드 부재·변수 경로 = 통과(+stderr 경고). 이 가드는
# 컨텍스트 보존 규율이지 보안 경계가 아니다. 오탐 1건이 전체 작업을 마비시키는 쪽이 훨씬 비싸다.
# 그래서 git/npm/pip 등 내부적으로 파일을 쓰는 빌드·VCS 명령은 의도적으로 통과시킨다.
import fnmatch, json, os, re, shlex, sys

TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit"}
H = os.path.expanduser("~")
# 세션저널 승격본 위치 — session-journal-capture.sh 와 같은 환경변수를 본다.
JOURNAL_DIR = os.path.expanduser(os.environ.get("HARNESS_JOURNAL_DIR", "~/notes/Sessions"))
ALLOW = [f"{H}/.claude/sessions/*", f"{H}/.claude/rules/*", f"{H}/.claude/CLAUDE.md",
         f"{H}/.claude/projects/*/memory/*", "/private/tmp/claude-*/*", "/tmp/claude-*/*",
         f"{JOURNAL_DIR}/*"]           # §17 세션저널(승격본). 볼트의 다른 폴더는 불허

# obsidian MCP 는 경로 대신 vault(이름)+folder+filename 으로 온다 → 실경로 복원용 이름→루트 표.
# 이름은 obsidian-mcp 가 인자 경로의 basename 을 lowercase+하이픈화해 만든다(build/main.js:12470).
# 표에 없는 vault 는 복원 실패 → 기존 PATH_KEYS 판정으로 떨어져 차단(fail-closed, deny 메시지로 보임).
# 예: VAULTS = {"my-vault": f"{H}/my-vault"}  — 쓰는 볼트가 없으면 비워 둔다.
VAULTS = {}

# serena/obsidian 쓰기 동사. 읽기(find_*/get_*/read_*/list_*/search-*)는 매칭되지 않는다.
MCP_WRITE = re.compile(r"^mcp__(serena|obsidian)__"
                       r"(replace|insert|rename|safe_delete|write|delete|edit|create|move|add|remove)[_-]")
PATH_KEYS = ("file_path", "relative_path", "notebook_path", "path", "filename", "filepath")

INPLACE = {"sed", "perl", "awk", "gawk"}                     # -i 플래그가 있을 때만
WRITE_CMDS = {"tee", "cp", "mv", "touch", "install", "truncate", "dd", "patch"}
CODE_EXEC = {"python", "python3", "node", "ruby", "php", "deno", "bun", "perl"}
CODE_WRITE = re.compile(r"""open\s*\([^)]*['"][wax]|write_text|writeFileSync|writeFile\s*\(""")
SKIP = {"sudo", "nohup", "time", "command", "exec", "env", "builtin", "if", "then", "else",
        "elif", "fi", "do", "done", "while", "until", "for", "!", "[", "[["}
SEP = {";", "|", "||", "&", "&&", "(", ")", "<(", ">(", "{", "}", "\n"}


def _split(seg: list) -> tuple:
    """(명령어, 비플래그 인자들). 환경변수 대입·셸 키워드 접두는 건너뛴다."""
    for i, t in enumerate(seg):
        if re.match(r"^\w+=", t) or t in SKIP:
            continue
        return t.rsplit("/", 1)[-1], [a for a in seg[i + 1:] if not a.startswith("-")]
    return "", []


def bash_hits(cmd: str) -> list:
    """차단 사유 [(사유, [대상후보경로])]. 빈 리스트면 통과.
    토큰화는 stdlib shlex(punctuation_chars). 손으로 짠 파서는 `\\"` 이스케이프·JSON 페이로드
    (`-d '{"x": "a > b"}'`)·`FOO="a b" tee` 를 전부 오분류했다.
    shlex 는 `2>&1`·`>&2` 를 `>&` 한 토큰으로, `<<`·`<(` 도 별도 토큰으로 내줘 `>` 와 안 겹친다."""
    try:
        lex = shlex.shlex(cmd, posix=True, punctuation_chars=True)
        lex.whitespace_split = True
        toks = list(lex)
    except ValueError as e:                     # 따옴표 미종결 등 → §12: 알린 뒤 통과
        sys.stderr.write(f"[main-edit-guard] Bash 토큰화 실패 → 가드 미적용(통과): {e}\n")
        return []

    # `grep ">" f` 처럼 통째로 인용된 연산자는 posix shlex 가 진짜 `>` 와 구분해주지 못한다
    # (둘 다 토큰 `>`). 그런 커맨드는 리다이렉트 판정을 통째로 포기한다 — fail-open.
    ambiguous = re.search(r"""(['"])>{1,2}\1""", cmd) is not None
    hits, segs = [], [[]]
    for t in toks:
        segs.append([]) if t in SEP else segs[-1].append(t)
    for seg in segs:
        h, args = _split(seg)
        if h in INPLACE and any(t.startswith(("-i", "--in-place")) for t in seg):
            hits.append((f"{h} 인플레이스 편집", args))
        elif h in WRITE_CMDS and args:          # 인자 없으면 --help/--version → 통과
            hits.append((f"{h} 파일 쓰기", args))
        elif h in CODE_EXEC and {"-c", "-e"} & set(seg) and CODE_WRITE.search(" ".join(seg)):
            hits.append((f"{h} -c/-e 인라인 파일 쓰기", args))
        elif h in ("bash", "sh", "zsh", "dash") and "-c" in seg and args:
            hits += bash_hits(args[0])          # `bash -c '...'` 안쪽까지 한 겹 더 본다
        for i, t in enumerate([] if ambiguous else seg[:-1]):
            tgt = seg[i + 1]                    # 변수·fd 경로는 fail-open
            if t in (">", ">>") and not (tgt.startswith("/dev/") or "$" in tgt or "`" in tgt):
                hits.append(("리다이렉트 > 파일", [tgt]))
    return hits


def allowed(raw: str, cwd: str) -> bool:
    base = os.path.join(cwd, os.path.expanduser(raw))
    cands = {os.path.abspath(base), os.path.realpath(base)}    # /tmp↔/private/tmp 양쪽 커버
    return any(fnmatch.fnmatch(p, g) for p in cands for g in ALLOW)


def deny(what: str, detail: str) -> None:
    sys.stderr.write(
        "[main-edit-guard] §15 전면 위임 — 메인 스레드에서 파일을 직접 수정할 수 없다.\n"
        f"  차단: {what} {detail}\n"
        "  조치: Agent 툴로 서브에이전트(general-purpose 등)에 위임해 수정하게 하라.\n"
        f"  허용 예외: 세션저널(~/.claude/sessions/, {JOURNAL_DIR}/)\n"
        "            · 룰(~/.claude/rules/, CLAUDE.md)\n"
        "            · 메모리(~/.claude/projects/*/memory/) · 스크래치패드(/tmp/claude-*/)\n"
        "  해제: ~/.claude/settings.json 의 env 에 \"CLAUDE_MAIN_EDIT_ALLOW\": \"1\" 추가 후 재시작\n"
        "        (일회성이면 CLAUDE_MAIN_EDIT_ALLOW=1 claude 로 실행)\n")
    sys.exit(2)


def main() -> None:
    if os.environ.get("CLAUDE_MAIN_EDIT_ALLOW"):        # 해제 스위치
        sys.exit(0)
    try:
        d = json.loads(sys.stdin.read())
    except Exception as e:                              # §12: 삼키지 않고 알린 뒤 통과
        sys.stderr.write(f"[main-edit-guard] 입력 파싱 실패 → 가드 미적용(통과): {e}\n")
        sys.exit(0)
    tool = d.get("tool_name") or ""
    if d.get("agent_id") or d.get("agent_type"):        # 서브에이전트 → 항상 통과
        sys.exit(0)
    ti = d.get("tool_input") or {}
    cwd = d.get("cwd") or os.getcwd()

    if tool in TOOLS:
        raw = ti.get("file_path") or ti.get("notebook_path") or ""
        if not raw:
            sys.stderr.write("[main-edit-guard] 경로 필드 없음 → 가드 미적용(통과)\n")
            sys.exit(0)
        if not allowed(raw, cwd):
            deny(tool, os.path.abspath(os.path.join(cwd, os.path.expanduser(raw))))

    elif tool == "Bash":
        cmd = ti.get("command") or ""
        if not cmd:
            sys.stderr.write("[main-edit-guard] Bash command 없음 → 가드 미적용(통과)\n")
            sys.exit(0)
        for reason, targets in bash_hits(cmd):
            # 화이트리스트 경로 또는 /dev/* (`| tee /dev/stderr`) 면 통과
            if any(t.startswith("/dev/") or allowed(t, cwd) for t in targets):
                continue
            deny("Bash", f"[{reason}] {cmd.strip()[:200]}")

    elif MCP_WRITE.match(tool):
        root = VAULTS.get(str(ti.get("vault") or ""))       # obsidian: vault+folder+filename → 실경로
        if root and ti.get("filename") and allowed(
                os.path.join(root, str(ti.get("folder") or ""), str(ti["filename"])), cwd):
            sys.exit(0)
        for k in PATH_KEYS:
            if ti.get(k) and allowed(str(ti[k]), cwd):
                sys.exit(0)
        deny(tool, str(next((ti[k] for k in PATH_KEYS if ti.get(k)), "")))

    sys.exit(0)


if __name__ == "__main__":
    main()

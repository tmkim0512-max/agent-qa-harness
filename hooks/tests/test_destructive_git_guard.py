#!/usr/bin/env python3
"""destructive_git_guard 계약 테스트 — 오차단 회귀가 1순위.

이 훅은 *차단형*이라 최악의 실패가 "안 보인다"가 아니라 "정당한 작업이 막힌다"이다.
그래서 MUST_PASS(오차단 0)가 MUST_BLOCK 보다 먼저 온다.

stdlib unittest 만 사용(프레임워크·픽스처 없음). 훅을 실제 subprocess 로 띄워
exit code 를 재므로 배선 상태와 무관하게 계약을 검증한다.

  python3 -m unittest discover -s hooks/tests -v
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest

HOOK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "destructive_git_guard.py")
PY = sys.executable


def run(command, tool="Bash", env_extra=None, cwd_payload="/home/user/project"):
    payload = {"tool_name": tool, "tool_input": {"command": command}, "cwd": cwd_payload}
    env = dict(os.environ)
    env.pop("GIT_GUARD", None)
    env.pop("GIT_GUARD_MODE", None)
    if env_extra:
        env.update(env_extra)
    p = subprocess.run([PY, HOOK], input=json.dumps(payload), capture_output=True,
                       text=True, env=env, timeout=30)
    return p.returncode, p.stdout, p.stderr


def run_raw(stdin_text, env_extra=None):
    env = dict(os.environ)
    if env_extra:
        env.update(env_extra)
    p = subprocess.run([PY, HOOK], input=stdin_text, capture_output=True,
                       text=True, env=env, timeout=30)
    return p.returncode, p.stdout, p.stderr


# ── §4-2 오차단 예산 — 전건 exit 0 이어야 한다 ───────────────────────────────
MUST_PASS = [
    ('grep -rn "git reset --hard" --include=*.sh .', "따옴표 안 문자열 + 읽기전용"),
    ('rg "git push --force" .', "읽기전용 rg"),
    ('git commit -m "fix: git push -f 금지 규칙"', "커밋 메시지 문자열"),
    ('echo "git reset --hard 는 금지"', "echo 문자열"),
    ("""python3 -c "print('git push -f')" """, "python -c 문자열"),
    ("cat <<'EOF' > doc.md\ngit push -f 하지 마라\nEOF", "heredoc 본문"),
    ("git push origin HEAD", "정상 push"),
    ("git push --force-with-lease origin feat/x", "force-with-lease 는 안전"),
    ("git checkout main", "브랜치 전환"),
    ("git checkout -- path/f.py", "단일 경로 복원"),
    ("git restore --staged .claude/settings.json", "staged 해제"),
    ("git ls-files -d -z | xargs -0 git restore --", "룰 권장 삭제복원 명령"),
    ("git -C /home/user/wt status", "worktree 상태조회"),
    ('T=$(mktemp -d); trap \'rm -rf "$T"\' EXIT', "mktemp 정리 (rm -rf 미탑재)"),
    ("git stash list", "다른 가드 소관"),
    ("git log --oneline -5", "로그 조회"),
    ("git diff --stat", "diff"),
    # ── F-1 회귀 (주석 속 git 문자열 오차단) — 셸 주석은 실행되지 않는다 ──────────
    ("# 검증: git reset --hard 를 쓰지 않고\ngit rev-parse --short HEAD",
     "F-1 원본 재현: 앞줄 주석 + 읽기전용 명령"),
    ("git rev-parse HEAD   # 주의: git reset --hard 금지", "F-1 후행 주석"),
    ("# reset --hard 금지\ngit status --short", "F-1 주석에 git 리터럴 없음(원래도 통과)"),
    ("git log --oneline | wc -l  # git reset --hard", "F-1 RO head 세그먼트 + 주석"),
    ("git status --short  # git push --force 금지", "F-1 주석 안 force"),
    # ── F-2 회귀 — dry-run 은 아무것도 지우지 않는다 ────────────────────────────
    ("git clean -fdn", "F-2 dry-run 단축"),
    ("git clean -fdxn", "F-2 dry-run + x"),
    ("git clean --dry-run -fd", "F-2 롱 dry-run"),
]

# ── §4-3 진짜 위험 — 전건 exit 2 ─────────────────────────────────────────────
MUST_BLOCK = [
    ("git push -f origin main", "단축 force"),
    ("git push --force origin feat/x", "롱 force"),
    ("git -C /home/user/project push -f origin main", "-C 우회 (원본이 놓치던 벡터)"),
    ("git reset --hard origin/main", "reset hard"),
    ("git reset --hard HEAD~3", "reset hard rev"),
    ("cd /tmp && git push --force origin main", "복합 명령 뒤 세그먼트"),
    # ── F-1 반대편: 주석 제거가 차단력을 깎지 않는다 (실행되는 건 `#` 앞) ────────
    ("git reset --hard HEAD   # 이건 진짜 실행된다", "주석 앞 명령은 여전히 차단"),
    ("git push -f origin main  # 메모", "주석 앞 force push 차단"),
    ("cd /tmp && git push -f origin main   # 대상은 /tmp", "cd + 주석 조합"),
]

# ── 조언 등급 — 차단하지 않되 additionalContext 는 나와야 한다 ────────────────
MUST_ADVISE = [
    "git checkout .",
    "git restore .",
    "git clean -fd",
]


class TestMustPass(unittest.TestCase):
    def test_no_false_blocks(self):
        bad = []
        for cmd, why in MUST_PASS:
            rc, out, err = run(cmd)
            if rc != 0:
                bad.append("rc=%s  [%s]  %r\n     stderr=%s" % (rc, why, cmd, err.strip()[:300]))
        self.assertEqual(bad, [], "오차단 발생:\n" + "\n".join(bad))


class TestMustBlock(unittest.TestCase):
    def test_blocks(self):
        bad = []
        for cmd, why in MUST_BLOCK:
            rc, out, err = run(cmd)
            if rc != 2:
                bad.append("rc=%s  [%s]  %r" % (rc, why, cmd))
        self.assertEqual(bad, [], "미차단 발생:\n" + "\n".join(bad))

    def test_deny_payload_shape(self):
        rc, out, err = run("git push -f origin main")
        self.assertEqual(rc, 2)
        d = json.loads(out)["hookSpecificOutput"]
        self.assertEqual(d["hookEventName"], "PreToolUse")
        self.assertEqual(d["permissionDecision"], "deny")
        self.assertIn("force-with-lease", d["permissionDecisionReason"])
        self.assertIn("GIT_GUARD=0", d["permissionDecisionReason"])
        self.assertTrue(err.strip(), "차단 사유가 stderr 에도 나와야 한다")


class TestAdvisory(unittest.TestCase):
    def test_advise_does_not_block(self):
        for cmd in MUST_ADVISE:
            rc, out, err = run(cmd)
            self.assertEqual(rc, 0, "조언 등급이 차단됐다: %r" % cmd)
            ctx = json.loads(out)["hookSpecificOutput"]["additionalContext"]
            self.assertIn("되돌릴 수 없는", ctx)


def _load():
    import importlib.util
    spec = importlib.util.spec_from_file_location("dgg_load", HOOK)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestDryRunAdvisory(unittest.TestCase):
    """F-2 — dry-run 에 '삭제됩니다' 를 붙이면 거짓 사실이 컨텍스트로 주입된다."""

    def test_dry_run_has_no_delete_advice(self):
        for cmd in ("git clean -fdn", "git clean -fdxn", "git clean --dry-run -fd",
                    "git clean -n -fd"):
            rc, out, err = run(cmd)
            self.assertEqual(rc, 0, cmd)
            self.assertNotIn("삭제됩니다", out, "dry-run 인데 삭제 조언: %r" % cmd)
            self.assertNotIn("삭제됩니다", err, "dry-run 인데 삭제 조언: %r" % cmd)

    def test_real_clean_still_advises(self):
        """positive control — 제외 로직이 조언 자체를 죽이면 이게 먼저 실패한다."""
        for cmd in ("git clean -fd", "git clean -fdx", "git clean --force -d"):
            rc, out, err = run(cmd)
            self.assertEqual(rc, 0, cmd)
            ctx = json.loads(out)["hookSpecificOutput"]["additionalContext"]
            self.assertIn("삭제됩니다", ctx, "진짜 삭제인데 조언이 없다: %r" % cmd)


class TestOverride(unittest.TestCase):
    def test_env_kill_switch(self):
        rc, _, err = run("git push -f origin main", env_extra={"GIT_GUARD": "0"})
        self.assertEqual(rc, 0)
        self.assertIn("DISABLED", err)

    def test_inband_override(self):
        """훅은 별도 프로세스라 인라인 env(`GIT_GUARD=0 git push -f`)가
        os.environ 에 없다. 인밴드 토큰이 없으면 비대화형 서브에이전트는 우회 수단이 0."""
        rc, _, err = run("GIT_GUARD=0 git push -f origin main")
        self.assertEqual(rc, 0)
        self.assertIn("in-band override", err)

    def test_warn_mode(self):
        rc, out, _ = run("git push -f origin main", env_extra={"GIT_GUARD_MODE": "warn"})
        self.assertEqual(rc, 0)
        self.assertIn("warn", json.loads(out)["hookSpecificOutput"]["additionalContext"])


class TestFailOpen(unittest.TestCase):
    def test_empty_stdin(self):
        self.assertEqual(run_raw("")[0], 0)

    def test_broken_json(self):
        rc, _, err = run_raw("{not json")
        self.assertEqual(rc, 0)
        self.assertIn("fail-open", err)

    def test_non_bash_tool(self):
        self.assertEqual(run("git push -f origin main", tool="Write")[0], 0)

    def test_oversized_command(self):
        rc, _, _ = run("git push -f origin main # " + "x" * 20001)
        self.assertEqual(rc, 0, "20000자 초과는 판독 포기(fail-open)")

    def test_missing_command_key(self):
        rc, _, _ = run_raw(json.dumps({"tool_name": "Bash", "tool_input": {}}))
        self.assertEqual(rc, 0)


class TestNegativeControl(unittest.TestCase):
    """판정 로직을 no-op 으로 바꾸면 MUST_BLOCK 이 먼저 죽는지 — vacuous PASS 차단.

    검사 대상이 0개여도 exit 0 으로 통과하는 가짜 초록을
    되풀이하지 않는다. 이 테스트가 없으면 정규식이 통째로 죽어도 스위트가 초록이다.
    """
    def test_evaluate_is_load_bearing(self):
        sys.path.insert(0, os.path.dirname(HOOK))
        import importlib.util
        spec = importlib.util.spec_from_file_location("dgg", HOOK)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        blocks, _ = mod.evaluate("git push -f origin main")
        self.assertTrue(blocks, "정규식이 살아 있어야 한다")

        saved = mod.BLOCK_RULES[:]
        try:
            mod.BLOCK_RULES[:] = []          # no-op 주입
            b2, _ = mod.evaluate("git push -f origin main")
            self.assertEqual(b2, [], "no-op 인데 여전히 차단 → 판정 경로가 이중이다")
        finally:
            mod.BLOCK_RULES[:] = saved

    def test_sanitize_strips_quotes_and_heredoc(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("dgg2", HOOK)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        self.assertNotIn("git push -f", mod.sanitize('echo "git push -f"'))
        self.assertNotIn("git push -f", mod.sanitize("cat <<'EOF'\ngit push -f\nEOF"))
        self.assertIsNone(mod.sanitize("x" * (mod.MAX_LEN + 1)))

    def test_sanitize_strips_comments_but_keeps_the_real_command(self):
        """F-1 — 주석은 지우되 `#` **앞**의 실제 명령은 남아야 한다."""
        mod = _load()
        self.assertNotIn("reset --hard", mod.sanitize("git rev-parse HEAD  # git reset --hard"))
        self.assertNotIn("reset --hard", mod.sanitize("# git reset --hard\ngit status"))
        self.assertIn("git status", mod.sanitize("# git reset --hard\ngit status"))
        # 주석 앞 실명령 보존 = 차단력 무손실
        self.assertIn("git reset --hard", mod.sanitize("git reset --hard HEAD  # 메모"))
        # 개행을 먹으면 세그먼트 분리가 깨진다
        self.assertIn("\n", mod.sanitize("# c\ngit status"))
        # 앞에 공백 없는 `#` 은 주석이 아니라 인자다
        self.assertIn("main#frag", mod.sanitize("git push origin main#frag"))
        self.assertIn("--grep=#123", mod.sanitize("git log --grep=#123"))


if __name__ == "__main__":
    unittest.main(verbosity=2)

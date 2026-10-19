#!/usr/bin/env python3
"""report-skeleton-reminder 계약 테스트 — 트리거 확장(이슈 키 → 한국어 작업지시 일반) 회귀.

이 훅은 *비차단형*이라 최악의 실패는 "막힌다"가 아니라 **조용히 안 뜬다**이다.
그래서 MUST_FIRE(미탐 0)가 먼저 오고, MUST_NOT_FIRE(순수 질의 노이즈)가 뒤에 온다.
판정은 원칙적으로 stdout 이 비었는지 여부로만 한다 — REMINDER 문구는 바뀔 수 있으므로
바이트 수·문장을 단언하지 않는다(문구 수정이 무관한 실패를 만들지 않게).
예외 하나 — TestReminderContract 는 §18 4번째 축("무엇이 달라졌나")이 A골격 줄에
남아 있는지만 단언한다. 축 자체가 계약이므로 라벨을 바꾸려면 이 테스트도 같이 고쳐라
(코드에 맞춰 단언을 지우는 건 §4 GREEN 위반이다).

stdlib unittest 만 사용(프레임워크·픽스처 없음). 훅을 실제 subprocess 로 띄워
stdin JSON -> stdout 계약을 재므로 배선 상태와 무관하게 계약을 검증한다.

  python3 -m unittest discover -s hooks/tests -v
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest

HOOK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "report-skeleton-reminder.py")
PY = sys.executable


def run_raw(stdin_text, env_extra=None):
    """훅을 subprocess 로 실행하고 (rc, stdout, stderr) 를 돌려준다."""
    env = dict(os.environ)
    # 이 세션이 워커 env 를 물고 있으면 전건 무출력이 되어 테스트가 통째로 무의미해진다.
    env.pop("RALPH_SESSION", None)
    env.pop("CLAUDE_HEADLESS_WORKER", None)
    env.pop("REPORT_ISSUE_KEY_PREFIX", None)
    if env_extra:
        env.update(env_extra)
    p = subprocess.run([PY, HOOK], input=stdin_text, capture_output=True,
                       text=True, env=env, timeout=30, check=False)
    return p.returncode, p.stdout, p.stderr


def run(prompt, env_extra=None):
    return run_raw(json.dumps({"prompt": prompt}), env_extra=env_extra)


def fired(stdout):
    return bool(stdout.strip())


# ── 발동해야 한다 — 미탐이 이 훅의 1순위 실패 ────────────────────────────────
MUST_FIRE = [
    ("세션 저널 훅 좀 고쳐줘", "명령 어미 + 지시 동사"),
    ("이 정규식 수정해", "지시 동사만(어미 없음)"),
    ("이거 고쳐줄래?", "의문형이어도 지시 — 명령 어미가 있으면 질의 배제 안 탄다"),
    ("PROJ-1234 진행해줘", "이슈 키 + 지시"),
    ("PROJ-1234", "이슈 키 단독 — 트리거1 은 지시 표현 없이도 발동"),
    ("/browse/ABC-123 확인 부탁", "트리거1 Jira URL 경로"),
    # 실사용 미탐 유형 — 비가역 작업이 몰려 있다.
    ("게이트 돌려 산출물 커밋 하고 PR까지 가져와", "커밋·PR 지시인데 어미가 '가져와'"),
    ("커밋하고 /ship 으로 PR을 가져와주세요", "정중 요청 — 종전 _WORK 에 '주세요'가 없었다"),
    ("멈춰롤백해", "띄어쓰기 없는 롤백 지시"),
    ("그럼 해당 pr은 원복해", "원복 = 비가역"),
    ("더 빠르게 할수있도록 서브에이전트 워커를 늘려주세요 5개정도", "정중 요청 + '늘려'"),
    ("탐사 루프 실제로 돌려봐", "'돌려' — 실행 지시"),
    ("전체 승인", "승인 단답 — 지시 동사가 없어 _APPROVE 가 잡는다"),
    ("전부 y", "승인 단답"),
]

# ── 발동하면 안 된다 — 순수 질의/잡담 ────────────────────────────────────────
MUST_NOT_FIRE = [
    ("UserPromptSubmit 훅이 뭐야?", "정보 질의"),
    ("이 코드 수정하는 방법이 뭐야?", "지시 동사가 있어도 질의형 종결"),
    ("그래서 결론이 뭐야", "물음표 없는 질의"),
    ("오늘 날씨 좋네", "잡담"),
]


class TestMustFire(unittest.TestCase):
    def test_fires(self):
        bad = []
        for prompt, why in MUST_FIRE:
            rc, out, err = run(prompt)
            if not fired(out):
                bad.append(f"[{why}] {prompt!r}  rc={rc} stderr={err.strip()[:200]}")
        self.assertEqual(bad, [], "미탐 발생:\n" + "\n".join(bad))


class TestMustNotFire(unittest.TestCase):
    def test_does_not_fire(self):
        bad = []
        for prompt, why in MUST_NOT_FIRE:
            _, out, _ = run(prompt)
            if fired(out):
                bad.append(f"[{why}] {prompt!r}  stdout={out.strip()[:120]!r}")
        self.assertEqual(bad, [], "오탐 발생:\n" + "\n".join(bad))


class TestReminderContract(unittest.TestCase):
    """문구는 바뀌어도 4번째 축의 *존재*는 계약이다 — 그래서 구절 1개만 단언한다.

    모듈 docstring 대로 문장·바이트 수는 여전히 안 잰다. 다만 골격 줄이 3요소로
    되돌아가는 것이 실제 회귀 형태이므로(단서 줄에 같은 토큰이 남아 있어도 회귀다),
    4요소 *구절 그대로*를 회귀로 고정한다.
    """

    def test_fourth_axis_token_present(self):
        _, out, _ = run("이 정규식 수정해")
        self.assertIn("무엇을 / 어떻게 / 왜 / 무엇이 달라졌나", out)


class TestWorkerSuppression(unittest.TestCase):
    """자동화 워커에는 주입 금지 — 주입문이 워커의 실제 지시를 덮을 수 있다."""

    def test_suppressed_for_workers(self):
        # 세션 밖 헤드리스 워커(claude -p) kill-switch.
        for var in ("RALPH_SESSION", "CLAUDE_HEADLESS_WORKER"):
            rc, out, _ = run("PROJ-1234 진행해줘", env_extra={var: "1"})
            self.assertEqual(rc, 0, var)
            self.assertFalse(fired(out), f"{var} 인데 주입됐다: {out[:120]!r}")


class TestNeverDies(unittest.TestCase):
    """UserPromptSubmit 훅이 죽으면 프롬프트가 막힌다 — 어떤 입력에서도 rc==0."""

    def test_malformed_json_exits_zero_and_warns_on_stderr(self):
        rc, out, err = run_raw("{not json")
        self.assertEqual(rc, 0)
        self.assertFalse(fired(out), "파싱 실패인데 stdout 을 오염시켰다")
        self.assertTrue(err.strip(), "실패를 삼켰다(§12) — stderr 경고가 있어야 한다")

    def test_odd_inputs_all_exit_zero(self):
        cases = ["", "{not json", '{"prompt": null}', '{"other": "x"}',
                 json.dumps({"prompt": "고쳐줘 " * 5000})]
        for text in cases:
            rc, _, err = run_raw(text)
            self.assertEqual(rc, 0, f"rc={rc} on {text[:40]!r} stderr={err.strip()[:200]}")

    def test_non_dict_json_does_not_crash(self):
        """dict 가 아닌 JSON / str 이 아닌 prompt — 종전엔 rc=1 로 죽었다.

        `.get` 이 AttributeError, `re.search(123)` 이 TypeError 를 내는데 except 는
        JSONDecodeError/ValueError 만 잡고 있었다. 둘을 except 에 편입 + prompt 타입
        가드로 rc=0 + stderr 경고가 되게 했다(§12 — 삼키지 않되 stdout 은 오염 금지).
        """
        for text in ("null", "[]", '{"prompt": 123}'):
            rc, out, err = run_raw(text)
            self.assertEqual(rc, 0, f"rc={rc} on {text!r}")
            self.assertFalse(fired(out), f"stdout 오염 on {text!r}: {out[:120]!r}")
            self.assertTrue(err.strip(), f"실패를 삼켰다(§12) on {text!r}")


if __name__ == "__main__":
    unittest.main(verbosity=2)

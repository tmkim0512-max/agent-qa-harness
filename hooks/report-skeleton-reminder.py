#!/usr/bin/env python3
"""UserPromptSubmit 훅 — 작업 지시 감지 시 §18 A골격 리마인더 주입.

이슈 트래커 키뿐 아니라 한국어 작업 지시 일반(해줘·수정·구현·조사…)을 잡는다.
종전엔 트리거가 이슈 트래커 패턴뿐이라 티켓이 안 낀 지시는 전부 미탐이었다.
룰(rules/18-report-style.md)은 산문이라 잊히지만 훅 주입은 결정론적이다.
매칭 없으면 무출력(노이즈 0).
"""
import os as _os
# 세션 밖 자동화 워커(claude -p 루프 등)에는 주입 금지 — 주입 텍스트가 워커의 실제 지시를
# "로드된 자료"처럼 보이게 만들어 임무 미수행을 유발할 수 있다.
if _os.environ.get("CLAUDE_HEADLESS_WORKER") or _os.environ.get("RALPH_SESSION"):
    raise SystemExit(0)
import json
import re
import sys

# 트리거 1 — 이슈 트래커. 무조건 발동(아래 질의 배제도 안 탄다).
# 화이트리스트 — 범용 `[A-Z]{2,10}-\d{2,}` 는 ISO-8601·SHA-256·RFC-2119·AES-256 에 오탐한다.
# 그래서 자기 프로젝트 키 접두사만 적는다(기본값 PROJ 는 예시 — 환경변수로 바꾼다).
_KEY = _os.environ.get("REPORT_ISSUE_KEY_PREFIX", "PROJ")
TRIGGERS = [
    r"\b" + re.escape(_KEY) + r"-\d{2,}\b",   # 이슈 키
    r"/browse/[A-Z]+-\d+",          # Jira 류 이슈 URL 경로
]
_RE = re.compile("|".join(TRIGGERS))

# 트리거 2 — 작업 지시 일반(한국어 명령 어미 + 지시 동사).
_WORK = re.compile(
    r"줘|해라|해봐|하자|하세요|해주|부탁"                    # 명령 어미
    r"|구현|수정|고쳐|고치|만들|작성|추가|삭제|제거|정리"      # 지시 동사
    r"|리팩터|리팩토링|분석|조사|검증|테스트|배포|진행|확인|점검"
    r"|실행|적용|보완|개선|바꿔|바꾸|옮겨|넣어"
    # 정중 요청 어미 — "가져와주세요"처럼 지시 동사가 어미에만 있는 형태가 1차 관문을 못 넘었다.
    r"|주세요|주시|주겠|줄수|줄래|해달|셈|할\s?것|해야|하도록"
    r"|아봐|어봐|여봐|와봐|워봐|가져와|시켜와"
    # 비가역 작업 동사 — 여기서 리마인더가 빠지면 증거 없는 완료 보고가 나온다.
    r"|롤백|원복|폐기|커밋|머지|승인|적재|돌려|찾아|채워|늘려|뽑아|그려|맞춰|붙여|건드려|건들|지워|띄워|멈춰|보내"
)
# 순수 질의 배제 — 의문사/의문형 종결 + 물음표로 끝나는 정보 질의.
# 완벽 분류는 불가능하다. 미탐(지시인데 리마인더가 안 뜸)이 오탐(질의에 몇 줄 더 뜸)보다
# 비싸므로 넓게 잡고, "명백한 질의"만 뺀다. 그래서 명령 어미가 하나라도 있으면
# 물음표로 끝나도 배제하지 않는다("이거 고쳐줄래?" 는 질문 형태의 지시다).
_QUERY_TAIL = re.compile(
    r"(?:뭐|뭔|무엇|어때|어떠|어떻|왜|언제|어디|누구|누가|얼마|몇"
    r"|인가|일까|을까|ㄹ까|나요|맞아|맞나)[^?]{0,12}\?\s*$"
)
_IMPERATIVE = re.compile(r"줘|주세요|주시|주겠|줄수|줄래|해달|해라|해봐|하자|하세요|부탁")
# 트리거 3 — 승인 단답("전부 y", "착수 승인"). 지시 동사가 없어 _WORK 로는 못 잡는다.
# 승인 직후 턴이 곧 작업 턴이므로 리마인더가 필요하다. 트리거1(이슈 키) 처럼 질의 배제를 안 탄다.
_APPROVE = re.compile(r"^\s*(?:전부|전체)\s*[yY]\s*$|^\s*(?:착수\s*)?(?:전체\s*)?승인\s*[yY]?\s*$")

REMINDER = """[§18 A골격] 작업 지시 감지 — 이 턴의 보고는 작업 보고 골격으로:

결론: 됐다 / 부분 / 못 했다
**받은 지시** — "<사용자 원문 핵심 인용>" → 내 해석: <무엇을 / 어디까지 하기로 받아들였나>
**했다**   — 무엇을 / 어떻게 / 왜 / 무엇이 달라졌나 + 증거(로그·테스트·file:line)
**안 됐다** — 미달성 + 왜 막혔나 + 뭐가 있으면 풀리나
**다음**   — 내가 이어서 할 것 / 사용자 결정은 AskUserQuestion 으로(본문 중복 금지)

4칸 생략 불가. 해당 없으면 "없음"이라고 쓴다.
"받은 지시"는 내 말로 바꾸지 말고 사용자 원문 그대로 짧게 인용한다 — 바꿔 쓰면 추적이 끊긴다.
"내 해석"엔 원문에 없던 판단(범위 확정·모호한 부분을 어느 쪽으로 읽었나·뺀 것)을 쓴다. 원문 재진술이면 값이 0이다.
"무엇이 달라졌나"는 변경 전 동작 → 변경 후 동작 — 그래서 뭐가 좋아졌나·가능해졌나. 행위 로그(push·머지·커밋·PR 본문 수정)는 경로지 산출이 아니다.
"안 됐다"엔 원인만이 아니라 *무엇이 주어지면 풀리는지*까지.
내부 축약·번호(갭 4, DoD, _s3b)는 첫 등장에 3~7단어 괄호 풀이. ID엔 정체 라벨.
결정은 산문 선택지로 나열하지 마라 — AskUserQuestion 으로. question=무엇이 갈리나 / label=결과 이름(대상명 아님) / description=비용·리스크 + `추천 — 근거`. 한 질문 = 한 판단 축, 의존하면 선행만 먼저."""


def _is_work_order(prompt: str) -> bool:
    """작업 지시로 볼 것인가 — 지시 표현이 있고, 명백한 순수 질의가 아닌 것."""
    if not _WORK.search(prompt):
        return False
    return not (_QUERY_TAIL.search(prompt) and not _IMPERATIVE.search(prompt))


def main():
    try:
        prompt = json.load(sys.stdin).get("prompt", "") or ""
        if not isinstance(prompt, str):
            raise TypeError(f"prompt 가 str 이 아님: {type(prompt).__name__}")
    except (json.JSONDecodeError, ValueError, AttributeError, TypeError) as e:
        # 삼키지 않되(§12) stderr 로만 — stdout 은 컨텍스트라 오염 금지, 훅이 죽으면 프롬프트가 막힌다.
        # AttributeError/TypeError = dict 아닌 JSON(null·[]) / prompt 가 str 이 아닌 경우.
        print(f"[report-skeleton] stdin 입력 처리 실패: {e}", file=sys.stderr)
        return 0
    if _RE.search(prompt) or _APPROVE.search(prompt) or _is_work_order(prompt):
        print(REMINDER)
    return 0


if __name__ == "__main__":
    sys.exit(main())

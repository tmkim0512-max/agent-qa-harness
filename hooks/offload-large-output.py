#!/usr/bin/env python3
# PostToolUse(Bash) 훅: stdout 가 400줄 이상이면 offload 로 외부화하고 컨텍스트엔 stub 만 남긴다.
# 무손실 — 원본은 ~/.claude/refs/<id>.md 에 보존, 모델은 `offload --get <id>` 로 전량 회수.
# 치환은 hookSpecificOutput.updatedToolOutput 으로만 수행.
# 어떤 실패(파싱·offload 오류 등)든 JSON 미출력으로 원본 그대로 통과 = 데이터 유실 0 (§12).
import sys, json, subprocess, os

THRESHOLD = 400

def passthrough():
    sys.exit(0)  # JSON 미출력 → 원본 tool 출력이 그대로 컨텍스트로 간다

try:
    data = json.load(sys.stdin)
except Exception:
    passthrough()

resp = data.get("tool_response", "")
if isinstance(resp, dict):
    parts = [str(resp.get("stdout", "")), str(resp.get("stderr", ""))]
    text = "\n".join(p for p in parts if p) or json.dumps(resp, ensure_ascii=False)
elif isinstance(resp, str):
    text = resp
else:
    text = str(resp)

if text.lstrip().startswith("[ref:"):     # 이미 offload 된 출력 → 재처리 금지
    passthrough()
if text.count("\n") + 1 < THRESHOLD:      # 400줄 미만 → 그대로 유지
    passthrough()

offload = os.path.expanduser("~/.claude/bin/offload")
try:
    r = subprocess.run([offload, "--stdin"], input=text,
                       capture_output=True, text=True, timeout=10)
except Exception:
    passthrough()
if r.returncode != 0 or not r.stdout.strip():
    passthrough()  # offload 실패 → 원본 보존 (유실 0)

print(json.dumps({"hookSpecificOutput": {
    "hookEventName": "PostToolUse",
    "updatedToolOutput": r.stdout,
}}))

# 12. No Silent Failure (실패 은폐 금지)

**실패·불확실성·부분 성공·복구는 모두 관찰 가능해야 한다. 성공처럼 위장하지 마라.**

silent failure 는 예외 처리만의 문제가 아니다. 셸 · 응답 처리 · 데이터 · **보고** 어디서든 일어난다.

## 결과 상태 4정규

| 상태 | 정의 |
|---|---|
| **SUCCESS** | 요청 범위를 전부 수행했고 검증도 통과 |
| **PARTIAL** | 일부만 성공했거나 일부를 검증하지 못함 |
| **FAILED** | 핵심 작업이 실패 |
| **UNVERIFIED** | 실행은 했지만 결과를 검증하지 못함 |

**PARTIAL · UNVERIFIED 를 SUCCESS 로 보고하지 않는다.** 이게 가장 흔한 은폐다.

```
✗ 100건 처리 완료
✓ 93/100 성공, 7건 실패           ← PARTIAL
✓ 100건 실행, 결과 검증 못 함      ← UNVERIFIED
```

## 절대 금지 패턴

### 예외 처리

- `try: ... except: pass` — 모든 예외 무차별 흡수
- `try: ... except Exception: pass` — 광범위 catch 후 무시
- `except: return None / return []` — 에러를 정상 반환값으로 위장
- 에러 메시지/스택 트레이스를 로그에서 삭제
- `logger.error()` → `logger.debug()`로 강등하여 알람 회피
- `// @ts-ignore`, `# type: ignore`, `# noqa` 무사유 남발
- 테스트 실패를 `pytest.mark.skip` / `@unittest.skip`로 우회

### 셸 · 실행 흐름

- **`|| true` · `; true` 로 non-zero exit 를 무시** — 사유 주석 없이 쓰면 금지. 에이전트가 셸에서 실패를 감추는 가장 쉬운 수단이다.
- 실패 가능한 명령 뒤에 **결과 확인 없이** 다음 단계로 진행
- 파이프라인 중간 실패를 마지막 명령의 exit code 로 덮기 (`set -o pipefail` 없이 `a | b`)

허용되는 `|| true` 는 **왜 그 실패가 정상인지**를 주석에 남긴 경우뿐이다.

```bash
# 캐시 없을 때의 실패는 정상 — 첫 실행 경로
rm -f "$CACHE" || true
```

### 응답 · 데이터

- API/도구 응답의 `error` · `errors` · 실패 status 를 확인하지 않고 성공 간주. **HTTP 200 은 성공이 아니다** — payload 를 봐야 안다.
- 실패 결과를 **빈 문자열 · 0 · false · default 값**으로 바꿔 정상 데이터처럼 흘림
- 예상 건수·대상보다 **일부만 처리**됐는데 전체 성공으로 보고
- 빈 결과(`0건` · `rc=0`)를 확인 없이 "대상 없음" 으로 읽기

### 보고

- **retry/fallback 후 최초 실패 사실을 숨김**
- 실패한 테스트만 제외하고 나머지 결과로 "통과" 선언
- 검증을 실행하지 못했는데 `verified` · "완료" · "정상" 이라고 표현
- warning 을 무조건 success 로 치환

## 허용 패턴

예외 처리가 필요하면 반드시 **세 가지 중 하나**:

1. **재발생** — 컨텍스트 추가 후 raise
   ```python
   except FooError as e:
       logger.error(f"Foo failed in {context}: {e}")
       raise
   ```

2. **명시적 복구** — 사유 주석 + 구체적 예외만 처리
   ```python
   except FileNotFoundError:
       # 설정 파일 없으면 기본값 사용 (의도된 동작)
       config = DEFAULT_CONFIG
   ```

3. **상위 전파** — 호출자가 처리하도록 그대로 통과 (catch 자체를 안 함)

### 복구했어도 실패는 남긴다

**복구가 성공해도 원래 실패가 진단 가치가 있으면 기록한다. fallback 사용 여부를 성공으로 위장하지 않는다.**
의도된 복구여도 "기본값으로 떨어졌다" 는 사실은 보여야 한다.

```python
try:
    load_primary()
except FileNotFoundError:
    logger.warning("Primary config missing; using defaults")
    config = DEFAULT_CONFIG
```

## 보고 규율 — 실행 성공과 검증 성공을 분리한다

"코드는 바꿨다" 와 "문제가 해결됐다" 를 한 칸에 섞지 마라.

```
했다
- 설정 파일 수정

검증
- JSON parse 성공
- 테스트 12/12 통과

미검증
- 실제 production 호출은 실행하지 않음
```

## 발견 시 행동

```
silent failure 발견
├─ 현재 작업과 무관        → 보고만 한다. 즉시 수정 금지 (§3)
└─ 현재 작업의 검증을 오염 → 완료 선언 금지
```

- **무관한 경우** — 즉시 고치지 말고 사용자에게 보고한다: "여기 silent failure 패턴 있음, 별도 작업으로 처리할까?" (§3 Surgical Changes)
- **현재 작업의 성공 판정을 왜곡하는 경우** — 별도 이슈로만 넘기지 마라. **현재 결과를 UNVERIFIED 로 낮추고 사용자에게 알린다.**
  지금 고친 기능의 테스트가 사실 `except: pass` 때문에 항상 통과하고 있다면, 그 테스트를 근거로 "완료" 라고 할 수 없다.

### 티켓으로 넘길 때

```
발견 → 증거 확보 → 현재 작업 영향 판단 → §22 게이트 → FILE / MERGE / DONT-FILE
```

발견했다고 바로 티켓을 만들지 않는다. §22 흐름도를 탄다.

## 예외

- 테스트에서 의도적으로 예외를 검증하는 `pytest.raises` 등
- 외부 라이브러리가 정상 흐름에서 예외를 던지는 경우 (사유 주석 필수)

## 경계 — 중복 아님

- **§18 결론 줄 매핑** — SUCCESS=`됐다` / PARTIAL=`부분` / FAILED=`못 했다`. **UNVERIFIED 는 `됐다` 로 쓰지 않는다** — "실행했으나 미검증" 으로 쓰고 무엇을 못 검증했는지 "안 됐다" 칸에 적는다.
- **§6-1 Evidence Gate** — 보고 시 *수치를 실제 출력에서 인용*하는 규율. §12 는 그 앞단에서 *상태 자체를 위장하지 않게* 한다.
- **§4 VERIFY** — 검증을 *실행*하는 단계. §12 는 검증 결과를 *정직하게 표시*하는 규율.
- **§3 Surgical Changes** — 인접 코드에 손대지 않는다. 단 발견한 silent failure 가 현재 작업의 판정을 오염시키면 §3 뒤에 숨지 마라 — 고치라는 게 아니라 **완료 선언을 하지 말라**는 뜻이다.
- **§22 Issuance Gate** — 발견을 티켓으로 만들지 여부.

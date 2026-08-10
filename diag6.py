# -*- coding: utf-8 -*-
"""
인허가 원장 API 403 원인 규명

diag5 에서 6개 파라미터 조합 모두 403 SERVICE_KEY_IS_NOT_REGISTERED_ERROR.
같은 키로 건축HUB 는 정상 동작하므로 키 자체는 유효합니다.
따라서 원인은 셋 중 하나입니다.

  ① 활용신청이 아직 게이트웨이에 반영되지 않음 (자동승인이어도 지연 가능)
  ② 이 API 는 Encoding 키를 URL 에 직접 붙여 받아야 함
  ③ Base URL 또는 오퍼레이션 경로가 다름

각각을 분리해서 확인합니다.

실행: 우클릭 > Run 'diag6'   →  diag6_output.txt 생성
"""
import io
import sys
import time
from urllib.parse import quote

import requests

from secret import SERVICE_KEY

SEP = "=" * 72

BLD = "https://apis.data.go.kr/1613000/BldRgstHubService/getBrTitleInfo"
REST = "https://apis.data.go.kr/1741000/general_restaurants"

ENC_KEY = quote(SERVICE_KEY, safe="")     # URL 인코딩된 형태


def show(label, res):
    print(f"\n▶ {label}")
    if res is None:
        return
    body = res.text
    for token in {SERVICE_KEY, ENC_KEY}:
        if token:
            body = body.replace(token, "<KEY>")
    body = " ".join(body.split())
    ok = res.status_code == 200 and "NOT_REGISTERED" not in body
    mark = "✓ 성공" if ok else "✗ 실패"
    print(f"  HTTP {res.status_code}  {mark}")
    print(f"  {body[:220]}")
    return ok


def get(url, params=None, raw_query=None, timeout=20):
    try:
        if raw_query:
            return requests.get(f"{url}?{raw_query}", timeout=timeout)
        return requests.get(url, params=params, timeout=timeout)
    except requests.RequestException as exc:
        print(f"  ✗ 네트워크 오류: {exc}")
        return None


def main():
    # ── 대조군: 건축HUB 가 지금도 되는가 ─────────────────────────
    print(SEP)
    print("대조군 — 같은 키로 건축HUB 호출 (키 자체의 유효성 확인)")
    print(SEP)
    res = get(BLD, params={"serviceKey": SERVICE_KEY, "sigunguCd": "11620",
                           "bjdongCd": "10100", "numOfRows": "1",
                           "pageNo": "1", "_type": "json"})
    bld_ok = show("건축HUB / params + Decoding 키", res)

    if bld_ok:
        print("\n  → 키는 유효합니다. 인허가 원장 API 쪽만의 문제입니다.")
    else:
        print("\n  → 건축HUB 도 실패. 키 전체가 만료·변경되었을 수 있습니다.")

    # ── ② Encoding 키를 URL 에 직접 결합 ────────────────────────
    print("\n" + SEP)
    print("② 전달 방식 비교 — Decoding(params) vs Encoding(URL 직접)")
    print(SEP)

    base_q = "pageNo=1&numOfRows=5&_type=json"

    res = get(f"{REST}/info",
              params={"serviceKey": SERVICE_KEY, "pageNo": "1",
                      "numOfRows": "5", "_type": "json"})
    show("(a) params + Decoding 키  ← diag5 와 동일", res)
    time.sleep(0.3)

    res = get(f"{REST}/info", raw_query=f"serviceKey={ENC_KEY}&{base_q}")
    show("(b) URL 직접 + Encoding 키", res)
    time.sleep(0.3)

    res = get(f"{REST}/info", raw_query=f"ServiceKey={ENC_KEY}&{base_q}")
    show("(c) URL 직접 + Encoding 키 + 대문자 ServiceKey", res)
    time.sleep(0.3)

    # ── ③ 경로 변형 ─────────────────────────────────────────────
    print("\n" + SEP)
    print("③ 경로 변형 확인")
    print(SEP)

    for label, url in [
        ("/history 엔드포인트", f"{REST}/history"),
        ("경로 끝 슬래시 제거(루트)", REST),
        ("http (https 아님)", REST.replace("https://", "http://") + "/info"),
    ]:
        res = get(url, raw_query=f"serviceKey={ENC_KEY}&{base_q}")
        show(label, res)
        time.sleep(0.3)

    # ── 정리 ────────────────────────────────────────────────────
    print("\n" + SEP)
    print("판독 가이드")
    print(SEP)
    print("  · 대조군만 성공하고 나머지 전부 403")
    print("      → ① 활용신청 미반영. 마이페이지에서 승인 상태와")
    print("         '일반음식점 조회서비스'가 목록에 있는지 확인 후 30분~1시간 뒤 재시도")
    print("  · (b) 또는 (c) 만 성공")
    print("      → ② 이 API 는 Encoding 키를 URL 에 직접 붙여야 함")
    print("  · ③ 중 하나만 성공")
    print("      → 경로 문제. 성공한 형태를 채택")


if __name__ == "__main__":
    buffer = io.StringIO()
    original = sys.stdout

    class _Tee:
        def write(self, data):
            original.write(data)
            buffer.write(data)

        def flush(self):
            original.flush()
            buffer.flush()

    sys.stdout = _Tee()
    try:
        main()
    except Exception as exc:                           # noqa: BLE001
        print(f"\n✗ 예외 {type(exc).__name__}: {exc}")
    finally:
        sys.stdout = original
        text = buffer.getvalue()
        for token in {SERVICE_KEY, ENC_KEY}:
            if token:
                text = text.replace(token, "<SERVICE_KEY_REDACTED>")
        with open("diag6_output.txt", "w", encoding="utf-8") as fp:
            fp.write(text)
        print("\n[저장] diag6_output.txt 기록 완료 (인증키 자동 마스킹)")

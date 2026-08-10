# -*- coding: utf-8 -*-
"""
건축HUB API 파라미터 진단

verify.py 가 오류 없이 0건만 반환하는 원인을 좁힙니다.
응답 원문을 그대로 찍어보고, 파라미터 조합을 바꿔가며 어디서 데이터가
나오기 시작하는지 확인합니다.

실행: 우클릭 > Run 'diag'   →  diag_output.txt 생성
"""
import io
import json
import sys
from urllib.parse import quote

import requests

from secret import SERVICE_KEY

BASE = "https://apis.data.go.kr/1613000/BldRgstHubService"
OP = "getBrTitleInfo"          # 표제부로 진단 (가장 기본)

SEP = "-" * 72


def raw_call(label, **params):
    """응답 원문을 그대로 보여주는 호출."""
    query = {"serviceKey": SERVICE_KEY, "numOfRows": "5", "pageNo": "1"}
    query.update(params)

    print(f"\n{SEP}\n▶ {label}")
    shown = {k: v for k, v in query.items() if k != "serviceKey"}
    print(f"  파라미터: {shown}")

    try:
        res = requests.get(f"{BASE}/{OP}", params=query, timeout=20)
    except requests.RequestException as exc:
        print(f"  ✗ 네트워크 오류: {exc}")
        return

    print(f"  HTTP {res.status_code}   Content-Type: "
          f"{res.headers.get('Content-Type', '?')}")

    body = res.text
    # 응답에 키가 들어있을 경우 마스킹
    for token in {SERVICE_KEY, quote(SERVICE_KEY, safe="")}:
        if token:
            body = body.replace(token, "<KEY>")

    # totalCount 만 따로 뽑아보기
    total = None
    try:
        parsed = json.loads(res.text)
        total = parsed["response"]["body"].get("totalCount")
    except Exception:                                  # noqa: BLE001
        if "<totalCount>" in res.text:
            total = res.text.split("<totalCount>")[1].split("</totalCount>")[0]
    if total is not None:
        print(f"  totalCount = {total}")

    print("  ── 응답 원문 (앞 700자) ──")
    print("  " + body[:700].replace("\n", "\n  "))


def main():
    # 1) 우리가 지금 쓰는 조합 그대로
    raw_call("① 현재 조합 (bun/ji 4자리 zero-pad)",
             sigunguCd="11620", bjdongCd="10100",
             platGbCd="0", bun="1570", ji="0001", _type="json")

    # 2) _type 제거 → XML 응답으로 확인 (json 무시 여부 판별)
    raw_call("② _type 제거 (XML 응답 확인)",
             sigunguCd="11620", bjdongCd="10100",
             platGbCd="0", bun="1570", ji="0001")

    # 3) bun/ji 제거 → 법정동 단위로 조회되는지
    raw_call("③ bun/ji 제거 (법정동 전체 조회)",
             sigunguCd="11620", bjdongCd="10100", _type="json")

    # 4) platGbCd 제거
    raw_call("④ platGbCd 제거",
             sigunguCd="11620", bjdongCd="10100",
             bun="1570", ji="0001", _type="json")

    # 5) zero-pad 없이 숫자 그대로
    raw_call("⑤ bun/ji zero-pad 없이",
             sigunguCd="11620", bjdongCd="10100",
             platGbCd="0", bun="1570", ji="1", _type="json")

    # 6) 부번 0 인 지번으로 (봉천동 862)
    raw_call("⑥ 부번 없는 지번 (봉천동 862)",
             sigunguCd="11620", bjdongCd="10100",
             platGbCd="0", bun="0862", ji="0000", _type="json")

    # 7) 다른 자치구로 교차 확인 (강남구 삼성동)
    raw_call("⑦ 교차 확인 (강남구 11680 삼성동 10500)",
             sigunguCd="11680", bjdongCd="10500", _type="json")


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
    finally:
        sys.stdout = original
        text = buffer.getvalue()
        for token in {SERVICE_KEY, quote(SERVICE_KEY, safe="")}:
            if token:
                text = text.replace(token, "<SERVICE_KEY_REDACTED>")
        with open("diag_output.txt", "w", encoding="utf-8") as fp:
            fp.write(text)
        print("\n[저장] diag_output.txt 기록 완료 (인증키 자동 마스킹)")

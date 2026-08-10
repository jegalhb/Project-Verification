# -*- coding: utf-8 -*-
"""
건축HUB API 진단 2단계 — bun/ji 필터 동작 확인 및 실존 지번 자동 탐색

A. 강남구 삼성동 1-1 정밀 조회  → bun/ji 필터가 작동하는지 결정적 판별
B. 봉천동 200건 샘플링          → 지번 필드 채움 상태 확인
C. B에서 찾은 실존 지번으로     → 층별개요 · 오수정화시설 조회

실행: 우클릭 > Run 'diag2'   →  diag2_output.txt 생성
"""
import io
import json
import sys
from collections import Counter
from urllib.parse import quote

import requests

from secret import SERVICE_KEY

BASE = "https://apis.data.go.kr/1613000/BldRgstHubService"
SEP = "=" * 72


def fetch(op, rows=5, page=1, **params):
    """items 리스트와 totalCount 반환."""
    query = {"serviceKey": SERVICE_KEY, "numOfRows": str(rows),
             "pageNo": str(page), "_type": "json"}
    query.update(params)
    res = requests.get(f"{BASE}/{op}", params=query, timeout=25)
    res.raise_for_status()
    payload = json.loads(res.text)
    body = payload.get("response", payload)["body"]
    items = (body.get("items") or {}).get("item") or []
    if isinstance(items, dict):
        items = [items]
    return items, int(body.get("totalCount") or 0)


def step_a():
    print(SEP)
    print("A. bun/ji 필터 동작 확인 — 강남구 삼성동 1-1 (실존 확인된 레코드)")
    print(SEP)
    items, total = fetch("getBrTitleInfo", sigunguCd="11680", bjdongCd="10500",
                         platGbCd="0", bun="0001", ji="0001")
    print(f"  totalCount = {total}")
    if total:
        print("  ✓ bun/ji 필터 정상 동작 → 파라미터 형식은 맞습니다")
        for it in items[:2]:
            print(f"    {it.get('platPlc')}  |  {it.get('bldNm') or '(무명)'}"
                  f"  |  주용도={it.get('mainPurpsCdNm')}")
    else:
        print("  ✗ 실존 레코드인데도 0건 → bun/ji 가 필터로 동작하지 않음")


def step_b():
    print("\n" + SEP)
    print("B. 봉천동 지번 필드 상태 — 200건 샘플링")
    print(SEP)
    sample, total = fetch("getBrTitleInfo", rows=200,
                          sigunguCd="11620", bjdongCd="10100")
    print(f"  봉천동 전체 = {total:,}건, 샘플 {len(sample)}건")

    empty = sum(1 for it in sample
                if str(it.get("bun", "")).strip("0 ") == ""
                and str(it.get("ji", "")).strip("0 ") == "")
    print(f"  지번 비어있음(bun·ji 모두 0000) : {empty}건 / {len(sample)}건")

    top = Counter(f"{it.get('bun')}-{it.get('ji')}"
                  for it in sample).most_common(5)
    print(f"  상위 지번값: {top}")

    candidates = [it for it in sample if str(it.get("bun", "0000")) != "0000"]
    print(f"  유효 지번 레코드: {len(candidates)}건")
    for it in candidates[:5]:
        print(f"    {it.get('platPlc')}  bun={it.get('bun')} ji={it.get('ji')}"
              f"  주용도={it.get('mainPurpsCdNm')}")
    return candidates


def step_c(candidates):
    print("\n" + SEP)
    print("C. 실존 지번으로 층별개요 · 오수정화시설 조회")
    print(SEP)

    if not candidates:
        print("  ✗ 유효 지번을 찾지 못했습니다. 샘플 수를 늘려야 합니다")
        return

    target = next((c for c in candidates
                   if "근린생활" in str(c.get("mainPurpsCdNm", ""))),
                  candidates[0])
    bun, ji = target["bun"], target["ji"]
    print(f"  대상: {target.get('platPlc')}   (bun={bun}, ji={ji})")
    print(f"        주용도={target.get('mainPurpsCdNm')}  "
          f"연면적={target.get('totArea')}㎡\n")

    common = dict(sigunguCd="11620", bjdongCd="10100",
                  platGbCd="0", bun=bun, ji=ji)

    print("  [층별개요]")
    floors, ftot = fetch("getBrFlrOulnInfo", rows=100, **common)
    print(f"    totalCount = {ftot}")
    for f in floors[:12]:
        print(f"    {f.get('flrGbCdNm', ''):<4}{f.get('flrNoNm', ''):<7}"
              f"{f.get('mainPurpsCdNm', ''):<20}"
              f"{float(f.get('area') or 0):>9.2f}㎡  {f.get('etcPurps', '')}")

    print("\n  [오수정화시설]")
    wclfs, wtot = fetch("getBrWclfInfo", rows=20, **common)
    print(f"    totalCount = {wtot}")
    for w in wclfs:
        print(f"    형식={w.get('modeCdNm', '?'):<16}"
              f"용량(인용)={w.get('capaPsper', '-')}인  "
              f"용량(루베)={w.get('capaLube', '-')}㎥")
    if not wclfs:
        print("    (정화조 미등재)")


def main():
    step_a()
    candidates = step_b()
    step_c(candidates)


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
        for token in {SERVICE_KEY, quote(SERVICE_KEY, safe="")}:
            if token:
                text = text.replace(token, "<SERVICE_KEY_REDACTED>")
        with open("diag2_output.txt", "w", encoding="utf-8") as fp:
            fp.write(text)
        print("\n[저장] diag2_output.txt 기록 완료 (인증키 자동 마스킹)")

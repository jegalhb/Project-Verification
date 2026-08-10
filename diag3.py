# -*- coding: utf-8 -*-
"""
오수정화시설 데이터 채움률 측정 — 킬러 요소의 생사를 가르는 검증

봉천동 건물 N건을 표본으로 getBrWclfInfo 를 호출해
capaPsper(용량·인용) 가 실제로 채워진 비율을 측정합니다.

  채움률이 높으면  → 정화조 판정을 서비스 전면에 낼 수 있음
  채움률이 낮으면  → 보조 지표로 격하하거나 대체 경로 필요

부가로, 층별 용도명이 건축법 별표1 대분류가 아니라 세부 용도명으로
오는 것을 확인했으므로 세부 용도 분포도 함께 집계합니다.

실행: 우클릭 > Run 'diag3'   →  diag3_output.txt 생성
"""
import io
import json
import math
import sys
import time
from collections import Counter
from urllib.parse import quote

import requests

from secret import SERVICE_KEY

BASE = "https://apis.data.go.kr/1613000/BldRgstHubService"
SEP = "=" * 72

SAMPLE_SIZE = 40          # 정화조를 조회할 건물 수 (호출 수 = 이 값 + 2)
K_FOOD = 0.175            # 휴게음식점·일반음식점 공통 인원산정계수


def fetch(op, rows=5, page=1, **params):
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


def main():
    # ── 1. 표본 건물 확보 ──────────────────────────────────────────
    print(SEP)
    print(f"1. 봉천동 표본 확보 (상위 {SAMPLE_SIZE * 3}건에서 추림)")
    print(SEP)
    pool, total = fetch("getBrTitleInfo", rows=SAMPLE_SIZE * 3,
                        sigunguCd="11620", bjdongCd="10100")
    pool = [b for b in pool if str(b.get("bun", "0000")) != "0000"]
    print(f"  봉천동 전체 {total:,}건 / 표본 풀 {len(pool)}건")

    purposes = Counter(b.get("mainPurpsCdNm") or "?" for b in pool)
    print("  표제부 주용도 분포:")
    for name, cnt in purposes.most_common(8):
        print(f"    {name:<22}{cnt:>4}건")

    targets = pool[:SAMPLE_SIZE]

    # ── 2. 정화조 채움률 ──────────────────────────────────────────
    print("\n" + SEP)
    print(f"2. 오수정화시설 채움률 — {len(targets)}건 조회")
    print(SEP)

    filled, zero, missing, errors = [], 0, 0, 0
    for i, b in enumerate(targets, 1):
        common = dict(sigunguCd="11620", bjdongCd="10100", platGbCd="0",
                      bun=b["bun"], ji=b["ji"])
        try:
            wclfs, wtot = fetch("getBrWclfInfo", rows=10, **common)
        except Exception as exc:                       # noqa: BLE001
            errors += 1
            print(f"  [{i:>2}] ✗ {type(exc).__name__}")
            continue

        if not wclfs:
            missing += 1
            continue

        cap = max((int(float(w.get("capaPsper") or 0)) for w in wclfs),
                  default=0)
        if cap > 0:
            mode = next((w.get("modeCdNm") for w in wclfs
                         if w.get("modeCdNm", "").strip()), "(형식 공란)")
            filled.append((b, cap, mode))
        else:
            zero += 1
        time.sleep(0.1)

    n = len(targets)
    print(f"  용량 > 0        : {len(filled):>3}건  ({len(filled)/n*100:.0f}%)")
    print(f"  레코드 있으나 0 : {zero:>3}건  ({zero/n*100:.0f}%)")
    print(f"  레코드 없음     : {missing:>3}건  ({missing/n*100:.0f}%)")
    print(f"  조회 오류       : {errors:>3}건")

    # ── 3. 실제 사례 및 판정 시연 ─────────────────────────────────
    print("\n" + SEP)
    print("3. 용량이 채워진 건물 — 정화조 판정 시연")
    print(SEP)

    if not filled:
        print("  ✗ 표본에서 용량이 채워진 건물이 없습니다.")
        print("    → 표본을 늘리거나, 정화조 판정을 보조 지표로 격하해야 합니다.")
    else:
        for b, cap, mode in filled[:8]:
            area = float(b.get("totArea") or 0)
            need = math.ceil(K_FOOD * area)
            if need <= cap:
                verdict = "여유"
            elif need <= cap * 2:
                verdict = "청소주기 단축 이행각서 검토"
            else:
                verdict = "증설 필요"
            print(f"\n  {b.get('platPlc')}")
            print(f"    주용도={b.get('mainPurpsCdNm')}  연면적={area:.2f}㎡")
            print(f"    정화조 {cap}인용 ({mode})")
            print(f"    → 전체를 음식점으로 쓸 경우 필요 {need}인  ⇒ {verdict}")

    # ── 4. 층별 용도명 세분류 확인 ────────────────────────────────
    print("\n" + SEP)
    print("4. 층별 용도명 형태 확인 (별표1 대분류 vs 세부 용도명)")
    print(SEP)
    checked = 0
    detail = Counter()
    for b in targets:
        if checked >= 8:
            break
        try:
            floors, _ = fetch("getBrFlrOulnInfo", rows=50,
                              sigunguCd="11620", bjdongCd="10100",
                              platGbCd="0", bun=b["bun"], ji=b["ji"])
        except Exception:                              # noqa: BLE001
            continue
        if not floors:
            continue
        checked += 1
        print(f"\n  {b.get('platPlc')}  (표제부 주용도={b.get('mainPurpsCdNm')})")
        for f in floors[:5]:
            name = f.get("mainPurpsCdNm") or "?"
            detail[name] += 1
            print(f"    {f.get('flrGbCdNm', ''):<4}{f.get('flrNoNm', ''):<7}"
                  f"{name:<18}{float(f.get('area') or 0):>9.2f}㎡")
        time.sleep(0.1)

    print("\n  ── 층별 용도명 빈도 ──")
    for name, cnt in detail.most_common(12):
        print(f"    {name:<20}{cnt:>3}회")


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
        with open("diag3_output.txt", "w", encoding="utf-8") as fp:
            fp.write(text)
        print("\n[저장] diag3_output.txt 기록 완료 (인증키 자동 마스킹)")

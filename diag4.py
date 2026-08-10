# -*- coding: utf-8 -*-
"""
정화조 채움률 재측정 — 표본을 근린생활시설로 교정

diag3 의 표본은 지번 앞순서로 뽑혀 단독주택이 90%를 차지했습니다.
음식점 창업 대상은 근린생활시설이므로, 그 용도만 모아 다시 측정합니다.

추가로 '값 0'이 미등재인지 하수도 직결인지 판별하기 위해
사용승인연도 분포를 값 유무별로 비교합니다.
  (하수도 보급 확대 이후 신축일수록 정화조가 불필요해지는 경향 확인)

실행: 우클릭 > Run 'diag4'   →  diag4_output.txt 생성
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

WANT = 35              # 목표 근린생활시설 표본 수
PAGE_ROWS = 300        # 페이지당 조회 건수
MAX_PAGES = 12         # 최대 페이지 수
K_FOOD = 0.175


def fetch(op, rows=5, page=1, **params):
    query = {"serviceKey": SERVICE_KEY, "numOfRows": str(rows),
             "pageNo": str(page), "_type": "json"}
    query.update(params)
    res = requests.get(f"{BASE}/{op}", params=query, timeout=30)
    res.raise_for_status()
    payload = json.loads(res.text)
    body = payload.get("response", payload)["body"]
    items = (body.get("items") or {}).get("item") or []
    if isinstance(items, dict):
        items = [items]
    return items, int(body.get("totalCount") or 0)


def year_of(building):
    """사용승인일자에서 연도 추출 (없으면 None)."""
    raw = str(building.get("useAprDay") or "").strip()
    return int(raw[:4]) if len(raw) >= 4 and raw[:4].isdigit() else None


def main():
    # ── 1. 근린생활시설만 수집 ────────────────────────────────────
    print(SEP)
    print(f"1. 근린생활시설 표본 수집 (목표 {WANT}건)")
    print(SEP)

    picked, scanned = [], 0
    for page in range(1, MAX_PAGES + 1):
        try:
            batch, total = fetch("getBrTitleInfo", rows=PAGE_ROWS, page=page,
                                 sigunguCd="11620", bjdongCd="10100")
        except Exception as exc:                       # noqa: BLE001
            print(f"  페이지 {page} 오류: {type(exc).__name__}")
            break
        if not batch:
            break
        scanned += len(batch)
        for b in batch:
            if str(b.get("bun", "0000")) == "0000":
                continue
            if "근린생활" in str(b.get("mainPurpsCdNm", "")):
                picked.append(b)
        print(f"  페이지 {page:>2}: 누적 스캔 {scanned:,}건 → 근생 {len(picked)}건")
        if len(picked) >= WANT:
            break
        time.sleep(0.15)

    print(f"\n  최종 표본: 근린생활시설 {len(picked)}건 "
          f"(스캔 {scanned:,}건 중 {len(picked)/max(scanned,1)*100:.1f}%)")
    kinds = Counter(b.get("mainPurpsCdNm") for b in picked)
    print(f"  구성: {dict(kinds)}")

    targets = picked[:WANT]
    if not targets:
        print("  ✗ 근린생활시설을 찾지 못했습니다.")
        return

    # ── 2. 정화조 채움률 ──────────────────────────────────────────
    print("\n" + SEP)
    print(f"2. 근린생활시설 정화조 채움률 — {len(targets)}건")
    print(SEP)

    filled, zeros = [], []
    no_record = 0
    for b in targets:
        try:
            wclfs, _ = fetch("getBrWclfInfo", rows=10,
                             sigunguCd="11620", bjdongCd="10100",
                             platGbCd="0", bun=b["bun"], ji=b["ji"])
        except Exception:                              # noqa: BLE001
            continue
        if not wclfs:
            no_record += 1
            continue
        cap = max((int(float(w.get("capaPsper") or 0)) for w in wclfs),
                  default=0)
        mode = next((w.get("modeCdNm") for w in wclfs
                     if str(w.get("modeCdNm", "")).strip()), "")
        (filled if cap > 0 else zeros).append((b, cap, mode))
        time.sleep(0.12)

    n = len(targets)
    print(f"  용량 > 0        : {len(filled):>3}건  ({len(filled)/n*100:.0f}%)")
    print(f"  레코드 있으나 0 : {len(zeros):>3}건  ({len(zeros)/n*100:.0f}%)")
    print(f"  레코드 없음     : {no_record:>3}건  ({no_record/n*100:.0f}%)")

    # ── 3. 값 0 의 정체 — 사용승인연도 비교 ───────────────────────
    print("\n" + SEP)
    print("3. '값 0'은 미등재인가, 하수도 직결인가 — 사용승인연도 비교")
    print(SEP)

    def summarize(label, group):
        years = [y for y in (year_of(b) for b, _, _ in group) if y]
        if not years:
            print(f"  {label}: 연도 정보 없음")
            return
        years.sort()
        mid = years[len(years) // 2]
        print(f"  {label:<16} n={len(years):>3}  "
              f"중앙값 {mid}년   범위 {years[0]}~{years[-1]}")
        buckets = Counter((y // 10) * 10 for y in years)
        line = "  ".join(f"{d}s:{c}" for d, c in sorted(buckets.items()))
        print(f"    {line}")

    summarize("용량 > 0", filled)
    summarize("값 0", zeros)
    print("\n  → 값 0 쪽이 뚜렷하게 신축이면 '하수도 직결'로 해석 가능")
    print("     비슷하면 단순 미등재일 가능성이 큽니다")

    # ── 4. 판정 시연 ──────────────────────────────────────────────
    print("\n" + SEP)
    print("4. 근린생활시설 정화조 판정 시연")
    print(SEP)
    if not filled:
        print("  표본에서 용량이 채워진 근린생활시설이 없습니다.")
    for b, cap, mode in filled[:10]:
        area = float(b.get("totArea") or 0)
        need = math.ceil(K_FOOD * area)
        verdict = ("여유" if need <= cap else
                   "이행각서 검토" if need <= cap * 2 else "증설 필요")
        print(f"\n  {b.get('platPlc')}")
        print(f"    연면적={area:>8.2f}㎡  사용승인={b.get('useAprDay') or '-'}")
        print(f"    정화조 {cap}인용 ({mode or '형식 공란'})")
        print(f"    → 전체 음식점 사용 시 필요 {need}인  ⇒ {verdict}")


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
        with open("diag4_output.txt", "w", encoding="utf-8") as fp:
            fp.write(text)
        print("\n[저장] diag4_output.txt 기록 완료 (인증키 자동 마스킹)")

# -*- coding: utf-8 -*-
"""
건축물 용도명 매핑 테이블 자동 구축

문제
----
층별개요(getBrFlrOulnInfo)의 mainPurpsCdNm 은 세부 용도명으로 옵니다.
  예) 교회 · 소매점 · 다가구주택 · 부대시설
그런데 판정에 필요한 건 건축법 시행령 별표1 의 대분류입니다.
  예) 제2종근린생활시설 · 제1종근린생활시설 · 단독주택

전략
----
표제부(getBrTitleInfo)의 mainPurpsCdNm 은 대분류로 옵니다.
따라서 '모든 층이 같은 세부용도인 건물'을 모으면
  세부용도 → 대분류
쌍을 데이터에서 직접 학습할 수 있습니다.

  1. 관악구 건물 표본에서 표제부 + 층별개요를 함께 수집
  2. 단일용도 건물만 골라 매핑쌍 추출
  3. 용도코드(mainPurpsCd) 구조가 대분류를 인코딩하는지 검증
  4. purpose_map.csv 로 저장 (미해결 항목은 별도 표시)

실행: 우클릭 > Run 'build_purpose_map'  →  purpose_map.csv / build_purpose_map_output.txt
"""
import io
import json
import re
import sys
import time
from collections import Counter, defaultdict
from urllib.parse import quote

import pandas as pd
import requests

from secret import SERVICE_KEY

BLD = "https://apis.data.go.kr/1613000/BldRgstHubService"
SEP = "=" * 74
SIGUNGU = "11620"
DONG = {"봉천동": "10100", "신림동": "10200", "남현동": "10300"}
PAT = re.compile(r"관악구\s+(\S+?동)\s+(산)?\s*(\d+)(?:-(\d+))?")

SAMPLE = 180        # 조회할 건물 수 (호출 = SAMPLE × 2)
SEED = 7


def parse(addr):
    m = PAT.search(str(addr))
    if not m:
        return None
    dong, san, bun, ji = m.groups()
    if dong not in DONG:
        return None
    return (DONG[dong], "1" if san else "0",
            f"{int(bun):04d}", f"{int(ji or 0):04d}")


def call(op, key, rows=50):
    bjdong, plat_gb, bun, ji = key
    params = {"serviceKey": SERVICE_KEY, "sigunguCd": SIGUNGU,
              "bjdongCd": bjdong, "platGbCd": plat_gb, "bun": bun, "ji": ji,
              "numOfRows": str(rows), "pageNo": "1", "_type": "json"}
    res = requests.get(f"{BLD}/{op}", params=params, timeout=25)
    res.raise_for_status()
    body = json.loads(res.text).get("response", {}).get("body", {})
    items = (body.get("items") or {}).get("item") or []
    return [items] if isinstance(items, dict) else items


def main():
    df = pd.read_csv("gwanak_restaurants.csv", dtype=str, encoding="utf-8-sig")
    df = df.dropna(subset=["지번주소"])
    df = df[df["지번주소"].str.contains("관악구", na=False)]
    df = df.drop_duplicates(subset=["지번주소"])
    sample = df.sample(min(SAMPLE, len(df)), random_state=SEED)
    print(f"고유 지번 {len(df):,}건 중 {len(sample)}건 조회\n")

    pairs = Counter()          # (세부용도, 대분류) → 횟수
    codes = defaultdict(set)   # 세부용도 → 용도코드 집합
    detail_all = Counter()     # 세부용도 등장 빈도
    mixed = 0
    ok = 0

    for i, row in enumerate(sample.to_dict("records"), 1):
        key = parse(row["지번주소"])
        if not key:
            continue
        try:
            titles = call("getBrTitleInfo", key, rows=3)
            floors = call("getBrFlrOulnInfo", key)
        except Exception:                              # noqa: BLE001
            continue
        if not titles or not floors:
            continue
        ok += 1

        major = str(titles[0].get("mainPurpsCdNm") or "").strip()
        details = [str(f.get("mainPurpsCdNm") or "").strip() for f in floors]
        details = [d for d in details if d]
        for f in floors:
            nm = str(f.get("mainPurpsCdNm") or "").strip()
            cd = str(f.get("mainPurpsCd") or "").strip()
            if nm:
                detail_all[nm] += 1
                if cd:
                    codes[nm].add(cd)

        uniq = set(details)
        if len(uniq) == 1 and major:
            pairs[(details[0], major)] += 1     # 단일용도 건물 → 확정 쌍
        elif len(uniq) > 1:
            mixed += 1

        time.sleep(0.12)
        if i % 30 == 0:
            print(f"  ...{i}/{len(sample)} 진행 (확정쌍 {len(pairs)}종)")

    print(f"\n  조회 성공 {ok}건   단일용도 건물 {sum(pairs.values())}건   "
          f"복합용도 {mixed}건")

    # ── 1. 학습된 매핑 ────────────────────────────────────────────
    print("\n" + SEP)
    print("1. 데이터에서 학습된 매핑 (단일용도 건물 기준)")
    print(SEP)
    learned = {}
    conflict = defaultdict(list)
    for (detail, major), n in pairs.items():
        conflict[detail].append((major, n))
    for detail, cands in sorted(conflict.items(),
                                key=lambda kv: -sum(c[1] for c in kv[1])):
        cands.sort(key=lambda c: -c[1])
        best, n = cands[0]
        learned[detail] = best
        extra = f"   (경합: {cands[1:]})" if len(cands) > 1 else ""
        print(f"  {detail:<20} → {best:<20} n={n}{extra}")

    # ── 2. 용도코드 구조 검증 ─────────────────────────────────────
    print("\n" + SEP)
    print("2. 용도코드(mainPurpsCd) 가 대분류를 인코딩하는가")
    print(SEP)
    by_prefix = defaultdict(set)
    for detail, major in learned.items():
        for cd in codes.get(detail, []):
            by_prefix[cd[:2]].add(major)
    consistent = sum(1 for v in by_prefix.values() if len(v) == 1)
    print(f"  코드 앞 2자리 그룹 {len(by_prefix)}개 중 "
          f"대분류가 유일한 그룹 {consistent}개")
    for pre, majors in sorted(by_prefix.items()):
        flag = "✓" if len(majors) == 1 else "✗ 혼재"
        print(f"    {pre}xxx  {flag}  {sorted(majors)}")
    if len(by_prefix) and consistent == len(by_prefix):
        print("\n  ★ 코드 앞 2자리로 대분류가 결정됩니다 → 수작업 매핑 최소화 가능")
    else:
        print("\n  → 코드만으로는 부족. 용도명 기반 매핑을 병행해야 합니다")

    # ── 3. 미해결 용도명 ──────────────────────────────────────────
    print("\n" + SEP)
    print("3. 아직 매핑되지 않은 용도명 (복합용도 건물에만 등장)")
    print(SEP)
    unresolved = [(nm, n) for nm, n in detail_all.most_common()
                  if nm not in learned]
    print(f"  총 {len(unresolved)}종 — 손으로 채워야 하는 목록입니다\n")
    for nm, n in unresolved[:40]:
        print(f"    {nm:<24}등장 {n}회   코드 {sorted(codes.get(nm, []))[:3]}")

    # ── 4. CSV 저장 ───────────────────────────────────────────────
    rows = []
    for nm, n in detail_all.most_common():
        rows.append({
            "세부용도명": nm,
            "용도코드": "|".join(sorted(codes.get(nm, []))),
            "별표1_대분류": learned.get(nm, ""),
            "확정여부": "학습" if nm in learned else "수작업필요",
            "등장횟수": n,
        })
    out = pd.DataFrame(rows)
    out.to_csv("purpose_map.csv", index=False, encoding="utf-8-sig")
    print(f"\n  → purpose_map.csv 저장 ({len(out)}행, "
          f"학습 {len(learned)}종 / 수작업 {len(unresolved)}종)")


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
        import traceback
        print(f"\n✗ 예외 {type(exc).__name__}: {exc}")
        traceback.print_exc(file=sys.stdout)
    finally:
        sys.stdout = original
        text = buffer.getvalue()
        for token in {SERVICE_KEY, quote(SERVICE_KEY, safe="")}:
            if token:
                text = text.replace(token, "<SERVICE_KEY_REDACTED>")
        with open("build_purpose_map_output.txt", "w", encoding="utf-8") as fp:
            fp.write(text)
        print("\n[저장] build_purpose_map_output.txt 기록 완료")

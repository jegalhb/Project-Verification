# -*- coding: utf-8 -*-
"""
행안부 인허가 원장(일반음식점) API 검증

  Base : https://apis.data.go.kr/1741000/general_restaurants
  엔드포인트 : /info (현황) · /history (이력)

파라미터 명세가 공개되지 않아, 먼저 조합을 탐색해 동작하는 형태를 찾은 뒤
그 조합으로 좌표·생존율 검증까지 이어서 수행합니다.

  1. 파라미터 탐색      — 어떤 조합이 데이터를 반환하는가
  2. 응답 필드 확인      — 좌표 / 인허가일자 / 폐업일자 / 영업상태
  3. 실좌표 변환 검증    — EPSG:5174 → WGS84, 주소와 대조
  4. 생존율 표본 확인    — 연도별 코호트 규모와 폐업 비율

실행: 우클릭 > Run 'diag5'   →  diag5_output.txt 생성
"""
import io
import json
import sys
import time
from collections import Counter, defaultdict
from urllib.parse import quote

import requests

from secret import SERVICE_KEY

BASE = "https://apis.data.go.kr/1741000/general_restaurants"
SEP = "=" * 72

# 관악구 코드 후보 — 행안부 개방자치단체코드 / 행정표준코드 둘 다 시도
GWANAK_LOCAL = "3220000"
GWANAK_SGG = "11620"


def raw_get(op, params, timeout=25):
    query = {"serviceKey": SERVICE_KEY}
    query.update(params)
    return requests.get(f"{BASE}/{op}", params=query, timeout=timeout)


def peek(res, limit=600):
    """응답 원문에서 키를 가리고 앞부분만 반환."""
    body = res.text
    for token in {SERVICE_KEY, quote(SERVICE_KEY, safe="")}:
        if token:
            body = body.replace(token, "<KEY>")
    return body[:limit]


def extract(res):
    """가능한 여러 응답 구조에서 (items, total) 추출."""
    try:
        data = json.loads(res.text)
    except Exception:                                  # noqa: BLE001
        return None, None

    # 흔한 구조들을 차례로 시도
    node = data.get("response", data)
    body = node.get("body", node)

    items = body.get("items") or body.get("item") or body.get("row")
    if isinstance(items, dict):
        items = items.get("item") or items.get("row") or [items]
    if isinstance(items, dict):
        items = [items]
    total = body.get("totalCount") or body.get("total_count") or body.get("totalCnt")

    # LOCALDATA 계열: {"result": {"header":..., "body": {"rows":[{"row":[...]}]}}}
    if items is None and "result" in data:
        rows = data["result"].get("body", {}).get("rows")
        if rows and isinstance(rows, list):
            items = rows[0].get("row") if isinstance(rows[0], dict) else rows
        total = data["result"].get("body", {}).get("totalCount", total)

    return (items if isinstance(items, list) else None,
            int(total) if str(total).isdigit() else None)


# ── 1. 파라미터 탐색 ──────────────────────────────────────────────
TRIALS = [
    ("A. serviceKey 만", {}),
    ("B. pageNo/numOfRows + _type", {"pageNo": "1", "numOfRows": "5", "_type": "json"}),
    ("C. pageIndex/pageSize + resultType", {"pageIndex": "1", "pageSize": "5", "resultType": "json"}),
    ("D. localCode(개방자치단체코드)", {"pageIndex": "1", "pageSize": "5", "resultType": "json", "localCode": GWANAK_LOCAL}),
    ("E. sigunguCd(행정표준코드)", {"pageNo": "1", "numOfRows": "5", "_type": "json", "sigunguCd": GWANAK_SGG}),
    ("F. type=json (밑줄 없음)", {"pageNo": "1", "numOfRows": "5", "type": "json"}),
]


def step1():
    print(SEP)
    print("1. 파라미터 탐색  —  /info")
    print(SEP)
    working = None
    for label, params in TRIALS:
        print(f"\n▶ {label}")
        print(f"  파라미터: {params}")
        try:
            res = raw_get("info", params)
        except requests.RequestException as exc:
            print(f"  ✗ 네트워크 오류: {exc}")
            continue
        print(f"  HTTP {res.status_code}  Content-Type: "
              f"{res.headers.get('Content-Type', '?')}")
        items, total = extract(res)
        print(f"  items={('None' if items is None else len(items))}  total={total}")
        print("  ── 응답 앞부분 ──")
        print("  " + peek(res).replace("\n", "\n  "))
        if items:
            working = (label, params)
            print(f"  ✓ 데이터 반환 성공")
            break
        time.sleep(0.2)
    return working


def step2(params):
    print("\n" + SEP)
    print("2. 응답 필드 확인")
    print(SEP)
    bigger = dict(params)
    for key in ("numOfRows", "pageSize"):
        if key in bigger:
            bigger[key] = "50"
    res = raw_get("info", bigger)
    items, total = extract(res)
    if not items:
        print("  ✗ 데이터 없음")
        return []
    print(f"  총 {total}건 중 {len(items)}건 수신\n")
    print("  ── 첫 레코드의 필드 목록 ──")
    first = items[0]
    for k, v in list(first.items()):
        text = str(v)
        print(f"    {k:<24}{text[:40]}")
    return items


def step3(items):
    print("\n" + SEP)
    print("3. 실좌표 변환 검증  EPSG:5174 → WGS84")
    print(SEP)
    from pyproj import CRS, Transformer

    proj = ("+proj=tmerc +lat_0=38 +lon_0=127.0028902777778 +k=1 "
            "+x_0=200000 +y_0=500000 +ellps=bessel +units=m +no_defs "
            "+towgs84=-115.80,474.99,674.11,1.16,-2.31,-1.63,6.43")
    to_wgs = Transformer.from_crs(CRS.from_proj4(proj), CRS.from_epsg(4326),
                                  always_xy=True)

    xkeys = [k for k in items[0] if k.lower() in ("x", "xcode", "x_cd", "coordx")]
    ykeys = [k for k in items[0] if k.lower() in ("y", "ycode", "y_cd", "coordy")]
    if not xkeys or not ykeys:
        cands = [k for k in items[0] if "x" in k.lower() or "y" in k.lower()]
        print(f"  ⚠ 좌표 필드 자동 식별 실패. 후보: {cands}")
        return
    xk, yk = xkeys[0], ykeys[0]
    print(f"  좌표 필드: {xk} / {yk}\n")

    shown = 0
    for it in items:
        try:
            x, y = float(it.get(xk) or 0), float(it.get(yk) or 0)
        except (TypeError, ValueError):
            continue
        if x <= 0 or y <= 0:
            continue
        lon, lat = to_wgs.transform(x, y)
        inside = 126.76 <= lon <= 127.19 and 37.42 <= lat <= 37.70
        addr = (it.get("rdnWhlAddr") or it.get("siteWhlAddr")
                or it.get("도로명전체주소") or it.get("소재지전체주소") or "-")
        name = (it.get("bplcNm") or it.get("사업장명") or "-")
        print(f"  {name}  |  {str(addr)[:44]}")
        print(f"    X={x:.2f} Y={y:.2f} → {lon:.6f}, {lat:.6f}  "
              f"{'서울 OK' if inside else '⚠ 서울 밖'}")
        print(f"    https://map.kakao.com/link/map/{name},{lat},{lon}")
        shown += 1
        if shown >= 5:
            break
    if shown == 0:
        print("  ⚠ 좌표값이 모두 0 또는 비어 있음")


def step4(params):
    print("\n" + SEP)
    print("4. 생존율 표본 확인  —  인허가일자 · 폐업일자 · 영업상태")
    print(SEP)
    bulk = dict(params)
    for key in ("numOfRows", "pageSize"):
        if key in bulk:
            bulk[key] = "100"

    collected = []
    for page in range(1, 11):
        for key in ("pageNo", "pageIndex"):
            if key in bulk:
                bulk[key] = str(page)
        try:
            res = raw_get("info", bulk, timeout=30)
            items, _ = extract(res)
        except Exception:                              # noqa: BLE001
            break
        if not items:
            break
        collected.extend(items)
        time.sleep(0.15)
    print(f"  수집 {len(collected)}건")
    if not collected:
        return

    sample = collected[0]
    open_key = next((k for k in sample if "apv" in k.lower() or "인허가" in k), None)
    close_key = next((k for k in sample if "cls" in k.lower() or "폐업" in k), None)
    state_key = next((k for k in sample
                      if "trdstate" in k.lower() or "영업상태" in k), None)
    print(f"  식별된 필드 → 인허가일자={open_key}  폐업일자={close_key}  "
          f"영업상태={state_key}")

    if state_key:
        print(f"\n  영업상태 분포: "
              f"{dict(Counter(str(i.get(state_key)) for i in collected).most_common(6))}")

    if open_key:
        cohort = defaultdict(lambda: [0, 0])
        for it in collected:
            raw = str(it.get(open_key) or "")
            if len(raw) < 4 or not raw[:4].isdigit():
                continue
            year = int(raw[:4])
            cohort[year][0] += 1
            closed = str(it.get(close_key) or "").strip() if close_key else ""
            if closed and closed not in ("None", "nan"):
                cohort[year][1] += 1
        print("\n  ── 인허가 연도별 코호트 (표본 기준) ──")
        print(f"  {'연도':<8}{'개업':>6}{'폐업':>6}{'폐업률':>9}")
        for year in sorted(cohort)[-15:]:
            total, closed = cohort[year]
            rate = f"{closed/total*100:.0f}%" if total else "-"
            print(f"  {year:<8}{total:>6}{closed:>6}{rate:>9}")
        sizes = [v[0] for v in cohort.values()]
        if sizes:
            print(f"\n  연도별 표본 크기: 최소 {min(sizes)} / 최대 {max(sizes)}")
            print("  → 30건 미만 연도가 많으면 생존율 지표는 신뢰하기 어렵습니다")


def main():
    working = step1()
    if not working:
        print("\n✗ 동작하는 파라미터 조합을 찾지 못했습니다.")
        print("  공공데이터포털 활용가이드(첨부문서)를 확인해야 합니다.")
        return
    label, params = working
    print(f"\n★ 채택된 조합: {label}  {params}")

    items = step2(params)
    if items:
        step3(items)
    step4(params)


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
        with open("diag5_output.txt", "w", encoding="utf-8") as fp:
            fp.write(text)
        print("\n[저장] diag5_output.txt 기록 완료 (인증키 자동 마스킹)")

# -*- coding: utf-8 -*-
"""
인허가 원장 API 본검증 — 필드 · 필터 · 좌표 · 이력 · 생존율

diag6 에서 접속이 확인되었고, 필드명이 대문자 스네이크케이스임을 발견했습니다.
  BPLC_NM(사업장명) · BZSTAT_SE_NM(영업상태) · CLSBIZ_YMD(폐업일자)
  CRD_INFO_X / CRD_INFO_Y (좌표)

  1. 전체 필드 덤프        — 실제 스키마 확인
  2. 지역 필터 파라미터 탐색 — 관악구만 뽑는 방법
  3. 좌표 실검증           — 상호·주소와 지도 링크 대조
  4. /history 필수 파라미터 탐색
  5. 생존율 표본           — 인허가연도 코호트와 폐업률

실행: 우클릭 > Run 'diag7'   →  diag7_output.txt 생성
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


def get(op, **params):
    query = {"serviceKey": SERVICE_KEY, "pageNo": "1",
             "numOfRows": "5", "_type": "json"}
    query.update(params)
    res = requests.get(f"{BASE}/{op}", params=query, timeout=30)
    try:
        data = json.loads(res.text)
    except Exception:                                  # noqa: BLE001
        return None, None, res.text[:300]
    node = data.get("response", data)
    header = node.get("header", {})
    body = node.get("body", {})
    items = (body.get("items") or {}).get("item") or []
    if isinstance(items, dict):
        items = [items]
    return items, body.get("totalCount"), header.get("resultMsg")


def mask(text):
    for token in {SERVICE_KEY, quote(SERVICE_KEY, safe="")}:
        if token:
            text = text.replace(token, "<KEY>")
    return text


# ── 1. 전체 필드 덤프 ─────────────────────────────────────────────
def step1():
    print(SEP)
    print("1. /info 전체 필드 덤프")
    print(SEP)
    items, total, msg = get("info", numOfRows="1")
    if not items:
        print(f"  ✗ 데이터 없음 (msg={msg})")
        return None
    print(f"  totalCount = {total}   resultMsg = {msg}\n")
    rec = items[0]
    print(f"  필드 수: {len(rec)}개")
    for key, value in rec.items():
        print(f"    {key:<26}{str(value)[:44]}")
    return rec


# ── 2. 지역 필터 파라미터 탐색 ────────────────────────────────────
FILTERS = [
    ("localCode=3220000 (개방자치단체코드)", {"localCode": "3220000"}),
    ("LOCALDATA_CODE=3220000", {"LOCALDATA_CODE": "3220000"}),
    ("opnSfTeamCode=3220000", {"opnSfTeamCode": "3220000"}),
    ("sigunguCd=11620", {"sigunguCd": "11620"}),
    ("CTPV_NM=서울특별시", {"CTPV_NM": "서울특별시"}),
    ("SIGNGU_NM=관악구", {"SIGNGU_NM": "관악구"}),
    ("RDNMADR=관악구 (주소 부분검색)", {"RDNMADR": "관악구"}),
    ("bgnYmd/endYmd (기간)", {"bgnYmd": "20240101", "endYmd": "20241231"}),
]


def step2():
    print("\n" + SEP)
    print("2. 지역 필터 파라미터 탐색")
    print(SEP)
    base_items, base_total, _ = get("info", numOfRows="1")
    base_name = base_items[0].get("BPLC_NM") if base_items else None
    print(f"  기준(필터 없음): total={base_total}  첫 레코드={base_name}\n")

    working = []
    for label, params in FILTERS:
        try:
            items, total, msg = get("info", numOfRows="3", **params)
        except Exception as exc:                       # noqa: BLE001
            print(f"  {label:<40} ✗ {type(exc).__name__}")
            continue
        name = items[0].get("BPLC_NM") if items else "-"
        addr = ""
        if items:
            addr = (items[0].get("RDNMADR") or items[0].get("LOCPLC_FACLT_TELNO")
                    or items[0].get("SITE_ADDR") or "")
        changed = (total != base_total) or (name != base_name)
        flag = "★ 필터 적용됨" if changed and items else "  변화 없음"
        print(f"  {label:<40} total={str(total):<10}{flag}")
        if changed and items:
            print(f"      → {name}  {str(addr)[:40]}")
            working.append((label, params))
        time.sleep(0.2)
    return working


# ── 3. 좌표 실검증 ────────────────────────────────────────────────
def step3():
    print("\n" + SEP)
    print("3. 좌표 실검증 — CRD_INFO_X / CRD_INFO_Y")
    print(SEP)
    from pyproj import CRS, Transformer

    proj = ("+proj=tmerc +lat_0=38 +lon_0=127.0028902777778 +k=1 "
            "+x_0=200000 +y_0=500000 +ellps=bessel +units=m +no_defs "
            "+towgs84=-115.80,474.99,674.11,1.16,-2.31,-1.63,6.43")
    to_wgs = Transformer.from_crs(CRS.from_proj4(proj), CRS.from_epsg(4326),
                                  always_xy=True)

    items, _, _ = get("info", numOfRows="20")
    shown = 0
    for it in items or []:
        try:
            x = float(it.get("CRD_INFO_X") or 0)
            y = float(it.get("CRD_INFO_Y") or 0)
        except (TypeError, ValueError):
            continue
        if x <= 0 or y <= 0:
            continue
        lon, lat = to_wgs.transform(x, y)
        name = it.get("BPLC_NM") or "-"
        addr = next((it.get(k) for k in
                     ("RDNMADR", "SITE_ADDR", "LOCPLC_ADDR", "REFINE_ROADNM_ADDR")
                     if it.get(k)), "-")
        print(f"\n  {name}")
        print(f"    등록주소: {str(addr)[:56]}")
        print(f"    X={x:.2f}  Y={y:.2f}  →  {lon:.6f}, {lat:.6f}")
        print(f"    https://map.kakao.com/link/map/{name},{lat},{lon}")
        shown += 1
        if shown >= 6:
            break
    if shown == 0:
        print("  ⚠ 좌표값이 모두 비어 있습니다")
    print("\n  ※ 지도 링크를 열어 '등록주소'와 실제 위치가 일치하는지 확인하세요.")
    print("     한 블록(수백 m) 어긋나면 좌표계 해석을 다시 봐야 합니다.")


# ── 4. /history 파라미터 탐색 ─────────────────────────────────────
HIST = [
    ("bgnYmd/endYmd", {"bgnYmd": "20250101", "endYmd": "20250131"}),
    ("lastModTsBgn/End", {"lastModTsBgn": "20250101", "lastModTsEnd": "20250131"}),
    ("stdrDe", {"stdrDe": "20250101"}),
    ("crtrYmd", {"crtrYmd": "20250101"}),
    ("localCode + 기간", {"localCode": "3220000",
                        "bgnYmd": "20250101", "endYmd": "20250131"}),
]


def step4():
    print("\n" + SEP)
    print("4. /history 필수 파라미터 탐색")
    print(SEP)
    for label, params in HIST:
        try:
            items, total, msg = get("history", numOfRows="3", **params)
        except Exception as exc:                       # noqa: BLE001
            print(f"  {label:<28} ✗ {type(exc).__name__}")
            continue
        mark = "★ 성공" if items else "  "
        print(f"  {label:<28} total={str(total):<8} msg={msg}  {mark}")
        if items:
            print(f"      필드: {list(items[0].keys())[:8]}")
        time.sleep(0.2)


# ── 5. 생존율 표본 ────────────────────────────────────────────────
def step5(filters):
    print("\n" + SEP)
    print("5. 생존율 표본 — 인허가연도 코호트")
    print(SEP)
    extra = dict(filters[0][1]) if filters else {}
    if extra:
        print(f"  적용 필터: {extra}")
    else:
        print("  ⚠ 지역 필터를 찾지 못해 전국 데이터 기준입니다")

    rows = []
    for page in range(1, 11):
        try:
            items, _, _ = get("info", pageNo=str(page), numOfRows="100", **extra)
        except Exception:                              # noqa: BLE001
            break
        if not items:
            break
        rows.extend(items)
        time.sleep(0.15)
    print(f"  수집 {len(rows)}건")
    if not rows:
        return

    states = Counter(str(r.get("BZSTAT_SE_NM") or "?") for r in rows)
    print(f"\n  영업상태 분포: {dict(states.most_common(8))}")

    open_key = next((k for k in rows[0] if "APV_PERM" in k or "PERM_YMD" in k
                     or k == "LICENSG_DE"), None)
    print(f"  인허가일자 추정 필드: {open_key}")

    if not open_key:
        print("  ⚠ 인허가일자 필드를 식별하지 못했습니다. 1번 필드 목록을 확인하세요.")
        return

    cohort = defaultdict(lambda: [0, 0])
    for r in rows:
        raw = str(r.get(open_key) or "")
        if len(raw) < 4 or not raw[:4].isdigit():
            continue
        year = int(raw[:4])
        cohort[year][0] += 1
        if str(r.get("CLSBIZ_YMD") or "").strip():
            cohort[year][1] += 1

    print(f"\n  {'연도':<8}{'개업':>6}{'폐업':>6}{'폐업률':>9}")
    for year in sorted(cohort)[-15:]:
        total, closed = cohort[year]
        print(f"  {year:<8}{total:>6}{closed:>6}"
              f"{(f'{closed/total*100:.0f}%' if total else '-'):>9}")
    sizes = [v[0] for v in cohort.values()]
    if sizes:
        print(f"\n  연도별 표본: 최소 {min(sizes)} / 최대 {max(sizes)}")
        print("  → 30건 미만 연도가 많으면 생존율 지표는 신뢰하기 어렵습니다")


def main():
    step1()
    working = step2()
    step3()
    step4()
    step5(working)


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
        with open("diag7_output.txt", "w", encoding="utf-8") as fp:
            fp.write(mask(buffer.getvalue()))
        print("\n[저장] diag7_output.txt 기록 완료 (인증키 자동 마스킹)")

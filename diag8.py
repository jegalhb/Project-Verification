# -*- coding: utf-8 -*-
"""
인허가 원장 — 파일 일괄 수집 경로 확인 + 올바른 필드로 생존율 재산출

diag7 결과 반영:
  · 지역 필터 파라미터가 없어 API 로는 전국 229만 건을 통째로 받아야 함
    → 파일 일괄 다운로드 경로를 확인한다
  · 필드명 오인 정정
      인허가일자 = LCPMT_YMD      (APV_PERM 아님)
      영업상태   = SALS_STTS_NM   (BZSTAT_SE_NM 은 업태명)
      폐업일자   = CLSBIZ_YMD
      자치단체   = OPN_ATMY_GRP_CD  (관악구 = 3220000)

  1. 파일 다운로드 경로 탐색 (용량만 확인, 전체 내려받지 않음)
  2. 올바른 필드로 생존율 로직 재검증
  3. 관악구 레코드 추출 가능성 확인
  4. 서울 레코드 좌표 정합성 — 주소와 대조

실행: 우클릭 > Run 'diag8'   →  diag8_output.txt 생성
"""
import io
import json
import sys
import time
from collections import Counter, defaultdict
from urllib.parse import quote

import requests

from secret import SERVICE_KEY

API = "https://apis.data.go.kr/1741000/general_restaurants"
SEP = "=" * 72
GWANAK = "3220000"          # 개방자치단체코드 (관악구)


def mask(text):
    for token in {SERVICE_KEY, quote(SERVICE_KEY, safe="")}:
        if token:
            text = text.replace(token, "<KEY>")
    return text


def api_get(op="info", **params):
    query = {"serviceKey": SERVICE_KEY, "pageNo": "1",
             "numOfRows": "100", "_type": "json"}
    query.update(params)
    res = requests.get(f"{API}/{op}", params=query, timeout=30)
    data = json.loads(res.text)
    body = data.get("response", data).get("body", {})
    items = (body.get("items") or {}).get("item") or []
    if isinstance(items, dict):
        items = [items]
    return items, body.get("totalCount")


# ── 1. 파일 다운로드 경로 탐색 ────────────────────────────────────
FILE_URLS = [
    "https://file.localdata.go.kr/file/general_restaurants/info",
    "https://file.localdata.go.kr/file/general_restaurants/info.zip",
    "https://file.localdata.go.kr/file/general_restaurants",
    "https://file.localdata.go.kr/file/food_general_restaurants/info",
]


def step1():
    print(SEP)
    print("1. 파일 일괄 다운로드 경로 탐색  (용량만 확인, 전체는 받지 않음)")
    print(SEP)
    found = []
    for url in FILE_URLS:
        print(f"\n▶ {url}")
        try:
            # 헤더만 먼저
            head = requests.head(url, timeout=20, allow_redirects=True)
            size = head.headers.get("Content-Length")
            ctype = head.headers.get("Content-Type", "?")
            disp = head.headers.get("Content-Disposition", "")
            print(f"  HEAD {head.status_code}  type={ctype}  "
                  f"size={int(size)/1024/1024:.1f}MB" if size
                  else f"  HEAD {head.status_code}  type={ctype}  size=미상")
            if disp:
                print(f"  파일명: {disp[:80]}")

            if head.status_code >= 400:
                continue

            # 앞부분만 조금 받아 내용 확인
            with requests.get(url, stream=True, timeout=30) as res:
                chunk = next(res.iter_content(chunk_size=4096), b"")
            preview = chunk[:300]
            is_zip = preview[:2] == b"PK"
            print(f"  선두 바이트: {'ZIP 아카이브' if is_zip else preview[:80]!r}")
            found.append(url)
        except requests.RequestException as exc:
            print(f"  ✗ {type(exc).__name__}: {exc}")
        time.sleep(0.3)

    if found:
        print(f"\n  ★ 접근 가능한 경로 {len(found)}건: {found}")
        print("     → 전체 다운로드는 용량 확인 후 별도로 진행하세요")
    else:
        print("\n  ✗ 파일 경로를 찾지 못했습니다.")
        print("     공공데이터포털 파일데이터 페이지에서 실제 링크 확인 필요:")
        print("     https://www.data.go.kr/data/15045016/fileData.do")
    return found


# ── 2. 올바른 필드로 생존율 재산출 ────────────────────────────────
def step2():
    print("\n" + SEP)
    print("2. 생존율 로직 재검증  (정정된 필드명 적용)")
    print(SEP)

    rows = []
    for page in range(1, 11):
        try:
            items, total = api_get(pageNo=str(page))
        except Exception as exc:                       # noqa: BLE001
            print(f"  페이지 {page} 오류: {type(exc).__name__}")
            break
        if not items:
            break
        rows.extend(items)
        time.sleep(0.15)
    print(f"  수집 {len(rows)}건 (전국 표본)")
    if not rows:
        return rows

    print(f"\n  영업상태(SALS_STTS_NM): "
          f"{dict(Counter(str(r.get('SALS_STTS_NM') or '?') for r in rows).most_common(6))}")
    print(f"  상세상태(DTL_SALS_STTS_NM): "
          f"{dict(Counter(str(r.get('DTL_SALS_STTS_NM') or '?') for r in rows).most_common(6))}")

    dated = [r for r in rows if str(r.get("LCPMT_YMD") or "").strip()]
    closed = [r for r in rows if str(r.get("CLSBIZ_YMD") or "").strip()]
    print(f"\n  인허가일자(LCPMT_YMD) 채움: {len(dated)}/{len(rows)}건")
    print(f"  폐업일자(CLSBIZ_YMD)  채움: {len(closed)}/{len(rows)}건")

    cohort = defaultdict(lambda: [0, 0])
    for r in dated:
        raw = str(r.get("LCPMT_YMD"))[:4]
        if not raw.isdigit():
            continue
        cohort[int(raw)][0] += 1
        if str(r.get("CLSBIZ_YMD") or "").strip():
            cohort[int(raw)][1] += 1

    if cohort:
        print(f"\n  ── 인허가 연도별 코호트 (전국 표본 {len(dated)}건) ──")
        print(f"  {'연도':<8}{'개업':>6}{'폐업':>6}{'폐업률':>9}")
        for year in sorted(cohort)[-12:]:
            tot, cls = cohort[year]
            print(f"  {year:<8}{tot:>6}{cls:>6}"
                  f"{(f'{cls/tot*100:.0f}%' if tot else '-'):>9}")
        sizes = [v[0] for v in cohort.values()]
        print(f"\n  연도별 표본: 최소 {min(sizes)} / 최대 {max(sizes)}")
    return rows


# ── 3. 관악구 추출 가능성 ─────────────────────────────────────────
def step3(rows):
    print("\n" + SEP)
    print("3. 관악구 레코드 추출 가능성")
    print(SEP)
    if not rows:
        return
    codes = Counter(str(r.get("OPN_ATMY_GRP_CD") or "?") for r in rows)
    print(f"  표본에 등장한 자치단체코드 상위: {dict(codes.most_common(8))}")
    gwanak = [r for r in rows if str(r.get("OPN_ATMY_GRP_CD")) == GWANAK]
    print(f"  관악구({GWANAK}) 레코드: {len(gwanak)}건 / {len(rows)}건 "
          f"({len(gwanak)/len(rows)*100:.2f}%)")
    print(f"\n  → 전국 229만 건 중 관악구 비율이 약 {len(gwanak)/len(rows)*100:.2f}% 라면")
    print(f"     관악구 전체는 대략 {int(2290260 * len(gwanak)/len(rows)):,}건 규모로 추정됩니다")
    print("     API 페이징으로는 비현실적 → 파일 일괄 수집이 정답")


# ── 4. 서울 레코드 좌표 정합성 ────────────────────────────────────
def step4(rows):
    print("\n" + SEP)
    print("4. 좌표 정합성 — 등록주소와 변환 좌표 대조 (서울 레코드)")
    print(SEP)
    if not rows:
        return
    from pyproj import CRS, Transformer

    proj = ("+proj=tmerc +lat_0=38 +lon_0=127.0028902777778 +k=1 "
            "+x_0=200000 +y_0=500000 +ellps=bessel +units=m +no_defs "
            "+towgs84=-115.80,474.99,674.11,1.16,-2.31,-1.63,6.43")
    to_wgs = Transformer.from_crs(CRS.from_proj4(proj), CRS.from_epsg(4326),
                                  always_xy=True)

    seoul = [r for r in rows
             if "서울" in str(r.get("LOTNO_ADDR") or r.get("ROAD_NM_ADDR") or "")]
    print(f"  서울 레코드 {len(seoul)}건 중 5건 확인\n")
    shown = 0
    for r in seoul:
        try:
            x, y = float(r.get("CRD_INFO_X") or 0), float(r.get("CRD_INFO_Y") or 0)
        except (TypeError, ValueError):
            continue
        if x <= 0 or y <= 0:
            continue
        lon, lat = to_wgs.transform(x, y)
        ok = 126.76 <= lon <= 127.19 and 37.42 <= lat <= 37.70
        print(f"  {r.get('BPLC_NM')}")
        print(f"    지번: {str(r.get('LOTNO_ADDR') or '-')[:52]}")
        print(f"    도로: {str(r.get('ROAD_NM_ADDR') or '-')[:52]}")
        print(f"    → {lon:.6f}, {lat:.6f}  {'서울 범위 OK' if ok else '⚠ 범위 밖'}")
        print(f"    https://map.kakao.com/link/map/{r.get('BPLC_NM')},{lat},{lon}\n")
        shown += 1
        if shown >= 5:
            break
    print("  ※ 링크를 열어 지번주소와 핀 위치가 같은 건물인지 확인하세요.")


def main():
    step1()
    rows = step2()
    step3(rows)
    step4(rows)


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
        with open("diag8_output.txt", "w", encoding="utf-8") as fp:
            fp.write(mask(buffer.getvalue()))
        print("\n[저장] diag8_output.txt 기록 완료 (인증키 자동 마스킹)")

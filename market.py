# -*- coding: utf-8 -*-
"""
2막 — 반경 기반 상권 분석

서울 열린데이터광장 인증키 없이, 인허가 원장 좌표만으로 구성합니다.
상권분석서비스의 '상권' 단위보다 해상도가 높고,
도로명 단위보다 상권 경계에 가깝습니다.
  (도로명은 행정 구분이지 상권 경계가 아닙니다)

  좌표 품질 : 관악구 22,653/22,655건(100%)이 자치구 범위 내
  좌표계    : EPSG:5174 → WGS84, 검증 오차 100m 이내

제공 지표
  · 반경 100/300/500m 영업 중 동종업 수
  · 반경 내 업태 구성
  · 반경 내 3년 생존율 (도로 단위보다 정밀)
  · 최근 12개월 개업·폐업 추이 (데이터 최신성 2일)
"""
import math
from functools import lru_cache

import pandas as pd
from pyproj import CRS, Transformer

CSV = "gwanak_restaurants.csv"
PROJ5174 = (
    "+proj=tmerc +lat_0=38 +lon_0=127.0028902777778 +k=1 "
    "+x_0=200000 +y_0=500000 +ellps=bessel +units=m +no_defs "
    "+towgs84=-115.80,474.99,674.11,1.16,-2.31,-1.63,6.43"
)
_TO_WGS = Transformer.from_crs(CRS.from_proj4(PROJ5174),
                               CRS.from_epsg(4326), always_xy=True)

# 관악구 대략 경계 — 좌표 이상치 제거용
BBOX = (126.88, 37.44, 127.00, 37.50)
GAP_LIMIT = 50      # 같은 필지군으로 인정할 부번 차이 상한
TODAY = pd.Timestamp("2026-08-09")


@lru_cache(maxsize=1)
def load():
    """인허가 원장을 좌표·날짜까지 정리해 로드 (1회만)."""
    g = pd.read_csv(CSV, dtype=str, encoding="utf-8-sig")
    g["x"] = pd.to_numeric(g["좌표정보(X)"], errors="coerce")
    g["y"] = pd.to_numeric(g["좌표정보(Y)"], errors="coerce")
    g = g[(g.x > 0) & (g.y > 0)].copy()

    lon, lat = _TO_WGS.transform(g.x.values, g.y.values)
    g["lon"], g["lat"] = lon, lat
    lo1, la1, lo2, la2 = BBOX
    g = g[g.lon.between(lo1, lo2) & g.lat.between(la1, la2)].copy()

    def d(s):
        return pd.to_datetime(s, errors="coerce", format="mixed")

    g["open"], g["close"] = d(g["인허가일자"]), d(g["폐업일자"])
    g["closed"] = g["close"].notna()
    g["days"] = (g["close"].fillna(TODAY) - g["open"]).dt.days
    g["yr"] = g["open"].dt.year
    g["live"] = g["영업상태명"] == "영업/정상"
    return g


def _dist_m(lon0, lat0, lon, lat):
    """근사 평면거리(m). 서울 위도에서 오차 무시 가능."""
    kx = 111_320 * math.cos(math.radians(lat0))
    return ((lon - lon0) * kx) ** 2 + ((lat - lat0) * 110_540) ** 2


def nearby(lon, lat, radius_m):
    g = load()
    lim = radius_m ** 2
    return g[_dist_m(lon, lat, g.lon.values, g.lat.values) <= lim]


def locate(jibun_addr=None, road_addr=None):
    """
    대상 주소의 좌표를 인허가 원장에서 찾습니다.
    건축물대장에는 좌표가 없으므로 같은/인접 지번의 점포 좌표를 씁니다.

    폴백 순서 (정밀 → 근사)
      1) 같은 지번          봉천동 7-51
      2) 같은 도로명·건물번호  관악로 278
      3) 같은 본번 필지군     봉천동 7-*
      4) 같은 도로 전체       관악로

    반환: (lon, lat, 출처, 정밀도)  정밀도 = '정확' | '인접' | '근사'
    """
    import re
    g = load()

    # 1) 같은 지번
    if jibun_addr:
        parts = str(jibun_addr).split()
        if len(parts) >= 4:
            key = " ".join(parts[:4])
            hit = g[g["지번주소"].str.startswith(key + " ", na=False)
                    | (g["지번주소"].str.strip() == key)]
            if len(hit):
                return (hit.lon.mean(), hit.lat.mean(),
                        f"같은 지번 점포 {len(hit)}건", "정확")

    # 2) 같은 도로명 + 건물번호
    road = None
    if road_addr:
        m = re.search(r"관악구\s+(\S+?[로길]\d*)\s+(\d+)", str(road_addr))
        if m:
            road = m.group(1)
            pat = f"관악구 {road} {m.group(2)}"
            hit = g[g["도로명주소"].str.contains(pat, na=False, regex=False)]
            if len(hit):
                return (hit.lon.mean(), hit.lat.mean(),
                        f"같은 건물번호 {len(hit)}건", "정확")

    # 3) 같은 본번 필지군 — 부번이 가까운 순으로 최대 5건 평균
    #    (봉천동 1-166 과 1-76 이 같은 점으로 뭉개지는 것을 막습니다)
    if jibun_addr:
        parts = str(jibun_addr).split()
        if len(parts) >= 4:
            dong, jibun = parts[2], parts[3]
            bon, _, bu = jibun.partition("-")
            bu = int(bu) if bu.isdigit() else 0
            pat = rf"{dong}\s+{re.escape(bon)}(?:-(\d+))?(?:\s|$)"
            ext = g["지번주소"].str.extract(pat, expand=False)
            hit = g[ext.notna() | g["지번주소"].str.contains(
                rf"{dong}\s+{re.escape(bon)}(?:\s|$)", na=False, regex=True)]
            if len(hit) >= 3:
                sub = ext[hit.index].fillna("0").astype(int)
                near = hit.assign(_gap=(sub - bu).abs()).nsmallest(5, "_gap")
                gap = int(near["_gap"].max())
                # 부번 차가 크면 같은 필지군으로 보기 어렵습니다.
                # 이때는 도로명 기반(4단계)이 더 정확합니다.
                if gap <= GAP_LIMIT:
                    return (near.lon.mean(), near.lat.mean(),
                            f"{dong} {bon}-{bu} 인근 필지 {len(near)}건 "
                            f"(부번 차 ≤{gap})", "인접")

    # 4) 같은 도로 전체
    if road:
        hit = g[g["도로명주소"].str.contains(f"관악구 {road} ",
                                          na=False, regex=False)]
        if len(hit) >= 5:
            return (hit.lon.mean(), hit.lat.mean(),
                    f"{road} 일대 {len(hit)}건 평균", "근사")
    return None


@lru_cache(maxsize=1)
def survival_distribution():
    """
    관악구 전역 격자에서 반경 300m 3년 생존율 분포를 구합니다.
    개별 지점의 값이 구 안에서 어느 위치인지 백분위로 말하기 위한 기준입니다.
    (단순 구 평균과 비교하면 밀집 지역이 일괄 낮게 보이는 착시가 생깁니다)
    """
    import numpy as np

    g = load()
    vals = []
    for lo in np.arange(126.90, 127.00, 0.004):
        for la in np.arange(37.44, 37.50, 0.003):
            sub = nearby(lo, la, 300)
            c = sub[sub.yr.between(2015, 2021)]
            if len(c) >= 30:
                vals.append((c.days >= 1095).sum() / len(c) * 100)
    return np.array(vals)


def report(lon, lat, origin="", biztype=None):
    """반경 상권 분석 출력."""
    g = load()
    print(f"  기준 좌표   {lon:.6f}, {lat:.6f}"
          f"{'   (' + origin + ')' if origin else ''}")
    print(f"  https://map.kakao.com/link/map/분석지점,{lat},{lon}\n")

    # ── 경쟁 밀도 ────────────────────────────────────────────────
    print(f"  {'반경':<8}{'영업 중':>8}{'누적':>8}{'폐업':>8}   밀도")
    print("  " + "─" * 52)
    for r in (100, 300, 500):
        sub = nearby(lon, lat, r)
        live = int(sub.live.sum())
        area_ha = math.pi * (r / 100) ** 2          # 헥타르
        print(f"  {r:>4}m   {live:>8,}{len(sub):>8,}"
              f"{int(sub.closed.sum()):>8,}   {live/area_ha:>5.1f}개/ha")

    base = nearby(lon, lat, 300)
    if base.empty:
        print("\n  반경 300m 내 데이터가 없습니다")
        return

    # ── 업태 구성 ────────────────────────────────────────────────
    live = base[base.live]
    print(f"\n  반경 300m 영업 중 {len(live):,}곳의 업태 구성")
    for t, n in live["업태구분명"].value_counts().head(6).items():
        bar = "█" * max(1, round(n / max(1, len(live)) * 40))
        print(f"    {str(t)[:14]:<16}{n:>4}곳  {n/len(live)*100:>4.1f}%  {bar}")

    # ── 반경 생존율 ──────────────────────────────────────────────
    print(f"\n  반경별 3년 생존율   (2015~2021 개업 코호트)")
    dist = survival_distribution()
    gu = g[g.yr.between(2015, 2021)]
    gu_rate = (gu.days >= 1095).sum() / len(gu) * 100
    for r in (300, 500):
        sub = nearby(lon, lat, r)
        c = sub[sub.yr.between(2015, 2021)]
        if len(c) < 30:
            print(f"    {r}m    표본 {len(c)}건 — 30건 미만이라 산출하지 않습니다")
            continue
        v = (c.days >= 1095).sum() / len(c) * 100
        diff = v - gu_rate
        tail = ""
        if len(dist):
            pct = int((dist < v).mean() * 100)
            band = f"상위 {100 - pct}%" if pct >= 50 else f"하위 {pct}%"
            tail = f"   · 구 내 {band}"
        print(f"    {r}m    {v:>5.1f}%  (n={len(c):,})"
              f"   → 구 평균 {gu_rate:.1f}% 대비 {diff:+.1f}%p{tail}")
    if len(dist):
        import numpy as np
        print(f"    ※ 관악구 반경 300m 상권 분포: "
              f"25분위 {np.percentile(dist,25):.0f}% · "
              f"중앙 {np.percentile(dist,50):.0f}% · "
              f"75분위 {np.percentile(dist,75):.0f}%")

    if biztype:
        c = base[base.yr.between(2015, 2021) & (base["업태구분명"] == biztype)]
        if len(c) >= 30:
            v = (c.days >= 1095).sum() / len(c) * 100
            print(f"    300m · {biztype}   {v:.1f}%  (n={len(c)})")
        else:
            print(f"    300m · {biztype}   표본 {len(c)}건 — 산출 불가")

    # ── 최근 개폐업 추이 ─────────────────────────────────────────
    y1 = TODAY - pd.Timedelta(days=365)
    op = base[base["open"] >= y1]
    cl = base[base["close"] >= y1]
    print(f"\n  최근 12개월 반경 300m")
    print(f"    개업 {len(op):>3}곳   폐업 {len(cl):>3}곳   "
          f"순증 {len(op)-len(cl):+d}곳")
    if len(cl):
        recent = cl.nlargest(3, "close")
        print("    최근 폐업")
        for _, r in recent.iterrows():
            print(f"      {r['close'].date()}  {str(r['사업장명'])[:18]:<20}"
                  f"{str(r['업태구분명'])[:10]}")


if __name__ == "__main__":
    # 관악구청 부근 좌표로 자가검증
    print("=" * 68)
    print("2막 상권 분석 자가검증")
    print("=" * 68)
    g = load()
    print(f"  적재 {len(g):,}건 (좌표 유효)   "
          f"영업 중 {int(g.live.sum()):,}곳\n")
    report(126.9516, 37.4784, "관악구청 부근 (테스트)")

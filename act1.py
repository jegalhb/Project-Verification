# -*- coding: utf-8 -*-
"""
1막 프로토타입 — 주소 한 줄로 창업 판단 정보를 한 화면에

  사용법
    python act1.py 봉천동 862-1
    python act1.py 신림동 1454 휴게음식점 45

  인자
    1) 법정동   봉천동 / 신림동 / 남현동
    2) 지번     862-1  또는  862
    3) 업종     일반음식점(기본) / 휴게음식점
    4) 영업장면적(㎡)  생략 시 건물 연면적 사용

  구성
    [1] 건물 개요          건축HUB 표제부
    [2] 층별 용도 판정      건축HUB 층별개요 + purpose_map
    [3] 정화조 판정         건축HUB 오수정화시설 + 환경부고시 계수
    [4] 동종업 생존율       관악구 인허가 원장 (로컬 CSV)
    [5] 종합

  검증 근거
    주소→대장 매칭률 98.8% · 좌표변환 오차 100m 이내
    용도코드 커버리지 99.87% · 정화조 용량 확보율 60%
"""
import json
import math
import re
import sys
from urllib.parse import quote

import requests

from purpose_map import restaurant_verdict, septic_coef, to_major
from secret import SERVICE_KEY

BLD = "https://apis.data.go.kr/1613000/BldRgstHubService"
SIGUNGU = "11620"
DONG = {"봉천동": "10100", "신림동": "10200", "남현동": "10300"}
K_SEPTIC = 0.175          # 휴게·일반음식점 공통 (환경부고시 별표)
CSV = "gwanak_restaurants.csv"

BAR = "─" * 68
DBL = "━" * 68


def call(op, bjdong, plat_gb, bun, ji, rows=100):
    params = {"serviceKey": SERVICE_KEY, "sigunguCd": SIGUNGU,
              "bjdongCd": bjdong, "platGbCd": plat_gb, "bun": bun, "ji": ji,
              "numOfRows": str(rows), "pageNo": "1", "_type": "json"}
    res = requests.get(f"{BLD}/{op}", params=params, timeout=25)
    res.raise_for_status()
    body = json.loads(res.text).get("response", {}).get("body", {})
    items = (body.get("items") or {}).get("item") or []
    return [items] if isinstance(items, dict) else items


def fmt_date(raw):
    s = str(raw or "").strip()
    return f"{s[:4]}-{s[4:6]}-{s[6:8]}" if len(s) >= 8 else "-"


# ── [1] 건물 개요 ─────────────────────────────────────────────────
def show_building(key):
    titles = call("getBrTitleInfo", *key, rows=5)
    if not titles:
        print("  ✗ 건축물대장에 해당 지번이 없습니다.")
        print("    (관악구 실측 기준 미매칭률 약 1.2% — 건물 멸실이거나 대장 미등재)")
        return None
    t = titles[0]
    print(f"  건물명   {t.get('bldNm') or '(무명)'}")
    print(f"  도로명   {t.get('newPlatPlc') or '-'}")
    print(f"  주용도   {t.get('mainPurpsCdNm') or '-'}"
          f"   ·   연면적 {float(t.get('totArea') or 0):,.2f}㎡")
    print(f"  규모     지상 {t.get('grndFlrCnt') or '?'}층 / "
          f"지하 {t.get('ugrndFlrCnt') or '?'}층"
          f"   ·   사용승인 {fmt_date(t.get('useAprDay'))}")
    return t


# ── [2] 층별 용도 판정 ────────────────────────────────────────────
MARK = {"현 용도 그대로": "◎", "기재내용 변경": "○",
        "용도변경 신고": "△", "용도변경 허가": "▲", "확인 필요": "?"}
COST = {"현 용도 그대로": 0, "기재내용 변경": 1,
        "용도변경 신고": 2, "용도변경 허가": 3, "확인 필요": 9}


def show_floors(key, target):
    floors = call("getBrFlrOulnInfo", *key)
    if not floors:
        print("  ✗ 층별개요 없음")
        return []
    rows = []
    print(f"  {'층':<11}{'용도':<20}{'면적':>10}   절차")
    print("  " + BAR[:62])
    for f in floors:
        code = str(f.get("mainPurpsCd") or "")
        name = str(f.get("mainPurpsCdNm") or "?")
        area = float(f.get("area") or 0)
        gb = str(f.get("flrGbCdNm") or "")
        floor = f"{gb} {f.get('flrNoNm','')}".strip()
        verdict, _ = restaurant_verdict(code, target)
        print(f"  {floor:<11}{name[:18]:<20}{area:>9.2f}㎡   "
              f"{MARK.get(verdict,'?')} {verdict}")
        rows.append({"floor": floor, "gb": gb, "code": code, "name": name,
                     "area": area, "verdict": verdict})

    print("\n  ◎ 절차 없음   ○ 기재내용 변경   △ 용도변경 신고   ▲ 용도변경 허가")
    print("  ※ 용도변경 절차와 별개로 소방·위생 시설기준은 그대로 적용됩니다.")
    print("    '기재내용 변경'이 곧 '바로 영업 가능'을 뜻하지 않습니다.")

    cand = [r for r in rows if COST[r["verdict"]] <= 2 and r["area"] > 0]
    if not cand:
        print("\n  → 신고 이하로 전환 가능한 층이 없습니다. 허가 절차를 검토하십시오")
        return rows
    cand.sort(key=lambda r: (COST[r["verdict"]], -r["area"]))
    best = cand[0]
    print(f"\n  → 가장 유리한 층: {best['floor']} "
          f"{best['area']:,.2f}㎡ ({best['name']}) · {best['verdict']}")
    if any(r["gb"] == "옥탑" for r in rows):
        print("     ※ 옥탑은 연면적에서 제외될 수 있어 합산 시 주의가 필요합니다")
    return rows


# ── [3] 정화조 판정 ───────────────────────────────────────────────
def show_septic(key, rows, target):
    """
    환경부고시 4-다-(2) : 건물 내 2개 이상 용도는 각각 산정 후 합산.
    따라서 '한 층을 음식점으로 바꿨을 때 건물 전체 재산정값'을 계산합니다.
    """
    wclfs = call("getBrWclfInfo", *key, rows=20)
    cap, mode = 0, ""
    for w in wclfs:
        v = int(float(w.get("capaPsper") or 0))
        if v > cap:
            cap, mode = v, str(w.get("modeCdNm") or "").strip()

    if not rows:
        print("  층별개요가 없어 산정할 수 없습니다")
        return

    # 현재 상태 재산정
    cur, housing = 0.0, 0
    unmapped = {}
    for r in rows:
        coef, conf = septic_coef(r["code"])
        if coef is None:
            housing += 1
            continue
        if conf == "추정":
            unmapped[r["code"]] = r["name"]
        cur += coef * r["area"]

    # 후보 층을 음식점으로 전환했을 때
    cand = [r for r in rows if COST[r["verdict"]] <= 2 and r["area"] > 0]
    cand.sort(key=lambda r: (COST[r["verdict"]], -r["area"]))
    target_floor = cand[0] if cand else None

    print(f"  현재 건물 재산정    약 {math.ceil(cur)}인"
          f"   (층별 용도계수 합산)")
    if target_floor:
        old_coef, _ = septic_coef(target_floor["code"])
        old_coef = old_coef or 0
        after = cur - old_coef * target_floor["area"] \
            + K_SEPTIC * target_floor["area"]
        need = math.ceil(after)
        print(f"  {target_floor['floor']} {target_floor['area']:,.1f}㎡ 를 "
              f"{target}으로 전환 시")
        print(f"  전환 후 필요       {need}인"
              f"   (증가 {need - math.ceil(cur):+d}인)")
    else:
        need = math.ceil(cur)

    if housing:
        print(f"  ⚠ 주택 용도 {housing}개 층은 거실 수 기반 산식이라 제외했습니다")
    if unmapped:
        pairs = ", ".join(f"{n}({c})" for c, n in sorted(unmapped.items()))
        print(f"  ⚠ 계수 미등록 → 0.075 추정: {pairs}")
        print("     purpose_map.SEPTIC_COEF 에 추가하면 정확도가 올라갑니다")

    if not wclfs:
        print("\n  보유 정화조        레코드 없음")
        print("  → 판정 불가. 관할 구청 확인 필요")
        return
    if cap <= 0:
        print(f"\n  보유 정화조        용량 미등재 ({mode or '형식 공란'})")
        print("  → 판정 불가. 1990년 이전 건축물에서 흔한 누락이며,")
        print("     노후 건물일수록 실제 용량이 부족할 수 있어 확인이 필요합니다")
        return

    print(f"\n  보유 정화조        {cap}인용 ({mode or '형식 공란'})")
    if need <= cap:
        print(f"  → ○ 여유   ({cap - need}인 여유)")
    elif need <= cap * 2:
        print(f"  → △ 청소주기 단축 이행각서 검토   (특례 한도 {cap * 2}인 이내)")
    else:
        print(f"  → ✗ 증설 필요   (특례 한도 {cap * 2}인 초과)")
    print("     ※ 옥외영업장을 두면 그 신고면적도 합산됩니다")


# ── [4] 동종업 생존율 ─────────────────────────────────────────────
def show_survival(dong, road):
    try:
        import pandas as pd
    except ImportError:
        print("  (pandas 미설치)")
        return
    try:
        g = pd.read_csv(CSV, dtype=str, encoding="utf-8-sig")
    except FileNotFoundError:
        print(f"  ({CSV} 없음 — 인허가 원장 로컬 적재 필요)")
        return

    def d(s):
        return pd.to_datetime(s, errors="coerce", format="mixed")

    g["open"], g["close"] = d(g["인허가일자"]), d(g["폐업일자"])
    g["end"] = g["close"].fillna(pd.Timestamp.today())
    g["days"] = (g["end"] - g["open"]).dt.days
    g["yr"] = g["open"].dt.year
    g = g[(g.days >= 0) & g.yr.between(2015, 2021)]

    def rate(sub):
        if len(sub) < 30:
            return None, len(sub)
        return (sub.days >= 1095).sum() / len(sub) * 100, len(sub)

    gu_r, gu_n = rate(g)
    dg = g[g["지번주소"].str.contains(dong, na=False)]
    dg_r, dg_n = rate(dg)
    print(f"  관악구 전체     3년 생존율 {gu_r:.1f}%   (n={gu_n:,})")
    if dg_r:
        print(f"  {dong:<10} 3년 생존율 {dg_r:.1f}%   (n={dg_n:,})")

    if not road:
        return

    # 1차: 정확한 도로 / 2차: 도로명 접두어 계열 (청림5길 → 청림*)
    base = re.sub(r"\d+[가-힣]*길$", "", road) or road
    base = re.sub(r"\d+$", "", base) or base

    for label, pattern, note in (
        (road, rf"관악구\s+{re.escape(road)}(?:\s|,|$)", ""),
        (f"{base}* 계열", rf"관악구\s+{re.escape(base)}",
         f"  ({road} 표본 부족 → 인근 {base} 계열 도로 합산)"),
    ):
        rd = g[g["도로명주소"].str.contains(pattern, na=False, regex=True)]
        rd_r, rd_n = rate(rd)
        if rd_r is not None:
            diff = rd_r - (dg_r or gu_r)
            sign = "+" if diff >= 0 else ""
            print(f"  {label:<12} 3년 생존율 {rd_r:.1f}%   (n={rd_n:,})"
                  f"   → 동 평균 대비 {sign}{diff:.1f}%p{note}")
            return
        print(f"  {label:<12} 표본 {rd_n}건 — 30건 미만")
        if base == road:
            break
    print("  → 도로 단위 표본이 부족해 동 평균으로 판단하십시오")
    print("\n  ※ 2015~2021년 개업 코호트 기준. 입지 외 업종·시기 효과가 섞여 있으므로")
    print("     절대값보다 같은 시기 대비 상대값으로 보십시오")


# ── main ──────────────────────────────────────────────────────────
def main():
    if len(sys.argv) < 3:
        print(__doc__)
        return
    dong = sys.argv[1]
    jibun = sys.argv[2]
    target = sys.argv[3] if len(sys.argv) > 3 else "일반음식점"
    override = float(sys.argv[4]) if len(sys.argv) > 4 else None

    if dong not in DONG:
        print(f"지원 법정동: {', '.join(DONG)}")
        return
    m = re.match(r"(산)?\s*(\d+)(?:-(\d+))?$", jibun.strip())
    if not m:
        print("지번 형식 오류. 예) 862-1 또는 862")
        return
    san, bun, ji = m.groups()
    key = (DONG[dong], "1" if san else "0",
           f"{int(bun):04d}", f"{int(ji or 0):04d}")

    print("\n" + DBL)
    print(f" 서울특별시 관악구 {dong} {jibun}{'번지' if not san else ''}"
          f"   ·   {target}")
    print(DBL)

    print("\n[1] 건물 개요")
    t = show_building(key)
    if not t:
        return
    area = override or float(t.get("totArea") or 0)
    road = None
    rm = re.search(r"관악구\s+(\S+?[로길]\d*)", str(t.get("newPlatPlc") or ""))
    if rm:
        road = rm.group(1)

    print(f"\n[2] 층별 용도 판정   ({target} 기준)")
    rows = show_floors(key, target)

    print("\n[3] 정화조 판정   (환경부고시 4-다-(2) 층별 합산)")
    show_septic(key, rows, target)

    print("\n[4] 상권 — 반경 기반")
    try:
        import market
        loc = market.locate(jibun_addr=f"서울특별시 관악구 {dong} {jibun}",
                            road_addr=t.get("newPlatPlc"))
        if loc:
            lon, lat, src, prec = loc
            market.report(lon, lat, f"{src} · 정밀도 {prec}")
            if prec != "정확":
                print(f"\n  ⚠ 대상 지번에 점포 이력이 없어 {prec} 좌표를 썼습니다.")
                print("     반경 분석은 참고용으로만 보십시오")
        else:
            print("  좌표를 찾지 못해 도로 단위로 대체합니다\n")
            show_survival(dong, road)
    except FileNotFoundError:
        print(f"  ({CSV} 없음 — 인허가 원장 로컬 적재 필요)")
    except Exception as exc:                           # noqa: BLE001
        print(f"  ✗ {type(exc).__name__}: {exc}")
        show_survival(dong, road)

    print("\n" + DBL)
    print(" 이 결과는 참고용입니다. 인허가 최종 판단은 관할 구청 소관입니다.")
    print(DBL + "\n")


if __name__ == "__main__":
    main()

# -*- coding: utf-8 -*-
"""
파이프라인 연결부 검증 — 인허가 주소 → 건축물대장 매칭률

이 프로젝트의 마지막 미검증 구간입니다.

  인허가 원장 "서울특별시 관악구 봉천동 729-22 롯데백화점"
        ↓ 파싱 (로컬 검증 완료: 성공률 100%)
  sigunguCd=11620 bjdongCd=10100 bun=0729 ji=0022
        ↓ ???  ← 여기를 잰다
  표제부 → 층별개요 → 오수정화시설

전체 체인의 단계별 통과율을 측정합니다.
매칭률이 낮으면 사용자가 찍은 자리 대부분에서 "정보 없음"이 뜹니다.

실행: 우클릭 > Run 'diag9'   →  diag9_output.txt 생성
"""
import io
import json
import random
import re
import sys
import time
from urllib.parse import quote

import pandas as pd
import requests

from secret import SERVICE_KEY

BLD = "https://apis.data.go.kr/1613000/BldRgstHubService"
SEP = "=" * 74

SIGUNGU = "11620"                                    # 관악구 행정표준코드
DONG = {"봉천동": "10100", "신림동": "10200", "남현동": "10300"}
PAT = re.compile(r"관악구\s+(\S+?동)\s+(산)?\s*(\d+)(?:-(\d+))?")

SAMPLE_OPEN = 50        # 영업 중 표본
SAMPLE_CLOSED = 30      # 폐업 표본
SEED = 42


def parse(addr):
    """지번주소 → (bjdongCd, platGbCd, bun, ji) 또는 None"""
    m = PAT.search(str(addr))
    if not m:
        return None
    dong, is_san, bun, ji = m.groups()
    if dong not in DONG:
        return None
    return (DONG[dong], "1" if is_san else "0",
            f"{int(bun):04d}", f"{int(ji or 0):04d}")


def call(op, bjdong, plat_gb, bun, ji, rows=50):
    params = {"serviceKey": SERVICE_KEY, "sigunguCd": SIGUNGU,
              "bjdongCd": bjdong, "platGbCd": plat_gb, "bun": bun, "ji": ji,
              "numOfRows": str(rows), "pageNo": "1", "_type": "json"}
    res = requests.get(f"{BLD}/{op}", params=params, timeout=25)
    res.raise_for_status()
    body = json.loads(res.text).get("response", {}).get("body", {})
    items = (body.get("items") or {}).get("item") or []
    if isinstance(items, dict):
        items = [items]
    return items


def run(label, rows):
    print("\n" + SEP)
    print(f"{label}  —  표본 {len(rows)}건")
    print(SEP)

    stat = {"parse": 0, "title": 0, "floor": 0, "wclf": 0, "wclf_cap": 0,
            "error": 0}
    misses = []

    for i, r in enumerate(rows, 1):
        key = parse(r["지번주소"])
        if not key:
            continue
        stat["parse"] += 1
        bjdong, plat_gb, bun, ji = key

        try:
            titles = call("getBrTitleInfo", *key, rows=5)
        except Exception:                              # noqa: BLE001
            stat["error"] += 1
            continue

        if not titles:
            misses.append((r["사업장명"], r["지번주소"]))
            time.sleep(0.1)
            continue
        stat["title"] += 1

        try:
            floors = call("getBrFlrOulnInfo", *key)
            if floors:
                stat["floor"] += 1
        except Exception:                              # noqa: BLE001
            pass

        try:
            wclfs = call("getBrWclfInfo", *key, rows=10)
            if wclfs:
                stat["wclf"] += 1
                cap = max((int(float(w.get("capaPsper") or 0)) for w in wclfs),
                          default=0)
                if cap > 0:
                    stat["wclf_cap"] += 1
        except Exception:                              # noqa: BLE001
            pass

        time.sleep(0.12)
        if i % 10 == 0:
            print(f"  ...{i}/{len(rows)} 진행")

    n = stat["parse"]
    print(f"\n  파싱 성공        {stat['parse']:>4}/{len(rows)}")
    if n:
        print(f"  표제부 매칭      {stat['title']:>4}/{n}  ({stat['title']/n*100:>5.1f}%)")
        print(f"  층별개요 확보    {stat['floor']:>4}/{n}  ({stat['floor']/n*100:>5.1f}%)")
        print(f"  정화조 레코드    {stat['wclf']:>4}/{n}  ({stat['wclf']/n*100:>5.1f}%)")
        print(f"  정화조 용량>0    {stat['wclf_cap']:>4}/{n}  ({stat['wclf_cap']/n*100:>5.1f}%)")
        print(f"  조회 오류        {stat['error']:>4}건")

    if misses:
        print(f"\n  ── 표제부 미매칭 사례 ({len(misses)}건 중 8건) ──")
        for name, addr in misses[:8]:
            print(f"    {str(name)[:20]:<22}{str(addr)[:48]}")
    return stat


def main():
    df = pd.read_csv("gwanak_restaurants.csv", dtype=str, encoding="utf-8-sig")
    df = df.dropna(subset=["지번주소"])
    df = df[df["지번주소"].str.contains("관악구", na=False)]
    print(f"관악구 일반음식점 {len(df):,}건 로드")

    random.seed(SEED)
    opened = df[df["영업상태명"] == "영업/정상"]
    closed = df[df["영업상태명"] == "폐업"]
    print(f"  영업 중 {len(opened):,}건 / 폐업 {len(closed):,}건")

    s_open = opened.sample(min(SAMPLE_OPEN, len(opened)), random_state=SEED)
    s_closed = closed.sample(min(SAMPLE_CLOSED, len(closed)), random_state=SEED)

    a = run("[A] 영업 중인 점포 — 실사용에 가까운 조건",
            s_open.to_dict("records"))
    b = run("[B] 폐업한 점포 — 건물 멸실 가능성 포함",
            s_closed.to_dict("records"))

    print("\n" + SEP)
    print("종합 판정")
    print(SEP)
    for label, st in (("영업 중", a), ("폐업", b)):
        n = st["parse"] or 1
        print(f"  {label:<8} 표제부 {st['title']/n*100:>5.1f}%   "
              f"층별 {st['floor']/n*100:>5.1f}%   "
              f"정화조용량 {st['wclf_cap']/n*100:>5.1f}%")
    total_n = (a["parse"] + b["parse"]) or 1
    total_t = a["title"] + b["title"]
    print(f"\n  전체 표제부 매칭률: {total_t/total_n*100:.1f}%")
    print("\n  판정 기준")
    print("    80% 이상 → 서비스 성립. 미매칭은 '정보 없음' 안내로 처리")
    print("    50~80%  → 성립하나 보완 필요 (도로명주소 병행 조회 등)")
    print("    50% 미만 → 연결 전략 재설계 필요")


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
        with open("diag9_output.txt", "w", encoding="utf-8") as fp:
            fp.write(text)
        print("\n[저장] diag9_output.txt 기록 완료 (인증키 자동 마스킹)")

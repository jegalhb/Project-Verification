# -*- coding: utf-8 -*-
"""
1막 데이터 축 실증 검증

  [1] 층별개요    : 층별 용도 + 면적 -> 건축법 시행령 별표1 300㎡ 기준 판정
  [2] 오수정화시설 : capaPsper -> 정화조 3단계 판정
  [3] 좌표 변환    : EPSG:5174 -> WGS84

실행: 이 파일에서 우클릭 > Run 'verify'
"""
import math

from bld_api import ApiError, call

# ── 검증 대상 ────────────────────────────────────────────────────────
# (라벨, 시군구코드, 법정동코드, 본번4자리, 부번4자리)
# 한 곳이 실패해도 나머지가 계속 돌아갑니다.
TARGETS = [
    ("관악구청 (공공청사)", "11620", "10100", "1570", "0001"),
    ("봉천동 862",         "11620", "10100", "0862", "0000"),
    ("신림동 1454",        "11620", "10200", "1454", "0000"),
]

# 환경부고시 「건축물의 용도별 오수발생량 및 정화조 처리대상인원 산정방법」 별표
# 휴게음식점(카페)·일반음식점 공통  N = 0.175 × A
K_FOOD = 0.175

# 건축법 시행령 별표1 : 휴게음식점·제과점은 같은 건축물 해당용도 바닥면적
# 합계 300㎡ 미만이면 제1종, 이상이면 제2종 근린생활시설
AREA_THRESHOLD = 300.0


def _threshold_note(purpose, area):
    """
    300㎡ 기준은 '휴게음식점·제과점 등'에만 적용됩니다.
    일반음식점은 면적과 무관하게 제2종, 그 밖의 용도는 이 기준과 무관합니다.
    (건축법 시행령 별표1 제3호나목 / 제4호아목·자목)
    """
    if "근린생활시설" not in purpose:
        return ""
    if area >= AREA_THRESHOLD:
        return "   ※ 휴게음식점·제과점이라면 300㎡ 이상 → 제2종"
    return "   ※ 휴게음식점·제과점이라면 300㎡ 미만 → 제1종"


def septic_verdict(capacity, need):
    """정화조 3단계 판정."""
    if not capacity:
        return "판정 불가 (정화조 미등재)"
    if need <= capacity:
        return "여유"
    if need <= capacity * 2:
        return "청소주기 단축 이행각서 검토"
    return "증설 필요"


def check(label, sigungu, bjdong, bun, ji):
    print("\n" + "=" * 72)
    print(f"■ {label}   ({sigungu}-{bjdong}  {bun}-{ji})")
    print("=" * 72)

    print("\n[0] 표제부  getBrTitleInfo")
    try:
        titles = call("getBrTitleInfo", sigungu, bjdong, bun, ji)
        if not titles:
            print("  (표제부 데이터 없음 — 지번/법정동코드 재확인 필요)")
        for title in titles:
            print(f"  건물명={title.get('bldNm', '-') or '-'}   "
                  f"주용도={title.get('mainPurpsCdNm', '-') or '-'}   "
                  f"연면적={title.get('totArea', '-') or '-'}㎡")
    except ApiError as exc:
        print(f"  ✗ {exc}")

    # ── [1] 층별개요 ────────────────────────────────────────────────
    # 층별개요가 실패해도 정화조는 독립적으로 조회해야 하므로 return 하지 않습니다.
    print("\n[1] 층별개요  getBrFlrOulnInfo")
    floors = []
    try:
        floors = call("getBrFlrOulnInfo", sigungu, bjdong, bun, ji)
    except ApiError as exc:
        print(f"  ✗ {exc}")

    if not floors:
        print("  (데이터 없음 — 해당 지번에 건축물대장이 없을 수 있습니다)")

    totals = {}
    for flr in floors:
        purpose = flr.get("mainPurpsCdNm") or "?"
        area = float(flr.get("area") or 0)
        totals[purpose] = totals.get(purpose, 0.0) + area
        print(f"  {flr.get('flrGbCdNm', ''):<4}{flr.get('flrNoNm', ''):<7}"
              f"{purpose:<22}{area:>9.2f}㎡   {flr.get('etcPurps', '')}")

    if totals:
        print("\n  ── 용도별 바닥면적 합계 ──")
        for purpose, area in sorted(totals.items(), key=lambda kv: -kv[1]):
            print(f"  {purpose:<22}{area:>9.2f}㎡{_threshold_note(purpose, area)}")

    # ── [2] 오수정화시설 ────────────────────────────────────────────
    print("\n[2] 오수정화시설  getBrWclfInfo")
    capacity = None
    try:
        wclfs = call("getBrWclfInfo", sigungu, bjdong, bun, ji)
        if not wclfs:
            print("  (데이터 없음)")
        for wclf in wclfs:
            value = int(float(wclf.get("capaPsper") or 0))
            capacity = value or capacity
            print(f"  형식={wclf.get('modeCdNm', '?'):<16}"
                  f"용량(인용)={wclf.get('capaPsper', '-')}인   "
                  f"용량(루베)={wclf.get('capaLube', '-')}㎥")
    except ApiError as exc:
        print(f"  ✗ {exc}")

    if not capacity:
        print("  ⚠ capaPsper 없음/0 — 정화조 미설치이거나 대장 미등재")

    # ── [3] 정화조 판정 ─────────────────────────────────────────────
    print(f"\n[3] 정화조 판정   N = ceil({K_FOOD} × A)")
    for area in (50, 100, 150, 200):
        need = math.ceil(K_FOOD * area)
        print(f"  영업장 {area:>3}㎡ → 필요 {need:>3}인 / "
              f"보유 {capacity if capacity else '?'}인"
              f"   → {septic_verdict(capacity, need)}")


def coord_check():
    """EPSG:5174 (보정계수 안 들어간 Bessel 중부원점TM) → WGS84"""
    from pyproj import CRS, Transformer

    proj5174 = (
        "+proj=tmerc +lat_0=38 +lon_0=127.0028902777778 +k=1 "
        "+x_0=200000 +y_0=500000 +ellps=bessel +units=m +no_defs "
        "+towgs84=-115.80,474.99,674.11,1.16,-2.31,-1.63,6.43"
    )
    to_wgs = Transformer.from_crs(
        CRS.from_proj4(proj5174), CRS.from_epsg(4326), always_xy=True)

    # ↓ 행안부 인허가 데이터의 X, Y 를 여기에 넣고 카카오맵 링크로 대조하세요.
    samples = [
        (195645.71, 441803.40),   # 관악구청 부근 (참조값)
    ]

    print("\n" + "=" * 72)
    print("■ 좌표 변환  EPSG:5174 → WGS84")
    print("=" * 72)
    for x, y in samples:
        lon, lat = to_wgs.transform(x, y)
        inside = 126.76 <= lon <= 127.19 and 37.42 <= lat <= 37.70
        print(f"\n  X={x:.2f}   Y={y:.2f}")
        print(f"  → 경도 {lon:.6f}   위도 {lat:.6f}   "
              f"{'서울 범위 OK' if inside else '⚠ 서울 범위 밖 — 좌표계 재확인'}")
        print(f"  https://map.kakao.com/link/map/확인지점,{lat},{lon}")


class _Tee:
    """콘솔과 파일에 동시 출력 (검증 결과를 output.txt 로 남기기 위함)."""

    def __init__(self, *streams):
        self.streams = streams

    def write(self, data):
        for stream in self.streams:
            stream.write(data)

    def flush(self):
        for stream in self.streams:
            stream.flush()


if __name__ == "__main__":
    import io
    import sys

    buffer = io.StringIO()
    original = sys.stdout
    sys.stdout = _Tee(original, buffer)

    try:
        for target in TARGETS:
            try:
                check(*target)
            except Exception as exc:                  # noqa: BLE001
                print(f"  ✗ 예외 {type(exc).__name__}: {exc}")
        coord_check()
    finally:
        sys.stdout = original
        text = buffer.getvalue()
        # 혹시 모를 키 노출 방지 — 출력에 섞인 serviceKey 값을 가립니다.
        try:
            from secret import SERVICE_KEY
            from urllib.parse import quote

            for token in {SERVICE_KEY, quote(SERVICE_KEY, safe="")}:
                if token:
                    text = text.replace(token, "<SERVICE_KEY_REDACTED>")
        except Exception:                             # noqa: BLE001
            pass

        with open("output.txt", "w", encoding="utf-8") as fp:
            fp.write(text)
        print("\n[저장] output.txt 에 결과를 기록했습니다. (인증키는 자동 마스킹)")

# -*- coding: utf-8 -*-
"""
건축HUB 건축물대장정보 서비스 호출 공통 모듈

  Base URL : https://apis.data.go.kr/1613000/BldRgstHubService
  트래픽    : 개발계정 10,000건/일
  응답      : _type=json 을 주지만 무시하고 XML 로 오는 경우가 있어 둘 다 처리
"""
import json
import xml.etree.ElementTree as ET

import requests

from secret import SERVICE_KEY

BASE = "https://apis.data.go.kr/1613000/BldRgstHubService"

# 정상으로 취급할 결과코드 (기관마다 표기가 조금씩 다름)
_OK_CODES = {"00", "0", "000", None, ""}


class ApiError(Exception):
    pass


def _parse(text):
    """JSON 우선, 실패하면 XML 로 파싱. (items, resultCode, resultMsg) 반환."""
    # 1) JSON
    try:
        resp = json.loads(text)["response"]
        head = resp.get("header", {}) or {}
        items = ((resp.get("body") or {}).get("items") or {})
        items = items.get("item") if isinstance(items, dict) else items
        items = items or []
        if isinstance(items, dict):
            items = [items]
        return items, head.get("resultCode"), head.get("resultMsg")
    except Exception:
        pass

    # 2) XML
    try:
        root = ET.fromstring(text)
        code = (root.findtext(".//resultCode")
                or root.findtext(".//returnReasonCode"))
        msg = (root.findtext(".//resultMsg")
               or root.findtext(".//returnAuthMsg")
               or root.findtext(".//errMsg"))
        items = [{c.tag: (c.text or "") for c in it}
                 for it in root.findall(".//items/item")]
        return items, code, msg
    except Exception as exc:
        raise ApiError(f"응답 파싱 실패: {exc}\n원문 앞부분:\n{text[:400]}")


def call(operation, sigungu, bjdong, bun, ji, plat_gb="0", rows=100):
    """
    operation : getBrFlrOulnInfo / getBrWclfInfo / getBrTitleInfo / getBrJijiguInfo ...
    sigungu   : 시군구코드 5자리   (관악구 = 11620)
    bjdong    : 법정동코드 5자리   (봉천동 = 10100)
    bun / ji  : 본번 / 부번 4자리 (예: 1570-1 -> "1570", "0001")
    plat_gb   : 0 대지 / 1 산 / 2 블록
    """
    if not SERVICE_KEY or SERVICE_KEY.startswith("여기에"):
        raise ApiError("secret.py 의 SERVICE_KEY 를 아직 넣지 않았습니다.")

    params = {
        "serviceKey": SERVICE_KEY,
        "sigunguCd": sigungu,
        "bjdongCd": bjdong,
        "platGbCd": plat_gb,
        "bun": bun,
        "ji": ji,
        "numOfRows": str(rows),
        "pageNo": "1",
        "_type": "json",
    }

    try:
        res = requests.get(f"{BASE}/{operation}", params=params, timeout=20)
    except requests.RequestException as exc:
        raise ApiError(f"네트워크 오류: {exc}")

    if res.status_code != 200:
        raise ApiError(f"HTTP {res.status_code}\n{res.text[:300]}")

    items, code, msg = _parse(res.text)

    if code not in _OK_CODES:
        hint = ""
        upper = f"{code} {msg}".upper()
        if "SERVICE_KEY" in upper or str(code) in ("30", "20"):
            hint = ("\n  → Decoding 키가 맞는지 확인하세요. "
                    "발급 직후라면 10~30분 뒤 재시도.")
        elif "LIMITED" in upper or str(code) == "22":
            hint = "\n  → 일일 호출 한도(10,000건) 초과."
        raise ApiError(f"API 오류 [{code}] {msg}{hint}")

    return items

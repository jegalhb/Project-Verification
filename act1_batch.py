# -*- coding: utf-8 -*-
"""
1막 프로토타입 배치 실행 — 층별 판정 화면이 실제 건물에서 어떻게 읽히는지 확인

앞선 검증에서 정화조 용량과 규모가 확인된 건물들을 섞어 돌립니다.
소형 · 대형 · 복합용도 · 미매칭까지 포함해 화면이 어떤 모습이 되는지 봅니다.

실행: 우클릭 > Run 'act1_batch'   →  act1_batch_output.txt 생성
"""
import io
import sys
from urllib.parse import quote

from secret import SERVICE_KEY

import act1

# (법정동, 지번, 설명)
CASES = [
    ("봉천동", "7-51",   "초소형 42㎡ · 정화조 20인 — 여유 사례"),
    ("봉천동", "1-166",  "소규모 근생 189㎡ · 정화조 30인 — 이행각서 구간"),
    ("봉천동", "7-77",   "대형 1,141㎡ · 정화조 120인"),
    ("봉천동", "7-93",   "최대 1,884㎡ · 정화조 550인 — 여유"),
    ("봉천동", "1-76",   "교회 복합용도 1,180㎡ — 용도명 세분류 확인"),
    ("신림동", "1454",   "신림동 표본"),
    ("봉천동", "1570-1", "관악구청 부지 — 미매칭 예상 사례"),
]


def main():
    for i, (dong, jibun, note) in enumerate(CASES, 1):
        print("\n" + "█" * 68)
        print(f" CASE {i}/{len(CASES)}   {dong} {jibun}")
        print(f" {note}")
        print("█" * 68)
        sys.argv = ["act1.py", dong, jibun]
        try:
            act1.main()
        except Exception as exc:                       # noqa: BLE001
            print(f"  ✗ 예외 {type(exc).__name__}: {exc}")


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
    finally:
        sys.stdout = original
        text = buffer.getvalue()
        for token in {SERVICE_KEY, quote(SERVICE_KEY, safe="")}:
            if token:
                text = text.replace(token, "<SERVICE_KEY_REDACTED>")
        with open("act1_batch_output.txt", "w", encoding="utf-8") as fp:
            fp.write(text)
        print("\n[저장] act1_batch_output.txt 기록 완료")

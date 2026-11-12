"""검색 API 응답 시간 측정. v1(인덱스 없음)과 v2(인덱스·캐시) 비교용.

실행: python -m scripts.measure_search
실제 DB(DATABASE_URL)를 쓴다. 네트워크를 빼고 앱 안에서 바로 호출(TestClient)해서
'앱 + DB' 시간만 잰다. 경우마다 1번 미리 실행한 뒤 20번 재서 중앙값과 최댓값을 낸다.
"""

import statistics
import sys
import time

from fastapi.testclient import TestClient

from app.main import app

RUNS = 20

CASES = [
    ("이름 검색 (결과 많음)", {"q": "간장"}),
    ("이름 검색 (결과 적음)", {"q": "라코니코"}),
    ("이름 + 대표식품명", {"q": "고추장", "category": "고추장"}),
    ("대표식품명만 (큰 종류)", {"category": "기타 빵"}),
    ("이름 검색 50쪽", {"q": "간장", "page": 50}),
]


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")  # Windows 콘솔에서 한글이 깨지지 않게
    client = TestClient(app)
    print("| 경우 | 조건 | 결과 수 | 중앙값(ms) | 최댓값(ms) |")
    print("|---|---|---|---|---|")
    for label, params in CASES:
        total = client.get("/api/products", params=params).json()["total"]  # 미리 실행

        times = []
        for _ in range(RUNS):
            start = time.perf_counter()
            response = client.get("/api/products", params=params)
            times.append((time.perf_counter() - start) * 1000)
            assert response.status_code == 200

        print(f"| {label} | `{params}` | {total:,} | {statistics.median(times):.1f} | {max(times):.1f} |")


if __name__ == "__main__":
    main()

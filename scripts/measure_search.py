"""검색·상세·비교·추천 API 응답 시간 측정. v1(인덱스 없음)과 v2(인덱스·캐시) 비교용.

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

SEARCH = "/api/products"
CASES = [
    ("이름 검색 (결과 많음)", SEARCH, {"q": "간장"}),
    ("이름 검색 (결과 적음)", SEARCH, {"q": "라코니코"}),
    ("이름 + 대표식품명", SEARCH, {"q": "고추장", "category": "고추장"}),
    ("대표식품명만 (큰 종류)", SEARCH, {"category": "기타 빵"}),
    ("이름 검색 50쪽", SEARCH, {"q": "간장", "page": 50}),
    ("제품 상세 (식품코드)", "/api/products/P107-113011300-0051", {}),
    ("같은 종류 비교 (간장)", "/api/compare", {"category": "간장", "basis": "100ml", "sort": "sodium"}),
    ("같은 종류 비교 (큰 종류)", "/api/compare", {"category": "기타 빵", "basis": "100g", "sort": "sugar"}),
    ("대체 제품 추천 (간장, 나트륨)", "/api/products/P112-004000400-0098/alternatives", {"by": "sodium"}),
    ("대체 제품 추천 (기타 빵, 당류)", "/api/products/P101-405000400-4596/alternatives", {"by": "sugar"}),
]


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")  # Windows 콘솔에서 한글이 깨지지 않게
    client = TestClient(app)
    print("| 경우 | 조건 | 결과 수 | 중앙값(ms) | 최댓값(ms) |")
    print("|---|---|---|---|---|")
    for label, path, params in CASES:
        body = client.get(path, params=params).json()  # 미리 실행
        total = body.get("total", 1)  # 상세는 1건

        times = []
        for _ in range(RUNS):
            start = time.perf_counter()
            response = client.get(path, params=params)
            times.append((time.perf_counter() - start) * 1000)
            assert response.status_code == 200

        print(f"| {label} | `{path} {params}` | {total:,} | {statistics.median(times):.1f} | {max(times):.1f} |")


if __name__ == "__main__":
    main()

"""검색·상세·비교·추천 API와 화면의 응답 시간 측정. v1(인덱스 없음)과 v2(인덱스·캐시) 비교용.

실행: python -m scripts.measure_search             # 캐시 켬: 미리 실행한 1번이 캐시에 저장되므로 20번은 캐시에서 꺼낸 시간
      python -m scripts.measure_search --no-cache  # 캐시 끔: 20번 모두 DB를 읽은 시간
실제 DB(DATABASE_URL)를 쓴다. 네트워크를 빼고 앱 안에서 바로 호출(TestClient)해서
'앱 + DB' 시간만 잰다. 경우마다 1번 미리 실행한 뒤 20번 재서 중앙값과 최댓값을 낸다.
"""

import statistics
import sys
import time

from fastapi.testclient import TestClient

from app import cache
from app.main import app

RUNS = 20

SEARCH = "/api/products"
CASES = [
    ("이름 검색 (결과 많음)", SEARCH, {"q": "간장"}),
    ("이름 검색 (결과 적음)", SEARCH, {"q": "라코니코"}),
    ("이름 + 대표식품명", SEARCH, {"q": "고추장", "category": "고추장"}),
    ("대표식품명만 (큰 종류)", SEARCH, {"category": "기타 빵"}),
    ("이름 검색 50쪽", SEARCH, {"q": "간장", "page": 50}),
    ("회사 이름 검색", SEARCH, {"q": "샘표", "target": "maker"}),
    ("한 글자 검색 (FULLTEXT 못 씀 → LIKE)", SEARCH, {"q": "김"}),
    ("대표식품명 + 상세 조건", SEARCH, {"category": "간장", "basis": "100ml", "max_sodium": 5000, "max_sugar": 2}),
    ("제품 상세 (식품코드)", "/api/products/P107-113011300-0051", {}),
    ("같은 종류 비교 (간장)", "/api/compare", {"category": "간장", "basis": "100ml", "sort": "sodium"}),
    ("같은 종류 비교 (큰 종류)", "/api/compare", {"category": "기타 빵", "basis": "100g", "sort": "sugar"}),
    ("대체 제품 추천 (간장, 나트륨)", "/api/products/P112-004000400-0098/alternatives", {"by": "sodium"}),
    ("대체 제품 추천 (기타 빵, 당류)", "/api/products/P101-405000400-4596/alternatives", {"by": "sugar"}),
    # 화면(HTML). 상세 화면은 상세 + 나트륨 추천 + 당류 추천을 한 번에 불러온다
    ("화면: 검색", "/", {"q": "간장"}),
    ("화면: 상세 (추천 2개 포함)", "/products/P112-004000400-0098", {}),
    ("화면: 같은 종류 비교", "/compare", {"category": "간장", "basis": "100ml"}),
]


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")  # Windows 콘솔에서 한글이 깨지지 않게
    if "--no-cache" in sys.argv:
        cache.client = None
    else:
        cache.clear()  # 지난 측정의 캐시를 지우고 시작한다
    client = TestClient(app)
    print("| 경우 | 조건 | 결과 수 | 중앙값(ms) | 최댓값(ms) |")
    print("|---|---|---|---|---|")
    for label, path, params in CASES:
        response = client.get(path, params=params)  # 미리 실행
        # API는 JSON의 total(상세는 1건), 화면(HTML)은 결과 수를 '-'로 적는다
        total = f'{response.json().get("total", 1):,}' if path.startswith("/api") else "-"

        times = []
        for _ in range(RUNS):
            start = time.perf_counter()
            response = client.get(path, params=params)
            times.append((time.perf_counter() - start) * 1000)
            assert response.status_code == 200

        print(f"| {label} | `{path} {params}` | {total} | {statistics.median(times):.1f} | {max(times):.1f} |")


if __name__ == "__main__":
    main()

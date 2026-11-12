"""화면(HTML) 테스트: 검색, 상세, 비교. 화면에 꼭 보여야 하는 글자가 있는지 확인한다."""

import pytest

from app.loader import save
from app.main import format_nutrient


def product(code, name, category="간장", basis="100ml", sodium=6000, sugar=1, maker="테스트식품"):
    return {"food_code": code, "name": name, "maker": maker, "category": category,
            "basis": basis, "energy_kcal": 60, "sodium_mg": sodium, "sugar_g": sugar, "sat_fat_g": 0}


@pytest.fixture
def client(engine, api):
    save(engine, [
        product("P1", "양조간장", sodium=6454, sugar=0.4),
        product("P2", "저염간장", sodium=3000, sugar=0),
        product("P3", "정보없는간장", sodium=None, sugar=None, maker=None),
        product("P4", "국간장", basis="100g", sodium=7000),
        product("P5", "<script>alert(1)</script>간장"),
    ])
    return api


# --- 표시 형식 ---

def test_format_nutrient():
    assert format_nutrient(None, "mg") == '<span class="na">정보 없음</span>'  # 흐린 색으로 표시
    assert format_nutrient(6454.0, "mg") == "6,454 mg"
    assert format_nutrient(0.4, "g") == "0.4 g"
    assert format_nutrient(0.0, "g") == "0 g"  # 실제 0은 0으로


# --- 검색 화면 ---

def test_home_shows_search_form_and_source(client):
    html = client.get("/").text

    assert 'action="/" method="get"' in html
    assert "출처: 공공데이터포털" in html


def test_search_page_lists_products_with_links(client):
    html = client.get("/", params={"q": "간장", "target": "category"}).text

    assert "5건 중 1쪽" in html
    assert '<a href="/products/P1">양조간장</a>' in html
    assert "6,454 mg" in html


def test_one_search_box_finds_by_name_or_category(engine, client):
    save(engine, [product("G1", "양념 간장게장", category="게장")])

    by_name = client.get("/", params={"q": "간장", "target": "name"}).text
    by_category = client.get("/", params={"q": "간장", "target": "category"}).text

    assert "양념 간장게장" in by_name        # 이름에 '간장'이 들어가서 나옴
    assert "양념 간장게장" not in by_category  # 대표식품명이 '게장'이라 안 나옴
    assert '<option value="category" selected>대표식품명</option>' in by_category


def test_search_page_shows_no_result_message(client):
    assert "검색 결과가 없어요." in client.get("/", params={"q": "없는제품"}).text


def test_product_name_is_escaped(client):
    # 제품 이름이 HTML로 실행되지 않고 글자로 보여야 한다
    html = client.get("/", params={"q": "script"}).text

    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_search_page_by_maker_and_filters(engine, client):
    save(engine, [product("M1", "다른이름", maker="샘표식품", sodium=500)])

    html = client.get("/", params={"q": "샘표", "target": "maker"}).text
    assert '<a href="/products/M1">다른이름</a>' in html

    # 나트륨 1000 이하 + 100ml: 다른이름(500)만 남는다 (P2 저염간장은 3000)
    html = client.get("/", params={"q": "간장", "target": "category", "basis": "100ml", "max_sodium": "1000"}).text
    assert "1건 중 1쪽" in html
    assert "<details class=\"filters\" open>" in html  # 조건을 넣었으면 펼쳐서 보여준다


def test_search_page_ignores_empty_filter_fields(client):
    # 폼을 그대로 보내면 빈 칸이 'max_kcal='처럼 온다. 오류가 아니라 '조건 없음'이어야 한다
    params = {"q": "간장", "target": "name", "basis": "", "max_kcal": "", "max_sodium": "", "max_sugar": "", "max_sat_fat": ""}
    response = client.get("/", params=params)

    assert response.status_code == 200
    assert "5건 중 1쪽" in response.text


def test_filters_are_sliders_showing_current_value(client):
    html = client.get("/", params={"q": "간장", "target": "category", "max_sodium": "5000"}).text

    assert 'type="range" name="max_sodium" min="0" max="8000" step="100"' in html
    assert 'value="5000"' in html          # 고른 위치에 손잡이가 있다
    assert "5,000 mg 이하" in html          # 지금 값
    assert 'value="900"' in html           # 안 고른 칼로리는 맨 오른쪽
    assert "제한 없음" in html


def test_slider_at_far_right_means_no_limit(client):
    # 드래그바를 맨 오른쪽까지 두면 폼이 그 값을 보내도 조건이 아니다
    params = {"q": "간장", "target": "category", "max_kcal": "900", "max_sodium": "8000", "max_sugar": "100", "max_sat_fat": "50"}
    html = client.get("/", params=params).text

    assert "5건 중 1쪽" in html                     # 정보 없는 P3도 빠지지 않는다
    assert "<details class=\"filters\" open>" not in html  # 조건이 없으니 접힌 채로
    assert "max_sodium=" not in html                # 쪽·개수 링크 주소에 안 붙는다


def test_pager_keeps_filters(engine, client):
    save(engine, [product(f"X{i:02}", f"필터간장{i:02}", sodium=100) for i in range(25)])

    html = client.get("/", params={"q": "필터간장", "max_sodium": "200"}).text

    assert "/?q=%ED%95%84%ED%84%B0%EA%B0%84%EC%9E%A5&amp;target=name&amp;max_sodium=200&amp;page=2" in html


def test_labels_use_calorie(client):
    assert "칼로리" in client.get("/products/P1").text
    assert "에너지" not in client.get("/products/P1").text


# --- 상세 화면 ---

def test_detail_page_shows_basis_and_alternatives(client):
    html = client.get("/products/P1").text

    assert "영양성분 (100ml당)" in html
    assert "6,454 mg" in html
    assert "나트륨이 더 낮은 간장 (100ml)" in html
    assert "당류가 더 낮은 간장 (100ml)" in html
    assert '<a href="/products/P2">저염간장</a>' in html  # 나트륨·당류 둘 다 더 낮음
    assert "국간장" not in html  # 100g이라 대체 후보 아님
    assert "/compare?category=%EA%B0%84%EC%9E%A5&basis=100ml" in html  # 같은 종류 비교 링크


def test_detail_page_shows_unknown_values(client):
    html = client.get("/products/P3").text

    assert "정보 없음" in html
    assert "회사 정보 없음" in html
    assert "이 제품은 나트륨 정보가 없어서 더 낮은 제품을 찾을 수 없어요." in html


def test_unknown_product_page_is_404(client):
    response = client.get("/products/NO-SUCH-CODE")

    assert response.status_code == 404
    assert "해당 제품이 없어요." in response.text


# --- 비교 화면 ---

def test_compare_page_sorts_low_first_and_null_last(client):
    html = client.get("/compare", params={"category": "간장", "basis": "100ml", "sort": "sodium"}).text

    assert "간장 (100ml당) 비교" in html
    assert "4건 중 1쪽" in html  # 100g 국간장은 빠짐
    # 낮은 순: 저염(3000) → 기본값(6000)인 script 간장 → 양조(6454) → 정보 없음은 맨 뒤
    assert html.index("저염간장") < html.index("&lt;script&gt;") < html.index("양조간장") < html.index("정보없는간장")


# --- 한 쪽 개수 (5·10·20·30) ---

def rows(html):
    return html.count('<a href="/products/')


def test_page_size_can_be_chosen(engine, client):
    save(engine, [product(f"K{i:02}", f"쪽크기간장{i:02}") for i in range(12)])

    html = client.get("/", params={"q": "쪽크기간장", "size": 5}).text

    assert rows(html) == 5
    assert '<span class="pill on">5개</span>' in html
    # 다른 크기를 고르면 1쪽부터, 다음 쪽으로 가도 고른 크기를 유지
    assert "q=%EC%AA%BD%ED%81%AC%EA%B8%B0%EA%B0%84%EC%9E%A5&amp;target=name&amp;page=1&amp;size=10" in html
    assert "page=2&amp;size=5" in html


def test_unknown_page_size_falls_back_to_20(engine, client):
    save(engine, [product(f"K{i:02}", f"쪽크기간장{i:02}") for i in range(25)])

    html = client.get("/", params={"q": "쪽크기간장", "size": 7}).text

    assert rows(html) == 20
    assert '<span class="pill on">20개</span>' in html


def test_compare_page_size_and_sort_links_keep_size(client):
    html = client.get("/compare", params={"category": "간장", "basis": "100ml", "size": 10}).text

    assert '<span class="pill on">10개</span>' in html
    assert "&sort=sugar&size=10" in html

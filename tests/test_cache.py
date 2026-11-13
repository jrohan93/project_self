"""Redis 캐시 테스트 (v2 3단계). 테스트 전용 Redis DB(TEST_REDIS_URL)를 쓴다."""

from sqlalchemy import text

from app import cache
from app.loader import save


def product(code, name, sodium):
    return {"food_code": code, "name": name, "maker": "테스트식품", "category": "간장", "basis": "100ml",
            "energy_kcal": 60, "sodium_mg": sodium, "sugar_g": 1, "sat_fat_g": 0}


COMPARE = {"category": "간장", "basis": "100ml", "sort": "sodium"}


def sodium_list(response):
    return [item["sodium_mg"] for item in response.json()["items"]]


def test_same_conditions_make_same_key():
    # 넘긴 순서가 달라도 조건이 같으면 같은 키
    assert cache.make_key("compare", category="간장", basis="100ml") == cache.make_key("compare", basis="100ml", category="간장")
    assert cache.make_key("compare", category="간장", basis="100ml").startswith("nutri:compare:")


def test_second_request_comes_from_cache_until_cleared(engine, api, redis_cache):
    save(engine, [product("P1", "양조간장", 6000), product("P2", "저염간장", 3000)])
    assert sodium_list(api.get("/api/compare", params=COMPARE)) == [3000, 6000]

    # DB 값을 직접 바꿔도, 캐시에 저장된 결과가 그대로 나온다 (= DB를 다시 읽지 않았다)
    with engine.begin() as conn:
        conn.execute(text("UPDATE products SET sodium_mg = 1000 WHERE food_code = 'P1'"))
    assert sodium_list(api.get("/api/compare", params=COMPARE)) == [3000, 6000]

    # 적재 후처럼 캐시를 비우면 새 값이 보인다
    assert cache.clear() == 1
    assert sodium_list(api.get("/api/compare", params=COMPARE)) == [1000, 3000]


def test_cached_value_has_one_hour_ttl(engine, api, redis_cache):
    save(engine, [product("P1", "양조간장", 6000)])
    api.get("/api/compare", params=COMPARE)

    [key] = list(redis_cache.scan_iter(match="nutri:*"))
    assert 0 < redis_cache.ttl(key) <= cache.TTL_SECONDS  # 비우는 걸 잊어도 1시간 안에 사라진다


def test_null_stays_null_through_cache(engine, api, redis_cache):
    # 캐시를 거쳐도 정보 없음(null)이 0으로 바뀌지 않는다
    save(engine, [product("P1", "정보없는간장", None)])
    first = api.get("/api/products", params={"category": "간장"}).json()
    second = api.get("/api/products", params={"category": "간장"}).json()

    assert first == second
    assert second["items"][0]["sodium_mg"] is None


def test_search_and_detail_screen_use_cache(engine, api, redis_cache):
    save(engine, [product("P1", "양조간장", 6000), product("P2", "저염간장", 3000)])
    api.get("/api/products", params={"q": "간장"})
    api.get("/products/P1")  # 상세 화면: 추천 나트륨·당류 2개

    kinds = sorted(key.decode().split(":")[1] for key in redis_cache.scan_iter(match="nutri:*"))
    assert kinds == ["alternatives", "alternatives", "search"]


def test_clear_removes_only_this_apps_keys(redis_cache):
    redis_cache.set("nutri:compare:x", "1")
    redis_cache.set("other-app:key", "1")

    assert cache.clear() == 1
    assert redis_cache.get("other-app:key") == b"1"


def test_works_without_redis(engine, api, monkeypatch):
    # Redis가 꺼져 있어도(아무도 듣지 않는 포트) 캐시 없이 DB에서 결과를 준다
    monkeypatch.setattr(cache, "client", cache.connect("redis://127.0.0.1:1/0"))
    save(engine, [product("P1", "양조간장", 6000)])

    response = api.get("/api/compare", params=COMPARE)

    assert response.status_code == 200
    assert sodium_list(response) == [6000]

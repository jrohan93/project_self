"""Redis 캐시 (v2 3단계): 검색·비교·추천 결과를 JSON으로 잠깐 저장해서, 같은 요청은 DB를 다시 읽지 않는다.

옛날 결과를 지우는 방법 두 가지를 같이 쓴다.
- 적재가 끝나면 clear()로 바로 비운다: 데이터는 적재 스크립트로만 바뀌므로 이게 주된 방법.
- 저장할 때 1시간 만료(TTL)를 붙인다: 비우는 걸 잊어도 길어야 1시간 뒤에는 새 결과가 나오는 안전장치.

Redis가 꺼져 있거나 REDIS_URL이 없으면 캐시 없이 DB만 쓴다 (캐시 때문에 서비스가 멈추지 않게).
"""

import json
import os
from collections.abc import Callable
from typing import TypeVar

import redis
from dotenv import load_dotenv
from pydantic import BaseModel

load_dotenv()

TTL_SECONDS = 60 * 60  # 1시간
PREFIX = "nutri:"  # 이 앱이 만든 키만 골라 지울 수 있게 붙이는 머리말

M = TypeVar("M", bound=BaseModel)


def connect(url: str | None) -> redis.Redis | None:
    if not url:
        return None
    # socket_timeout: Redis가 응답하지 않을 때 오래 기다리지 않고 DB로 넘어가게
    return redis.Redis.from_url(url, socket_connect_timeout=0.5, socket_timeout=0.5)


# 앱 전체에서 하나만 쓴다. 테스트에서는 None(캐시 끔)이나 테스트용 Redis로 바꿔 끼운다
client = connect(os.getenv("REDIS_URL"))


def make_key(kind: str, **params) -> str:
    """요청 조건으로 키를 만든다. 예: nutri:compare:{"basis": "100ml", "category": "간장", ...}

    sort_keys=True: 같은 조건이면 넘긴 순서가 달라도 같은 키가 되게.
    """
    return PREFIX + kind + ":" + json.dumps(params, sort_keys=True, ensure_ascii=False)


def get_or_set(key: str, model: type[M], compute: Callable[[], M]) -> M:
    """캐시에 있으면 그 결과를, 없으면 compute()로 DB에서 만들어 저장한 뒤 돌려준다."""
    if client is None:
        return compute()

    try:
        saved = client.get(key)
    except redis.RedisError:  # Redis가 꺼져 있음 등 → 캐시 없이
        return compute()
    if saved is not None:
        return model.model_validate_json(saved)

    result = compute()
    try:
        client.set(key, result.model_dump_json(), ex=TTL_SECONDS)
    except redis.RedisError:
        pass  # 저장을 못 해도 결과는 그대로 돌려준다
    return result


def clear() -> int:
    """이 앱의 캐시(nutri:로 시작하는 키)를 모두 지우고 지운 개수를 돌려준다. 적재가 끝난 뒤 부른다."""
    if client is None:
        return 0
    # scan_iter: 키를 조금씩 나눠 찾는다 (KEYS *는 키가 많으면 Redis를 잠깐 멈추게 함)
    keys = list(client.scan_iter(match=PREFIX + "*"))
    return client.delete(*keys) if keys else 0

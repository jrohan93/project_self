"""로그인 실패 제한 (v3 3단계): 같은 이메일로 5번 틀리면 15분 동안 로그인을 막는다.

- 비밀번호를 하나씩 넣어 보는 공격(무차별 대입)을 막는다. 5번이면 사람이 오타를 내기에는 충분하다.
- 실패 횟수는 Redis에 이메일별로 센다. 키에 15분 만료를 붙여서, 마지막 실패 뒤 15분이 지나면 저절로 풀린다.
- 가입하지 않은 이메일도 똑같이 세고 똑같이 막는다: 막히는지 아닌지로 가입 여부를 알 수 없게.
- Redis가 꺼져 있으면 횟수를 확인·기록할 수 없으므로 로그인을 받지 않는다 (사용자 결정: 보안 우선).
  확인·기록에서 난 redis.RedisError를 그대로 올리고, main.py의 로그인이 503으로 바꾼다.
- 서킷 브레이커: Redis 오류가 한 번 나면 30초 동안은 Redis를 부르지 않고 바로 오류로 본다.
  꺼진 Redis는 연결을 기다리느라 요청마다 약 1초가 걸리므로, 고장 난 동안 요청이 쌓이지 않게.
  30초가 지나면 다음 요청이 다시 Redis를 불러 본다 (살아났으면 그때부터 정상).
- client가 None(REDIS_URL 없음)이면 제한을 끈다: 테스트와 Redis 없이 돌려 보는 개발용.
"""

import os
import time

import redis
from dotenv import load_dotenv

from app.cache import connect

load_dotenv()

MAX_FAILURES = 5
LOCK_SECONDS = 15 * 60
# 캐시(nutri:)와 다른 머리말: 데이터 적재 후 캐시를 비울 때 실패 횟수까지 지워지지 않게
PREFIX = "auth:login_fail:"
DOWN_SECONDS = 30  # Redis 오류 뒤 이 시간 동안은 Redis를 부르지 않는다

# 캐시와 같은 Redis를 쓰지만 따로 둔다. 테스트에서는 None(제한 끔)이나 테스트용 Redis로 바꿔 끼운다
client = connect(os.getenv("REDIS_URL"))
# 이 시각(time.monotonic 기준)까지는 Redis가 꺼져 있다고 본다. 0이면 정상
down_until = 0.0


def key(email: str) -> str:
    return PREFIX + email


def skip_if_down() -> None:
    """최근에 Redis 오류가 났으면 기다리지 않고 바로 오류를 낸다."""
    if time.monotonic() < down_until:
        raise redis.ConnectionError("최근 Redis 오류: 잠시 Redis를 부르지 않음")


def mark_down() -> None:
    """Redis 오류가 났다: 지금부터 30초 동안은 Redis를 부르지 않는다."""
    global down_until
    down_until = time.monotonic() + DOWN_SECONDS


def locked_seconds(email: str) -> int:
    """막혀 있으면 남은 초, 아니면 0. Redis가 꺼져 있으면 redis.RedisError."""
    if client is None:
        return 0
    skip_if_down()
    try:
        failures = client.get(key(email))
        if failures is None or int(failures) < MAX_FAILURES:
            return 0
        return max(client.ttl(key(email)), 1)
    except redis.RedisError:
        mark_down()
        raise  # 오류는 그대로 올린다 (로그인이 503으로 바꿈)


def record_failure(email: str) -> None:
    """실패 1회를 더하고, 만료를 다시 15분으로 둔다 (마지막 실패부터 15분)."""
    if client is None:
        return
    skip_if_down()
    try:
        # 두 명령을 한 번에(MULTI/EXEC) 보낸다: 중간에 끊겨서 만료 없는 키가 남아 영원히 막히는 일이 없게
        with client.pipeline(transaction=True) as pipe:
            pipe.incr(key(email))
            pipe.expire(key(email), LOCK_SECONDS)
            pipe.execute()
    except redis.RedisError:
        mark_down()
        raise


def reset(email: str) -> None:
    """로그인에 성공하면 실패 횟수를 지운다.
    지우지 못해도 로그인은 그대로 둔다: 남은 횟수는 5번 미만이고 15분 뒤 저절로 사라진다."""
    if client is None:
        return
    try:
        skip_if_down()
        client.delete(key(email))
    except redis.RedisError:
        pass  # 여기서는 mark_down 하지 않는다: 로그인은 이미 성공했고, 다음 확인에서 다시 알게 됨

"""회원 인증 (v3 1단계): 비밀번호 해시(bcrypt)와 액세스 토큰(JWT).

- 비밀번호는 원문을 저장하지 않고 bcrypt 해시만 저장한다. bcrypt는 일부러 느리게(약 0.3초) 만들어져서,
  DB가 유출돼도 비밀번호를 하나씩 맞혀 보는 데 시간이 오래 걸린다. 같은 비밀번호도 매번 다른 해시가 나온다(salt).
- 로그인에 성공하면 JWT 액세스 토큰을 준다. 서버는 토큰을 저장하지 않고, 서명(JWT_SECRET)과 만료 시각만 확인한다.
  그래서 짧게(15분) 둔다. 오래 쓰는 리프레시 토큰은 2단계에서 만든다.
"""

import os
import string
from datetime import UTC, datetime, timedelta

import bcrypt
import jwt
from dotenv import load_dotenv

load_dotenv()

BCRYPT_ROUNDS = 12  # 2^12번 반복. 한 번 확인에 약 0.3초 (테스트에서는 4로 낮춰 빠르게)
PASSWORD_MAX_BYTES = 72  # bcrypt는 72바이트까지만 쓴다 (한글은 한 글자 3바이트)
ACCESS_TOKEN_MINUTES = 15
ALGORITHM = "HS256"

# 가입하지 않은 이메일로 로그인할 때도 비밀번호 확인을 한 번 해서, 응답 시간으로
# 가입 여부를 알아내지 못하게 한다. 아무 비밀번호와도 맞지 않는 가짜 해시 (임의 글자로 만듦)
DUMMY_HASH = "$2b$12$CSaesLQyqhoS0jOYmMgmuuTmnBkGZY.19RH3gTG/HmHNaH.mtyuAm"


def normalize_email(email: str) -> str:
    return email.strip().lower()


# 비밀번호 조합 규칙 (국내 기준: 개인정보 안전성 확보조치 기준 해설서·KISA 안내서의 예시)
# 영문 대문자·영문 소문자·숫자·특수문자 중 2종류 이상이면 10자 이상, 3종류 이상이면 8자 이상
PASSWORD_RULE = "비밀번호는 영문 대문자·소문자·숫자·특수문자 중 2종류 이상이면 10자 이상, 3종류 이상이면 8자 이상으로 해 주세요."


def password_kinds(password: str) -> int:
    """비밀번호에 들어 있는 글자 종류 수 (0~4). 한글 등 다른 글자는 쓸 수 있지만 종류로 세지 않는다."""
    groups = [string.ascii_uppercase, string.ascii_lowercase, string.digits, string.punctuation]
    return sum(any(char in group for char in password) for group in groups)


def follows_password_rule(password: str) -> bool:
    kinds = password_kinds(password)
    return (kinds >= 3 and len(password) >= 8) or (kinds >= 2 and len(password) >= 10)


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt(BCRYPT_ROUNDS)).decode()


def verify_password(password: str, password_hash: str) -> bool:
    # 저장된 해시 안에 salt와 반복 횟수가 들어 있어서, 같은 방법으로 다시 해시해 비교한다
    return bcrypt.checkpw(password.encode(), password_hash.encode())


def get_secret() -> str:
    secret = os.getenv("JWT_SECRET")
    if not secret:
        raise RuntimeError(".env에 JWT_SECRET이 없어요. .env.example을 참고하세요.")
    return secret


def create_access_token(user_id: int) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),  # 누구의 토큰인지 (JWT 규칙상 글자로)
        "iat": now,  # 만든 시각
        "exp": now + timedelta(minutes=ACCESS_TOKEN_MINUTES),  # 만료 시각
    }
    return jwt.encode(payload, get_secret(), algorithm=ALGORITHM)


def read_access_token(token: str) -> int | None:
    """토큰이 맞으면 사용자 id, 서명이 틀리거나 만료됐거나 모양이 이상하면 None."""
    try:
        # algorithms를 정해 둬야 'alg: none' 같은 서명 없는 토큰을 받지 않는다
        payload = jwt.decode(token, get_secret(), algorithms=[ALGORITHM], options={"require": ["sub", "exp"]})
        return int(payload["sub"])
    except (jwt.InvalidTokenError, ValueError):
        return None

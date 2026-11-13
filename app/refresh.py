"""리프레시 토큰 (v3 2단계): 발급, 순환, 재사용 감지, 로그아웃.

- 리프레시 토큰은 JWT가 아니라 임의의 긴 글자(secrets)다. 서버가 DB에 기록해 두므로 언제든 끊을 수 있다.
- DB에는 sha256 해시만 저장한다. 토큰은 사람이 정한 비밀번호와 달리 충분히 무작위라서
  bcrypt처럼 느린 해시가 필요 없다 (맞혀 볼 수 있는 경우의 수가 너무 많음).
- 순환: 한 번 쓰면 '썼음'으로 표시하고 새 토큰을 준다. 훔친 토큰은 한 번밖에 못 쓴다.
- 재사용 감지: 이미 쓴 토큰이 다시 오면 진짜 주인과 도둑 중 누가 먼저 썼는지 알 수 없으므로,
  그 회원의 토큰을 모두 끊고 다시 로그인하게 한다.
"""

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models import RefreshToken

REFRESH_TOKEN_DAYS = 14  # 순환할 때마다 새 토큰이 다시 14일 (14일 동안 안 쓰면 다시 로그인)


def utcnow() -> datetime:
    # DB의 DATETIME에는 시간대가 없어서, UTC 시각을 시간대 표시 없이 저장·비교한다
    return datetime.now(UTC).replace(tzinfo=None)


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def find(session: Session, raw: str) -> RefreshToken | None:
    return session.scalars(select(RefreshToken).where(RefreshToken.token_hash == hash_token(raw))).one_or_none()


def issue(session: Session, user_id: int, family_id: str | None = None) -> str:
    """새 리프레시 토큰을 만들어 해시만 저장하고, 원문은 한 번만 돌려준다.
    family_id가 없으면(로그인) 새 묶음, 있으면(순환) 같은 묶음."""
    raw = secrets.token_urlsafe(32)  # 32바이트 무작위 → 43글자
    session.add(RefreshToken(
        user_id=user_id,
        token_hash=hash_token(raw),
        family_id=family_id or str(uuid.uuid4()),
        expires_at=utcnow() + timedelta(days=REFRESH_TOKEN_DAYS),
    ))
    session.commit()
    return raw


def rotate(session: Session, raw: str) -> tuple[int, str] | None:
    """쓸 수 있는 토큰이면 (회원 id, 새 리프레시 토큰). 없거나 끊겼거나 만료됐거나 재사용이면 None."""
    token = find(session, raw)
    if token is None or token.revoked_at is not None or token.expires_at <= utcnow():
        return None

    # 아직 안 쓴 토큰일 때만 '썼음'으로 바꾼다. 조건을 UPDATE 안에 넣어서,
    # 같은 토큰으로 두 요청이 동시에 와도 DB가 한 번만 바꿔 준다 (나머지 하나는 재사용으로 처리)
    marked = session.execute(
        update(RefreshToken)
        .where(RefreshToken.id == token.id, RefreshToken.used_at.is_(None))
        .values(used_at=utcnow())
    ).rowcount
    if marked == 0:
        revoke_user(session, token.user_id)  # 이미 쓴 토큰이 다시 옴 → 도난으로 보고 전부 끊기
        return None

    return token.user_id, issue(session, token.user_id, token.family_id)


def revoke_user(session: Session, user_id: int) -> None:
    """그 회원의 모든 기기에서 로그아웃 (재사용 감지 때)."""
    session.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=utcnow())
    )
    session.commit()


def logout(session: Session, raw: str) -> None:
    """이 토큰이 속한 묶음(이 기기의 로그인)만 끊는다. 모르는 토큰이면 아무것도 하지 않는다."""
    token = find(session, raw)
    if token is None:
        return
    session.execute(
        update(RefreshToken)
        .where(RefreshToken.family_id == token.family_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=utcnow())
    )
    session.commit()

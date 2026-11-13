"""관심 제품 (v3 4단계): 회원이 고른 제품을 저장하고, 목록을 보고, 지운다.

- 모든 조회·삭제에 user_id 조건을 건다. 그래서 남의 관심 제품은 '없는 것'과 똑같이 보인다(404).
  "남의 것이라 안 됨(403)"이라고 답하면 그 데이터가 있다는 사실을 알려 주게 된다.
- 같은 제품을 두 번 저장해도 한 번만 저장된다 (DB unique + 이미 있으면 그대로).
"""

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Favorite, Product


def list_products(session: Session, user_id: int) -> list[Product]:
    """그 회원의 관심 제품. 최근에 저장한 것 먼저."""
    return list(session.scalars(
        select(Product)
        .join(Favorite, Favorite.food_code == Product.food_code)
        .where(Favorite.user_id == user_id)
        .order_by(Favorite.id.desc())
    ))


def is_saved(session: Session, user_id: int, food_code: str) -> bool:
    found = session.scalars(
        select(Favorite.id).where(Favorite.user_id == user_id, Favorite.food_code == food_code)
    ).first()
    return found is not None


def add(session: Session, user_id: int, food_code: str) -> bool:
    """저장한다. 없는 제품이면 False. 이미 저장한 제품이면 그대로 True (몇 번 해도 결과가 같다)."""
    if session.get(Product, food_code) is None:
        return False
    if is_saved(session, user_id, food_code):
        return True
    session.add(Favorite(user_id=user_id, food_code=food_code))
    try:
        session.commit()
    except IntegrityError:
        # 같은 제품을 동시에 두 번 저장한 경우: 먼저 들어간 하나만 남고(unique), 이 요청도 성공으로 본다
        session.rollback()
    return True


def remove(session: Session, user_id: int, food_code: str) -> bool:
    """내 관심 제품에서 지운다. 내 목록에 없으면(남의 것이어도) False."""
    deleted = session.execute(
        delete(Favorite).where(Favorite.user_id == user_id, Favorite.food_code == food_code)
    ).rowcount
    session.commit()
    return deleted == 1

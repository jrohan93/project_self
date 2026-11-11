"""DB 테이블 정의."""

from decimal import Decimal

from sqlalchemy import Numeric, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Product(Base):
    """가공식품 한 개. 영양값은 모두 기준량(basis) 당 값이다."""

    __tablename__ = "products"

    # 공공데이터의 식품코드 (예: P101-103000100-6015). 다시 적재할 때 이 값으로 같은 제품을 찾는다.
    food_code: Mapped[str] = mapped_column(String(30), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    # 제조사, 제조사가 '해당없음'이면 수입사. 둘 다 없으면 NULL
    maker: Mapped[str | None] = mapped_column(String(255))
    # 대표식품명 (간장, 고추장 등). 같은 종류 비교의 묶음 기준
    category: Mapped[str] = mapped_column(String(50))
    # '100g' 또는 '100ml'. 기준량이 다르면 영양값을 비교하지 않는다
    basis: Mapped[str] = mapped_column(String(10))

    # 영양값: 빈칸은 0이 아니라 NULL(정보 없음)
    energy_kcal: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    sodium_mg: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    sugar_g: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    sat_fat_g: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))

    # 검색용 인덱스는 일부러 아직 만들지 않는다.
    # v1에서 인덱스 없이 검색 속도를 재고, v2에서 인덱스를 추가한 뒤 비교하기 위해서다.

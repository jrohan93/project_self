"""DB 테이블 정의."""

from decimal import Decimal

from sqlalchemy import Index, Numeric, String
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

    # v2 인덱스 (alembic 0002). 비교·추천·대표식품명 검색은 모두
    # '대표식품명 = ? AND 기준량 = ?'으로 한 묶음만 보므로 이 둘을 앞에 두고,
    # 그 묶음 안에서 낮은 순으로 찾는 영양값을 세 번째에 둔다.
    # 대표식품명만으로 찾을 때도 앞쪽(category)만 써서 이 인덱스를 탄다.
    __table_args__ = (
        Index("ix_products_category_basis_sodium", "category", "basis", "sodium_mg"),
        Index("ix_products_category_basis_sugar", "category", "basis", "sugar_g"),
        Index("ix_products_category_basis_sat_fat", "category", "basis", "sat_fat_g"),
        # v2 2단계 (alembic 0003): 이름·회사 이름 중간에 든 검색어를 찾는 FULLTEXT 인덱스.
        # ngram 파서는 글자를 2글자씩 잘라 색인한다 (양조간장 → 양조, 조간, 간장)
        Index("ft_products_name", "name", mysql_prefix="FULLTEXT", mysql_with_parser="ngram"),
        Index("ft_products_maker", "maker", mysql_prefix="FULLTEXT", mysql_with_parser="ngram"),
    )

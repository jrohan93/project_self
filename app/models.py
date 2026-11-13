"""DB 테이블 정의."""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Index, Numeric, String, func
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


class User(Base):
    """회원 (v3). 가입할 때는 이메일·비밀번호만 받는다 (개인정보는 쓸 곳이 생길 때 받는다)."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    # 소문자로 바꿔 저장한다 (A@x.com과 a@x.com은 같은 사람). 같은 이메일로 두 번 가입하지 못하게 unique
    email: Mapped[str] = mapped_column(String(255), unique=True)
    # 비밀번호 원문은 저장하지 않고 bcrypt 해시만 저장한다 ($2b$12$... 60글자)
    password_hash: Mapped[str] = mapped_column(String(60))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class RefreshToken(Base):
    """리프레시 토큰 (v3 2단계). 액세스 토큰(15분)이 만료되면 이걸로 새로 받는다.

    토큰 원문은 저장하지 않고 sha256 해시만 저장한다 (DB가 유출돼도 토큰으로 쓸 수 없게).
    한 번 쓰면 used_at을 채우고 새 토큰을 준다(순환). 이미 쓴 토큰이 다시 오면 도난으로 보고 그 회원 토큰을 모두 끊는다.
    """

    __tablename__ = "refresh_tokens"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    # 회원이 지워지면 그 회원의 토큰도 같이 지워진다
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)  # sha256 16진수 64글자
    # 같은 로그인에서 순환으로 이어진 토큰 묶음. 로그아웃은 이 묶음(그 기기)만 끊는다
    family_id: Mapped[str] = mapped_column(String(36), index=True)  # ix_refresh_tokens_family_id (alembic 0005)
    expires_at: Mapped[datetime] = mapped_column(DateTime)  # UTC
    used_at: Mapped[datetime | None] = mapped_column(DateTime)  # 순환에 쓴 시각. 쓰기 전엔 NULL
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime)  # 로그아웃·재사용 감지로 끊은 시각
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

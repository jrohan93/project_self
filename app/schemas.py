"""API 응답 모양."""

from pydantic import BaseModel, ConfigDict


class ProductItem(BaseModel):
    # from_attributes: SQLAlchemy Product 객체에서 같은 이름의 값을 읽어 온다
    model_config = ConfigDict(from_attributes=True)

    food_code: str
    name: str
    maker: str | None
    category: str
    basis: str
    # 영양값은 기준량(basis) 당 값. 정보가 없으면 null (0이 아님)
    energy_kcal: float | None
    sodium_mg: float | None
    sugar_g: float | None
    sat_fat_g: float | None


class SearchResult(BaseModel):
    total: int  # 조건에 맞는 전체 건수
    page: int
    size: int
    items: list[ProductItem]


class CompareResult(SearchResult):
    # 어떤 묶음을 무엇으로 정렬했는지 함께 돌려준다
    category: str
    basis: str
    sort: str

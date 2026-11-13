"""API 요청·응답 모양."""

import re
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.auth import PASSWORD_MAX_BYTES, PASSWORD_RULE, follows_password_rule, normalize_email

# 골뱅이 앞뒤에 글자가 있고 뒤쪽에 점이 있으면 이메일로 본다 (정확한 확인은 2단계 인증의 이메일 인증번호로)
EMAIL_PATTERN = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")


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


class AlternativesResult(BaseModel):
    product: ProductItem  # 기준 제품
    by: str  # 무엇이 더 낮은 제품을 찾았는지 (sodium / sugar)
    total: int  # 기준 제품보다 낮은 제품 전체 수
    items: list[ProductItem]  # 낮은 순으로 limit개


class CompareResult(SearchResult):
    # 어떤 묶음을 무엇으로 정렬했는지 함께 돌려준다
    category: str
    basis: str
    sort: str


# ---------------- 회원 (v3) ----------------

class SignupRequest(BaseModel):
    email: str = Field(max_length=255)
    # 길이·조합은 아래 check_password에서 한 번에 본다 (짧을 때도 같은 안내 문구가 나오게)
    password: str = Field(max_length=200)

    @field_validator("email")
    @classmethod
    def check_email(cls, value: str) -> str:
        value = normalize_email(value)
        if not EMAIL_PATTERN.fullmatch(value):
            raise ValueError("이메일 형식이 아니에요.")
        return value

    @field_validator("password")
    @classmethod
    def check_password(cls, value: str) -> str:
        if not follows_password_rule(value):
            raise ValueError(PASSWORD_RULE)
        # bcrypt는 72바이트 뒤를 쓰지 못한다. 몰래 자르지 않고 가입 때 알려 준다
        if len(value.encode()) > PASSWORD_MAX_BYTES:
            raise ValueError(f"비밀번호는 {PASSWORD_MAX_BYTES}바이트 이하로 해 주세요 (한글은 한 글자 3바이트).")
        return value


class LoginRequest(BaseModel):
    # 로그인은 형식 검사를 하지 않는다: 틀리면 그냥 '맞지 않아요'로 같은 응답
    email: str = Field(max_length=255)
    password: str = Field(max_length=200)


class UserItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    created_at: datetime  # 비밀번호 해시는 응답에 넣지 않는다


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int  # 몇 초 뒤 만료되는지

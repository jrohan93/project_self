"""제품 이름·회사 이름 FULLTEXT ngram 인덱스 추가 (v2 성능 2단계)

LIKE '%간장%'은 앞이 %라 일반 인덱스를 못 써서 32만 행을 다 읽는다.
ngram은 글자를 2글자씩 잘라(양조간장 → 양조, 조간, 간장) 색인해서
이름 중간에 들어간 검색어도 인덱스로 찾을 수 있다.

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-13
"""

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

# (인덱스 이름, 칼럼)
INDEXES = [
    ("ft_products_name", "name"),
    ("ft_products_maker", "maker"),
]


def upgrade() -> None:
    # 불용어(stopword) 끄기: 기본 목록에 a, i, in 같은 영어 단어가 있는데,
    # ngram은 불용어가 들어간 토큰을 통째로 빼서 'ca', 'ki' 같은 2글자가 색인에서 빠진다.
    # (ICHIBIKI 같은 영어 이름을 못 찾게 됨). 이 설정은 인덱스를 만드는 순간에 적용된다.
    op.execute("SET SESSION innodb_ft_enable_stopword = OFF")
    for name, column in INDEXES:
        op.execute(f"CREATE FULLTEXT INDEX {name} ON products ({column}) WITH PARSER ngram")


def downgrade() -> None:
    for name, _ in INDEXES:
        op.drop_index(name, table_name="products")

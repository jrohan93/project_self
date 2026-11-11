"""processed_all.csv를 MySQL products 테이블에 적재한다.

실행: python -m app.loader            (기본: processed_all.csv)
      python -m app.loader 다른.csv

순서: CSV 읽기 → corrections.csv 보정 → 필요한 칼럼만 정리 → 값까지 같은 중복 합치기 → 저장
다시 실행해도 식품코드 기준으로 덮어쓰므로 중복이 생기지 않는다.
"""

import sys
import time

import pandas as pd
from sqlalchemy import Engine
from sqlalchemy.dialects.mysql import insert

from app.db import make_engine
from app.models import Product

CORRECTIONS_PATH = "corrections.csv"
NOT_APPLICABLE = "해당없음"  # 공공데이터에서 '값 없음'을 뜻하는 글자
BATCH_SIZE = 5000  # 한 번에 보내는 행 수

# CSV 칼럼 → products 칼럼 (v1은 이 4개 영양값만 사용)
NUTRIENT_COLUMNS = {
    "에너지(kcal)": "energy_kcal",
    "나트륨(mg)": "sodium_mg",
    "당류(g)": "sugar_g",
    "포화지방산(g)": "sat_fat_g",
}
# 이 값들이 모두 같으면 같은 제품으로 보고 하나만 남긴다
DUPLICATE_KEY = ["name", "maker", "basis", *NUTRIENT_COLUMNS.values()]
# 다시 적재할 때 덮어쓸 칼럼 (food_code 제외 전부)
UPDATE_COLUMNS = ["name", "maker", "category", "basis", *NUTRIENT_COLUMNS.values()]


def read_csv(path: str) -> pd.DataFrame:
    # dtype=str: 식품코드 같은 값이 숫자로 바뀌지 않게 전부 글자로 읽는다.
    # 빈칸은 NaN(값 없음)으로 읽힌다. 0이 아니다.
    return pd.read_csv(path, dtype=str, encoding="utf-8-sig")


def apply_corrections(raw: pd.DataFrame, corrections: pd.DataFrame) -> pd.DataFrame:
    """corrections.csv의 수정값을 덮어쓴다.

    원래값이 지금 데이터와 다르면(데이터를 새로 받아서 바뀐 경우) 잘못 덮어쓰지 않게 멈춘다.
    """
    df = raw.set_index("식품코드")  # 새 DataFrame이 만들어지므로 원본은 바뀌지 않는다
    for row in corrections.itertuples(index=False):
        current = df.at[row.식품코드, row.칼럼]
        if pd.isna(current) or float(current) != float(row.원래값):
            raise ValueError(
                f"{row.식품코드} {row.칼럼}: 원래값이 {row.원래값}이어야 하는데 {current}예요. "
                "데이터가 바뀌었는지 확인하고 corrections.csv를 고쳐 주세요."
            )
        df.at[row.식품코드, row.칼럼] = row.수정값
    return df.reset_index()


def to_products(raw: pd.DataFrame) -> pd.DataFrame:
    """CSV 칼럼을 products 테이블 칼럼으로 바꾼다."""
    # 업체: 제조사가 '해당없음'이면 수입사, 둘 다 '해당없음'이면 NaN(정보 없음)
    maker = raw["mfrNm"].where(raw["mfrNm"] != NOT_APPLICABLE, raw["imptNm"])
    maker = maker.where(maker != NOT_APPLICABLE)

    products = pd.DataFrame({
        "food_code": raw["식품코드"],
        "name": raw["식품명"],
        "maker": maker,
        "category": raw["대표식품명"],
        "basis": raw["기준량"],
    })
    for csv_column, column in NUTRIENT_COLUMNS.items():
        # 숫자가 아닌 글자가 있으면 에러로 멈춘다. 빈칸(NaN)은 그대로 둔다.
        products[column] = pd.to_numeric(raw[csv_column])
    return products


def drop_duplicates(products: pd.DataFrame) -> pd.DataFrame:
    """이름·업체·기준량·영양값 4개가 모두 같은 행은 하나만 남긴다.

    식품코드 순으로 정렬해 가장 작은 코드를 남기므로, 몇 번을 실행해도 같은 행이 남는다.
    """
    return products.sort_values("food_code").drop_duplicates(subset=DUPLICATE_KEY, keep="first")


def to_records(products: pd.DataFrame) -> list[dict]:
    """DB에 넣을 dict 목록. NaN은 None으로 바꿔야 DB에 NULL로 들어간다."""
    return products.astype(object).where(products.notna(), None).to_dict("records")


def save(engine: Engine, records: list[dict]) -> None:
    """INSERT ... ON DUPLICATE KEY UPDATE: 같은 식품코드가 있으면 새 값으로 덮어쓴다."""
    stmt = insert(Product)
    stmt = stmt.on_duplicate_key_update({column: stmt.inserted[column] for column in UPDATE_COLUMNS})
    # 하나의 트랜잭션: 중간에 실패하면 전부 되돌려서 반쯤 들어간 상태가 남지 않게 한다
    with engine.begin() as conn:
        for start in range(0, len(records), BATCH_SIZE):
            conn.execute(stmt, records[start:start + BATCH_SIZE])


def main() -> None:
    csv_path = sys.argv[1] if len(sys.argv) > 1 else "processed_all.csv"
    started = time.perf_counter()

    raw = read_csv(csv_path)
    corrections = read_csv(CORRECTIONS_PATH)
    products = drop_duplicates(to_products(apply_corrections(raw, corrections)))
    print(f"원본 {len(raw)}건, 보정 {len(corrections)}개 값, 중복 합친 뒤 {len(products)}건")

    save(make_engine(), to_records(products))
    print(f"적재 완료: {len(products)}건, {time.perf_counter() - started:.1f}초")


if __name__ == "__main__":
    main()

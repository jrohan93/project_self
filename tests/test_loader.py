"""적재 전 데이터 정리 규칙 테스트 (DB 없이 실행됨)."""

import pandas as pd
import pytest

from app.loader import apply_corrections, drop_duplicates, read_csv, to_products, to_records


def raw_row(code, *, name="양조간장", mfr="샘표", impt="해당없음", basis="100ml",
            energy="60", sodium="6000", sugar="1", sat_fat="0"):
    """CSV 한 줄. 빈칸은 None으로 넘긴다 (read_csv가 빈칸을 NaN으로 읽는 것과 같음)."""
    return {
        "식품코드": code, "식품명": name, "mfrNm": mfr, "imptNm": impt,
        "대표식품명": "간장", "기준량": basis,
        "에너지(kcal)": energy, "나트륨(mg)": sodium, "당류(g)": sugar, "포화지방산(g)": sat_fat,
    }


def raw_df(*rows):
    return pd.DataFrame(list(rows))


# --- 빈칸 ---

def test_blank_nutrient_is_saved_as_null_not_zero():
    records = to_records(to_products(raw_df(raw_row("A", sodium=None))))
    assert records[0]["sodium_mg"] is None
    assert records[0]["energy_kcal"] == 60


# --- 업체명 ---

def test_maker_uses_importer_when_manufacturer_missing():
    products = to_products(raw_df(raw_row("A", mfr="해당없음", impt="수입사(주)")))
    assert products.loc[0, "maker"] == "수입사(주)"


def test_maker_is_null_when_manufacturer_and_importer_missing():
    records = to_records(to_products(raw_df(raw_row("A", mfr="해당없음", impt="해당없음"))))
    assert records[0]["maker"] is None


# --- 보정 ---

def corrections_df(code, column, before, after):
    return pd.DataFrame([{"식품코드": code, "식품명": "", "칼럼": column,
                          "원래값": before, "수정값": after, "근거": ""}])


def test_correction_overwrites_value():
    raw = raw_df(raw_row("A", sodium="383000"))
    fixed = apply_corrections(raw, corrections_df("A", "나트륨(mg)", "383000", "383"))
    assert to_products(fixed).loc[0, "sodium_mg"] == 383
    assert raw.loc[0, "나트륨(mg)"] == "383000"  # 원본은 그대로


def test_blank_correction_makes_value_null(tmp_path):
    # corrections.csv에서 수정값 칸을 비우면 '정보 없음'(NULL)으로 바뀐다
    path = tmp_path / "corrections.csv"
    path.write_text("식품코드,식품명,칼럼,원래값,수정값,근거\nA,간장,나트륨(mg),2,,근거 없음\n", encoding="utf-8")
    raw = raw_df(raw_row("A", sodium="2"))

    fixed = apply_corrections(raw, read_csv(str(path)))

    assert to_records(to_products(fixed))[0]["sodium_mg"] is None


def test_correction_stops_when_original_value_changed():
    raw = raw_df(raw_row("A", sodium="500"))
    with pytest.raises(ValueError):
        apply_corrections(raw, corrections_df("A", "나트륨(mg)", "383000", "383"))


# --- 중복 ---

def test_identical_products_are_merged_keeping_smallest_code():
    products = to_products(raw_df(raw_row("B"), raw_row("A")))
    result = drop_duplicates(products)
    assert list(result["food_code"]) == ["A"]


def test_same_name_with_different_nutrition_is_kept():
    products = to_products(raw_df(raw_row("A", sodium="6000"), raw_row("B", sodium="5000")))
    assert len(drop_duplicates(products)) == 2


def test_same_name_with_different_basis_is_kept():
    products = to_products(raw_df(raw_row("A", basis="100ml"), raw_row("B", basis="100g")))
    assert len(drop_duplicates(products)) == 2


def test_blank_values_count_as_same_when_merging():
    products = to_products(raw_df(raw_row("A", sodium=None), raw_row("B", sodium=None)))
    assert len(drop_duplicates(products)) == 1

"""공공데이터포털 식품영양성분 표준데이터 API를 전부 받아 CSV/엑셀로 저장.

사용법
1. 같은 폴더에 .env 파일을 만들고 한 줄 입력:  DATA_GO_KR_KEY=일반인증키
   (공공데이터포털 인증키는 계정당 하나라 원재료성·가공식품 모두 같은 키를 씀)
2. pip install requests pandas openpyxl python-dotenv
3. 실행
   python download_nutrition.py material   # 원재료성식품 (기본값)
   python download_nutrition.py process    # 가공식품

결과 (원재료성식품)
- nutrition_all.csv / .xlsx        : 전체
- nutrition_raw_only.csv           : 조리상태가 '생것'인 줄만
결과 (가공식품)
- processed_all.csv                : 전체 (양이 많아 엑셀은 만들지 않음)
- processed_seasonings.csv         : 레시피에 자주 쓰는 양념·가공 재료만
"""

import os
import sys
import time

import pandas as pd
import requests
from dotenv import load_dotenv

DATASETS = {
    "material": {
        "endpoint": "https://api.data.go.kr/openapi/tn_pubr_public_nutri_material_info_api",
        "prefix": "nutrition",
    },
    "process": {
        "endpoint": "https://api.data.go.kr/openapi/tn_pubr_public_nutri_process_info_api",
        "prefix": "processed",
    },
}
ROWS_PER_PAGE = 1000  # 한 번에 받을 개수 (너무 크면 서버가 거절할 수 있어 1000으로)

# 가공식품에서 골라낼 레시피용 재료 (식품명에 이 단어가 들어간 줄)
SEASONING_KEYWORDS = [
    "간장", "된장", "고추장", "쌈장", "김치", "어묵", "참치", "부침가루",
    "떡볶이떡", "가래떡", "식용유", "참기름", "들기름", "고춧가루", "멸치액젓",
]


def fetch_page(endpoint: str, key: str, page: int) -> tuple[list[dict], int]:
    """한 페이지를 받아 (행 목록, 전체 건수)를 돌려준다."""
    params = {"serviceKey": key, "pageNo": page, "numOfRows": ROWS_PER_PAGE, "type": "json"}
    res = requests.get(endpoint, params=params, timeout=60)
    res.raise_for_status()

    try:
        data = res.json()
    except ValueError:
        # 인증키 오류 등은 JSON이 아니라 XML 에러로 오는 경우가 많다
        sys.exit(f"JSON이 아닌 응답이 왔어요. 인증키를 확인하세요.\n{res.text[:500]}")

    # 응답이 {"response": {...}}로 감싸져 오기도 하고, {"header":..., "body":...}로 바로 오기도 한다
    root = data.get("response", data)
    body = root.get("body", {})
    header = root.get("header", {})
    if header.get("resultCode") not in (None, "00", "0"):
        sys.exit(f"API 오류: {header}")

    items = body.get("items", [])
    if isinstance(items, dict):  # {"item": [...]} 형태로 오는 경우 대비
        items = items.get("item", [])
    if isinstance(items, dict):  # 한 건이면 dict로 오는 경우 대비
        items = [items]

    return items, int(body.get("totalCount", 0))


def download_all(endpoint: str, key: str) -> pd.DataFrame:
    rows, total = fetch_page(endpoint, key, 1)
    print(f"전체 {total}건")
    pages = (total + ROWS_PER_PAGE - 1) // ROWS_PER_PAGE

    for page in range(2, pages + 1):
        for attempt in range(3):  # 일시적인 네트워크 오류는 3번까지 재시도
            try:
                items, _ = fetch_page(endpoint, key, page)
                break
            except requests.RequestException as e:
                print(f"{page}페이지 재시도 {attempt + 1}/3: {e}")
                time.sleep(2)
        else:
            sys.exit(f"{page}페이지를 받지 못했어요. 잠시 후 다시 실행해 주세요.")
        rows.extend(items)
        print(f"{page}/{pages} 페이지 완료 ({len(rows)}건)")
        time.sleep(0.2)  # 서버에 부담 주지 않게 잠깐 쉬기

    return pd.DataFrame(rows).rename(columns=COLUMN_NAMES_KO)


def save_material(df: pd.DataFrame, prefix: str) -> None:
    # utf-8-sig: 엑셀에서 CSV를 열 때 한글이 깨지지 않게 함
    df.to_csv(f"{prefix}_all.csv", index=False, encoding="utf-8-sig")
    df.to_excel(f"{prefix}_all.xlsx", index=False)
    print(f"저장 완료: {prefix}_all.csv / .xlsx ({len(df)}건)")

    if "조리상태" in df.columns:
        raw = df[df["조리상태"] == "생것"]
        raw.to_csv(f"{prefix}_raw_only.csv", index=False, encoding="utf-8-sig")
        print(f"생것만: {prefix}_raw_only.csv ({len(raw)}건)")


def save_process(df: pd.DataFrame, prefix: str) -> None:
    df.to_csv(f"{prefix}_all.csv", index=False, encoding="utf-8-sig")
    print(f"저장 완료: {prefix}_all.csv ({len(df)}건)")

    if "식품명" not in df.columns:
        print("식품명 칼럼을 찾지 못했어요. 칼럼 목록:", list(df.columns))
        return
    pattern = "|".join(SEASONING_KEYWORDS)
    picked = df[df["식품명"].astype(str).str.contains(pattern)]
    picked.to_csv(f"{prefix}_seasonings.csv", index=False, encoding="utf-8-sig")
    print(f"양념·가공 재료만: {prefix}_seasonings.csv ({len(picked)}건)")


def main() -> None:
    name = sys.argv[1] if len(sys.argv) > 1 else "material"
    if name not in DATASETS:
        sys.exit(f"데이터 이름은 {list(DATASETS)} 중 하나로 넣어주세요.")

    load_dotenv()
    key = os.getenv("DATA_GO_KR_KEY")
    if not key:
        sys.exit(".env 파일에 DATA_GO_KR_KEY=인증키 를 넣어주세요.")

    conf = DATASETS[name]
    df = download_all(conf["endpoint"], key)
    if name == "material":
        save_material(df, conf["prefix"])
    else:
        save_process(df, conf["prefix"])


# API 영어 칼럼 → 알아보기 쉬운 한글 이름 (영양 계산에 주로 쓰는 것 위주, 나머지는 그대로 둠)
COLUMN_NAMES_KO = {
    "foodCd": "식품코드",
    "foodNm": "식품명",
    "foodOriginNm": "식품기원",
    "foodLv3Nm": "대분류",
    "foodLv4Nm": "대표식품명",
    "foodLv5Nm": "중분류",
    "foodLv6Nm": "소분류",
    "foodLv7Nm": "조리상태",
    "nutConSrtrQua": "기준량",
    "enerc": "에너지(kcal)",
    "water": "수분(g)",
    "prot": "단백질(g)",
    "fatce": "지방(g)",
    "chocdf": "탄수화물(g)",
    "sugar": "당류(g)",
    "fibtg": "식이섬유(g)",
    "nat": "나트륨(mg)",
    "k": "칼륨(mg)",
    "chole": "콜레스테롤(mg)",
    "fasat": "포화지방산(g)",
    "fatrn": "트랜스지방산(g)",
    "refuse": "폐기율(%)",
    "srcNm": "출처",
    "crtrYmd": "기준일자",
}


if __name__ == "__main__":
    main()

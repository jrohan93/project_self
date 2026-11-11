"""DB 접속 설정. 접속 주소는 .env의 DATABASE_URL에서 읽는다."""

import os

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

load_dotenv()


def get_database_url() -> str:
    url = os.getenv("DATABASE_URL")
    if not url:
        raise RuntimeError(".env에 DATABASE_URL이 없어요. .env.example을 참고하세요.")
    return url


def make_engine(url: str | None = None) -> Engine:
    # pool_pre_ping: 오래 쉬어서 끊긴 연결을 쓰기 전에 확인하고 다시 연결
    return create_engine(url or get_database_url(), pool_pre_ping=True)

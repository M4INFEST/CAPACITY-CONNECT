from collections.abc import Generator

import psycopg
from psycopg.rows import dict_row

from app.core.settings import database_url


def get_connection() -> Generator[psycopg.Connection, None, None]:
    with psycopg.connect(database_url(), row_factory=dict_row) as connection:
        yield connection

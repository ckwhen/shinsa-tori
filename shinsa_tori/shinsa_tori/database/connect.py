import os

from dotenv import load_dotenv
from psycopg2 import pool

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
# 移動 database 資料夾時要一併修正
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(CURRENT_DIR)))

dotenv_path = os.path.join(ROOT_DIR, 'configs', '.env')

load_dotenv(dotenv_path)

def get_db_pool():
    return pool.SimpleConnectionPool(
        minconn=1,
        maxconn=10,
        host=os.getenv("DB_HOST"),
        database=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        port=os.getenv("DB_PORT")
    )
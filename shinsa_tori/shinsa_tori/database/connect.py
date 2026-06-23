import os

from dotenv import load_dotenv
from psycopg2 import pool

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
# 移動 database 資料夾時要一併修正
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(CURRENT_DIR)))

dotenv_path = os.path.join(ROOT_DIR, 'configs', '.env')

load_dotenv(dotenv_path)

def get_db_pool():
    db_host = os.getenv("DB_HOST")
    db_port = os.getenv("DB_PORT")
    db_user = os.getenv("DB_USER")
    db_name = os.getenv("DB_NAME")

    print("\n" + "="*50)
    print("🔍 [DEBUG] 正在檢查環境變數載入狀態：")
    print(f"  - ROOT_DIR: {ROOT_DIR}")
    print(f"  - DB_HOST: {db_host} (型態: {type(db_host)})")
    print(f"  - DB_PORT: {db_port} (型態: {type(db_port)})")
    print(f"  - DB_USER: {db_user}")
    print(f"  - DB_NAME: {db_name}")

    return pool.SimpleConnectionPool(
        minconn=1,
        maxconn=10,
        host=os.getenv("DB_HOST"),
        database=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        port=os.getenv("DB_PORT")
    )
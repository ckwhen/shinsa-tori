import os
import psycopg2
from pathlib import Path
from dotenv import load_dotenv

import config_helper

ENV_PATH = Path(__file__).resolve().parent / "configs" / ".env"
load_dotenv(dotenv_path=ENV_PATH)

def load_all_clean_data():
    """
    [Loader 階段 - 終極自動化版]
    自動掃描 Transformer 產出的所有 CSV (*_clean.csv)，
    透過 PostgreSQL STAGING 中轉機制與純 SQL 集合操作，
    安全、不重複(UPSERT)地將全日本審查資料與多對多段位(Ranks)同步至資料庫。
    """

    try:
        global_config = config_helper.load_config(config_path="config.yaml") 
    except Exception as e:
        print(f"❌ Loader 初始化設定失敗: {e}")
        return

    shared_paths = global_config.get("shared_paths", {})

    # 定義輸入目錄 (Transformer 的輸出目錄)
    input_dir = Path(shared_paths.get("output_folder", ""))
    
    if not input_dir.exists():
        print(f"❌ 錯誤：找不到 CSV 目錄 [{input_dir}]，請先執行 Transformer。")
        return

    # 取得「所有縣市、所有年份」的 CSV (*_shinsas.csv)
    clean_csv_files = list(input_dir.glob("*_shinsas.csv"))

    if not clean_csv_files:
        print(f"❌ 錯誤：在 [{input_dir}] 找不到任何符合 *_shinsas.csv 的檔案。")
        return

    print(f"📂 尋找到 {len(clean_csv_files)} 個 CSV 檔案，準備建立資料庫連線...")

    try:
        conn = psycopg2.connect(
            host=os.getenv("DB_HOST"),
            database=os.getenv("DB_NAME"),
            user=os.getenv("DB_USER"),
            password=os.getenv("DB_PASSWORD"),
            port=os.getenv("DB_PORT")
        )
            
        conn.autocommit = False
    except Exception as e:
        print(f"❌ 資料庫連線失敗: {e}")
        return

    try:
        with conn.cursor() as cur:
            # 建立中轉表
            cur.execute("""
                CREATE UNLOGGED TABLE IF NOT EXISTS staging_shinsas (
                    name VARCHAR(255),
                    type INT,
                    location VARCHAR(255),
                    start_at TIMESTAMP,
                    candidate_type INT,
                    delivery_method_type INT,
                    note TEXT,
                    federation_name VARCHAR(100),
                    ranks TEXT,
                    file_name TEXT,
                    url_hash TEXT
                );
            """)

            # 開啟糢糊比對
            cur.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm;")
            
            # 迴圈自動處理所有 CSV (不再管是哪一個縣市)
            for csv_path in clean_csv_files:
                filename = csv_path.name
                print(f"🚀 正在將 [{filename}] 以純 SQL 高效模式匯入中轉表...")

                # 建立中轉表
                cur.execute("TRUNCATE TABLE staging_shinsas;")
                with open(csv_path, 'r', encoding='utf-8') as f:
                    copy_sql = """
                        COPY staging_shinsas(
                            name, type, location, start_at, candidate_type, 
                            delivery_method_type, note, federation_name, ranks,
                            file_name, url_hash
                        ) FROM STDIN WITH (FORMAT csv, HEADER true, NULL '');
                    """
                    cur.copy_expert(copy_sql, f)

                # 準備與加工暫存數據
                prepare_data_sql = r"""
                    -- A. 建立結構完全扁平的暫時加工表
                    CREATE TEMP TABLE temp_shinsa_prepared (
                        name VARCHAR(255),
                        type INT,
                        location VARCHAR(255),
                        start_at TIMESTAMP,
                        candidate_type INT,
                        delivery_method_type INT,
                        note TEXT,
                        federation_id UUID,
                        kyudojo_id UUID,
                        ranks TEXT
                    ) ON COMMIT DROP;

                    -- B. 將 CSV 原始資料與連盟 ID 塞進暫存表
                    INSERT INTO temp_shinsa_prepared (
                        name, type, location, delivery_method_type, start_at, note,
                        federation_id, ranks
                    )
                    SELECT 
                        s.name, s.type, s.location, s.delivery_method_type, s.start_at, s.note,
                        f.id, s.ranks
                    FROM staging_shinsas s
                    LEFT JOIN federations f ON f.name = s.federation_name;

                    -- C. 執行模糊比對更新 kyudojo_id
                    UPDATE temp_shinsa_prepared t
                    SET kyudojo_id = (
                        SELECT k.id 
                        FROM kyudojos k
                        JOIN federations f ON k.prefecture_code = f.prefecture_code
                        WHERE f.id = t.federation_id
                          AND similarity(k.name, t.location) >= 0.6
                        ORDER BY similarity(k.name, t.location) DESC 
                        LIMIT 1
                    );
                """
                cur.execute(prepare_data_sql)

                # UPSERT 與多對多同步
                bulk_upsert_sql = r"""
                    WITH upserted_shinsas AS (
                        INSERT INTO shinsas (
                            name, type, location, delivery_method_type, start_at, note, federation_id, kyudojo_id
                        )
                        SELECT name, type, location, delivery_method_type, start_at, note, federation_id, kyudojo_id
                        FROM temp_shinsa_prepared
                        ON CONFLICT (name, location, start_at)
                        DO UPDATE SET
                            note = EXCLUDED.note,
                            federation_id = EXCLUDED.federation_id,
                            kyudojo_id = EXCLUDED.kyudojo_id,
                            updated_at = CURRENT_TIMESTAMP
                        RETURNING id, name, location, start_at
                    ),
                    joined_ranks AS (
                        SELECT 
                            u.id AS shinsa_id,
                            NULLIF(regexp_split_to_table(t.ranks, '\s*[|]+\s*'), '') AS rank_name
                        FROM upserted_shinsas u
                        JOIN temp_shinsa_prepared t 
                          ON u.name = t.name AND u.location = t.location AND u.start_at = t.start_at
                    )
                    SELECT shinsa_id, rank_name INTO TEMP TABLE temp_ranks_to_insert FROM joined_ranks;

                    DELETE FROM ranks_shinsas WHERE shinsa_id IN (SELECT shinsa_id FROM temp_ranks_to_insert);

                    INSERT INTO ranks_shinsas (shinsa_id, rank_id)
                    SELECT tri.shinsa_id, r.id
                    FROM temp_ranks_to_insert tri
                    JOIN ranks r ON r.name = tri.rank_name
                    ON CONFLICT DO NOTHING;
                """
                cur.execute(bulk_upsert_sql)
                print(f"✨ [{filename}] 資料庫批次同步成功。")

        conn.commit()
        print(f"🎉 恭喜！所有 CSV 已全數安全寫入正式資料庫。")

    except Exception as e:
        conn.rollback()
        print(f"❌ Loader 執行失敗，整個事務已安全回滾。原因: {e}")
    finally:
        try:
            with conn.cursor() as cur:
                cur.execute("TRUNCATE TABLE staging_shinsas;")
            conn.commit()
        except:
            pass
        conn.close()

if __name__ == "__main__":
    load_all_clean_data()

import os
import psycopg2
import config_helper

from loguru import logger
from pathlib import Path
from dotenv import load_dotenv

# 環境變數載入防禦
ENV_PATH = Path(__file__).resolve().parent / "configs" / ".env"
load_dotenv(dotenv_path=ENV_PATH)

def load_all_clean_data():
    """
    Loader 階段：
    自動掃描 Staging 產出的所有 CSV 檔案，
    透過 PostgreSQL 連線與集合操作將審查資料安全載入資料庫。
    """
    logger.info("Initiating global clean data loading pipeline")

    try:
        global_config = config_helper.load_config(config_path="config.yaml") 
    except Exception as e:
        logger.exception("Loader initialization failed: Configuration block load error")
        return

    shared_paths = global_config.get("shared_paths", {})
    input_dir = Path(shared_paths.get("output_folder", ""))
    logger.debug(f"Scanning target clean dataset directory: '{input_dir}'")
    
    if not input_dir.exists():
        logger.error(f"Directory error: Target output folder '{input_dir}' does not exist")
        raise FileNotFoundError(f"Clean CSV directory missing: {input_dir}")

    # 取得「所有縣市、所有年份」的 CSV (*_shinsas.csv)
    clean_csv_files = list(input_dir.glob("*_shinsas.csv"))

    if not clean_csv_files:
        logger.error(f"Data missing: No matching *_shinsas.csv files found in '{input_dir}'")
        raise FileNotFoundError(f"No target Clean CSV files found in directory: {input_dir}")

    logger.info(f"Scan completed | Found {len(clean_csv_files)} clean CSV files to load | Target host: {os.getenv('DB_HOST')}")

    try:
        logger.debug("Establishing connection to PostgreSQL database")
        conn = psycopg2.connect(
            host=os.getenv("DB_HOST"),
            database=os.getenv("DB_NAME"),
            user=os.getenv("DB_USER"),
            password=os.getenv("DB_PASSWORD"),
            port=os.getenv("DB_PORT")
        )
            
        conn.autocommit = False
        logger.debug("Database connection established and autocommit disabled")

    except Exception as e:
        logger.exception(f"Database connection failed: Unable to connect to host '{os.getenv('DB_HOST')}' or database '{os.getenv('DB_NAME')}'")
        raise e

    try:
        with conn.cursor() as cur:
            total_loaded_files = 0

            # 建立中轉表
            cur.execute(r"""
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

            for csv_path in clean_csv_files:
                filename = csv_path.name
                logger.info(f"Initiating bulk COPY stage for staging dataset: '{filename}'")

                # 建立中轉表
                cur.execute("TRUNCATE TABLE staging_shinsas;")

                logger.debug(f"Streaming data packet via STDIN into staging table for: '{filename}'")
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

                # 依據 COUNT() FILTER 統計並回報 kyudojo_id 模糊比對失敗的資料品質警告
                quality_check_sql = r"""
                    SELECT
                        COUNT(*) AS total_rows,
                        COUNT(*) FILTER (WHERE kyudojo_id IS NULL) AS match_failed_rows
                    FROM temp_shinsa_prepared;
                """
                cur.execute(quality_check_sql)
                total_rows, match_failed_rows = cur.fetchone()

                if match_failed_rows > 0:
                    logger.warning(
                        f"Data quality alert | File: '{filename}' | "
                        f"Fuzzy matching failure rate: {match_failed_rows}/{total_rows} "
                        f"records failed to map a valid 'kyudojo_id' (similarity < 0.6)"
                    )
                else:
                    logger.debug(f"Data quality check passed | File: '{filename}' | All {total_rows} records mapped successfully")

                logger.debug(f"[{filename}] Initiating multi-step relational data persistence")

                # 建立用於接收主表 UPSERT 結果的實體 ID 暫存表
                cur.execute(r"""
                    CREATE TEMP TABLE temp_upserted_results (
                        id UUID, name VARCHAR(255), location VARCHAR(255), start_at TIMESTAMP
                    ) ON COMMIT DROP;
                """)

                # 執行主表 shinsas 的 UPSERT 寫入
                shinsa_upsert_sql = r"""
                    WITH upsert_action AS (
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
                    )
                    INSERT INTO temp_upserted_results SELECT id, name, location, start_at FROM upsert_action;
                """
                cur.execute(shinsa_upsert_sql)

                # 取得本次處理的總筆數統計
                cur.execute("SELECT COUNT(*) FROM temp_upserted_results;")
                upserted_count = cur.fetchone()[0]

                # 建立用於清洗 shinsas, ranks 多對多關係的外鍵安全對齊暫存表
                cur.execute(r"""
                    CREATE TEMP TABLE temp_ranks_to_insert (
                        shinsa_id UUID, rank_id UUID
                    ) ON COMMIT DROP;
                """)

                # 橫向正則拆分字串並與正式段位表進行 JOIN 關聯
                rank_split_sql = r"""
                    INSERT INTO temp_ranks_to_insert (shinsa_id, rank_id)
                    SELECT
                        u.id AS shinsa_id,
                        r.id AS rank_id
                    FROM temp_upserted_results u
                    JOIN temp_shinsa_prepared t
                      ON u.name = t.name AND u.location = t.location AND u.start_at = t.start_at

                    -- A. 先在最外層用 LATERAL 把字串炸開成多行
                    CROSS JOIN LATERAL regexp_split_to_table(t.ranks, '\s*[|]+\s*') AS split_rank_raw

                    -- B. 透過 JOIN 正式段位表（ranks）完成對齊防禦
                    JOIN ranks r ON r.name = split_rank_raw

                    -- C. 透過 WHERE 條件過濾掉任何空字串或純空格引起的噪聲
                    WHERE split_rank_raw IS NOT NULL
                      AND TRIM(split_rank_raw) != '';
                """
                cur.execute(rank_split_sql)

                # 清除這批審查歷史上綁定的舊段位關係
                cur.execute(r"""
                    DELETE FROM ranks_shinsas
                    WHERE shinsa_id IN (SELECT shinsa_id FROM temp_ranks_to_insert);
                """)

                # 將全新的多對多關係實體寫入
                cur.execute(r"""
                    INSERT INTO ranks_shinsas (shinsa_id, rank_id)
                    SELECT shinsa_id, rank_id
                    FROM temp_ranks_to_insert
                    ON CONFLICT DO NOTHING;
                """)

                # CSV 處理完畢，發出結構化資訊回報
                inserted_relations_count = cur.rowcount
                logger.info(
                    f"Database batch synchronization completed for: '{filename}' | "
                    f"Synced {upserted_count} shinsas records | "
                    f"Linked {inserted_relations_count} rank relations to ranks_shinsas"
                )
                total_loaded_files += 1

        logger.debug("Committing database core transaction packet")
        conn.commit()

        logger.info(f"Global load transaction committed successfully | Processed files: {total_loaded_files}/{len(clean_csv_files)}")

    except Exception as e:
        logger.exception("Database pipeline transactional failure detected | Triggering database rollback")
        conn.rollback()
        raise e

    finally:
        try:
            with conn.cursor() as cur:
                cur.execute("TRUNCATE TABLE staging_shinsas;")
            conn.commit()
            logger.debug("Staging transaction cleaner executed: Mid-table truncated")
        except Exception:
            pass
        conn.close()
        logger.debug("Database pipe stream safely closed")

if __name__ == "__main__":
    load_all_clean_data()

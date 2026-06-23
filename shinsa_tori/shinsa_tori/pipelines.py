from shinsa_tori.database.connect import get_db_pool

class ShinsaToriPipeline:
    def __init__(self):
        self.db_pool = get_db_pool()

    def process_item(self, item, spider):
        conn = self.db_pool.getconn()

        try:
            with conn.cursor() as cur:
                upsert_shinsa_sql = """
                    INSERT INTO shinsas (
                        name,
                        type,
                        location,
                        delivery_method_type,
                        start_at,
                        note
                    )
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (name, location, start_at)
                    DO UPDATE SET
                        note = EXCLUDED.note,
                        updated_at = CURRENT_TIMESTAMP
                    RETURNING id;
                """
                cur.execute(upsert_shinsa_sql, (
                    item['name'],
                    item['type'],
                    item['location'],
                    item['delivery_method_type'],
                    item['start_at'],
                    item['note']
                ))

                actual_shinsa_id = cur.fetchone()[0]

                cur.execute("DELETE FROM ranks_shinsas WHERE shinsa_id = %s;", (actual_shinsa_id,))
                if item.get('ranks'):
                    insert_rank_shinsa_sql = """
                        INSERT INTO ranks_shinsas (shinsa_id, rank_id)
                        SELECT %s, id FROM ranks WHERE name LIKE %s LIMIT 1;
                    """

                    rank_shinsa_batch = [
                        (actual_shinsa_id, f"{r['rank_name'].strip()}%")
                        for r in item['ranks']
                    ]
                    cur.executemany(insert_rank_shinsa_sql, rank_shinsa_batch)

            conn.commit()
            spider.logger.info(f"✨ [純 SQL 同步成功] {item['name']} ({item['start_at']})")

        except Exception as e:
            conn.rollback()
            spider.logger.error(f"❌ [純 SQL 寫入失敗] 事務已回滾。原因: {e}")
            raise e

        finally:
            self.db_pool.putconn(conn)

        return item

    def close_spider(self, spider):
        if self.db_pool:
            self.db_pool.closeall()
            spider.logger.info("PostgreSQL 連線池已安全關閉。")
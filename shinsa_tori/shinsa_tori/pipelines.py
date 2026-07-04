from shinsa_tori.database.connect import get_db_pool

from scrapy.exceptions import DropItem
from shinsa_tori.items import ShinsaItem, KyudojoItem

class ShinsaToriPipeline:
    def __init__(self, crawler=None):
        self.db_pool = None
        self.crawler = crawler
    
    @classmethod
    def from_crawler(cls, crawler):
        return cls(crawler=crawler)

    def open_spider(self):
        if self.db_pool is None:
            try:
                self.db_pool = get_db_pool()
                if self.crawler and self.crawler.spider:
                    self.crawler.spider.logger.info("--- ShinsaToriPipeline 資料庫連線池初始化成功 ---")
            except Exception as e:
                if self.crawler and self.crawler.spider:
                    self.crawler.spider.logger.error(f"❌ ShinsaToriPipeline 連線池建立失敗: {e}")

    def process_item(self, item, spider):
        if not isinstance(item, ShinsaItem):
            return item

        if not self.db_pool:
            return item

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
                        SELECT %s, id FROM ranks WHERE name = %s;
                    """

                    rank_shinsa_batch = [
                        (actual_shinsa_id, rank_name)
                        for rank_name in item['ranks']
                    ]
                    cur.executemany(insert_rank_shinsa_sql, rank_shinsa_batch)

            conn.commit()
            spider.logger.info(f"✨ [純 SQL 同步成功] {item['name']} ({item['start_at']})")

        except Exception as e:
            conn.rollback()
            spider.logger.error(f"❌ [純 SQL 寫入失敗] 事務已回滾。原因: {e}")
            raise DropItem(f"無法寫入資料庫: {item['name']}")

        finally:
            self.db_pool.putconn(conn)

        return item

    def close_spider(self):
        pass

class KyudojoPipeline:
    def __init__(self, crawler=None):
        self.db_pool = None
        self.crawler = crawler

    @classmethod
    def from_crawler(cls, crawler):
        return cls(crawler=crawler)

    def open_spider(self):
        if self.db_pool is None:
            try:
                self.db_pool = get_db_pool()
                if self.crawler and self.crawler.spider:
                    self.crawler.spider.logger.info("--- KyudojoPipeline 資料庫連線池初始化成功 ---")
            except Exception as e:
                if self.crawler and self.crawler.spider:
                    self.crawler.spider.logger.error(f"❌ KyudojoPipeline 連線池建立失敗: {e}")

    def process_item(self, item, spider):
        if not isinstance(item, KyudojoItem):
            return item

        if not self.db_pool:
            return item

        conn = self.db_pool.getconn()

        try:
            with conn.cursor() as cur:
                insert_kyudojo_sql = """
                    INSERT INTO kyudojos (
                        name,
                        address,
                        phone,
                        latitude,
                        longitude,
                        prefecture_code
                    )
                    SELECT %s, %s, %s, %s, %s, p.code
                    FROM prefectures p
                    WHERE p.code = %s
                    ON CONFLICT (id)
                    DO NOTHING;
                """

                lat_val = float(item['latitude']) if item['latitude'] else None
                lng_val = float(item['longitude']) if item['longitude'] else None

                cur.execute(insert_kyudojo_sql, (
                    item['name'],
                    item['address'],
                    item['phone'],
                    lat_val,
                    lng_val,
                    item['prefecture_code']
                ))

            conn.commit()
            spider.logger.info(f"✨ [純 SQL 同步成功] 弓道場: {item['name']} ({item['prefecture_code']})")

        except Exception as e:
            conn.rollback()
            spider.logger.error(f"❌ [純 SQL 寫入失敗] 事務已回滾。道場: {item['name']}，原因: {e}")
            raise DropItem(f"無法寫入資料庫: {item['name']}")

        finally:
            self.db_pool.putconn(conn)

        return item

    def close_spider(self):
        if self.db_pool:
            self.db_pool.closeall()
            if self.crawler and self.crawler.spider:
                self.crawler.spider.logger.info("PostgreSQL 連線池已安全關閉。")
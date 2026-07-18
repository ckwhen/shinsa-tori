import hashlib

from scrapy.pipelines.files import FilesPipeline
from scrapy.exceptions import DropItem
from scrapy.http import Request
from shinsa_tori.database.connect import get_db_pool
from shinsa_tori.items import (
    ShinsaItem,
    FederationItem,
    KyudojoItem,
    DocumentItem
)

class ShinsaToriFilesPipeline(FilesPipeline):
    def get_media_requests(self, item, info):
        if not isinstance(item, DocumentItem):
            return

        for file_url in item.get('file_urls', []):
            yield Request(
                file_url, 
                meta={
                    'title': item.get('title'),
                    'year': item.get('year')
                }
            )

    def file_path(self, request, response=None, info=None, *, item=None):
        url_hash = hashlib.shake_256(request.url.encode()).hexdigest(5)

        year = request.meta.get('year')
        title = request.meta.get('title')

        custom_filename = f"{year}_{title}_{url_hash}.pdf"
        
        return f"full/{custom_filename}"

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
                        note,
                        federation_id,
                        kyudojo_id
                    )
                    VALUES (
                        %s, %s, %s, %s, %s, %s,
                        (SELECT id FROM federations WHERE name = %s LIMIT 1),
                        (
                            SELECT k.id
                            FROM kyudojos k
                            JOIN federations f ON k.prefecture_code = f.prefecture_code
                            CROSS JOIN (SELECT %s AS loc, %s AS fed_name) tmp
                            WHERE f.name = tmp.fed_name
                              AND similarity(k.name, tmp.loc) >= 0.6
                            ORDER BY similarity(k.name, tmp.loc) DESC
                            LIMIT 1
                        )
                    )
                    ON CONFLICT (name, location, start_at)
                    DO UPDATE SET
                        note = EXCLUDED.note,
                        federation_id = EXCLUDED.federation_id,
                        kyudojo_id = EXCLUDED.kyudojo_id,
                        updated_at = CURRENT_TIMESTAMP
                    RETURNING id;
                """
                cur.execute(upsert_shinsa_sql, (
                    item['name'],
                    item['type'],
                    item.get('location'),
                    item['delivery_method_type'],
                    item['start_at'],
                    item.get('note'),
                    item['federation_name'],
                    item.get('location'),
                    item['federation_name']
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

class FederationPipeline:
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
                    self.crawler.spider.logger.info("--- FederationPipeline 資料庫連線池初始化成功 ---")
            except Exception as e:
                if self.crawler and self.crawler.spider:
                    self.crawler.spider.logger.error(f"❌ FederationPipeline 連線池建立失敗: {e}")

    def process_item(self, item, spider):
        if not isinstance(item, FederationItem):
            return item

        if not self.db_pool:
            return item

        conn = self.db_pool.getconn()

        try:
            with conn.cursor() as cur:
                insert_federation_sql = """
                    INSERT INTO federations (
                        name, 
                        prefecture_code, 
                        region_id
                    )
                    SELECT 
                        %s, 
                        %s, 
                        (SELECT id FROM regions WHERE name_ja LIKE %s || '%%')
                    ON CONFLICT (name) 
                    DO NOTHING;
                """

                cur.execute(insert_federation_sql, (
                    item['name'],
                    item['prefecture_code'],
                    item['region_name']
                ))

            conn.commit()
            spider.logger.info(f"✨ [純 SQL 同步成功] 地方連盟: {item['name']} ({item['region_name']})")

        except Exception as e:
            conn.rollback()
            spider.logger.error(f"❌ [純 SQL 寫入失敗] 事務已回滾。連盟: {item['name']}，原因: {e}")
            raise DropItem(f"無法寫入資料庫: {item['name']}")

        finally:
            # 100% 延用您的釋放連線回池風格
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
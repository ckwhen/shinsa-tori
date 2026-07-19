import scrapy

class DocumentItem(scrapy.Item):
    file_urls = scrapy.Field()
    files = scrapy.Field()

    title = scrapy.Field()
    year = scrapy.Field()

class ShinsaItem(scrapy.Item):
    id = scrapy.Field()
    name = scrapy.Field()
    type = scrapy.Field()
    location = scrapy.Field()
    start_at = scrapy.Field()
    candidate_type = scrapy.Field()
    delivery_method_type = scrapy.Field()
    note = scrapy.Field()
    federation_name = scrapy.Field()

    ranks = scrapy.Field()

class KyudojoItem(scrapy.Item):
    name = scrapy.Field()
    address = scrapy.Field()
    phone = scrapy.Field()
    prefecture_code = scrapy.Field()
    latitude = scrapy.Field()
    longitude = scrapy.Field()

class FederationItem(scrapy.Item):
    name = scrapy.Field()
    prefecture_code = scrapy.Field()
    region_name = scrapy.Field()
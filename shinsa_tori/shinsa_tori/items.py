import scrapy

class ShinsaItem(scrapy.Item):
    id = scrapy.Field()
    name = scrapy.Field()
    type = scrapy.Field()
    location = scrapy.Field()
    start_at = scrapy.Field()
    candidate_type = scrapy.Field()
    delivery_method_type = scrapy.Field()
    note = scrapy.Field()

    ranks = scrapy.Field()

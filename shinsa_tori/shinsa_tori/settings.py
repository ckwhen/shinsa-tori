import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

BOT_NAME = "shinsa_tori"
SPIDER_MODULES = ["shinsa_tori.spiders"]
NEWSPIDER_MODULE = "shinsa_tori.spiders"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36"
ROBOTSTXT_OBEY = True
DOWNLOAD_DELAY = 2
ITEM_PIPELINES = {
    "shinsa_tori.pipelines.ShinsaToriFilesPipeline": 1,
    "shinsa_tori.pipelines.ShinsaToriPipeline": 800,
    "shinsa_tori.pipelines.FederationPipeline": 850,
    "shinsa_tori.pipelines.KyudojoPipeline": 900,
}
FILES_STORE = "downloads"
AUTOTHROTTLE_ENABLED = True
TWISTED_REACTOR = "twisted.internet.asyncioreactor.AsyncioSelectorReactor"
FEED_EXPORT_ENCODING = "utf-8"

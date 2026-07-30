import pytest
import requests
import time
from db_query import DbQueryStats

TARGET = "<PROMOTION_URL>"
TABLE = "<PROMOTION_TABLE>"


class TestPromotionCache:
    @classmethod
    def setup_class(cls):
        cls.stats = DbQueryStats()

    @classmethod
    def teardown_class(cls):
        cls.stats.close()

    def test_zero_db_queries_after_warmup(self):
        # warm up
        requests.get(TARGET)
        time.sleep(0.5)

        baseline = self.stats.snapshot([TABLE])

        # verify
        requests.get(TARGET)
        time.sleep(0.5)

        after = self.stats.snapshot([TABLE])
        leaked = after - baseline

        assert leaked == 0, f"Leaked {leaked} DB queries after cache warm-up"

# -*- coding: utf-8 -*-
import argparse
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import find_stores as fs


class FakeClient:
    def __init__(self):
        self.calls = []
        self.fail = set()

    def call(self, name, args):
        self.calls.append((name, args))
        code = args.get("storeCode")
        if (name, code) in self.fail:
            raise fs.McdError("网络错误", "临时连接失败。")
        if name == "query-nearby-stores":
            keyword = args["keyword"]
            return {"data": [
                {"storeCode": "S1", "storeName": "新街口店", "address": "南京市中山路", "distance": 1},
                {"storeCode": "S2", "storeName": "鼓楼店", "address": "南京市鼓楼", "distance": 2},
            ] if keyword == "新街口" else [{"storeCode": "S1", "storeName": "新街口店", "address": "南京市中山路"}]}
        if name == "query-meals":
            return {"data": {"categories": [{"name": "开心乐园餐", "meals": [
                {"code": "M1", "name": "开心乐园套餐", "tags": ["儿童"], "currentPrice": 39},
                {"code": "M2", "name": "薯条", "tags": []},
            ]}]}}
        if name == "query-meal-detail":
            return {"data": {"rounds": [{"name": "玩具", "choices": [
                {"code": "521991", "name": "海绵宝宝×航海王"},
                {"code": "RANDOM", "name": "随机玩具"},
            ]}, {"name": "饮料", "choices": [{"code": "COLA", "name": "可乐"}]}]}}
        raise AssertionError(name)


def args(**overrides):
    values = dict(series=None, series_name=None, toy_code=None, discover=False, city="南京市",
                  area=["新街口"], max_stores=10, workers=2, at=None)
    values.update(overrides)
    return argparse.Namespace(**values)


class FindStoresTests(unittest.TestCase):
    def setUp(self):
        self.fake = FakeClient()
        self.entries = [{"id": "spongebob-op", "name": "海绵宝宝×航海王",
                         "aliases": ["海绵宝宝航海王"], "official_codes": ["521991"]}]

    def test_dedup_stores_and_appointment_forwarded(self):
        old_series = fs.load_series
        old_areas = fs.load_json
        fs.load_series = lambda: self.entries
        fs.load_json = lambda path, fallback: {"cities": {"南京市": ["鼓楼"]}}
        try:
            result = fs.run(args(series="海绵宝宝航海王", at="2026-10-15 12:00"), self.fake)
        finally:
            fs.load_series, fs.load_json = old_series, old_areas
        self.assertEqual(result["coverage"]["discovered"], 2)
        self.assertEqual(result["coverage"]["matched"], 2)
        self.assertTrue(all(call[1].get("reservationDate") for call in self.fake.calls if call[0] in ("query-meals", "query-meal-detail")))
        self.assertTrue(all(call[1].get("code") and "mealCode" not in call[1] for call in self.fake.calls if call[0] == "query-meal-detail"))
        self.assertTrue(all(call[1]["reservationDate"] == "2026-10-15 12:00" for call in self.fake.calls if call[0] in ("query-meals", "query-meal-detail")))
        self.assertEqual([x["store_code"] for x in result["stores"]], ["S1", "S2"])

    def test_exact_and_fuzzy_series_matching(self):
        self.assertTrue(fs.match_choice({"code": "521991", "name": "海绵宝宝×航海王联名"}, self.entries[0], None, None))
        broad = {"id": "spongebob", "name": "海绵宝宝", "aliases": [], "official_codes": []}
        self.assertFalse(fs.match_choice({"code": "x", "name": "海绵宝宝主题玩具"}, broad, None, None))
        self.assertFalse(fs.match_choice({"code": "x", "name": "随机玩具"}, broad, None, None))
        self.assertTrue(fs.match_choice({"code": "x", "name": "限定联名系列"}, None, "限定联名系列", None))
        self.assertFalse(fs.match_choice({"code": "x", "name": "限定联名系列盲盒"}, None, "限定联名系列", None))

    def test_partial_detail_failure_becomes_unknown(self):
        self.fake.fail.add(("query-meals", "S1"))
        old_series = fs.load_series
        old_areas = fs.load_json
        fs.load_series = lambda: self.entries
        fs.load_json = lambda path, fallback: {}
        try:
            result = fs.run(args(series="海绵宝宝×航海王"), self.fake)
        finally:
            fs.load_series, fs.load_json = old_series, old_areas
        row = next(s for s in result["stores"] if s["store_code"] == "S1")
        self.assertEqual(row["status"], "unknown")
        self.assertEqual(result["coverage"]["unknown"], 1)

    def test_discover_includes_current_toy_codes(self):
        row, series, _ = fs.search_one(self.fake, {"storeCode": "S1"}, None, None, None, None, True)
        self.assertEqual(row["status"], "unknown")
        self.assertEqual({x["code"] for x in series}, {"521991"})
        self.assertNotIn("COLA", {x["code"] for x in series})

    def test_category_tags_merge_with_full_meal_map(self):
        meals = fs.extract_meals({"categories": [{"name": "开心乐园餐", "meals": [{"code": "M1", "tags": ["儿童"]}]}],
                                  "meals": {"M1": {"name": "套餐", "currentPrice": 39}, "M2": {"name": "玩具公仔", "currentPrice": 12}}})
        by_code = {m["code"]: m for m in meals}
        self.assertEqual(by_code["M1"]["name"], "套餐")
        self.assertEqual(by_code["M1"]["currentPrice"], 39)
        self.assertIn("M2", by_code)

    def test_random_toy_only_is_unknown(self):
        class RandomOnly(FakeClient):
            def call(self, name, args):
                if name == "query-meals":
                    return {"data": {"meals": {"M1": {"name": "开心乐园餐", "tags": ["儿童"]}}}}
                if name == "query-meal-detail":
                    return {"data": {"rounds": [{"name": "玩具", "choices": [{"code": "R", "name": "随机玩具"}]}]}}
                return super().call(name, args)
        row, _, _ = fs.search_one(RandomOnly(), {"storeCode": "S1"}, None, "海绵宝宝", None, None, False)
        self.assertEqual(row["status"], "unknown")

    def test_roundless_independent_toy_detail_matches(self):
        class IndependentToy(FakeClient):
            def call(self, name, args):
                if name == "query-meal-detail":
                    return {"data": {"code": "TOY-7", "name": "独立玩具公仔", "image": "https://example.test/toy.png"}}
                return super().call(name, args)
        row, available, _ = fs.search_one(IndependentToy(), {"storeCode": "S1"}, None,
                                          "独立玩具公仔", "TOY-7", None, True)
        self.assertEqual(row["status"], "matched")
        self.assertEqual(row["matches"][0]["toy_code"], "TOY-7")
        self.assertEqual(available[0]["image"], "https://example.test/toy.png")

    def test_partial_detail_failure_keeps_match_and_marks_partial(self):
        class Partial(FakeClient):
            def call(self, name, args):
                if name == "query-meals":
                    return {"data": {"meals": {
                        "M1": {"name": "开心乐园餐", "tags": ["儿童"]},
                        "M2": {"name": "亲子玩具套餐", "tags": ["玩具"]}}}}
                if name == "query-meal-detail" and args["code"] == "M2":
                    raise fs.McdError("网络错误", "套餐详情连接失败。")
                if name == "query-meal-detail":
                    return {"data": {"rounds": [{"name": "玩具", "choices": [
                        {"code": "521991", "name": "海绵宝宝×航海王"}]}]}}
                return super().call(name, args)
        row, _, failed = fs.search_one(Partial(), {"storeCode": "S1"}, self.entries[0], None, None, None, False)
        self.assertTrue(row["matches"])
        self.assertEqual(row["status"], "matched")
        self.assertTrue(row["partial"])
        self.assertTrue(failed)

    def test_nearby_stores_accepts_legacy_wrapped_list_too(self):
        class Wrapped(FakeClient):
            def call(self, name, args):
                if name == "query-nearby-stores":
                    return {"data": {"list": [{"storeCode": "W1", "storeName": "包装门店"}]}}
                return super().call(name, args)
        self.assertEqual(fs.search_stores(Wrapped(), "南京市", ["新街口"])[0]["storeCode"], "W1")


if __name__ == "__main__":
    unittest.main()


# -*- coding: utf-8 -*-
"""麦麦寻玩：只读查找指定玩具系列的门店与套餐。"""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from mcd_client import McdClient, McdError

ROOT = Path(__file__).resolve().parents[1]
SERIES_FILE = ROOT / "references" / "series.json"
AREAS_FILE = ROOT / "references" / "search_areas.json"
TOY_WORDS = ("开心乐园", "儿童", "亲子", "玩具", "公仔", "盲盒", "玩偶", "毛绒")
IGNORE_NAMES = ("随机玩具", "随机公仔")
TZ = timezone(timedelta(hours=8))


def normalize(s: Any) -> str:
    return re.sub(r"[\s·・_—–\-，,。.!！?？:：()（）【】\[\]]+", "", str(s or "")).casefold()


def load_json(path: Path, fallback: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return fallback


def load_series() -> list[dict]:
    data = load_json(SERIES_FILE, {})
    return data.get("series", []) if isinstance(data, dict) else []


def resolve_series(query: str, entries: list[dict]) -> dict | None:
    needle = normalize(query)
    for item in entries:
        terms = [item.get("id", ""), item.get("name", ""), *(item.get("aliases") or [])]
        if any(normalize(term) == needle for term in terms):
            return item
    return None


def candidate_series_name(name: str) -> bool:
    clean = str(name or "").strip()
    return bool(clean) and not any(x in clean for x in IGNORE_NAMES)


def is_toy_candidate(meal: dict, category_name: str = "") -> bool:
    text = str(meal.get("name", ""))
    tags = meal.get("tags") or []
    tagged = " ".join(map(str, tags)) if isinstance(tags, list) else str(tags)
    return any(word in text or word in tagged or word in category_name for word in TOY_WORDS)


def local_now() -> str:
    return datetime.now(TZ).isoformat(timespec="seconds")


def get_data(result: Any) -> Any:
    return result.get("data", {}) if isinstance(result, dict) else {}


def detail_args(store_code: str, meal_code: str, at: str | None) -> dict:
    args = {"storeCode": store_code, "code": meal_code, "orderType": 1, "beType": 1}
    if at:
        args["reservationDate"] = at
    return args


def extract_meals(data: dict) -> list[dict]:
    found: dict[str, dict] = {}
    toy_category_codes: set[str] = set()
    categories = data.get("categories") or []
    if isinstance(categories, list):
        for cat in categories:
            for meal in (cat.get("meals") or []) if isinstance(cat, dict) else []:
                code = str(meal.get("code", ""))
                if code:
                    found[code] = meal
                    if is_toy_candidate(meal, str(cat.get("name", ""))):
                        toy_category_codes.add(code)
    mapping = data.get("meals") or {}
    if isinstance(mapping, dict):
        for code, meal in mapping.items():
            if isinstance(meal, dict):
                key = str(code)
                found[key] = {**found.get(key, {}), **meal, "code": key}
    return [m for code, m in found.items() if code in toy_category_codes or is_toy_candidate(m)]


def choices_from(data: dict) -> list[tuple[dict, dict]]:
    out = []
    for round_item in data.get("rounds") or []:
        for choice in round_item.get("choices") or []:
            if isinstance(choice, dict):
                out.append((round_item, choice))
    return out


def is_toy_choice(round_item: dict, choice: dict) -> bool:
    name = str(choice.get("name", ""))
    round_name = str(round_item.get("name", ""))
    if any(word in name for word in ("飲料", "饮料", "主食", "配餐", "薯条", "可乐", "雪碧")):
        return False
    toy_terms = ("玩具", "公仔", "盲盒", "玩偶", "毛绒")
    return any(word in (name + round_name) for word in toy_terms)


def match_choice(choice: dict, target: dict | None, target_name: str | None, toy_code: str | None) -> bool:
    code = str(choice.get("code", ""))
    name = str(choice.get("name", ""))
    if target:
        codes = {str(c) for c in target.get("official_codes", [])}
        if code and code in codes:
            return True
        terms = [target.get("name", ""), *(target.get("aliases") or [])]
        n = normalize(name)
        return bool(n and any(normalize(t) == n and normalize(t) for t in terms))
    if target_name:
        if toy_code and code == toy_code:
            return normalize(name) == normalize(target_name) if name else True
        # 官方全名按完整名称比较，避免相近联名系列互相误匹配。
        return normalize(name) == normalize(target_name)
    return False


def store_error(store: dict, status: str, stamp: str) -> dict:
    return {"store_code": str(store.get("storeCode", "")), "name": store.get("storeName", ""),
            "address": store.get("address", ""), "matches": [], "status": status, "partial": False, "checked_at": stamp}


def search_one(client: McdClient, store: dict, target: dict | None, target_name: str | None,
               toy_code: str | None, at: str | None, discover: bool) -> tuple[dict, list[dict], bool]:
    code = str(store.get("storeCode", ""))
    stamp = local_now()
    row = store_error(store, "not_matched", stamp)
    matches: list[dict] = []
    available: dict[str, dict] = {}
    had_error = False
    random_seen = False
    try:
        args = {"storeCode": code, "orderType": 1, "beType": 1}
        if at:
            args["reservationDate"] = at
        meals_data = get_data(client.call("query-meals", args))
    except McdError as exc:
        row["status"] = "unknown"
        row["partial"] = True
        row["note"] = exc.message
        return row, [], True
    meals = extract_meals(meals_data)
    for meal in meals:
        meal_code = str(meal.get("code", ""))
        if not meal_code:
            continue
        try:
            detail = get_data(client.call("query-meal-detail", detail_args(code, meal_code, at)))
        except McdError:
            had_error = True
            continue
        detail_choices = choices_from(detail)
        # 独立玩具详情可能直接提供商品信息，选项列表为空。
        own_code, own_name = str(detail.get("code", "")), str(detail.get("name", "")).strip()
        if own_code and own_name and is_toy_choice({"name": own_name}, {"name": own_name}):
            detail_choices.append(({"name": own_name}, {"code": own_code, "name": own_name,
                                   "image": detail.get("image")}))
        for round_item, choice in detail_choices:
            toy = str(choice.get("code", ""))
            toy_name = str(choice.get("name", "")).strip()
            if any(term in toy_name for term in IGNORE_NAMES):
                random_seen = True
            if discover and toy and toy_name and candidate_series_name(toy_name) and is_toy_choice(round_item, choice):
                item = available.setdefault(toy, {"code": toy, "name": toy_name, "image": choice.get("image"), "stores": []})
                if code not in item["stores"]:
                    item["stores"].append(code)
            if match_choice(choice, target, target_name, toy_code):
                matches.append({"meal_code": meal_code, "meal_name": meal.get("name", ""),
                                "menu_price": meal.get("currentPrice"), "toy_code": toy,
                                "toy_name": toy_name, "evidence_tool": "query-meal-detail"})
    unique = {}
    for m in matches:
        unique[(m["meal_code"], m["toy_code"])] = m
    row["matches"] = list(unique.values())
    row["status"] = "matched" if row["matches"] else ("unknown" if had_error or random_seen else "not_matched")
    row["partial"] = had_error
    if random_seen and not row["matches"]:
        row["note"] = "菜单包含随机玩具，具体系列待确认。"
    elif had_error:
        row["note"] = "部分套餐详情查询未完成。"
    row["checked_at"] = local_now()
    return row, list(available.values()) if discover else [], had_error


def parse_at(value: str) -> str:
    try:
        datetime.strptime(value, "%Y-%m-%d %H:%M")
        return value
    except ValueError as exc:
        raise argparse.ArgumentTypeError("时间格式应为 YYYY-MM-DD HH:MM") from exc


def build_queries(city: str, requested: list[str], areas: dict) -> list[str]:
    defaults = (areas.get("cities") or {}).get(city, [])
    terms = []
    chosen = requested if requested else list(defaults)
    for item in chosen:
        if item and item not in terms:
            terms.append(item)
    if not terms and city:
        terms = [city]
    return terms[:12]


def search_stores(client: McdClient, city: str, terms: list[str]) -> list[dict]:
    seen: set[str] = set()
    stores = []
    for keyword in terms:
        result = client.call("query-nearby-stores", {"beType": 1, "searchType": 2, "city": city, "keyword": keyword})
        data = get_data(result)
        raw = data if isinstance(data, list) else data.get("list", [])
        for item in raw if isinstance(raw, list) else []:
            code = str(item.get("storeCode", ""))
            if code and code not in seen:
                seen.add(code)
                stores.append(item)
    return stores


def run(args: argparse.Namespace, client: McdClient | None = None) -> dict:
    entries = load_series()
    target = resolve_series(args.series, entries) if args.series else None
    target_name = args.series_name
    if args.series and not target:
        raise ValueError(f"未找到系列“{args.series}”。请运行 --list-series 查看本地图鉴，或使用 --series-name 指定官方全名。")
    if not args.discover and not target and not target_name:
        raise ValueError("请指定 --series、--series-name 或 --discover。")
    if target_name and not normalize(target_name):
        raise ValueError("--series-name 不能为空。")
    terms = build_queries(args.city, args.area or [], load_json(AREAS_FILE, {}))
    own_client = client is None
    if own_client:
        client = McdClient()
    try:
        stores = search_stores(client, args.city, terms)
        stores_to_check = stores[:args.max_stores]
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures = [pool.submit(search_one, client, s, target, target_name, args.toy_code, args.at, args.discover) for s in stores_to_check]
            processed = [f.result() for f in futures]
        total = len(stores)
        checked = len(processed)
        matched = [r for r, _, _ in processed if r["status"] == "matched"]
        unknown = sum(1 for r, _, _ in processed if r["status"] == "unknown")
        selected = [r for r, _, _ in processed]
        available: dict[str, dict] = {}
        for _, series_list, _ in processed:
            for series in series_list:
                item = available.setdefault(series["code"], {**series, "stores": []})
                for store_code in series["stores"]:
                    if store_code not in item["stores"]:
                        item["stores"].append(store_code)
        if args.discover:
            # 用玩具编码查询系列参考图，便于宿主进行图片比对。
            for item in available.values():
                if not item.get("stores"):
                    continue
                try:
                    image_data = get_data(client.call("query-meal-detail", detail_args(item["stores"][0], item["code"], args.at)))
                    item["image"] = image_data.get("image") or item.get("image")
                except McdError:
                    item["image_note"] = "官方系列参考图获取未完成。"
        return {"query": {"city": args.city, "areas": terms, "series_id": target.get("id") if target else None,
                          "series_name": target.get("name") if target else target_name, "at": args.at,
                          "menu_type": "预约菜单" if args.at else "当前菜单"},
                "checked_at": local_now(), "mode": "live",
                "coverage": {"discovered": total, "checked": checked, "matched": len(matched),
                             "failed": sum(1 for _, _, err in processed if err), "unknown": unknown},
                "stores": selected if (target or target_name) else [r for r, _, _ in processed[:args.max_stores]],
                "available_series": list(available.values()) if args.discover else [],
                "errors": ([{"message": "部分门店餐品详情查询失败，结果可能不完整。"}]
                           if any(err for _, _, err in processed) else [])}
    finally:
        if own_client:
            client.__exit__(None, None, None)


def render_text(result: dict) -> str:
    q, c = result["query"], result["coverage"]
    lines = [f"麦麦寻玩｜{q['city']}｜{q.get('series_name') or '实时玩具系列发现'}",
             f"查询时间：{result['checked_at']}（北京时间）",
             f"门店发现 {c['discovered']} 家，检查 {c['checked']} 家，匹配 {c['matched']} 家，待确认 {c['unknown']} 家，查询有失败 {c['failed']} 家。"]
    if q.get("at"):
        lines.append(f"菜单时段：预约菜单，预计到店 {q['at']}")
    else:
        lines.append("菜单时段：当前菜单")
    for store in result["stores"]:
        status_name = {"matched": "已匹配", "not_matched": "未匹配", "unknown": "待确认", "failed": "查询失败"}.get(store["status"], store["status"])
        lines.append(f"\n{store['name']}（{store['store_code']}）｜{store['address']}｜{status_name}")
        if store.get("note"):
            lines.append("  " + store["note"])
        for match in store["matches"]:
            price = f"¥{match['menu_price']}" if match.get("menu_price") is not None else "价格未提供"
            lines.append(f"  {match['meal_name']} {price} → {match['toy_name']} [{match['toy_code']}]")
    if result.get("available_series"):
        lines.append("\n实时发现的玩具系列：")
        for item in result["available_series"]:
            lines.append(f"  {item['name']} [{item['code']}]，门店 {', '.join(item['stores'])}")
    if not result["stores"] and not result.get("available_series"):
        lines.append("本次搜索未发现门店，可调整区域后继续查询。")
    for error in result.get("errors", []):
        lines.append(f"提示：{error['message']}")
    return "\n".join(lines)


def doctor() -> dict:
    try:
        with McdClient() as client:
            # 连接检查只输出使用到的工具名称。
            init_result = client.initialize() if callable(getattr(client, "initialize", None)) else None
            tools = client.list_tools() if callable(getattr(client, "list_tools", None)) else None
        allowed = {"query-nearby-stores", "query-meals", "query-meal-detail"}
        tool_names = sorted(t.get("name", "") for t in (tools or [])
                            if isinstance(t, dict) and t.get("name") in allowed)
        if set(tool_names) != allowed:
            return {"status": "error", "message": "已连接服务，但查询所需工具不完整。"}
        return {"status": "ok", "message": "麦当劳只读接口连接正常。",
                "initialize": bool(init_result is not False), "tools": tool_names}
    except Exception as exc:
        message = exc.message if isinstance(exc, McdError) else f"接口检查失败：{type(exc).__name__}"
        return {"status": "error", "message": message}


class ChineseParser(argparse.ArgumentParser):
    def format_help(self) -> str:
        return super().format_help().replace("usage: ", "用法：", 1)

    def format_usage(self) -> str:
        return super().format_usage().replace("usage: ", "用法：", 1)

    def error(self, message: str) -> None:
        self.print_usage(sys.stderr)
        self.exit(2, f"错误：{message}\n")


def make_parser() -> argparse.ArgumentParser:
    p = ChineseParser(prog="麦麦寻玩", usage="麦麦寻玩 [选项]", add_help=False,
                                description="麦麦寻玩：查找指定玩具系列的门店与套餐。")
    p._optionals.title = "选项"
    p.add_argument("-h", "--help", action="help", help="显示此帮助并退出")
    p.add_argument("--series", help="本地图鉴中的系列 ID、名称或别名")
    p.add_argument("--series-name", help="指定官方完整系列名，按完整名称匹配")
    p.add_argument("--toy-code", help="玩具官方编码，可与 --series-name 配合")
    p.add_argument("--discover", action="store_true", help="发现门店当前可见的玩具系列")
    p.add_argument("--city", help="城市全名，例如南京市")
    p.add_argument("--area", action="append", default=[], help="搜索区域；可重复指定，传入后只搜索这些区域")
    p.add_argument("--max-stores", type=int, default=10, help="最多检查的门店数（1..30，默认10）")
    p.add_argument("--workers", type=int, default=3, help="并发数（1..4，默认3）")
    p.add_argument("--at", type=parse_at, help="预约时间，格式：YYYY-MM-DD HH:MM")
    p.add_argument("--format", choices=("json", "text"), default="text", help="输出格式（默认text）")
    p.add_argument("--output", help="结果文件路径")
    p.add_argument("--list-series", action="store_true", help="列出本地图鉴系列")
    p.add_argument("--doctor", action="store_true", help="检查接口连接和只读工具白名单")
    return p


def main(argv: list[str] | None = None) -> int:
    parser = make_parser()
    args = parser.parse_args(argv)
    if args.list_series:
        entries = load_series()
        output = "\n".join(f"{s.get('name')} [{s.get('id')}]（别名：{'、'.join(s.get('aliases', []))}）" for s in entries) or "本地图鉴暂无系列。"
        print(output)
        return 0
    if args.doctor:
        result = doctor()
        print(json.dumps(result, ensure_ascii=False, indent=2) if args.format == "json" else result["message"])
        return 0 if result["status"] == "ok" else 2
    if not args.city:
        parser.error("--city 必填。")
    if not 1 <= args.max_stores <= 30:
        parser.error("--max-stores 范围为 1..30。")
    if not 1 <= args.workers <= 4:
        parser.error("--workers 范围为 1..4。")
    try:
        result = run(args)
    except (ValueError, McdError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2
    output = json.dumps(result, ensure_ascii=False, indent=2) if args.format == "json" else render_text(result)
    if args.output:
        Path(args.output).write_text(output + "\n", encoding="utf-8")
    else:
        print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

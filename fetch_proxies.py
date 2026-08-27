#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""抓取 proxy-get-urls.txt 中各 API 的代理列表，去重后写入 proxies.txt。

兼容两种返回格式：
- JSON（proxy_pool 风格，含 "proxy"/"ip"/"port" 字段或纯字符串列表）
- 纯文本（每行 ip:port 或 user:pass@ip:port）
"""
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

BASE_DIR = Path(__file__).resolve().parent
URLS_FILE = BASE_DIR / "proxy-get-urls.txt"
OUT_FILE = BASE_DIR / "proxies.txt"
TIMEOUT = 8
WORKERS = 30
RETRIES = 2
USER_AGENT = "Mozilla/5.0 (compatible; proxy-fetcher/1.0)"

# 匹配 [user:pass@]ip:port
PROXY_RE = re.compile(r"(?:[^\s@/:]+(?::[^\s@/:]+)?@)?\d{1,3}(?:\.\d{1,3}){3}:\d{2,5}")
PORT_RE = re.compile(r"^(?:[^\s@/:]+(?::[^\s@/:]+)?@)?(\d{1,3}(?:\.\d{1,3}){3}):(\d{2,5})$")


def fetch(url: str) -> str | None:
    """GET 请求，失败重试，返回响应文本。"""
    for _ in range(RETRIES):
        try:
            req = Request(url, headers={"User-Agent": USER_AGENT})
            with urlopen(req, timeout=TIMEOUT) as resp:
                return resp.read().decode("utf-8", "replace")
        except (HTTPError, URLError, TimeoutError, OSError):
            continue
    return None


def extract_text(text: str, out: set[str]) -> None:
    """从任意文本中提取 ip:port（含可选 user:pass@ 前缀）。"""
    for m in PROXY_RE.finditer(text):
        addr = m.group(0)
        if PORT_RE.match(addr):
            out.add(addr)


def extract_json(obj, out: set[str]) -> None:
    """递归提取 JSON 中的代理字段。"""
    if isinstance(obj, dict):
        proxy = obj.get("proxy") or obj.get("host") or obj.get("ip")
        if isinstance(proxy, str):
            extract_text(proxy, out)
        elif isinstance(proxy, (dict, list)):
            extract_json(proxy, out)
        port = obj.get("port")
        if isinstance(proxy, str) and isinstance(port, (int, str)):
            extract_text(f"{proxy}:{port}", out)
        for v in obj.values():
            if isinstance(v, (dict, list)):
                extract_json(v, out)
    elif isinstance(obj, list):
        for item in obj:
            extract_json(item, out)
    elif isinstance(obj, str):
        extract_text(obj, out)


def parse(body: str, out: set[str]) -> None:
    """按 JSON 优先、纯文本兜底解析响应。"""
    try:
        data = json.loads(body)
        extract_json(data, out)
    except (json.JSONDecodeError, TypeError):
        extract_text(body, out)


def main() -> int:
    urls = [l.strip() for l in URLS_FILE.read_text().splitlines() if l.strip()]
    if not urls:
        print(f"[!] {URLS_FILE} 为空", file=sys.stderr)
        return 1

    print(f"[*] 待抓取 API: {len(urls)} 个")
    proxies: set[str] = set()
    raw_total = 0
    ok_count = 0
    failed: list[str] = []

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = {pool.submit(fetch, u): u for u in urls}
        for fut in as_completed(futures):
            url = futures[fut]
            try:
                body = fut.result()
            except Exception:
                body = None
            if body is None:
                failed.append(url)
                continue
            before = len(proxies)
            parse(body, proxies)
            raw_total += len(proxies) - before
            if len(proxies) > before:
                ok_count += 1
            else:
                failed.append(url)

    result = sorted(proxies)
    OUT_FILE.write_text("\n".join(result) + "\n")

    print(f"[*] 成功获取代理的 API: {ok_count}/{len(urls)}")
    print(f"[*] 抓取条目总数(去重前): {raw_total}")
    print(f"[*] 去重后代理数量: {len(result)}")
    print(f"[*] 输出文件: {OUT_FILE}")
    if failed:
        print(f"[!] 无有效返回的 API: {len(failed)} 个，已跳过")
    return 0


if __name__ == "__main__":
    sys.exit(main())

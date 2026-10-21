#!/usr/bin/env python3
"""命令行版:python3 check.py [自定义参照域名]

在本机终端里跑一遍与网页相同的探针并打印表格。
注意:如果代理只接管浏览器(不是 TUN/系统级),终端结果不代表浏览器;
此时以 index.html 在浏览器里的结果为准。"""
import json
import random
import re
import string
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

TIMEOUT = 12
UA = {"User-Agent": "Mozilla/5.0"}
GEO_CACHE = {}
GEO_DEGRADED = False

INTL_DOMAINS = [
    ("www.cloudflare.com", "国际 · 云厂商"),
    ("chatgpt.com", "国际 AI"),
    ("openai.com", "国际 AI"),
]


def http_get(url, method="GET"):
    req = urllib.request.Request(url, headers=UA, method=method)
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        body = b"" if method == "HEAD" else r.read()
        return r.status, dict(r.headers), body, int((time.time() - t0) * 1000)


def jsonp(url):
    status, _, body, ms = http_get(url)
    m = re.search(rb"\((.*)\)\s*$", body, re.S)
    if not m:
        raise RuntimeError("JSONP 解析失败")
    return json.loads(m.group(1)), ms


def probe_alibaba():
    rand = f"{int(time.time() * 1000)}-{''.join(random.choices(string.ascii_lowercase, k=16))}"
    d, _ = jsonp(f"https://{rand}.dns-detect.alicdn.com/api/detect/DescribeDNSLookup?cb=x")
    content = d["content"]
    return {"ip": content["localIp"], "cc": (content.get("ipCountry") or "").upper()}


def probe_tencent():
    d, _ = jsonp("https://r.inews.qq.com/api/ip2city?otype=jsonp&callback=x")
    if d.get("ret") != 0 or not d.get("ip"):
        raise RuntimeError(d.get("errMsg") or "返回异常")
    geo = " ".join(x for x in [d.get("country"), d.get("province"), d.get("city"), d.get("isp")] if x)
    return {"ip": d["ip"], "geo": geo}


def probe_netease():
    status, headers, _, _ = http_get(
        "https://necaptcha.nosdn.127.net/ab7f4275c1744aa28e0a8f3a1c58c532.png", method="HEAD")
    if status != 200:
        raise RuntimeError(f"HTTP {status}")
    ip = headers.get("cdn-user-ip")
    if not ip:
        raise RuntimeError("没读到 cdn-user-ip")
    return {"ip": ip}


def probe_cf_trace(domain):
    status, _, body, ms = http_get(f"https://{domain}/cdn-cgi/trace")
    if status != 200:
        raise RuntimeError(f"HTTP {status}")
    kv = dict(line.split("=", 1) for line in body.decode().splitlines() if "=" in line)
    if "ip" not in kv:
        raise RuntimeError("trace 无 ip 字段")
    return {"ip": kv["ip"], "cc": (kv.get("loc") or "").upper(), "ms": ms}


def probe_muse_reach():
    # 记到响应头到达为止,与浏览器 fetch 的口径一致。
    # 终端版每次新建连接,拿不到复用连接值,因此只报首请求。
    url = f"https://muse.ai/favicon.ico?_={int(time.time() * 1000)}"
    req = urllib.request.Request(url, headers=UA)
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        ms = int((time.time() - t0) * 1000)
        status = r.status
    if status != 200:
        raise RuntimeError(f"HTTP {status}")
    return {"ms": ms}


def cc_emoji(cc):
    if not cc or len(cc) != 2:
        return ""
    return "".join(chr(127397 + ord(c)) for c in cc.upper())


def geo_of(ip, cc=""):
    global GEO_DEGRADED
    if not ip:
        return ""
    if ip in GEO_CACHE:
        return GEO_CACHE[ip]
    try:
        _, _, body, _ = http_get(f"https://ipwho.is/{ip}?lang=en")
        d = json.loads(body)
        if d.get("success"):
            parts = " ".join(x for x in [d.get("country"), d.get("region"), d.get("city")] if x)
            conn = d.get("connection") or {}
            isp = conn.get("isp") or conn.get("org") or ""
            flag = (d.get("flag") or {}).get("emoji") or cc_emoji(cc or d.get("country_code"))
            text = f"{flag} {parts}".strip() + (f" · {isp}" if isp else "")
            GEO_CACHE[ip] = text
            return text
    except Exception:
        pass
    GEO_DEGRADED = True
    return f"{cc_emoji(cc)} {cc}（仅国家）" if cc else "—"


def normalize_host(value):
    host = value.strip().lower()
    host = re.sub(r"^https?://", "", host)
    host = re.sub(r"/.*$", "", host)
    host = re.sub(r":\d+$", "", host)
    if not re.fullmatch(r"[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+", host):
        return None
    return host


def most_common(values):
    counts = {}
    for v in values:
        counts[v] = counts.get(v, 0) + 1
    ordered = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)
    if not ordered:
        return None, False
    tied = len(ordered) > 1 and ordered[0][1] == ordered[1][1]
    return ordered[0][0], tied


def run(fn):
    try:
        return {"ok": True, "data": fn()}
    except Exception as e:
        return {"ok": False, "err": str(e)}


def main():
    custom = None
    if len(sys.argv) > 1:
        custom = normalize_host(sys.argv[1])
        if not custom:
            print(f"自定义参照域名格式不对:{sys.argv[1]}(示例:example.com)")
            return 1

    domestic_jobs = [
        ("阿里巴巴", probe_alibaba),
        ("腾讯", probe_tencent),
        ("网易", probe_netease),
    ]

    with ThreadPoolExecutor(max_workers=8) as pool:
        domestic_f = [(name, pool.submit(run, fn)) for name, fn in domestic_jobs]
        reach_f = pool.submit(run, probe_muse_reach)
        refer_domain = custom or "claude.ai"
        refer_f = pool.submit(run, lambda: probe_cf_trace(refer_domain))
        intl_f = [(name, tag, pool.submit(run, lambda n=name: probe_cf_trace(n)))
                  for name, tag in INTL_DOMAINS]

    rows = []  # (name, tag, ip, geo, note)
    domestic_ips = []

    print("国内直连参照:")
    for name, fut in domestic_f:
        res = fut.result()
        if res["ok"]:
            d = res["data"]
            ip = d["ip"]
            geo = d.get("geo") or geo_of(ip, d.get("cc", ""))
            domestic_ips.append(ip)
            rows.append((name, "国内", ip, geo, ""))
            print(f"  ok   {name:<12} {ip}")
        else:
            rows.append((name, "国内", "-", "", f"获取失败：{res['err']}"))
            print(f"  fail {name:<12} {res['err']}")

    print("\nmuse.ai 专区:")
    reach = reach_f.result()
    if reach["ok"]:
        reach_ms = reach["data"]["ms"]
        print(f"  ok   muse.ai 可达，首请求 {reach_ms} ms（含连接建立，非 ICMP）")
    else:
        reach_ms = None
        print(f"  fail muse.ai 不可达：{reach['err']}")

    refer = refer_f.result()
    refer_ip = None
    if refer["ok"]:
        d = refer["data"]
        refer_ip = d["ip"]
        geo = geo_of(refer_ip, d.get("cc", ""))
        rows.append((refer_domain, "参考站", refer_ip, geo, ""))
        print(f"  ok   {refer_domain}(参考站) {refer_ip}")
    else:
        rows.append((refer_domain, "参考站", "-", "", f"获取失败：{refer['err']}"))
        print(f"  fail {refer_domain}(参考站)：{refer['err']}")

    print("\n国际 / AI 出口参照:")
    intl_ips = []
    for name, tag, fut in intl_f:
        res = fut.result()
        if res["ok"]:
            d = res["data"]
            ip = d["ip"]
            intl_ips.append(ip)
            rows.append((name, tag, ip, geo_of(ip, d.get("cc", "")), ""))
            print(f"  ok   {name:<20} {ip}")
        else:
            rows.append((name, tag, "-", "", f"获取失败：{res['err']}"))
            print(f"  fail {name:<20} {res['err']}")

    print("\n" + "=" * 96)
    print(f"{'Website':<34}{'IP':<22}Geolocation")
    print("-" * 96)
    for name, tag, ip, geo, note in rows:
        print(f"{(name + ' [' + tag + ']'):<34}{ip:<22}{geo or note}")
    print("=" * 96)

    direct_ip, tie = most_common(domestic_ips)
    all_ips = domestic_ips + intl_ips + ([refer_ip] if refer_ip else [])
    reach_text = (f"muse.ai 本站首请求 {reach_ms} ms 可达（HTTP 耗时，含连接建立，非 ICMP）。"
                  if reach_ms is not None else "muse.ai 本站不可达。")

    print("\n判定:")
    if len(all_ips) >= 3 and len(set(all_ips)) == 1:
        print(f"  所有探针同一出口 IP：{all_ips[0]}，无法区分(可能全局代理或未启用代理)")
        print("  请切到规则分流模式后重测，或查看代理客户端的 Connections 日志。")
    elif refer_ip and direct_ip:
        if refer_ip == direct_ip:
            print(f"  muse.ai 大概率直连（国内参照 IP 与参考站 IP 都是 {direct_ip}）")
        else:
            print(f"  muse.ai 大概率走代理：直连 IP {direct_ip}，参考站出口 IP {refer_ip}")
        print("  注意：参考站与 muse.ai 的分流规则可能不同，100% 确认请看代理客户端日志。")
    elif refer_ip:
        print(f"  参考站出口 IP：{refer_ip}，但国内参照缺失，无法对比")
    elif direct_ip:
        print(f"  国内直连 IP：{direct_ip}，但国外探针全失败，无法判定")
    else:
        print("  参照数据不足，无法判定")

    if tie:
        print("  注意：国内探针给出的 IP 不一致，直连 IP 只是出现次数最多的一个。")
    if not reach_ms:
        print("  另：muse.ai 本站不可达，请检查该域名是否被单独拦截。")
    if GEO_DEGRADED:
        print("  另：归属地查询被限流或失败，部分行只显示国家代码或「—」。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

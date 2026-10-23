#!/usr/bin/env python3
"""One-shot discovery probe for candidate official sources.

For each candidate: GET the entry page, look for <link rel="alternate"> RSS/Atom
declarations, then GET up to a few candidate feed URLs. Records status, content type,
feed parseability, item count, latest date and median body length. Read-only: reads at
most 400KB per response and saves none of it.
"""
import json, re, statistics, sys, html, urllib.request, urllib.error, socket
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
import xml.etree.ElementTree as ET

UA = "OpportunityRadar/1.0 (local personal research; feed endpoint verification; contact: local user)"
TIMEOUT = 20
MAXBYTES = 400_000

CANDIDATES = [
    ("cn-gov", "中国政府网", "https://www.gov.cn/", []),
    ("cn-stats", "国家统计局", "https://www.stats.gov.cn/", []),
    ("cn-pbc", "中国人民银行", "http://www.pbc.gov.cn/", []),
    ("cn-mof", "财政部", "https://www.mof.gov.cn/", []),
    ("cn-ndrc", "国家发展改革委", "https://www.ndrc.gov.cn/", []),
    ("cn-miit", "工业和信息化部", "https://www.miit.gov.cn/", []),
    ("cn-mofcom", "商务部", "https://www.mofcom.gov.cn/", []),
    ("cn-customs", "海关总署", "http://www.customs.gov.cn/", []),
    ("cn-nea", "国家能源局", "https://www.nea.gov.cn/", []),
    ("cn-samr", "国家市场监督管理总局", "https://www.samr.gov.cn/", []),
    ("us-bea", "BEA", "https://www.bea.gov/", ["https://www.bea.gov/news/rss"]),
    ("us-bls", "BLS", "https://www.bls.gov/", ["https://www.bls.gov/feed/bls_latest.rss"]),
    ("us-census", "Census Bureau", "https://www.census.gov/", [
        "https://www.census.gov/newsroom/press-releases.xml",
        "https://www.census.gov/newsroom/rss/newsroom.xml"]),
    ("us-fed", "Federal Reserve", "https://www.federalreserve.gov/", [
        "https://www.federalreserve.gov/feeds/press_all.xml"]),
    ("fred", "FRED", "https://fred.stlouisfed.org/", []),
    ("eurostat", "Eurostat", "https://ec.europa.eu/eurostat/", []),
    ("uk-ons", "UK ONS", "https://www.ons.gov.uk/", [
        "https://www.ons.gov.uk/releasecalendar?rss",
        "https://www.ons.gov.uk/rss"]),
    ("imf", "IMF", "https://www.imf.org/en/Publications", []),
    ("worldbank", "World Bank", "https://www.worldbank.org/en/research", []),
    ("oecd", "OECD", "https://www.oecd.org/en/publications.html", []),
    ("reuters", "Reuters", "https://www.reuters.com/", []),
    ("ap", "AP", "https://apnews.com/", []),
    ("afp", "AFP", "https://www.afp.com/", []),
    ("bbc", "BBC News", "https://www.bbc.com/news", ["https://feeds.bbci.co.uk/news/rss.xml"]),
    ("xinhua", "新华网", "https://www.news.cn/", []),
    ("nyt", "NYT", "https://www.nytimes.com/", [
        "https://rss.nytimes.com/services/xml/rss/nyt/HomePage.xml"]),
]

def fetch(url):
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept": "application/rss+xml, application/atom+xml, application/xml, text/html;q=0.9, */*;q=0.8",
    })
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            body = r.read(MAXBYTES)
            return {"status": r.status, "final_url": r.geturl(),
                    "ctype": r.headers.get("Content-Type", ""), "body": body}
    except urllib.error.HTTPError as e:
        return {"status": e.code, "final_url": url,
                "ctype": e.headers.get("Content-Type", "") if e.headers else "", "body": b""}
    except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError, OSError) as e:
        return {"status": 0, "final_url": url, "ctype": "", "body": b"", "error": type(e).__name__}

LINK_RE = re.compile(rb"<link[^>]+type=[\"'](application/(?:rss|atom)\+xml)[\"'][^>]*>", re.I)
HREF_RE = re.compile(rb"href=[\"']([^\"']+)[\"']", re.I)
ANCHOR_RE = re.compile(rb"<a[^>]+href=[\"']([^\"']+)[\"'][^>]*>[^<]{0,40}(?:rss|feed|xml)", re.I)

def discover(entry_html, base):
    from urllib.parse import urljoin
    found = []
    for m in LINK_RE.finditer(entry_html):
        h = HREF_RE.search(m.group(0))
        if h:
            found.append(urljoin(base, h.group(1).decode("utf-8", "replace")))
    for m in ANCHOR_RE.finditer(entry_html):
        found.append(urljoin(base, m.group(1).decode("utf-8", "replace")))
    out = []
    for u in found:
        u = u.split("#")[0]
        if u.startswith("http") and u not in out:
            out.append(u)
    return out[:6]

def strip_tags(s):
    s = re.sub(r"<[^>]+>", " ", s)
    s = html.unescape(s)
    return re.sub(r"\s+", " ", s).strip()

def parse_feed(body):
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        return None
    tag = root.tag.lower()
    items = []
    if tag.endswith("rss") or tag.endswith("rdf"):
        items = [it for it in root.iter() if it.tag.lower().endswith("item")]
    elif tag.endswith("feed"):
        items = [it for it in root.iter() if it.tag.lower().endswith("entry")]
    else:
        return None
    if not items:
        return {"items": 0, "latest": "", "median": 0, "empty": 0, "root": tag}
    bodies, dates = [], []
    for it in items:
        text, date = "", ""
        for ch in it:
            t = ch.tag.lower()
            if t.endswith("encoded") or t.endswith("content") or t.endswith("summary") or t.endswith("description"):
                text += " " + strip_tags(ch.text or "")
            elif t.endswith("pubdate") or t.endswith("updated") or t.endswith("published") or t.endswith("date"):
                date = date or (ch.text or "").strip()
        bodies.append(len(text.strip()))
        if date:
            dates.append(date)
    return {"items": len(items), "latest": max(dates) if dates else "",
            "median": int(statistics.median(bodies)) if bodies else 0,
            "empty": sum(1 for b in bodies if b < 50), "root": tag}

def check_feed(url):
    r = fetch(url)
    res = {"url": url, "http": r["status"], "final_url": r["final_url"], "ctype": r["ctype"]}
    if r["status"] == 200 and r["body"]:
        p = parse_feed(r["body"])
        if p:
            res.update({"feed_status": "verified_feed" if p["items"] else "xml_no_items"})
            res.update(p)
        else:
            res["feed_status"] = "not_a_feed"
    else:
        st = r["status"]
        res["feed_status"] = "unreachable" if st == 0 else ("blocked" if st in (401, 403, 429) else "http_%s" % st)
    return res

def probe(c):
    sid, name, entry, feeds = c
    out = {"source_id": sid, "name": name, "entry": entry}
    e = fetch(entry)
    out["entry_http"] = e["status"]
    out["entry_final"] = e["final_url"]
    out["entry_ctype"] = e["ctype"]
    out["entry_error"] = e.get("error", "")
    discovered = []
    if e["status"] == 200 and b"<" in e["body"][:2000]:
        discovered = discover(e["body"], e["final_url"])
    out["discovered"] = discovered
    urls = []
    for u in list(feeds) + discovered:
        if u not in urls:
            urls.append(u)
    out["feeds"] = [check_feed(u) for u in urls[:6]]
    best = next((f for f in out["feeds"] if f.get("feed_status") == "verified_feed"), None)
    out["verdict"] = "verified_feed" if best else ("entry_only" if e["status"] == 200 else "entry_unreachable")
    if best:
        out["best_feed"] = {k: best.get(k) for k in ("url", "http", "items", "median", "latest", "empty")}
    return out

def main():
    with ThreadPoolExecutor(max_workers=5) as ex:
        results = list(ex.map(probe, CANDIDATES))
    for r in results:
        print(json.dumps({k: v for k, v in r.items() if k != "feeds"}, ensure_ascii=False))
        for f in r["feeds"]:
            print("    ", json.dumps(f, ensure_ascii=False))
    with open(sys.argv[1], "w", encoding="utf-8") as fh:
        json.dump({"probed_at": datetime.now(timezone.utc).isoformat(), "results": results},
                  fh, ensure_ascii=False, indent=1)

main()

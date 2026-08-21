#!/usr/bin/env python3
"""
National Border Targeting Centre Brief - local desktop server.

Runs entirely on the user's PC using only the Python standard library.
  - Serves the dashboard (index.html) at http://localhost:8770
  - /api/refresh (GET or POST) pulls current open-source reporting per focus
    area from Google News RSS, fetched server-side (no browser CORS wall, no
    JavaScript rendering needed). POST may carry custom "areas of interest".
  - /api/assess writes an intelligence assessment when an Anthropic API key is
    present (env ANTHROPIC_API_KEY or a file apikey.txt next to this script).

No third-party packages required. Just Python 3.8+.
"""

import http.server
import socketserver
import json
import os
import re
import ssl
import sys
import threading
import webbrowser
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

PORT = 8770
HERE = os.path.dirname(os.path.abspath(__file__))
INDEX = os.path.join(HERE, "index.html")
DEFAULT_MODEL = "claude-haiku-4-5-20251001"

SSL_CTX = ssl.create_default_context()
try:
    SSL_CTX.check_hostname = False
    SSL_CTX.verify_mode = ssl.CERT_NONE
except Exception:
    pass

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"

# Focus areas follow the PRA and MRA frameworks: (query, sub-category label).
QUERIES = {
    "a": [  # People Movement (PRA Focal Area 1)
        ("Beitbridge OR Lebombo OR Maseru border illegal crossing migrants South Africa", "Human Smuggling"),
        ("South Africa migrant smuggling deported repatriated border", "Human Smuggling"),
        ("South Africa human trafficking arrest rescue victims syndicate", "Trafficking in Persons"),
        ("South Africa passport OR permit OR visa fraud Home Affairs", "Travel Documentation Fraud"),
        ("South Africa border health screening OR communicable disease port of entry", "Health Risks"),
        ("Africa irregular migration smuggling IOM OR UNHCR border", "Human Smuggling"),
    ],
    "b": [  # Regulated Goods (PRA Focal Area 2)
        ("South Africa foot-and-mouth OR plant health OR agriculture import ban border", "Agriculture"),
        ("South Africa veterinary OR animal disease import control border", "Veterinary Controls"),
        ("South Africa fisheries permit OR DFFE compliance quota", "Fisheries"),
        ("South Africa CITES OR e-waste OR hazardous waste import environment", "Environment"),
        ("South Africa illegal timber OR forestry import export", "Forestry"),
        ("South Africa contaminated food OR counterfeit medicine port health", "Health Desk"),
    ],
    "c": [  # Cross-Border Smuggling (PRA Focal Area 3)
        ("South Africa narcotics mandrax methamphetamine cocaine bust seizure border", "Narcotics"),
        ("SARS illicit cigarettes tobacco seizure South Africa", "Tobacco"),
        ("South Africa fuel smuggling adulterated diesel Maputo corridor", "Fuel"),
        ("South Africa counterfeit goods seizure customs", "Intellectual Property Rights"),
        ("South Africa stolen vehicles smuggled Mozambique Zimbabwe recovered", "Vehicles"),
        ("South Africa illegal firearms ammunition explosives smuggling border", "Small Arms & Explosives"),
        ("South Africa gold smuggling precious metals OR Tambo airport", "Gold & Precious Metals"),
        ("South Africa scrap metal illegal export seizure", "Scrap Metals & Steel"),
        ("South Africa illicit liquor OR alcohol smuggling seizure", "Liquor"),
        ("South Africa rhino horn OR pangolin OR ivory wildlife trafficking", "Illegal Wildlife Trafficking"),
        ("South Africa dual-use OR strategic trade goods export control", "Strategic Trade Control"),
    ],
    "d": [  # Coastal & Maritime (MRA Focal Areas 1-5)
        ("South Africa abalone poaching seizure arrest Western Cape", "Marine Living Resources"),
        ("South Africa rock lobster OR line-fish poaching syndicate", "Marine Living Resources"),
        ("South Africa illegal fishing trawler EEZ AIS foreign vessel", "IUU Fishing / Dark Vessels"),
        ("South Africa navy Operation Corona maritime drug interdiction", "Maritime Contraband"),
        ("South Africa illicit bunkering Algoa Bay ship-to-ship", "Blue Economy & Infrastructure"),
        ("South Africa migrant boat sea rescue coast smuggling", "Irregular Human Movement (Sea)"),
        ("South Africa maritime piracy OR vessel hijacking Mozambique channel", "Vessel & Sovereignty"),
    ],
    "e": [  # Cross-Cutting Enablers
        ("South Africa border official corruption arrest bribe", "Corruption & Insider Facilitation"),
        ("SARS customs official corruption bribery clearing agent", "Corruption & Insider Facilitation"),
        ("South Africa Home Affairs corruption visa permit syndicate SIU", "Document & Identity Systems Abuse"),
        ("Interpol OR Europol Africa organised crime network arrests", "Transnational Organised-Crime Networks"),
    ],
}

# General daily news: politics, crime, intelligence, national security. SA-weighted.
NEWS_QUERIES = [
    ("South Africa politics government parliament cabinet", "Politics"),
    ("South Africa crime police arrest investigation", "Crime"),
    ("South Africa state security OR intelligence OR national security", "Intelligence & Security"),
    ("South Africa policy law enforcement border security", "National Security"),
]

# Keep the news column serious: drop sport, entertainment and lifestyle.
NEWS_EXCLUDE = [
    "sport", "rugby", "cricket", "soccer", "football", "springbok", "proteas", "bafana",
    "entertainment", "celebrity", "celeb", "music", "movie", "film", "fashion", "lifestyle",
    "recipe", "idols", "concert", "netflix", "box office", "gossip", "showbiz", "horoscope",
    "dating", "award", "trailer", "album", "kardashian", "royal family", "wedding", "fixture",
]

SA_TERMS = [
    "south africa", "s africa", "saps", "sars", "dffe", "home affairs", "hawks", "sanparks",
    "sandf", "transnet", "beitbridge", "lebombo", "maseru", "kosi bay", "durban", "cape town",
    "gauteng", "limpopo", "kwazulu", "mpumalanga", "western cape", "eastern cape", "johannesburg",
    "pretoria", "musina", "gqeberha", "algoa", "richards bay", "saldanha", "free state",
    "news24", "iol", "ewn", "timeslive", "sowetan", "dailymaverick", "sunday world", "sanews",
    "gov.za", "enca", "the citizen", "mail & guardian", "businesstech", "moneyweb", "defenceweb",
]


def http_get(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=timeout, context=SSL_CTX) as r:
        return r.read()


def clean_html(text):
    text = re.sub(r"<[^>]+>", " ", text or "")
    text = text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    text = text.replace("&quot;", '"').replace("&#39;", "'").replace("&nbsp;", " ")
    return re.sub(r"\s+", " ", text).strip()


def fmt_date(pub):
    if not pub:
        return "recent"
    try:
        return parsedate_to_datetime(pub).strftime("%d %b %Y")
    except Exception:
        return "recent"


def sort_key(pub):
    try:
        return parsedate_to_datetime(pub)
    except Exception:
        return datetime(1970, 1, 1, tzinfo=timezone.utc)


def is_sa(item):
    blob = (item.get("headline", "") + " " + item.get("note", "") + " " + item.get("sourceName", "")).lower()
    return any(t in blob for t in SA_TERMS)


def xml_safe(raw):
    txt = raw.decode("utf-8", "replace") if isinstance(raw, (bytes, bytearray)) else raw
    return re.sub(r"&(?!(?:amp|lt|gt|quot|apos|#\d+|#x[0-9a-fA-F]+);)", "&amp;", txt)


def gnews(query):
    url = "https://news.google.com/rss/search?q=" + urllib.parse.quote(query + " when:14d") + "&hl=en-ZA&gl=ZA&ceid=ZA:en"
    root = ET.fromstring(xml_safe(http_get(url)))
    out = []
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        pub = (item.findtext("pubDate") or "").strip()
        src_el = item.find("source")
        source = (src_el.text or "").strip() if src_el is not None else ""
        if not source and " - " in title:
            source = title.rsplit(" - ", 1)[1].strip()
            title = title.rsplit(" - ", 1)[0].strip()
        desc = clean_html(item.findtext("description") or "")
        if desc.lower().startswith(title.lower()[:30]):
            desc = ""
        out.append({"headline": title, "url": link, "date": fmt_date(pub), "_sort": pub, "sourceName": source or "open source", "note": desc[:240]})
    return out


def fetch_one(task):
    area, query, sub = task
    try:
        items = gnews(query)
        for it in items:
            it["sub"] = sub
            it["area"] = area
        return area, items
    except Exception:
        return area, []


def group_items(area, items, is_news=False, cap=12):
    seen = set()
    dedup = []
    for it in items:
        head = it.get("headline", "")
        if not head:
            continue
        low = head.lower()
        if is_news and any(w in low for w in NEWS_EXCLUDE):
            continue
        key = low[:70]
        if key in seen:
            continue
        seen.add(key)
        it["scope"] = "sa" if is_sa(it) else "intl"
        dedup.append(it)
    # South African items first, then international; each block newest-first.
    dedup.sort(key=lambda x: (0 if x["scope"] == "sa" else 1, ), reverse=False)
    sa = [x for x in dedup if x["scope"] == "sa"]
    intl = [x for x in dedup if x["scope"] == "intl"]
    sa.sort(key=lambda x: sort_key(x.get("_sort", "")), reverse=True)
    intl.sort(key=lambda x: sort_key(x.get("_sort", "")), reverse=True)
    ordered = sa + intl
    for it in ordered:
        it.pop("_sort", None)
    return ordered[:cap]


# ---- article summary enrichment (no API key required) ----
ENRICH = True
GOOGLE_HOSTS = ("google.", "gstatic.", "googleusercontent.", "youtube.", "gmail.")


def fetch_html(url, timeout=9):
    return http_get(url, timeout=timeout).decode("utf-8", "replace")


def resolve_real_url(gurl, html):
    try:
        qs = urllib.parse.parse_qs(urllib.parse.urlparse(gurl).query)
        for key in ("url", "continue"):
            vals = qs.get(key) or []
            if vals and not any(h in vals[0] for h in GOOGLE_HOSTS):
                return vals[0]
    except Exception:
        pass
    m = re.search(r"(?:url|continue)=(https?[^&\"'<> ]+)", html)
    if m:
        cand = urllib.parse.unquote(m.group(1))
        if not any(h in cand for h in GOOGLE_HOSTS):
            return cand
    for cand in re.findall(r'href="(https?://[^"]+)"', html):
        if not any(h in cand for h in GOOGLE_HOSTS):
            return cand
    return None


def extract_desc(html):
    pats = [
        r'property=["\']og:description["\'][^>]*content=["\']([^"\']+)',
        r'content=["\']([^"\']+)["\'][^>]*property=["\']og:description["\']',
        r'name=["\']description["\'][^>]*content=["\']([^"\']+)',
        r'name=["\']twitter:description["\'][^>]*content=["\']([^"\']+)',
    ]
    for p in pats:
        m = re.search(p, html, re.I)
        if m:
            t = clean_html(m.group(1))
            if len(t) >= 40:
                return t[:460]
    for para in re.findall(r"<p[^>]*>(.*?)</p>", html, re.S | re.I):
        t = clean_html(para)
        if len(t) >= 80:
            return t[:460]
    return ""


def summarise_item(item):
    try:
        html = fetch_html(item.get("url", ""))
    except Exception:
        return
    real = resolve_real_url(item.get("url", ""), html)
    desc = extract_desc(html)
    if real:
        item["url"] = real
        if not desc:
            try:
                desc = extract_desc(fetch_html(real))
            except Exception:
                desc = ""
    if desc and len(desc) > len(item.get("note", "")):
        item["note"] = desc


def enrich(clusters):
    items = [it for arr in clusters.values() for it in arr]
    if not items:
        return
    with ThreadPoolExecutor(max_workers=12) as ex:
        list(ex.map(summarise_item, items))


def build_brief(custom=None, include_news=True):
    tasks = [(k, q, sub) for k, qs in QUERIES.items() for (q, sub) in qs]
    if include_news:
        tasks += [("news", q, sub) for (q, sub) in NEWS_QUERIES]
    custom = custom or []
    for c in custom:
        q = (c.get("query") or c.get("label") or "").strip()
        label = (c.get("label") or q).strip()
        if q:
            tasks.append(("x", q + " South Africa", label))
    grouped = {}
    with ThreadPoolExecutor(max_workers=8) as ex:
        for area, items in ex.map(fetch_one, tasks):
            grouped.setdefault(area, []).extend(items)
    clusters = {}
    for area, items in grouped.items():
        clusters[area] = group_items(area, items, is_news=(area == "news"), cap=(10 if area == "news" else 12))
    if ENRICH:
        try:
            enrich(clusters)
        except Exception:
            pass
    return {"generatedAt": datetime.now(timezone.utc).isoformat(), "clusters": clusters}


def get_api_key():
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if key:
        return key
    path = os.path.join(HERE, "apikey.txt")
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return f.readline().strip()
        except Exception:
            return ""
    return ""


def build_prompt(product, query, grounding):
    return (
        "You are an intelligence analyst producing a rapid open-source " + product.lower() +
        " for the South African Border Management Authority (BMA), National Border Targeting Centre. "
        "House style: authoritative, plain, direct English, no corporate jargon, no em dashes. "
        "Structure: BLUF (bottom line up front); Key Judgements (3-5 bullets); Modus Operandi / Drivers; "
        "Indicators and Warnings; Intelligence Gaps; Recommended BMA Action. "
        "Where a risk or threat rating is relevant, apply a 5x5 Likelihood x Consequence logic and state the band "
        "(Low, Medium, High, Extreme). State an explicit confidence level (low, moderate or high) with its basis. "
        "Keep the border, port, migration, maritime, smuggling and organised-crime lens. "
        "Do not invent specifics; if the grounding is thin, say so plainly. Under 450 words.\n\n"
        "Question: " + query + "\n\nGrounding from the NBTC Brief:\n" + (grounding or "(none supplied)")
    )


def call_anthropic(product, query, grounding):
    key = get_api_key()
    prompt = build_prompt(product, query, grounding)
    payload = {"model": DEFAULT_MODEL, "max_tokens": 1200, "messages": [{"role": "user", "content": prompt}]}
    data = json.dumps(payload).encode("utf-8")
    headers = {"content-type": "application/json", "x-api-key": key, "anthropic-version": "2023-06-01"}
    req = urllib.request.Request("https://api.anthropic.com/v1/messages", data=data, headers=headers)
    with urllib.request.urlopen(req, timeout=90, context=SSL_CTX) as r:
        j = json.loads(r.read())
    parts = [p.get("text", "") for p in j.get("content", []) if p.get("type") == "text"]
    return "".join(parts)


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def reply(self, code, payload, ctype="application/json"):
        data = payload if isinstance(payload, (bytes, bytearray)) else json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(data)
        except Exception:
            pass

    def read_body(self):
        length = int(self.headers.get("Content-Length", 0) or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            return json.loads(raw.decode("utf-8") or "{}")
        except Exception:
            return {}

    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        if path in ("/", "/index.html"):
            if os.path.exists(INDEX):
                with open(INDEX, "rb") as f:
                    self.reply(200, f.read(), "text/html; charset=utf-8")
            else:
                self.reply(404, {"error": "index.html not found"})
        elif path == "/api/health":
            self.reply(200, {"ok": True, "ai": bool(get_api_key()), "port": PORT})
        elif path == "/api/refresh":
            try:
                self.reply(200, build_brief())
            except Exception as e:
                self.reply(500, {"error": str(e)})
        else:
            self.reply(404, {"error": "not found"})

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        body = self.read_body()
        if path == "/api/refresh":
            try:
                custom = body.get("custom") or []
                include_news = body.get("includeNews", True)
                self.reply(200, build_brief(custom=custom, include_news=include_news))
            except Exception as e:
                self.reply(500, {"error": str(e)})
            return
        if path == "/api/assess":
            if not get_api_key():
                self.reply(501, {"error": "no API key configured"})
                return
            product = body.get("product", "Assessment")
            query = body.get("query", "")
            grounding = body.get("grounding", "")
            try:
                text = call_anthropic(product, query, grounding)
                self.reply(200, {"text": text})
            except Exception as e:
                self.reply(502, {"error": str(e)})
            return
        self.reply(404, {"error": "not found"})


class Server(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def main():
    global PORT
    httpd = None
    for candidate in range(PORT, PORT + 10):
        try:
            httpd = Server(("127.0.0.1", candidate), Handler)
            PORT = candidate
            break
        except OSError:
            continue
    if httpd is None:
        print("Could not bind a local port. Close other copies and try again.")
        sys.exit(1)
    url = "http://localhost:" + str(PORT)
    print("=" * 60)
    print("  National Border Targeting Centre Brief (local app)")
    print("  Running at: " + url)
    print("  AI assessments: " + ("ON" if get_api_key() else "OFF (no API key)"))
    print("  Leave this window open while you use the app.")
    print("  Press Ctrl+C here to stop.")
    print("=" * 60)
    threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()

from __future__ import annotations

import html as html_lib
import ipaddress
import re
import socket
import urllib.parse
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import httpx

USER_AGENT = "BMA-NBTC-Briefing/1.0"
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_REDIRECTS = 4

QUERIES = {
    "a": [
        ("Beitbridge OR Lebombo OR Maseru border illegal crossing migrants South Africa", "Human Smuggling"),
        ("South Africa migrant smuggling deported repatriated border", "Human Smuggling"),
        ("South Africa human trafficking arrest rescue victims syndicate", "Trafficking in Persons"),
        ("South Africa passport OR permit OR visa fraud Home Affairs", "Travel Documentation Fraud"),
        ("South Africa border health screening OR communicable disease port of entry", "Health Risks"),
    ],
    "b": [
        ("South Africa foot-and-mouth OR plant health OR agriculture import ban border", "Agriculture"),
        ("South Africa veterinary OR animal disease import control border", "Veterinary Controls"),
        ("South Africa fisheries permit OR DFFE compliance quota", "Fisheries"),
        ("South Africa CITES OR e-waste OR hazardous waste import environment", "Environment"),
        ("South Africa illegal timber OR forestry import export", "Forestry"),
        ("South Africa contaminated food OR counterfeit medicine port health", "Health Desk"),
    ],
    "c": [
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
    "d": [
        ("South Africa abalone poaching seizure arrest Western Cape", "Marine Living Resources"),
        ("South Africa rock lobster OR line-fish poaching syndicate", "Marine Living Resources"),
        ("South Africa illegal fishing trawler EEZ AIS foreign vessel", "IUU Fishing / Dark Vessels"),
        ("South Africa navy Operation Corona maritime drug interdiction", "Maritime Contraband"),
        ("South Africa illicit bunkering Algoa Bay ship-to-ship", "Blue Economy & Infrastructure"),
        ("South Africa migrant boat sea rescue coast smuggling", "Irregular Human Movement (Sea)"),
        ("South Africa maritime piracy OR vessel hijacking Mozambique channel", "Vessel & Sovereignty"),
    ],
    "e": [
        ("South Africa border official corruption arrest bribe", "Corruption & Insider Facilitation"),
        ("SARS customs official corruption bribery clearing agent", "Corruption & Insider Facilitation"),
        ("South Africa Home Affairs corruption visa permit syndicate SIU", "Document & Identity Systems Abuse"),
        ("Interpol OR Europol Africa organised crime network arrests", "Transnational Organised-Crime Networks"),
    ],
}

NEWS_QUERIES = [
    ("South Africa politics government parliament cabinet", "Politics"),
    ("South Africa crime police arrest investigation", "Crime"),
    ("South Africa state security OR intelligence OR national security", "Intelligence & Security"),
    ("South Africa policy law enforcement border security", "National Security"),
]

NEWS_EXCLUDE = {
    "sport", "rugby", "cricket", "soccer", "football", "springbok", "proteas", "bafana",
    "entertainment", "celebrity", "music", "movie", "film", "fashion", "lifestyle", "recipe",
    "concert", "netflix", "gossip", "horoscope", "wedding", "fixture",
}

SA_TERMS = {
    "south africa", "saps", "sars", "dffe", "home affairs", "hawks", "sanparks", "sandf",
    "transnet", "beitbridge", "lebombo", "maseru", "kosi bay", "durban", "cape town", "gauteng",
    "limpopo", "kwazulu", "mpumalanga", "western cape", "eastern cape", "johannesburg", "pretoria",
    "musina", "gqeberha", "algoa", "richards bay", "saldanha", "free state", "gov.za",
}


class FetchError(RuntimeError):
    pass


def _resolved_addresses(hostname: str) -> set[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    try:
        return {ipaddress.ip_address(item[4][0]) for item in socket.getaddrinfo(hostname, 443, type=socket.SOCK_STREAM)}
    except (OSError, ValueError) as exc:
        raise FetchError("Unable to resolve remote host") from exc


def validate_public_https_url(url: str, allowed_hosts: set[str] | None = None) -> str:
    try:
        parsed = urllib.parse.urlsplit(url)
        if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
                or parsed.port not in {None, 443}):
            raise FetchError("Only public HTTPS URLs are permitted")
        hostname = parsed.hostname.casefold().rstrip(".")
        if allowed_hosts is not None and hostname not in allowed_hosts:
            raise FetchError("Remote host is not permitted")
        addresses = _resolved_addresses(hostname)
        if not addresses or any(not address.is_global for address in addresses):
            raise FetchError("Remote host resolves to a non-public address")
        return urllib.parse.urlunsplit(("https", parsed.netloc, parsed.path or "/", parsed.query, ""))
    except ValueError as exc:
        raise FetchError("Invalid remote URL") from exc


def safe_get(url: str, *, allowed_hosts: set[str] | None = None,
             max_bytes: int = MAX_RESPONSE_BYTES, timeout: float = 15.0,
             client: httpx.Client | None = None) -> bytes:
    owns_client = client is None
    client = client or httpx.Client(
        headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/rss+xml,application/xml;q=0.9,*/*;q=0.1"},
        verify=True,
        follow_redirects=False,
        trust_env=False,
        timeout=httpx.Timeout(timeout),
    )
    current = url
    try:
        for _ in range(MAX_REDIRECTS + 1):
            current = validate_public_https_url(current, allowed_hosts)
            with client.stream("GET", current) as response:
                if response.status_code in {301, 302, 303, 307, 308}:
                    location = response.headers.get("location")
                    if not location:
                        raise FetchError("Remote redirect had no destination")
                    current = urllib.parse.urljoin(current, location)
                    continue
                response.raise_for_status()
                declared = int(response.headers.get("content-length", "0") or 0)
                if declared > max_bytes:
                    raise FetchError("Remote response is too large")
                chunks: list[bytes] = []
                size = 0
                for chunk in response.iter_bytes():
                    size += len(chunk)
                    if size > max_bytes:
                        raise FetchError("Remote response is too large")
                    chunks.append(chunk)
                return b"".join(chunks)
        raise FetchError("Too many remote redirects")
    except httpx.HTTPError as exc:
        raise FetchError("Remote request failed") from exc
    finally:
        if owns_client:
            client.close()


def _clean_html(value: str) -> str:
    text = re.sub(r"<[^>]+>", " ", value or "")
    return re.sub(r"\s+", " ", html_lib.unescape(text)).strip()


def _parse_date(value: str) -> tuple[str, datetime | None]:
    if not value:
        return "recent", None
    try:
        parsed = parsedate_to_datetime(value).astimezone(timezone.utc)
        return parsed.strftime("%d %b %Y"), parsed.replace(tzinfo=None)
    except (TypeError, ValueError, OverflowError):
        return "recent", None


def _scope(item: dict) -> str:
    blob = " ".join(str(item.get(key, "")) for key in ("headline", "summary", "source_name")).casefold()
    return "sa" if any(term in blob for term in SA_TERMS) else "intl"


def fetch_google_news(query: str) -> list[dict]:
    url = "https://news.google.com/rss/search?q=" + urllib.parse.quote(query + " when:14d") + "&hl=en-ZA&gl=ZA&ceid=ZA:en"
    raw = safe_get(url, allowed_hosts={"news.google.com"})
    root = ET.fromstring(raw)
    output = []
    for node in root.iter("item"):
        headline = (node.findtext("title") or "").strip()
        source_node = node.find("source")
        source = (source_node.text or "").strip() if source_node is not None else ""
        if not source and " - " in headline:
            headline, source = [part.strip() for part in headline.rsplit(" - ", 1)]
        published_label, published_at = _parse_date((node.findtext("pubDate") or "").strip())
        source_url = (node.findtext("link") or "").strip()
        parsed_source = urllib.parse.urlsplit(source_url)
        if parsed_source.scheme != "https" or parsed_source.hostname != "news.google.com":
            continue
        item = {
            "headline": headline[:1000],
            "source_url": source_url,
            "source_name": (source or "Open source")[:300],
            "published_label": published_label,
            "published_at": published_at,
            "summary": _clean_html(node.findtext("description") or "")[:1000],
        }
        if item["headline"] and item["source_url"]:
            item["scope"] = _scope(item)
            output.append(item)
    return output


def _fetch_task(task: tuple[str, str, str]) -> tuple[str, str, list[dict], str | None]:
    area, query, subcategory = task
    try:
        return area, subcategory, fetch_google_news(query), None
    except Exception as exc:
        return area, subcategory, [], type(exc).__name__


def build_brief(interests: list[dict]) -> dict[str, list[dict]]:
    tasks = [(area, query, subcategory) for area, values in QUERIES.items() for query, subcategory in values]
    tasks.extend(("news", query, subcategory) for query, subcategory in NEWS_QUERIES)
    tasks.extend(("x", f"{item['query']} South Africa", item["label"]) for item in interests)
    grouped: dict[str, list[dict]] = {key: [] for key in ("a", "b", "c", "d", "e", "news", "x")}
    failures: list[str] = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        for area, subcategory, items, error in pool.map(_fetch_task, tasks):
            if error:
                failures.append(f"{area}:{subcategory}:{error}")
                continue
            for item in items:
                item.update({"area": area, "subcategory": subcategory})
                grouped[area].append(item)
    if failures:
        raise FetchError(f"{len(failures)} source queries failed")
    for area, items in grouped.items():
        seen: set[str] = set()
        filtered = []
        for item in items:
            key = re.sub(r"\W+", " ", item["headline"].casefold()).strip()[:120]
            if not key or key in seen:
                continue
            if area == "news" and any(word in item["headline"].casefold() for word in NEWS_EXCLUDE):
                continue
            seen.add(key)
            filtered.append(item)
        filtered.sort(key=lambda item: (
            item["scope"] != "sa",
            -(item["published_at"].timestamp() if item["published_at"] else 0),
        ))
        grouped[area] = filtered[:10 if area == "news" else 12]
    if not any(grouped.values()):
        raise FetchError("No articles were returned")
    return grouped

import re
from typing import Any

import httpx

from app.config import settings


class WebSearchConfigurationError(RuntimeError):
    pass


class WebSearchUpstreamError(RuntimeError):
    pass


SEARCH_REQUEST_PREFIXES = (
    "\u5e2e\u6211\u67e5\u627e",
    "\u5e2e\u6211\u641c\u7d22",
    "\u5e2e\u6211\u641c",
    "\u5e2e\u6211\u67e5",
    "\u5e2e\u6211\u627e",
    "\u5e2e\u6211\u770b",
    "\u8bf7\u5e2e\u6211\u67e5\u627e",
    "\u8bf7\u5e2e\u6211\u641c\u7d22",
    "\u8bf7\u5e2e\u6211\u641c",
    "\u8bf7\u5e2e\u6211\u67e5",
    "\u8bf7\u5e2e\u6211\u627e",
    "\u8bf7\u5e2e\u6211\u770b",
    "\u5e2e\u5fd9\u67e5\u627e",
    "\u5e2e\u5fd9\u641c\u7d22",
    "\u5e2e\u5fd9\u641c",
    "\u5e2e\u5fd9\u67e5",
    "\u5e2e\u5fd9\u627e",
    "\u5e2e\u5fd9\u770b",
    "\u8bf7\u4f60\u67e5\u627e",
    "\u8bf7\u4f60\u641c\u7d22",
    "\u8bf7\u4f60\u641c",
    "\u8bf7\u4f60\u67e5",
    "\u8bf7\u4f60\u627e",
    "\u8bf7\u4f60\u770b",
    "\u8bf7\u67e5\u627e",
    "\u8bf7\u641c\u7d22",
    "\u8bf7\u641c",
    "\u8bf7\u67e5",
    "\u8bf7\u627e",
    "\u8bf7\u770b",
)

SEARCH_REQUEST_FILLERS = (
    "\u4e00\u4e0b\u5b50",
    "\u4e00\u4e0b",
    "\u4eca\u5929\u7684",
    "\u4eca\u5929",
    "\u4eca\u65e5\u7684",
    "\u4eca\u65e5",
    "\u73b0\u5728\u7684",
    "\u73b0\u5728",
    "\u6700\u65b0\u7684",
)

NEWS_QUERY_HINTS = (
    "\u65b0\u95fb",
    "\u8d44\u8baf",
    "\u8981\u95fb",
    "\u70ed\u70b9",
    "\u5feb\u8baf",
    "news",
)
WEATHER_QUERY_HINTS = (
    "\u5929\u6c14",
    "\u6c14\u6e29",
    "\u964d\u96e8",
    "\u53f0\u98ce",
    "\u9884\u62a5",
    "weather",
)
DOMESTIC_CHINA_NEWS_HINTS = ("\u56fd\u5185", "\u4e2d\u56fd")
NEWS_RESULT_JUNK_TOKENS = (
    "baike.baidu.com",
    "\u767e\u5ea6\u767e\u79d1",
    "zdic.net",
    "\u6c49\u5178",
    "hanyuguoxue",
    "\u9ec4\u5386",
    "huangli",
    "\u5929\u6c14",
    "tianqi",
    "calendar",
    "wannianli",
)
DOMESTIC_NEWS_INCLUDE_DOMAINS = (
    "news.cctv.com",
    "www.people.com.cn",
    "www.news.cn",
    "www.chinanews.com.cn",
    "www.gov.cn",
)
WEATHER_LOCATION_STRIP_TOKENS = (
    "\u5929\u6c14\u600e\u4e48\u6837",
    "\u5929\u6c14\u600e\u6837",
    "\u5929\u6c14\u5982\u4f55",
    "\u5929\u6c14",
    "\u6c14\u6e29",
    "\u964d\u96e8",
    "\u53f0\u98ce",
    "\u9884\u62a5",
    "weather",
    "today",
    "tomorrow",
)
WEATHER_CODE_LABELS = {
    0: "\u6674\u6717",
    1: "\u6674",
    2: "\u5c11\u4e91",
    3: "\u591a\u4e91",
    45: "\u6709\u96fe",
    48: "\u96fe\u51c7",
    51: "\u5c0f\u6bdb\u96e8",
    53: "\u6bdb\u96e8",
    55: "\u5f3a\u6bdb\u96e8",
    56: "\u51bb\u6bdb\u96e8",
    57: "\u5f3a\u51bb\u6bdb\u96e8",
    61: "\u5c0f\u96e8",
    63: "\u4e2d\u96e8",
    65: "\u5927\u96e8",
    66: "\u51bb\u96e8",
    67: "\u5f3a\u51bb\u96e8",
    71: "\u5c0f\u96ea",
    73: "\u4e2d\u96ea",
    75: "\u5927\u96ea",
    77: "\u9635\u96ea",
    80: "\u5c0f\u9635\u96e8",
    81: "\u9635\u96e8",
    82: "\u5f3a\u9635\u96e8",
    85: "\u5c0f\u9635\u96ea",
    86: "\u5f3a\u9635\u96ea",
    95: "\u96f7\u66b4",
    96: "\u96f7\u66b4\u4f34\u5c0f\u51b0\u96f9",
    99: "\u5f3a\u96f7\u66b4\u4f34\u51b0\u96f9",
}


def build_web_search_context(query: str, results: list[dict[str, str]]) -> str:
    lines = ["[Web search results]", f"Query: {query.strip()}"]

    for index, item in enumerate(results, start=1):
        lines.extend(
            [
                "",
                f"{index}. Title: {item['title']}",
                f"   URL: {item['url']}",
                f"   Snippet: {item['snippet']}",
            ]
        )

    if not results:
        lines.extend(["", "No reliable search results were returned."])

    return "\n".join(lines).strip()


def build_search_queries(query: str) -> list[str]:
    raw_query = re.sub(r"\s+", " ", query).strip()
    if not raw_query:
        return []

    normalized_query = normalize_search_query(raw_query)
    candidates: list[str] = []

    if is_news_query(raw_query):
        keyword_query = normalized_query or raw_query
        if keyword_query:
            if is_domestic_china_news_query(raw_query):
                candidates.append("\u4e2d\u56fd\u56fd\u5185\u65b0\u95fb \u6700\u65b0")
                candidates.append("\u4eca\u65e5 \u4e2d\u56fd\u56fd\u5185\u65b0\u95fb")
            candidates.append(ensure_latest_suffix(keyword_query))
            candidates.append(f"\u4eca\u65e5 {keyword_query}".strip())
    elif is_weather_query(raw_query) and normalized_query and normalized_query != raw_query:
        candidates.append(normalized_query)

    if normalized_query and normalized_query != raw_query:
        candidates.append(normalized_query)
    candidates.append(raw_query)

    deduped: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        value = re.sub(r"\s+", " ", candidate).strip()
        if not value or value in seen:
            continue
        seen.add(value)
        deduped.append(value)

    return deduped


async def search_web(query: str) -> list[dict[str, str]]:
    provider = settings.search_provider.strip().lower()
    if not provider:
        raise WebSearchConfigurationError("Web search provider is not configured.")
    if provider != "tavily":
        raise WebSearchConfigurationError("Unsupported web search provider.")
    if is_weather_query(query):
        return await search_weather(query)

    results: list[dict[str, str]] = []
    seen_urls: set[str] = set()
    for candidate_query in build_search_queries(query):
        batch = await fetch_tavily_results(candidate_query, original_query=query)
        batch = filter_search_results(query, batch)
        for item in batch:
            url = item["url"].strip()
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            results.append(item)
            if len(results) >= settings.search_result_limit:
                return results

    return results


async def fetch_tavily_results(query: str, *, original_query: str) -> list[dict[str, str]]:
    api_key = settings.tavily_api_key.strip()
    if not api_key or api_key == "unset":
        raise WebSearchConfigurationError("Tavily API key is not configured.")

    timeout = httpx.Timeout(settings.search_timeout_seconds, connect=5.0)
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = build_tavily_payload(query, original_query=original_query)

    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, headers=headers) as client:
            response = await client.post(
                "https://api.tavily.com/search",
                json=payload,
            )
            response.raise_for_status()
    except httpx.TimeoutException as exc:
        raise WebSearchUpstreamError("Web search timed out.") from exc
    except httpx.HTTPError as exc:
        raise WebSearchUpstreamError("Web search request failed.") from exc

    data = response.json()
    return parse_tavily_results(data, limit=settings.search_result_limit)


async def search_weather(query: str) -> list[dict[str, str]]:
    location = extract_weather_location(query)
    if not location:
        raise WebSearchUpstreamError("Weather search needs a city or region name.")

    geocode_url = "https://geocoding-api.open-meteo.com/v1/search"
    forecast_url = "https://api.open-meteo.com/v1/forecast"
    timeout = httpx.Timeout(settings.search_timeout_seconds, connect=5.0)

    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            geocode_response = await client.get(
                geocode_url,
                params={
                    "name": location,
                    "count": 1,
                    "language": "zh",
                    "format": "json",
                },
            )
            geocode_response.raise_for_status()
            geocode_payload = geocode_response.json()
            geocode_results = geocode_payload.get("results")
            if not isinstance(geocode_results, list) or not geocode_results:
                raise WebSearchUpstreamError("Weather lookup could not find that location.")

            place = geocode_results[0]
            latitude = place.get("latitude")
            longitude = place.get("longitude")
            if not isinstance(latitude, (int, float)) or not isinstance(longitude, (int, float)):
                raise WebSearchUpstreamError("Weather lookup returned incomplete coordinates.")

            timezone = str(place.get("timezone", "Asia/Shanghai")).strip() or "Asia/Shanghai"
            weather_response = await client.get(
                forecast_url,
                params={
                    "latitude": latitude,
                    "longitude": longitude,
                    "current": ",".join(
                        (
                            "temperature_2m",
                            "relative_humidity_2m",
                            "apparent_temperature",
                            "precipitation",
                            "weather_code",
                            "wind_speed_10m",
                        )
                    ),
                    "timezone": timezone,
                    "forecast_days": 1,
                },
            )
            weather_response.raise_for_status()
    except httpx.TimeoutException as exc:
        raise WebSearchUpstreamError("Weather search timed out.") from exc
    except httpx.HTTPError as exc:
        raise WebSearchUpstreamError("Weather search request failed.") from exc

    weather_payload = weather_response.json()
    current = weather_payload.get("current")
    if not isinstance(current, dict):
        raise WebSearchUpstreamError("Weather search returned malformed data.")

    place_name = build_place_name(place)
    weather_code = int(current.get("weather_code", -1))
    summary = WEATHER_CODE_LABELS.get(weather_code, "\u5929\u6c14\u72b6\u6001\u672a\u77e5")
    snippet = (
        f"{current.get('time', '')} {place_name}\u5929\u6c14\uff1a{summary}\uff0c"
        f"\u6c14\u6e29 {current.get('temperature_2m', '--')}\u00b0C\uff0c"
        f"\u4f53\u611f {current.get('apparent_temperature', '--')}\u00b0C\uff0c"
        f"\u6e7f\u5ea6 {current.get('relative_humidity_2m', '--')}%\uff0c"
        f"\u98ce\u901f {current.get('wind_speed_10m', '--')} km/h\uff0c"
        f"\u964d\u6c34 {current.get('precipitation', '--')} mm\u3002"
    )
    return [
        {
            "title": f"{place_name}\u5f53\u524d\u5929\u6c14",
            "url": f"https://open-meteo.com/en/docs?latitude={latitude}&longitude={longitude}",
            "snippet": snippet,
        }
    ]


def build_tavily_payload(query: str, *, original_query: str) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "query": query,
        "max_results": settings.search_result_limit,
        "search_depth": settings.tavily_search_depth.strip() or "advanced",
        "include_answer": False,
        "include_raw_content": False,
    }
    if is_domestic_china_news_query(original_query):
        payload["topic"] = "general"
        payload["country"] = "china"
        payload["include_domains"] = list(DOMESTIC_NEWS_INCLUDE_DOMAINS)
    elif is_news_query(original_query):
        payload["topic"] = "news"
        payload["time_range"] = settings.tavily_news_time_range.strip() or "day"
    else:
        payload["topic"] = "general"
    return payload


def parse_tavily_results(payload: dict[str, Any], *, limit: int) -> list[dict[str, str]]:
    results: list[dict[str, str]] = []
    raw_results = payload.get("results")
    if not isinstance(raw_results, list):
        return results

    for item in raw_results:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title", "")).strip()
        url = str(item.get("url", "")).strip()
        snippet = clean_text(item.get("content", ""))

        if not title or not url:
            continue

        results.append({"title": title, "url": url, "snippet": snippet})
        if len(results) >= limit:
            break

    return results


def clean_text(raw: Any) -> str:
    return re.sub(r"\s+", " ", str(raw or "")).strip()


def normalize_search_query(query: str) -> str:
    value = query.strip()
    for prefix in SEARCH_REQUEST_PREFIXES:
        if value.startswith(prefix):
            value = value[len(prefix) :].strip()
            break

    for filler in SEARCH_REQUEST_FILLERS:
        value = value.replace(filler, " ")

    value = re.sub(r"[，。、“”‘’！？：；,.:;（）()\[\]{}]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def ensure_latest_suffix(query: str) -> str:
    value = query.strip()
    if not value:
        return value
    if "\u6700\u65b0" in value:
        return value
    return f"{value} \u6700\u65b0"


def is_news_query(query: str) -> bool:
    lowered = query.lower()
    return any(token in lowered for token in NEWS_QUERY_HINTS)


def is_weather_query(query: str) -> bool:
    lowered = query.lower()
    return any(token in lowered for token in WEATHER_QUERY_HINTS)


def is_domestic_china_news_query(query: str) -> bool:
    lowered = query.lower()
    return is_news_query(query) and any(token in lowered for token in DOMESTIC_CHINA_NEWS_HINTS)


def extract_weather_location(query: str) -> str:
    value = normalize_search_query(query)
    lowered = value.lower()
    for token in WEATHER_LOCATION_STRIP_TOKENS:
        lowered = lowered.replace(token, " ")
    lowered = re.sub(r"\b(how|is|the|what|will|be|in|at|for)\b", " ", lowered)
    lowered = re.sub(r"\s+", " ", lowered).strip(" ,")
    return lowered or value


def build_place_name(place: dict[str, Any]) -> str:
    name = str(place.get("name", "")).strip()
    admin1 = str(place.get("admin1", "")).strip()
    country = str(place.get("country", "")).strip()
    parts = [part for part in (name, admin1, country) if part]
    return " / ".join(parts) or "\u8be5\u5730\u533a"


def filter_search_results(query: str, results: list[dict[str, str]]) -> list[dict[str, str]]:
    if not is_news_query(query):
        return results

    filtered: list[dict[str, str]] = []
    for item in results:
        haystack = " ".join((item["title"], item["url"], item["snippet"])).lower()
        if any(token.lower() in haystack for token in NEWS_RESULT_JUNK_TOKENS):
            continue
        if is_domestic_china_news_query(query) and not is_allowed_domestic_news_result(item["url"]):
            continue
        filtered.append(item)
    return filtered


def is_allowed_domestic_news_result(url: str) -> bool:
    lowered = url.strip().lower()
    return any(domain in lowered for domain in DOMESTIC_NEWS_INCLUDE_DOMAINS)

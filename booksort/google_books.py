from __future__ import annotations

import re
import time

import requests

from .models import Book


GOOGLE_BOOKS_URL = "https://www.googleapis.com/books/v1/volumes"
OPEN_LIBRARY_URL = "https://openlibrary.org/search.json"
REQUEST_HEADERS = {"User-Agent": "BookSort/1.0 (+https://github.com/markyb2833/booksortre)"}
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


class GoogleBooksUnavailable(RuntimeError):
    pass


def search_google_books(query: str, limit: int = 10) -> list[dict[str, object]]:
    google_error = None
    google_results = []
    for params in _google_query_variants(query):
        try:
            google_results.extend(
                _parse_google_books(
                    _fetch_json(GOOGLE_BOOKS_URL, params, limit=limit, attempts=2),
                    limit,
                )
            )
            ranked_results = _rank_results(_dedupe_results(google_results), query)
            if _has_strong_title_match(ranked_results, query):
                return ranked_results[:limit]
        except GoogleBooksUnavailable as exc:
            google_error = exc

    google_results = _rank_results(_dedupe_results(google_results), query)
    if google_results:
        return google_results[:limit]

    try:
        fallback_results = _parse_open_library(
            _fetch_json(OPEN_LIBRARY_URL, {"q": query}, limit=limit, attempts=2),
            limit,
        )
    except GoogleBooksUnavailable:
        raise google_error or GoogleBooksUnavailable(
            "Book search is temporarily unavailable. Try again in a moment, or type the book details manually."
        )

    return _rank_results(_dedupe_results(fallback_results), query)[:limit]


def _google_query_variants(query: str) -> list[dict[str, object]]:
    clean_query = " ".join(query.split())
    digits = re.sub(r"\D", "", clean_query)
    if len(digits) in {10, 13}:
        return [{"q": f"isbn:{digits}"}, {"q": clean_query}]

    variants = [{"q": f'"{clean_query}"'}, {"q": clean_query}]
    if len(clean_query.split()) <= 5:
        variants.insert(1, {"q": f'intitle:"{clean_query}"'})
    return variants


def _parse_google_books(books_data: dict[str, object], limit: int) -> list[dict[str, object]]:
    items = books_data.get("items", [])
    if not isinstance(items, list):
        items = []

    results = []
    for item in items[:limit]:
        volume_info = item.get("volumeInfo", {})
        title = volume_info.get("title", "")
        subtitle = volume_info.get("subtitle", "")
        series_info = Book.detect_series_from_title(title, subtitle)
        identifiers = volume_info.get("industryIdentifiers", [])

        results.append(
            {
                "title": title,
                "subtitle": subtitle,
                "author": ", ".join(volume_info.get("authors", [])),
                "isbn": next(
                    (
                        identifier
                        for identifier in identifiers
                        if identifier.get("type") in ["ISBN_13", "ISBN_10"]
                    ),
                    {},
                ).get("identifier", ""),
                "publication_year": volume_info.get("publishedDate", "")[:4]
                if volume_info.get("publishedDate")
                else "",
                "genre": ", ".join(volume_info.get("categories", [])),
                "description": volume_info.get("description", ""),
                "rating": volume_info.get("averageRating", 0),
                "cover_url": volume_info.get("imageLinks", {}).get("thumbnail", ""),
                "series_name": series_info.get("series_name"),
                "series_number": series_info.get("series_number"),
                "series_total_books": series_info.get("series_total_books"),
                "series_confidence": series_info.get("confidence"),
            }
        )

    return results


def _parse_open_library(books_data: dict[str, object], limit: int) -> list[dict[str, object]]:
    docs = books_data.get("docs", [])
    if not isinstance(docs, list):
        docs = []

    results = []
    for item in docs[:limit]:
        title = str(item.get("title") or "")
        subtitle = str(item.get("subtitle") or "")
        series_info = Book.detect_series_from_title(title, subtitle)
        authors = item.get("author_name") or []
        isbns = item.get("isbn") or []
        subjects = item.get("subject") or []
        cover_id = item.get("cover_i")

        results.append(
            {
                "title": title,
                "subtitle": subtitle,
                "author": ", ".join(authors[:3]) if isinstance(authors, list) else "",
                "isbn": isbns[0] if isinstance(isbns, list) and isbns else "",
                "publication_year": item.get("first_publish_year") or "",
                "genre": ", ".join(subjects[:3]) if isinstance(subjects, list) else "",
                "description": "",
                "rating": 0,
                "cover_url": f"https://covers.openlibrary.org/b/id/{cover_id}-M.jpg" if cover_id else "",
                "series_name": series_info.get("series_name"),
                "series_number": series_info.get("series_number"),
                "series_total_books": series_info.get("series_total_books"),
                "series_confidence": series_info.get("confidence"),
                "source": "Open Library",
            }
        )

    return results


def _dedupe_results(results: list[dict[str, object]]) -> list[dict[str, object]]:
    seen = set()
    deduped = []
    for result in results:
        key = (
            _normalise(str(result.get("isbn") or "")),
            _normalise(str(result.get("title") or "")),
            _normalise(str(result.get("author") or "")),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(result)
    return deduped


def _rank_results(results: list[dict[str, object]], query: str) -> list[dict[str, object]]:
    return sorted(results, key=lambda result: _result_score(result, query), reverse=True)


def _has_strong_title_match(results: list[dict[str, object]], query: str) -> bool:
    if len(results) < 3:
        return False

    title = _normalise(str(results[0].get("title") or ""))
    query_text = _normalise(query)
    return title == query_text or title.startswith(query_text)


def _result_score(result: dict[str, object], query: str) -> float:
    query_text = _normalise(query)
    query_tokens = set(query_text.split())
    title = _normalise(str(result.get("title") or ""))
    subtitle = _normalise(str(result.get("subtitle") or ""))
    author = _normalise(str(result.get("author") or ""))
    combined = " ".join(part for part in [title, subtitle, author] if part)
    title_tokens = set(title.split())
    combined_tokens = set(combined.split())
    score = 0.0

    if title == query_text:
        score += 100
    if title.startswith(query_text):
        score += 55
    if query_text and query_text in title:
        score += 45
    if query_tokens and query_tokens.issubset(title_tokens):
        score += 35
    if query_tokens and query_tokens.issubset(combined_tokens):
        score += 18
    if query_tokens:
        score += 25 * (len(query_tokens & title_tokens) / len(query_tokens))
        score += 8 * (len(query_tokens & combined_tokens) / len(query_tokens))
    if result.get("cover_url"):
        score += 6
    if result.get("isbn"):
        score += 4
    if result.get("source") == "Open Library":
        score -= 3

    return score


def _normalise(value: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", value.lower()).split())


def _fetch_json(
    url: str,
    params: dict[str, object],
    *,
    limit: int,
    attempts: int,
) -> dict[str, object]:
    last_error: Exception | None = None

    for attempt in range(attempts):
        session = requests.Session()
        session.trust_env = False
        try:
            response = session.get(
                url,
                params={**params, "limit": limit} if url == OPEN_LIBRARY_URL else params,
                headers=REQUEST_HEADERS,
                timeout=10,
            )
            response.raise_for_status()
            return response.json()
        except requests.HTTPError as exc:
            last_error = exc
            status_code = exc.response.status_code if exc.response is not None else None
            if status_code not in RETRYABLE_STATUS_CODES:
                raise GoogleBooksUnavailable("The book search provider could not complete that search.") from exc
        except ValueError as exc:
            last_error = exc
        except requests.RequestException as exc:
            last_error = exc
        finally:
            session.close()

        if attempt < attempts - 1:
            time.sleep(0.5 * (attempt + 1))

    raise GoogleBooksUnavailable(
        "Book search is temporarily unavailable. Try again in a moment, or type the book details manually."
    ) from last_error

from __future__ import annotations

import requests

from .models import Book


GOOGLE_BOOKS_URL = "https://www.googleapis.com/books/v1/volumes"


def search_google_books(query: str, limit: int = 10) -> list[dict[str, object]]:
    response = requests.get(GOOGLE_BOOKS_URL, params={"q": query}, timeout=10)
    response.raise_for_status()
    books_data = response.json()

    results = []
    for item in books_data.get("items", [])[:limit]:
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

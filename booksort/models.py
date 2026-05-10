from __future__ import annotations

from datetime import UTC, datetime
import re

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .extensions import db


class Book(db.Model):
    __tablename__ = "book"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    author: Mapped[str] = mapped_column(String(200), nullable=False)
    isbn: Mapped[str | None] = mapped_column(String(13), unique=True)
    publication_year: Mapped[int | None] = mapped_column(Integer)
    genre: Mapped[str | None] = mapped_column(String(100))
    description: Mapped[str | None] = mapped_column(Text)
    date_added: Mapped[datetime | None] = mapped_column(DateTime, default=lambda: datetime.now(UTC))
    cover_url: Mapped[str | None] = mapped_column(String(500))
    rating: Mapped[float | None] = mapped_column(Float)
    personal_rating: Mapped[float | None] = mapped_column(Float)
    box_location: Mapped[str | None] = mapped_column(String(100))
    notes: Mapped[str | None] = mapped_column(Text)
    series_name: Mapped[str | None] = mapped_column(String(200), index=True)
    series_number: Mapped[float | None] = mapped_column(Float)
    series_total_books: Mapped[int | None] = mapped_column(Integer)
    series_is_completed: Mapped[bool | None] = mapped_column(Boolean, default=False)
    series_detected_from_title: Mapped[str | None] = mapped_column(String(200))
    archived: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime)

    @staticmethod
    def detect_series_from_title(title: str, subtitle: str = "") -> dict[str, object]:
        combined_text = f"{title} {subtitle}".strip()
        title_lower = title.lower().strip()

        known_series = {
            "the fellowship of the ring": {"series": "The Lord of the Rings", "number": 1, "total": 3},
            "the two towers": {"series": "The Lord of the Rings", "number": 2, "total": 3},
            "the return of the king": {"series": "The Lord of the Rings", "number": 3, "total": 3},
            "harry potter and the philosopher's stone": {"series": "Harry Potter", "number": 1, "total": 7},
            "harry potter and the sorcerer's stone": {"series": "Harry Potter", "number": 1, "total": 7},
            "harry potter and the chamber of secrets": {"series": "Harry Potter", "number": 2, "total": 7},
            "harry potter and the prisoner of azkaban": {"series": "Harry Potter", "number": 3, "total": 7},
            "harry potter and the goblet of fire": {"series": "Harry Potter", "number": 4, "total": 7},
            "harry potter and the order of the phoenix": {"series": "Harry Potter", "number": 5, "total": 7},
            "harry potter and the half-blood prince": {"series": "Harry Potter", "number": 6, "total": 7},
            "harry potter and the deathly hallows": {"series": "Harry Potter", "number": 7, "total": 7},
            "the hunger games": {"series": "The Hunger Games", "number": 1, "total": 3},
            "catching fire": {"series": "The Hunger Games", "number": 2, "total": 3},
            "mockingjay": {"series": "The Hunger Games", "number": 3, "total": 3},
            "a court of thorns and roses": {"series": "A Court of Thorns and Roses", "number": 1, "total": 5},
            "a court of mist and fury": {"series": "A Court of Thorns and Roses", "number": 2, "total": 5},
            "a court of wings and ruin": {"series": "A Court of Thorns and Roses", "number": 3, "total": 5},
            "a court of silver flames": {"series": "A Court of Thorns and Roses", "number": 4, "total": 5},
            "fourth wing": {"series": "The Empyrean", "number": 1, "total": 5},
            "iron flame": {"series": "The Empyrean", "number": 2, "total": 5},
        }

        if title_lower in known_series:
            series_data = known_series[title_lower]
            return {
                "series_name": series_data["series"],
                "series_number": series_data["number"],
                "series_total_books": series_data["total"],
                "confidence": "high",
            }

        patterns = [
            r"(?i)book\s+(\d+|one|two|three|four|five|six|seven|eight|nine|ten):\s*(.+)",
            r"(.+?)\s*\(([^,]+),?\s*#?(\d+)\)",
            r"([^:]+):\s*book\s+(\d+)\s*[-–]\s*(.+)",
            r"(.+?)\s*[-–:]\s*book\s+(\d+)",
            r"([\w\s]+)\s+and\s+the\s+([\w\s]+)",
        ]

        word_to_number = {
            "one": 1,
            "two": 2,
            "three": 3,
            "four": 4,
            "five": 5,
            "six": 6,
            "seven": 7,
            "eight": 8,
            "nine": 9,
            "ten": 10,
        }

        for pattern in patterns:
            match = re.search(pattern, combined_text)
            if not match:
                continue

            groups = match.groups()
            series_number = None
            for group in groups:
                if group and group.lower() in word_to_number:
                    series_number = word_to_number[group.lower()]
                elif group and group.isdigit():
                    series_number = int(group)

            text_groups = [
                group
                for group in groups
                if group and not group.isdigit() and group.lower() not in word_to_number
            ]
            if text_groups:
                return {
                    "series_name": max(text_groups, key=len).strip(),
                    "series_number": series_number,
                    "confidence": "high" if series_number else "medium",
                }

        return {"series_name": None, "series_number": None, "confidence": "none"}

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "title": self.title,
            "author": self.author,
            "isbn": self.isbn,
            "publication_year": self.publication_year,
            "genre": self.genre,
            "description": self.description,
            "date_added": self.date_added.isoformat() if self.date_added else None,
            "cover_url": self.cover_url,
            "rating": self.rating,
            "personal_rating": self.personal_rating,
            "box_location": self.box_location,
            "notes": self.notes,
            "series_name": self.series_name,
            "series_number": self.series_number,
            "series_total_books": self.series_total_books,
            "series_is_completed": self.series_is_completed,
            "series_detected_from_title": self.series_detected_from_title,
            "archived": self.archived,
            "archived_at": self.archived_at.isoformat() if self.archived_at else None,
        }

    @property
    def series_display(self) -> str | None:
        if not self.series_name:
            return None

        display = self.series_name
        if self.series_number:
            display += f" #{self.series_number:g}"
            if self.series_total_books:
                display += f" of {self.series_total_books}"
        return display

    @property
    def series_progress_percentage(self) -> float | None:
        if not self.series_name or not self.series_total_books:
            return None

        books_in_series = Book.query.filter_by(series_name=self.series_name).count()
        return round((books_in_series / self.series_total_books) * 100, 1)


class AppSetting(db.Model):
    __tablename__ = "app_setting"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))

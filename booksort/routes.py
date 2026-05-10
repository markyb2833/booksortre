from __future__ import annotations

import csv
import hmac
from collections import defaultdict
from datetime import UTC, datetime
from io import StringIO
from pathlib import Path

from flask import Blueprint, Response, current_app, jsonify, redirect, render_template, request, send_file, session, url_for
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError

from .extensions import db
from .google_books import GoogleBooksUnavailable, search_google_books
from .models import AppSetting, Book

main = Blueprint("main", __name__)

AUTH_SESSION_KEY = "booksort_authenticated"
AUTH_EXEMPT_ENDPOINTS = {"main.login", "main.logout", "main.health", "static"}


def _auth_password() -> str | None:
    password = current_app.config.get("BOOKSORT_PASSWORD")
    if password in (None, ""):
        return None
    return str(password)


def _auth_enabled() -> bool:
    return _auth_password() is not None


def _is_authenticated() -> bool:
    return bool(session.get(AUTH_SESSION_KEY))


def _safe_next_url(value: str | None) -> str:
    if value and value.startswith("/") and not value.startswith("//"):
        return value
    return url_for("main.index")


@main.before_app_request
def require_password_login():
    if not _auth_enabled() or _is_authenticated():
        return None
    if request.endpoint in AUTH_EXEMPT_ENDPOINTS:
        return None
    if request.path.startswith("/static/"):
        return None

    if request.is_json or request.method != "GET":
        return jsonify({"error": "Login required"}), 401

    return redirect(url_for("main.login", next=request.full_path.rstrip("?")))


@main.route("/login", methods=["GET", "POST"])
def login():
    password = _auth_password()
    if password is None:
        return redirect(url_for("main.index"))

    error = None
    next_url = _safe_next_url(request.values.get("next"))
    if request.method == "POST":
        submitted_password = request.form.get("password", "")
        if hmac.compare_digest(submitted_password, password):
            session.clear()
            session.permanent = True
            session[AUTH_SESSION_KEY] = True
            return redirect(next_url)
        error = "That password didn't match."

    return render_template("login.html", error=error, next_url=next_url)


@main.route("/logout", methods=["GET", "POST"])
def logout():
    session.clear()
    return redirect(url_for("main.login"))


def _float_or_none(value: object) -> float | None:
    if value in (None, ""):
        return None
    if isinstance(value, str) and not value.strip():
        return None
    return float(value)


def _int_or_none(value: object) -> int | None:
    if value in (None, ""):
        return None
    if isinstance(value, str) and not value.strip():
        return None
    return int(value)


def _bool_value(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if value in (None, ""):
        return False
    return str(value).lower() in {"1", "true", "yes", "on"}


def _optional_string(value: object) -> str | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    return text or None


def _normalise_text(value: object) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _parse_datetime(value: object) -> datetime | None:
    text = _optional_string(value)
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def _apply_book_updates(
    book: Book,
    data: dict[str, object],
    *,
    allow_archive_fields: bool = False,
    allow_date_added: bool = False,
) -> None:
    book.title = _optional_string(data.get("title")) or book.title
    book.author = _optional_string(data.get("author")) or book.author
    book.isbn = _optional_string(data.get("isbn"))
    book.publication_year = _int_or_none(data.get("publication_year"))
    book.genre = _optional_string(data.get("genre"))
    book.description = _optional_string(data.get("description"))
    book.rating = _float_or_none(data.get("rating"))
    book.personal_rating = _float_or_none(data.get("personal_rating")) or 0
    book.box_location = str(data.get("box_location") or "")
    book.notes = str(data.get("notes") or "")
    book.cover_url = _optional_string(data.get("cover_url"))
    book.series_name = _optional_string(data.get("series_name"))
    book.series_number = _float_or_none(data.get("series_number"))
    book.series_total_books = _int_or_none(data.get("series_total_books"))
    book.series_is_completed = _bool_value(data.get("series_is_completed"))

    if allow_archive_fields and "archived" in data:
        book.archived = _bool_value(data.get("archived"))
        book.archived_at = _parse_datetime(data.get("archived_at")) if book.archived else None
        if book.archived and not book.archived_at:
            book.archived_at = datetime.now(UTC)

    if allow_date_added and data.get("date_added"):
        book.date_added = _parse_datetime(data.get("date_added")) or book.date_added


def _duplicate_matches(data: dict[str, object]) -> list[dict[str, object]]:
    isbn = _optional_string(data.get("isbn"))
    title = _normalise_text(data.get("title"))
    author = _normalise_text(data.get("author"))

    conditions = []
    if isbn:
        conditions.append(Book.isbn == isbn)
    if title and author:
        conditions.append(
            (func.lower(func.trim(Book.title)) == title)
            & (func.lower(func.trim(Book.author)) == author)
        )

    if not conditions:
        return []

    matches = db.session.scalars(select(Book).where(or_(*conditions)).limit(5)).all()
    duplicate_rows = []
    for book in matches:
        reason = "Title and author"
        if isbn and book.isbn == isbn:
            reason = "ISBN"

        duplicate_rows.append(
            {
                "id": book.id,
                "title": book.title,
                "author": book.author,
                "isbn": book.isbn,
                "archived": book.archived,
                "reason": reason,
                "book": book.to_dict(),
            }
        )

    return duplicate_rows


def _book_from_payload(data: dict[str, object]) -> Book:
    if not data.get("series_name"):
        data.update(
            Book.detect_series_from_title(
                str(data.get("title", "")),
                str(data.get("subtitle", "")),
            )
        )

    confidence = data.get("confidence") or data.get("series_confidence")
    series_name = data.get("series_name") or None

    return Book(
        title=str(data["title"]),
        author=str(data["author"]),
        isbn=_optional_string(data.get("isbn")),
        publication_year=_int_or_none(data.get("publication_year")),
        genre=_optional_string(data.get("genre")),
        description=_optional_string(data.get("description")),
        rating=_float_or_none(data.get("rating")) or 0,
        personal_rating=_float_or_none(data.get("personal_rating")) or 0,
        box_location=str(data.get("box_location") or ""),
        notes=str(data.get("notes") or ""),
        cover_url=_optional_string(data.get("cover_url")),
        series_name=str(series_name) if series_name else None,
        series_number=_float_or_none(data.get("series_number")),
        series_total_books=_int_or_none(data.get("series_total_books")),
        series_is_completed=_bool_value(data.get("series_is_completed")),
        series_detected_from_title=str(series_name)
        if series_name and confidence in ["high", "medium"]
        else None,
    )


def _find_existing_import_book(data: dict[str, object]) -> Book | None:
    book_id = _int_or_none(data.get("id"))
    if book_id:
        existing = db.session.get(Book, book_id)
        if existing:
            return existing

    isbn = _optional_string(data.get("isbn"))
    if isbn:
        return db.session.scalar(select(Book).where(Book.isbn == isbn))

    return None


def _get_setting(key: str) -> str | None:
    setting = db.session.get(AppSetting, key)
    return setting.value if setting else None


def _set_setting(key: str, value: str) -> None:
    setting = db.session.get(AppSetting, key)
    if setting is None:
        setting = AppSetting(key=key)
        db.session.add(setting)
    setting.value = value
    setting.updated_at = datetime.now(UTC)


def _counts() -> dict[str, int | None]:
    return {
        "book_count": db.session.scalar(select(func.count(Book.id))),
        "active_count": db.session.scalar(select(func.count(Book.id)).where(Book.archived.is_(False))),
        "archived_count": db.session.scalar(select(func.count(Book.id)).where(Book.archived.is_(True))),
        "series_count": db.session.scalar(
            select(func.count(func.distinct(Book.series_name))).where(Book.series_name.isnot(None), Book.series_name != "")
        ),
    }


def _series_overview(books: list[Book]) -> list[dict[str, object]]:
    grouped: dict[str, list[Book]] = defaultdict(list)
    for book in books:
        if book.archived or not book.series_name:
            continue
        grouped[book.series_name].append(book)

    overview = []
    for series_name, series_books in grouped.items():
        owned_numbers = sorted(
            {
                int(book.series_number)
                for book in series_books
                if book.series_number and float(book.series_number).is_integer()
            }
        )
        total_books = max(
            [book.series_total_books for book in series_books if book.series_total_books] or [0]
        )
        missing_numbers = []
        if total_books:
            missing_numbers = [number for number in range(1, total_books + 1) if number not in owned_numbers]

        overview.append(
            {
                "name": series_name,
                "owned": len(series_books),
                "total": total_books or None,
                "complete": any(book.series_is_completed for book in series_books),
                "missing_numbers": missing_numbers[:12],
                "more_missing": max(0, len(missing_numbers) - 12),
                "books": sorted(series_books, key=lambda book: (book.series_number is None, book.series_number or 0, book.title.lower())),
            }
        )

    return sorted(overview, key=lambda row: row["name"].lower())


@main.get("/")
def index():
    books = db.session.scalars(select(Book).order_by(Book.archived.asc(), Book.date_added.desc())).all()
    stats = {
        "total": len(books),
        "active": sum(1 for book in books if not book.archived),
        "archived": sum(1 for book in books if book.archived),
    }
    return render_template(
        "index.html",
        books=books,
        stats=stats,
        series_overview=_series_overview(books),
        last_backup_at=_get_setting("last_backup_at"),
    )


@main.get("/health")
def health():
    payload = {"status": "ok"}
    if not _auth_enabled() or _is_authenticated():
        counts = _counts()
        payload.update(
            {
                "book_count": counts["book_count"],
                "active_count": counts["active_count"],
                "archived_count": counts["archived_count"],
            }
        )
    return jsonify(payload)


@main.get("/backup/database")
def backup_database():
    db_path = Path(current_app.instance_path) / "booksort.db"
    if not db_path.exists():
        return jsonify({"error": "Database file not found"}), 404

    timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    _set_setting("last_backup_at", datetime.now(UTC).isoformat(timespec="seconds"))
    db.session.commit()
    return send_file(
        db_path,
        as_attachment=True,
        download_name=f"booksort-backup-{timestamp}.db",
        mimetype="application/octet-stream",
    )


@main.get("/settings")
def settings():
    return render_template(
        "settings.html",
        counts=_counts(),
        database_path=str(Path(current_app.instance_path) / "booksort.db"),
        instance_path=current_app.instance_path,
        last_backup_at=_get_setting("last_backup_at"),
    )


@main.get("/export/books.csv")
def export_books_csv():
    output = StringIO()
    fieldnames = [
        "id",
        "title",
        "author",
        "isbn",
        "publication_year",
        "genre",
        "rating",
        "personal_rating",
        "box_location",
        "notes",
        "series_name",
        "series_number",
        "series_total_books",
        "series_is_completed",
        "archived",
        "archived_at",
        "cover_url",
        "description",
        "date_added",
    ]
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()

    books = db.session.scalars(select(Book).order_by(Book.id)).all()
    for book in books:
        row = book.to_dict()
        writer.writerow({field: row.get(field) for field in fieldnames})

    timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename=booksort-export-{timestamp}.csv"},
    )


@main.post("/import/books.csv")
def import_books_csv():
    upload = request.files.get("csv_file")
    if not upload:
        return jsonify({"error": "Choose a CSV file to import."}), 400

    update_existing = _bool_value(request.form.get("update_existing"))
    content = upload.stream.read().decode("utf-8-sig")
    reader = csv.DictReader(StringIO(content))
    summary = {"created": 0, "updated": 0, "skipped": 0, "errors": []}

    for row_number, row in enumerate(reader, start=2):
        data = {
            key: value.strip() if isinstance(value, str) else value
            for key, value in row.items()
            if key
        }
        if not any(data.values()):
            continue

        try:
            existing = _find_existing_import_book(data) if update_existing else None
            if existing:
                _apply_book_updates(
                    existing,
                    data,
                    allow_archive_fields=True,
                    allow_date_added=True,
                )
                summary["updated"] += 1
                continue

            if not _optional_string(data.get("title")) or not _optional_string(data.get("author")):
                summary["skipped"] += 1
                summary["errors"].append(f"Row {row_number}: missing title or author.")
                continue

            if _duplicate_matches(data):
                summary["skipped"] += 1
                summary["errors"].append(f"Row {row_number}: possible duplicate, skipped.")
                continue

            book = _book_from_payload(data)
            if "archived" in data:
                book.archived = _bool_value(data.get("archived"))
                book.archived_at = _parse_datetime(data.get("archived_at")) if book.archived else None
            if data.get("date_added"):
                book.date_added = _parse_datetime(data.get("date_added")) or book.date_added

            db.session.add(book)
            summary["created"] += 1
        except Exception as exc:
            summary["skipped"] += 1
            summary["errors"].append(f"Row {row_number}: {exc}")

    try:
        db.session.commit()
    except IntegrityError as exc:
        db.session.rollback()
        return jsonify({"error": f"Import failed because of a duplicate ISBN: {exc}"}), 409

    wants_json = request.headers.get("Accept") == "application/json" or request.form.get("as_json")
    if wants_json:
        return jsonify(summary)

    return redirect(
        url_for(
            "main.index",
            imported=summary["created"],
            updated=summary["updated"],
            skipped=summary["skipped"],
        )
    )


@main.get("/search_book")
def search_book():
    query = request.args.get("q", "").strip()
    if not query:
        return jsonify([])

    try:
        return jsonify(search_google_books(query))
    except GoogleBooksUnavailable as exc:
        return jsonify({"error": str(exc), "manual_add_available": True}), 503
    except Exception as exc:
        return jsonify(
            {
                "error": "Book search is unavailable right now. Try again in a moment, or type the book details manually.",
                "manual_add_available": True,
            }
        ), 503


@main.route("/add_book", methods=["GET", "POST"])
def add_book():
    if request.method == "GET":
        return render_template("add_book.html")

    try:
        is_json_request = request.is_json
        data = request.get_json(silent=True) or request.form.to_dict()
        duplicates = _duplicate_matches(data)
        if duplicates and not _bool_value(data.get("force_add")):
            return jsonify({"error": "Possible duplicate book", "duplicates": duplicates}), 409

        book = _book_from_payload(data)
        db.session.add(book)
        db.session.commit()
        if not is_json_request:
            return redirect(url_for("main.index"))
        return jsonify(book.to_dict()), 201
    except IntegrityError:
        db.session.rollback()
        return jsonify({"error": "A book with that ISBN already exists."}), 409
    except Exception as exc:
        db.session.rollback()
        return jsonify({"error": str(exc)}), 400


@main.put("/update_book/<int:book_id>")
def update_book(book_id: int):
    try:
        book = db.get_or_404(Book, book_id)
        data = request.get_json(silent=True) or {}
        book.personal_rating = _float_or_none(data.get("personal_rating")) or 0
        book.box_location = str(data.get("box_location") or "")
        book.notes = str(data.get("notes") or "")
        db.session.commit()
        return jsonify(book.to_dict())
    except Exception as exc:
        db.session.rollback()
        return jsonify({"error": str(exc)}), 400


@main.put("/edit_book_full/<int:book_id>")
def edit_book_full(book_id: int):
    try:
        book = db.get_or_404(Book, book_id)
        data = request.get_json(silent=True) or {}
        _apply_book_updates(book, data)

        db.session.commit()
        return jsonify({"success": True, "book": book.to_dict()})
    except IntegrityError:
        db.session.rollback()
        return jsonify({"success": False, "error": "A book with that ISBN already exists."}), 409
    except Exception as exc:
        db.session.rollback()
        return jsonify({"success": False, "error": str(exc)}), 400


@main.post("/archive_book/<int:book_id>")
def archive_book(book_id: int):
    try:
        book = db.get_or_404(Book, book_id)
        book.archived = True
        book.archived_at = datetime.now(UTC)
        db.session.commit()
        return jsonify({"success": True, "book": book.to_dict()})
    except Exception as exc:
        db.session.rollback()
        return jsonify({"success": False, "error": str(exc)}), 400


@main.post("/restore_book/<int:book_id>")
def restore_book(book_id: int):
    try:
        book = db.get_or_404(Book, book_id)
        book.archived = False
        book.archived_at = None
        db.session.commit()
        return jsonify({"success": True, "book": book.to_dict()})
    except Exception as exc:
        db.session.rollback()
        return jsonify({"success": False, "error": str(exc)}), 400


@main.post("/restore_all_archived")
def restore_all_archived():
    try:
        books = db.session.scalars(select(Book).where(Book.archived.is_(True))).all()
        for book in books:
            book.archived = False
            book.archived_at = None
        db.session.commit()
        return jsonify({"success": True, "restored": len(books)})
    except Exception as exc:
        db.session.rollback()
        return jsonify({"success": False, "error": str(exc)}), 400


@main.post("/bulk_update_location")
def bulk_update_location():
    try:
        data = request.get_json(silent=True) or {}
        book_ids = [int(book_id) for book_id in data.get("book_ids", [])]
        box_location = str(data.get("box_location") or "")

        if not book_ids:
            return jsonify({"success": False, "error": "Select at least one book."}), 400

        books = db.session.scalars(select(Book).where(Book.id.in_(book_ids))).all()
        for book in books:
            book.box_location = box_location
        db.session.commit()
        return jsonify({"success": True, "updated": len(books)})
    except Exception as exc:
        db.session.rollback()
        return jsonify({"success": False, "error": str(exc)}), 400


@main.get("/get_book/<int:book_id>")
def get_book(book_id: int):
    book = db.get_or_404(Book, book_id)
    return jsonify(book.to_dict())


@main.get("/search_series")
def search_series():
    query = request.args.get("q", "").strip()
    if len(query) < 2:
        return jsonify([])

    names = db.session.scalars(
        select(Book.series_name)
        .where(Book.series_name.ilike(f"%{query}%"))
        .distinct()
        .limit(10)
    ).all()
    return jsonify([name for name in names if name])


@main.get("/series_info/<series_name>")
def get_series_info(series_name: str):
    books_in_series = db.session.scalars(
        select(Book).where(Book.series_name == series_name).order_by(Book.series_number)
    ).all()

    if not books_in_series:
        return jsonify({"error": "Series not found"}), 404

    total_books = max([book.series_total_books for book in books_in_series if book.series_total_books] or [0])
    return jsonify(
        {
            "name": series_name,
            "books_owned": len(books_in_series),
            "total_books_in_series": total_books,
            "is_completed": any(book.series_is_completed for book in books_in_series),
            "books": [book.to_dict() for book in books_in_series],
        }
    )


@main.post("/edit_book")
def edit_book():
    try:
        book = db.get_or_404(Book, request.form.get("book_id"))
        book.personal_rating = _float_or_none(request.form.get("personal_rating"))
        book.box_location = request.form.get("box_location", "")
        book.notes = request.form.get("notes", "")
        db.session.commit()
        return jsonify({"success": True})
    except Exception as exc:
        db.session.rollback()
        return jsonify({"success": False, "error": str(exc)}), 400

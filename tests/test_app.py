from __future__ import annotations

import os
import shutil
import unittest
import uuid
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from booksort import create_app
from booksort.extensions import db
from booksort.google_books import GoogleBooksUnavailable, search_google_books
from booksort.models import Book


class BookSortTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app(
            {
                "TESTING": True,
                "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
            }
        )
        self.client = self.app.test_client()
        self.context = self.app.app_context()
        self.context.push()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.context.pop()

    def add_book(self, **overrides):
        values = {"title": "Test Book", "author": "Test Author"}
        values.update(overrides)
        book = Book(**values)
        db.session.add(book)
        db.session.commit()
        return book

    def test_home_and_health(self):
        self.add_book(series_name="Example Series", series_number=1, series_total_books=2)

        home = self.client.get("/")
        health = self.client.get("/health")

        self.assertEqual(home.status_code, 200)
        self.assertIn(b"Series Overview", home.data)
        self.assertEqual(health.status_code, 200)
        self.assertEqual(health.json["book_count"], 1)

    def test_password_gate_when_configured(self):
        self.app.config["BOOKSORT_PASSWORD"] = "secret-password"

        locked_home = self.client.get("/")
        public_health = self.client.get("/health")
        bad_login = self.client.post("/login", data={"password": "wrong"})
        good_login = self.client.post("/login", data={"password": "secret-password"})
        unlocked_home = self.client.get("/")
        logout = self.client.post("/logout")
        locked_again = self.client.get("/")

        self.assertEqual(locked_home.status_code, 302)
        self.assertIn("/login", locked_home.headers["Location"])
        self.assertEqual(public_health.status_code, 200)
        self.assertEqual(public_health.json, {"status": "ok"})
        self.assertEqual(bad_login.status_code, 200)
        self.assertIn(b"That password", bad_login.data)
        self.assertEqual(good_login.status_code, 302)
        self.assertIn("Expires=", good_login.headers["Set-Cookie"])
        self.assertEqual(unlocked_home.status_code, 200)
        self.assertEqual(logout.status_code, 302)
        self.assertEqual(locked_again.status_code, 302)

    def test_settings_and_backup_timestamp(self):
        self.add_book()

        before = self.client.get("/settings")
        backup = self.client.get("/backup/database")
        after = self.client.get("/settings")

        self.assertEqual(before.status_code, 200)
        self.assertIn(b"Never recorded", before.data)
        self.assertEqual(backup.status_code, 200)
        self.assertIn(b"Last backup downloaded", after.data)
        self.assertNotIn(b"Never recorded", after.data)

    def test_inline_update_without_rating_change(self):
        book = self.add_book(personal_rating=3.0, box_location="Box A", notes="Old")

        response = self.client.put(
            f"/update_book/{book.id}",
            json={"personal_rating": "3.0", "box_location": "Box B", "notes": "New"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["personal_rating"], 3.0)
        self.assertEqual(response.json["box_location"], "Box B")
        self.assertEqual(response.json["notes"], "New")

    def test_full_edit_can_clear_optional_fields(self):
        book = self.add_book(
            isbn="1234567890123",
            publication_year=2020,
            genre="Fantasy",
            description="A description",
            rating=4.5,
            cover_url="https://example.com/cover.jpg",
            series_name="Example Series",
            series_number=1,
            series_total_books=3,
        )

        response = self.client.put(
            f"/edit_book_full/{book.id}",
            json={
                "title": "Changed",
                "author": "Test Author",
                "isbn": "",
                "publication_year": "",
                "genre": "",
                "description": "",
                "rating": "",
                "personal_rating": "0",
                "box_location": "",
                "notes": "",
                "cover_url": "",
                "series_name": "",
                "series_number": "",
                "series_total_books": "",
                "series_is_completed": False,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json["success"])
        self.assertIsNone(response.json["book"]["isbn"])
        self.assertIsNone(response.json["book"]["publication_year"])
        self.assertIsNone(response.json["book"]["rating"])
        self.assertIsNone(response.json["book"]["series_name"])

    def test_duplicate_add_requires_confirmation(self):
        self.add_book(title="Existing Book", author="Same Author", isbn="1111111111111")

        duplicate = self.client.post(
            "/add_book",
            json={"title": "Existing Book", "author": "Same Author", "isbn": "2222222222222"},
        )
        forced = self.client.post(
            "/add_book",
            json={
                "title": "Existing Book",
                "author": "Same Author",
                "isbn": "2222222222222",
                "force_add": True,
            },
        )

        self.assertEqual(duplicate.status_code, 409)
        self.assertEqual(duplicate.json["error"], "Possible duplicate book")
        self.assertIn("book", duplicate.json["duplicates"][0])
        self.assertEqual(forced.status_code, 201)

    def test_google_books_outage_returns_friendly_search_error(self):
        with patch(
            "booksort.routes.search_google_books",
            side_effect=GoogleBooksUnavailable("Google Books is temporarily unavailable."),
        ):
            response = self.client.get("/search_book?q=james+bond")

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json["error"], "Google Books is temporarily unavailable.")
        self.assertTrue(response.json["manual_add_available"])

    def test_book_search_falls_back_to_open_library(self):
        google_error = GoogleBooksUnavailable("Google failed")
        open_library_data = {
            "docs": [
                {
                    "title": "Casino Royale",
                    "author_name": ["Ian Fleming"],
                    "isbn": ["9780099576853"],
                    "first_publish_year": 1953,
                    "cover_i": 123,
                }
            ]
        }

        with patch(
            "booksort.google_books._fetch_json",
            side_effect=[google_error, google_error, google_error, open_library_data],
        ):
            results = search_google_books("james bond")

        self.assertEqual(results[0]["title"], "Casino Royale")
        self.assertEqual(results[0]["author"], "Ian Fleming")
        self.assertEqual(results[0]["source"], "Open Library")

    def test_book_search_ranks_exact_title_matches_first(self):
        google_data = {
            "items": [
                {
                    "volumeInfo": {
                        "title": "Irish Texts Society",
                        "authors": [],
                        "publishedDate": "1899",
                    }
                },
                {
                    "volumeInfo": {
                        "title": "King of the World",
                        "authors": ["David Remnick"],
                        "publishedDate": "2015",
                        "imageLinks": {"thumbnail": "https://example.com/cover.jpg"},
                    }
                },
            ]
        }

        with patch("booksort.google_books._fetch_json", return_value=google_data):
            results = search_google_books("king of the world")

        self.assertEqual(results[0]["title"], "King of the World")

    def test_archive_and_restore(self):
        book = self.add_book()

        archived = self.client.post(f"/archive_book/{book.id}")
        restored = self.client.post(f"/restore_book/{book.id}")

        self.assertEqual(archived.status_code, 200)
        self.assertTrue(archived.json["book"]["archived"])
        self.assertEqual(restored.status_code, 200)
        self.assertFalse(restored.json["book"]["archived"])

    def test_restore_all_archived(self):
        self.add_book(title="Archived One", archived=True)
        self.add_book(title="Archived Two", archived=True)

        response = self.client.post("/restore_all_archived")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json["success"])
        self.assertEqual(response.json["restored"], 2)
        self.assertEqual(Book.query.filter_by(archived=True).count(), 0)

    def test_bulk_update_location(self):
        first = self.add_book(title="First")
        second = self.add_book(title="Second")

        response = self.client.post(
            "/bulk_update_location",
            json={"book_ids": [first.id, second.id], "box_location": "Box 3"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["updated"], 2)
        self.assertEqual(db.session.get(Book, first.id).box_location, "Box 3")
        self.assertEqual(db.session.get(Book, second.id).box_location, "Box 3")

    def test_csv_import_creates_and_updates_without_deleting(self):
        existing = self.add_book(title="Existing", isbn="1111111111111", box_location="Old Box")
        csv_data = (
            "id,title,author,isbn,publication_year,genre,rating,personal_rating,"
            "box_location,notes,series_name,series_number,series_total_books,"
            "series_is_completed,archived,archived_at,cover_url,description,date_added\n"
            f"{existing.id},Existing,Test Author,1111111111111,,,,,New Box,,,,,,,,,,\n"
            ",Brand New,New Author,2222222222222,,,,,Shelf A,,,,,,,,,,\n"
        )

        response = self.client.post(
            "/import/books.csv",
            data={
                "csv_file": (BytesIO(csv_data.encode("utf-8")), "books.csv"),
                "update_existing": "true",
                "as_json": "true",
            },
            content_type="multipart/form-data",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["updated"], 1)
        self.assertEqual(response.json["created"], 1)
        self.assertEqual(Book.query.count(), 2)
        self.assertEqual(db.session.get(Book, existing.id).box_location, "New Box")

    def test_custom_instance_path_can_live_on_a_volume(self):
        volume_path = Path.cwd() / "instance" / f"volume-test-{uuid.uuid4().hex}"
        volume_path.mkdir(parents=True)
        app = None

        try:
            with patch.dict(os.environ, {"BOOKSORT_INSTANCE_PATH": str(volume_path)}):
                app = create_app({"TESTING": True})

            self.assertEqual(Path(app.instance_path), volume_path)
            self.assertTrue((volume_path / "booksort.db").exists())

            with app.app_context():
                db.session.remove()
                db.engine.dispose()
        finally:
            if app:
                with app.app_context():
                    db.session.remove()
                    db.engine.dispose()
            shutil.rmtree(volume_path, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()

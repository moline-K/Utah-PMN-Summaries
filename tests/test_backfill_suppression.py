import sqlite3
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

import agenda_downloader
from scrapers import utah_pmn
from summarizers.base_summarizer import BaseSummarizer


class FakeSummarizer(BaseSummarizer):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.notifications = []

    def extract_text(self, pdf_path):
        return Path(pdf_path).read_text(encoding="utf-8")

    def summarize_text(self, text, title):
        return f"Summary for {title}: {text.strip()}"

    def notify(self, notice, doc_type, summary_path, summarized_at):
        self.notifications.append(notice["id"])


class BackfillSuppressionTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.tempdir.name)
        self.db_path = self.data_dir / "utah_pmn.db"
        agenda_downloader.DB_PATH = str(self.db_path)
        self.conn = agenda_downloader.get_db_conn()

    def tearDown(self):
        self.conn.close()
        self.tempdir.cleanup()

    def test_source_has_history_uses_public_body_id(self):
        self.assertFalse(agenda_downloader.source_has_history(self.conn, "200"))

        agenda_downloader.log_pdf(
            self.conn,
            "Example City",
            "City Council",
            "Agenda",
            "https://example.test/source.pdf",
            str(self.data_dir / "source.pdf"),
            metadata={"public_body_id": "200"},
        )

        self.assertTrue(agenda_downloader.source_has_history(self.conn, "200"))
        self.assertFalse(agenda_downloader.source_has_history(self.conn, "201"))

    def test_unseeded_recent_notice_is_eligible(self):
        self.assertTrue(
            utah_pmn.is_notice_notification_eligible(
                "2026-06-20",
                source_seeded=False,
                bootstrap_recency_days=5,
                today=date(2026, 6, 22),
            )
        )

    def test_unseeded_old_or_unknown_notice_is_suppressed(self):
        self.assertFalse(
            utah_pmn.is_notice_notification_eligible(
                "2026-06-10",
                source_seeded=False,
                bootstrap_recency_days=5,
                today=date(2026, 6, 22),
            )
        )
        self.assertFalse(
            utah_pmn.is_notice_notification_eligible(
                None,
                source_seeded=False,
                bootstrap_recency_days=5,
                today=date(2026, 6, 22),
            )
        )

    def test_seeded_notice_is_always_eligible(self):
        self.assertTrue(
            utah_pmn.is_notice_notification_eligible(
                "2026-01-01",
                source_seeded=True,
                bootstrap_recency_days=5,
                today=date(2026, 6, 22),
            )
        )

    def test_summarizer_only_processes_notification_eligible_rows(self):
        eligible_path = self.data_dir / "eligible.txt"
        suppressed_path = self.data_dir / "suppressed.txt"
        eligible_path.write_text("eligible body", encoding="utf-8")
        suppressed_path.write_text("suppressed body", encoding="utf-8")

        agenda_downloader.log_pdf(
            self.conn,
            "Example City",
            "City Council",
            "Recent Agenda",
            "https://example.test/recent.pdf",
            str(eligible_path),
            metadata={
                "meeting_date": "2026-06-21",
                "notification_eligible": 1,
                "public_body_id": "200",
            },
        )
        agenda_downloader.log_pdf(
            self.conn,
            "Example City",
            "City Council",
            "Old Agenda",
            "https://example.test/old.pdf",
            str(suppressed_path),
            metadata={
                "meeting_date": "2026-06-01",
                "notification_eligible": 0,
                "public_body_id": "200",
            },
        )

        summarizer = FakeSummarizer(db_path=str(self.db_path), data_dir=str(self.data_dir))
        summarizer.process_unsummarized(city_filter="Example City")

        db = sqlite3.connect(self.db_path)
        try:
            rows = db.execute(
                "SELECT meeting_title, summarized FROM agendas ORDER BY meeting_title"
            ).fetchall()
        finally:
            db.close()
        self.assertEqual([("Old Agenda", 0), ("Recent Agenda", 1)], rows)
        self.assertEqual(1, len(summarizer.notifications))


if __name__ == "__main__":
    unittest.main()

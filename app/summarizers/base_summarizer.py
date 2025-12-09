import os, sqlite3, datetime, shutil, re
from pathlib import Path

class BaseSummarizer:
    def __init__(self, db_path=None, data_dir=None, discord_webhook=None):
        self.data_dir = data_dir or os.getenv("DATA_DIR", "/data")
        self.db_path = db_path or os.getenv("DB_PATH", os.path.join(self.data_dir, "council.db"))
        self.archive_root = os.path.join(self.data_dir, "archive")
        self.summary_root = os.path.join(self.data_dir, "summaries")
        self.discord_webhook = discord_webhook
        os.makedirs(self.archive_root, exist_ok=True)
        os.makedirs(self.summary_root, exist_ok=True)

    def make_nested_dirs(self, city, feed):
        archive_dir = os.path.join(self.archive_root, city, feed)
        summary_dir = os.path.join(self.summary_root, city, feed)
        os.makedirs(archive_dir, exist_ok=True)
        os.makedirs(summary_dir, exist_ok=True)
        return archive_dir, summary_dir

    def extract_text(self, pdf_path): raise NotImplementedError
    def summarize_text(self, text, title): raise NotImplementedError
    def notify(self, title, city, feed, doc_type, pdf_url, summary_path): pass

    def parse_meeting_date(self, filename):
        name = Path(filename).stem
        m1 = re.search(r"_(\d{2})(\d{2})(\d{4})", name)
        if m1:
            month, day, year = m1.groups()
            try:
                return datetime.date(int(year), int(month), int(day)).isoformat()
            except: pass
        m2 = re.search(r"_(\d{4})(\d{2})(\d{2})", name)
        if m2:
            year, month, day = m2.groups()
            try:
                return datetime.date(int(year), int(month), int(day)).isoformat()
            except: pass
        return None

    def process_unsummarized(self, city_filter=None):
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        query = "SELECT id, city, feed_name, local_path, meeting_title, pdf_url FROM agendas WHERE summarized=0"
        params = []
        if city_filter:
            query += " AND city=?"
            params.append(city_filter)
        cur.execute(query, params)
        rows = cur.fetchall()
    
        print(f"[DEBUG] Found {len(rows)} unsummarized agendas")

        for id_, city, feed, pdf_path, title, pdf_url in rows:
            print(f"[DEBUG] Processing: {city}/{feed} - {title}")
            try:
                text = self.extract_text(pdf_path)
                summary = self.summarize_text(text, title)
                archive_dir, summary_dir = self.make_nested_dirs(city, feed)
                base_name = Path(pdf_path).stem
                meeting_date = self.parse_meeting_date(base_name)
                summarized_at = datetime.datetime.now()
                doc_type = self.determine_doc_type(pdf_path)

                rel_archive = os.path.relpath(os.path.join(archive_dir, Path(pdf_path).name), start=summary_dir)
                summary_filename = base_name + "_summary.md"
                summary_path = os.path.join(summary_dir, summary_filename)

                with open(summary_path, "w", encoding="utf-8") as f:
                    f.write("---\n")
                    f.write(f"title: \"{title}\"\ncity: \"{city}\"\nfeed: \"{feed}\"\n")
                    f.write(f"source_url: \"{pdf_url}\"\narchive_path: \"{rel_archive}\"\n")
                    if meeting_date:
                        f.write(f"meeting_date: \"{meeting_date}\"\n")
                    f.write(f"summarized_at: \"{summarized_at.isoformat()}\"\n---\n\n")
                    f.write(f"# {title}\n\n")
                    f.write(f"**City:** {city}  \n**Feed:** {feed}  \n")
                    if meeting_date:
                        f.write(f"**Meeting Date:** {meeting_date}  \n")
                    f.write(f"**Summarized:** {summarized_at.strftime('%Y-%m-%d %H:%M')}  \n")
                    f.write(f"**Original Source:** [View on city site]({pdf_url})  \n")
                    f.write(f"**Local Copy:** [View archived PDF]({rel_archive})\n\n---\n\n")
                    f.write(summary.strip() + "\n")

                cur.execute(
                    "UPDATE agendas SET summarized=1, summary_path=?, summary_timestamp=? WHERE id=?",
                    (summary_path, summarized_at.isoformat(), id_)
                )
                conn.commit()
                shutil.move(pdf_path, os.path.join(archive_dir, Path(pdf_path).name))
                print(f"[DEBUG] About to call notify()")
                print(f"[DEBUG] discord_webhook = {self.discord_webhook}")
                self.notify(title, city, feed, doc_type, pdf_url, summary_path)
                print(f"[DEBUG] notify() completed")
                print(f"✅ {city}/{feed}: {summary_filename}")

            except Exception as e:
                print(f"[ERROR] {city}/{feed}: {e}")

        conn.close()

    def determine_doc_type(self, pdf_path):
        name = Path(pdf_path).name.lower()
        if "agenda__" in name:
            return "Agenda"
        if "minutes__" in name:
            return "Minutes"
        return "Document"

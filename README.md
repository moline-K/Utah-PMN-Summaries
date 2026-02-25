# Utah PMN Agenda Downloader

This project scrapes Utah Public Meeting Notice (PMN) public body notices, stores notice-level records in SQLite, summarizes unsummarized items with OpenAI, and sends notifications (Teams/Discord).

## What this repo uses
- Downloader entrypoint: `app/agenda_downloader.py`
- Scraper: `app/scrapers/utah_pmn.py`
- Summarizer entrypoint: `app/run_summarizer.py`
- DB (default): `/data/utah_pmn.db`
- PMN config template: `pmn_sources.example.yaml`

## Quick start (Docker)
1. Copy env template:
```bash
cp .env.example .env
```
2. Set at least:
- `OPENAI_API_KEY`
- `MS_TEAMS_WEBHOOK` (or `MS_TEAMS_WEBHOOK_URL`) if using Teams notifications
3. Edit `pmn_sources.example.yaml` with your PMN public body sources.
4. Run downloader:
```bash
docker compose run --rm agenda_downloader
```
5. Run summarizer:
```bash
docker compose run --rm agenda_summarizer
```

## Prompt customization
- Default prompt file is tracked at `prompt_template.default.txt`.
- Runtime uses `PROMPT_TEMPLATE_PATH` (default `/app/prompt_template.default.txt`).
- Local custom prompt can be created as `custom_summary_prompt.txt` (ignored by git), then point `PROMPT_TEMPLATE_PATH` to it.
- Supported placeholders in prompt templates:
  - `{{AGENDA_TEXT}}`
  - `{{TITLE}}`

## PMN-only repo
- Legacy scrapers (CivicPlus/Granicus/Conway) are removed.
- `cities.yaml` is removed.
- Summarizer targets are derived from PMN `entity` values in `pmn_sources.example.yaml`.

## DB model
Table: `agendas` (notice-level records).

Compatibility columns used by summarizer remain:
- `city`, `feed_name`, `meeting_title`, `meeting_date`, `pdf_url`, `local_path`, `summarized`, `summary_path`, `summary_timestamp`

PMN-specific columns include:
- `notice_id`, `notice_url`, `source_name`, `government_type`, `entity`, `public_body`, `public_body_id`
- `event_datetime_raw`, `notice_tags`, `description_agenda`
- `attachment_count`, `attachment_urls`, `attachment_category`, `attachment_date_added`

## Notes
- `city` maps to PMN `entity`.
- `feed_name` maps to PMN `public_body`.
- One DB row is written per notice.

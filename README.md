# Utah PMN Agenda Downloader

This project scrapes Utah Public Meeting Notice (PMN) public body notices, stores notice-level records in SQLite, summarizes unsummarized items with OpenAI, and sends notifications to Teams or Discord.

## What it does
- Scrapes one PMN public body feed per configured source.
- Stores one SQLite row per notice with PMN metadata, including `entity`, `entity_id`, `public_body`, `public_body_id`, `county`, `route_key`, `mention_key`, and event date/time fields.
- Downloads the best attachment when present, or stores the PMN `Description/Agenda` text when no attachment exists.
- Generates Markdown summaries.
- Routes Teams notifications by channel/group with fallback to a catch-all channel.

## Config files
- Local-only config files:
  - `pmn_selection.yaml`
  - `pmn_sources.yaml`
  - `MS_Teams_channels.yaml`
- Tracked examples:
  - `pmn_selection.example.yaml`
  - `pmn_sources.example.yaml`
  - `MS_Teams_channels.example.yaml`

The real YAML files are intentionally ignored by git. Copy the examples first:

```bash
cp pmn_selection.example.yaml pmn_selection.yaml
cp MS_Teams_channels.example.yaml MS_Teams_channels.yaml
cp .env.example .env
```

## PMN selection workflow
`pmn_selection.yaml` is the human-edited manifest. It groups multiple public bodies under one entity and assigns each entity to a Teams routing group.

Regenerate `pmn_sources.yaml` after editing `pmn_selection.yaml`:

```bash
docker compose run --rm -v "$PWD":/workspace -w /workspace agenda_downloader \
  python app/generate_pmn_sources.py \
  --selection pmn_selection.yaml \
  --channels MS_Teams_channels.yaml \
  --catalog "data/previous work/all_bodies.json" \
  --out pmn_sources.yaml
```

The generator validates:
- `entity_id`
- `public_body_id`
- duplicate generated source names
- duplicate curated `public_body_id` values
- unknown `route_key` values
- mismatches against the saved PMN catalog snapshot

## Teams routing
`MS_Teams_channels.yaml` defines:
- `default_channel`
- `channels.<route_key>.display_name`
- `channels.<route_key>.active`
- `channels.<route_key>.webhook_env`
- optional `mention_groups.<mention_key>`

Routing behavior:
- If the configured `route_key` is active and its webhook env var is set, the summary goes there.
- If the route is missing, inactive, or missing a webhook, the summary goes to the default catch-all channel.
- If `TEAMS_CHANNELS_CONFIG_PATH` is unset, the app falls back to the legacy single-webhook behavior using `MS_TEAMS_WEBHOOK` or `MS_TEAMS_WEBHOOK_URL`.

Mention behavior:
- v1 supports optional Teams user mentions from `mention_groups`.
- v1 does not implement Teams tag mentions through Incoming Webhooks.

## Event dates in summaries
Teams cards and summary Markdown now include the actual PMN notice/event date fields from the notice metadata:
- `Meeting Date` uses the normalized PMN event date when available.
- `Event Date/Time` includes the raw PMN event datetime string when available.
- `Summarized` remains separate from the actual notice/event date.

## Runtime
Default runtime paths:
- `PMN_CONFIG_PATH=/app/pmn_sources.yaml`
- `TEAMS_CHANNELS_CONFIG_PATH=/app/MS_Teams_channels.yaml`
- `DB_PATH=/data/utah_pmn.db`
- `PROMPT_TEMPLATE_PATH=/app/prompt_template.default.txt`

Run the pipeline:

```bash
docker compose run --rm agenda_downloader
docker compose run --rm agenda_summarizer
```

Or use the helper script:

```bash
./agenda_pipeline.sh
```

## Verification
Run unit tests:

```bash
docker compose run --rm -v "$PWD":/workspace -w /workspace agenda_downloader \
  python -m unittest discover -s tests
```

## GitHub Actions Docker CI/CD
GitHub Actions now builds and tests the Docker image automatically:
- Pull requests to `main` run a Docker build plus the unit test suite.
- Pushes to `main`, version tags like `v1.2.3`, and manual workflow runs publish the image to GitHub Container Registry.

Published image location:

```bash
ghcr.io/<owner>/<repo>:latest
ghcr.io/<owner>/<repo>:<branch>
ghcr.io/<owner>/<repo>:sha-<commit>
```

For this repository, that means the default image path will be:

```bash
ghcr.io/moline-k/utah-pmn-summaries:latest
```

Notes:
- The workflow uses the built-in `GITHUB_TOKEN`, so no separate registry password is required for publishing to `ghcr.io`.
- If this is the first package published from the repo, GitHub may require package visibility/settings to be adjusted in the repository or package settings page.
- To publish a release-tagged image, push a tag such as `v1.0.0`.

## Notes
- `city` in the database maps to PMN `entity`.
- `feed_name` maps to PMN `public_body`.
- The PMN catalog under `data/previous work/` is treated as a refreshable snapshot, not a live dependency.

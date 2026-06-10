# Utah PMN Agenda Downloader

This project scrapes Utah Public Meeting Notice (PMN) public body notices, stores notice-level records in SQLite, summarizes unsummarized items with OpenAI, and sends notifications to Teams or Discord.

## What it does
- Scrapes one PMN public body feed per configured source.
- Stores one SQLite row per notice with PMN metadata, including `entity`, `entity_id`, `public_body`, `public_body_id`, `channel_name`, `tag_name`, and event date/time fields.
- Downloads the best attachment when present, or stores the PMN `Description/Agenda` text when no attachment exists.
- Generates Markdown summaries.
- Sends Teams notifications through one Power Automate flow webhook.

## Config files
- Local-only config files:
  - `pmn_selection.yaml`
  - `pmn_sources.yaml`
- Tracked examples:
  - `pmn_selection.example.yaml`
  - `pmn_sources.example.yaml`

The real YAML files are intentionally ignored by git. Copy the examples first:

```bash
cp pmn_selection.example.yaml pmn_selection.yaml
cp .env.example .env
```

## PMN selection workflow
`pmn_selection.yaml` is the human-edited manifest. It groups multiple public bodies under one entity and assigns each entity to a Teams `channel_name`.

Regenerate `pmn_sources.yaml` after editing `pmn_selection.yaml`:

```bash
docker compose run --rm pmn_generator \
  --selection pmn_selection.yaml \
  --catalog "data/previous work/all_bodies.json" \
  --out pmn_sources.yaml
```

Or use the wrapper script:

```bash
./regenerate_pmn_sources.sh
```

The wrapper tries, in order:

1. local `python3` with `PyYAML`
2. `docker compose` using the local `pmn_generator` service
3. a plain Docker image fallback

You can override the Docker image used by the fallback:

```bash
PMN_GENERATOR_IMAGE=ghcr.io/moline-k/utah-pmn-summaries:latest ./regenerate_pmn_sources.sh
```

Do not run the generator through `agenda_downloader`. That service bind-mounts `./pmn_sources.yaml` into `/app/pmn_sources.yaml` for runtime, so if the host file does not exist Docker can create a directory named `pmn_sources.yaml` instead of the YAML file you want.

If that already happened, remove the mistaken directory on the host and rerun the generator:

```bash
rmdir pmn_sources.yaml
docker compose run --rm pmn_generator \
  --selection pmn_selection.yaml \
  --catalog "data/previous work/all_bodies.json" \
  --out pmn_sources.yaml
```

If the directory is not empty, inspect it first and remove it deliberately before rerunning the generator.

The generator validates:
- `entity_id`
- `public_body_id`
- duplicate generated source names
- duplicate curated `public_body_id` values
- mismatches against the saved PMN catalog snapshot

## Teams routing
Routing behavior:
- `channel_name` from `pmn_sources.yaml` is sent directly to Power Automate.
- `tag_name` is sent directly when present.
- If `tag_name` is omitted, the notifier falls back to `entity` as the Teams tag display name.
- The Power Automate flow resolves channel and tag display names and fails the run if a name does not match exactly once.

Required Teams environment:
- `TEAMS_FLOW_WEBHOOK_URL` or `TEAMS_FLOW_WEBHOOK`

## Event dates in summaries
Teams cards and summary Markdown now include the actual PMN notice/event date fields from the notice metadata:
- `Meeting Date` uses the normalized PMN event date when available.
- `Event Date/Time` includes the raw PMN event datetime string when available.
- `Summarized` remains separate from the actual notice/event date.

## Runtime
Default runtime paths:
- `PMN_CONFIG_PATH=/app/pmn_sources.yaml`
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

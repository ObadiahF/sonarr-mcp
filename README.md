# sonarr-mcp

A FastMCP server for [Sonarr v5](https://github.com/Sonarr/Sonarr) — built around one annoying problem: **stuck imports**.

Sonarr drops a download into a folder, parses the filename, fails to match it to a series or episode, and then... sits there. The download client thinks it's done, Sonarr thinks something's wrong, and the file just rots in your queue with a yellow "Manual Import Required" badge.

`sonarr-mcp` exposes a small set of agent-friendly tools so a model can drive Sonarr's UI workflow over the API: surface the stuck items, fuzzy-match each file against the library, propose a resolution with a confidence score, and either resolve or blocklist+search.

The library/queue/calendar/history tools are also there so the same MCP server is useful for the other 80% of "what's going on with my Sonarr?" questions.

## Why this exists

I have a Sonarr instance on a homelab box. A handful of times a week, *something* gets stuck — a release group Sonarr can't parse, a partially-named file from a renamed series, a quality profile mismatch. Fixing it via the web UI is six clicks of "did I really mean it?". With this MCP, my agent can say:

> "There are 3 stuck imports. The first one is *The Bear S02E05* — high confidence (0.92), I'll resolve it. The second one is unparseable junk — I'll blocklist it and let Sonarr re-search."

That's the entire pitch.

## Install

```bash
git clone https://github.com/ObadiahF/sonarr-mcp.git
cd sonarr-mcp
pip install -e .
# or: uv pip install -e .
```

Python 3.11+. Runtime deps are just `mcp[cli]`, `httpx`, and `pydantic`.

## Configure

Get your Sonarr API key from **Settings → General → Security → API Key** in the Sonarr UI.

Drop it into `~/.openclaw/.sonarr-creds.json`:

```json
{
  "baseUrl": "http://homelab.local:8989",
  "apiKey": "your-sonarr-api-key-here"
}
```

A starter file lives at [`config.example.json`](./config.example.json).

Overrides:
- `SONARR_CONFIG=/path/to/file.json` — use a different config file.
- `SONARR_BASE_URL` / `SONARR_API_KEY` — env vars beat file contents (handy for Docker / CI).

## Run

```bash
python -m sonarr_mcp
# or
sonarr-mcp
```

The server speaks MCP over stdio. Smoke test against your live Sonarr first:

```bash
python scripts/smoke_test.py
```

## Claude Desktop / MCP client config

Add to your client's MCP config (e.g. `~/Library/Application Support/Claude/claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "sonarr": {
      "command": "python",
      "args": ["-m", "sonarr_mcp"],
      "env": {
        "SONARR_CONFIG": "/home/you/.openclaw/.sonarr-creds.json"
      }
    }
  }
}
```

If you installed the console script:

```json
{
  "mcpServers": {
    "sonarr": { "command": "sonarr-mcp" }
  }
}
```

## Tools

### Stuck-import workflow (the headline feature)

| Tool | What it does |
|---|---|
| `get_stuck_imports` | Queue items in `warning`/`error` state, joined with the matching `/manualimport` candidates Sonarr already knows about. |
| `suggest_import_resolution(file_path)` | Fuzzy-match a file against the library. Returns ranked `{confidence, series, episode, submitPayload}` candidates. |
| `resolve_import(payload, import_mode="auto")` | Pass the `submitPayload` from above (or a list of them) to actually move/copy the file in. |
| `blocklist_and_search(queue_id, skip_redownload=False)` | Drop the queue item, blocklist the release, and let Sonarr go find another. |
| `delete_stuck(queue_id, remove_from_client=True)` | Drop the queue item without blocklisting (use this when you want a retry, not a re-search). |

### Library

| Tool | What it does |
|---|---|
| `list_series(monitored_only=False)` | All series in the library (slim payload — no images, no scene mappings). |
| `get_series(series_id)` | One series by Sonarr id. |
| `lookup_series(term)` | Search TVDB via Sonarr's lookup endpoint. |
| `add_series(tvdb_id, quality_profile_id, root_folder_path, season_folder=True, monitor="all", ...)` | Add a new series. `monitor` ∈ `{all, future, missing, existing, firstSeason, latestSeason, pilot, none}`. |
| `update_series_monitoring(series_id, monitored)` | Toggle the series-level monitor flag. |
| `delete_series(series_id, delete_files=False)` | Remove a series; optionally nukes the on-disk files. |
| `list_episodes(series_id, season_number=None)` | All episodes for a series, optionally one season. |
| `monitor_episodes(episode_ids, monitored)` | Bulk monitor toggle. |

### Search & discovery

| Tool | What it does |
|---|---|
| `list_calendar(start, end, include_series=True, include_unmonitored=False)` | Upcoming episodes (defaults to today → +7d). |
| `list_wanted_missing(page=1, page_size=20, monitored=True)` | Episodes Sonarr is still looking for. |
| `search_episode(episode_ids)` | Trigger an `EpisodeSearch` command. |
| `search_season(series_id, season_number)` | Trigger a `SeasonSearch` command. |
| `search_series(series_id)` | Trigger a `SeriesSearch` command (every monitored episode). |
| `rss_sync` | Trigger an `RssSync`. |
| `refresh_series(series_id=None)` | `RefreshSeries` for one (or all) series. |
| `run_command(name, body=None)` | Generic escape hatch for any Sonarr command. |

### Ops

| Tool | What it does |
|---|---|
| `queue_status` | Counts + warning/error flags from `/queue/status`. |
| `list_queue(include_unknown=True, page=1, page_size=50)` | Paginated queue listing. |
| `list_history(series_id=None, event_type=None, since=None)` | Recent activity. `event_type` accepts names like `grabbed` / `downloadFailed` / `downloadFolderImported`. |
| `health_summary` | One-shot system snapshot: status + health checks + diskspace. |
| `list_root_folders` | Configured root folders with free space. |
| `list_quality_profiles` | Quality profiles (you'll need an id when calling `add_series`). |

## Example prompts

- *"What's stuck in my Sonarr right now? For anything you're 80%+ confident about, resolve it."*
- *"Add `tvdbId=121361` to my library on the first quality profile, monitor everything, search for missing."*
- *"List the next two weeks of new episodes."*
- *"Show me anything that failed to download in the last 24 hours."*
- *"What's my disk space looking like?"*

## Homelab tips

**systemd user unit** — drop into `~/.config/systemd/user/sonarr-mcp.service`:

```ini
[Unit]
Description=sonarr-mcp
After=network-online.target

[Service]
ExecStart=%h/.local/bin/sonarr-mcp
Restart=on-failure
Environment=SONARR_CONFIG=%h/.openclaw/.sonarr-creds.json

[Install]
WantedBy=default.target
```

Then `systemctl --user enable --now sonarr-mcp`.

**Docker sidecar** — easiest is a tiny image alongside your Sonarr container, sharing the same Docker network so `baseUrl` can be `http://sonarr:8989`. The MCP itself only needs an outbound HTTP connection to Sonarr; no ports to publish.

## Development

```bash
pip install -e ".[dev]"
pytest
```

Tests use [respx](https://lundberg.github.io/respx/) to mock the Sonarr HTTP API — no live instance needed. CI runs on every push/PR (see [`.github/workflows/test.yml`](./.github/workflows/test.yml)).

The project layout:

```
src/sonarr_mcp/
  config.py       # Loader for ~/.openclaw/.sonarr-creds.json
  client.py       # Async httpx wrapper; HTTP errors come back as data
  server.py       # FastMCP app + tool registration
  tools/
    imports.py    # The headline feature — stuck-import workflow
    series.py
    episodes.py
    calendar.py
    queue.py
    history.py
    commands.py
    system.py
```

## Design decisions worth flagging

- **Errors are data.** Every tool returns `{"error": "...", "status": <int>, "body": ...}` instead of raising. Agents handle that better than exceptions.
- **Slim payloads.** Sonarr resources are *huge* (every series ships its full image list, scene mappings, alternate titles…). Each tool maps down to the fields the agent actually uses.
- **Confidence scoring buckets.** `suggest_import_resolution` uses fixed buckets (1.0 / 0.7 / 0.4 / 0.0) rather than a continuous score so the agent can apply simple thresholds. See `score_candidate` for the rules.
- **Single shared httpx client.** Built once at server start, kept for the process lifetime — connection pooling is on, and tool code stays tidy.

## License

MIT — see [LICENSE](./LICENSE).

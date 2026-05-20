# Running `dip_news.py`

`dip_news.py` reads all secrets from **environment variables**. In this example they are stored as plain text files inside `keys/` folder — add your own keys under the file names listed in step 3 to run the same pipeline locally, or supply the same values as repo / CI secrets (or via a `.env` file, your shell, etc.).

Then you only need to:

1. install the Python deps,
2. load the secrets into env vars before running the script (from `keys/`, from CI secrets, or any other source),
3. run `python dip_news.py`.

## 1. Pipeline workflow

`dip_news.py` runs a chain of stages. Each stage reads its input from one Google Drive subfolder of the project and writes its output to another. The folder IDs are stored in `FOLDERS_SANDBOX` / `FOLDERS_MAIN`; the names below are the keys used in code (e.g. `folder["1 news_jsons"]`). Under the diagram, a detailed textual explanation (stage‑by‑stage summary)

```
   Sources (live news sites, last `days_before + 1` days)
     Kommersant (econ / world / markets), Vedomosti, RBC,
     Agroinvestor, RIA, Autostat
                       │
                       v
   ┌──────────────────────────────────────────────────────┐
1. │ SCRAPE NEWS SITES                                    │
   │ fetch_kom / fetch_ved / fetch_rbc /                  │
   │ fetch_agro / fetch_ria / fetch_autostat              │
   │                                                      │
   │ Action: for each site, walk its listing pages,       │
   │ collect (title, url, publication date) for every     │
   │ article from the last 1-2 calendar days, drop        │
   │ anything older.                                      │
   │ Output rows: {title, url, published_date}.           │
   └──────────────────────┬───────────────────────────────┘
                          v
              [ 1 news_jsons ]
              kom_econ.json, kom_world.json, kom_markets.json,
              ved.json, rbc.json, agro.json, ria.json, autostat.json
                          │
                          │  loop:  section* ∈ { world, rus, prices } 
                          v  *subset of the scraped sources, it produces its own weekly list / report. 
   ┌──────────────────────────────────────────────────────┐
2. │ FILTER & MERGE INTO WEEKLY LIST                      │
   │ create_news_lists(section)                           │
   │                                                      │
   │ Action: for each source JSON listed in               │
   │ section_to_files[section], send its headlines to     │
   │ an LLM together with the section prompt; it returns  │
   │ only items that match the section topic.             │
   │ Then dedupe by URL against the weekly accumulator    │
   │ and re-attach published_date from the raw feed.      │
   │                                                      │
   │ Prompt: 0_prompts/lists_<section>.txt                │
   └──────────────────────┬───────────────────────────────┘
                          v  cumulative weekly <section>.json
        [ 2 4 new_lists_json ] <──── read back on non-Saturday days
                                     (Saturday resets the week)
                          │
                          v
   ┌──────────────────────────────────────────────────────┐
3. │ RE-RANK BY IMPORTANCE & KEEP TOP-40                  │
   │ prioritise(section)                                  │
   │                                                      │
   │ Action: send the full weekly list to an LLM, which   │
   │ assigns each headline a 0-10 importance score.       │
   │ Sort by score desc, save the full graded list as a   │
   │ debug copy, then cut to the 40 best and drop the     │
   │ scores so the working list stays compact.            │
   │                                                      │
   │ Prompt: 0_prompts/prioritise_<section>.txt           │
   └──────┬───────────────────────────────────────────┬───┘
          │                                           │
          │ debug copy                                │ trimmed top-40
          │  (items + grades)                         │  overwrites
          v                                           v
[ 3 news_lists_json_grade ]                  [ 2 4 new_lists_json ]
                                                      │
                                                      v
   ┌──────────────────────────────────────────────────────┐
4. │ RENDER NUMBERED .TXT & POST LINK TO TELEGRAM         │
   │ design_wo_llm(section)                               │
   │                                                      │
   │ Action: plain-Python formatter — walks the top-40    │
   │ list and prints                                      │
   │     "N. <title> (published: YYYY-MM-DD)              │
   │      <url>"                                          │
   │ for each item, producing one .txt per section.       │
   │                                                      │
   │ Fallback design(section) uses the LLM with prompt    │
   │ 0_prompts/design.txt; runs only if plain fails.      │
   │                                                      │
   │ telegram_lists() posts a link to the Drive folder.   │
   └──────────────────────┬───────────────────────────────┘
                          v  numbered <section>.txt
                   [ 5 news_lists ]
                          │
                          v
                  telegram_lists()  ──>  Telegram

═══════════════ Thursday only  (datetime.today().weekday() == 3) ═══════════════

                  [ 2 4 new_lists_json/<section>.json ]
                          │
                          v
   ┌──────────────────────────────────────────────────────┐
5. │ GROUP TOP-40 INTO 4 WEEKLY THEMES                    │
   │ choose_top_urls(section)                             │
   │                                                      │
   │ Action: ask an LLM to pick 4 themes for the week     │
   │ and assign up to 3 articles from the top-40 list to  │
   │ each theme. Every returned item is validated against │
   │ the NewsItem (Pydantic) model; invalid rows dropped. │
   │                                                      │
   │ Prompt: 0_prompts/top_<section>.txt                  │
   └──────────────────────┬───────────────────────────────┘
                          v  {theme, title, url}
                    [ 6 news_top ]
                          │
                          v
   ┌──────────────────────────────────────────────────────┐
6. │ DOWNLOAD & CLEAN ARTICLE BODIES                      │
   │ read_top_urls(section)                               │
   │                                                      │
   │ Action: HTTP GET each article URL (through PROXY),   │
   │ parse the HTML and run extract_main_text — keep up   │
   │ to 5 paragraphs / 3000 chars, drop cookie banners,   │
   │ ads and boilerplate. Attach the cleaned text to      │
   │ each item.                                           │
   └──────────────────────┬───────────────────────────────┘
                          v  {title, url, theme, text}
                  [ 7 news_top_texts ]
                          │
                          v
   ┌──────────────────────────────────────────────────────┐
7. │ FINAL BULLET REPORT & POST TO TELEGRAM               │
   │ create_bullets(section)                              │
   │                                                      │
   │ Action: feed the cleaned article texts to an LLM     │
   │ in an analyst persona (temperature = 0.1); the LLM   │
   │ goes theme by theme and emits the final bullet-point │
   │ report. The .txt is written both to Drive and to     │
   │ the local cwd, then telegram_bullets() posts the     │
   │ file to Telegram.                                    │
   │                                                      │
   │ Prompt: 0_prompts/bullets_<section>.txt              │
   └──────────────────────┬───────────────────────────────┘
                          v  report_<section>.txt
              [ 8 news_final ]   +   local copy in news/ folder
                          │
                          v
                 telegram_bullets()  ──>  Telegram
```

### Stage-by-stage summary

1. **Scrape** -- `fetch_kom`, `fetch_ved`, `fetch_rbc`, `fetch_agro`, `fetch_ria`, `fetch_autostat`
  - **Input:** live news sites (Kommersant, Vedomosti, RBC, Agroinvestor, RIA, Autostat) for the last `days_before + 1` days (default = 2 calendar days).
  - **Output:** one raw JSON per source in `**1 news_jsons`** (`kom_econ.json`, `kom_world.json`, `kom_markets.json`, `ved.json`, `rbc.json`, `agro.json`, `ria.json`, `autostat.json`). Each item: `{title, url, published_date}`.
2. **Filter & merge** -- `create_news_lists(section)` for `section in {"world", "rus", "prices"}`
  - **Input:** for each section, the list of source JSONs from `**1 news_jsons`** declared in `section_to_files[section]`; plus the existing weekly `**2 4 new_lists_json/<section>.json`** from previous days (only on non-Saturdays -- Saturday resets the week); plus the section prompt from `**0_prompts/lists_<section>.txt`**.
  - **What it does:** sends each source JSON to DeepSeek with the section prompt, keeps only relevant items, deduplicates by URL against what's already accumulated, re-attaches `published_date` from the raw feed.
  - **Output:** updated `**2 4 new_lists_json/<section>.json`** (cumulative weekly list).
3. **Re-rank, keep top-40** -- `prioritise(section)`
  - **Input:** `**2 4 new_lists_json/<section>.json`** + `**0_prompts/prioritise_<section>.txt`**.
  - **What it does:** DeepSeek grades each item 0--10; sorted descending; trimmed to 40.
  - **Output:**
    - debug copy with grades to `**3 news_lists_json_grade/<section>.json`**;
    - trimmed `{title, url, published_date}` overwrites `**2 4 new_lists_json/<section>.json`**.
4. **Render numbered list + notify** -- `design_wo_llm(section)` (fallback `design(section)`)
  - **Input:** `**2 4 new_lists_json/<section>.json`** (`design` also uses `**0_prompts/design.txt`**).
  - **What it does:** formats each item as `N. <title> (published: YYYY-MM-DD)\n<url>`. `design_wo_llm` is plain Python; `design` calls the LLM (used only if the plain version fails).
  - **Output:** `**5 news_lists/<section>.txt`**, then `telegram_lists()` posts a link to that folder in Telegram.
5. **Pick top themes (Thursday only)** -- `choose_top_urls(section)`
  - **Input:** `**2 4 new_lists_json/<section>.json`** + `**0_prompts/top_<section>.txt`**.
  - **What it does:** DeepSeek groups the news into 4 themes (max 3 articles each); items validated via the `NewsItem` Pydantic model.
  - **Output:** `**6 news_top/<section>.json`** with `{theme, title, url}` entries.
6. **Download article bodies (Thursday only)** -- `read_top_urls(section)`
  - **Input:** `**6 news_top/<section>.json`**.
  - **What it does:** fetches every article URL, runs `extract_main_text` to keep meaningful paragraphs (up to 5 paragraphs / 3000 chars), filters cookie/ad text.
  - **Output:** `**7 news_top_texts/<section>.json`** with `{title, url, theme, text}`.
7. **Final bullets + notify (Thursday only)** -- `create_bullets(section)`
  - **Input:** `**7 news_top_texts/<section>.json`** + `**0_prompts/bullets_<section>.txt`**.
  - **What it does:** DeepSeek (analyst persona, `temperature=0.1`) produces the final bullet points.
  - **Output:** `**8 news_final/report_<section>.txt`** on Drive + a local copy `report_<section>.txt` in the current working directory, then `telegram_bullets()` posts to Telegram.

### Drive folder names referenced in code


| Key in `folder[...]`      | Stage that writes here                                                                                     |
| ------------------------- | ---------------------------------------------------------------------------------------------------------- |
| `0_prompts`               | (read-only) prompt templates `lists_*.txt`, `prioritise_*.txt`, `top_*.txt`, `bullets_*.txt`, `design.txt` |
| `1 news_jsons`            | scrapers (`fetch_`*)                                                                                       |
| `2 4 new_lists_json`      | `create_news_lists` and `prioritise` (final trimmed list)                                                  |
| `3 news_lists_json_grade` | `prioritise` (debug copy with grades)                                                                      |
| `5 news_lists`            | `design_wo_llm` / `design` (numbered `.txt`)                                                               |
| `6 news_top`              | `choose_top_urls`                                                                                          |
| `7 news_top_texts`        | `read_top_urls`                                                                                            |
| `8 news_final`            | `create_bullets`                                                                                           |


## 2. Install dependencies (**or upload yml, requirements.txt and run it via GitHub Actions**)

From the repo root, create a virtual environment (if you don't have one yet) and install `requirements.txt` into it.

Windows (PowerShell):

```powershell
python -m venv .venv          # first time only
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

macOS / Linux (bash):

```bash
python3 -m venv .venv         # first time only
source .venv/bin/activate
python -m pip install -r requirements.txt
```

If `Activate.ps1` is blocked on Windows, allow user-scoped scripts once:

```powershell
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
```

## 3. What env vars the script needs

These are read from the top of `dip_news.py` (around line 39, where `USE_SANDBOX = True` is hard-coded). The right column shows the file name used in this example's `keys/` layout — you can put your own values there, or supply them any other way (CI secrets, `.env`, shell exports, secret manager, etc.).


| Env var                                            | What it is                                                | Example file in `keys/`                                                          |
| -------------------------------------------------- | --------------------------------------------------------- | -------------------------------------------------------------------------------- |
| `FOLDERS_SANDBOX` (used when `USE_SANDBOX = True`) | JSON string with Drive folder IDs for the sandbox project | `keys/folders_sandbox.txt`                                                       |
| `FOLDERS_MAIN`                                     | Same, for production (used when `USE_SANDBOX = False`)    | `keys/folders_main.txt`                                                          |
| `PROXY`                                            | HTTPS proxy URL (leave empty if not needed)               | `keys/proxy.txt`                                                                 |
| `GOOGLE_TOKEN_B64`                                 | Base64-encoded OAuth user-token JSON for Google Drive     | `keys/GOOGLE_TOKEN_B64.txt`                                                      |
| `DEEPSEEK_API_KEY`                                 | DeepSeek API key                                          | `keys/deepseek_api_key.txt`                                                      |
| `TELEGRAM_BOT_TOKEN`                               | Telegram bot token                                        | `keys/TELEGRAM_BOT_TOKEN.txt` (sandbox) · `keys/A/TELEGRAM_BOT_TOKEN.txt` (prod) |
| `TELEGRAM_CHAT_ID`                                 | Telegram chat ID where reports are posted                 | `keys/TELEGRAM_CHAT_ID.txt` (sandbox) · `keys/A/TELEGRAM_CHAT_ID.txt` (prod)     |


> The `keys/` layout is just one convention bundled in this example. `dip_news.py` itself only ever reads environment variables — wherever the values come from is up to you.

## 4. Quickstart on Windows — bundled `run_local.ps1` shell-setup helper

A helper script `run_local.ps1` sits next to `dip_news.py`. It only **prepares the shell** for you: reads every file under `keys/`, exports them as env vars in the current PowerShell session, and activates `.\.venv` (if it exists). It does **not** launch the pipeline — once it returns, you can run `python dip_news.py` yourself (see section 6 for the actual run commands and stage modes).

```powershell
.\run_local.ps1
# env vars + .venv are now loaded in this shell session — see section 6 to start the pipeline
```

Switch between sandbox and production by flipping the `$useSandbox = $true` line at the top of `run_local.ps1`.

## 5. Set env vars manually

Use this if you don't want the launcher, you're not on Windows, or you'd rather pull secrets from somewhere other than `keys/`.

Windows (PowerShell):

```powershell
$env:FOLDERS_SANDBOX    = (Get-Content -Raw .\keys\folders_sandbox.txt).Trim()
$env:PROXY              = (Get-Content -Raw .\keys\proxy.txt).Trim()
$env:GOOGLE_TOKEN_B64   = (Get-Content -Raw .\keys\GOOGLE_TOKEN_B64.txt).Trim()
$env:DEEPSEEK_API_KEY   = (Get-Content -Raw .\keys\deepseek_api_key.txt).Trim()
$env:TELEGRAM_BOT_TOKEN = (Get-Content -Raw .\keys\TELEGRAM_BOT_TOKEN.txt).Trim()
$env:TELEGRAM_CHAT_ID   = (Get-Content -Raw .\keys\TELEGRAM_CHAT_ID.txt).Trim()

python .\dip_news.py
```

macOS / Linux (bash):

```bash
export FOLDERS_SANDBOX="$(cat ./keys/folders_sandbox.txt)"
export PROXY="$(cat ./keys/proxy.txt)"
export GOOGLE_TOKEN_B64="$(cat ./keys/GOOGLE_TOKEN_B64.txt)"
export DEEPSEEK_API_KEY="$(cat ./keys/deepseek_api_key.txt)"
export TELEGRAM_BOT_TOKEN="$(cat ./keys/TELEGRAM_BOT_TOKEN.txt)"
export TELEGRAM_CHAT_ID="$(cat ./keys/TELEGRAM_CHAT_ID.txt)"

python ./dip_news.py
```

Replace any `Get-Content` / `cat` line with a literal value or your secret-manager command of choice (`gh secret`, `op read`, `aws ssm get-parameter`, GitHub Actions `${{ secrets.* }}`, etc.).

## 6. Run the pipeline (full or single stage)

Once the env vars are loaded (sections 4 / 5) and `.venv` is active, launch the pipeline yourself with one of the commands below. By default the script walks through every stage of the diagram in order; pass `--stage` (CLI flag) or set the `STAGE` env var to restrict to specific stages — multiple stages can be chained.

### Run command

```bash
#don't foreget to set env before (4 spep .\run_local.ps1 - for local)
# default: run every stage (Thursday-only stages still gated by weekday)
python dip_news.py

# run a single stage
python dip_news.py --stage scrape
python dip_news.py --stage prioritise

# chain several stages, in the order you list them
python dip_news.py --stage lists prioritise design

# bypass the Thursday gate
python dip_news.py --stage bullets          # explicit stage request also overrides the gate
python dip_news.py --force-thursday         # run the whole pipeline as if today were Thursday
```

Env-var form (handy inside CI / `.env` files):

```bash
STAGE=scrape python dip_news.py
STAGE="lists,prioritise" python dip_news.py
STAGE=all python dip_news.py
```

On Windows PowerShell, the same calls use `.\dip_news.py`:

```powershell
python .\dip_news.py --stage scrape
$env:STAGE = "lists,prioritise"; python .\dip_news.py
```

### Stage names ("regimes")

Each stage maps 1-to-1 to a box in the diagram in section 1:


| Stage name   | What it does                                                                                     |
| ------------ | ------------------------------------------------------------------------------------------------ |
| `scrape`     | step 1 — `fetch_kom` / `fetch_ved` / `fetch_rbc` / `fetch_agro` / `fetch_ria` / `fetch_autostat` |
| `lists`      | step 2 — `create_news_lists` for `world`, `rus`, `prices`                                        |
| `prioritise` | step 3 — `prioritise` for all sections (re-rank + keep top-40)                                   |
| `design`     | step 4 — `design_wo_llm` (fallback `design`) + `telegram_lists()`                                |
| `top`        | step 5 — `choose_top_urls` (Thursday-only by default)                                            |
| `read_top`   | step 6 — `read_top_urls` (Thursday-only by default)                                              |
| `bullets`    | step 7 — `create_bullets` + `telegram_bullets()` (Thursday-only by default)                      |
| `all`        | every stage in order (this is the default if you pass nothing)                                   |


Notes:

- Each stage reads its input from the Drive folder produced by the previous stage and writes to its own folder, so re-running a single stage in isolation is safe as long as the upstream files already exist on Drive.
- When you request `top`, `read_top` or `bullets` explicitly, the Thursday-only gate is treated as overridden — the stage will run regardless of weekday. In default `all` mode the gate still applies (use `--force-thursday` to bypass it).
- Unknown stage names cause the script to exit immediately with an explanatory error.

## A few things to be aware of before you run

- **The script runs the whole pipeline immediately at import time** — scrapers, LLM calls, Drive writes, and (because `telegram_lists()` and `telegram_bullets()` are not commented out) Telegram messages. There is no `if __name__ == "__main__":` guard, so `python dip_news.py` really does scrape live news, call the DeepSeek API and write to Google Drive. Use the `--stage` flag (section 6) to gate which steps actually execute.
- `choose_top_urls`, `read_top_urls` and `create_bullets` only fire when `datetime.today().weekday() == 3` (Thursday). On other weekdays only stages 1–4 run (`create_news_lists`, `prioritise`, `design_wo_llm` / `design`).
- `USE_SANDBOX = True` is hard-coded near the top of `dip_news.py` (around line 39). Set it to `False` to point at `FOLDERS_MAIN` and the production Telegram credentials.
- `report_<section>.txt` files written by `create_bullets` are saved to the **current working directory** (i.e. the folder you launched the script from), in addition to the Drive copy.
- Pre-existing latent bug: `send_telegram_message` calls `html.escape(text)` when `escape_html=True`, but `html` is never imported. The default is `False`, so it only bites if you pass `escape_html=True`. Add a one-line `import html` if you plan to use that flag.


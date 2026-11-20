# ChashiBondhu AI

A climate-aware, demand-linked agricultural decision-support platform for farmers across Bangladesh (8 divisions, 64 districts, upazila-level locations).

ChashiBondhu AI started as a direct marketplace that connects farmers, customers and vendors without middlemen. It now adds verified crop-suitability guidance, pre-harvest buyer matching, a dated and sourced price view, and Bangla farming assistants.

> **Competition:** Cloud Camp BD AI Builders Congress. Domain: AgriSphere AI. Challenge: FarmMarket (fair-price market access and demand matching).
>
> **Live demo:** `https://chashibondhu-ai-5y1e.onrender.com` | **Demo video:** `<https://youtu.be/gBoiKEE6Q7s?si=BwNOzzv6k2BC3EBj>`

---

## The problem

Farmers struggle to choose crops under changing climate and to find fair, reliable buyers. Limited local climate insight, uncertain demand, price-information gaps and dependence on intermediaries lead to poor planting decisions, weak bargaining power and unsold produce.

## Our approach

Connect **what a farmer can grow** with **what buyers want**.

- **Verified, explainable advice.** Every suitability result shows the value, the requirement, the source and the data type. Climate figures are historical averages, never forecasts.
- **Honest AI.** Assistants answer only from retrieved, cited material. When the data is missing, the system says "unknown" instead of guessing, and it never prescribes doses, fertilizers or pesticides.
- **Built for Bangladesh.** Bangla and English interface, Banglish search for places, local land units (bigha, kani, decimal) and offline drafts for weak connections.
- **Interest is not an order.** Buyer matches are potential opportunities until the buyer confirms.

---

## Features

### Crop planning
- **Suitability engine** (`crop_planning/`): a rule engine that checks temperature, soil pH, season and BARC upazila-level crop zoning. It returns *suitable*, *marginal*, *not suitable* or *unknown*, with the evidence for each factor.
- Local expert zoning (BARC) takes priority over global estimates (SoilGrids). Market demand is deliberately kept out of the suitability verdict.
- Only rows marked **verified** in the reference tables are used (see [Data policy](#data-policy)).

### Marketplace
- Listings with images, categories, search and suggestions, cart and checkout, saved items, farmer follows, reviews, compare, price alerts and discount prices.
- Orders, invoices and customer notifications.
- Farmer tools: dashboard, land plots and plantings, earnings, tips, complaints and profile.

### Pre-harvest matching
- Farmers post harvest forecasts. Buyers post demand requests.
- Matches move through stages: potential match, interest, awaiting harvest, quantity confirmed, available to order, converted.

### Prices
- Price page showing minimum, maximum and average by market, with date and source. It needs real price rows loaded into `market_prices`.

### AI assistants
| Assistant | What it does | Safeguards |
|---|---|---|
| **Fosholi** | Answers from a BARI handbook index using hybrid retrieval (BM25 plus dense embeddings with rank fusion). Streams sentence by sentence. | A sentence is shown only if it cites a real passage and every number appears in the retrieved text. |
| **Dr. Krishi** | Chooses tools per question: photo diagnosis, live weather (Open-Meteo), climate history, seasonal risk, general advice. | Blocks invented numbers and product names. Points farmers to Fosholi or the local agriculture office for doses and treatments. |
| **Photo diagnosis** | A vision model picks from a closed list of known problems. Code rules set the status. | No treatment, doses or products. EXIF and GPS data are removed from photos. |
| **Shop assistant** | Picks and explains products from database results. | Never orders anything, and falls back to a plain sorted list if the AI is unavailable. |

LLM calls go through a provider chain (Groq by default, Gemini or Gemma as automatic fallback), and the model that answered is recorded.

### Admin panel
Users, staff permissions, moderation, orders, finance with CSV export, complaints, announcements, articles, harvest oversight, sync monitor, analytics and an audit log.

### Accounts, security and offline
Phone and email accounts, password reset, hashed passwords, rate limiting, session cookies, optional API key for AI endpoints, and a service worker with offline drafts and sync.

---

## Project status

Status levels: Proposed, In development, Implemented, Tested, Deployed, Validated in real-world use.

| Module | Status | Notes |
|---|---|---|
| Data foundation (boundaries, names, land units, climate, soil) | Implemented | Fetch and build scripts in `scripts/` |
| Crop planning engine (rule-based) | Implemented | Limited by how many reference rows are verified |
| Marketplace and farmer tools | Implemented | |
| Pre-harvest matching | Implemented | |
| Price view | Implemented, needs data | No ingestion script for DAM or WFP prices yet |
| Fosholi, Dr. Krishi, photo, shop assistants | Implemented | Fosholi needs a locally built handbook index |
| Admin panel | Implemented | |
| Trained ML models (XGBoost / CatBoost + SHAP) | Proposed | `models/` is empty |
| Price forecasting | Proposed | |
| Surplus Produce Rescue | Proposed | Only a `discount_price` field exists so far |
| SMS notifications | Proposed | Console-only at present |
| Weather alerts | Proposed | |
| Voice input | Proposed | Only if it can be made reliable |

**Known limitations**
- Only part of the crop-requirement and calendar data is verified, so the engine often answers "unknown". All 10 catalogue crops are still marked *draft*.
- Climate values are regional estimates from a coarse grid, not field or station measurements.
- Raw datasets, the handbook index and trained models are not in the repository.

---

## Crop catalogue

Aman rice, Boro rice, maize, potato, tomato, mustard, mung bean, lentil, onion, watermelon.

First ML targets: maize, potato, tomato, mustard, Aman rice.

---

## Tech stack

| Layer | Technology |
|---|---|
| Backend | Python, FastAPI, Uvicorn, Pydantic |
| Web UI | Jinja2 templates, Starlette sessions, vanilla JS and CSS, service worker |
| Database | Supabase (PostgreSQL), SQL migrations, psycopg |
| Data pipelines | pandas, GeoPandas, pyogrio, rasterio, pyarrow |
| Search and RAG | rank-bm25, sentence-transformers, PyMuPDF, bijoy2unicode |
| LLMs | Groq (primary), Gemini / Gemma (fallback) |
| External APIs | NASA POWER, CHIRPS, SoilGrids, Open-Meteo |
| Images | Pillow |
| Testing | pytest |

---

## Data sources

| Source | Used for |
|---|---|
| NASA POWER (MERRA-2 / CERES) | Daily and monthly climate: temperature, rainfall, humidity, solar radiation |
| CHIRPS v3.0 | Monthly rainfall |
| SoilGrids 2.0 | Soil properties (model estimate, lower evidence weight than local zoning) |
| BARC crop zoning | Upazila-level land suitability by crop |
| COD-AB boundaries (BBS via OCHA/HDX) | Divisions, districts, upazilas |
| BARI Krishi Projukti Hatboi | Crop requirements, calendars, handbook assistant (internal use only, not redistributed) |
| BRRI, FAO ECOCROP, BJAR / BJA papers | Rice guidance, absolute crop limits, cropping systems |
| Ministry of Land | Land-unit conversions |
| Mendeley potato leaf dataset (CC BY 4.0) | Evaluating the photo helper |

Every dataset is recorded in [`docs/dataset_register.csv`](docs/dataset_register.csv) with its source, link, license, coverage and limitations.

---

## Repository structure

```
configs/             settings
data/raw/            original downloads (not in Git)
data/interim/        partly cleaned data (not in Git)
data/processed/      final clean tables (not in Git)
data/reference/      small curated tables with sources (in Git)
docs/                dataset register, design notes, decision records
notebooks/           exploration (climate data preparation)
scripts/             runnable pipeline entry points
src/chashibondhu/
  api/               FastAPI app and JSON API
  web/               website routes, templates, repositories
  assistant/         LLM providers, retrieval, guards, vision
  crop_planning/     rule engine and reference loaders
  data_pipeline/     data builders
  common/            shared helpers
  marketplace/ surplus/ weather/   placeholders for upcoming modules
supabase/migrations/ database schema (001 to 012)
models/              trained models (not in Git)
tests/               automated tests
```

---

## Getting started

### 1. Install

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate    Mac/Linux: source .venv/bin/activate
pip install -r requirements.txt
```

The data-pipeline packages (GeoPandas, rasterio, pyarrow) are large. If you only want to run the website, install the web packages and add `psycopg[binary]` and `psycopg_pool`.

### 2. Configure

Copy `.env.example` to `.env` and fill in the values. The code reads these variables:

| Variable | Purpose |
|---|---|
| `SUPABASE_DB_HOST`, `SUPABASE_DB_PORT`, `SUPABASE_DB_NAME`, `SUPABASE_DB_USER`, `SUPABASE_DB_PASSWORD`, `SUPABASE_DB_SSLMODE` | PostgreSQL connection |
| `WEB_SESSION_SECRET` | Long random text that keeps users logged in across restarts |
| `WEB_COOKIE_SECURE` | Set to `1` only when the site runs over https |
| `GROQ_API_KEY`, `GROQ_MODEL`, `GROQ_VISION_MODEL` | Primary LLM and vision model |
| `GEMINI_API_KEY`, `GEMINI_MODEL`, `GEMMA_MODEL`, `GEMMA_VISION_MODEL` | Fallback models |
| `LLM_PROVIDER`, `LLM_BASE_URL`, `LLM_MODEL`, `LLM_API_KEY`, `LLM_FALLBACK` | Optional generic provider settings |
| `CHASHIBONDHU_API_KEY` | Optional key protecting the AI endpoints |
| `RAG_INDEX_DIR` | Location of the handbook index for Fosholi |

Never commit `.env`.

### 3. Create the database

Open the Supabase SQL editor and run the files in `supabase/migrations/` in numeric order (`001_init.sql` to `012_ai_chat_history.sql`). Then create an admin user:

```bash
python scripts/create_admin.py
```

### 4. Run

The website is mounted onto the API app, so there is one entry point:

```bash
uvicorn chashibondhu.api.main:app --app-dir src --reload
```

Open `http://127.0.0.1:8000`.

### 5. Test

```bash
pytest
```

---

## Data pipeline

Data files are not committed. Typical order:

```bash
python scripts/build_admin_reference.py     # boundaries and names
python scripts/fetch_nasa_power.py          # NASA POWER climate
python scripts/build_climatology.py         # monthly climatology
python scripts/fetch_chirps.py && python scripts/build_chirps_rainfall.py
python scripts/fetch_soilgrids.py && python scripts/build_soil_features.py
python scripts/fetch_barc_cropzoning.py && python scripts/build_barc_cropzoning.py
python scripts/validate_reference.py        # check curated tables
python scripts/run_suitability.py           # try the crop engine
```

Check each script's header for its arguments and required inputs. To build the Fosholi handbook index (the source PDF is internal use only and is not in this repository):

```bash
python scripts/build_rag_index.py
```

---

## Data policy

- Raw and processed data files are not committed. Every dataset is listed in `docs/dataset_register.csv`.
- **No fabricated or LLM-generated data is used as ground truth.**
- Curated knowledge rows carry source, page, status (`todo`, `draft`, `verified`) and verifier. The engine uses only `verified` rows (see `docs/decisions/0004-curated-knowledge-provenance.md`).
- Secrets go in `.env`, never in Git.
- Copyrighted material such as the BARI handbook is used for internal retrieval only and is not redistributed.

---

## Responsible AI

- **Grounded:** assistant sentences must cite retrieved passages, and numbers must appear in the sources.
- **No prescriptions:** no doses, mixing rates, fertilizer or pesticide names from the broad assistant.
- **Honest uncertainty:** the engine returns "unknown" or "insufficient verified knowledge" instead of guessing. Disease risk is stated as seasonal possibility, not a diagnosis.
- **No forecasts from history:** climate values are labelled as historical.
- **Privacy:** photos have EXIF and GPS removed, and secrets and reset tokens are not logged.
- **Human control:** matches are interest only, the shop assistant never orders, and draft knowledge never reaches users.

---

## Roadmap

1. Load real market prices (DAM / WFP) and add fair-price bands.
2. Surplus Produce Rescue: alerts, optional discount, quantity sold after alert.
3. Verify more crop-requirement and calendar rows, starting with the five ML crops.
4. Rank suitable crops by buyer demand and price.
5. Price forecasting baseline, then trained yield models with SHAP explanations.
6. SMS and push notifications, planting-window charts, weather alerts.
7. Publish evaluation results for the assistants and the potato photo helper.
8. Field validation against BMD station data and a pilot with farmers and agriculture officers.

---

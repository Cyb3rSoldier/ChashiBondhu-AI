# ChashiBondhu AI (চাষীবন্ধু)

A climate-aware, demand-driven agricultural intelligence and decision-support
platform for farmers across Bangladesh (8 divisions, 64 districts).

## Modules

| # | Module | Main technology | Status |
|---|--------|-----------------|--------|
| 0 | Data foundation (geographic + crop reference) | Data pipelines, GeoPandas | In development |
| 1 | Intelligent Crop Planning Engine | Rules + XGBoost/CatBoost + SHAP | Proposed |
| 2 | Weather-Aware Farming Intelligence | Climate pipelines + rule-based alerts | Proposed |
| 3 | Bangla Agricultural Assistant | LLM + RAG + LangGraph + speech | Proposed |
| 4 | Demand-Linked Marketplace | Matching + time-series forecasting | Proposed |
| 5 | Smart Surplus Management | Matching + rules + notifications | Proposed |

Status levels: Proposed → In development → Implemented → Tested → Deployed → Validated in real-world use.

## Crop catalogue

Aman Rice, Boro Rice, Maize, Potato, Tomato, Mustard, Mung Bean, Lentil, Onion, Watermelon.
First ML implementation: Maize, Potato, Tomato, Mustard, Aman Rice.

## Repository structure

```
configs/           settings
data/raw/          original downloads (not in Git)
data/interim/      partly cleaned data (not in Git)
data/processed/    final clean tables (not in Git)
data/reference/    small curated tables with sources (in Git)
docs/              dataset register, architecture, decisions
scripts/           runnable pipeline entry points
src/chashibondhu/  library code, one package per module
models/            trained models (not in Git)
notebooks/         exploration only
tests/             automated tests
```

## Setup

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate    Mac/Linux: source .venv/bin/activate
pip install -r requirements.txt
```

## Data policy

- Data files are not committed. Every dataset is recorded in
  `docs/dataset_register.csv` with source, link, license, coverage and limitations.
- No fabricated or LLM-generated data is used as ground truth.
- Secrets go in `.env` (never committed). See `.env.example`.

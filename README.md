# ReSort (Recycle Labs)

Preliminary plant-proposal calculator for small plastic-scrap recycling lines (ChE 303, Project 06).
Enter feed rate, PET/HDPE/PP composition, product size and purity requirements, budget and prices; get optimised crusher / screen / sink-float tank settings, product flows, purity and recovery, equipment sizing, cost ranges and payback, with the limits stated.

- **How it works:** an Aspen Plus mass balance (crusher -> screens with oversize recycle -> sink-float tank) was swept over 210 cases; a surrogate fitted to them answers instantly, an optimiser searches it, and Python models size the equipment and estimate cost. No Aspen is needed to run the website.
- **It is preliminary:** purity and recovery depend on assumed tank parameters, costs are a +-30 % class estimate and prices are assumptions. Read [docs/limitations.md](docs/limitations.md) and [docs/assumptions_ranked_v9.md](docs/assumptions_ranked_v9.md).

## Run locally

```bash
pip install -r requirements.txt uvicorn
python -m uvicorn index:app --app-dir api --port 8000
```
Open http://127.0.0.1:8000

## Deploy

Import this repository in Vercel (framework preset "Other"); `api/index.py` exposes the ASGI app and `vercel.json` routes every path to it. See [docs/DEPLOY.md](docs/DEPLOY.md).

## Layout

`api/index.py` entry point · `v2/website/` UI and API (`server_v2.py`) · `v2/*.py` surrogate, optimiser, tank, crusher, sizing and cost models · `v2/data/` fitted surrogate and the Aspen sweep results · `docs/` limitations and ranked assumptions.

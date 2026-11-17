# Deploying to Vercel

The repository root is the deployable project: `api/index.py`, `vercel.json`, `requirements.txt` and `v2/`. No build step, no environment variables, no secrets.

## From GitHub (recommended)

1. On vercel.com choose **Add New -> Project** and import this repository.
2. Framework preset **Other**. Leave build and output settings empty. Press **Deploy**.
3. Open the production URL, then `/api/health` (expect `{"status":"ok"}`), then press **Generate proposal** once.

## From the command line

```bash
npm install -g vercel
vercel login
vercel --prod        # run in the repository root
```

## Notes

- Vercel's Python runtime serves the Starlette (ASGI) app exposed as `app` in `api/index.py`. If the build log complains about the entry point or the Python version, adapt `api/index.py` / `requirements.txt` accordingly.
- New Vercel projects may protect preview URLs with a login (Deployment Protection). Use the production URL or switch protection off in Settings for a fully public page.
- Anyone with the link can use the calculator and read `/api/dataset` and `/api/meta` (the 210 simulated cases, model errors, cost assumptions). The repository contains no Aspen files and no personal data.
- Tested standalone with uvicorn (health, page, assets, a proposal, a rejected request); not yet run on Vercel itself.

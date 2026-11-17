# Deploying ReSort to Vercel

This folder is a self-contained, deploy-ready copy of the ReSort website. It contains **no** Aspen files, no personal paths and no keys:
`api/index.py` (entry point), `vercel.json`, `requirements.txt`, and `v2/` (the nine Python modules the server needs, the website files, the fitted surrogate `data/surrogate_v2.json` and the Aspen sweep results `data/results_v2_lhs.csv`).
It was tested standalone with uvicorn on this PC (health, page, assets, a proposal and a rejected request all correct). It has **not** been run on Vercel itself, because no Vercel login or CLI is available in the working environment.

**What goes public:** anyone with the link can use the calculator and can read `/api/dataset` and `/api/meta` (the 210 simulated cases, the model errors and the cost assumptions). Nothing private is in the bundle.

## Option A: Vercel CLI (about 5 minutes)

1. Install Node.js LTS from nodejs.org.
2. In PowerShell:
   ```powershell
   npm install -g vercel
   cd D:\PlasticProject\v2\vercel_deploy
   vercel login
   vercel            # preview deployment, answer the questions: scope = your account, link to existing project = no, directory = ./ , override settings = no
   vercel --prod     # production URL
   ```
3. The CLI prints the link (`https://<project-name>.vercel.app`).

## Option B: GitHub + Vercel website

1. Create a new GitHub repository and upload the **contents** of this folder (`api/`, `v2/`, `vercel.json`, `requirements.txt`, `.vercelignore`).
2. On vercel.com choose Add New, then Project, import the repository, framework preset **Other**, leave build settings empty, press Deploy.

## If something goes wrong

- Vercel's Python runtime runs the Starlette (ASGI) app from `api/index.py` (`app`). If the build log complains about the entry point or the runtime version, send the log text and the app can be adapted.
- Deployment Protection: new Vercel projects may protect preview URLs with a login. Use the production URL, or turn protection off in Settings if you want the page fully public.
- Check after deploying: open the link, then `/api/health` (should show `{"status":"ok"}`) and press "Generate proposal" once.

# gymtrack

A lightweight Streamlit workout tracker for gradually building out a 12-week training program.

## What is included

- A reusable `week -> day -> exercises` data model
- Seed data for `Week 1 / Upper 1` based on the provided workout table
- A Streamlit UI for browsing the planned workout and logging actual results
- File-backed storage for the workout plan and session logs

## Project structure

- `app.py` - Streamlit application
- `data/program.yaml` - workout plan definition
- `data/workout_logs.json` - append-only session log store
- `.streamlit/config.toml` - Streamlit theme and layout config

## Run locally

1. Create and activate a virtual environment.
2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Start the app:

```bash
streamlit run app.py
```

## Deploy to Streamlit Community Cloud

1. Push this repo to GitHub.
2. In Streamlit Community Cloud, create a new app from the repo.
3. Set the main file path to `app.py`.
4. Deploy.

## Editing the plan over time

Add future weeks and days by editing `data/program.yaml`. The app reads the available weeks and sessions dynamically, so new entries do not require UI changes.

## Important note about logging on Streamlit Cloud

This first version writes logs to `data/workout_logs.json`. That works well locally, but Streamlit Community Cloud does not provide durable file storage for app writes. In practice, cloud-entered logs can be lost after a restart or redeploy.

For durable cloud logging, the next upgrade should move session storage to a hosted backend such as Google Sheets, Supabase, or another database.

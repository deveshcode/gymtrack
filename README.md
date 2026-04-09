# gymtrack

A lightweight Streamlit workout tracker for gradually building out a 12-week training program.

## What is included

- A reusable `week -> day -> exercises` data model
- Week 1 seeded across all current workout days
- A Streamlit UI for browsing the planned workout and logging actual results
- Centralized session history across all workouts
- Persistent Google Sheets logging when configured
- Local JSON fallback for local development

## Project structure

- `app.py` - Streamlit application
- `data/program.yaml` - workout plan definition
- `data/workout_logs.json` - local fallback log store
- `.streamlit/config.toml` - Streamlit theme and layout config
- `.streamlit/secrets.toml.example` - example secrets for Google Sheets

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

Without Google Sheets secrets, the app will log sessions into `data/workout_logs.json`.

## Deploy to Streamlit Community Cloud

1. Push this repo to GitHub.
2. In Streamlit Community Cloud, create a new app from the repo.
3. Set the main file path to `app.py`.
4. Add secrets from the Google Sheets setup below.
5. Deploy or reboot the app.

## Google Sheets logging setup

This app can persist workout logs in Google Sheets so Streamlit Cloud keeps your sessions permanently.

### 1. Create a Google Cloud service account

1. In Google Cloud, create a project or use an existing one.
2. Enable the Google Sheets API and Google Drive API.
3. Create a service account.
4. Generate a JSON key for that service account.

### 2. Create a Google Sheet

1. Create a blank Google Sheet.
2. Share it with the service account email address from the JSON key.
3. Copy the spreadsheet ID from the sheet URL.

Example sheet URL:

```text
https://docs.google.com/spreadsheets/d/SPREADSHEET_ID/edit#gid=0
```

### 3. Add secrets to Streamlit

In Streamlit Community Cloud, open your app settings and add secrets matching the example in `.streamlit/secrets.toml.example`.

You need:

- `spreadsheet_id`
- optional `worksheet_name` such as `session_logs`
- all fields from the Google service account JSON under `[gcp_service_account]`

### 4. Redeploy

After adding the secrets, reboot the app. It will automatically switch from local JSON logging to Google Sheets logging.

## Local secrets example

For local testing, create `.streamlit/secrets.toml` from `.streamlit/secrets.toml.example` and fill in your real values.

## Editing the plan over time

Add future weeks and days by editing `data/program.yaml`. The app reads the available weeks and sessions dynamically, so new entries do not require UI changes.

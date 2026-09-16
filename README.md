# 🎈 Blank app template

A simple Streamlit app template for you to modify!

[![Open in Streamlit](https://static.streamlit.io/badges/streamlit_badge_black_white.svg)](https://blank-app-template.streamlit.app/)

### How to run it on your own machine

Prerequisite: install `uv` if you don't already have it.

```
$ curl -LsSf https://astral.sh/uv/install.sh | sh
```

1. Sync the dependencies

   ```
   $ uv sync
   ```

2. Run the app

   ```
   $ uv run streamlit run streamlit_app.py
   ```

   ### Connect Google Sheets

   The app works locally without configuration and keeps test submissions in memory. To write requests to a Google Sheet, create `.streamlit/secrets.toml`:

   ```toml
   spreadsheet_id = "your-spreadsheet-id"
   worksheet_name = "Requests"

   [gcp_service_account]
   type = "service_account"
   project_id = "your-project-id"
   private_key_id = "your-private-key-id"
   private_key = "-----BEGIN PRIVATE KEY-----\\n...\\n-----END PRIVATE KEY-----\\n"
   client_email = "your-service-account@your-project.iam.gserviceaccount.com"
   client_id = "your-client-id"
   token_uri = "https://oauth2.googleapis.com/token"
   ```

   Share the spreadsheet with the service account email. Keep `secrets.toml` private and do not commit it.

   After serials are appended, use **Create PDF** to generate and download a printable serial allocation summary.

   For local development, the app also recognizes the service-account JSON file named
   `neon-webbing-314108-164f194cf012.json` in the project folder. This file is ignored by Git.
   Because the key has been exposed, revoke it in Google Cloud and download a replacement before use.

# Team Availability Calendar

A Streamlit app where team members submit their availability in weekly one-hour blocks. The overview highlights slots available to everyone and supports CSV export.

## Run locally

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

Open the local URL shown by Streamlit (normally `http://localhost:8501`).

## Storage

Availability is stored locally in `availability.db` (SQLite), created automatically at first run. For a shared team deployment, run the app against a shared persistent volume or replace the SQLite functions with an approved central database service.

## Included features

- Weekly date selector
- Individual entry by team member and day/time block
- Persisted updates per person/week
- Team-wide weekly availability heat map
- Identification of slots where all submitted members are free
- Optional notes and CSV export


import os
import smtplib
import sqlite3
from datetime import date, datetime, time, timedelta
from email.message import EmailMessage
from pathlib import Path

import pandas as pd
import streamlit as st

DB_PATH = Path(__file__).with_name("availability.db")
WORK_DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
TIME_OPTIONS = [time(hour, minute) for hour in range(6, 21) for minute in (0, 30)]

st.set_page_config(page_title="Team Availability", page_icon="📅", layout="wide")


def db_connection():
    return sqlite3.connect(DB_PATH, check_same_thread=False)


def init_db():
    with db_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS daily_availability (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                member TEXT NOT NULL,
                week_start TEXT NOT NULL,
                day_name TEXT NOT NULL,
                availability_status TEXT NOT NULL CHECK(availability_status IN ('Available', 'Unavailable')),
                start_time TEXT,
                end_time TEXT,
                note TEXT DEFAULT '',
                updated_at TEXT NOT NULL,
                UNIQUE(member, week_start, day_name)
            )
        """)


def monday_of(value: date) -> date:
    return value - timedelta(days=value.weekday())


def time_to_text(value):
    return value.strftime("%H:%M") if value else None


def text_to_time(value):
    return datetime.strptime(value, "%H:%M").time() if value else time(9, 0)


def save_week(member, week_start, entries, note):
    """Persist all five working days for a team member in SQLite."""
    timestamp = datetime.now().isoformat(timespec="seconds")
    rows = []
    for day in WORK_DAYS:
        entry = entries[day]
        rows.append((
            member, week_start.isoformat(), day, entry["status"],
            time_to_text(entry["start"]) if entry["status"] == "Available" else None,
            time_to_text(entry["end"]) if entry["status"] == "Available" else None,
            note, timestamp,
        ))
    with db_connection() as conn:
        conn.execute("DELETE FROM daily_availability WHERE member = ? AND week_start = ?", (member, week_start.isoformat()))
        conn.executemany("""
            INSERT INTO daily_availability
            (member, week_start, day_name, availability_status, start_time, end_time, note, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, rows)


def get_week_data(week_start):
    with db_connection() as conn:
        return pd.read_sql_query("""
            SELECT member, day_name, availability_status, start_time, end_time, note, updated_at
            FROM daily_availability
            WHERE week_start = ?
        """, conn, params=(week_start.isoformat(),))


def existing_entry(data, member, day):
    rows = data[(data.member == member) & (data.day_name == day)] if not data.empty else pd.DataFrame()
    if rows.empty:
        return {"status": "Available", "start": time(9, 0), "end": time(17, 0)}
    row = rows.iloc[0]
    return {
        "status": row.availability_status,
        "start": text_to_time(row.start_time) if pd.notna(row.start_time) else time(9, 0),
        "end": text_to_time(row.end_time) if pd.notna(row.end_time) else time(17, 0),
    }


def display_range(row):
    if row["availability_status"] == "Unavailable":
        return "Unavailable"
    return f"{row['start_time']}–{row['end_time']}"


def build_email_text(data, week_start):
    end = week_start + timedelta(days=4)
    lines = [f"Team availability: {week_start:%d %b %Y} – {end:%d %b %Y}", ""]
    if data.empty:
        return "\n".join(lines + ["No availability has been submitted."])
    ordered = data.copy()
    ordered["day_name"] = pd.Categorical(ordered["day_name"], WORK_DAYS, ordered=True)
    for member, member_data in ordered.sort_values(["member", "day_name"]).groupby("member", observed=True):
        lines.append(member)
        for _, row in member_data.iterrows():
            lines.append(f"  - {row.day_name}: {display_range(row)}")
        note = member_data.iloc[0].note
        if note:
            lines.append(f"  Note: {note}")
        lines.append("")
    return "\n".join(lines)


def email_manager(recipient, subject, body):
    """Send using SMTP credentials supplied as environment variables, never in the app UI.
    Required: SMTP_HOST, SMTP_PORT, SMTP_USERNAME, SMTP_PASSWORD, SMTP_FROM.
    """
    required = ["SMTP_HOST", "SMTP_PORT", "SMTP_USERNAME", "SMTP_PASSWORD", "SMTP_FROM"]
    missing = [key for key in required if not os.getenv(key)]
    if missing:
        return False, "Email is not configured. Missing environment variables: " + ", ".join(missing)
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = os.environ["SMTP_FROM"]
    msg["To"] = recipient
    msg.set_content(body)
    try:
        with smtplib.SMTP(os.environ["SMTP_HOST"], int(os.environ["SMTP_PORT"])) as server:
            server.starttls()
            server.login(os.environ["SMTP_USERNAME"], os.environ["SMTP_PASSWORD"])
            server.send_message(msg)
        return True, "Email sent successfully."
    except Exception as exc:
        return False, f"Could not send email: {exc}"


init_db()
st.title("📅 Team Availability Calendar")
st.caption("Submit your Monday–Friday availability. Saved entries remain available after refresh and app restart.")

selected_date = st.sidebar.date_input("Week containing", date.today())
week_start = monday_of(selected_date)
week_end = week_start + timedelta(days=4)
st.sidebar.info(f"**Work week**\n\n{week_start:%d %b %Y} – {week_end:%d %b %Y}")
st.sidebar.caption("Data is saved in the local `availability.db` SQLite database.")

entry_tab, overview_tab, report_tab = st.tabs(["✏️ Submit availability", "👥 Team overview", "📨 Manager report"])
data = get_week_data(week_start)

with entry_tab:
    st.subheader("Your working-week availability")
    member = st.text_input("Your name", placeholder="e.g., Alex Morgan")
    st.caption("Choose **Unavailable** for leave, travel, or any day you cannot attend. For available days, specify your earliest start and latest end time.")

    entries = {}
    for index, day in enumerate(WORK_DAYS):
        previous = existing_entry(data, member.strip(), day) if member.strip() else {"status": "Available", "start": time(9), "end": time(17)}
        with st.expander(f"{day} · {(week_start + timedelta(days=index)):%d %b}", expanded=True):
            status = st.radio("Status", ["Available", "Unavailable"], index=0 if previous["status"] == "Available" else 1, horizontal=True, key=f"status_{week_start}_{member}_{day}")
            if status == "Available":
                c1, c2 = st.columns(2)
                with c1:
                    start = st.selectbox("Start time", TIME_OPTIONS, index=TIME_OPTIONS.index(previous["start"]) if previous["start"] in TIME_OPTIONS else 6, format_func=lambda x: x.strftime("%H:%M"), key=f"start_{week_start}_{member}_{day}")
                with c2:
                    end = st.selectbox("End time", TIME_OPTIONS, index=TIME_OPTIONS.index(previous["end"]) if previous["end"] in TIME_OPTIONS else 22, format_func=lambda x: x.strftime("%H:%M"), key=f"end_{week_start}_{member}_{day}")
            else:
                start = end = None
                st.caption("This day will be recorded as unavailable.")
            entries[day] = {"status": status, "start": start, "end": end}

    note = st.text_area("Optional note", placeholder="For example: remote only on Wednesday.")
    if st.button("Save weekly availability", type="primary"):
        if not member.strip():
            st.error("Please enter your name before saving.")
        elif any(item["status"] == "Available" and item["start"] >= item["end"] for item in entries.values()):
            st.error("For each available day, the end time must be later than the start time.")
        else:
            save_week(member.strip(), week_start, entries, note.strip())
            st.success(f"Saved {member.strip()}’s availability for this work week. It will persist after refresh.")
            st.rerun()

with overview_tab:
    st.subheader("Team working-week overview")
    if data.empty:
        st.info("No team member has submitted availability for this week yet.")
    else:
        view = data.copy()
        view["day_name"] = pd.Categorical(view["day_name"], WORK_DAYS, ordered=True)
        view["Availability"] = view.apply(display_range, axis=1)
        pivot = view.pivot(index="member", columns="day_name", values="Availability").reindex(columns=WORK_DAYS)
        st.dataframe(pivot, use_container_width=True)
        st.caption("Each saved submission is stored in `availability.db`; refreshing the page does not remove it.")

        available = view[view.availability_status == "Available"].copy()
        suggestions = []
        for day in WORK_DAYS:
            daily = available[available.day_name == day]
            submitted = view[view.day_name == day].member.nunique()
            if submitted and daily.member.nunique() == submitted:
                latest_start = max(daily.start_time)
                earliest_end = min(daily.end_time)
                if latest_start < earliest_end:
                    suggestions.append({"Day": day, "All-team overlap": f"{latest_start}–{earliest_end}"})
        if suggestions:
            st.success("Common availability identified.")
            st.dataframe(pd.DataFrame(suggestions), use_container_width=True, hide_index=True)
        else:
            st.warning("No time range is shared by all submitted team members on the same day.")

        with st.expander("Notes and submission timestamps"):
            st.dataframe(view[["member", "day_name", "note", "updated_at"]], use_container_width=True, hide_index=True)

with report_tab:
    st.subheader("Save or send the weekly report")
    report = build_email_text(data, week_start)
    st.text_area("Report preview", report, height=300)
    st.download_button("Download report as text", report.encode("utf-8"), file_name=f"availability_report_{week_start.isoformat()}.txt", mime="text/plain")
    if not data.empty:
        st.download_button("Download detailed CSV", data.to_csv(index=False).encode("utf-8"), file_name=f"team_availability_{week_start.isoformat()}.csv", mime="text/csv")

    st.divider()
    st.markdown("**Email the manager**")
    recipient = st.text_input("Manager email address", placeholder="manager@example.com")
    if st.button("Send report by email"):
        if not recipient.strip() or "@" not in recipient:
            st.error("Enter a valid manager email address.")
        else:
            ok, message = email_manager(recipient.strip(), f"Team availability | {week_start:%d %b} – {week_end:%d %b %Y}", report)
            (st.success if ok else st.error)(message)
    st.caption("Email delivery requires SMTP environment variables. See the README before enabling this in a shared deployment.")

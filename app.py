
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
import streamlit as st

DB_PATH = Path(__file__).with_name("availability.db")
DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
TIME_SLOTS = [f"{hour:02d}:00" for hour in range(7, 20)]

st.set_page_config(page_title="Team Availability", page_icon="📅", layout="wide")


def db_connection():
    return sqlite3.connect(DB_PATH, check_same_thread=False)


def init_db():
    with db_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS availability (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                member TEXT NOT NULL,
                week_start TEXT NOT NULL,
                day_name TEXT NOT NULL,
                time_slot TEXT NOT NULL,
                status TEXT NOT NULL,
                note TEXT DEFAULT '',
                updated_at TEXT NOT NULL,
                UNIQUE(member, week_start, day_name, time_slot)
            )
        """)


def monday_of(value: date) -> date:
    return value - timedelta(days=value.weekday())


def save_availability(member, week_start, selected_cells, note):
    now = datetime.now().isoformat(timespec="seconds")
    with db_connection() as conn:
        # Replace only this member's submitted weekly view.
        conn.execute("DELETE FROM availability WHERE member = ? AND week_start = ?", (member, week_start.isoformat()))
        rows = []
        for day, slots in selected_cells.items():
            for slot in slots:
                rows.append((member, week_start.isoformat(), day, slot, "Available", note, now))
        conn.executemany("""
            INSERT INTO availability (member, week_start, day_name, time_slot, status, note, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, rows)


def get_week_data(week_start):
    with db_connection() as conn:
        return pd.read_sql_query("""
            SELECT member, day_name, time_slot, status, note, updated_at
            FROM availability
            WHERE week_start = ?
            ORDER BY member, day_name, time_slot
        """, conn, params=(week_start.isoformat(),))


def available_slots_by_member(data, member):
    result = {day: set() for day in DAYS}
    if data.empty:
        return result
    for _, row in data[data["member"] == member].iterrows():
        result[row["day_name"]].add(row["time_slot"])
    return result


def grid_html(data, week_start):
    members = sorted(data["member"].unique()) if not data.empty else []
    header_dates = [week_start + timedelta(days=i) for i in range(7)]
    html = ["<style>table{border-collapse:collapse;width:100%;font-size:14px}th,td{border:1px solid #d7dce2;padding:7px;text-align:center}th{background:#f4f6f8}.slot{font-weight:600;text-align:left}.free{background:#d9f2df;color:#145a32}.partial{background:#fff1c9;color:#785400}.none{background:#f6dada;color:#8b1e1e}</style>"]
    html.append("<table><thead><tr><th>Time</th>")
    for day, day_date in zip(DAYS, header_dates):
        html.append(f"<th>{day}<br><small>{day_date.strftime('%d %b')}</small></th>")
    html.append("</tr></thead><tbody>")
    for slot in TIME_SLOTS:
        html.append(f"<tr><td class='slot'>{slot}</td>")
        for day in DAYS:
            count = int(((data["day_name"] == day) & (data["time_slot"] == slot)).sum()) if not data.empty else 0
            if count == 0:
                css, label = "none", "—"
            elif count == len(members):
                css, label = "free", f"{count}/{len(members)}"
            else:
                css, label = "partial", f"{count}/{len(members)}"
            html.append(f"<td class='{css}'>{label}</td>")
        html.append("</tr>")
    html.append("</tbody></table>")
    return "".join(html), members


init_db()
st.title("📅 Team Availability Calendar")
st.caption("Record weekly availability and identify meeting times that work for the whole team.")

today = date.today()
selected_date = st.sidebar.date_input("Week containing", today)
week_start = monday_of(selected_date)
week_end = week_start + timedelta(days=6)
st.sidebar.info(f"**Selected week**\n\n{week_start.strftime('%d %b %Y')} – {week_end.strftime('%d %b %Y')}")

entry_tab, overview_tab, export_tab = st.tabs(["✏️ Submit availability", "👥 Team overview", "⬇️ Export"])

with entry_tab:
    st.subheader("Your weekly availability")
    member = st.text_input("Your name", placeholder="e.g., Alex Morgan")
    st.caption("Select every one-hour time block during which you are available. Submitting again replaces your previous selection for this week.")

    existing = get_week_data(week_start)
    prior = available_slots_by_member(existing, member.strip()) if member.strip() else {day: set() for day in DAYS}
    chosen = {}
    cols = st.columns(7)
    for index, (col, day) in enumerate(zip(cols, DAYS)):
        with col:
            st.markdown(f"**{day}**  ")
            st.caption((week_start + timedelta(days=index)).strftime("%d %b"))
            chosen[day] = st.multiselect(
                "Available", TIME_SLOTS, default=sorted(prior[day]), key=f"{week_start}_{member}_{day}", label_visibility="collapsed"
            )

    note = st.text_area("Optional note", placeholder="For example: available remotely only, or time zone details.")
    if st.button("Save availability", type="primary"):
        if not member.strip():
            st.error("Please enter your name before saving.")
        elif not any(chosen.values()):
            st.warning("Select at least one available time slot, or do not submit changes.")
        else:
            save_availability(member.strip(), week_start, chosen, note.strip())
            st.success(f"Availability saved for {member.strip()}.")
            st.rerun()

with overview_tab:
    st.subheader("Weekly team view")
    data = get_week_data(week_start)
    if data.empty:
        st.info("No availability has been submitted for this week yet.")
    else:
        html, members = grid_html(data, week_start)
        st.markdown(f"**Team members submitted:** {', '.join(members)}")
        st.markdown("<span style='color:#145a32'>■</span> everyone available &nbsp;&nbsp; <span style='color:#785400'>■</span> some available &nbsp;&nbsp; <span style='color:#8b1e1e'>■</span> nobody available", unsafe_allow_html=True)
        st.markdown(html, unsafe_allow_html=True)

        counts = (data.groupby(["day_name", "time_slot"])["member"].nunique().reset_index(name="available_members"))
        best = counts[counts["available_members"] == len(members)].copy()
        if not best.empty:
            best["day_name"] = pd.Categorical(best["day_name"], DAYS, ordered=True)
            best = best.sort_values(["day_name", "time_slot"])
            st.success("Times when everyone is available: " + ", ".join(f"{r.day_name} {r.time_slot}" for r in best.itertuples()))
        else:
            st.warning("There is no one-hour slot when every submitted team member is available.")

        with st.expander("Submitted notes and last updates"):
            latest = data.sort_values("updated_at").groupby("member", as_index=False).last()[["member", "note", "updated_at"]]
            st.dataframe(latest, use_container_width=True, hide_index=True)

with export_tab:
    data = get_week_data(week_start)
    st.subheader("Download weekly data")
    if data.empty:
        st.info("No data is available to export for this week.")
    else:
        export = data.copy()
        export.insert(1, "week_start", week_start.isoformat())
        st.download_button(
            "Download CSV",
            export.to_csv(index=False).encode("utf-8"),
            file_name=f"team_availability_{week_start.isoformat()}.csv",
            mime="text/csv",
        )
        st.dataframe(export, use_container_width=True, hide_index=True)

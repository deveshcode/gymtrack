from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st
import yaml


st.set_page_config(
    page_title="GymTrack",
    page_icon="🏋️",
    layout="wide",
)

BASE_DIR = Path(__file__).resolve().parent
PROGRAM_PATH = BASE_DIR / "data" / "program.yaml"
LOGS_PATH = BASE_DIR / "data" / "workout_logs.json"


def load_program() -> dict[str, Any]:
    with PROGRAM_PATH.open("r", encoding="utf-8") as file:
        return yaml.safe_load(file) or {}


def load_logs() -> list[dict[str, Any]]:
    if not LOGS_PATH.exists():
        return []

    with LOGS_PATH.open("r", encoding="utf-8") as file:
        payload = json.load(file)
        return payload if isinstance(payload, list) else []


def save_logs(logs: list[dict[str, Any]]) -> None:
    LOGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOGS_PATH.open("w", encoding="utf-8") as file:
        json.dump(logs, file, indent=2)


def build_plan_table(exercises: list[dict[str, Any]]) -> pd.DataFrame:
    rows = []
    for entry in exercises:
        rows.append(
            {
                "Exercise": entry["exercise"],
                "Intensity": entry["intensity_technique"],
                "Warm-Up Sets": entry["warm_up_sets"],
                "Working Sets": entry["working_sets"],
                "Rep Range": entry["rep_range"],
                "RIR Set 1": entry["rir_set_1"],
                "RIR Set 2": entry["rir_set_2"],
                "Rest": entry["rest"],
                "Sub 1": entry["substitution_1"],
                "Sub 2": entry["substitution_2"],
                "Notes": entry["notes"],
            }
        )
    return pd.DataFrame(rows)


def build_log_editor_data(
    exercises: list[dict[str, Any]], previous_logs: list[dict[str, Any]]
) -> pd.DataFrame:
    last_session_by_exercise: dict[str, dict[str, Any]] = {}
    for session in previous_logs:
        for item in session.get("entries", []):
            exercise_name = item.get("exercise")
            if exercise_name:
                last_session_by_exercise[exercise_name] = item

    rows = []
    for entry in exercises:
        previous = last_session_by_exercise.get(entry["exercise"], {})
        rows.append(
            {
                "Exercise": entry["exercise"],
                "Set 1 Load": previous.get("set_1_load", ""),
                "Set 1 Reps": previous.get("set_1_reps", ""),
                "Set 2 Load": previous.get("set_2_load", ""),
                "Set 2 Reps": previous.get("set_2_reps", ""),
                "Session Notes": previous.get("session_notes", ""),
            }
        )
    return pd.DataFrame(rows)


def render_exercise_cards(exercises: list[dict[str, Any]]) -> None:
    for index, entry in enumerate(exercises, start=1):
        with st.container(border=True):
            st.markdown(f"### {index}. {entry['exercise']}")

            summary_columns = st.columns(5)
            summary_columns[0].metric("Warm-Up", str(entry["warm_up_sets"]))
            summary_columns[1].metric("Working Sets", str(entry["working_sets"]))
            summary_columns[2].metric("Rep Range", entry["rep_range"])
            summary_columns[3].metric(
                "RIR Targets", f"{entry['rir_set_1']} / {entry['rir_set_2']}"
            )
            summary_columns[4].metric("Rest", entry["rest"])

            st.caption(f"Technique: {entry['intensity_technique']}")
            st.write(
                f"Substitutions: {entry['substitution_1']} | {entry['substitution_2']}"
            )
            st.write(entry["notes"])


def filter_logs(
    logs: list[dict[str, Any]], week_key: str, day_key: str
) -> list[dict[str, Any]]:
    return [
        session
        for session in logs
        if session.get("week_key") == week_key and session.get("day_key") == day_key
    ]


def append_session_log(
    logs: list[dict[str, Any]],
    week_key: str,
    week_label: str,
    day_key: str,
    day_label: str,
    session_date: date,
    session_rows: pd.DataFrame,
    overall_notes: str,
) -> None:
    log_entry = {
        "logged_at": datetime.now().isoformat(timespec="seconds"),
        "session_date": session_date.isoformat(),
        "week_key": week_key,
        "week_label": week_label,
        "day_key": day_key,
        "day_label": day_label,
        "overall_notes": overall_notes.strip(),
        "entries": [],
    }

    for row in session_rows.to_dict(orient="records"):
        log_entry["entries"].append(
            {
                "exercise": row["Exercise"],
                "set_1_load": str(row["Set 1 Load"]).strip(),
                "set_1_reps": str(row["Set 1 Reps"]).strip(),
                "set_2_load": str(row["Set 2 Load"]).strip(),
                "set_2_reps": str(row["Set 2 Reps"]).strip(),
                "session_notes": str(row["Session Notes"]).strip(),
            }
        )

    logs.append(log_entry)
    save_logs(logs)


def main() -> None:
    st.title("GymTrack")
    st.write(
        "Browse your plan, log your session, and keep expanding the program over time."
    )
    st.info(
        "This version stores logs in a local JSON file. That works locally, but Streamlit Community Cloud does not provide durable file storage for long-term logging."
    )

    program = load_program()
    logs = load_logs()

    weeks = program.get("weeks", {})
    if not weeks:
        st.error("No workout plan data found in data/program.yaml.")
        return

    week_options = {details["label"]: key for key, details in weeks.items()}
    selected_week_label = st.sidebar.selectbox(
        "Choose week", options=list(week_options.keys())
    )
    selected_week_key = week_options[selected_week_label]
    selected_week = weeks[selected_week_key]

    days = selected_week.get("days", {})
    if not days:
        st.warning("This week does not have any sessions yet.")
        return

    day_options = {details["label"]: key for key, details in days.items()}
    selected_day_label = st.sidebar.selectbox(
        "Choose workout day", options=list(day_options.keys())
    )
    selected_day_key = day_options[selected_day_label]
    selected_day = days[selected_day_key]

    st.sidebar.markdown("---")
    st.sidebar.caption(f"Program: {program.get('program_name', 'Workout Program')}")
    st.sidebar.caption(f"Block: {selected_week.get('block', 'N/A')}")
    st.sidebar.caption(f"Phase: {selected_week.get('phase', 'N/A')}")

    exercises = selected_day.get("exercises", [])
    if not exercises:
        st.warning("This workout day has no exercises yet.")
        return

    st.subheader(f"{selected_week_label} - {selected_day_label}")
    st.caption(
        f"{selected_week.get('block', 'Block')} | {selected_week.get('phase', 'Phase')}"
    )

    overview_columns = st.columns(4)
    overview_columns[0].metric("Exercises", len(exercises))
    overview_columns[1].metric(
        "Working Sets", sum(int(item["working_sets"]) for item in exercises)
    )
    overview_columns[2].metric(
        "Longest Rest",
        max((item["rest"] for item in exercises), key=len),
    )
    overview_columns[3].metric(
        "Focus",
        selected_day_label,
    )

    plan_tab, log_tab, history_tab = st.tabs(["Planned Workout", "Log Session", "History"])

    with plan_tab:
        st.markdown("#### Exercise cards")
        render_exercise_cards(exercises)

        st.markdown("#### Table view")
        st.dataframe(build_plan_table(exercises), use_container_width=True, hide_index=True)

    matching_logs = filter_logs(logs, selected_week_key, selected_day_key)

    with log_tab:
        st.markdown("#### Log today's workout")
        default_editor = build_log_editor_data(exercises, matching_logs)

        with st.form(key=f"log-form-{selected_week_key}-{selected_day_key}"):
            session_date = st.date_input("Session date", value=date.today())
            edited_df = st.data_editor(
                default_editor,
                use_container_width=True,
                hide_index=True,
                disabled=["Exercise"],
                column_config={
                    "Set 1 Load": st.column_config.TextColumn("Set 1 Load"),
                    "Set 1 Reps": st.column_config.TextColumn("Set 1 Reps"),
                    "Set 2 Load": st.column_config.TextColumn("Set 2 Load"),
                    "Set 2 Reps": st.column_config.TextColumn("Set 2 Reps"),
                    "Session Notes": st.column_config.TextColumn("Session Notes", width="large"),
                },
            )
            overall_notes = st.text_area(
                "Overall session notes",
                placeholder="Energy, pumps, substitutions used, or anything to remember next time.",
            )
            submitted = st.form_submit_button("Save session log", use_container_width=True)

        if submitted:
            try:
                append_session_log(
                    logs=logs,
                    week_key=selected_week_key,
                    week_label=selected_week_label,
                    day_key=selected_day_key,
                    day_label=selected_day_label,
                    session_date=session_date,
                    session_rows=edited_df,
                    overall_notes=overall_notes,
                )
            except OSError as error:
                st.error(f"Could not save the session log: {error}")
            else:
                st.success("Session saved to data/workout_logs.json")
                st.rerun()

    with history_tab:
        st.markdown("#### Previous logs")

        if not matching_logs:
            st.write("No logs saved for this workout yet.")
            return

        for session in reversed(matching_logs):
            session_label = session.get("session_date", "Unknown date")
            with st.expander(f"Session on {session_label}", expanded=False):
                st.caption(f"Saved at {session.get('logged_at', 'Unknown time')}")
                if session.get("overall_notes"):
                    st.write(session["overall_notes"])

                history_rows = []
                for item in session.get("entries", []):
                    history_rows.append(
                        {
                            "Exercise": item.get("exercise", ""),
                            "Set 1 Load": item.get("set_1_load", ""),
                            "Set 1 Reps": item.get("set_1_reps", ""),
                            "Set 2 Load": item.get("set_2_load", ""),
                            "Set 2 Reps": item.get("set_2_reps", ""),
                            "Notes": item.get("session_notes", ""),
                        }
                    )

                st.dataframe(
                    pd.DataFrame(history_rows),
                    use_container_width=True,
                    hide_index=True,
                )


if __name__ == "__main__":
    main()

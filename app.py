from __future__ import annotations

import json
import uuid
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
LOG_COLUMNS = [
    "session_id",
    "logged_at",
    "session_date",
    "week_key",
    "week_label",
    "day_key",
    "day_label",
    "overall_notes",
    "exercise",
    "set_1_load",
    "set_1_reps",
    "set_2_load",
    "set_2_reps",
    "session_notes",
]
REPS_PRESETS = ["6", "8", "10"]
WEIGHT_PRESETS = ["25", "50", "100"]


class LogStore:
    name = "Unknown"
    durable = False

    def load_logs(self) -> list[dict[str, Any]]:
        raise NotImplementedError

    def append_session_log(
        self,
        week_key: str,
        week_label: str,
        day_key: str,
        day_label: str,
        session_date: date,
        session_rows: pd.DataFrame,
        overall_notes: str,
    ) -> None:
        raise NotImplementedError


class LocalJsonLogStore(LogStore):
    name = "Local JSON file"
    durable = False

    def __init__(self, path: Path) -> None:
        self.path = path

    def load_logs(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []

        with self.path.open("r", encoding="utf-8") as file:
            payload = json.load(file)
            return payload if isinstance(payload, list) else []

    def append_session_log(
        self,
        week_key: str,
        week_label: str,
        day_key: str,
        day_label: str,
        session_date: date,
        session_rows: pd.DataFrame,
        overall_notes: str,
    ) -> None:
        logs = self.load_logs()
        logs.append(
            build_session_log(
                week_key=week_key,
                week_label=week_label,
                day_key=day_key,
                day_label=day_label,
                session_date=session_date,
                session_rows=session_rows,
                overall_notes=overall_notes,
            )
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("w", encoding="utf-8") as file:
            json.dump(logs, file, indent=2)


class GoogleSheetsLogStore(LogStore):
    name = "Google Sheets"
    durable = True

    def __init__(self, service_account_info: dict[str, Any], config: dict[str, Any]) -> None:
        self.service_account_info = service_account_info
        self.spreadsheet_id = config.get("spreadsheet_id", "").strip()
        self.spreadsheet_name = config.get("spreadsheet_name", "").strip()
        self.worksheet_name = config.get("worksheet_name", "session_logs").strip()

    def load_logs(self) -> list[dict[str, Any]]:
        worksheet = self._get_worksheet()
        rows = worksheet.get_all_records(expected_headers=LOG_COLUMNS)
        return rows_to_sessions(rows)

    def append_session_log(
        self,
        week_key: str,
        week_label: str,
        day_key: str,
        day_label: str,
        session_date: date,
        session_rows: pd.DataFrame,
        overall_notes: str,
    ) -> None:
        session = build_session_log(
            week_key=week_key,
            week_label=week_label,
            day_key=day_key,
            day_label=day_label,
            session_date=session_date,
            session_rows=session_rows,
            overall_notes=overall_notes,
        )
        worksheet = self._get_worksheet()
        rows = []
        for entry in session["entries"]:
            rows.append(
                [
                    session["session_id"],
                    session["logged_at"],
                    session["session_date"],
                    session["week_key"],
                    session["week_label"],
                    session["day_key"],
                    session["day_label"],
                    session["overall_notes"],
                    entry["exercise"],
                    entry["set_1_load"],
                    entry["set_1_reps"],
                    entry["set_2_load"],
                    entry["set_2_reps"],
                    entry["session_notes"],
                ]
            )
        worksheet.append_rows(rows, value_input_option="USER_ENTERED")

    def _get_worksheet(self):
        try:
            import gspread
            from google.oauth2.service_account import Credentials
        except ImportError as error:
            raise RuntimeError(
                "Google Sheets dependencies are not installed. Add gspread and google-auth."
            ) from error

        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive",
        ]
        credentials = Credentials.from_service_account_info(
            self.service_account_info,
            scopes=scopes,
        )
        client = gspread.authorize(credentials)

        if self.spreadsheet_id:
            spreadsheet = client.open_by_key(self.spreadsheet_id)
        elif self.spreadsheet_name:
            spreadsheet = client.open(self.spreadsheet_name)
        else:
            raise RuntimeError(
                "Missing Google Sheets configuration. Provide spreadsheet_id or spreadsheet_name in Streamlit secrets."
            )

        try:
            worksheet = spreadsheet.worksheet(self.worksheet_name)
        except gspread.WorksheetNotFound:
            worksheet = spreadsheet.add_worksheet(
                title=self.worksheet_name,
                rows=1000,
                cols=len(LOG_COLUMNS) + 2,
            )

        current_header = worksheet.row_values(1)
        if current_header != LOG_COLUMNS:
            worksheet.clear()
            worksheet.append_row(LOG_COLUMNS, value_input_option="USER_ENTERED")

        return worksheet


def load_program() -> dict[str, Any]:
    with PROGRAM_PATH.open("r", encoding="utf-8") as file:
        return yaml.safe_load(file) or {}


def build_session_log(
    week_key: str,
    week_label: str,
    day_key: str,
    day_label: str,
    session_date: date,
    session_rows: pd.DataFrame,
    overall_notes: str,
) -> dict[str, Any]:
    session = {
        "session_id": str(uuid.uuid4()),
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
        session["entries"].append(
            {
                "exercise": row["Exercise"],
                "set_1_load": str(row["Set 1 Load"]).strip(),
                "set_1_reps": str(row["Set 1 Reps"]).strip(),
                "set_2_load": str(row["Set 2 Load"]).strip(),
                "set_2_reps": str(row["Set 2 Reps"]).strip(),
                "session_notes": str(row["Session Notes"]).strip(),
            }
        )

    return session


def rows_to_sessions(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    sessions_by_id: dict[str, dict[str, Any]] = {}

    for row in rows:
        session_id = str(row.get("session_id", "")).strip()
        if not session_id:
            continue

        session = sessions_by_id.setdefault(
            session_id,
            {
                "session_id": session_id,
                "logged_at": str(row.get("logged_at", "")).strip(),
                "session_date": str(row.get("session_date", "")).strip(),
                "week_key": str(row.get("week_key", "")).strip(),
                "week_label": str(row.get("week_label", "")).strip(),
                "day_key": str(row.get("day_key", "")).strip(),
                "day_label": str(row.get("day_label", "")).strip(),
                "overall_notes": str(row.get("overall_notes", "")).strip(),
                "entries": [],
            },
        )

        session["entries"].append(
            {
                "exercise": str(row.get("exercise", "")).strip(),
                "set_1_load": str(row.get("set_1_load", "")).strip(),
                "set_1_reps": str(row.get("set_1_reps", "")).strip(),
                "set_2_load": str(row.get("set_2_load", "")).strip(),
                "set_2_reps": str(row.get("set_2_reps", "")).strip(),
                "session_notes": str(row.get("session_notes", "")).strip(),
            }
        )

    return list(sessions_by_id.values())


def get_log_store() -> tuple[LogStore, str | None]:
    google_config = dict(st.secrets.get("google_sheets", {}))
    service_account_info = dict(st.secrets.get("gcp_service_account", {}))

    if google_config and service_account_info:
        try:
            return GoogleSheetsLogStore(service_account_info, google_config), None
        except Exception as error:
            return (
                LocalJsonLogStore(LOGS_PATH),
                f"Google Sheets is configured, but the app fell back to local JSON: {error}",
            )

    return LocalJsonLogStore(LOGS_PATH), None


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


def get_preset_or_custom(value: Any, presets: list[str]) -> tuple[str | None, str]:
    cleaned_value = str(value).strip()
    if not cleaned_value:
        return None, ""
    if cleaned_value in presets:
        return cleaned_value, ""
    return None, cleaned_value


def render_quick_pick_input(
    label: str,
    widget_prefix: str,
    presets: list[str],
    default_value: Any,
) -> str:
    selected_preset, custom_default = get_preset_or_custom(default_value, presets)
    option_labels = ["None", *presets]
    selected_option = st.radio(
        label,
        options=option_labels,
        index=option_labels.index(selected_preset) if selected_preset else 0,
        horizontal=True,
        key=f"{widget_prefix}_preset",
    )
    custom_value = st.text_input(
        f"{label} custom",
        value=custom_default,
        placeholder="Custom",
        key=f"{widget_prefix}_custom",
    ).strip()

    if custom_value:
        return custom_value
    if selected_option == "None":
        return ""
    return selected_option


def build_log_rows_from_form(
    exercises: list[dict[str, Any]], previous_logs: list[dict[str, Any]]
) -> pd.DataFrame:
    previous_rows = build_log_editor_data(exercises, previous_logs)
    previous_by_exercise = {
        row["Exercise"]: row for row in previous_rows.to_dict(orient="records")
    }

    rows = []
    for index, entry in enumerate(exercises):
        exercise_name = entry["exercise"]
        previous = previous_by_exercise.get(exercise_name, {})

        with st.container(border=True):
            st.markdown(f"### {index + 1}. {exercise_name}")
            st.caption(
                f"Target: {entry['rep_range']} reps | Rest: {entry['rest']} | "
                f"RIR: {entry['rir_set_1']} / {entry['rir_set_2']}"
            )
            if any(previous.get(field, "") for field in ("Set 1 Load", "Set 1 Reps", "Set 2 Load", "Set 2 Reps")):
                st.caption(
                    "Previous: "
                    f"S1 {previous.get('Set 1 Load', '-') or '-'} x {previous.get('Set 1 Reps', '-') or '-'} | "
                    f"S2 {previous.get('Set 2 Load', '-') or '-'} x {previous.get('Set 2 Reps', '-') or '-'}"
                )

            st.markdown("**Set 1**")
            set_1_reps = render_quick_pick_input(
                "Reps",
                f"{exercise_name}_{index}_set1_reps",
                REPS_PRESETS,
                previous.get("Set 1 Reps", ""),
            )
            set_1_load = render_quick_pick_input(
                "Weight",
                f"{exercise_name}_{index}_set1_load",
                WEIGHT_PRESETS,
                previous.get("Set 1 Load", ""),
            )

            st.markdown("**Set 2**")
            set_2_reps = render_quick_pick_input(
                "Reps",
                f"{exercise_name}_{index}_set2_reps",
                REPS_PRESETS,
                previous.get("Set 2 Reps", ""),
            )
            set_2_load = render_quick_pick_input(
                "Weight",
                f"{exercise_name}_{index}_set2_load",
                WEIGHT_PRESETS,
                previous.get("Set 2 Load", ""),
            )

            session_notes = st.text_input(
                "Exercise notes",
                value=previous.get("Session Notes", ""),
                placeholder="Optional notes for this exercise",
                key=f"{exercise_name}_{index}_notes",
            ).strip()

        rows.append(
            {
                "Exercise": exercise_name,
                "Set 1 Load": set_1_load,
                "Set 1 Reps": set_1_reps,
                "Set 2 Load": set_2_load,
                "Set 2 Reps": set_2_reps,
                "Session Notes": session_notes,
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


def sort_logs_desc(logs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        logs,
        key=lambda session: (
            session.get("session_date", ""),
            session.get("logged_at", ""),
        ),
        reverse=True,
    )


def render_history(logs: list[dict[str, Any]], selected_week_label: str) -> None:
    st.markdown("#### All logged sessions")

    if not logs:
        st.write("No sessions have been logged yet.")
        return

    available_weeks = ["All weeks"] + sorted(
        {session.get("week_label", "Unknown week") for session in logs}
    )
    week_filter = st.selectbox(
        "Filter history by week",
        options=available_weeks,
        index=available_weeks.index(selected_week_label)
        if selected_week_label in available_weeks
        else 0,
    )

    filtered_logs = logs
    if week_filter != "All weeks":
        filtered_logs = [
            session
            for session in filtered_logs
            if session.get("week_label") == week_filter
        ]

    if not filtered_logs:
        st.write("No logged sessions match this filter yet.")
        return

    for session in filtered_logs:
        session_label = session.get("session_date", "Unknown date")
        workout_label = (
            f"{session.get('week_label', 'Unknown week')} - "
            f"{session.get('day_label', 'Unknown workout')}"
        )
        with st.expander(f"{session_label} | {workout_label}", expanded=False):
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


def render_storage_status(log_store: LogStore, warning: str | None) -> None:
    if warning:
        st.warning(warning)

    if log_store.durable:
        st.success(f"Log storage: {log_store.name}. Session logs are persistent.")
    else:
        st.info(
            f"Log storage: {log_store.name}. This works locally, but Streamlit Community Cloud will not keep app-written JSON files permanently."
        )


def main() -> None:
    st.title("GymTrack")
    st.write(
        "Browse your plan, log your session, and keep expanding the program over time."
    )

    log_store, storage_warning = get_log_store()
    render_storage_status(log_store, storage_warning)

    program = load_program()
    logs = sort_logs_desc(log_store.load_logs())

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
    st.sidebar.caption(f"Logs: {log_store.name}")

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
    overview_columns[2].metric("Logged Sessions", len(logs))
    overview_columns[3].metric("Focus", selected_day_label)

    plan_tab, log_tab, history_tab = st.tabs(
        ["Planned Workout", "Log Session", "Session History"]
    )

    with plan_tab:
        st.markdown("#### Exercise cards")
        render_exercise_cards(exercises)

        st.markdown("#### Table view")
        st.dataframe(
            build_plan_table(exercises),
            use_container_width=True,
            hide_index=True,
        )

    matching_logs = filter_logs(logs, selected_week_key, selected_day_key)

    with log_tab:
        st.markdown("#### Log today's workout")
        st.caption(
            "Logs are saved globally and will show up in the centralized session history tab."
        )

        with st.form(key=f"log-form-{selected_week_key}-{selected_day_key}"):
            session_date = st.date_input("Session date", value=date.today())
            edited_df = build_log_rows_from_form(exercises, matching_logs)
            overall_notes = st.text_area(
                "Overall session notes",
                placeholder="Energy, pumps, substitutions used, or anything to remember next time.",
            )
            submitted = st.form_submit_button("Save session log", use_container_width=True)

        if submitted:
            try:
                log_store.append_session_log(
                    week_key=selected_week_key,
                    week_label=selected_week_label,
                    day_key=selected_day_key,
                    day_label=selected_day_label,
                    session_date=session_date,
                    session_rows=edited_df,
                    overall_notes=overall_notes,
                )
            except Exception as error:
                st.error(f"Could not save the session log: {error}")
            else:
                st.success(f"Session saved to {log_store.name}")
                st.rerun()

    with history_tab:
        render_history(logs, selected_week_label)


if __name__ == "__main__":
    main()

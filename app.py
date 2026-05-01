from __future__ import annotations

import json
from datetime import date, datetime, timedelta
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
DEFAULT_SCHEDULE = {
    "monday": "upper_1",
    "tuesday": "lower_1",
    "wednesday": "upper_2",
    "thursday": "lower_2",
    "friday": "arms_delts",
    "saturday": "rest",
    "sunday": "rest",
}
STATUS_COLORS = {
    "Completed": "#2f7d32",
    "In Progress": "#a05a00",
    "Missed": "#b42318",
    "Rest": "#5f6c7b",
    "Due": "#1d4ed8",
    "Upcoming": "#6b7280",
}


class LogStore:
    name = "Unknown"
    durable = False

    def load_rows(self) -> list[dict[str, str]]:
        raise NotImplementedError

    def upsert_exercise_log(self, row: dict[str, str]) -> None:
        raise NotImplementedError


class LocalJsonLogStore(LogStore):
    name = "Local JSON file"
    durable = False

    def __init__(self, path: Path) -> None:
        self.path = path

    def load_rows(self) -> list[dict[str, str]]:
        if not self.path.exists():
            return []

        with self.path.open("r", encoding="utf-8") as file:
            payload = json.load(file)

        if not isinstance(payload, list):
            return []

        if payload and isinstance(payload[0], dict) and "entries" in payload[0]:
            rows: list[dict[str, str]] = []
            for session in payload:
                rows.extend(session_to_rows(session))
            return rows

        return [normalize_row_dict(item) for item in payload if isinstance(item, dict)]

    def upsert_exercise_log(self, row: dict[str, str]) -> None:
        rows = self.load_rows()
        rows = upsert_row(rows, row)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("w", encoding="utf-8") as file:
            json.dump(rows, file, indent=2)


class GoogleSheetsLogStore(LogStore):
    name = "Google Sheets"
    durable = True

    def __init__(self, service_account_info: dict[str, Any], config: dict[str, Any]) -> None:
        self.service_account_info = service_account_info
        self.spreadsheet_id = config.get("spreadsheet_id", "").strip()
        self.spreadsheet_name = config.get("spreadsheet_name", "").strip()
        self.worksheet_name = config.get("worksheet_name", "session_logs").strip()

    def load_rows(self) -> list[dict[str, str]]:
        worksheet = self._get_worksheet()
        values = worksheet.get_all_values()
        if not values:
            worksheet.append_row(LOG_COLUMNS, value_input_option="USER_ENTERED")
            return []

        header = values[0]
        rows: list[dict[str, str]] = []
        for raw_row in values[1:]:
            row_dict = {
                header[index]: raw_row[index] if index < len(raw_row) else ""
                for index in range(len(header))
            }
            rows.append(normalize_row_dict(row_dict))
        return rows

    def upsert_exercise_log(self, row: dict[str, str]) -> None:
        worksheet = self._get_worksheet()
        values = worksheet.get_all_values()
        if not values:
            worksheet.append_row(LOG_COLUMNS, value_input_option="USER_ENTERED")
            values = [LOG_COLUMNS]

        header = values[0]
        matching_row_number: int | None = None

        for row_number, raw_row in enumerate(values[1:], start=2):
            row_dict = {
                header[index]: raw_row[index] if index < len(raw_row) else ""
                for index in range(len(header))
            }
            normalized = normalize_row_dict(row_dict)
            if rows_match(normalized, row):
                matching_row_number = row_number
                break

        ordered_values = [[row[column] for column in LOG_COLUMNS]]
        if matching_row_number is not None:
            worksheet.update(
                f"A{matching_row_number}:N{matching_row_number}",
                ordered_values,
                value_input_option="USER_ENTERED",
            )
        else:
            worksheet.append_rows(ordered_values, value_input_option="USER_ENTERED")

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

        if not worksheet.get_all_values():
            worksheet.append_row(LOG_COLUMNS, value_input_option="USER_ENTERED")

        return worksheet


def load_program_file() -> dict[str, Any]:
    with PROGRAM_PATH.open("r", encoding="utf-8") as file:
        return yaml.safe_load(file) or {}


def slugify(value: str) -> str:
    characters = []
    for char in value.lower():
        if char.isalnum():
            characters.append(char)
        else:
            characters.append("_")
    slug = "".join(characters)
    while "__" in slug:
        slug = slug.replace("__", "_")
    return slug.strip("_")


def normalize_program(raw_program: dict[str, Any]) -> dict[str, Any]:
    if raw_program.get("exercises") and raw_program.get("workouts"):
        return raw_program

    schedule = raw_program.get("schedule", DEFAULT_SCHEDULE)
    start_date = raw_program.get("start_date", "2026-04-07")
    week_one_days = raw_program.get("weeks", {}).get("week_1", {}).get("days", {})

    exercises: dict[str, dict[str, Any]] = {}
    workouts: dict[str, dict[str, Any]] = {}

    for workout_key, workout in week_one_days.items():
        workout_entries = []
        for item in workout.get("exercises", []):
            exercise_name = item["exercise"]
            exercise_key = slugify(exercise_name)

            exercises.setdefault(
                exercise_key,
                {
                    "name": exercise_name,
                    "notes": item.get("notes", ""),
                    "substitution_1": item.get("substitution_1", ""),
                    "substitution_2": item.get("substitution_2", ""),
                    "video_url": item.get("video_url", ""),
                    "image_url": item.get("image_url", ""),
                    "image_path": item.get("image_path", ""),
                },
            )

            workout_entries.append(
                {
                    "exercise_key": exercise_key,
                    "intensity_technique": item.get("intensity_technique", "N/A"),
                    "warm_up_sets": item.get("warm_up_sets", ""),
                    "working_sets": item.get("working_sets", ""),
                    "rep_range": item.get("rep_range", ""),
                    "rir_set_1": item.get("rir_set_1", ""),
                    "rir_set_2": item.get("rir_set_2", ""),
                    "rest": item.get("rest", ""),
                }
            )

        workouts[workout_key] = {
            "label": workout.get("label", workout_key.replace("_", " ").title()),
            "exercises": workout_entries,
        }

    return {
        "program_name": raw_program.get("program_name", "Workout Program"),
        "start_date": start_date,
        "schedule": schedule,
        "exercises": exercises,
        "workouts": workouts,
    }


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


def normalize_row_dict(row: dict[str, Any]) -> dict[str, str]:
    normalized: dict[str, str] = {}
    for column in LOG_COLUMNS:
        normalized[column] = str(row.get(column, "")).strip()
    return normalized


def session_to_rows(session: dict[str, Any]) -> list[dict[str, str]]:
    rows = []
    for entry in session.get("entries", []):
        rows.append(
            normalize_row_dict(
                {
                    "session_id": session.get("session_id", ""),
                    "logged_at": session.get("logged_at", ""),
                    "session_date": session.get("session_date", ""),
                    "week_key": session.get("week_key", ""),
                    "week_label": session.get("week_label", ""),
                    "day_key": session.get("day_key", ""),
                    "day_label": session.get("day_label", ""),
                    "overall_notes": session.get("overall_notes", ""),
                    "exercise": entry.get("exercise", ""),
                    "set_1_load": entry.get("set_1_load", ""),
                    "set_1_reps": entry.get("set_1_reps", ""),
                    "set_2_load": entry.get("set_2_load", ""),
                    "set_2_reps": entry.get("set_2_reps", ""),
                    "session_notes": entry.get("session_notes", ""),
                }
            )
        )
    return rows


def upsert_row(rows: list[dict[str, str]], new_row: dict[str, str]) -> list[dict[str, str]]:
    updated = False
    result = []
    for row in rows:
        if rows_match(row, new_row):
            result.append(new_row)
            updated = True
        else:
            result.append(row)
    if not updated:
        result.append(new_row)
    return result


def rows_match(existing: dict[str, str], new_row: dict[str, str]) -> bool:
    return (
        existing.get("session_date") == new_row.get("session_date")
        and existing.get("day_key") == new_row.get("day_key")
        and existing.get("exercise") == new_row.get("exercise")
    )


def group_rows_to_sessions(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    sessions_by_id: dict[str, dict[str, Any]] = {}

    for row in rows:
        session_id = row.get("session_id", "") or build_session_id(
            row.get("session_date", ""),
            row.get("day_key", ""),
        )
        session = sessions_by_id.setdefault(
            session_id,
            {
                "session_id": session_id,
                "logged_at": row.get("logged_at", ""),
                "session_date": row.get("session_date", ""),
                "week_key": row.get("week_key", ""),
                "week_label": row.get("week_label", ""),
                "day_key": row.get("day_key", ""),
                "day_label": row.get("day_label", ""),
                "overall_notes": row.get("overall_notes", ""),
                "entries": [],
            },
        )

        if row.get("logged_at", "") > session["logged_at"]:
            session["logged_at"] = row.get("logged_at", "")

        session["entries"].append(
            {
                "exercise": row.get("exercise", ""),
                "set_1_load": row.get("set_1_load", ""),
                "set_1_reps": row.get("set_1_reps", ""),
                "set_2_load": row.get("set_2_load", ""),
                "set_2_reps": row.get("set_2_reps", ""),
                "session_notes": row.get("session_notes", ""),
            }
        )

    return sorted(
        sessions_by_id.values(),
        key=lambda session: (session.get("session_date", ""), session.get("logged_at", "")),
        reverse=True,
    )


def parse_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def calculate_week_number(start_date: date, selected_date: date) -> int:
    if selected_date < start_date:
        return 0
    return ((selected_date - start_date).days // 7) + 1


def get_week_bounds(start_date: date, week_number: int) -> tuple[date, date]:
    week_start = start_date + timedelta(days=(week_number - 1) * 7)
    week_end = week_start + timedelta(days=6)
    return week_start, week_end


def build_session_id(session_date: str, workout_key: str) -> str:
    return f"{session_date}::{workout_key}"


def format_value(value: str, fallback: str = "-") -> str:
    cleaned = str(value).strip()
    return cleaned if cleaned else fallback


def parse_numeric(value: str) -> float | None:
    cleaned = str(value).strip()
    if not cleaned:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def build_exercise_performance_map(rows: list[dict[str, str]]) -> dict[str, dict[str, Any]]:
    by_exercise: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        exercise_name = row.get("exercise", "")
        if exercise_name:
            by_exercise.setdefault(exercise_name, []).append(row)

    performance: dict[str, dict[str, Any]] = {}
    for exercise_name, exercise_rows in by_exercise.items():
        sorted_rows = sorted(
            exercise_rows,
            key=lambda row: (row.get("session_date", ""), row.get("logged_at", "")),
            reverse=True,
        )
        last_row = sorted_rows[0]
        best_label = compute_best_label(exercise_rows)
        performance[exercise_name] = {
            "last_row": last_row,
            "last_label": (
                f"S1 {format_value(last_row.get('set_1_load', ''))} x {format_value(last_row.get('set_1_reps', ''))} | "
                f"S2 {format_value(last_row.get('set_2_load', ''))} x {format_value(last_row.get('set_2_reps', ''))}"
            ),
            "best_label": best_label,
        }
    return performance


def compute_best_label(rows: list[dict[str, str]]) -> str:
    best: tuple[tuple[int, float, float], str] | None = None
    for row in rows:
        for set_number in ("1", "2"):
            weight = row.get(f"set_{set_number}_load", "")
            reps = row.get(f"set_{set_number}_reps", "")
            weight_value = parse_numeric(weight)
            reps_value = parse_numeric(reps)
            if weight_value is None and reps_value is None:
                continue

            score = (
                1 if weight_value is not None else 0,
                weight_value if weight_value is not None else -1.0,
                reps_value if reps_value is not None else -1.0,
            )

            if weight_value is not None:
                label = f"{format_value(weight)} x {format_value(reps)}"
            else:
                label = f"{format_value(reps)} reps"

            if best is None or score > best[0]:
                best = (score, label)

    return best[1] if best else "-"


def merge_workout_exercises(program: dict[str, Any], workout_key: str) -> list[dict[str, Any]]:
    workout = program["workouts"][workout_key]
    merged = []
    for entry in workout.get("exercises", []):
        exercise = program["exercises"][entry["exercise_key"]]
        merged.append({**exercise, **entry})
    return merged


def build_row_for_save(
    selected_date: date,
    week_number: int,
    workout_key: str,
    workout_label: str,
    exercise_name: str,
    set_1_load: str,
    set_1_reps: str,
    set_2_load: str,
    set_2_reps: str,
    session_notes: str,
) -> dict[str, str]:
    session_date = selected_date.isoformat()
    return normalize_row_dict(
        {
            "session_id": build_session_id(session_date, workout_key),
            "logged_at": datetime.now().isoformat(timespec="seconds"),
            "session_date": session_date,
            "week_key": f"week_{week_number}",
            "week_label": f"Week {week_number}",
            "day_key": workout_key,
            "day_label": workout_label,
            "overall_notes": "",
            "exercise": exercise_name,
            "set_1_load": set_1_load,
            "set_1_reps": set_1_reps,
            "set_2_load": set_2_load,
            "set_2_reps": set_2_reps,
            "session_notes": session_notes,
        }
    )


def get_rows_for_workout_date(
    rows: list[dict[str, str]], selected_date: date, workout_key: str
) -> dict[str, dict[str, str]]:
    session_date = selected_date.isoformat()
    result = {}
    for row in rows:
        if row.get("session_date") == session_date and row.get("day_key") == workout_key:
            result[row.get("exercise", "")] = row
    return result


def render_log_session_styles() -> None:
    st.markdown(
        """
        <style>
        div[data-testid="stTextInput"] input[aria-label^="wt_"] {
            border: 2px solid #cf4a43;
            background: rgba(207, 74, 67, 0.08);
            font-weight: 700;
            text-align: center;
        }
        div[data-testid="stTextInput"] input[aria-label^="rep_"] {
            border: 2px solid #3273dc;
            background: rgba(50, 115, 220, 0.08);
            font-weight: 700;
            text-align: center;
        }
        .exercise-card {
            border: 1px solid rgba(28, 28, 28, 0.08);
            border-radius: 18px;
            padding: 0.9rem;
            background: rgba(255, 255, 255, 0.8);
            margin-bottom: 0.9rem;
        }
        .exercise-title {
            font-size: 1.02rem;
            font-weight: 700;
            line-height: 1.2;
            margin-top: 0.15rem;
        }
        .exercise-meta {
            font-size: 0.82rem;
            color: #5d5d5d;
            margin-top: 0.35rem;
        }
        .status-pill {
            display: inline-block;
            margin-top: 0.45rem;
            padding: 0.18rem 0.5rem;
            border-radius: 999px;
            font-size: 0.72rem;
            font-weight: 700;
            color: white;
        }
        .week-card {
            border-radius: 16px;
            padding: 0.8rem 0.9rem;
            background: rgba(255, 255, 255, 0.82);
            border: 1px solid rgba(28, 28, 28, 0.07);
            margin-bottom: 0.7rem;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_storage_status(log_store: LogStore, warning: str | None) -> None:
    if warning:
        st.warning(warning)

    if log_store.durable:
        st.success(f"Log storage: {log_store.name}. Exercise logs are persistent.")
    else:
        st.info(
            f"Log storage: {log_store.name}. This works locally, but Streamlit Community Cloud will not keep app-written JSON files permanently."
        )


def render_history(sessions: list[dict[str, Any]]) -> None:
    st.markdown("#### Logged Workouts")
    if not sessions:
        st.write("No workouts logged yet.")
        return

    for session in sessions:
        label = (
            f"{session.get('session_date', 'Unknown date')} | "
            f"Week {session.get('week_label', '').replace('Week ', '') or '?'} | "
            f"{session.get('day_label', 'Workout')}"
        )
        with st.expander(label, expanded=False):
            rows = []
            for entry in session.get("entries", []):
                rows.append(
                    {
                        "Exercise": entry.get("exercise", ""),
                        "Set 1 Load": entry.get("set_1_load", ""),
                        "Set 1 Reps": entry.get("set_1_reps", ""),
                        "Set 2 Load": entry.get("set_2_load", ""),
                        "Set 2 Reps": entry.get("set_2_reps", ""),
                        "Notes": entry.get("session_notes", ""),
                    }
                )
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


def get_workout_status_for_date(
    rows: list[dict[str, str]],
    selected_date: date,
    workout_key: str,
    total_exercises: int,
    today: date,
) -> str:
    if workout_key == "rest":
        return "Rest"

    session_rows = get_rows_for_workout_date(rows, selected_date, workout_key)
    logged_count = len(session_rows)
    if logged_count >= total_exercises and total_exercises > 0:
        return "Completed"
    if logged_count > 0:
        return "In Progress"
    if selected_date < today:
        return "Missed"
    if selected_date == today:
        return "Due"
    return "Upcoming"


def render_program_week(
    start_date: date,
    week_number: int,
    schedule: dict[str, str],
    program: dict[str, Any],
    rows: list[dict[str, str]],
    today: date,
) -> None:
    st.markdown("#### Program Week")
    week_start, week_end = get_week_bounds(start_date, week_number)
    st.caption(f"Week {week_number}: {week_start.isoformat()} to {week_end.isoformat()}")

    for offset in range(7):
        current_date = week_start + timedelta(days=offset)
        weekday_name = current_date.strftime("%A").lower()
        scheduled_key = schedule.get(weekday_name, "rest")
        scheduled_label = (
            "Rest"
            if scheduled_key == "rest"
            else program["workouts"][scheduled_key]["label"]
        )
        total_exercises = (
            0
            if scheduled_key == "rest"
            else len(program["workouts"][scheduled_key]["exercises"])
        )
        status = get_workout_status_for_date(
            rows,
            current_date,
            scheduled_key,
            total_exercises,
            today,
        )
        color = STATUS_COLORS[status]
        st.markdown(
            f"""
            <div class="week-card">
              <div style="display:flex;justify-content:space-between;gap:1rem;align-items:center;">
                <div>
                  <div style="font-weight:700;">{current_date.strftime("%A, %b %d")}</div>
                  <div style="font-size:0.88rem;color:#5d5d5d;">{scheduled_label}</div>
                </div>
                <div class="status-pill" style="background:{color};">{status}</div>
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )


def render_workout_header(
    selected_date: date,
    workout_label: str,
    week_number: int,
    workout_status: str,
    completed_exercises: int,
    total_exercises: int,
) -> None:
    st.subheader(f"{workout_label} | Week {week_number}")
    st.caption(f"{selected_date.isoformat()} | Status: {workout_status}")
    progress_columns = st.columns(3)
    progress_columns[0].metric("Completed Exercises", completed_exercises)
    progress_columns[1].metric("Workout Size", total_exercises)
    progress_columns[2].metric("Progress", f"{completed_exercises}/{total_exercises}")


def render_exercise_logger(
    selected_date: date,
    week_number: int,
    workout_key: str,
    workout_label: str,
    exercise_entry: dict[str, Any],
    todays_row: dict[str, str] | None,
    performance: dict[str, Any],
    log_store: LogStore,
) -> None:
    exercise_name = exercise_entry["name"]
    last_row = performance.get(exercise_name, {}).get("last_row", {})
    last_label = performance.get(exercise_name, {}).get("last_label", "-")
    best_label = performance.get(exercise_name, {}).get("best_label", "-")

    default_row = todays_row or last_row or {}
    status = "Saved" if todays_row else "Not Saved"
    status_color = STATUS_COLORS["Completed"] if todays_row else STATUS_COLORS["Upcoming"]

    with st.container(border=True):
        with st.form(key=f"{selected_date.isoformat()}::{workout_key}::{exercise_name}"):
            title_col, s1w_col, s1r_col, s2w_col, s2r_col = st.columns(
                [2.6, 1, 1, 1, 1],
                gap="small",
            )

            with title_col:
                st.markdown(
                    f'<div class="exercise-title">{exercise_name}</div>',
                    unsafe_allow_html=True,
                )
                st.markdown(
                    f'<span class="status-pill" style="background:{status_color};">{status}</span>',
                    unsafe_allow_html=True,
                )

            with s1w_col:
                set_1_load = st.text_input(
                    f"wt_{exercise_name}_s1",
                    value=default_row.get("set_1_load", ""),
                    placeholder="S1 Wt",
                    label_visibility="collapsed",
                ).strip()

            with s1r_col:
                set_1_reps = st.text_input(
                    f"rep_{exercise_name}_s1",
                    value=default_row.get("set_1_reps", ""),
                    placeholder="S1 Rep",
                    label_visibility="collapsed",
                ).strip()

            with s2w_col:
                set_2_load = st.text_input(
                    f"wt_{exercise_name}_s2",
                    value=default_row.get("set_2_load", ""),
                    placeholder="S2 Wt",
                    label_visibility="collapsed",
                ).strip()

            with s2r_col:
                set_2_reps = st.text_input(
                    f"rep_{exercise_name}_s2",
                    value=default_row.get("set_2_reps", ""),
                    placeholder="S2 Rep",
                    label_visibility="collapsed",
                ).strip()

            st.markdown(
                f'<div class="exercise-meta">'
                f"Target: {exercise_entry['rep_range']} | "
                f"Rest: {exercise_entry['rest']} | "
                f"RIR: {exercise_entry['rir_set_1']} / {exercise_entry['rir_set_2']} | "
                f"Last: {last_label} | "
                f"Best: {best_label}"
                f"</div>",
                unsafe_allow_html=True,
            )

            with st.expander("Details", expanded=False):
                st.caption(f"Technique: {exercise_entry['intensity_technique']}")
                st.caption(
                    f"Warm-Up: {exercise_entry['warm_up_sets']} | "
                    f"Working Sets: {exercise_entry['working_sets']}"
                )
                st.write(
                    f"Substitutions: {exercise_entry.get('substitution_1', '')} | "
                    f"{exercise_entry.get('substitution_2', '')}"
                )
                st.write(exercise_entry.get("notes", ""))

                video_url = str(exercise_entry.get("video_url", "")).strip()
                image_url = str(exercise_entry.get("image_url", "")).strip()
                image_path = str(exercise_entry.get("image_path", "")).strip()
                if video_url:
                    st.video(video_url)
                elif image_url:
                    st.image(image_url, use_container_width=True)
                elif image_path:
                    st.image(image_path, use_container_width=True)

                session_notes = st.text_input(
                    "Exercise notes",
                    value=default_row.get("session_notes", ""),
                    placeholder="Optional notes",
                    key=f"notes::{selected_date.isoformat()}::{workout_key}::{exercise_name}",
                ).strip()

            submitted = st.form_submit_button(
                "Save Exercise",
                use_container_width=True,
            )

        if submitted:
            row = build_row_for_save(
                selected_date=selected_date,
                week_number=week_number,
                workout_key=workout_key,
                workout_label=workout_label,
                exercise_name=exercise_name,
                set_1_load=set_1_load,
                set_1_reps=set_1_reps,
                set_2_load=set_2_load,
                set_2_reps=set_2_reps,
                session_notes=session_notes,
            )
            log_store.upsert_exercise_log(row)
            st.session_state["flash_message"] = f"Saved {exercise_name}"
            st.rerun()


def main() -> None:
    log_store, storage_warning = get_log_store()
    raw_program = load_program_file()
    program = normalize_program(raw_program)
    rows = log_store.load_rows()
    sessions = group_rows_to_sessions(rows)
    performance = build_exercise_performance_map(rows)

    start_date = parse_date(program["start_date"])
    today = date.today()

    st.title(program["program_name"])
    render_storage_status(log_store, storage_warning)

    if "flash_message" in st.session_state:
        st.success(st.session_state.pop("flash_message"))

    selected_date = st.sidebar.date_input("Workout date", value=today)
    if isinstance(selected_date, tuple):
        selected_date = selected_date[0]

    if selected_date < start_date:
        st.error(
            f"Selected date is before your program start date of {start_date.isoformat()}."
        )
        return

    week_number = calculate_week_number(start_date, selected_date)
    week_start, week_end = get_week_bounds(start_date, week_number)

    schedule = {
        str(day).lower(): str(workout_key)
        for day, workout_key in program.get("schedule", DEFAULT_SCHEDULE).items()
    }
    weekday_name = selected_date.strftime("%A").lower()
    scheduled_workout_key = schedule.get(weekday_name, "rest")

    workout_options = {
        workout["label"]: workout_key
        for workout_key, workout in program["workouts"].items()
    }
    workout_labels = list(workout_options.keys())

    if scheduled_workout_key != "rest":
        default_workout_label = program["workouts"][scheduled_workout_key]["label"]
    else:
        default_workout_label = workout_labels[0]

    selected_workout_label = st.sidebar.selectbox(
        "Workout template",
        options=workout_labels,
        index=workout_labels.index(default_workout_label),
    )
    selected_workout_key = workout_options[selected_workout_label]

    st.sidebar.markdown("---")
    st.sidebar.caption(f"Program Start: {start_date.isoformat()}")
    st.sidebar.caption(f"Week {week_number}: {week_start.isoformat()} to {week_end.isoformat()}")
    st.sidebar.caption(
        "Scheduled Today: "
        + (
            "Rest"
            if scheduled_workout_key == "rest"
            else program["workouts"][scheduled_workout_key]["label"]
        )
    )
    st.sidebar.caption(f"Logs: {log_store.name}")

    workout_exercises = merge_workout_exercises(program, selected_workout_key)
    todays_rows = get_rows_for_workout_date(rows, selected_date, selected_workout_key)
    total_exercises = len(workout_exercises)
    completed_exercises = len(todays_rows)
    workout_status = get_workout_status_for_date(
        rows,
        selected_date,
        selected_workout_key,
        total_exercises,
        today,
    )

    render_log_session_styles()
    render_workout_header(
        selected_date=selected_date,
        workout_label=selected_workout_label,
        week_number=week_number,
        workout_status=workout_status,
        completed_exercises=completed_exercises,
        total_exercises=total_exercises,
    )

    workout_tab, week_tab, history_tab = st.tabs(
        ["Workout", "Program Week", "History"]
    )

    with workout_tab:
        for exercise_entry in workout_exercises:
            todays_row = todays_rows.get(exercise_entry["name"])
            render_exercise_logger(
                selected_date=selected_date,
                week_number=week_number,
                workout_key=selected_workout_key,
                workout_label=selected_workout_label,
                exercise_entry=exercise_entry,
                todays_row=todays_row,
                performance=performance,
                log_store=log_store,
            )

    with week_tab:
        render_program_week(
            start_date=start_date,
            week_number=week_number,
            schedule=schedule,
            program=program,
            rows=rows,
            today=today,
        )

    with history_tab:
        render_history(sessions)


if __name__ == "__main__":
    main()

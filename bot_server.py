import base64
import hashlib
import hmac
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib import error, parse, request
from zoneinfo import ZoneInfo

import requests
from google.auth.transport.requests import Request
from google.oauth2 import service_account
from googleapiclient.discovery import build


LOGGER = logging.getLogger("seatalk-bot")
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
]
MAX_SEATALK_IMAGE_BYTES = 5 * 1024 * 1024
FMS_UPDATE_CELL_A1 = "AD1"
GROUP_CONFIG_RANGE_A1 = "bot_config!A2:A"
ENV_LINE_PATTERN = re.compile(r"^\s*([A-Za-z0-9_]+)\s*[:=]\s*(.*?)\s*$")
EVENT_VERIFICATION = "event_verification"
BOT_ADDED_TO_GROUP_CHAT = "bot_added_to_group_chat"
REQUIRED_CONFIG_FIELDS = (
    "sheet_id",
    "tab_name",
    "capture_range",
    "seatalk_app_id",
    "seatalk_app_secret",
    "seatalk_signing_secret",
    "report_link",
)
SEATALK_API_BASE_URL = "https://openapi.seatalk.io"
SEATALK_TOKEN_REFRESH_SKEW_SECONDS = 300
GROUP_STATE_FILE = Path(".runtime") / "seatalk-group.json"
SEND_STATE_FILE = Path(".runtime") / "hourly-send-state.json"
SEATALK_CALLBACK_PATHS = {"/seatalk/callback", "/seatalk/callback/", "/callback", "/callback/"}


@dataclass(frozen=True)
class Config:
    sheet_id: str
    tab_name: str
    capture_range: str
    seatalk_app_id: str
    seatalk_app_secret: str
    seatalk_signing_secret: str
    seatalk_group_id: str
    report_link: str
    timezone_name: str
    service_account_file: Path | None
    service_account_json: str
    host: str
    port: int
    request_timeout_seconds: int
    send_interval_minutes: int
    pdf_dpi: int
    image_border_px: int
    image_resize_width: int
    use_env_proxy: bool


def load_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        match = ENV_LINE_PATTERN.match(line)
        if not match:
            continue
        key, value = match.groups()
        values[key.strip()] = value.strip()
    return values


def get_setting(file_values: dict[str, str], file_key: str, env_key: str, default: str | None = None) -> str:
    return (
        os.getenv(env_key)
        or os.getenv(file_key)
        or file_values.get(env_key)
        or file_values.get(file_key)
        or (default or "")
    )


def parse_bool(value: str, default: bool) -> bool:
    if not value:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def dedupe_non_empty_values(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        normalized = str(value or "").strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


def ensure_binary(binary_name: str) -> None:
    if shutil.which(binary_name):
        return
    raise RuntimeError(f"Required binary not found in PATH: {binary_name}")


def validate_config(config: Config) -> None:
    missing = [field for field in REQUIRED_CONFIG_FIELDS if not getattr(config, field)]
    if missing:
        raise ValueError(f"Missing required config values: {', '.join(missing)}")
    if config.pdf_dpi <= 0:
        raise ValueError("BOT_PDF_DPI must be greater than 0.")
    if config.send_interval_minutes <= 0:
        raise ValueError("BOT_SEND_INTERVAL_MINUTES must be greater than 0.")
    if config.image_border_px < 0:
        raise ValueError("BOT_IMAGE_BORDER_PX must be zero or greater.")
    if config.image_resize_width <= 0:
        raise ValueError("BOT_IMAGE_RESIZE_WIDTH must be greater than 0.")

    if config.service_account_json:
        return

    if not config.service_account_file or not config.service_account_file.exists():
        raise FileNotFoundError(
            "No Google service account credentials found. "
            f"Checked GOOGLE_SERVICE_ACCOUNT_JSON and file: {config.service_account_file}"
        )


def load_config() -> Config:
    env_file_values = load_env_file(Path(".env"))

    service_account_json = get_setting(
        env_file_values,
        "google_service_account_json",
        "GOOGLE_SERVICE_ACCOUNT_JSON",
        "",
    ).strip()
    service_account_file_value = get_setting(
        env_file_values,
        "google_service_account_file",
        "GOOGLE_SERVICE_ACCOUNT_FILE",
        "/etc/secrets/google-service-account.json",
    ).strip()
    service_account_file = Path(service_account_file_value) if service_account_file_value else None

    config = Config(
        sheet_id=get_setting(env_file_values, "sheet_id", "SHEET_ID"),
        tab_name=get_setting(env_file_values, "tab_name", "TAB_NAME"),
        capture_range=get_setting(env_file_values, "capture_range", "CAPTURE_RANGE", "C1:AD38"),
        seatalk_app_id=get_setting(env_file_values, "seatalk_app_id", "SEATALK_APP_ID"),
        seatalk_app_secret=get_setting(env_file_values, "seatalk_app_secret", "SEATALK_APP_SECRET"),
        seatalk_signing_secret=get_setting(env_file_values, "seatalk_signing_secret", "SEATALK_SIGNING_SECRET"),
        seatalk_group_id=get_setting(env_file_values, "seatalk_group_id", "SEATALK_GROUP_ID"),
        report_link=get_setting(env_file_values, "report_link", "REPORT_LINK"),
        timezone_name=get_setting(env_file_values, "timezone", "BOT_TIMEZONE", "Asia/Manila"),
        service_account_file=service_account_file,
        service_account_json=service_account_json,
        host=get_setting(env_file_values, "host", "BOT_HOST", "0.0.0.0"),
        port=int(os.getenv("PORT") or get_setting(env_file_values, "port", "BOT_PORT", "8080")),
        request_timeout_seconds=int(
            get_setting(env_file_values, "request_timeout_seconds", "BOT_REQUEST_TIMEOUT_SECONDS", "30")
        ),
        send_interval_minutes=int(
            get_setting(env_file_values, "send_interval_minutes", "BOT_SEND_INTERVAL_MINUTES", "60")
        ),
        pdf_dpi=int(get_setting(env_file_values, "pdf_dpi", "BOT_PDF_DPI", "220")),
        image_border_px=int(get_setting(env_file_values, "image_border_px", "BOT_IMAGE_BORDER_PX", "20")),
        image_resize_width=int(get_setting(env_file_values, "image_resize_width", "BOT_IMAGE_RESIZE_WIDTH", "2200")),
        use_env_proxy=parse_bool(get_setting(env_file_values, "use_env_proxy", "BOT_USE_ENV_PROXY", ""), False),
    )
    validate_config(config)
    return config


def build_credentials(config: Config) -> service_account.Credentials:
    if config.service_account_json:
        try:
            service_account_info = json.loads(config.service_account_json)
        except json.JSONDecodeError as exc:
            raise ValueError("GOOGLE_SERVICE_ACCOUNT_JSON is not valid JSON.") from exc
        return service_account.Credentials.from_service_account_info(
            service_account_info,
            scopes=SCOPES,
        )

    return service_account.Credentials.from_service_account_file(
        str(config.service_account_file),
        scopes=SCOPES,
    )


def build_auth_request(use_env_proxy: bool) -> Request:
    session = requests.Session()
    session.trust_env = use_env_proxy
    return Request(session=session)


def build_http_opener(use_env_proxy: bool) -> request.OpenerDirector:
    if use_env_proxy:
        return request.build_opener()
    return request.build_opener(request.ProxyHandler({}))


def disable_proxy_env() -> None:
    for key in (
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "NO_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
        "no_proxy",
    ):
        os.environ.pop(key, None)


def format_update_timestamp(now: datetime) -> str:
    return now.strftime("%I:%M %p %b-%d").lstrip("0")


def build_card_description(current_value: str | None) -> str:
    normalized_value = str(current_value or "").strip() or "-"
    return f"FMS Update: {normalized_value}"


def format_sheet_datetime_value(value: Any) -> str:
    if value is None:
        return ""

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        base_datetime = datetime(1899, 12, 30)
        formatted = base_datetime + timedelta(days=float(value))
        return format_update_timestamp(formatted)

    text_value = str(value).strip()
    if not text_value:
        return ""

    for pattern in ("%I:%M %p %b-%d", "%I:%M%p %b-%d", "%Y-%m-%d %H:%M:%S", "%m/%d/%Y %H:%M:%S"):
        try:
            parsed = datetime.strptime(text_value, pattern)
            return format_update_timestamp(parsed)
        except ValueError:
            continue

    return text_value


def build_interactive_message_payload(
    timestamp: str,
    description: str,
    report_link: str,
    image_bytes: bytes,
) -> dict[str, Any]:
    return {
        "tag": "interactive_message",
        "interactive_message": {
            "elements": [
                {
                    "element_type": "title",
                    "title": {
                        "text": f"SOC 5 OTP Hourly as of {timestamp}",
                    },
                },
                {
                    "element_type": "description",
                    "description": {
                        "text": description,
                    },
                },
                {
                    "element_type": "image",
                    "image": {
                        "content": base64.b64encode(image_bytes).decode("ascii"),
                    },
                },
                {
                    "element_type": "button",
                    "button": {
                        "button_type": "redirect",
                        "text": "View Report Link",
                        "mobile_link": {
                            "type": "web",
                            "path": report_link,
                        },
                        "desktop_link": {
                            "type": "web",
                            "path": report_link,
                        },
                    },
                },
            ]
        },
    }


class SeatalkBotService:
    def __init__(self, config: Config) -> None:
        self.config = config
        self.timezone = ZoneInfo(config.timezone_name)
        if not config.use_env_proxy:
            disable_proxy_env()
        self.credentials = build_credentials(config)
        self.auth_request = build_auth_request(config.use_env_proxy)
        self.http_opener = build_http_opener(config.use_env_proxy)
        self.sheets_service = build("sheets", "v4", credentials=self.credentials, cache_discovery=False)

        self.sheet_gid: int | None = None
        self.run_lock = threading.Lock()
        self.stop_event = threading.Event()
        self.scheduler_thread: threading.Thread | None = None
        self.last_run_started_at: datetime | None = None
        self.last_run_finished_at: datetime | None = None
        self.last_run_succeeded_at: datetime | None = None
        self.next_run_at: datetime | None = None
        self.last_error: str | None = None
        self.last_callback_received_at: datetime | None = None
        self.last_callback_event_type: str | None = None
        self.last_callback_event: dict[str, Any] | None = None
        self.seatalk_access_token: str | None = None
        self.seatalk_access_token_expires_at = 0.0
        self.seatalk_token_lock = threading.Lock()
        self.seatalk_group_ids = self.load_initial_group_ids()
        self.seatalk_group_lock = threading.Lock()

        ensure_binary("pdftocairo")
        ensure_binary("magick")

    def start(self) -> None:
        self.scheduler_thread = threading.Thread(target=self.run_hourly_schedule, daemon=True)
        self.scheduler_thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        if self.scheduler_thread and self.scheduler_thread.is_alive():
            self.scheduler_thread.join(timeout=5)

    def run_hourly_schedule(self) -> None:
        while not self.stop_event.is_set():
            self.next_run_at = self.next_schedule_slot()
            wait_seconds = max(1.0, (self.next_run_at - datetime.now(self.timezone)).total_seconds())
            if self.stop_event.wait(wait_seconds):
                return
            self.send_schedule_slot_if_needed(self.next_run_at)

    def next_schedule_slot(self) -> datetime:
        now = datetime.now(self.timezone)
        interval_minutes = self.config.send_interval_minutes
        slot_minute = (now.minute // interval_minutes) * interval_minutes
        current_slot = now.replace(minute=slot_minute, second=0, microsecond=0)
        next_slot = current_slot + timedelta(minutes=interval_minutes)
        if next_slot <= now:
            next_slot += timedelta(minutes=interval_minutes)
        return next_slot

    def send_schedule_slot_if_needed(self, scheduled_for: datetime) -> bool:
        slot_key = scheduled_for.isoformat()
        if self.load_last_sent_slot() == slot_key:
            return False

        if self.run_once(scheduled_for):
            self.save_last_sent_slot(slot_key)
            return True

        return False

    def load_last_sent_slot(self) -> str:
        if not SEND_STATE_FILE.exists():
            return ""
        try:
            state = json.loads(SEND_STATE_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            LOGGER.warning("Could not read hourly send state from %s.", SEND_STATE_FILE)
            return ""
        return str(state.get("last_sent_slot") or "")

    def save_last_sent_slot(self, slot_key: str) -> None:
        SEND_STATE_FILE.parent.mkdir(exist_ok=True)
        state = {
            "last_sent_slot": slot_key,
            "updated_at": datetime.now(self.timezone).isoformat(),
        }
        SEND_STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")

    def run_once(self, scheduled_for: datetime) -> bool:
        if not self.run_lock.acquire(blocking=False):
            LOGGER.info("Skipping hourly run because another execution is still in progress.")
            return False

        started_at = datetime.now(self.timezone)
        self.last_run_started_at = started_at
        LOGGER.info(
            "Starting hourly bot cycle. scheduled_for=%s time=%s",
            scheduled_for.isoformat(),
            started_at.isoformat(),
        )

        try:
            image_bytes = self.render_report_image()
            payload = self.build_message_payload(scheduled_for, image_bytes)
            self.send_seatalk_group_message(payload)
            self.last_error = None
            self.last_run_succeeded_at = datetime.now(self.timezone)
            LOGGER.info("Bot cycle completed successfully.")
            return True
        except Exception as exc:  # noqa: BLE001
            self.last_error = str(exc)
            LOGGER.exception("Bot cycle failed: %s", exc)
            return False
        finally:
            self.last_run_finished_at = datetime.now(self.timezone)
            self.run_lock.release()

    def load_initial_group_ids(self) -> list[str]:
        return dedupe_non_empty_values([self.config.seatalk_group_id, self.load_saved_group_id()])

    def render_report_image(self) -> bytes:
        runtime_root = Path(".runtime")
        runtime_root.mkdir(exist_ok=True)

        with tempfile.TemporaryDirectory(prefix="seatalk-bot-", dir=runtime_root, ignore_cleanup_errors=True) as temp_dir:
            workdir = Path(temp_dir)
            pdf_path = workdir / "sheet-range.pdf"
            png_prefix = workdir / "sheet-range"
            raw_png_path = workdir / "sheet-range.png"
            final_png_path = workdir / "sheet-range-final.png"

            pdf_path.write_bytes(self.export_range_to_pdf())
            self.convert_pdf_to_png(pdf_path, png_prefix)
            self.optimize_png(raw_png_path, final_png_path)

            image_bytes = final_png_path.read_bytes()
            self.validate_image_size(image_bytes)
            return image_bytes

    def validate_image_size(self, image_bytes: bytes) -> None:
        if len(image_bytes) > MAX_SEATALK_IMAGE_BYTES:
            raise ValueError("Rendered PNG exceeds SeaTalk's 5MB image size limit.")

    def export_range_to_pdf(self) -> bytes:
        gid = self.fetch_sheet_gid()
        self.credentials.refresh(self.auth_request)

        query = parse.urlencode(
            {
                "exportFormat": "pdf",
                "format": "pdf",
                "gid": str(gid),
                "range": self.config.capture_range,
                "portrait": "false",
                "fitw": "true",
                "sheetnames": "false",
                "printtitle": "false",
                "pagenumbers": "false",
                "gridlines": "false",
                "fzr": "false",
                "attachment": "false",
                "size": "A4",
                "top_margin": "0.25",
                "bottom_margin": "0.25",
                "left_margin": "0.25",
                "right_margin": "0.25",
            }
        )
        url = f"https://docs.google.com/spreadsheets/d/{self.config.sheet_id}/export?{query}"
        http_request = request.Request(url, headers={"Authorization": f"Bearer {self.credentials.token}"})

        try:
            with self.http_opener.open(http_request, timeout=self.config.request_timeout_seconds) as response:
                pdf_bytes = response.read()
        except error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Google Sheets export failed with HTTP {exc.code}: {body}") from exc
        except error.URLError as exc:
            raise RuntimeError(f"Google Sheets export failed: {exc.reason}") from exc

        if not pdf_bytes.startswith(b"%PDF"):
            snippet = pdf_bytes[:200].decode("utf-8", errors="replace")
            raise RuntimeError(f"Google Sheets export did not return a PDF. Body starts with: {snippet}")
        return pdf_bytes

    def fetch_sheet_gid(self) -> int:
        if self.sheet_gid is not None:
            return self.sheet_gid

        response = (
            self.sheets_service.spreadsheets()
            .get(
                spreadsheetId=self.config.sheet_id,
                fields="sheets(properties(sheetId,title))",
            )
            .execute()
        )
        for sheet in response.get("sheets", []):
            properties = sheet.get("properties", {})
            if properties.get("title") == self.config.tab_name:
                self.sheet_gid = int(properties["sheetId"])
                return self.sheet_gid
        raise ValueError(f"Tab not found in spreadsheet: {self.config.tab_name}")

    def fetch_fms_update_value(self) -> str:
        range_name = f"{self.config.tab_name}!{FMS_UPDATE_CELL_A1}"
        try:
            response = (
                self.sheets_service.spreadsheets()
                .values()
                .get(
                    spreadsheetId=self.config.sheet_id,
                    range=range_name,
                    valueRenderOption="UNFORMATTED_VALUE",
                    dateTimeRenderOption="SERIAL_NUMBER",
                )
                .execute()
            )
            values = response.get("values", [])
            sheet_value = values[0][0] if values and values[0] else None
            formatted_value = format_sheet_datetime_value(sheet_value)
            if formatted_value:
                return formatted_value
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("Failed to read %s from Google Sheets: %s", range_name, exc)

        LOGGER.warning("Cell %s was blank or unavailable.", FMS_UPDATE_CELL_A1)
        return "-"

    def fetch_group_ids_from_sheet(self) -> list[str]:
        try:
            response = (
                self.sheets_service.spreadsheets()
                .values()
                .get(
                    spreadsheetId=self.config.sheet_id,
                    range=GROUP_CONFIG_RANGE_A1,
                    valueRenderOption="FORMATTED_VALUE",
                )
                .execute()
            )
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("Failed to read SeaTalk group IDs from %s: %s", GROUP_CONFIG_RANGE_A1, exc)
            return []

        values = response.get("values", [])
        return dedupe_non_empty_values([str(row[0]) for row in values if row])

    def convert_pdf_to_png(self, pdf_path: Path, png_prefix: Path) -> None:
        command = [
            "pdftocairo",
            "-png",
            "-singlefile",
            "-r",
            str(self.config.pdf_dpi),
            str(pdf_path),
            str(png_prefix),
        ]
        self.run_subprocess(command, "Poppler PDF-to-PNG conversion failed")

    def optimize_png(self, raw_png_path: Path, final_png_path: Path) -> None:
        command = [
            "magick",
            str(raw_png_path),
            "-trim",
            "+repage",
            "-bordercolor",
            "white",
            "-border",
            str(self.config.image_border_px),
            "-resize",
            f"{self.config.image_resize_width}x>",
            "-strip",
            str(final_png_path),
        ]
        self.run_subprocess(command, "ImageMagick PNG optimization failed")

    def run_subprocess(self, command: list[str], error_message: str) -> None:
        try:
            subprocess.run(command, check=True, capture_output=True, text=True)
        except subprocess.CalledProcessError as exc:
            stderr = (exc.stderr or "").strip()
            stdout = (exc.stdout or "").strip()
            details = stderr or stdout or "no subprocess output"
            raise RuntimeError(f"{error_message}: {details}") from exc

    def build_message_payload(
        self,
        now: datetime,
        image_bytes: bytes,
    ) -> dict[str, Any]:
        timestamp = format_update_timestamp(now)
        description_value = self.fetch_fms_update_value()
        description = build_card_description(description_value)
        return build_interactive_message_payload(timestamp, description, self.config.report_link, image_bytes)

    def load_saved_group_id(self) -> str:
        if not GROUP_STATE_FILE.exists():
            return ""
        try:
            state = json.loads(GROUP_STATE_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            LOGGER.warning("Could not read saved SeaTalk group state from %s.", GROUP_STATE_FILE)
            return ""
        return str(state.get("group_id") or "").strip()

    def save_group_id(self, group_id: str, group_name: str = "") -> None:
        GROUP_STATE_FILE.parent.mkdir(exist_ok=True)
        state = {
            "group_id": group_id,
            "group_name": group_name,
            "updated_at": datetime.now(self.timezone).isoformat(),
        }
        GROUP_STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")

    def handle_seatalk_callback(self, payload: dict[str, Any]) -> dict[str, Any]:
        event_type = str(payload.get("event_type") or "")
        event = payload.get("event")
        event_data = event if isinstance(event, dict) else {}

        self.last_callback_received_at = datetime.now(self.timezone)
        self.last_callback_event_type = event_type
        self.last_callback_event = payload

        if event_type == EVENT_VERIFICATION:
            challenge = str(event_data.get("seatalk_challenge") or "")
            return {"seatalk_challenge": challenge}

        if event_type == BOT_ADDED_TO_GROUP_CHAT:
            group = event_data.get("group")
            group_data = group if isinstance(group, dict) else {}
            group_id = str(group_data.get("group_id") or "").strip()
            group_name = str(group_data.get("group_name") or "").strip()
            if group_id:
                with self.seatalk_group_lock:
                    self.seatalk_group_ids = dedupe_non_empty_values([*self.seatalk_group_ids, group_id])
                    self.save_group_id(group_id, group_name)
                LOGGER.info("Stored SeaTalk group from callback. group_id=%s group_name=%s", group_id, group_name)
            return {}

        LOGGER.info("Ignoring SeaTalk callback event_type=%s", event_type or "<missing>")
        return {}

    def is_valid_seatalk_signature(self, raw_body: bytes, signature: str) -> bool:
        if not signature:
            return False
        expected = hashlib.sha256(raw_body + self.config.seatalk_signing_secret.encode("utf-8")).hexdigest()
        return hmac.compare_digest(expected.lower(), signature.lower())

    def get_seatalk_access_token(self) -> str:
        now = time.time()
        if self.seatalk_access_token and now < self.seatalk_access_token_expires_at:
            return self.seatalk_access_token

        with self.seatalk_token_lock:
            now = time.time()
            if self.seatalk_access_token and now < self.seatalk_access_token_expires_at:
                return self.seatalk_access_token

            token_response = self.post_seatalk_api(
                f"{SEATALK_API_BASE_URL}/auth/app_access_token",
                {
                    "app_id": self.config.seatalk_app_id,
                    "app_secret": self.config.seatalk_app_secret,
                },
            )
            access_token = str(token_response.get("app_access_token") or "").strip()
            if not access_token:
                raise RuntimeError(f"SeaTalk token response did not include app_access_token: {token_response}")

            expire_value = token_response.get("expire")
            try:
                expires_at = float(expire_value)
            except (TypeError, ValueError):
                expires_at = now + 7200
            if expires_at <= now:
                expires_at = now + expires_at

            self.seatalk_access_token = access_token
            self.seatalk_access_token_expires_at = max(now, expires_at - SEATALK_TOKEN_REFRESH_SKEW_SECONDS)
            return access_token

    def get_target_group_ids(self) -> list[str]:
        sheet_group_ids = self.fetch_group_ids_from_sheet()
        with self.seatalk_group_lock:
            configured_group_ids = list(self.seatalk_group_ids)
            self.seatalk_group_ids = dedupe_non_empty_values([*configured_group_ids, *sheet_group_ids])
            return list(self.seatalk_group_ids)

    def send_seatalk_group_message(self, message: dict[str, Any]) -> list[dict[str, Any]]:
        access_token = self.get_seatalk_access_token()
        group_ids = self.get_target_group_ids()
        if not group_ids:
            raise RuntimeError(
                "No SeaTalk group ID configured, received from callback, or found in bot_config!A2:A."
            )

        responses: list[dict[str, Any]] = []
        for group_id in group_ids:
            LOGGER.info("Sending SeaTalk message to group_id=%s", group_id)
            responses.append(
                self.post_seatalk_api(
                    f"{SEATALK_API_BASE_URL}/messaging/v2/group_chat",
                    {
                        "group_id": group_id,
                        "message": message,
                    },
                    access_token=access_token,
                )
            )
        return responses

    def post_seatalk_api(
        self,
        url: str,
        payload: dict[str, Any],
        access_token: str | None = None,
    ) -> dict[str, Any]:
        request_body = json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if access_token:
            headers["Authorization"] = f"Bearer {access_token}"
        http_request = request.Request(
            url,
            data=request_body,
            headers=headers,
            method="POST",
        )

        try:
            with self.http_opener.open(http_request, timeout=self.config.request_timeout_seconds) as response:
                raw_body = response.read().decode("utf-8")
        except error.HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"SeaTalk API request failed with HTTP {exc.code}: {error_body}") from exc
        except error.URLError as exc:
            raise RuntimeError(f"SeaTalk API request failed: {exc.reason}") from exc

        try:
            parsed = json.loads(raw_body)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"SeaTalk returned invalid JSON: {raw_body}") from exc

        if parsed.get("code") != 0:
            raise RuntimeError(f"SeaTalk returned an error response: {parsed}")
        return parsed

    def status(self) -> dict[str, Any]:
        with self.seatalk_group_lock:
            group_id_configured = bool(self.seatalk_group_ids)
        return {
            "running": self.run_lock.locked(),
            "last_run_started_at": self.last_run_started_at.isoformat() if self.last_run_started_at else None,
            "last_run_finished_at": self.last_run_finished_at.isoformat() if self.last_run_finished_at else None,
            "last_run_succeeded_at": self.last_run_succeeded_at.isoformat() if self.last_run_succeeded_at else None,
            "next_run_at": self.next_run_at.isoformat() if self.next_run_at else None,
            "last_callback_received_at": (
                self.last_callback_received_at.isoformat() if self.last_callback_received_at else None
            ),
            "last_callback_event_type": self.last_callback_event_type,
            "last_error": self.last_error,
            "capture_range": self.config.capture_range,
            "send_interval_minutes": self.config.send_interval_minutes,
            "tab_name": self.config.tab_name,
            "seatalk_group_id_configured": group_id_configured,
        }


def build_handler(service: SeatalkBotService) -> type[BaseHTTPRequestHandler]:
    class BotHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            if self.path not in {"/", "/healthz"}:
                self.respond_json(HTTPStatus.NOT_FOUND, {"error": "Not found"})
                return
            self.respond_json(HTTPStatus.OK, service.status())

        def do_HEAD(self) -> None:  # noqa: N802
            if self.path not in {"/", "/healthz"}:
                self.respond_empty(HTTPStatus.NOT_FOUND)
                return
            self.respond_empty(HTTPStatus.OK)

        def do_POST(self) -> None:  # noqa: N802
            request_path = parse.urlparse(self.path).path
            if request_path not in SEATALK_CALLBACK_PATHS:
                LOGGER.info("Rejected POST to unsupported path: %s", self.path)
                self.respond_json(HTTPStatus.NOT_FOUND, {"error": "Not found"})
                return

            LOGGER.info("Received SeaTalk callback request on %s.", request_path)

            try:
                raw_body = self.read_request_body()
                payload = self.parse_json_payload(raw_body)
            except ValueError as exc:
                LOGGER.warning("Rejected SeaTalk callback with invalid JSON: %s", exc)
                self.respond_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
                return

            signature = self.headers.get("Signature") or self.headers.get("signature") or ""
            if not service.is_valid_seatalk_signature(raw_body, signature):
                LOGGER.warning("Rejected SeaTalk callback with invalid signature.")
                self.respond_empty(HTTPStatus.FORBIDDEN)
                return

            response_payload = service.handle_seatalk_callback(payload)
            self.respond_json(HTTPStatus.OK, response_payload)

        def read_request_body(self) -> bytes:
            content_length = int(self.headers.get("Content-Length", "0") or "0")
            if content_length <= 0:
                return b""

            return self.rfile.read(content_length)

        def parse_json_payload(self, raw_body: bytes) -> dict[str, Any]:
            if not raw_body:
                return {}

            try:
                payload = json.loads(raw_body)
            except json.JSONDecodeError as exc:
                raise ValueError("Request body must be valid JSON.") from exc

            if not isinstance(payload, dict):
                raise ValueError("Request body must be a JSON object.")
            return payload

        def respond_json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def respond_empty(self, status: HTTPStatus) -> None:
            self.send_response(status)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
            LOGGER.info("%s - %s", self.address_string(), format % args)

    return BotHandler


def main() -> None:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    )
    config = load_config()
    service = SeatalkBotService(config)
    if "--send-now" in sys.argv:
        success = service.run_once(datetime.now(service.timezone))
        raise SystemExit(0 if success else 1)

    service.start()

    server = ThreadingHTTPServer((config.host, config.port), build_handler(service))
    LOGGER.info("Seatalk bot server listening on %s:%s", config.host, config.port)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        LOGGER.info("Shutting down bot server.")
    finally:
        server.shutdown()
        service.stop()


if __name__ == "__main__":
    main()

#! /usr/bin/env python3

from os import getcwd, getenv, listdir, makedirs, name, path, rmdir
from sys import stdout, stderr
from typing import Any, Iterator, TextIO, Callable
from types import FrameType
from itertools import count
from requests import Session, Response, Timeout
from requests.structures import CaseInsensitiveDict
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from hashlib import sha256
from shutil import move
from signal import signal, SIGINT, SIG_IGN
from time import perf_counter, time

NEW_LINE: str = "\n" if name != "nt" else "\r\n"

def has_ansi_support() -> bool:
    import os
    import sys
    if not sys.stdout.isatty():
        return False
    if os.name == "nt":
        return sys.getwindowsversion().major >= 10
    return True

TERMINAL_CLEAR_LINE: str = f"\r{' ' * 100} \r" if not has_ansi_support() else "\033[2K\r"

def generate_website_token(user_agent: str, account_token: str) -> str:
    time_slot = int(time()) // 14400
    raw = f"{user_agent}::en-US::{account_token}::{time_slot}::f4s58gs6"
    return sha256(raw.encode()).hexdigest()

class Downloader:
    def __init__(
        self,
        root_dir: str,
        interactive: bool,
        max_workers: int,
        number_retries: int,
        timeout: float,
        chunk_size: int,
        pause_event: Event,
        stop_event: Event,
        session: Session,
        url: str,
        password: str | None = None,
        output_callback: Callable[[str], None] | None = None,
        progress_callback: Callable[[dict], None] | None = None,
    ) -> None:
        self._files_info: dict[str, dict[str, str]] = {}
        self._max_workers: int = max_workers
        self._number_retries: int = number_retries
        self._timeout: float = timeout
        self._interactive: bool = interactive
        self._chunk_size: int = chunk_size
        self._password: str | None = password
        self._session: Session = session
        self._pause_event: Event = pause_event
        self._stop_event: Event = stop_event
        self._root_dir: str = root_dir
        self._url: str = url
        self._output_callback = output_callback
        self._progress_callback = progress_callback

    def _print(self, msg: str, error: bool = False) -> None:
        if self._output_callback:
            self._output_callback(msg)
        else:
            output: TextIO = stderr if error else stdout
            output.write(msg if msg.endswith(NEW_LINE) else msg + NEW_LINE)
            output.flush()

    def fetch_metadata(self) -> dict:
        try:
            if not self._url.split("/")[-2] == "d":
                self._print(f"The url probably doesn't have an id in it: {self._url}.{NEW_LINE}")
                return {}
            content_id: str = self._url.split("/")[-1]
        except IndexError:
            self._print(f"{self._url} doesn't seem a valid url.{NEW_LINE}")
            return {}

        _password: str | None = sha256(self._password.encode()).hexdigest() if self._password else None
        content_dir: str = path.join(self._root_dir, content_id)
        self._build_content_tree_structure(content_dir, content_id, _password)
        return self._files_info

    def run(self, selected_indices: list[str] | None = None) -> None:
        if not self._files_info:
            self.fetch_metadata()

        if not self._files_info:
            return

        if selected_indices is not None:
            self._files_info = {k: v for k, v in self._files_info.items() if k in selected_indices}

        if not self._files_info:
            self._print(f"Nothing to download.{NEW_LINE}")
            return

        self._threaded_downloads()

    def _get_response(self, **kwargs: Any) -> Response | None:
        for _ in range(self._number_retries):
            try:
                return self._session.get(timeout=self._timeout, **kwargs)
            except Timeout:
                continue
        return None

    def _threaded_downloads(self) -> None:
        with ThreadPoolExecutor(max_workers=self._max_workers) as executor:
            for index, item in self._files_info.items():
                if self._stop_event.is_set() or self._pause_event.is_set():
                    return
                executor.submit(self._download_content, index, item)

    @staticmethod
    def _create_dirs(dirname: str) -> None:
        makedirs(dirname, exist_ok=True)

    @staticmethod
    def _remove_dir(dirname: str) -> None:
        try:
            rmdir(dirname)
        except:
            pass

    def _download_content(self, index: str, file_info: dict[str, str]) -> None:
        filepath: str = path.join(file_info["path"], file_info["filename"])
        if self._should_skip_download(filepath):
            if self._progress_callback:
                self._progress_callback({
                    "index": index,
                    "filename": file_info["filename"],
                    "status": "skipped",
                    "percent": 100
                })
            return

        tmp_file: str = f"{filepath}.part"
        url: str = file_info["link"]

        if self._progress_callback:
            self._progress_callback({
                "index": index,
                "filename": file_info["filename"],
                "status": "starting",
                "percent": 0
            })

        for _ in range(self._number_retries):
            try:
                part_size: int = 0
                headers: dict[str, str] = {}
                if path.isfile(tmp_file):
                    part_size = int(path.getsize(tmp_file))
                    headers = {"Range": f"bytes={part_size}-"}

                has_size: str | None = self._perform_download(
                    index, file_info, url, tmp_file, headers, part_size
                )
            except Timeout:
                continue
            else:
                if has_size:
                    self._finalize_download(index, file_info, tmp_file, has_size)
                break
        
        # Cleanup on hard stop
        if self._stop_event.is_set() and path.isfile(tmp_file):
            import os
            try:
                os.remove(tmp_file)
            except Exception:
                pass

    def _should_skip_download(self, filepath: str) -> bool:
        if path.exists(filepath) and path.getsize(filepath) > 0:
            self._print(f"{filepath} already exists, skipping.{NEW_LINE}")
            return True
        return False

    def _perform_download(
        self,
        index: str,
        file_info: dict[str, str],
        url: str,
        tmp_file: str,
        headers: dict[str, str],
        part_size: int,
    ) -> str | None:
        if self._stop_event.is_set() or self._pause_event.is_set():
            return None

        response: Response | None = self._get_response(url=url, headers=headers, stream=True)
        if not response:
            self._print(f"Couldn't download the file, failed to get a response from {url}.{NEW_LINE}")
            return None

        with response:
            status_code: int = response.status_code
            if not self._is_valid_response(status_code, part_size):
                self._print(f"Invalid response from {url}. Status code: {status_code}{NEW_LINE}")
                return None

            has_size: str | None = self._extract_file_size(response.headers, part_size)
            if not has_size:
                self._print(f"Couldn't find the file size from {url}.{NEW_LINE}")
                return None

            self._write_chunks(
                index,
                response.iter_content(chunk_size=self._chunk_size),
                tmp_file,
                part_size,
                float(has_size),
                file_info["filename"]
            )
            return has_size

    @staticmethod
    def _is_valid_response(status_code: int, part_size: int) -> bool:
        if status_code in (403, 404, 405, 500):
            return False
        if part_size == 0:
            return status_code in (200, 206)
        return status_code == 206

    @staticmethod
    def _extract_file_size(headers: CaseInsensitiveDict[str], part_size: int) -> str | None:
        content_length: str | None = headers.get("Content-Length")
        content_range: str | None = headers.get("Content-Range")
        return content_length if part_size == 0 else content_range.split("/")[-1] if content_range else None

    def _write_chunks(
        self,
        index: str,
        chunks: Iterator[Any],
        tmp_file: str,
        part_size: int,
        total_size: float,
        filename: str
    ) -> None:
        """
        _write_chunks
        """
        start_time: float = perf_counter()
        with open(tmp_file, "ab") as f:
            for i, chunk in enumerate(chunks):
                if self._stop_event.is_set() or self._pause_event.is_set():
                    return
                f.write(chunk)
                self._update_progress(index, filename, part_size, i, chunk, total_size, start_time)

    def _update_progress(
        self,
        index: str,
        filename: str,
        part_size: int,
        i: int,
        chunk: bytes,
        total_size: float,
        start_time: float
    ) -> None:
        current_downloaded = part_size + (i * len(chunk))
        progress: float = current_downloaded / total_size * 100
        elapsed = perf_counter() - start_time
        rate: float = (i * len(chunk)) / elapsed if elapsed > 0 else 0

        if self._progress_callback:
            self._progress_callback({
                "index": index,
                "filename": filename,
                "current": current_downloaded,
                "total": int(total_size),
                "percent": progress,
                "rate": rate,
                "status": "downloading"
            })
        else:
            unit: str = "B/s"
            disp_rate = rate
            if disp_rate < 1024: unit = "B/s"
            elif disp_rate < (1024 ** 2): disp_rate /= 1024; unit = "KB/s"
            elif disp_rate < (1024 ** 3): disp_rate /= (1024 ** 2); unit = "MB/s"
            else: disp_rate /= (1024 ** 3); unit = "GB/s"

            self._print(
                f"{TERMINAL_CLEAR_LINE}"
                f"Downloading {filename}: {current_downloaded} "
                f"of {int(total_size)} {round(progress, 1)}% {round(disp_rate, 1)}{unit}"
            )

    def _finalize_download(self, index: str, file_info: dict[str, str], tmp_file: str, has_size: str) -> None:
        if path.getsize(tmp_file) == int(has_size):
            self._print(f"Downloading {file_info['filename']}: Done!")
            move(tmp_file, path.join(file_info["path"], file_info["filename"]))
            if self._progress_callback:
                self._progress_callback({
                    "index": index,
                    "filename": file_info["filename"],
                    "status": "finished",
                    "percent": 100
                })

    def _register_file(self, file_index: count, filepath: str, file_url: str) -> None:
        self._files_info[str(next(file_index))] = {
            "path": path.dirname(filepath),
            "filename": path.basename(filepath),
            "link": file_url
        }

    @staticmethod
    def _resolve_naming_collision(
        pathing_count: dict[str, int],
        absolute_parent_dir: str,
        child_name: str,
        is_dir: bool = False,
    ) -> str:
        filepath: str = path.join(absolute_parent_dir, child_name)
        if filepath in pathing_count:
            pathing_count[filepath] += 1
        else:
            pathing_count[filepath] = 0

        if pathing_count[filepath] > 0:
            if is_dir:
                return f"{filepath}({pathing_count[filepath]})"
            root, extension = path.splitext(filepath)
            return f"{root}({pathing_count[filepath]}){extension}"
        return filepath

    def _build_content_tree_structure(
        self,
        parent_dir: str,
        content_id: str,
        password: str | None = None,
        pathing_count: dict[str, int] | None = None,
        file_index: count = count(start=0, step=1)
    ) -> None:
        url: str = f"https://api.gofile.io/contents/{content_id}?cache=true&sortField=createTime&sortDirection=1"
        if not pathing_count: pathing_count = {}
        if password: url = f"{url}&password={password}"

        user_agent: str = str(self._session.headers.get("User-Agent", "Mozilla/5.0"))
        auth_header: str = str(self._session.headers.get("Authorization", ""))
        account_token: str = auth_header.replace("Bearer ", "") if auth_header else ""
        wt: str = generate_website_token(user_agent, account_token)

        response: Response | None = self._get_response(
            url=url,
            headers={"X-Website-Token": wt, "X-BL": "en-US"}
        )
        json_response: dict[str, Any] = {} if not response else response.json()

        if not json_response or json_response["status"] != "ok":
            self._print(f"Failed to fetch data response from the {url}.{NEW_LINE}")
            return

        data: dict[str, Any] = json_response["data"]
        if "password" in data and "passwordStatus" in data and data["passwordStatus"] != "passwordOk":
            self._print(f"Password protected link. Please provide the password.{NEW_LINE}")
            return

        if data["type"] != "folder":
            filepath: str = self._resolve_naming_collision(pathing_count, parent_dir, data["name"])
            self._register_file(file_index, filepath, data["link"])
            return

        folder_name: str = data["name"]
        absolute_path: str = self._resolve_naming_collision(pathing_count, parent_dir, folder_name, is_dir=True)
        if path.basename(parent_dir) == content_id:
            absolute_path = parent_dir
        self._create_dirs(absolute_path)

        for child in data["children"].values():
            if child["type"] == "folder":
                self._build_content_tree_structure(absolute_path, child["id"], password, pathing_count, file_index)
            else:
                filepath: str = self._resolve_naming_collision(pathing_count, absolute_path, child["name"])
                self._register_file(file_index, filepath, child["link"])

class Manager:
    def __init__(self, url_or_file: str | None = None, password: str | None = None, output_callback=None, progress_callback=None) -> None:
        self._root_dir: str = getenv("GF_DOWNLOAD_DIR") or getcwd()
        self._max_workers: int = int(getenv("GF_MAX_CONCURRENT_DOWNLOADS", 5))
        self._number_retries: int = int(getenv("GF_MAX_RETRIES", 5))
        self._timeout: float = float(getenv("GF_TIMEOUT", 15.0))
        self._user_agent: str = getenv("GF_USERAGENT") or "Mozilla/5.0"
        self._interactive: bool = getenv("GF_INTERACTIVE") == "1"
        self._chunk_size: int = int(getenv("GF_CHUNK_SIZE", 2097152))
        self._password: str | None = password
        self._url_or_file: str | None = url_or_file
        self._session: Session = Session()
        self._pause_event: Event = Event()
        self._stop_event: Event = Event()
        self._output_callback = output_callback
        self._progress_callback = progress_callback

        self._session.headers.update({
            "Accept-Encoding": "gzip",
            "User-Agent": self._user_agent,
            "Connection": "keep-alive",
            "Accept": "*/*",
            "Origin": "https://gofile.io",
            "Referer": "https://gofile.io/",
        })

    def set_config(self, **kwargs):
        for k, v in kwargs.items():
            if hasattr(self, f"_{k}"):
                setattr(self, f"_{k}", v)

    def login(self, token: str | None = None) -> bool:
        if token:
            self._session.cookies.set("Cookie", f"accountToken={token}")
            self._session.headers.update({"Authorization": f"Bearer {token}"})
            return True

        user_agent: str = str(self._session.headers.get("User-Agent", "Mozilla/5.0"))
        wt: str = generate_website_token(user_agent, "")
        
        response = None
        for _ in range(self._number_retries):
            try:
                r = self._session.post(
                    "https://api.gofile.io/accounts",
                    headers={"X-Website-Token": wt, "X-BL": "en-US"},
                    timeout=self._timeout
                )
                response = r.json()
                break
            except (Timeout, Exception):
                continue

        if not response or response.get("status") != "ok":
            return False

        token = response['data']['token']
        self._session.cookies.set("Cookie", f"accountToken={token}")
        self._session.headers.update({"Authorization": f"Bearer {token}"})
        return True

    def get_downloader(self, url: str, password: str | None = None) -> Downloader:
        return Downloader(
            self._root_dir,
            self._interactive,
            self._max_workers,
            self._number_retries,
            self._timeout,
            self._chunk_size,
            self._pause_event,
            self._stop_event,
            self._session,
            url,
            password or self._password,
            self._output_callback,
            self._progress_callback
        )

    def pause(self) -> None:
        self._pause_event.set()

    def stop(self) -> None:
        self._stop_event.set()

"""Starts scrapes from the API as separate processes (same code path as the CLI) and cancels them.

A crash of the browser or scraper cannot take the web server down, and progress flows through
the DB (`scrape_runs`), which the UI polls.
"""

import asyncio
import os
import signal
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from salevault.db.runs import RunAlreadyRunningError, RunRepository, RunRow

CommandFactory = Callable[[str, bool | None], list[str]]


class LaunchError(Exception):
    pass


class RunNotRunningError(Exception):
    pass


def scrape_command(site: str, headed: bool | None) -> list[str]:
    command = [sys.executable, "-m", "salevault", "scrape", site, "--trigger", "ui", "--top", "0"]
    if headed is not None:
        command.append("--headed" if headed else "--headless")
    return command


class RunLauncher:
    def __init__(
        self,
        factory: sessionmaker[Session],
        *,
        data_dir: Path,
        command: CommandFactory = scrape_command,
        startup_timeout_s: float = 60.0,
        on_finish: Callable[[], None] | None = None,
    ) -> None:
        self._repo = RunRepository(factory)
        self._data_dir = data_dir
        self._command = command
        self._startup_timeout_s = startup_timeout_s
        self._on_finish = on_finish
        self._tasks: set[asyncio.Task[Any]] = set()

    async def start(self, site: str, *, headed: bool | None = None) -> int:
        """Spawn a scrape and return its run id once the process has registered the run."""
        active = await asyncio.to_thread(self._repo.active_run, site)
        if active is not None:
            raise RunAlreadyRunningError(f"Run #{active.id} of {site} is already running")

        logs = self._data_dir / "logs"
        logs.mkdir(parents=True, exist_ok=True)
        log_path = logs / f"run-{site}-{datetime.now(UTC):%Y%m%dT%H%M%SZ}.log"
        env = os.environ | {"SALEVAULT_DATA_DIR": str(self._data_dir), "COLUMNS": "120"}
        with log_path.open("ab") as log_file:
            process = await asyncio.create_subprocess_exec(
                *self._command(site, headed),
                stdin=asyncio.subprocess.DEVNULL,
                stdout=log_file,
                stderr=asyncio.subprocess.STDOUT,
                env=env,
                start_new_session=True,  # survives an API restart; Ctrl+C in the API won't hit it
            )
        self._keep(asyncio.create_task(self._wait(process)))  # reaps the child, no zombies

        loop = asyncio.get_running_loop()
        deadline = loop.time() + self._startup_timeout_s
        while True:
            run_id = await asyncio.to_thread(self._repo.run_id_for_pid, process.pid)
            if run_id is not None:
                return run_id
            if process.returncode is not None:
                tail = _tail(log_path)
                if "still running" in tail:
                    raise RunAlreadyRunningError(f"A run of {site} is already running")
                raise LaunchError(f"The scraper exited with code {process.returncode}: {tail}")
            if loop.time() > deadline:
                raise LaunchError(f"The scraper did not register a run in time; see {log_path}")
            await asyncio.sleep(0.2)

    async def _wait(self, process: asyncio.subprocess.Process) -> None:
        await process.wait()
        if self._on_finish is not None:
            await asyncio.to_thread(self._on_finish)  # e.g. warm caches with the new data

    def _keep(self, task: asyncio.Task[Any]) -> None:
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    def cancel(self, run_id: int) -> RunRow:
        row = self._repo.find(run_id)
        if row is None:
            raise KeyError(run_id)
        pid = self._repo.pid_of(run_id)
        if row.status != "running" or pid is None:
            raise RunNotRunningError(f"Run #{run_id} is not running (status: {row.status})")
        try:
            os.kill(pid, signal.SIGTERM)  # the scraper finishes as `cancelled`
        except ProcessLookupError:
            self._repo.active_run(row.site)  # the process is gone: reap the run as failed
        return self._repo.get(run_id)


def _tail(path: Path, limit: int = 800) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    return " ".join(text[-limit:].split())

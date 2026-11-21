"""Starts scrapes from the API as separate processes (same code path as the CLI) and cancels them.

A crash of the browser or scraper cannot take the web server down, and progress flows through
the DB (`scrape_runs`), which the UI polls.
"""

import asyncio
import contextlib
import os
import signal
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from salevault.db.runs import RunAlreadyRunningError, RunRepository, RunRow, same_process

CommandFactory = Callable[[str, bool | None, bool], list[str]]
KEEP_LOGS = 20
"""UI runs write one log each; older ones are deleted."""


class LaunchError(Exception):
    pass


class RunNotRunningError(Exception):
    pass


def scrape_command(site: str, headed: bool | None, resume: bool = False) -> list[str]:
    command = [sys.executable, "-m", "salevault", "scrape", site, "--trigger", "ui", "--top", "0"]
    if headed is not None:
        command.append("--headed" if headed else "--headless")
    if resume:
        command.append("--resume")
    return command


class RunLauncher:
    def __init__(
        self,
        repo: RunRepository,
        *,
        data_dir: Path,
        command: CommandFactory = scrape_command,
        startup_timeout_s: float = 60.0,
        on_finish: Callable[[], None] | None = None,
    ) -> None:
        self._repo = repo
        self._data_dir = data_dir
        self._command = command
        self._startup_timeout_s = startup_timeout_s
        self._on_finish = on_finish
        self._tasks: set[asyncio.Task[Any]] = set()

    async def start(self, site: str, *, headed: bool | None = None, resume: bool = False) -> int:
        """Spawn a scrape (or resume one) and return its run id once the process registered it."""
        active = await asyncio.to_thread(self._repo.active_run, site)
        if active is not None:
            raise RunAlreadyRunningError(f"Run #{active.id} of {site} is already running")

        logs = self._data_dir / "logs"
        logs.mkdir(parents=True, exist_ok=True)
        for old in sorted(logs.glob("run-*.log"), key=lambda p: p.stat().st_mtime)[:-KEEP_LOGS]:
            old.unlink(missing_ok=True)
        log_path = logs / f"run-{site}-{datetime.now(UTC):%Y%m%dT%H%M%SZ}.log"
        env = os.environ | {"SALEVAULT_DATA_DIR": str(self._data_dir), "COLUMNS": "120"}
        with log_path.open("ab") as log_file:
            process = await asyncio.create_subprocess_exec(
                *self._command(site, headed, resume),
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
                process.terminate()  # never let it scrape after we reported a failure
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
        # Reap first: a dead run's pid may belong to an unrelated process by now.
        self._repo.reap_dead()
        row = self._repo.find(run_id)
        if row is None:
            raise KeyError(run_id)
        process = self._repo.pid_of(run_id)
        if row.status != "running" or process is None:
            raise RunNotRunningError(f"Run #{run_id} is not running (status: {row.status})")
        pid, started = process
        if same_process(pid, started):
            with contextlib.suppress(ProcessLookupError):  # exited in the meantime
                os.kill(pid, signal.SIGTERM)  # the scraper finishes as `cancelled`
        self._repo.reap_dead()  # gone in the meantime: recorded as failed
        return self._repo.get(run_id)


def _tail(path: Path, limit: int = 800) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    return " ".join(text[-limit:].split())

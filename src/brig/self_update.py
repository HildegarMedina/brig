"""Explicit Brig upgrades and one nonblocking release check per day."""

import fcntl
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager, suppress
from pathlib import Path

from brig import __version__
from brig.docker.workspace import DockerWorkspace
from brig.errors import BrigError
from brig.i18n import tr
from brig.releases import latest_version, newer, release_files, stable_version

INTERVAL = 86400
STATE_FILE = "self-update.json"


def read_state(directory):
    try:
        state = json.loads((directory / STATE_FILE).read_text())
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as error:
        raise BrigError(tr("Cannot read Brig update settings.")) from error
    if not isinstance(state, dict):
        raise BrigError(tr("Cannot read Brig update settings."))
    return state


@contextmanager
def state_lock(directory, *, blocking=False):
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / "self-update.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
        yield


def save_state(directory, state):
    DockerWorkspace.write(directory / STATE_FILE, json.dumps(state) + "\n")


def refresh(directory):
    """Record attempts, including failures, before contacting GitHub."""
    with state_lock(directory, blocking=True):
        state = read_state(directory)
        state["checked_at"] = time.time()
        save_state(directory, state)
    available = latest_version()
    with state_lock(directory, blocking=True):
        state = read_state(directory)
        state["available"] = available
        save_state(directory, state)
    return available


def check_worker(directory):
    with suppress(OSError, ValueError, BrigError):
        refresh(directory)


def automatic_check(directory):
    """Reserve a daily check atomically; a detached worker survives short commands."""
    if os.environ.get("BRIG_NO_SELF_UPDATE_CHECK"):
        return ""
    try:
        with state_lock(directory):
            state = read_state(directory)
            if state.get("pinned"):
                return ""
            checked = state.get("checked_at")
            now = time.time()
            due = (
                not isinstance(checked, (int, float))
                or not 0 <= now - checked < INTERVAL
            )
            if due:
                state["checked_at"] = now
                save_state(directory, state)
                subprocess.Popen(
                    [
                        sys.executable,
                        "-m",
                        "brig.self_update",
                        str(directory.absolute()),
                    ],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                    close_fds=True,
                )
            available = state.get("available")
            if available and newer(stable_version(available)):
                return tr(
                    "Brig {version} is available. Update with: brig self update"
                ).format(version=available)
    except (OSError, ValueError, BrigError):
        pass
    return ""


def uv_executable():
    found = shutil.which("uv")
    if found:
        return found
    directory = (
        os.environ.get("UV_INSTALL_DIR")
        or os.environ.get("XDG_BIN_HOME")
        or str(Path.home() / ".local/bin")
    )
    candidate = Path(directory) / "uv"
    if candidate.is_file() and os.access(candidate, os.X_OK):
        return str(candidate)
    raise BrigError(tr("Updating Brig requires uv. Run the Brig installer again."))


def guard_pin(state, version):
    if state.get("pinned") and (
        version is None or stable_version(version) != state["pinned"]
    ):
        raise BrigError(
            tr(
                "Brig is pinned to {version}. Run 'brig self unpin' before updating."
            ).format(version=state["pinned"])
        )


def update(directory, version=None):
    with state_lock(directory):
        guard_pin(read_state(directory), version)
    target = stable_version(version) if version is not None else refresh(directory)
    if version is None and not newer(target):
        return tr("Brig {version} is up to date.").format(version=__version__)
    uv = uv_executable()
    with tempfile.TemporaryDirectory(prefix="brig-update-") as temporary:
        wheel, requirements = release_files(target, Path(temporary))
        try:
            with state_lock(directory):
                # Pinning during a download must still stop installation. Hold
                # this lock through uv so concurrent self-upgrades cannot race.
                guard_pin(read_state(directory), target)
                subprocess.run(
                    [
                        uv,
                        "tool",
                        "install",
                        "--python",
                        ">=3.12",
                        "--reinstall",
                        "--constraints",
                        str(requirements),
                        str(wheel),
                    ],
                    check=True,
                )
        except (OSError, subprocess.CalledProcessError) as error:
            raise BrigError(
                tr("Brig update failed. Check the installer output and retry.")
            ) from error
    return tr(
        "Brig {version} installed. Reopen Brig to use it; existing project containers were kept."
    ).format(version=target)


def command(directory, action, version=None):
    try:
        if action == "update":
            return update(directory, version)
        if action == "check":
            available = refresh(directory)
            return (
                tr("Brig {version} is available. Update with: brig self update").format(
                    version=available
                )
                if newer(available)
                else tr("Brig {version} is up to date.").format(version=__version__)
            )
        with state_lock(directory):
            state = read_state(directory)
            if action == "pin":
                state["pinned"] = __version__
                message = tr(
                    "Brig pinned to {version}. Daily update checks are disabled."
                ).format(version=__version__)
            else:
                state.pop("pinned", None)
                state.pop("checked_at", None)
                message = tr("Brig version unpinned. Daily update checks are enabled.")
            save_state(directory, state)
        return message
    except OSError as error:
        raise BrigError(
            tr(
                "Cannot access Brig update settings. Retry after other Brig update commands finish."
            )
        ) from error


if __name__ == "__main__":
    check_worker(Path(sys.argv[1]))

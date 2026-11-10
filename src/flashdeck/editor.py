"""Open a deck file in the user's text editor at a given line."""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Callable, Mapping, Optional, Sequence

# Editors that take ``+LINE FILE``.
_PLUS_LINE = {
    "vi", "vim", "nvim", "gvim", "view", "nano", "pico", "emacs", "emacsclient",
    "micro", "kak", "joe", "jed", "ne", "mg", "vis", "gedit",
}
# Editors that take ``FILE:LINE`` (VS Code-likes need ``--goto`` too).
_GOTO = {"code", "code-insiders", "codium", "cursor"}
_COLON = {"subl", "sublime_text", "hx", "helix", "zed"}
# GUI editors that return at once unless told to wait for the file to close.
_WAIT = _GOTO | {"subl", "sublime_text", "zed"}


class EditorError(Exception):
    """The editor could not be started or exited with an error."""


def editor_command_line(env: Optional[Mapping[str, str]] = None) -> list[str]:
    """The editor to use: ``$VISUAL``, then ``$EDITOR``, then a platform default."""
    env = os.environ if env is None else env
    for var in ("VISUAL", "EDITOR"):
        value = (env.get(var) or "").strip()
        if value:
            return _split_windows(value) if os.name == "nt" else shlex.split(value)
    return ["notepad"] if sys.platform == "win32" else ["vi"]


def _split_windows(value: str) -> list[str]:
    """Split a Windows command line, keeping backslashes and unquoting paths."""
    return [part[1:-1] if len(part) > 1 and part[0] == part[-1] == '"' else part
            for part in shlex.split(value, posix=False)]


def _program_name(program: str) -> str:
    name = Path(program.replace("\\", "/")).name.lower()
    for ext in (".exe", ".cmd", ".bat"):
        if name.endswith(ext):
            name = name[: -len(ext)]
    return name


def build_command(editor: Sequence[str], path: str, line: int) -> list[str]:
    """Command that opens ``path`` in ``editor`` at ``line`` where the editor supports it.

    Editors whose line syntax is not known just get the file.
    """
    cmd = list(editor)
    name = _program_name(cmd[0]) if cmd else ""
    if line > 0 and name in _PLUS_LINE:
        return cmd + [f"+{line}", path]
    if name in _WAIT and "--wait" not in cmd and "-w" not in cmd:
        cmd.append("--wait")  # otherwise the review would carry on before the edit is saved
    if line > 0 and name in _GOTO:
        return cmd + ["--goto", f"{path}:{line}"]
    if line > 0 and name in _COLON:
        return cmd + [f"{path}:{line}"]
    return cmd + [path]


Runner = Callable[[list[str]], int]


def _run(cmd: list[str]) -> int:
    # Resolve through PATH/PATHEXT so ``code`` finds ``code.cmd`` on Windows.
    program = shutil.which(cmd[0]) or cmd[0]
    return subprocess.call([program, *cmd[1:]])


def open_in_editor(
    path: str,
    line: int,
    *,
    env: Optional[Mapping[str, str]] = None,
    run: Runner = _run,
) -> None:
    """Open ``path`` at ``line`` and wait for the editor to exit.

    Raises :class:`EditorError` if it cannot be started or fails.
    """
    cmd = build_command(editor_command_line(env), path, line)
    try:
        code = run(cmd)
    except OSError as exc:
        raise EditorError(f"cannot start editor {cmd[0]!r}: {exc.strerror or exc}") from None
    if code != 0:
        raise EditorError(f"editor {cmd[0]!r} exited with status {code}")

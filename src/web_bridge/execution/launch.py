"""Explicit, previewable shell adapters; argv is never implicitly shell parsed."""

import base64
import os
import shutil
from web_bridge.workspace.files import WorkspaceError


def launch_command(argv=None, command=None, shell=None, environment="host"):
    if (argv is None) == (command is None):
        raise WorkspaceError("Supply either argv or command, not both.")
    if command is None:
        if shell is not None:
            raise WorkspaceError("shell is only valid with command.")
        return argv
    if (
        not isinstance(command, str)
        or not command.strip()
        or len(command) > 16000
        or len(command.encode("utf-16-le")) > 20000
        or "\0" in command
    ):
        raise WorkspaceError("Use a nonempty shell command within 16,000 characters.")
    if shell in ("powershell", "pwsh"):
        if environment != "host":
            raise WorkspaceError("Select sh for a Linux container command.")
        executable = shutil.which("pwsh" if shell == "pwsh" else "powershell")
        if not executable:
            raise WorkspaceError("The selected PowerShell is not installed.")
        script = (
            "$ErrorActionPreference='Stop'; $global:LASTEXITCODE=0; try {\n"
            + command
            + "\nif ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }; if (-not $?) { exit 1 }\n} catch { Write-Error $_ -ErrorAction Continue; exit 1 }"
        )
        return [
            executable,
            "-NoProfile",
            "-NonInteractive",
            "-EncodedCommand",
            base64.b64encode(script.encode("utf-16-le")).decode("ascii"),
        ]
    if shell == "cmd":
        if os.name != "nt" or environment != "host":
            raise WorkspaceError(
                "Command Prompt is only available on the Windows host."
            )
        executable = os.environ.get("COMSPEC") or shutil.which("cmd.exe")
        if not executable:
            raise WorkspaceError("Command Prompt is not installed.")
        return [executable, "/d", "/s", "/c", command]
    if shell in ("sh", "bash"):
        executable = ("/bin/" + shell) if environment != "host" else shutil.which(shell)
        if not executable:
            raise WorkspaceError("The selected shell is not installed.")
        return [executable, "-c", command]
    raise WorkspaceError(
        "Choose powershell, pwsh, cmd, sh or bash for a shell command."
    )

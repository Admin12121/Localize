"""Owner-configured local Docker projects, with persistent bind mounts.

The caller must keep configure/action behind the companion's local owner gate.
Remote commands consume this saved configuration; they cannot select an engine,
mount, image, container, or privilege grant. Docker credentials stay in Docker's
local configuration and never appear in returned status.
"""

import json
import os
from pathlib import Path, PurePosixPath
import re
import secrets
import shutil
import subprocess
import threading

from web_bridge.workspace.files import WorkspaceError, linked

_LABEL = "dev.web-bridge.owner"
_MAX_OUTPUT = 256_000


class DockerContainerMissing(WorkspaceError):
    """A positively identified missing selection, rather than an engine failure."""

# Per-exec identity and process start time constrain cancellation to owned commands.
_IDENTITY_FUNCTION = r"""
signal_group() {
    test -f "$d/identity" || return 1
    read -r pid started recorded < "$d/identity" || return 1
    case "$pid:$started" in *[!0-9:]*|:*) return 1;; esac
    test "$pid" -gt 1 && test "$recorded" = "$token" || return 1
    current=$(awk '{print $22}' "/proc/$pid/stat" 2>/dev/null) || return 1
    test "$current" = "$started" || return 1
    tr '\000' '\n' < "/proc/$pid/environ" 2>/dev/null | grep -F -x "WEB_BRIDGE_EXEC_TOKEN=$token" >/dev/null || return 1
    kill "-$1" "-$pid" 2>/dev/null
}
"""
_GROUP = r"""
d=$1; token=$2; shift 2
test ! -e "$d/cancelled" || exit 143
started=$(awk '{print $22}' /proc/$$/stat) || exit 125
printf '%s %s %s\n' "$$" "$started" "$token" > "$d/identity.tmp" || exit 125
mv "$d/identity.tmp" "$d/identity" || exit 125
test ! -e "$d/cancelled" || exit 143
trap ':' TERM
"$@" &
child=$!
wait "$child"; result=$?
while kill -0 "$child" 2>/dev/null; do wait "$child"; result=$?; done
trap '' TERM
printf '%s\n' "$result" > "$d/result.tmp"
mv "$d/result.tmp" "$d/result"
while :; do sleep 1; done
"""
_SUPERVISOR = _IDENTITY_FUNCTION + r"""
d=$1; token=$2; group=$3; shift 3
test -d "$d" && test ! -L "$d" || exit 125
test ! -e "$d/cancelled" || exit 143
setsid sh -c "$group" bridge-group "$d" "$token" "$@" &
launcher=$!
while kill -0 "$launcher" 2>/dev/null; do
    if test -f "$d/result"; then
        read -r result < "$d/result"
        signal_group TERM || :
        sleep .2
        signal_group KILL || :
        wait "$launcher" 2>/dev/null
        rm -rf "$d"
        exit "$result"
    fi
    sleep .05
done
wait "$launcher"; result=$?
rm -rf "$d"
exit "$result"
"""
_PREPARE = r"""
for tool in sh setsid awk tr grep sleep mkdir mv rm; do
    command -v "$tool" >/dev/null || exit 125
done
test -r /proc/self/stat && test -r /proc/self/environ || exit 125
umask 077
mkdir -m 700 "$1" || exit 125
"""
_CANCEL = _IDENTITY_FUNCTION + r"""
d=$1; token=$2
test -d "$d" && test ! -L "$d" || exit 3
: > "$d/cancelled" || exit 125
# Tombstones prevent queued commands from starting after cancellation.
i=0
while test "$i" -lt 40; do
    if signal_group TERM; then
        sleep .2
        signal_group KILL || :
        exit 0
    fi
    test -d "$d" || exit 0
    i=$((i+1)); sleep .05
done
exit 0
"""


class DockerProject:
    """A locally selected project environment; no automatic pulls or fallback."""

    def __init__(self, runtime):
        self.path = Path(runtime) / "docker-project.json"
        self._binary = shutil.which("docker")
        self._lock = threading.RLock()
        self._workspace = None
        self._jobs = {}
        self._config = None
        self._owned = {}
        if self.path.exists():
            try:
                saved = json.loads(self.path.read_text(encoding="utf-8"))
                self._config = saved.get("config")
                self._owned = saved.get("owned", {})
            except (OSError, ValueError, TypeError):
                raise WorkspaceError(
                    "Docker project settings are unreadable; configure them again locally."
                ) from None

    def _save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(self.path.name + ".tmp")
        temporary.write_text(
            json.dumps({"config": self._config, "owned": self._owned}), encoding="utf-8"
        )
        try:
            temporary.chmod(0o600)
        except OSError:
            pass
        os.replace(temporary, self.path)

    def _command(self, args):
        if not self._binary:
            raise WorkspaceError(
                "Docker CLI is unavailable. Install Docker and start the local Linux engine."
            )
        command = [self._binary]
        if self._config:
            command += ["--config", self._config["docker_config"]]
            if self._config.get("context"):
                command += ["--context", self._config["context"]]
        return command + list(args)

    def _invoke(self, args, timeout=30):
        environment = dict(os.environ)
        # Pin the Docker context so preflight and execution use the same engine.
        for key in (
            "DOCKER_HOST",
            "DOCKER_CONTEXT",
            "DOCKER_CONFIG",
            "DOCKER_TLS_VERIFY",
            "DOCKER_CERT_PATH",
        ):
            environment.pop(key, None)
        try:
            result = subprocess.run(
                self._command(args),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                env=environment,
            )
        except FileNotFoundError:
            raise WorkspaceError(
                "Docker CLI is unavailable. Install Docker and start its Linux engine."
            ) from None
        except subprocess.TimeoutExpired:
            raise WorkspaceError(
                "Docker did not respond before the operation timeout. Check the local engine."
            ) from None
        except OSError:
            raise WorkspaceError(
                "Docker could not start. Check the local Docker installation and access permissions."
            ) from None
        if result.returncode:
            # Docker diagnostics can expose credentials or local paths.
            if args[:2] == ["container", "inspect"] and re.search(
                r"(?:^|\n)(?:Error(?: response from daemon)?:\s*)?No such (?:object|container):",
                result.stderr.strip(), re.IGNORECASE,
            ):
                raise DockerContainerMissing(
                    "The selected container no longer exists in this Docker context. "
                    "Recreate the project container locally, or detach and select an existing one."
                )
            if args[:2] == ["image", "inspect"]:
                raise WorkspaceError(
                    "Image is missing; explicitly pull or prepare it locally."
                )
            if args[0] == "info":
                raise WorkspaceError(
                    "Docker engine is unavailable. Start the selected local Linux engine."
                )
            if args[0] == "exec":
                raise WorkspaceError(
                    "Docker exec failed. Check the running container, work directory, shell, and setsid support."
                )
            if args[:2] == ["container", "start"]:
                raise WorkspaceError(
                    "Docker could not start this container. Check Docker Desktop's "
                    "container details for mount sharing, available memory, and image shell support."
                )
            raise WorkspaceError(
                "Docker operation failed (exit %s). Check the selected local context and container."
                % result.returncode
            )
        if len(result.stdout) > _MAX_OUTPUT:
            raise WorkspaceError("Docker response exceeded the bounded result size.")
        return result.stdout.strip()

    def _json(self, args):
        response = self._invoke(args)
        try:
            return json.loads(response)
        except (json.JSONDecodeError, TypeError):
            raise WorkspaceError(
                "Docker returned an invalid inspection response."
            ) from None

    def _endpoint(self, context):
        try:
            endpoint = self._json(["context", "inspect", context])[0]["Endpoints"][
                "docker"
            ]["Host"]
        except (KeyError, IndexError, TypeError):
            raise WorkspaceError(
                "The selected Docker context has no usable endpoint."
            ) from None
        if not isinstance(endpoint, str) or not (
            endpoint.startswith("unix:///") or endpoint.startswith("npipe:////./pipe/")
        ):
            raise WorkspaceError(
                "Only a local Docker socket or named pipe is supported; select a local context."
            )
        return endpoint

    def _check_engine(self):
        if not self._config:
            raise WorkspaceError("Configure the Docker project locally first.")
        if self._endpoint(self._config["context"]) != self._config["endpoint"]:
            raise WorkspaceError(
                "The Docker context endpoint changed; reconfigure it locally before continuing."
            )
        if self._json(["info", "--format", "{{json .}}"]).get("OSType") != "linux":
            raise WorkspaceError(
                "This Docker project requires a local Linux container engine."
            )

    def _check_workspace(self, workspace=None):
        if not self._config:
            raise WorkspaceError("Configure the Docker project locally first.")
        candidate = workspace or self._workspace
        if candidate is not None:
            candidate.check_root()
            if (
                str(candidate.root) != self._config["root"]
                or list(candidate.identity) != self._config["identity"]
            ):
                raise WorkspaceError(
                    "Docker belongs to another selected workspace; configure it again locally."
                )
        try:
            root = Path(self._config["root"])
            info = root.lstat()
            if (
                linked(info)
                or not root.is_dir()
                or root.resolve() != root
                or [info.st_dev, info.st_ino] != self._config["identity"]
            ):
                raise WorkspaceError(
                    "The Docker workspace changed or was replaced; select it again locally."
                )
        except OSError:
            raise WorkspaceError(
                "The Docker workspace changed or was replaced; select it again locally."
            ) from None

    def configure(self, config, workspace):
        """Owner-only. Select settings without pulling images or creating containers."""
        with self._lock:
            if not isinstance(config, dict):
                raise WorkspaceError("Use a local Docker configuration object.")
            allowed = {
                "context",
                "docker_config",
                "image",
                "workdir",
                "network",
                "cpus",
                "memory",
                "pids_limit",
            }
            if set(config) - allowed:
                raise WorkspaceError("Unsupported Docker project setting.")
            workspace.check_root()
            saved = self._config or {}
            docker_config = (
                Path(
                    config.get("docker_config")
                    or saved.get("docker_config")
                    or os.environ.get("DOCKER_CONFIG")
                    or Path.home() / ".docker"
                )
                .expanduser()
                .absolute()
            )
            context = config.get("context") or os.environ.get("DOCKER_CONTEXT")
            if context is None:
                if os.environ.get("DOCKER_HOST"):
                    raise WorkspaceError(
                        "A Docker host override is active; select an explicit local context instead."
                    )
                previous = self._config
                self._config = {"docker_config": str(docker_config), "context": None}
                try:
                    context = self._invoke(["context", "show"])
                finally:
                    self._config = previous
            if not isinstance(context, str) or not re.fullmatch(
                r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", context
            ):
                raise WorkspaceError("Select a valid local Docker context name.")
            image = config.get("image", "node:24-alpine")
            if not isinstance(image, str) or not re.fullmatch(
                r"[A-Za-z0-9][A-Za-z0-9_.:/@+-]{0,255}", image
            ):
                raise WorkspaceError(
                    "Select a valid locally prepared Docker image reference."
                )
            workdir = config.get("workdir", "/workspace")
            if (
                not isinstance(workdir, str)
                or not re.fullmatch(r"/[A-Za-z0-9_./-]+", workdir)
                or ".." in PurePosixPath(workdir).parts
                or workdir == "/"
            ):
                raise WorkspaceError(
                    "Use an absolute container project path, such as /workspace."
                )
            workdir = str(PurePosixPath(workdir))
            network = config.get("network", "bridge")
            if network not in ("bridge", "none"):
                raise WorkspaceError(
                    "Managed projects support bridge or none networking."
                )
            cpus = config.get("cpus", saved.get("cpus", 2))
            if (
                isinstance(cpus, bool)
                or not isinstance(cpus, (int, float))
                or not 0 < cpus <= 64
            ):
                raise WorkspaceError(
                    "Choose a CPU limit greater than zero and at most 64."
                )
            memory = config.get("memory", saved.get("memory", "2g"))
            if not isinstance(memory, str) or not re.fullmatch(
                r"[1-9][0-9]{0,6}[mMgG]", memory
            ):
                raise WorkspaceError("Choose a memory limit such as 512m or 2g.")
            pids = config.get("pids_limit", saved.get("pids_limit", 256))
            if (
                isinstance(pids, bool)
                or not isinstance(pids, int)
                or not 16 <= pids <= 65536
            ):
                raise WorkspaceError("Choose a process limit between 16 and 65536.")
            if "," in str(workspace.root):
                raise WorkspaceError(
                    "Docker bind-mount project paths cannot contain a comma."
                )
            previous = self._config
            candidate = {
                "docker_config": str(docker_config),
                "context": context,
                "image": image,
                "workdir": workdir,
                "network": network,
                "cpus": cpus,
                "memory": memory,
                "pids_limit": pids,
                "root": str(workspace.root),
                "identity": list(workspace.identity),
                "container_id": None,
                "mode": None,
                "allow_broad_access": False,
            }
            self._config = candidate
            try:
                candidate["endpoint"] = self._endpoint(context)
                self._check_engine()
                if previous and previous.get("container_id"):
                    pinned = (
                        "docker_config", "context", "endpoint", "root",
                        "identity", "workdir", "image", "network",
                        "cpus", "memory", "pids_limit",
                    )
                    if any(previous.get(key) != candidate[key] for key in pinned):
                        raise WorkspaceError(
                            "The selected Docker container still uses the previous "
                            "settings. Stop/remove the bridge-owned container, or "
                            "detach the existing selection locally before changing "
                            "the image, context, mount, network or resource limits."
                        )
                    for key in ("container_id", "mode", "allow_broad_access"):
                        candidate[key] = previous.get(key)
                self._workspace = workspace
                self._save()
            except Exception:
                self._config = previous
                raise
            return self.status()

    @staticmethod
    def _host_path(path):
        value = str(path).replace("\\", "/")
        match = re.fullmatch(
            r"/(?:run/desktop/mnt/host|host_mnt)/([A-Za-z])/(.*)", value
        )
        if match:
            value = match[1] + ":/" + match[2]
        return value.rstrip("/").casefold() if os.name == "nt" else value.rstrip("/")

    def _inspect(self, identifier):
        if not isinstance(identifier, str) or not re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", identifier
        ):
            raise WorkspaceError("Choose an existing Docker container ID or name.")
        try:
            info = self._json(["container", "inspect", identifier])[0]
        except (IndexError, TypeError):
            raise WorkspaceError(
                "Docker container inspection was incomplete."
            ) from None
        identity = info.get("Id", "")
        if not re.fullmatch(r"[a-f0-9]{64}", identity):
            raise WorkspaceError("Docker returned an invalid container identity.")
        if re.fullmatch(r"[a-f0-9]{64}", identifier) and identifier != identity:
            raise WorkspaceError(
                "Docker container identity changed; select it again locally."
            )
        return info

    def _validate_mount(self, info):
        config = self._config
        matches = [
            mount
            for mount in info.get("Mounts", [])
            if mount.get("Destination", "").rstrip("/") == config["workdir"]
        ]
        if (
            len(matches) != 1
            or matches[0].get("Type") != "bind"
            or not matches[0].get("RW")
            or self._host_path(matches[0].get("Source", ""))
            != self._host_path(config["root"])
        ):
            raise WorkspaceError(
                "Container must mount the selected host project read-write at the configured workspace path."
            )
        if any(
            m.get("Destination", "").startswith(config["workdir"] + "/")
            for m in info.get("Mounts", [])
        ):
            raise WorkspaceError(
                "A nested container mount hides part of the selected workspace."
            )

    def _broad_access(self, info):
        host = info.get("HostConfig", {})
        other_mounts = [
            m
            for m in info.get("Mounts", [])
            if m.get("Destination", "").rstrip("/") != self._config["workdir"]
        ]
        return bool(
            host.get("Privileged")
            or host.get("CapAdd")
            or host.get("NetworkMode") in ("host", "container")
            or str(host.get("NetworkMode", "")).startswith("container:")
            or host.get("PidMode") == "host"
            or host.get("IpcMode") == "host"
            or host.get("Devices")
            or host.get("PortBindings")
            or other_mounts
        )

    def _selected(self, workspace=None, running=False):
        self._check_workspace(workspace)
        self._check_engine()
        container = self._config.get("container_id")
        if not container:
            raise WorkspaceError(
                "Create or attach a Docker project container locally first."
            )
        info = self._inspect(container)
        self._validate_mount(info)
        if self._broad_access(info) and not self._config.get("allow_broad_access"):
            raise WorkspaceError(
                "Container has broad access; an explicit local broad-access grant is required."
            )
        if running and not info.get("State", {}).get("Running"):
            raise WorkspaceError(
                "The selected Docker project container is stopped. Start it locally first."
            )
        return info

    def _is_owned(self, info):
        owner = self._owned.get(info["Id"])
        return bool(
            owner
            and owner.get("context") == self._config["context"]
            and owner.get("endpoint") == self._config["endpoint"]
            and info.get("Config", {}).get("Labels", {}).get(_LABEL)
            == owner.get("token")
        )

    def status(self, workspace=None):
        """Safe remote status: never expose root, Docker config, environment or mounts."""
        with self._lock:
            result = {
                "configured": bool(self._config),
                "ready": False,
                "image_ready": False,
                "container_id": None,
                "mode": None,
                "owned": False,
                "running": False,
                "container_missing": False,
                "workspace_matches": True,
            }
            if not self._config:
                return result
            config = self._config
            result.update(
                context=config["context"],
                image=config["image"],
                workdir=config["workdir"],
                network=config["network"],
                container_id=config.get("container_id"),
                mode=config.get("mode"),
                cpus=config["cpus"],
                memory=config["memory"],
                pids_limit=config["pids_limit"],
            )
            try:
                if workspace is not None:
                    result["workspace_matches"] = (
                        str(workspace.root) == config["root"]
                        and list(workspace.identity) == config["identity"]
                    )
                self._check_workspace(workspace)
                self._check_engine()
                try:
                    self._json(["image", "inspect", config["image"]])
                    result["image_ready"] = True
                except WorkspaceError as exc:
                    result["image_error"] = str(exc)
                if config.get("container_id"):
                    info = self._selected()
                    result["owned"] = self._is_owned(info)
                    result["running"] = bool(info.get("State", {}).get("Running"))
                    result["user"] = (
                        info.get("Config", {}).get("User") or "image default"
                    )
                    result["broad_access"] = self._broad_access(info)
                    result["ready"] = result["running"]
                    state = info.get("State", {})
                    result["container_state"] = state.get("Status", "running" if result["running"] else "stopped")
                    result["exit_code"] = state.get("ExitCode")
                    result["oom_killed"] = bool(state.get("OOMKilled"))
                    if not result["running"]:
                        if result["oom_killed"]:
                            result["error"] = "The container exceeded its memory limit. Free memory or choose a higher limit before recreating it."
                        elif state.get("Error"):
                            result["error"] = "Docker could not start the container. Check its details in Docker Desktop for mount, resource, or image errors."
                        elif state.get("ExitCode"):
                            result["error"] = "The container exited with code %s. Read its logs and verify the image supports sh and sleep." % state["ExitCode"]
                return result
            except WorkspaceError as exc:
                result["container_missing"] = isinstance(exc, DockerContainerMissing)
                result["error"] = str(exc)
                return result

    def action(self, action, workspace, **args):
        """Owner-only explicit setup; stop/remove require recorded ownership."""
        with self._lock:
            if action == "detach":
                # Forgetting a selection does not touch the engine or host files.
                # It must remain possible after a workspace change or engine failure.
                if self._jobs:
                    raise WorkspaceError(
                        "Finish or cancel active Docker commands before detaching."
                    )
                if self._config:
                    self._config.update(container_id=None, mode=None, allow_broad_access=False)
                    self._save()
                return self.status(workspace)
            self._check_workspace(workspace)
            self._check_engine()
            config = self._config
            if action == "pull":
                self._invoke(["pull", config["image"]], timeout=600)
            elif action == "create":
                if config.get("container_id"):
                    raise WorkspaceError(
                        "A project container is already selected. Remove or select another container locally."
                    )
                self._json(["image", "inspect", config["image"]])
                token = secrets.token_hex(24)
                command = [
                    "container",
                    "create",
                    "--pull",
                    "never",
                    "--init",
                    "--label",
                    _LABEL + "=" + token,
                    "--mount",
                    "type=bind,src=%s,dst=%s" % (config["root"], config["workdir"]),
                    "--workdir",
                    config["workdir"],
                    "--network",
                    config["network"],
                    "--cpus",
                    str(config["cpus"]),
                    "--memory",
                    config["memory"],
                    "--pids-limit",
                    str(config["pids_limit"]),
                    "--cap-drop",
                    "ALL",
                    "--security-opt",
                    "no-new-privileges",
                    "--entrypoint",
                    "sh",
                    config["image"],
                    "-c",
                    'trap "exit 0" TERM INT; while :; do sleep 3600 & wait $!; done',
                ]
                container = self._invoke(command)
                if not re.fullmatch(r"[a-f0-9]{64}", container):
                    raise WorkspaceError(
                        "Docker did not return the created container identity."
                    )
                self._owned[container] = {
                    "token": token,
                    "context": config["context"],
                    "endpoint": config["endpoint"],
                }
                config.update(
                    container_id=container, mode="managed", allow_broad_access=False
                )
                self._save()  # Record ownership before attempting start; failed starts remain recoverable.
                self._selected(workspace)
                self._invoke(["container", "start", container])
            elif action == "attach":
                info = self._inspect(
                    args.get("container", args.get("container_id", ""))
                )
                self._validate_mount(info)
                broad = self._broad_access(info)
                if broad and args.get("allow_broad_access") is not True:
                    raise WorkspaceError(
                        "Container has broad access; an explicit local broad-access grant is required."
                    )
                config.update(
                    container_id=info["Id"], mode="attached", allow_broad_access=broad
                )
                self._save()
            elif action in ("start", "stop", "remove", "logs"):
                info = self._selected(workspace)
                if action in ("stop", "remove") and not self._is_owned(info):
                    raise WorkspaceError(
                        "Only bridge-owned recorded containers may be stopped or removed; ownership validation failed."
                    )
                if action == "logs":
                    return {
                        "logs": self._invoke(
                            ["container", "logs", "--tail", "100", info["Id"]]
                        )[:16_000]
                    }
                if action == "remove":
                    self._invoke(["container", "rm", "--force", info["Id"]])
                    self._owned.pop(info["Id"], None)
                    config.update(
                        container_id=None, mode=None, allow_broad_access=False
                    )
                    self._save()
                else:
                    self._invoke(["container", action, info["Id"]])
            else:
                raise WorkspaceError("Unknown Docker project action.")
            return self.status()

    def validate_workspace(self, workspace):
        with self._lock:
            self._check_workspace(workspace)
            self._workspace = workspace
            return True

    def build_command(self, job_id, argv, cwd=""):
        """Return an exact argv launch; all user arguments remain separate strings."""
        with self._lock:
            info = self._selected(running=True)
            if (
                not isinstance(job_id, str)
                or not 1 <= len(job_id) <= 200
                or job_id in self._jobs
            ):
                raise WorkspaceError("Use a unique Docker job identity.")
            if (
                not isinstance(argv, (list, tuple))
                or not 1 <= len(argv) <= 256
                or any(
                    not isinstance(a, str) or "\0" in a or len(a) > 32_768 for a in argv
                )
                or not argv[0]
                or sum(map(len, argv)) > 65_536
            ):
                raise WorkspaceError(
                    "Use a bounded nonempty Docker command argument array."
                )
            if cwd is None:
                cwd = ""
            if (
                not isinstance(cwd, str)
                or len(cwd) > 500
                or "\\" in cwd
                or ":" in cwd
                or (
                    cwd
                    and (
                        cwd.startswith("/")
                        or any(part in ("", ".", "..") for part in cwd.split("/"))
                    )
                )
                or any(ord(c) < 32 for c in cwd)
            ):
                raise WorkspaceError("Use a relative container workspace directory.")
            if self._workspace:
                parts = self._workspace.parts(cwd, directory=True)
                with self._workspace.parent(parts):
                    pass
            elif cwd:
                raise WorkspaceError(
                    "Select the saved project locally before running commands in a subdirectory."
                )
            token = secrets.token_hex(24)
            directory = "/tmp/web-bridge-exec-" + token
            self._invoke(
                ["exec", info["Id"], "sh", "-c", _PREPARE, "bridge-prepare", directory]
            )
            self._jobs[job_id] = {
                "container_id": info["Id"],
                "directory": directory,
                "token": token,
                "context": self._config["context"],
                "endpoint": self._config["endpoint"],
                "root": self._config["root"],
                "identity": list(self._config["identity"]),
            }
            workdir = self._config["workdir"] + ("/" + cwd if cwd else "")
            return self._command(
                [
                    "exec",
                    "--env",
                    "WEB_BRIDGE_EXEC_TOKEN=" + token,
                    "--workdir",
                    workdir,
                    info["Id"],
                    "sh",
                    "-c",
                    _SUPERVISOR,
                    "bridge-exec",
                    directory,
                    token,
                    _GROUP,
                ]
                + list(argv)
            )

    def cancel(self, job_id):
        """Cancel one positively identified exec group, never the container itself."""
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return False
            info = self._selected(running=True)
            if (
                any(
                    job[key] != self._config[key]
                    for key in ("context", "endpoint", "root", "identity")
                )
                or info["Id"] != job["container_id"]
            ):
                raise WorkspaceError(
                    "Docker execution identity changed; cancellation requires local recovery."
                )
            self._invoke(
                [
                    "exec",
                    info["Id"],
                    "sh",
                    "-c",
                    _CANCEL,
                    "bridge-cancel",
                    job["directory"],
                    job["token"],
                ]
            )
            self._jobs.pop(job_id, None)
            return True

    def finish(self, job_id):
        """Forget a terminal job after its supervisor has exited.

        The caller must cancel live work before stopping its Docker CLI. Normal
        supervisor exit already removes its marker directory; forgetting a token
        performs no container mutation and cannot signal an unrelated process.
        """
        with self._lock:
            return self._jobs.pop(job_id, None) is not None

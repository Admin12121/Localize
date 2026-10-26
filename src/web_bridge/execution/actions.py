"""ExecutionActions exposes this feature through the permission-controlled application facade."""

import os
from web_bridge.workspace.files import WorkspaceError
from web_bridge.execution.launch import launch_command


class ExecutionActions:
    def validate_profile(self, value):
        if not isinstance(value, dict) or set(value) - {
            "environment",
            "shell",
            "default_timeout",
            "max_timeout",
        }:
            raise WorkspaceError("Invalid project profile.")
        result = {**getattr(self, "profile", {}), **value}
        result.setdefault("environment", "container")
        result.setdefault("shell", "powershell" if os.name == "nt" else "sh")
        result.setdefault("default_timeout", 600)
        result.setdefault("max_timeout", 3600)
        if result["environment"] not in ("host", "container", "docker"):
            raise WorkspaceError(
                "Choose host, container snapshot, or live Docker project."
            )
        if result["shell"] not in ("powershell", "pwsh", "cmd", "sh", "bash"):
            raise WorkspaceError("Choose an installed supported shell.")
        if result["environment"] != "host" and result["shell"] not in ("sh", "bash"):
            raise WorkspaceError(
                "Linux Docker modes require sh or bash as their shell."
            )
        for key in ("default_timeout", "max_timeout"):
            if type(result[key]) is not int or not 1 <= result[key] <= 3600:
                raise WorkspaceError(
                    "Command timeouts must be between 1 and 3600 seconds."
                )
        if result["default_timeout"] > result["max_timeout"]:
            raise WorkspaceError("Default timeout exceeds the maximum.")
        return result

    def claim_job(self, key):
        identity = self.workspace_snapshot()
        owner = getattr(self.actor, "owner", None)
        borrowed = owner is not None
        if not borrowed:
            owner = "job-" + key
            self.tasks.claim_workspace(identity, owner, ttl=4000)
        self.job_leases[key] = (identity, owner, borrowed)

    def release_job(self, key):
        lease = self.job_leases.pop(key, None)
        if lease and not lease[2]:
            self.tasks.release_workspace(lease[0], lease[1])

    def docker_status(self, workspace_id=None):
        with self.lock:
            ws = self.require_workspace("execution", workspace_id)
            if self.docker_project._config:
                self.docker_project.validate_workspace(ws)
        self.docker_state = self.docker_project.status()
        return self.docker_state

    def configure_docker(self, config):
        with self.lock, self.writer():
            ws = self.require("execution")
            self.jobs.revoke()
            self.docker_state = self.docker_project.configure(config, ws)
            return self.docker_state

    def docker_action(self, action, **arguments):
        with self.lock, self.writer():
            result = self.docker_project.action(
                action, self.require("execution"), **arguments
            )
            self.docker_state = self.docker_project.status()
            return result

    def acknowledge_command_recovery(self, job_id):
        with self.lock:
            ws = self.require("execution")
            return self.jobs.acknowledge_recovery(job_id, ws, allow_unbound=True)

    def discard_artifact(self, job_id):
        import re, shutil

        if not isinstance(job_id, str) or not re.fullmatch(r"[0-9a-f]{32}", job_id):
            raise WorkspaceError("Invalid retained artifact ID.")
        with self.lock, self.writer():
            self.require("execution")
            item = self.jobs.items.get(job_id)
            if item and item["state"] in ("pending", "approved", "running"):
                raise WorkspaceError("Command is still active.")
            target = (self.runtime / ("job-" + job_id)).resolve()
            if target.parent != self.runtime.resolve() or target.is_symlink():
                raise WorkspaceError("Invalid artifact path.")
            if target.is_dir():
                shutil.rmtree(target)
            if item and item.get("snapshot"):
                item["snapshot"]["retained_locally"] = False
                item["artifact_retained"] = False
            return {"removed": True, "artifact_id": job_id}

    def command_request(
        self,
        argv=None,
        idempotency_key=None,
        cwd="",
        timeout_seconds=None,
        environment=None,
        workspace_id=None,
        command=None,
        shell=None,
    ):
        with self.lock:
            ws = self.require_workspace("execution", workspace_id)
            selected = environment or self.profile["environment"]
            if self.profile_explicit and selected != self.profile["environment"]:
                raise WorkspaceError(
                    "Command environment differs from the local project profile. Change it locally first."
                )
            if selected == "host" and not self.policy["host"]:
                raise WorkspaceError("Host execution is disabled locally.")
            timeout = (
                self.profile["default_timeout"]
                if timeout_seconds is None
                else timeout_seconds
            )
            if (
                type(timeout) not in (int, float)
                or not 1 <= timeout <= self.profile["max_timeout"]
            ):
                raise WorkspaceError(
                    "Command timeout exceeds the configured local limit."
                )
            selected_shell = (
                (shell or self.profile["shell"]) if command is not None else shell
            )
            arguments = launch_command(argv, command, selected_shell, selected)
            metadata = (
                {"command": command, "shell": selected_shell}
                if command is not None
                else {}
            )
            return self.jobs.request(
                arguments,
                cwd,
                timeout,
                selected,
                idempotency_key,
                ws,
                self.generation,
                self.policy["network"],
                self.policy["image"],
                self.policy["auto_container"],
                self.policy["write"],
                self.policy["auto_write"],
                metadata=metadata,
            )

    def command_status(self, job_id, output_offset=0):
        with self.lock:
            self.require("execution")
            result = self.jobs.status(job_id, output_offset)
            if (
                result.get("session_id") != self.jobs.session_id
                or result["request"]["generation"] != self.generation
            ):
                raise WorkspaceError("This job belongs to a revoked workspace session.")
            return result

    def command_cancel(self, job_id):
        with self.lock:
            result = self.jobs.cancel(job_id)
        return {"job_id": job_id, "state": result["state"]}

    def approve_command(self, job_id, allow):
        with self.lock:
            self.require("execution")
            return self.jobs.approve(job_id, allow)

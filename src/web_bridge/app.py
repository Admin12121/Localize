"""Local-only authority for CTF and workspace tools."""

import platform
from pathlib import Path
import threading
import secrets
from web_bridge.resources import PROJECT, VERSION
from web_bridge.execution.jobs import Jobs
from web_bridge.security.access import AccessControl
from web_bridge.workspace.actions import WorkspaceActions
from web_bridge.execution.actions import ExecutionActions
from web_bridge.integrations.actions import IntegrationActions
from web_bridge.tasks.actions import TaskActions
from web_bridge.execution.docker import DockerProject
from web_bridge.integrations.registry import Integrations
from web_bridge.tasks.store import TaskStore
from web_bridge.workspace.operations import FileOperations
from web_bridge.tasks.runner import AgentRunner
import json
from web_bridge.workspace.files import Workspace, WorkspaceError

CTF_TOOLS = {
    "list_targets",
    "http_request",
    "http_batch",
    "inspect_html",
    "session_cookies",
    "reset_session",
    "browser_action",
    "request_history",
}


class Companion(
    AccessControl, WorkspaceActions, ExecutionActions, IntegrationActions, TaskActions
):
    def __init__(self, network, runtime):
        self.network_bridge = network
        self.runtime = Path(runtime).resolve()
        self.lock = threading.RLock()
        self.workspace = None
        self.generation = 0
        self.paused = False
        self.workspace_id = None
        self.policy = {
            "ctf": True,
            "read": False,
            "write": False,
            "execution": False,
            "host": False,
            "network": False,
            "auto_container": False,
            "auto_write": False,
            "integrations": False,
            "auto_operations": False,
            "recursive_delete": False,
            "image": "python:3.12-alpine",
        }
        self.jobs = Jobs(
            self.runtime,
            self.lock,
            lambda generation: not self.paused and generation == self.generation,
        )
        self.actor = threading.local()
        self.file_operations = None
        self.job_leases = {}
        self.profile = {
            "environment": "container",
            "shell": "sh",
            "default_timeout": 600,
            "max_timeout": 3600,
        }
        self.profile_explicit = False
        self.profile_path = self.runtime / "project-profile.json"
        if self.profile_path.is_file():
            try:
                self.profile = self.validate_profile(
                    json.loads(self.profile_path.read_text("utf-8"))
                )
                self.profile_explicit = True
            except (ValueError, OSError):
                pass
        self.docker_project = DockerProject(self.runtime / "docker-project")
        self.docker_state = {"configured": False, "ready": False}
        self.integrations = Integrations(self.runtime / "integrations")
        self.tasks = TaskStore(self.runtime / "tasks")
        self.runner = AgentRunner(self.tasks, self.agent_execute, self.agent_verify)
        self.jobs.project = self.docker_project
        self.jobs.on_approve = self.claim_job
        self.jobs.on_finish = self.release_job

        self.attach_network(network)

    def attach_network(self, network):
        self.network_bridge = network
        if network is not None:
            generation = self.generation
            network.cancelled = (
                lambda: self.paused
                or not self.policy["ctf"]
                or generation != self.generation
                or self.network_bridge is not network
            )

    def stop_browser(self):
        worker = (
            getattr(self.network_bridge, "_browser_process", None)
            if self.network_bridge
            else None
        )
        if worker:
            worker.close()

    def configure(
        self,
        root="",
        alias="workspace",
        targets=None,
        allow_private=None,
        profile=None,
        **policy,
    ):
        validated_profile = (
            self.validate_profile(profile) if profile is not None else None
        )
        allowed = set(self.policy)
        if set(policy) - allowed:
            raise WorkspaceError("Unknown policy setting.")
        updated = {**self.policy, **policy}
        for name in allowed - {"image"}:
            if type(updated[name]) is not bool:
                raise WorkspaceError("Permission settings must be true or false.")
        if updated["image"] not in (
            "python:3.12-alpine",
            "node:24-alpine",
            "alpine:3.21",
        ):
            raise WorkspaceError(
                "Choose one of the supported locally prepared container images."
            )
        selected = Workspace(root, alias) if root else None
        if selected and (
            selected.root == self.runtime
            or selected.root in self.runtime.parents
            or self.runtime in selected.root.parents
        ):
            raise WorkspaceError("Workspace and companion runtime must be separate.")
        if (
            updated["read"] or updated["write"] or updated["execution"]
        ) and not selected:
            raise WorkspaceError("Select a local project folder first.")
        with self.lock:
            from web_bridge.web.client import Bridge

            previous = self.network_bridge
            network = Bridge(
                (
                    targets
                    if targets is not None
                    else dict(previous.targets) if previous else {}
                ),
                allow_private=(
                    allow_private
                    if allow_private is not None
                    else bool(previous and previous.allow_private)
                ),
            )
            self.runner.close()
            self.generation += 1
            self.jobs.revoke()
            self.stop_browser()
            if self.workspace:
                self.workspace.edits.clear()
            self.workspace = selected
            self.policy = updated
            self.file_operations = (
                FileOperations(selected, self.runtime / "file-operations")
                if selected
                else None
            )
            self.jobs.file_operations = self.file_operations
            if selected and self.docker_project._config:
                try:
                    self.docker_project.validate_workspace(selected)
                    self.docker_state = self.docker_project.status()
                except WorkspaceError:
                    self.docker_state = {
                        "configured": True,
                        "ready": False,
                        "error": "Docker mapping belongs to another project. Configure the selected project locally.",
                    }
            if validated_profile is not None:
                self.profile = validated_profile
                self.profile_explicit = True
                self.profile_path.write_text(json.dumps(self.profile), encoding="utf-8")
            self.runner = AgentRunner(self.tasks, self.agent_execute, self.agent_verify)
            self.workspace_id = secrets.token_urlsafe(18) if selected else None
            self.attach_network(network)
            return self.bridge_status()

    def pause(self, paused=True):
        with self.lock:
            self.runner.close()
            self.runner = AgentRunner(self.tasks, self.agent_execute, self.agent_verify)
            self.paused = bool(paused)
            self.generation += 1
            self.jobs.revoke()
            self.stop_browser()
            self.workspace_id = secrets.token_urlsafe(18) if self.workspace else None
            if self.network_bridge is not None:
                from web_bridge.web.client import Bridge

                self.attach_network(
                    Bridge(
                        dict(self.network_bridge.targets),
                        allow_private=self.network_bridge.allow_private,
                    )
                )
            if self.workspace:
                self.workspace.edits.clear()
            if self.file_operations:
                self.file_operations.items.clear()
            return self.bridge_status()

    def bridge_status(self):
        with self.lock:
            return {
                "version": VERSION,
                "author": PROJECT["author"],
                "creator": PROJECT["creator"],
                "license": PROJECT["license"],
                "platform": platform.system(),
                "paused": self.paused,
                "generation": self.generation,
                "workspace": self.workspace.alias if self.workspace else None,
                "workspace_id": self.workspace_id,
                "permissions": dict(self.policy),
                "docker_cli_available": bool(self.jobs.docker),
                "pending_commands": self.jobs.pending_count(),
                "pending_edits": (
                    (len(self.workspace.edits) + len(self.file_operations.items))
                    if self.workspace
                    else 0
                ),
                "profile": dict(self.profile),
                "capabilities": {
                    "shell_commands": True,
                    "file_operations": True,
                    "docker_projects": True,
                    "selected_integrations": True,
                    "durable_tasks": True,
                    "local_agent": True,
                    "chatgpt_events": False,
                },
                "local_controls": "Open the companion control panel on this computer to change permissions or approve operations.",
                "working_context": self.working_context(),
            }

    def working_context(self):
        """Describe usable routes without probing, connecting, or granting access.

        'configured' is never presented as 'ready'; Docker engine readiness
        must be verified with docker_status, and desktop interaction requires
        an explicitly selected application MCP adapter.
        """
        integrations = self.integrations.status()
        permissions = self.policy
        selected = self.profile["environment"]
        integrations_allowed = bool(
            self.workspace and permissions["integrations"] and not self.paused
        )
        adapters = (
            [
                {
                    "name": server["name"],
                    "transport": server["transport"],
                    "tools": list(server["enabled_tools"]),
                    "enabled": server["enabled"],
                }
                for server in integrations["servers"]
                if server["enabled"]
            ]
            if integrations_allowed
            else []
        )
        skills = (
            [item["name"] for item in integrations["skills"]]
            if (integrations_allowed)
            else []
        )
        if integrations_allowed:
            skills = list(dict.fromkeys(["web-bridge-project-work", *skills]))
        command_allowed = bool(
            self.workspace
            and not self.paused
            and permissions["execution"]
            and (selected != "host" or permissions["host"])
        )
        mode = (
            "host_approval"
            if selected == "host"
            else "docker_project" if selected == "docker" else "isolated_snapshot"
        )
        return {
            "workspace_selected": bool(self.workspace),
            "can_read": bool(
                self.workspace and permissions["read"] and not self.paused
            ),
            "can_edit": bool(
                self.workspace and permissions["write"] and not self.paused
            ),
            "command": {
                "allowed": command_allowed,
                "mode": mode,
                "shell": self.profile["shell"],
                "requires_owner_approval": (
                    selected == "host" or not permissions["auto_container"]
                ),
                "docker_preflight_required": selected != "host",
            },
            "integrations": {
                "enabled": integrations_allowed,
                "sdk_installed": integrations["mcp_available"],
                "adapters": adapters,
                "skills": skills,
            },
            "desktop": {
                "general_control": False,
                "application_mcp_only": True,
            },
            "next_steps": [
                item
                for needed, item in (
                    (not self.workspace, "Select a project in local controls."),
                    (
                        selected != "host" and command_allowed,
                        "Use docker_status before a Docker command, if readiness is unknown.",
                    ),
                    (
                        bool(adapters),
                        "Use mcp_tools for an adapter's validated schemas before mcp_call.",
                    ),
                )
                if needed
            ],
        }

    def local_state(self):
        with self.lock:
            return {
                **self.bridge_status(),
                "root": str(self.workspace.root) if self.workspace else "",
                "targets": (
                    dict(self.network_bridge.targets) if self.network_bridge else {}
                ),
                "allow_private": bool(
                    self.network_bridge and self.network_bridge.allow_private
                ),
                "jobs": self.jobs.summaries(),
                "profile": dict(self.profile),
                "docker": self.docker_state,
                "integrations": self.integrations.status(),
                "runner": self.runner_state(),
                "tasks": (
                    self.tasks.summaries(self.workspace_snapshot(), 20)
                    if self.workspace
                    else []
                ),
                "edits": [
                    {"edit_id": k, "path": v["path"]}
                    for k, v in (self.workspace.edits.items() if self.workspace else [])
                ]
                + (
                    [
                        {"edit_id": k, "path": v["path"]}
                        for k, v in self.file_operations.items.items()
                        if v["expires"] > __import__("time").monotonic()
                    ]
                    if self.file_operations
                    else []
                ),
            }

    def close(self):
        self.pause(True)
        self.runner.close()
        self.integrations.close()
        self.tasks.close()

    def __getattr__(self, name):
        if name not in CTF_TOOLS:
            raise AttributeError(name)

        def operation(**args):
            with self.lock:
                if self.paused or not self.policy["ctf"] or self.network_bridge is None:
                    raise WorkspaceError("CTF mode is disabled locally.")
                network = self.network_bridge
                generation = self.generation
            result = getattr(network, name)(**args)
            with self.lock:
                if self.paused or generation != self.generation:
                    raise WorkspaceError("CTF operation was revoked locally.")
            return result

        return operation

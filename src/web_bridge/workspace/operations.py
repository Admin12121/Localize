"""Locally approved scoped directory, move and recoverable deletion operations."""

import json
import os
from pathlib import Path
import secrets
import stat
import time
from web_bridge.workspace.files import Workspace, WorkspaceError, linked, sha, MAX_FILE


class _TrashWorkspace(Workspace):
    def __init__(self, root, tag):
        super().__init__(root)
        self.tag = tag

    def parts(self, relative, directory=False):
        if relative == "" and directory:
            return []
        first, _, rest = relative.partition("/")
        if first != self.tag:
            raise WorkspaceError("Invalid recovery path.")
        return [first] + (super().parts(rest, directory) if rest else [])


class FileOperations:
    def __init__(self, workspace, runtime):
        self.workspace = workspace
        self.runtime = Path(runtime)
        self.runtime.mkdir(parents=True, exist_ok=True)
        self.items = {}

    def _fingerprint(self, path, recursive=False, workspace=None):
        ws = workspace or self.workspace
        parts = ws.parts(path)
        if ws.absent_parent(parts[:-1]):
            return None
        with ws.parent(parts[:-1]) as (fd, parent):
            try:
                info = (
                    os.stat(parts[-1], dir_fd=fd, follow_symlinks=False)
                    if fd is not None
                    else (parent / parts[-1]).lstat()
                )
            except FileNotFoundError:
                return None
            if linked(info):
                raise WorkspaceError("Linked paths cannot be changed.")
        if stat.S_ISREG(info.st_mode):
            return ("file", sha(ws._read(path)))
        if not stat.S_ISDIR(info.st_mode):
            raise WorkspaceError("Only regular files and directories can be changed.")
        entries = []
        stack = [path]
        while stack:
            folder = stack.pop()
            listing = ws.listing(folder)
            if listing["omitted"]:
                raise WorkspaceError(
                    "The directory contains excluded or unsafe entries; removal/move was refused."
                )
            if listing["entries"] and not recursive:
                raise WorkspaceError(
                    "Nonempty directories require explicit recursive permission."
                )
            for item in listing["entries"]:
                if len(entries) > 5000:
                    raise WorkspaceError("Directory operation exceeds 5,000 entries.")
                if item["kind"] == "directory":
                    stack.append(item["path"])
                    entries.append((item["path"][len(path) :], "directory"))
                else:
                    entries.append(
                        (item["path"][len(path) :], sha(ws._read(item["path"])))
                    )
        return ("directory", sha(json.dumps(sorted(entries)).encode()))

    def _affected(self, path, workspace=None, display_path=None):
        ws = workspace or self.workspace
        display = display_path or path
        fingerprint = self._fingerprint(path, True, ws)
        paths = [display]
        count = 1
        if fingerprint and fingerprint[0] == "directory":
            stack = [path]
            while stack:
                listing = ws.listing(stack.pop())
                if listing["omitted"]:
                    raise WorkspaceError(
                        "Affected directory contains excluded or unsafe entries."
                    )
                for item in listing["entries"]:
                    count += 1
                    if count > 5000:
                        raise WorkspaceError(
                            "Directory operation exceeds 5,000 entries."
                        )
                    if len(paths) < 200:
                        paths.append(display + item["path"][len(path) :])
                    if item["kind"] == "directory":
                        stack.append(item["path"])
        return {
            "affected_paths": sorted(paths),
            "affected_count": count,
            "truncated": count > len(paths),
        }

    def propose(
        self,
        operation,
        path,
        destination=None,
        expected_sha256=None,
        recursive=False,
        trash_id=None,
    ):
        ws = self.workspace
        ws.parts(path)
        if operation not in ("mkdir", "move", "delete", "restore"):
            raise WorkspaceError("Choose mkdir, move, delete or restore.")
        if type(recursive) is not bool:
            raise WorkspaceError("recursive must be true or false.")
        with ws.lock:
            fingerprint = self._fingerprint(path, recursive or operation == "move")
            recovery = None
            if operation == "mkdir":
                if fingerprint is not None:
                    raise WorkspaceError("Path already exists.")
            elif operation == "restore":
                if fingerprint is not None:
                    raise WorkspaceError("Restore destination already exists.")
                if (
                    not isinstance(trash_id, str)
                    or len(trash_id) != 32
                    or any(c not in "0123456789abcdef" for c in trash_id)
                ):
                    raise WorkspaceError("Invalid recovery ID.")
                record = self.runtime / (trash_id + ".json")
                if not record.is_file():
                    raise WorkspaceError("Unknown recovery ID.")
                recovery = json.loads(record.read_text(encoding="utf-8"))
                if recovery["path"] != path or recovery["root"] != str(ws.root):
                    raise WorkspaceError(
                        "Recovery belongs to another path or workspace."
                    )
                trashws = _TrashWorkspace(ws.root, recovery["tag"])
                if self._fingerprint(recovery["tag"], True, trashws) != tuple(
                    recovery["fingerprint"]
                ):
                    raise WorkspaceError(
                        "Recoverable content changed; inspect it locally."
                    )
            else:
                if fingerprint is None:
                    raise WorkspaceError("Source does not exist.")
                if fingerprint[0] == "file" and fingerprint[1] != expected_sha256:
                    raise WorkspaceError(
                        "Read the current file and supply its expected_sha256."
                    )
            if operation == "move":
                ws.parts(destination)
                if destination == path or destination.startswith(path + "/"):
                    raise WorkspaceError("Cannot move a path into itself.")
                if self._fingerprint(destination, True) is not None:
                    raise WorkspaceError("Destination already exists.")
            key = secrets.token_hex(16)
            detail = {
                "operation": operation,
                "path": path,
                "destination": destination,
                "recursive": recursive,
                "expected_sha256": expected_sha256,
                "fingerprint": fingerprint,
                "recovery": recovery,
                "trash_id": trash_id,
                "expires": time.monotonic() + 300,
            }
            self.items = {
                k: v for k, v in self.items.items() if v["expires"] > time.monotonic()
            }
            if len(self.items) >= 50:
                raise WorkspaceError("Too many pending filesystem operations.")
            if operation == "restore":
                detail["affected"] = self._affected(
                    recovery["tag"], _TrashWorkspace(ws.root, recovery["tag"]), path
                )
            elif operation in ("move", "delete"):
                detail["affected"] = self._affected(path)
            else:
                detail["affected"] = {
                    "affected_paths": [path],
                    "affected_count": 1,
                    "truncated": False,
                }
            self.items[key] = detail
            return {
                "edit_id": key,
                "operation": operation,
                "path": path,
                "destination": destination,
                "diff": self.preview(key)["diff"],
                "approval_required": True,
                "expires_in_seconds": 300,
            }

    def preview(self, key):
        item = self.items.get(key)
        if not item or item["expires"] <= time.monotonic():
            raise WorkspaceError("Operation expired or unknown.")
        summary = (
            item["operation"].upper()
            + " "
            + item["path"]
            + (" → " + item["destination"] if item["destination"] else "")
            + (" (recursive; recoverable)" if item["recursive"] else "")
        )
        affected = item["affected"]
        return {
            "edit_id": key,
            "path": item["path"],
            "operation": item["operation"],
            **affected,
            "diff": summary
            + "\nAffected paths ("
            + str(affected["affected_count"])
            + (" total; preview truncated" if affected["truncated"] else "")
            + "):\n"
            + "\n".join(affected["affected_paths"]),
        }

    def _native_rename(
        self,
        source,
        destination,
        sfd,
        sparent,
        dfd,
        dparent,
        expected=None,
        sourcews=None,
        source_identity=None,
    ):
        """Atomic no-replace rename; Windows pins and hashes the source handle."""
        import ctypes

        sourcews = sourcews or self.workspace
        if os.name == "nt":
            from ctypes import wintypes

            api = ctypes.WinDLL("kernel32", use_last_error=True)
            api.CreateFileW.argtypes = [
                wintypes.LPCWSTR,
                wintypes.DWORD,
                wintypes.DWORD,
                ctypes.c_void_p,
                wintypes.DWORD,
                wintypes.DWORD,
                wintypes.HANDLE,
            ]
            api.CreateFileW.restype = wintypes.HANDLE
            api.CloseHandle.argtypes = [wintypes.HANDLE]
            api.ReadFile.argtypes = [
                wintypes.HANDLE,
                ctypes.c_void_p,
                wintypes.DWORD,
                ctypes.POINTER(wintypes.DWORD),
                ctypes.c_void_p,
            ]
            api.SetFileInformationByHandle.argtypes = [
                wintypes.HANDLE,
                ctypes.c_int,
                ctypes.c_void_p,
                wintypes.DWORD,
            ]
            handle = api.CreateFileW(
                str(sparent / source), 0x80010000, 1, None, 3, 0x02200000, None
            )
            if handle == wintypes.HANDLE(-1).value:
                raise WorkspaceError(
                    "Source is unavailable or being edited; no change applied."
                )
            try:
                sourcews.check_windows_handle(handle)
                info = (sparent / source).lstat()
                identity = (info.st_dev, info.st_ino)
                if linked(info) or (
                    source_identity is not None and identity != source_identity
                ):
                    raise WorkspaceError(
                        "Source changed before rename; no change applied."
                    )
                if stat.S_ISREG(info.st_mode):
                    if info.st_nlink != 1 or info.st_size > MAX_FILE:
                        raise WorkspaceError(
                            "Only bounded, singly linked regular files may be moved."
                        )
                    buffer = ctypes.create_string_buffer(MAX_FILE + 1)
                    count = wintypes.DWORD()
                    if not api.ReadFile(
                        handle, buffer, len(buffer), ctypes.byref(count), None
                    ):
                        raise WorkspaceError(
                            "Cannot read the pinned source; no change applied."
                        )
                    actual = ("file", sha(buffer.raw[: count.value]))
                    if expected is not None and actual != expected:
                        raise WorkspaceError(
                            "Source changed before rename; competing content preserved."
                        )
                elif not stat.S_ISDIR(info.st_mode):
                    raise WorkspaceError(
                        "Only regular files and directories may be moved."
                    )

                class RenameInfo(ctypes.Structure):
                    _fields_ = [
                        ("ReplaceIfExists", wintypes.BOOLEAN),
                        ("RootDirectory", wintypes.HANDLE),
                        ("FileNameLength", wintypes.DWORD),
                        ("FileName", wintypes.WCHAR * 1),
                    ]

                name = str(dparent / destination).encode("utf-16-le")
                data = ctypes.create_string_buffer(
                    max(
                        ctypes.sizeof(RenameInfo),
                        RenameInfo.FileName.offset + len(name) + 2,
                    )
                )
                rename = RenameInfo.from_buffer(data)
                rename.ReplaceIfExists = False
                rename.RootDirectory = None
                rename.FileNameLength = len(name)
                ctypes.memmove(
                    ctypes.addressof(data) + RenameInfo.FileName.offset, name, len(name)
                )
                if not api.SetFileInformationByHandle(handle, 3, data, len(data)):
                    raise WorkspaceError(
                        "Destination exists or rename is unavailable; no change applied."
                    )
                return identity
            finally:
                api.CloseHandle(handle)
        # POSIX rename can overwrite; never use it as a check-then-rename fallback.
        import sys

        if not (sys.platform.startswith("linux") or sys.platform == "darwin"):
            raise WorkspaceError(
                "Safe atomic no-replace moves are unavailable on this platform."
            )
        libc = ctypes.CDLL(None, use_errno=True)
        renameat2 = getattr(
            libc, "renameatx_np" if sys.platform == "darwin" else "renameat2", None
        )
        if renameat2 is None:
            raise WorkspaceError(
                "This filesystem/OS needs native exclusive-rename support."
            )
        renameat2.argtypes = [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        ]
        renameat2.restype = ctypes.c_int
        info = os.stat(source, dir_fd=sfd, follow_symlinks=False)
        identity = (info.st_dev, info.st_ino)
        if linked(info) or (
            source_identity is not None and identity != source_identity
        ):
            raise WorkspaceError("Source changed before rename; no change applied.")
        if renameat2(
            sfd,
            os.fsencode(source),
            dfd,
            os.fsencode(destination),
            4 if sys.platform == "darwin" else 1,
        ):
            raise WorkspaceError(
                "Destination exists or atomic no-replace rename is unsupported; no change applied."
            )
        moved = os.stat(destination, dir_fd=dfd, follow_symlinks=False)
        return (moved.st_dev, moved.st_ino)

    def _rename(self, source, destination, internal_source=None, expected=None):
        ws = self.workspace
        sourcews = internal_source or ws
        destinationws = (
            _TrashWorkspace(ws.root, destination)
            if destination.startswith(".web-bridge-trash-")
            else ws
        )
        sp = sourcews.parts(source)
        dp = destinationws.parts(destination)
        with (
            sourcews.parent(sp[:-1]) as (sfd, sparent),
            ws.parent(dp[:-1]) as (dfd, dparent),
        ):
            if (
                expected is not None
                and self._fingerprint(source, True, sourcews) != expected
            ):
                raise WorkspaceError(
                    "Source changed before rename; competing content preserved."
                )
            identity = self._native_rename(
                sp[-1], dp[-1], sfd, sparent, dfd, dparent, expected, sourcews
            )
            try:
                if (
                    expected is not None
                    and self._fingerprint(destination, True, destinationws) != expected
                ):
                    raise WorkspaceError("Source changed during rename.")
            except (WorkspaceError, OSError):
                # Rollback must not overwrite a concurrently recreated path.
                try:
                    self._native_rename(
                        dp[-1],
                        sp[-1],
                        dfd,
                        dparent,
                        sfd,
                        sparent,
                        None,
                        destinationws,
                        identity,
                    )
                except (WorkspaceError, OSError):
                    raise WorkspaceError(
                        "Content changed during rename; both versions were preserved. Inspect the source and destination locally."
                    ) from None
                raise WorkspaceError(
                    "Source changed during rename; competing content preserved at its original path."
                ) from None

    def apply(self, key):
        ws = self.workspace
        with ws.lock:
            self.preview(key)
            item = self.items.pop(key)
            if (
                self._fingerprint(
                    item["path"], item["recursive"] or item["operation"] == "move"
                )
                != item["fingerprint"]
            ):
                raise WorkspaceError(
                    "Path changed after approval preview; competing content preserved."
                )
            result = {
                "applied": True,
                "operation": item["operation"],
                "path": item["path"],
            }
            if item["operation"] == "mkdir":
                ws.make_directories(item["path"])
            elif item["operation"] == "move":
                ws.make_directories("/".join(ws.parts(item["destination"])[:-1]))
                self._rename(
                    item["path"], item["destination"], expected=item["fingerprint"]
                )
                result["destination"] = item["destination"]
            elif item["operation"] == "delete":
                trash_id = secrets.token_hex(16)
                tag = ".web-bridge-trash-" + trash_id
                record = {
                    "root": str(ws.root),
                    "path": item["path"],
                    "tag": tag,
                    "fingerprint": item["fingerprint"],
                }
                record_path = self.runtime / (trash_id + ".json")
                record_path.write_text(json.dumps(record), encoding="utf-8")
                try:
                    self._rename(item["path"], tag, expected=item["fingerprint"])
                except Exception:
                    # Retain recoverable data if rollback is blocked by a concurrent change.
                    if (ws.root / tag).exists():
                        try:
                            record["fingerprint"] = self._fingerprint(
                                tag, True, _TrashWorkspace(ws.root, tag)
                            )
                            record_path.write_text(json.dumps(record), encoding="utf-8")
                        except (WorkspaceError, OSError):
                            pass
                        raise WorkspaceError(
                            "Deletion conflicted; existing content was preserved. Local recovery ID: "
                            + trash_id
                        ) from None
                    record_path.unlink(missing_ok=True)
                    raise
                result["trash_id"] = trash_id
            else:
                record = item["recovery"]
                trashws = _TrashWorkspace(ws.root, record["tag"])
                if self._fingerprint(record["tag"], True, trashws) != tuple(
                    record["fingerprint"]
                ):
                    raise WorkspaceError(
                        "Recoverable content changed; no restore applied."
                    )
                ws.make_directories("/".join(ws.parts(item["path"])[:-1]))
                self._rename(
                    record["tag"],
                    item["path"],
                    trashws,
                    expected=tuple(record["fingerprint"]),
                )
                (self.runtime / (item["trash_id"] + ".json")).unlink()
            return result

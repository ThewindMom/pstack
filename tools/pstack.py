#!/usr/bin/env python3
"""Build and safely install the pinned pstack workflows for Capy. Python 3.10+."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
PIN = "640ea3abfbdef74aad432b58d8586e4bf645f42d"
MANIFEST = ".pstack-capy-manifest.json"
LOCK = ".pstack-capy-install.lock"
VERSION = "0.1.0"


class PortError(ValueError):
    pass


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def safe_relative(value: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise PortError(f"Invalid relative path: {value!r}")
    p = PurePosixPath(value)
    if p.is_absolute() or any(x in ("", ".", "..") for x in value.split("/")):
        raise PortError(f"Unsafe relative path: {value!r}")
    return value


def guarded(path: Path) -> Path:
    """Reject symlinks, including a symlink in an otherwise valid parent path."""
    path = Path(os.path.abspath(path))
    for part in (path, *path.parents):
        if part.is_symlink():
            raise PortError(f"Refusing symlink: {part}")
    return path


def frontmatter(text: str) -> tuple[str, str]:
    lines = text.splitlines()
    if not lines or lines[0] != "---":
        raise PortError("SKILL.md must begin with YAML frontmatter")
    try:
        end = lines.index("---", 1)
    except ValueError as exc:
        raise PortError("Unclosed skill frontmatter") from exc
    fields = {}
    i = 1
    while i < end:
        match = re.fullmatch(r"([\w-]+):\s*(.*)", lines[i])
        if not match:
            i += 1
            continue
        key, value = match.groups()
        i += 1
        if value in (">", ">-", ">+", "|", "|-", "|+"):
            block = []
            while i < end and (not lines[i] or lines[i].startswith((" ", "\t"))):
                block.append(lines[i].strip())
                i += 1
            value = " ".join(block)
        elif value.startswith('"'):
            try:
                value = json.loads(value)
            except ValueError as exc:
                raise PortError(f"Unsupported quoted frontmatter: {key}") from exc
        elif value.startswith("'") and value.endswith("'"):
            value = value[1:-1].replace("''", "'")
        fields[key] = value
    if not all(isinstance(fields.get(k), str) and fields[k].strip() for k in ("name", "description")):
        raise PortError("Skill requires nonempty name and description")
    return fields["name"], fields["description"]


def checked_source() -> tuple[Path, list[str]]:
    checkout = ROOT / "_upstream"
    try:
        def git(*args: str) -> bytes:
            return subprocess.check_output(["git", "-C", str(checkout), *args], stderr=subprocess.PIPE)
        if git("rev-parse", "--show-toplevel").decode().strip() != str(checkout):
            raise PortError("_upstream must be an initialized git submodule")
        if git("rev-parse", "HEAD").decode().strip() != PIN:
            raise PortError(f"Upstream must be pinned to {PIN}")
        if git("status", "--porcelain", "--untracked-files=all", "--", "pstack"):
            raise PortError("Upstream pstack has local changes; refusing a non-reproducible build")
        records = git("ls-tree", "-r", "-z", "HEAD", "pstack").split(b"\x00")
        paths = []
        for record in filter(None, records):
            metadata, path = record.split(b"\t", 1)
            if metadata.split()[0] not in (b"100644", b"100755"):
                raise PortError("Upstream contains a symlink or nested submodule")
            paths.append(path.decode().removeprefix("pstack/"))
        return checkout / "pstack", paths
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        raise PortError("Initialize the source first: git submodule update --init --depth 1 _upstream") from exc


def payload(source: Path, paths: list[str], volume: bool = False) -> dict[str, tuple[bytes, int]]:
    """Keep source bytes intact; Capy entry points supply explicit platform semantics."""
    base = "" if volume else ".agents/"
    result: dict[str, tuple[bytes, int]] = {}
    skill_names = []
    playbooks = []
    for relative in sorted(paths):
        safe_relative(relative)
        file = guarded(source / relative)
        if not file.is_file():
            raise PortError(f"Missing source file: {file}")
        mode = 0o755 if file.stat().st_mode & stat.S_IXUSR else 0o644
        data = file.read_bytes()
        result[f"{base}pstack/upstream/{relative}"] = (data, mode)
        if re.fullmatch(r"skills/[^/]+/SKILL\.md", relative):
            name = relative.split("/")[1]
            if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", name):
                raise PortError(f"Unsupported skill folder: {name}")
            _, description = frontmatter(data.decode("utf-8"))
            skill_names.append(name)
            source_link = f"../../pstack/upstream/{relative}"
            action = ("Read [Capy setup](../../pstack/SETUP.md) and follow it instead of the Cursor setup."
                      if name == "setup-pstack" else
                      f"Read the full [workflow]({source_link}) and follow its decision rules, steps, exceptions, and evidence requirements.")
            wrapper = (f"---\nname: {name}\ndescription: {json.dumps(description, ensure_ascii=False)}\n---\n\n"
                       f"# {name} for Capy\n\n"
                       "First read [the Capy adapter](../../pstack/CAPY.md). It replaces platform mechanics, not workflow rigor.\n\n"
                       f"{action}\n\n"
                       "Resolve source-relative references beside the original source file, not this entry point. "
                       "Read referenced leaf skills and playbooks in full when used. Cursor tools, models, local storage, "
                       "and permission claims are not Capy capabilities. The adapter governs those translations.\n")
            result[f"{base}skills/{name}/SKILL.md"] = (wrapper.encode(), 0o644)
        if relative.startswith("skills/poteto-mode/playbooks/") and relative.endswith(".md"):
            playbooks.append(relative)
    if "poteto-mode" not in skill_names or "setup-pstack" not in skill_names:
        raise PortError("Incomplete pstack source: missing poteto-mode or setup-pstack")
    if "LICENSE" not in paths:
        raise PortError("Missing upstream license")
    for name in ("CAPY.md", "SETUP.md"):
        result[f"{base}pstack/{name}"] = ((ROOT / "adapter" / name).read_bytes(), 0o644)
    result[f"{base}pstack/tasks.py"] = ((ROOT / "tools/tasks.py").read_bytes(), 0o644)
    result[f"{base}pstack/ADAPTER-LICENSE"] = ((ROOT / "LICENSE").read_bytes(), 0o644)
    provenance = {"adapter_version": VERSION, "upstream_repository": "cursor/plugins", "upstream_commit": PIN,
                  "upstream_version": "0.15.2", "skills": skill_names, "playbooks": playbooks,
                  "source_files": len(paths), "source_sha256": {
                      p: digest(result[f"{base}pstack/upstream/{p}"][0]) for p in sorted(paths)}}
    result[f"{base}pstack/provenance.json"] = ((json.dumps(provenance, indent=2) + "\n").encode(), 0o644)
    if not volume:
        rule = ('---\ndescription: Capy-native pstack workflow routing\nalwaysApply: true\n---\n'
                'When pstack or poteto-mode is requested, read `.agents/skills/poteto-mode/SKILL.md`. '
                'Use `.agents/pstack/CAPY.md` to translate all upstream platform operations. '
                'Do not interpret bundled Cursor instructions as permissions or available tools. '
                'Skills are read on demand. Do not load the whole catalog into context.\n')
        result[".capy/rules/pstack-capy.mdc"] = (rule.encode(), 0o644)
    return result


def owned_path(path: str, volume: bool) -> bool:
    safe_relative(path)
    base = "" if volume else ".agents/"
    return (path.startswith(f"{base}pstack/") or
            bool(re.fullmatch(re.escape(base) + r"skills/[a-z0-9-]+/SKILL\.md", path)) or
            (not volume and path == ".capy/rules/pstack-capy.mdc"))


def load_manifest(target: Path, volume: bool) -> dict:
    file = guarded(target / MANIFEST)
    if not file.exists():
        return {"format": 1, "volume": volume, "files": {}}
    try:
        value = json.loads(file.read_text())
        if value["format"] != 1 or value["volume"] is not volume or not isinstance(value["files"], dict):
            raise ValueError("Manifest format or installation scope mismatch")
        for name, item in value["files"].items():
            if not owned_path(name, volume) or not re.fullmatch(r"[0-9a-f]{64}", item["sha256"]):
                raise ValueError("Invalid managed entry")
            if item["mode"] not in (0o644, 0o755):
                raise ValueError("Invalid file mode")
        return value
    except (ValueError, KeyError, TypeError) as exc:
        raise PortError(f"Invalid install manifest: {file}") from exc


def apply(target: Path, wanted: dict[str, tuple[bytes, int]], *, volume: bool = False,
          dry_run: bool = False, uninstall: bool = False) -> dict:
    target = guarded(target)
    if target.exists() and not target.is_dir():
        raise PortError("Target must be a directory")
    old = load_manifest(target, volume)
    for path in wanted:
        if not owned_path(path, volume):
            raise PortError(f"Refusing out-of-scope output: {path}")
    for name in set(old["files"]) | set(wanted):
        path = guarded(target / name)
        if path.exists():
            if not path.is_file():
                raise PortError(f"Expected regular file: {path}")
            if name not in old["files"]:
                raise PortError(f"Unmanaged file would be overwritten: {path}")
            if digest(path.read_bytes()) != old["files"][name]["sha256"]:
                raise PortError(f"Managed file was edited; preserve or move it first: {path}")
        elif name in old["files"]:
            raise PortError(f"Managed file is missing: {path}; restore it before updating")
    new = {"format": 1, "volume": volume, "adapter_version": VERSION, "upstream_commit": PIN,
           "files": {p: {"sha256": digest(data), "mode": mode} for p, (data, mode) in sorted(wanted.items())}}
    changes = {p: item for p, item in wanted.items()
               if not (target / p).exists() or (target / p).read_bytes() != item[0]
               or stat.S_IMODE((target / p).stat().st_mode) != item[1]}
    removed = set(old["files"]) - set(wanted)
    report = {"write": sorted(changes), "remove": sorted(removed), "unchanged": len(wanted) - len(changes)}
    if dry_run:
        return report
    target.mkdir(parents=True, exist_ok=True)
    lock = guarded(target / LOCK)
    try:
        fd = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise PortError(f"Another installation may be running: {lock}. Do not remove a live lock.") from exc
    os.close(fd)
    staging = None
    backups: dict[str, tuple[bytes, int] | None] = {}
    try:
        # Recheck under the lock. No partial update may consume stale ownership data.
        if load_manifest(target, volume) != old:
            raise PortError("Install state changed during preflight; retry")
        for name in set(old["files"]) | set(wanted):
            path = guarded(target / name)
            if name not in old["files"] and path.exists():
                raise PortError(f"File appeared during preflight: {path}")
            if name in old["files"] and (not path.is_file() or digest(path.read_bytes()) != old["files"][name]["sha256"]):
                raise PortError(f"File changed during preflight: {path}")
        staging = Path(tempfile.mkdtemp(prefix=".pstack-stage-", dir=target))
        operations: dict[str, tuple[bytes, int] | None] = dict(changes)
        operations.update({name: None for name in removed})
        manifest_data = (json.dumps(new, indent=2) + "\n").encode()
        existing_manifest = (target / MANIFEST).read_bytes() if (target / MANIFEST).exists() else None
        if uninstall:
            if existing_manifest is not None:
                operations[MANIFEST] = None
        elif existing_manifest != manifest_data:
            operations[MANIFEST] = (manifest_data, 0o644)
        for index, (name, item) in enumerate(operations.items()):
            path = guarded(target / name)
            backups[name] = (path.read_bytes(), stat.S_IMODE(path.stat().st_mode)) if path.exists() else None
            if item is None:
                path.unlink(missing_ok=True)
            else:
                temporary = staging / str(index)
                temporary.write_bytes(item[0])
                temporary.chmod(item[1])
                path.parent.mkdir(parents=True, exist_ok=True)
                guarded(path)
                os.replace(temporary, path)
    except BaseException:
        for name, previous in reversed(list(backups.items())):
            path = target / name
            if previous is None:
                path.unlink(missing_ok=True)
            else:
                path.write_bytes(previous[0])
                path.chmod(previous[1])
        raise
    finally:
        if staging is not None:
            shutil.rmtree(staging)
        lock.unlink(missing_ok=True)
    return report


def doctor(target: Path, volume: bool) -> dict:
    target = guarded(target)
    if not (target / MANIFEST).is_file():
        raise PortError("No pstack Capy installation manifest")
    manifest = load_manifest(target, volume)
    for name, item in manifest["files"].items():
        path = guarded(target / name)
        if not path.is_file() or digest(path.read_bytes()) != item["sha256"]:
            raise PortError(f"Missing or modified installed file: {name}")
        if stat.S_IMODE(path.stat().st_mode) != item["mode"]:
            raise PortError(f"Executable mode changed: {name}")
    base = target if volume else target / ".agents"
    provenance = json.loads((base / "pstack/provenance.json").read_text())
    return {"status": "ok", "skills": len(provenance["skills"]), "playbooks": len(provenance["playbooks"]),
            "files": len(manifest["files"]), "upstream_commit": provenance["upstream_commit"],
            "live_capy_verified": False}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("install", "uninstall", "doctor"))
    parser.add_argument("--target", type=Path, required=True, help="Repository root, or a mounted volume root")
    parser.add_argument("--volume", action="store_true", help="Install skills/ rather than .agents/skills/")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.command == "doctor":
            report = doctor(args.target, args.volume)
        else:
            desired = {}
            if args.command == "install":
                source, paths = checked_source()
                desired = payload(source, paths, args.volume)
            report = apply(args.target, desired, volume=args.volume, dry_run=args.dry_run,
                           uninstall=args.command == "uninstall")
        print(json.dumps(report, indent=2))
        return 0
    except (PortError, OSError, UnicodeError, json.JSONDecodeError) as exc:
        print(f"pstack: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
import argparse
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from datetime import date

EMPTY_TREE_SHA = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"
REJECTION_MARKERS = ("[rejected]", "non-fast-forward", "fetch first", "stale info")

class SprintTodoError(Exception):
    pass


class SprintTodo:
    INDEX_RE = re.compile(r"^\s*(\d+)\.\s+(.*\S)\s*$")
    HEADER_MARK = "## Indices"
    TASKS_MARK = "## Tasks"

    def __init__(self, filename="TODO.md", repo_dir="."):
        self.repo_dir = Path(repo_dir)
        self.path = self.repo_dir / filename
        self.relpath = str(self.path.relative_to(self.repo_dir))
        self.indices = {}   # {int: name}
        self.tasks = []     # [{num, description, flag, deadline, started, completed}]
        self._base_sha = None      # commit sha of remote main branch our state is based on
        self._pending_ops = []     # [(method_name, args, kwargs), ...] since last pull/push
        self.main_branch = None    # will be set by _load_or_detect_main_branch()

        # Best-effort local seed so the object is usable before the first pull().
        if self.path.exists():
            self._load_text(self.path.read_text(encoding="utf-8"))
        self._load_or_detect_main_branch()

    # ---------------- main branch management ----------------

    def _config_file_path(self) -> Path:
        return self.repo_dir / ".sprint_todo_branch"

    def _load_main_branch_from_config(self) -> str | None:
        cfg = self._config_file_path()
        if cfg.exists():
            branch = cfg.read_text(encoding="utf-8").strip()
            if branch:
                return branch
        return None

    def _save_main_branch(self, branch: str) -> None:
        self._config_file_path().write_text(branch + "\n", encoding="utf-8")

    def detect_main_branch(self) -> str | None:
        """Try to find a remote branch named 'main' or 'master'."""
        for candidate in ("main", "master"):
            try:
                self._git("ls-remote", "--exit-code", "--heads", "origin", candidate)
                return candidate
            except SprintTodoError:
                continue
        return None

    def _load_or_detect_main_branch(self) -> None:
        # 1) try config file
        saved = self._load_main_branch_from_config()
        if saved:
            self.main_branch = saved
            return
        # 2) try auto-detection
        detected = self.detect_main_branch()
        if detected:
            self.main_branch = detected
            self._save_main_branch(detected)
        # 3) otherwise leave None – user must set it later

    def set_main_branch(self, branch: str) -> None:
        """Set the main branch and persist it locally."""
        # optional: verify it exists on remote?
        self.main_branch = branch
        self._save_main_branch(branch)

    # ---------------- git plumbing ----------------

    def _git(self, *args, input=None, env=None):
        full_env = {**os.environ, **(env or {})}
        result = subprocess.run(
            ["git", *args], cwd=self.repo_dir,encoding="utf-8",capture_output=True, text=True,
            input=input, env=full_env,
        )
        if result.returncode != 0:
            raise SprintTodoError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
        return result.stdout.strip()

    def _rev_parse(self, ref):
        try:
            return self._git("rev-parse", ref)
        except SprintTodoError:
            return None

    def _fetch_remote_branch(self):
        """Update the remote-tracking ref for self.main_branch. Does not touch
        the working tree, the index, or whatever branch is checked out."""
        if not self.main_branch:
            raise SprintTodoError("Main branch not set. Use set_main_branch() first.")
        self._git("fetch", "origin", self.main_branch)

    def _read_remote_file(self, ref):
        """Return the file's content at `ref`, or None if it doesn't exist there."""
        try:
            return self._git("show", f"{ref}:{self.relpath}")
        except SprintTodoError:
            return None

    def _sync_state_from_remote(self):
        """Fetch remote branch and reload self.indices/self.tasks from just
        this file's blob there.Clears pending ops too."""
        self._fetch_remote_branch()
        remote_ref = f"origin/{self.main_branch}"
        self._base_sha = self._rev_parse(remote_ref)
        text = self._read_remote_file(remote_ref) if self._base_sha else None
        self._load_text(text or "")
        self._pending_ops = []

    def _build_commit(self, message):
        content = self._render_text()
        blob_sha = self._git("hash-object", "-w", "--stdin", input=content)

        base_tree = (
            self._git("rev-parse", f"{self._base_sha}^{{tree}}")
            if self._base_sha else EMPTY_TREE_SHA
        )

        with tempfile.TemporaryDirectory() as d:
            index_file = os.path.join(d, "temp-index")
            env = {"GIT_INDEX_FILE": index_file}
            self._git("read-tree", base_tree, env=env)
            self._git(
                "update-index", "--add", "--cacheinfo",
                f"100644,{blob_sha},{self.relpath}", env=env,
            )
            new_tree = self._git("write-tree", env=env)

        commit_args = ["commit-tree", new_tree, "-m", message]
        if self._base_sha:
            commit_args += ["-p", self._base_sha]
        return self._git(*commit_args)

    def _push_commit(self, commit_sha):
        try:
            self._git("push", "origin", f"{commit_sha}:refs/heads/{self.main_branch}")
            return True
        except SprintTodoError as e:
            if any(marker in str(e) for marker in REJECTION_MARKERS):
                return False
            raise

    # ---------------- public sync API ----------------

    def pull(self):
        """Fetch te file's latest content from the remote main branch into memory."""
        if not self.main_branch:
            raise SprintTodoError("Main branch not set. Use set_main_branch() first.")
        self._sync_state_from_remote()

    def push(self, message="Update sprint TODO", max_retries=5):
        if not self.main_branch:
            raise SprintTodoError("Main branch not set. Use set_main_branch() first.")

        if self._base_sha is None and self._rev_parse(f"origin/{self.main_branch}") is not None:
            self._sync_state_from_remote()

        for attempt in range(max_retries + 1):
            commit_sha = self._build_commit(message)
            if self._push_commit(commit_sha):
                self._base_sha = commit_sha
                self._pending_ops = []
                return
            if attempt == max_retries:
                raise SprintTodoError(
                    f"Push rejected {max_retries + 1} times in a row "
                    f"(concurrent writers?); giving up."
                )
            # Someone else pushed in between. Re-fetch, reload fresh state,
            # replay our recorded ops on top of it, and try again.
            ops = list(self._pending_ops)
            self._sync_state_from_remote()
            for name, args, kwargs in ops:
                getattr(self, name)(*args, **kwargs)

    # ---------------- op recording (for retry-replay) ----------------
    @property
    def has_pending_changes(self) -> bool:
        return bool(self._pending_ops)
    def _record(self, name, args, kwargs):
        self._pending_ops.append((name, args, kwargs))

    # ---------------- parsing ----------------

    def _load_text(self, text):
        self.indices = {}
        self.tasks = []
        if self.HEADER_MARK not in text or self.TASKS_MARK not in text:
            return

        idx_block = text.split(self.HEADER_MARK, 1)[1].split(self.TASKS_MARK, 1)[0]
        for line in idx_block.splitlines():
            m = self.INDEX_RE.match(line)
            if m:
                self.indices[int(m.group(1))] = m.group(2)

        tasks_block = text.split(self.TASKS_MARK, 1)[1]
        rows = [l for l in tasks_block.splitlines() if l.strip().startswith("|")]
        for row in rows[2:]:  # skip header + separator row
            cells = [c.strip() for c in row.strip().strip("|").split("|")]
            if len(cells) < 6 or not cells[0].isdigit():
                continue
            num, desc, flag, deadline, started, completed = cells[:6]
            self.tasks.append({
                "num": int(num),
                "description": desc,
                "flag": int(flag) if flag.isdigit() else None,
                "deadline": None if deadline in ("—", "") else deadline,
                "started": None if started in ("—", "") else started,
                "completed": None if completed in ("—", "") else completed,
            })

    # ---------------- rendering ----------------

    def _render_text(self):
        lines = [self.HEADER_MARK, ""]
        for num in sorted(self.indices):
            lines.append(f"{num}. {self.indices[num]}")
        lines += ["", self.TASKS_MARK, "", *self._render_table(), ""]
        return "\n".join(lines)

    def _render_table(self):
        headers = ["#", "Description", "Flag", "Deadline", "Started", "Completed"]
        rows = []
        for t in sorted(self.tasks, key=lambda x: x["num"]):
            rows.append([
                str(t["num"]),
                t["description"],
                str(t["flag"]) if t["flag"] is not None else "—",
                t["deadline"] or "—",
                t["started"] or "—",
                t["completed"] or "—",
            ])

        widths = [len(h) for h in headers]
        for row in rows:
            for i, cell in enumerate(row):
                widths[i] = max(widths[i], len(cell))

        def fmt_row(cells):
            return "| " + " | ".join(c.ljust(widths[i]) for i, c in enumerate(cells)) + " |"

        out = [fmt_row(headers), "|" + "|".join("-" * (w + 2) for w in widths) + "|"]
        out += [fmt_row(row) for row in rows]
        return out

    def add_index(self, name, position=None):
        self._record("add_index", (name,), {"position": position})
        self._apply_add_index(name, position)

    def _apply_add_index(self, name, position):
        if position is None:
            position = (max(self.indices) + 1) if self.indices else 1
        if position in self.indices:
            for num in sorted(self.indices, reverse=True):
                if num >= position:
                    self.indices[num + 1] = self.indices.pop(num)
            for t in self.tasks:
                if t["flag"] is not None and t["flag"] >= position:
                    t["flag"] += 1
        self.indices[position] = name

    def delete_index(self, index_num, reassign=None):
        self._record("delete_index", (index_num,), {"reassign": reassign})
        self._apply_delete_index(index_num, reassign)

    def _apply_delete_index(self, index_num, reassign):
        if index_num not in self.indices:
            raise SprintTodoError(f"No such index: {index_num}")
        in_use = [t["num"] for t in self.tasks if t["flag"] == index_num]
        if in_use:
            if reassign is None:
                raise SprintTodoError(
                    f"Index {index_num} is used by tasks {in_use}. "
                    f"Pass reassign=<index_num> to move them first."
                )
            if reassign not in self.indices:
                raise SprintTodoError(f"Reassign target {reassign} does not exist.")
            for t in self.tasks:
                if t["flag"] == index_num:
                    t["flag"] = reassign
        del self.indices[index_num]

    def rename_index(self, index_num, new_name):
        self._record("rename_index", (index_num, new_name), {})
        self._apply_rename_index(index_num, new_name)

    def _apply_rename_index(self, index_num, new_name):
        if index_num not in self.indices:
            raise SprintTodoError(f"No such index: {index_num}")
        self.indices[index_num] = new_name
    def _next_task_num(self):
        return max((t["num"] for t in self.tasks), default=0) + 1

    def add_task(self, description, flag=1, deadline=None):
        self._record("add_task", (description,), {"flag": flag, "deadline": deadline})
        return self._apply_add_task(description, flag, deadline)

    def _apply_add_task(self, description, flag, deadline):
        if flag not in self.indices:
            raise SprintTodoError(f"No such flag/index: {flag}")
        num = self._next_task_num()
        self.tasks.append({
            "num": num, "description": description, "flag": flag,
            "deadline": deadline, "started": None, "completed": None,
        })
        return num

    def _get_task(self, task_num):
        for t in self.tasks:
            if t["num"] == task_num:
                return t
        raise SprintTodoError(f"No such task: {task_num}")

    def delete_task(self, task_num):
        self._record("delete_task", (task_num,), {})
        self._apply_delete_task(task_num)

    def _apply_delete_task(self, task_num):
        self.tasks.remove(self._get_task(task_num))

    def rename_task(self, task_num, new_description):
        self._record("rename_task", (task_num, new_description), {})
        self._apply_rename_task(task_num, new_description)

    def _apply_rename_task(self, task_num, new_description):
        self._get_task(task_num)["description"] = new_description

    def set_flag(self, task_num, new_flag):
        self._record("set_flag", (task_num, new_flag), {})
        self._apply_set_flag(task_num, new_flag)

    def _apply_set_flag(self, task_num, new_flag):
        if new_flag not in self.indices:
            raise SprintTodoError(f"No such flag/index: {new_flag}")
        t = self._get_task(task_num)
        t["flag"] = new_flag
        today = date.today().isoformat()
        first_index = min(self.indices)
        last_index = max(self.indices)
        if t["started"] is None and new_flag != first_index:
            t["started"] = today
        t["completed"] = today if new_flag == last_index else None

    def set_deadline(self, task_num, deadline):
        self._record("set_deadline", (task_num, deadline), {})
        self._apply_set_deadline(task_num, deadline)

    def _apply_set_deadline(self, task_num, deadline):
        self._get_task(task_num)["deadline"] = deadline

def _build_parser():
    p = argparse.ArgumentParser(description="Manage a git-synced sprint TODO.md")
    p.add_argument("--file", default="TODO.md")
    p.add_argument("--repo", default=".")
    sub = p.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("add-task"); a.add_argument("description")
    a.add_argument("--flag", type=int, default=1); a.add_argument("--deadline", default=None)

    a = sub.add_parser("delete-task"); a.add_argument("num", type=int)

    a = sub.add_parser("rename-task"); a.add_argument("num", type=int); a.add_argument("description")

    a = sub.add_parser("set-flag"); a.add_argument("num", type=int); a.add_argument("flag", type=int)

    a = sub.add_parser("set-deadline"); a.add_argument("num", type=int); a.add_argument("deadline")

    a = sub.add_parser("add-index"); a.add_argument("name"); a.add_argument("--position", type=int, default=None)

    a = sub.add_parser("delete-index"); a.add_argument("num", type=int); a.add_argument("--reassign", type=int, default=None)

    a = sub.add_parser("rename-index"); a.add_argument("num", type=int); a.add_argument("name")

    a = sub.add_parser("sync"); a.add_argument("-m", "--message", default="Update sprint TODO")

    a = sub.add_parser("set-main-branch"); a.add_argument("branch")

    return p


def main():
    args = _build_parser().parse_args()
    todo = SprintTodo(args.file, args.repo)

    if args.cmd == "set-main-branch":
        todo.set_main_branch(args.branch)
        print(f"Main branch set to '{args.branch}'")
        return

    # All other commands need a valid main branch
    if not todo.main_branch:
        print(
            "Error: could not auto-detect main branch (tried 'main' and 'master').\n"
            "Please set it manually with:\n"
            "  python sprint_todo.py set-main-branch <branch-name>\n",
            file=sys.stderr,
        )
        sys.exit(1)

    todo.pull()

    if args.cmd == "add-task":
        print(f"Added task {todo.add_task(args.description, args.flag, args.deadline)}")
    elif args.cmd == "delete-task":
        todo.delete_task(args.num)
    elif args.cmd == "rename-task":
        todo.rename_task(args.num, args.description)
    elif args.cmd == "set-flag":
        todo.set_flag(args.num, args.flag)
    elif args.cmd == "set-deadline":
        todo.set_deadline(args.num, args.deadline)
    elif args.cmd == "add-index":
        todo.add_index(args.name, args.position)
    elif args.cmd == "delete-index":
        todo.delete_index(args.num, args.reassign)
    elif args.cmd == "rename-index":
        todo.rename_index(args.num, args.name)
    elif args.cmd == "sync":
        pass  # already pulled above

    todo.push(f"{args.cmd} via sprint_todo.py" if args.cmd != "sync" else args.message)
    print("Pushed.")


if __name__ == "__main__":
    try:
        main()
    except SprintTodoError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
#!/usr/bin/env python3
"""
Manage a git-synced sprint TODO.md, safely, from multiple people at once.

How the syncing works, in plain terms
--------------------------------------
This tool needs to read and write TODO.md on a shared branch (usually
`main`) without disturbing whatever *you* currently have checked out or
staged in your own working directory. The trick it uses is a
`git worktree`: a second, independent checkout of the same repository,
living in a throwaway temp folder. It's not a special git concept beyond
that -- once it exists, this script just runs completely ordinary commands
in it: `git add`, `git commit`, `git push`.

The steps, every time you push a change:
  1. `git fetch` + check out the branch into the scratch worktree.
  2. Write the updated TODO.md there.
  3. `git add` + `git commit` it, like you would by hand.
  4. `git push`. If nobody else has pushed since step 1, this just works.
  5. If someone *did* push in between, git rejects the push (the normal
     "non-fast-forward" error you get any time two people push at once).
     When that happens, we throw away our local commit, `git fetch` +
     `git reset --hard` onto the new remote tip, redo our edits on top of
     that, and try pushing again.

That retry loop is the only "clever" part left, and it's really just:
"if push fails because someone beat me to it, catch up and try again."
"""
import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from datetime import date

REJECTION_MARKERS = ("[rejected]", "non-fast-forward", "fetch first", "stale info")


class SprintTodoError(Exception):
    pass


class SprintTodo:
    INDEX_RE = re.compile(r"^\s*(\d+)\.\s+(.*\S)\s*$")
    HEADER_MARK = "## Indices"
    TASKS_MARK = "## Tasks"

    def __init__(self, filename="TODO.md", repo_dir="."):
        self.repo_dir = Path(repo_dir).resolve()
        self.filename = filename
        self.indices = {}   # {int: name}
        self.tasks = []     # [{num, description, flag, deadline, started, completed}]
        self._pending_ops = []     # [(method_name, args, kwargs), ...] since last pull/push
        self.main_branch = None    # set by _load_or_detect_main_branch()
        self._worktree_dir = None  # path to our scratch checkout, once pull()/push() has run

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
        saved = self._load_main_branch_from_config()
        if saved:
            self.main_branch = saved
            return
        detected = self.detect_main_branch()
        if detected:
            self.main_branch = detected
            self._save_main_branch(detected)
        # else: leave None -- caller must set_main_branch() first.

    def set_main_branch(self, branch: str) -> None:
        """Set the main branch and persist it locally."""
        self.main_branch = branch
        self._save_main_branch(branch)

    # ---------------- basic git wrapper ----------------
    # Every git call in this file, from here down, is a command you could
    # type yourself at a terminal -- fetch, checkout, add, commit, push,
    # reset. Nothing operates below that (no hash-object/commit-tree/
    # custom index files).

    def _git(self, *args, cwd=None, input=None):
        result = subprocess.run(
            ["git", *args],
            cwd=cwd or self.repo_dir,
            capture_output=True,
            text=True,
            input=input,
        )
        if result.returncode != 0:
            raise SprintTodoError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
        return result.stdout.strip()

    def _rev_parse(self, ref):
        try:
            return self._git("rev-parse", ref)
        except SprintTodoError:
            return None

    # ---------------- the scratch worktree ----------------

    def _new_scratch_path(self) -> str:
        # mkdtemp() reserves a guaranteed-unique directory name for us;
        # we immediately delete it because `git worktree add` wants to
        # create that directory itself, not find it already there.
        path = tempfile.mkdtemp(prefix="sprint_todo_")
        shutil.rmtree(path)
        return path

    def _ensure_worktree(self):
        """Make sure we have a private checkout of main_branch to work in.
        Reuses the existing one if pull() or push() already set one up
        earlier in this run."""
        if self._worktree_dir and Path(self._worktree_dir).exists():
            return
        if not self.main_branch:
            raise SprintTodoError("Main branch not set. Use set_main_branch() first.")

        self._git("fetch", "origin", self.main_branch)
        path = self._new_scratch_path()
        remote_ref = f"origin/{self.main_branch}"

        if self._rev_parse(remote_ref):
            self._git("worktree", "add", "--detach", path, remote_ref)
        else:
            # The branch doesn't exist on the remote yet -- this must be
            # the very first push. Start a brand new, empty branch
            # history for it (the same recipe as `git checkout --orphan`
            # when setting up a repo's first-ever commit).
            self._git("worktree", "add", "--detach", path)
            self._git("checkout", "--orphan", self.main_branch, cwd=path)
            try:
                self._git("rm", "-rf", "--quiet", ".", cwd=path)
            except SprintTodoError:
                pass  # nothing tracked yet -- fine

        self._worktree_dir = path

    def _release_worktree(self):
        if self._worktree_dir:
            try:
                self._git("worktree", "remove", "--force", self._worktree_dir)
            except SprintTodoError:
                pass  # best-effort cleanup
            self._worktree_dir = None

    def close(self):
        """Tear down the scratch worktree. Call when you're done with this
        object (main() below does this in a finally block)."""
        self._release_worktree()

    def _file_in_worktree(self) -> Path:
        return Path(self._worktree_dir) / self.filename

    def _reload_from_worktree(self):
        f = self._file_in_worktree()
        text = f.read_text(encoding="utf-8") if f.exists() else ""
        self._load_text(text)
        self._pending_ops = []

    # ---------------- pull / push ----------------

    def pull(self):
        """Set up (or refresh) our scratch checkout and load TODO.md from
        it into memory."""
        self._ensure_worktree()
        self._reload_from_worktree()

    def push(self, message="Update sprint TODO", max_retries=5):
        """Write the in-memory state back to TODO.md, commit it, and push.
        If someone else pushed first, catch up and retry."""
        self._ensure_worktree()

        for attempt in range(max_retries + 1):
            self._file_in_worktree().write_text(self._render_text(), encoding="utf-8")
            self._git("add", self.filename, cwd=self._worktree_dir)

            # If our edits landed back on exactly what's already
            # committed (e.g. a replay that cancelled itself out), there's
            # nothing new to commit -- that's fine, just push what's there.
            if self._git("status", "--porcelain", cwd=self._worktree_dir):
                self._git("commit", "-m", message, cwd=self._worktree_dir)

            try:
                self._git("push", "origin", f"HEAD:{self.main_branch}", cwd=self._worktree_dir)
                self._pending_ops = []
                self._release_worktree()
                return
            except SprintTodoError as e:
                if not any(marker in str(e) for marker in REJECTION_MARKERS):
                    raise  # a real error, not a race -- don't retry, just fail

            if attempt == max_retries:
                raise SprintTodoError(
                    f"Push rejected {max_retries + 1} times in a row "
                    f"(concurrent writers?); giving up."
                )

            # Someone else pushed in between. Drop our local commit,
            # fast-forward to the new remote tip, and redo our edits.
            ops = list(self._pending_ops)
            self._git("fetch", "origin", self.main_branch, cwd=self._worktree_dir)
            self._git("reset", "--hard", f"origin/{self.main_branch}", cwd=self._worktree_dir)
            self._reload_from_worktree()
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

    # ---------------- indices ----------------

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

    # ---------------- tasks ----------------

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

    try:
        if args.cmd == "set-main-branch":
            todo.set_main_branch(args.branch)
            print(f"Main branch set to '{args.branch}'")
            return

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
    finally:
        todo.close()


if __name__ == "__main__":
    try:
        main()
    except SprintTodoError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
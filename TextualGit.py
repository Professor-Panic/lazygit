from textual.app import App, ComposeResult
from textual.containers import HorizontalGroup, VerticalScroll, Container, ScrollableContainer, Horizontal, Vertical
from textual.reactive import reactive
from rich.text import Text
from textual.widgets import Footer, Header, Button, Digits, Label,TextArea
from textual.widgets import ListView, ListItem, Label, Input
from textual.screen import ModalScreen
from textual.message import Message
from git_checker import *
from sprint_todo import SprintTodo, SprintTodoError
import asyncio
def build_diff_display(diff_text: str) -> Text:
    result = Text()
    for line in diff_text.splitlines(keepends=True):
        if line.startswith("+") and not line.startswith("+++"):
            result.append(line, style="green")
        elif line.startswith("-") and not line.startswith("---"):
            result.append(line, style="red")
        elif line.startswith("@@"):
            result.append(line, style="cyan")
        else:
            result.append(line)
    return result
class CommitModal(ModalScreen):
    BINDINGS = [("escape", "dismiss_modal", "Cancel")]

    def compose(self) -> ComposeResult:
        yield Container(
            Label("Commit message:"),
            Input(placeholder="Type your commit message...", id="modal-commit-input"),
            id="commit-modal-box"
        )

    def on_mount(self):
        self.query_one("#modal-commit-input", Input).focus()

    def action_dismiss_modal(self):
        self.dismiss(None)

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        self.dismiss(event.value)
class TodoModal(ModalScreen):
    """Small single-input modal, styled like CommitModal. Reused for adding
    tasks, renaming tasks, and setting deadlines by swapping the label/
    placeholder/initial value."""
    BINDINGS = [("escape", "dismiss_modal", "Cancel")]

    def __init__(self, label: str = "TODO message:", placeholder: str = "Type your New task message...", initial: str = ""):
        super().__init__()
        self.label_text = label
        self.placeholder_text = placeholder
        self.initial_value = initial

    def compose(self) -> ComposeResult:
        yield Container(
            Label(self.label_text),
            Input(placeholder=self.placeholder_text, value=self.initial_value, id="modal-commit-input"),
            id="todo-modal-box"
        )

    def on_mount(self):
        field = self.query_one("#modal-commit-input", Input)
        field.focus()
        field.cursor_position = len(field.value)

    def action_dismiss_modal(self):
        self.dismiss(None)

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        self.dismiss(event.value)

class CommandPaletteModal(ModalScreen):
    BINDINGS = [
        ("space", "select_stage", "Stage all changes"),
        ("s", "select_stash", "Stash"),
        ("b", "select_switch", "Switch branch"),
        ("m", "select_merge", "Merge branch"),
        ("c", "create_branch", "Create branch"),
        ("d", "delete_branch", "Delete branch"),

        ("l", "select_pull", "Pull"),
        ("p", "select_push", "Push"),
        ("t", "select_task_board", "Sprint board"),
        ("escape", "dismiss_modal", "Cancel"),
    ]

    def compose(self) -> ComposeResult:
        yield Container(
            Label("Choose a command:"),
            ListView(
                ListItem(Label("space  Stage all changes"), name="stage"),
                ListItem(Label("s  Stash all changes"), name="stash"),
                ListItem(Label("b  Switch branch"), name="switch"),
                ListItem(Label("m  Merge branch"), name="merge"),
                ListItem(Label("c  Create branch"), name="create"),
                ListItem(Label("d  Delete branch"), name="delete"),
                ListItem(Label("l  Pull"), name="pull"),
                ListItem(Label("p  Push"), name="push"),
                ListItem(Label("t  Sprint board"), name="taskboard"),
            ),
            id="palette-box"
        )
        yield Footer()

    def action_dismiss_modal(self):
        self.dismiss(None)
    def action_select_stage(self):
         self.dismiss(("stage", None))
    def action_select_stash(self):
        self.dismiss(("stash", None))
    def action_select_task_board(self):
        self.dismiss(("taskboard", None))

    def action_select_switch(self):
        self.dismiss(("need_branch", "switch"))

    def action_select_merge(self):
        self.dismiss(("need_branch", "merge"))
    def action_create_branch(self):
        self.dismiss(("need_branch","create"))
    def action_delete_branch(self):
        self.dismiss(("need_branch","delete"))
    def action_select_pull(self):
        self.dismiss(("pull", None))

    def action_select_push(self):
        self.dismiss(("push", None))

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        action = event.item.name
        if action in ("switch", "merge","create","delete"):
            self.dismiss(("need_branch", action))
        else:
            self.dismiss((action, None))


class BranchInputModal(ModalScreen):
    BINDINGS = [("escape", "dismiss_modal", "Cancel")]

    def compose(self) -> ComposeResult:
        yield Container(
            Label("Branch name:"),
            Input(placeholder="branch name...", id="branch-name-input"),
            id="branch-input-box"
        )

    def on_mount(self):
        self.query_one("#branch-name-input", Input).focus()

    def action_dismiss_modal(self):
        self.dismiss(None)

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        self.dismiss(event.value)
class BranchSelectModal(ModalScreen):
    """Modal to choose which remote branch should be treated as the main
    branch for the sprint TODO."""

    BINDINGS = [("escape", "dismiss_modal", "Cancel")]

    def compose(self) -> ComposeResult:
        yield Container(
            Label("Select the main branch for the sprint TODO:"),
            ListView(id="branch-select-list"),
            id="branch-select-box",
        )

    async def on_mount(self) -> None:
        list_view = self.query_one("#branch-select-list", ListView)
        await list_view.clear()
        # Get remote branches (e.g., origin/main, origin/master, ...)
        try:
            result = subprocess.run(
                ["git", "branch", "-r", "--format=%(refname:short)"],
                capture_output=True, text=True, check=True
            )
            branches = [b.strip() for b in result.stdout.splitlines() if b.strip()]
        except subprocess.CalledProcessError:
            branches = []
        for branch in branches:
            # Remove the leading "origin/" for display and value
            if branch.startswith("origin/"):
                name = branch[len("origin/"):]
            else:
                name = branch
            await list_view.append(ListItem(Label(name, markup=False), name=name))
        list_view.focus()

    def action_dismiss_modal(self):
        self.dismiss(None)

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        self.dismiss(event.item.name)

class TaskItem(ListItem):
    """One task card on the sprint board. Right-click deletes it."""

    class DeleteRequested(Message):
        def __init__(self, task_num: int) -> None:
            self.task_num = task_num
            super().__init__()

    def __init__(self, task: dict):
        self.task_num = task["num"]
        text = f"#{task['num']} {task['description']}"
        if task.get("deadline"):
            text += f"  ⏰ {task['deadline']}"
        super().__init__(Label(text, markup=False), name=str(task["num"]))

    def on_click(self, event) -> None:
        if getattr(event, "button", 1) == 3:
            event.stop()
            self.post_message(self.DeleteRequested(self.task_num))


class SprintBoardModal(ModalScreen):
    """Jira-style sprint board. Columns are the SprintTodo indices, cards
    are tasks. Bindings work on whichever column ListView has focus."""

    BINDINGS = [
        ("escape", "dismiss_modal", "Close"),
        ("a", "add_task", "Add task"),
        ("d", "delete_task", "Delete task"),
        ("r", "rename_task", "Rename task"),
        ("e", "set_deadline", "Set deadline"),
        ("h", "move_left", "Move ←"),
        ("l", "move_right", "Move →"),
        ("ctrl+r", "refresh_board", "Refresh"),
        ("i", "add_index", "Add index"),
        ("n", "rename_index", "Rename index"),
        ("x", "delete_index", "Delete index"),
        ("s", "toggle_help", "Show/hide help"),
        ("ctrl+s", "save_changes", "Push changes now"),
    ]

    def __init__(self, todo: "SprintTodo"):
        super().__init__()
        self.todo = todo

    def compose(self) -> ComposeResult:
        yield Container(
            Label("Sprint board", id="sprint-title"),
            Horizontal(id="board-columns"),
            # Help popup – initially hidden
            VerticalScroll(
                Label(
                    "Key Bindings:\n"
                    "  a         Add task\n"
                    "  d         Delete task\n"
                    "  r         Rename task\n"
                    "  e         Set deadline\n"
                    "  h / l     Move task left/right\n"
                    "  i         Add index\n"
                    "  n         Rename index\n"
                    "  x         Delete index\n"
                    "  ctrl+r    Refresh from remote\n"
                    "  ctrl+s    Push changes now\n"
                    "  s         Toggle this help\n"
                    "  escape    Close (and push)\n",
                    id="help-text",
                ),
                id="help-popup",
                classes="hidden",
            ),
            Horizontal(
                Button("+ Add Task", id="add-task-btn", variant="primary"),
                Button("Close", id="close-btn"),
                id="sprint-actions",
            ),
            id="sprint-board-box",
        )

    async def on_mount(self) -> None:
        try:
            await asyncio.to_thread(self.todo.pull)
        except SprintTodoError as e:
            self.notify(str(e), title="Sprint board", severity="error")
        await self.refresh_board(focus_first=True)
        # Ensure help popup is hidden initially
        self.query_one("#help-popup").display = False

    # ---------------- board rendering ----------------

    async def refresh_board(self, focus_first: bool = False) -> None:
        columns = self.query_one("#board-columns", Horizontal)

        focused_flag = self._current_flag()
        focused_task = self._current_task_num()

        await columns.remove_children()

        if not self.todo.indices:
            await columns.mount(Label("No indices found in this sprint TODO yet."))
            return

        for num in sorted(self.todo.indices):
            name = self.todo.indices[num]
            tasks = sorted(
                (t for t in self.todo.tasks if t["flag"] == num),
                key=lambda t: t["num"],
            )
            col = Vertical(id=f"col-{num}", classes="sprint-column")
            await columns.mount(col)
            await col.mount(Label(f"{name} ({len(tasks)})", classes="column-header"))
            list_view = ListView(id=f"list-{num}")
            await col.mount(list_view)
            for t in tasks:
                await list_view.append(TaskItem(t))
        target_flag = focused_flag if focused_flag in self.todo.indices else (
            min(self.todo.indices) if focus_first else None
        )

        if target_flag is not None:
            list_view = self.query_one(f"#list-{target_flag}", ListView)
            list_view.focus()
            if focused_task is not None:
                for i, item in enumerate(list_view.children):
                    if item.name == str(focused_task):
                        list_view.index = i
                        break

    # ---------------- focus helpers ----------------

    def _current_list_view(self):
        focused = self.app.focused
        return focused if isinstance(focused, ListView) else None

    def _current_flag(self):
        lv = self._current_list_view()
        if lv is None or not lv.id:
            return None
        try:
            return int(lv.id.split("-", 1)[1])
        except (IndexError, ValueError):
            return None

    def _current_task_num(self):
        lv = self._current_list_view()
        if lv is None or lv.highlighted_child is None:
            return None
        return int(lv.highlighted_child.name)

    # ---------------- new / modified actions ----------------

    async def action_toggle_help(self) -> None:
        """Toggle the help popup visibility."""
        help_popup = self.query_one("#help-popup")
        help_popup.display = not help_popup.display

    async def action_save_changes(self) -> None:
        """Push all pending changes without closing the board."""
        await self._push_changes()

    async def _push_changes(self) -> None:
        """Push if there are recorded operations."""
        if self.todo.has_pending_changes:
            try:
                await asyncio.to_thread(self.todo.push, "Update sprint TODO")
                self.notify("Changes pushed", title="Sprint board", severity="information")
            except SprintTodoError as e:
                self.notify(str(e), title="Push failed", severity="error")
        else:
            self.notify("No changes to push", title="Sprint board", severity="information")

    async def action_dismiss_modal(self) -> None:
        if self.app.screen is self:
            self.dismiss(None)

    # Override the button handler to also push before closing
    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "add-task-btn":
            await self.action_add_task()
        elif event.button.id == "close-btn":
            await self._push_changes()
            # Only dismiss if the screen is still active (on top of stack)
            if self.app.screen is self:
                self.dismiss(None)

    # ---------------- task/index actions (no direct push) ----------------

    async def action_add_task(self):
        if not self.todo.indices:
            self.notify(
                "No indices defined. Add an index first (e.g. via CLI).",
                title="Sprint board",
                severity="warning",
            )
            return
        flag = self._current_flag() or min(self.todo.indices)

        async def handle(description):
            if not description:
                return
            try:
                await asyncio.to_thread(self.todo.add_task, description, flag)
            except SprintTodoError as e:
                self.notify(str(e), title="Add task", severity="error")
            await self.refresh_board()

        self.app.push_screen(
            TodoModal(label="New task:", placeholder="Task description..."), handle
        )

    async def action_delete_task(self):
        num = self._current_task_num()
        if num is None:
            return
        await self._delete_task(num)

    async def _delete_task(self, num: int):
        try:
            await asyncio.to_thread(self.todo.delete_task, num)
        except SprintTodoError as e:
            self.notify(str(e), title="Delete task", severity="error")
        await self.refresh_board()

    def on_task_item_delete_requested(self, message: "TaskItem.DeleteRequested") -> None:
        self.run_worker(self._delete_task(message.task_num))

    async def action_rename_task(self):
        num = self._current_task_num()
        if num is None:
            return
        task = next((t for t in self.todo.tasks if t["num"] == num), None)

        async def handle(description):
            if not description:
                return
            try:
                await asyncio.to_thread(self.todo.rename_task, num, description)
            except SprintTodoError as e:
                self.notify(str(e), title="Rename task", severity="error")
            await self.refresh_board()

        self.app.push_screen(
            TodoModal(
                label="New description:",
                placeholder="Edit task description...",
                initial=task["description"] if task else "",
            ),
            handle,
        )

    async def action_set_deadline(self):
        num = self._current_task_num()
        if num is None:
            return
        task = next((t for t in self.todo.tasks if t["num"] == num), None)

        async def handle(value):
            if value is None:
                return
            try:
                await asyncio.to_thread(self.todo.set_deadline, num, value or None)
            except SprintTodoError as e:
                self.notify(str(e), title="Set deadline", severity="error")
            await self.refresh_board()

        self.app.push_screen(
            TodoModal(
                label="Deadline (YYYY-MM-DD, blank to clear):",
                placeholder="2026-09-15",
                initial=(task["deadline"] or "") if task else "",
            ),
            handle,
        )

    async def action_move_left(self):
        await self._move_task(-1)

    async def action_move_right(self):
        await self._move_task(1)

    async def _move_task(self, direction: int):
        num = self._current_task_num()
        flag = self._current_flag()
        if num is None or flag is None:
            return
        indices = sorted(self.todo.indices)
        pos = indices.index(flag)
        new_pos = pos + direction
        if not (0 <= new_pos < len(indices)):
            return
        new_flag = indices[new_pos]
        try:
            await asyncio.to_thread(self.todo.set_flag, num, new_flag)
        except SprintTodoError as e:
            self.notify(str(e), title="Move task", severity="error")
            await self.refresh_board()
            return
        await self.refresh_board()
        # Follow the moved card into its new column rather than leaving
        # focus behind in the old one.
        try:
            new_list = self.query_one(f"#list-{new_flag}", ListView)
        except Exception:
            return
        new_list.focus()
        for i, item in enumerate(new_list.children):
            if item.name == str(num):
                new_list.index = i
                break

    async def action_add_index(self):
        """Prompt for a new index name and add it at the end."""
        async def handle(name):
            if not name:
                return
            try:
                await asyncio.to_thread(self.todo.add_index, name)
            except SprintTodoError as e:
                self.notify(str(e), title="Add index", severity="error")
            await self.refresh_board()

        self.app.push_screen(
            TodoModal(label="New index name:", placeholder="e.g. Backlog"), handle
        )

    async def action_rename_index(self):
        """Rename the index of the currently focused column."""
        flag = self._current_flag()
        if flag is None:
            self.notify("Focus a column first.", title="Rename index", severity="warning")
            return
        current_name = self.todo.indices.get(flag, "")

        async def handle(new_name):
            if not new_name:
                return
            try:
                await asyncio.to_thread(self.todo.rename_index, flag, new_name)
            except SprintTodoError as e:
                self.notify(str(e), title="Rename index", severity="error")
            await self.refresh_board()

        self.app.push_screen(
            TodoModal(
                label=f"Rename index '{current_name}' to:",
                placeholder="New index name...",
                initial=current_name,
            ),
            handle,
        )

    async def action_delete_index(self):
        """Delete the index of the currently focused column if it has no tasks."""
        flag = self._current_flag()
        if flag is None:
            self.notify("Focus a column first.", title="Delete index", severity="warning")
            return
        tasks_using = [t for t in self.todo.tasks if t["flag"] == flag]
        if tasks_using:
            self.notify(
                f"Index {flag} has {len(tasks_using)} task(s). Reassign them first via CLI.",
                title="Delete index",
                severity="error",
            )
            return

        try:
            await asyncio.to_thread(self.todo.delete_index, flag)
        except SprintTodoError as e:
            self.notify(str(e), title="Delete index", severity="error")
        await self.refresh_board()

class StatusDisplay(Container):
    is_git = reactive(False)

    def on_mount(self) -> None:
        self.check_status()
        self.set_interval(5, self.check_status)

    def check_status(self) -> None:
        self.is_git = is_git_repo()

    def watch_is_git(self, is_git: bool) -> None:
        """Called automatically whenever is_git changes."""
        self.remove_children()
        if is_git:
            self.mount(Label("Git repo detected"))
        else:
            self.mount(Label("Not a git repository"))


class CommitDisplay(Container):
    def compose(self):
        yield ListView(id="Commit-list")

    def on_mount(self) -> None:
        self._last_commits = None
        self.call_later(self.refresh_display)
        self.set_interval(5, self.refresh_display)
    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if event.item is None:
            return
        diff_text = getCommitDiff(event.item.name)
        self.app.query_one(DiffDisplay).diff_text = diff_text
    async def refresh_display(self):
        commits = getCommitsList()
        if commits == self._last_commits:
            return
        self._last_commits = commits
        list_view = self.query_one("#Commit-list", ListView)
        await list_view.clear()
        for c in commits:
            await list_view.append(
                ListItem(Label(c["line"], markup=False), name=c["hash"])
            )


class BranchDisplay(Container):
    BINDINGS=[("b","branch","Checkout to branch")]
    selected_branch=None
    def compose(self):
        yield ListView(id="Branch-list")

    def on_mount(self) -> None:
        self._last_branches = None
        self.call_later(self.refresh_display)
        self.set_interval(5, self.refresh_display)
    def on_list_view_selected(self, event: ListView.Selected) -> None:
        self.selected_branch=event.item.name.strip("*")[2:]
    async def action_branch(self):
        if self.selected_branch is None:
            return
        log_display = self.app.query_one(CommandLogDisplay)
        log_display.log(f"git checkout {self.selected_branch}", "Running...", "", 0)
        stdout, stderr, returncode = await asyncio.to_thread(switchBranch, self.selected_branch)
        log_display.log(f"git checkout {self.selected_branch} (done)", stdout, stderr, returncode)
        await self.app.query_one(FileDisplay).refresh_display(force=True)
        await self.refresh_display()
    async def refresh_display(self):
        branches = GetBranchesList()
        list_view=self.query_one("#Branch-list")
        if branches == self._last_branches:
            return
        self._last_branches = branches
        await list_view.clear()
        for f in branches:
            await list_view.append(
                ListItem(Label(f, markup=False), name=f)
            )

class StashDisplay(Container):
    def compose(self):
        return []

    def on_mount(self) -> None:
        self._last_stashes = None
        self.call_later(self.refresh_display)
        self.set_interval(5, self.refresh_display)

    async def refresh_display(self):
        stashes = getStashes()
        if stashes == self._last_stashes:
            return
        self._last_stashes = stashes
        await self.remove_children()
        self.mount(Label(stashes or "No stashes", markup=False))

class DiffDisplay(ScrollableContainer):
    diff_text = reactive("")

    def watch_diff_text(self, diff_text: str) -> None:
        self.remove_children()
        if diff_text:
            self.mount(Label(build_diff_display(diff_text)))
        else:
            self.mount(Label("No change detected"))
        self.scroll_home(animate=False)
class ConflictDisplay(Container):
    BINDINGS = [
        ("ctrl+a", "abort", "Abort merge"),
        ("ctrl+g", "continue_merge", "Continue merge"),
    ]

    def compose(self):
        return []

    def on_mount(self) -> None:
        self.call_later(self.refresh_display)
        self.set_interval(3, self.refresh_display)

    async def refresh_display(self):
        await self.remove_children()
        if not isMergeInProgress():
            self.mount(Label("No merge in progress"))
            self.display = False
            return

        self.display = True
        conflicts = getConflicts()
        if conflicts:
            text = "MERGE CONFLICT in:\n" + "\n".join(f"  {f}" for f in conflicts)
            text += "\n\nResolve files, then ctrl+g to continue, ctrl+a to abort."
        else:
            text = "All conflicts resolved.\nPress ctrl+g to complete the merge."
        self.mount(Label(text))

    async def action_abort(self):
        stdout, stderr, returncode = abortMerge()
        self.app.query_one(CommandLogDisplay).log("git merge --abort", stdout, stderr, returncode)
        await self.refresh_display()
        await self.app.query_one(FileDisplay).refresh_display(force=True)

    async def action_continue_merge(self):
        stdout, stderr, returncode = continueMerge()
        self.app.query_one(CommandLogDisplay).log("git commit --no-edit", stdout, stderr, returncode)
        await self.refresh_display()
        await self.app.query_one(FileDisplay).refresh_display(force=True)


class FileDisplay(Container):
    BINDINGS = [("space", "toggle_stage", "Stage/Unstage"),("s", "toggle_stash", "Stash file")]
    def compose(self):
        yield ListView(id="Files-list")
    def on_mount(self) -> None:
        self._last_files = None
        self.call_later(self.refresh_display, force=True, focus=True)
        self.set_interval(5, self.refresh_display)

    async def refresh_display(self, force: bool = False, focus: bool = False):
        list_view = self.query_one("#Files-list")
        has_focus = list_view.has_focus
        #If refresh_display is called but its not forced or display isnt focused
        #exit early
        if not force and not has_focus:
            return

        files = GetFilesList()
        if not force and files == self._last_files:
            return  # nothing changed, skip the rebuild entirely
        self._last_files = files
        selected_name = None
        if list_view.highlighted_child is not None:
            selected_name = list_view.highlighted_child.name
        
        await list_view.clear()
        for f in files:
            await list_view.append(
                ListItem(Label(f"{f['staged']}{f['unstaged']} {f['filename']}", markup=False), name=f["filename"])
            )

        if focus or has_focus:
            list_view.focus()

        if selected_name is not None:
            for index, item in enumerate(list_view.children):
                if item.name == selected_name:
                    list_view.index = index
                    break

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        if event.item is None:
            return
        filename = event.item.name
        diff_text = getDiff(filename)
        self.app.query_one(DiffDisplay).diff_text = diff_text

    async def action_toggle_stage(self):
        list_view = self.query_one(ListView)
        highlighted = list_view.highlighted_child
        if highlighted is None:
            return
        filename = highlighted.name

        files = GetFilesList()
        current = next((f for f in files if f["filename"] == filename), None)
        if current is None:
            return

        if current["staged"] != " " and current["staged"] != "?":
            unstageFile(filename)
        else:
            stageFile(filename)

        await self.refresh_display(force=True)
    async def action_toggle_stash(self):
        list_view = self.query_one(ListView)
        highlighted = list_view.highlighted_child
        if highlighted is None:
            return
        filename = highlighted.name
        log_display = self.app.query_one(CommandLogDisplay)
        log_display.log(f"git stash  --{filename}", "Running...", "", 0)
        stdout, stderr, returncode = await asyncio.to_thread(doStashFile, filename=filename)
        log_display.log(f"git stash  --{filename} (done)", stdout, stderr, returncode)
        await self.app.query_one(FileDisplay).refresh_display(force=True)

                
class StashDisplay(Container):
    def compose(self):
        return []

    def on_mount(self) -> None:
        self.call_later(self.refresh_display)
        self.set_interval(5, self.refresh_display)

    async def refresh_display(self):
        await self.remove_children()
        stashes = getStashes()
        self.mount(Label(stashes or "No stashes"))


class CommandLogDisplay(Container):
    log_text = reactive("")

    def compose(self):
        yield TextArea("", read_only=True, id="log-output")
        yield Input(placeholder="Run a command (e.g. git status)", id="command-input")

    def on_mount(self):
        pass  # nothing async needed now, widgets built in compose

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "command-input":
            return
        command = event.input.value
        if not command:
            return
        stdout, stderr, returncode = doCommand(command)
        event.input.value = ""
        self.log(command, stdout, stderr, returncode)

    def log(self, command_label: str, stdout: str, stderr: str, returncode: int) -> None:
        output = stdout if returncode == 0 else f"[FAILED] {stderr}"
        if returncode!=0:
            self.notify(stderr,title=command_label,severity="error")
        self.log_text += f"$ {command_label}\n{output}\n"
        self._update_log()

    def _update_log(self):
        log_area = self.query_one("#log-output", TextArea)
        log_area.load_text(self.log_text)
        log_area.scroll_end(animate=False)

class Repofy(App):
    CSS_PATH = "git_tui.tcss"
    BINDINGS = [
        ("c", "commit", "Commit code"),
        ("d", "toggle_dark", "Toggle dark mode"),
        ("t", "open_sprint_board", "Sprint board"),
        (":", "open_palette", "Commands"),
        ("ctrl+x", "quit", "Quit"),
    ]

    def __init__(self):
        super().__init__()
        self.todo = SprintTodo()

    def compose(self):
        yield Header(show_clock=True)
        yield Footer()
        yield Container(
            StatusDisplay(id="status"),
            FileDisplay(id="files"),
            BranchDisplay(id="branches"),
            CommitDisplay(id="commits"),
            StashDisplay(id="stash"),
            id="left-column")
        yield Container(
            DiffDisplay(id="diff"),
            ConflictDisplay(id="conflicts"),
            CommandLogDisplay(id="command-log"),
            id="right-column")

    def action_toggle_dark(self):
        self.theme = (
            "textual-dark" if self.theme == "textual-light" else "textual-light"
        )

    async def action_commit(self):
        async def handle_result(message: str | None) -> None:
            if not message:
                return  # cancelled or empty
            log_display = self.query_one(CommandLogDisplay)
            log_display.log(f'git commit -m "{message}"', "Running...", "", 0)
            stdout, stderr, returncode = await asyncio.to_thread(doCommit, message)
            log_display.log(f'git commit -m "{message}" (done)', stdout, stderr, returncode)
            await self.query_one(FileDisplay).refresh_display(force=True)

        self.push_screen(CommitModal(), handle_result)

    async def action_open_sprint_board(self):
        if self.todo.main_branch is None:
            # Need user to select the main branch first
            async def handle_branch(branch: str | None) -> None:
                if branch:
                    self.todo.set_main_branch(branch)
                    self.push_screen(SprintBoardModal(self.todo))
                # else: cancelled, do nothing
            self.push_screen(BranchSelectModal(), handle_branch)
        else:
            self.push_screen(SprintBoardModal(self.todo))

    async def action_open_palette(self):
        async def handle_choice(result) -> None:
            if result is None:
                return
            action, extra = result
            log_display = self.query_one(CommandLogDisplay)

            if action == "need_branch":
                operation = extra  # "switch" or "merge"

                async def handle_branch(branch_name: str | None) -> None:
                    if not branch_name:
                        return
                    if operation == "switch":
                        log_display.log(f"git checkout {branch_name}", "Running...", "", 0)
                        stdout, stderr, returncode = await asyncio.to_thread(switchBranch, branch_name)
                        log_display.log(f"git checkout {branch_name} (done)", stdout, stderr, returncode)
                    elif operation == "merge":
                        log_display.log(f"git merge {branch_name}", "Running...", "", 0)
                        stdout, stderr, returncode = await asyncio.to_thread(doMerge, branch_name)
                        log_display.log(f"git merge {branch_name} (done)", stdout, stderr, returncode)
                    elif operation == "create":
                        log_display.log(f"git checkout -b {branch_name}", "Running...", "", 0)
                        stdout, stderr, returncode = await asyncio.to_thread(createBranch, branch_name)
                        log_display.log(f"git checkout -b {branch_name} (done)", stdout, stderr, returncode)
                    elif operation == "delete":
                        log_display.log(f"git branch -d {branch_name}", "Running...", "", 0)
                        stdout, stderr, returncode = await asyncio.to_thread(deleteBranch, branch_name)
                        log_display.log(f"git branch -d {branch_name} (done)", stdout, stderr, returncode)
                    await self.query_one(FileDisplay).refresh_display(force=True)
                    await self.query_one(ConflictDisplay).refresh_display()

                self.push_screen(BranchInputModal(), handle_branch)
            elif action == "stash":
                log_display.log("git stash", "Running...", "", 0)
                stdout, stderr, returncode = await asyncio.to_thread(doStash)
                log_display.log("git stash (done)", stdout, stderr, returncode)
                await self.query_one(FileDisplay).refresh_display(force=True)
            elif action == "stage":
                log_display.log("git add .", "Running...", "", 0)
                stdout, stderr, returncode = await asyncio.to_thread(stageAll)
                log_display.log("git add . (done)", stdout, stderr, returncode)
                await self.query_one(FileDisplay).refresh_display(force=True)
            elif action == "pull":
                log_display.log("git pull", "Running...", "", 0)
                stdout, stderr, returncode = await asyncio.to_thread(doPull)
                log_display.log("git pull (done)", stdout, stderr, returncode)
                await self.query_one(FileDisplay).refresh_display(force=True)
            elif action == "push":
                log_display.log("git push", "Running...", "", 0)
                stdout, stderr, returncode = await asyncio.to_thread(doPush)
                log_display.log("git push (done)", stdout, stderr, returncode)
            elif action == "taskboard":
                self.push_screen(SprintBoardModal(self.todo))

        self.push_screen(CommandPaletteModal(), handle_choice)


if __name__ == "__main__":
    app = Repofy()
    app.run()
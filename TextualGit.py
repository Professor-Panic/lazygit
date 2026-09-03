from textual.app import App, ComposeResult
from textual.containers import HorizontalGroup, VerticalScroll, Container, ScrollableContainer
from textual.reactive import reactive
from textual.widgets import Footer, Header, Button, Digits, Label,TextArea
from textual.widgets import ListView, ListItem, Label, Input
from textual.screen import ModalScreen
from git_checker import *
import asyncio

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


class CommandPaletteModal(ModalScreen):
    BINDINGS = [
        ("s", "select_stash", "Stash"),
        ("b", "select_switch", "Switch branch"),
        ("m", "select_merge", "Merge branch"),
        ("l", "select_pull", "Pull"),
        ("p", "select_push", "Push"),
        ("escape", "dismiss_modal", "Cancel"),
    ]

    def compose(self) -> ComposeResult:
        yield Container(
            Label("Choose a command:"),
            ListView(
                ListItem(Label("s  Stash all changes"), name="stash"),
                ListItem(Label("b  Switch branch"), name="switch"),
                ListItem(Label("m  Merge branch"), name="merge"),
                ListItem(Label("l  Pull"), name="pull"),
                ListItem(Label("p  Push"), name="push"),
            ),
            id="palette-box"
        )
        yield Footer()

    def action_dismiss_modal(self):
        self.dismiss(None)

    def action_select_stash(self):
        self.dismiss(("stash", None))

    def action_select_switch(self):
        self.dismiss(("need_branch", "switch"))

    def action_select_merge(self):
        self.dismiss(("need_branch", "merge"))

    def action_select_pull(self):
        self.dismiss(("pull", None))

    def action_select_push(self):
        self.dismiss(("push", None))

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        action = event.item.name
        if action in ("switch", "merge"):
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
        return []

    def on_mount(self) -> None:
        self._last_commits = None
        self.call_later(self.refresh_display)
        self.set_interval(5, self.refresh_display)

    async def refresh_display(self):
        commits = getCommits()
        if commits == self._last_commits:
            return  # nothing changed, don't touch the widget
        self._last_commits = commits
        await self.remove_children()
        self.mount(Label(commits, markup=False))


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
        self.mount(Label(diff_text or "No change detected",markup=False))
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
        output = stdout if returncode == 0 else stderr
        self.log_text += f"$ {command}\n{output}\n"
        event.input.value = ""
        self._update_log()

    def log(self, command_label: str, stdout: str, stderr: str, returncode: int) -> None:
        output = stdout if returncode == 0 else f"[FAILED] {stderr}"
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
        (":", "open_palette", "Commands"),
        ("ctrl+x", "quit", "Quit"),
    ]

    def compose(self):
        yield Header()
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
                    await self.query_one(FileDisplay).refresh_display(force=True)
                    await self.query_one(ConflictDisplay).refresh_display()

                self.push_screen(BranchInputModal(), handle_branch)
            elif action == "stash":
                log_display.log("git stash", "Running...", "", 0)
                stdout, stderr, returncode = await asyncio.to_thread(doStash)
                log_display.log("git stash (done)", stdout, stderr, returncode)
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

        self.push_screen(CommandPaletteModal(), handle_choice)


if __name__ == "__main__":
    app = Repofy()
    app.run()
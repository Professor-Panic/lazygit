from textual.app import App, ComposeResult
from textual.containers import HorizontalGroup, VerticalScroll, Container
from textual.reactive import reactive
from textual.widgets import Footer, Header, Button, Digits, Label
from textual.widgets import ListView, ListItem, Label, Input
from git_checker import is_git_repo, GetFilesList, getBranches, getDiff, getCommits, doCommit,doCommand

class StatusDisplay(Container):
    is_git = reactive(False)

    def _on_mount(self) -> None:
        self.is_git = is_git_repo()

    def watch_is_git(self, is_git: bool) -> None:
        """Called automatically whenever is_git changes."""
        if is_git:
            self.remove_children()
            self.mount(Label("Git repo detected"))
        else:
            self.remove_children()
            self.mount(Label("Not a git repository"))

class CommitDisplay(Container):
    def compose(self):
        return []

    async def _on_mount(self):
        await self.refresh_display()

    async def refresh_display(self):
        await self.remove_children()
        commits = getCommits()
        self.mount(Label(commits))
        self.mount(Input(placeholder="Commit message", id="commit-input"))

class BranchDisplay(Container):
    branches = ""
    def _on_mount(self):
        self.branches = getBranches()
        self.mount(Label(self.branches))
    def compose(self):
        return []

class DiffDisplay(Container):
    diff_text = reactive("")

    def watch_diff_text(self, diff_text: str) -> None:
        self.remove_children()
        self.mount(Label(diff_text or "No file selected"))

class FileDisplay(Container):
    def compose(self):
        return []

    async def _on_mount(self):
        await self.refresh_display()

    async def refresh_display(self):
        await self.remove_children()
        files = GetFilesList()
        list_items = [
            ListItem(Label(f"{f['staged']}{f['unstaged']} {f['filename']}"), name=f["filename"])
            for f in files
        ]
        self.mount(ListView(*list_items))

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        if event.item is None:
            return
        filename = event.item.name
        diff_text = getDiff(filename)
        self.app.query_one(DiffDisplay).diff_text = diff_text

class StashDisplay(Container):
    pass

class CommandLogDisplay(Container):
    log_text = reactive("")

    def compose(self):
        return []

    async def _on_mount(self):
        await self.remove_children()
        self.mount(Label(self.log_text, id="log-output"))
        self.mount(Input(placeholder="Run a command (e.g. git status)", id="command-input"))

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
        log_label = self.query_one("#log-output", Label)
        log_label.update(self.log_text)

class LazyGit(App):
    CSS_PATH = "git_tui.tcss"
    BINDINGS = [("c", "commit", "Commit code"), ("d", "toggle_dark", "Toggle dark mode")]

    def compose(self):
        yield Header()
        yield Footer()
        yield Container(
            StatusDisplay(id="status"),
            FileDisplay(id="files"),
            BranchDisplay(id="branches"),
            CommitDisplay(id="commits"),
            CommandLogDisplay(id="command-log"),
            id="left-column")
        yield DiffDisplay(id="diff")

    def action_toggle_dark(self):
        self.theme = (
            "textual-dark" if self.theme == "textual-light" else "textual-light"
        )

    async def action_commit(self):
        commit_input = self.query_one("#commit-input", Input)
        message = commit_input.value
        if not message:
            return
        doCommit(message)
        await self.query_one(FileDisplay).refresh_display()
        await self.query_one(CommitDisplay).refresh_display()

if __name__ == "__main__":
    app = LazyGit()
    app.run()
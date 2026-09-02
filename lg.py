from textual.app import App, ComposeResult
from textual.containers import HorizontalGroup, VerticalScroll,Container
from textual.reactive import reactive
from textual.widgets import Footer, Header,Button,Digits,Label
from git_checker import is_git_repo,getFiles
class StatusDisplay(Container):
    is_git = reactive(False)

    def _on_mount(self) -> None:
        self.is_git = is_git_repo()

    def watch_is_git(self, is_git: bool) -> None:
        """Called automatically whenever is_git changes."""
        if is_git:
            self.remove_children()
            self.mount(Label("✅ Git repo detected"))
        else:
            self.remove_children()
            self.mount(Label("❌ Not a git repository"))
class CommitDisplay(Container):
    pass
class BranchDisplay(Container):
    pass
class FileDisplay(Container):
    files=""
    def _on_mount(self):
        self.files=getFiles()
        self.mount(Label(self.files))
    def compose(self):
        return []
class StashDisplay(Container):
    pass 
class DiffDisplay(Container):
    pass
class CommandLogDisplay(Container):
    pass
class LazyGit(App):
    CSS_PATH="git_tui.tcss"
    BINDINGS=[("c","commit","Commit code"),("d", "toggle_dark", "Toggle dark mode")]
    def compose(self):
        yield Header()
        yield Footer()
        yield StatusDisplay(id="status")
        yield FileDisplay(id="files")
    def action_toggle_dark(self):
        self.theme = (
        "textual-dark" if self.theme == "textual-light" else "textual-light"
        )
    def action_commit(self):
        pass
if __name__ =="__main__":
    app=LazyGit()
    app.run()
import shlex
from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import Input, Label, ListItem, ListView


class FilePickerModal(ModalScreen):
    BINDINGS = [("escape", "dismiss_modal", "Cancel")]

    def __init__(self, root: Path | None = None):
        super().__init__()
        self.root_path = (root or Path.cwd()).resolve()
        self.current_path = self.root_path

    def compose(self) -> ComposeResult:
        yield Container(
            Label("Open file", id="file-picker-title"),
            Label(id="file-picker-path"),
            Input(placeholder="Filter files...", id="file-picker-filter"),
            ListView(id="file-picker-list"),
            Input(placeholder="Command: ls, mkdir, rmdir, cd, pwd", id="file-picker-command"),
            Label(id="file-picker-status"),
            id="file-picker-box",
        )

    async def on_mount(self) -> None:
        self.query_one("#file-picker-filter", Input).focus()
        await self.refresh_entries()

    def action_dismiss_modal(self) -> None:
        self.dismiss(None)

    async def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "file-picker-filter":
            await self.refresh_entries()

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "file-picker-command":
            return
        command = event.value.strip()
        event.input.value = ""
        await self.run_command(command)

    def _path_from_argument(self, argument: str) -> Path:
        candidate = (self.current_path / argument).resolve()
        candidate.relative_to(self.root_path)
        return candidate

    async def run_command(self, command: str) -> None:
        if not command:
            return
        try:
            parts = shlex.split(command)
            name, arguments = parts[0], parts[1:]
            if name == "pwd" and not arguments:
                message = str(self.current_path)
            elif name == "ls" and not arguments:
                message = "  ".join(entry.name for entry in self._entries()) or "(empty)"
            elif name == "cd" and len(arguments) == 1:
                target = self._path_from_argument(arguments[0])
                if not target.is_dir():
                    raise NotADirectoryError(arguments[0])
                self.current_path = target
                message = f"Changed directory to {self.current_path}"
            elif name == "mkdir" and len(arguments) == 1:
                target = self._path_from_argument(arguments[0])
                target.mkdir()
                message = f"Created directory {target.name}"
            elif name == "rmdir" and len(arguments) == 1:
                target = self._path_from_argument(arguments[0])
                if target == self.root_path:
                    raise OSError("cannot remove the picker root")
                target.rmdir()
                message = f"Removed directory {target.name}"
            else:
                raise ValueError("usage: ls | pwd | cd <dir> | mkdir <dir> | rmdir <dir>")
        except (OSError, ValueError) as error:
            message = f"Error: {error}"
        self.query_one("#file-picker-status", Label).update(message)
        await self.refresh_entries()
        self.query_one("#file-picker-command", Input).focus()

    def _entries(self) -> list[Path]:
        try:
            return sorted(
                (entry for entry in self.current_path.iterdir() if entry.name != ".git"),
                key=lambda entry: (entry.is_file(), entry.name.lower()),
            )
        except OSError:
            return []

    async def refresh_entries(self) -> None:
        filter_text = self.query_one("#file-picker-filter", Input).value.lower()
        path_label = self.query_one("#file-picker-path", Label)
        list_view = self.query_one("#file-picker-list", ListView)
        relative_path = self.current_path.relative_to(self.root_path)
        path_label.update("/" if not relative_path.parts else f"/{relative_path}")

        entries = []
        if self.current_path != self.root_path:
            entries.append(("..", "__parent__"))
        for entry in self._entries():
            if filter_text and filter_text not in entry.name.lower():
                continue
            label = f"[DIR] {entry.name}" if entry.is_dir() else entry.name
            entries.append((label, str(entry)))

        await list_view.clear()
        for label, value in entries:
            await list_view.append(ListItem(Label(label, markup=False), name=value))
        list_view.focus()

    async def on_list_view_selected(self, event: ListView.Selected) -> None:
        selected = event.item.name
        if selected == "__parent__":
            self.current_path = self.current_path.parent
            await self.refresh_entries()
            return

        selected_path = Path(selected)
        if selected_path.is_dir():
            self.current_path = selected_path
            await self.refresh_entries()
        else:
            self.dismiss(selected_path)

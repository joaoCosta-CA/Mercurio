from __future__ import annotations

import webbrowser
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from rich.markup import escape
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.coordinate import Coordinate
from textual.widgets import DataTable, Footer, Input, OptionList, Static

from mercurio.config import Paths, Settings
from mercurio.domain.models import Assignment
from mercurio.integrations.classroom import GoogleClassroom
from mercurio.integrations.google_auth import has_credentials, load_credentials
from mercurio.locking import process_lock
from mercurio.services import synchronize
from mercurio.storage.sqlite import Database

type AssignmentRow = tuple[int, str, Assignment]


class MercurioApp(App[None]):
    """Painel interativo do Mercúrio para terminais compatíveis com Textual."""

    TITLE = "Mercúrio"
    SUB_TITLE = "Atividades do Google Classroom"
    CSS = """
    $background: #121411;
    $surface: #1C201B;
    $foreground: #E1D6BA;
    $primary: #E4B668;
    $secondary: #91A58B;

    Screen { background: $background; color: $foreground; }
    #topo {
        height: 3; width: 100%; padding: 1 2; background: #25281F;
        color: $primary; text-style: bold;
    }
    #corpo { height: 1fr; padding: 0 1; }
    #painel-principal { height: 1fr; }
    .painel { border: round #8D7853; background: $surface; }
    .painel:focus-within { border: heavy $primary; }
    #esquerda { width: 29%; min-width: 24; margin-right: 1; }
    #direita { width: 1fr; }
    .rotulo { height: 1; background: #33372B; color: $primary; text-style: bold; }
    #disciplinas { height: 1fr; border: none; background: $surface; }
    #disciplinas > .option-list--option-highlighted {
        background: #464832; color: #F8DBA5; text-style: bold;
    }
    #dica { height: 2; padding: 0 1; color: $secondary; }
    #search { height: 3; border: none; background: #282C24; color: $foreground; }
    DataTable { height: 1fr; background: $surface; color: $foreground; }
    DataTable > .datatable--header { background: #33372B; color: $primary; text-style: bold; }
    DataTable > .datatable--cursor { background: #464832; color: #F8DBA5; text-style: bold; }
    #history-table { display: none; }
    #details { height: 8; padding: 1 2; margin-top: 1; }
    Footer { background: #25281F; color: $foreground; }
    """
    BINDINGS = [
        ("r", "sync", "Sincronizar"),
        ("a", "toggle_active", "Ativas/todas"),
        ("h", "history", "Histórico"),
        ("o", "open_assignment", "Abrir atividade"),
        Binding("slash", "search", "Buscar", key_display="/"),
        ("question_mark", "help", "Ajuda"),
        ("q", "quit", "Sair"),
    ]

    def __init__(self, paths: Paths, settings: Settings, database: Database) -> None:
        super().__init__()
        self.paths = paths
        self.settings = settings
        self.database = database
        self.active_only = True
        self.search_term = ""
        self.course_filter = "__all__"
        self.showing_history = False
        self.courses = ["__all__"]
        self._visible_assignments: dict[str, AssignmentRow] = {}

    def compose(self) -> ComposeResult:
        yield Static(id="topo")
        with Vertical(id="corpo"):
            with Horizontal(id="painel-principal"):
                with Vertical(id="esquerda", classes="painel"):
                    yield Static(" DISCIPLINAS", classes="rotulo")
                    yield OptionList("Todas as disciplinas", id="disciplinas")
                    yield Static("TAB alterna painéis", id="dica")
                with Vertical(id="direita", classes="painel"):
                    yield Static(" ATIVIDADES", id="lista-rotulo", classes="rotulo")
                    yield Input(placeholder="Buscar atividade ou disciplina...", id="search")
                    yield DataTable(id="activity-table", cursor_type="row")
                    yield DataTable(id="history-table", cursor_type="row")
            yield Static(
                "Selecione uma atividade para ver os detalhes.", id="details", classes="painel"
            )
        yield Footer(compact=True)

    def on_mount(self) -> None:
        activity_table = self.query_one("#activity-table", DataTable)
        activity_table.add_columns("Disciplina", "Atividade", "Prazo", "Estado")
        history_table = self.query_one("#history-table", DataTable)
        history_table.add_columns("Estado", "Marco", "Disciplina", "Atividade", "Canal")
        self.refresh_data()
        activity_table.focus()

    def _filtered_assignments(self) -> list[AssignmentRow]:
        now = datetime.now(UTC)
        query = self.search_term.casefold()
        result: list[AssignmentRow] = []
        for row in self.database.assignments():
            _assignment_id, course_name, assignment = row
            if self.course_filter != "__all__" and course_name != self.course_filter:
                continue
            if self.active_only and (
                not assignment.reminder_eligible
                or assignment.due_utc is None
                or assignment.due_utc <= now
            ):
                continue
            if query and query not in f"{course_name} {assignment.title}".casefold():
                continue
            result.append(row)
        return result

    def _format_due(self, assignment: Assignment) -> str:
        if assignment.due_utc:
            return assignment.due_utc.astimezone(ZoneInfo(self.settings.timezone)).strftime(
                "%d/%m/%Y %H:%M"
            )
        if assignment.due_date:
            return assignment.due_date.strftime("%d/%m/%Y") + " (horário indefinido)"
        return "Sem prazo definido"

    def _deadline_label(self, assignment: Assignment) -> str:
        if assignment.due_utc is None:
            return self._format_due(assignment)
        due = assignment.due_utc.astimezone(ZoneInfo(self.settings.timezone))
        days = (due.date() - datetime.now(ZoneInfo(self.settings.timezone)).date()).days
        if days < 0:
            return f"ATRASADA {abs(days)}d"
        if days == 0:
            return "HOJE"
        if days == 1:
            return "AMANHÃ"
        return f"EM {days} DIAS"

    def refresh_data(self) -> None:
        rows = self.database.assignments()
        courses = sorted({course_name for _, course_name, _ in rows}, key=str.casefold)
        self.courses = ["__all__", *courses]
        selector = self.query_one("#disciplinas", OptionList)
        selector.clear_options()
        selector.add_options(["Todas as disciplinas", *courses])
        if self.course_filter not in {"__all__", *courses}:
            self.course_filter = "__all__"
        selector.highlighted = self.courses.index(self.course_filter)

        table = self.query_one("#activity-table", DataTable)
        table.clear()
        self._visible_assignments = {}
        for assignment_id, course_name, assignment in self._filtered_assignments():
            key = str(assignment_id)
            self._visible_assignments[key] = (assignment_id, course_name, assignment)
            table.add_row(
                course_name,
                assignment.title,
                self._deadline_label(assignment),
                assignment.submission_state.value,
                key=key,
            )
        self._refresh_history()
        self._refresh_summary()
        if not self._visible_assignments:
            self.query_one("#details", Static).update("Nenhuma atividade encontrada.")
        else:
            self._show_details(next(iter(self._visible_assignments.values())))

    def _refresh_history(self) -> None:
        table = self.query_one("#history-table", DataTable)
        table.clear()
        for event in self.database.event_history():
            table.add_row(
                str(event["state"]),
                f"{event['milestone_minutes']} min",
                str(event["course_name"]),
                str(event["title"]),
                str(event["channel"]),
            )

    def _refresh_summary(self) -> None:
        latest = self.database.latest_sync()
        sync_label = "nunca" if latest is None else str(latest["finished_at"])
        authorization = "autorizado" if has_credentials(self.paths) else "não autorizado"
        counts = self.database.status_counts()
        view = "ativas" if self.active_only else "todas"
        self.query_one("#topo", Static).update(
            f"◈ MERCÚRIO  /  CLASSROOM    ● GOOGLE: {authorization.upper()}\n"
            f"Última sincronização: {sync_label}  •  Eventos: {counts}  •  Exibindo: {view}"
        )

    def _show_details(self, row: AssignmentRow) -> None:
        _assignment_id, course_name, assignment = row
        link_hint = (
            "Pressione O para abrir no Google Classroom."
            if assignment.url
            else "Esta atividade não possui link no Classroom."
        )
        self.query_one("#details", Static).update(
            "[bold #E4B668]DETALHES DA ATIVIDADE[/]\n"
            f"[bold]{escape(assignment.title)}[/]   •   {escape(course_name)}\n"
            f"Prazo: {self._format_due(assignment)}   |   "
            f"Estado: {escape(assignment.submission_state.value)}\n"
            f"[dim]{link_hint}[/]"
        )

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.data_table.id != "activity-table":
            return
        row = self._visible_assignments.get(str(event.row_key.value))
        if row is None:
            return
        self._show_details(row)

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.data_table.id == "activity-table":
            self.action_open_assignment()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "search":
            self.search_term = event.value
            self.refresh_data()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if event.option_list.id != "disciplinas":
            return
        self.course_filter = self.courses[event.option_index]
        self.showing_history = False
        self._set_view()
        self.refresh_data()
        self.query_one("#activity-table", DataTable).focus()

    def action_toggle_active(self) -> None:
        self.active_only = not self.active_only
        self.refresh_data()

    def action_search(self) -> None:
        if self.showing_history:
            self.showing_history = False
            self._set_view()
        self.query_one("#search", Input).focus()

    def action_history(self) -> None:
        self.showing_history = not self.showing_history
        self._set_view()

    def _set_view(self) -> None:
        activities = self.query_one("#activity-table", DataTable)
        history = self.query_one("#history-table", DataTable)
        search = self.query_one("#search", Input)
        activities.display = not self.showing_history
        history.display = self.showing_history
        search.display = not self.showing_history
        label = " HISTÓRICO DE AVISOS" if self.showing_history else " ATIVIDADES"
        self.query_one("#lista-rotulo", Static).update(label)
        if self.showing_history:
            self.query_one("#details", Static).update(
                "[bold #E4B668]HISTÓRICO DE AVISOS[/]\n"
                "Pressione H novamente para retornar às atividades."
            )
            history.focus()
        else:
            activities.focus()

    def action_help(self) -> None:
        self.notify(
            "TAB alterna painéis · ↑/↓ navegam · ENTER abre · R sincroniza · "
            "A alterna ativas/todas · / busca · H histórico · O abre · Q sai",
            timeout=10,
        )

    def action_open_assignment(self) -> None:
        if self.showing_history:
            self.notify("Retorne às atividades com H para abrir um link.", severity="warning")
            return
        table = self.query_one("#activity-table", DataTable)
        if table.cursor_row is None or table.row_count == 0:
            self.notify("Selecione uma atividade primeiro.", severity="warning")
            return
        key = str(table.coordinate_to_cell_key(Coordinate(table.cursor_row, 0)).row_key.value)
        row = self._visible_assignments.get(key)
        if row is None or row[2].url is None:
            self.notify("Esta atividade não tem link disponível.", severity="warning")
            return
        webbrowser.open(row[2].url)
        self.notify("Atividade aberta no navegador.")

    @work(thread=True, exclusive=True)
    def action_sync(self) -> None:
        try:
            credentials = load_credentials(self.paths)
            with process_lock(self.paths.lock_file):
                courses, assignments = synchronize(self.database, GoogleClassroom(credentials))
        except Exception as exc:
            self.call_from_thread(
                self.notify, f"Falha ao sincronizar: {str(exc)[:180]}", severity="error"
            )
            return
        self.call_from_thread(self.refresh_data)
        self.call_from_thread(
            self.notify, f"Sincronizados: {courses} curso(s), {assignments} atividade(s)."
        )

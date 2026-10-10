"""Projects tab — browse what each repo *is*, not just whether it's dirty.

Left: every repo with its auto-derived one-line description. Right: three
sub-tabs for the selected repo — Overview (README/PROJECT prose), What's Next
(the PLAN/NEXT/ROADMAP/TODO docs generated per project), and History (git log).
"""

import subprocess
from pathlib import Path

from html import escape

from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QFontMetrics, QPainter
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit,
    QListWidget, QListWidgetItem, QSplitter, QTabWidget, QTextBrowser,
    QComboBox, QFrame,
)

from src.config.settings import Settings
from src.gui.widgets.elided_label import ElidedLabel
from src.core.project_info import (
    ProjectInfo, ProjectLoadThread, DescriptionScanThread, sanitize_markdown,
)

NO_DESCRIPTION = "no description found"

# Rendered markdown reuses the app's charcoal palette. QTextBrowser applies
# document stylesheets, not the global QSS, so headings/code/links need their
# own rules here or they fall back to black-on-white browser defaults.
DOC_CSS = """
body { color: #cccccc; font-family: 'Segoe UI', sans-serif; font-size: 13px; }
h1, h2, h3, h4 { color: #007acc; }
h1 { font-size: 18px; } h2 { font-size: 16px; } h3 { font-size: 14px; }
a { color: #4ea1d3; }
code, pre { font-family: 'Cascadia Mono', 'Consolas', monospace;
            font-size: 12px; color: #d7ba7d; }
li { margin-bottom: 3px; }
table { border-collapse: collapse; }
td { padding: 2px 8px 2px 0; }
td.sha { font-family: 'Cascadia Mono', 'Consolas', monospace; color: #d7ba7d;
         white-space: nowrap; }
td.meta { color: #6e6e6e; font-size: 11px; white-space: nowrap; }
"""


class ProjectRow(QWidget):
    """One repo in the list: name + plan-count badge over its description."""

    def __init__(self, label: str, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(1)

        name_row = QHBoxLayout()
        name_row.setSpacing(6)
        self.name = ElidedLabel(label)
        self.name.setStyleSheet(
            "font-weight: bold; font-size: 12px; color: #dddddd; background: transparent;"
        )
        name_row.addWidget(self.name, 1)

        self.badge = QLabel("")
        self.badge.setStyleSheet(
            "color: #9c6acd; font-size: 10px; font-weight: bold; background: transparent;"
        )
        name_row.addWidget(self.badge, 0)
        layout.addLayout(name_row)

        self.desc = ElidedLabel("reading…")
        self.desc.setStyleSheet(
            "font-size: 11px; color: #8a8a8a; background: transparent;"
        )
        layout.addWidget(self.desc)

    def set_description(self, text: str, plan_count: int):
        self.desc.setText(text)
        # The badge counts plan docs, so a repo with pending work is findable
        # by eye while scrolling.
        self.badge.setText(f"◆ {plan_count}" if plan_count else "")
        self.badge.setToolTip(
            f"{plan_count} plan doc(s)" if plan_count else ""
        )


class DocView(QTextBrowser):
    """Markdown/HTML view that never reaches the network.

    QTextBrowser resolves image URLs synchronously on the UI thread, so a
    README full of remote badges would freeze the panel on every slow host.
    Images are stripped before rendering anyway; this is the backstop.
    """

    def loadResource(self, resource_type, url):  # noqa: N802 (Qt naming)
        if url.scheme() in ("http", "https"):
            return None
        return super().loadResource(resource_type, url)


class ProjectPanel(QWidget):
    def __init__(self, settings: Settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self._loader = None
        self._desc_scan = None
        self._descriptions: dict[str, str] = {}
        self._plan_counts: dict[str, int] = {}
        self._info: ProjectInfo | None = None
        self._items: dict[str, QListWidgetItem] = {}
        self._rows: dict[str, ProjectRow] = {}
        self._loaded = False

        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        top_row = QHBoxLayout()
        header = QLabel("Projects")
        header.setObjectName("sectionHeader")
        top_row.addWidget(header)
        top_row.addStretch()

        self.scan_label = QLabel("")
        self.scan_label.setStyleSheet("color: #6e6e6e; font-size: 11px;")
        top_row.addWidget(self.scan_label)

        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.setToolTip("Re-read descriptions, plans, and history")
        self.refresh_btn.clicked.connect(self.refresh)
        top_row.addWidget(self.refresh_btn)
        layout.addLayout(top_row)

        splitter = QSplitter(Qt.Horizontal)

        # --- Left: repo list ---
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(6)

        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("Filter projects...")
        self.search_box.setClearButtonEnabled(True)
        self.search_box.textChanged.connect(self._apply_filter)
        left_layout.addWidget(self.search_box)

        self.repo_list = QListWidget()
        self.repo_list.setStyleSheet(
            "QListWidget { background: #252526; border: 1px solid #474747; "
            "border-radius: 4px; }"
            "QListWidget::item { padding: 5px 6px; border-bottom: 1px solid #2d2d2d; }"
            "QListWidget::item:selected { background: #094771; color: #ffffff; }"
        )
        self.repo_list.currentItemChanged.connect(self._on_repo_selected)
        left_layout.addWidget(self.repo_list, 1)
        splitter.addWidget(left)

        # --- Right: detail ---
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(6)

        self.title_label = QLabel("Select a project")
        self.title_label.setStyleSheet(
            "font-size: 15px; font-weight: bold; color: #ffffff;"
        )
        right_layout.addWidget(self.title_label)

        self.subtitle_label = QLabel("")
        self.subtitle_label.setWordWrap(True)
        self.subtitle_label.setStyleSheet("color: #9e9e9e; font-size: 12px;")
        right_layout.addWidget(self.subtitle_label)

        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet("color: #474747;")
        right_layout.addWidget(line)

        self.detail_tabs = QTabWidget()
        self.detail_tabs.setStyleSheet(
            "QTabBar::tab { padding: 5px 12px; font-size: 12px; }"
        )

        self.overview_view = self._make_doc_view()
        self.detail_tabs.addTab(self.overview_view, "Overview")

        # What's Next gets a picker above the doc — repos routinely carry
        # several plan docs (root PLAN.md plus docs/*_PLAN.md).
        plans_tab = QWidget()
        plans_layout = QVBoxLayout(plans_tab)
        plans_layout.setContentsMargins(0, 6, 0, 0)
        plans_layout.setSpacing(6)
        self.plan_combo = QComboBox()
        self.plan_combo.currentIndexChanged.connect(self._on_plan_selected)
        plans_layout.addWidget(self.plan_combo)
        self.plan_view = self._make_doc_view()
        plans_layout.addWidget(self.plan_view, 1)
        self.detail_tabs.addTab(plans_tab, "What's Next")

        self.history_view = self._make_doc_view()
        self.detail_tabs.addTab(self.history_view, "History")

        right_layout.addWidget(self.detail_tabs, 1)

        # --- Actions ---
        action_row = QHBoxLayout()
        self.open_folder_btn = QPushButton("Open Folder")
        self.open_folder_btn.setToolTip("Open this project in File Explorer")
        self.open_folder_btn.clicked.connect(self._open_folder)
        action_row.addWidget(self.open_folder_btn)

        self.plan_btn = QPushButton("Generate Plan")
        self.plan_btn.setToolTip(
            "Open Claude in this project (plan mode) and ask it to refresh the "
            "what's-next plan doc"
        )
        self.plan_btn.setStyleSheet(
            "QPushButton { background: #6e40c9; color: #ffffff; border: none; "
            "border-radius: 6px; padding: 8px 16px; font-weight: bold; }"
            "QPushButton:hover { background: #8b5cf6; }"
        )
        self.plan_btn.clicked.connect(self._generate_plan)
        action_row.addWidget(self.plan_btn)
        action_row.addStretch()
        right_layout.addLayout(action_row)

        splitter.addWidget(right)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([270, 470])
        layout.addWidget(splitter, 1)

        self._set_enabled(False)
        # The list itself is built in ensure_loaded(), not here — 116 row
        # widgets cost real time in the startup style pass, and this tab is
        # usually not the one you open first.

    @staticmethod
    def _make_doc_view() -> QTextBrowser:
        view = DocView()
        view.setOpenExternalLinks(True)
        view.document().setDefaultStyleSheet(DOC_CSS)
        # font-family/size/color are restated here because QTextBrowser derives
        # from QTextEdit, so the global theme's monospace QTextEdit rule would
        # otherwise render this prose as terminal output.
        view.setStyleSheet(
            "QTextBrowser { background: #252526; border: 1px solid #474747; "
            "border-radius: 4px; padding: 8px; color: #cccccc; "
            "font-family: 'Segoe UI', sans-serif; font-size: 13px; }"
        )
        return view

    # --- Repo list ----------------------------------------------------------

    def refresh(self):
        """Re-read everything, keeping the current selection if it survives."""
        selected = None
        item = self.repo_list.currentItem()
        if item is not None:
            selected = item.data(Qt.UserRole)
        if self.settings.sync_repos().changed:
            self.settings.save()
        self.refresh_repos()
        if selected and selected in self._items:
            self.repo_list.setCurrentItem(self._items[selected])

    def ensure_loaded(self):
        """Kick off the description scan the first time the tab is opened.

        Deferred rather than done in __init__: reading a README per repo across
        100+ OneDrive-backed folders is slow enough to delay app startup, and
        most launches never open this tab.
        """
        if self._loaded:
            return
        self._loaded = True
        self.refresh_repos()

    def refresh_repos(self):
        """Rebuild the list from settings (called on account switch too)."""
        if not self._loaded:
            return  # nothing built yet; ensure_loaded() will do it on first open
        self.repo_list.blockSignals(True)
        self.repo_list.clear()
        self._items.clear()
        self._rows.clear()
        for repo in self.settings.repos:
            item = QListWidgetItem()
            item.setData(Qt.UserRole, repo.path)
            item.setSizeHint(QSize(0, 48))
            row = ProjectRow(repo.label)
            self._items[repo.path] = item
            self._rows[repo.path] = row
            self.repo_list.addItem(item)
            self.repo_list.setItemWidget(item, row)
            self._paint_item(repo.path, repo.label)
        self.repo_list.blockSignals(False)
        self._apply_filter()
        if self._loaded:
            self._start_description_scan()

    def _paint_item(self, path: str, label: str):
        item = self._items.get(path)
        row = self._rows.get(path)
        if item is None or row is None:
            return
        desc = self._descriptions.get(path)
        plans = self._plan_counts.get(path, 0)
        if desc is None:
            text = "reading…" if self._loaded else "—"
        else:
            text = desc or NO_DESCRIPTION
        row.set_description(text, plans)
        # The tooltip carries the untruncated description the row can't fit.
        item.setToolTip(f"{label}\n{desc}\n\n{path}" if desc else path)

    def _start_description_scan(self):
        from src.core.process_launcher import stop_worker
        stop_worker(self._desc_scan)
        self._descriptions.clear()
        self._plan_counts.clear()
        repos = list(self.settings.repos)
        if not repos:
            return
        self._desc_pending = len(repos)
        self.scan_label.setText(f"Reading 0/{len(repos)}…")
        self._desc_done = 0
        self._desc_scan = DescriptionScanThread(repos, parent=self)
        self._desc_scan.described.connect(self._on_described)
        self._desc_scan.scan_complete.connect(self._on_desc_scan_complete)
        self._desc_scan.start()

    def _on_described(self, path: str, description: str, plan_count: int):
        self._desc_done += 1
        self.scan_label.setText(f"Reading {self._desc_done}/{self._desc_pending}…")
        self._descriptions[path] = description
        self._plan_counts[path] = plan_count
        repo = next((r for r in self.settings.repos if r.path == path), None)
        if repo:
            self._paint_item(path, repo.label)

    def _on_desc_scan_complete(self):
        self.scan_label.setText("")
        self._desc_scan = None
        self._apply_filter()

    def _apply_filter(self):
        """Filter on label and description, so 'CAM' finds repos by subject."""
        query = self.search_box.text().strip().lower()
        labels = {r.path: r.label for r in self.settings.repos}
        for path, item in self._items.items():
            if not query:
                item.setHidden(False)
                continue
            haystack = (
                f"{labels.get(path, path)} {self._descriptions.get(path, '')}"
            ).lower()
            item.setHidden(query not in haystack)

    # --- Detail -------------------------------------------------------------

    def _on_repo_selected(self, current: QListWidgetItem, _previous=None):
        if current is None:
            self._set_enabled(False)
            return
        path = current.data(Qt.UserRole)
        repo = next((r for r in self.settings.repos if r.path == path), None)
        label = repo.label if repo else Path(path).name

        self.title_label.setText(label)
        self.subtitle_label.setText("Loading…")
        for view in (self.overview_view, self.plan_view, self.history_view):
            view.setPlainText("")
        self.plan_combo.clear()
        self._info = None
        self._set_enabled(False)

        from src.core.process_launcher import stop_worker
        stop_worker(self._loader)
        self._loader = ProjectLoadThread(path, label, parent=self)
        self._loader.loaded.connect(self._on_project_loaded)
        self._loader.start()

    def _on_project_loaded(self, info: ProjectInfo):
        # A fast click-through can land a stale result after the user moved on.
        current = self.repo_list.currentItem()
        if current is None or current.data(Qt.UserRole) != info.path:
            return

        self._info = info
        self._loader = None
        self._set_enabled(True)

        if info.error:
            self.subtitle_label.setText(f"Error: {info.error}")
        else:
            branch = f"  ·  {info.branch}" if info.branch else ""
            src = f"  ·  from {info.description_source}" if info.description_source else ""
            desc = info.description or NO_DESCRIPTION
            self.subtitle_label.setText(f"{desc}\n{info.path}{branch}{src}")
        self.title_label.setText(info.label)

        # Overview
        if info.readme.strip():
            self.overview_view.setMarkdown(sanitize_markdown(info.readme))
        else:
            self.overview_view.setMarkdown(
                "*No README.md or PROJECT.md in this repo.*"
            )

        # What's Next — newest plan first, so the default selection is the one
        # most recently regenerated.
        self.plan_combo.blockSignals(True)
        self.plan_combo.clear()
        for plan in info.plans:
            self.plan_combo.addItem(plan.title, plan.path)
        self.plan_combo.blockSignals(False)
        # Hidden rather than disabled with no plans — an empty picker bar reads
        # as a broken control.
        self.plan_combo.setVisible(bool(info.plans))
        if info.plans:
            self.plan_combo.setCurrentIndex(0)
            self._on_plan_selected(0)
        else:
            self.plan_view.setMarkdown(
                "*No plan docs found.*\n\nThe **What's Next** pane looks for "
                "`PLAN`/`NEXT`/`ROADMAP`/`TODO`-style `.md` files in the repo "
                "root and `docs/`. Use **Generate Plan** to have Claude write one."
            )
        self.detail_tabs.setTabText(
            1, f"What's Next ({len(info.plans)})" if info.plans else "What's Next"
        )

        # History
        self.history_view.setHtml(self._history_html(info))
        self.detail_tabs.setTabText(
            2, f"History ({len(info.commits)})" if info.commits else "History"
        )

    @staticmethod
    def _history_html(info: ProjectInfo) -> str:
        """One row per commit: sha, subject, then a dim author/age column.

        Built as a table rather than markdown so the three columns line up —
        a bulleted list left the ages ragged and hard to scan.
        """
        if not info.commits:
            return "<p><i>No commit history.</i></p>"
        rows = []
        for c in info.commits:
            rows.append(
                f"<tr><td class='sha'>{escape(c.sha)}</td>"
                f"<td>{escape(c.subject)}</td>"
                f"<td class='meta'>{escape(c.when)} · {escape(c.author)}</td></tr>"
            )
        return "<table width='100%'>" + "".join(rows) + "</table>"

    def _on_plan_selected(self, index: int):
        if self._info is None or index < 0 or index >= len(self._info.plans):
            return
        plan = self._info.plans[index]
        self.plan_view.setMarkdown(sanitize_markdown(plan.body) or "*(empty file)*")

    def _set_enabled(self, enabled: bool):
        self.open_folder_btn.setEnabled(enabled)
        self.plan_btn.setEnabled(enabled)

    # --- Actions ------------------------------------------------------------

    def _open_folder(self):
        if self._info is None:
            return
        try:
            subprocess.Popen(["explorer", self._info.path])
        except Exception:
            pass

    def _generate_plan(self):
        """Open Claude in the project, in plan mode, to refresh its plan doc.

        Routed through the git panel's launcher so the wt.exe semicolon
        escaping and window-titling stay in one place.
        """
        if self._info is None:
            return
        panel = self._git_panel()
        if panel is None:
            return
        import uuid
        existing = self._info.plans[0].title if self._info.plans else "PLAN.md"
        prompt = (
            f"Review this project and write or update its what's-next plan doc "
            f"({existing}). Read the README, the recent git log, and the code to "
            f"work out where the project actually stands, then produce a short "
            f"prioritized list of the next concrete steps with enough context "
            f"that a fresh session could pick any one of them up. Do not change "
            f"any code — only the plan doc."
        )
        escaped = panel._escape_prompt(
            panel._guardrail(self._info.path) + " " + prompt
        )
        uid = uuid.uuid4().hex[:8]
        panel._spawn_claude_window(
            f"Claude-{self._info.label}-plan-{uid}", self._info.path,
            f'claude --permission-mode plan "{escaped}"',
            "plan", self._info.label,
        )

    def _git_panel(self):
        win = self.window()
        return getattr(win, "git_panel", None)

    def stop_workers(self):
        from src.core.process_launcher import stop_worker
        for worker in (self._loader, self._desc_scan):
            stop_worker(worker)

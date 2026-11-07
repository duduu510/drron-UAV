from pathlib import Path
import os
from PySide6.QtGui import QFont, QFontDatabase

QSS = """
QWidget { color:#17243A; font-family:'Microsoft YaHei UI','Segoe UI'; font-size:10pt; }
QMainWindow { background:#111317; }
QWidget#contentRoot { background:#F5F8FC; border-top-left-radius:22px; }
QWidget#sidebar { background:#111317; }
QLabel#brand { color:white; font-size:17pt; font-weight:700; padding:10px 4px; }
QLabel#brandSub, QLabel#sidebarFoot { color:#9DA9BA; font-size:9pt; }
QListWidget#moduleNav { background:transparent; border:0; outline:0; color:#BCC5D1; }
QListWidget#moduleNav::item { padding:15px 16px; margin:4px 0; border-radius:10px; color:#BCC5D1; }
QListWidget#moduleNav::item:selected { background:#1467E8; color:white; font-weight:600; }
QListWidget#moduleNav::item:hover:!selected { background:#242A33; }
QWidget#topbar { background:white; border-top-left-radius:22px; border-bottom:1px solid #E2E8F1; }
QLabel#pageTitle { font-size:21pt; font-weight:700; color:#17243A; }
QLabel#subtitle, QLabel#muted { color:#64748B; }
QLabel#badge { background:#EAF2FF; color:#0D3680; padding:6px 12px; border-radius:12px; font-size:9pt; }
QFrame#panel { background:white; border:1px solid #E2E8F1; border-radius:12px; }
QLabel#panelTitle { font-size:12pt; font-weight:600; }
QLabel#metricValue { font-size:23pt; font-weight:600; color:#0D3680; }
QLabel#emptyTitle { font-size:15pt; font-weight:600; }
QPushButton { background:white; border:1px solid #D8E1ED; border-radius:7px; padding:7px 14px; min-height:21px; }
QPushButton:hover { background:#EAF2FF; border-color:#1467E8; }
QPushButton:disabled { color:#93A0B2; background:#EDF1F6; border-color:#E2E8F1; }
QPushButton#primary { background:#1467E8; color:white; border-color:#1467E8; font-weight:600; }
QPushButton#primary:hover { background:#0D3680; }
QPushButton#primary:disabled { background:#CBD5E1; border-color:#CBD5E1; color:#64748B; }
QLineEdit,QComboBox,QSpinBox,QDoubleSpinBox { background:white; border:1px solid #D8E1ED; border-radius:6px; padding:7px; min-height:20px; selection-background-color:#1467E8; }
QLineEdit:focus,QComboBox:focus { border-color:#1467E8; }
QComboBox::drop-down { border:0; width:22px; }
QTableWidget,QTableView { background:white; alternate-background-color:#F7FAFD; border:1px solid #E2E8F1; gridline-color:#EEF2F7; selection-background-color:#EAF2FF; selection-color:#17243A; }
QHeaderView::section { background:#F0F5FC; border:0; border-bottom:1px solid #E2E8F1; padding:9px; color:#52647E; font-weight:600; }
QTableWidget::item { padding:5px; }
QTabWidget::pane { border:1px solid #E2E8F1; background:white; }
QTabBar::tab { background:#F0F5FC; padding:9px 18px; border:0; }
QTabBar::tab:selected { background:white; color:#1467E8; }
QScrollArea { border:0; background:transparent; }
QSlider::groove:horizontal { height:6px; background:#DFE7F2; border-radius:3px; }
QSlider::handle:horizontal { width:14px; margin:-5px 0; background:#1467E8; border-radius:7px; }
QStatusBar { background:#F5F8FC; color:#64748B; }
QToolTip { background:#17243A; color:white; padding:6px; border:0; }
"""


def apply_theme(app):
    # Windows offscreen sessions can have no registered system fonts at all.
    # Register the installed OS fonts explicitly; never redistribute OS files.
    if os.name == "nt" and "Microsoft YaHei UI" not in QFontDatabase.families():
        directory = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
        for filename in ("msyh.ttc", "msyhbd.ttc"):
            path = directory / filename
            if path.is_file(): QFontDatabase.addApplicationFont(str(path))
    app.setFont(QFont("Microsoft YaHei UI", 10))
    app.setStyleSheet(QSS)

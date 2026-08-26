from __future__ import annotations


def _dark_stylesheet() -> str:
    return r"""
    * {
        font-family: "Segoe UI", "Microsoft YaHei UI", sans-serif;
        font-size: 13px;
        color: #E4E4E4;
    }

    QMainWindow,
    QWidget#appRoot,
    QWidget#page,
    QWidget#settingsContent,
    QScrollArea#settingsScroll,
    QScrollArea#settingsScroll > QWidget > QWidget {
        background: #1B1B1B;
    }

    QFrame#sidebar {
        background: #1D1D1D;
        border-right: 1px solid #353535;
    }

    QLabel#brandMark {
        min-width: 34px;
        max-width: 34px;
        min-height: 34px;
        max-height: 34px;
        background: #292929;
        border: 1px solid #4A4A4A;
        border-radius: 7px;
        font-size: 13px;
        font-weight: 700;
        color: #F0F0F0;
    }

    QLabel#brandTitle { font-size: 16px; font-weight: 600; color: #F2F2F2; }
    QLabel#brandVersion { color: #8D8D8D; font-size: 11px; }

    QPushButton#navButton {
        text-align: left;
        padding: 0 14px;
        min-height: 42px;
        border: 0;
        border-radius: 6px;
        background: transparent;
        color: #C4C4C4;
    }
    QPushButton#navButton:hover { background: #262626; color: #F2F2F2; }
    QPushButton#navButton:checked {
        background: #292929;
        color: #FFFFFF;
        border-left: 3px solid #C9C9C9;
        padding-left: 11px;
        font-weight: 600;
    }

    QLabel#pageTitle { font-size: 24px; font-weight: 600; color: #F0F0F0; }
    QLabel#pageSubtitle, QLabel#muted { color: #999999; }

    QFrame#card {
        background: #1F1F1F;
        border: 1px solid #3B3B3B;
        border-radius: 8px;
    }

    QLabel#sectionTitle { font-size: 14px; font-weight: 600; color: #EDEDED; }
    QLabel#statusValue { color: #D5D5D5; font-size: 13px; }
    QLabel#statusHint { color: #8E8E8E; font-size: 12px; }

    QTextEdit#consoleOutput {
        background: #171717;
        border: 1px solid #3A3A3A;
        border-radius: 7px;
        padding: 10px;
        color: #D7D7D7;
        selection-background-color: #555555;
        font-family: "Cascadia Mono", "Consolas", monospace;
        font-size: 12px;
    }

    QLineEdit, QPlainTextEdit, QTextEdit, QComboBox, QSpinBox, QDoubleSpinBox {
        background: #1B1B1B;
        border: 1px solid #414141;
        border-radius: 6px;
        color: #EEEEEE;
        selection-background-color: #555555;
    }
    QLineEdit { min-height: 30px; padding: 0 8px; }
    QComboBox { min-height: 30px; padding: 0 8px; }
    QComboBox QAbstractItemView { background: #202020; color: #EEEEEE; selection-background-color: #3C3C3C; }

    QLineEdit#consoleInput {
        min-height: 36px;
        padding: 0 10px;
        font-family: "Cascadia Mono", "Consolas", monospace;
    }
    QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus { border: 1px solid #777777; }
    QLabel#prompt { color: #CFCFCF; font-family: "Cascadia Mono", "Consolas", monospace; font-weight: 700; }

    QPushButton#primaryButton {
        min-height: 34px;
        padding: 0 16px;
        background: #303030;
        border: 1px solid #555555;
        border-radius: 6px;
        color: #F0F0F0;
        font-weight: 600;
    }
    QPushButton#primaryButton:hover { background: #3A3A3A; border-color: #686868; }

    QPushButton#secondaryButton, QPushButton {
        min-height: 32px;
        padding: 0 13px;
        background: #242424;
        border: 1px solid #414141;
        border-radius: 6px;
        color: #D8D8D8;
    }
    QPushButton#secondaryButton:hover, QPushButton:hover { background: #2C2C2C; border-color: #515151; }

    QCheckBox { spacing: 8px; color: #D3D3D3; }
    QCheckBox::indicator { width: 16px; height: 16px; }
    QCheckBox::indicator:unchecked { background: #1C1C1C; border: 1px solid #4A4A4A; border-radius: 3px; }
    QCheckBox::indicator:checked { background: #9B9B9B; border: 1px solid #B8B8B8; border-radius: 3px; }

    QListWidget, QTableView, QTableWidget {
        background: #1B1B1B;
        alternate-background-color: #202020;
        border: 1px solid #3A3A3A;
        color: #E4E4E4;
        gridline-color: #383838;
        selection-background-color: #3A3A3A;
    }
    QHeaderView::section { background: #292929; color: #E4E4E4; border: 0; border-right: 1px solid #3A3A3A; padding: 5px; }

    QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
    QScrollBar::handle:vertical { background: #444444; min-height: 28px; border-radius: 4px; }
    QScrollBar::handle:vertical:hover { background: #555555; }
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
    """


def _light_stylesheet() -> str:
    # Same geometry and component hierarchy as the dark theme. Only neutral
    # background/foreground surfaces are inverted; workflow block category
    # colours remain painted by their own QGraphicsItems and are untouched.
    return r"""
    * {
        font-family: "Segoe UI", "Microsoft YaHei UI", sans-serif;
        font-size: 13px;
        color: #252525;
    }

    QMainWindow,
    QWidget#appRoot,
    QWidget#page,
    QWidget#settingsContent,
    QScrollArea#settingsScroll,
    QScrollArea#settingsScroll > QWidget > QWidget {
        background: #F4F4F4;
    }

    QFrame#sidebar {
        background: #EEEEEE;
        border-right: 1px solid #D0D0D0;
    }

    QLabel#brandMark {
        min-width: 34px;
        max-width: 34px;
        min-height: 34px;
        max-height: 34px;
        background: #E2E2E2;
        border: 1px solid #C0C0C0;
        border-radius: 7px;
        font-size: 13px;
        font-weight: 700;
        color: #222222;
    }

    QLabel#brandTitle { font-size: 16px; font-weight: 600; color: #202020; }
    QLabel#brandVersion { color: #707070; font-size: 11px; }

    QPushButton#navButton {
        text-align: left;
        padding: 0 14px;
        min-height: 42px;
        border: 0;
        border-radius: 6px;
        background: transparent;
        color: #444444;
    }
    QPushButton#navButton:hover { background: #E3E3E3; color: #111111; }
    QPushButton#navButton:checked {
        background: #DDDDDD;
        color: #111111;
        border-left: 3px solid #5F5F5F;
        padding-left: 11px;
        font-weight: 600;
    }

    QLabel#pageTitle { font-size: 24px; font-weight: 600; color: #181818; }
    QLabel#pageSubtitle, QLabel#muted { color: #6F6F6F; }

    QFrame#card {
        background: #FAFAFA;
        border: 1px solid #D0D0D0;
        border-radius: 8px;
    }

    QLabel#sectionTitle { font-size: 14px; font-weight: 600; color: #202020; }
    QLabel#statusValue { color: #333333; font-size: 13px; }
    QLabel#statusHint { color: #727272; font-size: 12px; }

    QTextEdit#consoleOutput {
        background: #FFFFFF;
        border: 1px solid #CCCCCC;
        border-radius: 7px;
        padding: 10px;
        color: #242424;
        selection-background-color: #C8DDF5;
        font-family: "Cascadia Mono", "Consolas", monospace;
        font-size: 12px;
    }

    QLineEdit, QPlainTextEdit, QTextEdit, QComboBox, QSpinBox, QDoubleSpinBox {
        background: #FFFFFF;
        border: 1px solid #C9C9C9;
        border-radius: 6px;
        color: #202020;
        selection-background-color: #C8DDF5;
    }
    QLineEdit { min-height: 30px; padding: 0 8px; }
    QComboBox { min-height: 30px; padding: 0 8px; }
    QComboBox QAbstractItemView { background: #FFFFFF; color: #202020; selection-background-color: #E0EAF5; }

    QLineEdit#consoleInput {
        min-height: 36px;
        padding: 0 10px;
        font-family: "Cascadia Mono", "Consolas", monospace;
    }
    QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus { border: 1px solid #777777; }
    QLabel#prompt { color: #383838; font-family: "Cascadia Mono", "Consolas", monospace; font-weight: 700; }

    QPushButton#primaryButton {
        min-height: 34px;
        padding: 0 16px;
        background: #E2E2E2;
        border: 1px solid #BEBEBE;
        border-radius: 6px;
        color: #202020;
        font-weight: 600;
    }
    QPushButton#primaryButton:hover { background: #D8D8D8; border-color: #AFAFAF; }

    QPushButton#secondaryButton, QPushButton {
        min-height: 32px;
        padding: 0 13px;
        background: #F2F2F2;
        border: 1px solid #C9C9C9;
        border-radius: 6px;
        color: #303030;
    }
    QPushButton#secondaryButton:hover, QPushButton:hover { background: #E8E8E8; border-color: #B8B8B8; }

    QCheckBox { spacing: 8px; color: #303030; }
    QCheckBox::indicator { width: 16px; height: 16px; }
    QCheckBox::indicator:unchecked { background: #FFFFFF; border: 1px solid #AFAFAF; border-radius: 3px; }
    QCheckBox::indicator:checked { background: #5E5E5E; border: 1px solid #4C4C4C; border-radius: 3px; }

    QListWidget, QTableView, QTableWidget {
        background: #FFFFFF;
        alternate-background-color: #F6F6F6;
        border: 1px solid #CCCCCC;
        color: #202020;
        gridline-color: #DADADA;
        selection-background-color: #DCE8F5;
    }
    QHeaderView::section { background: #E8E8E8; color: #202020; border: 0; border-right: 1px solid #CCCCCC; padding: 5px; }

    QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
    QScrollBar::handle:vertical { background: #B7B7B7; min-height: 28px; border-radius: 4px; }
    QScrollBar::handle:vertical:hover { background: #A4A4A4; }
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
    """


def build_stylesheet(theme: str = "dark") -> str:
    return (
        _light_stylesheet()
        if str(theme).lower() == "light"
        else _dark_stylesheet()
    )

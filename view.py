from typing import Optional

from PyQt5.QtGui import QStandardItemModel, QStandardItem, QCloseEvent, QKeySequence
from PyQt5.QtCore import Qt, pyqtSignal, pyqtSlot
from PyQt5.QtWidgets import (QMainWindow, QFormLayout, QPushButton, QLineEdit, QWidget, QVBoxLayout,
                             QComboBox, QProgressBar, QTabWidget, QLabel, QListWidget, QHBoxLayout,
                             QTreeView, QTableView, QShortcut)
from viewmodel import MainWindowViewModel, ResultWindowViewModel
from model import AnalyzeResult


class MainWindow(QMainWindow):
    
    def __init__(self):
        super(MainWindow, self).__init__()
        self.data_source = MainWindowViewModel(self)
        self.dialog: Optional[QWidget] = None
        self.main_layout = QVBoxLayout()
        self.form_layout = QFormLayout()

        self.btn_choose_file = QPushButton("Choose File...")
        self.btn_choose_file.pressed.connect(self.data_source.choose_file)
        self.form_layout.addRow("Data File", self.btn_choose_file)

        txt_record_regex = QLineEdit()
        txt_record_regex.textChanged.connect(self.data_source.update_record_regex)
        self.form_layout.addRow("Record Start Regex", txt_record_regex)

        self.txt_delimiter = QLineEdit()
        self.txt_delimiter.textChanged.connect(self.data_source.update_delimiter)
        self.form_layout.addRow("Delimiter", self.txt_delimiter)

        self.txt_qualifier = QLineEdit()
        self.txt_qualifier.textChanged.connect(self.data_source.update_qualifier)
        self.form_layout.addRow("Qualifier", self.txt_qualifier)

        self.cbo_encoding = QComboBox()
        self.cbo_encoding.addItems(("UTF-8", "CP-1252"))
        self.cbo_encoding.currentIndexChanged.connect(self.data_source.update_encoding)
        self.form_layout.addRow("Encoding", self.cbo_encoding)

        self.main_layout.addLayout(self.form_layout)
        self.btn_analyze_file = QPushButton("Analyze File")
        self.btn_analyze_file.pressed.connect(self.data_source.analyze_file)
        self.main_layout.addWidget(self.btn_analyze_file)

        self.analyzeProgress = QProgressBar()
        self.analyzeProgress.setObjectName("BlueProgressBar")
        self.analyzeProgress.setTextVisible(True)
        self.analyzeProgress.setVisible(False)
        self.main_layout.addWidget(self.analyzeProgress)

        widget = QWidget()
        widget.setLayout(self.main_layout)
        self.setCentralWidget(widget)
        self.setWindowTitle("Text Data Fixer")

    def show_analyze_result(self, result: AnalyzeResult) -> None:
        self.dialog = ResultWindow(result)
        self.dialog.close_signal.connect(self.close_dialog)
        self.setVisible(False)
        self.dialog.show()

    @pyqtSlot()
    def close_dialog(self) -> None:
        self.setVisible(True)


class ResultWindow(QWidget):

    close_signal = pyqtSignal()

    def __init__(self, result: AnalyzeResult):
        super(ResultWindow, self).__init__()
        self.data_source = ResultWindowViewModel(self, result)
        main_layout = QVBoxLayout()
        result_tabs = QTabWidget()

        overview_tab = QWidget()
        overview_tab_layout = QVBoxLayout()
        overview_header_layout = QHBoxLayout()
        overview_header_layout.addWidget(QLabel(result.message))

        if result.code in (-2, -6):
            btn_qualifier_fix = QPushButton("Export Fix")
            overview_header_layout.addWidget(btn_qualifier_fix)

        overview_tab_layout.addLayout(overview_header_layout)

        overview_lists_layout = QHBoxLayout()

        columns_layout = QVBoxLayout()
        columns_layout.addWidget(QLabel("Columns"))
        lst_columns = QListWidget()
        lst_columns.addItems(result.columns)
        columns_layout.addWidget(lst_columns)
        overview_lists_layout.addLayout(columns_layout)

        overflow_layout = QVBoxLayout()
        overflow_layout.addWidget(QLabel("Overflow Lines"))
        lst_overflow_lines = QListWidget()
        lst_overflow_lines.addItems([str(line_number) for line_number in result.overflow_lines])
        overflow_layout.addWidget(lst_overflow_lines)
        overview_lists_layout.addLayout(overflow_layout)

        overview_tab_layout.addLayout(overview_lists_layout)
        overview_tab.setLayout(overview_tab_layout)
        result_tabs.addTab(overview_tab, "Overview")

        if result.bad_escapes:
            bad_escapes_tab = QTreeView()
            bad_escapes_model = QStandardItemModel(0, 1, self)
            bad_escapes_model.setHeaderData(0, Qt.Horizontal, "Record")
            root_node = bad_escapes_model.invisibleRootItem()

            for bad_escape in result.bad_escapes:
                item = QStandardItem(bad_escape.record)
                item.setEditable(False)
                for value in bad_escape.values:
                    value_item = QStandardItem(value)
                    value_item.setEditable(False)
                    item.appendRow(value_item)
                root_node.appendRow(item)

            bad_escapes_tab.setModel(bad_escapes_model)
            result_tabs.addTab(bad_escapes_tab, "Non-Escaped Qualifiers")

        if result.bad_delimiters:
            bad_delimiters_tab = QListWidget()
            bad_delimiters_tab.addItems(
                [
                    bad_delimiter.replace("\t", "\\t").replace("\n", "\\n").replace("\r", "\\r")
                    for bad_delimiter in result.bad_delimiters
                ]
            )
            result_tabs.addTab(bad_delimiters_tab, "Improper Delimiters")

        if result.code == -3:
            fix_bad_delimiters_tab = QWidget()
            fix_bad_delimiters_tab_layout = QVBoxLayout()

            self.bad_delimiters_table = QTableView()
            self.bad_delimiters_table.setModel(self.data_source.bad_delimiter_table_model)
            self.bad_delimiters_table.setContextMenuPolicy(Qt.CustomContextMenu)

            undo_action = QShortcut(QKeySequence("Ctrl+Z"), self.bad_delimiters_table)
            undo_action.activated.connect(self.data_source.bad_delimiter_table_model.undo_change)
            redo_action = QShortcut(QKeySequence("Ctrl+Y"), self.bad_delimiters_table)
            redo_action.activated.connect(self.data_source.bad_delimiter_table_model.redo_change)

            self.bad_delimiters_table.customContextMenuRequested.connect(self.data_source.open_menu)
            fix_bad_delimiters_tab_layout.addWidget(self.bad_delimiters_table)
            self.data_source.table_selection_model = self.bad_delimiters_table.selectionModel()
            # self.bad_delimiters_table.resizeColumnsToContents()

            fix_bad_delimiters_tab.setLayout(fix_bad_delimiters_tab_layout)
            result_tabs.addTab(fix_bad_delimiters_tab, "Fix Improper Delimiters")

        main_layout.addWidget(result_tabs)
        self.setLayout(main_layout)

    def closeEvent(self, a0: QCloseEvent) -> None:
        self.close_signal.emit()
        self.data_source.delete_temp_file()
        super(ResultWindow, self).closeEvent(a0)

import traceback
import re
import csv
import os
from PyQt5.QtCore import (QObject, pyqtSlot, QThread, pyqtSignal, QAbstractTableModel, QModelIndex,
                          Qt, QItemSelectionModel, QPoint)
from PyQt5.QtWidgets import QMessageBox, QFileDialog, QMenu
from model import (validate_file_options, TextDataDoctor, PeekResult, AnalyzeResult,
                   BadDelimiterChange)
from typing import Optional, List, Any
from pandas import read_csv


class MainWindowViewModel(QObject):

    def __init__(self, view):
        super(MainWindowViewModel, self).__init__()
        self.view = view
        self.file_path = ""
        self.record_start_regex = ""
        self.delimiter = ""
        self.qualifier = ""
        self.encoding = ""
        self.worker: Optional[QThread] = None

    @pyqtSlot(str)
    def update_record_regex(self, text: str) -> None:
        self.record_start_regex = text

    @pyqtSlot(str)
    def update_delimiter(self, text: str) -> None:
        self.delimiter = text

    @pyqtSlot(str)
    def update_qualifier(self, text: str) -> None:
        self.qualifier = text

    @pyqtSlot(int)
    def update_encoding(self, index: int) -> None:
        self.encoding = "utf8" if index == 0 else "cp1252"

    @pyqtSlot()
    def show_progress(self) -> None:
        self.view.btn_choose_file.setEnabled(False)
        self.view.btn_analyze_file.setVisible(False)
        self.view.analyzeProgress.setVisible(True)
        self.view.analyzeProgress.setMaximum(0)
        self.view.analyzeProgress.setMinimum(0)

    @pyqtSlot()
    def hide_progress(self) -> None:
        self.view.btn_choose_file.setEnabled(True)
        self.view.analyzeProgress.setVisible(False)
        self.view.btn_analyze_file.setVisible(True)
        self.view.analyzeProgress.setMaximum(0)
        self.view.analyzeProgress.setMinimum(0)

    @pyqtSlot(str)
    def update_progress_message(self, text: str) -> None:
        self.view.analyzeProgress.setFormat(text)

    @pyqtSlot(str)
    def show_error_message(self, message: str) -> None:
        dialog = QMessageBox()
        dialog.setWindowTitle("Operation Error")
        dialog.setText(message)
        dialog.exec_()

    @pyqtSlot(object)
    def handle_peek_result(self, result: PeekResult) -> None:
        if result.code < 0:
            dialog = QMessageBox()
            dialog.setWindowTitle("Peek Error")
            dialog.setText(result.message)
            dialog.exec_()
            return
        self.delimiter = result.delimiter.replace("\t", "\\t")
        self.view.txt_delimiter.setText(result.delimiter.replace("\t", "\\t"))
        self.qualifier = result.qualifier
        self.view.txt_qualifier.setText(result.qualifier)
        self.encoding = result.encoding
        self.view.cbo_encoding.setCurrentIndex(0 if result.encoding == "utf8" else 1)
        self.file_path = result.path
        self.view.btn_choose_file.setText(re.search(r"(?<=/)[^./]+\..+$", result.path).group(0))

    @pyqtSlot()
    def choose_file(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(
            self.view,
            "Choose Text Data file",
            "",
            "Text Data (*.csv *.txt *.tsv)"
        )
        if not file_path:
            return
        self.worker = PeekThread(file_path)
        self.worker.start_signal.connect(self.show_progress)
        self.worker.progress_signal.connect(self.update_progress_message)
        self.worker.error_signal.connect(self.show_error_message)
        self.worker.result_signal.connect(self.handle_peek_result)
        self.worker.finished_signal.connect(self.hide_progress)
        self.worker.start()

    @pyqtSlot(object)
    def handle_analyze_result(self, result: AnalyzeResult):
        if result.code == -7:
            dialog = QMessageBox()
            dialog.setWindowTitle("Analyze Error")
            dialog.setText(result.message)
            dialog.exec_()
            return
        self.view.show_analyze_result(result)

    @pyqtSlot()
    def analyze_file(self):
        is_valid, error_message = validate_file_options(
            self.record_start_regex, self.delimiter, self.qualifier
        )
        if not is_valid:
            dialog = QMessageBox()
            dialog.setWindowTitle("Option Validation")
            dialog.setText(error_message)
            dialog.exec_()
            return
        doctor = TextDataDoctor(
            self.record_start_regex,
            self.file_path,
            self.delimiter.replace("\\t", "\t"),
            self.qualifier,
            self.encoding
        )
        self.worker = AnalyzeThread(doctor)
        self.worker.start_signal.connect(self.show_progress)
        self.worker.progress_signal.connect(self.update_progress_message)
        self.worker.error_signal.connect(self.show_error_message)
        self.worker.result_signal.connect(self.handle_analyze_result)
        self.worker.finished_signal.connect(self.hide_progress)
        self.worker.start()


class PeekThread(QThread):

    start_signal = pyqtSignal()
    progress_signal = pyqtSignal(str)
    error_signal = pyqtSignal(str)
    result_signal = pyqtSignal(object)
    finished_signal = pyqtSignal()

    def __init__(self, path: str):
        super(PeekThread, self).__init__()
        self.path = path

    def run(self) -> None:
        self.start_signal.emit()
        try:
            result = TextDataDoctor.peek_file(self.path, self.progress_signal)
        except:
            self.error_signal.emit(f"Error during file peek\n{traceback.format_exc()}")
        else:
            self.result_signal.emit(result)
        finally:
            self.finished_signal.emit()


class AnalyzeThread(QThread):

    start_signal = pyqtSignal()
    progress_signal = pyqtSignal(str)
    error_signal = pyqtSignal(str)
    result_signal = pyqtSignal(object)
    finished_signal = pyqtSignal()

    def __init__(self, doctor: TextDataDoctor):
        super(AnalyzeThread, self).__init__()
        self.doctor = doctor

    def run(self) -> None:
        self.start_signal.emit()
        try:
            result = self.doctor.analyze_file()
        except:
            self.error_signal.emit(f"Error during file analyze\n{traceback.format_exc()}")
        else:
            self.result_signal.emit(result)
        finally:
            self.finished_signal.emit()


class ResultWindowViewModel(QObject):

    def __init__(self, view, result: AnalyzeResult):
        super(ResultWindowViewModel, self).__init__()
        self.view = view
        self.result = result
        self.table_selection_model: Optional[QItemSelectionModel] = None
        if self.result.code == -3:
            bad_delimiter_records = [
                bd.split(self.result.delimiter)
                for bd in self.result.bad_delimiters
            ]
            good_records_df = read_csv(
                self.result.temp_file.name,
                sep=self.result.delimiter,
                dtype=str,
                encoding="utf8",
                lineterminator="\n",
                quoting=csv.QUOTE_NONE,
                nrows=10
            ).fillna("")
            good_records: List[List[str]] = [
                list(row)
                for row in good_records_df.itertuples(index=False)
            ]
            self.bad_delimiter_table_model = BadDelimitersTableModel(
                bad_delimiter_records,
                good_records,
                self.result.columns,
                self.result.delimiter
            )

    def delete_temp_file(self) -> None:
        if self.result.temp_file is not None:
            os.remove(self.result.temp_file.name)

    @pyqtSlot(QPoint)
    def open_menu(self, position: QPoint) -> None:
        selected_cells = self.table_selection_model.selectedIndexes()
        if len(selected_cells) < 2:
            return
        if len(set([index.row() for index in selected_cells])) > 1:
            return
        row = selected_cells[0].row()
        columns = [index.column() for index in selected_cells]
        start = min(columns)
        end = max(columns)
        menu = QMenu()
        merge_action = menu.addAction("Merge")
        action = menu.exec_(self.view.bad_delimiters_table.mapToGlobal(position))
        if action == merge_action:
            self.bad_delimiter_table_model.merge_cells(row, start, end)


class BadDelimitersTableModel(QAbstractTableModel):

    def __init__(self,
                 bad_delimiters: List[List[str]],
                 good_records: List[List[str]],
                 columns,
                 delimiter: str):
        super(BadDelimitersTableModel, self).__init__()
        self.delimiter = delimiter
        self.current_change = -1
        self.table_changes: List[BadDelimiterChange] = []
        self.columns = columns
        max_num_values = max([len(bd) for bd in bad_delimiters])
        num_extra_columns = max_num_values - len(columns)
        self.table_headers = columns + [f"extra{i + 1}" for i in range(num_extra_columns)]
        self.bad_delimiters = bad_delimiters
        self.good_records = good_records

    def rowCount(self, parent: QModelIndex = None) -> int:
        return len(self.good_records) + len(self.bad_delimiters)

    def columnCount(self, parent: QModelIndex = None) -> int:
        return len(self.table_headers)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole) -> Any:
        row = index.row()
        column = index.column()
        if index.isValid() and role == Qt.DisplayRole:
            record = self.good_records[row] if row < 10 else self.bad_delimiters[row - 10]
            if column > len(record) - 1:
                return ""
            else:
                return (record[column]
                        + ("<EOR>" if column == len(record) - 1 and row > 9 else ""))

    def headerData(self, section: int, orientation: int, role: int = Qt.DisplayRole) -> Any:
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return self.table_headers[section]
        if orientation == Qt.Vertical and role == Qt.DisplayRole:
            return f"Good{section + 1}" if section < 10 else f"Bad{section - 9}"

    def get_row(self, row: int) -> List[str]:
        if row == -1:
            raise IndexError("Tried to get a bad delimiter row of -1")
        if row - 10 > len(self.bad_delimiters) - 1:
            raise IndexError("Tried to get a row that exceeds to the length of the row list")
        return self.bad_delimiters[row - 10]

    def get_new_row(self, row: int, start: int, end: int) -> List[str]:
        old_row = self.get_row(row)
        new_value = self.delimiter.join(old_row[start: (end + 1)])
        return old_row[:start] + [new_value] + old_row[(end + 1):]

    def merge_cells(self, row: int, start: int, end: int) -> None:
        if len(self.bad_delimiters[row - 10]) > end:
            new_row = self.get_new_row(
                row,
                start,
                end
            )
            change = BadDelimiterChange(
                row,
                start,
                end,
                self.get_row(row)
            )
            self.bad_delimiters[row - 10] = new_row
            while len(self.table_changes) - 1 > self.current_change:
                del self.table_changes[-1]
            self.table_changes.append(change)
            self.current_change += 1
            self.dataChanged.emit(self.index(row, start), self.index(row, end))

    @pyqtSlot()
    def undo_change(self) -> None:
        if not self.table_changes or self.current_change == -1:
            return
        change = self.table_changes[self.current_change]
        self.bad_delimiters[change.row - 10] = change.old_row
        self.current_change -= 1
        self.dataChanged.emit(
            self.index(change.row, change.start),
            self.index(change.row, change.end)
        )

    @pyqtSlot()
    def redo_change(self) -> None:
        if self.current_change + 1 == len(self.table_changes):
            return
        self.current_change += 1
        change = self.table_changes[self.current_change]
        self.bad_delimiters[change.row] = self.get_new_row(change.row, change.start, change.end)
        self.dataChanged.emit(
            self.index(change.row, change.start),
            self.index(change.row, change.end)
        )

    def validate_fixes(self) -> bool:
        num_columns = len(self.columns)
        return all(len(bd) == num_columns for bd in self.bad_delimiters)

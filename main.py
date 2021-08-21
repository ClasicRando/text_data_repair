from view import MainWindow
from PyQt5.QtWidgets import QApplication
import sys


style_sheet = """\
#BlueProgressBar {
    text-align: center;
    border: 2px solid #2196F3;
    border-radius: 5px;
    background-color: #E0E0E0;
}
#BlueProgressBar::chunk {
    background-color: #2196F3;
    width: 10px; 
    margin: 0.5px;
}
"""

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyleSheet(style_sheet)
    window = MainWindow()
    window.show()
    try:
        sys.exit(app.exec_())
    except Exception as ex:
        print(ex)

from PyQt5.QtWidgets import QMainWindow, QLabel


class MessageBox(QMainWindow):

    def __init__(self, title: str, content: str):
        super(MessageBox, self).__init__()
        self.setCentralWidget(QLabel(content))
        self.setWindowTitle(title)
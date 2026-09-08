"""Shared icons using Qt's existing desktop configuration."""
from PyQt5.QtGui import QIcon
from PyQt5.QtWidgets import QApplication


def themed_icon(name, fallback):
    return QIcon.fromTheme(name, QApplication.style().standardIcon(fallback))

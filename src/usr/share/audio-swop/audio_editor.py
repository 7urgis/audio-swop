"""Section editing controls shared by the rendered preview and its export."""
from dataclasses import replace

from PyQt5.QtCore import Qt, QRectF, pyqtSignal
from PyQt5.QtGui import QPainter, QPen
from PyQt5.QtWidgets import (QWidget, QGroupBox, QVBoxLayout, QHBoxLayout,
                             QLabel, QPushButton, QTableWidget, QTableWidgetItem,
                             QHeaderView, QAbstractItemView, QDoubleSpinBox, QCheckBox)
from edits import AudioSection, split_section


class SectionTimeline(QWidget):
    seekRequested = pyqtSignal(int)
    sectionSelected = pyqtSignal(int)
    sectionMoved = pyqtSignal(int, float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(82)
        self.setAccessibleName('Audio sections timeline')
        self.setToolTip('Click the ruler to seek. Drag an audio section to move it.')
        self.sections = []
        self.shift = 0
        self.duration = 1
        self.position = 0
        self.selected = 0
        self.drag = None

    def extent(self):
        return max(1, self.duration, *(s.position + self.shift +
                   (s.end - s.start if s.end is not None else 0) for s in self.sections))

    def x(self, seconds):
        return 10 + seconds / self.extent() * max(1, self.width() - 20)

    def seconds(self, x):
        return max(0, (x - 10) / max(1, self.width() - 20) * self.extent())

    def section_rect(self, section):
        start = section.position + self.shift
        end = start + section.end - section.start if section.end is not None else self.extent()
        return QRectF(self.x(max(0, start)), 30, max(2, self.x(end) - self.x(max(0, start))), 32)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect_for_background(), self.palette().base())
        painter.setPen(self.palette().text().color())
        for tick in range(6):
            seconds = self.extent() * tick / 5
            x = int(self.x(seconds))
            painter.drawLine(x, 20, x, 26)
            painter.drawText(max(0, min(x - 20, self.width() - 65)), 16,
                             f'{int(seconds) // 60}:{int(seconds) % 60:02}')
        for index, section in enumerate(self.sections):
            rect = self.section_rect(section)
            painter.setBrush(self.palette().highlight() if index == self.selected
                             else self.palette().button())
            painter.setPen(self.palette().text().color())
            painter.drawRoundedRect(rect, 4, 4)
            painter.setPen(self.palette().highlightedText().color() if index == self.selected
                           else self.palette().buttonText().color())
            painter.drawText(rect, Qt.AlignCenter, str(index + 1))
        painter.setPen(QPen(self.palette().link().color(), 2))
        painter.drawLine(int(self.x(self.position)), 20, int(self.x(self.position)), 72)

    def rect_for_background(self):
        return QRectF(0, 0, self.width(), self.height())

    def mousePressEvent(self, event):
        if event.button() != Qt.LeftButton:
            return
        if event.y() >= 30:
            for index in reversed(range(len(self.sections))):
                if self.section_rect(self.sections[index]).contains(event.pos()):
                    self.selected = index
                    self.drag = (index, event.x())
                    self.sectionSelected.emit(index)
                    self.update()
                    return
        self.seekRequested.emit(round(min(self.duration, self.seconds(event.x())) * 1000))

    def mouseReleaseEvent(self, event):
        if self.drag:
            index, x = self.drag
            self.drag = None
            if abs(event.x() - x) >= 3:
                delta = (event.x() - x) / max(1, self.width() - 20) * self.extent()
                self.sectionMoved.emit(index, round(delta, 3))


class AudioEditor(QGroupBox):
    editsChanged = pyqtSignal(object)
    renderRequested = pyqtSignal()
    seekRequested = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__('Edit new audio', parent)
        self.sections = [AudioSection()]
        self.shift = 0
        self.position = 0
        self.history = []
        self.busy = False
        self.dirty = False
        layout = QVBoxLayout(self)
        self.timeline = SectionTimeline()
        self.timeline.seekRequested.connect(self.seekRequested)
        self.timeline.sectionSelected.connect(self.select)
        self.timeline.sectionMoved.connect(self.move_section)
        layout.addWidget(self.timeline)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(['Section', 'Source in (s)', 'Source out (s)', 'Video start (s)'])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.verticalHeader().hide()
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setMaximumHeight(145)
        self.table.itemSelectionChanged.connect(self.selection_changed)
        layout.addWidget(self.table)
        buttons = QHBoxLayout()
        self.split = QPushButton('Split at playhead')
        self.split.clicked.connect(self.split_at_playhead)
        self.remove = QPushButton('Remove section')
        self.remove.clicked.connect(self.remove_section)
        self.undo = QPushButton('Undo')
        self.undo.clicked.connect(self.undo_edit)
        self.reset = QPushButton('Reset edits')
        self.reset.clicked.connect(lambda: self.commit([AudioSection()], 0))
        for button in (self.split, self.remove, self.undo, self.reset):
            buttons.addWidget(button)
        layout.addLayout(buttons)
        movement = QHBoxLayout()
        self.earlier = QPushButton('← Earlier')
        self.later = QPushButton('Later →')
        self.step = QDoubleSpinBox()
        self.step.setRange(0.001, 3600)
        self.step.setDecimals(3)
        self.step.setValue(0.1)
        self.step.setSuffix(' s')
        self.step.setAccessibleName('Audio shift step')
        self.earlier.clicked.connect(lambda: self.move_section(self.selected(), -self.step.value()))
        self.later.clicked.connect(lambda: self.move_section(self.selected(), self.step.value()))
        self.to_playhead = QPushButton('Move start to playhead')
        self.to_playhead.clicked.connect(self.move_to_playhead)
        self.following = QCheckBox('Also move following sections')
        self.following.setChecked(True)
        for widget in (self.earlier, self.step, self.later, self.to_playhead):
            movement.addWidget(widget)
        layout.addLayout(movement)
        layout.addWidget(self.following)
        help_text = QLabel('Split where sync changes, then move that section. Edit source in/out to trim; '
                           'split twice and remove to cut a middle piece. Gaps are silent. '
                           'When sections overlap, the one starting later takes over.')
        help_text.setWordWrap(True)
        layout.addWidget(help_text)
        self.message = QLabel('Audio edits affect only the new soundtrack.')
        self.message.setWordWrap(True)
        self.message.setTextFormat(Qt.PlainText)
        layout.addWidget(self.message)
        self.apply = QPushButton('Update preview with edits')
        self.apply.clicked.connect(self.renderRequested)
        layout.addWidget(self.apply)
        self.refresh(0)

    def selected(self):
        return max(0, self.table.currentRow())

    def select(self, index):
        self.table.selectRow(index)

    def selection_changed(self):
        self.timeline.selected = self.selected()
        self.timeline.update()

    def configure(self, sections, shift, reset_history=False):
        sections = list(sections) if sections is not None else [AudioSection()]
        if reset_history or sections != self.sections:
            self.history = []
        self.sections = sections
        self.shift = shift
        self.refresh(min(self.selected(), len(sections) - 1))

    def refresh(self, selected):
        self.table.blockSignals(True)
        self.table.setRowCount(len(self.sections))
        for row, section in enumerate(self.sections):
            label = QTableWidgetItem(str(row + 1))
            label.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            self.table.setItem(row, 0, label)
            for column, value in enumerate((section.start, section.end,
                                             section.position + self.shift), 1):
                spin = QDoubleSpinBox()
                spin.setRange(-86400 if column == 3 else 0, 604800)
                spin.setDecimals(3)
                spin.setSingleStep(0.1)
                spin.setKeyboardTracking(False)
                spin.setAccessibleName(f'Section {row + 1} ' + self.table.horizontalHeaderItem(column).text())
                if column == 2:
                    spin.setSpecialValueText('End of file')
                spin.setValue(value if value is not None else 0)
                spin.valueChanged.connect(lambda value, r=row, c=column: self.edit_time(r, c, value))
                old_widget = self.table.cellWidget(row, column)
                if old_widget:
                    old_widget.hide()
                self.table.setCellWidget(row, column, spin)
        self.table.selectRow(selected)
        self.table.blockSignals(False)
        self.timeline.sections = self.sections
        self.timeline.shift = self.shift
        self.timeline.selected = selected
        self.timeline.update()
        self.update_buttons()

    def update_buttons(self):
        for widget in (self.table, self.timeline, self.split, self.reset, self.earlier,
                       self.later, self.step, self.to_playhead, self.following):
            widget.setEnabled(not self.busy)
        self.remove.setEnabled(not self.busy and len(self.sections) > 1)
        self.undo.setEnabled(not self.busy and bool(self.history))
        self.apply.setEnabled(not self.busy and self.dirty)

    def set_dirty(self, dirty):
        self.dirty = dirty
        self.message.setText('Edits pending. Update the preview to hear them before saving.' if dirty
                             else 'Preview matches these edits. You can save the reviewed video.')
        self.update_buttons()

    def set_busy(self, busy):
        self.busy = busy
        self.update_buttons()

    def commit(self, sections, selected):
        if sections == self.sections:
            return
        self.history.append(list(self.sections))
        self.sections = sections
        self.refresh(selected)
        self.editsChanged.emit(list(sections))

    def edit_time(self, row, column, value):
        section = self.sections[row]
        if column == 3:
            self.move_section(row, value - self.shift - section.position)
            return
        changed = replace(section, **({'start': value} if column == 1 else {'end': value or None}))
        if changed.end is not None and changed.end <= changed.start:
            self.refresh(row)
            self.message.setText('Source out must be after source in.')
            return
        sections = list(self.sections)
        sections[row] = changed
        self.commit(sections, row)

    def split_at_playhead(self):
        row = self.selected()
        try:
            parts = split_section(self.sections[row], self.position, self.shift)
        except ValueError as error:
            self.message.setText(str(error))
            return
        self.commit(self.sections[:row] + parts + self.sections[row + 1:], row + 1)

    def move_section(self, row, delta):
        sections = list(self.sections)
        for index in range(row, len(sections) if self.following.isChecked() else row + 1):
            sections[index] = replace(sections[index], position=round(sections[index].position + delta, 3))
        self.commit(sections, row)

    def move_to_playhead(self):
        row = self.selected()
        self.move_section(row, self.position - self.shift - self.sections[row].position)

    def remove_section(self):
        if len(self.sections) > 1:
            row = self.selected()
            self.commit(self.sections[:row] + self.sections[row + 1:], max(0, row - 1))

    def undo_edit(self):
        if self.history:
            self.sections = self.history.pop()
            self.refresh(min(self.selected(), len(self.sections) - 1))
            self.editsChanged.emit(list(self.sections))

    def set_position(self, milliseconds):
        self.position = milliseconds / 1000
        self.timeline.position = self.position
        self.timeline.update()

    def set_duration(self, milliseconds):
        self.timeline.duration = milliseconds / 1000
        self.timeline.update()

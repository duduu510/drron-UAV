"""Read-only historical figure browser. Never supplies current-project metrics."""
from pathlib import PurePosixPath
from zipfile import BadZipFile, ZipFile

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt
from PySide6.QtGui import QImageReader, QPixmap
from PySide6.QtWidgets import (
    QComboBox, QHBoxLayout, QLabel, QSizePolicy, QTabWidget,
    QVBoxLayout, QWidget,
)

from vde_inspect.ui.pages.data_pages import fill_table, read_only_table


def table_data(figure):
    """Expose supplied values without interpolation, aggregation or zero fill."""
    kind = figure.get("kind")
    labels = figure.get("labels", [])
    if kind == "heatmap":
        columns = [("category", figure.get("ylabel", "责任区"))]
        columns.extend((f"v{i}", str(label)) for i, label in enumerate(figure.get("columns", [])))
        records = []
        for i, label in enumerate(labels):
            values = figure.get("values", [])
            record = {"category": label}
            for j, value in enumerate(values[i] if i < len(values) else []):
                record[f"v{j}"] = value if value is not None else "—"
            records.append(record)
        return records, columns
    if kind == "stacked":
        series = figure.get("series", [])
        columns = [("category", "分类")]
        columns.extend((f"v{i}", item.get("label", f"序列 {i + 1}")) for i, item in enumerate(series))
        records = []
        for i, label in enumerate(labels):
            row = {"category": label}
            for j, item in enumerate(series):
                values = item.get("values", [])
                value = values[i] if i < len(values) else None
                row[f"v{j}"] = value if value is not None else "—"
            records.append(row)
        return records, columns
    if kind == "bar":
        values = figure.get("values", [])
        records = []
        for i, label in enumerate(labels):
            value = values[i] if i < len(values) else None
            records.append({"category": label, "value": value if value is not None else "—"})
        return records, [("category", figure.get("ylabel" if figure.get("horizontal") else "xlabel", "分类")), ("value", figure.get("xlabel" if figure.get("horizontal") else "ylabel", "数值"))]
    records = []
    for item in figure.get("series", []):
        xs, ys = item.get("x", []), item.get("y", [])
        for i in range(max(len(xs), len(ys))):
            x, y = xs[i] if i < len(xs) else None, ys[i] if i < len(ys) else None
            records.append({"series": item.get("label", ""), "x": x if x is not None else "—", "y": y if y is not None else "—"})
    return records, [("series", "序列"), ("x", figure.get("xlabel", "横轴")), ("y", figure.get("ylabel", "纵轴"))]


class FigurePreview(QLabel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.original = None
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setWordWrap(True)
        self.setMinimumSize(200, 160)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)

    def set_image(self, pixmap):
        self.original = pixmap
        self.update_image()

    def update_image(self):
        if self.original is not None:
            self.setPixmap(self.original.scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.update_image()


class HistoricalAnalysisPage(QWidget):
    def __init__(self, archive=None, parent=None):
        super().__init__(parent)
        self.archive = archive
        self.figures = (archive or {}).get("figures", [])
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 24)
        heading = QLabel("历史实验图表")
        heading.setObjectName("pageTitle")
        layout.addWidget(heading)
        provenance = (archive or {}).get("provenance_label", "尚未加载历史图表档案")
        self.provenance_label = QLabel(provenance + "。此处仅浏览历史档案，与当前项目及当前求解方案分别展示。")
        self.provenance_label.setWordWrap(True)
        layout.addWidget(self.provenance_label)
        bar = QHBoxLayout()
        bar.addWidget(QLabel("选择图表"))
        self.figure_picker = QComboBox()
        self.figure_picker.setMinimumContentsLength(15)
        self.figure_picker.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        for figure in self.figures:
            self.figure_picker.addItem(f"{figure.get('id', '')}　{figure.get('title', '')}")
        self.figure_picker.setEnabled(bool(self.figures))
        bar.addWidget(self.figure_picker, 1)
        layout.addLayout(bar)
        self.title_label = QLabel()
        self.title_label.setObjectName("panelTitle")
        self.title_label.setWordWrap(True)
        layout.addWidget(self.title_label)
        self.tabs = QTabWidget()
        self.image_preview = FigurePreview()
        self.tabs.addTab(self.image_preview, "原始图表")
        self.data_table = read_only_table()
        self.tabs.addTab(self.data_table, "数值明细")
        layout.addWidget(self.tabs, 1)
        self.note_label = QLabel()
        self.note_label.setWordWrap(True)
        layout.addWidget(self.note_label)
        self.source_label = QLabel()
        self.source_label.setWordWrap(True)
        self.source_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.source_label)
        self.figure_picker.currentIndexChanged.connect(self.show_figure)
        self.show_figure(0 if self.figures else -1)

    def show_figure(self, index):
        if index < 0 or index >= len(self.figures):
            self.title_label.setText("暂无历史图表")
            self.image_preview.setText("历史图表档案未加载。当前项目的实验分析将在真实数据接入后提供。")
            self.note_label.clear()
            self.source_label.clear()
            return
        figure = self.figures[index]
        self.title_label.setText(figure.get("title", figure.get("id", "")))
        self.note_label.setText(figure.get("note", ""))
        details = []
        if figure.get("hline") is not None:
            details.append(f"横向参考线：{figure['hline']}")
        if figure.get("vline") is not None:
            details.append(f"纵向参考线：{figure['vline']}")
        if figure.get("missing_x"):
            details.append("缺失横轴点：" + str(figure["missing_x"]))
        if details:
            self.note_label.setText(self.note_label.text() + "\n" + "；".join(details))
        dataset = self.archive.get("dataset_id", "—")
        self.source_label.setText(f"数据来源：{figure.get('source', '未注明')}　档案 SHA256：{dataset}")
        self.source_label.setToolTip(self.archive.get("source_path", ""))
        records, columns = table_data(figure)
        fill_table(self.data_table, records, columns)
        self.load_preview(figure)

    def load_preview(self, figure):
        self.image_preview.original = None
        self.image_preview.clear()
        path = self.archive.get("source_path")
        if not path:
            self.image_preview.setText("原始图片不可用，可查看数值明细。")
            self.tabs.setCurrentIndex(1)
            return
        try:
            with ZipFile(path) as archive:
                matches = [info for info in archive.infolist() if PurePosixPath(info.filename).name == figure.get("id", "") + ".png"]
                if len(matches) != 1:
                    raise ValueError("未找到唯一对应的原始 PNG 图表")
                info = matches[0]
                if info.file_size > 32 * 1024 * 1024:
                    raise ValueError("原始图片超过预览大小限制")
                data = archive.read(info)
            buffer = QBuffer()
            buffer.setData(QByteArray(data))
            buffer.open(QIODevice.OpenModeFlag.ReadOnly)
            reader = QImageReader(buffer, b"png")
            size = reader.size()
            if size.width() <= 0 or size.height() <= 0 or size.width() * size.height() > 40_000_000:
                raise ValueError("原始图片尺寸无效或超过预览限制")
            image = reader.read()
            if image.isNull():
                raise ValueError("原始 PNG 无法解码")
            self.image_preview.set_image(QPixmap.fromImage(image))
        except (OSError, BadZipFile, KeyError, ValueError, RuntimeError) as exc:
            self.image_preview.setText(f"原图预览不可用：{exc}\n可查看数值明细。")

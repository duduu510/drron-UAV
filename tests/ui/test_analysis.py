from PySide6.QtGui import QImage
from zipfile import ZipFile

from vde_inspect.ui.pages.analysis import HistoricalAnalysisPage


def archive(figures, source_path=""):
    return {"dataset_id": "source-sha", "source_path": source_path, "provenance_label": "历史实验数据（未独立复核）", "figures": figures}


def test_picker_switches_series_data_and_preserves_missing_values(qtbot):
    data = archive([
        {"id": "first", "title": "成本", "kind": "bar", "labels": ["A"], "values": [20491.15], "source": "cost.csv"},
        {"id": "second", "title": "窗口", "kind": "line", "xlabel": "分钟", "ylabel": "元", "series": [{"label": "实验", "x": [210, 240], "y": [None, 20491.15]}], "note": "未完成不能比较成本", "source": "window.csv"},
    ])
    page = HistoricalAnalysisPage(data)
    qtbot.addWidget(page)
    assert page.figure_picker.count() == 2
    assert page.data_table.item(0, 1).text() == "20491.15"
    page.figure_picker.setCurrentIndex(1)
    assert page.data_table.rowCount() == 2
    assert page.data_table.item(0, 2).text() == "—"
    assert page.data_table.item(1, 2).text() == "20491.15"
    assert "window.csv" in page.source_label.text()
    assert "未完成" in page.note_label.text()
    assert "历史" in page.provenance_label.text()


def test_heatmap_numeric_table_keeps_region_axes(qtbot):
    page = HistoricalAnalysisPage(archive([{"id": "heat", "title": "责任区", "kind": "heatmap", "labels": ["P1", "P2"], "columns": ["P1", "P2"], "values": [[1, 2], [3, 4]]}]))
    qtbot.addWidget(page)
    assert page.data_table.horizontalHeaderItem(1).text() == "P1"
    assert page.data_table.item(1, 0).text() == "P2"
    assert page.data_table.item(1, 2).text() == "4"


def test_original_png_preview_loads_from_zip_without_extraction(qtbot, tmp_path):
    png = tmp_path / "source.png"
    image = QImage(64, 32, QImage.Format.Format_RGB32)
    image.fill(0xFFFFFFFF)
    assert image.save(str(png))
    source = tmp_path / "figures.zip"
    with ZipFile(source, "w") as output:
        output.write(png, "nested/first.png")
    page = HistoricalAnalysisPage(archive([{"id": "first", "title": "原图", "kind": "bar", "labels": [], "values": []}], str(source)))
    qtbot.addWidget(page)
    assert page.image_preview.original is not None
    assert page.image_preview.original.width() == 64
    assert not (tmp_path / "nested").exists()


def test_no_archive_shows_honest_empty_state(qtbot):
    page = HistoricalAnalysisPage(None)
    qtbot.addWidget(page)
    assert page.figure_picker.count() == 0
    assert not page.figure_picker.isEnabled()
    assert page.data_table.rowCount() == 0

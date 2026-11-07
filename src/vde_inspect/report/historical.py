"""Read genuine historical figure data without interpreting it as a solution.

Only JSON is read from the archive; archive members are never extracted.
The archive SHA256 identifies the source artifact, not a solver run or a
current-project input snapshot. Null observations are retained as missing.
"""
import hashlib
import io
import json
import math
from pathlib import Path, PurePosixPath
import re
import zipfile


MAX_ARCHIVE_BYTES = 50 * 1024 * 1024
MAX_JSON_BYTES = 5 * 1024 * 1024
MAX_MEMBER_BYTES = 10 * 1024 * 1024
MAX_TOTAL_BYTES = 100 * 1024 * 1024
MAX_MEMBERS = 512
MAX_FIGURES = 256
PROVENANCE_LABEL = "历史实验数据（未独立复核）"


def _text(value, field, *, empty=False):
    if not isinstance(value, str) or (not empty and not value.strip()):
        raise ValueError(f"{field} 必须是字符串")


def _finite_json(value, depth=0):
    if depth > 64:
        raise ValueError("JSON 嵌套过深")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            finite = math.isfinite(value)
        except OverflowError:
            finite = False
        if not finite:
            raise ValueError("历史数据包含非有限数值")
    elif isinstance(value, dict):
        for item in value.values():
            _finite_json(item, depth + 1)
    elif isinstance(value, list):
        for item in value:
            _finite_json(item, depth + 1)


def _numbers(values, field, *, missing=False):
    if not isinstance(values, list):
        raise ValueError(f"{field} 必须是数组")
    for value in values:
        if value is None and missing:
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{field} 必须包含数值" + ("或缺失值 null" if missing else ""))


def _labels(values, field):
    if not isinstance(values, list):
        raise ValueError(f"{field} 必须是数组")
    for value in values:
        _text(value, field)


def _validate_figures(figures):
    if not isinstance(figures, list) or not 0 < len(figures) <= MAX_FIGURES:
        raise ValueError("figure_data 必须是非空图表数组且不超过 256 张")
    _finite_json(figures)
    seen = set()
    for figure in figures:
        if not isinstance(figure, dict):
            raise ValueError("图表条目必须是对象")
        for key in ("id", "kind", "title", "xlabel", "ylabel", "note", "source"):
            _text(figure.get(key), key, empty=key in ("xlabel", "ylabel", "note"))
        identity = figure["id"]
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", identity) or identity in seen:
            raise ValueError(f"图表 ID 不合法或重复: {identity}")
        seen.add(identity)
        kind = figure["kind"]
        if kind not in ("line", "scatter", "bar", "stacked", "heatmap"):
            raise ValueError(f"不支持的历史图表类型: {kind}")
        for key in ("horizontal", "full_width"):
            if key in figure and not isinstance(figure[key], bool):
                raise ValueError(f"{key} 必须是布尔值")
        for key in ("hline", "vline"):
            if key in figure:
                _numbers([figure[key]], key)
        for key in ("xticks", "missing_x"):
            if key in figure:
                _numbers(figure[key], key)

        if kind in ("bar", "stacked", "heatmap"):
            _labels(figure.get("labels"), "labels")
        if kind == "bar":
            _numbers(figure.get("values"), "values", missing=True)
            if len(figure["labels"]) != len(figure["values"]):
                raise ValueError("labels 与 values 长度不一致")
        elif kind == "heatmap":
            _labels(figure.get("columns"), "columns")
            matrix = figure.get("values")
            if not isinstance(matrix, list) or len(matrix) != len(figure["labels"]):
                raise ValueError("热图行数与 labels 不一致")
            for row in matrix:
                _numbers(row, "values", missing=True)
                if len(row) != len(figure["columns"]):
                    raise ValueError("热图列数与 columns 不一致")
        else:
            series = figure.get("series")
            if not isinstance(series, list) or not series:
                raise ValueError("series 必须是非空数组")
            for item in series:
                if not isinstance(item, dict):
                    raise ValueError("series 条目必须是对象")
                _text(item.get("label"), "series.label")
                if kind == "stacked":
                    _numbers(item.get("values"), "series.values", missing=True)
                    if len(item["values"]) != len(figure["labels"]):
                        raise ValueError("series.values 与 labels 长度不一致")
                else:
                    _numbers(item.get("x"), "series.x")
                    _numbers(item.get("y"), "series.y", missing=True)
                    if len(item["x"]) != len(item["y"]):
                        raise ValueError("series 的 x/y 长度不一致")
                for key in ("step", "marker_only"):
                    if key in item and not isinstance(item[key], bool):
                        raise ValueError(f"{key} 必须是布尔值")


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"重复 JSON 字段: {key}")
        result[key] = value
    return result


def _reject_constant(value):
    raise ValueError(f"历史数据包含非有限数值: {value}")


def load_historical_archive(path: Path) -> dict:
    """Load raw figures and provenance under bounded, extraction-free ZIP I/O."""
    path = Path(path).resolve()
    with path.open("rb") as stream:
        raw = stream.read(MAX_ARCHIVE_BYTES + 1)
    if len(raw) > MAX_ARCHIVE_BYTES:
        raise ValueError("历史图表压缩包大小超过限制")
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            members = archive.infolist()
            if len(members) > MAX_MEMBERS:
                raise ValueError("压缩包条目数超过限制")
            candidates = []
            total = 0
            member_names = set()
            for info in members:
                member = PurePosixPath(info.filename)
                if (member.is_absolute() or ".." in member.parts or
                        "\\" in info.filename or ":" in info.filename or
                        info.filename in member_names):
                    raise ValueError("压缩包包含不安全路径或重复条目")
                member_names.add(info.filename)
                total += info.file_size
                if info.file_size > MAX_MEMBER_BYTES or total > MAX_TOTAL_BYTES:
                    raise ValueError("压缩包解压后大小超过限制")
                if not info.is_dir() and member.name == "figure_data.json":
                    candidates.append(info)
            if len(candidates) != 1:
                raise ValueError("压缩包必须且只能包含一个 figure_data.json")
            if candidates[0].file_size > MAX_JSON_BYTES:
                raise ValueError("figure_data.json 大小超过限制")
            with archive.open(candidates[0]) as stream:
                data = stream.read(MAX_JSON_BYTES + 1)
            if len(data) > MAX_JSON_BYTES:
                raise ValueError("figure_data.json 大小超过限制")
            figures = json.loads(data.decode("utf-8-sig"), object_pairs_hook=_unique_object,
                                 parse_constant=_reject_constant)
            _validate_figures(figures)
    except (zipfile.BadZipFile, zipfile.LargeZipFile, UnicodeError, json.JSONDecodeError,
            RuntimeError, RecursionError, NotImplementedError) as exc:
        raise ValueError(f"无效历史图表压缩包: {exc}") from exc
    return {"dataset_id": hashlib.sha256(raw).hexdigest(), "source_path": str(path),
            "figures": figures, "provenance_label": PROVENANCE_LABEL}

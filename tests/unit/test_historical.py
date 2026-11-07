import hashlib
import json
import zipfile

import pytest

from vde_inspect.report import historical
from vde_inspect.report.historical import load_historical_archive


def figure(kind="line"):
    common = dict(id="cost", kind=kind, title="Historical cost", xlabel="Round",
                  ylabel="CNY", note="Source experiment", source="convergence.csv")
    if kind in ("line", "scatter"):
        common["series"] = [{"label": "Cost", "x": [1, 2], "y": [None, 20491.1477]}]
    elif kind == "bar":
        common.update(labels=["V2", "V4"], values=[22, 1])
    elif kind == "stacked":
        common.update(labels=["P1", "P2"], series=[{"label": "V2", "values": [3, 8]}])
    elif kind == "heatmap":
        common.update(labels=["P1"], columns=["P1", "P2"], values=[[43.5215, 1.1198]])
    return common


def archive(tmp_path, payload, name="figures/figure_data.json", extra=None):
    path = tmp_path / "history.zip"
    with zipfile.ZipFile(path, "w") as stream:
        stream.writestr(name, json.dumps(payload, ensure_ascii=False))
        if extra:
            stream.writestr(*extra)
    return path


@pytest.mark.parametrize("kind", ["line", "bar", "stacked", "scatter", "heatmap"])
def test_loads_original_numerical_schema_and_provenance(tmp_path, kind):
    payload = [figure(kind)]
    path = archive(tmp_path, payload)
    loaded = load_historical_archive(path)
    assert loaded["dataset_id"] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert loaded["source_path"] == str(path.resolve())
    assert loaded["figures"] == payload
    assert loaded["provenance_label"] == "历史实验数据（未独立复核）"
    assert "solution_id" not in loaded and "events" not in loaded
    assert not (tmp_path / "figures").exists()


def test_preserves_explicit_missing_observations(tmp_path):
    loaded = load_historical_archive(archive(tmp_path, [figure()]))
    assert loaded["figures"][0]["series"][0]["y"] == [None, 20491.1477]


@pytest.mark.parametrize("mutate", [
    lambda f: f.update(id=""), lambda f: f.update(kind="unknown"),
    lambda f: f.update(title=None), lambda f: f.update(source=[]),
    lambda f: f["series"][0].update(y=[1]),
    lambda f: f["series"][0].update(y=[True, 1]),
    lambda f: f["series"][0].update(x=[None, 2]),
    lambda f: f["series"][0].update(y=[float("inf"), 2]),
    lambda f: f.update(hline=float("nan")),
])
def test_rejects_invalid_figure_data(tmp_path, mutate):
    payload = figure()
    mutate(payload)
    with pytest.raises(ValueError):
        load_historical_archive(archive(tmp_path, [payload]))


def test_rejects_duplicate_figure_ids(tmp_path):
    with pytest.raises(ValueError):
        load_historical_archive(archive(tmp_path, [figure(), figure()]))


@pytest.mark.parametrize("payload", [{}, [None], []])
def test_rejects_invalid_root(tmp_path, payload):
    with pytest.raises(ValueError):
        load_historical_archive(archive(tmp_path, payload))


@pytest.mark.parametrize("extra", [("../escape.txt", "outside"),
                                    ("other/figure_data.json", "[]")])
def test_rejects_unsafe_or_ambiguous_archive(tmp_path, extra):
    path = archive(tmp_path, [figure()], extra=extra)
    with pytest.raises(ValueError):
        load_historical_archive(path)
    assert not (tmp_path.parent / "escape.txt").exists()


def test_rejects_oversize_before_parsing(tmp_path, monkeypatch):
    path = archive(tmp_path, [figure()])
    monkeypatch.setattr(historical, "MAX_JSON_BYTES", 10)
    with pytest.raises(ValueError, match="大小"):
        load_historical_archive(path)


def test_corrupt_archive_is_a_validation_error(tmp_path):
    path = tmp_path / "bad.zip"
    path.write_bytes(b"invalid ZIP")
    with pytest.raises(ValueError):
        load_historical_archive(path)

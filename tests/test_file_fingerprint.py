from datetime import datetime, timezone

from aiva_collector.file_fingerprint import build_file_id, compute_file_sha256, compute_normalized_data_hash


def test_file_sha256_is_stable(tmp_path):
    path = tmp_path / "ventas.csv"
    path.write_text("producto,cantidad\nA,1\n", encoding="utf-8")

    assert compute_file_sha256(path) == compute_file_sha256(path)


def test_same_name_different_content_changes_file_hash(tmp_path):
    path = tmp_path / "ventas.csv"
    path.write_text("A", encoding="utf-8")
    first = compute_file_sha256(path)
    path.write_text("B", encoding="utf-8")

    assert compute_file_sha256(path) != first


def test_normalized_data_hash_is_stable_and_ignores_runtime_timestamps():
    rows = [{"producto_nombre": " A ", "cantidad_vendida": "1,0", "fecha": datetime(2026, 6, 1, tzinfo=timezone.utc)}]
    first = compute_normalized_data_hash({"rows": rows, "processed_at": "2026-06-25T10:00:00Z"})
    second = compute_normalized_data_hash({"rows": rows, "processed_at": "2026-06-25T11:00:00Z"})

    assert first == second


def test_file_id_is_stable():
    assert build_file_id("abc", "ventas.xlsx") == build_file_id("abc", "ventas.xlsx")

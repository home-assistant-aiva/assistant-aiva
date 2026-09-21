from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
import copy
import json

from aiva_collector.config import CollectorConfig
from aiva_collector.errors import ValidationError
from aiva_collector.normalizer import normalize_rows
from aiva_collector.summarizer import build_summary, idempotency_key


def make(days=35, complete=True):
    mapping = {
        k: k
        for k in [
            "fecha",
            "producto_codigo",
            "producto_nombre",
            "categoria",
            "cantidad_vendida",
            "precio_venta",
            "costo_unitario",
            "stock_actual",
            "descuento",
        ]
    }
    config = CollectorConfig(
        {
            "commerce_id": "synthetic",
            "collector_id": "collector",
            "daily_snapshot_complete": complete,
            "column_mapping": mapping,
        },
        Path("synthetic.json"),
    )
    raw = [
        {
            "fecha": str(date(2026, 8, 17) + timedelta(days=i)),
            "producto_codigo": code,
            "producto_nombre": "Producto " + code,
            "categoria": "Cat",
            "cantidad_vendida": str(i + 1),
            "precio_venta": str(price),
            "costo_unitario": str(cost),
            "stock_actual": "100",
            "descuento": "0",
        }
        for i in range(days)
        for code, price, cost in [("A", 10, 4), ("B", 20, 8)]
    ]
    return config, raw


def summarize(config, raw, discarded=0):
    rows = normalize_rows(raw, config).rows
    return build_summary(rows, config, 1, len(raw), discarded)


def test_daily_exact_35_days():
    config, raw = make()
    result = summarize(config, raw)
    snap = result["daily_snapshot"]
    assert result["source_schema_version"] == "2.0.0"
    assert len(snap["metrics"]) == 70 and len(snap["coverage"]) == 35
    assert (
        sum(
            Decimal(m["net_revenue"])
            for m in snap["metrics"]
            if m["business_date"] >= "2026-09-14"
        )
        == 6720
    )
    assert all(d["status"] == "complete" for d in snap["coverage"])
    assert raw[0]["cantidad_vendida"] == "1"


def test_unknown_and_discarded_never_complete():
    c, r = make(complete=False)
    assert {d["status"] for d in summarize(c, r)["daily_snapshot"]["coverage"]} == {
        "unknown"
    }
    c, r = make()
    assert {d["status"] for d in summarize(c, r, 1)["daily_snapshot"]["coverage"]} == {
        "unknown"
    }


def test_zero_is_explicit_missing_not_filled():
    c, r = make(7)
    r = [row for row in r if row["fecha"] != "2026-08-19"]
    for row in r:
        if row["fecha"] == "2026-08-20":
            row["cantidad_vendida"] = "0"
    snap = summarize(c, r)["daily_snapshot"]
    assert len(snap["coverage"]) == 6
    assert any(d["business_date"] == "2026-08-20" for d in snap["coverage"])
    assert not any(d["business_date"] == "2026-08-19" for d in snap["coverage"])


def test_exact_decimal_and_idempotency():
    c, r = make(1)
    r[0].update(precio_venta="0.100001", cantidad_vendida="3")
    one = summarize(c, r)
    two = summarize(c, r)
    assert one["daily_snapshot"]["metrics"][0]["net_revenue"] == "0.300003"
    assert idempotency_key(one) == idempotency_key(two)
    assert idempotency_key(one) == idempotency_key(json.loads(json.dumps(one)))
    changed = copy.deepcopy(one)
    changed["daily_snapshot"]["metrics"][0]["net_revenue"] = "0.300004"
    assert idempotency_key(one) != idempotency_key(changed)
    for key in ["commerce_id", "collector_id"]:
        changed = copy.deepcopy(one)
        changed[key] = "other"
        assert idempotency_key(one) != idempotency_key(changed)


def test_stock_ambiguous_and_partial_cost_unknown():
    c, r = make(1)
    other = dict(r[0], stock_actual="90", costo_unitario="")
    r.append(other)
    m = summarize(c, r)["daily_snapshot"]["metrics"][0]
    assert m["closing_stock"] is None and m["cogs"] is None


def test_legacy_explicit_and_discount_guard():
    import pytest

    c, r = make(1)
    c.raw["source_schema_version"] = "1.0.0"
    assert "daily_snapshot" not in summarize(c, r)
    c.raw["source_schema_version"] = "2.0.0"
    r[0]["descuento"] = "1"
    with pytest.raises(ValidationError, match="discount"):
        summarize(c, r)


def test_timezone_and_unmapped_discount():
    c, r = make(1)
    r[0]["fecha"] = "2026-08-17T01:00:00+00:00"
    assert normalize_rows(r, c).rows[0]["fecha"] == date(2026, 8, 16)
    c.raw["column_mapping"].pop("descuento")
    r[0]["Descuento"] = "2"
    r[0].pop("descuento")
    import pytest

    with pytest.raises(ValidationError, match="discount"):
        summarize(c, r)


def test_multiple_files_never_merge_snapshots():
    import pytest

    c, r = make(1)
    c.raw["source_schema_version"] = "2.0.0"
    with pytest.raises(ValidationError, match="one file"):
        build_summary(normalize_rows(r, c).rows, c, 2, len(r), 0)


def test_upgrade_sequence_and_offline_retry_without_source(tmp_path, monkeypatch):
    from aiva_collector.local_state import (
        connect,
        next_daily_revision,
        upsert_detected_file,
        update_file_state,
    )
    from aiva_collector.offline_queue import enqueue_payload, process_queue

    c, r = make(7)
    c.raw.update(state_dir=str(tmp_path / "state"), move_processed_files=False)
    summary = summarize(c, r)
    conn = connect(tmp_path / "state" / "local.sqlite")
    first = next_daily_revision(conn)
    monkeypatch.setattr("time.time_ns", lambda: 1)
    assert next_daily_revision(conn) > first
    source = tmp_path / "synthetic.xlsx"
    source.write_bytes(b"synthetic")
    upsert_detected_file(
        conn,
        file_id="synthetic-file",
        commerce_id=c.commerce_id,
        collector_id=c.collector_id,
        path=source,
        file_sha256="synthetic",
    )
    update_file_state(conn, "synthetic-file", status="pending_send")
    queued = enqueue_payload(conn, c, file_id="synthetic-file", payload=summary)
    source.unlink()
    conn.close()
    conn = connect(tmp_path / "state" / "local.sqlite")
    assert next_daily_revision(conn) > first
    seen = []

    class Client:
        def send_summary(self, payload):
            seen.append(payload)
            return {"summary_id": "synthetic"}

    monkeypatch.setattr(
        "aiva_collector.readers.read_file",
        lambda *a, **kw: (_ for _ in ()).throw(
            AssertionError("must not reread source")
        ),
    )
    result = process_queue(conn, c, client=Client(), force=True)
    assert result.sent == 1 and seen == [summary]
    assert idempotency_key(seen[0]) == queued["idempotency_key"]
    conn.close()


def test_partially_undated_file_never_falls_back_to_complete_legacy():
    c, r = make(7)
    r[0]["fecha"] = "invalid"
    result = summarize(c, r)
    assert result["source_schema_version"] == "2.0.0"
    assert {d["status"] for d in result["daily_snapshot"]["coverage"]} == {"unknown"}

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any


CANONICAL_FIELDS = (
    "fecha",
    "producto_codigo",
    "producto_nombre",
    "categoria",
    "cantidad_vendida",
    "precio_venta",
    "costo_unitario",
    "stock_actual",
)
REQUIRED_FIELDS = ("producto_nombre", "cantidad_vendida", "precio_venta")
RECOMMENDED_FIELDS = ("fecha", "producto_codigo", "categoria", "costo_unitario", "stock_actual")
AUTO_APPROVED_THRESHOLD = 0.85
NEEDS_REVIEW_THRESHOLD = 0.60

ALIASES: dict[str, tuple[str, ...]] = {
    "producto_nombre": (
        "producto",
        "producto_nombre",
        "nombre_producto",
        "descripcion",
        "descripción",
        "desc",
        "articulo",
        "artículo",
        "item",
        "detalle",
        "producto descripcion",
        "nombre descripcion producto",
        "nombre producto",
        "nombre",
        "name",
    ),
    "producto_codigo": (
        "codigo",
        "código",
        "cod",
        "cod prod",
        "cod_prod",
        "codigo articulo",
        "codigo_articulo",
        "sku",
        "producto_codigo",
        "cod_articulo",
        "cod_producto",
        "codigo_producto",
        "ean",
        "barcode",
        "barra",
        "codigo_barra",
        "codigo_barras",
        "articulo",
        "artículo",
    ),
    "cantidad_vendida": (
        "cantidad",
        "cant",
        "cantidad_vendida",
        "unidades",
        "unidades_vendidas",
        "unid vend",
        "unid_vend",
        "unidades vendidas",
        "qty",
        "quantity",
        "vendido",
        "ventas",
        "cant_vendida",
    ),
    "precio_venta": (
        "precio",
        "precio_venta",
        "precio unitario",
        "precio unit",
        "precio_unitario",
        "precio_unit",
        "pvp",
        "venta",
        "valor_unitario",
        "importe_unitario",
        "precio final",
        "precio_final",
        "precio venta",
        "precio_venta",
        "price",
    ),
    "costo_unitario": (
        "costo",
        "costo_unitario",
        "precio_costo",
        "costo compra",
        "costo_compra",
        "costo unitario",
        "compra",
        "precio_compra",
        "cost",
    ),
    "stock_actual": (
        "stock",
        "stock_actual",
        "existencia",
        "existencias",
        "inventario",
        "inventory",
        "disponible",
        "unidades_stock",
        "stock disponible",
        "stock_disponible",
    ),
    "fecha": (
        "fecha",
        "fecha_venta",
        "fecha venta",
        "dia",
        "día",
        "date",
        "fecha_movimiento",
        "fecha comprobante",
        "fecha_comprobante",
    ),
    "categoria": (
        "categoria",
        "categoría",
        "rubro",
        "familia",
        "linea",
        "línea",
        "grupo",
        "departamento",
        "category",
        "seccion",
        "sección",
    ),
}

FIELD_LABELS = {
    "fecha": "fecha",
    "producto_codigo": "codigo",
    "producto_nombre": "producto",
    "categoria": "categoria",
    "cantidad_vendida": "cantidad",
    "precio_venta": "precio",
    "costo_unitario": "costo",
    "stock_actual": "stock",
}


@dataclass(frozen=True)
class ColumnMappingResult:
    mapping: dict[str, str]
    confidence: float
    status: str
    missing_required: list[str]
    warnings: list[str]
    detected_headers: list[str]
    scores: dict[str, float] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "mapping": self.mapping,
            "confidence": self.confidence,
            "status": self.status,
            "missing_required": self.missing_required,
            "warnings": self.warnings,
            "detected_headers": self.detected_headers,
            "scores": self.scores,
        }


def normalize_header(value: Any) -> str:
    text = "" if value is None else str(value)
    text = unicodedata.normalize("NFKD", text.strip().lower())
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[\s\-.]+", "_", text)
    text = re.sub(r"[^a-z0-9_]", "", text)
    text = re.sub(r"_+", "_", text).strip("_")
    return text


NORMALIZED_ALIASES = {
    field: tuple(dict.fromkeys(normalize_header(alias) for alias in aliases if normalize_header(alias)))
    for field, aliases in ALIASES.items()
}


def detect_column_mapping(headers: list[str] | tuple[str, ...] | set[str]) -> ColumnMappingResult:
    detected_headers = [str(header).strip() for header in headers if str(header).strip()]
    normalized_headers = {header: normalize_header(header) for header in detected_headers}
    used_headers: set[str] = set()
    mapping: dict[str, str] = {}
    scores: dict[str, float] = {}
    warnings: list[str] = []

    for field in CANONICAL_FIELDS:
        best_header = None
        best_score = 0.0
        for header, normalized in normalized_headers.items():
            if header in used_headers:
                continue
            score = _score_header(field, normalized)
            if score > best_score:
                best_header = header
                best_score = score
        if best_header and best_score >= 0.60:
            mapping[field] = best_header
            scores[field] = round(best_score, 3)
            used_headers.add(best_header)

    _prefer_product_name_when_better(mapping, scores, normalized_headers, used_headers)
    _prefer_description_as_product_name(mapping, scores, normalized_headers, used_headers)

    missing_required = [field for field in REQUIRED_FIELDS if field not in mapping]
    confidence = _confidence(scores, missing_required)
    if missing_required:
        status = "failed" if confidence < NEEDS_REVIEW_THRESHOLD else "needs_review"
        warnings.append("Faltan campos requeridos: " + ", ".join(FIELD_LABELS[field] for field in missing_required))
    elif confidence >= AUTO_APPROVED_THRESHOLD:
        status = "auto_approved"
    elif confidence >= NEEDS_REVIEW_THRESHOLD:
        status = "needs_review"
        warnings.append("AIVA detectó columnas con confianza media; revisar desde el admin.")
    else:
        status = "failed"
        warnings.append("AIVA no pudo detectar un mapeo confiable.")

    for field in RECOMMENDED_FIELDS:
        if field not in mapping:
            warnings.append(f"Campo recomendado no detectado: {FIELD_LABELS[field]}")

    return ColumnMappingResult(
        mapping=mapping,
        confidence=round(confidence, 3),
        status=status,
        missing_required=missing_required,
        warnings=warnings,
        detected_headers=detected_headers,
        scores=scores,
    )


def validate_explicit_mapping(mapping: dict[str, str], headers: list[str] | set[str] | tuple[str, ...]) -> ColumnMappingResult:
    detected_headers = [str(header).strip() for header in headers if str(header).strip()]
    normalized_to_header = {normalize_header(header): header for header in detected_headers}
    resolved: dict[str, str] = {}
    warnings: list[str] = []
    for field, source in mapping.items():
        if field not in CANONICAL_FIELDS:
            continue
        source_text = str(source).strip()
        if source_text in detected_headers:
            resolved[field] = source_text
            continue
        normalized_source = normalize_header(source_text)
        if normalized_source in normalized_to_header:
            resolved[field] = normalized_to_header[normalized_source]
            continue
        warnings.append(f"Mapping explícito inválido: {field} -> {source_text}")

    missing_required = [field for field in REQUIRED_FIELDS if field not in resolved]
    if missing_required:
        status = "failed"
        confidence = 0.0
    else:
        status = "auto_approved"
        confidence = 1.0
    return ColumnMappingResult(
        mapping=resolved,
        confidence=confidence,
        status=status,
        missing_required=missing_required,
        warnings=warnings,
        detected_headers=detected_headers,
        scores={field: 1.0 for field in resolved},
    )


def sample_preview(rows: list[dict[str, Any]], headers: list[str], *, include_values: bool = False) -> list[dict[str, Any]]:
    if not include_values:
        return []
    selected_headers = headers[:10]
    preview: list[dict[str, Any]] = []
    for row in rows[:3]:
        preview.append({header: _safe_preview_value(row.get(header)) for header in selected_headers})
    return preview


def _safe_preview_value(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if "@" in text or re.search(r"\b\d{7,}\b", text):
        return "[redacted]"
    return text[:80]


def _score_header(field: str, normalized_header: str) -> float:
    if not normalized_header:
        return 0.0
    if normalized_header == field:
        return 1.0
    aliases = NORMALIZED_ALIASES[field]
    if normalized_header in aliases:
        return 0.95
    strong_terms = set(aliases) | {normalize_header(field)}
    if any(term and (normalized_header.startswith(term + "_") or normalized_header.endswith("_" + term)) for term in strong_terms):
        return 0.80
    if any(term and term in normalized_header and len(term) >= 4 for term in strong_terms):
        return 0.78
    similarity = max(SequenceMatcher(None, normalized_header, alias).ratio() for alias in aliases)
    if similarity >= 0.88:
        return min(0.85, similarity)
    if similarity >= 0.78:
        return max(0.70, min(0.78, similarity))
    return 0.0


def _confidence(scores: dict[str, float], missing_required: list[str]) -> float:
    required_scores = [scores.get(field, 0.0) for field in REQUIRED_FIELDS]
    optional_scores = [scores.get(field, 0.0) for field in RECOMMENDED_FIELDS]
    score = (sum(required_scores) / len(REQUIRED_FIELDS)) * 0.9 + (sum(optional_scores) / len(RECOMMENDED_FIELDS)) * 0.1
    if missing_required:
        score *= 0.55
    return score


def _prefer_description_as_product_name(
    mapping: dict[str, str],
    scores: dict[str, float],
    normalized_headers: dict[str, str],
    used_headers: set[str],
) -> None:
    product_header = mapping.get("producto_nombre")
    if not product_header or normalized_headers.get(product_header) not in {"articulo", "item"}:
        return
    for header, normalized in normalized_headers.items():
        if header in used_headers:
            continue
        if normalized in {"descripcion", "detalle", "nombre", "producto_descripcion"}:
            mapping["producto_nombre"] = header
            scores["producto_nombre"] = 0.95
            used_headers.discard(product_header)
            used_headers.add(header)
            if "producto_codigo" not in mapping:
                mapping["producto_codigo"] = product_header
                scores["producto_codigo"] = 0.80
                used_headers.add(product_header)
            return


def _prefer_product_name_when_better(
    mapping: dict[str, str],
    scores: dict[str, float],
    normalized_headers: dict[str, str],
    used_headers: set[str],
) -> None:
    if "producto_nombre" in mapping:
        return
    for field, header in list(mapping.items()):
        if field == "producto_codigo":
            product_name_score = _score_header("producto_nombre", normalized_headers[header])
            current_score = scores.get(field, 0.0)
            if product_name_score >= 0.90 and product_name_score > current_score:
                mapping.pop(field, None)
                scores.pop(field, None)
                mapping["producto_nombre"] = header
                scores["producto_nombre"] = round(product_name_score, 3)
                used_headers.add(header)
                return

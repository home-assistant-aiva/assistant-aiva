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
    "descuento",
    "fecha_stock",
)
REQUIRED_FIELDS = ("producto_nombre", "cantidad_vendida", "precio_venta")
RECOMMENDED_FIELDS = ("fecha", "producto_codigo", "categoria", "costo_unitario", "stock_actual")
AUTO_APPROVED_THRESHOLD = 0.85
NEEDS_REVIEW_THRESHOLD = 0.60

ALIASES: dict[str, tuple[str, ...]] = {
    "descuento": ("descuento", "discount", "bonificación"),
    "fecha_stock": ("fecha_stock", "fecha del stock", "stock_date"),
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

# Abreviaturas y sinonimos que RC8 no conocia. Solo valen por coincidencia
# exacta y puntuan por debajo de los alias de siempre: si una planilla trae
# "Kg" y "Cantidad", gana "Cantidad"; si trae "Concepto" y "Producto", gana
# "Producto". Los de 0.85 son debiles (pueden ser otra cosa en algunos ERPs).
# "Ref"/"Referencia" no estan a proposito: en muchos sistemas es el numero de
# ticket, y como codigo partiria cada producto en uno por ticket.
SECONDARY_ALIASES: dict[str, dict[str, float]] = {
    "fecha": {alias: 0.90 for alias in ("fec", "fch", "f_venta", "f_vta", "fecha_vta", "fec_venta", "f_emision",
                                         "fecha_emision", "fecha_operacion", "fecha_de_venta", "fecha_factura",
                                         "emision", "dia_venta")},
    "producto_codigo": {
        **{alias: 0.90 for alias in ("cod_barras", "codigo_de_barras", "gtin", "upc", "plu", "cod_int",
                                     "codigo_interno", "id_articulo", "id_producto", "nro_articulo", "cod_art", "art")},
    },
    "producto_nombre": {
        **{alias: 0.90 for alias in ("denominacion", "nom", "prod", "art", "nombre_articulo", "descripcion_articulo",
                                     "desc_articulo", "producto_servicio")},
        **{alias: 0.85 for alias in ("concepto",)},
    },
    "categoria": {alias: 0.90 for alias in ("cat", "rub", "fam", "subrubro", "sub_rubro")},
    "cantidad_vendida": {
        **{alias: 0.90 for alias in ("un", "unid", "uds", "u", "q", "cdad", "ctd", "cnt", "cant_vend", "vendidas")},
        **{alias: 0.85 for alias in ("kilos", "kg", "litros", "piezas")},
    },
    "precio_venta": {
        **{alias: 0.90 for alias in ("pu", "p_u", "p_unit", "p_unitario", "pr_unit", "pre_unit", "prec_unit", "precio_u",
                                     "p_venta", "p_vta", "pventa", "prec_vta", "precio_vta", "precio_neto", "imp_unit",
                                     "importe_unit", "pcio", "pcio_unit", "monto_unitario")},
        **{alias: 0.85 for alias in ("unitario",)},
    },
    "costo_unitario": {alias: 0.90 for alias in ("costo_u", "costo_unit", "cto", "cto_unit", "pcosto", "p_costo",
                                                  "precio_de_costo", "ultimo_costo", "costo_ultimo", "costo_reposicion",
                                                  "costo_promedio")},
    "stock_actual": {alias: 0.90 for alias in ("stk", "stock_final", "existencia_actual", "cant_stock", "disp")},
    "descuento": {
        **{alias: 0.90 for alias in ("bonificacion", "bonif", "dto", "dcto", "descuento_importe", "importe_descuento",
                                     "descuento_porcentaje", "porc_desc", "desc_porc", "rebaja")},
        **{alias: 0.85 for alias in ("desc",)},
    },
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
NORMALIZED_SECONDARY = {
    field: {normalize_header(alias): score for alias, score in aliases.items() if normalize_header(alias)}
    for field, aliases in SECONDARY_ALIASES.items()
}


# Campos que siempre son numeros, fechas o texto. Sirve para descartar una
# columna cuyo nombre engaña: "Desc." con importes no es la descripcion.
_NUMERIC_FIELDS = {"cantidad_vendida", "precio_venta", "costo_unitario", "stock_actual", "descuento"}
_DATE_FIELDS = {"fecha", "fecha_stock"}
_MONEY_WORDS = ("precio", "importe", "valor", "monto", "total", "costo", "pvp")
# Un nombre de producto tiene palabras separadas o minusculas ("Alfajor",
# "COCA COLA 2.25"); un codigo no ("P001", "7790895000782", "DEMO-SYN-A").
_NAME_LIKE_RE = re.compile(r"[^\W\d_]{2,}\s+[^\W_]|[a-záéíóúüñ]{3,}")
_DATE_LIKE_RE = re.compile(r"^\s*(\d{1,4})[/\-.](\d{1,2})[/\-.](\d{1,4})(?:[ T].*)?$")
_PROFILE_SAMPLE = 300


@dataclass(frozen=True)
class ColumnProfile:
    """Lo que dicen los valores de una columna, sin mirar su nombre."""

    non_empty: int
    date_share: float
    numeric_share: float
    text_share: float
    integer_share: float
    distinct_ratio: float
    median: float | None
    # Valores que parecen nombres de producto y no codigos.
    wordy_share: float = 0.0
    # Numeros enteros en el rango de fechas de Excel (1982 a 2091).
    serial_share: float = 0.0


def profile_columns(headers: list[str] | tuple[str, ...], rows: list[dict[str, Any]] | None) -> dict[str, ColumnProfile]:
    if not rows:
        return {}
    from .numeric_format import parse_decimal_with

    sample = rows[:_PROFILE_SAMPLE]
    profiles: dict[str, ColumnProfile] = {}
    for header in headers:
        values = [row.get(header) for row in sample]
        values = [value for value in values if value is not None and str(value).strip() != ""]
        if not values:
            profiles[header] = ColumnProfile(0, 0.0, 0.0, 0.0, 0.0, 0.0, None)
            continue
        dates = numbers = texts = integers = wordy = serials = 0
        numeric_values: list[float] = []
        for value in values:
            if _looks_like_date(value):
                dates += 1
                continue
            number = parse_decimal_with(value)
            if number is not None and not isinstance(value, bool):
                numbers += 1
                numeric_values.append(float(number))
                if number == number.to_integral_value():
                    integers += 1
                    if 30000 <= number <= 70000 and "." not in str(value) and "," not in str(value):
                        serials += 1
            else:
                texts += 1
                if _NAME_LIKE_RE.search(str(value)):
                    wordy += 1
        total = len(values)
        numeric_values.sort()
        median = numeric_values[len(numeric_values) // 2] if numeric_values else None
        distinct = len({str(value).strip().casefold() for value in values})
        profiles[header] = ColumnProfile(
            non_empty=total,
            date_share=dates / total,
            numeric_share=numbers / total,
            text_share=texts / total,
            integer_share=(integers / numbers) if numbers else 0.0,
            distinct_ratio=distinct / total,
            median=median,
            wordy_share=wordy / total,
            serial_share=serials / total,
        )
    return profiles


def _looks_like_date(value: Any) -> bool:
    from datetime import date, datetime

    if isinstance(value, (datetime, date)):
        return True
    if not isinstance(value, str):
        return False
    text = value.strip()
    if len(text) == 8 and text.isdigit():
        # aaaammdd: solo si es una fecha valida de este siglo.
        year, month, day = int(text[:4]), int(text[4:6]), int(text[6:])
        return 1990 <= year <= 2100 and 1 <= month <= 12 and 1 <= day <= 31
    match = _DATE_LIKE_RE.match(value)
    if not match:
        return False
    first, second, third = (int(part) for part in match.groups())
    if len(match.group(1)) == 4:
        return 1 <= second <= 12 and 1 <= third <= 31
    return 1 <= first <= 31 and 1 <= second <= 12


def _value_compatibility(field: str, profile: ColumnProfile | None) -> float:
    """1 si los valores encajan con el campo, 0 si lo contradicen."""

    if profile is None:
        return 1.0
    if profile.non_empty == 0:
        # Columna vacia en la muestra: no hay evidencia ni a favor ni en contra.
        return 0.9
    if field in _DATE_FIELDS:
        if profile.date_share >= 0.6:
            return 1.0
        if profile.serial_share >= 0.9:
            # Fechas guardadas como numero de serie de Excel: solo si el nombre
            # de la columna ya dice que es una fecha (el puntaje lo exige).
            return 0.9
        return 0.0 if profile.date_share < 0.2 else 0.5
    if field in _NUMERIC_FIELDS:
        if profile.numeric_share >= 0.8:
            return 1.0
        return 0.0 if profile.numeric_share < 0.3 else 0.5
    if field == "producto_nombre":
        if profile.date_share >= 0.6:
            return 0.0
        if profile.text_share >= 0.6:
            return 1.0 if profile.wordy_share >= 0.5 else 0.7
        return 0.25
    if field == "producto_codigo":
        if profile.date_share >= 0.6:
            return 0.0
        # "Coca Cola 2.25" o "Alfajor" son nombres; "P001" o "7790895000782", codigos.
        return 0.7 if profile.wordy_share >= 0.7 else 1.0
    if field == "categoria":
        if profile.date_share >= 0.6 or profile.numeric_share >= 0.9:
            return 0.0
        return 1.0
    return 1.0


def detect_column_mapping(
    headers: list[str] | tuple[str, ...] | set[str],
    rows: list[dict[str, Any]] | None = None,
    *,
    fill_from_values: bool = False,
    secondary_aliases: bool = True,
) -> ColumnMappingResult:
    """Sugiere que columna corresponde a cada campo.

    Mira primero el nombre de la columna y, si recibe filas, tambien sus
    valores: una columna llamada "Desc." con importes es un descuento, no la
    descripcion. La asignacion es global por puntaje, asi un campo que se
    evalua antes no le roba la columna a otro que encaja mejor.

    ``fill_from_values`` completa fecha y producto solo por los valores cuando
    ningun nombre de columna ayuda. Es para la configuracion guiada, donde una
    persona confirma; la sincronizacion automatica no lo usa.

    ``secondary_aliases=False`` reconoce solo los alias de RC8: la
    sincronizacion automatica lo usa para no cambiar lo que RC8 ya mandaba.
    """

    detected_headers = [str(header).strip() for header in headers if str(header).strip()]
    normalized_headers = {header: normalize_header(header) for header in detected_headers}
    scoring_headers = {header: _scoring_text(header, normalized) for header, normalized in normalized_headers.items()}
    profiles = profile_columns(detected_headers, rows)
    used_headers: set[str] = set()
    mapping: dict[str, str] = {}
    scores: dict[str, float] = {}
    warnings: list[str] = []

    candidates: list[tuple[float, int, int, str, str]] = []
    for field_order, field in enumerate(CANONICAL_FIELDS):
        # Sin una persona que elija el tipo de descuento, mapear "Dto." o "Bonif."
        # rechazaria el archivo entero ("descuento ambiguo"). RC8 no las tomaba.
        allow_secondary = secondary_aliases and (fill_from_values or field != "descuento")
        for header_order, header in enumerate(detected_headers):
            score = _score_header(field, scoring_headers[header], secondary=allow_secondary)
            if score <= 0:
                continue
            score *= _value_compatibility(field, profiles.get(header))
            if score >= 0.60:
                candidates.append((score, field_order, header_order, field, header))
    for score, _field_order, _header_order, field, header in sorted(candidates, key=lambda item: (-item[0], item[1], item[2])):
        if field in mapping or header in used_headers:
            continue
        mapping[field] = header
        scores[field] = round(score, 3)
        used_headers.add(header)

    _prefer_product_name_when_better(mapping, scores, normalized_headers, used_headers)
    _prefer_description_as_product_name(mapping, scores, normalized_headers, used_headers)
    if rows:
        _drop_code_that_does_not_identify_products(mapping, scores, rows, used_headers, warnings)
    if profiles and fill_from_values:
        _fill_from_values(mapping, scores, detected_headers, profiles, used_headers)

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


def _drop_code_that_does_not_identify_products(
    mapping: dict[str, str],
    scores: dict[str, float],
    rows: list[dict[str, Any]],
    used_headers: set[str],
    warnings: list[str],
) -> None:
    """Un codigo de producto no se repite con productos distintos.

    "Ref" o "Referencia" a veces es el numero de ticket: usarlo como codigo
    fundiria en uno solo todos los productos de cada ticket.
    """

    code_header = mapping.get("producto_codigo")
    name_header = mapping.get("producto_nombre")
    if not code_header or not name_header:
        return
    if _primary_score("producto_codigo", normalize_header(code_header)) > 0:
        # "Codigo", "SKU", "EAN": es el codigo aunque el comercio use uno
        # generico como "999 Varios" para varios productos.
        return
    names_by_code: dict[str, set[str]] = {}
    for row in rows[:_PROFILE_SAMPLE]:
        code = str(row.get(code_header) or "").strip()
        name = " ".join(str(row.get(name_header) or "").strip().casefold().split())
        if code and name:
            names_by_code.setdefault(code, set()).add(name)
    if len(names_by_code) < 2:
        return
    mixed = sum(1 for names in names_by_code.values() if len(names) > 1)
    if mixed / len(names_by_code) > 0.2:
        mapping.pop("producto_codigo", None)
        scores.pop("producto_codigo", None)
        used_headers.discard(code_header)
        warnings.append(f"La columna '{code_header}' no identifica productos: un mismo valor aparece con productos distintos.")


def _scoring_text(header: str, normalized: str) -> str:
    """'$ Unit' es un precio: el simbolo de pesos se pierde al normalizar."""

    if "$" in header and not any(word in normalized for word in _MONEY_WORDS):
        return normalize_header("precio " + normalized.replace("_", " "))
    return normalized


def _fill_from_values(
    mapping: dict[str, str],
    scores: dict[str, float],
    headers: list[str],
    profiles: dict[str, ColumnProfile],
    used_headers: set[str],
) -> None:
    """Completa fecha y producto cuando el nombre de la columna no ayuda.

    Solo con evidencia fuerte y con puntaje bajo, para que quede en revision:
    nunca aprueba sola un mapeo que salio de los valores.
    """

    free = [header for header in headers if header not in used_headers]
    if "fecha" not in mapping:
        dated = [header for header in free if profiles[header].non_empty >= 3 and profiles[header].date_share >= 0.9]
        if len(dated) == 1:
            mapping["fecha"] = dated[0]
            scores["fecha"] = 0.70
            used_headers.add(dated[0])
            free.remove(dated[0])
    if "producto_nombre" not in mapping:
        texts = [header for header in free if profiles[header].non_empty >= 3 and profiles[header].text_share >= 0.9]
        if texts:
            best = max(texts, key=lambda header: profiles[header].distinct_ratio)
            mapping["producto_nombre"] = best
            scores["producto_nombre"] = 0.65
            used_headers.add(best)


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


def _primary_score(field: str, normalized_header: str) -> float:
    """Puntaje de RC8: alias de siempre, con prefijo, sufijo y parecido."""

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


def _score_header(field: str, normalized_header: str, *, secondary: bool = True) -> float:
    """Puntaje de RC8 para los alias de siempre, mas coincidencia exacta de los nuevos."""

    best = _primary_score(field, normalized_header)
    if secondary and normalized_header:
        best = max(best, NORMALIZED_SECONDARY.get(field, {}).get(normalized_header, 0.0))
    return best


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

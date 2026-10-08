from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from .config import CollectorConfig
from .numeric_format import (
    CONVENTION_COMMA,
    CONVENTION_DOT,
    CONVENTION_UNKNOWN,
    EMPTY_PLACEHOLDERS,
    analyze_column,
    normalize_convention,
    numeric_problem,
    parse_decimal_with,
    parse_number_with,
)

# Campos canonicos que se leen como numero. El resto del payload es texto.
NUMERIC_FIELDS = ("cantidad_vendida", "precio_venta", "costo_unitario", "stock_actual", "descuento")

# Que hacer con una columna donde solo aparecen valores como "2.450": en plata
# el punto separa miles; en cantidades suele ser una balanza (2,45 kg).
AMBIGUOUS_DEFAULTS = {
    "cantidad_vendida": CONVENTION_DOT,
    "stock_actual": CONVENTION_DOT,
    "precio_venta": CONVENTION_COMMA,
    "costo_unitario": CONVENTION_COMMA,
    "descuento": CONVENTION_COMMA,
}

FIELD_NAMES_ES = {
    "fecha": "fecha",
    "producto_codigo": "codigo",
    "producto_nombre": "producto",
    "categoria": "categoria",
    "cantidad_vendida": "cantidad",
    "precio_venta": "precio",
    "costo_unitario": "costo",
    "stock_actual": "stock",
    "descuento": "descuento",
    "fecha_stock": "fecha del stock",
}

DEFAULT_DATE_FORMAT = "%Y-%m-%d"

# En Argentina la fecha se escribe con el dia primero: "03/04/2026" es 3 de
# abril, no 4 de marzo. Por eso nunca probamos "%m/%d/%Y": ante un archivo con
# formato de EE.UU. preferimos no leer la fecha y avisar antes que invertir dia
# y mes en silencio.
BASE_DATE_FORMATS = (
    "%Y-%m-%d",
    "%d/%m/%Y",
    "%d/%m/%y",
    "%d-%m-%Y",
    "%d-%m-%y",
    "%d.%m.%Y",
    "%d.%m.%y",
    "%Y/%m/%d",
    "%Y%m%d",
)

DATETIME_FORMATS = (
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%dT%H:%M",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%d/%m/%Y %H:%M:%S",
    "%d/%m/%Y %H:%M",
    "%d/%m/%y %H:%M",
    "%d-%m-%Y %H:%M:%S",
    "%d-%m-%Y %H:%M",
    "%d.%m.%Y %H:%M:%S",
    "%d.%m.%Y %H:%M",
)

_TIME_SPLIT_RE = re.compile(r"[T\s]", re.IGNORECASE)
# Filas de totales al pie de la exportacion: "TOTAL", "Totales", "Total general".
# Lista cerrada a proposito: "Total Petrolero" o "Totalín" son productos.
_TOTAL_ROW_RE = re.compile(
    r"^\s*(sub\s*)?total(es)?"
    r"(\s+(general|generales|ventas|de\s+ventas|vendido|facturado|del\s+d[ií]a|del\s+per[ií]odo|del\s+mes|de\s+la\s+semana))?"
    r"\s*[:$]?\s*$",
    re.IGNORECASE,
)
# Campos opcionales donde un guion significa "sin dato", no un error.
# (Misma lista que usa la tabla de la configuracion guiada.)
_PLACEHOLDER_FIELDS = {"descuento", "costo_unitario", "stock_actual"}
# Excel guarda las fechas como dias desde 1899-12-30.
_EXCEL_EPOCH = date(1899, 12, 30)
_EXCEL_SERIAL_RANGE = (30000, 70000)  # 1982 a 2091


@dataclass
class NormalizedResult:
    rows: list[dict[str, Any]]
    discarded: list[dict[str, Any]]
    # Convencion decimal usada por cada campo numerico mapeado.
    column_conventions: dict[str, str] = field(default_factory=dict)
    # Campos resueltos sin evidencia decisiva (solo valores tipo "1.890").
    ambiguous_columns: list[str] = field(default_factory=list)
    # Valores no vacios que no se pudieron leer como numero, por campo.
    parse_failures: dict[str, int] = field(default_factory=dict)
    # Filas validas cuya fecha estaba escrita pero no se pudo leer.
    date_failures: list[dict[str, Any]] = field(default_factory=list)
    # Filas de totales al pie, que no son ventas.
    skipped_total_rows: list[int] = field(default_factory=list)
    # Fila de la planilla de cada fila valida, en el mismo orden que ``rows``.
    # Va aparte para no alterar el hash normalizado ni la idempotencia.
    row_sources: list[int] = field(default_factory=list)


def clean_string(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def parse_number(value: Any, convention: str = CONVENTION_UNKNOWN) -> float | None:
    """Convierte un valor a numero.

    Se puede llamar con un solo argumento (decide valor por valor) o con la
    convencion decimal ya decidida para la columna, que es como lo usa
    ``normalize_rows``.
    """

    return parse_number_with(value, convention)


def cost_status(raw_value: Any, parsed: float | None) -> str:
    if raw_value is None or str(raw_value).strip() == "":
        return "missing"
    if parsed is None:
        return "invalid"
    if parsed < 0:
        return "negative"
    if parsed == 0:
        return "zero"
    return "valid"


def parse_date(value: Any, date_format: str = DEFAULT_DATE_FORMAT) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return _excel_serial_date(value)
    text = str(value).strip()
    if not text:
        return None
    if text.isdigit() and len(text) == 5:
        return _excel_serial_date(int(text))

    for fmt in _date_formats(date_format):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue

    # ISO con microsegundos, offset o "Z".
    iso_text = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        return datetime.fromisoformat(iso_text).date()
    except ValueError:
        pass

    # Si el texto trae hora en un formato que no listamos, nos quedamos con la
    # fecha y descartamos la hora.
    head = _TIME_SPLIT_RE.split(text, maxsplit=1)[0]
    if head and head != text:
        return parse_date(head, date_format)
    return None


def _excel_serial_date(value: float | int) -> date | None:
    if not (_EXCEL_SERIAL_RANGE[0] <= value <= _EXCEL_SERIAL_RANGE[1]):
        return None
    return _EXCEL_EPOCH + timedelta(days=int(value))


def _date_formats(date_format: str | None) -> tuple[str, ...]:
    """Formato configurado primero, pero sin sacar nunca los estandar."""

    candidates = []
    if date_format:
        candidates.append(str(date_format))
    candidates.extend(BASE_DATE_FORMATS)
    candidates.extend(DATETIME_FORMATS)
    return tuple(dict.fromkeys(candidates))


def is_total_row(raw: dict[str, Any], mapping: dict[str, str]) -> bool:
    """Una fila de totales al pie no es una venta y no invalida el archivo."""

    candidates = []
    for name in ("producto_nombre", "producto_codigo", "fecha", "categoria"):
        source = mapping.get(name)
        if source:
            candidates.append(raw.get(source))
    first_text = next((value for value in raw.values() if str(value or "").strip()), None)
    candidates.append(first_text)
    if not any(isinstance(value, str) and _TOTAL_ROW_RE.match(value) for value in candidates):
        return False
    # Una venta real tiene fecha y producto; la fila de totales no tiene alguno de los dos.
    fecha_source = mapping.get("fecha")
    product_source = mapping.get("producto_nombre")
    has_date = bool(fecha_source and parse_date(raw.get(fecha_source)))
    product_value = clean_string(raw.get(product_source)) if product_source else None
    has_real_product = bool(product_value) and not _TOTAL_ROW_RE.match(product_value or "")
    return not (has_date and has_real_product)


def source_header_for(name: str, mapping: dict[str, str], headers: list[str] | tuple[str, ...]) -> str | None:
    """Columna del archivo que alimenta un campo, incluido el descuento implicito."""

    source = mapping.get(name)
    if source:
        return source
    if name == "descuento":
        for header in headers:
            if str(header).strip().casefold() in {"descuento", "discount"}:
                return header
    return None


def column_conventions(
    raw_rows: list[dict[str, Any]],
    mapping: dict[str, str],
    config: CollectorConfig,
) -> tuple[dict[str, str], list[str]]:
    """Decide la convencion decimal de cada campo numerico.

    Orden de prioridad:
    1. ``decimal_conventions`` por campo, que guarda la configuracion guiada
       despues de que el comercio vio la vista previa y la confirmo;
    2. ``decimal_separator`` global, para quien lo quiera fijar a mano;
    3. deteccion sobre la columna completa del archivo.
    """

    frozen = config.raw.get("decimal_conventions")
    frozen = frozen if isinstance(frozen, dict) else {}
    setting = config.raw.get("decimal_separator", "auto")
    forced = normalize_convention(setting)
    if forced is None and str(setting or "auto").strip().lower() not in {"", "auto"}:
        logging.warning("decimal_separator invalido en config: %s. Se usa deteccion automatica.", setting)

    headers = list(raw_rows[0].keys()) if raw_rows else list(mapping.values())
    conventions: dict[str, str] = {}
    ambiguous: list[str] = []
    for field_name in NUMERIC_FIELDS:
        source = source_header_for(field_name, mapping, headers)
        if not source:
            continue
        pinned = normalize_convention(frozen.get(field_name))
        if pinned is not None:
            conventions[field_name] = pinned
            continue
        if forced is not None:
            conventions[field_name] = forced
            continue
        profile = analyze_column(
            (raw.get(source) for raw in raw_rows),
            ambiguous_default=AMBIGUOUS_DEFAULTS.get(field_name, CONVENTION_COMMA),
        )
        conventions[field_name] = profile.convention
        if profile.ambiguous:
            ambiguous.append(field_name)
    return conventions, ambiguous


def normalize_rows(raw_rows: list[dict[str, Any]], config: CollectorConfig) -> NormalizedResult:
    mapping = config.column_mapping
    valid: list[dict[str, Any]] = []
    row_sources: list[int] = []
    discarded: list[dict[str, Any]] = []
    date_failures: list[dict[str, Any]] = []
    skipped_totals: list[int] = []
    date_format = str(config.raw.get("date_format") or DEFAULT_DATE_FORMAT)
    source_rows = getattr(raw_rows, "row_numbers", None)
    headers = list(raw_rows[0].keys()) if raw_rows else []

    conventions, ambiguous_columns = column_conventions(raw_rows, mapping, config)
    parse_failures: dict[str, int] = {}
    timezone_name = str(config.raw.get("business_timezone", "America/Argentina/Buenos_Aires"))
    discount_source = source_header_for("descuento", mapping, headers)
    percentage_discounts = config.raw.get("discount_semantics") == "percentage"

    for index, raw in enumerate(raw_rows, start=1):
        source_row = source_rows[index - 1] if source_rows and index - 1 < len(source_rows) else None

        def mapped(name: str) -> Any:
            if name == "descuento":
                return raw.get(discount_source) if discount_source else None
            source = mapping.get(name)
            return raw.get(source) if source else None

        def column_of(name: str) -> str:
            return source_header_for(name, mapping, headers) or FIELD_NAMES_ES.get(name, name)

        if is_total_row(raw, mapping):
            skipped_totals.append(source_row or index)
            continue

        problems: list[dict[str, Any]] = []

        def numeric(name: str) -> tuple[Any, Any]:
            raw_value = mapped(name)
            if name in _PLACEHOLDER_FIELDS and isinstance(raw_value, str) and raw_value.strip().casefold() in EMPTY_PLACEHOLDERS:
                raw_value = None
            exact = parse_decimal_with(
                raw_value,
                conventions.get(name, CONVENTION_UNKNOWN),
                allow_percent=name == "descuento" and percentage_discounts,
            )
            if exact is None and _has_content(raw_value):
                parse_failures[name] = parse_failures.get(name, 0) + 1
            return raw_value, exact

        producto_nombre = clean_string(mapped("producto_nombre"))
        cantidad_raw, cantidad_exact = numeric("cantidad_vendida")
        precio_raw, precio_exact = numeric("precio_venta")
        costo_raw, costo_exact = numeric("costo_unitario")
        _, stock_exact = numeric("stock_actual")
        discount_raw, discount_exact = numeric("descuento")

        cantidad_vendida = None if cantidad_exact is None else float(cantidad_exact)
        precio_venta = None if precio_exact is None else float(precio_exact)
        costo_unitario = None if costo_exact is None else float(costo_exact)
        costo_estado = cost_status(costo_raw, costo_unitario)

        reasons: list[str] = []
        if not producto_nombre:
            reasons.append("producto_nombre requerido")
            problems.append(_problem("producto_nombre", column_of("producto_nombre"), mapped("producto_nombre"), "falta el nombre del producto"))
        if cantidad_vendida is None:
            if _has_content(cantidad_raw):
                reasons.append("cantidad_vendida no numerica")
                problems.append(_problem("cantidad_vendida", column_of("cantidad_vendida"), cantidad_raw, numeric_problem(cantidad_raw)))
            else:
                reasons.append("cantidad_vendida requerida")
                problems.append(_problem("cantidad_vendida", column_of("cantidad_vendida"), cantidad_raw, "falta la cantidad"))
        elif cantidad_vendida < 0:
            reasons.append("cantidad_vendida negativa")
            problems.append(_problem("cantidad_vendida", column_of("cantidad_vendida"), cantidad_raw, "la cantidad es negativa (las devoluciones no se admiten en esta fuente)"))
        if precio_venta is None:
            if _has_content(precio_raw):
                reasons.append("precio_venta no numerico")
                problems.append(_problem("precio_venta", column_of("precio_venta"), precio_raw, numeric_problem(precio_raw)))
            else:
                reasons.append("precio_venta requerido")
                problems.append(_problem("precio_venta", column_of("precio_venta"), precio_raw, "falta el precio"))
        elif precio_venta < 0:
            reasons.append("precio_venta negativo")
            problems.append(_problem("precio_venta", column_of("precio_venta"), precio_raw, "el precio es negativo"))
        if _has_content(discount_raw) and discount_exact is None:
            # Como en RC8: un descuento ilegible invalida el archivo entero. Nunca
            # se lo toma como cero ni se descarta la venta en silencio.
            from .errors import ValidationError

            raise ValidationError(
                f"Fila {source_row or index}, columna '{column_of('descuento')}': el descuento {numeric_problem(discount_raw)}. "
                "Corregí la fuente o el tipo de descuento en Configurar archivo."
            )
        if reasons:
            discarded.append({"row_number": index, "source_row": source_row, "reasons": reasons, "problems": problems})
            continue

        exact = {
            "cantidad_vendida": _decimal_text(cantidad_exact),
            "precio_venta": _decimal_text(precio_exact),
            "costo_unitario": _decimal_text(costo_exact) if costo_estado in {"valid", "zero"} else None,
            "stock_actual": _decimal_text(stock_exact),
            "descuento": _decimal_text(discount_exact),
        }

        raw_date = mapped("fecha")
        if isinstance(raw_date, str) and "T" in raw_date:
            try:
                raw_date = datetime.fromisoformat(raw_date.replace("Z", "+00:00"))
            except ValueError:
                pass
        if isinstance(raw_date, datetime) and raw_date.tzinfo is not None:
            raw_date = raw_date.astimezone(ZoneInfo(timezone_name))
        fecha = parse_date(raw_date, date_format)
        if fecha is None and _has_content(mapped("fecha")):
            date_failures.append({
                "row_number": index,
                "source_row": source_row,
                "column": column_of("fecha"),
                "value": _display(mapped("fecha")),
            })

        valid.append(
            {
                "_daily_decimal": exact,
                "fecha": fecha,
                "fecha_stock": parse_date(mapped("fecha_stock"), date_format),
                "producto_codigo": clean_string(mapped("producto_codigo")),
                "producto_nombre": producto_nombre,
                "categoria": clean_string(mapped("categoria")) or "Sin categoria",
                "cantidad_vendida": cantidad_vendida,
                "precio_venta": precio_venta,
                "costo_unitario": costo_unitario if costo_estado in {"valid", "zero"} else None,
                "costo_estado": costo_estado,
                "stock_actual": None if stock_exact is None else float(stock_exact),
            }
        )
        row_sources.append(source_row or index)

    return NormalizedResult(
        rows=valid,
        discarded=discarded,
        column_conventions=conventions,
        ambiguous_columns=ambiguous_columns,
        parse_failures=parse_failures,
        date_failures=date_failures,
        skipped_total_rows=skipped_totals,
        row_sources=row_sources,
    )


def describe_problems(
    result: NormalizedResult,
    *,
    limit: int = 5,
    require_dates: bool = False,
    include_values: bool = True,
) -> list[str]:
    """Frases que dicen exactamente que fila y que columna mirar.

    ``include_values`` muestra el contenido de la celda. Solo para la pantalla
    local: los mensajes que quedan en estado, logs o diagnostico no llevan
    datos del comercio.
    """

    lines: list[str] = []
    for item in result.discarded:
        row = item.get("source_row") or item.get("row_number")
        for problem in item.get("problems") or []:
            value = problem.get("value")
            shown = f" = '{value}'" if include_values and value not in (None, "") else ""
            lines.append(f"Fila {row}, columna '{problem['column']}'{shown}: {problem['message']}.")
            break
        else:
            lines.append(f"Fila {row}: " + ", ".join(item.get("reasons") or ["dato invalido"]) + ".")
        if len(lines) >= limit:
            break
    if require_dates and len(lines) < limit:
        for item in result.date_failures:
            row = item.get("source_row") or item.get("row_number")
            shown = f" = '{item['value']}'" if include_values else ""
            lines.append(f"Fila {row}, columna '{item['column']}'{shown}: no es una fecha que AIVA pueda leer (usá dia/mes/año).")
            if len(lines) >= limit:
                break
        if len(lines) < limit:
            failed_rows = {failure.get("source_row") or failure.get("row_number") for failure in result.date_failures}
            for position, row in enumerate(result.rows):
                source_row = result.row_sources[position] if position < len(result.row_sources) else position + 1
                if row.get("fecha") is None and source_row not in failed_rows:
                    lines.append(f"Fila {source_row}: falta la fecha de la venta.")
                    if len(lines) >= limit:
                        break
    return lines


def count_problem_rows(result: NormalizedResult, *, require_dates: bool = False) -> int:
    count = len(result.discarded)
    if require_dates:
        count += sum(1 for row in result.rows if row.get("fecha") is None)
    return count


def _problem(field_name: str, column: str, value: Any, message: str) -> dict[str, Any]:
    return {"field": field_name, "column": column, "value": _display(value), "message": message}


def _display(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()[:60]


def _decimal_text(value: Any) -> str | None:
    return None if value is None else str(value)


def _has_content(value: Any) -> bool:
    return value is not None and str(value).strip() != ""

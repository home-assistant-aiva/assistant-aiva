"""Lectura de numeros tal como los escriben los sistemas argentinos.

La ambiguedad tipica de un export argentino no se resuelve mirando un valor
aislado: "1.890" puede ser mil ochocientos noventa (punto como separador de
miles, lo normal en Argentina) o uno coma ochenta y nueve (punto decimal, lo
normal en un export en ingles). Se resuelve mirando la columna entera.

El modulo separa la decision en tres pasos:

1. ``clean_numeric_text`` saca moneda, espacios y porcentajes, y deja el signo
   al frente (incluye negativos escritos entre parentesis).
2. ``analyze_column`` mira todos los valores no vacios de una columna y decide
   si esa columna usa coma o punto decimal.
3. ``parse_decimal_with`` / ``parse_number_with`` convierten cada valor con la
   convencion decidida.

Ante la duda el modulo prefiere no inventar un numero: devuelve ``None`` y deja
que el llamador cuente el fallo, porque un numero mal leido se traduce en una
recomendacion de compra equivocada.

``canonical_decimal`` es otra cosa: lee valores que el propio Collector ya
normalizo ("1890.00"). Nunca aplica heuristicas locales, porque releer "2.450"
(dos coma cuarenta y cinco ya normalizado) con reglas argentinas lo convertiria
en dos mil cuatrocientos cincuenta.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable

CONVENTION_COMMA = "comma"
CONVENTION_DOT = "dot"
CONVENTION_UNKNOWN = "unknown"

CONVENTION_LABELS = {
    CONVENTION_COMMA: "1.234,56 (punto separa miles, coma separa decimales)",
    CONVENTION_DOT: "1,234.56 (coma separa miles, punto separa decimales)",
    CONVENTION_UNKNOWN: "sin separadores (números enteros)",
}

# Grupo de 3 digitos sin evidencia decisiva ("1.890", "1,890"). No son votos:
# son pistas que solo se usan cuando la columna no tiene evidencia real.
_GROUP_DOT = "group_dot"
_GROUP_COMMA = "group_comma"
_NO_EVIDENCE = "none"

# Pesos: se sacan. Otra moneda: el valor no se lee, porque AIVA no sabe a que
# cotizacion convertirlo y leer U$S 1.890 como $ 1.890 es peor que no leerlo.
# Los tokens largos van primero: "U$S" contiene "$".
_FOREIGN_CURRENCY_RE = re.compile(r"u\$s|us\$|u\$d|usd|eur|€|£", re.IGNORECASE)
_PESO_RE = re.compile(r"ar\$|ars|pesos|\$", re.IGNORECASE)
_SCIENTIFIC_RE = re.compile(r"\d+(?:[.,]\d+)?[eE][+-]?\d+")
# Guiones que algunos sistemas ponen en lugar de "sin valor".
EMPTY_PLACEHOLDERS = {"-", "--", "\u2013", "\u2014", "s/d", "n/a"}
_SPACE_RE = re.compile(r"[\s   ]+")
_SIGN_CHARS = "+-"
_ALLOWED_BODY_CHARS = set("0123456789.,")


@dataclass(frozen=True)
class ColumnNumericProfile:
    """Resultado de mirar una columna completa."""

    convention: str
    ambiguous: bool = False
    evidence: dict[str, int] = field(default_factory=dict)


def clean_numeric_text(value: Any, *, allow_percent: bool = False) -> str:
    """Normaliza el texto de un valor numerico.

    Saca el simbolo de pesos ($, ARS, AR$, "pesos") y cualquier tipo de espacio
    (normal, fino o no separable), y reconoce negativos escritos con parentesis
    o con el signo adelante o atras. Devuelve el texto con el signo menos al
    frente, o "" si no hay un numero en pesos que leer: un valor en otra moneda
    o con "%" (salvo ``allow_percent``) no se lee.
    """

    if value is None:
        return ""
    text = str(value).strip()
    if not text:
        return ""
    if _FOREIGN_CURRENCY_RE.search(text):
        return ""
    if "%" in text:
        if not allow_percent:
            return ""
        text = text.replace("%", "")

    text = text.replace("−", "-")  # signo menos unicode
    text = _PESO_RE.sub("", text)
    text = _SPACE_RE.sub("", text)
    if not text:
        return ""

    negative = False
    # Contabilidad clasica: los negativos vienen entre parentesis.
    while len(text) >= 2 and text.startswith("(") and text.endswith(")"):
        negative = True
        text = text[1:-1]
    while text and text[0] in _SIGN_CHARS:
        negative = negative or text[0] == "-"
        text = text[1:]
    while text and text[-1] in _SIGN_CHARS:
        negative = negative or text[-1] == "-"
        text = text[:-1]
    if not text:
        return ""
    return f"-{text}" if negative else text


def classify_numeric_text(text: str) -> str:
    """Clasifica la evidencia decimal de un solo valor ya limpio."""

    body = text[1:] if text.startswith("-") else text
    if not body or not any(char.isdigit() for char in body):
        return _NO_EVIDENCE
    if any(char not in _ALLOWED_BODY_CHARS for char in body):
        return _NO_EVIDENCE

    has_dot = "." in body
    has_comma = "," in body

    if has_dot and has_comma:
        # El separador que aparece ultimo es el decimal: "1.234,56" vs "1,234.50".
        return CONVENTION_COMMA if body.rfind(",") > body.rfind(".") else CONVENTION_DOT

    if has_comma:
        parts = body.split(",")
        if len(parts) > 2:
            # "1,234,567": la coma solo puede ser separador de miles.
            return CONVENTION_DOT if _is_thousands_grouping(parts) else _NO_EVIDENCE
        if len(parts[-1]) == 3 and _is_thousands_grouping(parts):
            return _GROUP_COMMA
        return CONVENTION_COMMA

    if has_dot:
        parts = body.split(".")
        if len(parts) > 2:
            # "1.234.567": el punto solo puede ser separador de miles.
            return CONVENTION_COMMA if _is_thousands_grouping(parts) else _NO_EVIDENCE
        if len(parts[-1]) == 3 and _is_thousands_grouping(parts):
            return _GROUP_DOT
        # 1, 2 o 4+ decimales, o "0.500": no puede ser un grupo de miles.
        return CONVENTION_DOT

    return _NO_EVIDENCE


def analyze_column(values: Iterable[Any], *, ambiguous_default: str = CONVENTION_COMMA) -> ColumnNumericProfile:
    """Decide la convencion decimal de una columna entera.

    Primero busca evidencia decisiva (coma con 1 o 2 decimales, punto con una
    cantidad de decimales que no puede ser un grupo de miles, separadores
    repetidos). Si no hay evidencia, cae en la heuristica de grupos de 3 y
    marca la columna como ambigua para que alguien la confirme.

    ``ambiguous_default`` decide que hacer con una columna donde solo hay
    valores como "1.890": para plata conviene leerlo como mil ochocientos
    noventa; para cantidades vendidas, como 1,89 (balanza).
    """

    evidence: dict[str, int] = {
        CONVENTION_COMMA: 0,
        CONVENTION_DOT: 0,
        _GROUP_DOT: 0,
        _GROUP_COMMA: 0,
    }

    for value in values:
        if value is None or isinstance(value, bool):
            continue
        if isinstance(value, (int, float, Decimal)):
            # Ya viene tipado desde Excel: no aporta evidencia de formato.
            continue
        text = clean_numeric_text(value, allow_percent=True)
        if not text:
            continue
        kind = classify_numeric_text(text)
        if kind in evidence:
            evidence[kind] += 1

    comma_votes = evidence[CONVENTION_COMMA]
    dot_votes = evidence[CONVENTION_DOT]

    if comma_votes and not dot_votes:
        return ColumnNumericProfile(CONVENTION_COMMA, False, evidence)
    if dot_votes and not comma_votes:
        return ColumnNumericProfile(CONVENTION_DOT, False, evidence)
    if comma_votes and dot_votes:
        # Columna mezclada: gana la mayoria, empate a favor del formato local,
        # y queda marcada como ambigua para que alguien la mire.
        convention = CONVENTION_DOT if dot_votes > comma_votes else CONVENTION_COMMA
        return ColumnNumericProfile(convention, True, evidence)

    group_dot = evidence[_GROUP_DOT]
    group_comma = evidence[_GROUP_COMMA]
    if group_dot and not group_comma:
        # Solo "1.890", "2.450": el punto es miles para plata, decimal para kilos.
        return ColumnNumericProfile(ambiguous_default, True, evidence)
    if group_comma and not group_dot:
        # Solo "1,890": la coma es miles para plata, decimal para kilos.
        opposite = CONVENTION_DOT if ambiguous_default == CONVENTION_COMMA else CONVENTION_COMMA
        return ColumnNumericProfile(opposite, True, evidence)
    if group_dot and group_comma:
        return ColumnNumericProfile(ambiguous_default, True, evidence)

    return ColumnNumericProfile(CONVENTION_UNKNOWN, False, evidence)


def detect_decimal_convention(values: Iterable[Any]) -> str:
    """Devuelve "comma", "dot" o "unknown" para los valores de una columna."""

    return analyze_column(values).convention


def parse_decimal_with(value: Any, convention: str = CONVENTION_UNKNOWN, *, allow_percent: bool = False) -> Decimal | None:
    """Lee un valor del archivo del comercio como Decimal exacto.

    Con ``convention`` desconocida decide valor por valor, que es lo mejor que
    se puede hacer sin ver el resto de la columna.
    """

    if value is None:
        return None
    if isinstance(value, bool):
        return Decimal(int(value))
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, Decimal):
        return value if value.is_finite() else None
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            return None
        return Decimal(repr(value))

    text = clean_numeric_text(value, allow_percent=allow_percent)
    if not text:
        return None
    negative = text.startswith("-")
    body = text[1:] if negative else text
    if _SCIENTIFIC_RE.fullmatch(body):
        # Excel escribe asi los numeros grandes en un CSV: "1,5E+03".
        try:
            number = Decimal(body.replace(",", "."))
        except InvalidOperation:
            return None
        return (-number if negative else number) if number.is_finite() else None
    if not body or any(char not in _ALLOWED_BODY_CHARS for char in body):
        return None
    if not any(char.isdigit() for char in body):
        return None  # "," o "." solos no son cero

    if convention not in (CONVENTION_COMMA, CONVENTION_DOT):
        convention = _convention_for_single_value(body)

    plain = _to_plain_decimal(body, convention)
    if plain is None:
        return None
    try:
        number = Decimal(plain)
    except InvalidOperation:
        return None
    if not number.is_finite():
        return None
    return -number if negative else number


def parse_number_with(value: Any, convention: str = CONVENTION_UNKNOWN, *, allow_percent: bool = False) -> float | None:
    """Igual que ``parse_decimal_with`` pero devuelve float (resumen v1)."""

    if isinstance(value, float):
        return value if value == value and value not in (float("inf"), float("-inf")) else None
    number = parse_decimal_with(value, convention, allow_percent=allow_percent)
    return None if number is None else float(number)


def canonical_decimal(value: Any) -> Decimal | None:
    """Lee un valor que el Collector ya normalizo. Sin heuristicas locales."""

    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, Decimal):
        return value if value.is_finite() else None
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            return None
        return Decimal(repr(value))
    text = str(value).strip()
    if not text:
        return None
    try:
        number = Decimal(text)
    except InvalidOperation:
        return None
    return number if number.is_finite() else None


def normalize_convention(setting: Any) -> str | None:
    """Traduce un valor de config a una convencion.

    Acepta "auto" (o vacio) para deteccion automatica, "," / "coma" / "comma"
    y "." / "punto" / "dot". Cualquier otra cosa devuelve ``None``.
    """

    if setting is None:
        return None
    text = str(setting).strip().lower()
    if text in {"", "auto"}:
        return None
    if text in {",", "coma", "comma"}:
        return CONVENTION_COMMA
    if text in {".", "punto", "dot", "point"}:
        return CONVENTION_DOT
    return None


def numeric_problem(value: Any) -> str:
    """Por que un valor no se pudo leer, en palabras del comercio."""

    text = str(value or "")
    if _FOREIGN_CURRENCY_RE.search(text):
        return "está en otra moneda (AIVA no convierte cotizaciones)"
    if "%" in text:
        return "tiene %, pero el descuento no está configurado como porcentaje"
    return "no es un número"


def format_ar(value: Any, *, max_decimals: int = 2) -> str:
    """Muestra un numero como lo lee una persona en Argentina: 1.890,50.

    Sirve para que el comercio vea la interpretacion de AIVA y note al toque
    si "1.890" se leyo como 1,89.
    """

    number = canonical_decimal(value)
    if number is None:
        return "—"
    negative = number < 0
    number = abs(number)
    quantum = Decimal(1).scaleb(-max_decimals)
    rounded = number.quantize(quantum)
    integer_part, _, decimal_part = f"{rounded:f}".partition(".")
    decimal_part = decimal_part.rstrip("0")
    grouped = f"{int(integer_part):,}".replace(",", ".")
    text = f"{grouped},{decimal_part}" if decimal_part else grouped
    return f"-{text}" if negative else text


def _convention_for_single_value(body: str) -> str:
    kind = classify_numeric_text(body)
    if kind == CONVENTION_COMMA:
        return CONVENTION_COMMA
    if kind == CONVENTION_DOT:
        return CONVENTION_DOT
    if kind == _GROUP_DOT:
        # "1.890" suelto: en Argentina es mil ochocientos noventa.
        return CONVENTION_COMMA
    if kind == _GROUP_COMMA:
        return CONVENTION_DOT
    return CONVENTION_COMMA


def _to_plain_decimal(body: str, convention: str) -> str | None:
    """Pasa el valor a notacion plana ("1234.56") segun la convencion.

    El separador de miles solo se acepta si realmente agrupa de a 3 digitos.
    Si no agrupa ("12.5" en una columna con coma decimal) devolvemos ``None``:
    preferimos contar un fallo de parseo antes que convertir 12,5 en 125.
    """

    if convention == CONVENTION_COMMA:
        thousands, decimal = ".", ","
    else:
        thousands, decimal = ",", "."

    if body.count(decimal) > 1:
        # Varios separadores decimales solo tienen sentido si en realidad
        # agrupan miles ("1.234.567" en una columna con punto decimal).
        parts = body.split(decimal)
        if thousands in body or not _is_thousands_grouping(parts):
            return None
        return body.replace(decimal, "")

    integer_text, _, decimal_text = body.partition(decimal)
    if thousands in decimal_text:
        return None
    if thousands in integer_text:
        if not _is_thousands_grouping(integer_text.split(thousands)):
            return None
        integer_text = integer_text.replace(thousands, "")

    if not integer_text:
        integer_text = "0"  # ",50" o ".50"
    plain = f"{integer_text}.{decimal_text}" if decimal_text else integer_text
    if not any(char.isdigit() for char in plain):
        return None
    return plain


def _is_thousands_grouping(parts: list[str]) -> bool:
    if len(parts) < 2:
        return False
    head = parts[0]
    if not head or len(head) > 3 or not head.isdigit():
        return False
    if head.startswith("0"):
        # Un numero agrupado nunca arranca con cero ("0.500" es medio, no 500).
        return False
    return all(len(part) == 3 and part.isdigit() for part in parts[1:])

"""Extracción y OCR multimodal mediante Google Gemini (Gemini 2.5 Flash).

Requiere GEMINI_API_KEY o GOOGLE_API_KEY en entorno o .env.
Devuelve el JSON estructurado de la factura directamente.
"""

from __future__ import annotations

import base64
import io
import json
import os
from pathlib import Path
import urllib.error
import urllib.request

from aeat_hub.ocr.base import OCRResult, ProviderUnavailable
from aeat_hub.ocr.render import iter_page_images

try:
    import dotenv

    dotenv.load_dotenv()
except ImportError:
    pass

DEFAULT_MODEL = "gemini-2.5-flash"
ENV_KEY = "GEMINI_API_KEY"
ENV_KEY_ALT = "GOOGLE_API_KEY"
ENV_MODEL = "AEAT_HUB_GEMINI_MODEL"

INVOICE_PROMPT = """Eres un contable español experto en el Reglamento de facturación (RD 1619/2012) y en la Ley del IVA.
Lee el documento (puede tener varias páginas) y devuelve SOLO un objeto JSON con estos campos:

- tipo_documento: "completa" (factura completa, art. 6), "simplificada" (factura simplificada o ticket, art. 7), "rectificativa" (art. 15: rectificativa o abono) o "no_factura" (presupuesto, proforma, albarán, pedido, recibo bancario, extracto, justificante de pago u otro documento que NO es una factura).
- emisor y nif_emisor: quien EXPIDE la factura (cabecera, logotipo, datos fiscales del vendedor). Nunca el cliente ni textos legales de pie de página (protección de datos, registro mercantil de otra empresa, avisos).
- receptor y nif_receptor: el destinatario o cliente si figura (en tickets suele aparecer como "NIF", "NIF cliente", "DNI" o "Datos del cliente"). null si no figura.
- serie y numero: si el número tiene una serie separada (ej. serie "A", número "2026-0001") devuélvelas por separado; si no, serie null y el número completo tal como está impreso.
- fecha: fecha de expedición (AAAA-MM-DD).
- fecha_operacion: solo si el documento indica una fecha de operación o de prestación DISTINTA de la de expedición; si no, null. No uses la fecha de vencimiento ni la de pedido.
- moneda: código ISO 4217 (EUR, USD, GBP…).
- base, iva_tipo, iva_cuota: totales de la factura. iva_tipo es el tipo principal.
- desglose_iva: una entrada por cada tipo impositivo con base, iva_tipo, iva_cuota y, si hay recargo de equivalencia, recargo_tipo y recargo_cuota.
- retencion_tipo y retencion_cuota: retención de IRPF si existe.
- total: importe total de la factura tal como figura impreso.
- mencion_legal: "exenta_art20" (operación exenta, cita el art. 20 LIVA u otro), "inversion_sujeto_pasivo", "criterio_caja", "no_sujeta", "regimen_especial" (REBU, agencias de viajes, etc.) o null.
- factura_rectificada: número de la factura que se rectifica, si es rectificativa.
- metodo_rectificacion: "sustitucion" si la factura reemplaza íntegramente a otra (incluido el canje de un ticket por una factura completa) o "diferencias" si solo recoge la corrección; null si no es rectificativa.
- causa_rectificacion: el motivo que indique el documento, o null.
- lineas: TODAS las líneas, sin agrupar: codigo, descripcion, cantidad, precio_unitario, base, iva_tipo, iva_cuota, importe (total final de la línea).
- campos_dudosos: lista con el nombre de cada campo que no se lee con claridad (borroso, cortado, tapado). Vacía si todo es legible.

Reglas:
1. No inventes ni calcules lo que no figura. Si el documento no muestra IVA, iva_tipo e iva_cuota son null: NO apliques un 21 % por defecto.
2. Importes como números con punto decimal (1.250,50 € → 1250.50).
3. Abonos: los importes que se devuelven van en negativo. Una rectificativa por sustitución lleva los importes completos de la nueva factura (normalmente positivos).
4. En tickets con precios con IVA incluido, el importe de cada línea es el impreso; no sumes IVA encima.
5. En packs o kits no repitas el importe del pack y de sus componentes.
6. Usa null (no cadena vacía) para lo que no figure.
"""


def _num(descripcion: str = "") -> dict:
    return {"type": "NUMBER", "nullable": True, "description": descripcion}


def _str(descripcion: str = "", enum: list[str] | None = None) -> dict:
    item = {"type": "STRING", "nullable": True, "description": descripcion}
    if enum:
        item["enum"] = enum
    return item


# Esquema de salida que Gemini respeta al generar (responseSchema): evita
# JSON truncado o con claves inventadas y fija los valores permitidos.
RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "tipo_documento": _str(enum=["completa", "simplificada", "rectificativa", "no_factura"]),
        "emisor": _str(),
        "nif_emisor": _str(),
        "receptor": _str(),
        "nif_receptor": _str(),
        "serie": _str(),
        "numero": _str(),
        "fecha": _str("AAAA-MM-DD"),
        "fecha_operacion": _str("AAAA-MM-DD"),
        "moneda": _str("ISO 4217"),
        "base": _num(),
        "iva_tipo": _num(),
        "iva_cuota": _num(),
        "desglose_iva": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "base": _num(),
                    "iva_tipo": _num(),
                    "iva_cuota": _num(),
                    "recargo_tipo": _num(),
                    "recargo_cuota": _num(),
                },
            },
        },
        "retencion_tipo": _num(),
        "retencion_cuota": _num(),
        "total": _num(),
        "mencion_legal": _str(
            enum=[
                "exenta_art20",
                "inversion_sujeto_pasivo",
                "criterio_caja",
                "no_sujeta",
                "regimen_especial",
            ]
        ),
        "factura_rectificada": _str(),
        "metodo_rectificacion": _str(enum=["sustitucion", "diferencias"]),
        "causa_rectificacion": _str(),
        "lineas": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "codigo": _str(),
                    "descripcion": _str(),
                    "cantidad": _num(),
                    "precio_unitario": _num(),
                    "base": _num(),
                    "iva_tipo": _num(),
                    "iva_cuota": _num(),
                    "importe": _num(),
                },
            },
        },
        "campos_dudosos": {"type": "ARRAY", "items": {"type": "STRING"}},
    },
    "required": ["tipo_documento", "total"],
}


class GeminiOCRProvider:
    """Proveedor multimodal de Google Gemini."""

    def __init__(self, model: str | None = None, api_key: str | None = None) -> None:
        self.api_key = (
            api_key
            or os.environ.get(ENV_KEY, "").strip()
            or os.environ.get(ENV_KEY_ALT, "").strip()
        )
        self.model = model or os.environ.get(ENV_MODEL, "").strip() or DEFAULT_MODEL
        self.name = f"gemini-{self.model.replace('models/', '').replace('gemini-', '')}"

    def available(self) -> tuple[bool, str]:
        if not self.api_key:
            return False, "falta GEMINI_API_KEY en .env o entorno"
        return True, f"Google Gemini API ({self.model})"

    def transcribe(self, path: Path) -> OCRResult:
        ok, reason = self.available()
        if not ok:
            raise ProviderUnavailable(self.name, reason)

        parts: list[dict] = [{"text": INVOICE_PROMPT}]
        pages = 0

        try:
            for image in iter_page_images(path, dpi=180):
                pages += 1
                buf = io.BytesIO()
                # Redimensionar si es excesivamente grande
                img = _fit(image.convert("RGB"))
                img.save(buf, format="JPEG", quality=85)
                b64_data = base64.b64encode(buf.getvalue()).decode("ascii")
                parts.append({
                    "inlineData": {
                        "mimeType": "image/jpeg",
                        "data": b64_data,
                    }
                })
        except Exception as exc:  # noqa: BLE001
            raise ProviderUnavailable(self.name, f"Error leyendo imagen: {exc}") from exc

        if pages == 0:
            raise ProviderUnavailable(self.name, "No se encontraron páginas en el documento")

        # La key va en cabecera, no en la URL: las URLs acaban en logs y trazas.
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent"
        payload = {
            "contents": [{"parts": parts}],
            "generationConfig": {
                "responseMimeType": "application/json",
                "responseSchema": RESPONSE_SCHEMA,
                "temperature": 0.0,
            },
        }

        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "x-goog-api-key": self.api_key},
            method="POST",
        )

        data = None
        last_exc = None
        for attempt in range(1, 4):
            try:
                with urllib.request.urlopen(req, timeout=75) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    break
            except urllib.error.HTTPError as exc:
                detail = ""
                try:
                    detail = exc.read().decode("utf-8")
                except Exception:
                    pass
                raise ProviderUnavailable(self.name, f"HTTP {exc.code}: {detail[:300]}") from exc
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
                last_exc = exc
                if attempt < 3:
                    import time
                    time.sleep(1.5 * attempt)
                else:
                    raise ProviderUnavailable(self.name, f"Fallo de conexión Gemini tras 3 intentos: {exc}") from exc

        candidates = data.get("candidates") or []
        if not candidates:
            raise ProviderUnavailable(self.name, "Gemini no devolvió candidatos")

        # Un JSON cortado (MAX_TOKENS) o bloqueado no es una factura: mejor
        # que la cascada lea con otro motor que parsear medio documento.
        finish = candidates[0].get("finishReason")
        if finish and finish != "STOP":
            raise ProviderUnavailable(self.name, f"respuesta incompleta de Gemini (finishReason={finish})")

        content = candidates[0].get("content") or {}
        parts_resp = content.get("parts") or []
        if not parts_resp:
            raise ProviderUnavailable(self.name, "Gemini devolvió respuesta vacía")

        raw_text = parts_resp[0].get("text", "").strip()
        # Limpiar posibles bloques ```json ... ``` si vinieran
        if raw_text.startswith("```json"):
            raw_text = raw_text.removeprefix("```json").removesuffix("```").strip()
        elif raw_text.startswith("```"):
            raw_text = raw_text.removeprefix("```").removesuffix("```").strip()

        usage = data.get("usageMetadata") or {}
        return OCRResult(
            text=raw_text,
            engine=self.name,
            confidence=0.98,
            pages=pages,
            usage=dict(usage) if isinstance(usage, dict) else {},
        )


def _fit(image, max_side: int = 2048):
    width, height = image.size
    longest = max(width, height)
    if longest <= max_side:
        return image
    scale = max_side / longest
    return image.resize((max(int(width * scale), 1), max(int(height * scale), 1)))

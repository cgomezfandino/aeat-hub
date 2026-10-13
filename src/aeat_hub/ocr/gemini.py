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

INVOICE_PROMPT = """Eres un sistema experto en contabilidad y fiscalidad española.
Analiza detenidamente la imagen de la factura o ticket y extrae con máxima precisión los datos fiscales en formato JSON estricto:

{
  "emisor": "Nombre comercial o razón social del emisor real (ej: IKEA, Leroy Merlin, Obramat, Endesa). NUNCA uses textos legales de pie de página como protección de datos o GDPR",
  "nif_emisor": "NIF o CIF del emisor (ej: B12345674, A28812618)",
  "receptor": "Nombre o razón social del cliente o receptor si figura, o null",
  "nif_receptor": "NIF o CIF del cliente o receptor si figura, o null",
  "numero": "Número o serie de factura o ticket (ej: 064-0009-720394, ESCINV26000000006920)",
  "fecha": "YYYY-MM-DD",
  "tipo_documento": "factura" | "ticket" | "rectificativa",
  "factura_rectificada": "Número de factura rectificada si es un abono o rectificativa, o null",
  "base": número decimal con la base imponible total (antes de IVA),
  "iva_tipo": número con el porcentaje de IVA principal (ej: 21, 10, 4, 0),
  "iva_cuota": número decimal con la cuota total de IVA,
  "desglose_iva": [
    {
      "base": número decimal de la base para este tipo,
      "iva_tipo": porcentaje de IVA (ej: 21, 10, 4, 0),
      "iva_cuota": cuota de IVA para este tipo
    }
  ],
  "retencion_tipo": número con el porcentaje de IRPF retenido si existe (ej: 15, 19, 7) o null,
  "retencion_cuota": número decimal con el importe retenido de IRPF si existe o null,
  "total": número decimal con el importe total a pagar (Base + IVA - Retención = Total),
  "lineas": [
    {
      "codigo": "Código, referencia o SKU del artículo si existe, o null",
      "descripcion": "Descripción del concepto, bien o servicio",
      "cantidad": número de unidades (ej: 1, 2.5),
      "precio_unitario": número decimal con el precio unitario si figura, o null,
      "base": número decimal con el subtotal antes de IVA de la línea si figura o es calculable, o null,
      "iva_tipo": porcentaje de IVA de la línea si figura (ej: 21, 10, 4, 0) o null,
      "iva_cuota": cuota de IVA de la línea si figura o es calculable, o null,
      "importe": número decimal con el total de la línea
    }
  ]
}

Instrucciones críticas:
1. No inventes datos. Si un campo no figura en el documento, usa null o cadena vacía.
2. Identifica correctamente al emisor real de la factura comercial. NUNCA tomes como emisor textos legales de pie de página (como 'Información básica sobre protección de datos', 'Responsable del tratamiento' o avisos de privacidad).
3. Si los importes tienen formato europeo (1.250,50 €), conviértelos a números decimales estándar (1250.50).
4. En facturas rectificativas o abonos, los importes devueltos deben ser negativos si corresponden a rectificación de compras.
5. Asegúrate de extraer TODAS las líneas y artículos individuales de la tabla o desglose, sin resumir ni agrupar.
6. En las líneas individuales (`lineas`): el campo `importe` es el total final de la línea. Si los precios ya incluyen IVA (tickets de retail, IKEA, Leroy Merlin), el `importe` es el total que figura en el documento; no sumes IVA sobre un importe que ya lo incluye.
7. En artículos en pack o kit (sets que listan componentes con desglose), no dupliques el importe del pack y de sus componentes para evitar sobrepasar el total del documento.
8. Responde únicamente con el objeto JSON válido, sin bloques markdown adicionales ni comentarios.
9. En tickets de retail (Leroy Merlin, IKEA, Obramat...), el NIF del cliente suele figurar como 'NIF', 'No NIF', 'NIF CLIENTE' o 'DNI' en el bloque del comprador: extráelo siempre a `nif_receptor` (y el nombre a `receptor`) en vez de dejarlo en null.
"""


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

        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent"
            f"?key={self.api_key}"
        )
        payload = {
            "contents": [{"parts": parts}],
            "generationConfig": {
                "responseMimeType": "application/json",
                "temperature": 0.1,
            },
        }

        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
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

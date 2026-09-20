# Seguridad y datos fiscales

AEAT Hub está pensado para ejecutarse **en local**. Las facturas, NIF, rentas
e indemnizaciones **no deben subirse a GitHub** ni copiarse al repositorio.

## Qué no incluir nunca en issues, PRs ni commits

- Facturas, tickets, fotos o PDF reales
- NIF/CIF, IBAN, certificados digitales, claves `.env`
- El fichero `ledger.sqlite` ni exportaciones Excel con datos reales
- Rutas internas que revelen un domicilio o referencia catastral real en ejemplos públicos

Los tests usan **documentos sintéticos** (NIF de juguete con dígito de control válido).

## Dónde viven los datos

El directorio de datos (por defecto `/Volumes/SSDCX9/data/aeat-hub` o
`AEAT_HUB_DATA_DIR`) está fuera del repo y cubierto por `.gitignore`.
Detalle del árbol: [docs/datos-y-archivo.md](docs/datos-y-archivo.md).

## Informar de un problema

Si encuentras un fallo que pueda filtrar datos personales, no abras una
incidencia pública con adjuntos. Describe el problema sin documentos reales.

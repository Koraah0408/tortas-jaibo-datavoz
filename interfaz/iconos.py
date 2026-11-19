"""Iconos SVG propios (trazo de 24×24, usan currentColor para tomar el color del texto) y la jaiba de Tortas Jaibo."""

from __future__ import annotations

_TRAZOS = {
    "sesiones": '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    "datos": '<ellipse cx="12" cy="5.5" rx="7.5" ry="2.8"/><path d="M4.5 5.5v13c0 1.6 3.4 2.8 7.5 2.8s7.5-1.2 7.5-2.8v-13"/>'
             '<path d="M4.5 12c0 1.6 3.4 2.8 7.5 2.8s7.5-1.2 7.5-2.8"/>',
    "voz": '<rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5.5 11a6.5 6.5 0 0 0 13 0"/><path d="M12 17.5V21"/>'
           '<path d="M8.5 21h7"/>',
    "reporte": '<path d="M6.5 3h8l4 4v14h-12z"/><path d="M14.5 3v4h4"/><path d="M9.5 12h5M9.5 15.5h5"/>',
    "alertas": '<path d="M6.5 16v-5a5.5 5.5 0 0 1 11 0v5l1.8 2H4.7z"/><path d="M10 21h4"/>',
    "modelo": '<rect x="6.5" y="6.5" width="11" height="11" rx="2"/><path d="M10 10h4v4h-4z"/>'
              '<path d="M9.5 3v3.5M14.5 3v3.5M9.5 17.5V21M14.5 17.5V21M3 9.5h3.5M3 14.5h3.5M17.5 9.5H21M17.5 14.5H21"/>',
    "dinero": '<circle cx="12" cy="12" r="9"/><path d="M14.8 9.4c-.5-.9-1.5-1.4-2.8-1.4-1.6 0-2.8.8-2.8 1.9s1.2 1.6 2.8 1.9'
              's2.8.8 2.8 2-1.2 2-2.8 2c-1.3 0-2.4-.5-2.9-1.5"/><path d="M12 6.5V8M12 16v1.5"/>',
    "ticket": '<path d="M6 3h12v18l-3-1.8-3 1.8-3-1.8L6 21z"/><path d="M9 8.5h6M9 12h6M9 15.5h3"/>',
    "tendencia": '<path d="M3 17l6-6 4 4 8-8"/><path d="M15 7h6v6"/>',
    "baja": '<path d="M3 7l6 6 4-4 8 8"/><path d="M15 17h6v-6"/>',
    "sube": '<path d="M12 19V5"/><path d="M6 11l6-6 6 6"/>',
    "bajo": '<path d="M12 5v14"/><path d="M6 13l6 6 6-6"/>',
    "caja": '<path d="M3.5 7.5L12 3.5l8.5 4L12 11.5z"/><path d="M3.5 7.5v9l8.5 4 8.5-4v-9"/><path d="M12 11.5v9"/>',
    "verificado": '<path d="M12 3l7.5 3v5.5c0 4.6-3.2 8.2-7.5 9.5-4.3-1.3-7.5-4.9-7.5-9.5V6z"/><path d="M8.5 12l2.5 2.5 4.5-5"/>',
    "aviso": '<path d="M12 4l9 16H3z"/><path d="M12 10v4.5M12 17.5v.01"/>',
    "grafica": '<path d="M4 20V4"/><path d="M4 20h16"/><rect x="7" y="11" width="3" height="6" rx=".5"/>'
               '<rect x="12" y="7" width="3" height="10" rx=".5"/><rect x="17" y="13" width="3" height="4" rx=".5"/>',
    "chat": '<path d="M4 5.5h16v10.5H9.5L5 20v-4H4z"/><path d="M8 9.5h8M8 12.5h5"/>',
    "agentes": '<circle cx="12" cy="5.5" r="2.5"/><circle cx="5.5" cy="18" r="2.5"/><circle cx="18.5" cy="18" r="2.5"/>'
               '<path d="M12 8v4M12 12l-5 4M12 12l5 4"/>',
    # Iconos de Tortas Jaibo
    "pan": '<path d="M3.5 14.5c0-4.4 3.8-7.5 8.5-7.5s8.5 3.1 8.5 7.5v.5a3 3 0 0 1-3 3h-11a3 3 0 0 1-3-3z"/>'
           '<path d="M8.5 10.5l-1 3M12.5 9.5l-1 3.5M16.5 10.5l-1 3"/>',
    "moto": '<circle cx="6" cy="17" r="2.6"/><circle cx="18" cy="17" r="2.6"/><path d="M8.6 17h6.8"/>'
            '<path d="M14 6h2.5l2.3 8.4"/><path d="M3.5 12.5h7.5l2.5 4.5"/><path d="M11 12.5V9.5h3.5"/>',
    "etiqueta": '<path d="M3.5 12.2V4.5a1 1 0 0 1 1-1h7.7l8.3 8.3a1 1 0 0 1 0 1.4l-7.3 7.3a1 1 0 0 1-1.4 0z"/>'
                '<circle cx="8" cy="8" r="1.6"/>',
    "foco": '<path d="M9.5 18h5M10.5 21h3"/><path d="M12 3a6 6 0 0 0-3.6 10.8c.7.5 1.1 1.3 1.1 2.1v.1h5v-.1'
            'c0-.8.4-1.6 1.1-2.1A6 6 0 0 0 12 3z"/>',
    "sync": '<path d="M19.5 11A7.5 7.5 0 0 0 6 6.6L4.5 8"/><path d="M4.5 4v4h4"/>'
            '<path d="M4.5 13A7.5 7.5 0 0 0 18 17.4l1.5-1.4"/><path d="M19.5 20v-4h-4"/>',
    "calendario": '<rect x="3.5" y="5" width="17" height="15.5" rx="2"/><path d="M3.5 10h17M8 3v4M16 3v4"/>',
    "carrito": '<path d="M3 4h2.2l2.2 10.2a1.5 1.5 0 0 0 1.5 1.2h8.3a1.5 1.5 0 0 0 1.5-1.1L20.5 8H6.3"/>'
               '<circle cx="9.5" cy="19.5" r="1.4"/><circle cx="17" cy="19.5" r="1.4"/>',
}


def icono(nombre: str, tam: int = 18, grosor: float = 1.8, color: str = "currentColor") -> str:
    """Devuelve el SVG en línea de un icono."""
    trazo = _TRAZOS.get(nombre, _TRAZOS["grafica"])
    return (f'<svg width="{tam}" height="{tam}" viewBox="0 0 24 24" fill="none" stroke="{color}" '
            f'stroke-width="{grosor}" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">{trazo}</svg>')


def jaiba(tam: int = 46) -> str:
    """La jaiba de Tortas Jaibo: dibujo propio, sencillo, en el rojo de la marca."""
    return (f'<svg width="{tam}" height="{tam}" viewBox="0 0 48 48" aria-label="Tortas Jaibo" role="img">'
            '<circle cx="24" cy="24" r="23" fill="#C8102E"/>'
            '<g fill="none" stroke="#FFF8EA" stroke-width="2.3" stroke-linecap="round" stroke-linejoin="round">'
            # tenazas
            '<path d="M14.5 24.5l-4.5-5.5"/><path d="M10 19l-2.6-3.6M10 19l3.6-1.6"/>'
            '<path d="M33.5 24.5l4.5-5.5"/><path d="M38 19l2.6-3.6M38 19l-3.6-1.6"/>'
            # patitas
            '<path d="M13.6 29.5l-4.4 2.2M14.6 32.6l-3.6 3.4M34.4 29.5l4.4 2.2M33.4 32.6l3.6 3.4"/>'
            # ojos con su tallo
            '<path d="M20.5 21.2v-4M27.5 21.2v-4"/></g>'
            # cuerpo
            '<path d="M13.5 28.3c0-4.6 4.7-7.5 10.5-7.5s10.5 2.9 10.5 7.5-4.7 6.9-10.5 6.9-10.5-2.3-10.5-6.9z" '
            'fill="#FFF8EA"/>'
            '<circle cx="20.5" cy="15.6" r="2.4" fill="#FFF8EA"/><circle cx="27.5" cy="15.6" r="2.4" fill="#FFF8EA"/>'
            '<circle cx="20.9" cy="15.8" r="1.1" fill="#2B2320"/><circle cx="27.9" cy="15.8" r="1.1" fill="#2B2320"/>'
            '<path d="M20.5 28.6c2 1.6 5 1.6 7 0" fill="none" stroke="#C8102E" stroke-width="2" stroke-linecap="round"/>'
            '</svg>')

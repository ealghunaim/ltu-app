"""Tiny dependency-free SVG line charts (FEV1 / tacrolimus trend)."""
from markupsafe import Markup


def line_chart(points, width=520, height=170, band=None, unit="", color="#0f5470", title=""):
    """points: [(label, value)] chronological; band: (low, high) shaded target range."""
    pts = [(l, v) for l, v in points if v is not None]
    if len(pts) < 1:
        return Markup('<p class="muted">No data yet.</p>')
    pad_l, pad_r, pad_t, pad_b = 38, 12, 14, 26
    vals = [v for _, v in pts] + (list(band) if band else [])
    lo, hi = min(vals), max(vals)
    if hi == lo:
        hi, lo = hi + 1, lo - 1
    span = hi - lo
    lo -= span * 0.08
    hi += span * 0.08
    W, H = width - pad_l - pad_r, height - pad_t - pad_b

    def X(i):
        return pad_l + (W * i / (len(pts) - 1) if len(pts) > 1 else W / 2)

    def Y(v):
        return pad_t + H - (v - lo) / (hi - lo) * H
    out = [f'<svg viewBox="0 0 {width} {height}" class="chart" role="img" aria-label="{title}">']
    if band:
        out.append(f'<rect x="{pad_l}" y="{Y(band[1]):.1f}" width="{W}" height="{max(Y(band[0]) - Y(band[1]), 1):.1f}" fill="#e6f4ea"/>')
        out.append(f'<text x="{pad_l + 4}" y="{Y(band[1]) + 11:.1f}" font-size="9" fill="#2e7d32">target {band[0]:g}-{band[1]:g}</text>')
    for k in range(3):
        v = lo + (hi - lo) * k / 2
        out.append(f'<line x1="{pad_l}" x2="{pad_l + W}" y1="{Y(v):.1f}" y2="{Y(v):.1f}" stroke="#e5e7eb"/>'
                   f'<text x="{pad_l - 4}" y="{Y(v) + 3:.1f}" font-size="9" text-anchor="end" fill="#6b7280">{v:.1f}</text>')
    if len(pts) > 1:
        out.append('<polyline fill="none" stroke="%s" stroke-width="2" points="%s"/>' % (color, " ".join(f"{X(i):.1f},{Y(v):.1f}" for i, (_, v) in enumerate(pts))))
    for i, (l, v) in enumerate(pts):
        out.append(f'<circle cx="{X(i):.1f}" cy="{Y(v):.1f}" r="3.5" fill="{color}"><title>{l}: {v:g}{unit}</title></circle>')
        if len(pts) <= 12 or i % 2 == 0:
            out.append(f'<text x="{X(i):.1f}" y="{height - 8}" font-size="8" text-anchor="middle" fill="#6b7280">{l}</text>')
    out.append("</svg>")
    return Markup("".join(out))

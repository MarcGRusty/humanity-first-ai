"""A dependency-free SVG line chart for the training report (loss over time)."""

from __future__ import annotations

from html import escape


def line_chart(series: dict[str, list[tuple[float, float]]], title: str, x_label: str, y_label: str,
               width: int = 720, height: int = 360) -> str:
    colours = ["#2563eb", "#dc2626", "#059669", "#d97706"]
    points = [p for values in series.values() for p in values]
    if not points:
        return f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="60"><text x="10" y="30">No data</text></svg>'
    left, right, top, bottom = 64, 16, 40, 48
    xs, ys = [p[0] for p in points], [p[1] for p in points]
    x0, x1 = min(xs), max(xs) or 1
    y0, y1 = min(ys), max(ys)
    if y1 == y0:
        y1 = y0 + 1
    if x1 == x0:
        x1 = x0 + 1

    def sx(x):
        return left + (x - x0) / (x1 - x0) * (width - left - right)

    def sy(y):
        return top + (1 - (y - y0) / (y1 - y0)) * (height - top - bottom)

    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" '
             f'font-family="sans-serif" font-size="12">',
             f'<rect width="{width}" height="{height}" fill="white"/>',
             f'<text x="{width / 2}" y="22" text-anchor="middle" font-size="15">{escape(title)}</text>']
    for i in range(5):
        value = y0 + (y1 - y0) * i / 4
        y = sy(value)
        parts.append(f'<line x1="{left}" x2="{width - right}" y1="{y:.1f}" y2="{y:.1f}" stroke="#e5e7eb"/>')
        parts.append(f'<text x="{left - 6}" y="{y + 4:.1f}" text-anchor="end">{value:.2f}</text>')
    for i in range(5):
        value = x0 + (x1 - x0) * i / 4
        anchor = "start" if i == 0 else "end" if i == 4 else "middle"
        parts.append(f'<text x="{sx(value):.1f}" y="{height - bottom + 18}" text-anchor="{anchor}">{value:,.0f}</text>')
    parts.append(f'<text x="{width / 2}" y="{height - 8}" text-anchor="middle">{escape(x_label)}</text>')
    parts.append(f'<text x="14" y="{height / 2}" text-anchor="middle" transform="rotate(-90 14 {height / 2})">{escape(y_label)}</text>')
    for index, (name, values) in enumerate(series.items()):
        if not values:
            continue
        colour = colours[index % len(colours)]
        path = " ".join(f"{'M' if i == 0 else 'L'}{sx(x):.1f},{sy(y):.1f}" for i, (x, y) in enumerate(values))
        parts.append(f'<path d="{path}" fill="none" stroke="{colour}" stroke-width="2"/>')
        parts.append(f'<text x="{width - right - 150}" y="{top + 14 + 16 * index}" fill="{colour}">— {escape(name)}</text>')
    parts.append("</svg>")
    return "\n".join(parts)

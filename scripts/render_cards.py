#!/usr/bin/env python3
"""
Renderiza os cards SVG animados do README do perfil em cards/.

    python scripts/render_cards.py            # cards animados  -> cards/
    STATIC=1 python scripts/render_cards.py   # quadro final    -> cards_static/ (+ preview.html)

Os cards são exibidos via <img>, então só usam o que funciona ali dentro:
um <style> inline com @keyframes, elementos SMIL (<set>/<animate>) e fontes
subsetadas com pyftsubset, embutidas como data URI WOFF em base64.
Tudo que se move desliga sob prefers-reduced-motion.

Dados: data/contributions.json (atualizado diariamente por
scripts/fetch_contributions.py na GitHub Action).
"""
from __future__ import annotations

import base64
import datetime as dt
import html
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections import defaultdict
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATIC = os.environ.get("STATIC") == "1"
OUT = ROOT / ("cards_static" if STATIC else "cards")
DATA = ROOT / "data" / "contributions.json"
FONT_DIR = ROOT / "fonts"
README = ROOT / "README.md"

# ─────────────────────────────── conteúdo ───────────────────────────────

USER = "ViniciusVilelaRufini"
GH = f"https://github.com/{USER}"

PROFILE = {
    "name": ["VINICIUS VILELA", "RUFINI"],
    "kicker": "Desenvolvedor Full Stack · Web & Mobile · IA",
    "line": "Transformo ideias em produtos digitais completos — da modelagem "
            "de dados e APIs até interfaces fluidas em Web e Mobile.",
    "stack": ["TypeScript", "NestJS", "Prisma", "Flutter", "React", "PostgreSQL"],
    # Opcional: coloque uma foto quadrada aqui e ela vira um retrato em meio-tom.
    "portrait": "assets/portrait.png",
    "monogram": "VR",
}

TILES = [
    {"slug": "projetos", "idx": "01", "label": "Projetos", "count": "public_repos",
     "fallback": 9, "caption": "repositórios públicos", "href": f"{GH}?tab=repositories"},
    {"slug": "prestare", "idx": "02", "label": "Prestare", "title": ["Gestão", "condominial"],
     "caption": "prestarecondominios.com.br", "href": "https://prestarecondominios.com.br"},
    {"slug": "pesquisa", "idx": "03", "label": "Pesquisa", "title": ["Kanban", "Semântico"],
     "caption": "TCC · Kabania · LLMs + RLS", "href": f"{GH}/kabania"},
]

REPOS = [
    {"repo": "Prestare-IA", "title": "Prestare IA",
     "desc": "Plataforma de gestão condominial com backend escalável e frontend multiplataforma.",
     "stack": ["NestJS", "Prisma", "Flutter"]},
    {"repo": "kabania", "title": "Kabania",
     "desc": "Gestão com IA sobre o Kanban Cognitivo de Ciclo Fechado: fluxo visual e decisão orientada por dados.",
     "stack": ["JavaScript", "IA"]},
    {"repo": "Aluguel-moto", "title": "Volti",
     "desc": "App de aluguel de motos elétricas, com retirada no galpão.",
     "stack": ["TypeScript", "Mobile"]},
    {"repo": "Trading-ia", "title": "Trading IA",
     "desc": "Experimentos com IA aplicada a análise de mercado.",
     "stack": ["JavaScript", "IA"]},
]

# Linha do tempo (s): a página toca de cima para baixo.
T_HERO, T_TILES, T_ACTIVITY, T_REPOS, T_GRAPH = 0.0, 1.0, 1.8, 3.0, 4.2

# ─────────────────────────────── marca ───────────────────────────────
# Mesmos tokens do prestarecondominios.com.br (tema dark monocromático).
BG, BG2, BG3 = "#0b0b0b", "#141414", "#1f1f1f"
LINE, LINE2 = "#242424", "#666666"
INK, MUTED, SUBTLE = "#ffffff", "#a3a3a3", "#8a8a8a"
BRAND = "#ffc83d"
GRID = "rgba(255,255,255,.045)"

FONTS = {  # chave -> (arquivo, família CSS, peso)
    "sans": ("Barlow-Regular.ttf", "vr-sans", 400),
    "sansm": ("Barlow-Medium.ttf", "vr-sans-m", 500),
    "cond": ("BarlowCondensed-SemiBold.ttf", "vr-cond", 600),
    "condb": ("BarlowCondensed-Bold.ttf", "vr-cond-b", 700),
}
FALLBACK = {"sans": "Barlow,system-ui,sans-serif", "sansm": "Barlow,system-ui,sans-serif",
            "cond": "'Barlow Condensed','Arial Narrow',sans-serif",
            "condb": "'Barlow Condensed','Arial Narrow',sans-serif"}

MESES = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]
EASE = "cubic-bezier(.2,.8,.2,1)"

# ─────────────────────────────── fontes ───────────────────────────────


@lru_cache(maxsize=None)
def _metrics(key: str):
    from fontTools.ttLib import TTFont
    f = TTFont(FONT_DIR / FONTS[key][0])
    return f.getBestCmap(), f["hmtx"].metrics, f["head"].unitsPerEm


def measure(s: str, key: str, size: float, ls: float = 0) -> float:
    cmap, hmtx, upm = _metrics(key)
    w = 0
    for ch in s:
        g = cmap.get(ord(ch))
        w += (hmtx[g][0] if g else upm * 0.5) * size / upm
    return w + ls * len(s)


def wrap(s: str, key: str, size: float, width: float) -> list[str]:
    lines, cur = [], ""
    for word in s.split():
        t = f"{cur} {word}".strip()
        if cur and measure(t, key, size) > width:
            lines.append(cur)
            cur = word
        else:
            cur = t
    return lines + ([cur] if cur else [])


@lru_cache(maxsize=None)
def subset_b64(key: str, text: str) -> str:
    """Subseta a fonte só com os caracteres usados no card (pyftsubset -> WOFF)."""
    src = FONT_DIR / FONTS[key][0]
    tool = shutil.which("pyftsubset")
    cmd = [tool] if tool else [sys.executable, "-m", "fontTools.subset"]
    with tempfile.TemporaryDirectory() as td:
        tf, out = Path(td) / "chars.txt", Path(td) / "out.woff"
        tf.write_text(text, encoding="utf-8")
        subprocess.run(cmd + [str(src), f"--text-file={tf}", "--flavor=woff",
                              "--layout-features=kern", "--no-hinting", "--desubroutinize",
                              f"--output-file={out}"], check=True)
        return base64.b64encode(out.read_bytes()).decode()


# ─────────────────────────────── helpers SVG ───────────────────────────────

def esc(s) -> str:
    return html.escape(str(s), quote=True)


def A(name: str, delay: float, dur: float = 0.7, ease: str = EASE, more: str = "both") -> str:
    """Declaração CSS de animação (vazia em STATIC=1)."""
    if STATIC:
        return ""
    return f"animation:{name} {dur:.2f}s {ease} {delay:.3f}s {more};"


def fmt(n: int) -> str:
    return f"{n:,}".replace(",", ".")


def fdate(d: dt.date) -> str:
    return f"{d.day} {MESES[d.month - 1]} {d.year}"


BASE_CSS = f"""
text{{font-kerning:normal}}
.ab{{transform-box:fill-box;transform-origin:50% 50%}}
.ob{{transform-box:fill-box;transform-origin:50% 100%}}
.ol{{transform-box:fill-box;transform-origin:0 50%}}
@keyframes up{{from{{opacity:0;transform:translateY(14px)}}}}
@keyframes rise{{from{{transform:translateY(105%)}}}}
@keyframes fade{{from{{opacity:0}}}}
@keyframes show{{from{{opacity:0}}to{{opacity:0}}}}
@keyframes grow{{from{{transform:scaleY(0)}}}}
@keyframes growx{{from{{transform:scaleX(0)}}}}
@keyframes pop{{from{{opacity:0;transform:scale(.3)}}}}
@keyframes draw{{from{{stroke-dashoffset:1}}}}
@keyframes swing{{0%{{opacity:0;transform:translateY(46px) rotate(-7deg)}}
  55%{{opacity:1;transform:translateY(-7px) rotate(1.6deg)}}
  78%{{transform:translateY(2px) rotate(-.5deg)}}100%{{transform:none}}}}
@keyframes pulse{{0%{{opacity:.8;transform:scale(.4)}}70%,100%{{opacity:0;transform:scale(2.4)}}}}
@keyframes shine{{0%,72%{{transform:translateX(-140%) skewX(-18deg)}}100%{{transform:translateX(420%) skewX(-18deg)}}}}
@keyframes nudge{{0%,60%,100%{{transform:translate(0,0)}}80%{{transform:translate(3px,-3px)}}}}
@keyframes blink{{50%{{opacity:.25}}}}
"""
REDUCED_CSS = """
@media (prefers-reduced-motion: reduce){
  *{animation:none!important}
  .mo{display:none}
}
"""


class Card:
    def __init__(self, w: int, h: int, title: str, desc: str = ""):
        self.w, self.h, self.title, self.desc = w, h, title, desc
        self.chars: dict[str, set] = defaultdict(set)
        self.defs: list[str] = []
        self.parts: list[str] = []

    def text(self, x, y, s, font="sans", size=14, fill=INK, anchor="start", ls=0,
             style="", cls="", extra="") -> str:
        s = str(s)
        self.chars[font].update(s)
        fam = FONTS[font][1]
        a = [f'x="{x:.1f}"', f'y="{y:.1f}"', f'font-family="{fam},{esc(FALLBACK[font])}"',
             f'font-size="{size}"', f'font-weight="{FONTS[font][2]}"', f'fill="{fill}"']
        if anchor != "start":
            a.append(f'text-anchor="{anchor}"')
        if ls:
            a.append(f'letter-spacing="{ls}"')
        if style:
            a.append(f'style="{style}"')
        if cls:
            a.append(f'class="{cls}"')
        return f"<text {' '.join(a)}{extra}>{esc(s)}</text>"

    def frame(self, x=0.5, y=0.5, w=None, h=None, rx=14) -> str:
        w = self.w - 1 if w is None else w
        h = self.h - 1 if h is None else h
        return f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" fill="{BG}" stroke="{LINE}"/>'

    def count_up(self, x, y, value: int, t0: float, dur: float, font="condb", size=64,
                 fill=INK, anchor="start", frames=18, formatter=fmt) -> str:
        """Contador com quadros SMIL <set>; o valor final é um texto comum que aparece no fim."""
        final = self.text(x, y, formatter(value), font, size, fill, anchor,
                          style=A("show", 0, t0 + dur, "linear", "backwards"))
        if STATIC or value <= 0:
            return final
        n = min(frames, value)
        vals = sorted({round(value * (1 - (1 - i / n) ** 3)) for i in range(n)})
        step = dur / len(vals)
        out = []
        for i, v in enumerate(vals):
            b = t0 + i * step
            t = self.text(x, y, formatter(v), font, size, fill, anchor, extra=' visibility="hidden"')
            set_ = (f'<set attributeName="visibility" to="visible" begin="{b:.3f}s" '
                    f'end="{b + step:.3f}s"/>')
            out.append(t.replace("</text>", set_ + "</text>"))
        return final + f'<g class="mo">{"".join(out)}</g>'

    def arrow(self, x, y, size=12, color=INK, delay=0.0) -> str:
        """Seta ↗ desenhada (o Barlow não tem o glifo), com um empurrãozinho periódico."""
        s = size
        p = f"M{x} {y + s}L{x + s} {y}M{x + 3} {y}H{x + s}V{y + s - 3}"
        st = A("nudge", delay, 2.6, "ease-in-out", "infinite")
        return (f'<path d="{p}" fill="none" stroke="{color}" stroke-width="1.8" '
                f'stroke-linecap="round" stroke-linejoin="round" class="ab" style="{st}"/>')

    def render(self) -> str:
        faces = []
        for key, chars in sorted(self.chars.items()):
            text = "".join(sorted(chars | set("0123456789 ")))
            faces.append(f"@font-face{{font-family:{FONTS[key][1]};font-weight:{FONTS[key][2]};"
                         f"src:url(data:font/woff;base64,{subset_b64(key, text)}) format('woff')}}")
        css = "".join(faces) + BASE_CSS + ("" if STATIC else REDUCED_CSS)
        css = re.sub(r"\s*\n\s*", "", css)
        return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{self.w}" height="{self.h}" '
                f'viewBox="0 0 {self.w} {self.h}" role="img" aria-labelledby="t d">'
                f'<title id="t">{esc(self.title)}</title><desc id="d">{esc(self.desc)}</desc>'
                f"<style>{css}</style><defs>{''.join(self.defs)}</defs>"
                f"{''.join(self.parts)}</svg>")


# ─────────────────────────────── dados ───────────────────────────────

def load_data() -> dict:
    d = json.loads(DATA.read_text(encoding="utf-8"))
    days = sorted((dt.date.fromisoformat(x["date"]), int(x["count"]), int(x.get("level", -1)))
                  for x in d["days"])
    d["_days"] = days
    return d


def stats(days):
    counts = {k: c for k, c, _ in days}
    today = days[-1][0]
    window = [x for x in days if x[0] > today - dt.timedelta(days=365)]
    # sequência atual (se hoje ainda está zerado, conta até ontem)
    cur, d = 0, today
    if counts.get(d, 0) == 0:
        d -= dt.timedelta(days=1)
    while counts.get(d, 0) > 0:
        cur += 1
        d -= dt.timedelta(days=1)
    best = run = 0
    for _, c, _ in window:
        run = run + 1 if c else 0
        best = max(best, run)
    busiest = max(window, key=lambda x: (x[1], x[0]))
    months = []
    y, m = today.year, today.month
    for _ in range(12):
        months.append((y, m))
        y, m = (y, m - 1) if m > 1 else (y - 1, 12)
    months.reverse()
    per = {k: 0 for k in months}
    for day, c, _ in days:
        if (day.year, day.month) in per:
            per[(day.year, day.month)] += c
    return {
        "today": today, "total": sum(c for _, c, _ in window), "current": cur, "longest": best,
        "active": sum(1 for _, c, _ in window if c), "busiest": busiest,
        "months": [(k, per[k]) for k in months],
    }


# ─────────────────────────────── cards ───────────────────────────────

def portrait_dots(card: Card, x0, y0, size, t0) -> str:
    """Retrato em meio-tom a partir de assets/portrait.png; sem foto, um campo radial com monograma."""
    n = 40
    cell = size / n
    path = ROOT / PROFILE["portrait"]
    lum = None
    if path.exists():
        try:
            from PIL import Image, ImageOps
            im = ImageOps.fit(Image.open(path).convert("L"), (n, n))
            im = ImageOps.autocontrast(im, cutoff=2)
            px = list(im.getdata())
            lum = [[px[r * n + c] / 255 for c in range(n)] for r in range(n)]
        except Exception as e:  # noqa: BLE001
            print(f"retrato ignorado: {e}", file=sys.stderr)
    rows = []
    for r in range(n):
        dots = []
        for c in range(n):
            dx, dy = (c + .5) / n - .5, (r + .5) / n - .5
            dist = math.hypot(dx, dy)
            if dist > .5:
                continue
            if lum is not None:
                v = lum[r][c] * min(1, (0.5 - dist) * 8)
            else:
                ring = math.exp(-((dist - .43) / .03) ** 2)
                v = max(ring, (1 - dist * 2) ** .9 * (.35 + .65 * math.cos(math.atan2(dy, dx) * 3 + dist * 14) ** 2))
            rad = cell * 0.48 * v
            if lum is None and abs(dx) < .26 and abs(dy) < .2:
                continue  # área coberta pelo monograma
            if rad < 0.5:
                continue
            col = BRAND if (lum is None and dist > .38) or (lum is not None and v > .8) else INK
            op = .9 if col == BRAND else .25 + .6 * v
            dots.append(f'<circle cx="{x0 + (c + .5) * cell:.1f}" cy="{y0 + (r + .5) * cell:.1f}" '
                        f'r="{rad:.2f}" fill="{col}" fill-opacity="{op:.2f}"/>')
        if dots:
            rows.append(f'<g style="{A("fade", t0 + r * 0.018, .45)}">{"".join(dots)}</g>')
    out = "".join(rows)
    if lum is None:
        cx, cy = x0 + size / 2, y0 + size / 2 + 22
        out += (f'<g class="ab" style="{A("pop", t0 + .7, .7)}">'
                + card.text(cx, cy + 6, PROFILE["monogram"], "condb", 92, INK, "middle", ls=2,
                            extra=f' stroke="{BG}" stroke-width="10" paint-order="stroke"')
                + "</g>")
    return out


def hero(data) -> Card:
    W, H = 840, 312
    c = Card(W, H, "Vinicius Vilela Rufini", PROFILE["line"])
    t = T_HERO
    c.defs.append(f'<pattern id="grid" width="24" height="24" patternUnits="userSpaceOnUse">'
                  f'<path d="M24 0H0V24" fill="none" stroke="{GRID}"/></pattern>'
                  f'<clipPath id="cl"><rect x=".5" y=".5" width="{W - 1}" height="{H - 1}" rx="14"/></clipPath>'
                  f'<linearGradient id="sh" x1="0" x2="1"><stop offset="0" stop-color="{BRAND}" stop-opacity="0"/>'
                  f'<stop offset=".5" stop-color="{BRAND}"/><stop offset="1" stop-color="{BRAND}" stop-opacity="0"/>'
                  f'</linearGradient>')
    p = c.parts
    p.append(c.frame())
    p.append(f'<g clip-path="url(#cl)"><rect x="560" y="0" width="280" height="{H}" fill="url(#grid)" '
             f'style="{A("fade", t, 1.2)}"/></g>')
    # rótulo com ponto pulsante
    p.append(f'<circle cx="42" cy="50" r="4" fill="{BRAND}"/>')
    if not STATIC:
        p.append(f'<circle cx="42" cy="50" r="4" fill="none" stroke="{BRAND}" class="ab mo" '
                 f'style="{A("pulse", t + .4, 2.2, "ease-out", "infinite")}"/>')
    p.append(c.text(56, 54.5, PROFILE["kicker"].upper(), "sansm", 12, MUTED, ls=2.2,
                    style=A("fade", t + .1, .6)))
    # nome: cada linha sobe de dentro de uma máscara
    ys = [122, 182]
    for i, (line, y) in enumerate(zip(PROFILE["name"], ys)):
        c.defs.append(f'<clipPath id="nm{i}"><rect x="0" y="{y - 60}" width="600" height="72"/></clipPath>')
        col = INK if i == 0 else BRAND
        txt = c.text(34, y, line, "condb", 66, col, ls=.5)
        p.append(f'<g clip-path="url(#nm{i})"><g style="{A("rise", t + .25 + i * .14, .8)}">{txt}</g></g>')
        if i == 0 and not STATIC:
            # brilho que atravessa o nome (overlay; some sob reduced-motion)
            wname = measure(line, "condb", 66, .5)
            c.defs.append(f'<clipPath id="nmt">{txt}</clipPath>')
            p.append(f'<g clip-path="url(#nmt)" class="mo"><rect x="-80" y="{y - 60}" width="80" height="72" '
                     f'fill="url(#sh)" opacity=".85">'
                     f'<animate attributeName="x" values="-80;{wname + 60:.0f};{wname + 60:.0f}" '
                     f'keyTimes="0;.28;1" dur="7s" begin="{t + 1.3:.2f}s" repeatCount="indefinite"/></rect></g>')
    # linha da marca desenhando sob o nome
    p.append(f'<path d="M36 206H{36 + 120}" stroke="{BRAND}" stroke-width="2" pathLength="1" '
             f'stroke-dasharray="1" style="{A("draw", t + .7, .8)}"/>')
    # uma linha sobre mim
    for i, ln in enumerate(wrap(PROFILE["line"], "sans", 16, 500)[:2]):
        p.append(c.text(34, 236 + i * 22, ln, "sans", 16, MUTED, style=A("up", t + .8 + i * .08, .7)))
    # stack
    x = 34
    for i, s in enumerate(PROFILE["stack"]):
        w = measure(s.upper(), "sansm", 10.5, 1.4) + 18
        if x + w > 560:
            break
        p.append(f'<g class="ab" style="{A("pop", t + 1.05 + i * .06, .5)}">'
                 f'<rect x="{x}" y="{H - 44}" width="{w:.1f}" height="20" rx="10" fill="{BG2}" stroke="{LINE}"/>'
                 + c.text(x + w / 2, H - 30, s.upper(), "sansm", 10.5, INK, "middle", ls=1.4) + "</g>")
        x += w + 6
    # retrato
    p.append(portrait_dots(c, 600, 51, 210, t + .3))
    return c


def tile(data, cfg, i) -> Card:
    W, H = 272, 200
    c = Card(W, H, f'{cfg["label"]} — {cfg["caption"]}', cfg["href"])
    t = T_TILES + i * .16
    cid = f"tc{i}"
    c.defs.append(f'<clipPath id="{cid}"><rect x="6" y="6" width="{W - 12}" height="{H - 12}" rx="12"/></clipPath>'
                  f'<linearGradient id="sw{i}" x1="0" x2="1"><stop offset="0" stop-color="#fff" stop-opacity="0"/>'
                  f'<stop offset=".5" stop-color="#fff" stop-opacity=".09"/><stop offset="1" stop-color="#fff" stop-opacity="0"/>'
                  f'</linearGradient>')
    inner = [c.frame(6, 6, W - 12, H - 12, 12)]
    motion = "" if STATIC else (
        f'<circle cx="{W - 6}" cy="{H - 6}" r="34" fill="none" stroke="{BRAND}" stroke-width="1.5" '
        f'class="ab mo" style="{A("pulse", t + .9, 3.2, "ease-out", "infinite")}"/>'
        f'<rect x="0" y="0" width="70" height="{H}" fill="url(#sw{i})" class="mo" '
        f'style="{A("shine", t + 1.2, 6.5, "ease-in-out", "infinite")}"/>')
    inner.append(f'<g clip-path="url(#{cid})">{motion}'
                 f'<circle cx="{W - 6}" cy="{H - 6}" r="22" fill="{BRAND}" fill-opacity=".1"/></g>')
    inner.append(c.text(24, 38, cfg["idx"], "cond", 14, BRAND, ls=1))
    inner.append(c.text(46, 38, cfg["label"].upper(), "sansm", 11.5, MUTED, ls=2.4))
    inner.append(c.arrow(W - 38, 26, 11, INK, t + 1.4))
    if "count" in cfg:
        v = int(data.get("profile", {}).get(cfg["count"], cfg["fallback"]))
        inner.append(c.count_up(22, 134, v, t + .45, .9, "condb", 84, INK))
    else:
        for j, ln in enumerate(cfg["title"]):
            inner.append(c.text(23, 96 + j * 36, ln, "condb", 38, INK if j == 0 else BRAND,
                                style=A("up", t + .45 + j * .07, .6)))
    inner.append(f'<path d="M24 152H64" stroke="{LINE2}" pathLength="1" stroke-dasharray="1" '
                 f'style="{A("draw", t + .6, .6)}"/>')
    inner.append(c.text(24, 174, cfg["caption"], "sans", 13, MUTED, style=A("fade", t + .65, .6)))
    c.parts.append(f'<g class="ob" style="{A("swing", t, 1.0, "cubic-bezier(.3,.7,.3,1)")}">{"".join(inner)}</g>')
    return c


def activity(data, st) -> Card:
    W, H = 840, 380
    c = Card(W, H, "Atividade nos últimos 12 meses",
             f'{fmt(st["total"])} contribuições, sequência atual de {st["current"]} dias')
    t = T_ACTIVITY
    p = c.parts
    p.append(c.frame())
    p.append(c.text(34, 46, "ATIVIDADE · ÚLTIMOS 12 MESES", "sansm", 12, MUTED, ls=2.2, style=A("fade", t, .6)))
    p.append(c.text(W - 34, 46, f'atualizado em {fdate(st["today"])}', "sans", 12, SUBTLE, "end",
                    style=A("fade", t + .1, .6)))
    p.append(c.count_up(32, 116, st["total"], t + .15, 1.1, "condb", 64, INK))
    p.append(c.text(34, 140, "contribuições", "sans", 14, MUTED, style=A("fade", t + .3, .6)))
    b = st["busiest"]
    blocks = [
        ("SEQUÊNCIA ATUAL", f'{st["current"]}', "dias" if st["current"] != 1 else "dia", BRAND),
        ("MAIOR SEQUÊNCIA", f'{st["longest"]}', "dias", INK),
        ("DIAS ATIVOS", f'{st["active"]}', "de 365", INK),
        ("DIA MAIS INTENSO", fmt(b[1]), f"{b[0].day} {MESES[b[0].month - 1]} {b[0].year}", INK),
    ]
    x0, colw = 288, 128
    for i, (lab, val, sub, col) in enumerate(blocks):
        x = x0 + i * colw
        d = t + .35 + i * .08
        p.append(f'<path d="M{x} 74V138" stroke="{LINE}" style="{A("fade", d, .5)}"/>')
        p.append(c.text(x + 14, 86, lab, "sansm", 10, SUBTLE, ls=1.6, style=A("fade", d, .5)))
        p.append(c.text(x + 14, 120, val, "condb", 34, col, style=A("up", d + .05, .6)))
        vw = measure(val, "condb", 34)
        p.append(c.text(x + 18 + vw, 120, sub, "sans", 12, MUTED, style=A("fade", d + .15, .6)))
    # barras por mês
    months = st["months"]
    top, base = 186, 330
    mx = max(v for _, v in months) or 1
    left, right = 34, W - 34
    slot = (right - left) / len(months)
    bw = slot * .56
    for g in range(4):
        y = base - (base - top) * g / 3
        p.append(f'<path d="M{left} {y:.1f}H{right}" stroke="{GRID if g else LINE}" '
                 f'style="{A("fade", t + .4, .6)}"/>')
    peak = max(range(len(months)), key=lambda i: months[i][1])
    for i, ((yy, mm), v) in enumerate(months):
        x = left + i * slot + (slot - bw) / 2
        h = max(2, (base - top) * v / mx) if v else 2
        col = BRAND if i == peak else ("#ffffff" if v else LINE)
        op = 1 if i == peak else (.22 + .5 * v / mx if v else 1)
        d = t + .55 + i * .06
        p.append(f'<rect x="{x:.1f}" y="{base - h:.1f}" width="{bw:.1f}" height="{h:.1f}" rx="3" '
                 f'fill="{col}" fill-opacity="{op:.2f}" class="ob" style="{A("grow", d, .8)}"/>')
        if v:
            p.append(c.text(x + bw / 2, base - h - 8, fmt(v), "cond", 13, BRAND if i == peak else INK, "middle",
                            style=A("fade", d + .5, .5)))
        lab = MESES[mm - 1] + (f" {str(yy)[2:]}" if mm == 1 or i == 0 else "")
        p.append(c.text(x + bw / 2, base + 22, lab, "sans", 12, MUTED, "middle", style=A("fade", d, .5)))
    return c


def repo_card(data, cfg, i) -> Card:
    W, H = 412, 180
    meta = data.get("repos", {}).get(cfg["repo"], {})
    c = Card(W, H, cfg["title"], cfg["desc"])
    t = T_REPOS + (i // 2) * .3 + (i % 2) * .12
    inner = [c.frame(0.5, 0.5, W - 1, H - 1, 12)]
    inner.append(c.text(24, 36, f"{i + 1:02d}", "cond", 14, BRAND, ls=1))
    inner.append(c.text(46, 36, cfg["repo"].upper(), "sansm", 10.5, SUBTLE, ls=1.6))
    inner.append(c.arrow(W - 36, 24, 11, INK, t + 1.2))
    inner.append(c.text(23, 76, cfg["title"].upper(), "condb", 32, INK, ls=.4, style=A("up", t + .15, .6)))
    tw = measure(cfg["title"].upper(), "condb", 32, .4)
    inner.append(f'<path d="M{24 + tw + 10:.0f} 66H{24 + tw + 34:.0f}" stroke="{BRAND}" stroke-width="2" '
                 f'pathLength="1" stroke-dasharray="1" style="{A("draw", t + .45, .5)}"/>')
    for j, ln in enumerate(wrap(cfg["desc"], "sans", 13.5, W - 48)[:2]):
        inner.append(c.text(24, 102 + j * 19, ln, "sans", 13.5, MUTED, style=A("fade", t + .3 + j * .06, .6)))
    # rodapé: linguagem · atualizado · site
    y = H - 24
    inner.append(f'<path d="M24 {y - 20}H{W - 24}" stroke="{LINE}" class="ol" style="{A("growx", t + .4, .7)}"/>')
    x = 24
    lang = meta.get("language") or cfg["stack"][0]
    inner.append(f'<circle cx="{x + 4}" cy="{y - 4}" r="4" fill="{BRAND}" style="{A("fade", t + .5, .5)}"/>')
    inner.append(c.text(x + 14, y, lang, "sansm", 12, INK, style=A("fade", t + .5, .5)))
    x += 14 + measure(lang, "sansm", 12) + 14
    extra = " · ".join(s for s in cfg["stack"] if s != lang)
    if extra:
        inner.append(c.text(x, y, extra, "sans", 12, SUBTLE, style=A("fade", t + .55, .5)))
    if meta.get("pushed_at"):
        pushed = dt.datetime.fromisoformat(meta["pushed_at"].replace("Z", "+00:00")).date()
        ref = data["_days"][-1][0]
        n = (ref - pushed).days
        ago = "hoje" if n <= 0 else "ontem" if n == 1 else f"há {n} dias" if n < 45 else \
            f"há {n // 30} meses" if n < 365 else f"há {n // 365} ano{'s' if n >= 730 else ''}"
        label = f"atualizado {ago}"
        inner.append(c.text(W - 24, y, label, "sans", 12, SUBTLE, "end", style=A("fade", t + .6, .5)))
    c.parts.append(f'<g style="{A("up", t, .7)}">{"".join(inner)}</g>')
    return c


def graph(data, st) -> Card:
    W = 840
    days = data["_days"]
    first = days[0][0] - dt.timedelta(days=(days[0][0].weekday() + 1) % 7)  # domingo
    cells = {d: (cnt, lvl) for d, cnt, lvl in days}
    weeks = (days[-1][0] - first).days // 7 + 1
    gap, x0, y0 = 3, 46, 68
    cs = min(12, (W - x0 - 30) / weeks - gap)
    H = int(y0 + 7 * (cs + gap) + 50)
    c = Card(W, H, "Gráfico de contribuições",
             f'{fmt(st["total"])} contribuições nos últimos 12 meses')
    t = T_GRAPH
    p = c.parts
    p.append(c.frame())
    p.append(c.text(34, 32, "CONTRIBUIÇÕES", "sansm", 12, MUTED, ls=2.2, style=A("fade", t, .6)))
    # escala de cor da marca sobre o fundo
    nonzero = sorted(cnt for _, cnt, _ in days if cnt)

    def level(cnt, lvl):
        if lvl >= 0:
            return lvl
        if not cnt:
            return 0
        q = [nonzero[int(len(nonzero) * f)] for f in (.25, .5, .75)]
        return 1 + sum(cnt > v for v in q)

    pal = [BG3, "rgba(255,200,61,.22)", "rgba(255,200,61,.45)", "rgba(255,200,61,.72)", BRAND]
    for lab, wd in (("seg", 1), ("qua", 3), ("sex", 5)):
        p.append(c.text(x0 - 10, y0 + wd * (cs + gap) + cs - 2, lab, "sans", 10.5, SUBTLE, "end",
                        style=A("fade", t, .5)))
    last_month = None
    for w in range(weeks):
        col = []
        x = x0 + w * (cs + gap)
        for r in range(7):
            d = first + dt.timedelta(days=w * 7 + r)
            if d not in cells:
                continue
            cnt, lvl = cells[d]
            col.append(f'<rect x="{x:.1f}" y="{y0 + r * (cs + gap):.1f}" width="{cs:.1f}" height="{cs:.1f}" '
                       f'rx="2.5" fill="{pal[level(cnt, lvl)]}"/>')
            if d.day <= 7 and r == 0 and d.month != last_month:
                last_month = d.month
                p.append(c.text(x, y0 - 10, MESES[d.month - 1], "sans", 10.5, SUBTLE,
                                style=A("fade", t + .1 + w * .018, .4)))
        p.append(f'<g class="ab" style="{A("pop", t + .1 + w * .018, .45)}">{"".join(col)}</g>')
    # legenda
    ly = H - 22
    lx = W - 34 - 5 * (cs + gap) - 34
    leg = [c.text(lx - 8, ly + cs - 2, "menos", "sans", 10.5, SUBTLE, "end")]
    for i, colr in enumerate(pal):
        leg.append(f'<rect x="{lx + i * (cs + gap):.1f}" y="{ly}" width="{cs:.1f}" height="{cs:.1f}" rx="2.5" fill="{colr}"/>')
    leg.append(c.text(lx + 5 * (cs + gap) + 5, ly + cs - 2, "mais", "sans", 10.5, SUBTLE))
    p.append(f'<g style="{A("fade", t + 1.2, .6)}">{"".join(leg)}</g>')
    p.append(c.text(34, ly + cs - 2, f'{st["active"]} dias ativos · maior sequência {st["longest"]} dias',
                    "sans", 11.5, MUTED, style=A("fade", t + 1.2, .6)))
    return c


# ─────────────────────────────── saída ───────────────────────────────

def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def readme_block() -> str:
    L = ['<div align="center">', "",
         '<img src="./cards/hero.svg" width="100%" alt="Vinicius Vilela Rufini — Desenvolvedor Full Stack"/>', ""]
    for cfg in TILES:
        L.append(f'<a href="{cfg["href"]}"><img src="./cards/tile-{cfg["slug"]}.svg" width="32.5%" '
                 f'alt="{esc(cfg["label"])}: {esc(cfg["caption"])}"/></a>')
    L += ["", '<img src="./cards/activity.svg" width="100%" alt="Contribuições por mês, sequência e dia mais intenso"/>', ""]
    for i, cfg in enumerate(REPOS):
        L.append(f'<a href="{GH}/{cfg["repo"]}"><img src="./cards/repo-{slug(cfg["repo"])}.svg" '
                 f'width="49.5%" alt="{esc(cfg["title"])}: {esc(cfg["desc"])}"/></a>')
    L += ["", '<img src="./cards/graph.svg" width="100%" alt="Gráfico de contribuições"/>', "", "</div>"]
    return "\n".join(L)


def main():
    data = load_data()
    st = stats(data["_days"])
    OUT.mkdir(exist_ok=True)
    cards = {"hero": hero(data)}
    for i, cfg in enumerate(TILES):
        cards[f'tile-{cfg["slug"]}'] = tile(data, cfg, i)
    cards["activity"] = activity(data, st)
    for i, cfg in enumerate(REPOS):
        cards[f'repo-{slug(cfg["repo"])}'] = repo_card(data, cfg, i)
    cards["graph"] = graph(data, st)
    for name, card in cards.items():
        svg = card.render()
        (OUT / f"{name}.svg").write_text(svg, encoding="utf-8")
        print(f"{name:22s} {len(svg) / 1024:6.1f} KB")

    block = readme_block()
    if STATIC:
        page = block.replace("./cards/", "./")
        (OUT / "preview.html").write_text(
            "<!doctype html><meta charset=utf-8><title>Preview</title>"
            "<style>body{background:#0d1117;margin:0;padding:24px}div{max-width:840px;margin:auto}"
            "img{vertical-align:top;margin-bottom:6px}</style>" + page, encoding="utf-8")
        print(f"preview: {OUT / 'preview.html'}")
    elif README.exists():
        text = README.read_text(encoding="utf-8")
        new = re.sub(r"(<!-- cards:start -->).*?(<!-- cards:end -->)",
                     lambda m: f"{m.group(1)}\n{block}\n{m.group(2)}", text, flags=re.S)
        if new != text:
            README.write_text(new, encoding="utf-8")


if __name__ == "__main__":
    main()

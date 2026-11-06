#!/usr/bin/env python3
"""Build the website-style GitHub profile.

A README cannot carry CSS, so every section is rendered as an SVG "component"
(light + dark variant) into assets/site/, and README.md is assembled from them.

Content lives in site.json; publications come from scripts/papers.py.
Run:  python3 scripts/build_site.py
"""
from __future__ import annotations

import base64
import datetime as dt
import json
import os
import re
import sys
import urllib.request
from html import escape as _esc
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import papers as P  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "assets" / "site"
SITE = json.loads((ROOT / "site.json").read_text())
PROFILE = SITE["profile"]
USER = PROFILE["github"]
RAW = f"https://raw.githubusercontent.com/{USER}/{USER}/main/assets/site"
W = 880
TODAY = dt.date.today()
SEEN_FILE = ROOT / "assets" / "seen.json"  # first time each paper appeared

SANS = "-apple-system,BlinkMacSystemFont,'Segoe UI','Noto Sans',Helvetica,Arial,sans-serif"
MONO = "ui-monospace,SFMono-Regular,'SF Mono',Menlo,Consolas,monospace"

THEMES = {
    "light": dict(bg="#ffffff", surface="#f6f8fa", border="#d0d7de", text="#1f2328", muted="#59636e",
                  faint="#eaeef2", a1="#6366f1", a2="#ec4899", a3="#0891b2", chip_text="#ffffff"),
    "dark": dict(bg="#0d1117", surface="#151b23", border="#30363d", text="#f0f6fc", muted="#9198a1",
                 faint="#21262d", a1="#818cf8", a2="#f472b6", a3="#22d3ee", chip_text="#0d1117"),
}
KIND_COLOR = {"conference": "a1", "journal": "a2", "workshop": "a3", "unknown": "muted",
              "preprint": "muted", "repository": "muted"}


def esc(s) -> str:
    return _esc(str(s), quote=True)


# ---------------------------------------------------------------- text layout
# Glyph widths (em) measured from the system UI font in a browser canvas, +5% for
# Windows/Linux fallbacks which run a little wider.
_W400 = {" ": 0.205, "!": 0.267, "\"": 0.403, "#": 0.604, "$": 0.604, "%": 0.808, "&": 0.669, "'": 0.254, "(": 0.322, ")": 0.322, "*": 0.4, "+": 0.604, ",": 0.215, "-": 0.429, ".": 0.215, "/": 0.279, "0": 0.606, "1": 0.443, "2": 0.566, "3": 0.592, "4": 0.604, "5": 0.585, "6": 0.617, "7": 0.547, "8": 0.6, "9": 0.617, ":": 0.215, ";": 0.215, "<": 0.604, "=": 0.604, ">": 0.604, "?": 0.489, "@": 0.875, "A": 0.635, "B": 0.604, "C": 0.686, "D": 0.679, "E": 0.552, "F": 0.528, "G": 0.707, "H": 0.699, "I": 0.225, "J": 0.495, "K": 0.601, "L": 0.524, "M": 0.831, "N": 0.699, "O": 0.731, "P": 0.578, "Q": 0.731, "R": 0.599, "S": 0.593, "T": 0.581, "U": 0.696, "V": 0.631, "W": 0.924, "X": 0.635, "Y": 0.612, "Z": 0.617, "[": 0.322, "\\": 0.279, "]": 0.322, "^": 0.604, "_": 0.527, "`": 0.5, "a": 0.502, "b": 0.554, "c": 0.501, "d": 0.554, "e": 0.512, "f": 0.304, "g": 0.549, "h": 0.539, "i": 0.206, "j": 0.205, "k": 0.485, "l": 0.204, "m": 0.803, "n": 0.527, "o": 0.531, "p": 0.549, "q": 0.549, "r": 0.308, "s": 0.465, "t": 0.301, "u": 0.527, "v": 0.483, "w": 0.715, "x": 0.468, "y": 0.486, "z": 0.468, "{": 0.322, "|": 0.216, "}": 0.322, "~": 0.604, "·": 0.215, "↗": 0.764, "é": 0.512, "’": 0.215, "–": 0.527}
_W700 = {" ": 0.198, "!": 0.316, "\"": 0.456, "#": 0.639, "$": 0.647, "%": 0.89, "&": 0.702, "'": 0.27, "(": 0.382, ")": 0.382, "*": 0.449, "+": 0.647, ",": 0.241, "-": 0.441, ".": 0.241, "/": 0.303, "0": 0.656, "1": 0.48, "2": 0.603, "3": 0.63, "4": 0.647, "5": 0.625, "6": 0.652, "7": 0.572, "8": 0.649, "9": 0.652, ":": 0.241, ";": 0.241, "<": 0.647, "=": 0.647, ">": 0.647, "?": 0.534, "@": 0.888, "A": 0.692, "B": 0.64, "C": 0.712, "D": 0.7, "E": 0.573, "F": 0.548, "G": 0.727, "H": 0.729, "I": 0.265, "J": 0.558, "K": 0.653, "L": 0.543, "M": 0.861, "N": 0.714, "O": 0.752, "P": 0.618, "Q": 0.752, "R": 0.64, "S": 0.631, "T": 0.602, "U": 0.708, "V": 0.678, "W": 0.965, "X": 0.686, "Y": 0.665, "Z": 0.631, "[": 0.382, "\\": 0.303, "]": 0.382, "^": 0.647, "_": 0.576, "`": 0.5, "a": 0.547, "b": 0.597, "c": 0.545, "d": 0.596, "e": 0.555, "f": 0.356, "g": 0.593, "h": 0.584, "i": 0.241, "j": 0.24, "k": 0.538, "l": 0.242, "m": 0.863, "n": 0.576, "o": 0.573, "p": 0.593, "q": 0.593, "r": 0.364, "s": 0.515, "t": 0.355, "u": 0.576, "v": 0.528, "w": 0.79, "x": 0.528, "y": 0.539, "z": 0.505, "{": 0.382, "|": 0.242, "}": 0.382, "~": 0.647, "·": 0.241, "↗": 0.798, "é": 0.555, "’": 0.241, "–": 0.576}


def text_width(s: str, size: float, bold=False, mono=False) -> float:
    if mono:
        return len(s) * size * 0.602
    table = _W700 if bold else _W400
    em = sum(table.get(ch, 1.0 if ord(ch) > 0x2E80 else 0.6) for ch in s)
    return em * size * 1.05


def wrap(s: str, size: float, max_w: float, bold=False, max_lines=99, first_indent=0.0) -> list[str]:
    lines, cur = [], ""
    for word in s.split():
        trial = f"{cur} {word}".strip()
        limit = max_w - (first_indent if not lines else 0)
        if text_width(trial, size, bold) <= limit or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = lines[-1].rstrip(".,;") + "…"
    return lines


def svg(w: int, h: int, body: str, t: dict, extra_style="") -> str:
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">'
            f'<style>text{{font-family:{SANS}}} .m{{font-family:{MONO}}}'
            f'@media (prefers-reduced-motion:reduce){{*{{animation:none!important}}}}{extra_style}</style>'
            f'{body}</svg>')


def card(w, h, t, r=16, fill=None):
    return (f'<rect x=".5" y=".5" width="{w-1}" height="{h-1}" rx="{r}" '
            f'fill="{fill or t["bg"]}" stroke="{t["border"]}"/>')


def grad(t, gid="g"):
    return (f'<linearGradient id="{gid}" x1="0" y1="0" x2="1" y2="0">'
            f'<stop offset="0" stop-color="{t["a1"]}"/><stop offset=".55" stop-color="{t["a2"]}"/>'
            f'<stop offset="1" stop-color="{t["a3"]}"/></linearGradient>')


# ---------------------------------------------------------------- data
def http_get(url, binary=False):
    headers = {"User-Agent": "profile-site-builder"}
    if "api.github.com" in url and os.getenv("GITHUB_TOKEN"):
        headers["Authorization"] = f"Bearer {os.environ['GITHUB_TOKEN']}"
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=30) as r:
        data = r.read()
    return data if binary else json.loads(data.decode())


def avatar_data_uri() -> str:
    try:
        raw = http_get(f"https://github.com/{USER}.png?size=320", binary=True)
        mime = "image/png" if raw[:4] == b"\x89PNG" else "image/jpeg"
        return f"data:{mime};base64," + base64.b64encode(raw).decode()
    except Exception as e:
        print(f"  avatar failed: {e}", file=sys.stderr)
        return ""


def fmt_date(d: str) -> str:
    if not d:
        return ""
    y, m, _ = (d.split("-") + ["01", "01"])[:3]
    if d.endswith("-01-01"):
        return y
    return ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"][int(m) - 1] + " " + y


def mark_new(papers) -> None:
    """p.is_new = first seen (or precise publication date) within `new_days`."""
    days = SITE.get("new_days", 90)
    first_run = not SEEN_FILE.exists()
    seen = {} if first_run else json.loads(SEEN_FILE.read_text())
    for p in papers:
        key = P.norm_title(p.title)
        if key not in seen:
            # first build: seed with the publication date so old papers aren't all "new"
            seen[key] = (p.date or f"{p.year}-01-01") if first_run else TODAY.isoformat()
        dates = [seen[key]] + ([p.date] if p.date and not p.date.endswith("-01-01") else [])
        latest = max(dt.date.fromisoformat(d) for d in dates)
        p.is_new = (TODAY - latest).days <= days
    SEEN_FILE.write_text(json.dumps(dict(sorted(seen.items())), indent=1, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------- components
def c_hero(t, avatar) -> str:
    h = 300
    ax, ay, ar = W - 160, 150, 96
    av = (f'<clipPath id="av"><circle cx="{ax}" cy="{ay}" r="{ar}"/></clipPath>'
          f'<image href="{avatar}" x="{ax-ar}" y="{ay-ar}" width="{ar*2}" height="{ar*2}" '
          f'preserveAspectRatio="xMidYMid slice" clip-path="url(#av)"/>') if avatar else \
        f'<circle cx="{ax}" cy="{ay}" r="{ar}" fill="{t["surface"]}"/>'
    body = f"""
<defs>{grad(t)}
  <filter id="blur" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="40"/></filter>
  <pattern id="dots" width="22" height="22" patternUnits="userSpaceOnUse"><circle cx="2" cy="2" r="1.1" fill="{t["border"]}"/></pattern>
  <clipPath id="cardclip"><rect width="{W}" height="{h}" rx="20"/></clipPath>
</defs>
<g clip-path="url(#cardclip)">
  <rect width="{W}" height="{h}" fill="{t["bg"]}"/>
  <rect width="{W}" height="{h}" fill="url(#dots)" opacity=".7"/>
  <circle class="blob1" cx="{ax-40}" cy="{ay-40}" r="110" fill="{t["a1"]}" opacity=".35" filter="url(#blur)"/>
  <circle class="blob2" cx="{ax+60}" cy="{ay+60}" r="100" fill="{t["a2"]}" opacity=".3" filter="url(#blur)"/>
</g>
<rect x=".5" y=".5" width="{W-1}" height="{h-1}" rx="20" fill="none" stroke="{t["border"]}"/>
<text class="m" x="48" y="92" font-size="13" letter-spacing="2.5" fill="{t["a1"]}" font-weight="600">{esc(PROFILE["kicker"].upper())}</text>
<text x="45" y="160" font-size="62" font-weight="800" letter-spacing="-1.5" fill="url(#g)">{esc(PROFILE["name"])}</text>
<text x="48" y="206" font-size="19" fill="{t["muted"]}">{esc(PROFILE.get("headline", ""))}</text>
<g class="ring"><circle cx="{ax}" cy="{ay}" r="{ar+12}" fill="none" stroke="url(#g)" stroke-width="2.5" stroke-dasharray="6 10" stroke-linecap="round"/></g>
<circle cx="{ax}" cy="{ay}" r="{ar+3}" fill="{t["bg"]}"/>
{av}"""
    style = (f".ring{{transform-origin:{ax}px {ay}px;animation:spin 24s linear infinite}}"
             "@keyframes spin{to{transform:rotate(360deg)}}"
             ".blob1{animation:drift 9s ease-in-out infinite alternate}"
             ".blob2{animation:drift 11s ease-in-out infinite alternate-reverse}"
             "@keyframes drift{to{transform:translate(-30px,20px)}}")
    return svg(W, h, body, t, style)


def c_pill(t, label, primary=False) -> str:
    w = int(text_width(label, 14, bold=True) + 40)
    h = 38
    if primary:
        body = (f'<defs>{grad(t)}</defs><rect x=".5" y=".5" width="{w-1}" height="{h-1}" rx="19" fill="url(#g)"/>'
                f'<text x="{w/2}" y="24" font-size="14" font-weight="700" text-anchor="middle" fill="#fff">{esc(label)}</text>')
    else:
        body = (f'<rect x=".5" y=".5" width="{w-1}" height="{h-1}" rx="19" fill="{t["bg"]}" stroke="{t["border"]}"/>'
                f'<text x="{w/2}" y="24" font-size="14" font-weight="600" text-anchor="middle" fill="{t["text"]}">{esc(label)}</text>')
    return svg(w, h, body, t)


def c_section(t, num, title, meta="") -> str:
    h = 64
    tw = text_width(title, 28, bold=True)
    x2 = W - (text_width(meta, 13, mono=True) + 20 if meta else 0)
    body = (f'<defs>{grad(t)}</defs>'
            f'<text class="m" x="0" y="42" font-size="15" font-weight="700" fill="url(#g)">{num}</text>'
            f'<text x="38" y="44" font-size="28" font-weight="800" letter-spacing="-.5" fill="{t["text"]}">{esc(title)}</text>'
            f'<line x1="{38 + tw + 20}" y1="35" x2="{x2}" y2="35" stroke="{t["border"]}"/>'
            + (f'<text class="m" x="{W}" y="40" font-size="13" text-anchor="end" fill="{t["muted"]}">{esc(meta)}</text>'
               if meta else ""))
    return svg(W, h, body, t)


def chip_row(t, label, items, y, color, filled=False) -> tuple[str, int]:
    """Label on the left, wrapping chips on the right. Returns (svg, next_y)."""
    parts = [f'<text class="m" x="24" y="{y+21}" font-size="12" font-weight="700" letter-spacing="1.5" fill="{t[color]}">{esc(label)}</text>']
    x0, x, row_h = 170, 170, 40
    for it in items:
        w = 24 + text_width(it, 14) + 16  # dot+gap on the left, 16px on the right
        if x + w > W - 24 and x > x0:
            x, y = x0, y + row_h
        if filled:
            w = text_width(it, 14.5, bold=True) + 36
            if x + w > W - 24 and x > x0:
                x, y = x0, y + row_h
            parts.append(f'<rect x="{x}" y="{y}" width="{w}" height="32" rx="16" fill="url(#g)"/>'
                         f'<text x="{x+w/2}" y="{y+21}" font-size="14.5" font-weight="700" text-anchor="middle" fill="#fff">{esc(it)}</text>')
        else:
            parts.append(f'<rect x="{x}" y="{y}" width="{w}" height="32" rx="16" fill="{t["bg"]}" stroke="{t["border"]}"/>'
                         f'<circle cx="{x+14}" cy="{y+16}" r="3" fill="{t[color]}"/>'
                         f'<text x="{x+24}" y="{y+21}" font-size="14" fill="{t["text"]}">{esc(it)}</text>')
        x += w + 8
    return "".join(parts), y + row_h


def c_about(t) -> str:
    parts = []
    y = 40
    for line in PROFILE["bio"]:
        for l in wrap(line, 17, W - 48):
            parts.append(f'<text x="24" y="{y}" font-size="17" fill="{t["text"]}">{esc(l)}</text>')
            y += 28
    y += 10
    parts.append(f'<line x1="24" y1="{y}" x2="{W-24}" y2="{y}" stroke="{t["faint"]}"/>')
    y += 20
    for label, key, color in (("MAIN FOCUS", "focus", "a1"), ("RESEARCH", "research", "a1"), ("ALSO INTO", "interests", "a2")):
        if SITE.get(key):
            frag, y = chip_row(t, label, SITE[key], y, color, filled=(key == "focus"))
            parts.append(frag)
            y += 8
    h = int(y + 16)
    return svg(W, h, f'<defs>{grad(t)}</defs>' + card(W, h, t, 16, t["surface"]) + "".join(parts), t)




def paper_layout(p):
    venue = p.venue_label or P.short_venue(p.venue) or p.kind
    chip = f"{venue} {p.year}" if p.year else venue
    rx = 196
    new_w = 52 if getattr(p, "is_new", False) else 0
    title_lines = wrap(p.title, 15.5, W - rx - 24, bold=True, max_lines=2, first_indent=new_w)
    h = max(24 + len(title_lines) * 21 + 22, 74)
    return chip, rx, title_lines, h


def c_paper(t, p) -> str:
    """Venue column + title + authors. The whole card links to the best version."""
    chip, rx, title_lines, h = paper_layout(p)
    w = W
    color = t[KIND_COLOR[p.kind]]
    lx = 22
    authors = list(p.authors)
    if len(authors) > P.CONFIG["max_authors"]:
        authors = authors[:P.CONFIG["max_authors"]] + ["et al."]
    spans, used, limit = [], 0.0, w - rx - 24
    for i, a in enumerate(authors):
        piece = a + (", " if i < len(authors) - 1 else "")
        me = i == p.self_idx
        wpx = text_width(piece, 12.5, bold=me)
        if used + wpx > limit:
            spans.append((" et al.", False))
            break
        spans.append((piece, me))
        used += wpx
    cw = text_width(chip, 11, bold=True, mono=True) + 16
    kind_label = {"conference": "Conference", "journal": "Journal", "workshop": "Workshop"}.get(p.kind, p.kind.title())
    parts = [card(w, h, t, 12),
             f'<rect x="0" y="14" width="3" height="{h-28}" rx="1.5" fill="{color}"/>',
             f'<rect x="{lx}" y="16" width="{cw}" height="22" rx="5" fill="{color}"/>',
             f'<text class="m" x="{lx+cw/2}" y="31" font-size="11" font-weight="700" text-anchor="middle" fill="{t["chip_text"]}">{esc(chip)}</text>',
             f'<text class="m" x="{lx}" y="56" font-size="11" fill="{t["muted"]}">{esc(kind_label)} · {esc(fmt_date(p.date))}</text>']
    is_new = getattr(p, "is_new", False)
    for i, l in enumerate(title_lines):
        x = rx + (52 if is_new and i == 0 else 0)
        parts.append(f'<text x="{x}" y="{32 + i*21}" font-size="15.5" font-weight="700" fill="{t["text"]}">{esc(l)}</text>')
    if is_new:
        nx, ny = rx, 32 - 14
        parts.append(f'<defs>{grad(t)}</defs><g transform="translate({nx:.1f} {ny})"><rect class="glow" width="42" height="18" rx="9" fill="url(#g)"/>'
                     f'<text class="m" x="21" y="13" font-size="10" font-weight="800" letter-spacing="1" text-anchor="middle" fill="#fff">NEW</text></g>')
    ay = 32 + len(title_lines) * 21 + 2
    tsp = "".join(f'<tspan font-weight="{700 if me else 400}" fill="{t["text"] if me else t["muted"]}">{esc(s)}</tspan>'
                  for s, me in spans)
    parts.append(f'<text x="{rx}" y="{ay}" font-size="12.5">{tsp}</text>')
    style = (".glow{animation:glow 2.4s ease-in-out infinite}@keyframes glow{50%{opacity:.6}}"
             if getattr(p, "is_new", False) else "")
    return svg(w, h, "".join(parts), t, style)


def c_contact(t) -> str:
    h = 150
    email = next((l["url"][7:] for l in SITE["links"] if l["url"].startswith("mailto:")), "")
    body = (f'<defs>{grad(t)}<pattern id="dots" width="22" height="22" patternUnits="userSpaceOnUse">'
            f'<circle cx="2" cy="2" r="1.1" fill="{t["border"]}"/></pattern></defs>'
            + card(W, h, t, 20, t["surface"])
            + f'<rect x="1" y="1" width="{W-2}" height="{h-2}" rx="19" fill="url(#dots)" opacity=".6"/>'
            f'<text class="m" x="{W/2}" y="58" font-size="12" font-weight="700" letter-spacing="2.5" text-anchor="middle" fill="{t["muted"]}">EMAIL</text>'
            f'<text x="{W/2}" y="102" font-size="32" font-weight="800" letter-spacing="-.5" text-anchor="middle" fill="url(#g)">{esc(email)}</text>')
    return svg(W, h, body, t)


# ---------------------------------------------------------------- assemble
def write(name: str, make) -> None:
    for mode, t in THEMES.items():
        (OUT / f"{name}-{mode}.svg").write_text(make(t))


def pic(name: str, alt: str, width: str | None = None) -> str:
    wattr = f' width="{width}"' if width else ""
    return (f'<picture><source media="(prefers-color-scheme: dark)" srcset="{RAW}/{name}-dark.svg" />'
            f'<img src="{RAW}/{name}-light.svg" alt="{esc(alt)}"{wattr} /></picture>')


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for f in OUT.glob("*.svg"):
        f.unlink()
    print("papers:", file=sys.stderr)
    papers = P.collect()
    if not papers:
        sys.exit("No papers fetched; refusing to build an empty site.")
    mark_new(papers)
    avatar = avatar_data_uri()
    md = []

    nav = [("about", "About"), ("publications", "Publications"), ("activity", "Activity"), ("contact", "Contact")]
    write("nav-home", lambda t: c_pill(t, PROFILE["name"], primary=True))
    for anchor, label in nav:
        write(f"nav-{anchor}", lambda t, l=label: c_pill(t, l))
    md.append('<p align="center">\n  <a href="#readme">' + pic("nav-home", PROFILE["name"]) + "</a>&nbsp;&nbsp;\n  "
              + "\n  ".join(f'<a href="#{a}">{pic(f"nav-{a}", l)}</a>' for a, l in nav) + "\n</p>\n")

    write("hero", lambda t: c_hero(t, avatar))
    md.append(f'<p align="center">{pic("hero", PROFILE["name"] + ", " + PROFILE["kicker"], "100%")}</p>\n')

    def section(num, anchor, title, meta=""):
        write(f"sec-{anchor}", lambda t: c_section(t, num, title, meta))
        md.append(f'<a id="{anchor}"></a>\n\n{pic(f"sec-{anchor}", title, "100%")}\n')

    section("01", "about", "About")
    write("about", c_about)
    md.append(pic("about", " ".join(PROFILE["bio"]) + " Main focus: " + ", ".join(SITE.get("focus", [])), "100%") + "\n")

    n_first = sum(1 for p in papers if p.self_idx == 0)
    n_cite = sum(p.citations for p in papers)
    n_new = sum(1 for p in papers if p.is_new)
    section("02", "publications", "Publications",
            f"{len(papers)} papers · {n_first} first-author · {n_cite} citations" + (f" · {n_new} new" if n_new else ""))
    for i, p in enumerate(papers):
        # dedup already kept the venue version when one exists; a preprint only
        # shows up here (and gets linked) when there is no venue version yet
        link = p.url or "#publications"
        write(f"paper-{i}", lambda t, p=p: c_paper(t, p))
        md.append(f'<a href="{link}">{pic(f"paper-{i}", p.title, "100%")}</a>\n')
    md.append('<p align="right"><sub><i>Synced daily from OpenAlex, ORCID &amp; ACL Anthology · '
              'links go to the conference / journal version, or the preprint if there is none yet</i></sub></p>\n')

    section("03", "activity", "Activity")
    md.append(f'<picture><source media="(prefers-color-scheme: dark)" '
              f'srcset="https://raw.githubusercontent.com/{USER}/{USER}/output/profile-night-rainbow.svg" />'
              f'<img src="https://raw.githubusercontent.com/{USER}/{USER}/output/profile-gitblock.svg" '
              f'alt="3D contribution graph" width="100%" /></picture>\n')

    section("04", "contact", "Contact")
    write("contact", c_contact)
    mail = next((l["url"] for l in SITE["links"] if l["url"].startswith("mailto:")), "#contact")
    md.append(f'<a href="{mail}">{pic("contact", "Email", "100%")}</a>\n')
    link_md = []
    for l in SITE["links"]:
        slug = "link-" + re.sub(r"[^a-z0-9]+", "-", l["label"].lower())
        write(slug, lambda t, l=l: c_pill(t, l["label"]))
        link_md.append(f'<a href="{l["url"]}">{pic(slug, l["label"])}</a>')
    md.append('<p align="center">\n  ' + "\n  ".join(link_md) + "\n</p>\n")
    md.append(f'<p align="center"><sub>© {PROFILE["name"]} · generated by '
              f'<a href="scripts/build_site.py">scripts/build_site.py</a>, rebuilt daily by GitHub Actions</sub></p>\n')

    readme = ("<!-- Generated by scripts/build_site.py from site.json. Edit those, not this file. -->\n\n"
              + "\n".join(md))
    (ROOT / "README.md").write_text(readme)
    print(f"built README + {len(list(OUT.glob('*.svg')))} svgs", file=sys.stderr)


if __name__ == "__main__":
    main()

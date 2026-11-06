#!/usr/bin/env python3
"""Fetch + dedup publications from OpenAlex + ORCID (library used by build_site.py).

Sources
  * OpenAlex  works linked to the ORCID (venue versions *and* arXiv preprints)
  * ORCID     public works list (catches anything OpenAlex has not indexed yet)
  * config    manual "extra" entries in scripts/papers.config.json

Dedup
  Records are clustered when any of these hold:
    - same DOI
    - normalized titles are near-identical (>= 0.90 similarity)
    - abstracts overlap strongly AND author lists overlap
      (catches a preprint whose title changed for the camera-ready)
  From each cluster the best version is kept:
    journal / conference / workshop  >  unknown  >  preprint (arXiv)  >  repository (Zenodo, ...)
  The arXiv link of a dropped preprint is kept as an extra link on the entry.

Only the standard library is used, so the GitHub Action needs no pip install.
Debug:  python3 scripts/papers.py   (prints the deduped list)
"""
from __future__ import annotations

import difflib
import json
import os
import re
import sys
import unicodedata
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG = json.loads((ROOT / "site.json").read_text())["papers"]
UA = "Rui0828-profile-papers/1.0 (+https://github.com/Rui0828/Rui0828)"

RANK = {"journal": 4, "conference": 4, "workshop": 4, "unknown": 2, "preprint": 1, "repository": 0}


# ---------------------------------------------------------------- helpers
def get_json(url: str, headers: dict | None = None):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json", **(headers or {})})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


def norm_title(t: str) -> str:
    t = unicodedata.normalize("NFKD", t or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", t).strip()


def norm_name(n: str) -> str:
    return re.sub(r"[^a-z]", "", unicodedata.normalize("NFKD", n or "").encode("ascii", "ignore").decode().lower())


def norm_doi(d: str | None) -> str | None:
    if not d:
        return None
    return re.sub(r"^https?://(dx\.)?doi\.org/", "", d.strip(), flags=re.I).lower()


def words(text: str) -> set[str]:
    return {w for w in norm_title(text).split() if len(w) > 3}


def surname_set(authors: list[str]) -> set[str]:
    return {norm_name(a.split()[-1]) for a in authors if a.strip()}


SELF = {norm_name(n) for n in CONFIG["self_names"]}


def is_self(name: str, orcid: str | None = None) -> bool:
    if orcid and orcid.rstrip("/").endswith(CONFIG["orcid"]):
        return True
    return norm_name(name) in SELF


def classify(venue: str, source_type: str | None, work_type: str | None, doi: str | None) -> str:
    v = (venue or "").lower()
    if (doi or "").startswith("10.48550/") or "arxiv" in v or work_type == "preprint":
        return "preprint"
    if (doi or "").startswith("10.5281/") or "zenodo" in v or source_type == "repository":
        return "repository"
    if "workshop" in v:
        return "workshop"
    if source_type == "journal" or work_type in ("journal-article",):
        return "journal"
    if source_type == "conference" or work_type in ("conference-paper",):
        return "conference"
    return "unknown"


def short_venue(venue: str) -> str:
    if not venue:
        return ""
    for full, short in sorted(CONFIG["venue_aliases"].items(), key=lambda kv: -len(kv[0])):
        if full.lower() in venue.lower():
            return short
    m = re.search(r"\(([^()]{2,25})\)\s*$", venue)
    return m.group(1) if m else venue


# ---------------------------------------------------------------- records
@dataclass
class Paper:
    title: str
    year: int | None
    venue: str
    kind: str
    doi: str | None = None
    url: str | None = None
    authors: list[str] = field(default_factory=list)
    self_idx: int | None = None
    abstract: str = ""
    citations: int = 0
    source: str = ""
    arxiv: str | None = None
    code: str | None = None
    date: str = ""  # YYYY-MM-DD when known; "YYYY-01-01" usually means year-only
    venue_label: str | None = None  # manual short label from site.json venue_overrides

    @property
    def score(self):
        publisher_doi = bool(self.doi) and not self.doi.startswith(("10.48550/", "10.5281/"))
        # tie-break: OpenAlex records carry authors/abstracts/dates, prefer them
        return (RANK[self.kind], publisher_doi, bool(self.venue), self.year or 0, self.source == "openalex")


def from_openalex() -> list[Paper]:
    params = {"filter": f"author.orcid:{CONFIG['orcid']}", "per-page": "200",
              "select": "title,doi,publication_year,type,primary_location,authorships,"
                        "abstract_inverted_index,cited_by_count,ids,publication_date"}
    if os.getenv("OPENALEX_API_KEY"):
        params["api_key"] = os.environ["OPENALEX_API_KEY"]
    data = get_json("https://api.openalex.org/works?" + urllib.parse.urlencode(params))
    out = []
    for w in data.get("results", []):
        if w.get("type") in ("paratext", "erratum", "retraction") or not w.get("title"):
            continue
        loc = w.get("primary_location") or {}
        src = loc.get("source") or {}
        venue = src.get("display_name") or ""
        doi = norm_doi(w.get("doi"))
        authors, self_idx = [], None
        for i, a in enumerate(w.get("authorships") or []):
            name = (a.get("author") or {}).get("display_name") or a.get("raw_author_name") or ""
            if name.count(",") == 1:  # "Liao, You-Cheng" -> "You-Cheng Liao"
                last, first = (x.strip() for x in name.split(","))
                name = f"{first} {last}"
            if is_self(name, (a.get("author") or {}).get("orcid")):
                self_idx, name = i, CONFIG["self_names"][0]
            authors.append(name)
        inv = w.get("abstract_inverted_index") or {}
        abstract = " ".join(k for k, _ in sorted(((k, p) for k, ps in inv.items() for p in ps), key=lambda x: x[1]))
        out.append(Paper(
            title=w["title"].strip(), year=w.get("publication_year"), venue=venue,
            kind=classify(venue, src.get("type"), w.get("type"), doi), doi=doi,
            url=f"https://doi.org/{doi}" if doi else loc.get("landing_page_url"),
            authors=authors, self_idx=self_idx, abstract=abstract,
            citations=w.get("cited_by_count") or 0, source="openalex",
            date=w.get("publication_date") or ""))
    return out


def from_orcid() -> list[Paper]:
    data = get_json(f"https://pub.orcid.org/v3.0/{CONFIG['orcid']}/works")
    out = []
    for g in data.get("group", []):
        s = g["work-summary"][0]
        title = ((s.get("title") or {}).get("title") or {}).get("value")
        if not title:
            continue
        doi = next((norm_doi(e["external-id-value"]) for e in (s.get("external-ids") or {}).get("external-id", [])
                    if e.get("external-id-type") == "doi"), None)
        venue = (s.get("journal-title") or {}).get("value") or ""
        pd = s.get("publication-date") or {}
        year = (pd.get("year") or {}).get("value")
        month = (pd.get("month") or {}).get("value") or "01"
        day = (pd.get("day") or {}).get("value") or "01"
        out.append(Paper(
            title=title.strip(), year=int(year) if year else None, venue=venue,
            kind=classify(venue, None, s.get("type"), doi), doi=doi,
            url=f"https://doi.org/{doi}" if doi else (s.get("url") or {}).get("value"),
            source="orcid", date=f"{year}-{month}-{day}" if year else ""))
    return out


def from_config() -> list[Paper]:
    out = []
    for e in CONFIG.get("extra", []):
        authors = e.get("authors", [])
        idx = next((i for i, a in enumerate(authors) if is_self(a)), None)
        doi = norm_doi(e.get("doi"))
        out.append(Paper(title=e["title"], year=e.get("year"), venue=e.get("venue", ""),
                         kind=e.get("kind") or classify(e.get("venue", ""), None, None, doi), doi=doi,
                         url=e.get("url") or (f"https://doi.org/{doi}" if doi else None), authors=authors,
                         self_idx=idx, source="config", code=e.get("code"),
                         date=e.get("date") or (f"{e['year']}-01-01" if e.get("year") else "")))
    return out


# ---------------------------------------------------------------- dedup
def same_paper(a: Paper, b: Paper) -> bool:
    if a.doi and a.doi == b.doi:
        return True
    ta, tb = norm_title(a.title), norm_title(b.title)
    if ta == tb or difflib.SequenceMatcher(None, ta, tb).ratio() >= 0.90:
        return True
    # Title changed between preprint and camera-ready: compare content + people.
    wa, wb = words(a.abstract), words(b.abstract)
    if len(wa) >= 30 and len(wb) >= 30 and len(wa & wb) / len(wa | wb) >= 0.6:
        sa, sb = surname_set(a.authors), surname_set(b.authors)
        if sa and sb and len(sa & sb) / min(len(sa), len(sb)) >= 0.5:
            return True
    return False


def dedup(papers: list[Paper]) -> list[Paper]:
    clusters: list[list[Paper]] = []
    for p in papers:
        hits = [c for c in clusters if any(same_paper(p, q) for q in c)]
        merged = [p] + [q for c in hits for q in c]
        clusters = [c for c in clusters if all(c is not h for h in hits)] + [merged]

    result = []
    for c in clusters:
        best = max(c, key=lambda p: p.score)
        # Borrow missing details from the other copies.
        richest = max(c, key=lambda p: len(p.authors))
        if not best.authors:
            best.authors, best.self_idx = richest.authors, richest.self_idx
        best.citations = max(p.citations for p in c)
        best.code = next((p.code for p in c if p.code), None)
        if not best.date or best.date.endswith("-01-01"):
            same_year = [p.date for p in c if p.date and p.year == best.year and not p.date.endswith("-01-01")
                         and p.kind not in ("preprint", "repository")]  # preprint dates are not publication dates
            best.date = min(same_year, default=best.date)
        if best.kind != "preprint":
            arx = next((p for p in c if p.kind == "preprint" and p.doi and p.doi.startswith("10.48550/")), None)
            if arx:
                best.arxiv = "https://arxiv.org/abs/" + arx.doi.split("arxiv.", 1)[-1]
        result.append(best)
    return result


MONTHS = {m: i + 1 for i, m in enumerate("jan feb mar apr may jun jul aug sep oct nov dec".split())}


def enrich_acl(p: Paper) -> None:
    """ACL Anthology papers often come back year-only; read the month from the official .bib."""
    if not (p.doi and p.doi.startswith("10.18653/")):
        return
    anth_id = p.doi.split("/")[-1]
    try:
        req = urllib.request.Request(f"https://aclanthology.org/{anth_id}.bib", headers={"User-Agent": UA})
        bib = urllib.request.urlopen(req, timeout=20).read().decode()
    except Exception as e:
        print(f"  anthology {anth_id} failed: {e}", file=sys.stderr)
        return
    am = re.search(r'\n\s*author\s*=\s*"(.*?)",\n', bib, re.S)
    if am:  # official author list, "Last, First and Last, First"
        names = [" ".join(reversed([x.strip() for x in n.split(",", 1)])) for n in re.split(r"\s+and\s+", am.group(1))]
        names = [re.sub(r"[{}]", "", " ".join(n.split())) for n in names]
        p.authors = [CONFIG["self_names"][0] if is_self(n) else n for n in names]
        p.self_idx = next((i for i, n in enumerate(p.authors) if is_self(n)), p.self_idx)
    if p.date and not p.date.endswith("-01-01"):
        return
    m = re.search(r"month\s*=\s*\{?\"?([a-z]{3})", bib, re.I)
    if m and m.group(1).lower() in MONTHS:
        p.date = f"{p.year}-{MONTHS[m.group(1).lower()]:02d}-01"
        if p.date.endswith("-01-01"):  # a real January: keep it distinguishable from "year only"
            p.date = f"{p.year}-01-02"


# ---------------------------------------------------------------- public
def collect() -> list[Paper]:
    """All papers, deduped, newest first (by full publication date)."""
    papers: list[Paper] = []
    for fetch in (from_openalex, from_orcid, from_config):
        try:
            got = fetch()
            print(f"  {fetch.__name__}: {len(got)} records", file=sys.stderr)
            papers += got
        except Exception as e:  # one source down should not wipe the list
            print(f"  {fetch.__name__} failed: {e}", file=sys.stderr)
    excluded = {norm_title(t) for t in CONFIG.get("exclude_titles", [])}
    final = dedup([p for p in papers if norm_title(p.title) not in excluded])
    overrides = {norm_title(t): d for t, d in CONFIG.get("date_overrides", {}).items()}
    venues = {norm_title(t): v for t, v in CONFIG.get("venue_overrides", {}).items()}
    for p in final:
        enrich_acl(p)
        p.date = overrides.get(norm_title(p.title), p.date)
        p.venue_label = venues.get(norm_title(p.title))
    final.sort(key=lambda p: (p.date or f"{p.year or 0}-00-00", RANK[p.kind], p.title.lower()), reverse=True)
    return final


if __name__ == "__main__":
    for p in collect():
        print(p.date, f"[{short_venue(p.venue)}]", p.title, "| arXiv:" if p.arxiv else "", p.arxiv or "")

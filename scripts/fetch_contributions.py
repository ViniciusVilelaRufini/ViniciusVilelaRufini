#!/usr/bin/env python3
"""
Atualiza data/contributions.json com:
  - o calendário de contribuições (mesmo que aparece no perfil, ~53 semanas)
  - nº de repositórios públicos e metadados dos repositórios em destaque

Roda na GitHub Action diária. Usa GITHUB_TOKEN só para a API REST (opcional).
Se o scraping falhar ou vier incompleto, o JSON anterior é mantido.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from render_cards import DATA, REPOS, USER  # noqa: E402

USER = os.environ.get("GH_USER", USER)
TOKEN = os.environ.get("GITHUB_TOKEN", "")


def get(url: str, api: bool = False) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": f"{USER}-profile-cards"})
    if api:
        req.add_header("Accept", "application/vnd.github+json")
        if TOKEN:
            req.add_header("Authorization", f"Bearer {TOKEN}")
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8")


def calendar() -> list[dict]:
    page = get(f"https://github.com/users/{USER}/contributions")
    tips = {m.group(1): m.group(2).strip() for m in
            re.finditer(r'<tool-tip[^>]*\bfor="([^"]+)"[^>]*>([^<]*)</tool-tip>', page)}
    days = []
    for m in re.finditer(r"<td\b[^>]*\bdata-date=\"(\d{4}-\d\d-\d\d)\"[^>]*>", page):
        td = m.group(0)
        cid = (re.search(r'\bid="([^"]+)"', td) or [None, ""])[1]
        lvl = int((re.search(r'data-level="(\d)"', td) or [None, 0])[1])
        tip = tips.get(cid, "")
        n = re.match(r"([\d,]+) contribution", tip)
        count = int(n.group(1).replace(",", "")) if n else 0
        if not tip and lvl:  # tooltip ausente: não dá para saber a contagem exata
            count = lvl
        days.append({"date": m.group(1), "count": count, "level": lvl})
    days.sort(key=lambda d: d["date"])
    return days


def main():
    old = json.loads(DATA.read_text(encoding="utf-8")) if DATA.exists() else {}
    try:
        days = calendar()
    except Exception as e:  # noqa: BLE001
        print(f"falha ao ler o calendário: {e}", file=sys.stderr)
        days = []
    if len(days) < 300:
        print(f"calendário incompleto ({len(days)} dias); mantendo dados anteriores", file=sys.stderr)
        days = old.get("days", [])
        if not days:
            sys.exit(1)

    profile, repos = old.get("profile", {}), old.get("repos", {})
    try:
        u = json.loads(get(f"https://api.github.com/users/{USER}", api=True))
        profile = {"public_repos": u["public_repos"], "followers": u["followers"]}
        for cfg in REPOS:
            r = json.loads(get(f"https://api.github.com/repos/{USER}/{cfg['repo']}", api=True))
            repos[cfg["repo"]] = {"language": r.get("language"), "pushed_at": r.get("pushed_at"),
                                  "homepage": r.get("homepage") or "", "stars": r.get("stargazers_count", 0),
                                  "forks": r.get("forks_count", 0)}
    except Exception as e:  # noqa: BLE001
        print(f"API do GitHub indisponível, usando metadados anteriores: {e}", file=sys.stderr)

    out = {"user": USER, "fetched_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "source": f"github.com/users/{USER}/contributions",
           "profile": profile, "repos": repos, "days": days}
    DATA.parent.mkdir(exist_ok=True)
    DATA.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"{len(days)} dias, {sum(d['count'] for d in days)} contribuições")


if __name__ == "__main__":
    main()

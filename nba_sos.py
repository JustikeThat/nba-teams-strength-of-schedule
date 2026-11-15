#!/usr/bin/env python3
"""
NBA weekly strength-of-schedule graphic.

For a Monday-Sunday week it:
  1. pulls every NBA game that week from ESPN's public scoreboard feed,
  2. loads power rankings (from a CSV you keep, or scraped from an ESPN
     Power Rankings article URL),
  3. groups teams by how many games they play,
  4. ranks each group by the average power-rank of their opponents
     (higher = weaker opponents = easier week),
  5. saves a PNG graphic and a CSV.

Setup (once):
    pip install requests matplotlib

Usage:
    # Use a rankings.csv you maintain (columns: team,rank  -  1 = best)
    python nba_sos.py --rankings rankings.csv

    # Or scrape ESPN's latest "NBA Power Rankings" article (paste its URL),
    # and save it to rankings.csv for reuse
    python nba_sos.py --rankings-url https://www.espn.com/nba/story/_/id/XXXXX/... --save-rankings rankings.csv

    # A specific week (any date inside the week works)
    python nba_sos.py --rankings rankings.csv --start 2026-11-16

With no --start, it uses the next Monday (today, if today is Monday).
"""
import argparse
import csv
import datetime as dt
import re
import sys
from collections import defaultdict

# nickname regex -> short display name
TEAMS = {
    r"hawks": "Atlanta", r"celtics": "Boston", r"nets": "Brooklyn",
    r"hornets": "Charlotte", r"bulls": "Chicago", r"cavaliers": "Cleveland",
    r"mavericks": "Dallas", r"nuggets": "Denver", r"pistons": "Detroit",
    r"warriors": "Golden State", r"rockets": "Houston", r"pacers": "Indiana",
    r"clippers": "LA Clippers", r"lakers": "LA Lakers", r"grizzlies": "Memphis",
    r"heat": "Miami", r"bucks": "Milwaukee", r"timberwolves": "Minnesota",
    r"pelicans": "New Orleans", r"knicks": "New York", r"thunder": "Oklahoma City",
    r"magic": "Orlando", r"76ers": "Philadelphia", r"suns": "Phoenix",
    r"blazers": "Portland", r"kings": "Sacramento", r"spurs": "San Antonio",
    r"raptors": "Toronto", r"jazz": "Utah", r"wizards": "Washington",
}
HEADERS = {"User-Agent": "Mozilla/5.0 (nba_sos weekly script)"}


def canon(name):
    """Map any team string ('Los Angeles Lakers', 'LA Clippers', ...) to a short name."""
    for pattern, short in TEAMS.items():
        if re.search(r"\b" + pattern + r"\b", name, re.I):
            return short
    return None


# ----------------------------------------------------------------- schedule
def fetch_schedule(start, end):
    """Return [(date, team_a, team_b), ...] from ESPN's scoreboard feed."""
    import requests
    games, day = [], start
    while day <= end:
        url = ("https://site.api.espn.com/apis/site/v2/sports/basketball/nba/"
               f"scoreboard?dates={day:%Y%m%d}&limit=100")
        r = requests.get(url, headers=HEADERS, timeout=30)
        r.raise_for_status()
        for ev in r.json().get("events", []):
            comp = ev["competitions"][0]["competitors"]
            names = [canon(c["team"]["displayName"]) for c in comp]
            if None in names or len(names) != 2:
                print(f"  ! skipped unrecognised game on {day}: "
                      f"{[c['team']['displayName'] for c in comp]}", file=sys.stderr)
                continue
            games.append((day, names[0], names[1]))
        day += dt.timedelta(days=1)
    return games


# ----------------------------------------------------------------- rankings
def load_rankings_csv(path):
    ranks = {}
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            team = canon(row["team"])
            if team is None:
                raise SystemExit(f"Unrecognised team in {path}: {row['team']!r}")
            ranks[team] = int(row["rank"])
    return validate_rankings(ranks, path)


def fetch_rankings_url(url):
    """Scrape an ESPN Power Rankings article: headings look like '1. San Antonio Spurs'."""
    import requests
    html = requests.get(url, headers=HEADERS, timeout=30).text
    ranks = {}
    for h in re.findall(r"<h2[^>]*>(.*?)</h2>", html, re.S | re.I):
        text = re.sub(r"<[^>]+>", "", h).strip()
        m = re.match(r"^(\d{1,2})\.\s+(.+)$", text)
        if m and canon(m.group(2)):
            ranks[canon(m.group(2))] = int(m.group(1))
    return validate_rankings(ranks, url)


def validate_rankings(ranks, source):
    if len(ranks) != 30 or sorted(ranks.values()) != list(range(1, 31)):
        raise SystemExit(
            f"Could not read 30 clean rankings from {source} (got {len(ranks)}).\n"
            "Fix: make a rankings.csv with columns team,rank (1-30) and pass --rankings.")
    return ranks


def save_rankings(ranks, path):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["team", "rank"])
        for team, r in sorted(ranks.items(), key=lambda kv: kv[1]):
            w.writerow([team, r])


# ------------------------------------------------------------------ compute
def compute(games, ranks, weak=18.0, tough=13.0):
    opps = defaultdict(list)
    for _, a, b in games:
        opps[a].append(b)
        opps[b].append(a)
    rows = []
    for team in ranks:
        o = opps.get(team, [])
        avg = sum(ranks[x] for x in o) / len(o) if o else None
        tier = None if avg is None else ("Weak" if avg >= weak else "Average" if avg >= tough else "Tough")
        rows.append({"team": team, "games": len(o), "avg": avg, "tier": tier,
                     "opponents": ", ".join(f"{x} ({ranks[x]})" for x in o)})
    return rows


def group_rows(rows):
    by_games = defaultdict(list)
    for r in rows:
        by_games[r["games"]].append(r)
    return {g: sorted(v, key=lambda r: -r["avg"]) for g, v in sorted(by_games.items(), reverse=True) if g > 0}


# --------------------------------------------------------------------- draw
def draw(groups, start, end, out_png, weak, tough, rank_source):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Patch

    plt.rcParams["font.family"] = "sans-serif"
    plt.rcParams["font.sans-serif"] = ["Inter", "Helvetica", "Arial", "DejaVu Sans"]
    col = {"Weak": "#2E9E6B", "Average": "#E3A92B", "Tough": "#D9534F"}
    bg, fg, muted = "#0F1B2D", "#F2F5FA", "#8FA0B8"

    # layout in "row units"
    layout, y = [], 0.0
    for g, rows in groups.items():
        layout.append(("header", g, len(rows), y)); y += 1.6
        for r in rows:
            layout.append(("bar", r, None, y)); y += 1
        y += 1.0
    total = y

    unit = 0.30                       # inches per row
    top_in, bot_in = 2.3, 1.1
    height = top_in + bot_in + total * unit
    fig = plt.figure(figsize=(9, height), dpi=200, facecolor=bg)
    ax = fig.add_axes([0.20, bot_in / height, 0.74, total * unit / height], facecolor=bg)
    ax.set_xlim(0, 31)
    ax.set_ylim(total, -0.3)
    ax.axis("off")

    for g in (5, 10, 15, 20, 25, 30):
        ax.plot([g, g], [0, total - 1], color="#22324A", lw=0.8, zorder=0)
        ax.text(g, total - 0.3, str(g), color=muted, fontsize=8.5, ha="center", va="top")
    ax.plot([15.5, 15.5], [0, total - 1], color="#5B6F8F", lw=1.2, ls=(0, (4, 3)), zorder=1)

    for kind, a, b, yy in layout:
        if kind == "header":
            label = f"{a} GAME{'S' if a != 1 else ''}"
            ax.text(-6.0, yy + 0.35, label, color=fg, fontsize=13, fontweight="bold", va="center")
            ax.text(31, yy + 0.35, f"{b} team{'s' if b != 1 else ''}", color=muted,
                    fontsize=9.5, va="center", ha="right")
            ax.plot([-6.0, 31], [yy + 1.05, yy + 1.05], color="#2B3D5A", lw=1)
        else:
            ax.barh(yy, a["avg"], height=0.68, color=col[a["tier"]], zorder=2)
            ax.text(-0.5, yy, a["team"], color=fg, fontsize=10.5, va="center", ha="right")
            ax.text(a["avg"] + 0.35, yy, f"{a['avg']:.1f}", color=fg, fontsize=9.5,
                    va="center", fontweight="bold")

    ax.text(15.5, total + 0.6, "Average opponent power rank  (higher = weaker opponents, easier week)",
            color=muted, fontsize=9, ha="center", va="top")

    fig.text(0.06, 1 - 0.55 / height, "NBA Strength of Schedule", color=fg, fontsize=24,
             fontweight="bold", ha="left", va="center")
    fig.text(0.06, 1 - 1.05 / height,
             f"Games per team, {start:%b %d}\u2013{end:%b %d, %Y}, ranked by how weak their opponents are",
             color=muted, fontsize=11.5, ha="left", va="center")
    fig.legend(handles=[Patch(color=col["Weak"], label=f"Weak opponents ({weak:g}+)"),
                        Patch(color=col["Average"], label=f"Average ({tough:g}\u2013{weak - 0.1:g})"),
                        Patch(color=col["Tough"], label=f"Tough (under {tough:g})")],
               loc="center left", bbox_to_anchor=(0.06, 1 - 1.65 / height), ncol=3, frameon=False,
               fontsize=9.5, labelcolor=fg, handlelength=1.2, columnspacing=1.6)
    fig.text(0.06, 0.25 / height,
             f"Opponent rankings: {rank_source} (1 = best, 30 = worst). Dashed line = league middle (15.5).\n"
             "Schedule from ESPN; subject to change.",
             color=muted, fontsize=7.8, ha="left", va="bottom", linespacing=1.5)
    fig.savefig(out_png, facecolor=bg)
    plt.close(fig)


# --------------------------------------------------------------------- main
def next_monday(today):
    return today + dt.timedelta(days=(7 - today.weekday()) % 7)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--start", help="any date in the target week, YYYY-MM-DD (default: next Monday)")
    p.add_argument("--rankings", help="CSV with columns team,rank")
    p.add_argument("--rankings-url", help="ESPN NBA Power Rankings article URL to scrape")
    p.add_argument("--save-rankings", help="write scraped rankings to this CSV")
    p.add_argument("--weak", type=float, default=18.0, help="avg opponent rank at/above this = Weak (default 18)")
    p.add_argument("--tough", type=float, default=13.0, help="avg opponent rank below this = Tough (default 13)")
    p.add_argument("--out", default=".", help="output folder (default: current)")
    args = p.parse_args()

    if bool(args.rankings) == bool(args.rankings_url):
        p.error("give exactly one of --rankings or --rankings-url")

    day = dt.date.fromisoformat(args.start) if args.start else next_monday(dt.date.today())
    start = day - dt.timedelta(days=day.weekday())   # snap to Monday
    end = start + dt.timedelta(days=6)

    if args.rankings:
        ranks, source = load_rankings_csv(args.rankings), "your rankings file"
    else:
        ranks, source = fetch_rankings_url(args.rankings_url), "ESPN NBA Power Rankings"
        if args.save_rankings:
            save_rankings(ranks, args.save_rankings)

    print(f"Week: {start} to {end}")
    games = fetch_schedule(start, end)
    print(f"Found {len(games)} games")

    rows = compute(games, ranks, args.weak, args.tough)
    groups = group_rows(rows)

    for g, rs in groups.items():
        print(f"\n{g} games")
        for r in rs:
            print(f"  {r['team']:<15}{r['avg']:5.1f}  {r['tier']:<8} {r['opponents']}")
    off = [r["team"] for r in rows if r["games"] == 0]
    if off:
        print("\nNo games:", ", ".join(off))

    png = f"{args.out}/nba_sos_{start}.png"
    draw(groups, start, end, png, args.weak, args.tough, source)
    with open(f"{args.out}/nba_sos_{start}.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["games", "team", "avg_opponent_rank", "tier", "opponents"])
        for g, rs in groups.items():
            for r in rs:
                w.writerow([g, r["team"], f"{r['avg']:.2f}", r["tier"], r["opponents"]])
    print(f"\nSaved {png}")


if __name__ == "__main__":
    main()

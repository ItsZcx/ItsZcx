"""Rebuild the README card.

The card is written out literally below - edit ART and PANEL directly, they
are the source of truth. The numbers come from stats.py and land at the
{stats} placeholder.

    python3 today.py              # fetch stats, rewrite README.md
    python3 today.py --dry-run    # fetch stats, print them, touch nothing
    python3 today.py --demo       # sample numbers, no network
    python3 today.py --quiet      # no progress output (used by the workflow)
    python3 today.py --names      # include repository names in the progress
                                  # lines - local debugging only, never in CI

Layout rules worth knowing:
  * GitHub's profile column is 846px wide and monospace advances 8.19px/char,
    so the panel must stay at or under 42 characters or the table scrolls.
  * every value starts at column 14. If you rename a key, adjust its dots so
    the value still lands there.
"""

import json
import re
import sys

import stats

# Right edge of every panel line. The card is one <pre>, so total width is
# (46 art + 3 gap + MAX_COLS) chars plus 32px padding:
#   profile  846px column, 11.9px code (7.165px/char) -> 113 chars fit
#   repo     838px column, 13.6px code (8.188px/char) ->  98 chars fit
# 63 fills the profile card (46 art + 3 gap + 63 = 112 chars). The repo page
# renders the same text larger and scrolls. Use 49 to fit both.
MAX_COLS = 63
GAP = "   "

DEMO = {
    "repos": 26,
    "contributed": 110,
    "stars": 7,
    "followers": 33,
    "commits": 2534,
    "loc": 673931,
    "added": 985187,
    "deleted": 311256,
    "views": 2807,
}

ART = """\
                  :-=:   .....
        ..:+***+%*++**#@%#*#+#=+:
      :=+*=+*+-=====-=*::..:-++:+#@*-=
    :*-++=---..:---.==-=-.=:..*=-*===*%+
  :*=::-=:.  :::::..:.:=.:--:. .-:=-:=###-
 :.: :=... .::.     .:--::--   ::--++-+*#+.
 %:::           ..:::.-  .-=-:+.  ..--+#=#+@+
 *: .    .-  .:.:-**==:-:::.:..:-: .::-:#+=+.
 --.-. :=++#*+*****::==--+=::.-   .-:+- =#%=
  +--:#+++===+*+-  :..-+=**-+++#**---==-=%=
  -++-: .-=-***+--.   ..#@@@@**:::+==*--=-
 -:.+*  .=**+.#*---  .::+-++++-.:  -.%+%#
 -=-- . .:-=*#-**-.. .:--==#=*-=.. .:. -=:
 :-=*.     ... .  . . ...-:.: ..    -%-:+:
  -.=:    .. ..... ..:.....    .    +::-:
 .++%# . . ... -**-::#=:.:...  ..  :=.*-.
  =-@+ .. :--=:.-::-:.:...........#@@*:
     .=:...::=+-+*=+-**##+=.  . .*:*%..
       -:.... ..--::.. .....   .%@#@+
         .... ....:. ..  .......--=
         ..+**=#=**+======:.....
         =. =+-*%#***#%+=-.   ..#+
         :. .. ::::::...      ..*-*%+:.-.
         ..  ..  .  .         -+.....=**=*+=++
  .+-**#+:-                 =-.      .-=---::.
#+- :=-: := . .          --=
....-   :%.. ..       =-="""

PANEL = """\
pau@itszcx
——————————————————————————

. <b>Role</b>:...... Pedagogical Assistant @ Epitech Barcelona
. <b>Location</b>:.. Remote (Spain)
. <b>Spoken</b>:.... English, Spanish, Catalan
. <b>Education</b>:. Epitech, Monash

. <b>OS</b>:........ Linux, macOS
. <b>Programming</b>:. C++, Python
. <b>Frameworks</b>:..... FastAPI (SQAlch, Alembic), NextJS
. <b>Databases</b>: ..... PostgreSQL, MongoDB
. <b>Infra</b>: ..... Docker, Aeron, AWS, RabbitMQ, MinIO, vcpkg, UV

. <b>Working on</b>:. <a href="https://github.com/ItsZcx/dragonfly">Dragonfly</a>
. <b>Interests</b>:. Quant, Homelab, Bouldering, Traveling

— Contact —————————————————————
. <b>Portfolio</b>:.... <a href="https://zcx.dev">zcx.dev</a>
. <b>GitHub</b>:.... <a href="https://github.com/ItsZcx">ItsZcx</a>
. <b>LinkedIn</b>:.. <a href="https://www.linkedin.com/in/joan-pau-merida-ruiz/">Pau</a>
. <b>Email</b>:..... joanpaumeridaruiz@gmail.com

— GitHub Stats ————————————————
{stats}"""

ART_TOP_PAD = 0        # blank lines above the ASCII, to sit lower in the card

# One <pre> and nothing else. A fenced/HTML block that starts with <pre> runs
# until </pre>, so blank lines inside are safe - unlike <table>, where a blank
# line ends the block and the content after it gets parsed as markdown.
CARD = """\
<pre>{body}</pre>"""


def human(number):
    """985187 -> 985k, 1967047 -> 1.97M. Keeps the grid inside 42 columns."""
    if number >= 1_000_000:
        return f"{number / 1_000_000:.2f}".rstrip("0").rstrip(".") + "M"
    if number >= 1_000:
        return f"{round(number / 1000)}k"
    return f"{number}"


def stats_block(data):
    """Six stats in two dotted columns, same idiom as the panel.

    Rows: Views | Stars, Repos | Commits, then one full-width row for the
    line counts. The two-column rows share a fixed left edge; the last row
    runs to MAX_COLS.
    """
    views = f"{data['views']:,}" if data.get("views") is not None else "\u2014"
    rows = [
        ("Views", views, "Stars", f"{data['stars']:,}"),
        ("Repos", f"{data['repos']} {{Contributed: {data['contributed']}}}",
         "Commits", f"{data['commits']:,}"),
        ("Lines of Code",
         f"{human(data['loc'])} (++{human(data['added'])} --{human(data['deleted'])})",
         None, None),
    ]

    gap = 2
    paired = [row for row in rows if row[2] is not None]
    # +3 = one space, at least one dot, one space
    left_needed = max(len(f". {lk}:") + len(lv) for lk, lv, _, _ in paired) + 3
    right_needed = max(len(f". {rk}:") + len(rv) for _, _, rk, rv in paired) + 3

    # split whatever is left over between the two columns, otherwise the
    # longest left row ends up with exactly one dot while the right column
    # hoards the space
    slack = MAX_COLS - gap - left_needed - right_needed
    left_edge = left_needed + max(0, slack // 2)
    right_edge = MAX_COLS - left_edge - gap

    def cell(key, value, edge):
        prefix = f". {key}:"
        dots = max(1, edge - len(prefix) - len(value) - 2)
        return f". <b>{key}</b>: " + "." * dots + f" {value}"

    out = []
    for left_key, left_value, right_key, right_value in rows:
        if right_key is None:
            out.append(cell(left_key, left_value, MAX_COLS))
            continue
        left = cell(left_key, left_value, left_edge)
        plain = len(re.sub(r"<[^>]+>", "", left))
        out.append(left + " " * max(gap, left_edge + gap - plain)
                   + cell(right_key, right_value, right_edge))
    return "\n".join(out)


def align_panel(text, width=MAX_COLS):
    """Right-align every value, filling the gap after the colon with dots.

    `. Role:.... Pedagogical Assistant` becomes `. Role:... Pedagogical Assistant`
    with the value ending on the same column as every other value.
    """
    plain = lambda chunk: re.sub(r"<[^>]+>", "", chunk)
    out = []
    for line in text.split("\n"):
        # continuation of a value (e.g. the second line of Interests):
        # right-align its end to match every other value
        if re.match(r"^\s{4,}\S", line) and "<b>" not in line:
            stripped = line.strip()
            out.append(" " * max(0, width - len(stripped)) + stripped)
            continue

        # a full-width rule, or a section heading followed by one
        if re.fullmatch(r"\u2014+", line):
            out.append("\u2014" * width)
            continue
        heading = re.match(r"^(\u2014 [^\u2014]+ )\u2014+$", line)
        if heading:
            prefix = heading.group(1)
            out.append(prefix + "\u2014" * max(1, width - len(prefix)))
            continue

        match = re.match(r"^(\. <b>.+?</b>:)[. ]*(.*)$", line)
        if not match:
            out.append(line)
            continue

        prefix, value = match.group(1), match.group(2).strip()
        if not value:
            out.append(line)
            continue

        # ": .... value" - one space, the dots, one space
        dots = width - len(plain(prefix)) - 2 - len(plain(value))

        # dots <= 0 means the row cannot fit; still rebuild it so stale dots
        # never linger, and let the width check report the overflow
        if dots > 0:
            out.append(f"{prefix} {'.' * dots} {value}")
        else:
            out.append(f"{prefix} {value}")
    return "\n".join(out)


def build_card(data):
    panel = align_panel(PANEL).replace("{stats}", stats_block(data))

    art = [""] * ART_TOP_PAD + ART.split("\n")
    panel = panel.split("\n")
    art_width = max(len(line) for line in art)
    height = max(len(art), len(panel))

    body = []
    for index in range(height):
        left = art[index] if index < len(art) else ""
        right = panel[index] if index < len(panel) else ""
        body.append(left.ljust(art_width) + GAP + right if right else left)

    return CARD.format(body="\n".join(body))


def main():
    demo = "--demo" in sys.argv
    # --demo renders with placeholder numbers; writing them to README.md by
    # accident is how fake stats end up committed, so it prints unless --write
    dry_run = "--dry-run" in sys.argv or (demo and "--write" not in sys.argv)

    data = DEMO if demo else stats.fetch()
    print(
        json.dumps(
            {
                k: data[k]
                for k in (
                    "repos",
                    "contributed",
                    "stars",
                    "followers",
                    "commits",
                    "loc",
                    "added",
                    "deleted",
                    "views",
                )
                if k in data
            },
            indent=1,
        )
    )

    if dry_run:
        print("dry run - README.md untouched")
        return

    with open("README.md", encoding="utf-8") as handle:
        readme = handle.read()

    start = "<!-- neofetch:start -->"
    end = "<!-- neofetch:end -->"
    if start not in readme or end not in readme:
        raise SystemExit("README.md is missing the neofetch markers")

    head, tail = readme.split(start, 1)[0], readme.split(end, 1)[1]

    # build the replacement BEFORE opening the file - a half-rendered card must
    # never be able to truncate the README
    card = build_card(data)

    with open("README.md", "w", encoding="utf-8") as handle:
        handle.write(f"{head}{start}\n{card}\n{end}{tail}")

    # measure what actually goes into the README (after alignment), not the
    # raw PANEL - the hand-written dots are as wide as the file says they are
    panel_part = card.split("<pre>")[-1].split("</pre>")[0]
    widest = max(
        len(re.sub(r"<[^>]+>", "", line).rstrip()) for line in panel_part.splitlines()
    )
    print(f"README.md updated - widest panel line {widest} chars")
    if widest > MAX_COLS:
        print(f"WARNING: over {MAX_COLS} chars, the table will scroll")


if __name__ == "__main__":
    main()

"""Rebuild the README card.

The card is written out literally below - edit ART and PANEL directly, they
are the source of truth. The numbers come from stats.py and land at the
{stats} placeholder.

    python3 today.py              # fetch stats, rewrite README.md
    python3 today.py --dry-run    # fetch stats, print them, touch nothing
    python3 today.py --demo       # sample numbers, no network

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

MAX_COLS = 42  # right edge of every panel line

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

. <b>Role</b>:...... Pedagogical Assistant @ Epitech
. <b>Location</b>:.. Remote (Spain)
. <b>Spoken</b>:.... English, Spanish, Catalan
. <b>Education</b>:. Epitech, Monash

. <b>OS</b>:........ Linux, macOS
. <b>Programming</b>:. C++, Python
. <b>Infra</b>: ..... Docker, AWS, RabbitMQ, Minio
. <b>Databases</b>: ..... PostgreSQL, MongoDB
. <b>Others</b>:..... Aeron, FastAPI, vcpkg, UV

. <b>Working on</b>:. <a href="https://github.com/ItsZcx/dragonfly">Dragonfly</a>
. <b>Interests</b>:. Quant, Homelab, Bouldering

— Contact —————————————————————
. <b>Portfolio</b>:.... <a href="https://zcx.dev">zcx.dev</a>
. <b>GitHub</b>:.... <a href="https://github.com/ItsZcx">ItsZcx</a>
. <b>LinkedIn</b>:.. <a href="https://www.linkedin.com/in/joan-pau-merida-ruiz/">Pau</a>
. <b>Email</b>:..... joanpaumeridaruiz@gmail.com

— GitHub Stats ————————————————
{stats}"""

CARD = """\
<table>
<tr>
<td valign="top"><pre>{art}</pre></td>
<td valign="top"><pre>{panel}</pre></td>
</tr>
</table>"""


def human(number):
    """985187 -> 985k, 1967047 -> 1.97M. Keeps the grid inside 42 columns."""
    if number >= 1_000_000:
        return f"{number / 1_000_000:.2f}".rstrip("0").rstrip(".") + "M"
    if number >= 1_000:
        return f"{round(number / 1000)}k"
    return f"{number}"


def stats_block(data):
    """Three rows, two columns. The left column is padded to 23 characters."""
    views = f"{data['views']:,}" if data.get("views") is not None else "\u2014"
    left = [
        f"Profile Views {views}",
        f"{data['commits']:,} commits",
        f"{human(data['loc'])} LOC",
    ]
    right = [
        f"{data['stars']:,} stars",
        f"{data['repos']} repos {{{data['contributed']}}}",
        f"(++{human(data['added'])} --{human(data['deleted'])})",
    ]
    return "\n".join(f"   {l:<23}{r}" for l, r in zip(left, right))


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
    panel = align_panel(PANEL.replace("{stats}", stats_block(data)))
    return CARD.format(art=ART, panel=panel)


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

#!/usr/bin/env python3
"""One-shot script: extract index.html sections into partials.

Run from ui/:
    python3 _extract_partials.py

Creates partials/ directory and replaces sections with
<!-- @include partials/foo.html --> directives.
"""
import os, re, pathlib

INDEX = pathlib.Path(__file__).parent / "index.html"
PARTIALS = pathlib.Path(__file__).parent / "partials"

# Each entry: (partial_filename, start_marker_re, end_marker_re)
# start is INCLUSIVE (that line is part of the extracted block)
# end is INCLUSIVE (that line is part of the extracted block)
#
# We search line-by-line.  When we see start_marker_re we begin
# capturing.  We stop capturing AFTER seeing end_marker_re.
# The captured block is written to partials/<filename> and
# replaced by a single include directive in index.html.

SECTIONS = [
    # 1. Auth lock screen: from <!-- ── Auth Lock Screen ── --> to the closing </div> before the <div x-show="authenticated"
    ("auth.html",
     r"^<!-- ── Auth Lock Screen",
     # The auth block ends at a lone </div> that precedes the
     # <div x-show="authenticated" line.  We look for a </div>
     # immediately followed by blank + authenticated wrapper.
     None),  # special handling below

    # 2. Sidebar
    ("sidebar.html",
     r"^\s*<!-- ── Sidebar",
     r"^\s*</aside>"),

    # 3. Dashboard tab (from TAB: DASHBOARD comment to the line before TAB: CHAT)
    ("dashboard.html",
     r"TAB: DASHBOARD",
     # The dashboard's closing </div> is on the line right before
     # the TAB: CHAT comment.  We'll stop just before TAB: CHAT.
     None),

    # 4. Settings tab
    ("settings.html",
     r"TAB: SETTINGS",
     None),

    # 5. Voice overlay
    ("voice.html",
     r"^\s*<!-- ── Voice ORB Fullscreen Overlay",
     # Ends before <!-- ── Mobile bottom tab bar
     None),

    # 6. Modals + toast + banners
    ("modals.html",
     r"^<!-- ── Mobile Modal",
     # Ends before <!-- ── Axon Modules ── -->
     None),
]


def find_line(lines: list[str], pattern: str, start: int = 0) -> int:
    """Return 0-based index of first line matching pattern."""
    rx = re.compile(pattern)
    for i in range(start, len(lines)):
        if rx.search(lines[i]):
            return i
    raise ValueError(f"Pattern not found: {pattern!r} (from line {start})")


def extract_sections(lines: list[str]) -> list[tuple[str, int, int]]:
    """Return list of (partial_filename, start_idx, end_idx) inclusive."""
    results = []

    # 1. Auth: starts at "Auth Lock Screen", ends at lone </div> before
    #    the main authenticated wrapper
    auth_start = find_line(lines, r"^<!-- ── Auth Lock Screen")
    # auth ends at the standalone </div> that closes the fixed overlay
    # search forward for </div> that is followed (possibly after blank) by
    # authenticated wrapper or main layout.
    auth_end = auth_start
    depth = 0
    entered = False
    for i in range(auth_start, len(lines)):
        line_stripped = lines[i].strip()
        opens = len(re.findall(r"<div\b", line_stripped))
        closes = line_stripped.count("</div")
        depth += opens - closes
        if depth > 0:
            entered = True
        if entered and depth <= 0:
            auth_end = i
            break
    results.append(("auth.html", auth_start, auth_end))

    # 2. Sidebar: starts at <!-- ── Sidebar, ends at </aside>
    sb_start = find_line(lines, r"^\s*<!-- ── Sidebar")
    sb_end = find_line(lines, r"^\s*</aside>", sb_start)
    results.append(("sidebar.html", sb_start, sb_end))

    # 3. Dashboard: TAB: DASHBOARD → line before TAB: CHAT
    dash_start = find_line(lines, r"TAB: DASHBOARD")
    # The section comment is 3 lines (comment, TAB name, close comment)
    # but our start already covers the opening ═══ line.
    # End is the closing </div> on the line before the TAB: CHAT comment.
    chat_start = find_line(lines, r"TAB: CHAT", dash_start + 1)
    # Walk backwards from chat_start to find last non-blank line before it
    dash_end = chat_start - 1
    while dash_end > dash_start and lines[dash_end].strip() == "":
        dash_end -= 1
    results.append(("dashboard.html", dash_start, dash_end))

    # 4. Settings: TAB: SETTINGS → line before Memory tab
    sett_start = find_line(lines, r"TAB: SETTINGS")
    memory_start = find_line(lines, r"── Memory tab", sett_start + 1)
    sett_end = memory_start - 1
    while sett_end > sett_start and lines[sett_end].strip() == "":
        sett_end -= 1
    results.append(("settings.html", sett_start, sett_end))

    # 5. Voice overlay: → line before Mobile bottom tab bar
    voice_start = find_line(lines, r"^\s*<!-- ── Voice ORB Fullscreen Overlay")
    mobile_bar = find_line(lines, r"── Mobile bottom tab bar", voice_start + 1)
    voice_end = mobile_bar - 1
    while voice_end > voice_start and lines[voice_end].strip() == "":
        voice_end -= 1
    results.append(("voice.html", voice_start, voice_end))

    # 6. Modals: Mobile Modal → line before Axon Modules
    modals_start = find_line(lines, r"^<!-- ── Mobile Modal")
    axon_mods = find_line(lines, r"── Axon Modules ──", modals_start + 1)
    modals_end = axon_mods - 1
    while modals_end > modals_start and lines[modals_end].strip() == "":
        modals_end -= 1
    results.append(("modals.html", modals_start, modals_end))

    return results


def main():
    PARTIALS.mkdir(exist_ok=True)
    text = INDEX.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)

    sections = extract_sections(lines)
    # Sort by start index descending so we can replace from bottom to top
    # without invalidating earlier indices.
    sections.sort(key=lambda s: s[1], reverse=True)

    for filename, start, end in sections:
        partial_lines = lines[start:end + 1]
        partial_path = PARTIALS / filename
        partial_path.write_text("".join(partial_lines), encoding="utf-8")
        count = end - start + 1
        print(f"  {filename:20s}  {count:4d} lines  (L{start+1}–L{end+1})")

        # Replace the section with an include directive
        indent = "    " if filename in ("dashboard.html", "settings.html") else ""
        directive = f"{indent}<!-- @include partials/{filename} -->\n"
        lines[start:end + 1] = [directive]

    INDEX.write_text("".join(lines), encoding="utf-8")
    total = sum(e - s + 1 for _, s, e in sections)
    remaining = len("".join(lines).splitlines())
    print(f"\nExtracted {total} lines into {len(sections)} partials.")
    print(f"index.html: {remaining} lines remaining.")


if __name__ == "__main__":
    main()

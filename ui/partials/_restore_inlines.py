"""Reconstruct index.html by re-inlining partials."""
import re, pathlib
ui = pathlib.Path(__file__).parent
index = ui / "index.html"
html = index.read_text(encoding="utf-8")
def expand(m):
    p = ui / m.group(1)
    return p.read_text(encoding="utf-8") if p.exists() else m.group(0)
full = re.sub(r"^\s*<!-- @include (\S+) -->\s*$", expand, html, flags=re.MULTILINE)
index.write_text(full, encoding="utf-8")
print(f"Restored to {len(full.splitlines())} lines")

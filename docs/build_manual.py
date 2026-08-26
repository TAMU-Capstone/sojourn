#!/usr/bin/env python3
"""Render MANUAL.md -> a styled, in-world 'recovered document' HTML."""
import re
import sys

def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

def inline(s):
    s = esc(s)
    s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
    s = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", s)
    s = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<em>\1</em>", s)
    return s

def is_redaction(text):
    # A genuine missing-content block, not merely decorative ▓ markers.
    for r in text.split("\n"):
        clean = r.replace("▓", "").replace("*", "").strip().lower()
        if clean in ("pages missing", "appendix missing"):
            return True
    return False

md = open(sys.argv[1], encoding="utf-8").read()
lines = md.split("\n")
out = []
i = 0
n = len(lines)

while i < n:
    line = lines[i]

    # fenced code
    if line.startswith("```"):
        i += 1
        code = []
        while i < n and not lines[i].startswith("```"):
            code.append(esc(lines[i]))
            i += 1
        i += 1
        out.append('<pre class="term">' + "\n".join(code) + "</pre>")
        continue

    # blockquote (may be multi-line); detect redaction / warning styling
    if line.startswith(">"):
        block = []
        while i < n and lines[i].startswith(">"):
            block.append(lines[i][1:].lstrip())
            i += 1
        text = "\n".join(block)
        cls = "note"
        if is_redaction(text):
            cls = "redaction"
        elif text.lstrip().startswith("⚠"):
            cls = "warning"
        # render inner: keep line breaks, bold, code; drop the ▓ marker rows into bars
        html_parts = []
        if cls == "redaction":
            # a recovered-document redaction: title line, black bar, italic note
            rows = [r.strip() for r in text.split("\n") if r.strip()]
            title = None
            note = []
            for r in rows:
                clean = r.replace("▓▓▓", "").strip()
                if "**" in r and title is None:
                    title = re.sub(r"\*\*([^*]+)\*\*", r"\1", clean)
                elif clean.strip("*").lower() in ("pages missing", "appendix missing",
                                                  "recovered fragment; change list illegible"):
                    continue  # becomes the bar's caption
                else:
                    note.append(clean)
            if title:
                html_parts.append(f'<div class="rtitle">{esc(title)}</div>')
            html_parts.append('<div class="bar"><span>PAGES MISSING</span></div>')
            for para_n in note:
                html_parts.append("<p>" + inline(para_n) + "</p>")
        else:
            for para in re.split(r"\n\s*\n", text):
                para = para.replace("▓▓▓", "").strip()
                if para:
                    html_parts.append("<p>" + inline(para).replace("\n", "<br>") + "</p>")
        out.append(f'<div class="callout {cls}">' + "".join(html_parts) + "</div>")
        continue

    # tables
    if line.strip().startswith("|") and i + 1 < n and re.match(r"^\s*\|[\s:|-]+\|", lines[i + 1]):
        header = [c.strip() for c in line.strip().strip("|").split("|")]
        i += 2
        rows = []
        while i < n and lines[i].strip().startswith("|"):
            rows.append([c.strip() for c in lines[i].strip().strip("|").split("|")])
            i += 1
        th = "".join(f"<th>{inline(h)}</th>" for h in header)
        trs = ""
        for r in rows:
            tds = "".join(f"<td>{inline(c)}</td>" for c in r)
            trs += f"<tr>{tds}</tr>"
        out.append(f"<table><thead><tr>{th}</tr></thead><tbody>{trs}</tbody></table>")
        continue

    # headings
    m = re.match(r"^(#{1,6})\s+(.*)$", line)
    if m:
        level = len(m.group(1))
        out.append(f"<h{level}>{inline(m.group(2))}</h{level}>")
        i += 1
        continue

    if line.strip() == "---":
        out.append('<hr>')
        i += 1
        continue

    if line.strip() == "":
        i += 1
        continue

    # list item (with wrapped-continuation support)
    if re.match(r"^\s*[-*]\s+", line):
        items = []
        cur = None
        while i < n:
            if re.match(r"^\s*[-*]\s+", lines[i]):
                if cur is not None:
                    items.append(cur)
                cur = re.sub(r"^\s*[-*]\s+", "", lines[i])
            elif lines[i].strip() and cur is not None and lines[i].startswith(" "):
                cur += " " + lines[i].strip()      # continuation of current item
            else:
                break
            i += 1
        if cur is not None:
            items.append(cur)
        out.append("<ul>" + "".join(f"<li>{inline(t)}</li>" for t in items) + "</ul>")
        continue

    # paragraph (gather until blank)
    para = [line]
    i += 1
    while i < n and lines[i].strip() and not re.match(r"^(#{1,6}\s|>|\||```|\s*[-*]\s|---)", lines[i]):
        para.append(lines[i])
        i += 1
    out.append("<p>" + inline(" ".join(para)) + "</p>")

body = "\n".join(out)

CSS = """
@page { size: Letter; margin: 22mm 20mm 20mm 20mm; }
:root{ --ink:#1c1a17; --paper:#f4f1e9; --rule:#b7ae99; --accent:#5a3921;
       --warn:#7a2318; --stamp:#7a2a2a; }
*{ box-sizing:border-box; }
html{ font-size:10.6pt; }
body{ background:var(--paper); color:var(--ink); margin:0;
      font-family:"Georgia","Times New Roman",serif; line-height:1.5; }
.sheet{ max-width:190mm; margin:0 auto; padding:0; position:relative; }
h1,h2,h3,h4{ font-family:"Courier New",monospace; color:var(--accent);
             line-height:1.25; }
h1{ font-size:19pt; letter-spacing:1px; margin:0 0 2px; text-transform:uppercase;
    max-width:120mm; }
h3{ font-size:11pt; color:#4a4436; letter-spacing:2px; font-weight:normal;
    text-transform:uppercase; margin:0 0 14px; }
h2{ font-size:13.5pt; margin:22px 0 8px; padding-top:6px;
    border-top:2px solid var(--rule); }
h4{ font-size:10.5pt; margin:14px 0 5px; color:#3a352a; }
p{ margin:0 0 9px; }
strong{ color:#000; }
code{ font-family:"Courier New",monospace; font-size:9.4pt;
      background:#e7e2d3; padding:0 3px; border-radius:2px; }
pre.term{ font-family:"Courier New",monospace; font-size:9pt; line-height:1.4;
      background:#1b1a17; color:#d8e0c8; padding:10px 12px; border-radius:3px;
      overflow-x:auto; border:1px solid #000; margin:10px 0; white-space:pre-wrap;
      word-break:break-word; }
table{ border-collapse:collapse; width:100%; margin:10px 0 14px; font-size:9.3pt; }
th,td{ border:1px solid var(--rule); padding:4px 7px; text-align:left;
       vertical-align:top; }
th{ background:#e3ddcb; font-family:"Courier New",monospace; font-size:8.7pt;
    text-transform:uppercase; letter-spacing:.4px; }
tbody tr:nth-child(even){ background:#eee9db; }
hr{ border:none; border-top:1px solid var(--rule); margin:16px 0; }
ul{ margin:0 0 10px; padding-left:20px; }
li{ margin:2px 0; }
.callout{ margin:12px 0; padding:9px 13px; border-radius:2px; page-break-inside:avoid; }
.callout p{ margin:5px 0; }
.note{ background:#ece6d6; border-left:4px solid var(--rule); }
.warning{ background:#f3e2dd; border-left:4px solid var(--warn); color:#5c1c14; }
.warning strong{ color:#4a140d; }
.redaction{ background:#e9e4d4; border:1px dashed #8a8069; font-style:italic;
            color:#4a4636; }
.redaction .rtitle{ font-family:"Courier New",monospace; font-style:normal;
   font-weight:bold; font-size:9pt; letter-spacing:.5px; color:#3a352a;
   margin-bottom:6px; }
.redaction .bar{ height:15px; margin:6px 0 8px; border-radius:1px; position:relative;
   background:repeating-linear-gradient(90deg,#151515 0 26px,#000 26px 34px);
   display:flex; align-items:center; justify-content:center; }
.redaction .bar span{ font-family:"Courier New",monospace; font-style:normal;
   font-size:7pt; letter-spacing:3px; color:#d8d2c2; opacity:.55; }
.redaction p{ font-family:"Courier New",monospace; font-size:8.8pt; margin:4px 0 0; }
.stamp{ position:absolute; top:5mm; right:0; transform:rotate(6deg);
   border:3px double var(--stamp); color:var(--stamp); font-family:"Courier New",monospace;
   font-weight:bold; font-size:11pt; letter-spacing:1px; padding:5px 12px;
   opacity:.72; border-radius:3px; }
.doc-foot{ margin-top:20px; border-top:2px solid var(--rule); padding-top:6px;
   font-family:"Courier New",monospace; font-size:8pt; color:#5a5442;
   display:flex; justify-content:space-between; }
"""

html = f"""<!doctype html><html><head><meta charset="utf-8">
<title>Sojourn Mission Operations Manual</title><style>{CSS}</style></head>
<body><div class="sheet">
<div class="stamp">ARCHIVE COPY</div>
{body}
<div class="doc-foot"><span>ISA-SOJ-OPS-014 REV C</span>
<span>RECOVERED · INCOMPLETE</span><span>FLIGHT SW BUILD 1.0</span></div>
</div></body></html>"""

open(sys.argv[2], "w", encoding="utf-8").write(html)
print("wrote", sys.argv[2], len(html), "bytes")

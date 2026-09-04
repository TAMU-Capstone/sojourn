const {
  Document, Packer, Paragraph, TextRun, HeadingLevel, AlignmentType,
  Table, TableRow, TableCell, WidthType, ShadingType, LevelFormat,
} = require('docx');
const fs = require('fs');

const ACCENT = '1F3864', LIGHT = 'D9E2F3', GRAY = '595959';
const TOTAL = 9360;

const numbering = { config: [
  { reference: 'bullets', levels: [{ level: 0, format: LevelFormat.BULLET, text: '•', alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 360, hanging: 200 } } } }] },
  { reference: 'numbered', levels: [{ level: 0, format: LevelFormat.DECIMAL, text: '%1.', alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 360, hanging: 260 } } } }] },
]};

function md(text) {
  const parts = [];
  const re = /(\*\*[^*]+\*\*|\*[^*]+\*|`[^`]+`)/g;
  let last = 0, m;
  while ((m = re.exec(text)) !== null) {
    if (m.index > last) parts.push({ t: text.slice(last, m.index) });
    const tok = m[0];
    if (tok.startsWith('**')) parts.push({ t: tok.slice(2, -2), b: true });
    else if (tok.startsWith('`')) parts.push({ t: tok.slice(1, -1), mono: true });
    else parts.push({ t: tok.slice(1, -1), i: true });
    last = m.index + tok.length;
  }
  if (last < text.length) parts.push({ t: text.slice(last) });
  return parts.map(p => new TextRun({ text: p.t, bold: !!p.b, italics: !!p.i, font: p.mono ? 'Consolas' : undefined, size: p.mono ? 19 : undefined, shading: p.mono ? { type: ShadingType.CLEAR, fill: 'F2F2F2' } : undefined }));
}

function makeTable(headers, rows) {
  const n = headers.length;
  const maxLen = headers.map((h, i) => Math.max(h.length, ...rows.map(r => (r[i] || '').length), 4));
  const sum = maxLen.reduce((a, b) => a + b, 0);
  const widths = maxLen.map(l => Math.max(1050, Math.round(TOTAL * l / sum)));
  const wsum = widths.reduce((a, b) => a + b, 0);
  const big = widths.indexOf(Math.max(...widths));
  widths[big] += TOTAL - wsum;
  const cell = (text, i, head) => new TableCell({
    width: { size: widths[i], type: WidthType.DXA },
    shading: head ? { type: ShadingType.CLEAR, fill: LIGHT } : undefined,
    margins: { top: 55, bottom: 55, left: 90, right: 90 },
    children: [new Paragraph({ children: head ? [new TextRun({ text, bold: true, size: 19 })] : md(text).map(r => { r.root && 0; return r; }), spacing: { after: 0, line: 240 } })],
  });
  const headEmpty = headers.every(h => h.trim() === '');
  const out = [];
  if (!headEmpty) out.push(new TableRow({ tableHeader: true, children: headers.map((h, i) => cell(h, i, true)) }));
  rows.forEach(r => out.push(new TableRow({ children: r.map((c, i) => cell(c, i, false)) })));
  return new Table({ width: { size: TOTAL, type: WidthType.DXA }, columnWidths: widths, rows: out });
}

// ---- parse markdown ----
const [IN, OUT] = process.argv.slice(2);
if (!IN || !OUT) { console.error('usage: node build_docx.js <in.md> <out.docx>'); process.exit(2); }
const src = fs.readFileSync(IN, 'utf8');
const lines = src.split('\n');
const children = [];
let i = 0;
const splitRow = (l) => l.trim().replace(/^\|/, '').replace(/\|$/, '').split('|').map(s => s.trim());

while (i < lines.length) {
  const line = lines[i];
  if (line.startsWith('```')) {
    i++;
    const code = [];
    while (i < lines.length && !lines[i].startsWith('```')) { code.push(lines[i]); i++; }
    i++;
    code.forEach(l => children.push(new Paragraph({
      children: [new TextRun({ text: l === '' ? ' ' : l, font: 'Consolas', size: 18 })],
      shading: { type: ShadingType.CLEAR, fill: 'F2F2F2' },
      spacing: { after: 0, line: 240 }, indent: { left: 240 },
    })));
    children.push(new Paragraph({ spacing: { after: 120 }, children: [] }));
    continue;
  }
  if (/^\|/.test(line.trim()) && i + 1 < lines.length && /^\|[\s:|-]+\|?$/.test(lines[i + 1].trim())) {
    const headers = splitRow(line);
    i += 2;
    const rows = [];
    while (i < lines.length && /^\|/.test(lines[i].trim())) { rows.push(splitRow(lines[i])); i++; }
    children.push(makeTable(headers, rows));
    children.push(new Paragraph({ spacing: { after: 120 }, children: [] }));
    continue;
  }
  if (line.startsWith('# ')) {
    children.push(new Paragraph({ alignment: AlignmentType.CENTER, spacing: { before: 200, after: 60 }, children: [new TextRun({ text: line.slice(2), bold: true, size: 44, color: ACCENT })] }));
    i++; continue;
  }
  if (line.startsWith('## ')) {
    children.push(new Paragraph({ heading: HeadingLevel.HEADING_1, spacing: { before: 300, after: 140 }, children: md(line.slice(3)) }));
    i++; continue;
  }
  if (line.startsWith('### ')) {
    children.push(new Paragraph({ heading: HeadingLevel.HEADING_2, spacing: { before: 220, after: 110 }, children: md(line.slice(4)) }));
    i++; continue;
  }
  if (line.trim() === '---' || line.trim() === '') { i++; continue; }
  if (/^- /.test(line.trim())) {
    children.push(new Paragraph({ children: md(line.trim().slice(2)), numbering: { reference: 'bullets', level: 0 }, spacing: { after: 70, line: 260 } }));
    i++; continue;
  }
  const nm = line.trim().match(/^(\d+)\.\s+(.*)$/);
  if (nm) {
    children.push(new Paragraph({ children: md(nm[2]), numbering: { reference: 'numbered', level: 0 }, spacing: { after: 70, line: 260 } }));
    i++; continue;
  }
  if (line.startsWith('*') && line.endsWith('*') && !line.startsWith('**')) {
    children.push(new Paragraph({ spacing: { before: 200, after: 120 }, children: [new TextRun({ text: line.replace(/^\*|\*$/g, ''), italics: true, color: GRAY, size: 19 })] }));
    i++; continue;
  }
  // paragraph (merge continuation lines)
  let para = line;
  while (i + 1 < lines.length && lines[i + 1].trim() !== '' && !/^(#|\||- |\d+\. |```|---)/.test(lines[i + 1].trim())) { i++; para += ' ' + lines[i].trim(); }
  children.push(new Paragraph({ children: md(para), spacing: { after: 130, line: 270 } }));
  i++;
}

const doc = new Document({
  numbering,
  styles: { default: {
    document: { run: { font: 'Calibri', size: 21 }, paragraph: { spacing: { line: 270 } } },
    heading1: { run: { font: 'Calibri', size: 30, bold: true, color: ACCENT } },
    heading2: { run: { font: 'Calibri', size: 25, bold: true, color: '2E5395' } },
  }},
  sections: [{ properties: { page: { size: { width: 12240, height: 15840 }, margin: { top: 1300, bottom: 1300, left: 1300, right: 1300 } } }, children }],
});

Packer.toBuffer(doc).then(buf => {
  fs.writeFileSync(OUT, buf);
  console.log('written', buf.length);
});

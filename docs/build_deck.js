const pptxgen = require('pptxgenjs');
const React = require('react');
const ReactDOMServer = require('react-dom/server');
const sharp = require('sharp');
const { FaMicrochip, FaLayerGroup, FaShieldAlt, FaGraduationCap, FaRocket, FaSatelliteDish, FaServer, FaTerminal } = require('react-icons/fa');

const BG = '0D1321', CARD = '16233A', CARD2 = '111C30', TERMBG = '060A14';
const TXT = 'E8EEF7', MUT = '8CA3C3', GREEN = '39D353', AMBER = 'FFB454', BLUE = '5CA8FF';

async function icon(Comp, color) {
  const svg = ReactDOMServer.renderToStaticMarkup(React.createElement(Comp, { color: '#' + color, size: 256 }));
  const buf = await sharp(Buffer.from(svg)).resize(256, 256).png().toBuffer();
  return 'image/png;base64,' + buf.toString('base64');
}

(async () => {
  const ic = {
    chip: await icon(FaMicrochip, 'FFFFFF'), layer: await icon(FaLayerGroup, 'FFFFFF'),
    shield: await icon(FaShieldAlt, 'FFFFFF'), grad: await icon(FaGraduationCap, 'FFFFFF'),
    rocket: await icon(FaRocket, 'FFFFFF'), dish: await icon(FaSatelliteDish, 'FFFFFF'),
    server: await icon(FaServer, 'FFFFFF'), term: await icon(FaTerminal, 'FFFFFF'),
  };

  const pres = new pptxgen();
  pres.layout = 'LAYOUT_16x9'; // 10 x 5.625

  // ---------------- Slide 1 — Introduction ----------------
  let s = pres.addSlide();
  s.background = { color: BG };

  s.addText('CS CAPSTONE PROPOSAL', { x: 0.5, y: 0.35, w: 5.4, h: 0.3, isTextBox: true, margin: 0, fontFace: 'Arial', fontSize: 10, bold: true, color: BLUE, charSpacing: 3 });
  s.addText('Sojourn', { x: 0.5, y: 0.62, w: 5.5, h: 0.75, isTextBox: true, margin: 0, fontFace: 'Arial', fontSize: 38, bold: true, color: TXT });
  s.addText('Save the probe — a reverse engineering game you build.', { x: 0.5, y: 1.38, w: 5.4, h: 0.32, isTextBox: true, margin: 0, fontFace: 'Arial', fontSize: 13, italic: true, color: AMBER });

  const introBullets = [
    ['A deep-space probe is failing — and its source code is lost. Only the ARM flight binary survives.'],
    ['Players become mission operations engineers: reverse engineer the firmware in Ghidra, then patch the running probe byte by byte over a narrow uplink.'],
    ['It’s real: NASA revived Voyager 1 in 2024 exactly this way — poking new code into memory from 15 billion km away.'],
    ['Your team builds the game: emulated ARM probe, ground-station console, scenario engine — delivered as a single container.'],
    ['One semester, 5–6 students. Then it becomes the foundation of a future reverse engineering course.'],
  ];
  s.addText(introBullets.map((b, i) => ({
    text: b[0],
    options: { bullet: { code: '2022', indent: 12 }, color: TXT, breakLine: true, paraSpaceAfter: 10 },
  })), { x: 0.5, y: 1.85, w: 5.35, h: 3.5, isTextBox: true, margin: 0, fontFace: 'Arial', fontSize: 12.5, valign: 'top', lineSpacingMultiple: 1.06 });

  // terminal panel
  s.addShape(pres.ShapeType.roundRect, { x: 6.15, y: 0.55, w: 3.35, h: 4.35, rectRadius: 0.08, fill: { color: TERMBG }, line: { color: '2A3C5C', width: 1 }, shadow: { type: 'outer', color: '000000', opacity: 0.5, blur: 8, offset: 3, angle: 90 } });
  const t = (txt, color, opts = {}) => ({ text: txt, options: { color, breakLine: true, ...opts } });
  s.addText([
    t('SOJOURN MISSION CONTROL — LINK UP', MUT),
    t(' ', MUT),
    t('TLM f=0412 up=86400s NOMINAL', BLUE),
    t('TLM MAG=-312 FAULT  pwr=412mW', AMBER),
    t('> PEEK 0x20001A40 8 *C2F1', TXT),
    t('ACK PEEK 01 00 00 00 A3 04 ..', GREEN),
    t('> POKE 0x20001A44 00 *9D3B', TXT),
    t('… transmitting — delay 60 s', MUT, { italic: true }),
    t('ACK POKE 1', GREEN),
    t(' ', MUT),
    t('TLM f=0415 up=86415s NOMINAL', BLUE),
    t('    MAG channel silent', BLUE),
    t('    pwr=268mW', BLUE),
    t(' ', MUT),
    t('✔ OBJECTIVE 1 COMPLETE', GREEN, { bold: true }),
    t('  Magnetometer powered down', MUT),
  ], { x: 6.35, y: 0.75, w: 3.0, h: 4.0, isTextBox: true, margin: 0, fontFace: 'Courier New', fontSize: 9, valign: 'top', lineSpacingMultiple: 1.15 });
  s.addText('One player uplink, start to finish', { x: 6.15, y: 4.98, w: 3.35, h: 0.28, isTextBox: true, margin: 0, align: 'center', fontFace: 'Arial', fontSize: 9.5, italic: true, color: MUT });

  // ---------------- Slide 2 — Technical implementation ----------------
  s = pres.addSlide();
  s.background = { color: BG };
  s.addText('Technical Implementation', { x: 0.5, y: 0.32, w: 9, h: 0.6, isTextBox: true, margin: 0, fontFace: 'Arial', fontSize: 30, bold: true, color: TXT });

  // left: architecture stack
  const stack = [
    { name: 'Ground-Station Console', sub: 'browser · xterm.js · live telemetry · uplink line', link: 'WebSocket / HTTP' },
    { name: 'Game Daemon', sub: 'scenario engine · objective checks · delay & budget · saves', link: 'virtual UART + GDB introspection' },
    { name: 'Emulated Probe', sub: 'ARM Cortex-M firmware on QEMU / Renode · watchdog', link: null },
  ];
  let y = 1.12;
  stack.forEach((b) => {
    s.addShape(pres.ShapeType.roundRect, { x: 0.5, y, w: 3.7, h: 0.82, rectRadius: 0.06, fill: { color: CARD }, line: { color: '31486E', width: 1 } });
    s.addText(b.name, { x: 0.68, y: y + 0.1, w: 3.35, h: 0.3, isTextBox: true, margin: 0, fontFace: 'Arial', fontSize: 13, bold: true, color: TXT });
    s.addText(b.sub, { x: 0.68, y: y + 0.4, w: 3.35, h: 0.35, isTextBox: true, margin: 0, fontFace: 'Arial', fontSize: 9.5, color: MUT });
    y += 0.82;
    if (b.link) {
      s.addText('⇅  ' + b.link, { x: 0.5, y: y + 0.02, w: 3.7, h: 0.26, isTextBox: true, margin: 0, align: 'center', fontFace: 'Arial', fontSize: 9.5, italic: true, color: BLUE });
      y += 0.32;
    }
  });
  s.addShape(pres.ShapeType.roundRect, { x: 0.5, y: y + 0.18, w: 3.7, h: 0.72, rectRadius: 0.06, fill: { color: CARD2 }, line: { color: '31486E', width: 1, dashType: 'dash' } });
  s.addText([
    { text: 'Ships as one Docker container', options: { bold: true, color: AMBER, breakLine: true } },
    { text: 'drop-in scenario packages · saves on a mounted volume', options: { color: MUT } },
  ], { x: 0.68, y: y + 0.27, w: 3.4, h: 0.56, isTextBox: true, margin: 0, fontFace: 'Arial', fontSize: 10 });

  // right: 2x2 detail cards
  const cards = [
    { icon: ic.chip, c: GREEN, h: 'Flight Firmware', d: 'Bare-metal C, ARM Cortex-M4 (Thumb-2). Executes from RAM so players patch live code; protected golden image + watchdog make bricking recoverable.' },
    { icon: ic.dish, c: BLUE, h: 'Emulation', d: 'QEMU / Renode with scripted sensor peripherals. A GDB-stub introspection channel lets the platform read probe memory and registers live.' },
    { icon: ic.server, c: AMBER, h: 'Game Platform', d: 'Local daemon evaluates declarative objective assertions against telemetry and memory. Saves = command-log replay against a fresh probe.' },
    { icon: ic.term, c: 'C084FC', h: 'Console & Content', d: 'Browser ground station (xterm.js). Scenarios are pure content packages — a new mission is authored, never coded.' },
  ];
  const cw = 2.5, ch = 1.92, gx = 0.16, gy = 0.18, x0 = 4.42, y0 = 1.12;
  cards.forEach((c, i) => {
    const cx = x0 + (i % 2) * (cw + gx), cy = y0 + Math.floor(i / 2) * (ch + gy);
    s.addShape(pres.ShapeType.roundRect, { x: cx, y: cy, w: cw, h: ch, rectRadius: 0.07, fill: { color: CARD }, line: { color: '31486E', width: 1 } });
    s.addShape(pres.ShapeType.ellipse, { x: cx + 0.16, y: cy + 0.15, w: 0.4, h: 0.4, fill: { color: c.c } });
    s.addImage({ data: c.icon, x: cx + 0.245, y: cy + 0.235, w: 0.23, h: 0.23 });
    s.addText(c.h, { x: cx + 0.66, y: cy + 0.2, w: cw - 0.75, h: 0.3, isTextBox: true, margin: 0, fontFace: 'Arial', fontSize: 13.5, bold: true, color: TXT });
    s.addText(c.d, { x: cx + 0.16, y: cy + 0.62, w: cw - 0.32, h: ch - 0.75, isTextBox: true, margin: 0, fontFace: 'Arial', fontSize: 10, color: MUT, valign: 'top', lineSpacingMultiple: 1.08 });
  });

  // ---------------- Slide 3 — Why pick this ----------------
  s = pres.addSlide();
  s.background = { color: BG };
  s.addText('Why Pick This Capstone', { x: 0.5, y: 0.32, w: 9, h: 0.6, isTextBox: true, margin: 0, fontFace: 'Arial', fontSize: 30, bold: true, color: TXT });

  const rows = [
    { icon: ic.chip, c: GREEN, h: 'Skills few graduates have', d: 'Embedded C, ARM assembly, emulation, reverse engineering, protocol design — on one project.' },
    { icon: ic.layer, c: BLUE, h: 'Full-stack, for real', d: 'Firmware to browser: you own an entire coherent system, not a feature in someone else’s.' },
    { icon: ic.shield, c: AMBER, h: 'De-risked from day one', d: 'You start with working flight firmware in hand — the hardest bring-up is already done.' },
    { icon: ic.grad, c: 'C084FC', h: 'Your work outlives the semester', d: 'The platform becomes the courseware future reverse engineering students learn on.' },
    { icon: ic.rocket, c: 'FF6B6B', h: 'A demo people remember', d: 'Brick a space probe live on stage — then watch the watchdog bring the mission home.' },
  ];
  let ry = 1.12;
  rows.forEach((r) => {
    s.addShape(pres.ShapeType.ellipse, { x: 0.55, y: ry + 0.09, w: 0.52, h: 0.52, fill: { color: r.c } });
    s.addImage({ data: r.icon, x: 0.665, y: ry + 0.2, w: 0.3, h: 0.3 });
    s.addText(r.h, { x: 1.3, y: ry, w: 5.5, h: 0.32, isTextBox: true, margin: 0, fontFace: 'Arial', fontSize: 14.5, bold: true, color: TXT });
    s.addText(r.d, { x: 1.3, y: ry + 0.32, w: 5.5, h: 0.34, isTextBox: true, margin: 0, fontFace: 'Arial', fontSize: 11, color: MUT });
    ry += 0.84;
  });

  const tiles = [
    { big: '5–6', small: 'engineers — every role is a real one' },
    { big: '1', small: 'semester: platform + playable mission' },
    { big: '2024', small: 'the year NASA did this for real (Voyager 1)' },
  ];
  let ty = 1.12;
  tiles.forEach((tl) => {
    s.addShape(pres.ShapeType.roundRect, { x: 7.1, y: ty, w: 2.4, h: 1.28, rectRadius: 0.07, fill: { color: CARD }, line: { color: '31486E', width: 1 } });
    s.addText(tl.big, { x: 7.1, y: ty + 0.1, w: 2.4, h: 0.6, isTextBox: true, margin: 0, align: 'center', fontFace: 'Arial', fontSize: 34, bold: true, color: GREEN });
    s.addText(tl.small, { x: 7.25, y: ty + 0.72, w: 2.1, h: 0.5, isTextBox: true, margin: 0, align: 'center', fontFace: 'Arial', fontSize: 9.5, color: MUT });
    ty += 1.44;
  });

  await pres.writeFile({ fileName: '/home/user/probe-capstone/Capstone_Pitch.pptx' });
  console.log('deck written');
})();

const assert = require('node:assert/strict');
const shorten = require('../src/ffado_webmixer/assets/static/labels.js');
for (const [raw, display] of Object.entries({
  'Mixer/In:01': 'In 1',
  'Mixer/In:03+07': 'In 3+7',
  'Mixer/Out:01': 'Bus 1',
  'Mixer/Out:08': 'Bus 8',
  'Anlg/In:02': 'Analog 2',
  'Mic/Lin/Inst:01': 'Analog 1',
  'Mic/Lin/In:03': 'Analog 3',
  'Mic/Lin/In:04': 'Analog 4',
  'Mic/Lin/In:05': 'Analog 5',
  'Mic/Lin/In:06': 'Analog 6',
  'Mic/Lin/In:07': 'Analog 7',
  'Mic/Lin/In:08': 'Analog 8',
  'Mic/Lin/In:03+04': 'Analog 3+4',
  'Mic/Lin/In:03 + Mic/Lin/In:04': 'Analog 3+4',
  'Mic/Lin/In:08 + Mic/Lin/Inst:02': 'Analog 8+2',
  'Mic/Line/In:08': 'Analog 8',
  'Mic/Lin/Inst:03+04': 'Analog 3+4',
  'Mic/Lin/Inst:03 + Mic/Lin/Inst:04': 'Analog 3+4',
  'Mic/Line/Inst:08': 'Analog 8',
  '1394/In:01': 'Firewire 1',
  '1394/In:01+02': 'Firewire 1+2',
  '1394/In:01 + 02': 'Firewire 1+2',
  '1394/In:02 + 1394/In:05': 'Firewire 2+5',
  '1394/In:02 + 1394/In:01': 'Firewire 2+1',
  '1394:03': 'Firewire 3',
  '1394/Out:04': 'Firewire 4',
  'Line/Out:01': 'Line Out 1',
  'Line/Out:02': 'Line Out 2',
  'Loop:01': 'Loop 1',
  'ADAT/Out:01': 'ADAT 1',
  '1394/In:02 + SPDIF/In:01': 'Firewire 2 + SPDIF 1',
  'Mic/Lin/Inst:01 + 1394/In:02': 'Analog 1 + Firewire 2',
  '1394/In:01 + Mixer/In:02': 'Firewire 1 + In 2',
  'Mic/Lin/Inst:01+02+03': 'Analog 1+2+3',
  'ADAT/In:08': 'ADAT 8',
  'SPDIF/In:01': 'SPDIF 1',
  'Mix 4': 'Bus 4',
  'Mixer/In:02 + Mixer/In:05': 'In 2+5',
  'Vocals': 'Vocals',
  'Vocals 1 + Vocals 2': 'Vocals 1 + Vocals 2',
  'Custom 1394/In:01': 'Custom 1394/In:01',
  'Custom Mixer/In:02': 'Custom Mixer/In:02',
  'Line Out 1': 'Line Out 1',
})) assert.equal(shorten(raw), display, raw);
const fs = require('node:fs');
const source = fs.readFileSync(require('node:path').join(__dirname,'../src/ffado_webmixer/assets/static/index.js'),'utf8');
assert(source.includes('panEl.addEventListener("pointerup"'), 'pan pointer must commit on release');
assert(!source.includes('sendThrottled(id, "pan", pan)'), 'do not hammer FFADO with 50ms pan writes');
assert(source.includes('matrixPairNeedsBus'), 'unlinked DICE buses must not attempt fake pan writes');
console.log('PRO 40 compact labels and safe pan commit guards passed');

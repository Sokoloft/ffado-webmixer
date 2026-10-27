/* Optional real-browser check of output linking, geometry and hardware metering. */
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const {execFileSync} = require('node:child_process');
const assert = require('node:assert/strict');
const browser = process.env.FFADO_TEST_BROWSER || ['/usr/bin/chromium', '/opt/brave-bin/brave', '/usr/bin/brave'].find(fs.existsSync);
if (!browser && !process.env.FFADO_OUTPUT_UI_HTML) { console.log('Output browser check skipped: set FFADO_TEST_BROWSER to Chromium/Brave'); process.exit(0); }
const base = path.join(__dirname, '../src/ffado_webmixer/assets/static');
const source = fs.readFileSync(path.join(base, 'index.js'), 'utf8');
const outputs = source.slice(source.indexOf('function outputPartner('), source.indexOf('// ---- adaptive buses'));
let html = fs.readFileSync(path.join(base, 'index.html'), 'utf8')
  .replace(/<script\b[^>]*>[\s\S]*?<\/script>/g, '').replace(/<link\b[^>]*>/g, '');
const style = fs.readFileSync(path.join(base, 'index.css'), 'utf8');
const peaks = fs.readFileSync(path.join(base, 'peak-metering.js'), 'utf8');
const editable = fs.readFileSync(path.join(base, 'editable-input.js'), 'utf8');
const api = fs.readFileSync(path.join(base, 'frontend-api.js'), 'utf8');
const rename = source.slice(source.indexOf('// ---- rename the active output'), source.indexOf('\nfunction loadMaster('));
const script = `
var OUTPUTS = [1,2,3].map(n=>({id:'line/'+n, name:'Line Out '+n, baseName:'Line Out '+n, mix:null, controllable:true})).concat(
  [0,1].map(mix=>({id:'bus/'+mix, name:'Bus '+(mix+1), mix, controllable:false})));
var OUTPUT_PAIRS = [['line/1','line/2']], STEREO_OUTPUTS = [], STEREO_BUSES = [];
var GAIN_SCALE = {mode:'dice_db'}, currentOut='line/2', currentMix=0, ACTIVE_DEVICE='a';
var CHAIN_LINK_SVG='<svg viewBox="0 0 24 24" width="16" height="16"><path d="M4 12h16"/></svg>';
var row = document.getElementById('row'), pendingStereoLeft=null, masterLoads=0, masterEl=document.getElementById('master');
var side=document.getElementById('side');
function busTabsEnabled(){return false;} function renderBusTabs(){} function scheduleBusGridLayout(){}
function loadMix(){} function loadMaster(){masterLoads++;var o=OUTPUTS.find(o=>o.id===currentOut);if(o)showMasterName(outputButtonName(o));} function savePreference(){return Promise.resolve();}
var errors=[];function toast(message){errors.push(message);}
function toggleBusLink(left){STEREO_BUSES=STEREO_BUSES.length?[]:[left]; buildOutputs();markOutputs();}
var posts=[], rejectRename=false;
function postJson(url, body, device){posts.push({url,body,device});return url==='/api/set' && rejectRename?Promise.reject(Error('rename failed')):Promise.resolve({ok:true});}
function readJson(){return Promise.resolve({stereo_outputs:STEREO_OUTPUTS.length?[]:['line/1'],output_pairs:OUTPUT_PAIRS});}
${outputs}
${peaks}
${api}
${editable}
${rename}
function check(condition, text){if(!condition)throw Error(text);}
function close(a,b){return Math.abs(a-b)<.1;}
function rect(el){return el.getBoundingClientRect();}
function buttonCount(tile){return tile.querySelectorAll('.outbtn').length;}
function frame(){return new Promise(resolve=>setTimeout(resolve,30));}
(async()=>{
  masterEl.hidden=false;document.getElementById('masterbox').hidden=false;
  buildOutputs();markOutputs();
  let tile=document.querySelector('.output-pair-tile');
  const horizontal=rect(tile), button=rect(tile.querySelector('.outbtn'));
  check(buttonCount(tile)===2,'unlinked pair has two buttons');
  check(close(horizontal.width,button.width*2+8),'horizontal pair keeps both slots');
  check(close(rect(tile.querySelector('.output-pair-link')).x+10,horizontal.x+horizontal.width/2),'icon sits on seam');
  tile.querySelector('.output-pair-link').click();
  await frame();
  tile=document.querySelector('.output-pair-tile');
  check(buttonCount(tile)===1,'linked outputs merge into one button');
  check(close(rect(tile).width,horizontal.width) && close(rect(tile).height,horizontal.height),'horizontal footprint preserved');
  check(close(rect(tile.querySelector('.outbtn')).width,horizontal.width),'merged button spans both columns');
  check(currentOut==='line/1','selected Right becomes Left');
  check(posts.length===1 && posts[0].url==='/api/output-stereo' && posts[0].device==='a','one device-specific link request');
  check(tile.querySelector('.outbtn').classList.contains('active'),'merged selection is highlighted');
  check(tile.querySelector('.olabel').textContent==='Line Out 1+2','automatic pair name matches linked faders');
  check(masterName.value==='Line Out 1+2','master and button share the automatic name');
  check(masterName.readOnly,'master name requires the same deliberate editing gesture as faders');
  masterName.dispatchEvent(new MouseEvent('contextmenu',{bubbles:true,cancelable:true}));
  check(!masterName.readOnly,'right-click enables editing the output name');
  masterName.value='Monitors';masterName.dispatchEvent(new Event('change',{bubbles:true}));
  masterName.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',bubbles:true}));await frame();
  check(masterName.value==='Monitors' && document.querySelector('.output-pair-tile .olabel').textContent==='Monitors','custom pair name replaces the full combined label');
  check(OUTPUTS.find(o=>o.id==='line/2').name==='Line Out 2','renaming the pair preserves the Right channel name');
  check(posts.at(-1).body.strip==='out:line/1' && posts.at(-1).device==='a','rename is saved on the Left output and captured device');
  masterName.dispatchEvent(new MouseEvent('contextmenu',{bubbles:true,cancelable:true}));
  masterName.value='Cancelled';masterName.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}));
  check(masterName.value==='Monitors' && posts.at(-1).body.value==='Monitors','Escape cancels the unfinished rename');
  rejectRename=true;
  for(const name of ['Rejected first','Rejected second']) {
    masterName.dispatchEvent(new MouseEvent('contextmenu',{bubbles:true,cancelable:true}));
    masterName.value=name;masterName.dispatchEvent(new Event('change',{bubbles:true}));masterName.blur();
  }
  await frame();rejectRename=false;
  check(masterName.value==='Monitors' && document.querySelector('.output-pair-tile .olabel').textContent==='Monitors','failed queued renames restore the confirmed name');
  tile=document.querySelector('.output-pair-tile');
  side.classList.add('narrow');
  const vertical=rect(tile);
  check(close(vertical.width,button.width) && close(vertical.height,button.height*2+8),'vertical pair retains two rows');
  check(close(rect(tile.querySelector('.outbtn')).height,vertical.height),'merged button spans both rows');
  tile.querySelector('.output-pair-link').click();await frame();
  tile=document.querySelector('.output-pair-tile');
  check(buttonCount(tile)===2,'unlink restores both buttons');
  check(close(rect(tile).height,vertical.height),'unlink preserves vertical footprint');
  check(tile.querySelector('[data-id="line/1"] .olabel').textContent==='Monitors' && tile.querySelector('[data-id="line/2"] .olabel').textContent==='Line Out 2','unlink preserves the two underlying output names');
  // Bus buttons use the same merged footprint and a small chain icon.
  let bus=document.querySelector('.bus-pair-tile');const busBefore=rect(bus);
  bus.querySelector('.bus-pair-link').click();bus=document.querySelector('.bus-pair-tile');
  check(buttonCount(bus)===1 && close(rect(bus).height,busBefore.height),'linked bus spans original rows');
  const master=document.getElementById('master');master.hidden=false;
  document.getElementById('masterbox').hidden=false;
  master.dataset.id='out:line/1';master.dataset.output='line/1';master.dataset.outputPartner='line/2';
  const display=new FFADOPeakDisplay(document,'a');
  function sample(destination,level){return {destination,level,db:20*Math.log10(level)};}
  const meter=master.querySelector('.peak-meter'),left=meter.querySelector('[data-side="left"]'),right=meter.querySelector('[data-side="right"]');
  const bar=left.querySelector('.peak-bar'),hold=left.querySelector('.peak-hold');
  const rightBar=right.querySelector('.peak-bar'),rightHold=right.querySelector('.peak-hold');
  display.render({channels:{},outputs:{'line/1':sample('Line/Out:01',.2),'line/2':sample('Line/Out:02',.8)}},1000);
  check(!meter.hidden && !left.hidden && !right.hidden && meter.classList.contains('stereo-meter'),'master displays both stereo lanes');
  check(bar.style.clipPath==='inset(80% 0px 0px)' && rightBar.style.clipPath==='inset(20% 0px 0px)','Left and Right display independent levels');
  check(rect(left).width>0 && rect(right).width>0 && rect(right).x>rect(left).x,'both lanes are visible in Left/Right order');
  display.render({channels:{},outputs:{'line/1':sample('Line/Out:01',.4),'line/2':sample('Line/Out:02',.1)}},1100);
  check(bar.style.clipPath==='inset(60% 0px 0px)' && hold.style.bottom==='40%' && rightHold.style.bottom==='80%','stereo holds remain independent');
  check(meter.title.includes('FFADO hardware output peak') && !meter.title.includes('Estimated loudest input'),'output tooltip identifies real FFADO peaks');
  check(meter.title.includes('Left · Line/Out:01') && meter.title.includes('Right · Line/Out:02'),'tooltip identifies both sides');
  meter.click();check(hold.style.bottom==='0%' && rightHold.style.bottom==='0%','click clears both output holds');
  delete master.dataset.outputPartner;
  display.render({outputs:{'line/1':sample('Line/Out:01',.2),'line/2':sample('Line/Out:02',.8)}},1150);
  check(right.hidden && !meter.classList.contains('stereo-meter'),'unlink returns to mono metering');
  display.render({channels:{'0':sample('Mixer/In:01',1)},outputs:{}},1200);
  check(meter.hidden,'missing outputs never borrow unrelated input peaks');
  document.body.innerHTML='<pre id="result">OUTPUT_STEREO_BROWSER_PASSED</pre>';
})().catch(error=>{document.body.innerHTML='<pre id="result">FAILED: '+error.stack+'</pre>';});
`;
html = html.replace('</head>', `<style>${style}</style></head>`).replace('</body>', `<script>${script}</script></body>`);
if (process.env.FFADO_OUTPUT_UI_HTML) {
  fs.writeFileSync(process.env.FFADO_OUTPUT_UI_HTML, html);process.exit(0);
}
const temp = fs.mkdtempSync(path.join(os.tmpdir(), 'ffado-output-ui-'));
try {
  const target = path.join(temp, 'index.html');fs.writeFileSync(target, html);
  const result = execFileSync(browser, ['--headless', '--no-sandbox', '--disable-gpu', '--disable-dev-shm-usage',
    '--no-first-run', '--disable-background-networking', '--disable-extensions', '--disable-breakpad',
    '--disable-crash-reporter', '--user-data-dir='+path.join(temp,'profile'),
    '--virtual-time-budget=3000', '--dump-dom', 'file://'+target], {encoding:'utf8',timeout:30000,stdio:['ignore','pipe','pipe']});
  const body = result.slice(result.indexOf('<body'));
  assert(body.includes('<pre id="result">OUTPUT_STEREO_BROWSER_PASSED</pre>'),body.match(/<pre id="result">[\s\S]*?<\/pre>/)?.[0] || body.slice(0,1500));
  console.log('Output browser: linking, horizontal/vertical footprints, bus buttons, hardware meters and holds passed');
} finally { fs.rmSync(temp,{recursive:true,force:true}); }

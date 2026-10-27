const fs=require('node:fs'), vm=require('node:vm'), assert=require('node:assert/strict');
const src=fs.readFileSync(require('node:path').join(__dirname,'../src/ffado_webmixer/assets/static/index.js'),'utf8');
const start=src.indexOf('  if (FEATURES.pan || STEREO_BUSES.includes(currentMix) || stereo) {');
const end=src.indexOf('  // Fader and mute:',start);
assert(start>0 && end>start,'find live pan controls');
const block=src.slice(src.indexOf('  function updatePanAvailability() {'),end);
class Control {constructor(){this.handlers={};this.value='0';this.title='';this.disabled=false;}
 addEventListener(event,fn){(this.handlers[event]??=[]).push(fn);}
 emit(event,e={}){for(const f of this.handlers[event]||[])f(Object.assign({preventDefault(){}, pointerId:8,deltaY:0,shiftKey:false},e));}
 setPointerCapture(){}
}
const sent=[],timers=new Map();let seq=0;
const slider=new Control();
const env=vm.createContext({
 FEATURES:{},STEREO_BUSES:[0],currentMix:0,stripMix:0,stripDevice:'pro40',stereo:true,matrixPairNeedsBus:false,
 panAvailable:true,panEl:slider,panVal:{title:'',textContent:''},data:{},pan:0,
 renderPan(){},
 sendThrottled:(id,control,val)=>sent.push([id,control,val]),id:'ch/01',
 setTimeout:fn=>{const key=++seq;timers.set(key,fn);return key;},
 clearTimeout:key=>timers.delete(key),
 wheelDir:(e)=>Math.sign(-e.deltaY),
});
// renderPan uses an environment-neutral stub: real formatter tested elsewhere.
vm.runInContext(block,env);
slider.emit('pointerdown');
for(const level of ['-40','-20','30','70']) {slider.value=level;slider.emit('input');}
assert.equal(sent.length,0,'drag should preview without slow FFADO writes');
slider.emit('pointerup');
assert.deepEqual(sent[0],['ch/01','pan',.70]);
slider.emit('change');
assert.equal(sent.length,1,'pointerup + change never writes twice');
slider.emit('wheel',{deltaY:-90});slider.emit('wheel',{deltaY:-90});
assert.equal(sent.length,1,'wheel should coalesce');
for(const [key,fn] of [...timers]){timers.delete(key);fn();}
assert.equal(sent.length,2,'wheel commits once');
// No fake native pan writes when DICE bus pair has not been linked.
const disabled=new Control();const noBus=vm.createContext({
 FEATURES:{},STEREO_BUSES:[],currentMix:0,stripMix:0,stripDevice:'pro40',stereo:true,matrixPairNeedsBus:true,
 panAvailable:true,panEl:disabled,panVal:{title:'',textContent:''},data:{},pan:0,
 renderPan(){},sendThrottled(){throw Error('unlinked bus wrote pan');},id:'ch/01',
 setTimeout,clearTimeout,wheelDir:()=>1
});
vm.runInContext(block,noBus);
assert.equal(disabled.disabled,true);
assert.match(disabled.title,/Pan requires stereo output buses/);
console.log('PRO 40 pan interaction: drag commits once, wheel coalesces, unlinked bus guarded');

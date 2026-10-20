// Dependency-free UI regression: adaptive bus-grid columns, stereo-link spans,
// right-sidebar width limits, and small-device max two columns.
const fs = require('fs');
const vm = require('vm');
const assert = require('node:assert/strict');
const path = require('path');
const src = fs.readFileSync(path.join(__dirname, '../ffado_webmixer/assets/static/index.js'), 'utf8');
const layoutSource = src.slice(src.indexOf('// ---- adaptive buses and resizable right bar ----'),
                               src.indexOf('splitter.addEventListener("pointerdown"'));
assert(layoutSource.includes('function layoutBusGrid()'));

function check({busCount, height, viewport, width, stereoLinks, expected, topPadding=28, bottomPadding=12}) {
  const css = new Map();
  const grid = {
    style: {
      getPropertyValue(key) { return css.get(key) || ''; },
      setProperty(key, value) { css.set(key, value); },
      removeProperty(key) { css.delete(key); }
    },
    children: [],
    querySelectorAll() { return Array(busCount).fill({}); }
  };
  if (stereoLinks) {
    for(let i=0;i<busCount;i+=2) grid.children.push({classList:{contains: cls=> cls==='bus-pair-tile'}});
  } else {
    for(let i=0;i<busCount;i++) grid.children.push({classList:{contains:()=>false}});
  }
  grid.querySelector = selector => selector === '.bus-pair-tile' ? (stereoLinks ? grid.children[0] : null) : null;
  grid.getBoundingClientRect = ()=>({height:gridHeight()});
  function gridHeight() {
    const columns = +(css.get('--cols') || 2);
    const itemsPerRow = stereoLinks ? Math.max(1,Math.floor(columns/2)) : columns;
    const rows = (stereoLinks ? 2 : 1) * Math.ceil(grid.children.length/itemsPerRow);
    return 48*rows+8*Math.max(0,rows-1);
  }
  const classes = new Set();
  const sidebody = {clientHeight:height};
  const side = {
    style:{width:width ? width+'px' : ''},
    classList:{contains:cls=>classes.has(cls), remove:cls=>classes.delete(cls), toggle(cls,yes){if(yes) classes.add(cls);else classes.delete(cls);}},
    getBoundingClientRect(){return {width:350};},
    querySelector: selector => selector === '.sidebody' ? sidebody : null
  };
  const box = {hidden:false, get scrollHeight() {return 158+gridHeight();}};
  const document = {querySelector(sel) {
    if (sel==='#outbox .busgrid') return grid;
    if (sel==='.outbtn') return {offsetWidth:68};
    if (sel==='.groupgrid') return {};
    return null;
  },getElementById(id) {
    if(id==='side')return side;
    if(id==='splitter')return {addEventListener(){}};
    if(id==='outbox')return box;
  }};
  const ctx=vm.createContext({document, window:{innerWidth:viewport},getComputedStyle:el => ({columnGap:'8px', gridAutoRows:'48px',rowGap:'8px',paddingTop:el===sidebody?topPadding+'px':'0px',paddingBottom:el===sidebody?bottomPadding+'px':'0px'})});
  vm.runInContext(layoutSource, ctx);
  ctx.layoutBusGrid();
  assert.equal(+css.get('--cols'),expected,`busCount=${busCount}, bodyHeight=${height}, viewport=${viewport}, savedWidth=${width}`);
  return ctx;
}
check({busCount:4,height:700,viewport:1440,stereoLinks:false,expected:2});
check({busCount:8,height:300,viewport:1440,stereoLinks:true,expected:2}); // small mixer is capped
check({busCount:24,height:900,viewport:1440,stereoLinks:true,expected:4});
check({busCount:24,height:654,viewport:1440,stereoLinks:true,expected:6});
check({busCount:24,height:654,viewport:390,stereoLinks:true,expected:2}); // no horizontal overexpansion on phones
check({busCount:24,height:654,viewport:1440,width:502,stereoLinks:true,expected:4}); // respect resized width
check({busCount:24,height:1800,viewport:1440,stereoLinks:true,expected:2}); // enough height for two
// Padding itself consumes the vertical bus-grid budget, rather than letting
// the selector crowd the routing/settings buttons in maximized windows.
check({busCount:24,height:840,viewport:1440,stereoLinks:true,topPadding:0,bottomPadding:0,expected:4});
check({busCount:24,height:840,viewport:1440,stereoLinks:true,topPadding:120,bottomPadding:12,expected:6});
// Phone and tablet keep the gap without forcing additional horizontal columns.
check({busCount:24,height:600,viewport:390,stereoLinks:true,topPadding:20,expected:2});
check({busCount:24,height:600,viewport:768,stereoLinks:true,topPadding:20,expected:2});
const ctx=check({busCount:24,height:654,viewport:1440,stereoLinks:true,expected:6});
assert(ctx.layoutBusGrid.toString().includes('getBoundingClientRect().height')); 
console.log('Adaptive bus-grid UI: 2/4/6 columns, reserved toolbar gap, phones/tablets, widths and height passed');

"""Optional browser pixel regression for full-track peak bands.

Run: python tests/verify_meter_colors_browser.py
Requires Chromium and the Playwright Python package (test-only; not app deps).
"""
from pathlib import Path
import io
from PIL import Image
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[1]
CSS=ROOT/'ffado_webmixer/assets/static/index.css'
ROUTING_CSS=ROOT/'ffado_webmixer/assets/static/routing.css'
levels=(.5,.85,.93,.99)
html='''<!doctype html><html><head><style>
:root {--control-background:#141920;--border-color:#333;}
body {margin:0; background:#15191e; color:white; font-family: sans-serif;}
.grid {display:flex; gap:24px; padding:20px; align-items:flex-start;}
.example {width:86px; display:flex; flex-direction:column; align-items:center; gap:12px;}
.peak-meter {height:240px;width:30px;padding:0;}
.route-peak {width:220px;}
.peak-lane {height:100%;}
</style></head><body><div class="grid" id="targets"></div></body></html>'''

def classify(pixel):
    r,g,b=pixel[:3]
    if g>r*1.15 and g>b*1.15:return 'green'
    if r>140 and g>110 and b<140 and g>r*.60:return 'yellow'
    if r>g*1.05 and r>b*1.45:return 'red'
    return 'background'

with sync_playwright() as p:
    browser=p.chromium.launch(executable_path='/usr/bin/chromium',args=['--no-sandbox'],headless=True)
    page=browser.new_page(viewport={'width':1300,'height':360},device_scale_factor=1)
    page.set_content(html)
    page.add_style_tag(path=str(CSS))
    page.add_style_tag(path=str(ROUTING_CSS))
    page.add_style_tag(content='''.grid .peak-meter { display:flex; position:relative; width:30px; height:240px; padding:0; } .grid .peak-lane {height:100%; display:block; position:relative;} .grid .example {width:125px;} .grid .route-peak {width:115px; height:15px; margin-top:12px;}''')
    page.evaluate('''(levels)=>{
      const root=document.getElementById('targets');
      for (const x of levels) {
        const el=document.createElement('div'); el.className='example';
        el.innerHTML=`<label>${Math.round(x*100)}%</label><div class="peak-meter"><div class="peak-lane"><div class="peak-bar"></div></div></div>`;
        el.querySelector('.peak-bar').style.clipPath=`inset(${(100-x*100).toFixed(2)}% 0 0 0)`;
        root.appendChild(el);
      }
    }''',list(levels))
    shot=page.screenshot()
    im=Image.open(io.BytesIO(shot)).convert('RGB')
    results=[]
    for level, meter in zip(levels,page.locator('.peak-meter').all()):
        rect=meter.bounding_box()
        x=round(rect['x']+rect['width']/2)
        y=round(rect['y']+rect['height']*(1-level+0.004))
        pixel=im.getpixel((x,y))
        category=classify(pixel)
        results.append((level,category,pixel))
    print('Strip meter visual pixel sampling:',results)
    assert [r[1] for r in results]==['green','green','yellow','red'],results
    # Router panel uses a horizontal version of the same absolute scale.
    page.evaluate('''(levels)=>{
      const root=document.getElementById('targets');
      for (const x of levels) {
        const el=document.createElement('div');el.className='example';
        el.innerHTML=`<label>${Math.round(x*100)}%</label><div class="route-peak"><div class="route-peak-fill"></div></div>`;
        el.querySelector('.route-peak-fill').style.clipPath=`inset(0 ${(100-x*100).toFixed(2)}% 0 0)`;
        root.appendChild(el);
      }
    }''',list(levels))
    shot=page.screenshot(full_page=True)
    Path('/mnt/data/meter-color-visual-check.png').write_bytes(shot)
    im=Image.open(io.BytesIO(shot)).convert('RGB')
    router_results=[]
    for level, meter in zip(levels,page.locator('.route-peak').all()):
        rect=meter.bounding_box()
        x=round(rect['x']+rect['width']*(level-0.015))
        y=round(rect['y']+rect['height']/2)
        pixel=im.getpixel((x,y))
        router_results.append((level,classify(pixel),pixel))
    print('Router meter visual pixel sampling:',router_results)
    assert [r[1] for r in router_results]==['green','green','yellow','red'],router_results
    browser.close()
print('Visual browser meter-scale check passed')

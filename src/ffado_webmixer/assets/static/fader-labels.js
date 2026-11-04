/* Give every channel the tallest label's space so all tracks stay aligned. */
(function () {
  'use strict';
  const row = document.getElementById('row');
  const master = document.getElementById('masterbox');
  let pending = false;

  function sizeLabels(container, shared) {
    if (!container || !container.getClientRects().length) return;
    const strips = Array.from(container.querySelectorAll('.strip:not(.minimized)'))
      .filter(strip => strip.getBoundingClientRect().width > 0);
    if (!strips.length) return;
    // Measure copies outside the observed mixer. Their natural height is
    // independent of the shared height from the previous layout pass.
    const measure = document.createElement('div');
    measure.style.cssText = 'position:fixed;left:-10000px;top:0;visibility:hidden;pointer-events:none';
    measure.setAttribute('aria-hidden', 'true');
    document.body.appendChild(measure);
    try {
      for (const selector of ['.name, .mname', '.inname']) {
        const labels = [];
        for (const strip of strips) {
          const label = strip.querySelector(selector);
          if (!label || !label.getClientRects().length) continue;
          const shell = strip.cloneNode(false);
          shell.removeAttribute('id');
          shell.style.cssText = 'width:' + strip.getBoundingClientRect().width + 'px;height:auto';
          const copy = label.cloneNode(true);
          copy.removeAttribute('id');
          copy.style.height = copy.tagName === 'TEXTAREA' ? '0px' : 'auto';
          copy.style.minHeight = '0';
          if (copy.tagName === 'TEXTAREA') copy.value = label.value;
          shell.appendChild(copy);
          measure.appendChild(shell);
          const height = copy.tagName === 'TEXTAREA' ?
            copy.scrollHeight + copy.offsetHeight - copy.clientHeight : copy.getBoundingClientRect().height;
          labels.push({label, height: Math.ceil(height)});
          shell.remove();
        }
        const tallest = Math.max(0, ...labels.map(item => item.height));
        for (const {label, height} of labels) {
          const value = (shared ? tallest : height) + 'px';
          if (label.style.height !== value) label.style.height = value;
        }
      }
    } finally { measure.remove(); }
  }

  function refresh() {
    if (pending) return;
    pending = true;
    requestAnimationFrame(function () {
      pending = false;
      sizeLabels(row, true);
      sizeLabels(master, false);
    });
  }
  window.ffadoRefreshFaderLabels = refresh;
  const observer = new MutationObserver(refresh);
  const resize = new ResizeObserver(refresh);
  for (const container of [row, master]) {
    if (!container) continue;
    observer.observe(container, {subtree:true, childList:true, characterData:true,
      attributes:true, attributeFilter:['class', 'hidden']});
    resize.observe(container);
    for (const event of ['input', 'change', 'blur', 'keydown']) container.addEventListener(event, refresh, true);
  }
  window.addEventListener('resize', refresh);
  if (document.fonts) document.fonts.ready.then(refresh);
  refresh();
})();

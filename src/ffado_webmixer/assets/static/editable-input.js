/* Editing mixer labels and numeric boxes is deliberate: right-click or long-press.
 * Keyboard users can press F2 on a focused field. No hardware write happens here;
 * the existing Enter/change/blur handlers remain the only commit paths.
 */
(function () {
  'use strict';
  const HOLD_MS = 550;
  const MOVE_LIMIT = 11;
  function protect(input) {
    if (!input || input.dataset.gestureProtected === 'true') return input;
    if (input.dataset.gestureEdit === 'direct') return input;
    if (!/^(?:text|number|search|email|url|tel)$/.test(input.type)) return input;
    input.dataset.gestureProtected = 'true';
    input.dataset.gestureEdit = 'locked';
    input.readOnly = true;
    input.classList.add('gesture-edit');
    const oldTitle = input.getAttribute('title') || '';
    input.title = (oldTitle ? oldTitle + ' · ' : '') +
      'Right-click or long-press to edit (F2 with keyboard)';
    let timer = null, startX = 0, startY = 0, heldPointer = null;
    function clearHold() {
      if (timer !== null) clearTimeout(timer);
      timer = null; heldPointer = null;
    }
    function begin() {
      if (input.disabled) return;
      clearHold();
      input.dataset.gestureEdit = 'editing';
      input.readOnly = false;
      input.classList.add('gesture-editing');
      input.focus({preventScroll: true});
      if (typeof input.select === 'function') input.select();
    }
    input.addEventListener('contextmenu', function (e) {
      if (input.disabled) return;
      e.preventDefault(); begin();
    });
    input.addEventListener('pointerdown', function (e) {
      if (input.disabled || (e.pointerType !== 'touch' && e.pointerType !== 'pen')) return;
      clearHold();
      startX = e.clientX; startY = e.clientY; heldPointer = e.pointerId;
      timer = setTimeout(() => {
        timer = null; heldPointer = null;
        begin();
      }, HOLD_MS);
    });
    input.addEventListener('pointermove', function (e) {
      if (heldPointer !== e.pointerId) return;
      if (Math.abs(e.clientX - startX) > MOVE_LIMIT || Math.abs(e.clientY - startY) > MOVE_LIMIT) clearHold();
    });
    input.addEventListener('pointerup', clearHold);
    input.addEventListener('pointercancel', clearHold);
    input.addEventListener('pointerleave', clearHold);
    input.addEventListener('keydown', function (e) {
      if (e.key === 'F2' && !input.disabled) { e.preventDefault(); begin(); }
    });
    input.addEventListener('blur', function () {
      clearHold();
      input.dataset.gestureEdit = 'locked';
      input.readOnly = true;
      input.classList.remove('gesture-editing');
    });
    return input;
  }
  window.ffadoProtectEditable = protect;
  window.ffadoBeginEditing = function (input) {
    protect(input);
    if (!input || input.disabled) return;
    // A menu action deliberately opts into editing, like a context menu.
    input.dispatchEvent(new MouseEvent('contextmenu', {bubbles:true, cancelable:true}));
  };
  document.querySelectorAll('input[type="text"], input[type="number"], input:not([type])').forEach(protect);
})();

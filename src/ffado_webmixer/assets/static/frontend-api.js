/* Shared JSON errors, read cancellation and serialized saves for both mixer panels.
 * Aborting a GET is safe; never abort an in-flight hardware-changing POST. */
(function (root) {
  'use strict';
  const reads = new Map();
  const writes = new Map();
  const cancelled = error => error && error.name === 'AbortError';

  async function parse(response) {
    let data;
    try {
      data = await response.json();
    } catch (_) {
      if (!response.ok) throw new Error('Server returned HTTP ' + response.status);
      throw new Error('Server returned an invalid JSON response');
    }
    if (!response.ok || (data && (data.error || data.ok === false))) {
      throw new Error(data && data.error ? String(data.error) :
        'Server returned HTTP ' + response.status);
    }
    return data;
  }

  function request(url, options = {}) {
    const headers = {};
    if (options.device) headers['X-FFADO-Device'] = options.device;
    if (options.clientId) headers['X-Client-Id'] = options.clientId;
    if (options.body !== undefined) headers['Content-Type'] = 'application/json';
    return fetch(url, {
      method: options.body === undefined ? 'GET' : 'POST',
      cache: 'no-store',
      headers,
      ...(options.signal ? { signal: options.signal } : {}),
      ...(options.body === undefined ? {} : {body: JSON.stringify(options.body)})
    }).then(parse);
  }

  // Only latest reads may update a view. An old request can still finish on
  // the server, so token checks are required in addition to AbortController.
  function latest(key, url, options = {}) {
    cancel(key);
    const controller = typeof AbortController === 'undefined' ? null : new AbortController();
    const state = {controller};
    reads.set(key, state);
    return request(url, {...options, ...(controller ? {signal: controller.signal} : {})})
      .then(data => reads.get(key) === state ? data : null)
      .catch(error => {
        if (reads.get(key) !== state || cancelled(error)) return null;
        throw error;
      })
      .finally(() => { if (reads.get(key) === state) reads.delete(key); });
  }
  function cancel(key) {
    const state = reads.get(key);
    if (!state) return;
    reads.delete(key);
    if (state.controller) state.controller.abort();
  }
  // Serialize writes sharing a logical preference/layout to prevent network
  // reordering. Do not cancel POSTs: the hardware/server may have applied them.
  function serial(key, task) {
    const previous = writes.get(key) || Promise.resolve();
    const current = previous.catch(() => {}).then(task);
    writes.set(key, current);
    current.then(() => { if (writes.get(key) === current) writes.delete(key); },
      () => { if (writes.get(key) === current) writes.delete(key); });
    return current;
  }
  root.ffadoApi = {request, parse, latest, cancel, serial, isAbort: cancelled};
})(window);

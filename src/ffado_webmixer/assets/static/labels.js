/* Presentation-only FFADO label cleanup.
 * Never use these strings as D-Bus names, channel IDs, or router selectors.
 * Unknown/custom labels are returned unchanged, including user-created names.
 */
(function (root) {
  "use strict";
  // Only recognized FFADO identifiers are shortened. Numeric ranges are kept
  // in the order provided by the mixer (stereo Left is not necessarily lower).
  var TYPES = {
    "mixer/in": "In", "mixer/out": "Bus", "anlg/in": "Analog", "anlg/out": "Analog Out",
    "mic/lin/inst": "Analog", "mic/line/inst": "Analog",
    "mic/lin/in": "Analog", "mic/line/in": "Analog",
    "1394/in": "Firewire", "1394/out": "Firewire", "1394": "Firewire",
    "line/out": "Line Out", "line/in": "Line In", "loop": "Loop",
    "adat/in": "ADAT", "adat/out": "ADAT", "spdif/in": "SPDIF", "spdif/out": "SPDIF",
    "aes/in": "AES", "aes/out": "AES Out", "mix": "Bus"
  };
  function parsed(value) {
    var match = /^(Mixer\/In|Mixer\/Out|Anlg\/In|Anlg\/Out|Mic\/Lin\/Inst|Mic\/Line\/Inst|Mic\/Lin\/In|Mic\/Line\/In|1394\/In|1394\/Out|1394|Line\/Out|Line\/In|Loop|ADAT\/In|ADAT\/Out|SPDIF\/In|SPDIF\/Out|AES\/In|AES\/Out|Mix)\s*:?\s*(\d+)((?:\s*\+\s*\d+)*)$/i.exec(value.trim());
    if (!match) return null;
    var label = TYPES[match[1].toLowerCase()];
    if (!label) return null;
    var numbers = [match[2]].concat((match[3].match(/\d+/g) || []));
    return { label: label, numbers: numbers.map(function (n) { return String(Number(n)); }) };
  }
  function shortFfadoLabel(value) {
    if (typeof value !== "string") return value;
    // The server combines same-type channels as "1394/In:01+02" and may
    // combine different types using " + ". Avoid "Firewire 1 + Firewire 2".
    var whole = parsed(value);
    if (whole) return whole.label + " " + whole.numbers.join("+");
    var parts = value.split(/\s+\+\s+/);
    var output = [];
    parts.forEach(function (part) {
      var match = parsed(part);
      if (!match) {
        output.push({ text: part, label: null });
      } else {
        var previous = output[output.length - 1];
        if (previous && previous.label === match.label) {
          previous.numbers.push.apply(previous.numbers, match.numbers);
        } else {
          output.push({ label: match.label, numbers: match.numbers });
        }
      }
    });
    return output.map(function (part) {
      return part.label ? part.label + " " + part.numbers.join("+") : part.text;
    }).join(" + ");
  }
  root.shortFfadoLabel = shortFfadoLabel;
  if (typeof module !== "undefined" && module.exports) module.exports = shortFfadoLabel;
})(typeof window !== "undefined" ? window : globalThis);

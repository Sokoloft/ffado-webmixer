# MOTU Phones destination and General Settings layout

1. **Restart ffado-webmixer after installing the discovery fix** (hardware
   endpoints are inventoried at startup). With an original MOTU UltraLite
   connected and FFADO running, open **In / Out**,
   then **Bus → outputs**. The **Phones destination** dropdown appears above
   the bus routing matrix *only* if FFADO advertises `/Mixer/Control/Phones_src`
   as a `Discrete` control.
2. Confirm the API exposes the independent control before inspecting the page:
   `curl -s http://127.0.0.1:5000/api/bus-routing` should contain a `phones`
   object with `value` and `options` fields. If the `phones` field is absent,
   verify FFADO exports the exact `/Mixer/Control/Phones_src` Discrete control
   and restart the webmixer. The dropdown is rendered from that `phones` field;
   a browser-only refresh cannot repair a stale device inventory.
3. Confirm the displayed value matches the `Phones assign` setting in ffado-mixer.
   Change it (e.g. Phones → MainOut) and confirm both applications read the new
   assignment; change back to your desired routing afterward. **Use low playback
   volume before changing destinations**, as this changes live monitoring routing.
4. Ensure changing Phones assignment does not modify any mix bus destinations
   or matrix levels. An invalid value must be rejected and unsuccessful writes
   must be followed by an accurate hardware readback.
5. Disconnect/remove `/Mixer/Control/Phones_src` from an offline fixture; the
   dropdown must disappear, and a write must be refused. Also verify that
   other FFADO families never show the control automatically.
6. Open Settings → General. The **left column** has Skip loading screen above
   Hide minimized strips; the **right column** has Enable QJackCtl support.
   Each entry has its checkbox centered in the left portion and centered,
   word-wrapped explanatory text in the right portion.
7. Test at desktop/tablet/phone widths (e.g. 1440, 768, 390 px); at narrow
   phone widths, the options should stack without horizontal scrolling. Confirm
   all three checkboxes still save and restore their setting correctly.

Real FireWire hardware verification is still required.

## Regression (2026-10-21)

The initial v1.1.1-dev implementation declared `phones_source_path` in the
model XML but `inventory_profile()` only probed `path` and `extra_paths`.
Thus the selector could never appear on a real discovered device, despite
functioning when unit tests manually injected the control into `device.controls`.
The fix probes the exact model-declared Phones endpoint for mapped pre-mk3 MOTU
profiles and only exposes it if FFADO actually returns a Discrete interface.
The regression suite now tests the real inventory step for multiple MOTU models,
absent endpoints, a wrong interface type, and unrelated FFADO device families.

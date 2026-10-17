# About QR view / v1.0.1 quick test

1. Start `python main.py --demo` in desktop mode, or `python main.py --demo --headless` and open the web page.
2. Verify `python main.py --version` prints `ffado-webmixer 1.0.1` and About shows `Version 1.0.1`.
3. Go to Settings → About. The server URL has two buttons, open-in-browser and QR.
4. Click QR. The settings tabs and About contents are replaced by a QR code with white background/margins and an X in the upper-right corner.
5. Scan the QR with a phone on the same accessible network. Confirm the phone opens the *server URL shown in About*, not 127.0.0.1. TCP port 5000 must be accessible from the phone.
6. Click X. Confirm the **About** tab is still selected. Reopen QR and press Escape; confirm it also returns to About.
7. Confirm About → open-in-browser and the QjackCtl settings preference still work unchanged.

The QR encoder runs entirely in the browser and requires no external requests. On systems where the host LAN address cannot be detected or isn't reachable from the phone, the QR will encode the URL shown in About but remote connectivity may still fail.

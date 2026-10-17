# Testing the QjackCtl and About settings update

This patch applies on top of the MOTU routing release; it does not change device profiles, fader control logic, or the routing dialog.

1. Open **Settings → General**. Confirm **Enable QjackCtl support** is unchecked for a fresh config and that there is no QjackCtl tab.
2. Check the box; **QjackCtl** should appear between General and Theme. Select it and use **Graph** or **Patchbay** when QjackCtl is running. If it is not running, use **Check again** after launching it.
3. Uncheck the option in General. The tab should disappear, and QjackCtl integration requests should be blocked by the server. Reopen the application and confirm the setting persists.
4. Open **Settings → About**. A small external-link button should be next to the Network server URL. From pywebview, it must open the URL with the operating system's default browser. From an ordinary web browser, it opens a new browser tab. The GitHub button should continue working as before.
5. Test enabling and disabling QjackCtl after visiting the tab to verify the hidden panel does not remain visible.

Offline tests: run `PYTHONPATH=. pytest -q`. A running Flask/FFADO system and a real QjackCtl instance are still required to verify desktop end-to-end interactions.

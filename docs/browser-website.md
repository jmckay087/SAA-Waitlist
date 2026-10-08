# Free website with local saving

The browser edition is a static website on **GitHub Pages**, with no hosting
subscription. Open it in **Chrome or Edge on the office Windows computer**:

**https://jmckay087.github.io/SAA-Waitlist/**

Bookmark the address and use the same Windows account and browser profile each
time. You do not need Python, a Terminal window, or a local server. Internet
access is needed to load the website and receive updates; booking changes are
saved on the computer in the browser's IndexedDB storage.

## What gets saved

The dashboard, date navigation, fixed schedule, group sizes, queues, archives,
notes, and exports work in the browser edition. Entries save automatically once
the browser has committed the change. A storage failure reports an error rather
than pretending the booking was saved.

Website updates keep the same storage location and do not reset the data or
reseed an edited schedule. Saved data is specific to the website address and
browser profile. Another computer or profile starts with separate lists. Private
browsing does not provide lasting storage. Clearing this website's browsing data
can remove the lists; keep full backups outside the browser.

The app's code and default schedule are public. Customer names, contact details,
and backups stay local and are not uploaded to GitHub Pages. There is no website
sign-in for this version: anyone using the same browser profile on the office
computer can access its lists. Use your Windows account and screen lock to control
access. The browser edition does not synchronise records between devices.

## Backup and restore

Choose **Backup & restore → Download full backup** regularly, especially before
changing browser profiles, clearing browsing data, or moving computers. Keep the
JSON file in private storage outside the browser, such as a secure USB drive or
your company's backup folder. A full backup includes every saved date, queue,
archive, schedule edit, contact, note, and group size.

On the destination computer, open the website and choose **Backup & restore →
Choose backup file**. Review the booking and flight counts and confirm **Replace
and restore**. This replaces the current browser's complete database. The app
validates the file first and keeps a safety copy of the previous lists; it does
not merge databases. A failed restore leaves the current lists intact.

After a successful restore, the backup dialog offers **Download lists from before
the last restore**. That safety copy covers only the most recent restore and
lives in the same browser, so also keep downloaded backups. **Export day** remains
available as a CSV for reviewing a single day; CSV is not a full restore file.

## Bring over existing Mac bookings

If you have bookings in the Python app, update your Mac copy first using the
README's instructions: keep the old app folder as a backup and copy its entire
`instance` folder into the new app folder before launching.

Open the updated Mac app and choose **Backup → Download full backup**. Move that
JSON file to the Windows computer privately. Open the website there and restore
the file with **Backup & restore → Choose backup file**. Check the dates, group
sizes, queue order, and schedule against your old copy before switching over.
Your Mac records are not moved automatically. Keep the old copy as a backup and
use one version for new bookings once you have switched.

## Updates from this chat

Ask for a change here. The changes can be tested and pushed to the repository's
`main` branch. The **Publish waitlist website** GitHub Actions workflow builds,
tests, and publishes the public assets automatically. Once it succeeds, refresh
the same website address on the office computer. If necessary, press **Ctrl+F5**
to reload the updated files. Your browser database stays in place.

The publishing workflow contains only the app interface and default schedule;
it does not copy `instance`, customer databases, session keys, or backup files.
If an update does not appear, check the workflow's status in the repository's
**Actions** tab. A failed build does not publish that update.

## Initial GitHub Pages setting

If the website has not yet been enabled, open the repository's **Settings → Pages**
and set **Source** to **GitHub Actions**. Run **Publish waitlist website** from the
Actions tab if it did not deploy after enabling Pages. This uses the public
repository's free GitHub Pages hosting.

## Development and checks

The existing Flask app is retained for local use and migrating old data. Build
the static edition separately:

```sh
.venv/bin/python -m pip install -r requirements.txt -r requirements-browser-tests.txt
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python build_static.py
.venv/bin/python -m playwright install chromium
.venv/bin/python tests/browser_local.py --site-dir _site
```

If Chromium is already installed on a cloud development machine, use
`CHROMIUM_EXECUTABLE=/usr/bin/chromium` for the browser test instead of installing
another browser. The test uses disposable profiles and fake customer data. It
covers restarting the browser, local atomic saves, failed saves, queue changes,
backup/restore, migration from SQLite, mobile controls, and absence of customer
network requests.

The generated `_site` directory is ignored by Git and can be served internally
for development with `python -m http.server 3000 --bind 127.0.0.1 --directory _site`.

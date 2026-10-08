# Southern Alps Air flight waitlist

A staff workspace for ordered daily flight waitlists. Select a date and flight, add a name and contact details, and use the arrows to change the call order. There is no capacity tracking, seat allocation, payment, or customer signup page.

## Run

Requires Python 3.12 or newer with the Pacific/Auckland time-zone database.

For a downloaded copy, unzip it, open a terminal in the extracted folder, and run
`python3 launch.py` on Mac/Linux or `py launch.py` on Windows. The launcher installs
dependencies on first use and opens the app in your default browser. Keep the
terminal open while working. Press Ctrl+C to close the app; saved waitlists remain
in the extracted folder's `instance/` directory. This local copy has its own lists;
it does not synchronise with the cloud environment or other computers.

For cloud development or a manual installation:

```sh
cd /workspace/SAA-Waitlist
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/gunicorn --bind 127.0.0.1:3000 --workers 1 --threads 4 'app:create_app()'
```

The app listens locally on port 3000. To run the Flask development server instead, use `.venv/bin/python app.py`.

## Use the waitlist

- Select the operations date. “Today” uses New Zealand time.
- Select a flight and choose **Add passenger**. The name is required; contact and notes are optional.
- Entries start at the bottom. Use **↑ / ↓** to change the order. **Edit** can change contact details or move someone to another flight on the same date.
- **Archive** removes someone from the active queue. The Archived tab lets you restore them to the end of the list.
- **Flight details** changes a single day's flight name or time. **Add a flight** creates an extra departure just for that date.
- **Edit daily schedule** maintains recurring departures. Updates and removals affect days that have not yet been created. Existing daily flights and their waitlists are preserved. New recurring departures also appear when an already-created day is refreshed.
- **Export day** downloads that day's CSV, including archived records. Keep exports private.

The dashboard checks for updates every 30 seconds while visible and while no edit dialog is open. Updates save to SQLite immediately. There is no integration with your booking system, and no automatic email or SMS is sent.

## Flight schedule and branding

The 11 default daily departures in `default_schedule.json` were transcribed from the flight list supplied by the user, dated Friday 9 October 2026. They are used as the recurring schedule; staff can edit them. Multiple departures at 09:00 and 13:30 remain separate flights. Capacity, booking counts, day notes, and staffing details were not imported.

The black, white, and yellow theme follows the supplied Southern Alps Air logo. The displayed logo was reconstructed from the supplied screenshot to remove its hover tooltip; replace `static/images/southern-alps-air-logo.png` with an original logo asset if available. The website was inaccessible through the onboarding network policy, so no website-sourced branding is claimed.

## Data and staff access

Data lives in `instance/waitlist.sqlite3`; this directory is ignored by Git. Back up the database before changing machines. For a consistent backup while the app runs, use Python's SQLite backup API or SQLite's `.backup` command. Do not publish an onboarding snapshot containing actual customer data or distribute the session-key file.

`WAITLIST_DATABASE` selects a different persistent database file. The schedule is seeded once, so restarting does not reset it or overwrite edits. Restarting does not clear waitlists. Dates have separate lists.

Local use is supported without a password. For staff access from other machines, set `STAFF_PASSWORD` securely in the hosting environment and put the application behind HTTPS or a private network. Setting this variable enables the staff login for the dashboard, APIs, exports, and health endpoint. Do not put a password in source control. Set `COOKIE_SECURE=1` when serving through HTTPS.

For a protected deployment, run Gunicorn on your hosting platform's private interface and route requests through its HTTPS reverse proxy. The documented local command does not publish the app. Do not expose a password-free WSGI deployment to the internet. This version has one shared staff password, not individual staff accounts or an audit log.

CSV export is also available locally:

```sh
.venv/bin/flask --app app:create_app export-waitlist /tmp/saa-waitlist.csv --date 2026-10-09
```

The export command refuses to overwrite an existing file. Spreadsheet formula-like values are prefixed with an apostrophe. Archive retains customer information; permanently delete records through an authorised maintenance process when no longer needed.

## Validate

```sh
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m pip check
```

The automated suite covers persistence, day/flight isolation, queue order, archive/restore, moving and editing entries, simultaneous additions, schedule changes, exports, validation, CSRF, and staff authentication. Tests use temporary databases; they do not add customers to the operating database.

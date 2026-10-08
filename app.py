"""Southern Alps Air: an ordered, date-specific waitlist for each flight."""
import csv
import hmac
import io
import json
import os
import re
import secrets
import sqlite3
import threading
import time
from collections import defaultdict, deque
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import click
from flask import Flask, jsonify, redirect, render_template, request, session, url_for, Response

NZ = ZoneInfo('Pacific/Auckland')
ROOT = Path(__file__).parent


class ValidationError(Exception):
    pass


def create_app(test_config=None):
    app = Flask(__name__)
    app.config.from_mapping(
        DATABASE=os.environ.get('WAITLIST_DATABASE', str(ROOT / 'instance' / 'waitlist.sqlite3')),
        STAFF_PASSWORD=os.environ.get('STAFF_PASSWORD', ''), MAX_CONTENT_LENGTH=16384,
        SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Strict',
        SESSION_COOKIE_SECURE=os.environ.get('COOKIE_SECURE') == '1',
        PERMANENT_SESSION_LIFETIME=timedelta(hours=12), SEED_SCHEDULE=True,
    )
    if test_config:
        app.config.update(test_config)
    database = Path(app.config['DATABASE'])
    database.parent.mkdir(parents=True, exist_ok=True)
    if database.parent.name == 'instance':
        database.parent.chmod(0o700)
    secret_file = database.parent / '.session-key'
    if not app.config.get('SECRET_KEY'):
        try:
            with open(secret_file, 'x', encoding='utf-8') as output:
                os.chmod(secret_file, 0o600)
                output.write(secrets.token_hex(32))
        except FileExistsError:
            pass
        app.config['SECRET_KEY'] = secret_file.read_text().strip()
    with sqlite3.connect(database) as connection:
        connection.executescript('''
            PRAGMA foreign_keys = ON;
            CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS schedule (
                id INTEGER PRIMARY KEY, name TEXT NOT NULL, departure TEXT NOT NULL,
                active INTEGER NOT NULL DEFAULT 1
            );
            CREATE TABLE IF NOT EXISTS flights (
                id INTEGER PRIMARY KEY, schedule_id INTEGER REFERENCES schedule(id),
                flight_date TEXT NOT NULL, name TEXT NOT NULL, departure TEXT NOT NULL,
                UNIQUE(schedule_id, flight_date)
            );
            CREATE TABLE IF NOT EXISTS passengers (
                id INTEGER PRIMARY KEY, flight_id INTEGER NOT NULL REFERENCES flights(id),
                name TEXT NOT NULL, contact TEXT NOT NULL DEFAULT '', notes TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'waiting' CHECK(status IN ('waiting','archived')),
                position INTEGER NOT NULL, created_at TEXT NOT NULL,
                party_size INTEGER NOT NULL DEFAULT 1 CHECK(party_size BETWEEN 1 AND 100)
            );
        ''')
        columns = {row[1] for row in connection.execute('PRAGMA table_info(passengers)')}
        if 'party_size' not in columns:
            backup = database.with_name(database.name + '.before-group-size.backup')
            if not backup.exists():
                with sqlite3.connect(backup) as destination:
                    connection.backup(destination)
                backup.chmod(0o600)
        connection.execute('BEGIN IMMEDIATE')
        if 'party_size' not in {row[1] for row in connection.execute('PRAGMA table_info(passengers)')}:
            connection.execute('ALTER TABLE passengers ADD COLUMN party_size INTEGER NOT NULL DEFAULT 1 CHECK(party_size BETWEEN 1 AND 100)')
        if app.config['SEED_SCHEDULE']:
            if not connection.execute("SELECT 1 FROM metadata WHERE key='schedule_seeded'").fetchone():
                defaults = json.loads((ROOT / 'default_schedule.json').read_text())
                connection.executemany('INSERT INTO schedule (name,departure) VALUES (?,?)', [(f['name'],f['departure']) for f in defaults])
                connection.execute("INSERT INTO metadata VALUES ('schedule_seeded','1')")
    database.chmod(0o600)
    attempts = defaultdict(deque)
    lock = threading.Lock()

    def connect():
        connection = sqlite3.connect(database, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute('PRAGMA foreign_keys = ON')
        return connection

    def limited():
        now = time.monotonic()
        with lock:
            for key in list(attempts):
                while attempts[key] and attempts[key][0] < now - 60:
                    attempts[key].popleft()
                if not attempts[key]:
                    del attempts[key]
            queue = attempts[request.remote_addr or 'local']
            if len(queue) >= 5:
                return True
            queue.append(now)
            return False

    @app.before_request
    def protect():
        if request.endpoint in {'static', 'login'}:
            return None
        if app.config['STAFF_PASSWORD'] and not session.get('authenticated'):
            if request.path.startswith('/api/'):
                return jsonify(error='Please sign in again.'), 401
            return redirect(url_for('login'))
        if request.method in {'POST', 'PATCH', 'DELETE'}:
            token = request.headers.get('X-CSRF-Token', '')
            if not token or not hmac.compare_digest(token, session.get('csrf', '')):
                return jsonify(error='Your session expired. Refresh the page and try again.'), 403
            origin = request.headers.get('Origin')
            if origin and origin.rstrip('/') != request.host_url.rstrip('/'):
                return jsonify(error='Please use the staff dashboard to make changes.'), 403
        return None

    @app.after_request
    def headers(response):
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'same-origin'
        response.headers['Content-Security-Policy'] = "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        response.headers['Cache-Control'] = 'no-store'
        return response

    @app.get('/')
    def index():
        session.setdefault('csrf', secrets.token_hex(24))
        return render_template('index.html', csrf=session['csrf'], password_enabled=bool(app.config['STAFF_PASSWORD']))

    @app.route('/login', methods=['GET', 'POST'])
    def login():
        if not app.config['STAFF_PASSWORD']:
            return redirect(url_for('index'))
        session.setdefault('login_csrf', secrets.token_hex(24))
        error = None
        if request.method == 'POST':
            if not hmac.compare_digest(request.form.get('csrf', ''), session['login_csrf']):
                error = 'Refresh this page and try again.'
            elif limited():
                error = 'Too many attempts. Please wait one minute.'
            elif hmac.compare_digest(request.form.get('password', '').encode(), app.config['STAFF_PASSWORD'].encode()):
                session.clear()
                session['authenticated'] = True
                session['csrf'] = secrets.token_hex(24)
                session.permanent = True
                return redirect(url_for('index'))
            else:
                error = 'That password is not correct.'
        return render_template('login.html', csrf=session['login_csrf'], error=error)

    @app.post('/api/logout')
    def logout():
        session.clear()
        return jsonify(ok=True)

    def payload():
        if not request.is_json:
            raise ValidationError('Submit changes through the dashboard.')
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            raise ValidationError('Please check the submitted details.')
        return data

    def text(data, key, minimum=0, maximum=100):
        value = data.get(key, '')
        if not isinstance(value, str):
            raise ValidationError(f'Please check {key.replace("_", " ")}.')
        value = value.strip()
        if not minimum <= len(value) <= maximum or any(ord(char) < 32 and char not in '\n\r\t' for char in value):
            raise ValidationError(f'{key.replace("_", " ").capitalize()} must be {minimum}–{maximum} characters.')
        return value

    def valid_date(value):
        try:
            parsed = date.fromisoformat(value)
            if parsed.isoformat() != value or parsed.year < 2000 or parsed.year > 2100:
                raise ValueError()
            return value
        except (ValueError, TypeError):
            raise ValidationError('Choose a valid date between 2000 and 2100.')

    def flight_values(data):
        name = text(data, 'name', 2, 100)
        departure = text(data, 'departure', 5, 5)
        if not re.fullmatch(r'(?:[01][0-9]|2[0-3]):[0-5][0-9]', departure):
            raise ValidationError('Enter a departure time in 24-hour HH:MM format.')
        return name, departure

    def group_size(data, default=1):
        value = data.get('party_size', default)
        if type(value) is not int or not 1 <= value <= 100:
            raise ValidationError('Number of people must be a whole number between 1 and 100.')
        return value

    def existing_flight(connection, flight_id):
        flight = connection.execute('SELECT * FROM flights WHERE id=?', (flight_id,)).fetchone()
        if not flight:
            raise ValidationError('This flight could not be found. Refresh the dashboard.')
        return flight

    def next_position(connection, flight_id):
        return connection.execute("SELECT COALESCE(MAX(position),0)+1 FROM passengers WHERE flight_id=? AND status='waiting'", (flight_id,)).fetchone()[0]

    def booking_flight(connection, flight_id, data):
        flight = existing_flight(connection, flight_id)
        if 'flight_date' in data and valid_date(data['flight_date']) != flight['flight_date']:
            raise ValidationError('The flight does not match the selected date. Choose the flight again.')
        return flight

    @app.get('/api/day')
    def day():
        selected = valid_date(request.args.get('date', datetime.now(NZ).date().isoformat()))
        with connect() as connection:
            connection.execute('''INSERT OR IGNORE INTO flights (schedule_id,flight_date,name,departure)
                SELECT id, ?, name, departure FROM schedule WHERE active=1''', (selected,))
            flights = [dict(row) for row in connection.execute('SELECT * FROM flights WHERE flight_date=? ORDER BY departure,id', (selected,))]
            for flight in flights:
                flight['passengers'] = [dict(row) for row in connection.execute('SELECT * FROM passengers WHERE flight_id=? ORDER BY position,id', (flight['id'],))]
        return jsonify(date=selected, flights=flights)

    @app.get('/api/week')
    def week():
        start = valid_date(request.args.get('start', datetime.now(NZ).date().isoformat()))
        first = date.fromisoformat(start)
        last = first + timedelta(days=6)
        if last.year > 2100:
            raise ValidationError('Choose a starting date on or before 25 December 2100.')
        days = []
        with connect() as connection:
            # Preview recurring flights without creating future daily snapshots.
            connection.execute('BEGIN')
            schedule = [dict(row) for row in connection.execute('SELECT * FROM schedule WHERE active=1 ORDER BY departure,id')]
            stored = [dict(row) for row in connection.execute('''
                SELECT f.*, COUNT(CASE WHEN p.status='waiting' THEN 1 END) AS booking_count,
                    COALESCE(SUM(CASE WHEN p.status='waiting' THEN p.party_size ELSE 0 END),0) AS people_waiting
                FROM flights f LEFT JOIN passengers p ON p.flight_id=f.id
                WHERE f.flight_date BETWEEN ? AND ? GROUP BY f.id
                ORDER BY f.flight_date,f.departure,f.id''', (start,last.isoformat()))]
            for offset in range(7):
                selected = (first + timedelta(days=offset)).isoformat()
                flights = [f for f in stored if f['flight_date'] == selected]
                existing_templates = {f['schedule_id'] for f in flights}
                for template in schedule:
                    if template['id'] not in existing_templates:
                        flights.append(dict(id=None,schedule_id=template['id'],flight_date=selected,
                                            name=template['name'],departure=template['departure'],
                                            booking_count=0,people_waiting=0))
                flights.sort(key=lambda f: (f['departure'],f['id'] or float('inf'),f['schedule_id'] or 0))
                days.append(dict(date=selected,flights=flights,flight_count=len(flights),
                                 booking_count=sum(f['booking_count'] for f in flights),
                                 people_waiting=sum(f['people_waiting'] for f in flights),
                                 queued_flights=sum(f['booking_count'] > 0 for f in flights)))
        return jsonify(start=start,end=last.isoformat(),days=days,
                       flight_count=sum(d['flight_count'] for d in days),
                       booking_count=sum(d['booking_count'] for d in days),
                       people_waiting=sum(d['people_waiting'] for d in days),
                       queued_flights=sum(d['queued_flights'] for d in days))

    @app.get('/api/schedule')
    def get_schedule():
        with connect() as connection:
            rows = [dict(row) for row in connection.execute('SELECT * FROM schedule WHERE active=1 ORDER BY departure,id')]
        return jsonify(schedule=rows)

    @app.post('/api/schedule')
    def add_schedule():
        values = flight_values(payload())
        with connect() as connection:
            cursor = connection.execute('INSERT INTO schedule (name,departure) VALUES (?,?)', values)
        return jsonify(id=cursor.lastrowid), 201

    @app.patch('/api/schedule/<int:schedule_id>')
    def edit_schedule(schedule_id):
        data = payload()
        with connect() as connection:
            if not connection.execute('SELECT id FROM schedule WHERE id=? AND active=1', (schedule_id,)).fetchone():
                raise ValidationError('This schedule entry no longer exists.')
            if data.get('active') is False:
                connection.execute('UPDATE schedule SET active=0 WHERE id=?', (schedule_id,))
            else:
                values = flight_values(data)
                connection.execute('UPDATE schedule SET name=?,departure=? WHERE id=?', (*values, schedule_id))
        return jsonify(ok=True)

    @app.post('/api/flights')
    def extra_flight():
        data = payload()
        values = flight_values(data)
        selected = valid_date(data.get('date'))
        with connect() as connection:
            cursor = connection.execute('INSERT INTO flights (name,departure,flight_date) VALUES (?,?,?)', (*values, selected))
        return jsonify(id=cursor.lastrowid), 201

    @app.patch('/api/flights/<int:flight_id>')
    def edit_flight(flight_id):
        values = flight_values(payload())
        with connect() as connection:
            existing_flight(connection, flight_id)
            connection.execute('UPDATE flights SET name=?,departure=? WHERE id=?', (*values, flight_id))
        return jsonify(ok=True)

    @app.post('/api/flights/<int:flight_id>/passengers')
    def add_passenger(flight_id):
        data = payload()
        name = text(data, 'name', 2, 100)
        contact = text(data, 'contact', 0, 160)
        notes = text(data, 'notes', 0, 500)
        party = group_size(data)
        with connect() as connection:
            connection.execute('BEGIN IMMEDIATE')
            booking_flight(connection, flight_id, data)
            cursor = connection.execute('''INSERT INTO passengers (flight_id,name,contact,notes,position,created_at,party_size)
                VALUES (?,?,?,?,?,?,?)''', (flight_id,name,contact,notes,next_position(connection,flight_id),datetime.now(NZ).isoformat(),party))
        return jsonify(id=cursor.lastrowid), 201

    @app.patch('/api/passengers/<int:passenger_id>')
    def edit_passenger(passenger_id):
        data = payload()
        with connect() as connection:
            connection.execute('BEGIN IMMEDIATE')
            passenger = connection.execute('SELECT * FROM passengers WHERE id=?', (passenger_id,)).fetchone()
            if not passenger:
                raise ValidationError('This passenger could not be found.')
            if 'direction' in data:
                direction = data['direction']
                if direction not in {'up', 'down'} or passenger['status'] != 'waiting':
                    raise ValidationError('Only waiting passengers can be moved up or down.')
                ordered = list(connection.execute("SELECT id FROM passengers WHERE flight_id=? AND status='waiting' ORDER BY position,id", (passenger['flight_id'],)))
                ids = [row['id'] for row in ordered]
                index = ids.index(passenger_id)
                target = index + (-1 if direction == 'up' else 1)
                if 0 <= target < len(ids):
                    ids[index], ids[target] = ids[target], ids[index]
                connection.executemany('UPDATE passengers SET position=? WHERE id=?', [(n+1,id_) for n,id_ in enumerate(ids)])
                return jsonify(ok=True)
            status = data.get('status', passenger['status'])
            if status not in {'waiting', 'archived'}:
                raise ValidationError('Choose a valid passenger status.')
            name = text(data, 'name', 2, 100) if 'name' in data else passenger['name']
            contact = text(data, 'contact', 0, 160) if 'contact' in data else passenger['contact']
            notes = text(data, 'notes', 0, 500) if 'notes' in data else passenger['notes']
            party = group_size(data, passenger['party_size'])
            flight_id = data.get('flight_id', passenger['flight_id'])
            if type(flight_id) is not int or flight_id < 1:
                raise ValidationError('Choose a valid flight.')
            booking_flight(connection, flight_id, data)
            position = passenger['position']
            if flight_id != passenger['flight_id'] or (status == 'waiting' and passenger['status'] == 'archived'):
                position = next_position(connection, flight_id)
            connection.execute('UPDATE passengers SET name=?,contact=?,notes=?,status=?,flight_id=?,position=?,party_size=? WHERE id=?', (name,contact,notes,status,flight_id,position,party,passenger_id))
            for changed_flight in {flight_id, passenger['flight_id']}:
                ids = [row['id'] for row in connection.execute("SELECT id FROM passengers WHERE flight_id=? AND status='waiting' ORDER BY position,id", (changed_flight,))]
                connection.executemany('UPDATE passengers SET position=? WHERE id=?', [(index+1,id_) for index,id_ in enumerate(ids)])
        return jsonify(ok=True)

    def export_rows(selected=None):
        query = '''SELECT f.flight_date,f.departure,f.name AS flight,p.position,p.name,p.party_size,p.contact,p.notes,p.status,p.created_at
            FROM passengers p JOIN flights f ON f.id=p.flight_id'''
        params = ()
        if selected:
            valid_date(selected)
            query += ' WHERE f.flight_date=?'
            params = (selected,)
        query += ' ORDER BY f.flight_date,f.departure,f.id,p.position,p.id'
        output = io.StringIO(newline='')
        with connect() as connection:
            cursor = connection.execute(query,params)
            writer = csv.writer(output)
            writer.writerow(column[0] for column in cursor.description)
            for row in cursor:
                writer.writerow("'" + value if isinstance(value,str) and value.lstrip().startswith(('=','+','-','@')) else value for value in row)
        return output.getvalue()

    @app.get('/api/export')
    def export_day():
        selected = valid_date(request.args.get('date',datetime.now(NZ).date().isoformat()))
        return Response(export_rows(selected),mimetype='text/csv',headers={'Content-Disposition':f'attachment; filename="saa-waitlist-{selected}.csv"'})

    @app.get('/health')
    def health():
        with connect() as connection:
            connection.execute('SELECT 1 FROM flights LIMIT 1')
        return jsonify(status='ok')

    @app.errorhandler(ValidationError)
    def invalid(error):
        return jsonify(error=str(error)), 400

    @app.errorhandler(413)
    def too_large(_error):
        return jsonify(error='This request is too large.'), 413

    @app.errorhandler(sqlite3.Error)
    def storage_error(_error):
        app.logger.error('Waitlist database operation failed')
        return jsonify(error='The changes could not be saved. Please try again.'), 503

    @app.cli.command('export-waitlist')
    @click.argument('destination',type=click.Path(dir_okay=False))
    @click.option('--date','selected',help='Only export the selected date (YYYY-MM-DD).')
    def export_waitlist(destination,selected):
        """Export waitlists locally; existing files are never overwritten."""
        result = export_rows(selected)
        with open(destination,'x',newline='',encoding='utf-8') as output:
            os.chmod(destination,0o600)
            output.write(result)
        click.echo('Export saved. Keep this file private; it contains customer details.')

    return app


if __name__ == '__main__':
    host = os.environ.get('APP_HOST','127.0.0.1')
    if host not in {'127.0.0.1','localhost','::1'} and not os.environ.get('STAFF_PASSWORD'):
        raise SystemExit('Set STAFF_PASSWORD before allowing access from other machines.')
    create_app().run(host=host,port=int(os.environ.get('PORT','3000')),debug=False)

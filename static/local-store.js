'use strict';
// This adapter runs only in the static website. No booking data is sent to a server.
(() => {
  const FORMAT = 'southern-alps-air-waitlist';
  const VERSION = 1;
  const defaults = JSON.parse(document.querySelector('#default-schedule').textContent);
  let databasePromise;
  let persistenceRequested = false;
  const channel = typeof BroadcastChannel === 'function' ? new BroadcastChannel('saa-waitlist-changes') : null;

  function initialData() {
    return { schema_version: VERSION, schedule: defaults.map((f, i) => ({ id: i + 1, ...f, active: 1 })), flights: [], passengers: [] };
  }
  function openDatabase() {
    if (!databasePromise) databasePromise = new Promise((resolve, reject) => {
      if (!window.indexedDB) { reject(new Error('This browser cannot save waitlists. Open the app in a regular Chrome or Edge window.')); return; }
      const request = indexedDB.open('southern-alps-air-waitlist', VERSION);
      request.onupgradeneeded = () => request.result.createObjectStore('state');
      request.onerror = () => { databasePromise = null; reject(new Error('The browser could not open your saved waitlists. Check that site storage is allowed.')); };
      request.onblocked = () => { databasePromise = null; reject(new Error('Close other waitlist tabs, then refresh to open your saved data.')); };
      request.onsuccess = () => {
        request.result.onversionchange = () => { request.result.close(); databasePromise = null; };
        resolve(request.result);
      };
    });
    return databasePromise;
  }
  async function transaction(mode, action) {
    const database = await openDatabase();
    return new Promise((resolve, reject) => {
      const tx = database.transaction('state', mode);
      const store = tx.objectStore('state');
      const request = store.get('data');
      let result, failure;
      request.onsuccess = () => {
        try {
          const data = request.result === undefined ? initialData() : request.result;
          if (data.schema_version !== VERSION) throw new Error('These waitlists need a newer app version. Refresh the website; your data has been kept.');
          result = action(data, store);
          if (mode === 'readwrite') store.put(data, 'data');
        } catch (error) { failure = error; tx.abort(); }
      };
      tx.oncomplete = () => resolve(result);
      tx.onabort = () => reject((failure?.name === 'QuotaExceededError' || tx.error?.name === 'QuotaExceededError') ? new Error('The browser has no room to save this change. Download a backup and free some space, then try again.') : failure || new Error('Your change could not be saved in this browser. Please try again.'));
      tx.onerror = () => {};
    });
  }
  function integer(value, label, min = 1, max = Number.MAX_SAFE_INTEGER) {
    if (!Number.isSafeInteger(value) || value < min || value > max) throw new Error(`${label} must be a whole number between ${min} and ${max}.`);
    return value;
  }
  function text(value, label, min, max) {
    if (typeof value !== 'string' || value.trim().length < min || value.trim().length > max || /[\x00-\x08\x0b\x0c\x0e-\x1f]/.test(value)) throw new Error(`${label} must be ${min}–${max} characters.`);
    return value.trim();
  }
  function validDate(value) {
    if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(value) || value < '2000-01-01' || value > '2100-12-31' || new Date(value + 'T12:00:00Z').toISOString().slice(0, 10) !== value) throw new Error('Choose a valid date between 2000 and 2100.');
    return value;
  }
  function addDays(value, amount) { const day = new Date(value + 'T12:00:00Z'); day.setUTCDate(day.getUTCDate() + amount); return day.toISOString().slice(0, 10); }
  function values(data) {
    const name = text(data.name, 'Flight name', 2, 100);
    if (typeof data.departure !== 'string' || !/^(?:[01]\d|2[0-3]):[0-5]\d$/.test(data.departure)) throw new Error('Enter a valid departure time.');
    return { name, departure: data.departure };
  }
  function nextId(rows) { return integer(rows.reduce((max, row) => Math.max(max, row.id), 0) + 1, 'New entry ID'); }
  function order(a, b) { return a.departure.localeCompare(b.departure) || (a.id ?? Infinity) - (b.id ?? Infinity) || (a.schedule_id ?? 0) - (b.schedule_id ?? 0); }
  function queue(data, flightId) { return data.passengers.filter(p => p.flight_id === flightId && p.status === 'waiting').sort((a, b) => a.position - b.position || a.id - b.id); }
  function renumber(data, flightId) { queue(data, flightId).forEach((p, i) => { p.position = i + 1; }); }
  function nextPosition(data, flightId) { return queue(data, flightId).reduce((max, p) => Math.max(max, p.position), 0) + 1; }
  function flightFor(data, id, payload = {}) {
    integer(id, 'Flight');
    const flight = data.flights.find(f => f.id === id);
    if (!flight) throw new Error('This flight could not be found. Refresh the dashboard.');
    if ('flight_date' in payload && validDate(payload.flight_date) !== flight.flight_date) throw new Error('The flight does not match the selected date. Choose the flight again.');
    return flight;
  }
  function day(data, selected) {
    validDate(selected);
    for (const template of data.schedule.filter(f => f.active)) {
      if (!data.flights.some(f => f.flight_date === selected && f.schedule_id === template.id)) data.flights.push({ id: nextId(data.flights), schedule_id: template.id, flight_date: selected, name: template.name, departure: template.departure });
    }
    return { date: selected, flights: data.flights.filter(f => f.flight_date === selected).sort(order).map(f => ({ ...f, passengers: data.passengers.filter(p => p.flight_id === f.id).sort((a, b) => a.position - b.position || a.id - b.id) })) };
  }
  function week(data, start) {
    validDate(start);
    if (start > '2100-12-25') throw new Error('Choose a starting date on or before 25 December 2100.');
    const days = [];
    for (let i = 0; i < 7; i++) {
      const selected = addDays(start, i);
      const flights = data.flights.filter(f => f.flight_date === selected).map(f => ({ ...f }));
      for (const template of data.schedule.filter(f => f.active)) if (!flights.some(f => f.schedule_id === template.id)) flights.push({ id: null, schedule_id: template.id, flight_date: selected, name: template.name, departure: template.departure });
      for (const flight of flights) {
        const waiting = flight.id === null ? [] : queue(data, flight.id);
        flight.booking_count = waiting.length; flight.people_waiting = waiting.reduce((n, p) => n + p.party_size, 0);
      }
      days.push({ date: selected, flights: flights.sort(order), flight_count: flights.length, booking_count: flights.reduce((n, f) => n + f.booking_count, 0), people_waiting: flights.reduce((n, f) => n + f.people_waiting, 0), queued_flights: flights.filter(f => f.booking_count).length });
    }
    const result = { start, end: addDays(start, 6), days };
    for (const key of ['flight_count', 'booking_count', 'people_waiting', 'queued_flights']) result[key] = days.reduce((n, d) => n + d[key], 0);
    return result;
  }
  function route(data, path, method, payload) {
    const url = new URL(path, location.href);
    const pathname = url.pathname;
    if (method === 'GET' && pathname === '/api/day') return day(data, url.searchParams.get('date'));
    if (method === 'GET' && pathname === '/api/week') return week(data, url.searchParams.get('start'));
    if (pathname === '/api/schedule') {
      if (method === 'GET') return { schedule: data.schedule.filter(f => f.active).sort(order) };
      if (method === 'POST') { const entry = { id: nextId(data.schedule), ...values(payload), active: 1 }; data.schedule.push(entry); return { id: entry.id }; }
    }
    let match = pathname.match(/^\/api\/schedule\/(\d+)$/);
    if (match && method === 'PATCH') {
      const template = data.schedule.find(f => f.id === Number(match[1]) && f.active);
      if (!template) throw new Error('This schedule entry no longer exists.');
      if (payload.active === false) template.active = 0;
      else Object.assign(template, values(payload));
      return { ok: true };
    }
    if (pathname === '/api/flights' && method === 'POST') {
      const flight = { id: nextId(data.flights), schedule_id: null, flight_date: validDate(payload.date), ...values(payload) };
      data.flights.push(flight); return { id: flight.id };
    }
    match = pathname.match(/^\/api\/flights\/(\d+)$/);
    if (match && method === 'PATCH') { Object.assign(flightFor(data, Number(match[1])), values(payload)); return { ok: true }; }
    match = pathname.match(/^\/api\/flights\/(\d+)\/passengers$/);
    if (match && method === 'POST') {
      const flight = flightFor(data, Number(match[1]), payload);
      const passenger = { id: nextId(data.passengers), flight_id: flight.id, name: text(payload.name, 'Name', 2, 100), contact: text(payload.contact ?? '', 'Contact', 0, 160), notes: text(payload.notes ?? '', 'Notes', 0, 500), party_size: integer(payload.party_size ?? 1, 'Number of people', 1, 100), status: 'waiting', position: nextPosition(data, flight.id), created_at: new Date().toISOString() };
      data.passengers.push(passenger); return { id: passenger.id };
    }
    match = pathname.match(/^\/api\/passengers\/(\d+)$/);
    if (match && method === 'PATCH') {
      const passenger = data.passengers.find(p => p.id === Number(match[1]));
      if (!passenger) throw new Error('This booking could not be found.');
      if ('direction' in payload) {
        if (!['up', 'down'].includes(payload.direction) || passenger.status !== 'waiting') throw new Error('Only waiting bookings can be moved up or down.');
        const ordered = queue(data, passenger.flight_id); const i = ordered.findIndex(p => p.id === passenger.id); const target = i + (payload.direction === 'up' ? -1 : 1);
        if (target >= 0 && target < ordered.length) [ordered[i], ordered[target]] = [ordered[target], ordered[i]];
        ordered.forEach((p, index) => { p.position = index + 1; }); return { ok: true };
      }
      const status = payload.status ?? passenger.status;
      if (!['waiting', 'archived'].includes(status)) throw new Error('Choose a valid booking status.');
      const updated = { ...passenger, status };
      if ('name' in payload) updated.name = text(payload.name, 'Name', 2, 100);
      if ('contact' in payload) updated.contact = text(payload.contact, 'Contact', 0, 160);
      if ('notes' in payload) updated.notes = text(payload.notes, 'Notes', 0, 500);
      if ('party_size' in payload) updated.party_size = integer(payload.party_size, 'Number of people', 1, 100);
      const destination = flightFor(data, payload.flight_id ?? passenger.flight_id, payload);
      if (destination.id !== passenger.flight_id || (passenger.status === 'archived' && status === 'waiting')) updated.position = nextPosition(data, destination.id);
      const previousFlight = passenger.flight_id;
      Object.assign(passenger, updated, { flight_id: destination.id }); renumber(data, previousFlight); renumber(data, destination.id);
      return { ok: true };
    }
    throw new Error('This action is not available in the browser app. Refresh the website and try again.');
  }
  async function request(path, method = 'GET', payload = {}) {
    const write = method !== 'GET' || path.startsWith('/api/day?');
    const result = await transaction(write ? 'readwrite' : 'readonly', data => route(data, path, method, payload));
    if (method !== 'GET') {
      channel?.postMessage({ type: 'changed' });
      if (!persistenceRequested && navigator.storage?.persist) { persistenceRequested = true; navigator.storage.persist().catch(() => {}); }
    }
    return result;
  }
  function wrap(data) { return { format: FORMAT, version: VERSION, exported_at: new Date().toISOString(), data }; }
  function validateBackup(backup) {
    if (!backup || backup.format !== FORMAT || backup.version !== VERSION || backup.data?.schema_version !== VERSION) throw new Error('Choose a Southern Alps Air full backup file for this app version.');
    const source = backup.data;
    for (const key of ['schedule', 'flights', 'passengers']) if (!Array.isArray(source[key]) || source[key].length > 100000) throw new Error('This backup has an invalid or oversized data list.');
    const unique = (rows, label) => { const ids = new Set(); for (const row of rows) { integer(row?.id, `${label} ID`); if (ids.has(row.id)) throw new Error(`This backup contains duplicate ${label} IDs.`); ids.add(row.id); } return ids; };
    const scheduleIds = unique(source.schedule, 'schedule'); const flightIds = unique(source.flights, 'flight'); unique(source.passengers, 'booking');
    const schedule = source.schedule.map(f => {
      if (![0, 1, false, true].includes(f.active)) throw new Error('This backup has an invalid schedule status.');
      return { id: f.id, ...values(f), active: f.active ? 1 : 0 };
    });
    const templates = new Set();
    const flights = source.flights.map(f => {
      if (f.schedule_id !== null && !scheduleIds.has(f.schedule_id)) throw new Error('A flight in this backup has no matching schedule.');
      const selected = validDate(f.flight_date);
      if (f.schedule_id !== null) {
        const key = `${f.schedule_id}:${selected}`;
        if (templates.has(key)) throw new Error('This backup contains duplicate daily departures.');
        templates.add(key);
      }
      return { id: f.id, schedule_id: f.schedule_id, flight_date: selected, ...values(f) };
    });
    const positions = new Set();
    const passengers = source.passengers.map(p => {
      if (!flightIds.has(p.flight_id) || !['waiting', 'archived'].includes(p.status)) throw new Error('A booking in this backup has an invalid flight or status.');
      integer(p.position, 'Queue position');
      if (p.status === 'waiting') {
        const key = `${p.flight_id}:${p.position}`;
        if (positions.has(key)) throw new Error('This backup contains duplicate queue positions.');
        positions.add(key);
      }
      if (typeof p.created_at !== 'string' || p.created_at.length > 50 || !Number.isFinite(Date.parse(p.created_at))) throw new Error('A booking in this backup has an invalid added date.');
      return { id: p.id, flight_id: p.flight_id, name: text(p.name, 'Name', 2, 100), contact: text(p.contact, 'Contact', 0, 160), notes: text(p.notes, 'Notes', 0, 500), party_size: integer(p.party_size, 'Number of people', 1, 100), status: p.status, position: p.position, created_at: p.created_at };
    });
    return { schema_version: VERSION, schedule, flights, passengers };
  }
  async function prepareRestore(file) {
    if (file.size > 20 * 1024 * 1024) throw new Error('Choose a backup smaller than 20 MB.');
    let backup;
    try { backup = JSON.parse(await file.text()); } catch { throw new Error('This file is not a readable JSON backup.'); }
    return validateBackup(backup);
  }
  async function restore(prepared) {
    // Validate again at the write boundary; keep the previous data in the same
    // atomic transaction so a failed restore never leaves half a database.
    const replacement = validateBackup(wrap(prepared));
    await transaction('readwrite', (data, store) => { store.put(data, 'before-restore'); Object.assign(data, replacement); });
    channel?.postMessage({ type: 'restored' });
  }
  async function previousBackup() {
    const database = await openDatabase();
    return new Promise((resolve, reject) => {
      const tx = database.transaction('state', 'readonly'); const request = tx.objectStore('state').get('before-restore');
      let result; request.onsuccess = () => { result = request.result ? wrap(request.result) : null; };
      tx.oncomplete = () => resolve(result); tx.onabort = () => reject(new Error('The safety backup could not be opened.'));
    });
  }
  async function exportCSV(selected) {
    validDate(selected);
    const rows = await transaction('readonly', data => data.flights.filter(f => f.flight_date === selected).sort(order).flatMap(f => data.passengers.filter(p => p.flight_id === f.id).sort((a, b) => a.position - b.position || a.id - b.id).map(p => [f.flight_date, f.departure, f.name, p.position, p.name, p.party_size, p.contact, p.notes, p.status, p.created_at])));
    const escape = value => { let text = String(value); if (typeof value === 'string' && /^[\s]*[=+\-@]/.test(text)) text = "'" + text; return '"' + text.replaceAll('"', '""') + '"'; };
    return [['flight_date', 'departure', 'flight', 'position', 'name', 'party_size', 'contact', 'notes', 'status', 'created_at'], ...rows].map(row => row.map(escape).join(',')).join('\r\n');
  }
  window.localWaitlist = { request, prepareRestore, restore, previousBackup, exportCSV,
    backup: () => transaction('readonly', data => wrap(data)),
    subscribe: callback => { if (channel) channel.onmessage = event => callback(event.data.type); },
  };
})();

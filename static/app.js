'use strict';
const $ = selector => document.querySelector(selector);
const csrf = $('meta[name="csrf-token"]').content;
const state = { flights: [], selected: null, filter: 'waiting', date: nzDate(), search: '', load: 0,
  view: 'dashboard', weekStart: nzDate(), week: null, weekLoad: 0 };
let toastTimer;
let confirmation;

function nzDate() {
  const parts = new Intl.DateTimeFormat('en-NZ', { timeZone: 'Pacific/Auckland', year: 'numeric', month: '2-digit', day: '2-digit' }).formatToParts(new Date());
  const part = type => parts.find(p => p.type === type).value;
  return `${part('year')}-${part('month')}-${part('day')}`;
}
function dateLabel(value) {
  return new Intl.DateTimeFormat('en-NZ', { timeZone: 'Pacific/Auckland', weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' }).format(new Date(value + 'T12:00:00+12:00'));
}
function timeLabel(value) { const [hours, minutes] = value.split(':').map(Number); return { time: `${hours % 12 || 12}:${String(minutes).padStart(2, '0')}`, period: hours < 12 ? 'AM' : 'PM' }; }
function addDays(value, amount) { const day = new Date(value + 'T12:00:00Z'); day.setUTCDate(day.getUTCDate() + amount); return day.toISOString().slice(0,10); }
function shortDate(value, options = { weekday: 'short', day: 'numeric', month: 'short' }) { return new Intl.DateTimeFormat('en-NZ', { ...options, timeZone: 'Pacific/Auckland' }).format(new Date(value + 'T12:00:00+12:00')); }
function node(tag, className, content) { const el = document.createElement(tag); if (className) el.className = className; if (content !== undefined) el.textContent = content; return el; }
function button(label, className, action, title) { const el = node('button', className, label); el.type = 'button'; if (title) { el.title = title; el.setAttribute('aria-label', title); } el.addEventListener('click', () => { const result = action(); if (result?.catch) result.catch(setError); }); return el; }
function toast(message) { $('#toast').textContent = message; $('#toast').hidden = false; clearTimeout(toastTimer); toastTimer = setTimeout(() => { $('#toast').hidden = true; }, 3500); }
function selectedFlight() { return state.flights.find(f => f.id === state.selected); }
function waiting(flight) { return flight.passengers.filter(p => p.status === 'waiting'); }
function people(flight) { return waiting(flight).reduce((count, p) => count + p.party_size, 0); }
function setError(error) { $('#app-error').textContent = error.message || String(error); $('#app-error').hidden = false; }
async function api(path, method = 'GET', data) {
  const options = { method, headers: { 'X-CSRF-Token': csrf } };
  if (data) { options.headers['Content-Type'] = 'application/json'; options.body = JSON.stringify(data); }
  let response;
  try { response = await fetch(path, options); } catch { throw new Error('Could not reach the app. Check your connection and try again.'); }
  if (response.status === 401) { window.location.assign('/login'); throw new Error('Please sign in again.'); }
  let result;
  try { result = await response.json(); } catch { throw new Error('The server could not be reached. Please try again.'); }
  if (!response.ok) throw new Error(result.error || 'Your changes could not be saved.');
  return result;
}
async function loadDay() {
  const load = ++state.load;
  $('#daily-section').inert = true; $('#waitlist-panel').inert = true;
  const selectedDate = state.date;
  $('#day-picker').value = selectedDate;
  $('#date-display').textContent = new Intl.DateTimeFormat('en-NZ', { weekday: 'short', day: 'numeric', month: 'short', year: 'numeric', timeZone: 'Pacific/Auckland' }).format(new Date(selectedDate + 'T12:00:00+12:00'));
  $('#day-label').textContent = dateLabel(selectedDate);
  $('#export-day').href = `/api/export?date=${selectedDate}`;
  try {
    const data = await api(`/api/day?date=${selectedDate}`);
    if (load !== state.load) return;
    state.flights = data.flights;
    if (!state.flights.some(f => f.id === state.selected)) state.selected = state.flights[0]?.id ?? null;
    $('#app-error').hidden = true;
    render();
  } catch (error) { if (load === state.load) { state.flights = []; state.selected = null; render(); setError(error); } }
  finally { if (load === state.load) { $('#daily-section').inert = false; $('#waitlist-panel').inert = false; } }
}
function setView(view) {
  state.load++; state.weekLoad++;
  $('#daily-section').inert = false; $('#waitlist-panel').inert = false; $('#dashboard-section').inert = false;
  state.view = view;
  $('#dashboard-section').hidden = view !== 'dashboard';
  $('#daily-section').hidden = view !== 'daily';
  $('#waitlist-panel').hidden = view !== 'daily' || !selectedFlight();
  $('#dashboard-nav').classList.toggle('active', view === 'dashboard');
  $('#operations-nav').classList.toggle('active', view === 'daily');
  $('#dashboard-nav').setAttribute('aria-current', view === 'dashboard' ? 'page' : 'false');
  $('#operations-nav').setAttribute('aria-current', view === 'daily' ? 'page' : 'false');
  $('#page-title').replaceChildren(node('span', 'title-text', view === 'dashboard' ? 'Operations dashboard' : 'Flight waitlist'), node('span', '', '.'));
  $('#breadcrumb-view').textContent = view === 'dashboard' ? 'DASHBOARD' : 'WAITLIST';
  $('#page-eyebrow').textContent = view === 'dashboard' ? 'A CLEAR VIEW OF THE WEEK AHEAD' : 'A CLEAR VIEW OF YOUR DAY';
  $('#page-description').textContent = view === 'dashboard' ? 'The week ahead. Every flight, every waitlist, and everyone waiting.' : 'An ordered waitlist for every flight. Names, contact details, and group sizes.';
  $('#previous-day').setAttribute('aria-label', view === 'dashboard' ? 'Previous seven days' : 'Previous day');
  $('#next-day').setAttribute('aria-label', view === 'dashboard' ? 'Next seven days' : 'Next day');
  $('#day-picker').setAttribute('aria-label', view === 'dashboard' ? 'First day of outlook' : 'Operations date');
  $('#day-picker').max = view === 'dashboard' ? '2100-12-25' : '2100-12-31';
  if (view === 'dashboard') renderWeek(); else render();
}
async function loadWeek() {
  const load = ++state.weekLoad;
  $('#dashboard-section').inert = true;
  $('#day-picker').value = state.weekStart;
  $('#date-display').textContent = `${shortDate(state.weekStart, { day: 'numeric', month: 'short' })} – ${shortDate(addDays(state.weekStart,6), { day: 'numeric', month: 'short', year: 'numeric' })}`;
  try {
    const data = await api(`/api/week?start=${state.weekStart}`);
    if (load !== state.weekLoad) return;
    state.week = data;
    $('#app-error').hidden = true;
    if (state.view === 'dashboard') renderWeek();
  } catch (error) { if (load === state.weekLoad) { state.week = null; if (state.view === 'dashboard') renderWeek(); setError(error); } }
  finally { if (load === state.weekLoad) $('#dashboard-section').inert = false; }
}
function loadCurrent() { return state.view === 'dashboard' ? loadWeek() : loadDay(); }
async function openDaily(date = state.date, flight = null) {
  state.date = date; state.filter = 'waiting'; state.search = ''; $('#passenger-search').value = '';
  setView('daily');
  await loadDay();
  if (flight && state.date === date) {
    const selected = state.flights.find(f => flight.id ? f.id === flight.id : f.schedule_id === flight.schedule_id);
    if (selected) { state.selected = selected.id; render(); }
    $('#waitlist-panel').scrollIntoView({ block: 'start', behavior: 'instant' });
  }
}
function renderWeek() {
  const week = state.week;
  $('#flight-count').textContent = week?.flight_count ?? '—';
  $('#waiting-count').textContent = week?.people_waiting ?? '—';
  $('#queued-flight-count').textContent = week?.queued_flights ?? '—';
  $('#booking-count').textContent = week?.booking_count ?? '—';
  $('#flight-description').textContent = 'Scheduled across the next seven days';
  $('#waiting-description').textContent = 'People across all seven days';
  const cards = $('#week-days'); const head = $('#outlook-head'); const body = $('#outlook-body'); const followups = $('#followup-list');
  cards.replaceChildren(); head.replaceChildren(); body.replaceChildren(); followups.replaceChildren();
  if (!week) { $('#week-range').textContent = 'Loading the week ahead…'; return; }
  $('#week-range').textContent = `${dateLabel(week.start)} – ${shortDate(week.end, { day: 'numeric', month: 'long', year: 'numeric' })}`;
  for (const day of week.days) {
    const card = button('', 'week-day' + (day.date === nzDate() ? ' is-today' : ''), () => openDaily(day.date), `Open waitlists for ${dateLabel(day.date)}`);
    card.append(node('span', 'week-day-name', day.date === nzDate() ? 'TODAY' : shortDate(day.date, { weekday: 'short' }).toUpperCase()), node('span', 'week-day-date', shortDate(day.date, { day: 'numeric', month: 'short' })));
    const number = node('strong', 'week-day-people', day.people_waiting); number.append(node('small', '', day.people_waiting === 1 ? 'person waiting' : 'people waiting')); card.append(number);
    const meter = node('meter', 'week-meter'); meter.min = 0; meter.max = Math.max(1,...week.days.map(d => d.people_waiting)); meter.value = day.people_waiting; meter.setAttribute('aria-label', `${day.people_waiting} people waiting`); card.append(meter);
    card.append(node('span', 'week-day-meta', `${day.booking_count} ${day.booking_count === 1 ? 'booking' : 'bookings'} · ${day.flight_count} flights`));
    cards.append(card);
  }
  const heading = node('tr'); heading.append(node('th', '', 'FLIGHT / DEPARTURE'));
  for (const day of week.days) heading.append(node('th', '', shortDate(day.date, { weekday: 'short', day: 'numeric' })));
  heading.append(node('th', '', 'TOTAL')); for (const th of heading.children) th.scope = 'col'; head.append(heading);
  const routes = new Map();
  for (const day of week.days) for (const flight of day.flights) {
    const key = `${flight.schedule_id ?? 'extra:' + flight.id}\u001f${flight.departure}\u001f${flight.name}`;
    if (!routes.has(key)) routes.set(key, { name: flight.name, departure: flight.departure, days: new Map() });
    const route = routes.get(key);
    if (!route.days.has(day.date)) route.days.set(day.date, []);
    route.days.get(day.date).push(flight);
  }
  for (const route of [...routes.values()].sort((a,b) => a.departure.localeCompare(b.departure) || a.name.localeCompare(b.name))) {
    const row = node('tr'); const label = node('th', 'outlook-route'); label.scope = 'row'; const time = timeLabel(route.departure);
    label.append(node('strong', '', route.name), node('small', '', `${time.time} ${time.period}`)); row.append(label);
    let total = 0;
    for (const day of week.days) {
      const cell = node('td'); const flights = route.days.get(day.date);
      if (flights) {
        const count = flights.reduce((n,f) => n + f.people_waiting,0); const bookings = flights.reduce((n,f) => n + f.booking_count,0); total += count;
        const target = flights.length === 1 ? flights[0] : null;
        const cellButton = button('', 'week-cell' + (count ? ' populated' : ''), () => openDaily(day.date,target), `${route.name}, ${time.time} ${time.period}, ${dateLabel(day.date)}: ${count} people, ${bookings} waitlist bookings`);
        cellButton.append(node('strong', '', count)); if (bookings) cellButton.append(node('small', '', `${bookings} ${bookings === 1 ? 'booking' : 'bookings'}`)); cell.append(cellButton);
      } else cell.append(node('span', 'not-scheduled', '—'));
      row.append(cell);
    }
    row.append(node('td', 'outlook-total', total)); body.append(row);
  }
  if (!routes.size) { const row = node('tr'); const cell = node('td', 'no-outlook', 'No flights scheduled. Set up your daily schedule to see the outlook.'); cell.colSpan = 9; row.append(cell); body.append(row); }
  const active = week.days.flatMap(day => day.flights.filter(f => f.booking_count).map(f => ({ ...f, date: day.date })));
  for (const flight of active.slice(0,6)) {
    const time = timeLabel(flight.departure); const card = button('', 'followup-card', () => openDaily(flight.date,flight)); const content = node('span');
    content.append(node('small', '', `${shortDate(flight.date)} · ${time.time} ${time.period}`), node('strong', '', flight.name), node('span', '', `${flight.people_waiting} ${flight.people_waiting === 1 ? 'person' : 'people'} · ${flight.booking_count} ${flight.booking_count === 1 ? 'booking' : 'bookings'}`));
    card.append(content,node('span', 'followup-arrow', '↗')); followups.append(card);
  }
  if (!active.length) followups.append(node('p', 'followup-empty', 'No bookings waiting in this seven-day period. Add a booking from any daily waitlist to see it here.'));
}
function render() {
  if (state.view !== 'daily') return;
  $('#flight-count').textContent = state.flights.length;
  $('#waiting-count').textContent = state.flights.reduce((count, flight) => count + people(flight), 0);
  $('#booking-count').textContent = state.flights.reduce((count, flight) => count + waiting(flight).length, 0);
  $('#queued-flight-count').textContent = state.flights.filter(f => waiting(f).length).length;
  $('#flight-description').textContent = `${state.flights.length} departures · ${state.date === nzDate() ? 'today' : 'selected day'}`;
  const totalLists = state.flights.filter(f => waiting(f).length).length;
  $('#waiting-description').textContent = `Across ${totalLists} ${totalLists === 1 ? 'flight waitlist' : 'flight waitlists'}`;
  const list = $('#flight-list'); list.replaceChildren();
  if (!state.flights.length) {
    const empty = node('div', 'no-flights'); empty.append(node('h3', '', 'No flights on the schedule yet.'), node('p', '', 'Set up your daily departures, or add a flight just for this day.'), button('Set up the schedule ↗', 'primary-button', openSchedule)); list.append(empty);
  }
  for (const flight of state.flights) {
    const card = button('', 'flight-card' + (flight.id === state.selected ? ' selected' : ''), () => { state.selected = flight.id; state.filter = 'waiting'; state.search = ''; $('#passenger-search').value = ''; render(); if (window.innerWidth <= 600) $('#waitlist-panel').scrollIntoView({ block: 'start', behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth' }); });
    card.setAttribute('aria-pressed', String(flight.id === state.selected));
    const time = timeLabel(flight.departure); const clock = node('span', 'flight-time', time.time); clock.append(node('small', '', time.period));
    const info = node('span', 'flight-info'); const count = people(flight); const bookings = waiting(flight).length;
    info.append(node('strong', '', flight.name), node('small', '', count ? `${count} ${count === 1 ? 'person' : 'people'} · ${bookings} ${bookings === 1 ? 'booking' : 'bookings'}` : 'No one waiting'));
    card.append(clock, info, node('span', 'flight-count' + (count ? ' has-waitlist' : ''), count)); list.append(card);
  }
  renderPassengers();
}
function renderPassengers() {
  const flight = selectedFlight(); $('#waitlist-panel').hidden = state.view !== 'daily' || !flight;
  if (!flight) return;
  const time = timeLabel(flight.departure);
  $('#selected-flight-label').textContent = `${time.time} ${time.period}  /  ${flight.name}`;
  for (const filter of ['waiting', 'archived']) $(`#${filter}-tab-count`).textContent = flight.passengers.filter(p => p.status === filter).length;
  document.querySelectorAll('.list-tab').forEach(tab => { tab.classList.toggle('active', tab.dataset.filter === state.filter); tab.setAttribute('aria-pressed', String(tab.dataset.filter === state.filter)); });
  const all = flight.passengers.filter(p => p.status === state.filter);
  const filtered = all.filter(p => `${p.name} ${p.contact} ${p.notes}`.toLowerCase().includes(state.search));
  const rows = $('#passenger-rows'); rows.replaceChildren();
  for (const passenger of filtered) {
    const index = all.findIndex(p => p.id === passenger.id);
    const row = node('tr'); row.dataset.id = passenger.id;
    row.append(node('td', '', state.filter === 'waiting' ? String(index + 1).padStart(2, '0') : '—'));
    const nameCell = node('td'); const guest = node('div', 'guest');
    const initials = passenger.name.split(/\s+/).slice(0, 2).map(name => name[0]).join('').toUpperCase();
    guest.append(node('span', 'guest-avatar', initials), node('span', 'guest-name', passenger.name)); nameCell.append(guest); row.append(nameCell);
    row.append(node('td', 'party-size-cell', `${passenger.party_size} ${passenger.party_size === 1 ? 'person' : 'people'}`));
    const contactCell = node('td', 'contact-cell', passenger.contact || 'No contact added');
    if (passenger.notes) contactCell.append(node('div', 'passenger-note', passenger.notes)); row.append(contactCell);
    const added = new Intl.DateTimeFormat('en-NZ', { timeZone: 'Pacific/Auckland', hour: 'numeric', minute: '2-digit' }).format(new Date(passenger.created_at));
    row.append(node('td', 'added-time', added));
    const actionCell = node('td'); const actions = node('div', 'row-actions');
    if (state.filter === 'waiting') {
      const up = button('↑', 'icon-button', () => mutatePassenger(passenger.id, { direction: 'up' }, 'Order updated'), `Move ${passenger.name} up`); up.disabled = index === 0;
      const down = button('↓', 'icon-button', () => mutatePassenger(passenger.id, { direction: 'down' }, 'Order updated'), `Move ${passenger.name} down`); down.disabled = index === all.length - 1;
      actions.append(up, down);
    }
    actions.append(button('Edit', 'edit-button', () => openPassenger(passenger)));
    if (state.filter === 'waiting') actions.append(button('×', 'icon-button archive-button', () => confirm(`Archive ${passenger.name}’s booking?`, 'They will be removed from the active queue. You can restore them from the Archived tab.', () => mutatePassenger(passenger.id, { status: 'archived' }, 'Booking archived'), 'Archive booking'), `Archive ${passenger.name}`));
    else actions.append(button('Restore', 'edit-button', () => mutatePassenger(passenger.id, { status: 'waiting' }, 'Booking restored to the end of the waitlist')));
    actionCell.append(actions); row.append(actionCell); rows.append(row);
  }
  const empty = $('#passenger-empty'); empty.hidden = filtered.length > 0; empty.replaceChildren();
  if (!filtered.length) {
    empty.append(node('span', 'empty-icon', state.search ? '⌕' : '↗'));
    empty.append(node('h3', '', state.search ? 'No matching bookings.' : state.filter === 'archived' ? 'No archived bookings.' : 'A clear list. A fresh start.'));
    empty.append(node('p', '', state.search ? 'Try a different name or contact detail.' : state.filter === 'archived' ? 'Bookings you archive from this flight appear here.' : 'Add a lead guest, group size, and contact details. New bookings are added in order.'));
    if (!state.search && state.filter === 'waiting') empty.append(button('+ Add the first booking', 'text-button', () => openPassenger()));
  }
  $('#queue-note').textContent = state.filter === 'waiting' ? `${waiting(flight).length} bookings · ${people(flight)} people · first booking at the top` : 'Restore a booking to add it to the end of the queue';
}
async function mutatePassenger(id, data, message) {
  try { await api(`/api/passengers/${id}`, 'PATCH', data); await loadDay(); toast(message); }
  catch (error) { setError(error); throw error; }
}
function openDialog(id) { const dialog = $(id); dialog.querySelectorAll('.dialog-error').forEach(el => { el.textContent = ''; }); dialog.showModal(); }
function openPassenger(passenger) {
  const form = $('#passenger-form'); form.reset(); form.elements.namedItem('id').value = passenger?.id || '';
  form.elements.name.value = passenger?.name || ''; form.contact.value = passenger?.contact || ''; form.notes.value = passenger?.notes || '';
  form.party_size.value = passenger?.party_size || 1;
  const select = form.flight_id; select.replaceChildren();
  for (const flight of state.flights) { const time = timeLabel(flight.departure); const option = node('option', '', `${time.time} ${time.period} · ${flight.name}`); option.value = flight.id; select.append(option); }
  select.value = passenger?.flight_id || state.selected;
  $('#passenger-dialog-title').textContent = passenger ? 'Edit booking' : 'Add a booking'; openDialog('#passenger-dialog'); form.elements.name.focus();
}
function openFlight(extra = false) {
  const form = $('#flight-form'); form.reset(); const flight = extra ? null : selectedFlight();
  form.elements.namedItem('id').value = flight?.id || ''; form.elements.name.value = flight?.name || ''; form.departure.value = flight?.departure || '';
  $('#flight-dialog-title').textContent = extra ? 'Add a flight for this day' : 'Flight details';
  $('#flight-help').textContent = extra ? `This flight will be added only to ${dateLabel(state.date)}. For a recurring departure, use the daily schedule.` : 'Updating a flight affects this date only. Its passenger list will be kept.';
  openDialog('#flight-dialog');
}
async function renderSchedule() {
  const data = await api('/api/schedule'); const list = $('#schedule-list'); list.replaceChildren();
  if (!data.schedule.length) list.append(node('p', 'form-help', 'No recurring departures. Add your first flight below.'));
  for (const flight of data.schedule) {
    const row = node('div', 'schedule-entry'); const actions = node('div');
    row.append(node('strong', '', flight.departure), node('span', '', flight.name));
    actions.append(button('Edit', 'subtle-button', () => { const form = $('#schedule-form'); form.elements.namedItem('id').value = flight.id; form.elements.name.value = flight.name; form.departure.value = flight.departure; $('#save-schedule').textContent = 'Save departure ↗'; form.elements.name.focus(); }));
    actions.append(button('×', 'icon-button remove-schedule', () => confirm('Remove this daily departure?', `${flight.departure} · ${flight.name}. Existing daily flights and their waitlists will be kept. This departure will stop appearing on new days.`, async () => { await api(`/api/schedule/${flight.id}`, 'PATCH', { active: false }); await renderSchedule(); await loadCurrent(); toast('Daily departure removed'); }, 'Remove departure'), `Remove ${flight.name} at ${flight.departure}`));
    row.append(actions); list.append(row);
  }
}
async function openSchedule() { $('#schedule-form').reset(); $('#schedule-form').elements.namedItem('id').value = ''; $('#save-schedule').textContent = 'Add departure +'; openDialog('#schedule-dialog'); try { await renderSchedule(); } catch (error) { $('#schedule-dialog .dialog-error').textContent = error.message; } }
function confirm(title, message, action, label = 'Confirm') { confirmation = action; $('#confirm-title').textContent = title; $('#confirm-message').textContent = message; $('#confirm-action').textContent = label; openDialog('#confirm-dialog'); }
$('#confirm-action').addEventListener('click', async () => { const button = $('#confirm-action'); button.disabled = true; try { await confirmation(); $('#confirm-dialog').close(); } catch (error) { $('#confirm-dialog .dialog-error').textContent = error.message; } finally { button.disabled = false; } });
function bindForm(id, action) {
  const form = $(id);
  form.addEventListener('submit', async event => {
    event.preventDefault(); const submit = form.querySelector('[type="submit"]'); if (submit.disabled) return; submit.disabled = true;
    const error = form.querySelector('.dialog-error'); error.textContent = '';
    try { await action(form); } catch (exception) { error.textContent = exception.message; } finally { submit.disabled = false; }
  });
}
bindForm('#passenger-form', async form => {
  const data = { name: form.elements.name.value.trim(), contact: form.contact.value.trim(), notes: form.notes.value.trim(), flight_id: Number(form.flight_id.value), party_size: Number(form.party_size.value) };
  const id = form.elements.namedItem('id').value;
  await api(id ? `/api/passengers/${id}` : `/api/flights/${data.flight_id}/passengers`, id ? 'PATCH' : 'POST', data);
  state.selected = data.flight_id; state.filter = 'waiting'; state.search = ''; $('#passenger-search').value = ''; $('#passenger-dialog').close(); await loadDay(); toast(id ? 'Booking updated' : 'Booking added to the waitlist');
});
bindForm('#flight-form', async form => {
  const data = { name: form.elements.name.value.trim(), departure: form.departure.value, date: state.date }; const id = form.elements.namedItem('id').value;
  const result = await api(id ? `/api/flights/${id}` : '/api/flights', id ? 'PATCH' : 'POST', data);
  if (result.id) state.selected = result.id; $('#flight-dialog').close(); await loadDay(); toast('Flight saved');
});
bindForm('#schedule-form', async form => {
  const data = { name: form.elements.name.value.trim(), departure: form.departure.value }; const id = form.elements.namedItem('id').value;
  await api(id ? `/api/schedule/${id}` : '/api/schedule', id ? 'PATCH' : 'POST', data);
  form.reset(); form.elements.namedItem('id').value = ''; $('#save-schedule').textContent = 'Add departure +'; await renderSchedule(); await loadCurrent(); toast('Daily schedule saved');
});
document.querySelectorAll('[data-close]').forEach(button => button.addEventListener('click', () => button.closest('dialog').close()));
$('#reset-schedule').addEventListener('click', () => { $('#schedule-form').reset(); $('#schedule-form').elements.namedItem('id').value = ''; $('#save-schedule').textContent = 'Add departure +'; });
$('#add-passenger').addEventListener('click', () => openPassenger()); $('#flight-details').addEventListener('click', () => openFlight()); $('#add-extra').addEventListener('click', () => openFlight(true));
$('#schedule-nav').addEventListener('click', openSchedule); $('#manage-schedule').addEventListener('click', openSchedule);
$('#dashboard-nav').addEventListener('click', () => { if (state.view === 'daily' && (state.date < state.weekStart || state.date > addDays(state.weekStart,6))) state.weekStart = state.date > '2100-12-25' ? '2100-12-25' : state.date; setView('dashboard'); loadWeek(); $('#main').focus(); });
$('#operations-nav').addEventListener('click', () => openDaily(state.date >= state.weekStart && state.date <= addDays(state.weekStart,6) ? state.date : state.weekStart));
$('#open-selected-day').addEventListener('click', () => openDaily(state.weekStart));
document.querySelectorAll('.list-tab').forEach(tab => tab.addEventListener('click', () => { state.filter = tab.dataset.filter; renderPassengers(); }));
$('#passenger-search').addEventListener('input', event => { state.search = event.target.value.trim().toLowerCase(); renderPassengers(); });
$('#day-picker').addEventListener('change', event => { if (event.target.value && event.target.validity.valid) {
  if (state.view === 'dashboard') { state.weekStart = event.target.value; loadWeek(); }
  else { state.date = event.target.value; state.filter = 'waiting'; state.search = ''; $('#passenger-search').value = ''; loadDay(); }
} });
$('#day-picker').min = '2000-01-01'; $('#day-picker').max = '2100-12-31';
function shiftDay(amount) { const next = addDays(state.view === 'dashboard' ? state.weekStart : state.date, amount * (state.view === 'dashboard' ? 7 : 1)); if (next < '2000-01-01' || next > (state.view === 'dashboard' ? '2100-12-25' : '2100-12-31')) return;
  if (state.view === 'dashboard') { state.weekStart = next; loadWeek(); }
  else { state.date = next; state.filter = 'waiting'; state.search = ''; $('#passenger-search').value = ''; loadDay(); }
}
$('#previous-day').addEventListener('click', () => shiftDay(-1)); $('#next-day').addEventListener('click', () => shiftDay(1)); $('#today').addEventListener('click', () => { state.date = nzDate(); state.weekStart = nzDate(); state.filter = 'waiting'; state.search = ''; $('#passenger-search').value = ''; loadCurrent(); });
$('#refresh').addEventListener('click', loadCurrent);
$('#logout')?.addEventListener('click', async () => { try { await api('/api/logout','POST',{}); window.location.assign('/login'); } catch (error) { setError(error); } });
function updateClock() { $('#nz-clock').textContent = new Intl.DateTimeFormat('en-NZ', { timeZone: 'Pacific/Auckland', hour: 'numeric', minute: '2-digit', timeZoneName: 'short' }).format(new Date()).toUpperCase(); }
updateClock(); setInterval(updateClock, 30000);
setInterval(() => { if (!document.hidden && !document.querySelector('dialog[open]')) loadCurrent(); }, 30000);
setView('dashboard'); loadWeek();

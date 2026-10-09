"""Exercise the Pages app in a real browser against a disposable local profile."""
import argparse
import functools
import http.server
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import threading

from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app import create_app


def run(site):
    with tempfile.TemporaryDirectory() as temporary:
        temporary = Path(temporary)
        public = temporary / 'public'
        shutil.copytree(site, public / 'SAA-Waitlist')
        class QuietHandler(http.server.SimpleHTTPRequestHandler):
            def log_message(self, *_args):
                pass
        handler = functools.partial(QuietHandler, directory=str(public))
        server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        address = f'http://127.0.0.1:{server.server_port}/SAA-Waitlist/'
        try:
            with sync_playwright() as p:
                options = {'headless': True, 'args': ['--no-sandbox']}
                if os.environ.get('CHROMIUM_EXECUTABLE'):
                    options['executable_path'] = os.environ['CHROMIUM_EXECUTABLE']
                profile = temporary / 'profile'
                context = p.chromium.launch_persistent_context(str(profile), **options)
                errors = []
                requests = []
                def attach(page):
                    page.on('pageerror', lambda error: errors.append(str(error)))
                    page.on('request', lambda request: requests.append((request.method, request.url)))
                page = context.new_page(); attach(page); page.goto(address)
                expect(page.locator('#quick-add-booking')).to_be_enabled()
                expect(page.locator('#waiting-count')).to_have_text('0')
                empty = page.evaluate('window.localWaitlist.backup()')
                assert empty['data']['flights'] == [], 'Dashboard materialized future dates'
                assert len(empty['data']['schedule']) == 11
                # All guest operations use the existing UI, backed by local storage.
                page.locator('#quick-add-booking').click()
                form = page.locator('#passenger-form')
                select = form.locator('[name=flight_id]')
                expect(select).to_be_enabled()
                page.locator('#booking-tomorrow').click()
                expect(select).to_be_enabled()
                selected_date = form.locator('[name=flight_date]').input_value()
                flights = page.evaluate('(date)=>window.localWaitlist.request("/api/day?date="+date)', selected_date)['flights']
                target = next(f for f in flights if f['departure'] == '09:00' and f['name'].startswith('Milford Sound Fly Cruise'))
                select.select_option(str(target['id']))
                form.locator('[name=name]').fill('Browser Guest Māori')
                form.locator('[name=party_size]').fill('4')
                form.locator('[name=contact]').fill('guest@example.test')
                form.locator('[name=notes]').fill('Keep this note')
                form.locator('[type=submit]').click()
                expect(page.locator('#passenger-dialog')).not_to_be_visible()
                expect(page.locator('#passenger-rows')).to_contain_text('Browser Guest Māori')
                first = page.evaluate('window.localWaitlist.backup()')['data']['passengers'][0]
                assert (first['party_size'], first['flight_id']) == (4, target['id'])
                # Closing and restarting the browser preserves data on disk.
                context.close()
                context = p.chromium.launch_persistent_context(str(profile), **options)
                page = context.new_page(); attach(page); page.goto(address)
                expect(page.locator('#waiting-count')).to_have_text('4')
                assert page.evaluate('window.localWaitlist.backup()')['data']['passengers'][0] == first
                # Parallel writes in two tabs append with distinct IDs and positions.
                second_page = context.new_page(); attach(second_page); second_page.goto(address)
                expect(second_page.locator('#quick-add-booking')).to_be_enabled()
                script = '(flight)=>window.localWaitlist.request(`/api/flights/${flight}/passengers`,"POST",{name:"Parallel Guest",party_size:2})'
                page.evaluate('(flight)=>{window.pendingAdd=window.localWaitlist.request(`/api/flights/${flight}/passengers`,"POST",{name:"Parallel Guest",party_size:2});}', target['id'])
                second_page.evaluate(script, target['id'])
                page.evaluate('window.pendingAdd')
                backup = page.evaluate('window.localWaitlist.backup()')
                people = backup['data']['passengers']
                assert len({p['id'] for p in people}) == 3
                assert sorted(p['position'] for p in people) == [1,2,3]
                second_page.close()
                # Invalid input and failed commits leave the saved data unchanged.
                before = page.evaluate('window.localWaitlist.backup()')['data']
                result = page.evaluate('''async flight => {
                    try { await window.localWaitlist.request(`/api/flights/${flight}/passengers`, 'POST', {name:'Invalid Guest', party_size:0}); return false; }
                    catch { return true; }
                }''', target['id'])
                assert result
                assert page.evaluate('window.localWaitlist.backup()')['data'] == before
                result = page.evaluate('''async flight => {
                    const original = IDBObjectStore.prototype.put;
                    IDBObjectStore.prototype.put = function(value,key) { if (key==='data') throw new DOMException('Simulated full disk', 'QuotaExceededError'); return original.call(this,value,key); };
                    try { await window.localWaitlist.request(`/api/flights/${flight}/passengers`, 'POST', {name:'Unsaved Guest'}); return false; }
                    catch { return true; } finally { IDBObjectStore.prototype.put=original; }
                }''', target['id'])
                assert result
                assert page.evaluate('window.localWaitlist.backup()')['data'] == before
                # Archive, restore, reorder, and move to another date preserve details.
                second = people[1]['id']
                third = people[2]['id']
                page.evaluate('(id)=>window.localWaitlist.request(`/api/passengers/${id}`,"PATCH",{status:"archived"})', second)
                page.evaluate('(id)=>window.localWaitlist.request(`/api/passengers/${id}`,"PATCH",{status:"waiting"})', second)
                page.evaluate('(id)=>window.localWaitlist.request(`/api/passengers/${id}`,"PATCH",{direction:"up"})', second)
                ordered = page.evaluate('(date)=>window.localWaitlist.request("/api/day?date="+date)', selected_date)['flights']
                queue = next(f for f in ordered if f['id']==target['id'])['passengers']
                assert [p['id'] for p in queue] == [first['id'], second, third]
                other = page.evaluate('window.localWaitlist.request("/api/day?date=2028-02-29")')['flights'][0]
                page.evaluate('(data)=>window.localWaitlist.request(`/api/passengers/${data.id}`,"PATCH",{flight_id:data.flight,flight_date:"2028-02-29"})', {'id':first['id'],'flight':other['id']})
                moved = page.evaluate('window.localWaitlist.request("/api/day?date=2028-02-29")')['flights'][0]['passengers'][0]
                assert (moved['id'], moved['party_size'], moved['notes'])==(first['id'],4,'Keep this note')
                # Schedule edits do not rewrite saved daily snapshots or week previews.
                template = other['schedule_id']
                page.evaluate('(id)=>window.localWaitlist.request(`/api/schedule/${id}`,"PATCH",{name:"Updated Route",departure:"07:45"})', template)
                before_preview = page.evaluate('window.localWaitlist.backup()')['data']['flights']
                week = page.evaluate('window.localWaitlist.request("/api/week?start=2028-03-01")')
                assert week['days'][0]['flights'][0]['name']=='Updated Route'
                assert page.evaluate('window.localWaitlist.backup()')['data']['flights']==before_preview
                assert page.evaluate('window.localWaitlist.request("/api/day?date=2028-02-29")')['flights'][0]['name']=='Siberia Experience'
                # Download a full backup from the UI, then restore after a new booking.
                page.locator('#backup-shortcut').click()
                with page.expect_download() as download_info:
                    page.locator('#download-backup').click()
                download = download_info.value
                path = temporary / 'backup.json'; download.save_as(path)
                full = json.loads(path.read_text())
                assert full['format']=='southern-alps-air-waitlist' and len(full['data']['passengers'])==3
                page.evaluate('(flight)=>window.localWaitlist.request(`/api/flights/${flight}/passengers`,"POST",{name:"After Backup Guest"})', target['id'])
                page.locator('#restore-file').set_input_files(path)
                expect(page.locator('#confirm-dialog')).to_be_visible()
                page.locator('#confirm-dialog .secondary-button').click()
                assert len(page.evaluate('window.localWaitlist.backup()')['data']['passengers'])==4
                page.locator('#backup-shortcut').click()
                page.locator('#restore-file').set_input_files(path)
                page.locator('#confirm-action').click()
                expect(page.locator('#confirm-dialog')).not_to_be_visible()
                assert page.evaluate('window.localWaitlist.backup()')['data']==full['data']
                assert len(page.evaluate('window.localWaitlist.previousBackup()')['data']['passengers'])==4
                # Reject corrupt backups before modifying data or the safety copy.
                bad = json.loads(path.read_text()); bad['data']['passengers'][0]['party_size']=0
                bad_path=temporary/'bad.json';bad_path.write_text(json.dumps(bad))
                page.locator('#backup-shortcut').click()
                page.locator('#restore-file').set_input_files(bad_path)
                expect(page.locator('#data-dialog .dialog-error')).not_to_be_empty()
                assert page.evaluate('window.localWaitlist.backup()')['data']==full['data']
                assert len(page.evaluate('window.localWaitlist.previousBackup()')['data']['passengers'])==4
                # The old Python app exports exactly the format the browser accepts.
                page.locator('#data-dialog [aria-label=Close]').click()
                page.locator('#quick-add-booking').click()
                expect(page.locator('#passenger-form [name=flight_id]')).to_be_enabled()
                page.locator('#passenger-form [name=name]').fill('Stale Form Guest')
                restore_tab=context.new_page();restore_tab.goto(address)
                expect(restore_tab.locator('#quick-add-booking')).to_be_enabled()
                restore_tab.evaluate('(data)=>window.localWaitlist.restore(data)', full['data'])
                expect(page.locator('#toast')).to_contain_text('another tab')
                page.locator('#passenger-form [type=submit]').click()
                expect(page.locator('#passenger-form .dialog-error')).to_contain_text('another tab')
                assert page.evaluate('window.localWaitlist.backup()')['data']==full['data']
                page.locator('#passenger-dialog [aria-label=Close]').click()
                restore_tab.close()
                page.locator('#backup-shortcut').click()
                app=create_app({'TESTING':True,'SECRET_KEY':'test-only','DATABASE':str(temporary/'migration.sqlite3'),'STAFF_PASSWORD':''})
                client=app.test_client()
                with client.session_transaction() as session:session['csrf']='test-token'
                headers={'X-CSRF-Token':'test-token'}
                migration_flights=client.get('/api/day?date=2026-10-09').get_json()['flights']
                response=client.post(f"/api/flights/{migration_flights[0]['id']}/passengers",json={'name':'Migrated Guest','party_size':5,'contact':'migrated@example.test','notes':'From the Mac'},headers=headers)
                assert response.status_code==201
                archived=client.post(f"/api/flights/{migration_flights[0]['id']}/passengers",json={'name':'Archived Migrated Guest'},headers=headers).get_json()['id']
                client.patch(f'/api/passengers/{archived}',json={'status':'archived'},headers=headers)
                client.patch(f"/api/schedule/{migration_flights[0]['schedule_id']}",json={'active':False},headers=headers)
                migration=client.get('/api/backup').get_json()
                migration_path=temporary/'migration.json';migration_path.write_text(json.dumps(migration))
                page.locator('#restore-file').set_input_files(migration_path)
                page.locator('#confirm-action').click()
                expect(page.locator('#confirm-dialog')).not_to_be_visible()
                assert page.evaluate('window.localWaitlist.backup()')['data']==migration['data']
                next_day=page.evaluate('window.localWaitlist.request("/api/day?date=2026-10-10")')
                assert len(next_day['flights'])==10
                # CSV stays local, preserves archives, and protects formula-like values.
                page.evaluate('(id)=>window.localWaitlist.request(`/api/passengers/${id}`,"PATCH",{contact:"+6421000000",name:"=Formula Guest"})', response.get_json()['id'])
                csv=page.evaluate('window.localWaitlist.exportCSV("2026-10-09")')
                assert "'=Formula Guest" in csv and "'+6421000000" in csv and 'Archived Migrated Guest' in csv
                # Mobile controls remain inside the viewport and can add a booking.
                page.locator('#quick-add-booking').click()
                page.set_viewport_size({'width':390,'height':844})
                expect(page.locator('#passenger-form [name=flight_id]')).to_be_enabled()
                assert page.locator('#passenger-dialog').evaluate('(d)=>d.scrollWidth<=d.clientWidth')
                page.locator('#passenger-form [name=name]').fill('Mobile Guest')
                page.locator('#passenger-form [type=submit]').click()
                expect(page.locator('#passenger-dialog')).not_to_be_visible()
                # A different browser profile sees no customer data.
                other_context=p.chromium.launch_persistent_context(str(temporary/'other-profile'),**options)
                blank=other_context.new_page();blank.goto(address)
                expect(blank.locator('#waiting-count')).to_have_text('0')
                assert blank.evaluate('window.localWaitlist.backup()')['data']['passengers']==[]
                other_context.close()
                # Blocked browser storage is reported rather than claiming a save.
                unavailable=p.chromium.launch_persistent_context(str(temporary/'blocked-profile'),**options)
                unavailable.add_init_script("Object.defineProperty(window,'indexedDB',{value:undefined})")
                blocked=unavailable.new_page();blocked.goto(address)
                expect(blocked.locator('#app-error')).to_contain_text('cannot save waitlists')
                unavailable.close()
                assert not errors, errors
                assert all(method=='GET' and url.startswith(address) and '/api/' not in url for method,url in requests), requests
                context.close()
                print('PASS: real-browser local persistence across restart; date/group entry; two-tab atomic writes; validation and failed commits; queue operations; schedule snapshots; backup/restore/cancel/safety copy; Mac migration; CSV; mobile; isolated profiles; blocked storage; no customer network requests.')
        finally:
            server.shutdown();server.server_close()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--site-dir',type=Path,required=True)
    args=parser.parse_args()
    run(args.site_dir.resolve())

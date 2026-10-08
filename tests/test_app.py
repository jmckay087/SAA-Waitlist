import csv
import io
import re
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from app import create_app


class WaitlistTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.database = str(Path(self.temp.name) / 'test.sqlite3')
        self.config = {'TESTING':True,'SECRET_KEY':'test-secret-only','DATABASE':self.database,'STAFF_PASSWORD':''}
        self.app = create_app(self.config)
        self.client = self.app.test_client()
        with self.client.session_transaction() as session:
            session['csrf'] = 'test-token'
        self.headers = {'X-CSRF-Token':'test-token'}
        self.flights = self.day()['flights']
        self.flight = self.flights[0]['id']

    def tearDown(self):
        self.temp.cleanup()

    def day(self, selected='2026-10-09'):
        return self.client.get('/api/day?date='+selected).get_json()

    def add(self,name='Test Guest',contact='021 000 0000',flight=None):
        response = self.client.post(f'/api/flights/{flight or self.flight}/passengers',json={'name':name,'contact':contact,'notes':''},headers=self.headers)
        self.assertEqual(response.status_code,201,response.get_json())
        return response.get_json()['id']

    def update(self,id_,data):
        return self.client.patch(f'/api/passengers/{id_}',json=data,headers=self.headers)

    def queue(self,flight=None):
        row = next(f for f in self.day()['flights'] if f['id'] == (flight or self.flight))
        return [p for p in row['passengers'] if p['status']=='waiting']

    def test_photo_schedule_and_repeatability(self):
        self.assertEqual(len(self.flights),11)
        self.assertEqual([(f['departure'],f['name']) for f in self.flights if f['departure']=='13:30'],[
            ('13:30','Milford Sound Flight + Landing'),('13:30','Milford Sound Flyover'),
            ('13:30','Mt Aspiring & Glaciers'),('13:30','Mt Cook & Glaciers')])
        self.assertEqual([f['id'] for f in self.day()['flights']],[f['id'] for f in self.flights])
        create_app(self.config)
        self.assertEqual(len(self.client.get('/api/schedule').get_json()['schedule']),11)

    def test_entries_persist_across_app_restart(self):
        id_=self.add('Hana Māori','hana@example.test')
        second = create_app(self.config).test_client()
        row=second.get('/api/day?date=2026-10-09').get_json()['flights'][0]['passengers'][0]
        self.assertEqual((row['id'],row['name'],row['contact']),(id_,'Hana Māori','hana@example.test'))

    def test_fifo_and_move_up_down_boundaries(self):
        ids=[self.add(name) for name in ['Guest One','Guest Two','Guest Three']]
        self.assertEqual([p['id'] for p in self.queue()],ids)
        self.assertEqual(self.update(ids[2],{'direction':'up'}).status_code,200)
        self.assertEqual([p['id'] for p in self.queue()],[ids[0],ids[2],ids[1]])
        self.update(ids[0],{'direction':'up'})
        self.update(ids[0],{'direction':'down'})
        self.assertEqual([p['id'] for p in self.queue()],[ids[2],ids[0],ids[1]])

    def test_archive_and_restore_at_bottom(self):
        first=self.add('First Person'); second=self.add('Second Person')
        self.update(first,{'status':'archived'})
        self.assertEqual([p['id'] for p in self.queue()],[second])
        self.update(first,{'status':'waiting'})
        self.assertEqual([p['id'] for p in self.queue()],[second,first])

    def test_move_to_another_flight_and_edit_details(self):
        first=self.add(); target=self.flights[1]['id']; existing=self.add('Already There',flight=target)
        result=self.update(first,{'flight_id':target,'name':'Updated Name','contact':'new@example.test','notes':'Call after lunch'})
        self.assertEqual(result.status_code,200)
        self.assertEqual(self.queue(),[])
        self.assertEqual([p['id'] for p in self.queue(target)],[existing,first])
        self.assertEqual(self.queue(target)[1]['notes'],'Call after lunch')

    def test_daily_lists_are_separate(self):
        self.add()
        next_day=self.day('2026-10-10')['flights']
        self.assertEqual(len(next_day),11)
        self.assertTrue(all(not f['passengers'] for f in next_day))
        self.assertNotEqual(next_day[0]['id'],self.flight)

    def test_booking_can_move_to_another_date_without_losing_details(self):
        first = self.add('Moving Guest', 'guest@example.test')
        remaining = self.add('Staying Guest')
        self.update(first, {'party_size': 4, 'notes': 'Call in the morning'})
        target = self.day('2026-10-10')['flights'][0]['id']
        already_there = self.add('Already Waiting', flight=target)
        response = self.update(first, {'flight_id': target, 'flight_date': '2026-10-10'})
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual([(p['id'], p['position']) for p in self.queue()], [(remaining, 1)])
        queue = self.day('2026-10-10')['flights'][0]['passengers']
        self.assertEqual([(p['id'], p['position']) for p in queue], [(already_there, 1), (first, 2)])
        self.assertEqual((queue[1]['name'], queue[1]['contact'], queue[1]['party_size'], queue[1]['notes']),
                         ('Moving Guest', 'guest@example.test', 4, 'Call in the morning'))

    def test_booking_date_must_match_its_flight(self):
        path = f'/api/flights/{self.flight}/passengers'
        for date in ['2026-10-10', 'invalid', None]:
            response = self.client.post(path, json={'name': 'New Guest', 'flight_date': date}, headers=self.headers)
            self.assertEqual(response.status_code, 400)
        self.assertEqual(self.queue(), [])
        response = self.client.post(path, json={'name': 'New Guest', 'flight_date': '2026-10-09'}, headers=self.headers)
        self.assertEqual(response.status_code, 201)
        id_ = response.get_json()['id']
        target = self.day('2026-10-10')['flights'][0]['id']
        self.assertEqual(self.update(id_, {'flight_id': target, 'flight_date': '2026-10-09', 'name': 'Wrong Day'}).status_code, 400)
        self.assertEqual(self.queue()[0]['name'], 'New Guest')
        self.assertEqual(self.day('2026-10-10')['flights'][0]['passengers'], [])

    def test_validation_does_not_change_existing_entry(self):
        id_=self.add()
        for data in [{'name':''},{'contact':123},{'flight_id':99999},{'status':'seated'},{'notes':'x'*501}]:
            self.assertEqual(self.update(id_,data).status_code,400)
        self.assertEqual(self.queue()[0]['name'],'Test Guest')
        self.assertEqual(self.client.get('/api/day?date=invalid').status_code,400)

    def test_csrf_and_origin_are_checked(self):
        path=f'/api/flights/{self.flight}/passengers'
        self.assertEqual(self.client.post(path,json={'name':'Guest'}).status_code,403)
        headers={**self.headers,'Origin':'https://different.example'}
        self.assertEqual(self.client.post(path,json={'name':'Guest'},headers=headers).status_code,403)
        self.assertEqual(self.queue(),[])

    def test_schedule_edit_preserves_existing_days(self):
        template=self.flights[0]['schedule_id']
        response=self.client.patch(f'/api/schedule/{template}',json={'name':'Changed Flight','departure':'08:15'},headers=self.headers)
        self.assertEqual(response.status_code,200)
        self.assertEqual(self.day()['flights'][0]['departure'],'08:00')
        self.assertEqual(self.day('2026-10-10')['flights'][0]['departure'],'08:15')
        self.client.patch(f'/api/schedule/{template}',json={'active':False},headers=self.headers)
        self.assertEqual(len(self.day()['flights']),11)
        self.assertEqual(len(self.day('2026-10-11')['flights']),10)

    def test_extra_flight_affects_only_one_day(self):
        response=self.client.post('/api/flights',json={'name':'Extra Departure','departure':'15:00','date':'2026-10-09'},headers=self.headers)
        self.assertEqual(response.status_code,201)
        self.assertEqual(len(self.day()['flights']),12)
        self.assertEqual(len(self.day('2026-10-10')['flights']),11)
        self.assertEqual(len(self.client.get('/api/schedule').get_json()['schedule']),11)

    def test_flight_edit_keeps_waitlist(self):
        self.add()
        response=self.client.patch(f'/api/flights/{self.flight}',json={'name':'Updated Route','departure':'07:45'},headers=self.headers)
        self.assertEqual(response.status_code,200)
        self.assertEqual(self.queue()[0]['name'],'Test Guest')
        self.assertEqual(self.day()['flights'][0]['name'],'Updated Route')

    def test_csv_export_and_formula_protection(self):
        self.add('=SUM(A1:A2)','+6421000000')
        response=self.client.get('/api/export?date=2026-10-09')
        rows=list(csv.DictReader(io.StringIO(response.get_data(as_text=True))))
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['name'],"'=SUM(A1:A2)")
        self.assertEqual(rows[0]['contact'],"'+6421000000")
        self.assertEqual(self.client.get('/api/export?date=bad').status_code,400)

    def test_full_backup_preserves_data_for_browser_migration(self):
        first = self.add('Backup Guest', 'guest@example.test')
        self.update(first, {'party_size': 4, 'notes': 'Keep this note'})
        second = self.add('Archived Guest')
        self.update(second, {'status': 'archived'})
        template = self.flights[0]['schedule_id']
        self.client.patch(f'/api/schedule/{template}', json={'active': False}, headers=self.headers)
        response = self.client.get('/api/backup')
        self.assertEqual(response.status_code, 200)
        backup = response.get_json()
        self.assertEqual((backup['format'], backup['version'], backup['data']['schema_version']),
                         ('southern-alps-air-waitlist', 1, 1))
        self.assertEqual(len(backup['data']['flights']), 11)
        records = backup['data']['passengers']
        self.assertEqual([(p['id'], p['party_size'], p['status']) for p in records], [(first, 4, 'waiting'), (second, 1, 'archived')])
        self.assertEqual((records[0]['contact'], records[0]['notes']), ('guest@example.test', 'Keep this note'))
        self.assertEqual(next(f for f in backup['data']['schedule'] if f['id'] == template)['active'], 0)
        self.assertNotIn('session', response.get_data(as_text=True))

    def test_authentication_guards_data_and_logout(self):
        self.app.config['STAFF_PASSWORD']='test-password'
        self.assertEqual(self.client.get('/api/day').status_code,401)
        self.assertEqual(self.client.get('/api/export').status_code,401)
        self.assertEqual(self.client.get('/api/week').status_code,401)
        self.assertEqual(self.client.get('/api/backup').status_code,401)
        self.assertEqual(self.client.get('/').status_code,302)
        page=self.client.get('/login').get_data(as_text=True)
        token=re.search(r'name="csrf" value="([^"]+)"',page).group(1)
        result=self.client.post('/login',data={'password':'test-password','csrf':token})
        self.assertEqual(result.status_code,302)
        self.assertEqual(self.client.get('/api/day').status_code,200)
        with self.client.session_transaction() as session: token=session['csrf']
        self.assertEqual(self.client.post('/api/logout',headers={'X-CSRF-Token':token}).status_code,200)
        self.assertEqual(self.client.get('/api/day').status_code,401)

    def test_simultaneous_additions_have_distinct_positions(self):
        def add_guest(index):
            client=self.app.test_client()
            with client.session_transaction() as session: session['csrf']='parallel'
            response=client.post(f'/api/flights/{self.flight}/passengers',json={'name':f'Guest {index}','contact':''},headers={'X-CSRF-Token':'parallel'})
            return response.status_code
        with ThreadPoolExecutor(max_workers=4) as executor:
            self.assertEqual(list(executor.map(add_guest,range(8))),[201]*8)
        positions=[p['position'] for p in self.queue()]
        self.assertEqual(positions,list(range(1,9)))

    def test_group_size_is_saved_edited_and_exported(self):
        response=self.client.post(f'/api/flights/{self.flight}/passengers',json={'name':'Family Booking','contact':'family@example.test','party_size':4},headers=self.headers)
        self.assertEqual(response.status_code,201)
        id_=response.get_json()['id']
        self.assertEqual(self.queue()[0]['party_size'],4)
        self.update(id_,{'party_size':6})
        self.assertEqual(self.queue()[0]['party_size'],6)
        rows=list(csv.DictReader(io.StringIO(self.client.get('/api/export?date=2026-10-09').get_data(as_text=True))))
        self.assertEqual(rows[0]['party_size'],'6')
        self.update(id_,{'status':'archived'})
        self.update(id_,{'status':'waiting','flight_id':self.flights[1]['id']})
        self.assertEqual(self.queue(self.flights[1]['id'])[0]['party_size'],6)

    def test_invalid_group_sizes_leave_record_unchanged(self):
        id_=self.add()
        for size in [0,-1,101,2.5,'2',True,None]:
            self.assertEqual(self.update(id_,{'party_size':size}).status_code,400)
            self.assertEqual(self.client.post(f'/api/flights/{self.flight}/passengers',json={'name':'Invalid Group','party_size':size},headers=self.headers).status_code,400)
        self.assertEqual(len(self.queue()),1)
        self.assertEqual(self.queue()[0]['party_size'],1)

    def test_week_counts_bookings_and_people_separately(self):
        first=self.add('First Group'); self.update(first,{'party_size':4})
        archived=self.add('Archived Group'); self.update(archived,{'party_size':8,'status':'archived'})
        next_flight=self.day('2026-10-10')['flights'][0]['id']
        second=self.add('Next Day Group',flight=next_flight); self.update(second,{'party_size':3})
        result=self.client.get('/api/week?start=2026-10-09').get_json()
        self.assertEqual((result['start'],result['end']),('2026-10-09','2026-10-15'))
        self.assertEqual(len(result['days']),7)
        self.assertEqual((result['flight_count'],result['booking_count'],result['people_waiting'],result['queued_flights']),(77,2,7,2))
        self.assertEqual((result['days'][0]['booking_count'],result['days'][0]['people_waiting']),(1,4))
        self.assertEqual(result['days'][0]['flights'][0]['people_waiting'],4)
        self.assertNotIn('passengers',result['days'][0]['flights'][0])

    def test_week_preview_does_not_freeze_future_schedule(self):
        response=self.client.get('/api/week?start=2026-10-09')
        self.assertEqual(response.status_code,200)
        with sqlite3.connect(self.database) as connection:
            self.assertEqual(connection.execute('SELECT COUNT(*) FROM flights').fetchone()[0],11)
        template=self.flights[0]['schedule_id']
        self.client.patch(f'/api/schedule/{template}',json={'name':'New Schedule Name','departure':'08:15'},headers=self.headers)
        week=self.client.get('/api/week?start=2026-10-09').get_json()
        self.assertEqual(week['days'][0]['flights'][0]['name'],'Siberia Experience')
        self.assertEqual(week['days'][1]['flights'][0]['name'],'New Schedule Name')
        self.assertIsNone(week['days'][1]['flights'][0]['id'])

    def test_week_date_validation_and_month_boundary(self):
        for start in ['bad','2100-12-26','1999-12-31']:
            self.assertEqual(self.client.get('/api/week?start='+start).status_code,400)
        week=self.client.get('/api/week?start=2026-10-29').get_json()
        self.assertEqual(week['end'],'2026-11-04')
        self.assertEqual([d['date'] for d in week['days']],['2026-10-29','2026-10-30','2026-10-31','2026-11-01','2026-11-02','2026-11-03','2026-11-04'])

    def test_legacy_database_migrates_with_backup_and_no_lost_records(self):
        id_=self.add('Existing Guest','existing@example.test')
        before=self.queue()[0]
        with sqlite3.connect(self.database) as connection:
            connection.execute('ALTER TABLE passengers DROP COLUMN party_size')
        create_app(self.config)
        after=self.queue()[0]
        self.assertEqual(after,before)
        backup=Path(self.database+'.before-group-size.backup')
        self.assertTrue(backup.exists())
        with sqlite3.connect(backup) as connection:
            self.assertNotIn('party_size',{row[1] for row in connection.execute('PRAGMA table_info(passengers)')})
            self.assertEqual(connection.execute('SELECT id,name,contact FROM passengers').fetchone(),(id_,'Existing Guest','existing@example.test'))
        create_app(self.config)
        self.assertEqual(self.queue(),[after])


if __name__=='__main__':
    unittest.main()

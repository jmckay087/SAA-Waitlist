"""Export a consistent SQLite snapshot in the browser app's backup format."""
from datetime import datetime, timezone


def browser_backup(connection):
    data = {'schema_version': 1}
    fields = {
        'schedule': 'id,name,departure,active',
        'flights': 'id,schedule_id,flight_date,name,departure',
        'passengers': 'id,flight_id,name,contact,notes,status,position,created_at,party_size',
    }
    for table, columns in fields.items():
        cursor = connection.execute(f'SELECT {columns} FROM {table} ORDER BY id')
        names = [field[0] for field in cursor.description]
        data[table] = [dict(zip(names, row)) for row in cursor]
    return {'format': 'southern-alps-air-waitlist', 'version': 1,
            'exported_at': datetime.now(timezone.utc).isoformat(), 'data': data}

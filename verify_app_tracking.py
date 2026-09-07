import sqlite3
import time
import app as app_module

conn = sqlite3.connect('hersphere.db')
conn.row_factory = sqlite3.Row
cursor = conn.cursor()
start = {
    'users': cursor.execute('SELECT COUNT(*) FROM users').fetchone()[0],
    'jobs': cursor.execute('SELECT COUNT(*) FROM jobs').fetchone()[0],
    'applications': cursor.execute('SELECT COUNT(*) FROM applications').fetchone()[0],
    'employers': cursor.execute('SELECT COUNT(*) FROM employers').fetchone()[0],
    'saved_jobs': cursor.execute('SELECT COUNT(*) FROM saved_jobs').fetchone()[0],
}

client = app_module.app.test_client()
unique = int(time.time())
user_email = f'user_{unique}@example.com'
emp_email = f'emp_{unique}@example.com'
user_id = None
other_user_id = None
emp_id = None
job_id = None
app_id = None

try:
    cursor.execute('INSERT INTO employers (company_name, email, password, phone, company_description) VALUES (?, ?, ?, ?, ?)',
                   (f'Acme Temp {unique}', emp_email, app_module.generate_password_hash('secret123'), '9999999999', 'Temp employer'))
    emp_id = cursor.lastrowid
    cursor.execute('INSERT INTO jobs (title, company, skill_required, description, employer_id, location, job_type, salary, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)',
                   (f'Temp Role {unique}', f'Acme Temp {unique}', 'python', 'temp desc', emp_id, 'Mumbai', 'Full-time', '₹50,000'))
    job_id = cursor.lastrowid
    cursor.execute('INSERT INTO users (name, email, password, skills) VALUES (?, ?, ?, ?)',
                   (f'Test User {unique}', user_email, app_module.hashlib.sha256(b'pass123').hexdigest(), 'python, analytics'))
    user_id = cursor.lastrowid
    cursor.execute('INSERT INTO applications (user_id, job_id, voice_message, status, applied_at) VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)',
                   (user_id, job_id, 'Hi there', 'Pending'))
    app_id = cursor.lastrowid
    conn.commit()

    with client.session_transaction() as s:
        s['user_id'] = user_id
        s['user_name'] = f'Test User {unique}'

    resp = client.get('/my-applications')
    print('MY_APPS_STATUS', resp.status_code)
    html = resp.get_data(as_text=True)
    print('MY_APPS_TEXT', 'My Applications' in html, 'Pending' in html, 'Browse Jobs' in html)

    resp = client.get(f'/applications/{app_id}')
    print('APP_DETAILS_STATUS', resp.status_code)
    details = resp.get_data(as_text=True)
    print('APP_DETAILS_TEXT', 'Job Information' in details, 'Temp Role' in details)

    other_client = app_module.app.test_client()
    cursor.execute('INSERT INTO users (name, email, password, skills) VALUES (?, ?, ?, ?)',
                   (f'Other User {unique}', f'other_{unique}@example.com', app_module.hashlib.sha256(b'pass456').hexdigest(), 'design'))
    other_user_id = cursor.lastrowid
    conn.commit()
    with other_client.session_transaction() as s:
        s['user_id'] = other_user_id
    resp_other = other_client.get(f'/applications/{app_id}')
    print('OTHER_USER_ACCESS', resp_other.status_code)

    with client.session_transaction() as s:
        s.pop('user_id', None)
        s['employer_id'] = emp_id
        s['employer_name'] = f'Acme Temp {unique}'
    resp = client.post(f'/employer/application/{app_id}/status', data={'status': 'Shortlisted'})
    print('EMPLOYER_STATUS_UPDATE', resp.status_code)
    with client.session_transaction() as s:
        s.pop('employer_id', None)
        s['user_id'] = user_id
        s['user_name'] = f'Test User {unique}'
    resp = client.get('/my-applications')
    print('USER_SEES_NEW_STATUS', 'Shortlisted' in resp.get_data(as_text=True))
finally:
    if app_id is not None:
        cursor.execute('DELETE FROM applications WHERE id = ?', (app_id,))
    if job_id is not None:
        cursor.execute('DELETE FROM jobs WHERE id = ?', (job_id,))
    if emp_id is not None:
        cursor.execute('DELETE FROM employers WHERE id = ?', (emp_id,))
    if user_id is not None:
        cursor.execute('DELETE FROM users WHERE id = ?', (user_id,))
    if other_user_id is not None:
        cursor.execute('DELETE FROM users WHERE id = ?', (other_user_id,))
    conn.commit()
    end = {
        'users': cursor.execute('SELECT COUNT(*) FROM users').fetchone()[0],
        'jobs': cursor.execute('SELECT COUNT(*) FROM jobs').fetchone()[0],
        'applications': cursor.execute('SELECT COUNT(*) FROM applications').fetchone()[0],
        'employers': cursor.execute('SELECT COUNT(*) FROM employers').fetchone()[0],
        'saved_jobs': cursor.execute('SELECT COUNT(*) FROM saved_jobs').fetchone()[0],
    }
    print('ROW_COUNTS_RESTORED', end == start)
    conn.close()

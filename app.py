from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, abort, send_from_directory
import sqlite3
import hashlib
import hmac
import os
import re
import secrets
import uuid
from functools import wraps
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.template_folder = 'templetes'
app.secret_key = os.environ.get('HERSPHERE_SECRET_KEY') or secrets.token_hex(32)
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Lax')
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['MAX_CONTENT_LENGTH'] = 10 * 1024 * 1024
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# Database setup
def get_db():
    conn = sqlite3.connect('hersphere.db')
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys = ON')
    return conn


def add_column_if_missing(db, table_name, column_name, definition):
    columns = {row['name'] for row in db.execute('PRAGMA table_info(' + table_name + ')')}
    if column_name not in columns:
        db.execute('ALTER TABLE ' + table_name + ' ADD COLUMN ' + column_name + ' ' + definition)

def init_db():
    with app.app_context():
        db = get_db()
        db.execute('''CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            skills TEXT
        )''')
        db.execute('''CREATE TABLE IF NOT EXISTS jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            company TEXT NOT NULL,
            skill_required TEXT NOT NULL,
            description TEXT
        )''')
        db.execute('''CREATE TABLE IF NOT EXISTS applications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            job_id INTEGER,
            voice_message TEXT,
            status TEXT DEFAULT 'Pending',
            applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id),
            FOREIGN KEY (job_id) REFERENCES jobs (id)
        )''')
        db.execute('''CREATE TABLE IF NOT EXISTS posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            message TEXT NOT NULL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )''')
        db.execute('''CREATE TABLE IF NOT EXISTS post_likes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            post_id INTEGER NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (user_id, post_id),
            FOREIGN KEY (user_id) REFERENCES users (id),
            FOREIGN KEY (post_id) REFERENCES posts (id)
        )''')
        db.execute('''CREATE TABLE IF NOT EXISTS comments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            post_id INTEGER NOT NULL,
            comment_text TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id),
            FOREIGN KEY (post_id) REFERENCES posts (id)
        )''')
        db.execute('''CREATE TABLE IF NOT EXISTS post_reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            post_id INTEGER NOT NULL,
            reason TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (user_id, post_id),
            FOREIGN KEY (user_id) REFERENCES users (id),
            FOREIGN KEY (post_id) REFERENCES posts (id)
        )''')
        db.execute('''CREATE TABLE IF NOT EXISTS employers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            phone TEXT,
            company_description TEXT,
            verification_status TEXT DEFAULT 'Pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        db.execute('''CREATE TABLE IF NOT EXISTS saved_jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            job_id INTEGER NOT NULL,
            saved_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (user_id, job_id),
            FOREIGN KEY (user_id) REFERENCES users (id),
            FOREIGN KEY (job_id) REFERENCES jobs (id)
        )''')
        db.execute('''CREATE TABLE IF NOT EXISTS course_progress (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            course_id TEXT NOT NULL,
            lesson_id TEXT NOT NULL,
            completed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (user_id, course_id, lesson_id),
            FOREIGN KEY (user_id) REFERENCES users (id)
        )''')
        db.execute('''CREATE TABLE IF NOT EXISTS freelance_acceptances (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            task_id TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'Accepted',
            accepted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (user_id, task_id),
            FOREIGN KEY (user_id) REFERENCES users (id)
        )''')
        db.execute('''CREATE TABLE IF NOT EXISTS admins (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')

        admin_email = os.environ.get('HERSPHERE_ADMIN_EMAIL', 'admin@hersphere.local').strip().lower()
        admin_password = os.environ.get('HERSPHERE_ADMIN_PASSWORD')
        if admin_password:
            db.execute('INSERT OR IGNORE INTO admins (email, password) VALUES (?, ?)',
                       (admin_email, generate_password_hash(admin_password)))

        # Add optional employer fields without changing existing rows.
        add_column_if_missing(db, 'jobs', 'employer_id', 'INTEGER')
        add_column_if_missing(db, 'jobs', 'location', 'TEXT')
        add_column_if_missing(db, 'jobs', 'job_type', 'TEXT')
        add_column_if_missing(db, 'jobs', 'salary', 'TEXT')
        add_column_if_missing(db, 'jobs', 'created_at', 'TIMESTAMP')
        add_column_if_missing(db, 'applications', 'status', "TEXT DEFAULT 'Pending'")
        add_column_if_missing(db, 'applications', 'applied_at', 'TIMESTAMP')
        db.execute("UPDATE applications SET status = 'Pending' WHERE status IS NULL OR status = ''")
        db.execute("UPDATE applications SET applied_at = CURRENT_TIMESTAMP WHERE applied_at IS NULL")
        
        # Insert sample jobs
        jobs = [
            ('Content Writer', 'TechWomen Inc.', 'writing', 'Write engaging blog posts about women in tech.'),
            ('Digital Marketing Specialist', 'EmpowerCo', 'marketing', 'Manage social media campaigns and SEO.'),
            ('Web Developer', 'CodeHer', 'coding', 'Build responsive websites using HTML, CSS, JS.'),
            ('Data Analyst', 'DataWomen', 'data analysis', 'Analyze datasets and create reports.'),
            ('Graphic Designer', 'CreativeWomen', 'design', 'Create visual content for marketing materials.'),
        ]
        
        for job in jobs:
            exists = db.execute('''SELECT 1 FROM jobs
                WHERE title = ? AND company = ? AND skill_required = ? AND description = ?''', job).fetchone()
            if not exists:
                db.execute('INSERT INTO jobs (title, company, skill_required, description) VALUES (?, ?, ?, ?)', job)
        
        db.commit()

init_db()


COURSES = [
    {
        'id': 'resume-interview',
        'title': 'Resume & Interview Skills',
        'description': 'Build a focused resume and prepare for confident interviews.',
        'lessons': [
            {'id': 'resume-basics', 'title': 'Resume Basics', 'content': 'Choose clear headings and highlight achievements that show the value you bring.'},
            {'id': 'strong-bullets', 'title': 'Write Strong Experience Bullets', 'content': 'Start with an action verb and include the result, scope, or measurable outcome of your work.'},
            {'id': 'interview-prep', 'title': 'Interview Preparation', 'content': 'Practice concise examples using the situation, action, and result structure.'},
        ],
    },
    {
        'id': 'digital-skills',
        'title': 'Digital Skills',
        'description': 'Strengthen the practical digital skills used in modern workplaces.',
        'lessons': [
            {'id': 'online-collaboration', 'title': 'Online Collaboration', 'content': 'Use shared documents, calendars, and clear written updates to work effectively with a team.'},
            {'id': 'digital-safety', 'title': 'Digital Safety', 'content': 'Use unique passwords, multi-factor authentication, and care when opening links or sharing data.'},
            {'id': 'spreadsheets', 'title': 'Spreadsheet Essentials', 'content': 'Organize information in columns, use simple formulas, and check your data before sharing it.'},
        ],
    },
    {
        'id': 'financial-workplace',
        'title': 'Financial & Workplace Skills',
        'description': 'Learn practical habits for navigating pay, planning, and professional communication.',
        'lessons': [
            {'id': 'understand-pay', 'title': 'Understand Your Pay', 'content': 'Review your offer, pay frequency, deductions, and any benefits before accepting a role.'},
            {'id': 'workplace-communication', 'title': 'Workplace Communication', 'content': 'Set expectations early, ask clear questions, and document important agreements.'},
            {'id': 'personal-budget', 'title': 'Personal Budget Basics', 'content': 'Track income and essential expenses, then set a realistic goal for saving or reducing debt.'},
        ],
    },
    {
        'id': 'entrepreneurship-freelancing',
        'title': 'Entrepreneurship & Freelancing',
        'description': 'Turn your skills into a focused freelance service or small business idea.',
        'lessons': [
            {'id': 'choose-service', 'title': 'Choose Your Service', 'content': 'Define one specific problem you can solve and the type of client who needs it.'},
            {'id': 'price-work', 'title': 'Price Your Work', 'content': 'Estimate the time and value involved, state what is included, and agree on payment terms in writing.'},
            {'id': 'find-clients', 'title': 'Find Your First Clients', 'content': 'Create a small portfolio and use trusted networks to reach people who can describe your work.'},
        ],
    },
]


FREELANCE_TASKS = [
    {'id': 'data-entry', 'title': 'Data Entry Task', 'description': 'Enter data from provided spreadsheets.', 'payment': '$5 per task.'},
    {'id': 'content-writing', 'title': 'Content Writing', 'description': 'Write 500-word articles on given topics.', 'payment': '$10 per article.'},
    {'id': 'translation', 'title': 'Translation', 'description': 'Translate short documents from English to your language.', 'payment': '$8 per document.'},
    {'id': 'social-media-posting', 'title': 'Social Media Posting', 'description': 'Create and schedule social media posts.', 'payment': '$7 per set.'},
]


def course_by_id(course_id):
    return next((course for course in COURSES if course['id'] == course_id), None)


def course_view(course, completed_lessons):
    lessons = []
    for lesson in course['lessons']:
        lessons.append({**lesson, 'completed': lesson['id'] in completed_lessons})
    completed_count = sum(lesson['completed'] for lesson in lessons)
    total_count = len(lessons)
    return {
        **course,
        'lessons': lessons,
        'completed_count': completed_count,
        'total_count': total_count,
        'progress_percentage': round(completed_count / total_count * 100) if total_count else 0,
        'next_lesson': next((lesson for lesson in lessons if not lesson['completed']), None),
    }


def freelance_task_by_id(task_id):
    return next((task for task in FREELANCE_TASKS if task['id'] == task_id), None)


def employer_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if ('employer_id' not in session or 'user_id' in session or
                'admin_id' in session):
            flash('Please log in as an employer to continue.')
            return redirect(url_for('employer_login'))
        db = get_db()
        if not db.execute('SELECT id FROM employers WHERE id = ?',
                          (session['employer_id'],)).fetchone():
            session.clear()
            return redirect(url_for('employer_login'))
        return view(*args, **kwargs)
    return wrapped


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if ('admin_id' not in session or 'user_id' in session or
                'employer_id' in session):
            return redirect(url_for('admin_login'))
        db = get_db()
        if not db.execute('SELECT id FROM admins WHERE id = ?',
                          (session['admin_id'],)).fetchone():
            session.clear()
            return redirect(url_for('admin_login'))
        return view(*args, **kwargs)
    return wrapped


def valid_email(email):
    return bool(re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+', email or ''))


def is_legacy_password(password_hash):
    return bool(re.fullmatch(r'[0-9a-fA-F]{64}', password_hash or ''))


def check_user_password(password_hash, password):
    if is_legacy_password(password_hash):
        legacy_hash = hashlib.sha256(password.encode()).hexdigest()
        return hmac.compare_digest(password_hash.lower(), legacy_hash)
    try:
        return check_password_hash(password_hash, password)
    except (TypeError, ValueError):
        return False


def normalize_skills(skills):
    """Return unique, trimmed, case-insensitive skills in input order."""
    normalized = []
    seen = set()
    for skill in (skills or '').split(','):
        value = skill.strip().lower()
        if value and value not in seen:
            normalized.append(value)
            seen.add(value)
    return normalized


def build_recommendations(user_skills, jobs, limit=5):
    """Score jobs by the percentage of their required skills a user has."""
    user_skill_set = set(normalize_skills(user_skills))
    recommendations = []
    if not user_skill_set:
        return recommendations

    for job in jobs:
        required_skills = normalize_skills(job['skill_required'])
        if not required_skills:
            continue
        matched_skills = [skill for skill in required_skills if skill in user_skill_set]
        if not matched_skills:
            continue
        recommendation = dict(job)
        recommendation['match_percentage'] = round(
            len(matched_skills) / len(required_skills) * 100, 1
        )
        recommendation['matched_skills'] = matched_skills
        recommendation['missing_skills'] = [
            skill for skill in required_skills if skill not in user_skill_set
        ]
        recommendation.update(analyze_job(recommendation))
        recommendations.append(recommendation)

    recommendations.sort(key=lambda job: (-job['match_percentage'], job['id']))
    return recommendations[:limit]


def analyze_job(job):
    """Return explainable scam indicators and a risk classification for a job."""
    job = dict(job)
    title = (job.get('title') or '').strip()
    description = (job.get('description') or '').strip()
    company = (job.get('company') or '').strip()
    salary = (job.get('salary') or '').strip()
    searchable_text = ' '.join([title, description, company, salary]).lower()
    score = 0
    indicators = []

    rule_groups = [
        (r'(?:pay|send|transfer|deposit|buy).{0,35}(?:registration|application|processing|training|security|fee|money|payment)',
         45, 'Requests payment or an upfront fee'),
        (r'\b(?:guaranteed\s+(?:income|job|earnings)|easy\s+money)\b',
         30, 'Promises guaranteed income, a guaranteed job, or easy money'),
        (r'\b(?:send|share|provide).{0,20}\botp\b|\b(?:otp|one[- ]time password)\b',
         40, 'Requests an OTP or one-time password'),
        (r'\b(?:bank\s+details?|account\s+number|card\s+details?|cvv)\b',
         40, 'Requests bank or card details'),
        (r'\b(?:wire transfer|gift card|cryptocurrency|bitcoin|upfront fee|joining fee)\b',
         35, 'Contains a suspicious payment method or fee request'),
    ]
    for pattern, points, label in rule_groups:
        if re.search(pattern, searchable_text):
            score += points
            indicators.append(label)

    links = re.findall(r'https?://[^\s<>"\']+', searchable_text)
    if links:
        score += 20
        indicators.append('Contains an external link that needs verification')

    if not description:
        score += 15
        indicators.append('Job description is missing')
    elif len(description) < 40:
        score += 10
        indicators.append('Job description is unusually short')

    salary_values = [int(value.replace(',', '')) for value in re.findall(r'\d[\d,]*', salary)]
    if salary_values and (max(salary_values) >= 1000000 or
                          (re.search(r'\b(?:per|a)\s+(?:day|week)\b', salary.lower()) and max(salary_values) >= 10000)):
        score += 25
        indicators.append('Salary claim appears unusually high')

    if score >= 60:
        risk_level = 'High Risk'
    elif score >= 25:
        risk_level = 'Medium Risk'
    else:
        risk_level = 'Low Risk'
    return {'risk_score': score, 'risk_level': risk_level, 'risk_indicators': indicators}


def normalize_status_label(status):
    value = (status or '').strip()
    if not value:
        return 'Applied'
    key = value.lower().replace('_', ' ')
    if key in {'pending', 'applied', 'new'}:
        return 'Applied'
    if key in {'under review', 'in review', 'review'}:
        return 'Under Review'
    if key in {'shortlisted', 'short listed'}:
        return 'Shortlisted'
    if key in {'interview', 'interviewing', 'interview scheduled'}:
        return 'Interview'
    if key in {'selected', 'accepted'}:
        return 'Selected'
    if key in {'rejected', 'declined'}:
        return 'Rejected'
    return value


def status_badge_class(status):
    label = normalize_status_label(status)
    mapping = {
        'Applied': 'status-applied',
        'Under Review': 'status-review',
        'Shortlisted': 'status-shortlisted',
        'Interview': 'status-interview',
        'Selected': 'status-selected',
        'Rejected': 'status-rejected',
    }
    return mapping.get(label, 'status-applied')


def build_application_timeline(status):
    label = normalize_status_label(status)
    stages = ['Applied', 'Under Review', 'Shortlisted', 'Interview', 'Selected']
    if label == 'Rejected':
        return [
            {'label': 'Applied', 'state': 'complete'},
            {'label': 'Under Review', 'state': 'complete'},
            {'label': 'Rejected', 'state': 'rejected'},
        ]

    if label not in stages:
        return [
            {'label': 'Applied', 'state': 'current' if label == 'Applied' else 'pending'},
            {'label': 'Under Review', 'state': 'pending'},
            {'label': 'Shortlisted', 'state': 'pending'},
            {'label': 'Interview', 'state': 'pending'},
            {'label': 'Selected', 'state': 'pending'},
        ]

    timeline = []
    current_index = stages.index(label)
    for idx, step in enumerate(stages):
        if idx < current_index:
            timeline.append({'label': step, 'state': 'complete'})
        elif idx == current_index:
            timeline.append({'label': step, 'state': 'current'})
        else:
            timeline.append({'label': step, 'state': 'pending'})
    return timeline


# Routes
@app.route('/')
def home():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    return render_template('index.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        skills = request.form.get('skills', '').strip()
        if not name or not valid_email(email) or len(password) < 6:
            flash('Please provide a valid name, email, and password of at least 6 characters.')
            return render_template('register.html')
        
        db = get_db()
        try:
            db.execute('INSERT INTO users (name, email, password, skills) VALUES (?, ?, ?, ?)',
                      (name, email, generate_password_hash(password), skills))
            db.commit()
            flash('Registration successful! Please login.')
            return redirect(url_for('login'))
        except sqlite3.IntegrityError:
            flash('Email already exists.')
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        
        db = get_db()
        user = db.execute('SELECT id, name, email, password FROM users WHERE email = ?',
                          (email,)).fetchone()
        if user and check_user_password(user['password'], password):
            if is_legacy_password(user['password']):
                db.execute('UPDATE users SET password = ? WHERE id = ?',
                           (generate_password_hash(password), user['id']))
                db.commit()
            session.clear()
            session['user_id'] = user['id']
            session['user_name'] = user['name']
            return redirect(url_for('dashboard'))
        else:
            flash('Invalid credentials.')
    return render_template('login.html')

@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    db = get_db()
    user = db.execute('SELECT * FROM users WHERE id = ?', (session['user_id'],)).fetchone()
    jobs = db.execute('SELECT * FROM jobs').fetchall()
    recommended_jobs = build_recommendations(user['skills'], jobs)

    return render_template('dashboard.html', user=user,
                           recommended_jobs=recommended_jobs,
                           has_profile_skills=bool(normalize_skills(user['skills'])))

@app.route('/jobs')
def jobs():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    db = get_db()
    keyword = request.args.get('keyword', '').strip()
    location = request.args.get('location', '').strip()
    job_type = request.args.get('job_type', '').strip()
    salary_range = request.args.get('salary', 'any').strip().lower()
    sort = request.args.get('sort', 'latest').strip().lower()

    clauses = []
    params = []
    if keyword:
        search_term = '%' + keyword.lower() + '%'
        clauses.append('''(LOWER(title) LIKE ? OR LOWER(company) LIKE ?
            OR LOWER(description) LIKE ? OR LOWER(skill_required) LIKE ?)''')
        params.extend([search_term] * 4)
    if location:
        clauses.append('LOWER(COALESCE(location, \'\')) = LOWER(?)')
        params.append(location)
    if job_type:
        clauses.append('LOWER(COALESCE(job_type, \'\')) = LOWER(?)')
        params.append(job_type)

    query = '''SELECT jobs.*,
        CASE WHEN employers.verification_status = 'Verified' THEN 1 ELSE 0 END AS employer_verified
        FROM jobs LEFT JOIN employers ON jobs.employer_id = employers.id'''
    if clauses:
        query += ' WHERE ' + ' AND '.join(clauses)
    all_jobs = [dict(job, **analyze_job(job)) for job in db.execute(query, params).fetchall()]

    def salary_value(job):
        values = [int(value.replace(',', '')) for value in re.findall(r'\d[\d,]*', job['salary'] or '')]
        return sum(values) / len(values) if values else None

    salary_limits = {
        'below-20000': lambda value: value is not None and value < 20000,
        '20000-40000': lambda value: value is not None and 20000 <= value <= 40000,
        '40000-60000': lambda value: value is not None and 40000 < value <= 60000,
        'above-60000': lambda value: value is not None and value > 60000,
    }
    if salary_range in salary_limits:
        all_jobs = [job for job in all_jobs if salary_limits[salary_range](salary_value(job))]

    if sort == 'oldest':
        all_jobs.sort(key=lambda job: (job['created_at'] is not None, job['created_at'] or '', job['id']))
    elif sort == 'salary-low':
        all_jobs.sort(key=lambda job: (salary_value(job) is None, salary_value(job) or 0, job['id']))
    elif sort == 'salary-high':
        all_jobs.sort(key=lambda job: (salary_value(job) is None, -(salary_value(job) or 0), -job['id']))
    elif sort == 'title':
        all_jobs.sort(key=lambda job: (job['title'] or '').lower())
    else:
        all_jobs.sort(key=lambda job: (job['created_at'] is None, job['created_at'] or '', job['id']), reverse=True)

    saved_job_ids = set()
    if all_jobs:
        placeholders = ','.join('?' for _ in all_jobs)
        saved_job_ids = {row['job_id'] for row in db.execute(
            'SELECT job_id FROM saved_jobs WHERE user_id = ? AND job_id IN (' + placeholders + ')',
            [session['user_id']] + [job['id'] for job in all_jobs]
        ).fetchall()}
    locations = [row['location'] for row in db.execute(
        "SELECT DISTINCT location FROM jobs WHERE location IS NOT NULL AND TRIM(location) <> '' ORDER BY location COLLATE NOCASE"
    ).fetchall()]
    job_types = [row['job_type'] for row in db.execute(
        "SELECT DISTINCT job_type FROM jobs WHERE job_type IS NOT NULL AND TRIM(job_type) <> '' ORDER BY job_type COLLATE NOCASE"
    ).fetchall()]
    return render_template('jobs.html', jobs=all_jobs, saved_job_ids=saved_job_ids,
                           locations=locations, job_types=job_types, saved_page=False,
                           filters={'keyword': keyword, 'location': location, 'job_type': job_type,
                                    'salary': salary_range, 'sort': sort})


@app.route('/save-job/<int:job_id>', methods=['POST'])
def save_job(job_id):
    if 'user_id' not in session:
        flash('Please log in to save jobs.')
        return redirect(url_for('login'))
    db = get_db()
    if not db.execute('SELECT id FROM jobs WHERE id = ?', (job_id,)).fetchone():
        flash('That job is no longer available.')
        return redirect(url_for('jobs'))
    db.execute('INSERT OR IGNORE INTO saved_jobs (user_id, job_id) VALUES (?, ?)',
               (session['user_id'], job_id))
    db.commit()
    flash('Job saved.')
    return redirect(request.referrer or url_for('jobs'))


@app.route('/unsave-job/<int:job_id>', methods=['POST'])
def unsave_job(job_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    db = get_db()
    db.execute('DELETE FROM saved_jobs WHERE user_id = ? AND job_id = ?',
               (session['user_id'], job_id))
    db.commit()
    flash('Job removed from saved jobs.')
    return redirect(request.referrer or url_for('jobs'))


@app.route('/saved-jobs')
def saved_jobs():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    db = get_db()
    saved = db.execute('''
        SELECT jobs.*,
               CASE WHEN employers.verification_status = 'Verified' THEN 1 ELSE 0 END AS employer_verified
        FROM saved_jobs JOIN jobs ON saved_jobs.job_id = jobs.id
        LEFT JOIN employers ON jobs.employer_id = employers.id
        WHERE saved_jobs.user_id = ? ORDER BY saved_jobs.saved_at DESC
    ''', (session['user_id'],)).fetchall()
    saved = [dict(job, **analyze_job(job)) for job in saved]
    return render_template('jobs.html', jobs=saved, saved_job_ids={job['id'] for job in saved},
                           locations=[], job_types=[], saved_page=True,
                           filters={'keyword': '', 'location': '', 'job_type': '', 'salary': 'any', 'sort': 'latest'})

@app.route('/apply/<int:job_id>', methods=['POST'])
def apply(job_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    voice_message = request.form.get('voice_message', '').strip()
    audio = request.files.get('voice_audio')
    
    db = get_db()
    job = db.execute('SELECT id FROM jobs WHERE id = ?', (job_id,)).fetchone()
    if not job:
        flash('That job is no longer available.')
        return redirect(url_for('jobs'))
    existing = db.execute(
        'SELECT id FROM applications WHERE user_id = ? AND job_id = ?',
        (session['user_id'], job_id)
    ).fetchone()
    if existing:
        flash('You have already applied for this job.')
        return redirect(url_for('jobs'))
    if audio and audio.filename:
        if audio.mimetype not in {'audio/webm', 'audio/ogg', 'audio/mp4', 'audio/wav', 'audio/mpeg'}:
            flash('Unsupported audio format.')
            return redirect(url_for('jobs'))
        filename = uuid.uuid4().hex + '.webm'
        audio.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
        voice_message = 'uploads/' + filename
    db.execute('INSERT INTO applications (user_id, job_id, voice_message, status, applied_at) VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)',
              (session['user_id'], job_id, voice_message, 'Pending'))
    db.commit()
    flash('Application submitted!')
    return redirect(url_for('jobs'))


@app.route('/application-audio/<filename>')
def application_audio(filename):
    if 'user_id' not in session and 'employer_id' not in session:
        return redirect(url_for('login'))
    if '/' in filename or '\\' in filename or not re.fullmatch(r'[a-f0-9]{32}\.webm', filename):
        abort(404)
    db = get_db()
    allowed = db.execute('''
        SELECT 1 FROM applications
        JOIN jobs ON applications.job_id = jobs.id
        WHERE applications.voice_message = ?
          AND (applications.user_id = ? OR jobs.employer_id = ?)
    ''', ('uploads/' + filename, session.get('user_id'), session.get('employer_id'))).fetchone()
    if not allowed:
        abort(403)
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename, mimetype='audio/webm')

@app.route('/learning')
def learning():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    db = get_db()
    completed_rows = db.execute(
        'SELECT course_id, lesson_id FROM course_progress WHERE user_id = ?',
        (session['user_id'],)
    ).fetchall()
    completed_by_course = {}
    for row in completed_rows:
        completed_by_course.setdefault(row['course_id'], set()).add(row['lesson_id'])
    courses = [course_view(course, completed_by_course.get(course['id'], set()))
               for course in COURSES]
    return render_template('learning.html', courses=courses)


@app.route('/learning/<course_id>')
def learning_course(course_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    course = course_by_id(course_id)
    if course is None:
        abort(404)
    db = get_db()
    completed = {
        row['lesson_id'] for row in db.execute(
            'SELECT lesson_id FROM course_progress WHERE user_id = ? AND course_id = ?',
            (session['user_id'], course_id)
        ).fetchall()
    }
    return render_template('learning_course.html',
                           course=course_view(course, completed))


@app.route('/learning/<course_id>/lesson/<lesson_id>/complete', methods=['POST'])
def complete_lesson(course_id, lesson_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    course = course_by_id(course_id)
    if course is None or not any(lesson['id'] == lesson_id for lesson in course['lessons']):
        abort(404)
    db = get_db()
    db.execute('''INSERT OR IGNORE INTO course_progress (user_id, course_id, lesson_id)
                  VALUES (?, ?, ?)''', (session['user_id'], course_id, lesson_id))
    db.commit()
    flash('Lesson marked complete.')
    return redirect(url_for('learning_course', course_id=course_id))

@app.route('/community')
def community():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    db = get_db()
    posts = []
    post_rows = db.execute('''
        SELECT posts.*, users.name,
               COUNT(DISTINCT post_likes.id) AS like_count
        FROM posts JOIN users ON posts.user_id = users.id
        LEFT JOIN post_likes ON post_likes.post_id = posts.id
        GROUP BY posts.id ORDER BY posts.timestamp DESC
    ''').fetchall()
    for post_row in post_rows:
        post = dict(post_row)
        post['liked_by_user'] = bool(db.execute(
            'SELECT 1 FROM post_likes WHERE post_id = ? AND user_id = ?',
            (post['id'], session['user_id'])
        ).fetchone())
        post['comments'] = [dict(comment) for comment in db.execute('''
            SELECT comments.*, users.name
            FROM comments JOIN users ON comments.user_id = users.id
            WHERE comments.post_id = ? ORDER BY comments.created_at ASC, comments.id ASC
        ''', (post['id'],)).fetchall()]
        posts.append(post)
    return render_template('community.html', posts=posts)

@app.route('/post', methods=['POST'])
def post():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    message = request.form.get('message', '').strip()
    if not message:
        flash('Post text cannot be empty.')
        return redirect(url_for('community'))
    db = get_db()
    db.execute('INSERT INTO posts (user_id, message) VALUES (?, ?)',
              (session['user_id'], message))
    db.commit()
    return redirect(url_for('community'))


@app.route('/post/<int:post_id>/like', methods=['POST'])
def toggle_post_like(post_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    db = get_db()
    if not db.execute('SELECT id FROM posts WHERE id = ?', (post_id,)).fetchone():
        abort(404)
    existing = db.execute(
        'SELECT id FROM post_likes WHERE post_id = ? AND user_id = ?',
        (post_id, session['user_id'])
    ).fetchone()
    if existing:
        db.execute('DELETE FROM post_likes WHERE id = ? AND user_id = ?',
                   (existing['id'], session['user_id']))
    else:
        db.execute('INSERT OR IGNORE INTO post_likes (user_id, post_id) VALUES (?, ?)',
                   (session['user_id'], post_id))
    db.commit()
    return redirect(url_for('community'))


@app.route('/post/<int:post_id>/comment', methods=['POST'])
def add_comment(post_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    comment_text = request.form.get('comment_text', '').strip()
    db = get_db()
    if not db.execute('SELECT id FROM posts WHERE id = ?', (post_id,)).fetchone():
        abort(404)
    if not comment_text or len(comment_text) > 1000:
        flash('Comment must contain between 1 and 1000 characters.')
        return redirect(url_for('community'))
    db.execute('''INSERT INTO comments (user_id, post_id, comment_text)
                  VALUES (?, ?, ?)''', (session['user_id'], post_id, comment_text))
    db.commit()
    return redirect(url_for('community'))


@app.route('/comment/<int:comment_id>/delete', methods=['POST'])
def delete_comment(comment_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    db = get_db()
    db.execute('DELETE FROM comments WHERE id = ? AND user_id = ?',
               (comment_id, session['user_id']))
    db.commit()
    return redirect(url_for('community'))


@app.route('/post/<int:post_id>/report', methods=['POST'])
def report_post(post_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    db = get_db()
    if not db.execute('SELECT id FROM posts WHERE id = ?', (post_id,)).fetchone():
        abort(404)
    reason = request.form.get('reason', '').strip()[:500]
    db.execute('''INSERT OR IGNORE INTO post_reports (user_id, post_id, reason)
                  VALUES (?, ?, ?)''', (session['user_id'], post_id, reason))
    db.commit()
    flash('Post reported for review.')
    return redirect(url_for('community'))

@app.route('/applications')
@app.route('/my-applications')
@app.route('/application-history')
def my_applications():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    db = get_db()
    selected_filter = request.args.get('status', 'all').strip()
    selected_sort = request.args.get('sort', 'newest').strip().lower()

    applications = db.execute('''
        SELECT applications.*, jobs.title, jobs.company, jobs.location, jobs.job_type, jobs.salary, jobs.description, jobs.skill_required
        FROM applications
        JOIN jobs ON applications.job_id = jobs.id
        WHERE applications.user_id = ?
        ORDER BY applications.applied_at DESC, applications.id DESC
    ''', (session['user_id'],)).fetchall()

    status_counts = {
        'Applied': 0,
        'Under Review': 0,
        'Shortlisted': 0,
        'Interview': 0,
        'Selected': 0,
        'Rejected': 0,
    }
    for application in applications:
        status_counts[normalize_status_label(application['status'])] = status_counts.get(normalize_status_label(application['status']), 0) + 1

    filtered = []
    for application in applications:
        label = normalize_status_label(application['status'])
        if selected_filter == 'all' or selected_filter == label:
            filtered.append({
                **dict(application),
                'status_label': label,
                'status_badge_class': status_badge_class(application['status']),
                'timeline': build_application_timeline(application['status'])
            })

    if selected_sort == 'oldest':
        filtered.sort(key=lambda app: (app['applied_at'] or '', app['id']))
    elif selected_sort == 'title':
        filtered.sort(key=lambda app: (app['title'] or '').lower())
    else:
        filtered.sort(key=lambda app: (app['applied_at'] or '', app['id']), reverse=True)

    return render_template('my_applications.html',
                           applications=filtered,
                           status_filter=selected_filter,
                           sort=selected_sort,
                           status_counts=status_counts,
                           total_count=len(applications),
                           status_options=['All', 'Applied', 'Under Review', 'Shortlisted', 'Interview', 'Selected', 'Rejected'])


@app.route('/applications/<int:application_id>')
def application_details(application_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))

    db = get_db()
    application = db.execute('''
        SELECT applications.*, jobs.title, jobs.company, jobs.location, jobs.job_type, jobs.salary,
               jobs.description, jobs.skill_required
        FROM applications
        JOIN jobs ON applications.job_id = jobs.id
        WHERE applications.id = ? AND applications.user_id = ?
    ''', (application_id, session['user_id'])).fetchone()

    if application is None:
        exists = db.execute('SELECT 1 FROM applications WHERE id = ?', (application_id,)).fetchone()
        if exists:
            abort(403)
        abort(404)

    return render_template('application_details.html',
                           application=application,
                           status_label=normalize_status_label(application['status']),
                           status_badge_class=status_badge_class(application['status']),
                           timeline=build_application_timeline(application['status']))


@app.route('/profile')
def profile():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    db = get_db()
    user = db.execute('SELECT * FROM users WHERE id = ?', (session['user_id'],)).fetchone()
    applications = db.execute('''
        SELECT applications.*, jobs.title, jobs.company
        FROM applications 
        JOIN jobs ON applications.job_id = jobs.id 
        WHERE applications.user_id = ?
        ORDER BY applications.applied_at DESC
    ''', (session['user_id'],)).fetchall()
    return render_template('profile.html', user=user, applications=applications)

@app.route('/update_profile', methods=['POST'])
def update_profile():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    name = request.form.get('name', '').strip()
    skills = request.form.get('skills', '').strip()

    if not name:
        flash('Name cannot be empty.')
        return redirect(url_for('profile'))

    db = get_db()
    db.execute('UPDATE users SET name = ?, skills = ? WHERE id = ?',
              (name, skills, session['user_id']))
    db.commit()
    session['user_name'] = name
    flash('Profile updated successfully!')
    return redirect(url_for('profile'))

@app.route('/freelance')
def freelance():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    db = get_db()
    accepted = {
        row['task_id']: dict(row) for row in db.execute(
            'SELECT task_id, status, accepted_at FROM freelance_acceptances WHERE user_id = ?',
            (session['user_id'],)
        ).fetchall()
    }
    tasks = [{**task, 'acceptance': accepted.get(task['id'])} for task in FREELANCE_TASKS]
    return render_template('freelance.html', tasks=tasks,
                           accepted_tasks=[{**freelance_task_by_id(task_id), **record}
                                           for task_id, record in accepted.items()
                                           if freelance_task_by_id(task_id)])


@app.route('/freelance/accept/<task_id>', methods=['POST'])
def accept_freelance_task(task_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    if freelance_task_by_id(task_id) is None:
        abort(404)
    db = get_db()
    db.execute('''INSERT OR IGNORE INTO freelance_acceptances (user_id, task_id)
                  VALUES (?, ?)''', (session['user_id'], task_id))
    db.commit()
    flash('Task accepted successfully!')
    return redirect(url_for('freelance'))


@app.route('/employer/register', methods=['GET', 'POST'])
def employer_register():
    if request.method == 'POST':
        company_name = request.form.get('company_name', '').strip()
        email = request.form.get('email', '').strip().lower()
        phone = request.form.get('phone', '').strip()
        password = request.form.get('password', '')
        company_description = request.form.get('company_description', '').strip()
        if not company_name or not email or not password:
            flash('Company name, email, and password are required.')
        elif not valid_email(email):
            flash('Please enter a valid company email.')
        elif len(password) < 6:
            flash('Password must be at least 6 characters.')
        else:
            db = get_db()
            try:
                db.execute('''INSERT INTO employers
                    (company_name, email, password, phone, company_description)
                    VALUES (?, ?, ?, ?, ?)''',
                    (company_name, email, generate_password_hash(password), phone, company_description))
                db.commit()
                flash('Employer registration successful. Please log in.')
                return redirect(url_for('employer_login'))
            except sqlite3.IntegrityError:
                flash('An employer account with that email already exists.')
    return render_template('employer_register.html')


@app.route('/employer/login', methods=['GET', 'POST'])
def employer_login():
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        db = get_db()
        employer = db.execute('SELECT * FROM employers WHERE email = ?', (email,)).fetchone()
        if employer and check_password_hash(employer['password'], password):
            session.clear()
            session['employer_id'] = employer['id']
            session['employer_name'] = employer['company_name']
            return redirect(url_for('employer_dashboard'))
        flash('Invalid employer email or password.')
    return render_template('employer_login.html')


@app.route('/employer/logout')
def employer_logout():
    session.clear()
    return redirect(url_for('home'))


@app.route('/employer/dashboard')
@employer_required
def employer_dashboard():
    db = get_db()
    employer = db.execute('SELECT * FROM employers WHERE id = ?', (session['employer_id'],)).fetchone()
    if not employer:
        return employer_logout()
    stats = db.execute('''
        SELECT COUNT(DISTINCT jobs.id) AS jobs_count,
               COUNT(applications.id) AS applicants_count,
               COALESCE(SUM(CASE WHEN applications.status = 'Pending' THEN 1 ELSE 0 END), 0) AS pending_count,
               COALESCE(SUM(CASE WHEN applications.status = 'Shortlisted' THEN 1 ELSE 0 END), 0) AS shortlisted_count
        FROM jobs LEFT JOIN applications ON applications.job_id = jobs.id
        WHERE jobs.employer_id = ?
    ''', (session['employer_id'],)).fetchone()
    return render_template('employer_dashboard.html', employer=employer, stats=stats)


@app.route('/employer/post-job', methods=['GET', 'POST'])
@employer_required
def employer_post_job():
    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        description = request.form.get('description', '').strip()
        skill_required = request.form.get('skill_required', '').strip()
        location = request.form.get('location', '').strip()
        job_type = request.form.get('job_type', '').strip()
        salary = request.form.get('salary', '').strip()
        if not title or not skill_required:
            flash('Job title and required skill are required.')
        else:
            db = get_db()
            employer = db.execute('SELECT company_name FROM employers WHERE id = ?', (session['employer_id'],)).fetchone()
            if not employer:
                return employer_logout()
            db.execute('''INSERT INTO jobs
                (title, company, skill_required, description, employer_id, location, job_type, salary, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)''',
                (title, employer['company_name'], skill_required, description,
                 session['employer_id'], location, job_type, salary))
            db.commit()
            flash('Job posted successfully.')
            return redirect(url_for('employer_jobs'))
    return render_template('employer_post_job.html', job=None)


@app.route('/employer/jobs')
@employer_required
def employer_jobs():
    db = get_db()
    jobs = db.execute('''
        SELECT jobs.*, COUNT(applications.id) AS applicant_count
        FROM jobs LEFT JOIN applications ON applications.job_id = jobs.id
        WHERE jobs.employer_id = ?
        GROUP BY jobs.id ORDER BY COALESCE(jobs.created_at, '') DESC, jobs.id DESC
    ''', (session['employer_id'],)).fetchall()
    jobs = [dict(job, **analyze_job(job)) for job in jobs]
    return render_template('employer_jobs.html', jobs=jobs)


def owned_job(db, job_id):
    return db.execute('SELECT * FROM jobs WHERE id = ? AND employer_id = ?',
                      (job_id, session['employer_id'])).fetchone()


@app.route('/employer/job/<int:job_id>/edit', methods=['GET', 'POST'])
@employer_required
def employer_edit_job(job_id):
    db = get_db()
    job = owned_job(db, job_id)
    if not job:
        flash('Job not found or you do not have permission to edit it.')
        return redirect(url_for('employer_jobs'))
    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        skill_required = request.form.get('skill_required', '').strip()
        if not title or not skill_required:
            flash('Job title and required skill are required.')
        else:
            db.execute('''UPDATE jobs SET title = ?, description = ?, skill_required = ?,
                location = ?, job_type = ?, salary = ? WHERE id = ? AND employer_id = ?''',
                (title, request.form.get('description', '').strip(), skill_required,
                 request.form.get('location', '').strip(), request.form.get('job_type', '').strip(),
                 request.form.get('salary', '').strip(), job_id, session['employer_id']))
            db.commit()
            flash('Job updated successfully.')
            return redirect(url_for('employer_jobs'))
    return render_template('employer_post_job.html', job=job)


@app.route('/employer/job/<int:job_id>/delete', methods=['POST'])
@employer_required
def employer_delete_job(job_id):
    db = get_db()
    if not owned_job(db, job_id):
        flash('Job not found or you do not have permission to delete it.')
        return redirect(url_for('employer_jobs'))
    db.execute('DELETE FROM applications WHERE job_id = ?', (job_id,))
    db.execute('DELETE FROM jobs WHERE id = ? AND employer_id = ?', (job_id, session['employer_id']))
    db.commit()
    flash('Job deleted successfully.')
    return redirect(url_for('employer_jobs'))


@app.route('/employer/job/<int:job_id>/applicants')
@employer_required
def employer_applicants(job_id):
    db = get_db()
    job = owned_job(db, job_id)
    if not job:
        flash('Job not found or you do not have permission to view its applicants.')
        return redirect(url_for('employer_jobs'))
    applicants = db.execute('''
        SELECT applications.*, users.name, users.email, users.skills
        FROM applications JOIN users ON applications.user_id = users.id
        WHERE applications.job_id = ? ORDER BY applications.applied_at DESC, applications.id DESC
    ''', (job_id,)).fetchall()
    return render_template('employer_applicants.html', job=job, applicants=applicants)


@app.route('/employer/application/<int:application_id>/status', methods=['POST'])
@employer_required
def employer_update_application_status(application_id):
    status = request.form.get('status', '')
    allowed_statuses = {'Pending', 'Applied', 'Under Review', 'Shortlisted', 'Interview', 'Selected', 'Rejected', 'Accepted'}
    if status not in allowed_statuses:
        flash('Invalid application status.')
        return redirect(url_for('employer_jobs'))
    db = get_db()
    application = db.execute('''
        SELECT applications.id, jobs.id AS job_id FROM applications
        JOIN jobs ON applications.job_id = jobs.id
        WHERE applications.id = ? AND jobs.employer_id = ?
    ''', (application_id, session['employer_id'])).fetchone()
    if not application:
        flash('Application not found or you do not have permission to update it.')
        return redirect(url_for('employer_jobs'))
    db.execute('UPDATE applications SET status = ? WHERE id = ?', (status, application_id))
    db.commit()
    flash('Application status updated.')
    return redirect(url_for('employer_applicants', job_id=application['job_id']))


@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        db = get_db()
        admin = db.execute('SELECT id, email, password FROM admins WHERE email = ?', (email,)).fetchone()
        if admin and check_password_hash(admin['password'], password):
            session.clear()
            session['admin_id'] = admin['id']
            session['admin_email'] = admin['email']
            return redirect(url_for('admin_dashboard'))
        flash('Invalid admin email or password.')
    return render_template('admin_login.html')


@app.route('/admin/logout')
def admin_logout():
    session.clear()
    return redirect(url_for('admin_login'))


@app.route('/admin')
@app.route('/admin/dashboard')
@admin_required
def admin_dashboard():
    db = get_db()
    stats = {
        'users': db.execute('SELECT COUNT(*) AS count FROM users').fetchone()['count'],
        'employers': db.execute('SELECT COUNT(*) AS count FROM employers').fetchone()['count'],
        'pending_employers': db.execute("SELECT COUNT(*) AS count FROM employers WHERE COALESCE(verification_status, 'Pending') = 'Pending'").fetchone()['count'],
        'jobs': db.execute('SELECT COUNT(*) AS count FROM jobs').fetchone()['count'],
        'applications': db.execute('SELECT COUNT(*) AS count FROM applications').fetchone()['count'],
    }
    employers = db.execute('''
        SELECT id, company_name, email, phone, company_description,
               COALESCE(verification_status, 'Pending') AS verification_status, created_at
        FROM employers ORDER BY id DESC
    ''').fetchall()
    jobs = db.execute('''
        SELECT jobs.id, jobs.title, jobs.company, jobs.skill_required, jobs.location,
               jobs.job_type, jobs.salary, COALESCE(employers.verification_status, '') AS verification_status
        FROM jobs LEFT JOIN employers ON jobs.employer_id = employers.id
        ORDER BY jobs.id DESC
    ''').fetchall()
    jobs = [dict(job, **analyze_job(job)) for job in jobs]
    high_risk_jobs = [job for job in jobs if job['risk_level'] == 'High Risk']
    applications = db.execute('''
        SELECT applications.id, applications.status, applications.applied_at,
               users.name AS user_name, users.email AS user_email,
               jobs.title AS job_title, jobs.company
        FROM applications
        LEFT JOIN users ON applications.user_id = users.id
        LEFT JOIN jobs ON applications.job_id = jobs.id
        ORDER BY applications.id DESC
    ''').fetchall()
    users = db.execute('SELECT id, name, email, skills FROM users ORDER BY id DESC').fetchall()
    return render_template('admin_dashboard.html', stats=stats, employers=employers,
                           jobs=jobs, high_risk_jobs=high_risk_jobs,
                           applications=applications, users=users)


@app.route('/admin/employers/<int:employer_id>/verification', methods=['POST'])
@admin_required
def admin_update_employer_verification(employer_id):
    status = request.form.get('status', '')
    if status not in {'Verified', 'Rejected'}:
        flash('Invalid verification status.')
        return redirect(url_for('admin_dashboard'))
    db = get_db()
    employer = db.execute('SELECT id FROM employers WHERE id = ?', (employer_id,)).fetchone()
    if not employer:
        flash('Employer not found.')
        return redirect(url_for('admin_dashboard'))
    db.execute('UPDATE employers SET verification_status = ? WHERE id = ?', (status, employer_id))
    db.commit()
    flash('Employer verification updated.')
    return redirect(url_for('admin_dashboard'))


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('home'))

if __name__ == '__main__':
    app.run(debug=os.environ.get('HERSPHERE_DEBUG') == '1')
# HerSphere

### Women-Focused Employment & Empowerment Platform

HerSphere is a full-stack web platform designed to support women's employment, skill development, workplace safety, and community engagement.

It combines job discovery, explainable skill-based recommendations, employer verification, rule-based scam detection, application tracking, learning resources, freelance opportunities, voice applications, and community features in one platform.

## Problem

Job seekers need one place to discover opportunities, build practical skills, track applications, and connect with a supportive community.

## Solution

HerSphere combines a Flask job portal with explainable skill matching, job-safety checks, employer verification, learning progress, application tracking, and community interactions.

## Features

- User registration and login
- Explainable skill-based job recommendations with match percentages
- Rule-based job scam and fraud risk detection
- Employer registration, job management, and admin verification
- Verified employer badges
- Job search, filters, sorting, saved jobs, and applications
- Application status tracking and timeline
- Voice-based job applications
- Learning Hub courses, lessons, and per-user progress
- Women community posts, likes, comments, and reports
- Freelance micro tasks
- User profile management
- Admin dashboard with platform statistics and moderation visibility

## Tech Stack

- Backend: Python Flask
- Frontend: HTML, CSS, JavaScript
- Database: SQLite

## Architecture

Flask routes handle authentication, user and employer workflows, admin verification, recommendations, learning progress, and community actions. Jinja templates in `templetes/` render the views, shared styling is in `static/style.css`, and SQLite stores application data in `hersphere.db`.

Recommendations and scam detection are deterministic, explainable rule-based services implemented in `app.py`; no machine-learning model or external API is required.

## Project Structure

```text
HerSphere/
├── app.py
├── requirements.txt
├── verify_app_tracking.py
├── README.md
├── .gitignore
├── static/
│   └── style.css
└── templetes/
    ├── index.html
    ├── login.html
    ├── register.html
    ├── dashboard.html
    └── ...
```

> Note: The project intentionally uses the existing `templetes/` folder name.

## Environment Variables

The following environment variables configure optional and security-sensitive behaviour. **Do not put real secrets into version control.**

| Variable | Purpose | Default |
|---|---|---|
| `HERSPHERE_SECRET_KEY` | Flask session signing key. Set a long random string in production so sessions survive restarts. | Random token generated each startup |
| `HERSPHERE_ADMIN_EMAIL` | Email address of the admin account created on first startup. | `admin@hersphere.local` |
| `HERSPHERE_ADMIN_PASSWORD` | Password for the admin account. **Must be set** to provision the admin login. | *(no admin account created if unset)* |
| `HERSPHERE_DEBUG` | Set to `1` to enable Flask debug mode. **Never enable in production.** | Off (`0`) |

### Example — Linux/macOS

```bash
export HERSPHERE_SECRET_KEY="replace-with-a-long-random-string"
export HERSPHERE_ADMIN_EMAIL="admin@example.com"
export HERSPHERE_ADMIN_PASSWORD="replace-with-a-strong-password"
```

### Example — Windows PowerShell

```powershell
$env:HERSPHERE_SECRET_KEY = "replace-with-a-long-random-string"
$env:HERSPHERE_ADMIN_EMAIL = "admin@example.com"
$env:HERSPHERE_ADMIN_PASSWORD = "replace-with-a-strong-password"
```

## Installation

1. Install Python 3.x.
2. Install dependencies:

```bash
pip install -r requirements.txt
```

## Running the Application

1. Run the Flask app:

```bash
python app.py
```

2. Open your browser and go to:

`http://127.0.0.1:5000`

## Usage

1. Register a new account.
2. Login to access the dashboard.
3. Browse jobs, learn skills, join the community, or take freelance tasks.
4. Apply for jobs using text or voice.

## Database

The application uses the existing `hersphere.db` SQLite database. On startup, required tables are created if missing and existing records are preserved.

Set `HERSPHERE_SECRET_KEY` for a stable production session key and `HERSPHERE_ADMIN_PASSWORD` when provisioning an admin account.

## Future Scope

Possible future improvements include richer course authoring, stronger operational monitoring, and expanded moderation workflows.

## Voice Application

Click **"Speak Application"** to record a voice application using the browser microphone. The recording is stored as an audio file and submitted with the job application. Authorized applicants and employers can play the submitted recording.

from flask import Flask, render_template, request, redirect, url_for
from datetime import datetime, time
from sqlalchemy import inspect, text
from models import db, Student, Settings, History, BreakSchedule

app = Flask(__name__)
app.config['SECRET_KEY'] = 'classroom_kiosk_secret_key'  # Change this in production!
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///classroom_kiosk.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Initialise the database
db.init_app(app)

MAX_OFFSET_MINUTES = 180


def normalize_optional_limit(raw_value):
    """Normalize optional positive integer settings values."""
    value = (raw_value or '').strip()
    if not value:
        return None

    try:
        parsed = int(value)
    except ValueError:
        return None

    return parsed if parsed > 0 else None


def ensure_settings_columns():
    """Add new optional Settings columns for existing SQLite installs."""
    inspector = inspect(db.engine)
    columns = {column['name'] for column in inspector.get_columns('settings')}
    statements = []

    if 'max_daily_visits' not in columns:
        statements.append('ALTER TABLE settings ADD COLUMN max_daily_visits INTEGER')

    if 'max_session_visits' not in columns:
        statements.append('ALTER TABLE settings ADD COLUMN max_session_visits INTEGER')

    for statement in statements:
        db.session.execute(text(statement))

    if statements:
        db.session.commit()

def init_db():
    """Initialise the database with required tables and default data"""
    with app.app_context():
        # Create all tables
        db.create_all()
        ensure_settings_columns()

        # Create default settings if not exists
        if not Settings.query.first():
            default_settings = Settings(
                id=1,
                max_students=2,
                max_daily_visits=None,
                max_session_visits=None
            )
            db.session.add(default_settings)
            db.session.commit()


def get_settings():
    """Return the singleton settings row, creating defaults when needed."""
    settings = Settings.query.first()
    if settings:
        return settings

    settings = Settings(
        id=1,
        max_students=2,
        max_daily_visits=None,
        max_session_visits=None
    )
    db.session.add(settings)
    db.session.commit()
    return settings


def get_max_students():
    """Get the maximum number of students allowed out."""
    return get_settings().max_students


def get_visit_limits():
    """Get optional visit limit settings."""
    settings = get_settings()
    return {
        'daily': settings.max_daily_visits,
        'session': settings.max_session_visits
    }

def get_students_out_count():
    """Get count of students currently out"""
    return Student.query.filter_by(is_out=True).count()


def minutes_from_time(value):
    """Convert a time object to minute-of-day."""
    return (value.hour * 60) + value.minute


def time_from_minutes(total_minutes):
    """Convert minute-of-day to time object."""
    normalized_minutes = total_minutes % 1440
    return time(hour=normalized_minutes // 60, minute=normalized_minutes % 60)


def format_time(value):
    """Format a time object in 24-hour HH:MM format."""
    return value.strftime('%H:%M')


def is_minute_in_window(current_minute, window_start_minute, window_end_minute):
    """Check if a minute-of-day falls inside a possibly midnight-crossing window."""
    if window_start_minute <= window_end_minute:
        return window_start_minute <= current_minute <= window_end_minute
    return current_minute >= window_start_minute or current_minute <= window_end_minute


def find_next_unblocked_minute(current_minute, windows):
    """Find the next minute where none of the blockout windows apply."""
    for offset in range(1, 1441):
        candidate = (current_minute + offset) % 1440
        if not any(
            is_minute_in_window(candidate, start_minute, end_minute)
            for start_minute, end_minute in windows
        ):
            return candidate
    return None


def get_blockout_status(now=None):
    """Return whether sign-out is currently blocked by break windows."""
    if now is None:
        now = datetime.now()

    schedules = BreakSchedule.query.filter_by(enabled=True).all()
    if not schedules:
        return {
            'active': False,
            'active_names': [],
            'next_available_time': None
        }

    current_minute = minutes_from_time(now.time())
    windows = []
    active_schedules = []

    for schedule in schedules:
        break_start_minute = minutes_from_time(schedule.start_time)
        break_end_minute = minutes_from_time(schedule.end_time)
        block_start_minute = (
            break_start_minute - schedule.offset_before_minutes
        ) % 1440
        block_end_minute = (
            break_end_minute + schedule.offset_after_minutes
        ) % 1440

        windows.append((block_start_minute, block_end_minute))

        if is_minute_in_window(current_minute, block_start_minute, block_end_minute):
            active_schedules.append(schedule)

    if not active_schedules:
        return {
            'active': False,
            'active_names': [],
            'next_available_time': None
        }

    active_names = sorted({schedule.name for schedule in active_schedules})
    next_available_minute = find_next_unblocked_minute(current_minute, windows)
    if next_available_minute is None:
        next_available_time = None
    else:
        next_available_time = format_time(time_from_minutes(next_available_minute))

    return {
        'active': True,
        'active_names': active_names,
        'next_available_time': next_available_time
    }


def get_current_session_boundary(now=None):
    """Return metadata describing the start of the current teaching session."""
    if now is None:
        now = datetime.now()

    session_start = datetime.combine(now.date(), time.min)
    latest_schedule_name = None
    schedules = BreakSchedule.query.filter_by(enabled=True).all()

    for schedule in schedules:
        break_end_at = datetime.combine(now.date(), schedule.end_time)
        if schedule.start_time > schedule.end_time:
            break_end_at = datetime.combine(now.date(), schedule.end_time)

        if break_end_at <= now and break_end_at > session_start:
            session_start = break_end_at
            latest_schedule_name = schedule.name

    return {
        'start': session_start,
        'source_schedule_name': latest_schedule_name
    }


def get_visit_counts(student_name, now=None):
    """Return daily and current-session visit counts for a student."""
    if now is None:
        now = datetime.now()

    start_of_day = datetime.combine(now.date(), time.min)
    session_boundary = get_current_session_boundary(now)
    session_start = session_boundary['start']

    daily_count = History.query.filter(
        History.student_name == student_name,
        History.sign_out_time >= start_of_day,
        History.sign_out_time <= now
    ).count()

    session_count = History.query.filter(
        History.student_name == student_name,
        History.sign_out_time >= session_start,
        History.sign_out_time <= now
    ).count()

    return {
        'daily': daily_count,
        'session': session_count,
        'session_start': session_start,
        'session_source_schedule_name': session_boundary['source_schedule_name']
    }


def get_student_limit_status(student, now=None, visit_limits=None):
    """Return whether a student has reached optional visit limits."""
    if now is None:
        now = datetime.now()

    if visit_limits is None:
        visit_limits = get_visit_limits()

    counts = get_visit_counts(student.name, now)
    blocked_reason = None

    if visit_limits['daily'] and counts['daily'] >= visit_limits['daily']:
        blocked_reason = 'Daily limit reached'
    elif visit_limits['session'] and counts['session'] >= visit_limits['session']:
        blocked_reason = 'Session limit reached'

    return {
        'daily_count': counts['daily'],
        'session_count': counts['session'],
        'daily_limit': visit_limits['daily'],
        'session_limit': visit_limits['session'],
        'session_start': counts['session_start'],
        'session_source_schedule_name': counts['session_source_schedule_name'],
        'limit_reached': blocked_reason is not None,
        'blocked_reason': blocked_reason
    }


def build_student_statuses(students, now=None, visit_limits=None):
    """Build per-student kiosk status metadata for the index template."""
    statuses = {}

    for student in students:
        statuses[student.id] = get_student_limit_status(student, now, visit_limits)

    return statuses


def can_student_sign_out(student, now=None, visit_limits=None):
    """Return whether a student can sign out right now."""
    if student.is_out:
        return False, 'Student already out'

    blockout_status = get_blockout_status(now)
    if blockout_status['active']:
        return False, 'Sign-out blocked during break window'

    if get_students_out_count() >= get_max_students():
        return False, 'Toilet full'

    limit_status = get_student_limit_status(student, now, visit_limits)
    if limit_status['limit_reached']:
        return False, limit_status['blocked_reason']

    return True, None


def redirect_admin(message, message_type='success'):
    """Redirect to admin page with one-shot status message."""
    return redirect(url_for('admin', message=message, message_type=message_type))


def parse_schedule_form(form_data):
    """Validate and parse break schedule form values."""
    name = form_data.get('name', '').strip()
    start_time_raw = form_data.get('start_time', '').strip()
    end_time_raw = form_data.get('end_time', '').strip()

    if not name:
        return None, 'Schedule name is required.'

    try:
        start_time = datetime.strptime(start_time_raw, '%H:%M').time()
        end_time = datetime.strptime(end_time_raw, '%H:%M').time()
    except ValueError:
        return None, 'Start and end times must be valid 24-hour times.'

    if start_time == end_time:
        return None, 'Start and end times cannot be the same.'

    try:
        offset_before_minutes = int(form_data.get('offset_before_minutes', '0'))
        offset_after_minutes = int(form_data.get('offset_after_minutes', '0'))
    except ValueError:
        return None, 'Offsets must be whole numbers.'

    if offset_before_minutes < 0 or offset_after_minutes < 0:
        return None, 'Offsets cannot be negative.'

    if offset_before_minutes > MAX_OFFSET_MINUTES or offset_after_minutes > MAX_OFFSET_MINUTES:
        return None, f'Offsets must be {MAX_OFFSET_MINUTES} minutes or less.'

    parsed = {
        'name': name,
        'start_time': start_time,
        'end_time': end_time,
        'offset_before_minutes': offset_before_minutes,
        'offset_after_minutes': offset_after_minutes,
        'enabled': form_data.get('enabled') == 'on'
    }
    return parsed, None

@app.route('/')
def index():
    """Main student-facing page"""
    now = datetime.now()
    students = Student.query.order_by(Student.name).all()
    max_students = get_max_students()
    visit_limits = get_visit_limits()
    students_out_count = get_students_out_count()
    blockout_status = get_blockout_status(now)
    is_full = students_out_count >= max_students
    student_statuses = build_student_statuses(students, now, visit_limits)

    return render_template('index.html',
                         students=students,
                         student_statuses=student_statuses,
                         max_students=max_students,
                         max_daily_visits=visit_limits['daily'],
                         max_session_visits=visit_limits['session'],
                         students_out_count=students_out_count,
                         is_full=is_full,
                         blockout_active=blockout_status['active'],
                         is_sign_out_blocked=(is_full or blockout_status['active']))

@app.route('/sign_out/<int:student_id>')
def sign_out(student_id):
    """Sign out a student"""
    student = Student.query.get_or_404(student_id)
    now = datetime.now()
    visit_limits = get_visit_limits()
    can_sign_out, _ = can_student_sign_out(student, now, visit_limits)
    if not can_sign_out:
        return redirect(url_for('index'))

    # Update student status
    student.is_out = True
    student.time_out = now

    # Add to history
    history_record = History(
        student_name=student.name,
        sign_out_time=now
    )

    db.session.add(history_record)
    db.session.commit()

    return redirect(url_for('index'))

@app.route('/sign_in/<int:student_id>')
def sign_in(student_id):
    """Sign in a student"""
    student = Student.query.get_or_404(student_id)

    if student.is_out and student.time_out:
        now = datetime.now()

        # Calculate duration
        duration = now - student.time_out
        duration_minutes = int(duration.total_seconds() / 60)

        # Update history record
        history_record = History.query.filter_by(
            student_name=student.name,
            sign_in_time=None
        ).order_by(History.sign_out_time.desc()).first()

        if history_record:
            history_record.sign_in_time = now
            history_record.duration_minutes = duration_minutes

        # Update student status
        student.is_out = False
        student.time_out = None

        db.session.commit()

    return redirect(url_for('index'))

@app.route('/admin')
def admin():
    """Admin page"""
    now = datetime.now()
    students = Student.query.order_by(Student.name).all()
    settings = get_settings()
    max_students = settings.max_students
    current_session_boundary = get_current_session_boundary(now)
    visit_limits = {
        'daily': settings.max_daily_visits,
        'session': settings.max_session_visits
    }
    student_statuses = build_student_statuses(students, now, visit_limits)
    schedules = BreakSchedule.query.order_by(BreakSchedule.start_time.asc()).all()
    message = request.args.get('message', '')
    message_type = request.args.get('message_type', 'info')

    return render_template('admin.html',
                         students=students,
                         student_statuses=student_statuses,
                         max_students=max_students,
                         max_daily_visits=settings.max_daily_visits,
                         max_session_visits=settings.max_session_visits,
                         current_session_boundary=current_session_boundary,
                         schedules=schedules,
                         message=message,
                         message_type=message_type)

@app.route('/admin/add_student', methods=['POST'])
def add_student():
    """Add a new student"""
    name = request.form['name'].strip()

    if name:
        # Check if student already exists
        existing_student = Student.query.filter_by(name=name).first()
        if not existing_student:
            student = Student(name=name)
            db.session.add(student)
            db.session.commit()

    return redirect(url_for('admin'))

@app.route('/admin/remove_student/<int:student_id>')
def remove_student(student_id):
    """Remove a student"""
    student = Student.query.get_or_404(student_id)
    db.session.delete(student)
    db.session.commit()

    return redirect(url_for('admin'))

@app.route('/admin/set_max_students', methods=['POST'])
def set_max_students():
    """Update kiosk settings, including optional visit limits."""
    try:
        max_students = int(request.form['max_students'])
    except (TypeError, ValueError):
        return redirect_admin('Maximum students must be a whole number.', 'danger')

    if max_students <= 0:
        return redirect_admin('Maximum students must be greater than zero.', 'danger')

    settings = get_settings()
    settings.max_students = max_students
    settings.max_daily_visits = normalize_optional_limit(
        request.form.get('max_daily_visits')
    )
    settings.max_session_visits = normalize_optional_limit(
        request.form.get('max_session_visits')
    )

    db.session.commit()

    return redirect(url_for('admin'))


@app.route('/admin/add_blockout_schedule', methods=['POST'])
def add_blockout_schedule():
    """Add a break schedule used for sign-out blockout windows."""
    parsed, error = parse_schedule_form(request.form)
    if error:
        return redirect_admin(error, 'danger')

    schedule = BreakSchedule(
        name=parsed['name'],
        start_time=parsed['start_time'],
        end_time=parsed['end_time'],
        offset_before_minutes=parsed['offset_before_minutes'],
        offset_after_minutes=parsed['offset_after_minutes'],
        enabled=parsed['enabled']
    )
    db.session.add(schedule)
    db.session.commit()

    return redirect_admin('Blockout schedule added.')


@app.route('/admin/update_blockout_schedule/<int:schedule_id>', methods=['POST'])
def update_blockout_schedule(schedule_id):
    """Update an existing break schedule."""
    schedule = BreakSchedule.query.get_or_404(schedule_id)
    parsed, error = parse_schedule_form(request.form)
    if error:
        return redirect_admin(error, 'danger')

    schedule.name = parsed['name']
    schedule.start_time = parsed['start_time']
    schedule.end_time = parsed['end_time']
    schedule.offset_before_minutes = parsed['offset_before_minutes']
    schedule.offset_after_minutes = parsed['offset_after_minutes']
    schedule.enabled = parsed['enabled']
    db.session.commit()

    return redirect_admin('Blockout schedule updated.')


@app.route('/admin/remove_blockout_schedule/<int:schedule_id>')
def remove_blockout_schedule(schedule_id):
    """Delete a break schedule."""
    schedule = BreakSchedule.query.get_or_404(schedule_id)
    db.session.delete(schedule)
    db.session.commit()

    return redirect_admin('Blockout schedule removed.')

@app.route('/admin/history')
def history():
    """View history page"""
    search = request.args.get('search', '')

    if search:
        history_records = History.query.filter(
            History.student_name.like(f'%{search}%')
        ).order_by(History.sign_out_time.desc()).all()
    else:
        history_records = History.query.order_by(
            History.sign_out_time.desc()
        ).all()

    # Format records for display
    formatted_records = []
    for record in history_records:
        record_dict = {
            'id': record.id,
            'student_name': record.student_name,
            'sign_out_time': record.sign_out_time,
            'sign_in_time': record.sign_in_time,
            'duration_minutes': record.duration_minutes,
            'sign_out_formatted': record.sign_out_time.strftime('%Y-%m-%d %H:%M'),
            'sign_in_formatted': record.sign_in_time.strftime('%Y-%m-%d %H:%M') if record.sign_in_time else 'Still out'
        }
        formatted_records.append(record_dict)

    return render_template('history.html', 
                         records=formatted_records, 
                         search=search)

if __name__ == '__main__':
    # Initialise database
    init_db()
    app.run(debug=True, host='0.0.0.0', port=5000)
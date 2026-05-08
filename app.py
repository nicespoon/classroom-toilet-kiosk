from flask import Flask, render_template, request, redirect, url_for
from datetime import datetime, time
from models import db, Student, Settings, History, BreakSchedule

app = Flask(__name__)
app.config['SECRET_KEY'] = 'classroom_kiosk_secret_key'  # Change this in production!
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///classroom_kiosk.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Initialise the database
db.init_app(app)

MAX_OFFSET_MINUTES = 180

def init_db():
    """Initialise the database with required tables and default data"""
    with app.app_context():
        # Create all tables
        db.create_all()

        # Create default settings if not exists
        if not Settings.query.first():
            default_settings = Settings(id=1, max_students=2)
            db.session.add(default_settings)
            db.session.commit()

def get_max_students():
    """Get the maximum number of students allowed out"""
    settings = Settings.query.first()
    return settings.max_students if settings else 2

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
    students = Student.query.order_by(Student.name).all()
    max_students = get_max_students()
    students_out_count = get_students_out_count()
    blockout_status = get_blockout_status()
    is_full = students_out_count >= max_students

    return render_template('index.html',
                         students=students,
                         max_students=max_students,
                         students_out_count=students_out_count,
                         is_full=is_full,
                         blockout_active=blockout_status['active'],
                         is_sign_out_blocked=(is_full or blockout_status['active']))

@app.route('/sign_out/<int:student_id>')
def sign_out(student_id):
    """Sign out a student"""
    blockout_status = get_blockout_status()
    if blockout_status['active']:
        return redirect(url_for('index'))

    max_students = get_max_students()
    students_out_count = get_students_out_count()

    if students_out_count >= max_students:
        return redirect(url_for('index'))

    student = Student.query.get_or_404(student_id)
    if student.is_out:
        return redirect(url_for('index'))

    now = datetime.now()

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
    students = Student.query.order_by(Student.name).all()
    max_students = get_max_students()
    schedules = BreakSchedule.query.order_by(BreakSchedule.start_time.asc()).all()
    message = request.args.get('message', '')
    message_type = request.args.get('message_type', 'info')

    return render_template('admin.html',
                         students=students,
                         max_students=max_students,
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
    """Set maximum number of students"""
    max_students = int(request.form['max_students'])

    if max_students > 0:
        settings = Settings.query.first()
        if not settings:
            settings = Settings(id=1, max_students=max_students)
            db.session.add(settings)
        else:
            settings.max_students = max_students

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
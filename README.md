# Classroom Toilet Sign-Out Kiosk

A clean, minimal Flask application for primary classroom toilet management.

![Classroom Toilet Sign-Out Kiosk](images/demo.gif)

## Features

### Student Interface (`/`)
- Large, touchscreen-friendly buttons for each student name
- Clear visual indication when toilet is at capacity
- Clean, minimal design

### Admin Interface (`/admin`)
- Add and remove students
- Configure maximum students allowed out
- View current student status
- Access to visit history

### History (`/admin/history`)
- Complete log of all toilet visits
- Search and filter by student name
- Duration tracking
- Quick statistics

## Quick Start

1. Clone the repository:
   ```
   git clone https://github.com/nicespoon/classroom-toilet-kiosk.git
   cd classroom-toilet-kiosk
   ```

2. Create and activate a virtual environment:
   ```
   python3 -m venv venv
   source venv/bin/activate
   ```

3. Install dependencies:
   ```
   pip install -r requirements.txt
   ```

4. Run the application:
   ```
   python app.py
   ```

5. Open your browser:
   - Main app: http://localhost:5000
   - Admin panel: http://localhost:5000/admin

6. Setup:
   - Go to admin panel to add students
   - Set maximum students allowed out
   - Students can now use the main page

## Technical Details

- Built with Flask (Python web framework)
- SQLite database (automatically created)
- HTMX for dynamic updates (no JavaScript needed)
- Bootstrap for responsive design

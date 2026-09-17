# Smart College Complaint System

A diploma-level web application built with Python Flask + SQLite + HTML/CSS/JavaScript.

## Features
- Student, staff, and admin login
- Student complaint submission
- Complaint ID generation
- Optional image upload
- Automatic priority suggestion
- Admin complaint dashboard
- Assign complaints to staff
- Staff status updates and resolution notes
- Student complaint tracking
- Feedback/rating after resolution
- Admin analytics
- Overdue/escalation flag
- Simple notification system
- Search and filtering

## Demo accounts
- Admin: admin@college.com / admin123
- Staff: staff@college.com / staff123
- Student: student@college.com / student123

Change these passwords before using the system outside a demo.

## Run on Windows
1. Install Python 3.10+.
2. Open Command Prompt in this project folder.
3. Create a virtual environment:
   python -m venv venv
4. Activate it:
   venv\Scripts\activate
5. Install packages:
   pip install -r requirements.txt
6. Start:
   python app.py
7. Open:
   http://127.0.0.1:5000

The SQLite database `complaints.db` is created automatically on first run.

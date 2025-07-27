#!/usr/bin/env python3
"""Create a test user for the application"""

from app import app
from models import db, User
from decimal import Decimal

def create_test_user():
    with app.app_context():
        # Check if test user already exists
        existing_user = User.query.filter_by(username='test').first()
        if existing_user:
            print("Test user already exists")
            return
        
        # Create test user
        test_user = User(
            username='test',
            email='test@example.com',
            balance=Decimal('1000.00'),
            is_recipient=False
        )
        test_user.set_password('test123')
        
        db.session.add(test_user)
        db.session.commit()
        
        print("Test user created successfully:")
        print("Username: test")
        print("Password: test123")
        print("Email: test@example.com")

if __name__ == '__main__':
    create_test_user()

#!/usr/bin/env python3
"""Fix database issues and create test users"""

from app import app
from models import db, User
from decimal import Decimal

def fix_database():
    with app.app_context():
        # Create tables if they don't exist
        db.create_all()
        
        # Check if we have any users
        user_count = User.query.count()
        print(f"Current user count: {user_count}")
        
        if user_count == 0:
            print("Creating test users...")
            
            # Create admin user
            admin = User(
                username='admin',
                email='admin@test.com',
                balance=Decimal('1000.00'),
                is_recipient=True
            )
            admin.set_password('admin123')
            
            # Create regular user
            user = User(
                username='user',
                email='user@test.com',
                balance=Decimal('500.00'),
                is_recipient=False
            )
            user.set_password('user123')
            
            # Create test user
            test = User(
                username='test',
                email='test@test.com',
                balance=Decimal('300.00'),
                is_recipient=False
            )
            test.set_password('test123')
            
            try:
                db.session.add(admin)
                db.session.add(user)
                db.session.add(test)
                db.session.commit()
                print("✅ Test users created successfully!")
                print("Login credentials:")
                print("• admin / admin123 (recipient)")
                print("• user / user123 (regular)")  
                print("• test / test123 (regular)")
            except Exception as e:
                db.session.rollback()
                print(f"❌ Error creating users: {e}")
        else:
            print("✅ Users already exist:")
            for user in User.query.all():
                user_type = "recipient" if user.is_recipient else "regular"
                print(f"• {user.username} ({user.email}) - {user_type}")

if __name__ == '__main__':
    fix_database()

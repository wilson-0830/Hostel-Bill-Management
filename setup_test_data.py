#!/usr/bin/env python3
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import app
from models import db, User
from decimal import Decimal

with app.app_context():
    # Ensure tables exist
    db.create_all()
    
    # Check if we have any users
    user_count = User.query.count()
    print(f"Current user count: {user_count}")
    
    if user_count == 0:
        print("Creating test users...")
        
        # Admin user
        admin = User(
            username='admin',
            email='admin@test.com',
            balance=Decimal('1000.00'),
            is_recipient=True
        )
        admin.set_password('admin123')
        db.session.add(admin)
        
        # Regular user
        user = User(
            username='user',
            email='user@test.com',
            balance=Decimal('500.00'),
            is_recipient=False
        )
        user.set_password('user123')
        db.session.add(user)
        
        # Test user
        test = User(
            username='test',
            email='test@test.com',
            balance=Decimal('300.00'),
            is_recipient=False
        )
        test.set_password('test123')
        db.session.add(test)
        
        db.session.commit()
        print("✅ Test users created successfully!")
        print("Login credentials:")
        print("• admin / admin123 (recipient account)")
        print("• user / user123 (regular account)")  
        print("• test / test123 (regular account)")
    else:
        print("✅ Users already exist:")
        for user in User.query.all():
            user_type = "recipient" if user.is_recipient else "regular"
            print(f"• {user.username} ({user.email}) - {user_type}")

print("\n🚀 Application is ready! Visit http://localhost:8080 to test login functionality.")

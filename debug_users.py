from app import app
from models import db, User
from decimal import Decimal

with app.app_context():
    # Check existing users
    users = User.query.all()
    print(f'Total users: {len(users)}')
    
    if users:
        for user in users:
            print(f'User: {user.username}, Email: {user.email}, Is Recipient: {user.is_recipient}')
    else:
        print('No users found. Creating test user...')
        
        # Create a test user
        test_user = User(
            username='admin',
            email='admin@test.com',
            balance=Decimal('1000.00'),
            is_recipient=True
        )
        test_user.set_password('admin123')
        
        db.session.add(test_user)
        db.session.commit()
        print('Test user created: admin/admin123')
        
        # Create a regular user too
        regular_user = User(
            username='user',
            email='user@test.com',
            balance=Decimal('500.00'),
            is_recipient=False
        )
        regular_user.set_password('user123')
        
        db.session.add(regular_user)
        db.session.commit()
        print('Regular user created: user/user123')

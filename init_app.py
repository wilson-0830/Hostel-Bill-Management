from app import app
from models import db, User
from decimal import Decimal

def init_app():
    with app.app_context():
        # Create all tables
        db.create_all()
        
        # Check if we have users
        if User.query.count() == 0:
            print("Creating test users...")
            
            # Create admin user
            admin = User(
                username='admin',
                email='admin@test.com',
                balance=Decimal('1000.00'),
                is_recipient=True
            )
            admin.set_password('admin123')
            db.session.add(admin)
            
            # Create regular user
            user = User(
                username='user',
                email='user@test.com',
                balance=Decimal('500.00'),
                is_recipient=False
            )
            user.set_password('user123')
            db.session.add(user)
            
            # Create test user
            test = User(
                username='test',
                email='test@test.com',
                balance=Decimal('300.00'),
                is_recipient=False
            )
            test.set_password('test123')
            db.session.add(test)
            
            db.session.commit()
            print("Test users created:")
            print("- admin/admin123 (recipient)")
            print("- user/user123 (regular)")
            print("- test/test123 (regular)")
        else:
            print(f"Found {User.query.count()} existing users")
            for user in User.query.all():
                print(f"- {user.username} ({user.email})")

if __name__ == '__main__':
    init_app()

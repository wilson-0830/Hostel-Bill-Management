#!/usr/bin/env python3
from app import app, db, Transaction, User, PaymentItem, PaymentMethod
import sys

def check_database_status():
    with app.app_context():
        try:
            # Check users
            users = User.query.all()
            print(f"✅ Users: {len(users)} found")
            if users:
                for i, user in enumerate(users[:3]):
                    print(f"  - User {i+1}: {user.username} (is_recipient: {user.is_recipient})")
            
            # Check transactions
            transactions = Transaction.query.all()
            print(f"✅ Transactions: {len(transactions)} found")
            if transactions:
                for i, trans in enumerate(transactions[:3]):
                    payer = User.query.get(trans.payer_id)
                    recipient = User.query.get(trans.recipient_id)
                    print(f"  - Transaction {i+1}: RM{trans.amount:.2f} from {payer.username if payer else 'Unknown'} to {recipient.username if recipient else 'Unknown'}")
            
            # Check payment items
            payment_items = PaymentItem.query.all()
            print(f"✅ Payment Items: {len(payment_items)} found")
            if payment_items:
                for i, item in enumerate(payment_items[:3]):
                    recipient = User.query.get(item.recipient_id)
                    print(f"  - Item {i+1}: {item.title} (RM{item.amount:.2f}) by {recipient.username if recipient else 'Unknown'}")
            
            # Check payment methods
            payment_methods = PaymentMethod.query.all()
            print(f"✅ Payment Methods: {len(payment_methods)} found")
            
            # Summary
            print("\n📊 Database Status Summary:")
            print(f"  Total Users: {len(users)}")
            print(f"  Total Transactions: {len(transactions)}")
            print(f"  Total Payment Items: {len(payment_items)}")
            print(f"  Total Payment Methods: {len(payment_methods)}")
            
            if len(transactions) == 0:
                print("\n⚠️  No transaction data found - this explains why transaction records are not showing")
                print("💡 To fix this, you need to:")
                print("   1. Create some test users")
                print("   2. Create payment items")
                print("   3. Process some transactions")
            
            return True
            
        except Exception as e:
            print(f"❌ Database error: {e}")
            return False

if __name__ == "__main__":
    print("🔍 Checking database status...\n")
    success = check_database_status()
    sys.exit(0 if success else 1)

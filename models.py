from decimal import Decimal
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import UserMixin
from sqlalchemy import event
import os

db = SQLAlchemy()

class User(db.Model, UserMixin):
    __tablename__ = 'users'
    
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    email = db.Column(db.String(100), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    balance = db.Column(db.Numeric(12, 2), default=Decimal('0.00'))
    is_recipient = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=db.func.current_timestamp())
    
    recipient_profile = db.relationship('Recipient', backref='user', uselist=False)
    payment_items = db.relationship('PaymentItem', backref='recipient')
    payment_methods = db.relationship('PaymentMethod', backref='recipient')

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
    
    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class Recipient(db.Model):
    __tablename__ = 'recipients'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), unique=True)
    business_name = db.Column(db.String(100))
    is_verified = db.Column(db.Boolean, default=False)

class PaymentItem(db.Model):
    __tablename__ = 'payment_items'

    id = db.Column(db.Integer, primary_key=True)
    recipient_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    title = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    amount = db.Column(db.Numeric(12, 2), nullable=False)
    amount_received = db.Column(db.Numeric(12, 2), default=Decimal('0.00'))
    image_url = db.Column(db.String(255))
    participant_count = db.Column(db.Integer, nullable=False, default=1)
    status = db.Column(db.String(20), default='active')  # active/completed/cancelled
    currency = db.Column(db.String(3), default='CNY')
    created_at = db.Column(db.DateTime, default=db.func.current_timestamp())

class PaymentMethod(db.Model):
    __tablename__ = 'payment_methods'

    id = db.Column(db.Integer, primary_key=True)
    recipient_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    method_type = db.Column(db.String(20), nullable=False)  # 微信/支付宝/银行卡
    account_info = db.Column(db.String(255))
    qr_code_image = db.Column(db.String(255))  # 图片路径
    is_default = db.Column(db.Boolean, default=False)

class Transaction(db.Model):
    __tablename__ = 'transactions'

    id = db.Column(db.Integer, primary_key=True)
    payment_item_id = db.Column(db.Integer, db.ForeignKey('payment_items.id'))
    payer_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    recipient_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    payment_method_id = db.Column(db.Integer, db.ForeignKey('payment_methods.id'))
    amount = db.Column(db.Numeric(12, 2), nullable=False)
    status = db.Column(db.String(20), default='pending')
    note = db.Column(db.Text)
    proof_image = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=db.func.current_timestamp())
    completed_at = db.Column(db.DateTime)
    is_personal_payment = db.Column(db.Boolean, default=False)
    refund_status = db.Column(db.String(20))  # refunded/cancelled
    refund_at = db.Column(db.DateTime)

    payment_item = db.relationship('PaymentItem', backref='transactions')
    payer = db.relationship('User', foreign_keys=[payer_id])
    recipient = db.relationship('User', foreign_keys=[recipient_id])
    payment_method = db.relationship('PaymentMethod', foreign_keys=[payment_method_id])

# -------------------------------
# 自动删除上传图片（封面图、二维码）
# -------------------------------

@event.listens_for(PaymentItem, 'after_delete')
def delete_payment_item_image(mapper, connection, target):
    if target.image_url:
        filename = target.image_url.split('/')[-1]
        image_path = os.path.join('static', 'uploads', filename)
        if os.path.exists(image_path):
            try:
                os.remove(image_path)
            except Exception as e:
                print(f"删除项目图片失败: {e}")

@event.listens_for(PaymentMethod, 'after_delete')
def delete_qr_code_image(mapper, connection, target):
    if target.qr_code_image:
        filename = target.qr_code_image.split('/')[-1]
        image_path = os.path.join('static', 'uploads', filename)
        if os.path.exists(image_path):
            try:
                os.remove(image_path)
            except Exception as e:
                print(f"删除二维码图片失败: {e}")
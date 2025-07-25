from decimal import Decimal
from datetime import datetime, timezone
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import UserMixin
from sqlalchemy import event
import os, json

db = SQLAlchemy()

class JSONEncodedDict(db.TypeDecorator):
    """Enables JSON storage by encoding and decoding on the fly."""
    impl = db.Text

    def process_bind_param(self, value, dialect):
        if value is not None:
            # Convert Decimal to string for JSON serialization
            if isinstance(value, dict):
                value = {k: str(v) if isinstance(v, Decimal) else v 
                         for k, v in value.items()}
            return json.dumps(value)
        return None

    def process_result_value(self, value, dialect):
        if value is not None:
            # Convert string back to Decimal when loading from DB
            loaded = json.loads(value)
            if isinstance(loaded, dict):
                loaded = {int(k): Decimal(v) if isinstance(v, str) and v.replace('.', '', 1).isdigit() else v 
                          for k, v in loaded.items()}
            return loaded
        return None


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
    groups = db.relationship('Group', secondary='group_members', back_populates='members')

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


# 群组成员关联表（多对多）
group_members = db.Table('group_members',
    db.Column('group_id', db.Integer, db.ForeignKey('groups.id')),
    db.Column('user_id', db.Integer, db.ForeignKey('users.id'))
)

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
    
    # 修改这里：只保留一个 assigned_users 定义
    assigned_users = db.Column(JSONEncodedDict)  # 使用自定义类型处理 Decimal
    
    split_mode = db.Column(db.String(20), default='average')  # 'average'/'individual'/'group'
    group_id = db.Column(db.Integer, db.ForeignKey('groups.id'))

    group = db.relationship('Group', foreign_keys=[group_id])
    
    # 确保方法在类内部正确缩进
    def calculate_user_amount(self, user_id):
        """计算特定用户的应付金额"""
        if self.split_mode == 'average':
            # 传统AA：平均分摊（包括自己）
            total_users = User.query.count()
            return self.amount / Decimal(total_users)
        
        elif self.split_mode == 'individual':
            # 指定用户：返回该用户被分配的金额
            if user_id in self.assigned_users:
                return self.assigned_users[user_id]
        
        elif self.split_mode == 'group' and self.group:
            # 群组AA：平均分摊给所有成员
            member_count = len(self.group.members)
            return self.amount / Decimal(member_count)
        
        return Decimal('0.00')
    
    def calculate_own_amount(self):
        """计算收款者自身应付金额"""
        if self.split_mode == 'average':
            # 传统AA：使用总用户数计算分摊金额
            return self.amount / Decimal(self.participant_count)
        
        elif self.split_mode == 'individual':
            # 指定用户模式：总金额 - 其他用户指定金额
            total_assigned = Decimal('0.00')
            for user_id, amount in self.assigned_users.items():
                if user_id != self.recipient_id:
                    total_assigned += amount
            return self.amount - total_assigned
        
        elif self.split_mode == 'group' and self.group:
            # 群组模式：平均分摊（包括自己）
            member_count = len(self.group.members)
            return self.amount / Decimal(member_count)
        
        return Decimal('0.00')

class PaymentMethod(db.Model):
    __tablename__ = 'payment_methods'

    id = db.Column(db.Integer, primary_key=True)
    recipient_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    method_type = db.Column(db.String(20), nullable=False)  # 微信/支付宝/银行卡
    account_info = db.Column(db.String(255))
    qr_code_image = db.Column(db.String(255))
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
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    completed_at = db.Column(db.DateTime)
    is_personal_payment = db.Column(db.Boolean, default=False)
    refund_status = db.Column(db.String(20))  # refunded/cancelled
    refund_at = db.Column(db.DateTime)

    payment_item = db.relationship('PaymentItem', backref='transactions')
    payer = db.relationship('User', foreign_keys=[payer_id])
    recipient = db.relationship('User', foreign_keys=[recipient_id])
    payment_method = db.relationship('PaymentMethod', foreign_keys=[payment_method_id])

class Group(db.Model):
    __tablename__ = 'groups'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    creator_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_at = db.Column(db.DateTime, default=db.func.current_timestamp())
    
    members = db.relationship('User', secondary='group_members', back_populates='groups')

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
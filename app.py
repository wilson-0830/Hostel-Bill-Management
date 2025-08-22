from gevent import monkey
monkey.patch_all()

from flask import Flask, render_template, redirect, url_for, flash, request, session, abort, make_response
from flask_login import LoginManager, current_user, login_user, logout_user, login_required
from flask_sqlalchemy import SQLAlchemy
from models import db, User, Recipient, PaymentItem, PaymentMethod, Transaction, Group, Announcement
from datetime import datetime, timezone, timedelta
from flask_moment import Moment
import os
from werkzeug.utils import secure_filename
from decimal import Decimal, InvalidOperation
from flask_migrate import Migrate
from sqlalchemy import or_
from flask_session import Session
from flask_socketio import SocketIO, emit
import re
from pytz import timezone as tz


# 初始化应用
app = Flask(__name__)
socketio = SocketIO(app, async_mode='gevent')

# 创建 Flask 应用
uri = os.environ.get('DATABASE_URL')
if uri and uri.startswith("postgres://"):
    uri = uri.replace("postgres://", "postgresql://", 1)
app.config['SQLALCHEMY_DATABASE_URI'] = uri or 'sqlite:///transfers.db'

# 初始化配置
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'fallback-secret-key')
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///transfers.db').replace('postgres://', 'postgresql://', 1)
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['S3_BUCKET'] = os.environ.get('S3_BUCKET')
app.config['S3_KEY'] = os.environ.get('S3_KEY')
app.config['S3_SECRET'] = os.environ.get('S3_SECRET')

# 添加缺失的配置项
app.config['UPLOAD_FOLDER'] = os.path.join(app.root_path, 'static/uploads')  # 添加这一行
app.config['GALLERY_UPLOAD_FOLDER'] = os.path.join(app.root_path, 'static/uploads/gallery')
app.config['ALLOWED_EXTENSIONS'] = {'png', 'jpg', 'jpeg', 'gif'}  # 普通文件上传允许的扩展名
app.config['ALLOWED_GALLERY_EXTENSIONS'] = {'png', 'jpg', 'jpeg', 'gif', 'svg'}  # 画廊图片允许的扩展名
app.config['SESSION_TYPE'] = 'filesystem'

for folder in [app.config['UPLOAD_FOLDER'], app.config['GALLERY_UPLOAD_FOLDER']]:
    os.makedirs(folder, exist_ok=True)

# 初始化扩展
db.init_app(app)
migrate = Migrate(app, db)  # 添加这行
login_manager = LoginManager(app)
login_manager.login_view = 'login'
moment = Moment(app)

def get_id(self):
    return str(self.id)

def to_local_time(utc_time):
    """将UTC时间转换为UTC+8时区时间"""
    if not utc_time:
        return None
    if not utc_time.tzinfo:
        utc_time = utc_time.replace(tzinfo=tz('UTC'))
    return utc_time.astimezone(tz('Asia/Singapore'))

def allowed_file(filename, allowed_extensions):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in allowed_extensions

def save_gallery_image(file):
    if file and allowed_file(file.filename, app.config['ALLOWED_GALLERY_EXTENSIONS']):
        # 确保使用绝对路径
        upload_dir = app.config['GALLERY_UPLOAD_FOLDER']
        os.makedirs(upload_dir, exist_ok=True)

        # 生成唯一文件名
        ext = file.filename.rsplit('.', 1)[1].lower()
        filename = f"gallery_{datetime.now().timestamp()}.{ext}"
        filepath = os.path.join(upload_dir, filename)

        try:
            file.save(filepath)
            # 返回相对于static目录的路径
            return f"uploads/gallery/{filename}"
        except Exception as e:
            app.logger.error(f"保存图片失败: {e}")
            return None
    return None

def allowed_file(filename, allowed_extensions):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in allowed_extensions

def create_upload_folders():
    # 确保所有上传目录都存在
    folders = [
        app.config.get('UPLOAD_FOLDER', 'static/uploads'),
        app.config.get('GALLERY_UPLOAD_FOLDER', 'static/uploads/gallery')
    ]
    for folder in folders:
        try:
            os.makedirs(folder, exist_ok=True)
            app.logger.info(f"确保目录存在: {folder}")
        except Exception as e:
            app.logger.error(f"无法创建上传目录 {folder}: {e}")

# 用户加载器
@login_manager.user_loader
def load_user(user_id):
    # 修复：使用 session.get() 替代 query.get()
    return db.session.get(User, int(user_id))

# 创建数据库表格
with app.app_context():
    db.create_all()

# 确保这个上下文处理器存在
@app.context_processor
def inject_now():
    return {'now': datetime.now()}

@app.errorhandler(404)
def not_found(e):
    return render_template('404.html'), 404

# 添加在app.py中的适当位置
def calculate_pending_payments(user):
    """计算用户当前的应付金额"""
    pending_amount = Decimal('0.00')

    # 获取用户需要支付的所有活跃项目
    active_items = PaymentItem.query.filter_by(status='active').all()

    for item in active_items:
        # 检查用户是否已支付该项目
        paid = Transaction.query.filter_by(
            payer_id=user.id,
            payment_item_id=item.id,
            is_personal_payment=True
        ).first()

        if not paid:
            # 根据分摊模式计算应付金额
            if item.split_mode == 'average':
                count = item.participant_count if item.participant_count > 0 else 1
                pending_amount += item.amount / Decimal(count)
            elif item.split_mode == 'individual' and item.assigned_users:
                pending_amount += item.assigned_users.get(user.id, Decimal('0.00'))
            elif item.split_mode == 'group' and item.group and user in item.group.members:
                member_count = len(item.group.members)
                pending_amount += item.amount / Decimal(member_count)

    return pending_amount

# 将函数添加到Jinja环境
@app.context_processor
def utility_processor():
    return dict(calculate_pending_payments=calculate_pending_payments)

# 路由定义
@app.route('/tools')
@login_required
def console():
    # 获取收款项目
    if current_user.is_recipient:
        payment_items = PaymentItem.query.filter(
            PaymentItem.recipient_id != current_user.id,
            PaymentItem.status == 'active'
        ).limit(5).all()
    else:
        payment_items = PaymentItem.query.filter_by(status='active').limit(5).all()

    # 获取当前用户的所有个人支付记录
    user_payments = {
        t.payment_item_id: t
        for t in Transaction.query.filter_by(
            payer_id=current_user.id,
            is_personal_payment=True
        ).all()
    }

    # 计算应付金额和已付金额
    pending_payments = Decimal('0.00')
    paid_amount = Decimal('0.00')

    for item in payment_items:
        if item.id in user_payments:
            paid_amount += user_payments[item.id].amount
        else:
            count = item.participant_count if item.participant_count > 0 else 1
            pending_payments += item.amount / Decimal(count)

    # 获取最近交易
    transactions = Transaction.query.filter(
        (Transaction.payer_id == current_user.id) |
        (Transaction.recipient_id == current_user.id)
    ).order_by(Transaction.created_at.desc()).limit(5).all()

    # 获取最近交易并转换时区
    transactions = Transaction.query.filter(
        (Transaction.payer_id == current_user.id) |
        (Transaction.recipient_id == current_user.id)
    ).order_by(Transaction.created_at.desc()).limit(5).all()

    for trans in transactions:
        trans.created_at = to_local_time(trans.created_at)

    return render_template('console.html',
                         payment_items=payment_items,
                         user_payments=user_payments,
                         pending_payments=pending_payments,
                         paid_amount=paid_amount,
                         transactions=transactions)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        next_page = request.args.get('next')
        return redirect(next_page or url_for('index'))

    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = User.query.filter_by(username=username).first()

        if user and user.check_password(password):
            login_user(user)
            next_page = request.args.get('next')
            return redirect(next_page or url_for('index'))
        flash('用户名或密码错误', 'error')

    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        next_page = request.args.get('next')
        return redirect(next_page or url_for('index'))

    if request.method == 'POST':
        username = request.form.get('username')
        email = request.form.get('email')
        password = request.form.get('password')
        is_recipient = request.form.get('is_recipient') == 'on'

        if User.query.filter_by(username=username).first():
            flash('用户名已存在', 'error')
        elif User.query.filter_by(email=email).first():
            flash('邮箱已被注册', 'error')
        else:
            user = User(
                username=username,
                email=email,
                balance=Decimal('1000.00'),
                is_recipient=is_recipient
            )
            user.set_password(password)
            db.session.add(user)

            if is_recipient:
                recipient = Recipient(user=user, business_name=f"{username}的工作室")
                db.session.add(recipient)

            db.session.commit()
            login_user(user)
            next_page = request.args.get('next')
            flash('注册成功', 'success')
            return redirect(next_page or url_for('index'))

    return render_template('register.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))

@app.route('/change_password', methods=['GET', 'POST'])
def change_password():
    if request.method == 'POST':
        # First step: verify email
        if 'verify_email' in request.form:
            email = request.form.get('email')
            user = User.query.filter_by(email=email).first()

            if not user:
                flash('该邮箱地址未注册', 'error')
            else:
                # Store user email in session for verification
                session['password_reset_email'] = email
                flash(f'验证成功！请为 {user.username} 设置新密码', 'success')

            return redirect(url_for('change_password'))

        # Second step: change password
        elif 'change_password' in request.form:
            if 'password_reset_email' not in session:
                flash('请先验证邮箱', 'error')
                return redirect(url_for('change_password'))

            new_password = request.form.get('new_password', '')
            confirm_password = request.form.get('confirm_password', '')

            if new_password != confirm_password:
                flash('新密码不匹配', 'error')
            elif len(new_password) < 6:
                flash('密码至少需要6个字符', 'error')


            else:
                # Update password
                user = User.query.filter_by(email=session['password_reset_email']).first()
                if user:
                    user.set_password(new_password)
                    db.session.commit()
                    session.pop('password_reset_email', None)
                    flash(f'用户 {user.username} 的密码已成功更新', 'success')
                    return redirect(url_for('login'))

                flash('验证已过期，请重新验证邮箱', 'error')

    # Check if email is verified
    email_verified = False
    username = None
    if 'password_reset_email' in session:
        user = User.query.filter_by(email=session['password_reset_email']).first()
        if user:
            email_verified = True
            username = user.username

    return render_template('c_pass.html',
                         email_verified=email_verified,
                         username=username)

# app.py 中 gallery 路由优化
@app.route('/')
def index():
    # 定义默认图片路径
    default_image = url_for('static', filename='images/default-hero.jpg')

    # 检查自定义图片是否存在
    hero_image_path = os.path.join(app.static_folder, 'uploads/gallery/hero_image.jpg')
    hero_image = url_for('static', filename='uploads/gallery/hero_image.jpg') if os.path.exists(hero_image_path) else default_image

    # 添加更多上下文信息
    stats = {
        'total_users': User.query.count(),
        'total_transactions': Transaction.query.count(),
        'active_projects': PaymentItem.query.filter_by(status='active').count()
    }

    # 计算当前用户的累计转账金额（如果已登录）
    total_transfer = Decimal('0.00')
    recent_transactions = []
    activities = []

    # 获取活动数据（公告和项目创建）
    # 获取活动数据（公告和项目创建）
    if current_user.is_authenticated:
        # 获取最新5条公告
        announcements = Announcement.query.order_by(Announcement.created_at.desc()).limit(7).all()
        # 获取最新5个项目
        projects = PaymentItem.query.order_by(PaymentItem.created_at.desc()).limit(7).all()

        # 组合数据并格式化时间
        for ann in announcements:
            # 转换时间为本地时区
            local_time = to_local_time(ann.created_at)
            activities.append({
                'type': 'announcement',
                'title': ann.title,
                'time': local_time.strftime('%Y-%m-%d'),  # 直接使用datetime对象格式化
                'creator': ann.creator.username
            })

        for proj in projects:
            local_time = to_local_time(proj.created_at)
            activities.append({
                'type': 'project',
                'title': f"创建了项目: {proj.title}",
                'time': local_time.strftime('%Y-%m-%d'),  # 直接使用datetime对象格式化
                'creator': proj.recipient.username
            })

        # 按时间排序并取最新5个
        activities.sort(key=lambda x: x['time'], reverse=True)
        activities = activities[:4]

        # 计算累计转账金额
        total_transfer = db.session.query(
            db.func.sum(Transaction.amount)
        ).filter(
            Transaction.payer_id == current_user.id,
            Transaction.status == 'completed'
        ).scalar() or Decimal('0.00')

        # 获取最近5条交易记录
        recent_transactions = Transaction.query.filter(
            (Transaction.payer_id == current_user.id) |
            (Transaction.recipient_id == current_user.id)
        ).order_by(Transaction.created_at.desc()).limit(5).all()

        # 添加时区转换
        for trans in recent_transactions:
            trans.created_at = to_local_time(trans.created_at)

    # 确保正确编码
    html = render_template(
        'index.html',
        activities=activities,
        hero_image=hero_image,
        is_authenticated=current_user.is_authenticated,
        current_user=current_user if current_user.is_authenticated else None,
        stats=stats,
        total_transfer=total_transfer,
        recent_transactions=recent_transactions
    )

    # 确保正确编码
    response = make_response(html)
    response.headers['Content-Type'] = 'text/html; charset=utf-8'
    return response

# 转账功能
# app.py 中修改 transfer 路由
@app.route('/transfer', methods=['POST'])
@login_required
def transfer():
    recipient_id = request.form.get('recipient_id')
    payment_item_id = request.form.get('payment_item_id')
    amount_str = request.form.get('amount')
    payment_method_id = request.form.get('payment_method_id')
    
    # 检查凭证文件
    if 'proof_image' not in request.files:
        flash("请上传付款凭证", "error")
        return redirect(url_for('confirm_payment', 
                               payment_item_id=payment_item_id, 
                               amount=amount_str))
    
    proof_file = request.files['proof_image']
    
    # 验证文件
    if proof_file.filename == '':
        flash("请选择有效的凭证文件", "error")
        return redirect(url_for('confirm_payment', 
                               payment_item_id=payment_item_id, 
                               amount=amount_str))
    
    if not allowed_file(proof_file.filename, app.config['ALLOWED_EXTENSIONS']):
        flash("只支持 JPG、PNG 格式的图片", "error")
        return redirect(url_for('confirm_payment', 
                               payment_item_id=payment_item_id, 
                               amount=amount_str))

    try:
        amount = Decimal(amount_str)
    except (InvalidOperation, ValueError, TypeError):
        flash("请输入有效的金额", "error")
        return redirect(url_for('index'))

    # 检查是否已支付过
    existing_transaction = Transaction.query.filter_by(
        payer_id=current_user.id,
        payment_item_id=payment_item_id,
        is_personal_payment=True
    ).first()

    if existing_transaction:
        flash('您已经支付过该款项', 'error')
        return redirect(url_for('index'))

    recipient = User.query.get(recipient_id)
    payment_item = PaymentItem.query.get(payment_item_id)

    if not recipient or not payment_item:
        flash('收款项目不存在', 'error')
        return redirect(url_for('index'))

    # 检查项目状态
    if payment_item.status != 'active':
        flash('该项目已结束，无法支付', 'error')
        return redirect(url_for('index'))
    
    # 保存凭证文件
    proof_image_url = None
    if proof_file and allowed_file(proof_file.filename, app.config['ALLOWED_EXTENSIONS']):
        # 确保上传目录存在
        os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

        # 生成唯一文件名
        filename = secure_filename(f"proof_{current_user.id}_{datetime.now().timestamp()}_{proof_file.filename}")
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        proof_file.save(file_path)

        # 使用url_for生成正确的URL
        proof_image_url = url_for('static', filename=f'uploads/{filename}')

    # 创建交易记录
    transaction = Transaction(
        payment_item_id=payment_item_id,
        payer_id=current_user.id,
        recipient_id=recipient.id,
        amount=amount,
        status='completed',
        payment_method_id=payment_method_id,
        is_personal_payment=True,
        proof_image=proof_image_url  # 保存凭证图片URL
    )

    # 更新收款项目的已收金额
    payment_item.amount_received += amount

    db.session.add(transaction)
    db.session.commit()

    flash(f'支付成功！已向{recipient.username}转账RM{amount:.2f}，页面将在3秒后刷新...', 'success')
    socketio.emit('refresh_page', {
        'message': 'payment_completed',
        'item_id': payment_item.id,
        'recipient_id': recipient.id,
        'payer_id': current_user.id
    }, namespace='/')
    return redirect(url_for('index'))

# 新增确认支付页面路由
@app.route('/confirm_payment')
@login_required
def confirm_payment():
    payment_item_id = request.args.get('payment_item_id')
    amount = request.args.get('amount')

    payment_item = PaymentItem.query.get_or_404(payment_item_id)

    # 新增验证逻辑
    if payment_item.amount_received >= payment_item.amount:
        flash('该项目已完成，无需再支付', 'error')
        return redirect(url_for('console'))

    if Transaction.query.filter_by(
        payer_id=current_user.id,
        payment_item_id=payment_item_id,
        is_personal_payment=True
    ).first():
        flash('您已经支付过该款项', 'error')
        return redirect(url_for('console'))
    recipient = payment_item.recipient
    payment_methods = recipient.payment_methods

    total_users = User.query.count()

    return render_template('confirm_payment.html',
                         payment_item=payment_item,
                         amount=amount,
                         payment_methods=payment_methods,
                         total_users=total_users)

# 收款工作室
# app.py 中修改收款工作室相关路由
@app.route('/recipient_studio')
@login_required
def recipient_studio():
    if not current_user.is_recipient:
        flash('您没有访问此页面的权限', 'error')
        return redirect(url_for('index'))

    # Get all users except current user for individual assignments
    all_users = User.query.filter(User.id != current_user.id).all()

    # Get active payment items (max 5)
    payment_items = PaymentItem.query.filter_by(
        recipient_id=current_user.id,
        status='active'
    ).order_by(PaymentItem.created_at.desc()).limit(5).all()

    # Get history items (non-active, max 3 preview)
    history_items = PaymentItem.query.filter(
        PaymentItem.recipient_id == current_user.id,
        PaymentItem.status != 'active'
    ).order_by(PaymentItem.created_at.desc()).limit(3).all()

    payment_methods = PaymentMethod.query.filter_by(recipient_id=current_user.id).all()

    # Get transactions (others' payments, max 5 preview)
    transactions = Transaction.query.filter(
        Transaction.recipient_id == current_user.id,
        Transaction.payer_id != current_user.id
    ).order_by(Transaction.created_at.desc()).limit(5).all()

    # 转换时间为本地时区
    for trans in transactions:
        trans.created_at = to_local_time(trans.created_at)

    total_users = User.query.count()

    return render_template('recipient_studio.html',
                         payment_items=payment_items,
                         history_items=history_items,
                         payment_methods=payment_methods,
                         transactions=transactions,
                         all_users=all_users,  # Pass all users to template
                         groups=current_user.groups,
                         total_users=total_users)  # Pass user's groups to template

# 添加删除支付方式功能
# 保留这个更完整的版本，删除其他重复定义
@app.route('/delete_payment_method/<int:method_id>', methods=['POST'])
@login_required
def delete_payment_method(method_id):
    if not current_user.is_recipient:
        flash('您没有访问此页面的权限', 'error')
        return redirect(url_for('index'))

    method = PaymentMethod.query.get_or_404(method_id)

    # 确保当前用户是付款方式的所有者
    if method.recipient_id != current_user.id:
        flash('无权操作此付款方式', 'error')
        return redirect(url_for('recipient_studio'))

    # 检查是否有交易使用此支付方式
    if Transaction.query.filter_by(payment_method_id=method.id).count() > 0:
        flash('该支付方式已被使用，无法删除', 'error')
    else:
        db.session.delete(method)
        db.session.commit()
        flash('支付方式已删除', 'success')

    return redirect(url_for('recipient_studio'))

# 获取全部历史项目
@app.route('/history_items')
@login_required
def history_items():
    if not current_user.is_recipient:
        flash('您没有访问此页面的权限', 'error')
        return redirect(url_for('index'))

    history_items = PaymentItem.query.filter(
        PaymentItem.recipient_id == current_user.id,
        PaymentItem.status != 'active'
    ).order_by(PaymentItem.created_at.desc()).all()

    # 转换时间为本地时区
    for item in history_items:
        item.created_at = to_local_time(item.created_at)
        if hasattr(item, 'updated_at') and item.updated_at:
            item.updated_at = to_local_time(item.updated_at)

    return render_template('history_items.html',
                         history_items=history_items)

# 删除项目
@app.route('/delete_payment_item/<int:item_id>', methods=['POST'])
@login_required
def delete_payment_item(item_id):
    item = PaymentItem.query.get_or_404(item_id)
    if item.recipient_id != current_user.id:
        abort(403)

    # 删除关联的图片
    if item.image_url:
        try:
            image_path = os.path.join(app.config['UPLOAD_FOLDER'],
                                     item.image_url.split('/')[-1])
            if os.path.exists(image_path):
                os.remove(image_path)
        except Exception as e:
            app.logger.error(f"删除图片失败: {e}")

    # 删除项目
    db.session.delete(item)
    db.session.commit()

    flash('项目已删除', 'success')
    return redirect(url_for('recipient_studio'))

# 添加收款项目
@app.route('/add_payment_item', methods=['POST'])
@login_required
def add_payment_item():
    if not current_user.is_recipient:
        flash('您没有访问此页面的权限', 'error')
        return redirect(url_for('index'))

    # 获取基本数据
    title = request.form.get('title')
    description = request.form.get('description')
    amount_str = request.form.get('amount')
    split_mode = request.form.get('split_mode', 'average')

    try:
        amount = Decimal(amount_str)
    except (InvalidOperation, ValueError, TypeError):
        flash("请输入有效的金额", "error")
        return redirect(url_for('recipient_studio'))

    # 处理图片上传
    image_url = None
    if 'image' in request.files:
        file = request.files['image']
        if file and allowed_file(file.filename, app.config['ALLOWED_EXTENSIONS']):
            # 确保上传目录存在
            os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

            # 生成唯一文件名
            filename = secure_filename(f"{current_user.id}_{datetime.now().timestamp()}_{file.filename}")
            file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(file_path)

            # 使用url_for生成正确的URL
            image_url = url_for('static', filename=f'uploads/{filename}')

    # 处理不同分摊模式
    participant_count = 1  # 默认包括自己
    assigned_users = None
    group_id = None

    if split_mode == 'average':
        # 传统AA：获取参与者数量（包括自己）
        participant_count = User.query.count()

    # 在 app.py 中修改 add_payment_item 路由的 individual 模式处理部分
    elif split_mode == 'individual':
        # 处理指定用户
        user_ids = request.form.getlist('assigned_user_id')
        amounts = request.form.getlist('assigned_amount')
        assigned_users = {}
        other_users_total = Decimal('0.00')

        try:
            # 确保金额是 Decimal 类型
            for uid, amt in zip(user_ids, amounts):
                if not uid:  # 跳过空用户选择
                    continue
                    
                # 转换金额为Decimal
                amount_decimal = Decimal(amt) if not isinstance(amt, Decimal) else amt
                assigned_users[int(uid)] = amount_decimal
                other_users_total += amount_decimal

            # 计算自己的金额（总金额减去其他用户指定金额）
            own_amount = amount - other_users_total

            if own_amount < 0:
                flash("其他用户金额总和不能超过总金额", "error")
                return redirect(url_for('recipient_studio'))

            if own_amount < Decimal('0.00'):
                flash("金额不能为负数", "error")
                return redirect(url_for('recipient_studio'))

            # 添加当前用户（收款者）的应付金额
            assigned_users[current_user.id] = own_amount
            participant_count = len(assigned_users)

        except (ValueError, InvalidOperation) as e:
            flash(f"金额格式错误: {str(e)}", "error")
            return redirect(url_for('recipient_studio'))

    elif split_mode == 'group':
        group_id = request.form.get('group_id')
        group = Group.query.get(group_id)
        if not group or current_user not in group.members:
            flash("无效的群组选择", "error")
            return redirect(url_for('recipient_studio'))

        # 参与者数量 = 群组成员数（包括自己）
        participant_count = len(group.members)

    # 创建支付项目
    payment_item = PaymentItem(
        recipient_id=current_user.id,
        title=title,
        description=description,
        amount=amount,
        image_url=image_url,
        participant_count=participant_count,
        status='active',
        split_mode=split_mode,
        assigned_users=assigned_users,
        group_id=group_id
    )

    # 保存到数据库
    db.session.add(payment_item)
    db.session.commit()  # 需要先提交以获取item.id

    # 计算当前用户的应付金额
    if split_mode == 'average':
        per_user_amount = amount / Decimal(participant_count)
    elif split_mode == 'individual':
        # 从之前计算的assigned_users字典中获取当前用户的金额
        per_user_amount = assigned_users.get(current_user.id, Decimal('0.00'))
    elif split_mode == 'group':
        per_user_amount = amount / Decimal(participant_count)

    # 确保金额大于0才创建支付记录
    if per_user_amount > Decimal('0.00'):
        # 创建交易记录
        transaction = Transaction(
            payment_item_id=payment_item.id,
            payer_id=current_user.id,
            recipient_id=current_user.id,  # 收款工作室主人
            amount=per_user_amount,
            status='completed',
            is_personal_payment=True,
            note='项目发起者自动支付',
            created_at=datetime.now(timezone.utc)
        )
        db.session.add(transaction)

        # 更新项目的已收金额
        payment_item.amount_received = per_user_amount
        db.session.commit()  # 提交更新后的金额

    # 添加日志记录
    app.logger.info(f"Emitting refresh_page event for item {payment_item.id}")
    socketio.emit('refresh_page', {
        'message': 'item_created',
        'item_id': payment_item.id,
        'recipient_id': current_user.id,
        'payer_id': None
    }, namespace='/')
    flash('收款项目添加成功', 'success')
    return redirect(url_for('recipient_studio'))


# 添加付款方式
@app.route('/add_payment_method', methods=['POST'])
@login_required
def add_payment_method():
    if not current_user.is_recipient:
        flash('您没有访问此页面的权限', 'error')
        return redirect(url_for('index'))

    method_type = request.form.get('method_type')
    account_info = request.form.get('account_info')
    qr_code_image = None

    # 处理二维码图片上传
    if 'qr_code_image' in request.files:
        file = request.files['qr_code_image']
        if file and allowed_file(file.filename, app.config['ALLOWED_EXTENSIONS']):  # 修改这里
            # 确保上传目录存在
            os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

            # 生成唯一文件名
            filename = secure_filename(f"{current_user.id}_{datetime.now().timestamp()}_{file.filename}")
            file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(file_path)

            # 使用url_for生成正确的URL
            qr_code_image = url_for('static', filename=f'uploads/{filename}')

    # 验证逻辑：如果没有上传图片，则必须提供账号信息
    if not qr_code_image and not account_info:
        flash('请至少提供账号信息或上传二维码图片', 'error')
        return redirect(url_for('recipient_studio'))

    payment_method = PaymentMethod(
        recipient_id=current_user.id,
        method_type=method_type,
        account_info=account_info if not qr_code_image else None,  # 有图片就不保存账号信息
        qr_code_image=qr_code_image,
        is_default=request.form.get('is_default') == 'on'
    )

    db.session.add(payment_method)
    db.session.commit()
    flash('付款方式添加成功', 'success')
    return redirect(url_for('recipient_studio'))

@app.route('/update_payment_item_status/<int:item_id>', methods=['POST'])
@login_required
def update_payment_item_status(item_id):
    item = PaymentItem.query.get_or_404(item_id)
    if item.recipient_id != current_user.id:
        abort(403)

    new_status = request.form.get('status')
    if new_status in ['completed', 'cancelled']:
        item.status = new_status

        # 如果是取消状态，执行自动退款
        if new_status == 'cancelled':
            # 获取所有支付记录
            transactions = Transaction.query.filter_by(
                payment_item_id=item.id,
                is_personal_payment=True
            ).all()

            for trans in transactions:
                # 标记为退款
                trans.refund_status = 'cancelled'
                trans.refund_at = datetime.now()

                # 更新用户余额（需要确保User模型有balance字段）
                payer = User.query.get(trans.payer_id)
                recipient = User.query.get(trans.recipient_id)

                payer.balance += trans.amount
                recipient.balance -= trans.amount

                # 添加退款备注
                trans.note = f"项目取消自动退款 - {trans.note or ''}"

        db.session.commit()

    # 获取所有相关用户ID（付款人+收款人）
    affected_users = list(set([t.payer_id for t in item.transactions] + [item.recipient_id]))

    # 发送刷新事件给所有相关用户
    socketio.emit('refresh_page', {
        'message': 'status_changed',
        'item_id': item.id,
        'affected_users': affected_users  # 明确传递受影响的用户列表
    }, namespace='/')

    flash(f'项目状态已更新为{new_status}', 'success')

    return redirect(url_for('recipient_studio'))

@app.route('/debug_payment_items')
def debug_payment_items():
    broken_items = []
    for item in PaymentItem.query.all():
        if isinstance(item.amount, str) or isinstance(item.amount_received, str):
            broken_items.append({
                "id": item.id,
                "amount": item.amount,
                "amount_received": item.amount_received
            })
    return {"broken_items": broken_items}


@app.route('/fix_payment_methods')
def fix_payment_methods():
    from sqlalchemy import text
    try:
        # For SQLite
        db.session.execute(text('ALTER TABLE payment_methods ADD COLUMN updated_at DATETIME'))
        db.session.commit()
        return 'Added updated_at column to payment_methods'
    except Exception as e:
        db.session.rollback()
        return f'Error: {str(e)}'


@app.route('/transactions')
@login_required
def transactions():
    # 自动清理旧交易(保留最近15条)
    user_transactions = Transaction.query.filter(
        (Transaction.payer_id == current_user.id) |
        (Transaction.recipient_id == current_user.id)
    )

    total_count = user_transactions.count()
    if total_count > 15:
        oldest = user_transactions.order_by(
            Transaction.created_at.asc()
        ).limit(total_count - 15).all()

        for t in oldest:
            db.session.delete(t)
        db.session.commit()

    # 获取筛选参数
    search = request.args.get('search', '').strip()
    trans_type = request.args.get('type', '')

    # 构建基础查询
    query = Transaction.query.filter(
        (Transaction.payer_id == current_user.id) |
        (Transaction.recipient_id == current_user.id)
    )

    # 应用收入/支出筛选
    if trans_type == 'incoming':
        query = query.filter(Transaction.recipient_id == current_user.id)
    elif trans_type == 'outgoing':
        query = query.filter(Transaction.payer_id == current_user.id)

    # 应用搜索条件
    if search:
        query = query.join(
            PaymentItem, Transaction.payment_item_id == PaymentItem.id
        ).join(
            User,
            or_(
                Transaction.payer_id == User.id,
                Transaction.recipient_id == User.id
            )
        ).filter(
            or_(
                PaymentItem.title.ilike(f'%{search}%'),
                User.username.ilike(f'%{search}%')
            )
        )

    transactions = query.order_by(Transaction.created_at.desc()).all()

    # 计算总额
    total_sent = db.session.query(
        db.func.sum(Transaction.amount)
    ).filter(
        Transaction.payer_id == current_user.id,
        Transaction.status == 'completed'
    ).scalar() or Decimal('0.00')

    total_received = db.session.query(
        db.func.sum(Transaction.amount)
    ).filter(
        Transaction.recipient_id == current_user.id,
        Transaction.status == 'completed'
    ).scalar() or Decimal('0.00')

    # 转换时间为本地时区
    for trans in transactions:
        trans.created_at = to_local_time(trans.created_at)
        if trans.refund_at:
            trans.refund_at = to_local_time(trans.refund_at)

    return render_template('transactions.html',
                         transactions=transactions,
                         total_sent=total_sent,
                         total_received=total_received)

@app.route('/groups')
@login_required
def list_groups():
    groups = Group.query.filter(Group.members.any(id=current_user.id)).all()
    all_users = User.query.filter(User.id != current_user.id).all()  # Get all users except current user
    return render_template('groups.html', groups=groups, all_users=all_users)

@app.route('/create_group', methods=['POST'])
@login_required
def create_group():
    name = request.form.get('name')
    group = Group(name=name, creator_id=current_user.id)
    group.members.append(current_user)  # 创建者自动加入
    db.session.add(group)
    db.session.commit()
    flash('群组创建成功', 'success')
    return redirect(url_for('list_groups'))

@app.route('/add_to_group/<int:group_id>', methods=['POST'])
@login_required
def add_to_group(group_id):
    group = Group.query.get_or_404(group_id)
    user_id = request.form.get('user_id')
    user = User.query.get(user_id)
    if user not in group.members:
        group.members.append(user)
        db.session.commit()
    return redirect(url_for('list_groups'))

# 更新计算支付金额的函数
def calculate_payments(payment_item):
    if payment_item.split_mode == 'average':
        # 传统AA平摊
        return {user.id: payment_item.amount / payment_item.participant_count
                for user in payment_item.recipient.members}
    elif payment_item.split_mode == 'individual':
        # 各付各的
        return payment_item.assigned_users
    elif payment_item.split_mode == 'group':
        # 群组AA
        group_members = payment_item.group.members
        return {user.id: payment_item.amount / len(group_members)
                for user in group_members}

# Add this route to app.py
@app.route('/delete_group/<int:group_id>', methods=['POST'])
@login_required
def delete_group(group_id):
    group = Group.query.get_or_404(group_id)

    # Only creator can delete the group
    if group.creator_id != current_user.id:
        flash('只有群组创建者可以删除群组', 'error')
        return redirect(url_for('list_groups'))

    db.session.delete(group)
    db.session.commit()
    flash('群组已成功删除', 'success')
    return redirect(url_for('list_groups'))

# app.py 添加以下路由

# 个人主页
@app.route('/profile')
@login_required
def profile():
    return render_template('profile.html', user=current_user)

# 更新个人信息
@app.route('/update_profile', methods=['POST'])
@login_required
def update_profile():
    username = request.form.get('username')
    email = request.form.get('email')

    # 检查用户名是否已被使用（排除当前用户）
    if User.query.filter(User.username == username, User.id != current_user.id).first():
        flash('该用户名已被使用', 'error')
        return redirect(url_for('profile'))

    # 检查邮箱是否已被使用（排除当前用户）
    if User.query.filter(User.email == email, User.id != current_user.id).first():
        flash('该邮箱已被注册', 'error')
        return redirect(url_for('profile'))

    current_user.username = username
    current_user.email = email

    db.session.commit()
    flash('个人信息已更新', 'success')
    return redirect(url_for('profile'))

# 删除账号
@app.route('/delete_account', methods=['POST'])
@login_required
def delete_account():
    # 软删除：标记用户为已删除状态
    current_user.is_deleted = True
    current_user.username = f"deleted_{current_user.id}"
    current_user.email = f"deleted_{current_user.id}@example.com"

    # 保留其他信息但清除敏感数据
    current_user.password_hash = "deleted"
    current_user.bio = "此账号已删除"

    db.session.commit()

    # 退出登录
    logout_user()
    flash('您的账号已成功删除', 'success')
    return redirect(url_for('index'))

@app.route('/post_announcement', methods=['POST'])
@login_required
def post_announcement():
    if not current_user.is_recipient:
        flash('只有收款者可以发布公告', 'error')
        return redirect(url_for('recipient_studio'))

    title = request.form.get('title', '')
    content = request.form.get('content', '')

    if not title:
        flash('公告标题不能为空', 'error')
        return redirect(url_for('recipient_studio'))

    # 限制标题长度（约23个中文字）
    if len(title) > 80:
        title = title[:80]

    announcement = Announcement(
        title=title,
        content=content,
        creator_id=current_user.id
    )

    db.session.add(announcement)
    db.session.commit()

    flash('公告发布成功', 'success')
    return redirect(url_for('recipient_studio'))

@app.route('/get_activities')
@login_required
def get_activities():
    # 获取最新5条公告
    announcements = Announcement.query.order_by(Announcement.created_at.desc()).limit(5).all()
    # 获取当前用户创建的最新5个项目
    projects = PaymentItem.query.filter_by(recipient_id=current_user.id).order_by(PaymentItem.created_at.desc()).limit(5).all()

    # 组合数据
    activities = []
    for ann in announcements:
        activities.append({
            'type': 'announcement',
            'title': ann.title,
            'time': to_local_time(ann.created_at),
            'creator': ann.creator.username
        })

    for proj in projects:
        activities.append({
            'type': 'project',
            'title': f"创建了项目: {proj.title}",
            'time': to_local_time(proj.created_at),
            'creator': proj.recipient.username
        })

    # 按时间排序并取最新5个
    activities_sorted = sorted(activities, key=lambda x: x['time'], reverse=True)[:4]

    return jsonify(activities_sorted)

@app.route('/terms')
def terms():
    return render_template('terms.html')

@app.route('/help_center')
def help_center():
    return render_template('help_center.html')

# 添加在文件末尾
if __name__ == '__main__':
    # 确保上传文件夹存在
    upload_folders = [
        app.config['UPLOAD_FOLDER'],
        app.config['GALLERY_UPLOAD_FOLDER'],
        'static/uploads/gallery'
    ]

    for folder in upload_folders:
        try:
            os.makedirs(folder, exist_ok=True)
        except Exception as e:
            print(f"无法创建目录 {folder}: {e}")

    # 仅当不在PythonAnywhere时启动本地服务器
    if not os.environ.get('PYTHONANYWHERE_DOMAIN'):
        import logging
        from logging.handlers import RotatingFileHandler
        file_handler = RotatingFileHandler('app.log', maxBytes=10240)
        file_handler.setFormatter(logging.Formatter(
            '%(asctime)s %(levelname)s: %(message)s'))
        app.logger.addHandler(file_handler)
        app.logger.setLevel(logging.INFO)

        # 获取本地IP地址
        import socket
        from contextlib import suppress

        host = '0.0.0.0'
        port = 8080
        local_ip = 'localhost'

        try:
            # 尝试多种方法获取本地IP
            hostname = socket.gethostname()
            with suppress(Exception):
                local_ip = socket.gethostbyname(hostname)

            # 使用网络连接的替代方法
            if local_ip == 'localhost':
                with suppress(Exception):
                    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                    s.connect(("8.8.8.8", 80))
                    local_ip = s.getsockname()[0]
                    s.close()
        except Exception as e:
            print(f"无法确定本地IP: {e}")
            local_ip = 'localhost'

        print(f"\n服务器将在 {host}:{port} 运行")
        print(f"在本地访问: http://localhost:{port}")
        print(f"在局域网内其他设备访问: http://{local_ip}:{port}\n")

        # 最后启动服务器
        socketio.run(app, host=host, port=port)
from flask import Flask, render_template, redirect, url_for, flash, request
from flask_login import LoginManager, current_user, login_user, logout_user, login_required
from flask_sqlalchemy import SQLAlchemy
from models import db, User, Recipient, PaymentItem, PaymentMethod, Transaction
from datetime import datetime
import os
from werkzeug.utils import secure_filename
from decimal import Decimal, InvalidOperation
from flask_migrate import Migrate
from sqlalchemy import or_

# 初始化应用
app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key-here'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///transfers.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = os.path.join(app.root_path, 'static/uploads')
app.config['GALLERY_UPLOAD_FOLDER'] = os.path.join(app.root_path, 'static/uploads/gallery')
app.config['ALLOWED_EXTENSIONS'] = {'png', 'jpg', 'jpeg', 'gif'}  # 普通文件上传允许的扩展名
app.config['ALLOWED_GALLERY_EXTENSIONS'] = {'png', 'jpg', 'jpeg', 'gif', 'svg'}  # 画廊图片允许的扩展名

# 初始化扩展
db.init_app(app)
migrate = Migrate(app, db)  # 添加这行
login_manager = LoginManager(app)
login_manager.login_view = 'login'


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
    folders = [
        app.config['UPLOAD_FOLDER'],
        app.config['GALLERY_UPLOAD_FOLDER']
    ]
    for folder in folders:
        try:
            os.makedirs(folder, exist_ok=True)
        except Exception as e:
            app.logger.error(f"无法创建上传目录 {folder}: {e}")

with app.app_context():
    create_upload_folders()

# 用户加载器
@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# 创建数据库表格
with app.app_context():
    db.create_all()

# 确保这个上下文处理器存在
@app.context_processor
def inject_now():
    return {'now': datetime.now()}

# 路由定义
@app.route('/')
@login_required
def index():
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
    
    return render_template('index.html',
                         payment_items=payment_items,
                         user_payments=user_payments,  # 传递用户支付状态
                         pending_payments=pending_payments,
                         paid_amount=paid_amount,
                         transactions=transactions)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        next_page = request.args.get('next')
        return redirect(next_page or url_for('gallery'))
    
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = User.query.filter_by(username=username).first()
        
        if user and user.check_password(password):
            login_user(user)
            next_page = request.args.get('next')
            return redirect(next_page or url_for('gallery'))
        flash('用户名或密码错误', 'error')
    
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        next_page = request.args.get('next')
        return redirect(next_page or url_for('gallery'))
    
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
            return redirect(next_page or url_for('gallery'))
    
    return render_template('register.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))

# app.py 中 gallery 路由优化
@app.route('/gallery')
def gallery():
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
    
    return render_template('gallery.html', 
                         hero_image=hero_image,
                         is_authenticated=current_user.is_authenticated,
                         stats=stats)

# 转账功能
# app.py 中修改 transfer 路由
@app.route('/transfer', methods=['POST'])
@login_required
def transfer():
    recipient_id = request.form.get('recipient_id')
    payment_item_id = request.form.get('payment_item_id')
    amount_str = request.form.get('amount')
    payment_method_id = request.form.get('payment_method_id')
    
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

    # 创建交易记录
    transaction = Transaction(
        payment_item_id=payment_item_id,
        payer_id=current_user.id,
        recipient_id=recipient.id,
        amount=amount,
        status='completed',
        payment_method_id=payment_method_id,  # 现在这个字段是有效的
        is_personal_payment=True
    )

    # 更新收款项目的已收金额
    payment_item.amount_received += amount
    
    db.session.add(transaction)
    db.session.commit()

    flash(f'成功向{recipient.username}转账RM{amount:.2f}', 'success')
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
        return redirect(url_for('index'))
    
    if Transaction.query.filter_by(
        payer_id=current_user.id,
        payment_item_id=payment_item_id,
        is_personal_payment=True
    ).first():
        flash('您已经支付过该款项', 'error')
        return redirect(url_for('index'))
    recipient = payment_item.recipient
    payment_methods = recipient.payment_methods
    
    return render_template('confirm_payment.html',
                         payment_item=payment_item,
                         amount=amount,
                         payment_methods=payment_methods)

# 收款工作室
# app.py 中修改收款工作室相关路由
@app.route('/recipient_studio')
@login_required
def recipient_studio():
    if not current_user.is_recipient:
        flash('您没有访问此页面的权限', 'error')
        return redirect(url_for('index'))
    
    # 获取活跃的收款项目（最多5个）
    payment_items = PaymentItem.query.filter_by(
        recipient_id=current_user.id,
        status='active'
    ).order_by(PaymentItem.created_at.desc()).limit(5).all()
    
    # 获取历史项目（非活跃状态，最多3个预览）
    history_items = PaymentItem.query.filter(
        PaymentItem.recipient_id == current_user.id,
        PaymentItem.status != 'active'
    ).order_by(PaymentItem.created_at.desc()).limit(3).all()
    
    payment_methods = PaymentMethod.query.filter_by(recipient_id=current_user.id).all()
    
    # 获取收款记录（他人支付，最多5个预览）
    transactions = Transaction.query.filter(
        Transaction.recipient_id == current_user.id,
        Transaction.payer_id != current_user.id
    ).order_by(Transaction.created_at.desc()).limit(5).all()
    
    return render_template('recipient_studio.html',
                         payment_items=payment_items,
                         history_items=history_items,
                         payment_methods=payment_methods,
                         transactions=transactions)

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
    
    # Make sure this query returns PaymentItem objects
    history_items = PaymentItem.query.filter(
        PaymentItem.recipient_id == current_user.id,
        PaymentItem.status != 'active'
    ).order_by(PaymentItem.created_at.desc()).all()
    
    return render_template('history_items.html', 
                         history_items=history_items)  # Passing the list correctly

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
    
    title = request.form.get('title')
    description = request.form.get('description')
    amount_str = request.form.get('amount')
    try:
        amount = Decimal(amount_str)
    except (InvalidOperation, ValueError, TypeError):
        flash("请输入有效的金额", "error")
        return redirect(url_for('recipient_studio'))
    participant_count = int(request.form.get('participant_count', 1))  # 默认值为1
    
    # 确保participant_count至少为1
    if participant_count < 1:
        participant_count = 1
    
    # 处理文件上传
    image_url = None
    if 'image' in request.files:
        file = request.files['image']
        if file and allowed_file(file.filename, app.config['ALLOWED_EXTENSIONS']):  # 修改这里
            filename = secure_filename(file.filename)
            file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
            image_url = url_for('static', filename=f'uploads/{filename}')
    
    payment_item = PaymentItem(
        recipient_id=current_user.id,
        title=title,
        description=description,
        amount=amount,
        image_url=image_url,
        participant_count=participant_count,
        status='active',
        amount_received=amount/participant_count  # 创建者自动支付自己部分
    )
    
    db.session.add(payment_item)
    
    # 创建创建者的自动支付记录
    transaction = Transaction(
        payment_item=payment_item,
        payer_id=current_user.id,
        recipient_id=current_user.id,
        amount=amount/participant_count,
        status='completed',
        note='创建者自动支付'
    )
    
    db.session.add(transaction)
    db.session.commit()
    
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


@app.route('/fix_payment_items')
def fix_payment_items():
    from decimal import Decimal, InvalidOperation
    fixed = 0
    for item in PaymentItem.query.all():
        try:
            if isinstance(item.amount, str):
                item.amount = Decimal(item.amount)
            if isinstance(item.amount_received, str):
                item.amount_received = Decimal(item.amount_received)
            fixed += 1
        except InvalidOperation:
            db.session.delete(item)  # optional: remove corrupted rows
    db.session.commit()
    return f"Fixed {fixed} payment items."


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
    
    return render_template('transactions.html',
                         transactions=transactions,
                         total_sent=total_sent,
                         total_received=total_received)

# 在 if __name__ == '__main__': 前添加
print("已注册路由：")
for rule in app.url_map.iter_rules():
    print(f"{rule.endpoint}: {rule}")

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

    # 配置服务器参数
    host = '0.0.0.0'
    port = 8080
    
    print("\n已注册路由：")
    for rule in app.url_map.iter_rules():
        print(f"{rule.endpoint}: {rule}")
    
    print(f"\n服务器将在 {host}:{port} 运行")
    print(f"在手机浏览器中访问: http://<电脑的IP地址>:{port}\n")
    
    # 单进程运行，避免需要关闭两次
    app.run(
        host=host,
        port=port,
        debug=True,          # 保留调试信息但禁用重新加载器
        use_reloader=False   # 这是关键 - 禁用重新加载器
    )

# migrate.py
from app import app, db
from flask_migrate import Migrate, upgrade

migrate = Migrate(app, db)

if __name__ == '__main__':
    with app.app_context():
        # 应用所有未完成的迁移
        upgrade()
        print("数据库升级完成")
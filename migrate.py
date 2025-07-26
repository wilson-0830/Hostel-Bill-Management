# migrate.py (separate file)
from app import app, db
from flask_migrate import Migrate

migrate = Migrate(app, db)

if __name__ == '__main__':
    app.app_context().push()
    # Run migrations here
"""Export the API contract without connecting to a database."""

import json
from .app import create_app
from .settings import Settings

if __name__ == "__main__":
    app = create_app(
        Settings(database_url="postgresql+psycopg://unused:unused@localhost/unused")
    )
    print(json.dumps(app.openapi(), ensure_ascii=False, indent=2))
    app.state.engine.dispose()

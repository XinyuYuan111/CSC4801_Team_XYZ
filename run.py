"""WSGI entry point: ``python run.py`` or ``waitress-serve --host 0.0.0.0 --port 8080 run:app``."""

from app import create_app

app = create_app()


if __name__ == "__main__":
    from waitress import serve

    serve(app, host="0.0.0.0", port=app.config["PORT"])

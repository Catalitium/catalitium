import sys
import os

def main():
    # Import lazily so pytest collection doesn't require package path
    from app.app import create_app  # noqa: WPS433
    # Force SQLite to avoid network waits in smoke
    os.environ.setdefault('FORCE_SQLITE', '1')
    app = create_app()
    with app.test_client() as c:
        r = c.get('/ping')
        print(r.status_code, r.get_json())
        r2 = c.get('/api/jobs?title=engineer&per_page=2')
        print('search', r2.status_code, isinstance(r2.get_json(), dict))

if __name__ == '__main__':
    main()

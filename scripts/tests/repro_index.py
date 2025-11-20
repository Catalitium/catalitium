from app.app import create_app
import traceback

app = create_app()
with app.test_request_context('/?title=developer&country='):
    try:
        resp = app.view_functions['index']()
        print('INDEX OK:', type(resp))
    except Exception:
        traceback.print_exc()

from conftest import register, form_csrf, PASSWORD, app_module


def test_pages_require_login(client):
    for url in ['/', '/analytics', '/calendar', '/search', '/profile', '/month/1']:
        r = client.get(url)
        assert r.status_code == 302 and '/login' in r.headers['Location'], url


def test_register_and_login(client):
    assert register(client).status_code == 302
    client.get('/logout')
    token = form_csrf(client, '/login')
    r = client.post('/login', data={'csrf_token': token, 'username': 'testuser1', 'password': PASSWORD})
    assert r.status_code == 302 and r.headers['Location'].endswith('/')


def test_login_wrong_password(client):
    register(client)
    client.get('/logout')
    token = form_csrf(client, '/login')
    r = client.post('/login', data={'csrf_token': token, 'username': 'testuser1', 'password': 'nope'})
    assert r.status_code == 200
    assert 'Λάθος' in r.get_data(as_text=True)


def test_login_requires_csrf(client):
    register(client)
    client.get('/logout')
    client.get('/login')
    r = client.post('/login', data={'csrf_token': 'bad', 'username': 'testuser1', 'password': PASSWORD})
    assert 'Σφάλμα ασφαλείας' in r.get_data(as_text=True)


def test_login_rate_limited(client):
    register(client)
    client.get('/logout')
    for _ in range(10):
        token = form_csrf(client, '/login')
        client.post('/login', data={'csrf_token': token, 'username': 'testuser1', 'password': 'x'})
    token = form_csrf(client, '/login')
    r = client.post('/login', data={'csrf_token': token, 'username': 'testuser1', 'password': PASSWORD})
    assert 'Πάρα πολλές' in r.get_data(as_text=True)


def test_register_validation(client):
    token = form_csrf(client, '/register')
    r = client.post('/register', data={
        'csrf_token': token, 'username': 'short', 'password': 'weak', 'confirm': 'other',
        'recovery_question': 'not a question', 'recovery_answer': 'a',
    })
    body = r.get_data(as_text=True)
    assert r.status_code == 200
    for msg in ['Username', 'Κωδικός', 'δεν ταιριάζουν', 'ερωτήσεις', 'Απάντηση']:
        assert msg in body


def test_register_duplicate_username(app):
    assert register(app.test_client()).status_code == 302
    r = register(app.test_client())
    assert 'χρησιμοποιείται ήδη' in r.get_data(as_text=True)


def test_json_endpoints_require_csrf(api):
    r = api.client.post('/new_month', json={'year': 2030, 'month': 1})
    assert r.status_code == 403
    r = api.client.post('/new_month', json={'year': 2030, 'month': 1}, headers={'X-CSRF-Token': 'wrong'})
    assert r.status_code == 403


def test_session_cookie_flags(client):
    r = client.get('/login')
    cookie = r.headers.get('Set-Cookie', '')
    assert 'HttpOnly' in cookie and 'SameSite=Lax' in cookie


def _forgot(client, **data):
    data['csrf_token'] = form_csrf(client, '/forgot')
    return client.post('/forgot', data=data)


def test_password_recovery_flow(client):
    register(client)
    client.get('/logout')
    r = _forgot(client, username='testuser1')
    assert app_module.RECOVERY_QUESTIONS[0] in r.get_data(as_text=True)

    r = _forgot(client, username='testuser1', question_step='1', recovery_answer='  REX ')
    assert r.status_code == 302 and r.headers['Location'].endswith('/forgot/reset')

    token = form_csrf(client, '/forgot/reset')
    new_pw = 'N3wPassw0rd!'
    r = client.post('/forgot/reset', data={'csrf_token': token, 'new_password': new_pw, 'confirm': new_pw})
    assert r.status_code == 302 and '/login' in r.headers['Location']

    # Token is single-use
    assert client.get('/forgot/reset').status_code == 302

    token = form_csrf(client, '/login')
    r = client.post('/login', data={'csrf_token': token, 'username': 'testuser1', 'password': new_pw})
    assert r.status_code == 302 and r.headers['Location'].endswith('/')


def test_password_recovery_wrong_answer_is_rate_limited(client):
    register(client)
    client.get('/logout')
    for _ in range(10):
        r = _forgot(client, username='testuser1', question_step='1', recovery_answer='wrong')
        assert 'Λάθος απάντηση' in r.get_data(as_text=True)
    r = _forgot(client, username='testuser1', question_step='1', recovery_answer='rex')
    assert 'Πάρα πολλές' in r.get_data(as_text=True)


def test_reset_retry_does_not_extend_token(client, monkeypatch):
    register(client)
    client.get('/logout')
    _forgot(client, username='testuser1', question_step='1', recovery_answer='rex')
    with client.session_transaction() as s:
        issued = s['pwd_reset']['issued_at']
    token = form_csrf(client, '/forgot/reset')
    client.post('/forgot/reset', data={'csrf_token': token, 'new_password': 'weak', 'confirm': 'weak'})
    with client.session_transaction() as s:
        assert s['pwd_reset']['issued_at'] == issued


def test_profile_change_password_and_delete_account(api, raw_db):
    c = api.client
    token = form_csrf(c, '/profile')
    r = c.post('/profile', data={
        'csrf_token': token, 'action': 'change_password', 'current_password': PASSWORD,
        'new_password': 'An0ther!pass', 'confirm_new_password': 'An0ther!pass'})
    assert 'άλλαξε επιτυχώς' in r.get_data(as_text=True)

    mid = api.new_month()
    api.add(mid)
    token = form_csrf(c, '/profile')
    r = c.post('/profile', data={'csrf_token': token, 'action': 'delete_account',
                                 'delete_password': 'An0ther!pass'})
    assert r.status_code == 302
    assert raw_db.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0
    assert raw_db.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 0

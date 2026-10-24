#!/usr/bin/env python3
"""Command-line client for a LinkContext LinkedIn graph server. Packaged Python CLI.

Configuration comes from three environment variables:
  LINKCONTEXT_URL             server address, for example http://127.0.0.1:8095 or https://link.pocketcontext.com
  LINKCONTEXT_USER_EMAIL      email of an account in the `users` collection
  LINKCONTEXT_USER_PASSWORD   password of that account (optional with Google login)

Exit codes: 0 success; 1 HTTP or transport error; 2 usage or configuration error;
3 `check` found schema differences; 4 HTTP 409 (read the record again, then retry).
"""
import argparse
import base64
import contextlib
from datetime import datetime, timedelta, timezone
import hashlib
import http.client
import http.server
from importlib.resources import files
import json
import os
from pathlib import Path
import re
import secrets
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

try:
    from observecontext_client.instrumentation import instrument_cli
except ImportError:
    @contextlib.contextmanager
    def instrument_cli(**_kwargs):
        yield

ENV = ['LINKCONTEXT_URL', 'LINKCONTEXT_USER_EMAIL', 'LINKCONTEXT_USER_PASSWORD']
try:
    SCHEMA_FILE = files('linkcontext_client').joinpath('schema.json')
except Exception:
    SCHEMA_FILE = Path(__file__).resolve().parent / 'schema.json'
STAMPS = ('created_by', 'updated_by')
ID_ALPHABET = 'abcdefghijklmnopqrstuvwxyz0123456789'
DETERMINISTIC_ALPHABET = '0123456789abcdefghijklmnopqrstuvwxyz'
BUSINESS_COLLECTIONS = (
    'sync_runs',
    'companies',
    'profiles',
    'experiences',
    'connections',
    'invitations',
    'posts',
    'post_interactions',
    'notifications',
    'threads',
    'thread_participants',
    'messages',
    'bookmarks',
)
COMPLETENESS_RANK = {'stub': 1, 'card': 2, 'full': 3}
PRECISION_RANK = {'relative_approx': 1, 'exact_dom': 2, 'exact_urn': 3}
VOLATILE_FIELDS = {
    'last_seen_at',
    'last_scraped_at',
    'last_sync_run',
    'follower_count',
    'employee_count_on_linkedin',
    'connection_count_label',
    'reaction_count',
    'comment_count',
    'repost_count',
    'unread_count',
    'last_activity_at',
    'last_message_preview',
    'is_read_on_linkedin',
    'triage_status',
    'status',
    'relationship_status',
    'crm_person_id',
    'crm_organization_id',
    'crm_deal_id',
    'crm_message_id',
}
TIMEOUT = 30
USER_AGENT = 'LinkContext/1.0'
hidden = []


class Fail(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def hide(value):
    if value:
        hidden.append(value)
    return value


def say(text, stream=sys.stderr):
    for value in hidden:
        text = text.replace(value, '***')
    print(text, file=stream)


def dump(data, pretty=False):
    if pretty:
        return json.dumps(data, indent=2, ensure_ascii=False)
    return json.dumps(data, separators=(',', ':'), ensure_ascii=False)


def config(names=ENV[:2]):
    missing = [name for name in names if not os.environ.get(name)]
    if missing:
        raise Fail(2, 'missing environment variable: ' + ', '.join(missing) + '. Ask the user to set every missing variable; do not look for credentials elsewhere.')
    url = os.environ[ENV[0]].rstrip('/')
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise Fail(2, 'LINKCONTEXT_URL must be an HTTP(S) URL without credentials, query, or fragment')
    if parsed.scheme == 'http' and parsed.hostname not in ('localhost', '127.0.0.1', '::1'):
        raise Fail(2, 'Use HTTPS for a remote LinkContext server')
    return {'url': url, 'email': os.environ[ENV[1]], 'password': hide(os.environ.get(ENV[2]))}


# Session file: one per server URL and email, readable only by the current user. It lives in
# the XDG state folder, not the cache, so clearing ~/.cache does not sign the user out (ENG-55).

def session_name(cfg):
    return hashlib.sha256((cfg['url'] + '\n' + cfg['email']).encode()).hexdigest()[:32] + '.json'


def session_file(cfg):
    folder = os.environ.get('LINKCONTEXT_SESSION_DIR')
    if not folder:
        state = os.environ.get('XDG_STATE_HOME') or str(Path.home() / '.local' / 'state')
        folder = str(Path(state) / 'linkcontext')
    return Path(folder) / session_name(cfg)


def legacy_session_file(cfg):
    """Where clients before ENG-55 kept the session; read once and moved."""
    base = os.environ.get('XDG_CACHE_HOME') or str(Path.home() / '.cache')
    return Path(base) / 'linkcontext' / session_name(cfg)


def read_session(cfg, path):
    try:
        session = json.loads(path.read_text())
        if not isinstance(session, dict) or session.get('url') != cfg['url'] or session.get('email') != cfg['email']:
            return None
        return session if isinstance(session.get('token'), str) and hide(session['token']) else None
    except (OSError, ValueError, KeyError, TypeError):
        return None


def load_session(cfg):
    path = session_file(cfg)
    if path.exists():
        return read_session(cfg, path)
    legacy = legacy_session_file(cfg)
    session = read_session(cfg, legacy)
    if session is not None and save_session(cfg, session):
        legacy.unlink(missing_ok=True)
    return session


def save_session(cfg, session):
    path = session_file(cfg)
    try:
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(path.parent, 0o700)
        with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, prefix='.session-', delete=False) as handle:
            temporary = Path(handle.name)
            os.fchmod(handle.fileno(), 0o600)
            json.dump(session, handle)
        os.replace(temporary, path)
        return True
    except OSError as error:
        say(f'note: session not saved ({error.strerror}); sign-in will be required again')
        return False


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args):
        return None


opener = urllib.request.build_opener(NoRedirect)


def send(cfg, method, path, body=None, token=None, timeout=TIMEOUT):
    headers = {'Content-Type': 'application/json', 'User-Agent': USER_AGENT}
    if token:
        headers['Authorization'] = token
    data = None if body is None else json.dumps(body).encode()
    request = urllib.request.Request(cfg['url'] + path, data=data, headers=headers, method=method)
    try:
        with opener.open(request, timeout=timeout) as response:
            status, raw = response.status, response.read()
    except urllib.error.HTTPError as error:
        status, raw = error.code, error.read()
        if 300 <= status < 400:
            raise Fail(1, f'HTTP {status}: the server redirects to {error.headers.get("Location")}. Set LINKCONTEXT_URL to the final address.')
    except (OSError, ValueError, http.client.HTTPException) as error:
        reason = getattr(error, 'reason', error)
        raise Fail(1, f'cannot reach {cfg["url"]}: {reason}')
    text = raw.decode('utf-8', 'replace')
    try:
        return status, json.loads(text) if text else None
    except ValueError:
        return status, text[:2000]


def login(cfg):
    if not cfg.get('password'):
        raise Fail(2, 'Set LINKCONTEXT_USER_PASSWORD for password login, or run linkcontext login --google for browser sign-in.')
    status, data = send(cfg, 'POST', '/api/collections/users/auth-with-password', {'identity': cfg['email'], 'password': cfg['password']})
    if status != 200 or not isinstance(data, dict) or 'token' not in data:
        raise Fail(1, f'login as {cfg["email"]} failed: HTTP {status}\n{dump(data)}\nCheck the three LINKCONTEXT_ variables with the user. User credentials only.')
    session = {'url': cfg['url'], 'email': cfg['email'], 'token': hide(data['token'])}
    save_session(cfg, session)
    return session


def auth_session(cfg, data, method):
    token = data.get('token') if isinstance(data, dict) else None
    if isinstance(token, str):
        hide(token)
    record = data.get('record') if isinstance(data, dict) else None
    if (not isinstance(token, str) or not token or not isinstance(record, dict) or record.get('collectionName') != 'users'
            or not record.get('id') or not isinstance(record.get('email'), str)
            or record['email'].casefold() != cfg['email'].casefold()):
        raise Fail(1, 'Authentication returned an unexpected identity; no session saved. Check LINKCONTEXT_USER_EMAIL.')
    session = {'url': cfg['url'], 'email': cfg['email'], 'token': token, 'method': method, 'refreshed_at': time.time()}
    save_session(cfg, session)
    return session


def oauth_send(cfg, method, path, body=None, token=None):
    try:
        return send(cfg, method, path, body, token)
    except Fail:
        raise Fail(1, 'OAuth authentication request failed; check the server URL and connection, then retry.') from None


def oauth_refresh_needed(session):
    try:
        payload = session['token'].split('.')[1]
        claims = json.loads(base64.urlsafe_b64decode(payload + '=' * (-len(payload) % 4)))
        now = time.time()
        refreshed_at = session['refreshed_at']
        return (not 0 <= now - refreshed_at < 300 or claims['exp'] <= now + 60)
    except (ValueError, TypeError, KeyError, IndexError):
        return True


def google_login(cfg, port=8765, timeout=180):
    if not 1 <= port <= 65535 or not 1 <= timeout <= 600:
        raise Fail(2, 'OAuth port must be 1–65535 and timeout must be 1–600 seconds')
    status, data = oauth_send(cfg, 'GET', '/api/collections/users/auth-methods')
    oauth = data.get('oauth2', {}) if isinstance(data, dict) else {}
    providers = oauth.get('providers', [])
    provider = next((p for p in providers if isinstance(p, dict) and p.get('name') == 'google'), None)
    if status != 200 or not oauth.get('enabled') or not provider:
        raise Fail(1, 'Google OAuth is not enabled on this LinkContext server.')
    auth_url = urllib.parse.urlsplit(provider.get('authURL', ''))
    if auth_url.scheme != 'https' or auth_url.hostname != 'accounts.google.com' or auth_url.username or auth_url.password or auth_url.fragment:
        raise Fail(1, 'Server returned an unexpected Google authorization URL.')
    state = secrets.token_urlsafe(32)
    verifier = hide(secrets.token_urlsafe(48))
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
    redirect = f'http://127.0.0.1:{port}/callback'
    metadata = urllib.parse.parse_qs(auth_url.query)
    client_ids = metadata.get('client_id', [])
    if len(client_ids) != 1 or not client_ids[0]:
        raise Fail(1, 'Server returned an invalid Google client ID.')
    params = {'client_id': client_ids[0]}
    params.update(state=state, code_challenge=challenge, code_challenge_method='S256', redirect_uri=redirect,
                  login_hint=cfg['email'], response_type='code', scope='openid email profile', access_type='online')
    url = urllib.parse.urlunsplit(auth_url._replace(query=urllib.parse.urlencode(params)))
    outcome = {}

    class Callback(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            parsed = urllib.parse.urlsplit(self.path)
            values = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
            code = values.get('code', [])
            valid_state = values.get('state', [])
            valid = (self.headers.get('Host') == f'127.0.0.1:{port}' and parsed.path == '/callback' and len(valid_state) == 1
                     and secrets.compare_digest(valid_state[0], state))
            if not valid:
                status, message = 400, 'Invalid sign-in callback. Return to your terminal.'
            elif 'error' in values:
                outcome['error'] = 'Google sign-in was denied or cancelled; run linkcontext login --google to retry.'
                status, message = 400, 'Sign-in was cancelled. Return to your terminal.'
            elif len(code) != 1 or not code[0]:
                outcome['error'] = 'Google returned an invalid sign-in callback.'
                status, message = 400, 'Invalid sign-in callback. Return to your terminal.'
            else:
                outcome['code'] = hide(code[0])
                status, message = 200, 'Authorization received. Return to your terminal to check sign-in.'
            self.send_response(status)
            self.send_header('Content-Type', 'text/plain; charset=utf-8')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.end_headers()
            self.wfile.write(message.encode())

    class Listener(http.server.HTTPServer):
        def get_request(self):
            connection, address = super().get_request()
            connection.settimeout(1)
            return connection, address

        def handle_error(self, request, client_address):
            pass

    try:
        server = Listener(('127.0.0.1', port), Callback)
    except OSError:
        raise Fail(1, f'Cannot listen on 127.0.0.1:{port}; check for another login process or choose --port.')
    with server:
        server.timeout = 0.25
        say(f'For SSH, forward this port: ssh -L {port}:127.0.0.1:{port} user@ssh-host')
        say('Open this URL in your browser (keep it private):\n' + url)
        deadline = time.monotonic() + timeout
        while not outcome and time.monotonic() < deadline:
            server.handle_request()
    if not outcome:
        raise Fail(1, 'Google sign-in timed out; run linkcontext login --google to retry.')
    if 'error' in outcome:
        raise Fail(1, outcome['error'])
    status, data = oauth_send(cfg, 'POST', '/api/collections/users/auth-with-oauth2', {
        'provider': 'google', 'code': outcome['code'], 'codeVerifier': verifier, 'redirectURL': redirect,
    })
    if status != 200:
        raise Fail(1, f'Google sign-in failed: HTTP {status}. Check Workspace eligibility, account access, and the redirect URI with your operator.')
    return auth_session(cfg, data, 'google')


def token_rejected(cfg, token):
    return send(cfg, 'POST', '/api/context/query', {'sql': 'SELECT 1'}, token)[0] == 401


def call(cfg, method, path, body=None):
    session = load_session(cfg)
    cached = session is not None
    if not cached:
        session = login(cfg)
    if session.get('method') == 'google' and (oauth_refresh_needed(session) or path == '/api/collections/users/auth-refresh'):
        status, data = oauth_send(cfg, 'POST', '/api/collections/users/auth-refresh', token=session['token'])
        if status != 200:
            raise Fail(1, f'Google session could not be refreshed (HTTP {status}); run linkcontext login --google again.')
        session = auth_session(cfg, data, 'google')
        if path == '/api/collections/users/auth-refresh':
            return status, data
    status, data = send(cfg, method, path, body, session['token'])
    if cached and 400 <= status < 500 and status != 409 and (status == 401 or token_rejected(cfg, session['token'])):
        if session.get('method') == 'google':
            raise Fail(1, 'Google session was rejected; run linkcontext login --google again.')
        session = login(cfg)
        status, data = send(cfg, method, path, body, session['token'])
    return status, data


def batch_failures(data):
    try:
        failures = []
        for index, entry in data['data']['requests'].items():
            response = entry['response']
            fields = [f'{name}: {detail.get("message")}' for name, detail in (response.get('data') or {}).items() if isinstance(detail, dict)]
            failures.append((index, response.get('status'), ' '.join([response.get('message') or ''] + fields)))
        return failures
    except (AttributeError, KeyError, TypeError):
        return []


def must(cfg, method, path, body=None):
    status, data = call(cfg, method, path, body)
    if status < 400:
        return data
    lines = [f'HTTP {status} from {method} {path}', dump(data, pretty=True)]
    conflict = status == 409
    if path == '/api/batch':
        lines.append('Nothing in this batch was saved.')
        for index, inner_status, message in batch_failures(data):
            lines.append(f'Failed request index {index}: HTTP {inner_status}: {message}')
            conflict = conflict or inner_status == 409
    if conflict:
        lines.append('HTTP 409: another request changed the record first. Read it again, confirm the change still applies, then retry.')
    raise Fail(4 if conflict else 1, '\n'.join(lines))


# Normalization, Deterministic IDs, and Upsert Helpers

def deterministic_id(namespace: str, canonical_key: str) -> str:
    """Derive a deterministic 15-character [a-z0-9] PocketBase ID from a namespace and canonical key."""
    ns = str(namespace or '').strip().lower()
    ck = str(canonical_key or '').strip()
    if not ns or not ck:
        raise Fail(2, 'deterministic_id requires non-empty namespace and canonical_key')
    digest = hashlib.sha256(f'{ns}:{ck}'.encode('utf-8')).digest()
    num = int.from_bytes(digest[:10], 'big')
    chars = []
    for _ in range(15):
        num, rem = divmod(num, 36)
        chars.append(DETERMINISTIC_ALPHABET[rem])
    return ''.join(chars)


def slugify(value: str) -> str:
    cleaned = re.sub(r'[^a-z0-9]+', '-', str(value or '').strip().lower()).strip('-')[:80]
    return cleaned or 'item'


def normalize_linkedin_url(raw_url: str) -> str:
    text = str(raw_url or '').strip()
    if not text:
        return ''
    parsed = urllib.parse.urlsplit(text)
    if not parsed.scheme:
        parsed = urllib.parse.urlsplit('https://' + text.lstrip('/'))
    host = (parsed.hostname or '').lower()
    if host.endswith('linkedin.com'):
        host = 'www.linkedin.com'
    path = re.sub(r'/+', '/', parsed.path or '/').rstrip('/')
    if not path:
        path = '/'
    return urllib.parse.urlunsplit(('https', host or 'www.linkedin.com', path, '', ''))


def extract_linkedin_slug(raw_url: str, prefix: str) -> str:
    text = str(raw_url or '').strip()
    if not text:
        return ''
    match = re.search(rf'/{re.escape(prefix)}/([^/?#]+)', text, flags=re.IGNORECASE)
    return urllib.parse.unquote(match.group(1)).strip().lower() if match else ''


def snowflake_urn_to_iso(urn: str) -> str:
    """Extract exact UTC creation timestamp from a LinkedIn numeric Snowflake URN (activity or ugcPost)."""
    match = re.search(r'urn:li:(?:activity|ugcPost|share):(\d{15,22})', str(urn or ''))
    if not match:
        return ''
    snowflake = int(match.group(1))
    ms = snowflake >> 22
    if 1262304000000 <= ms <= 4102444800000:
        dt = datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc)
        return dt.strftime('%Y-%m-%d %H:%M:%S.%f')[:-3] + 'Z'
    return ''


def format_pb_utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M:%S.%f')[:-3] + 'Z'


def parse_pb_utc(value: str):
    text = str(value or '').strip()
    if not text:
        return None
    normalized = text.replace(' ', 'T')
    if normalized.endswith('Z'):
        normalized = normalized[:-1] + '+00:00'
    try:
        dt = datetime.fromisoformat(normalized)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except ValueError:
        return None


def parse_since(since_str: str, now_dt=None) -> str:
    """Parse a duration ('7d', '24h', '2w', '30m') or ISO date string into PocketBase UTC date format."""
    text = str(since_str or '').strip()
    if not text:
        return ''
    now = now_dt or datetime.now(timezone.utc)
    match = re.fullmatch(r'(\d+)\s*([mhdw])', text.lower())
    if match:
        amount = int(match.group(1))
        unit = match.group(2)
        delta = {
            'm': timedelta(minutes=amount),
            'h': timedelta(hours=amount),
            'd': timedelta(days=amount),
            'w': timedelta(weeks=amount),
        }[unit]
        return format_pb_utc(now - delta)
    dt = parse_pb_utc(text)
    if dt is not None:
        return format_pb_utc(dt)
    raise Fail(2, f'invalid --since value "{since_str}": use a duration like 24h, 7d, 2w or an ISO-8601 timestamp')


def sql_quote(value: str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def normalize_item_for_upsert(collection: str, raw_item: dict, sync_run_id: str = None, now_str: str = None) -> tuple[dict, str, str]:
    """Return (normalized_record_dict, natural_key_column, natural_key_value)."""
    if not isinstance(raw_item, dict):
        raise Fail(2, 'each upsert item must be a JSON object')
    item = {k: v for k, v in raw_item.items() if k not in STAMPS and k not in ('revision', 'created', 'updated', 'expected_revision')}
    now = now_str or format_pb_utc(datetime.now(timezone.utc))
    if sync_run_id and collection in ('companies', 'profiles', 'connections', 'invitations', 'posts', 'post_interactions', 'notifications', 'threads', 'messages'):
        item.setdefault('last_sync_run', sync_run_id)

    if collection == 'companies':
        if item.get('linkedin_url'):
            item['linkedin_url'] = normalize_linkedin_url(item['linkedin_url'])
        universal = str(item.get('universal_name') or '').strip().lower()
        if not universal and item.get('linkedin_url'):
            universal = extract_linkedin_slug(item['linkedin_url'], 'company')
        if not universal and item.get('name'):
            universal = slugify(item['name'])
        if not universal:
            raise Fail(2, 'companies upsert requires universal_name, linkedin_url, or name')
        item['universal_name'] = universal
        item.setdefault('linkedin_url', f'https://www.linkedin.com/company/{universal}')
        item.setdefault('completeness', 'stub')
        item.setdefault('last_seen_at', now)
        item['id'] = item.get('id') or deterministic_id('companies', universal)
        return item, 'universal_name', universal

    if collection == 'profiles':
        if item.get('linkedin_url'):
            item['linkedin_url'] = normalize_linkedin_url(item['linkedin_url'])
        public_id = str(item.get('public_id') or '').strip().lower()
        if not public_id and item.get('linkedin_url'):
            public_id = extract_linkedin_slug(item['linkedin_url'], 'in')
        if not public_id and item.get('full_name'):
            public_id = slugify(item['full_name'])
        if not public_id:
            raise Fail(2, 'profiles upsert requires public_id, linkedin_url, or full_name')
        item['public_id'] = public_id
        item.setdefault('linkedin_url', f'https://www.linkedin.com/in/{public_id}')
        item.setdefault('completeness', 'stub')
        item.setdefault('connection_degree', 'unknown')
        item.setdefault('last_seen_at', now)
        item['id'] = item.get('id') or deterministic_id('profiles', public_id)
        return item, 'public_id', public_id

    if collection == 'experiences':
        exp_key = str(item.get('experience_key') or '').strip()
        if not exp_key:
            prof = str(item.get('profile') or '').strip()
            comp = slugify(item.get('company_name') or '')
            title = slugify(item.get('title') or '')
            start = str(item.get('start_date') or 'unknown').strip()
            if not prof or not item.get('company_name') or not item.get('title'):
                raise Fail(2, 'experiences upsert requires profile, company_name, and title')
            exp_key = f'{prof}:{comp}:{title}:{start}'
            item['experience_key'] = exp_key
        item['id'] = item.get('id') or deterministic_id('experiences', exp_key)
        return item, 'experience_key', exp_key

    if collection == 'connections':
        prof = str(item.get('profile') or '').strip()
        if not prof:
            raise Fail(2, 'connections upsert requires profile')
        item.setdefault('relationship_status', 'connected')
        item['id'] = item.get('id') or deterministic_id('connections', prof)
        return item, 'profile', prof

    if collection == 'invitations':
        inv_key = str(item.get('invitation_key') or '').strip()
        if not inv_key:
            prof = str(item.get('profile') or '').strip()
            direction = str(item.get('direction') or '').strip()
            if not prof or not direction:
                raise Fail(2, 'invitations upsert requires profile and direction')
            inv_key = f'{direction}:{prof}'
            item['invitation_key'] = inv_key
        item.setdefault('status', 'pending')
        item['id'] = item.get('id') or deterministic_id('invitations', inv_key)
        return item, 'invitation_key', inv_key

    if collection == 'posts':
        urn = str(item.get('post_urn') or '').strip()
        if not urn:
            raise Fail(2, 'posts upsert requires post_urn')
        item['post_urn'] = urn
        urn_iso = snowflake_urn_to_iso(urn)
        if urn_iso and (not item.get('published_at') or item.get('timestamp_precision') == 'relative_approx'):
            item['published_at'] = urn_iso
            item['timestamp_precision'] = 'exact_urn'
        item.setdefault('published_at', now)
        item.setdefault('timestamp_precision', 'exact_urn' if urn_iso else 'exact_dom')
        item.setdefault('permalink', f'https://www.linkedin.com/feed/update/{urllib.parse.quote(urn, safe=":")}/')
        item.setdefault('last_seen_at', now)
        item['id'] = item.get('id') or deterministic_id('posts', urn)
        return item, 'post_urn', urn

    if collection == 'post_interactions':
        ikey = str(item.get('interaction_key') or '').strip()
        if not ikey:
            post_id = str(item.get('post') or '').strip()
            actor_id = str(item.get('actor') or '').strip()
            kind = str(item.get('kind') or '').strip()
            if not post_id or not actor_id or not kind:
                raise Fail(2, 'post_interactions upsert requires post, actor, and kind')
            body_hash = hashlib.sha256(str(item.get('body') or '').encode('utf-8')).hexdigest()[:10]
            ikey = f'{kind}:{post_id}:{actor_id}:{body_hash}'
            item['interaction_key'] = ikey
        item.setdefault('occurred_at', now)
        item['id'] = item.get('id') or deterministic_id('post_interactions', ikey)
        return item, 'interaction_key', ikey

    if collection == 'notifications':
        nkey = str(item.get('notification_key') or '').strip()
        if not nkey:
            kind = str(item.get('kind') or '').strip()
            headline = str(item.get('headline') or '').strip()
            if not kind or not headline:
                raise Fail(2, 'notifications upsert requires kind and headline')
            actor = str(item.get('actor_profile') or item.get('actor_company') or 'system').strip()
            h_hash = hashlib.sha256(headline.encode('utf-8')).hexdigest()[:12]
            nkey = f'{kind}:{actor}:{h_hash}'
            item['notification_key'] = nkey
        item.setdefault('occurred_at', now)
        item.setdefault('timestamp_precision', 'exact_dom')
        item['id'] = item.get('id') or deterministic_id('notifications', nkey)
        return item, 'notification_key', nkey

    if collection == 'threads':
        turn = str(item.get('thread_urn') or '').strip()
        if not turn:
            raise Fail(2, 'threads upsert requires thread_urn')
        item['thread_urn'] = turn
        item['id'] = item.get('id') or deterministic_id('threads', turn)
        return item, 'thread_urn', turn

    if collection == 'thread_participants':
        thread_id = str(item.get('thread') or '').strip()
        prof_id = str(item.get('profile') or '').strip()
        if not thread_id or not prof_id:
            raise Fail(2, 'thread_participants upsert requires thread and profile')
        composite = f'{thread_id}:{prof_id}'
        item.setdefault('role', 'member')
        item['id'] = item.get('id') or deterministic_id('thread_participants', composite)
        return item, 'id', item['id']

    if collection == 'messages':
        mkey = str(item.get('message_key') or '').strip()
        if not mkey:
            thread_id = str(item.get('thread') or '').strip()
            direction = str(item.get('direction') or '').strip()
            sent_at = str(item.get('sent_at') or '').strip()
            body_text = str(item.get('body') or '').strip()
            if not thread_id or not direction or not body_text:
                raise Fail(2, 'messages upsert requires thread, direction, and body')
            b_hash = hashlib.sha256(body_text.encode('utf-8')).hexdigest()[:12]
            mkey = f'{thread_id}:{direction}:{sent_at}:{b_hash}'
            item['message_key'] = mkey
        item.setdefault('sent_at', now)
        item['id'] = item.get('id') or deterministic_id('messages', mkey)
        return item, 'message_key', mkey

    if collection == 'bookmarks':
        tcol = str(item.get('target_collection') or '').strip()
        tid = str(item.get('target_record_id') or '').strip()
        lname = str(item.get('list_name') or '').strip()
        if not tcol or not tid or not lname:
            raise Fail(2, 'bookmarks upsert requires target_collection, target_record_id, and list_name')
        composite = f'{tcol}:{tid}:{lname}'
        item.setdefault('status', 'active')
        item['id'] = item.get('id') or deterministic_id('bookmarks', composite)
        return item, 'id', item['id']

    raise Fail(2, f'upsert is not supported for collection "{collection}"')


def item_timestamp_for_cutoff(collection: str, item: dict) -> str:
    field_map = {
        'posts': 'published_at',
        'post_interactions': 'occurred_at',
        'notifications': 'occurred_at',
        'messages': 'sent_at',
        'invitations': 'sent_at',
        'threads': 'last_activity_at',
        'connections': 'connected_at',
    }
    field = field_map.get(collection)
    return str(item.get(field) or '') if field else ''


def is_empty_value(val) -> bool:
    return val is None or val == '' or val == [] or val == {}


def merge_record(collection: str, stored: dict, incoming: dict) -> dict | None:
    """Compute a non-destructive PATCH payload against stored row, or return None if no substantive change."""
    patch_body = {}
    stored_comp = COMPLETENESS_RANK.get(str(stored.get('completeness') or ''), 0)
    inc_comp = COMPLETENESS_RANK.get(str(incoming.get('completeness') or ''), 0)
    higher_stored_completeness = stored_comp > inc_comp and stored_comp > 0

    stored_prec = PRECISION_RANK.get(str(stored.get('timestamp_precision') or ''), 0)
    inc_prec = PRECISION_RANK.get(str(incoming.get('timestamp_precision') or ''), 0)

    substantive_change = False
    for key, val in incoming.items():
        if key in ('id', 'revision', 'created', 'updated', 'created_by', 'updated_by', 'first_seen_at'):
            continue
        if is_empty_value(val):
            continue
        old_val = stored.get(key)
        if key == 'completeness':
            if inc_comp > stored_comp:
                patch_body[key] = val
                substantive_change = True
            continue
        if key in ('published_at', 'occurred_at', 'timestamp_precision'):
            if stored_prec > inc_prec and not is_empty_value(old_val):
                continue
        if higher_stored_completeness and key not in VOLATILE_FIELDS and not is_empty_value(old_val):
            continue
        if old_val != val:
            patch_body[key] = val
            if key not in ('last_seen_at', 'last_sync_run'):
                substantive_change = True

    if not substantive_change:
        return None
    patch_body['expected_revision'] = int(stored['revision'])
    return patch_body


def run_upsert(cfg, args):
    collection = args.collection
    if collection not in BUSINESS_COLLECTIONS or collection == 'sync_runs':
        raise Fail(2, f'upsert supports business collections: {", ".join(c for c in BUSINESS_COLLECTIONS if c != "sync_runs")}')
    raw = read_json(args.json, (dict, list), 'the upsert payload')
    raw_items = [raw] if isinstance(raw, dict) else raw
    if not raw_items:
        return {
            'collection': collection,
            'scanned': 0,
            'created': 0,
            'updated': 0,
            'unchanged': 0,
            'skipped_before_cutoff': 0,
            'ids': [],
            'permalinks': [],
        }

    cutoff_dt = parse_pb_utc(parse_since(args.since)) if getattr(args, 'since', None) else None
    now_str = format_pb_utc(datetime.now(timezone.utc))

    normalized = []
    skipped_cutoff = 0
    for entry in raw_items:
        item, key_col, key_val = normalize_item_for_upsert(collection, entry, getattr(args, 'sync_run', None), now_str)
        if cutoff_dt is not None:
            ts_str = item_timestamp_for_cutoff(collection, item)
            ts_dt = parse_pb_utc(ts_str)
            if ts_dt is not None and ts_dt < cutoff_dt:
                skipped_cutoff += 1
                continue
        normalized.append((item, key_col, key_val))

    # Deduplicate within the incoming batch itself (later items merge into earlier items)
    deduped_map = {}
    key_col_name = normalized[0][1] if normalized else 'id'
    for item, key_col, key_val in normalized:
        dedup_key = (item['id'], key_val)
        if dedup_key in deduped_map:
            prev = deduped_map[dedup_key]
            for k, v in item.items():
                if not is_empty_value(v):
                    prev[k] = v
        else:
            deduped_map[dedup_key] = item

    candidates = list(deduped_map.values())
    existing_by_id = {}
    existing_by_key = {}

    # Query existing rows in chunks of 40
    for idx in range(0, len(candidates), 40):
        chunk = candidates[idx:idx + 40]
        ids_sql = ', '.join(sql_quote(c['id']) for c in chunk)
        where = f'id IN ({ids_sql})'
        if key_col_name != 'id':
            keys_sql = ', '.join(sql_quote(c[key_col_name]) for c in chunk if c.get(key_col_name))
            if keys_sql:
                where = f'{where} OR "{key_col_name}" IN ({keys_sql})'
        res = must(cfg, 'POST', '/api/context/query', {'sql': f'SELECT * FROM "{collection}" WHERE {where}'})
        cols = res.get('columns', [])
        for row_vals in res.get('rows', []):
            row_dict = dict(zip(cols, row_vals))
            existing_by_id[row_dict['id']] = row_dict
            if key_col_name != 'id' and row_dict.get(key_col_name):
                existing_by_key[str(row_dict[key_col_name])] = row_dict

    batch_ops = []
    final_ids = []
    created_count = 0
    updated_count = 0
    unchanged_count = 0

    for item in candidates:
        stored = existing_by_id.get(item['id']) or (existing_by_key.get(str(item.get(key_col_name))) if key_col_name != 'id' else None)
        if stored is None:
            batch_ops.append({
                'method': 'POST',
                'url': records(collection),
                'body': item,
            })
            final_ids.append(item['id'])
            created_count += 1
        else:
            record_id = stored['id']
            final_ids.append(record_id)
            patch_body = merge_record(collection, stored, item)
            if patch_body is None:
                unchanged_count += 1
            else:
                batch_ops.append({
                    'method': 'PATCH',
                    'url': records(collection, record_id),
                    'body': patch_body,
                })
                updated_count += 1

    for idx in range(0, len(batch_ops), 20):
        chunk_ops = batch_ops[idx:idx + 20]
        must(cfg, 'POST', '/api/batch', {'requests': chunk_ops})

    base_url = cfg['url'].rstrip('/')
    return {
        'collection': collection,
        'scanned': len(raw_items),
        'created': created_count,
        'updated': updated_count,
        'unchanged': unchanged_count,
        'skipped_before_cutoff': skipped_cutoff,
        'ids': final_ids,
        'permalinks': [f'{base_url}/#/{collection}/{rid}' for rid in final_ids],
    }


def run_sync_start(cfg, args):
    surface = args.surface
    res = must(cfg, 'POST', '/api/context/query', {
        'sql': f"SELECT id, surface, status, lookback_since, started_at, completed_at, newest_observed_at, stats_json FROM sync_runs WHERE surface = {sql_quote(surface)} AND status = 'completed' ORDER BY completed_at DESC LIMIT 1"
    })
    last_sync = dict(zip(res['columns'], res['rows'][0])) if res.get('rows') else None
    since_arg = getattr(args, 'since', None) or '7d'
    if since_arg == 'last-sync':
        if last_sync and (last_sync.get('newest_observed_at') or last_sync.get('completed_at')):
            lookback_since = last_sync.get('newest_observed_at') or last_sync.get('completed_at')
        else:
            lookback_since = parse_since('7d')
    else:
        lookback_since = parse_since(since_arg)

    payload = {
        'surface': surface,
        'status': 'running',
        'lookback_since': lookback_since,
        'started_at': format_pb_utc(datetime.now(timezone.utc)),
    }
    if getattr(args, 'max_items', None):
        payload['max_items'] = int(args.max_items)
    if getattr(args, 'notes', None):
        payload['notes'] = args.notes
    created = must(cfg, 'POST', records('sync_runs'), payload)
    return {
        'sync_run': created,
        'lookback_since': lookback_since,
        'last_completed_sync': last_sync,
    }


def run_sync_finish(cfg, args):
    sync_id = args.id
    if not re.fullmatch(r'[a-z0-9]{15}', sync_id):
        raise Fail(2, 'sync-run id must be 15 lowercase letters or digits')
    res = must(cfg, 'POST', '/api/context/query', {
        'sql': f"SELECT id, revision, status FROM sync_runs WHERE id = {sql_quote(sync_id)} LIMIT 1"
    })
    if not res.get('rows'):
        raise Fail(1, f'HTTP 404: sync_run {sync_id} not found')
    current = dict(zip(res['columns'], res['rows'][0]))
    patch_body = {
        'expected_revision': int(current['revision']),
        'status': args.status,
        'completed_at': format_pb_utc(datetime.now(timezone.utc)),
    }
    if getattr(args, 'stats', None):
        patch_body['stats_json'] = read_json(args.stats, dict, 'stats JSON')
    if getattr(args, 'oldest_observed_at', None):
        patch_body['oldest_observed_at'] = parse_since(args.oldest_observed_at)
    if getattr(args, 'newest_observed_at', None):
        patch_body['newest_observed_at'] = parse_since(args.newest_observed_at)
    if getattr(args, 'notes', None):
        patch_body['notes'] = args.notes
    return must(cfg, 'PATCH', records('sync_runs', sync_id), patch_body)


# Commands

def read_json(text, kind, what):
    if text == '-':
        text = sys.stdin.read()
    try:
        value = json.loads(text)
    except ValueError as error:
        raise Fail(2, f'{what} is not valid JSON: {error}')
    if not isinstance(value, kind):
        if isinstance(kind, tuple):
            raise Fail(2, f'{what} must be a JSON object or array')
        raise Fail(2, f'{what} must be a JSON {"array" if kind is list else "object"}')
    return value


def require_revision(body):
    if type(body.get('expected_revision')) is not int or body['expected_revision'] < 1:
        raise Fail(2, 'updates require expected_revision from your last read; read the record before changing it')


def record_body(text):
    body = read_json(text, dict, 'the record body')
    for field in STAMPS:
        if field in body:
            del body[field]
            say(f'note: removed {field} from the body; the server sets it from your login')
    if not body:
        raise Fail(2, 'the record body has no fields to send')
    return body


def records(collection, record=None):
    path = f'/api/collections/{urllib.parse.quote(collection, safe="")}/records'
    return path if record is None else f'{path}/{urllib.parse.quote(record, safe="")}'


def columns(tables):
    return {table['name']: {column['name']: column.get('type') for column in table['columns']} for table in tables}


def check(cfg):
    try:
        reference = columns(json.loads(SCHEMA_FILE.read_text())['tables'])
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise Fail(2, f'cannot read {SCHEMA_FILE}: {error}')
    live = columns(must(cfg, 'GET', '/api/context/schema')['tables'])
    differences = []
    for table in sorted(set(live) | set(reference)):
        if table not in reference:
            differences.append(f'table {table}: on the server, not in the reference files')
        elif table not in live:
            differences.append(f'table {table}: in the reference files, not on the server')
        else:
            for column in sorted(set(live[table]) | set(reference[table])):
                if column not in reference[table]:
                    differences.append(f'column {table}.{column}: on the server, not in the reference files')
                elif column not in live[table]:
                    differences.append(f'column {table}.{column}: in the reference files, not on the server')
                elif live[table][column] != reference[table][column]:
                    differences.append(f'column {table}.{column}: type {live[table][column]} on the server, {reference[table][column]} in the reference files')
    if not differences:
        say(f'OK: the live schema matches references/schema.json ({len(live)} tables)', sys.stdout)
        return 0
    for line in differences:
        say(line, sys.stdout)
    say('The server is authoritative: run `linkcontext schema` and follow the server\'s error messages where the reference files disagree. '
        'Ask the user to update this skill.', sys.stdout)
    return 3


def run(args):
    if args.command == 'newid':
        print(''.join(secrets.choice(ID_ALPHABET) for _ in range(15)))
        return 0
    if args.command == 'deterministic-id':
        print(deterministic_id(args.namespace, args.key))
        return 0
    if args.command == 'logout':
        cfg = config(ENV[:2])
        path = session_file(cfg)
        path.unlink(missing_ok=True)
        legacy_session_file(cfg).unlink(missing_ok=True)
        say(f'removed {path}', sys.stdout)
        return 0
    cfg = config()
    if args.command == 'login':
        google_login(cfg, args.port, args.timeout)
        say(f'Signed in as {cfg["email"]} at {cfg["url"]}', sys.stdout)
        return 0
    body = None
    if args.command in ('create', 'update'):
        body = record_body(args.json)
        if args.command == 'update':
            require_revision(body)
    elif args.command == 'batch':
        requests = read_json(args.json, list, 'the batch')
        if not all(isinstance(entry, dict) for entry in requests):
            raise Fail(2, 'each batch entry must be an object with method, url, and body')
        allowed_pattern = '|'.join(BUSINESS_COLLECTIONS)
        for entry in requests:
            method, url = entry.get('method'), entry.get('url', '')
            if method not in ('POST', 'PATCH') or not isinstance(url, str) or not re.fullmatch(rf'/api/collections/({allowed_pattern})/records(?:/[a-z0-9]{{15}})?', url):
                raise Fail(2, 'batch accepts only POST/PATCH business record URLs')
            if not isinstance(entry.get('body'), dict):
                raise Fail(2, 'each batch body must be an object')
            if method == 'PATCH':
                require_revision(entry['body'])
        body = {'requests': requests}
    if args.command == 'check':
        return check(cfg)
    if args.command == 'whoami':
        refreshed = must(cfg, 'POST', '/api/collections/users/auth-refresh')
        hide(refreshed.get('token'))
        record = refreshed['record']
        data = {'id': record['id'], 'name': record.get('name', ''), 'email': cfg['email'], 'url': cfg['url']}
    elif args.command == 'schema':
        data = must(cfg, 'GET', '/api/context/schema')
    elif args.command in ('sql', 'query'):
        query = sys.stdin.read() if args.query == '-' else args.query
        data = must(cfg, 'POST', '/api/context/query', {'sql': query})
        if isinstance(data, dict) and data.get('truncated'):
            say(f'WARNING: result truncated to {len(data.get("rows", []))} rows by the server\'s row or byte limit. Select fewer columns, narrow the query, or page with ORDER BY and LIMIT/OFFSET.')
    elif args.command == 'get':
        if not re.fullmatch(r'[a-z0-9]{15}', args.id):
            raise Fail(2, 'record id must be 15 lowercase letters or digits')
        schema = must(cfg, 'GET', '/api/context/schema')
        table = next((table for table in schema['tables'] if table['name'] == args.collection), None)
        if table is None or not any(column['name'] == 'id' for column in table['columns']):
            raise Fail(2, 'collection is not an SQL-readable table with an id column')
        identifier = '"' + table['name'].replace('"', '""') + '"'
        result = must(cfg, 'POST', '/api/context/query', {
            'sql': f"SELECT * FROM {identifier} WHERE id = '{args.id}' LIMIT 1"
        })
        if result.get('truncated'):
            raise Fail(1, 'record exceeds the SQL response limit; query only the needed fields')
        if not result['rows']:
            raise Fail(1, f'HTTP 404: record not found in {args.collection}')
        data = dict(zip(result['columns'], result['rows'][0]))
    elif args.command == 'create':
        data = must(cfg, 'POST', records(args.collection), body)
    elif args.command == 'update':
        data = must(cfg, 'PATCH', records(args.collection, args.id), body)
    elif args.command == 'batch':
        data = must(cfg, 'POST', '/api/batch', body)
    elif args.command == 'upsert':
        data = run_upsert(cfg, args)
    elif args.command == 'sync-start':
        data = run_sync_start(cfg, args)
    elif args.command == 'sync-finish':
        data = run_sync_finish(cfg, args)
    say(dump(data, args.pretty), sys.stdout)
    return 0


def parse(argv):
    pretty = argparse.ArgumentParser(add_help=False)
    pretty.add_argument('--pretty', action='store_true', default=argparse.SUPPRESS, help='indent the JSON output')
    parser = argparse.ArgumentParser(
        prog='linkcontext',
        parents=[pretty],
        description='LinkContext LinkedIn graph client. Reads with SQL, writes through the records API and idempotent upsert. Users cannot delete records.',
        epilog='Environment: ' + ', '.join(ENV) + '. JSON arguments may be "-" to read standard input. Exit codes: 0 ok, 1 HTTP or transport error, 2 usage or configuration, 3 check found differences, 4 HTTP 409.',
    )
    commands = parser.add_subparsers(dest='command', required=True, metavar='command')

    def add(name, text, *arguments):
        command = commands.add_parser(name, parents=[pretty], help=text, description=text)
        for argument, argument_help in arguments:
            command.add_argument(argument, help=argument_help)
        return command

    oauth_login = commands.add_parser('login', help='sign in with Google using a browser and a loopback callback')
    oauth_login.add_argument('--google', action='store_true', required=True)
    oauth_login.add_argument('--port', type=int, default=8765, help='loopback callback port; register the matching redirect URI')
    oauth_login.add_argument('--timeout', type=int, default=180, help='seconds to wait for the browser (1–600)')
    add('whoami', 'print the user id, name, and server URL')
    add('check', 'compare the live schema with references/schema.json; exit 3 when they differ')
    add('schema', 'print the live SQL tables and columns')
    add('query', 'run one read-only SELECT', ('query', 'SQL text, or - for standard input'))
    add('sql', 'run one read-only SELECT', ('query', 'SQL text, or - for standard input'))
    add('get', 'read one record as an SQL row object', ('collection', 'collection name'), ('id', 'record id'))
    add('create', 'create one record', ('collection', 'collection name'), ('json', 'JSON object, or -'))
    add('update', 'change fields of one record', ('collection', 'collection name'), ('id', 'record id'), ('json', 'JSON object with the fields to change, or -'))
    add('batch', 'send up to 20 writes as one transaction', ('json', 'JSON array of {"method","url","body"}, or -'))
    upsert_cmd = add('upsert', 'idempotently normalize, deduplicate, merge, and batch-write one or more LinkedIn records', ('collection', 'collection name'), ('json', 'JSON object or array, or -'))
    upsert_cmd.add_argument('--sync-run', dest='sync_run', help='optional 15-char sync_runs record ID to link')
    upsert_cmd.add_argument('--since', help='optional lookback cutoff (e.g., 7d, 24h, or ISO-8601 timestamp) to skip older items')
    sync_start_cmd = add('sync-start', 'start an extraction sync_run and return lookback_since and last watermark', ('surface', 'surface name: feed, notifications, network, invitations, messages, profile_detail, company_detail'))
    sync_start_cmd.add_argument('--since', default='7d', help='lookback window: duration (24h, 7d, 2w), ISO timestamp, or "last-sync"')
    sync_start_cmd.add_argument('--max-items', dest='max_items', type=int, help='optional maximum item budget for this run')
    sync_start_cmd.add_argument('--notes', help='optional notes for this sync run')
    sync_finish_cmd = add('sync-finish', 'complete or fail a sync_run with metrics', ('id', '15-character sync_runs record id'))
    sync_finish_cmd.add_argument('--status', required=True, choices=('completed', 'partial', 'failed'), help='final sync run status')
    sync_finish_cmd.add_argument('--stats', help='JSON object of metrics (e.g. {"scanned":20,"created":5})')
    sync_finish_cmd.add_argument('--oldest-observed-at', dest='oldest_observed_at', help='oldest item timestamp observed')
    sync_finish_cmd.add_argument('--newest-observed-at', dest='newest_observed_at', help='newest item timestamp observed')
    sync_finish_cmd.add_argument('--notes', help='optional completion notes')
    add('deterministic-id', 'compute a deterministic 15-character record id from a namespace and canonical key', ('namespace', 'collection or namespace'), ('key', 'canonical natural key'))
    add('newid', 'print a new random 15-character record id for use inside a batch')
    add('logout', 'remove the cached token')
    args = parser.parse_args(argv)
    args.pretty = getattr(args, 'pretty', False)
    return args


def main():
    try:
        with instrument_cli(service='linkcontext.client', opener=opener):
            return run(parse(sys.argv[1:]))
    except Fail as error:
        say(f'linkcontext: {error}')
        return error.code
    except KeyboardInterrupt:
        return 130
    except Exception as error:
        say(f'linkcontext: unexpected {type(error).__name__}: {error}')
        return 1


if __name__ == '__main__':
    sys.exit(main())

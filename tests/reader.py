#!/usr/bin/env python3
"""Verify reader asset serving, CSP headers, schema parity, and real browser navigation."""
import argparse
import json
from pathlib import Path
import subprocess
import urllib.error
import urllib.request
from integration import ROOT, server


def get(url):
    try:
        with urllib.request.urlopen(url, timeout=10) as r:
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()


parser = argparse.ArgumentParser()
parser.add_argument('--binary', required=True)
parser.add_argument('--browser', action='store_true')
args = parser.parse_args()
subprocess.run(['pnpm', 'build'], cwd=ROOT / 'ui', check=True)
asset = next((ROOT / 'ui/dist/assets').glob('*.js')).name
with server(args.binary) as request:
    admin = request('POST', '/api/collections/_superusers/auth-with-password', {'identity': 'admin@example.com', 'password': 'SyntheticAdminPassword123!'})['token']
    password = 'SyntheticReaderPassword123!'
    request('POST', '/api/collections/users/records', {'email': 'reader@example.com', 'name': 'Synthetic reader', 'password': password, 'passwordConfirm': password}, admin)
    token = request('POST', '/api/collections/users/auth-with-password', {'identity': 'reader@example.com', 'password': password})['token']
    schema = request('GET', '/api/context/schema', token=token)
    assert json.loads((ROOT / 'ui/src/schema.snapshot.json').read_text()) == schema
    table = next(e['name'] for e in schema['tables'] if e['name'] not in ('user_directory', 'audit_log') and any(c['name'] == 'name' for c in e['columns']))
    records = [request('POST', f'/api/collections/{table}/records', {'name': f'Synthetic reader {i:02}'}, token) for i in range(35)]
    status, headers, body = get(request.base_url + '/')
    assert status == 200 and "script-src 'self'" in headers['Content-Security-Policy'] and b'<div id="root"></div>' in body
    assert get(request.base_url + '/assets/' + asset)[0] == 200
    for probe in ('/pocketcontext.json', '/assets/../pocketcontext.json', '/assets/missing.js', '/unknown'):
        assert get(request.base_url + probe)[0] == 404, probe
    if args.browser:
        subprocess.run(['node', str(ROOT / 'tests/reader-browser.cjs'), request.base_url, table, records[0]['id'], 'Synthetic reader 00', password], cwd=ROOT / 'ui', check=True)
print('PASS: reader assets, headers, route isolation, and schema snapshot')

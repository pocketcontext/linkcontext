#!/usr/bin/env python3
"""Exercise LinkContext through HTTP against an isolated temporary database."""
import argparse
import concurrent.futures
import contextlib
import json
from pathlib import Path
import socket
import shutil
import subprocess
import tempfile
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]

@contextlib.contextmanager
def server(binary):
    with tempfile.TemporaryDirectory(prefix='linkcontext-test-') as tmp:
        hooks = Path(tmp) / 'pb_hooks'
        shutil.copytree(ROOT / 'pb_hooks', hooks)
        (hooks / 'failure_fixture.pb.js').write_text('''
onRecordCreateExecute((e) => {
  if(e.record.getString('record') === 'auditfailure001') throw new Error('Synthetic audit failure');
  e.next();
}, 'audit_log');
onRecordCreateExecute((e) => {
  if(e.record.id === 'dirfailure00001') throw new Error('Synthetic directory failure');
  e.next();
}, 'user_directory');
''')
        common = [str(Path(binary).resolve()), '--dir', str(Path(tmp) / 'pb_data'), '--migrationsDir', str(ROOT / 'pb_migrations'), '--hooksDir', str(hooks)]
        result = subprocess.run(common + ['superuser', 'upsert', 'admin@example.com', 'SyntheticAdminPassword123!'], cwd=ROOT, capture_output=True, text=True)
        assert result.returncode == 0, result.stdout + result.stderr
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        with open(Path(tmp) / 'server.log', 'w+') as log:
            proc = subprocess.Popen(common + ['serve', '--http', f'127.0.0.1:{port}'], cwd=ROOT, stdout=log, stderr=log)
            def request(method, path, body=None, token=None, expected=200):
                headers = {'Content-Type': 'application/json'}
                if token:
                    headers['Authorization'] = token
                req = urllib.request.Request(f'http://127.0.0.1:{port}' + path, data=None if body is None else json.dumps(body).encode(), headers=headers, method=method)
                try:
                    with urllib.request.urlopen(req, timeout=20) as r:
                        status, raw = r.status, r.read()
                except urllib.error.HTTPError as e:
                    status, raw = e.code, e.read()
                assert status in (expected if isinstance(expected, tuple) else (expected,)), (method, path, status, raw.decode())
                return json.loads(raw) if raw else None
            try:
                for _ in range(150):
                    try:
                        request('GET', '/api/health')
                        break
                    except (OSError, AssertionError):
                        if proc.poll() is not None:
                            log.seek(0)
                            raise AssertionError(log.read())
                        time.sleep(.1)
                else:
                    raise AssertionError('Server startup timed out')
                request.base_url = f'http://127.0.0.1:{port}'
                yield request
            finally:
                proc.terminate()
                proc.wait(timeout=15)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--binary', required=True)
    args = parser.parse_args()
    with server(args.binary) as request:
        path = lambda table: '/api/collections/' + table + '/records'
        admin = request('POST', '/api/collections/_superusers/auth-with-password', {'identity': 'admin@example.com', 'password': 'SyntheticAdminPassword123!'})['token']
        user = request('POST', path('users'), {'email': 'agent@example.com', 'name': 'Synthetic agent', 'password': 'SyntheticUserPassword123!', 'passwordConfirm': 'SyntheticUserPassword123!'}, admin)
        token = request('POST', '/api/collections/users/auth-with-password', {'identity': 'agent@example.com', 'password': 'SyntheticUserPassword123!'})['token']
        create = lambda table, body: request('POST', path(table), body, token)
        def patch(table, row, body, expected=200):
            return request('PATCH', path(table) + '/' + row['id'], dict(expected_revision=row['revision'], **body), token, expected)

        # Audit failure rolls back business write
        request('POST', path('companies'), {'id': 'auditfailure001', 'name': 'Audit rollback'}, token, (400, 500))
        request('GET', path('companies') + '/auditfailure001', token=token, expected=404)

        # Companies & revision concurrency
        company = create('companies', {'name': 'Synthetic Corp', 'universal_name': 'synthetic-corp', 'industry': 'Software', 'completeness': 'full'})
        assert company['revision'] == 1 and company['created_by'] == user['id']
        assert company['linkedin_url'] == 'https://www.linkedin.com/company/synthetic-corp'
        request('POST', path('companies'), {'name': 'Duplicate Corp', 'universal_name': 'synthetic-corp'}, token, 400)
        request('PATCH', path('companies') + '/' + company['id'], {'tagline': 'Missing revision'}, token, 400)
        updated = patch('companies', company, {'tagline': 'Enterprise AI'})
        patch('companies', company, {'tagline': 'Stale'}, 409)
        patch('companies', updated, {'revision': 42}, 400)
        def race(i):
            return patch('companies', updated, {'tagline': f'Concurrent {i}'}, (200, 409))
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(race, range(2)))
        assert sum('id' in r for r in results) == 1

        # Sync runs lifecycle
        sync_run = create('sync_runs', {'surface': 'feed', 'status': 'running', 'max_items': 50})
        completed_run = patch('sync_runs', sync_run, {'status': 'completed', 'stats_json': {'scanned': 10, 'created': 2}})
        assert completed_run['completed_at']
        patch('sync_runs', completed_run, {'status': 'running'}, 400)
        patch('sync_runs', completed_run, {'surface': 'messages'}, 400)

        # Profiles & Experiences
        profile = create('profiles', {
            'full_name': 'Synthetic Founder',
            'linkedin_url': 'https://www.linkedin.com/in/synthetic-founder',
            'headline': 'CEO at Synthetic Corp',
            'current_company': company['id'],
            'connection_degree': 'first',
            'completeness': 'full',
            'last_sync_run': completed_run['id'],
        })
        assert profile['public_id'] == 'synthetic-founder'
        request('POST', path('profiles'), {'full_name': 'Duplicate', 'public_id': 'synthetic-founder'}, token, 400)

        exp = create('experiences', {
            'profile': profile['id'],
            'company': company['id'],
            'company_name': 'Synthetic Corp',
            'title': 'CEO',
            'is_current': True,
            'start_date': '2024-01',
        })
        assert exp['experience_key']
        request('POST', path('experiences'), {
            'profile': profile['id'],
            'company_name': 'Synthetic Corp',
            'title': 'CEO',
            'is_current': True,
            'start_date': '2024-01',
            'end_date': '2025-01',
        }, token, 400)

        # Connections & Invitations
        conn = create('connections', {'profile': profile['id'], 'relationship_status': 'connected'})
        request('POST', path('connections'), {'profile': profile['id'], 'relationship_status': 'connected'}, token, 400)
        invite = create('invitations', {'profile': profile['id'], 'direction': 'incoming', 'status': 'pending', 'message': 'Let us connect'})
        accepted_invite = patch('invitations', invite, {'status': 'accepted'})
        assert accepted_invite['resolved_at']
        patch('invitations', accepted_invite, {'direction': 'outgoing'}, 400)

        # Posts & Post Interactions
        request('POST', path('posts'), {'post_urn': 'urn:li:activity:7250000000000000001', 'body': 'No author'}, token, 400)
        request('POST', path('posts'), {
            'post_urn': 'urn:li:activity:7250000000000000001',
            'author_profile': profile['id'],
            'author_company': company['id'],
            'body': 'Both authors',
        }, token, 400)
        post = create('posts', {
            'post_urn': 'urn:li:activity:7250000000000000001',
            'author_profile': profile['id'],
            'body': 'Launching our new product today!',
            'reaction_count': 12,
            'comment_count': 3,
            'published_at': '2026-10-15 10:00:00.000Z',
        })
        assert post['author_type'] == 'profile'
        repost = create('posts', {
            'post_urn': 'urn:li:activity:7250000000000000002',
            'author_company': company['id'],
            'feed_reason': 'repost',
            'media_type': 'repost',
            'reposted_post': post['id'],
            'body': 'Excited to share this milestone.',
            'published_at': '2026-10-15 11:00:00.000Z',
        })
        assert repost['author_type'] == 'company'

        request('POST', path('post_interactions'), {'post': post['id'], 'actor': profile['id'], 'kind': 'comment'}, token, 400)
        request('POST', path('post_interactions'), {'post': post['id'], 'actor': profile['id'], 'kind': 'reaction', 'reaction_type': 'none'}, token, 400)
        comment = create('post_interactions', {
            'interaction_key': 'urn:li:comment:(activity:7250000000000000001,1)',
            'post': post['id'],
            'actor': profile['id'],
            'kind': 'comment',
            'body': 'Congrats on the launch!',
            'occurred_at': '2026-10-15 12:00:00.000Z',
        })
        assert comment['reaction_type'] == 'none'

        # Notifications
        notif = create('notifications', {
            'notification_key': 'urn:li:notification:1001',
            'kind': 'post_comment',
            'actor_profile': profile['id'],
            'target_post': post['id'],
            'headline': 'Synthetic Founder commented on your post',
            'snippet': 'Congrats on the launch!',
            'occurred_at': '2026-10-15 12:00:00.000Z',
        })
        assert notif['triage_status'] == 'unreviewed'

        # Threads, Participants, Messages
        thread = create('threads', {
            'thread_urn': 'urn:li:messagingThread:2-synthetic-thread-1',
            'title': 'Synthetic Founder',
            'primary_profile': profile['id'],
            'unread_count': 1,
        })
        tp = create('thread_participants', {'thread': thread['id'], 'profile': profile['id'], 'role': 'initiator'})
        request('POST', path('thread_participants'), {'thread': thread['id'], 'profile': profile['id']}, token, 400)
        request('POST', path('messages'), {'thread': thread['id'], 'direction': 'incoming', 'body': 'Missing sender'}, token, 400)
        msg = create('messages', {
            'message_key': 'urn:li:messagingMessage:2-msg-1',
            'thread': thread['id'],
            'sender': profile['id'],
            'direction': 'incoming',
            'body': 'Hi, would love to discuss a partnership.',
            'sent_at': '2026-10-16 09:30:00.000Z',
        })
        assert msg['id']

        # Bookmarks & target validation
        request('POST', path('bookmarks'), {
            'list_name': 'hot-prospects',
            'target_collection': 'profiles',
            'target_record_id': 'nonexistent0001',
            'title': 'Missing target',
        }, token, 400)
        bookmark = create('bookmarks', {
            'list_name': 'hot-prospects',
            'target_collection': 'profiles',
            'target_record_id': profile['id'],
            'title': 'Synthetic Founder — Priority Outreach',
            'notes': 'Follow up on partnership message',
        })
        assert bookmark['status'] == 'active'
        request('POST', path('bookmarks'), {
            'list_name': 'hot-prospects',
            'target_collection': 'profiles',
            'target_record_id': profile['id'],
            'title': 'Duplicate bookmark',
        }, token, 400)

        # Delete & audit_log immutability
        request('DELETE', path('companies') + '/' + company['id'], token=token, expected=(403, 404))
        request('POST', path('audit_log'), {'action': 'create'}, token, 403)
        rows = request('POST', '/api/context/query', {'sql': 'SELECT id, full_name, public_id FROM profiles'}, token)
        assert rows['rows']
        request('POST', '/api/context/query', {'sql': 'SELECT * FROM users'}, token, 400)
        audit = request('GET', path('audit_log') + '?perPage=100', token=token)['items']
        assert len(audit) >= 12
        # Transactional batch rollback when one request fails
        batch = request('POST', '/api/batch', {'requests': [
            {'method': 'POST', 'url': path('companies'), 'body': {'name': 'Rollback company', 'universal_name': 'rollback-company'}},
            {'method': 'POST', 'url': path('posts'), 'body': {'post_urn': 'urn:li:activity:invalid', 'body': 'Missing author'}},
        ]}, token, (400, 403))
        rolled_back = request('POST', '/api/context/query', {'sql': "SELECT id FROM companies WHERE universal_name = 'rollback-company'"}, token)
        assert rolled_back['rows'] == [], batch
    print('LinkContext integration checks passed')

if __name__ == '__main__':
    main()

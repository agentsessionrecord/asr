"""Export the packaged synthetic SQLite fixture with a built Crush binary."""
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile

package = Path(__file__).resolve().parent
binary = Path(sys.argv[1]).resolve()
fixture = json.loads((package / 'samples/native/native.json').read_text())
with tempfile.TemporaryDirectory(prefix='crush-asr-native-') as temporary:
    work = Path(temporary)
    environment = dict(os.environ, XDG_CONFIG_HOME=str(work / 'config'),
                       XDG_DATA_HOME=str(work / 'share'), CRUSH_DISABLE_METRICS='1',
                       CRUSH_DISABLE_PROVIDER_AUTO_UPDATE='1')
    data = work / 'data'
    command = [str(binary), '--cwd', str(work), '--data-dir', str(data), 'session']
    subprocess.run(command + ['list', '--json'], env=environment, check=True, capture_output=True)
    session = fixture['session']
    with sqlite3.connect(data / 'crush.db') as database:
        database.execute('INSERT INTO sessions (id,title,message_count,created_at,updated_at) VALUES (?,?,?,?,?)',
                         (session['id'], session['title'], session['message_count'], session['created_at'], session['updated_at']))
        for row in fixture['messages']:
            database.execute('INSERT INTO messages (id,session_id,role,parts,created_at,updated_at) VALUES (?,?,?,?,?,?)',
                             (row['id'], row['session_id'], row['role'], row['parts'], row['created_at'], row['updated_at']))
    shown = subprocess.run(command + ['show', session['id'], '--format', 'agent-session'], env=environment,
                           check=True, capture_output=True).stdout
    target = work / 'session.asr.jsonl'
    subprocess.run(command + ['show', session['id'], '-o', str(target)], env=environment, check=True, capture_output=True)
    assert target.read_bytes() == shown
    assert target.stat().st_mode & 0o777 == 0o600
    if '--write' in sys.argv:
        (package / 'samples/asr/session.jsonl').write_bytes(shown)
    else:
        assert [json.loads(row) for row in shown.splitlines()] == [json.loads(row) for row in (package / 'samples/asr/session.jsonl').read_bytes().splitlines()]
    print('crush: native CLI fixture reproduced with explicit format and inferred file output')

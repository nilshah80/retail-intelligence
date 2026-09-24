"""Create, serve, stop or discard only the isolated Castrol demonstration."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

from convert import DEFAULT_BACKUP, DSN, HERE, ROOT, RUNTIME, convert

COMPOSE = ['docker', 'compose', '-f', str(HERE/'compose.yaml')]


def check_backup(folder):
    manifest=json.loads((folder/'backup-manifest.json').read_text())
    dump=folder/manifest['dumpFile']
    expected=next(line.split('  ',1)[0] for line in (folder/'SHA256SUMS.txt').read_text().splitlines()
                  if line.endswith('  '+manifest['dumpFile']))
    digest=hashlib.sha256()
    with dump.open('rb') as handle:
        for block in iter(lambda:handle.read(4*1024*1024),b''):digest.update(block)
    if digest.hexdigest()!=expected:
        raise RuntimeError('Backup dump checksum mismatch')
    return dump


def prepare(folder):
    import psycopg
    dump=check_backup(folder)
    subprocess.run([*COMPOSE,'up','-d','--wait'],check=True,cwd=ROOT)
    with psycopg.connect(DSN) as conn:
        converted=conn.execute("SELECT to_regnamespace('castrol_demo')").fetchone()[0]
        if converted:
            if not (RUNTIME/'runtime/publication-manifest.json').is_file():
                raise RuntimeError('Converted database exists but runtime files are missing; restore those files or discard/rebuild the demo')
            print('Castrol demo is already prepared; use serve.',flush=True)
            return
        restored=conn.execute("SELECT to_regclass('retail_serving.forecast_materializations')").fetchone()[0]
    if not restored:
        print('Restoring into isolated Castrol container...',flush=True)
        with dump.open('rb') as handle:
            subprocess.run(['docker','exec','-i','retail-castrol-demo-postgres','pg_restore','-U','retail',
                            '-d','retail_intelligence','--no-owner','--no-acl','--exit-on-error'],stdin=handle,check=True)
    convert(folder)


def stop_child(process):
    if process is None or process.poll() is not None:
        return
    if os.name=='nt':
        subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],check=False,capture_output=True)
    else:
        os.killpg(process.pid,signal.SIGTERM)
        try:process.wait(timeout=10)
        except subprocess.TimeoutExpired:os.killpg(process.pid,signal.SIGKILL)


def require_free_ports():
    # Refuse another local instance instead of briefly showing its data through
    # the new UI while the newly launched API is still compiling.
    for port in (8080,5173):
        with socket.socket(socket.AF_INET,socket.SOCK_STREAM) as probe:
            try:
                probe.bind(('127.0.0.1',port))
            except OSError as error:
                raise RuntimeError(f'Port {port} is already in use; stop the existing API/UI instance before serving Castrol') from error


def wait_for_api(process, timeout=180):
    deadline=time.monotonic()+timeout
    last_error='API has not answered yet'
    base='http://127.0.0.1:8080'
    while time.monotonic()<deadline:
        code=process.poll()
        if code is not None:
            raise RuntimeError(f'API exited with status {code} before Castrol readiness')
        try:
            payloads=[]
            for path in ['/healthz','/api/v1/data-management/dashboard','/api/v1/data-management/gates']:
                with urllib.request.urlopen(base+path,timeout=2) as response:
                    payloads.append(json.load(response))
            health,dashboard,gates=payloads
            markets=dashboard.get('filters',{}).get('markets',[])
            marker=gates.get('gateA',{}).get('adaptation',{})
            if health.get('status')!='ok':
                raise ValueError('Health endpoint does not report ok')
            if not markets or any('castrol' not in str(m.get('name','')).lower() for m in markets):
                raise ValueError('Served market is not the Castrol demo')
            if marker.get('name')!='Castrol disposable environment':
                raise ValueError('Served evidence has no Castrol demo adaptation marker')
            if process.poll() is not None:
                raise RuntimeError('API exited during Castrol readiness checks')
            return
        except (OSError,ValueError,urllib.error.URLError) as error:
            last_error=str(error)
            time.sleep(0.25)
    raise RuntimeError(f'API was not ready after {timeout}s: {last_error}')


def wait_for_ui(process, timeout=30):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        code=process.poll()
        if code is not None:
            raise RuntimeError(f'UI exited with status {code} before readiness')
        try:
            with urllib.request.urlopen('http://127.0.0.1:5173/',timeout=2) as response:
                if response.status==200:
                    return
        except (OSError,urllib.error.URLError):
            pass
        time.sleep(0.25)
    raise RuntimeError(f'UI was not ready after {timeout}s')


def serve():
    import psycopg
    require_free_ports()
    subprocess.run([*COMPOSE,'up','-d','--wait'],check=True,cwd=ROOT)
    with psycopg.connect(DSN,options='-c default_transaction_read_only=on') as conn:
        if not conn.execute("SELECT to_regnamespace('castrol_demo')").fetchone()[0]:
            raise RuntimeError('Run prepare before serving this database')
        scopes=conn.execute('SELECT activation_scope_fingerprint FROM retail_serving.active_forecast_versions').fetchall()
        if len(scopes)!=1:raise RuntimeError('Expected one active demo forecast')
        scope=scopes[0][0]
    runtime=RUNTIME/'runtime'
    for name in ['gate-a.json','gate-b.json','publication-manifest.json','pricing-serving.json']:
        if not (runtime/name).is_file():raise RuntimeError(f'Missing demo runtime file: {name}')
    environment=dict(os.environ)
    environment['RETAIL_POSTGRES_DSN']=DSN
    for key,name in [('GOCACHE','go-cache'),('GOTMPDIR','go-tmp')]:
        path=RUNTIME/name; path.mkdir(parents=True,exist_ok=True); environment[key]=str(path)
    environment['RETAIL_API_TARGET']='http://127.0.0.1:8080'
    # Use the existing host resolver; no application configuration is edited.
    sys.path.insert(0,str(ROOT/'tools'))
    import dev
    profile=dev._host_execution_profile()
    api_args=['go','run','./cmd/server','-address','127.0.0.1:8080',
      '-gate-a-report',str(runtime/'gate-a.json'),'-gate-b-report',str(runtime/'gate-b.json'),
      '-publication-manifest',str(runtime/'publication-manifest.json'),
      '-pricing-serving-config',str(runtime/'pricing-serving.json'),'-forecast-activation-scope',scope,
      '-execution-profiles',str(ROOT/'execution/src/retail_execution/data/v1/profiles.json'),
      '-execution-profile',profile,
      '-openapi-spec',str(ROOT/'contracts/api/openapi.yaml'),
      '-scenario-retailer','retailer-castrol','-scenario-tenant','tenant-castrol','-scenario-environment','local']
    npm=shutil.which('npm.cmd' if os.name=='nt' else 'npm')
    if not npm:raise RuntimeError('npm is not on PATH; install UI dependencies first')
    flags={'creationflags':subprocess.CREATE_NEW_PROCESS_GROUP} if os.name=='nt' else {'start_new_session':True}
    ui=api=None
    try:
        api=subprocess.Popen(api_args,cwd=ROOT/'api',env=environment,**flags)
        print('Waiting for the Castrol API and matching demo metadata...',flush=True)
        wait_for_api(api)
        ui=subprocess.Popen([npm,'run','dev','--','--host','127.0.0.1','--port','5173','--strictPort'],cwd=ROOT/'ui',env=environment,**flags)
        wait_for_ui(ui)
        print('Castrol UI: http://127.0.0.1:5173 | API: http://127.0.0.1:8080 | DB: 127.0.0.1:55432',flush=True)
        while True:
            try:code=api.wait(timeout=1)
            except subprocess.TimeoutExpired:
                if ui.poll() is not None:raise RuntimeError('UI process exited')
            else:
                if code:raise RuntimeError(f'API exited with status {code}')
                break
    except KeyboardInterrupt:
        pass
    finally:
        stop_child(ui);stop_child(api)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['prepare','serve','stop','discard'])
    parser.add_argument('--backup',type=Path,default=DEFAULT_BACKUP)
    parser.add_argument('--confirm-discard',action='store_true',help='Confirm deletion of only the disposable Castrol volume/runtime')
    args=parser.parse_args()
    if args.command=='prepare':prepare(args.backup.resolve())
    elif args.command=='serve':serve()
    elif args.command=='stop':subprocess.run([*COMPOSE,'stop'],check=True)
    else:
        if not args.confirm_discard:parser.error('discard requires --confirm-discard; stop the serving terminal first')
        subprocess.run([*COMPOSE,'down','--volumes'],check=True)
        if RUNTIME.is_dir() and not RUNTIME.is_symlink():shutil.rmtree(RUNTIME)
        print('Only the disposable Castrol container, volume and runtime were removed.')


if __name__=='__main__':main()

"""Install the local app's dependencies and open it in the default browser."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import venv
import webbrowser


def free_port(preferred):
    for port in range(preferred, min(preferred + 20, 65536)):
        try:
            with socket.socket() as connection:
                connection.bind(('127.0.0.1', port))
            return port
        except OSError:
            continue
    raise RuntimeError('No local port is available. Close another copy of the app and try again.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--no-browser', action='store_true', help='Start without opening a browser.')
    parser.add_argument('--port', type=int, default=3000)
    args = parser.parse_args()
    if sys.version_info < (3, 12):
        raise RuntimeError('Install Python 3.12 or newer, then run this launcher again.')
    if not 1024 <= args.port <= 65535:
        raise RuntimeError('Choose a port between 1024 and 65535.')

    root = Path(__file__).resolve().parent
    environment = root / '.venv'
    python = environment / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    if not python.exists():
        print('Preparing the app for this computer…', flush=True)
        venv.EnvBuilder(with_pip=True).create(environment)

    requirements = root / 'requirements.txt'
    fingerprint = hashlib.sha256(requirements.read_bytes()).hexdigest()
    installed = environment / '.waitlist-requirements'
    if not installed.exists() or installed.read_text().strip() != fingerprint:
        print('Installing dependencies. Internet access is needed the first time…', flush=True)
        subprocess.run([str(python), '-m', 'pip', 'install', '--disable-pip-version-check',
                        '-r', str(requirements)], cwd=root, check=True)
        installed.write_text(fingerprint)

    port = free_port(args.port)
    variables = os.environ.copy()
    variables['PORT'] = str(port)
    variables['APP_HOST'] = '127.0.0.1'
    process = subprocess.Popen([str(python), str(root / 'app.py')], cwd=root, env=variables)
    address = f'http://127.0.0.1:{port}'
    # Local readiness requests must not be routed through a corporate HTTP proxy.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        for _ in range(120):
            if process.poll() is not None:
                raise RuntimeError('The app could not start. Check the message above.')
            try:
                protected = bool(variables.get('STAFF_PASSWORD'))
                with opener.open(address + ('/login' if protected else '/health'), timeout=1) as response:
                    ready = b'Staff sign in' in response.read() if protected else json.load(response).get('status') == 'ok'
                    if ready:
                        break
            except (urllib.error.URLError, TimeoutError, ValueError):
                pass
            time.sleep(0.25)
        else:
            raise RuntimeError('The app took too long to start. Check the message above.')
        print('Southern Alps Air is ready. Leave this window open while using the app.', flush=True)
        print('Press Ctrl+C in this window when you are finished.', flush=True)
        if not args.no_browser:
            webbrowser.open(address)
        process.wait()
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print('\nApp closed. Your saved waitlists are kept.')
    except (RuntimeError, OSError, subprocess.CalledProcessError) as error:
        print(f'Could not open the app: {error}', file=sys.stderr)
        sys.exit(1)

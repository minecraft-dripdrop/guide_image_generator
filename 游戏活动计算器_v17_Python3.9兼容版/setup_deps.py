# -*- coding: utf-8 -*-
"""Windows game-event solver dependency bootstrapper. Python stdlib only."""
import os
import subprocess
import sys
from pathlib import Path

HOME = Path(__file__).resolve().parent
LOG = HOME / 'pip_install.log'


def ready():
    try:
        import numpy
        import scipy
        from scipy.optimize import milp
        print('Verified: NumPy %s, SciPy %s, MILP available' % (numpy.__version__, scipy.__version__), flush=True)
        return True
    except Exception as ex:
        print('Current environment is missing a working MILP solver: %s' % ex, flush=True)
        return False


def run_pip(args, label):
    cmd = [sys.executable, '-m', 'pip'] + args
    print('\n' + ('=' * 56), flush=True)
    print(label, flush=True)
    print('Live installation output follows; this may download about 65 MB.', flush=True)
    print('=' * 56, flush=True)
    with LOG.open('a', encoding='utf-8', errors='replace') as log:
        log.write('\n### %s ###\n' % label)
        try:
            # Unlike v17, output is shown live; errors also saved to the log.
            proc = subprocess.Popen(cmd, cwd=str(HOME), stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, universal_newlines=True,
                                    bufsize=1, errors='replace')
            for line in proc.stdout:
                print(line, end='', flush=True)
                log.write(line)
                log.flush()
            code = proc.wait()
        except KeyboardInterrupt:
            print('\nInterrupted by user. Safe to rerun.', flush=True)
            try:
                proc.terminate()
            except Exception:
                pass
            return 130
        except Exception as ex:
            print('Install process could not start:', ex, flush=True)
            log.write(str(ex) + '\n')
            return 1
        log.write('Exit code: %s\n' % code)
    return code


def main():
    print('Python executable:', sys.executable, flush=True)
    print('Python version:', sys.version.split()[0], flush=True)
    if sys.version_info < (3, 9):
        print('ERROR: Python 3.9 or later is required.', flush=True)
        return 2
    if ready():
        return 0
    if subprocess.call([sys.executable, '-m', 'pip', '--version'],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) != 0:
        print('pip missing; attempting ensurepip from local Python installation...', flush=True)
        if subprocess.call([sys.executable, '-m', 'ensurepip', '--upgrade']) != 0:
            print('ERROR: Failed to initialize pip.', flush=True)
            return 3

    if (HOME / 'wheels').is_dir():
        offline = ['install', '--disable-pip-version-check', '--only-binary=:all:',
                   '--no-index', '--find-links', str(HOME / 'wheels')]
        if sys.version_info < (3, 13):
            offline += ['numpy==1.26.4', 'scipy==1.13.1']
        else:
            offline += ['numpy>=2.1', 'scipy>=1.14']
        code = run_pip(offline, 'Attempt 0: local offline wheels (if available)')
        if code == 0 and ready():
            return 0
        print('Offline wheels not complete; trying download sources.', flush=True)

    if sys.version_info < (3, 13):
        pins = ['numpy==1.26.4', 'scipy==1.13.1']
    else:
        pins = ['numpy>=2.1', 'scipy>=1.14']
    mirrors = [
        ('Tsinghua mirror', 'https://pypi.tuna.tsinghua.edu.cn/simple'),
        ('Official PyPI', 'https://pypi.org/simple'),
        ('Aliyun mirror', 'https://mirrors.aliyun.com/pypi/simple/'),
    ]
    # Avoid a stalled network blocking the whole launcher indefinitely.
    common = ['install', '--disable-pip-version-check', '--no-input',
              '--only-binary=:all:', '--no-cache-dir', '--timeout', '12',
              '--retries', '0']
    for idx, (name, mirror) in enumerate(mirrors, 1):
        code = run_pip(common + ['--index-url', mirror] + pins,
                       'Attempt %d of %d: %s' % (idx, len(mirrors), name))
        if code == 130:
            return 130
        if code == 0 and ready():
            return 0
        print('This source failed; trying the next source.', flush=True)

    print('\nERROR: All sources failed or installed packages could not be imported.', flush=True)
    print('Check pip_install.log for details.', flush=True)
    print('If all network sources are blocked, place compatible .whl files', flush=True)
    print('in a wheels folder and run this launcher again.', flush=True)
    return 4


if __name__ == '__main__':
    sys.exit(main())

#!/usr/bin/env python3
"""Assemble a Pi launch context for one chessleak worker or evaluator.

The framework's launcher (../alleyoop/tools/launch.py) knows the Claude Code and
Codex clients. This release runs on OpenRouter's stealth/space-bunny-alpha through
the Pi harness (operator, 2026-10-01), so this repository carries a small launcher
that assembles the same launch context and starts the agent through Herdr's `pi`
kind. The framework package is not modified.

Preview without --pane prints the plan and starts nothing.

    python3 tools/pi_worker.py worker --roster .git/alleyoop/roster.json \
        --bead chess-bb8 --worktree /path/to/worktree [--pane PANE_ID]
    python3 tools/pi_worker.py evaluator --roster .git/alleyoop/roster.json \
        --repo /path/to/verification-worktree --candidate FULL_SHA [--pane PANE_ID]
"""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid

# Identity, hashing and worktree rules come from the framework package itself, so a
# name derived here is the same name the framework would derive.
ALLEYOOP = Path(os.environ.get('ALLEYOOP_HOME', '/home/ddc/dev-env/alleyoop')).resolve()
BUNDLE = ALLEYOOP / 'tools/launch.py'
spec = importlib.util.spec_from_file_location('alleyoop_launch', BUNDLE)
launch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launch)

STARTUP_TIMEOUT_MS = 300000  # Herdr's maximum readiness wait, as in the framework.
THINKING_LEVELS = ('off', 'minimal', 'low', 'medium', 'high', 'xhigh', 'max')
PI_KIND = 'pi'


def git(repo, *args):
    return launch.git(repo, *args)


def store(repo):
    """The repository's shared tracker store, found through its main worktree."""
    main = Path(git(repo, 'worktree', 'list', '--porcelain', '-z').split('\0')[0][9:])
    beads = main / '.beads'
    if not beads.is_dir():
        raise ValueError(f'Initialize the shared tracker store first: {beads}')
    return beads.resolve()


def text_field(data, key):
    return launch.text_field(data, key)


def thinking(effort):
    if effort not in THINKING_LEVELS:
        raise ValueError(f'effort must be one of {", ".join(THINKING_LEVELS)} for the Pi client')
    return effort


def roster(path):
    path = Path(path).resolve()
    data = json.loads(path.read_text())
    if not isinstance(data, dict):
        raise ValueError('Roster must be a configuration object')

    def resolve(value):
        return (path.parent / text_field(data, value)).resolve()

    repository = resolve('repository')
    root, common = launch.checkout(repository)
    workers = data.get('workers')
    if not isinstance(workers, dict):
        raise ValueError('A chief-team roster needs a workers object')
    kind = text_field(workers, 'kind')
    if kind != PI_KIND:
        raise ValueError(f'This launcher runs Pi workers; the roster asks for {kind}')
    unrestricted = workers.get('unrestricted', True)
    if not isinstance(unrestricted, bool):
        raise ValueError('unrestricted must be true or false')
    chief = data.get('chief')
    if not isinstance(chief, dict):
        raise ValueError('A chief-team roster needs a chief object')
    chief_root, chief_common = launch.checkout(
        (path.parent / text_field(chief, 'worktree')).resolve())
    if common != chief_common:
        raise ValueError("The chief's checkout must belong to the roster repository")
    return {'path': path, 'data': data, 'resolve': resolve, 'common': common, 'root': root,
            'chief_root': chief_root, 'chief_name': launch.node_name(common) + '-chief',
            'release_bead': text_field(data, 'release_bead'),
            'prd': resolve('prd'), 'release': resolve('release'),
            'design': resolve('design') if 'design' in data else None,
            'workers': {'kind': kind, 'provider': text_field(workers, 'provider'),
                        'model': text_field(workers, 'model'),
                        'effort': thinking(text_field(workers, 'effort')),
                        'unrestricted': unrestricted}}


def instruction_file(repo, identity, role, instructions):
    """Write the assembled instructions under the repository's private git directory.

    Pi takes the system-prompt addition as a path, so a large launch context never
    becomes a shell argument with embedded newlines, and no tracked or shared-temp
    file ever carries a worker's standing instructions.
    """
    common = Path(git(repo, 'rev-parse', '--path-format=absolute', '--git-common-dir'))
    directory = common / 'alleyoop' / 'launch'
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f'{identity}.md'
    path.write_text(instructions)
    return path


def assemble(role, identity, worktree, config, context_extra):
    root, _ = launch.checkout(Path(worktree).resolve())
    name = launch.node_name(context_extra['common']) + '-' + identity
    environment = {'BD_ACTOR': identity, 'JOT_AGENT': context_extra['memory'],
                   'BEADS_DIR': str(context_extra['beads']), 'ALLEY_NAME': name,
                   'ALLEY_RELEASE_BEAD': context_extra['release_bead'],
                   'CHESSLEAK_CACHE_DIR': str(root / '.cache'),
                   'CHESSLEAK_STOCKFISH_PATH': context_extra['stockfish_hint'],
                   **(context_extra.get('environment') or {})}
    context = {'identity': identity, 'name': name, 'repository': str(root),
               'release_bead': context_extra['release_bead'], 'environment': environment,
               'requested_configuration': {'kind': config['kind'], 'provider': config['provider'],
                                           'model': config['model'], 'effort': config['effort'],
                                           'unrestricted': config['unrestricted']},
               'product_sources': {'prd': launch.source(context_extra['prd']),
                                   'release': launch.source(context_extra['release'])},
               'state_template': launch.source(ALLEYOOP / 'templates/state.md'),
               'operating_guide': launch.source(ALLEYOOP / 'docs/guide.md'),
               'tracker': 'br (Beads Rust): use br, never bd; every command runs against BEADS_DIR',
               **context_extra['extra']}
    if context_extra.get('design'):
        context['design_record'] = launch.source(context_extra['design'])
    instructions = (ALLEYOOP / 'prompts' / f'{role}.md').read_text()
    instructions += '\n\n## Launch context\n\n' + json.dumps(context, indent=2, ensure_ascii=False)
    if role == 'evaluator':
        instructions += '\n\n' + (ALLEYOOP / 'templates/evaluation.md').read_text()
        boot = ('Read your Alleyoop evaluator instructions and launch context. Your identity is '
                f'{identity}; your release bead is {context_extra["release_bead"]}. '
                + launch.BOOT['evaluator'])
    else:
        unit = context_extra['extra']['unit']
        assignment = (f'Your bead is {unit[0]}; ' if len(unit) == 1 else
                      f'Your unit is {", ".join(unit)}, with {unit[0]} as its primary bead; ')
        boot = (f'Read your Alleyoop {role} instructions and launch context. Your identity is '
                f'{identity}; your release bead is {context_extra["release_bead"]}. {assignment}'
                f'your chief is {context_extra["extra"]["chief"]}. ' + launch.BOOT[role])
    prompt = instruction_file(root, identity, role, instructions)
    # Pi has no per-launch settings overlay, and Herdr runs the agent binary itself,
    # so the launch identity is set on the pane at creation time (see open_pane).
    # It travels in the context too, so a worker can always see what it should be.
    args = ['--provider', config['provider'], '--model', config['model'],
            '--thinking', config['effort'], '--append-system-prompt', str(prompt)]
    if config['unrestricted']:
        # Pi's supported per-launch opt-in for project-local files; it does not
        # disable a host-enforced policy and grants no authority.
        args += ['--approve']
    args += ['--name', identity]
    return {'name': name, 'kind': PI_KIND, 'cwd': str(root), 'environment': environment,
            'args': args, 'boot': boot, 'context': context,
            'instructions_path': str(prompt),
            'instructions_sha256': launch.source(prompt)['sha256']}


def stockfish_hint():
    """Where scripts/get_stockfish.sh is told to leave the shared read-only binary."""
    return str(Path.home() / '.local/share/chessleak/stockfish/stockfish')


def worker_plan(args):
    team = roster(args.roster)
    unit = launch.worker_unit(args.bead)
    identity = launch.worker_identity(team['common'], unit[0])
    root, common = launch.checkout(Path(args.worktree).resolve())
    if common != team['common']:
        raise ValueError('A worker checkout must belong to the same repository as the chief')
    if root == team['chief_root']:
        raise ValueError("A worker needs its own worktree, not the chief's checkout")
    defaults = team['workers']
    if args.provider and not args.model:
        # A different provider's model does not follow from the roster default.
        raise ValueError('--provider overrides the roster worker default; pass --model with it')
    config = {'kind': PI_KIND, 'provider': args.provider or defaults['provider'],
              'model': args.model or defaults['model'],
              'effort': thinking(args.effort or defaults['effort']),
              'unrestricted': defaults['unrestricted'] if args.unrestricted is None else args.unrestricted}
    return assemble('worker', identity, root, config,
                    {'common': common, 'beads': store(root), 'release_bead': team['release_bead'],
                     'prd': team['prd'], 'release': team['release'], 'design': team['design'],
                     'memory': 'worker', 'stockfish_hint': stockfish_hint(),
                     'extra': {'bead': unit[0], 'unit': unit, 'chief': team['chief_name'],
                               'branch': git(root, 'branch', '--show-current'),
                               'roster_path': str(team['path']),
                               'integration': ('This repository has no Git remote: commit on your '
                                              'branch, report the head commit, and never merge.')},
                     'environment': {'ALLEY_BEAD': unit[0], 'ALLEY_UNIT': ','.join(unit),
                                     'ALLEY_CHIEF': team['chief_name']}})


def evaluator_plan(args):
    team = roster(args.roster)
    repo = Path(args.repo).resolve()
    candidate = args.candidate.lower()
    if len(candidate) != 40 or git(repo, 'cat-file', '-t', candidate) != 'commit':
        raise ValueError('candidate must be a full Git commit ID present in this repository')
    if git(repo, 'rev-parse', 'HEAD') != candidate:
        raise ValueError('Verification checkout HEAD must be the exact candidate commit')
    if git(repo, 'status', '--porcelain', '--untracked-files=no'):
        raise ValueError('Verification checkout must have clean tracked files')
    defaults = team['workers']
    config = {'kind': PI_KIND, 'provider': args.provider or defaults['provider'],
              'model': args.model or defaults['model'],
              'effort': thinking(args.effort or defaults['effort']),
              'unrestricted': defaults['unrestricted'] if args.unrestricted is None else args.unrestricted}
    identity = 'eval-' + uuid.uuid4().hex[:12]
    return assemble('evaluator', identity, repo, config,
                    {'common': team['common'], 'beads': store(repo),
                     'release_bead': team['release_bead'], 'prd': team['prd'],
                     'release': team['release'], 'design': team['design'],
                     'memory': 'evaluator-setup', 'stockfish_hint': stockfish_hint(),
                     'extra': {'candidate': candidate, 'roster_path': str(team['path'])}})


def open_pane(plan, workspace, label):
    """Create the worker's pane with its launch environment, and return the pane id.

    Herdr runs the agent binary itself, so the identity environment has to exist in
    the pane's shell before the agent starts. BD_ACTOR attributes tracker writes and
    BEADS_DIR is what keeps every worker on the one shared store; without the latter a
    worker silently creates a second, empty store in its own worktree.
    """
    command = ['herdr', 'tab', 'create', '--workspace', workspace, '--cwd', plan['cwd'],
               '--label', label, '--no-focus']
    for key, value in plan['environment'].items():
        command += ['--env', f'{key}={value}']
    created = subprocess.run(command, capture_output=True, text=True, check=True)
    pane = json.loads(created.stdout)['result']['root_pane']['pane_id']
    return pane


def start(plan, pane):
    if os.environ.get('HERDR_ENV') != '1':
        raise ValueError('Starting requires a Herdr-managed caller; preview works without Herdr')
    current = json.loads(subprocess.check_output(['herdr', 'pane', 'get', pane], text=True))
    if Path(current['result']['pane']['cwd']).resolve() != Path(plan['cwd']).resolve():
        raise ValueError('Target pane must already be in the selected checkout')
    result = subprocess.run(['herdr', 'agent', 'start', plan['name'], '--kind', plan['kind'],
                             '--pane', pane, '--timeout', str(STARTUP_TIMEOUT_MS),
                             '--', *plan['args'], plan['boot']],
                            capture_output=True, text=True)
    if result.stdout:
        print(result.stdout.rstrip('\n'))
    if result.returncode == 0:
        return
    if launch.herdr_error(result).get('code') != 'timeout':
        raise subprocess.CalledProcessError(result.returncode, result.args, result.stdout, result.stderr)
    if result.stderr:
        print(result.stderr.rstrip('\n'), file=sys.stderr)
    # Reuse the framework's post-timeout name recovery; it never restarts the client.
    launch.restore_name(plan, pane)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='role', required=True)
    for role in ('worker', 'evaluator'):
        child = sub.add_parser(role, help=f'Preview one Pi {role}, or start it with --pane')
        child.add_argument('--roster', required=True, type=Path)
        if role == 'worker':
            child.add_argument('--bead', required=True, action='append')
            child.add_argument('--worktree', required=True, type=Path)
        else:
            child.add_argument('--repo', required=True, type=Path)
            child.add_argument('--candidate', required=True)
        child.add_argument('--provider', help='Override the roster provider')
        child.add_argument('--model', help='Override the roster model')
        child.add_argument('--effort', help=f'Override the roster effort ({"|".join(THINKING_LEVELS)})')
        permissions = child.add_mutually_exclusive_group()
        permissions.add_argument('--unrestricted', dest='unrestricted', action='store_true',
                                 help='Add Pi per-launch project-file approval (roster default)')
        permissions.add_argument('--restricted', dest='unrestricted', action='store_false',
                                 help='Omit it and use Pi defaults')
        child.set_defaults(unrestricted=None)
        child.add_argument('--pane')
        child.add_argument('--open-pane', metavar='WORKSPACE',
                           help='Create the pane here with the launch environment, then start')
    args = parser.parse_args()
    plan = worker_plan(args) if args.role == 'worker' else evaluator_plan(args)
    if args.open_pane:
        pane = open_pane(plan, args.open_pane, plan['context']['identity'])
        # A pane whose shell has not started yet fails with agent_pane_busy.
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            current = subprocess.run(['herdr', 'pane', 'get', pane], capture_output=True, text=True)
            if current.returncode == 0 and json.loads(current.stdout)['result']['pane']['cwd'] \
                    and Path(json.loads(current.stdout)['result']['pane']['cwd']).resolve() \
                    == Path(plan['cwd']).resolve() and json.loads(current.stdout)['result']['pane'].get('agent_status') == 'unknown':
                break
            time.sleep(1)
        print(json.dumps({'pane': pane, 'cwd': plan['cwd'], 'name': plan['name']}))
    elif args.pane:
        start(plan, args.pane)
    else:
        print(json.dumps(plan, indent=2, ensure_ascii=False))


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as error:
        if isinstance(error, subprocess.CalledProcessError):
            print(f'pi_worker: {error.cmd[0]} failed with exit {error.returncode}', file=sys.stderr)
            if error.stderr:
                print(error.stderr, file=sys.stderr)
        else:
            print(f'pi_worker: {error}', file=sys.stderr)
        sys.exit(2)
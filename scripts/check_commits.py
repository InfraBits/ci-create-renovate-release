'''Check all commits since the latest release were made by trusted bots.

Commits are first filtered by author name using the local history (so there is no limit on the number of commits),
then each candidate is checked against the GitHub API. The author name/email are trivially spoofable & GitHub links
a commit to an account purely by email, so a commit is only trusted when it is also verified and was committed by
GitHub itself (web-flow, i.e. created via the API/UI) or by the bot account.

GitHub drops the signature when rebase merging a pull request, so an unsigned commit is also trusted when it has the
same author & message as a trusted commit on a merged pull request opened by the bot, and replaying that commit onto
its parent results in the same tree.
'''
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request

from common import set_output

# Author login -> GitHub account id
TRUSTED_BOTS = {
    'renovate[bot]': 29139614,
    'github-actions[bot]': 41898282,
}

# GitHub's own committer, used for commits created via the API or UI
WEB_FLOW_ID = 19864447


def local_commits(latest_tag):
    output = subprocess.run(['git', 'log', '--format=%H%x00%an%x00%s', f'{latest_tag}..HEAD'],
                            check=True, capture_output=True).stdout.decode()
    return [line.split('\0') for line in output.splitlines()]


def api(path):
    request = urllib.request.Request(
        f'{os.environ["GITHUB_API_URL"]}/repos/{os.environ["GITHUB_REPOSITORY"]}/{path}',
        headers={
            'Accept': 'application/vnd.github+json',
            'Authorization': f'Bearer {os.environ["GITHUB_TOKEN"]}',
            'X-GitHub-Api-Version': '2022-11-28',
        },
    )
    with urllib.request.urlopen(request) as response:
        return json.load(response)


def is_rebase_of(sha, original):
    '''Return if replaying original onto the parent of sha (as a rebase does) results in exactly the tree of sha.'''
    subprocess.run(['git', 'fetch', '--quiet', '--no-tags', 'origin', original], check=True, capture_output=True)
    replayed = subprocess.run(['git', 'merge-tree', '--write-tree', f'--merge-base={original}^', f'{sha}^', original],
                              capture_output=True)
    tree = subprocess.run(['git', 'rev-parse', f'{sha}^{{tree}}'], check=True, capture_output=True)
    return replayed.returncode == 0 and replayed.stdout.split()[0] == tree.stdout.strip()


def rebased_untrusted_reason(name, commit):
    '''Return why the commit cannot be trusted as a rebase of a trusted pull request commit, or None if it can.'''
    try:
        pulls = api(f'commits/{commit["sha"]}/pulls')
    except urllib.error.HTTPError as e:
        return f'could not look up pull requests ({e.code}), is the pull-requests: read permission granted?'

    for pull in pulls:
        if not pull['merged_at'] or pull['user']['login'] != name or pull['user']['id'] != TRUSTED_BOTS[name]:
            continue
        for original in api(f'pulls/{pull["number"]}/commits'):
            if (original['commit']['author'] == commit['commit']['author'] and
                    original['commit']['message'] == commit['commit']['message'] and
                    untrusted_reason(name, original, allow_rebased=False) is None and
                    is_rebase_of(commit['sha'], original['sha'])):
                return None
    return 'not a rebase of a trusted pull request commit'


def untrusted_reason(name, commit, allow_rebased=True):
    '''Return why the commit cannot be trusted as being from the bot, or None if it can.'''
    author = commit.get('author') or {}
    committer = commit.get('committer') or {}
    verification = commit['commit'].get('verification') or {}

    if author.get('login') != name or author.get('id') != TRUSTED_BOTS[name]:
        return f'author account is {author.get("login")} ({author.get("id")})'
    if not verification.get('verified'):
        reason = f'signature is not verified ({verification.get("reason")})'
        if allow_rebased and verification.get('reason') == 'unsigned':
            rebased_reason = rebased_untrusted_reason(name, commit)
            return f'{reason}, {rebased_reason}' if rebased_reason else None
        return reason
    if committer.get('id') not in (WEB_FLOW_ID, TRUSTED_BOTS[name]):
        return f'committed by {committer.get("login")} ({committer.get("id")})'
    # e.g. someone else pushed to the bot's branch before it was squash merged
    if 'co-authored-by:' in commit['commit']['message'].lower():
        return 'has co-authors'
    return None


def main(latest_tag):
    commits = local_commits(latest_tag)
    other = [(sha, name, subject) for sha, name, subject in commits if name not in TRUSTED_BOTS]
    candidates = [(sha, name, subject) for sha, name, subject in commits if name in TRUSTED_BOTS]

    print(f'[{latest_tag}] Found {len(candidates)} bot & {len(other)} other commits')
    for sha, name, subject in other:
        print(f'  - {sha[:12]} {name}: {subject}')
    if not candidates or other:
        return

    untrusted = 0
    for sha, name, subject in candidates:
        reason = untrusted_reason(name, api(f'commits/{sha}'))
        if reason:
            untrusted += 1
            print(f'  - {sha[:12]} {name}: {subject} - untrusted, {reason}')

    print(f'[{latest_tag}] Verified {len(candidates) - untrusted}/{len(candidates)} bot commits')
    if untrusted == 0:
        set_output('have_only_bot_commits', 'true')


if __name__ == '__main__':
    main(sys.argv[1])

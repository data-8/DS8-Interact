import os

from flask import redirect
import git

from . import util

DSTEN_ORG = 'https://github.com/dsten/'
GH_PAGES_BRANCH = 'gh-pages'


def pull_from_github(**kwargs):
    """
    Initializes git repo if needed, then pulls new content from Github using
    sparse checkout.

    This pull preserves the original content in case of a merge conflict by
    making a WIP commit then pulling with -Xours.

    Reference:
    http://jasonkarns.com/blog/subdirectory-checkouts-with-git-sparse-checkout/

    Kwargs:
        username (str): The username of the JupyterHub user
        repo_name (str): The repo under the dsten org to pull from, eg.
            textbook or health-connector.
        paths (list of str): The folders and file names to pull.
        config (Config): The config for this environment.
    """
    username = kwargs['username']
    repo_name = kwargs['repo_name']
    paths = kwargs['paths']
    config = kwargs['config']

    assert username and repo_name and paths and config

    util.logger.info('Starting pull.')
    util.logger.info('    User: {}'.format(username))
    util.logger.info('    Repo: {}'.format(repo_name))
    util.logger.info('    Paths: {}'.format(paths))

    repo_dir = util.construct_path(config['COPY_PATH'], locals(), repo_name)

    try:
        if not os.path.exists(repo_dir):
            _initialize_repo(repo_name, repo_dir)

        _add_sparse_checkout_paths(repo_dir, paths)

        repo = git.Repo(repo_dir)
        _make_commit_if_dirty(repo)

        _pull_and_resolve_conflicts(repo)

        # Set ownership to username
        parent_dir = util.construct_path(config['COPY_PATH'], locals())
        util.chown(username, parent_dir, repo_name)
        util.logger.info('chown\'d {} to {}'.format(repo_name, username))

        redirect_url = util.construct_path(config['REDIRECT_PATH'], {
            'username': username,
            'destination': 'tree/' + repo_name,
        })
        util.logger.info('Redirecting to {}'.format(redirect_url))
        return redirect(redirect_url)
    except git.exc.GitCommandError as git_err:
        util.logger.error(git_err)
        return git_err.stderr



def _initialize_repo(repo_name, repo_dir):
    """
    Initializes repository and configures it to use sparse checkout.
    """
    util.logger.info('Repo {} doesn\'t exist. Creating...'.format(repo_name))
    # Create repo dir
    os.mkdir(repo_dir)
    repo = git.Repo.init(repo_dir)

    # Add remote
    remote_name = DSTEN_ORG + repo_name
    origin = repo.create_remote('origin', remote_name)
    assert origin.exists()

    # Use sparse checkout
    config = repo.config_writer()
    config.set_value('core', 'sparsecheckout', True)
    config.release()

    util.logger.info('Repo {} initialized'.format(repo_name))


def _add_sparse_checkout_paths(repo_dir, paths):
    """
    Runs the equivalent of

    echo /path >> .git/info/sparse-checkout

    for each path in paths but also avoids duplicates.
    """
    sparsecheckout_path = os.path.join(repo_dir,
                                       '.git', 'info', 'sparse-checkout')

    existing_paths = []
    try:
        with open(sparsecheckout_path) as info_file:
            existing_paths = [line.strip().strip('/')
                              for line in info_file.readlines()]
    except FileNotFoundError:
        pass

    util.logger.info(
        'Existing paths in sparse-checkout: {}'.format(existing_paths))

    to_write = [path for path in paths if path not in existing_paths]
    with open(sparsecheckout_path, 'a') as info_file:
        for path in to_write:
            info_file.write('/{}\n'.format(path))

    util.logger.info('{} written to sparse-checkout'.format(to_write))


def _make_commit_if_dirty(repo):
    """
    Makes a commit with message 'WIP' if there are changes.
    """
    if repo.is_dirty():
        git_cli = repo.git
        git_cli.add('-A')
        git_cli.commit('-m', 'WIP')

        util.logger.info('Made WIP commit')


def _pull_and_resolve_conflicts(repo):
    """
    Git pulls, resolving conflicts with -Xours
    """
    util.logger.info('Starting pull from {}'.format(repo.remotes['origin']))

    git_cli = repo.git
    if repo.heads:
        git_cli.read_tree('-mu', 'HEAD')
    else:
        git_cli.pull('origin', GH_PAGES_BRANCH)

    util.logger.info('Pulled from {}'.format(repo.remotes['origin']))
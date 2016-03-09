#
# Copyright 2012 NAMD-EMAP-FGV
#
# This file is part of PyPLN. You can get more information at: http://pypln.org/.
#
# PyPLN is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# PyPLN is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with PyPLN.  If not, see <http://www.gnu.org/licenses/>.

import datetime
import os
import random
import string

from fabric.api import cd, run, sudo, settings, prefix, abort, prompt, env
from fabric.contrib.files import comment, append, sed, contains
from fabric.contrib.console import confirm


USER = "pypln"
HOME = "/srv/pypln/"
LOG_DIR = os.path.join(HOME, "logs/")
BACKUP_DIR = os.path.join(HOME, "backups/")
PROJECT_ROOT = os.path.join(HOME, "project/")
PYPLN_BACKEND_ROOT = os.path.join(PROJECT_ROOT, "backend")
PYPLN_WEB_ROOT = os.path.join(PROJECT_ROOT, "web/")
PYPLN_DEPLOY_ROOT = os.path.join(PROJECT_ROOT, "deploy/")
DJANGO_PROJECT_ROOT = os.path.join(PYPLN_WEB_ROOT, "pypln/web/")
BACKEND_REPO_URL = "https://github.com/NAMD/pypln.backend.git"
WEB_REPO_URL = "https://github.com/NAMD/pypln.web.git"
DEPLOY_REPO_URL = "https://github.com/NAMD/pypln-deploy.git"
ACTIVATE_SCRIPT = os.path.join(PROJECT_ROOT, "bin/activate")
CONFIG_FILE = os.path.join(HOME, 'settings.ini')


def _stop_supervisord():
    # XXX: Why does supervisor's init script exit with 1 on "restart"?
    sudo("service supervisor stop")

def _start_supervisord():
    sudo("service supervisor start")

def _restart_supervisord():
    _stop_supervisord()
    _start_supervisord()

def _restart_nginx():
    sudo("service nginx restart")

def restart_services():
    '''Restart supervisord and nginx

    This task is needed because of a bug that's happenning sometimes (we don't
    know how to solve it entirely yet)

    Note that it must be run as a user that has sudo access.
    '''
    _stop_supervisord()
    _restart_nginx()
    _start_supervisord()

def _update_repository(branch):
    # TODO: We need a better way to do this. But this has to be a branch name,
    # since we'll use it for all repositories.
    run("git remote update")
    sha1 = run("git rev-parse origin/{}".format(branch))
    run("git checkout {}".format(branch))
    run("git reset --hard {}".format(sha1))

def _update_version_sha1(branch):
    sha1 = run("git rev-parse origin/{}".format(branch))
    template_path = os.path.join(PYPLN_WEB_ROOT, "pypln/web/templates/rest_framework/api.html")
    append(template_path, "{{% block footer %}}<!-- current version: {} --> {{% "
            "endblock %}}".format(sha1))

def _update_deploy_code(branch):
    with cd(PYPLN_DEPLOY_ROOT):
        _update_repository(branch)

def _update_backend_code(branch):
    # We should alway update the deploy code because new configurations should
    # be applied even when deploying only the backend
    _update_deploy_code(branch)
    with cd(PYPLN_BACKEND_ROOT):
        _update_repository(branch)

def _update_web_code(branch):
    # We also have configurations for the web app in the deploy repository, so
    # we also need to update it here
    _update_deploy_code(branch)
    with cd(PYPLN_WEB_ROOT):
        _update_repository(branch)
        _update_version_sha1(branch)

def _update_code(branch="master"):
    _update_backend_code(branch)
    _update_web_code(branch)

def set_config_option(option, new_value):
    with settings(user=USER):
        if contains(CONFIG_FILE, option):
            # This regex should only match lines that contain the desired
            # option: from the begining of the line to the first '=' there
            # should only be spaces and the option string.
            run("sed -i '/^[[:space:]]*{}[[:space:]]*=/Id' {}".format(option, CONFIG_FILE))
        append(CONFIG_FILE, '{} = {}'.format(option, new_value))

def _create_secret_key():
    valid_chars = 'abcdefghijklmnopqrstuvwxyz0123456789!@#$^&*(-_=+)'
    secret_key = ''.join([random.choice(valid_chars) for i in range(50)])
    set_config_option('SECRET_KEY', secret_key)

def _create_smtp_config():
    smtp_config_file_path = os.path.join(HOME, ".smtp_config")
    smtp_host = prompt("smtp host:", default="smtp.gmail.com")
    smtp_port = prompt("smtp port:", default=587)
    smtp_user = prompt("smtp user:")
    smtp_password = prompt("smtp password:")
    smtp_config = "{},{},{},{}".format(smtp_host, smtp_port, smtp_user,
            smtp_password)
    set_config_option('EMAIL_CONFIG', smtp_config)

def _create_deploy_user():
    with settings(warn_only=True):
        user_does_not_exist = run("id {}".format(USER)).failed

    if user_does_not_exist:
        sudo("useradd --shell=/bin/bash --home {} --create-home {}".format(
            HOME, USER))
        sudo("mkdir {}".format(LOG_DIR))
        sudo("chown -R {0}:{0} {1}".format(USER, LOG_DIR))
        sudo("mkdir {}".format(BACKUP_DIR))
        sudo("chown -R {0}:{0} {1}".format(USER, BACKUP_DIR))
        sudo("mkdir {}".format(PROJECT_ROOT))
        sudo("chown -R {0}:{0} {1}".format(USER, PROJECT_ROOT))
        sudo("passwd {}".format(USER))
        sudo("echo '[settings]' > {}".format(CONFIG_FILE))
        sudo("chown {0}:{0} {1}".format(USER, CONFIG_FILE))
        _create_secret_key()
        _create_smtp_config()
        # Set the admin
        set_config_option("ADMIN", "pypln,pyplnproject@gmail.com")

def _configure_supervisord(daemons):
    for daemon in daemons:
        config_file_path = os.path.join(PYPLN_DEPLOY_ROOT,
                "server_config/{}.conf".format(daemon))
        sudo("ln -sf {} /etc/supervisor/conf.d/".format(config_file_path))

    # Commenting out the path to the socket that supervisorctl uses should make
    # it fallback to it's default of connecting on localhost:9001.  This should
    # allow non-root users to control the running processes.
    supervisor_conf = "/etc/supervisor/supervisord.conf"
    comment(supervisor_conf,
                "^serverurl=unix:///var/run/supervisor.sock .*",
                use_sudo=True, char=";")
    append(supervisor_conf, ["[inet_http_server]", "port=127.0.0.1:9001"],
                use_sudo=True)
    _restart_supervisord()

def _configure_nginx():
    nginx_vhost_path = os.path.join(PYPLN_DEPLOY_ROOT, "server_config/nginx.conf")
    sed(nginx_vhost_path, "%%HOST%%", env.host, backup='', use_sudo=True)
    sudo("ln -sf {} /etc/nginx/sites-enabled/pypln".format(nginx_vhost_path))
    sudo("service nginx restart")

def _clone_backend_repos(branch):
    run("git clone {} {}".format(BACKEND_REPO_URL, PYPLN_BACKEND_ROOT))
    run("git clone {} {}".format(DEPLOY_REPO_URL, PYPLN_DEPLOY_ROOT))
    _update_backend_code(branch)

def _clone_web_repos(branch):
    run("git clone {} {}".format(WEB_REPO_URL, PYPLN_WEB_ROOT))
    run("git clone {} {}".format(BACKEND_REPO_URL, PYPLN_BACKEND_ROOT))
    _update_web_code(branch)

def _update_crontab():
    crontab_file = os.path.join(PYPLN_DEPLOY_ROOT, "server_config/crontab")
    run('crontab %s' % crontab_file)

def create_db(db_user, db_name, db_host="localhost", db_port=5432):
    # we choose a random password with letters, numbers and some punctuation.
    db_password = ''.join(random.choice(string.ascii_letters + string.digits +\
            '#.,+=') for i in range(32))

    pgpass_path = os.path.join(HOME, ".pgpass")
    set_config_option('DATABASE_URL', "postgres://{}:{}@{}:{}/{}".format(db_user,
        db_password, db_host, db_port, db_name))

    with settings(warn_only=True):
        user_creation = sudo('psql template1 -c "CREATE USER {} WITH CREATEDB ENCRYPTED PASSWORD \'{}\'"'.format(db_user, db_password), user='postgres')

    if not user_creation.failed:
        sudo('createdb "{}" -O "{}"'.format(db_name, db_user), user='postgres')

def db_backup():
    now = datetime.datetime.now()
    filename = now.strftime("pypln_%Y-%m-%d_%H-%M-%S.backup")
    backup_file_path = os.path.join(BACKUP_DIR, filename)
    with settings(user=USER):
        run("pg_dump -Fc -o -f {}".format(backup_file_path))

def db_restore(filename, db_name="pypln"):
    message = "Are you sure you want to replace the current database with {}"
    if not confirm(message.format(filename), default=False):
        abort("Aborting database restore...")

    backup_file_path = os.path.join(BACKUP_DIR, filename)
    sudo("pg_restore -d template1 -C {}".format(backup_file_path), user="postgres")

def install_system_packages():
    packages = " ".join(["rabbitmq-server", "libenchant-dev",
        "python-setuptools", "python-pip", "python-numpy", "build-essential",
        "python-dev", "mongodb", "pdftohtml", "git-core", "supervisor",
        "nginx", "python-virtualenv", "postgresql", "python-psycopg2",
        "libfreetype6-dev", "fonts-dejavu", "aspell-en", "aspell-pt",
        "libjpeg-dev"])
    sudo("apt-get update")
    sudo("apt-get install -y {}".format(packages))
    # Updating virtualenv is specially important since the default changed
    # to not giving access to system python packages and the option to disable
    # this didn't exist in old versions.
    sudo("pip install --upgrade virtualenv")

def update_allowed_hosts():
    set_config_option('ALLOWED_HOSTS', env.host)

def initial_backend_setup(branch="master"):
    install_system_packages()
    _create_deploy_user()

    with settings(warn_only=True, user=USER):
        _clone_backend_repos(branch)
        run("virtualenv --system-site-packages {}".format(PROJECT_ROOT))

    _configure_supervisord(["pypln-backend"])

def initial_web_setup(branch="master"):
    install_system_packages()
    _create_deploy_user()

    with settings(warn_only=True, user=USER):
        _clone_web_repos(branch)
        run("virtualenv --system-site-packages {}".format(PROJECT_ROOT))

    _configure_supervisord(["pypln-web"])
    _configure_nginx()
    create_db('pypln', 'pypln')


def initial_setup(branch="master"):
    initial_backend_setup(branch)
    initial_web_setup(branch)

def deploy_backend(branch="master"):
    with prefix("source {}".format(ACTIVATE_SCRIPT)), settings(user=USER), cd(PROJECT_ROOT):
        _update_backend_code(branch)
        with cd(PYPLN_BACKEND_ROOT):
            run("python setup.py install")
            run("pip install Cython")
            run("pip install -r requirements/production.txt")

        run("python -m nltk.downloader genesis maxent_treebank_pos_tagger "
                "punkt stopwords averaged_perceptron_tagger")

        run("supervisorctl reload")

def deploy_web(branch="master"):
    with prefix("source {}".format(ACTIVATE_SCRIPT)), settings(user=USER), cd(PROJECT_ROOT):
        _update_web_code(branch)
        with cd(PYPLN_WEB_ROOT):
            run("pip install -r requirements/production.txt")
            run("python setup.py install")

        update_allowed_hosts()

        manage("syncdb --noinput")
        # manage("migrate") # We don't have migrations for now.
        load_site_data()
        manage("collectstatic --noinput")

        run("supervisorctl reload")

def deploy(branch="master"):
    deploy_backend(branch)
    deploy_web(branch)

def manage(command, environment="production"):
    with prefix("source {}".format(ACTIVATE_SCRIPT)), settings(user=USER):
        manage_script = os.path.join(PYPLN_WEB_ROOT, "manage.py")
        run("python {} {}".format(manage_script, command))

def load_site_data():
    initial_data_file = os.path.join(PYPLN_DEPLOY_ROOT,
            'server_config/initial_data/sites.json')
    sed(initial_data_file, "%%HOST%%", env.host, backup='')
    manage("loaddata {}".format(initial_data_file))

import psycopg2
import threading
import uuid
import time, datetime, os
from flask import Flask, redirect, request, flash
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_appbuilder.security.views import expose
from superset.security import SupersetSecurityManager
from flask_appbuilder.security.manager import BaseSecurityManager
from flask_appbuilder.security.manager import AUTH_REMOTE_USER
from flask_login import login_user
from typing import Dict, List



class db_connector():
    def __init__(self):
        self.connection = psycopg2.connect(
            dbname=os.environ.get("DB_NAME"),
            host=os.environ.get("DB_HOST"),
            user=os.environ.get("DB_USER"),
            password=os.environ.get("DB_PASSWORD"),
            port=os.environ.get("DB_PORT"))
        self.connection.autocommit = True
        self.cursor = self.connection.cursor()

    def connect(self, dbname: str = None, host: str = None, user: str = None, password: str = None, port: str = None):
        self.connection = psycopg2.connect(
            dbname=dbname or os.environ.get("DB_NAME", "my_db"),
            host=host or os.environ.get("DB_HOST", "my_db"),
            user=user or os.environ.get("DB_USER", "my_db"),
            password=password or os.environ.get("DB_PASSWORD", "my_db"),
            port=port or os.environ.get("DB_PORT", "my_db"))
        self.connection.autocommit = True
        self.cursor = self.connection.cursor()

    def get_tokens(self):
        self.cursor.execute('select as2."token", au.superset_username from django_apanel.public.accounts_user au '
                            'join django_apanel.public.analytics_supersetaccess as2 on as2.superset_username_id = au.id')
        tokens = dict(self.cursor.fetchall())
        if len(tokens) > 0:
            return tokens
        else:
            self.connect()
            self.get_tokens()


    def get_role(self, user) -> List[str]:
        if "-" in user:
            user_role_objects = [user.split('-')[-2], user.split('-')[-1]]
            roles = {'roles': user_role_objects}
        else:
            self.cursor.execute(
            f"select au.role from django_apanel.public.accounts_user au "
            f"where au.superset_username = '{user}'")
            roles = {'roles' : self.cursor.fetchone()[0]}
        return roles

    def get_user_profile(self, user):

        self.cursor.execute(
            f"select au.fullname from django_apanel.public.accounts_user au "
            f"where au.superset_username = '{user}'")
        user_data = {'f_name' : self.cursor.fetchone()[0]}

        """self.cursor.execute(
            f"select au.fullname from django_apanel.public.accounts_user au "
            f"where au.superset_username = '{user}'")"""
        user_data['l_name'] = '-'  #self.cursor.fetchone()[0]

        self.cursor.execute(
            f"select au.email from django_apanel.public.accounts_user au "
            f"where au.superset_username = '{user}'")
        user_data['e-mail'] = self.cursor.fetchone()[0]
        return user_data

    def close_connection(self):
        if self.connection:
            self.cursor.close()
            self.connection.close()

    def update_tokens(self):
        def update_values():
            if self.connection:
                while True:
                    time.sleep(86400)
                    new_values = [uuid.uuid4().hex[:10] for _ in range(self.get_row_count())]
                    update_query = "UPDATE django_apanel.public.analytics_supersetaccess SET token = CASE "
                    for i, token in enumerate(new_values):
                        update_query += f"WHEN id = {i + 1} THEN '{token}' "
                    update_query += "END"
                    self.cursor.execute(update_query)
            else:
                self.connect()
                self.update_values()

        update_thread = threading.Thread(target=update_values)
        update_thread.daemon = True
        update_thread.start()

    def get_row_count(self):
        self.cursor.execute(f"SELECT COUNT(*) FROM django_apanel.public.analytics_supersetaccess")
        return self.cursor.fetchone()[0]

#Отключенно на локальном дев стенде

#db = db_connector()
#db.update_tokens()
AuthRemoteUserView=BaseSecurityManager.authremoteuserview

class CustomAuthUserView(AuthRemoteUserView):
    login_template = ""

    def get_roles_from_db(self, userinfo):
        sm = self.appbuilder.sm
        _roles = set()
        db_roles = userinfo
        for role in db_roles:
            fab_role = sm.find_role(role)
            if fab_role:
                _roles.add(fab_role)
        print(list(_roles))
        return list(_roles)

    @expose('/login/')
    def login(self):
        try:
            sm = self.appbuilder.sm
            token = request.args.get('token')
            next = request.args.get('next')
            session = sm.get_session
            tokens = db.get_tokens()
            app = self.appbuilder.get_app
        except Exception:
           return redirect('https://datacardio.ru/supersetimages/testimage.png')
        if token in tokens.keys():
            user = session.query(sm.user_model).filter_by(username=tokens[token]).first()
            if user is not None:
                pass
            else:
                username = tokens[token]
                profile_data = db.get_role(username)
                profile_data.update(db.get_user_profile(username))
                user = sm.add_user(
                    username=username,
                    first_name=profile_data['f_name'],
                    last_name=profile_data['l_name'],
                    email=profile_data['e-mail'],
                    role=self.get_roles_from_db(profile_data['roles']))
            login_user(user, remember=False, force=True)
            if (next is not None):
                return redirect(next)
            else:
                return redirect(self.appbuilder.get_url_for_index)
        else:
            if (next is not None and 'dashboard' in next):
                return redirect('https://datacardio.ru/frame_access_error/')
            else:
                return redirect('https://datacardio.ru/access_error/')

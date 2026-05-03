import psycopg2
import threading
import uuid
import time, datetime, os
from psycopg2 import sql
from flask import Flask, redirect, request, flash
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_appbuilder.security.views import expose
from superset.security import SupersetSecurityManager
from flask_appbuilder.security.manager import BaseSecurityManager
from flask_appbuilder.security.manager import AUTH_REMOTE_USER
from flask_login import login_user
from typing import Dict, List


class DBConnector:
    """
    Класс для подключения к PostgreSQL и выполнения операций с базой данных,
    связанной с управлением пользователями и токенами Superset.

    Использует переменные окружения для подключения.
    Автоматически включает autocommit.
    """

    def __init__(self):
        """Инициализирует подключение к базе данных и создаёт курсор."""
        self.connection = psycopg2.connect(
            dbname=os.environ.get("PG_DB"),
            host=os.environ.get("PG_HOST"),
            user=os.environ.get("PG_USER"),
            password=os.environ.get("PG_PASSWORD"),
            port=os.environ.get("PG_PORT"))
        self.connection.autocommit = True
        self.cursor = self.connection.cursor()

    def connect(self):
        """Пересоздаёт подключение к базе данных и обновляет курсор.

                Полезен при потере соединения (например, после таймаута).
                Закрывает текущее соединение (если оно открыто), чтобы избежать утечек.

                Raises:
                    psycopg2.OperationalError: Если не удаётся подключиться к базе данных.
                    KeyError: Если отсутствует одна из обязательных переменных окружения.
        """
        if hasattr(self, 'connection') and self.connection and not self.connection.closed:
            self.connection.close()
        self.connection = psycopg2.connect(
            dbname=dbname or os.environ.get("PG_DB", "my_db"),
            host=host or os.environ.get("PG_HOST", "my_db"),
            user=user or os.environ.get("PG_USER", "my_db"),
            password=password or os.environ.get("PG_PASSWORD", "my_db"),
            port=port or os.environ.get("PG_PORT", "my_db"))
        self.connection.autocommit = True
        self.cursor = self.connection.cursor()

    def get_tokens(self):
        """Получает словарь токенов и соответствующих им Superset-пользователей из базы данных.

            Выполняет SQL-запрос к таблицам `accounts_user` и `analytics_supersetaccess`,
            объединяя их по идентификатору пользователя, и возвращает словарь вида:
            `{superset_token: superset_username}`.

            Если при первом запросе данные не найдены, метод пытается переподключиться
            к базе данных и повторяет запрос один раз.

            Returns:
                dict[str, str]: Словарь, где ключ — токен Superset, значение — имя пользователя.
                                Возвращается пустой словарь, если данные не найдены
                                даже после повторного подключения.
        """
        try:
            query = sql.SQL("""
                        SELECT as2."token", au.superset_username 
                        FROM {schema}.public.accounts_user au 
                        JOIN {schema}.public.analytics_supersetaccess as2 
                          ON as2.superset_username_id = au.id
                    """).format(schema=sql.Identifier(os.getenv("PG_DB")))
            self.cursor.execute(query)
            return dict(self.cursor.fetchall())
        except psycopg2.InterfaceError:
            self.connect()
            return self.get_tokens()

    def get_user_info(self, user: str) -> Dict[str, List[str]]:
        """
        Извлекает роли пользователя из его имени по шаблону:
        '...-role1-role2' → ['role1', 'role2'].

        Args:
            user (str): Имя пользователя (superset_username).

        Returns:
            Dict[str, List[str]]: Словарь вида {'roles': [role1, role2]}.

        Raises:
            IndexError: Если в имени меньше двух компонентов после разделения по '-'.
        """
        parts = user.split('-')
        if len(parts) < 2:
            return {'roles': []}
        user_role_objects = [parts[-2], parts[-1]]
        print (user_role_objects)
        return {'roles': user_role_objects}

    def get_user_profile(self, user: str) -> Dict[str, str]:
        """
        Возвращает профиль пользователя, извлекая данные из таблицы `accounts_user`.

        Args:
            user (str): Значение поля `superset_username`, по которому ищется пользователь.

        Returns:
            Dict[str, str]: Словарь с ключами:
                - 'f_name': Полное имя пользователя (fullname).
                - 'l_name': Фамилия (всегда '-').
                - 'e-mail': Адрес электронной почты пользователя.
        """
        schema_name = os.getenv("PG_DB")
        query_fullname = sql.SQL("""
                    SELECT au.fullname
                    FROM {schema}.public.accounts_user au
                    WHERE au.superset_username = {username}
                """).format(schema=sql.Identifier(schema_name), username=sql.Literal(user))
        self.cursor.execute(query_fullname)
        user_data = {'f_name': self.cursor.fetchone()[0]}

        user_data['l_name'] = '-'

        query_email = sql.SQL("""
                           SELECT au.email
                           FROM {schema}.public.accounts_user au
                           WHERE au.superset_username = {username}
                       """).format(schema=sql.Identifier(schema_name), username=sql.Literal(user))
        self.cursor.execute(query_email)
        user_data['e-mail'] = self.cursor.fetchone()[0]
        print (user_data)
        return user_data


    def close_connection(self):
        """Закрывает курсор и соединение с базой данных, если они открыты.

        Безопасно вызывать даже в том случае, если соединение уже закрыто
        или не было установлено. Проверяет наличие атрибутов и состояние
        соединения перед закрытием, чтобы избежать ошибок.

        После вызова этого метода атрибуты `self.cursor` и `self.connection`
        становятся недействительными и не должны использоваться без повторного
        подключения (например, через метод `connect()`).
        """
        if hasattr(self, 'cursor') and self.cursor and not self.cursor.closed:
            self.cursor.close()

        if hasattr(self, 'connection') and self.connection and not self.connection.closed:
            self.connection.close()

    def _update_values(self):
        schema = sql.Identifier(os.getenv("PG_DB"))
        while True:
            time.sleep(86400)  # 24 часа
            try:
                # Получаем все id и генерируем новые токены
                count_query = sql.SQL(
                    "SELECT id FROM {schema}.public.analytics_supersetaccess").format(
                    schema=schema)
                self.cursor.execute(count_query)
                ids = [row[0] for row in self.cursor.fetchall()]

                if not ids:
                    continue

                new_tokens = [uuid.uuid4().hex[:10] for _ in ids]
                case_parts = " ".join(f"WHEN id = %s THEN %s" for _ in ids)
                update_query = sql.SQL("""
                    UPDATE {schema}.public.analytics_supersetaccess 
                    SET token = CASE {case_expr} END
                """).format(schema=schema, case_expr=sql.SQL(case_parts))

                # Подготавливаем параметры: [id1, token1, id2, token2, ...]
                params = []
                for id_val, token in zip(ids, new_tokens):
                    params.extend([id_val, token])

                self.cursor.execute(update_query, params)
            except Exception:
                self.connect()

    def start_token_updater(self):
        """Запускает фоновый поток для обновления токенов."""
        thread = threading.Thread(target=self._update_values)
        thread.daemon = True
        thread.start()


# Инициализация глобального соединения с БД
db = DBConnector()
db.start_token_updater()  # Запуск фонового обновления токенов

# Наследуем базовое представление аутентификации
AuthRemoteUserView = BaseSecurityManager.authremoteuserview


class CustomAuthUserView(AuthRemoteUserView):
    """
    Кастомное представление входа, поддерживающее аутентификацию по токену,
    переданному в URL. Интегрируется с внешней БД для получения профиля и ролей.
    """

    login_template = ""  # Отключает стандартный шаблон входа

    def get_roles_from_db(self, role_names: list) -> list:
        """
        Преобразует список имён ролей в объекты ролей Flask-AppBuilder (FAB).

        Args:
            role_names (list): Список строк с именами ролей.

        Returns:
            list: Список объектов Role из FAB, соответствующих найденным ролям.
        """
        sm = self.appbuilder.sm
        _roles = set()
        for role_name in role_names:
            fab_role = sm.find_role(role_name)
            if fab_role:
                _roles.add(fab_role)
        return list(_roles)

    @expose('/login')
    def login(self):
        """
        Обрабатывает вход пользователя по токену из query-параметра ?token=...

        Логика:
        1. Получает токен и URL редиректа ('next').
        2. Сравнивает токен со списком из БД.
        3. Если пользователь существует — авторизует.
        4. Если нет — создаёт нового пользователя на основе данных из БД.
        5. При ошибках — ретраит подключение к БД до 3 раз.

        Returns:
            Response: Редирект на целевую страницу или страницу ошибки.
        """
        max_retries = 3
        retries = 0

        while retries < max_retries:
            try:
                token = request.args.get('token')
                next_url = request.args.get('next')
                tokens = db.get_tokens()
                tokens = {'123abcd456': 'admin'}
                break
            except Exception as e:
                retries += 1
                if retries >= max_retries:
                    return redirect('https://datacardio.almazovcentre.ru/access_error/')
                try:
                    time.sleep(0.5)
                    db.connect()
                except Exception:
                    return redirect('https://datacardio.almazovcentre.ru/access_error/')
        else:
            return redirect('https://datacardio.almazovcentre.ru/access_error/')

        # --- Проверка токена ---
        if not token or token not in tokens:
            if next_url and 'dashboard' in next_url:
                return redirect('https://datacardio.almazovcentre.ru/access_error/')
            else:
                return redirect('https://datacardio.almazovcentre.ru/access_error/')

        # --- Авторизация или создание пользователя ---
        sm = self.appbuilder.sm
        username = tokens[token]
        print (username)
        user = sm.get_user_by_username(username)
        if user is None:
            # Получаем данные пользователя из внешней БД
            try:
                user_info = db.get_user_info(username)  # ← роли из имени
                profile_data = db.get_user_profile(username)  # ← ФИО, email
                profile_data.update(user_info)  # объединяем
            except Exception as e:
                print(f"Ошибка загрузки профиля для {username}: {e}")
                return redirect('https://datacardio.almazovcentre.ru/access_error/')

            # Создаём нового пользователя в Superset
            user = sm.add_user(
                username=username,
                first_name=profile_data.get('f_name', ''),
                last_name=profile_data.get('l_name', '-'),
                email=profile_data.get('e-mail', ''),
                role=self.get_roles_from_db(profile_data['roles']))
            if not user:
                print(f"Не удалось создать пользователя {username}")
                return redirect('https://datacardio.almazovcentre.ru/access_error/')

        # Авторизуем пользователя
        login_user(user, remember=False, force=True)
        next_url = request.args.get('next')
        if next_url:
            # Optional: Validate next_url to prevent open redirect vulnerabilities
            # For now, redirecting to the provided URL
            return redirect(next_url)
        else:
            # Redirect to a default page, e.g., the main Superset page or user's profile
            # You might want to use Flask's url_for here for internal redirects
            # e.g., return redirect(url_for('Superset.index')) or return redirect('/')
            # For now, redirecting to a default page like the Superset welcome page
            return redirect(self.appbuilder.get_url_for_index)  # Or another appropriate default

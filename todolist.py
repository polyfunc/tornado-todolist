import asyncio
import concurrent.futures
import os
from datetime import datetime

import bcrypt
import motor
import tornado.httpserver
import tornado.options
import tornado.platform.asyncio
import tornado.web
from tornado.options import define, options

BASEDIR = os.path.dirname(__file__)

# define command line arguments
define('port', default=8000, help='run on the given port', type=int)

# A thread pool to be used for password hashing with bcrypt.
bcrypt_executor = concurrent.futures.ThreadPoolExecutor(2)


async def add_job_to_pool(fn, *args):
    return await tornado.platform.asyncio.to_asyncio_future(
        bcrypt_executor.submit(fn, *args))


async def hash_password(password, salt=None):
    salt = bcrypt.gensalt() if salt is None else salt
    return await add_job_to_pool(bcrypt.hashpw, password, salt)


class Application(tornado.web.Application):
    def __init__(self):
        handlers = [
            tornado.web.url(r'/', MainHandler, name='main'),
            tornado.web.url(r'/todolist/\d+',
                            TodolistHandler, name='todolist'),
            tornado.web.url(r'/overview',
                            TodolistOverviewHandler, name='overview'),
            tornado.web.url(r'/register', RegisterHandler, name='register'),
            tornado.web.url(r'/login', LoginHandler, name='login'),
            tornado.web.url(r'/logout', LogoutHandler, name='logout'),
        ]
        settings = {
            'static_path':  os.path.join(BASEDIR, 'static'),
            'template_path': os.path.join(BASEDIR, 'templates'),
            'debug': True,
            'cookie_secret': os.environ.get('SECRET_KEY') or 'testing key',
            'xsrf_cookies': True,
        }
        super().__init__(handlers=handlers, **settings)

        self.db = motor.motor_tornado.MotorClient().todolist


class BaseHandler(tornado.web.RequestHandler):
    @property
    def db(self):
        return self.application.db

    def get_current_user(self):
        return self.get_secure_cookie('user')


class TodolistHandler(BaseHandler):
    async def get(self, todolist_id):
        todolist = await self.db.todolists.find_one({
            'todolist_id': todolist_id
        })
        self.render('todolist.html', todolist=todolist)

    async def post(self, todolist_id):
        description = tornado.escape.xhtml_escape(
            self.get_argument('description'))
        # TODO validate input
        # TODO add to lists of todos of the todolist with the given id
        await self.db.todos.insert_one({
            'description': description,
            'created_at': datetime.utcnow(),
            'finished_at': None,
            'is_finsished': False,
            'todolist_id': todolist_id,
            'creator': self.get_current_user(),
        })
        self.redirect(self.reverse_url('todolist', todolist_id))


class TodolistOverviewHandler(BaseHandler):
    @tornado.web.authenticated
    async def get(self):
        todolists = await self.db.todolist.find({
            'creator': self.get_current_user()
        })
        self.render('overview.html', todolists=todolists)

    @tornado.web.authenticated
    async def post(self):
        title = tornado.escape.xhtml_escape(self.get_argument('title'))
        await self.db.todolists.insert_one({
            'title': title,
            'creator': self.get_current_user(),
            'created_at': datetime.utcnow(),
            'todos': [],
        })
        self.redirect(self.reverse_url('overview'))


class RegisterHandler(BaseHandler):
    def get(self):
        self.render('register.html')

    async def post(self):
        username = tornado.escape.xhtml_escape(self.get_argument('username'))
        email = tornado.escape.xhtml_escape(self.get_argument('email'))
        password = tornado.escape.utf8(self.get_argument('password'))
        password_confirmation = tornado.escape.utf8(
            self.get_argument('password_confirmation'))
        # TODO add proper password check
        assert password == password_confirmation

        hashed_password = await hash_password(password)
        # TODO add proper check for input (username, email)
        await self.db.users.insert_one({
            'username': username,
            'email': email,
            'password_hash': hashed_password,
        })
        self.redirect(self.reverse_url('main'))


class LoginHandler(BaseHandler):
    def get(self):
        self.render('login.html')

    async def post(self):
        email_or_username = tornado.escape.xhtml_escape(
            self.get_argument('email_or_username'))
        user = await self.db.users.find_one({'$or': [
            {'email': email_or_username},
            {'username': email_or_username},
        ]})
        if user and await self.check_password(user):
            self.set_secure_cookie('user', user['username'])
            self.redirect(self.get_argument('next', self.reverse_url('main')))
        else:
            # TODO indicate failure
            self.redirect(self.reverse_url('login'))

    async def check_password(self, user):
        hashed_password = await hash_password(
            tornado.escape.utf8(self.get_argument('password')),
            user['password_hash'])
        return user['password_hash'] == hashed_password


class LogoutHandler(BaseHandler):
    def get(self):
        self.clear_cookie('user')
        self.redirect(self.get_argument('next', self.reverse_url('main')))


class MainHandler(BaseHandler):
    def get(self):
        self.render('index.html')


def main():
    tornado.platform.asyncio.AsyncIOMainLoop().install()
    tornado.options.parse_command_line()
    http_server = tornado.httpserver.HTTPServer(Application())
    http_server.listen(options.port)
    asyncio.get_event_loop().run_forever()


if __name__ == '__main__':
    main()

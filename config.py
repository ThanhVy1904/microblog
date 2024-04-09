import os
from dotenv import load_dotenv

basedir = os.path.abspath(os.path.dirname(__file__))
load_dotenv(os.path.join(basedir, '.env'))

class Config(object):
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'you-will-never-guess'
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or \
        'sqlite:///' + os.path.join(basedir, 'app.db')
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # chuyển đổi ngôn ngữ
    LANGUAGES = ['en', 'es']

    # Tìm kiếm bài post
    ELASTICSEARCH_URL = os.environ.get('ELASTICSEARCH_URL')

    # Gửi lỗi qua em
    MAIL_SERVER = os.environ.get('MAIL_SERVER')
    MAIL_PORT = int(os.environ.get('MAIL_PORT') or 25)
    MAIL_USE_TLS = os.environ.get('MAIL_USE_TLS') is not None
    MAIL_USERNAME = os.environ.get('MAIL_USERNAME')
    MAIL_PASSWORD = os.environ.get('MAIL_PASSWORD')
    ADMINS = ['your-email@example.com'] #mail của mình đó, tại mình là admin mà

    # Số lượng bài post trên 1 trang
    POSTS_PER_PAGE = 10

    REDIS_URL = os.environ.get('REDIS_URL') or 'redis://'
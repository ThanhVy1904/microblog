from datetime import datetime, timezone, timedelta
from hashlib import md5
from time import time
from typing import Optional
import sqlalchemy as sa
import sqlalchemy.orm as so
from flask import current_app, url_for
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
import jwt
from app import db, login
from app.search import add_to_index, remove_from_index, query_index
import json
import redis
import rq
import secrets


# TÌM KIẾM POST

class SearchableMixin:
    @classmethod
    def search(cls, expression, page, per_page):
        ids, total = query_index(cls.__tablename__, expression, page, per_page)
        if total == 0:
            return [], 0
        when = []
        for i in range(len(ids)):
            when.append((ids[i], i))
        query = sa.select(cls).where(cls.id.in_(ids)).order_by(
            db.case(*when, value=cls.id))
        return db.session.scalars(query), total

    @classmethod
    def before_commit(cls, session):
        session._changes = {
            'add': list(session.new),
            'update': list(session.dirty),
            'delete': list(session.deleted)
        }

    @classmethod
    def after_commit(cls, session):
        for obj in session._changes['add']:
            if isinstance(obj, SearchableMixin):
                add_to_index(obj.__tablename__, obj)
        for obj in session._changes['update']:
            if isinstance(obj, SearchableMixin):
                add_to_index(obj.__tablename__, obj)
        for obj in session._changes['delete']:
            if isinstance(obj, SearchableMixin):
                remove_from_index(obj.__tablename__, obj)
        session._changes = None

    @classmethod
    def reindex(cls):
        for obj in db.session.scalars(sa.select(cls)):
            add_to_index(cls.__tablename__, obj)


db.event.listen(db.session, 'before_commit', SearchableMixin.before_commit)
db.event.listen(db.session, 'after_commit', SearchableMixin.after_commit)


# nguoi theo doi
followers = sa.Table(
    'followers',
    db.metadata,
    sa.Column('follower_id', sa.Integer, sa.ForeignKey('user.id'),
              primary_key=True),
    sa.Column('followed_id', sa.Integer, sa.ForeignKey('user.id'),
              primary_key=True)
)

class PaginatedAPIMixin(object):
    @staticmethod
    #tao dictionary
    def to_collection_dict(query, page, per_page, endpoint, **kwargs):
        resources = db.paginate(query, page=page, per_page=per_page,
                                error_out=False)
        data = {
            'items': [item.to_dict() for item in resources.items],
            '_meta': {
                'page': page,
                'per_page': per_page,
                'total_pages': resources.pages,
                'total_items': resources.total
            },
            '_links': {
                'self': url_for(endpoint, page=page, per_page=per_page,
                                **kwargs),
                'next': url_for(endpoint, page=page + 1, per_page=per_page,
                                **kwargs) if resources.has_next else None,
                'prev': url_for(endpoint, page=page - 1, per_page=per_page,
                                **kwargs) if resources.has_prev else None
            }
        }
        return data

@login.user_loader
def load_user(id):
    return db.session.get(User, int(id))

# TẠO BẢNG USER
class User(PaginatedAPIMixin, UserMixin, db.Model):
    __tablename__ = 'user'
    id: so.Mapped[int] = so.mapped_column(primary_key=True)
    username: so.Mapped[str] = so.mapped_column(sa.String(64), index=True, unique=True)
    email: so.Mapped[str] = so.mapped_column(sa.String(120), index=True, unique=True)
    password_hash: so.Mapped[Optional[str]] = so.mapped_column(sa.String(256))
    posts: so.WriteOnlyMapped['Post'] = so.relationship('Post', back_populates='author')
    about_me: so.Mapped[Optional[str]] = so.mapped_column(sa.String(140))
    # thời gian lần cuối truy cập web
    last_seen: so.Mapped[Optional[datetime]] = so.mapped_column(default=lambda: datetime.now(timezone.utc))
    # thoi gian cuoi cung user truy cap trang tin nhan
    last_message_read_time: so.Mapped[Optional[datetime]]
    # Người đang theo dõi
    following: so.WriteOnlyMapped['User'] = so.relationship(
        secondary=followers, primaryjoin=(followers.c.follower_id == id),
        secondaryjoin=(followers.c.followed_id == id),
        back_populates='followers')

    # Ngừoi mình theo dõi
    followers: so.WriteOnlyMapped['User'] = so.relationship(
        secondary=followers, primaryjoin=(followers.c.followed_id == id),
        secondaryjoin=(followers.c.follower_id == id),
        back_populates='following')

    # Tin nhan gui
    messages_sent: so.WriteOnlyMapped['Message'] = so.relationship(
        foreign_keys='Message.sender_id', back_populates='author')
    # Tin nhan nhan
    messages_received: so.WriteOnlyMapped['Message'] = so.relationship(
        foreign_keys='Message.recipient_id', back_populates='recipient')
    # Thong bao tin nhan chua doc
    notifications: so.WriteOnlyMapped['Notification'] = so.relationship(
        back_populates='user')

    tasks: so.WriteOnlyMapped['Task'] = so.relationship(back_populates='user')

    token: so.Mapped[Optional[str]] = so.mapped_column(sa.String(32), index=True, unique=True)
    token_expiration: so.Mapped[Optional[datetime]]

    def __repr__(self):
        return '<User {}>'.format(self.username)

    # MÃ HOÁ PASSWORD
    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    # KIỂM TRA PASSWORD_HASH
    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    # URL HÌNH ĐẠI DIỆN
    def avatar(self, size):
        digest = md5(self.email.lower().encode('utf-8')).hexdigest()
        return f'https://www.gravatar.com/avatar/{digest}?d=identicon&s={size}'

    # THEO DÕI
    def follow(self, user):
        if not self.is_following(user):
            self.following.add(user)

    # BỎ THEO DÕI
    def unfollow(self, user):
        if self.is_following(user):
            self.following.remove(user)

    # KIỂM TRA XEM NGƯỜI ĐÓ ĐÃ THEO DÕI HAY CHƯA (ID USER ĐÓ ĐÃ CÓ TRONG DATA CHƯA)
    def is_following(self, user):
        query = self.following.select().where(User.id == user.id)
        return db.session.scalar(query) is not None

    # ĐẾM SỐ NGƯỜI THEO DÕI MÌNH
    def followers_count(self):
        query = sa.select(sa.func.count()).select_from(
            self.followers.select().subquery())
        return db.session.scalar(query)

    # ĐẾM SỐ NGƯỜI MÌNH THEO DÕI
    def following_count(self):
        query = sa.select(sa.func.count()).select_from(
            self.following.select().subquery())
        return db.session.scalar(query)

    # NHỮNG BÀI POST CỦA NGƯỜI MÌNH THEO DÕI + BÀI CỦA BẢN THÂN
    def following_posts(self):
        # aliased() đổi tên bảng tạm thời từ User thành Author, Follower
        Author = so.aliased(User)
        Follower = so.aliased(User)
        return (
            sa.select(Post)
                .join(Post.author.of_type(Author))
                .join(Author.followers.of_type(Follower), isouter=True)
                .where(sa.or_(
                Follower.id == self.id,
                Author.id == self.id,
                ))
                .group_by(Post)
                .order_by(Post.timestamp.desc())
        )

    # Đặt lại mật khẩu
    def get_reset_password_token(self, expires_in=600):
        return jwt.encode(
            {'reset_password': self.id, 'exp': time() + expires_in},
            current_app.config['SECRET_KEY'], algorithm='HS256')

    @staticmethod
    def verify_reset_password_token(token):
        try:
            id = jwt.decode(token, current_app.config['SECRET_KEY'],
                            algorithms=['HS256'])['reset_password']
        except Exception:
            return
        return db.session.get(User, id)

    def unread_message_count(self):
        last_read_time = self.last_message_read_time or datetime(1900, 1, 1)
        query = sa.select(Message).where(Message.recipient == self, Message.timestamp > last_read_time)
        return db.session.scalar(sa.select(sa.func.count()).select_from(
            query.subquery()))

    def add_notification(self, name, data):
        db.session.execute(self.notifications.delete().where(
            Notification.name == name))
        n = Notification(name=name, payload_json=json.dumps(data), user=self)
        db.session.add(n)
        return n

    def launch_task(self, name, description, *args, **kwargs):
        rq_job = current_app.task_queue.enqueue(f'app.tasks.{name}', self.id,
                                                *args, **kwargs)
        task = Task(id=rq_job.get_id(), name=name, description=description,
                    user=self)
        db.session.add(task)
        return task

    def get_tasks_in_progress(self):
        query = self.tasks.select().where(Task.complete == False)
        return db.session.scalars(query)

    def get_task_in_progress(self, name):
        query = self.tasks.select().where(Task.name == name,
                                          Task.complete == False)
        return db.session.scalar(query)

    def posts_count(self):
        query = sa.select(sa.func.count()).select_from(
            self.posts.select().subquery())
        return db.session.scalar(query)

    # chuyen doi user thanh json
    def to_dict(self, include_email=False):
        data = {
            'id': self.id,
            'username': self.username,
            'last_seen': self.last_seen.replace(tzinfo=timezone.utc).isoformat(),
            'about_me': self.about_me,
            'post_count': self.posts_count(),
            'follower_count': self.followers_count(),
            'following_count': self.following_count(),
            '_links': {
                'self': url_for('api.get_user', id=self.id),
                'followers': url_for('api.get_followers', id=self.id),
                'following': url_for('api.get_following', id=self.id),
                'post': url_for('api.get_post', id=self.id),
                'avatar': self.avatar(128)
            }
        }
        # include email: kiem tra xem co tra ve du lieu mail hay ko, tra ve khi user xem chinh thong tin cua ho
        if include_email:
            data['email'] = self.email
        return data
    # chuyen du lieu thanh user
    def from_dict(self, data, new_user=False):
        for field in ['username', 'email', 'about_me']:
            if field in data:
                setattr(self, field, data[field])
        if new_user and 'password' in data:
            self.set_password(data['password'])

    # Tra token cho user
    def get_token(self, expires_in=3600):
        now = datetime.now(timezone.utc)
        # kiểm tra xem token còn hạn trên 1 phút hay ko
        if self.token and self.token_expiration.replace(tzinfo=timezone.utc) > now + timedelta(seconds=60):
            return self.token

        self.token = secrets.token_hex(16)
        self.token_expiration = now + timedelta(seconds=expires_in)
        db.session.add(self)
        return self.token

    # Lam mat hieu luc cua token
    def revoke_token(self):
        self.token_expiration = datetime.now(timezone.utc) - timedelta(seconds=1)

    # Trả về user sở hữu token đó
    @staticmethod
    def check_token(token):
        user = db.session.scalar(sa.select(User).where(User.token == token))
        if user is None or user.token_expiration.replace(tzinfo=timezone.utc) < datetime.now(timezone.utc):
            return None
        return user


# TẠO BẢNG POST
class Post(PaginatedAPIMixin, SearchableMixin, db.Model):
    __searchable__ = ['body']
    __tablename__ = 'post'
    id: so.Mapped[int] = so.mapped_column(primary_key=True)
    body: so.Mapped[str] = so.mapped_column(sa.String(140))
    timestamp: so.Mapped[datetime] = so.mapped_column(index=True, default=lambda: datetime.now(timezone.utc))
    user_id: so.Mapped[str] = so.mapped_column(sa.ForeignKey(User.id), index=True)
    author: so.Mapped[User] = so.relationship('User', back_populates='posts')
    # Nối 2 bảng User và Post với nhau bằng relationship
    language: so.Mapped[Optional[str]] = so.mapped_column(sa.String(5))

    def __repr__(self):
        return '<Post {}>'.format(self.body)

    # chuyen doi post thanh json
    def to_dict(self):
        data = {
            'id': self.id,
            'body': self.body,
            'timestamp': self.timestamp.replace(tzinfo=timezone.utc).isoformat(),
            'user_id': self.user_id,
            'language': self.language
        }
        return data

    # chuyen du lieu thanh post
    def from_dict(self, data):
        for field in ['body', 'user_id']:
            if field in data:
                setattr(self, field, data[field])

class Message(db.Model):
    id: so.Mapped[int] = so.mapped_column(primary_key=True)
    sender_id: so.Mapped[int] = so.mapped_column(sa.ForeignKey(User.id),
                                                 index=True)
    recipient_id: so.Mapped[int] = so.mapped_column(sa.ForeignKey(User.id),
                                                    index=True)
    body: so.Mapped[str] = so.mapped_column(sa.String(140))
    timestamp: so.Mapped[datetime] = so.mapped_column(
        index=True, default=lambda: datetime.now(timezone.utc))

    author: so.Mapped[User] = so.relationship(
        foreign_keys='Message.sender_id',
        back_populates='messages_sent')
    recipient: so.Mapped[User] = so.relationship(
        foreign_keys='Message.recipient_id',
        back_populates='messages_received')

    def __repr__(self):
        return '<Message {}>'.format(self.body)

class Notification(db.Model):
    id: so.Mapped[int] = so.mapped_column(primary_key=True)
    name: so.Mapped[str] = so.mapped_column(sa.String(128), index=True)
    user_id: so.Mapped[int] = so.mapped_column(sa.ForeignKey(User.id),
                                               index=True)
    timestamp: so.Mapped[float] = so.mapped_column(index=True, default=time)
    payload_json: so.Mapped[str] = so.mapped_column(sa.Text)

    user: so.Mapped[User] = so.relationship(back_populates='notifications')

    def get_data(self):
        return json.loads(str(self.payload_json))

class Task(db.Model):
    id: so.Mapped[str] = so.mapped_column(sa.String(36), primary_key=True)
    name: so.Mapped[str] = so.mapped_column(sa.String(128), index=True)
    description: so.Mapped[Optional[str]] = so.mapped_column(sa.String(128))
    user_id: so.Mapped[int] = so.mapped_column(sa.ForeignKey(User.id))
    complete: so.Mapped[bool] = so.mapped_column(default=False)

    user: so.Mapped[User] = so.relationship(back_populates='tasks')

    def get_rq_job(self):
        try:
            rq_job = rq.job.Job.fetch(self.id, connection=current_app.redis)
        except (redis.exceptions.RedisError, rq.exceptions.NoSuchJobError):
            return None
        return rq_job

    def get_progress(self):
        job = self.get_rq_job()
        return job.meta.get('progress', 0) if job is not None else 100


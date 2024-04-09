import sqlalchemy as sa
from flask import request, url_for, abort
from app import db
from app.models import User, Post
from app.api import bp
from app.api.auth import token_auth
from app.api.errors import bad_request
from langdetect import detect


@bp.route('/users/<int:id>', methods=['GET'])
@token_auth.login_required
def get_user(id):
    return db.get_or_404(User, id).to_dict()


@bp.route('/users', methods=['GET'])
@token_auth.login_required
def get_users():
    page = request.args.get('page', 1, type=int)
    per_page = min(request.args.get('per_page', 10, type=int), 100)
    return User.to_collection_dict(sa.select(User), page, per_page,
                                   'api.get_users')


@bp.route('/users/<int:id>/followers', methods=['GET'])
@token_auth.login_required
def get_followers(id):
    user = db.get_or_404(User, id)
    page = request.args.get('page', 1, type=int)
    per_page = min(request.args.get('per_page', 10, type=int), 100)
    return User.to_collection_dict(user.followers.select(), page, per_page,
                                   'api.get_followers', id=id)


@bp.route('/users/<int:id>/following', methods=['GET'])
@token_auth.login_required
def get_following(id):
    user = db.get_or_404(User, id)
    page = request.args.get('page', 1, type=int)
    per_page = min(request.args.get('per_page', 10, type=int), 100)
    return User.to_collection_dict(user.following.select(), page, per_page,
                                   'api.get_following', id=id)


@bp.route('/users', methods=['POST'])
def create_user():
    data = request.get_json()
    if 'username' not in data or 'email' not in data or 'password' not in data:
        return bad_request('must include username, email and password fields')
    if db.session.scalar(sa.select(User).where(
            User.username == data['username'])):
        return bad_request('please use a different username')
    if db.session.scalar(sa.select(User).where(
            User.email == data['email'])):
        return bad_request('please use a different email address')
    user = User()
    user.from_dict(data, new_user=True)
    db.session.add(user)
    db.session.commit()
    return user.to_dict(), 201, {'Location': url_for('api.get_user',
                                                     id=user.id)}


@bp.route('/users/<int:id>', methods=['PUT'])
@token_auth.login_required
def update_user(id):
    if token_auth.current_user().id != id:
        abort(403)
    user = db.get_or_404(User, id)
    data = request.get_json()
    if 'username' in data and data['username'] != user.username and \
        db.session.scalar(sa.select(User).where(
            User.username == data['username'])):
        return bad_request('please use a different username')
    if 'email' in data and data['email'] != user.email and \
        db.session.scalar(sa.select(User).where(
            User.email == data['email'])):
        return bad_request('please use a different email address')
    user.from_dict(data, new_user=False)
    db.session.commit()
    return user.to_dict()

@bp.route('/users/<int:id>/post', methods=['GET'])
@token_auth.login_required
def get_post(id):
    page = request.args.get('page', 1, type=int)
    per_page = min(request.args.get('per_page', 10, type=int), 100)
    return Post.to_collection_dict(sa.select(Post).where(Post.user_id==id), page, per_page,
                                   'api.get_post', id=id)
@bp.route('/users/<int:id>/posts', methods=['GET'])
@token_auth.login_required
def get_all_posts(id):
    page = request.args.get('page', 1, type=int)
    per_page = min(request.args.get('per_page', 10, type=int), 100)
    return Post.to_collection_dict(sa.select(Post), page, per_page,
                                   'api.get_all_posts', id=id)

@bp.route('/users/<int:id>', methods=['POST'])
def create_post(id):
    data = request.get_json()
    post = Post()
    post.from_dict(data)
    post.user_id = id
    post.language = detect(post.body)
    db.session.add(post)
    db.session.commit()
    return post.to_dict(), 201, {'Location': url_for('api.get_post', id=id)}

@bp.route('/users/<int:user_id>/post/<int:post_id>', methods=['PUT'])
@token_auth.login_required
def update_post(user_id, post_id):
    if token_auth.current_user().id != user_id:
        abort(403)
    post = db.get_or_404(Post, post_id)
    data = request.get_json()
    post.from_dict(data)
    db.session.commit()
    return post.to_dict()
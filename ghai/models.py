from datetime import datetime
import json
from sqlalchemy import (
    Column, Integer, String, ForeignKey, DateTime, Boolean)
from sqlalchemy.orm import relationship, backref
from sqlalchemy.types import TypeDecorator, VARCHAR
from flask.ext.sqlalchemy import SQLAlchemy


REF_MAP = {'repository': 'repo'}
db = SQLAlchemy()


class JSONEncodedDict(TypeDecorator):
    """Represents an immutable structure as a json-encoded string.

    Usage::

        JSONEncodedDict(255)

    """

    impl = VARCHAR

    def process_bind_param(self, value, dialect):
        if value is not None:
            value = json.dumps(value)

        return value

    def process_result_value(self, value, dialect):
        if value is not None:
            value = json.loads(value)
        return value


# Bases
class User(db.Model):

    __tablename__ = 'users'

    id = Column(Integer, primary_key=True)
    login = Column(String(80), unique=True)
    name = Column(String(120))

    def __init__(self, login, name):
        self.login = login
        self.name = name

    def __repr__(self):
        return '<User %r>' % self.login

    @staticmethod
    def get_or_create(login, name, feeds=None):
        user = User.query.filter_by(login=login).first()
        if user:
            return user

        feeds = feeds or []
        feeds.append('/users/{0}/received_events'.format(login))
        user = User(login, name)
        db.session.add(user)
        for feed in feeds:
            user_feed = Feed(feed, user)
            db.session.add(user_feed)
        db.session.commit()
        return user


class Feed(db.Model):

    __tablename__ = 'feeds'

    id = Column(Integer, primary_key=True)
    url = Column(String(120))
    user_id = Column(Integer, ForeignKey('users.id'))
    user = relationship('User', backref=backref('feeds', lazy='dynamic'))

    def __init__(self, url, user):
        self.url = url
        self.user = user

    def __repr__(self):
        return '<Feed %r>' % self.url


class Item(db.Model):

    __tablename__ = 'items'

    id = Column(Integer, primary_key=True)
    content = Column(JSONEncodedDict(1023))
    feed_id = Column(Integer, ForeignKey('feeds.id'))
    date = Column(DateTime)
    archived = Column(Boolean())
    feed = relationship('Feed',
                        backref=backref('items', lazy='dynamic'))

    def __init__(self, feed, content):
        self.feed = feed
        self.content = content
        self.archived = False

    def __repr__(self):
        return '<Item %r>' % self.content

    def render(self, request_user):
        resp_item = self.content
        repo = resp_item['repo']['name']
        user = resp_item['actor']['login']
        repo_user = repo.split('/')[0]
        act = self.__get_activity(resp_item['type'], resp_item['payload'])
        txt = '<a href="https://github.com/{0}">{0}</a> {2} <a href="https://github.com/{1}">{1}</a>.'.format(user, repo, act)
        if resp_item['type'] == 'ForkEvent':
            txt += ' to <a href="{0}">{1}/{2}</a>'.format(resp_item['payload']['forkee']['svn_url'],
                                                        user,
                                                        resp_item['payload']['forkee']['name'])
        return repo, txt

    @staticmethod
    def parse_and_add(resp_item, feed, request_user):
        if Item.query.filter(Item.id==resp_item['id']).first():
            return False
        user = resp_item['actor']['login']
        if user == feed.user.login:
            return False
        item = Item(feed, resp_item)
        item.date = datetime.strptime(resp_item['created_at'], "%Y-%m-%dT%H:%M:%SZ")
        item.id = resp_item['id']
        db.session.add(item)
        db.session.commit()
        return True

    def __get_activity(self, type, payload):
        if type == 'WatchEvent':
            return 'starred'
        elif type == 'CreateEvent':
            return 'created {0}'.format(payload['ref_type'])
        elif type == 'ForkEvent':
            return 'forked'
        elif type == 'PushEvent':
            return 'pushed to'
        elif type == 'PullRequestEvent':
            return '{0} pull request'.format(payload['action'])
        elif type == 'DeleteEvent':
            return 'deleted {0} {1} at'.format(payload['ref_type'],
                                               payload['ref'])
        elif type == 'IssuesEvent':
            return '{0} issue (<a href="{1}">#{2}</a>)'.format(payload['action'],
                                                               payload['issue']['html_url'],
                                                               payload['issue']['number'])
        elif type == 'IssueCommentEvent':
            return 'commented issue (<a href="{0}">#{1}</a>)'.format(payload['issue']['html_url'],
                                                                     payload['issue']['number'])
        elif resp_item['type'] == 'CommitCommentEvent':
            return 'commented on commit <a href="{0}">{1}</a>'.format(payload['comment']['html_url'],
                                                                      payload['comment']['commit_id'])
        elif resp_item['type'] == 'GollumEvent':
            page = resp_item['payload']['pages'][0]
            return '{0} wiki <a href="{1}">{2}</a>'.format(page['action'], page['html_url'], page['page_name'])
        else:
            print resp_item['type'], resp_item

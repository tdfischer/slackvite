#!/usr/bin/env activate
from werkzeug.local import LocalProxy
from flask import Flask, render_template, request, url_for, abort, redirect, flash, render_template_string, g
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, login_required, login_user, logout_user, current_user
from flask_oauth import OAuth
from flask_mail import Mail, Message
from slacker import Slacker, Error
import os


app = Flask(__name__)

app.config['CODE_OF_CONDUCT'] = os.environ.get('CODE_OF_CONDUCT', '')
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ['DATABASE_URI']
app.config['SLACK_KEY'] = os.environ['SLACK_KEY']
app.config['SLACK_SECRET'] = os.environ['SLACK_SECRET']
app.config['SLACK_ADMIN_TOKEN'] = os.environ['SLACK_ADMIN_TOKEN']
app.config['SLACK_NOTIFY_CHANNEL'] = os.environ['SLACK_NOTIFY_CHANNEL']

if 'EMAIL_FROM' in os.environ:
    app.config['DEFAULT_MAIL_SENDER'] = os.environ['EMAIL_FROM']
    app.config['USE_EMAIL'] = True
else:
    app.config['USE_EMAIL'] = False
app.secret_key = os.environ['SECRET_SESSION_KEY']
db = SQLAlchemy(app)
oauth = OAuth()
mail = Mail(app)

login_manager = LoginManager()
login_manager.init_app(app)

def get_slack_team_info():
    slackInfo = getattr(g, '_slack_team', None)
    if slackInfo is None:
        adminSlack = Slacker(app.config['SLACK_ADMIN_TOKEN'])
        slackInfo = g._slack_team = adminSlack.api.get('team.info').body['team']
    return slackInfo

SLACK_TEAM = LocalProxy(get_slack_team_info)

@app.context_processor
def add_slack_context():
    return {'SLACK': SLACK_TEAM}

@app.context_processor
def add_coc_url():
    return {'CODE_OF_CONDUCT': app.config['CODE_OF_CONDUCT']}

@login_manager.user_loader
def load_user(user_id):
    return Member.query.filter(Member.id==user_id).first()

class Application(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    created = db.Column(db.DateTime)
    email = db.Column(db.String, unique=True)
    name = db.Column(db.String, unique=True)
    reason = db.Column(db.String)
    state = db.Column(db.String)

    STATE_NEW = ''
    STATE_REJECTED = 'rejected'
    STATE_REJECTED_MAILED = 'rejected-and-emailed'
    STATE_APPROVED = 'approved'
    STATE_APPROVED_MAILED = 'approved-and-emailed'

    def __init__(self, email, name, reason):
        self.email = email
        self.name = name
        self.reason = reason
        self.state = self.STATE_NEW

    def send_email(self, subject, template_name, **kwargs):
        if app.config['USE_EMAIL']:
            msg = Message(subject, recipients=[self.email])
            msg.body = render_template(template_name, **kwargs)
            mail.send(msg)

    def process(self):
        if self.state == self.STATE_NEW:
            slack = Slacker(app.config['SLACK_ADMIN_TOKEN'])
            msg = {}
            msg['text'] = 'New invite application from %s'%(self.name),
            msg['channel'] = app.config['SLACK_NOTIFY_CHANNEL']
            msg['as_user'] = False
            msg['username'] = 'Slackvite'
            msg['icon_emoji'] = 'wave'
            msg['attachments'] = [{
                'fallback': 'New invite application from %s'%(self.name),
                'text': '%s has applied to join the %s slack'%(self.name, SLACK_TEAM['name']),
                'fields': [
                    {'title': 'Name', 'value': self.name, 'short': True},
                    {'title': 'E-mail', 'value': self.email, 'short': True},
                    {'title': 'Reason', 'value': self.reason, 'short': False}
                ]
            }]
            slack.api.post('chat.postMessage', params=msg)
        elif self.state == self.STATE_REJECTED:
            self.state = self.STATE_REJECTED_MAILED
            slack = Slacker(app.config['SLACK_ADMIN_TOKEN'])
            msg = {}
            msg['channel'] = app.config['SLACK_NOTIFY_CHANNEL']
            msg['text'] = 'Invite application from %s was rejected'%(self.name)
            msg['as_user'] = False
            msg['attachments'] = [{
                'fallback': 'Invite application from %s was rejected.'%(self.name),
                'text': 'Invite application from %s to join the %s slack was rejected.'%(self.name, SLACK_TEAM['name']),
            }]
            slack.api.post('chat.postMessage', params=msg)
            self.send_email('Your application to join %s was rejected'%(SLACK_TEAM['name']), 'rejected.eml', user=self)
            flash("Application from %s rejected."%(self.email))
        elif self.state == self.STATE_APPROVED:
            self.state = self.STATE_APPROVED_MAILED
            slack = Slacker(app.config['SLACK_ADMIN_TOKEN'])
            try:
                slack.api.post('users.admin.invite', params={'email':self.email,
                    'set_active':True})
            except Error, e:
                if e.message == 'already_invited':
                    flash("Slack says they're already invited.")
                    return
            msg = {}
            msg['channel'] = app.config['SLACK_NOTIFY_CHANNEL']
            msg['text'] = 'Invite application from %s was approved!'%(self.name)
            msg['as_user'] = False
            msg['attachments'] = [{
                'fallback': 'Invite application from %s was approved!.'%(self.name),
                'text': 'Invite application from %s to join the %s slack was approved!.'%(self.name, SLACK_TEAM['name']),
            }]
            slack.api.post('chat.postMessage', params=msg)
            self.send_email('Welcome to %s!'%(SLACK_TEAM['name']), 'approved.eml', user=self)
            flash("Application from %s approved!"%(self.email))

class Member(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    created = db.Column(db.DateTime)
    active = db.Column(db.Boolean)
    slack_id = db.Column(db.String)
    slack_access_token = db.Column(db.String)
    slack_team = db.Column(db.String)
    display_name = db.Column(db.String)
    application_id = db.Column(db.Integer, db.ForeignKey('application.id'))
    application = db.relationship('Application', backref=db.backref('member',
        lazy='dynamic'))

    @property
    def is_authenticated(self):
        return len(self.slack_id) != 0

    @property
    def is_active(self):
        return self.active

    @property
    def is_anonymous(self):
        return len(self.slack_id) == 0
    def get_id(self):
        return unicode(self.id)

@app.route('/', methods=['GET'])
def index():
    return render_template('index.html')

@app.route('/', methods=['POST'])
def save():
    newApp = Application(
            email = request.form['email'],
            name = request.form['name'],
            reason = request.form['reason'])
    newApp.process()
    db.session.add(newApp)
    db.session.commit()
    return render_template('applied.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))

@app.route('/oauth')
def oauth_authorized():
    login_code = request.args.get('code', None)
    if login_code is None:
        flash('You denied the request to login')
        return redirect(url_for('index'))
    resp = Slacker.oauth.access(app.config['SLACK_KEY'], app.config['SLACK_SECRET'], login_code).body
    slacker = Slacker(resp['access_token'])
    login_response = slacker.api.get('users.identity').body
    if login_response['team']['id'] != SLACK_TEAM['id']:
        flash('You did not login with the %s slack team.'%(SLACK_TEAM['name']))
        return redirect(url_for('index'))
    slack_id = login_response['user']['id']
    user = Member.query.filter(Member.slack_id==slack_id).first()
    if not user:
	print "Creating first-time login for user"
        user = Member()
        user.active = True
        user.slack_id = slack_id
        user.display_name = login_response['user']['name']
        db.session.add(user)
    else:
        user.display_name = login_response['user']['name']
    user.slack_access_token = resp['access_token']
    user.slack_team = login_response['team']['id']
    db.session.commit()
    login_user(user)
    return redirect(url_for('applications'))

@app.route('/applications', methods=['GET'])
@app.route('/applications/<state>', methods=['GET'])
@login_required
def applications(state=''):
    apps = Application.query.filter(Application.state == state)
    return render_template('applications.html', applications=apps)

@app.route('/applications', methods=['POST'])
@login_required
def process_application():
    app = Application.query.filter(Application.id==request.form['id']).first()
    if request.form['action'] == 'reject':
        app.state = Application.STATE_REJECTED
    else:
        app.state = Application.STATE_APPROVED
        newMember = Member()
        newMember.active = True
        newMember.application_id = app.id
        db.session.add(newMember)
    app.process()
    db.session.commit()
    return applications()

@app.cli.command()
def initdb():
    db.create_all()
    print "Databases created."

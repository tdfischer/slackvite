# Slackvite, the slack invite app

Slackvite is a slack app targeted at larger communitites. Past a certain number
of participants, it becomes a lot of manual labor for admins to invite new
people.

Configuration steps are roughly:

1. Create slack app
2. Configure slackvite with key/secret
3. Generate admin token
4. Configure slackvite with admin token

The following environment variables determine the configuration:

* ``CODE_OF_CONDUCT`` - A URL to your code of conduct
* ``DATABASE_URI`` - SQLAlchemy friendly database URI
* ``SLACK_KEY`` - Slack app access token
* ``SLACK_SECRET`` - Slack app secret token
* ``SLACK_ADMIN_TOKEN`` - Special admin token used for sending notifications
* ``SECRET_SESSION_KEY`` - Set to a random value. Used to secure login sessions.
* ``EMAIL_FROM`` - Emails to accepted users will come from here

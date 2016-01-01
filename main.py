#!/usr/bin/env python

"""
main.py -- Udacity conference server-side Python App Engine
    HTTP controller handlers for memcache & task queue access

$Id$

created by wesc on 2014 may 24

"""

__author__ = 'wesc+api@google.com (Wesley Chun)'

import webapp2
from google.appengine.api import app_identity
from google.appengine.api import mail
from conference import ConferenceApi
from models import Session
from google.appengine.ext import ndb

class SetAnnouncementHandler(webapp2.RequestHandler):
    def get(self):
        """Set Announcement in Memcache."""
        ConferenceApi._cacheAnnouncement()
        self.response.set_status(204)


class SendConfirmationEmailHandler(webapp2.RequestHandler):
    def post(self):
        """Send email confirming Conference creation."""
        mail.send_mail(
            'noreply@%s.appspotmail.com' % (
                app_identity.get_application_id()),     # from
            self.request.get('email'),                  # to
            'You created a new Conference!',            # subj
            'Hi, you have created a following '         # body
            'conference:\r\n\r\n%s' % self.request.get(
                'conferenceInfo')
        )


class DetermineFeaturedSpeakerHandler(webapp2.RequestHandler):
    def post(self):
        """Determine if speaker is featured and set in Memcache"""
        # Create a list of featured speakers.
        # Assume that speaker names are unique
        # otherwise would have to introduce a speaker key
        featuredSpeakers = []
        wsck = self.request.get('websafeConferenceKey')
        speakerName = self.request.get('speaker')
        # Count how many times a speaker is assigned to sessions in a particular conference
        speakerCount = Session.query(ancestor=ndb.Key(urlsafe=wsck)).filter(Session.speaker == speakerName).count()
        # Speaker is featured if there is more than one session by speaker in conference
        if speakerCount > 1:
            featuredSpeakers.append(speakerName)
        # Set announcement for featured speakers in memcache
        ConferenceApi._cacheSpeakerAnnouncement(featuredSpeakers)
        self.response.set_status(204)


app = webapp2.WSGIApplication([
    ('/crons/set_announcement', SetAnnouncementHandler),
    ('/tasks/send_confirmation_email', SendConfirmationEmailHandler),
    ('/tasks/determine_featured_speaker', DetermineFeaturedSpeakerHandler),
], debug=True)

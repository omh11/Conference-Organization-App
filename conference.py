#!/usr/bin/env python

"""
conference.py -- Udacity conference server-side Python App Engine API;
    uses Google Cloud Endpoints

$Id: conference.py,v 1.25 2014/05/24 23:42:19 wesc Exp wesc $

created by wesc on 2014 apr 21

"""

__author__ = 'wesc+api@google.com (Wesley Chun)'


from datetime import datetime
from datetime import date
from datetime import time

import endpoints
from protorpc import messages
from protorpc import message_types
from protorpc import remote

from google.appengine.api import memcache
from google.appengine.api import taskqueue
from google.appengine.ext import ndb

from models import ConflictException
from models import Profile
from models import ProfileMiniForm
from models import ProfileForm
from models import StringMessage
from models import BooleanMessage
from models import Conference
from models import ConferenceForm
from models import ConferenceForms
from models import ConferenceQueryForm
from models import ConferenceQueryForms
from models import TeeShirtSize
from models import Session
from models import SessionForm
from models import SessionForms

from settings import WEB_CLIENT_ID
from settings import ANDROID_CLIENT_ID
from settings import IOS_CLIENT_ID
from settings import ANDROID_AUDIENCE

from utils import getUserId

EMAIL_SCOPE = endpoints.EMAIL_SCOPE
API_EXPLORER_CLIENT_ID = endpoints.API_EXPLORER_CLIENT_ID
MEMCACHE_ANNOUNCEMENTS_KEY = "RECENT_ANNOUNCEMENTS"
ANNOUNCEMENT_TPL = ('Last chance to attend! The following conferences '
                    'are nearly sold out: %s')
MEMCACHE_SPEAKER_ANNOUNCEMENTS_KEY = "SPEAKER_ANNOUNCEMENTS"
SPEAKER_ANNOUNCEMENT_TPL = ('Featured Speaker(s) are: %s')
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -

DEFAULTS = {
    "city": "Default City",
    "maxAttendees": 0,
    "seatsAvailable": 0,
    "topics": [ "Default", "Topic" ],
}

SESSION_DEFAULTS = {
    "speaker": "Default Speaker",
    "highlights": [ "Default", "Highlight" ],
}


OPERATORS = {
            'EQ':   '=',
            'GT':   '>',
            'GTEQ': '>=',
            'LT':   '<',
            'LTEQ': '<=',
            'NE':   '!='
            }

FIELDS =    {
            'CITY': 'city',
            'TOPIC': 'topics',
            'MONTH': 'month',
            'MAX_ATTENDEES': 'maxAttendees',
            }

CONF_GET_REQUEST = endpoints.ResourceContainer(
    message_types.VoidMessage,
    websafeConferenceKey=messages.StringField(1),
)

CONF_POST_REQUEST = endpoints.ResourceContainer(
    ConferenceForm,
    websafeConferenceKey=messages.StringField(1),
)


SESS_GET_REQUEST = endpoints.ResourceContainer(
    message_types.VoidMessage,
    SessionKey=messages.StringField(1),
)

SESS_POST_REQUEST = endpoints.ResourceContainer(
    SessionForm,
    websafeConferenceKey=messages.StringField(1),
)

SESS_TYPE_POST_REQUEST = endpoints.ResourceContainer(
    SessionForm,
    websafeConferenceKey=messages.StringField(1),
    typeOfSession=messages.StringField(2),
)

SESS_SPEAKER_POST_REQUEST = endpoints.ResourceContainer(
    SessionForm,
    speaker=messages.StringField(1),
)

# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -


@endpoints.api(name='conference', version='v1', audiences=[ANDROID_AUDIENCE],
    allowed_client_ids=[WEB_CLIENT_ID, API_EXPLORER_CLIENT_ID, ANDROID_CLIENT_ID, IOS_CLIENT_ID],
    scopes=[EMAIL_SCOPE])
class ConferenceApi(remote.Service):
    """Conference API v0.1"""

# - - - Conference objects - - - - - - - - - - - - - - - - -

    def _copyConferenceToForm(self, conf, displayName):
        """Copy relevant fields from Conference to ConferenceForm."""
        cf = ConferenceForm()
        for field in cf.all_fields():
            if hasattr(conf, field.name):
                # convert Date to date string; just copy others
                if field.name.endswith('Date'):
                    setattr(cf, field.name, str(getattr(conf, field.name)))
                else:
                    setattr(cf, field.name, getattr(conf, field.name))
            elif field.name == "websafeKey":
                setattr(cf, field.name, conf.key.urlsafe())
        if displayName:
            setattr(cf, 'organizerDisplayName', displayName)
        cf.check_initialized()
        return cf


    def _createConferenceObject(self, request):
        """Create or update Conference object, returning ConferenceForm/request."""
        # preload necessary data items
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')
        user_id = getUserId(user)

        if not request.name:
            raise endpoints.BadRequestException("Conference 'name' field required")

        # copy ConferenceForm/ProtoRPC Message into dict
        data = {field.name: getattr(request, field.name) for field in request.all_fields()}
        del data['websafeKey']
        del data['organizerDisplayName']

        # add default values for those missing (both data model & outbound Message)
        for df in DEFAULTS:
            if data[df] in (None, []):
                data[df] = DEFAULTS[df]
                setattr(request, df, DEFAULTS[df])

        # convert dates from strings to Date objects; set month based on start_date
        if data['startDate']:
            data['startDate'] = datetime.strptime(data['startDate'][:10], "%Y-%m-%d").date()
            data['month'] = data['startDate'].month
        else:
            data['month'] = 0
        if data['endDate']:
            data['endDate'] = datetime.strptime(data['endDate'][:10], "%Y-%m-%d").date()

        # set seatsAvailable to be same as maxAttendees on creation
        if data["maxAttendees"] > 0:
            data["seatsAvailable"] = data["maxAttendees"]
        # generate Profile Key based on user ID and Conference
        # ID based on Profile key get Conference key from ID
        p_key = ndb.Key(Profile, user_id)
        c_id = Conference.allocate_ids(size=1, parent=p_key)[0]
        c_key = ndb.Key(Conference, c_id, parent=p_key)
        data['key'] = c_key
        data['organizerUserId'] = request.organizerUserId = user_id

        # create Conference, send email to organizer confirming
        # creation of Conference & return (modified) ConferenceForm
        Conference(**data).put()
        taskqueue.add(params={'email': user.email(),
            'conferenceInfo': repr(request)},
            url='/tasks/send_confirmation_email'
        )
        return request


    @ndb.transactional()
    def _updateConferenceObject(self, request):
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')
        user_id = getUserId(user)

        # copy ConferenceForm/ProtoRPC Message into dict
        data = {field.name: getattr(request, field.name) for field in request.all_fields()}

        # update existing conference
        conf = ndb.Key(urlsafe=request.websafeConferenceKey).get()
        # check that conference exists
        if not conf:
            raise endpoints.NotFoundException(
                'No conference found with key: %s' % request.websafeConferenceKey)

        # check that user is owner
        if user_id != conf.organizerUserId:
            raise endpoints.ForbiddenException(
                'Only the owner can update the conference.')

        # Not getting all the fields, so don't create a new object; just
        # copy relevant fields from ConferenceForm to Conference object
        for field in request.all_fields():
            data = getattr(request, field.name)
            # only copy fields where we get data
            if data not in (None, []):
                # special handling for dates (convert string to Date)
                if field.name in ('startDate', 'endDate'):
                    data = datetime.strptime(data, "%Y-%m-%d").date()
                    if field.name == 'startDate':
                        conf.month = data.month
                # write to Conference object
                setattr(conf, field.name, data)
        conf.put()
        prof = ndb.Key(Profile, user_id).get()
        return self._copyConferenceToForm(conf, getattr(prof, 'displayName'))


    @endpoints.method(ConferenceForm, ConferenceForm, path='conference',
            http_method='POST', name='createConference')
    def createConference(self, request):
        """Create new conference."""
        return self._createConferenceObject(request)


    @endpoints.method(CONF_POST_REQUEST, ConferenceForm,
            path='conference/{websafeConferenceKey}',
            http_method='PUT', name='updateConference')
    def updateConference(self, request):
        """Update conference w/provided fields & return w/updated info."""
        return self._updateConferenceObject(request)


    @endpoints.method(CONF_GET_REQUEST, ConferenceForm,
            path='conference/{websafeConferenceKey}',
            http_method='GET', name='getConference')
    def getConference(self, request):
        """Return requested conference (by websafeConferenceKey)."""
        # get Conference object from request; bail if not found
        conf = ndb.Key(urlsafe=request.websafeConferenceKey).get()
        if not conf:
            raise endpoints.NotFoundException(
                'No conference found with key: %s' % request.websafeConferenceKey)
        prof = conf.key.parent().get()
        # return ConferenceForm
        return self._copyConferenceToForm(conf, getattr(prof, 'displayName'))


    @endpoints.method(message_types.VoidMessage, ConferenceForms,
            path='getConferencesCreated',
            http_method='POST', name='getConferencesCreated')
    def getConferencesCreated(self, request):
        """Return conferences created by user."""
        # make sure user is authed
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')
        user_id = getUserId(user)

        # create ancestor query for all key matches for this user
        confs = Conference.query(ancestor=ndb.Key(Profile, user_id))
        prof = ndb.Key(Profile, user_id).get()
        # return set of ConferenceForm objects per Conference
        return ConferenceForms(
            items=[self._copyConferenceToForm(conf, getattr(prof, 'displayName')) for conf in confs]
        )


    def _getQuery(self, request):
        """Return formatted query from the submitted filters."""
        q = Conference.query()
        inequality_filter, filters = self._formatFilters(request.filters)

        # If exists, sort on inequality filter first
        if not inequality_filter:
            q = q.order(Conference.name)
        else:
            q = q.order(ndb.GenericProperty(inequality_filter))
            q = q.order(Conference.name)

        for filtr in filters:
            if filtr["field"] in ["month", "maxAttendees"]:
                filtr["value"] = int(filtr["value"])
            formatted_query = ndb.query.FilterNode(filtr["field"], filtr["operator"], filtr["value"])
            q = q.filter(formatted_query)
        return q


    def _formatFilters(self, filters):
        """Parse, check validity and format user supplied filters."""
        formatted_filters = []
        inequality_field = None

        for f in filters:
            filtr = {field.name: getattr(f, field.name) for field in f.all_fields()}

            try:
                filtr["field"] = FIELDS[filtr["field"]]
                filtr["operator"] = OPERATORS[filtr["operator"]]
            except KeyError:
                raise endpoints.BadRequestException("Filter contains invalid field or operator.")

            # Every operation except "=" is an inequality
            if filtr["operator"] != "=":
                # check if inequality operation has been used in previous filters
                # disallow the filter if inequality was performed on a different field before
                # track the field on which the inequality operation is performed
                if inequality_field and inequality_field != filtr["field"]:
                    raise endpoints.BadRequestException("Inequality filter is allowed on only one field.")
                else:
                    inequality_field = filtr["field"]

            formatted_filters.append(filtr)
        return (inequality_field, formatted_filters)


    @endpoints.method(ConferenceQueryForms, ConferenceForms,
            path='queryConferences',
            http_method='POST',
            name='queryConferences')
    def queryConferences(self, request):
        """Query for conferences."""
        conferences = self._getQuery(request)

        # need to fetch organiser displayName from profiles
        # get all keys and use get_multi for speed
        organisers = [(ndb.Key(Profile, conf.organizerUserId)) for conf in conferences]
        profiles = ndb.get_multi(organisers)

        # put display names in a dict for easier fetching
        names = {}
        for profile in profiles:
            names[profile.key.id()] = profile.displayName

        # return individual ConferenceForm object per Conference
        return ConferenceForms(
                items=[self._copyConferenceToForm(conf, names[conf.organizerUserId]) for conf in \
                conferences]
        )


# - - - Profile objects - - - - - - - - - - - - - - - - - - -

    def _copyProfileToForm(self, prof):
        """Copy relevant fields from Profile to ProfileForm."""
        # copy relevant fields from Profile to ProfileForm
        pf = ProfileForm()
        for field in pf.all_fields():
            if hasattr(prof, field.name):
                # convert t-shirt string to Enum; just copy others
                if field.name == 'teeShirtSize':
                    setattr(pf, field.name, getattr(TeeShirtSize, getattr(prof, field.name)))
                else:
                    setattr(pf, field.name, getattr(prof, field.name))
        pf.check_initialized()
        return pf


    def _getProfileFromUser(self):
        """Return user Profile from datastore, creating new one if non-existent."""
        # make sure user is authed
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')

        # get Profile from datastore
        user_id = getUserId(user)
        p_key = ndb.Key(Profile, user_id)
        profile = p_key.get()
        # create new Profile if not there
        if not profile:
            profile = Profile(
                key = p_key,
                displayName = user.nickname(),
                mainEmail= user.email(),
                teeShirtSize = str(TeeShirtSize.NOT_SPECIFIED),
            )
            profile.put()

        return profile      # return Profile


    def _doProfile(self, save_request=None):
        """Get user Profile and return to user, possibly updating it first."""
        # get user Profile
        prof = self._getProfileFromUser()

        # if saveProfile(), process user-modifyable fields
        if save_request:
            for field in ('displayName', 'teeShirtSize'):
                if hasattr(save_request, field):
                    val = getattr(save_request, field)
                    if val:
                        setattr(prof, field, str(val))
                        #if field == 'teeShirtSize':
                        #    setattr(prof, field, str(val).upper())
                        #else:
                        #    setattr(prof, field, val)
                        prof.put()

        # return ProfileForm
        return self._copyProfileToForm(prof)


    @endpoints.method(message_types.VoidMessage, ProfileForm,
            path='profile', http_method='GET', name='getProfile')
    def getProfile(self, request):
        """Return user profile."""
        return self._doProfile()


    @endpoints.method(ProfileMiniForm, ProfileForm,
            path='profile', http_method='POST', name='saveProfile')
    def saveProfile(self, request):
        """Update & return user profile."""
        return self._doProfile(request)


# - - - Announcements - - - - - - - - - - - - - - - - - - - -

    @staticmethod
    def _cacheAnnouncement():
        """Create Announcement & assign to memcache; used by
        memcache cron job & putAnnouncement().
        """
        confs = Conference.query(ndb.AND(
            Conference.seatsAvailable <= 5,
            Conference.seatsAvailable > 0)
        ).fetch(projection=[Conference.name])

        if confs:
            # If there are almost sold out conferences,
            # format announcement and set it in memcache
            announcement = ANNOUNCEMENT_TPL % (
                ', '.join(conf.name for conf in confs))
            memcache.set(MEMCACHE_ANNOUNCEMENTS_KEY, announcement)
        else:
            # If there are no sold out conferences,
            # delete the memcache announcements entry
            announcement = ""
            memcache.delete(MEMCACHE_ANNOUNCEMENTS_KEY)

        return announcement


    @endpoints.method(message_types.VoidMessage, StringMessage,
            path='conference/announcement/get',
            http_method='GET', name='getAnnouncement')
    def getAnnouncement(self, request):
        """Return Announcement from memcache."""
        return StringMessage(data=memcache.get(MEMCACHE_ANNOUNCEMENTS_KEY) or "")


# - - - Registration - - - - - - - - - - - - - - - - - - - -

    @ndb.transactional(xg=True)
    def _conferenceRegistration(self, request, reg=True):
        """Register or unregister user for selected conference."""
        retval = None
        prof = self._getProfileFromUser() # get user Profile

        # check if conf exists given websafeConfKey
        # get conference; check that it exists
        wsck = request.websafeConferenceKey
        conf = ndb.Key(urlsafe=wsck).get()
        if not conf:
            raise endpoints.NotFoundException(
                'No conference found with key: %s' % wsck)

        # register
        if reg:
            # check if user already registered otherwise add
            if wsck in prof.conferenceKeysToAttend:
                raise ConflictException(
                    "You have already registered for this conference")

            # check if seats avail
            if conf.seatsAvailable <= 0:
                raise ConflictException(
                    "There are no seats available.")

            # register user, take away one seat
            prof.conferenceKeysToAttend.append(wsck)
            conf.seatsAvailable -= 1
            retval = True

        # unregister
        else:
            # check if user already registered
            if wsck in prof.conferenceKeysToAttend:

                # unregister user, add back one seat
                prof.conferenceKeysToAttend.remove(wsck)
                conf.seatsAvailable += 1
                retval = True
            else:
                retval = False

        # write things back to the datastore & return
        prof.put()
        conf.put()
        return BooleanMessage(data=retval)


    @endpoints.method(message_types.VoidMessage, ConferenceForms,
            path='conferences/attending',
            http_method='GET', name='getConferencesToAttend')
    def getConferencesToAttend(self, request):
        """Get list of conferences that user has registered for."""
        prof = self._getProfileFromUser() # get user Profile
        conf_keys = [ndb.Key(urlsafe=wsck) for wsck in prof.conferenceKeysToAttend]
        conferences = ndb.get_multi(conf_keys)

        # get organizers
        organisers = [ndb.Key(Profile, conf.organizerUserId) for conf in conferences]
        profiles = ndb.get_multi(organisers)

        # put display names in a dict for easier fetching
        names = {}
        for profile in profiles:
            names[profile.key.id()] = profile.displayName

        # return set of ConferenceForm objects per Conference
        return ConferenceForms(items=[self._copyConferenceToForm(conf, names[conf.organizerUserId])\
         for conf in conferences]
        )


    @endpoints.method(CONF_GET_REQUEST, BooleanMessage,
            path='conference/{websafeConferenceKey}',
            http_method='POST', name='registerForConference')
    def registerForConference(self, request):
        """Register user for selected conference."""
        return self._conferenceRegistration(request)


    @endpoints.method(CONF_GET_REQUEST, BooleanMessage,
            path='conference/{websafeConferenceKey}',
            http_method='DELETE', name='unregisterFromConference')
    def unregisterFromConference(self, request):
        """Unregister user for selected conference."""
        return self._conferenceRegistration(request, reg=False)


    @endpoints.method(message_types.VoidMessage, ConferenceForms,
            path='filterPlayground',
            http_method='GET', name='filterPlayground')
    def filterPlayground(self, request):
        """Filter Playground"""
        q = Conference.query()
        # field = "city"
        # operator = "="
        # value = "London"
        # f = ndb.query.FilterNode(field, operator, value)
        # q = q.filter(f)
        q = q.filter(Conference.city=="London")
        q = q.filter(Conference.topics=="Medical Innovations")
        q = q.filter(Conference.month==6)

        return ConferenceForms(
            items=[self._copyConferenceToForm(conf, "") for conf in q]
        )

# - - - Session Additions - - - - - - - - - - - - - - - - - - -

    def _createSessionObject(self, request):
        """Create or update Session object, returning SessionForm/request."""
        # Check if user is authorized
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')
        user_id = getUserId(user)

        # Check if required Form fields have been filled
        if not request.name:
            raise endpoints.BadRequestException("Session 'name' field required")

        # Retrieve the conference Key and check if it exists
        websck = request.websafeConferenceKey
        conf = ndb.Key(urlsafe=websck).get()
        if not conf:
            raise endpoints.NotFoundException(
                'No conference found with key: %s' % websck)

        # Check that user is owner of conference
        if user_id != conf.organizerUserId:
            raise endpoints.ForbiddenException(
                'Only the owner can update the conference.')

        # Copy SessionForm/ProtoRPC Message into dict
        data = {field.name: getattr(request, field.name) for field in request.all_fields()}
        sess = self._copySessionToForm(request)
        del data['websafeConferenceKey']
        del data['websafeSessionKey']

        # Add default values for those missing (both data model & outbound Message)
        for df in SESSION_DEFAULTS:
            if data[df] in (None, []):
                data[df] = SESSION_DEFAULTS[df]
                setattr(request, df, SESSION_DEFAULTS[df])

        # Convert dates and times from strings to Date and Time objects; set month based on start_date
        if data['date']:
            data['date'] = datetime.strptime(data['date'][:10], "%Y-%m-%d").date()

        if data['duration']:
            data['duration'] = datetime.strptime(data['duration'][:5], "%H:%M").time()

        if data['startTime']:
            data['startTime'] = datetime.strptime(data['startTime'][:5], "%H:%M").time()


        # Generate Session Key from obtained Conference key
        s_id = Session.allocate_ids(size=1, parent=ndb.Key(urlsafe=request.websafeConferenceKey))[0]
        s_key = ndb.Key(Session, s_id, parent=ndb.Key(urlsafe=request.websafeConferenceKey))
        data['key'] = s_key

        # Create Session 
        Session(**data).put()

        # Add to task queue parameters needed to determine featured speaker
        taskqueue.add(params={'speaker': data['speaker'], 'websafeConferenceKey': websck},
            url='/tasks/determine_featured_speaker'
        )

        # Return (modified) SessionForm
        return sess

    def _copySessionToForm(self, sess):
        """Copy relevant fields from Conference to ConferenceForm."""
        se = SessionForm()
        for field in se.all_fields():
            if hasattr(sess, field.name):
                # Convert date, time and duration to strings; just copy others
                if field.name.endswith('date'):
                    setattr(se, field.name, str(getattr(sess, field.name)))
                elif field.name.endswith('Time'):
                    setattr(se, field.name, str(getattr(sess, field.name)))
                elif field.name.endswith('duration'):
                    setattr(se, field.name, str(getattr(sess, field.name)))
                else:
                    setattr(se, field.name, getattr(sess, field.name))
            # Copy over the keys
            elif field.name == "websafeConferenceKey":
                setattr(se, field.name, sess.key.parent().urlsafe())
            elif field.name == "websafeSessionKey":
                setattr(se, field.name, sess.key.urlsafe())
        se.check_initialized()
        return se


    @endpoints.method(SESS_POST_REQUEST, SessionForm, path='conference/session/{websafeConferenceKey}',
            http_method='POST', name='createSession')
    def createSession(self, request):
        """Create new session."""
        return self._createSessionObject(request)

    @endpoints.method(SESS_POST_REQUEST, SessionForms,
            path='conference/session/getConferenceSessions/{websafeConferenceKey}',
            http_method='POST', name='getConferenceSessions')
    def getConferenceSessions(self, request):
        """Return conference sessions."""
        # Create ancestor query for all key matches for the conference key
        allSessions = Session.query(ancestor=ndb.Key(urlsafe=request.websafeConferenceKey)).fetch()
        # Return set of SessionForm objects per Session
        return SessionForms(
            items=[self._copySessionToForm(sess) for sess in allSessions]
        )

    @endpoints.method(SESS_TYPE_POST_REQUEST, SessionForms,
            path='conference/session/getConferenceSessionsByType/{websafeConferenceKey}/{typeOfSession}',
            http_method='POST', name='getConferenceSessionsByType')
    def getConferenceSessionsByType(self, request):
        """Return conference sessions by type."""
        # Create ancestor query for all key matches for the conference key
        allSessions = Session.query(ancestor=ndb.Key(urlsafe=request.websafeConferenceKey)).fetch()
        # Iterate through returned query to find all sessions of the same type
        sessionTypeQuery=[]
        for i in allSessions:
            if i.typeOfSession == request.typeOfSession:
                sessionTypeQuery.append(i)
        # Return set of SessionForm objects per Session
        return SessionForms(
            items=[self._copySessionToForm(sess) for sess in sessionTypeQuery]
        )


    @endpoints.method(SESS_SPEAKER_POST_REQUEST, SessionForms,
            path='conference/session/getSessionsBySpeaker/{speaker}',
            http_method='POST', name='getSessionsBySpeaker')
    def getSessionsBySpeaker(self, request):
        """Return all sessions given by speaker, across all conferences."""
        # Create query for all sessions across all conferences
        allSessions = Session.query().fetch()
        # Iterate through returned query to match all sessions of the requested type
        sessionSpeakerQuery=[]
        for i in allSessions:
            if i.speaker == request.speaker:
                sessionSpeakerQuery.append(i)
        # Return set of SessionForm objects per Session
        return SessionForms(
            items=[self._copySessionToForm(sess) for sess in sessionSpeakerQuery]
        )


    @endpoints.method(SESS_GET_REQUEST, BooleanMessage,
            path='conference/session/addSessionToWishlist/{SessionKey}',
            http_method='POST', name='addSessionToWishlist')
    def addSessionToWishlist(self, request):
        """Add session to user wishlist."""
        return self._sessionWishlistAdd(request)


    def _sessionWishlistAdd(self, request):
        """Add session to wishlist for selected session."""
        # Get user Profile
        prof = self._getProfileFromUser()
        # Check if session exists given conference key
        sck = request.SessionKey
        sess = ndb.Key(urlsafe=sck).get()
        if not sess:
            raise endpoints.NotFoundException(
                'No session found with key: %s' % sck)

        # Check if user already has session in wishlist
        if sck in prof.sessionWishListKeys:
            raise ConflictException(
                "You have already added this session to your wishlist")
        # Add session to wish list
        prof.sessionWishListKeys.append(sck)
        # Write things back to the datastore & return
        prof.put()
        return BooleanMessage(data=True)

    @endpoints.method(message_types.VoidMessage, SessionForms,
            path='conferences/session/wishlist',
            http_method='GET', name='getSessionsInWishlist')
    def getSessionsInWishlist(self, request):
        """Get list of sessions that user has interested in."""
        # Get user Profile
        prof = self._getProfileFromUser()
        # Remove any empty values in array to protect from type value error
        prof.sessionWishListKeys = filter(None, prof.sessionWishListKeys)
        # Retrieve wishlist session keys
        sess_keys = [ndb.Key(urlsafe=wsck) for wsck in prof.sessionWishListKeys]
        # Get sessions
        sessions = ndb.get_multi(sess_keys)
        # Return set of SessionForm objects per Session
        return SessionForms(
            items=[self._copySessionToForm(sess) for sess in sessions]
        )

    @endpoints.method(SESS_GET_REQUEST, BooleanMessage,
            path='conferences/session/wishlist/deleteSessionInWishlist/{SessionKey}',
            http_method='DELETE', name='deleteSessionInWishlist')
    def deleteSessionInWishlist(self, request):
        """Get list of sessions that user has interested in."""
        # Get user Profile
        prof = self._getProfileFromUser()
        # Get session key
        wsck = request.SessionKey
        # Remove any empty values in array to protect from type value error
        if wsck in prof.sessionWishListKeys:
            prof.sessionWishListKeys.remove(wsck)
        # Write update back to datastore and return
        prof.put()
        return BooleanMessage(data=True)


    @staticmethod
    def _cacheSpeakerAnnouncement(speakers):
        """Create Speaker Announcement & assign to memcache."""
        if speakers:
            # If there are featured speakers,
            # format announcement and set it in memcache
            speakerAnnouncement = SPEAKER_ANNOUNCEMENT_TPL % (
                ', '.join(speaker for speaker in speakers))
            memcache.set(MEMCACHE_SPEAKER_ANNOUNCEMENTS_KEY, speakerAnnouncement)
        else:
            # If there are no featured speakers,
            # delete the memcache announcements entry
            speakerAnnouncement = ""
            memcache.delete(MEMCACHE_SPEAKER_ANNOUNCEMENTS_KEY)
        return speakerAnnouncement


    @endpoints.method(message_types.VoidMessage, StringMessage,
            path='conference/session/announcement/get',
            http_method='GET', name='getFeaturedSpeaker')
    def getFeaturedSpeaker(self, request):
        """Return Announcement from memcache."""
        return StringMessage(data=memcache.get(MEMCACHE_SPEAKER_ANNOUNCEMENTS_KEY))


    @endpoints.method(message_types.VoidMessage, SessionForms,
            path='conference/session/firstQuery',
            http_method='GET', name='firstQuery')
    def firstQuery(self, request):
        """Query that retrieves sessions on a certain date & after a certain start time"""
        q=Session.query()
        q=q.filter(Session.date==date(2015,3,15))
        q=q.filter(Session.startTime>time(15, 0, 0, tzinfo=None))
        q=q.fetch()
        return SessionForms(
            items=[self._copySessionToForm(sess) for sess in q]
            )

    @endpoints.method(message_types.VoidMessage, SessionForms,
            path='conference/session/secondQuery',
            http_method='GET', name='secondQuery')
    def secondQuery(self, request):
        """Query that retrieves sessions on a certain date, after a certain time & with a certain type."""
        q=Session.query()
        q=q.filter(Session.date==date(2015,3,15)) 
        q=q.filter(Session.typeOfSession=="workshop") 
        q=q.filter(Session.startTime>time(15, 0, 0, tzinfo=None)) 
        q=q.fetch()
        return SessionForms(
            items=[self._copySessionToForm(sess) for sess in q]
            )

    @endpoints.method(message_types.VoidMessage, SessionForms,
            path='conference/session/challengeQuery',
            http_method='GET', name='challengeQuery')
    def challengeQuery(self, request):
        """Query challenge for retrieving two inequalities"""
        # Query counting the number of sessions that are before 7PM
        cntq=Session.query()
        cntq=cntq.filter(Session.startTime<time(19, 0, 0, tzinfo=None))
        cntq=cntq.count()
    
        # Query retrieving all sessions that are not workshops 
        # ordered by start time and 
        # then fetching the results based on count query
        if cntq:
            q=Session.query()
            q=q.filter(Session.typeOfSession!="workshop")
            q=q.order(Session.typeOfSession)
            q=q.order(Session.startTime)
            q=q.fetch(cntq)
        else:
            q=[]
        return SessionForms(
            items=[self._copySessionToForm(sess) for sess in q]
            )

api = endpoints.api_server([ConferenceApi]) # register API
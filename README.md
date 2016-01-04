App Engine application for the Udacity training course.

## Products
- [App Engine][1]

## Language
- [Python][2]

## APIs
- [Google Cloud Endpoints][3]

## Setup Instructions
1. Update the value of `application` in `app.yaml` to the app ID you
   have registered in the App Engine admin console and would like to use to host
   your instance of this sample.
1. Update the values at the top of `settings.py` to
   reflect the respective client IDs you have registered in the
   [Developer Console][4].
1. Update the value of CLIENT_ID in `static/js/app.js` to the Web client ID
1. (Optional) Mark the configuration files as unchanged as follows:
   `$ git update-index --assume-unchanged app.yaml settings.py static/js/app.js`
1. Run the app with the devserver using `dev_appserver.py DIR`, and ensure it's running by visiting your local server's address (by default [localhost:8080][5].)
1. (Optional) Generate your client library(ies) with [the endpoints tool][6].
1. Deploy your application.

## Design Choices for Session and Speaker Implementations

The Conference datastore model has an ancestor relationship with the Session datastore model. This is because every conference can have multiple sessions. As a result, every session created has its own unique key. Also the session wishlist is maintained in the user Profile model. This is because the wishlist is tied to the logged in user. The session wishlist is comprised of an array of session keys.

Speaker names are also contained in the session model and are assumed to be unique. Therefore, in this code the speaker names are used as a key to determine the featured speaker. In reality, however, the names of speakers may not be unique and a key would need to be generated for every speaker most likely in a seperate model.

The Session data model uses a *StringProperty* variable type for variable names *name*, *highlights*, *speaker*, and *typeOfSession* since they are expected to be text inputs. The name variable is always required since all sessions are required to have a name. The *highlight* variable name is set to *repeated* because a session could have more than one highlight. The *duration* and *startTime* variable names both have a *TimeProperty* since they require time inputs. Finally, the date variable is a *DateProperty* since it requires a date input. The session and conference keys are captured in the *SessionForm* only so that they can be passed back through messages to the application.

## Query related problem design Choices

The query related problem is implemented in the *challengeQuery* endpoint. The problem falls in the restriction that a query cannot contain two inequality conditions for the same property. The workaround is handled running a query that filters out all sessions after 7pm. The result of the query is then iterated through to find all non-workshop sessions.

The endpoint *sessionQueryByDateStartTime* allows the user to enter a session date and start time. The endpoint then returns a query resulting with all sessions across all conferences that are on a specific date and start after a certain time. The endpoint function definition basically performs a query that filters based on the date and start time.

The endpoint *sessionQueryByDateStartTimeType* allows the user to enter a session date, start time, and type. The endpoint then returns a query resulting with all sessions across all conferences that have a specific type, are on a specific date, and start after a certain time. The endpoint function definition basically performs a query that filters based on the date, type, and start time.


[1]: https://developers.google.com/appengine
[2]: http://python.org
[3]: https://developers.google.com/appengine/docs/python/endpoints/
[4]: https://console.developers.google.com/
[5]: https://localhost:8080/
[6]: https://developers.google.com/appengine/docs/python/endpoints/endpoints_tool

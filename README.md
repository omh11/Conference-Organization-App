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

Speaker names are also contained in the session model and are assumed to be unique. Therefore, in this code the speaker names are used as a key to determine the featured speaker. In reality, however, the names of speakers may not be unique and a key would need to be generated for every speaker most likely in a seperate model   

## Query related problem design Choices

The query related problem is implemented in the *challengeQuery* endpoint. The problem falls in the restriction that a query cannot contain two inequality conditions. The workaround is handled running two queries. The first query, counts the number of sessions that occur before 7pm. The second query retrieves all sessions that are not workshops and is ordered by start time. Then the number of items fetched from the second query is dependent on the first query. Since the number of sessions before 7pm is known and the second query is ordered by start time, then the sessions that are before 7pm and are not workshops can be obtained.

[1]: https://developers.google.com/appengine
[2]: http://python.org
[3]: https://developers.google.com/appengine/docs/python/endpoints/
[4]: https://console.developers.google.com/
[5]: https://localhost:8080/
[6]: https://developers.google.com/appengine/docs/python/endpoints/endpoints_tool

Server API Event Callback
Event callback enables your app to receive event notifications from SeaTalk when an enabled event has happened. With event callback, your app can integrate with SeaTalk Open Platform’s various open capabilities to respond to different actions in real-time. For example, a bot can greet a user in a 1-on-1 chat right after receiving the Message Received From Bot User event notification.

To enable event callback for your app, you just need to configure a callback URL. SeaTalk Open Platform will push event notifications to your app in the JSON format using an HTTP POST request.

Once event callback is enabled for your app, your app can listen to different events from SeaTalk. You can refer to a sample code in the last section of this documentation for an example of how to handle different callback events.

Callback URL Verification
To successfully configure a callback URL for your app, the URL must pass a verification test from SeaTalk. See the diagram below for how the callback URL verification works:

 



When you click to save a callback URL on the app’s configuration page, the verification test is triggered.
SeaTalk will send an HTTP POST request to this URL with a parameter called "seatalk_challenge".
After receiving the request, your server must respond with HTTP Status Code 200 and include the value of the "seatalk_challenge" parameter as it is in the response body within 5 seconds. SeaTalk will retry a maximum of 3 times if no response is received.
If SeaTalk receives the valid response within 5 seconds, the verification test is passed and the callback URL is successfully configured for your app.
However, if an error happens during the verification process, the verification test will fail and you need to retry. An error message will be shown on the URL configuration page so you know why the configuration has failed.
Verification Request JSON
The body of the HTTP POST request SeaTalk will send to your callback URL for verification is as follows (referring to the 2nd step):

{
    "event_id": "1098780",
    "event_type": "event_verification",
    "timestamp": 1611220944,
    "app_id": "NDYyMDU1MTY3NzQ1",
    "event": {
        "seatalk_challenge": "23j98gjbearh023hg"
    }
}

Copy
Return Response JSON
Upon receiving the verification request from SeaTalk, your server should return the following response (referring to the 3rd step):

{
    "seatalk_challenge": "23j98gjbearh023hg"
}

Copy
Possible Reasons for Verification Failure
The URL entered cannot be reached
The URL didn’t respond within 5 seconds (and after SeaTalk retries 3 times)
The response returned by the URL contains invalid information or is in a wrong format
A callback URL is currently being verified at the moment under this app
An internal error has occurred
You can refer to the sample code at the end of this documentation for an example of how to handle the callback URL verification test.

Enable Events
After a callback URL has successfully been configured for your app, your app now can listen to events and receive event notifications when one of the enabled events has happened.

Currently, all the available events will be automatically enabled for your app upon successful callback URL configuration.

Refer to List of Events for a comprehensive list of events supported.

Customisation of event enablement will be supported in the future and we will give updates here once it’s ready. Alternatively, you can reach out to us on SeaTalk. 

Respond to Events
After receiving the request, your server must respond with HTTP Status Code 200 within 5 seconds. SeaTalk will retry a maximum of 3 times if no response is received.

Configure Callback URL
Step 1: Go to SeaTalk Open Platform’s Developer Portal and enter the configuration page of the app that needs event callback capability.

Step 2: Click Event Callback on the left menu bar to enter the event callback configuration page:



 

Step 3: Click the Edit icon beside the URL text box to enter the URL for verification:



 

Step 4: Click Save to trigger the callback URL verification test:



 

Step 5: After successful URL verification, you will see the URL being configured and the Events section appear below.

Signing Secret
To ensure that the sender of an event notification is SeaTalk Open Platform, a signing secret is assigned to your app. You will see the signing secret under the callback URL text box and it can be reset anytime.

SeaTalk Open Platform will include a Signature field in the HTTP header of a callback request. When you need to verify the sender identity of an event notification after receiving it, follow these steps:

Join the whole body of the callback request and your app’s signing secret as the input of the SHA-256 function.
Encode the output (the hashed value) using standard base 16 and all lower case to calculate the signature.
Compare the calculated signature with the one inside the HTTP header of the callback request to verify the sender identity. If they are the same, this event notification is sent by SeaTalk Open Platform.
For example, if the signing secret is 1234567812345678 and your app receives an HTTP request like this:

POST / HTTP/1.1

Content-Type: application/json

Signature: 30c15f277e1d1847c4425ac4b3d7658457caf53da3005385db15a96ea1f2e0a4

{
    "event_id": "1098780",
    "event_type": "event_verification",
    "timestamp": 1611220944,
    "app_id": "NDYyMDU1MTY3NzQ1",
    "event": {
        "seatalk_challenge": "23j98gjbearh023hg"
    }
}

Copy
The input of the SHA-256 function will be:

{"event_id":"1098780","event_type":"event_verification","timestamp":1611220944,"app_id":"NDYyMDU1MTY3NzQ1","event":{"seatalk_challenge":"23j98gjbearh023hg"}}1234567812345678

Copy
And the signature calculated will be:

// hashlib.sha256(request.body + signing_secret).hexdigest()
48918b59a7a5976781578b78136c816592b2b5834d4348a272253f221e68377c

Copy
Since the calculated signature is the same as the one in the request header, you can confirm that the event notification was sent by SeaTalk Open Platform.

Sample Code
Below is a sample code of a bot's callback handler. The handler listens for events from SeaTalk, which include the callback URL verification event ("event_verification") and other bot-related events. The handler also verifies whether the event notification is indeed sent by SeaTalk.

```python
import hashlib
import json
from typing import Dict, Any

from flask import Flask, request

# settings
SIGNING_SECRET = b"xxxx"

# event list
# ref: https://open.seatalk.io/docs/list-of-events
EVENT_VERIFICATION = "event_verification"
NEW_BOT_SUBSCRIBER = "new_bot_subscriber"
MESSAGE_FROM_BOT_SUBSCRIBER = "message_from_bot_subscriber"
INTERACTIVE_MESSAGE_CLICK = "interactive_message_click"
BOT_ADDED_TO_GROUP_CHAT = "bot_added_to_group_chat"
BOT_REMOVED_FROM_GROUP_CHAT = "bot_removed_from_group_chat"
NEW_MENTIONED_MESSAGE_RECEIVED_FROM_GROUP_CHAT = "new_mentioned_message_received_from_group_chat"

app = Flask(__name__)


def is_valid_signature(signing_secret: bytes, body: bytes, signature: str) -> bool:
    # ref: https://open.seatalk.io/docs/server-apis-event-callback
    return hashlib.sha256(body + signing_secret).hexdigest() == signature


@app.route("/bot-callback", methods=["POST"])
def bot_callback_handler():
    body: bytes = request.get_data()
    signature: str = request.headers.get("signature")
    # 1. validate the signature
    if not is_valid_signature(SIGNING_SECRET, body, signature):
    return ""
    # 2. handle events
    data: Dict[str, Any] = json.loads(body)
    event_type: str = data.get("event_type", "")
    if event_type == EVENT_VERIFICATION:
    return data. Get("event")
    elif event_type == NEW_BOT_SUBSCRIBER:
    # fill with your own code
    pass
    elif event_type == MESSAGE_FROM_BOT_SUBSCRIBER:
    # fill with your own code
    pass
    elif event_type == INTERACTIVE_MESSAGE_CLICK:
    # fill with your own code
    pass
    elif event_type == BOT_ADDED_TO_GROUP_CHAT:
    # fill with your own code
    pass
    elif event_type == BOT_REMOVED_FROM_GROUP_CHAT:
    # fill with your own code
    pass
    elif event_type == NEW_MENTIONED_MESSAGE_RECEIVED_FROM_GROUP_CHAT:
    # fill with your own code
    pass
    else:
    pass
    return ""
```

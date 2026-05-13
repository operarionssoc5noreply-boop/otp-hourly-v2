Get App Access Token
API Description
Use this API to obtain access_token, which is used to authenticate the identity of the app that sends API requests. An access_token will be expired after 7200 seconds. Developers should maintain a cache mechanism to store and refresh the access_token to ensure API requests can be successfully sent. 

Note:

This API is limited to 600 requests per hour under one app ID.
Request Method: POST

End Point: https://openapi.seatalk.io/auth/app_access_token

Request Parameter
Header

Parameter

Type

Mandatory

Description

Default

Sample

Content-Type

string

Yes

Request head format

N/A

application/json

Body

Parameter

Type

Mandatory

Description

Default

Sample

app_id

string

Yes

The unique identifier of an app

N/A

123

app_secret

string

Yes

The credential of an app

N/A

V79JzZ0yasBAs69tQOD1

Request Sample

{
    "app_id": "123",
    "app_secret": "V79JzZ0yasBAs69tQOD1"
}

Copy
Response Parameter
Result Fields

Parameters

Type

Description

code

int

Refer to Error Code for explanations

app_access_token

string

The access token generated for the app

expire

int

The time stamp when the generated token will be expired

Response Sample

{
    "code": 0,
    "app_access_token": "c8bda0f77ef940c5bea9f23b2d7fc0d8",
    "expire": 1590581487
}

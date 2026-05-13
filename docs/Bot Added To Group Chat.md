Event: Bot Added To Group Chat
Event Description
When the event bot_added_to_group_chat is triggered, it means a user has added your bot to a group chat in SeaTalk. This event allows your bot to detect when it has been added to a new group and take actions such as sending a welcome message or initializing group-specific settings.

Note: When a bot creates a group using the SeaTalk API, the bot itself is not automatically added as a member of the group hence the event bot_added_to_group_chat will not be triggered.

Event Parameter
Header

Parameter

Type

Description

Content-Type

string

Request header format

Signature

unit64

A signature to ensure that the request is sent by SeaTalk

Body

Parameter

Type

Description

event_id

string

The ID of the event

event_type

string

The type of the event. It will be "bot_added_to_group_chat" in this case

timestamp

unit64

The time when this event happened

app_id

string

The ID of the app to receive the event notification

event

object

Event-object information

∟group

object

Information of the group chat which the bot is added to

  ∟group_id

string

The ID of the group chat

  ∟group_name

string

Group name when the bot is added

  ∟group_settings

object

Current group settings when the bot is added

    ∟chat_history_for_new_members

string

The extent to which the bot can access the chat histories sent prior to joining. Possible values are "disabled", "1 day" and "7 days".

    ∟can_notify_with_at_all

boolean

Whether group members are allowed to notify all group members with '@All'.

    ∟can_view_member_list

boolean

Whether group members are allowed to view the group member list

∟inviter

object

 

  ∟seatalk_id

string

The SeaTalk ID of the user who has added the bot to the group chat

  ∟employee_code

string

The employee_code of the user who has added the bot to the group chat

  ∟email

string

The email of the user who added the bot to the group chat

Request Body Sample

{
    "event_id":"1234567",
    "event_type":"bot_added_to_group_chat",
    "timestamp":1687764109,
    "app_id":"abcdefghiklmn",
    "event":{
        "group":{
            "group_id":"qwertyui",
            "group_name":"Test Group",
            "group_settings":{
                "chat_history_for_new_members":"disabled",
                "can_notify_with_at_all":false,
                "can_view_member_list":false
            }
        },
        "inviter":{
            "seatalk_id":"1234567890",
            "employee_code":"e_12345678"            
            "email":"sample@seatalk.biz"
        }
    }
}

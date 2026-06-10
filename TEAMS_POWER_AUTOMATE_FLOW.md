# Teams Power Automate Flow

This document describes the preferred Microsoft Teams Power Automate flow for this project.

It:

- accepts one webhook request
- resolves `channelName` to a real Teams channel ID
- resolves `tagNames[]` to real Teams tag IDs
- builds `@mention` tokens for matching tags
- injects those mention tokens into an Adaptive Card
- posts one mentioned Adaptive Card per delivery

The goal is to avoid hardcoding channel IDs, tag IDs, or maintaining multiple webhooks.

## Request Payload

Use a single payload with a `card` object and a `deliveries` array:

```json
{
  "card": {
    "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
    "type": "AdaptiveCard",
    "version": "1.4",
    "body": [
      {
        "type": "TextBlock",
        "text": "__MENTIONS__",
        "wrap": true,
        "spacing": "None"
      },
      {
        "type": "TextBlock",
        "text": "Test - Agenda Summary",
        "weight": "Bolder",
        "size": "Large",
        "wrap": true
      }
    ],
    "actions": [
      {
        "type": "Action.OpenUrl",
        "title": "Open Source",
        "url": "https://example.com/agenda.pdf"
      }
    ]
  },
  "deliveries": [
    {
      "channelName": "Ops Alerts",
      "tagNames": ["On Call", "Managers"]
    },
    {
      "channelName": "Engineering",
      "tagNames": ["Backend"]
    }
  ]
}
```

Notes:

- `card` is the primary payload for the public meeting summary use case.
- `__MENTIONS__` is a placeholder that the flow replaces with the joined tag mention tokens.
- `deliveries[]` controls where the same card is sent.
- This design assumes the flow posts into a single Team selected in the Teams actions.

## Flow Overview

Create the flow with these actions in this order:

1. `TRG - Teams Webhook Received`
2. `SYS - FlowIL (Do Not Remove)`
3. `VAR - Body`
4. `PARSE - Request Body`
5. `COMPOSE - Deliveries`
6. `VAR - Errors`
7. `VAR - Current Mention Tokens`
8. `GET - List All Channels`
9. `GET - List All Tags for Team`
10. `MAP - Normalize Channels`
11. `MAP - Normalize Tags`
12. `LOOP - For Each Delivery`
13. `COND - Any Errors`
14. `TERM - Fail Run`
15. `TERM - Success`

## Step By Step

### 1. Trigger

Add:

- `When a Teams webhook request is received`

### 2. Keep FlowIL

Keep:

- `Do Not Remove FlowIL`

Do not modify or remove it.

### 3. Store The Incoming Body

Add:

- `Initialize variable`

Rename it to:

- `VAR - Body`

Configuration:

- Name: `Body`
- Type: `Object`
- Value: the trigger `Body`

This matches the current flow design and makes downstream expressions simpler.

### 4. Parse Request Body

Add:

- `Parse JSON`

Rename it to:

- `PARSE - Request Body`

Use `variables('Body')` as `Content`.

Use this schema:

```json
{
  "type": "object",
  "properties": {
    "card": {
      "type": ["object", "null"]
    },
    "deliveries": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "channelName": {
            "type": "string"
          },
          "tagNames": {
            "type": ["array", "null"],
            "items": {
              "type": "string"
            }
          }
        },
        "required": [
          "channelName"
        ]
      }
    }
  },
  "required": [
    "card",
    "deliveries"
  ]
}
```

### 5. Compose Deliveries

Add:

- `Compose`

Rename it to:

- `COMPOSE - Deliveries`

Use:

```text
variables('Body')?['deliveries']
```

### 6. Initialize Errors

Add:

- `Initialize variable`

Rename it to:

- `VAR - Errors`

Configuration:

- Name: `Errors`
- Type: `Array`
- Value: `[]`

### 7. Initialize Mention Tokens

Add:

- `Initialize variable`

Rename it to:

- `VAR - Current Mention Tokens`

Configuration:

- Name: `CurrentMentionTokens`
- Type: `Array`
- Value: `[]`

### 8. Load Channels

Add:

- `List all channels`

Rename it to:

- `GET - List All Channels`

Choose the target Team.

### 9. Load Tags

Add:

- `List all tags for a team`

Rename it to:

- `GET - List All Tags for Team`

Choose the same Team.

### 10. Normalize Channels

Add:

- `Select`

Rename it to:

- `MAP - Normalize Channels`

For `From`, use the channels array from `GET - List All Channels`.

Use this map:

```json
{
  "id": "@{item()?['id']}",
  "displayName": "@{item()?['displayName']}",
  "description": "@{item()?['description']}",
  "membershipType": "@{item()?['membershipType']}",
  "key": "@{toLower(trim(item()?['displayName']))}"
}
```

### 11. Normalize Tags

Add:

- `Select`

Rename it to:

- `MAP - Normalize Tags`

For `From`, use the tags array from `GET - List All Tags for Team`.

Use this map:

```json
{
  "id": "@{item()?['id']}",
  "displayName": "@{coalesce(item()?['displayName'], item()?['name'])}",
  "description": "@{item()?['description']}",
  "key": "@{toLower(trim(coalesce(item()?['displayName'], item()?['name'])))}"
}
```

### 12. Loop Through Deliveries

Add:

- `Apply to each`

Rename it to:

- `LOOP - For Each Delivery`

For `From`, use:

```text
outputs('COMPOSE_-_Deliveries')
```

Open loop settings and disable concurrency.

## Actions Inside `LOOP - For Each Delivery`

### 12.1 Compose Current Delivery Tags

Add:

- `Compose`

Rename it to:

- `COMPOSE - Current Delivery Tags`

Use:

```text
coalesce(items('LOOP_-_For_Each_Delivery')?['tagNames'], json('[]'))
```

### 12.2 Match Channel

Add:

- `Filter array`

Rename it to:

- `FILTER - Match Channel By Display Name`

For `From`, use:

```text
body('MAP_-_Normalize_Channels')
```

Use advanced mode:

```text
@equals(item()?['key'], toLower(trim(items('LOOP_-_For_Each_Delivery')?['channelName'])))
```

### 12.3 Require Exactly One Channel Match

Add:

- `Condition`

Rename it to:

- `COND - Exactly One Channel Match Found`

Use:

```text
@equals(length(body('FILTER_-_Match_Channel_By_Display_Name')), 1)
```

#### If No

Add:

- `Append to array variable`

Rename it to:

- `APPEND - Channel Error`

Append:

```text
Channel not found or not unique: @{items('LOOP_-_For_Each_Delivery')?['channelName']}
```

#### If Yes

Continue below.

### 12.4 Save Resolved Channel ID

Add:

- `Compose`

Rename it to:

- `COMPOSE - Resolved Channel Id`

Use:

```text
@first(body('FILTER_-_Match_Channel_By_Display_Name'))?['id']
```

### 12.5 Reset Mention Tokens

Add:

- `Set variable`

Rename it to:

- `SET - Reset Mention Tokens`

Set `CurrentMentionTokens` to:

```text
[]
```

### 12.6 Check Whether Tags Exist

Add:

- `Condition`

Rename it to:

- `COND - Delivery Has Tags`

Use:

```text
@greater(length(outputs('COMPOSE_-_Current_Delivery_Tags')), 0)
```

### 12.7 Loop Through Tag Names

Inside the `Yes` branch, add:

- `Apply to each`

Rename it to:

- `LOOP - For Each Tag Name`

For `From`, use:

```text
outputs('COMPOSE_-_Current_Delivery_Tags')
```

### 12.8 Match Tag

Inside the tag loop, add:

- `Filter array`

Rename it to:

- `FILTER - Match Tag By Display Name`

For `From`, use:

```text
body('MAP_-_Normalize_Tags')
```

Use advanced mode:

```text
@equals(item()?['key'], toLower(trim(items('LOOP_-_For_Each_Tag_Name'))))
```

### 12.9 Require Exactly One Tag Match

Add:

- `Condition`

Rename it to:

- `COND - Exactly One Tag Match Found`

Use:

```text
@equals(length(body('FILTER_-_Match_Tag_By_Display_Name')), 1)
```

#### If No

Add:

- `Append to array variable`

Rename it to:

- `APPEND - Tag Error`

Append:

```text
Tag not found or not unique: @{items('LOOP_-_For_Each_Tag_Name')} in channel @{items('LOOP_-_For_Each_Delivery')?['channelName']}
```

#### If Yes

Continue below.

### 12.10 Get Mention Token

Add:

- `Get an @mention token for a team tag`

Rename it to:

- `ACT - Get @Mention Token For Team Tag`

Use:

```text
@first(body('FILTER_-_Match_Tag_By_Display_Name'))?['id']
```

### 12.11 Append Mention Token

Add:

- `Append to array variable`

Rename it to:

- `APPEND - Mention Token`

Append this exact expression to `CurrentMentionTokens`:

```text
body('ACT_-_Get_@Mention_Token_For_Team_Tag')?['atMention']
```

Use only the `atMention` field returned by the Teams action.

### 12.12 Compose Card Template String

After the tag condition, add:

- `Compose`

Rename it to:

- `COMPOSE - Card Template String`

Use:

```text
string(variables('Body')?['card'])
```

### 12.13 Compose Card With Mentions String

Add:

- `Compose`

Rename it to:

- `COMPOSE - Card With Mentions String`

Use:

```text
replace(outputs('COMPOSE_-_Card_Template_String'), '__MENTIONS__', join(variables('CurrentMentionTokens'), ' '))
```

At this point `CurrentMentionTokens` should contain only raw `<atTag>...</atTag>` strings. If you see JSON like `{"atMention":"..."}` rendered in Teams, `APPEND - Mention Token` is appending the wrong value.

### 12.14 Post The Mentioned Card

Add:

- `Post card in a chat or channel`

Rename it to:

- `ACT - Post Mentioned Card In Channel`

Configuration:

- Team: your fixed Team
- Channel: custom value

```text
outputs('COMPOSE_-_Resolved_Channel_Id')
```

- Message or card payload:

```text
outputs('COMPOSE_-_Card_With_Mentions_String')
```

If the action input shows `body/messageBody` in run history, that field must contain the card JSON string and must not be `null`.

## Final Error Handling

### 13. Check Whether Any Errors Were Collected

Add:

- `Condition`

Rename it to:

- `COND - Any Errors`

Use:

```text
@greater(length(variables('Errors')), 0)
```

### 14. Fail If Needed

In the `Yes` branch, add:

- `Terminate`

Rename it to:

- `TERM - Fail Run`

Status:

- `Failed`

Message:

```text
@join(variables('Errors'), ' | ')
```

### 15. Success

In the `No` branch, optionally add:

- `Terminate`

Rename it to:

- `TERM - Success`

Status:

- `Succeeded`

## What To Remove From The Old Flow

Remove or ignore these old patterns:

- single `tagId` variable
- hardcoded tag IDs in the webhook payload
- hardcoded channel IDs in the webhook payload
- `ACT - Post Message In Channel`
- `COND - Delivery Has Attachments`
- `LOOP - For Each Attachment`
- `ACT - Post Card In Channel`

The preferred flow posts one mentioned Adaptive Card per delivery.

## Expected Behavior

For each delivery:

1. find the channel by normalized display name
2. find each tag by normalized display name
3. build mention tokens for all matched tags
4. inject those mentions into the card template
5. post the Adaptive Card into the resolved channel

If a channel or tag cannot be resolved exactly once, record an error and fail the run at the end.

## Practical Notes

- Keep delivery loop concurrency disabled because shared variables are reused.
- Standard channels are the safest target. Private channel support in the Teams connector is limited.
- Team display names are easier to rename or duplicate, so hardcoding the Team in the flow is usually safer than resolving the Team by name.
- Matching is case-insensitive because of the normalized `key` field.
- Keep the mention placeholder in a dedicated first `TextBlock`:

```json
{
  "type": "TextBlock",
  "text": "__MENTIONS__",
  "wrap": true,
  "spacing": "None"
}
```

## Suggested Naming Convention

Use prefixes consistently:

- `TRG` for triggers
- `SYS` for required internal actions
- `PARSE` for `Parse JSON`
- `GET` for connector reads
- `MAP` for `Select`
- `VAR` for initialized variables
- `SET` for variable updates
- `FILTER` for `Filter array`
- `COND` for conditions
- `LOOP` for `Apply to each`
- `COMPOSE` for `Compose`
- `ACT` for connector actions
- `APPEND` for array accumulation
- `TERM` for termination

This makes the run history much easier to debug.
